"""
Foreign-currency accounts, realised and unrealised gains/losses, and period-end revaluation.

Model (kept deliberately simple and auditable):

  * An account is *foreign-held* when ledger_accounts.foreign_currency is set (a USD bank account, a EUR credit card, a GBP loan...). Every posting to it
    must be in that currency (enforced in ledger.service.post_journal) so its FOREIGN balance is always exactly sum(orig_debit - orig_credit), and its
    BASE carrying value is sum(debit - credit).
  * Money going IN is booked at the spot rate of the day. Money going OUT is booked at the account's AVERAGE COST (its carrying rate), and the difference
    between what was received/bought in base currency and that carrying cost is a REALISED gain or loss (posted to the Realised FX account).
  * At period end, `revalue` restates each foreign account to the closing rate. The adjustment is an UNREALISED gain or loss, posted to the Unrealised FX
    account, and (by default) auto-reverses on the next day, so realised results are never counted twice. Running it twice for the same date only posts
    the difference. Historical cost is always measured EXCLUDING revaluation journals.
  * Rates are the organisation's own (entered, typed on the journal, or fetched by the optional feed). Nothing is ever guessed: a missing rate stops the run.
  * Invoices and bills remain in the base currency in this release, so receivables/payables are not revalued; foreign-held accounts are.
"""
import re
from collections import defaultdict
from datetime import date, timedelta
from decimal import Decimal

from sqlalchemy import func

from accfino.core import models as m
from accfino.modules.accounting.models import ledger as lm
from accfino.modules.accounting.books.common import BooksError
from accfino.modules.accounting.ledger import service as L
from accfino.modules.accounting.ledger.journal_models import FxRate

Z = Decimal("0.00")
MONETARY_TYPES = ("bank", "credit_card", "current_asset", "non_current_asset", "current_liability", "non_current_liability")
REALISED_KEY, UNREALISED_KEY = "fx_realised", "fx_unrealised"
NAMES = {REALISED_KEY: "Realised Foreign Exchange Gain/Loss", UNREALISED_KEY: "Unrealised Foreign Exchange Gain/Loss"}


def q2(v):
    return Decimal(v).quantize(Decimal("0.01"), rounding="ROUND_HALF_UP")


def base_currency(org):
    return (org.base_currency or "AUD").upper()


# ------------------------------------------------------------------------------------------------ rates --
def latest_rate(db, org, currency, on_date):
    r = db.query(FxRate).filter(FxRate.org_id == org.id, FxRate.currency == currency, FxRate.rate_date <= on_date).order_by(FxRate.rate_date.desc()).first()
    return (Decimal(r.rate), r.rate_date) if r else (None, None)


def spot(db, org, currency, on_date, override=None):
    """The rate for a transaction: an explicit override (e.g. the rate shown on the statement) or the organisation's latest stored rate. Never a guess."""
    if override not in (None, ""):
        try:
            r = Decimal(str(override))
        except Exception:
            raise BooksError("The exchange rate is not a number")
        if not (Decimal("0.00000001") <= r <= Decimal("1000000")):
            raise BooksError("The exchange rate is outside a sensible range")
        return r.quantize(Decimal("0.00000001"))
    r, _ = latest_rate(db, org, currency, on_date)
    if r is None:
        raise BooksError(f"There is no {currency} exchange rate on or before {on_date.isoformat()}. Add one under Foreign currency > Rates (or enter the rate you were given)")
    return r.quantize(Decimal("0.00000001"))


# ------------------------------------------------------------------------------------------------ accounts --
def ensure_fx_accounts(db, org):
    """The two gain/loss accounts, created on first use (one system account each). Returns {key: LedgerAccount}."""
    out = {}
    for key in (REALISED_KEY, UNREALISED_KEY):
        a = db.query(lm.LedgerAccount).filter_by(org_id=org.id, system_key=key).first()
        if a is None:
            taken = {c for (c,) in db.query(lm.LedgerAccount.code).filter_by(org_id=org.id)}
            code = next((c for c in ("491", "492", "493", "494", "495", "496", "497", "498", "499") if c not in taken), None) or next(str(n) for n in range(9100, 9999) if str(n) not in taken)
            name = NAMES[key]
            if db.query(lm.LedgerAccount.id).filter_by(org_id=org.id, name=name).first():
                name = f"{name} (system)"
            a = lm.LedgerAccount(org_id=org.id, code=code, name=name, account_type="other_income", account_class="revenue", system_key=key,
                                description="Created by AccFino for foreign-currency gains (credit) and losses (debit)", currency=base_currency(org))
            db.add(a)
            db.flush()
        out[key] = a
    return out


