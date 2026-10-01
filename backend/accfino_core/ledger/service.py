"""
accfino_core.ledger.service
---------------------------
The only code path that writes to the general ledger. Every module (bank sync
now; invoices, bills, payroll, depreciation in later phases) posts through
post_journal(), so the validation rules live in one place:

  * at least two lines; each line is a debit OR a credit, never both
  * debits equal credits exactly (Decimal, 2 dp, ROUND_HALF_UP)
  * accounts, tax codes and tracking options belong to the organisation
  * inactive accounts cannot be posted to
  * nothing can be posted on or before the organisation's lock date
  * posted journals are never edited or deleted - they are reversed

PostgreSQL triggers enforce the same balance and immutability rules as a second line of defence.
"""
from collections import defaultdict
from datetime import date
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation

from sqlalchemy import func

from accfino_core import models as m

CENT = Decimal("0.01")


class LedgerError(ValueError):
    """Business-rule violation; API layer returns 422 with the message."""


def money(value) -> Decimal:
    if value is None or value == "":
        return Decimal("0.00")
    try:
        d = value if isinstance(value, Decimal) else Decimal(str(value))
    except (InvalidOperation, ValueError):
        raise LedgerError(f"Invalid amount: {value!r}")
    if not d.is_finite():
        raise LedgerError(f"Invalid amount: {value!r}")
    return d.quantize(CENT, rounding=ROUND_HALF_UP)


def _check_date(org, jdate: date):
    if not isinstance(jdate, date):
        raise LedgerError("Journal date is required")
    if org.lock_date and jdate <= org.lock_date:
        raise LedgerError(f"Date {jdate.isoformat()} is on or before the lock date {org.lock_date.isoformat()}")


FX_EXEMPT_SOURCES = ("fx_reval", "fx_reval_reversal")      # the revaluation posts base-currency adjustments to foreign-held accounts by design


def _check_foreign_accounts(db, accounts, currency, source_type, reversal_of_id):
    held = [a for a in accounts.values() if a.foreign_currency]
    if not held or source_type in FX_EXEMPT_SOURCES:
        return
    if reversal_of_id:
        orig = db.get(m.Journal, reversal_of_id)
        if orig is not None and orig.source_type in FX_EXEMPT_SOURCES:
            return
    for a in held:
        if (currency or "").upper() != a.foreign_currency:
            raise LedgerError(f"Account {a.code} {a.name} is held in {a.foreign_currency}: post to it in a {a.foreign_currency} journal (or through the bank feed), "
                              "not in the base currency - otherwise its foreign balance and revaluation would be wrong")


def post_journal(db, org, *, journal_date, lines, narration=None, source_type="manual",
                 source_ref=None, created_by=None, reversal_of_id=None, reference=None, currency=None, exchange_rate=None):
    """Validate and post a balanced journal. Returns the Journal (flushed, not committed)."""
    _check_date(org, journal_date)
    if not lines or len(lines) < 2:
        raise LedgerError("A journal needs at least two lines")

    acc_ids = {int(l["account_id"]) for l in lines if l.get("account_id") is not None}
    accounts = {a.id: a for a in db.query(m.LedgerAccount)
                .filter(m.LedgerAccount.org_id == org.id, m.LedgerAccount.id.in_(acc_ids))}
    tax_ids = {int(l["tax_code_id"]) for l in lines if l.get("tax_code_id")}
    taxes = {t.id: t for t in db.query(m.TaxCode)
             .filter(m.TaxCode.org_id == org.id, m.TaxCode.id.in_(tax_ids))} if tax_ids else {}
    opt_ids = {int(o) for l in lines for o in (l.get("tracking_option_ids") or [])}
    valid_opts = set()
    if opt_ids:
        valid_opts = {o.id for o in db.query(m.TrackingOption).join(m.TrackingCategory)
                      .filter(m.TrackingCategory.org_id == org.id, m.TrackingOption.id.in_(opt_ids))}

    _check_foreign_accounts(db, accounts, currency, source_type, reversal_of_id)
    clean, total_dr, total_cr = [], Decimal("0.00"), Decimal("0.00")
    for i, l in enumerate(lines, start=1):
        aid = l.get("account_id")
        if aid is None or int(aid) not in accounts:
            raise LedgerError(f"Line {i}: account not found in this organisation")
        acc = accounts[int(aid)]
        if not acc.is_active:
            raise LedgerError(f"Line {i}: account {acc.code} {acc.name} is inactive")
        dr, cr = money(l.get("debit")), money(l.get("credit"))
        if dr < 0 or cr < 0:
            raise LedgerError(f"Line {i}: amounts cannot be negative")
        if (dr == 0) == (cr == 0):
            raise LedgerError(f"Line {i}: enter either a debit or a credit")
        tid = l.get("tax_code_id")
        if tid and int(tid) not in taxes:
            raise LedgerError(f"Line {i}: tax code not found in this organisation")
        opts = [int(o) for o in (l.get("tracking_option_ids") or [])]
        if any(o not in valid_opts for o in opts):
            raise LedgerError(f"Line {i}: tracking option not found in this organisation")
        total_dr += dr
        total_cr += cr
        clean.append(dict(account_id=acc.id, debit=dr, credit=cr, tax_code_id=int(tid) if tid else None,
                          tax_amount=money(l.get("tax_amount")), description=(l.get("description") or None),
                          tracking_option_ids=opts or None, contact_name=l.get("contact_name"),
                          orig_debit=money(l["orig_debit"]) if l.get("orig_debit") is not None else None,
                          orig_credit=money(l["orig_credit"]) if l.get("orig_credit") is not None else None))
    if total_dr != total_cr:
        raise LedgerError(f"Journal does not balance: debits {total_dr} vs credits {total_cr}")

    # Allocate the journal number under a row lock so concurrent posts can't collide
    locked_org = db.query(m.Organisation).filter(m.Organisation.id == org.id).with_for_update().one()
    number = locked_org.next_journal_no
    locked_org.next_journal_no = number + 1

    j = m.Journal(org_id=org.id, journal_no=number, journal_date=journal_date,
                  narration=(narration or "")[:500] or None, reference=((reference or "").strip()[:100] or None), source_type=source_type,
                  source_ref=source_ref, status="posted", reversal_of_id=reversal_of_id,
                  total=total_dr, created_by=created_by, currency=currency, exchange_rate=exchange_rate)
    db.add(j)
    db.flush()
    for n, c in enumerate(clean, start=1):
        db.add(m.JournalLine(journal_id=j.id, org_id=org.id, line_no=n, **c))
    db.flush()
    return j


def reverse_journal(db, org, journal_id: int, *, reversal_date=None, narration=None, created_by=None):
    j = db.query(m.Journal).filter(m.Journal.org_id == org.id, m.Journal.id == journal_id) \
        .with_for_update().one_or_none()
    if j is None:
        raise LedgerError("Journal not found")
    if j.status == "reversed":
        raise LedgerError(f"Journal {j.journal_no} is already reversed")
    if j.reversal_of_id:
        raise LedgerError("A reversing journal cannot itself be reversed; post a new journal instead")
    if db.query(m.Journal.id).filter(m.Journal.org_id == org.id, m.Journal.reversal_of_id == j.id).first():
        raise LedgerError(f"Journal {j.journal_no} already has an auto-reversing journal; it cannot be reversed a second time")
    rdate = reversal_date or j.journal_date
    lines = [dict(account_id=l.account_id, debit=l.credit, credit=l.debit, tax_code_id=l.tax_code_id,
                  tax_amount=l.tax_amount, description=l.description,
                  tracking_option_ids=l.tracking_option_ids, contact_name=l.contact_name,
                  orig_debit=l.orig_credit, orig_credit=l.orig_debit)
             for l in j.lines]
    r = post_journal(db, org, journal_date=rdate, lines=lines,
                     narration=narration or f"Reversal of journal {j.journal_no}",
                     source_type="reversal", source_ref=f"journal:{j.id}", created_by=created_by,
                     reversal_of_id=j.id, currency=j.currency, exchange_rate=j.exchange_rate)
    j.status = "reversed"
    j.reversed_by_id = r.id
    db.flush()
    return r