def foreign_accounts(db, org, include_inactive=False):
    q = db.query(lm.LedgerAccount).filter(lm.LedgerAccount.org_id == org.id, lm.LedgerAccount.foreign_currency.isnot(None))
    if not include_inactive:
        q = q.filter(lm.LedgerAccount.is_active.is_(True))
    return q.order_by(lm.LedgerAccount.code).all()


def set_account_currency(db, org, account_id, currency):
    """Make an account foreign-held (or back to base). Only allowed while the account has no postings, so its foreign balance is exact from the start."""
    a = db.query(lm.LedgerAccount).filter_by(org_id=org.id, id=account_id).one_or_none()
    if a is None:
        raise BooksError("Account not found", 404)
    cur = (currency or "").strip().upper() or None
    if cur == base_currency(org):
        cur = None
    if cur and not re.fullmatch(r"[A-Z]{3}", cur):
        raise BooksError(f"'{currency}' is not a valid 3-letter currency code")
    if cur == a.foreign_currency:
        return a
    if cur:
        if a.account_type not in MONETARY_TYPES:
            raise BooksError("Only bank, card, loan and other balance-sheet money accounts can be held in a foreign currency")
        if a.system_key:
            raise BooksError("System accounts (receivables, payables, GST...) stay in the base currency")
    if db.query(lm.JournalLine.id).filter_by(org_id=org.id, account_id=a.id).first():
        raise BooksError(f"{a.code} {a.name} already has postings. Create a new account for the {cur or 'base-currency'} balance and move it across "
                         "(an existing balance has no foreign-currency amounts to revalue)", 409)
    a.foreign_currency = cur
    a.currency = cur or base_currency(org)
    db.flush()
    return a


# ------------------------------------------------------------------------------------------------ positions --
def position(db, org, acc, as_at=None, include_reval=False):
    """(foreign_balance, base_carrying) for a foreign-held account, signed with debits positive. Revaluation journals are EXCLUDED by default so the base
    figure is the historical cost."""
    q = db.query(func.coalesce(func.sum(func.coalesce(lm.JournalLine.orig_debit, 0) - func.coalesce(lm.JournalLine.orig_credit, 0)), 0),
                 func.coalesce(func.sum(lm.JournalLine.debit - lm.JournalLine.credit), 0)) \
        .join(lm.Journal, lm.Journal.id == lm.JournalLine.journal_id).filter(lm.JournalLine.org_id == org.id, lm.JournalLine.account_id == acc.id)
    if as_at:
        q = q.filter(lm.Journal.journal_date <= as_at)
    if not include_reval:
        q = q.filter(lm.Journal.source_type.notin_(L.FX_EXEMPT_SOURCES))
    f, b = q.one()
    return q2(f), q2(b)


def carry(db, org, acc, delta_f, on_spot, as_at=None):
    """Base amount (signed, debit positive) to book for a movement of `delta_f` (signed, in the account's currency) on a foreign-held account.
    A movement that INCREASES the position is booked at spot. One that REDUCES it is booked at the account's average cost (so the difference to what was
    received or given in base currency is a realised gain/loss); any part beyond zero is booked at spot."""
    delta_f = q2(delta_f)
    fbal, cost = position(db, org, acc, as_at)
    if fbal == 0 or (fbal > 0) == (delta_f > 0):
        return q2(delta_f * on_spot)
    covered = min(abs(delta_f), abs(fbal))
    part = cost if covered == abs(fbal) else q2(cost * covered / abs(fbal))          # emptying the account takes ALL of its cost: no stray cents left behind
    excess = abs(delta_f) - covered
    total = abs(part) + (q2(excess * on_spot) if excess else Z)
    return total if delta_f > 0 else -total