# ------------------------------------------------------------------ reports --
def _fy_start(org, as_at: date) -> date:
    end_m = org.fy_end_month or 6
    start_m = end_m % 12 + 1
    year = as_at.year if as_at.month >= start_m else as_at.year - 1
    if start_m == 1:
        year = as_at.year
    return date(year, start_m, 1)


def _sums(db, org, date_from=None, date_to=None):
    q = db.query(m.JournalLine.account_id, func.coalesce(func.sum(m.JournalLine.debit), 0),
                 func.coalesce(func.sum(m.JournalLine.credit), 0)) \
        .join(m.Journal, m.Journal.id == m.JournalLine.journal_id) \
        .filter(m.Journal.org_id == org.id)
    if date_from:
        q = q.filter(m.Journal.journal_date >= date_from)
    if date_to:
        q = q.filter(m.Journal.journal_date <= date_to)
    return {aid: (money(d), money(c)) for aid, d, c in q.group_by(m.JournalLine.account_id)}


def _accounts(db, org):
    return {a.id: a for a in db.query(m.LedgerAccount).filter(m.LedgerAccount.org_id == org.id)}


def _acc_row(a, amount):
    return {"account_id": a.id, "code": a.code, "name": a.name, "type": a.account_type,
            "amount": str(amount)}


def trial_balance(db, org, as_at: date):
    sums, accs = _sums(db, org, date_to=as_at), _accounts(db, org)
    rows, tdr, tcr = [], Decimal("0.00"), Decimal("0.00")
    for aid, (d, c) in sums.items():
        net = d - c
        if net == 0:
            continue
        a = accs[aid]
        dr, cr = (net, Decimal("0.00")) if net > 0 else (Decimal("0.00"), -net)
        tdr += dr
        tcr += cr
        rows.append({"account_id": a.id, "code": a.code, "name": a.name, "type": a.account_type,
                     "class": a.account_class, "debit": str(dr), "credit": str(cr)})
    rows.sort(key=lambda r: r["code"])
    return {"as_at": as_at.isoformat(), "rows": rows, "total_debit": str(tdr), "total_credit": str(tcr),
            "balanced": tdr == tcr}


def profit_and_loss(db, org, date_from: date, date_to: date):
    sums, accs = _sums(db, org, date_from, date_to), _accounts(db, org)
    sections = defaultdict(list)
    totals = defaultdict(lambda: Decimal("0.00"))
    for aid, (d, c) in sums.items():
        a = accs[aid]
        if a.account_class not in ("revenue", "expense"):
            continue
        amt = (c - d) if a.account_class == "revenue" else (d - c)
        if amt == 0:
            continue
        sections[a.account_type].append(_acc_row(a, amt))
        totals[a.account_type] += amt
    for v in sections.values():
        v.sort(key=lambda r: r["code"])
    income = totals["revenue"]
    gross = income - totals["direct_costs"]
    operating = gross - totals["expense"]
    net = operating + totals["other_income"] - totals["other_expense"]
    return {"from": date_from.isoformat(), "to": date_to.isoformat(),
            "income": sections["revenue"], "total_income": str(income),
            "cost_of_sales": sections["direct_costs"], "total_cost_of_sales": str(totals["direct_costs"]),
            "gross_profit": str(gross),
            "expenses": sections["expense"], "total_expenses": str(totals["expense"]),
            "operating_profit": str(operating),
            "other_income": sections["other_income"], "total_other_income": str(totals["other_income"]),
            "other_expenses": sections["other_expense"], "total_other_expenses": str(totals["other_expense"]),
            "net_profit": str(net)}


def balance_sheet(db, org, as_at: date):
    fy_start = _fy_start(org, as_at)
    sums, accs = _sums(db, org, date_to=as_at), _accounts(db, org)
    groups = defaultdict(list)
    totals = defaultdict(lambda: Decimal("0.00"))
    pl_to_date = Decimal("0.00")
    for aid, (d, c) in sums.items():
        a = accs[aid]
        if a.account_class in ("revenue", "expense"):
            continue
        amt = (d - c) if a.account_class == "asset" else (c - d)
        if amt == 0:
            continue
        groups[a.account_type].append(_acc_row(a, amt))
        totals[a.account_class] += amt
    cur = profit_and_loss(db, org, fy_start, as_at)
    current_year = money(cur["net_profit"])
    all_pl = Decimal("0.00")
    for aid, (d, c) in sums.items():
        a = accs[aid]
        if a.account_class == "revenue":
            all_pl += c - d
        elif a.account_class == "expense":
            all_pl -= d - c
    prior_years = all_pl - current_year
    equity_total = totals["equity"] + prior_years + current_year
    for v in groups.values():
        v.sort(key=lambda r: r["code"])
    assets, liabilities = totals["asset"], totals["liability"]
    return {
        "as_at": as_at.isoformat(), "financial_year_start": fy_start.isoformat(),
        "assets": {k: groups[k] for k in ("bank", "current_asset", "inventory", "fixed_asset", "non_current_asset")},
        "total_assets": str(assets),
        "liabilities": {k: groups[k] for k in ("credit_card", "current_liability", "non_current_liability")},
        "total_liabilities": str(liabilities),
        "net_assets": str(assets - liabilities),
        "equity": groups["equity"],
        "retained_earnings_prior_years": str(prior_years),
        "current_year_earnings": str(current_year),
        "total_equity": str(equity_total),
        "balanced": assets - liabilities == equity_total,
    }


def general_ledger(db, org, account_id: int, date_from: date, date_to: date):
    a = db.query(m.LedgerAccount).filter_by(org_id=org.id, id=account_id).one_or_none()
    if a is None:
        raise LedgerError("Account not found")
    debit_normal = a.account_class in ("asset", "expense")
    opening = _sums(db, org, date_to=date.fromordinal(date_from.toordinal() - 1)).get(a.id, (0, 0))
    bal = money(opening[0]) - money(opening[1])
    bal = bal if debit_normal else -bal
    rows = []
    q = db.query(m.JournalLine, m.Journal).join(m.Journal, m.Journal.id == m.JournalLine.journal_id) \
        .filter(m.Journal.org_id == org.id, m.JournalLine.account_id == a.id,
                m.Journal.journal_date >= date_from, m.Journal.journal_date <= date_to) \
        .order_by(m.Journal.journal_date, m.Journal.journal_no, m.JournalLine.line_no)
    opening_balance = bal
    for line, j in q:
        mv = line.debit - line.credit
        bal += mv if debit_normal else -mv
        rows.append({"date": j.journal_date.isoformat(), "journal_id": j.id, "journal_no": j.journal_no,
                     "narration": j.narration, "description": line.description, "source_type": j.source_type,
                     "debit": str(line.debit), "credit": str(line.credit), "balance": str(bal)})
    return {"account": {"id": a.id, "code": a.code, "name": a.name, "type": a.account_type},
            "from": date_from.isoformat(), "to": date_to.isoformat(),
            "opening_balance": str(opening_balance), "closing_balance": str(bal), "rows": rows}


def journal_to_dict(j, accounts=None):
    return {
        "id": j.id, "journal_no": j.journal_no, "date": j.journal_date.isoformat(),
        "narration": j.narration, "reference": j.reference, "source_type": j.source_type, "source_ref": j.source_ref,
        "status": j.status, "reversal_of_id": j.reversal_of_id, "reversed_by_id": j.reversed_by_id,
        "total": str(j.total), "created_by": j.created_by,
        "currency": j.currency, "exchange_rate": str(j.exchange_rate) if j.exchange_rate is not None else None,
        "created_at": j.created_at.isoformat() if j.created_at else None,
        "lines": [{"line_no": l.line_no, "account_id": l.account_id,
                   "account_code": l.account.code if l.account else None,
                   "account_name": l.account.name if l.account else None,
                   "description": l.description, "debit": str(l.debit), "credit": str(l.credit),
                   "tax_code_id": l.tax_code_id, "tax_code": l.tax_code.name if l.tax_code else None,
                   "tax_amount": str(l.tax_amount), "tracking_option_ids": l.tracking_option_ids,
                   "contact_name": l.contact_name,
                   "orig_debit": str(l.orig_debit) if l.orig_debit is not None else None,
                   "orig_credit": str(l.orig_credit) if l.orig_credit is not None else None} for l in j.lines],
    }