def build_fx_journal(db, org, acc_lines, *, other_lines, currency, rate):
    """Assemble a balanced base-currency journal from foreign-held account legs (already carried) and other legs. Any imbalance is the realised gain/loss
    and is booked to the Realised FX account. acc_lines / other_lines: dicts with account_id, signed (base, debit +), orig (foreign, signed or None), plus extras."""
    legs = list(acc_lines) + list(other_lines)
    residual = sum((l["signed"] for l in legs), Z)
    lines = []
    for l in legs:
        s = l["signed"]
        d = dict(account_id=l["account_id"], debit=s if s > 0 else Z, credit=-s if s < 0 else Z, description=l.get("description"), tax_code_id=l.get("tax_code_id"),
                 tax_amount=l.get("tax_amount", Z), contact_name=l.get("contact_name"), tracking_option_ids=l.get("tracking_option_ids"))
        o = l.get("orig")
        if o is not None:
            d["orig_debit"], d["orig_credit"] = (q2(o) if o > 0 else Z), (q2(-o) if o < 0 else Z)
        if d["debit"] or d["credit"]:
            lines.append(d)
    realised = Z
    if residual:
        acc = ensure_fx_accounts(db, org)[REALISED_KEY]
        realised = -residual                       # signed as a base debit: positive = loss, negative = gain
        lines.append(dict(account_id=acc.id, debit=realised if realised > 0 else Z, credit=-realised if realised < 0 else Z,
                          description=f"Realised foreign exchange {'loss' if realised > 0 else 'gain'} ({currency})", tax_amount=Z))
    return lines, realised


# ------------------------------------------------------------------------------------------------ revaluation --
def _booked(db, org, acc, as_at):
    v = db.query(func.coalesce(func.sum(lm.JournalLine.debit - lm.JournalLine.credit), 0)).join(lm.Journal, lm.Journal.id == lm.JournalLine.journal_id) \
        .filter(lm.JournalLine.org_id == org.id, lm.JournalLine.account_id == acc.id, lm.Journal.source_type == "fx_reval", lm.Journal.journal_date == as_at).scalar()
    return q2(v)


def revaluation_preview(db, org, as_at):
    rows, missing = [], []
    for acc in foreign_accounts(db, org, include_inactive=True):
        fbal, cost = position(db, org, acc, as_at)
        booked = _booked(db, org, acc, as_at)
        if fbal == 0 and cost == 0 and booked == 0:
            continue
        rate, rdate = latest_rate(db, org, acc.foreign_currency, as_at)
        row = dict(account_id=acc.id, code=acc.code, name=acc.name, currency=acc.foreign_currency, foreign_balance=str(fbal), historical_base=str(cost),
                   rate=str(rate) if rate is not None else None, rate_date=rdate.isoformat() if rdate else None, revalued_base=None, adjustment=None,
                   already_booked=str(booked), to_post=None)
        if rate is None:
            missing.append(acc.foreign_currency)
        else:
            target = q2(fbal * rate)
            row.update(revalued_base=str(target), adjustment=str(target - cost), to_post=str(target - cost - booked))
        rows.append(row)
    missing = sorted(set(missing))
    tot = sum((Decimal(r["to_post"]) for r in rows if r["to_post"] is not None), Z)
    return dict(as_at=as_at.isoformat(), base=base_currency(org), rows=rows, missing_rates=missing, net_to_post=str(tot), can_post=bool(rows) and not missing and any(Decimal(r["to_post"]) != 0 for r in rows if r["to_post"] is not None),
                unrealised_total=str(sum((Decimal(r["adjustment"]) for r in rows if r["adjustment"] is not None), Z)))


def revalue(db, org, user_id, as_at, *, reverse=True):
    """Post the unrealised gain/loss journals (one per currency) at `as_at`, each auto-reversing the next day. Caller commits."""
    if not isinstance(as_at, date):
        raise BooksError("Choose the date to revalue at")
    pv = revaluation_preview(db, org, as_at)
    if not pv["rows"]:
        raise BooksError("There are no foreign-currency accounts with a balance to revalue. Mark a bank account as held in a foreign currency first")
    if pv["missing_rates"]:
        raise BooksError(f"No exchange rate on or before {as_at.isoformat()} for {', '.join(pv['missing_rates'])}. Add the closing rate (Foreign currency > Rates) and run again - "
                         "AccFino does not guess a revaluation rate")
    unreal = ensure_fx_accounts(db, org)[UNREALISED_KEY]
    by_ccy = defaultdict(list)
    for r in pv["rows"]:
        if Decimal(r["to_post"]) != 0:
            by_ccy[r["currency"]].append(r)
    posted = []
    for ccy, rows in sorted(by_ccy.items()):
        lines = []
        for r in rows:
            amt = Decimal(r["to_post"])                                # + = the account's base value goes up: debit the account, credit unrealised GAIN
            lines.append(dict(account_id=r["account_id"], debit=amt if amt > 0 else Z, credit=-amt if amt < 0 else Z, description=f"Revalue {ccy} at {r['rate']}", tax_amount=Z))
            lines.append(dict(account_id=unreal.id, debit=-amt if amt < 0 else Z, credit=amt if amt > 0 else Z, description=f"Unrealised FX on {r['code']} {r['name']}", tax_amount=Z))
        ref = f"fxreval:{ccy}:{as_at.isoformat()}"
        try:
            j = L.post_journal(db, org, journal_date=as_at, lines=lines, narration=f"Revaluation of {ccy} accounts at {as_at.isoformat()}", reference=f"FXREVAL {ccy} {as_at.isoformat()}"[:100],
                               source_type="fx_reval", source_ref=ref, created_by=user_id)
            rj = None
            if reverse:
                rev = [dict(account_id=l.account_id, debit=l.credit, credit=l.debit, description=l.description, tax_amount=Z) for l in j.lines]
                rj = L.post_journal(db, org, journal_date=as_at + timedelta(days=1), lines=rev, narration=f"Auto-reversal of revaluation journal {j.journal_no}", reference=f"FXREVAL {ccy} {as_at.isoformat()}"[:100],
                                    source_type="fx_reval_reversal", source_ref=f"journal:{j.id}", created_by=user_id, reversal_of_id=j.id)
                j.reversed_by_id = rj.id
                db.flush()
        except L.LedgerError as e:
            raise BooksError(str(e), 422)
        posted.append(dict(currency=ccy, journal_id=j.id, journal_no=j.journal_no, reversal_journal_no=rj.journal_no if rj else None, net=str(sum((Decimal(r["to_post"]) for r in rows), Z))))
    return dict(as_at=as_at.isoformat(), posted=posted, nothing_to_do=not posted, preview=pv)


# ------------------------------------------------------------------------------------------------ report --
def _sum_net(db, org, key, d1, d2):
    a = db.query(lm.LedgerAccount).filter_by(org_id=org.id, system_key=key).first()
    if a is None:
        return None, Z
    v = db.query(func.coalesce(func.sum(lm.JournalLine.credit - lm.JournalLine.debit), 0)).join(lm.Journal, lm.Journal.id == lm.JournalLine.journal_id) \
        .filter(lm.JournalLine.org_id == org.id, lm.JournalLine.account_id == a.id, lm.Journal.journal_date.between(d1, d2)).scalar()
    return a, q2(v)


def gains_losses_report(db, org, d1, d2):
    """Realised and unrealised FX for a period (gain positive, loss negative), by currency, plus the foreign positions at the end of the period."""
    if d1 > d2:
        raise BooksError("The 'from' date is after the 'to' date")
    out = dict(**{"from": d1.isoformat(), "to": d2.isoformat()}, base=base_currency(org))
    for key, label in ((REALISED_KEY, "realised"), (UNREALISED_KEY, "unrealised")):
        acc, total = _sum_net(db, org, key, d1, d2)
        by = defaultdict(lambda: Z)
        if acc is not None:
            rows = db.query(lm.JournalLine, lm.Journal).join(lm.Journal, lm.Journal.id == lm.JournalLine.journal_id) \
                .filter(lm.JournalLine.org_id == org.id, lm.JournalLine.account_id == acc.id, lm.Journal.journal_date.between(d1, d2)).all()
            for jl, j in rows:
                ccy = j.currency
                if not ccy and j.source_type == "fx_reval":
                    ccy = (j.source_ref or "").split(":")[1] if (j.source_ref or "").count(":") >= 2 else None
                if not ccy and j.source_type == "fx_reval_reversal" and j.reversal_of_id:
                    o = db.get(lm.Journal, j.reversal_of_id)
                    ccy = (o.source_ref or "").split(":")[1] if o and (o.source_ref or "").count(":") >= 2 else None
                by[ccy or "Other"] += jl.credit - jl.debit
        out[label] = dict(account=dict(id=acc.id, code=acc.code, name=acc.name) if acc else None, total=str(total), by_currency=[dict(currency=c, amount=str(q2(v))) for c, v in sorted(by.items())])
    out["net"] = str(Decimal(out["realised"]["total"]) + Decimal(out["unrealised"]["total"]))
    pos = []
    for acc in foreign_accounts(db, org, include_inactive=True):
        f, c = position(db, org, acc, d2)
        r, rd = latest_rate(db, org, acc.foreign_currency, d2)
        if f or c:
            pos.append(dict(code=acc.code, name=acc.name, currency=acc.foreign_currency, foreign_balance=str(f), historical_base=str(c), rate=str(r) if r else None,
                            revalued_base=str(q2(f * r)) if r else None))
    out["positions"] = pos
    return out
