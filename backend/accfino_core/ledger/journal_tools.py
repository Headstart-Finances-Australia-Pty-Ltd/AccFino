"""
journal_tools - everything around a journal that is not the posting itself (posting stays in ledger.service.post_journal, the only writer).

  expand_lines / preview      GST-aware line expansion: 'GST inclusive' / 'GST exclusive' add the GST line and carry tax_amount for the BAS
                              (a manual journal coded with a 10% tax code but no GST used to silently under-report 1A/1B)
  post_journal_full           post a manual journal with reference, GST handling, and an optional AUTO-REVERSING date (accruals)
  drafts                      save as draft -> submit -> approve/reject, with segregation of duties; drafts never touch the ledger
  suggest_bank_journals       AI/rule/learned coding of unreconciled bank lines -> reviewable suggestions with a confidence and a reason;
                              approving one posts through the SAME code path as manual reconciliation (and teaches the classifier)
  repeating journals          templates with {month}/{year}/... labels that create a draft or post on a schedule
  import_journals             CSV import (validate first, all-or-nothing, as drafts or posted)
  general_ledger_detail       ERPNext-style ledger: multi-account, party, tracking, source and text filters; group by account / voucher /
                              party / dimension / source / month, with opening and closing balances
  ledger_health / history / describe_source   what needs attention, the audit trail of a journal, and where a journal came from
"""
import csv
import io
import json
import re
from calendar import monthrange
from collections import defaultdict
from datetime import date, datetime, timedelta
from decimal import Decimal

from sqlalchemy import func, or_

from accfino_core import models as m
from accfino_core.books import banking as K
from accfino_core.books import models as b
from accfino_core.books.common import BooksError, get_account, get_tax, money
from accfino_core.ledger import ai_coder as AI
from accfino_core.ledger import service as L
from accfino_core.ledger.journal_models import AMOUNTS_ARE, FREQUENCIES, FxRate, JournalDraft, RepeatingJournal

Z = Decimal("0.00")
APPROVER_ROLES = ("owner", "admin", "accountant")
CONTROL_KEYS = ("ar_control", "ap_control")
MAX_IMPORT_LINES, MAX_IMPORT_JOURNALS = 2000, 500


def _s(x):
    return str(x)


def can_approve(ctx):
    return ctx.is_admin or ctx.role in APPROVER_ROLES


def _err(e):
    return BooksError(str(e), 422)


# ------------------------------------------------------------------------------------------------ settings --
def get_settings(db, org):
    row = db.get(m.SystemSetting, f"ledger.settings:{org.id}")
    out = {"require_journal_approval": False, "llm_suggestions": False, "llm_assist": False, "fx_feed_enabled": False, "fx_feed_currencies": []}
    if row and row.value:
        try:
            out.update(json.loads(row.value))
        except Exception:
            pass
    return out


def save_settings(db, org, patch):
    cur = get_settings(db, org)
    for k in ("require_journal_approval", "llm_suggestions", "llm_assist", "fx_feed_enabled"):
        if k in patch:
            cur[k] = bool(patch[k])
    if patch.get("fx_feed_currencies") is not None:
        codes = []
        for c in patch["fx_feed_currencies"]:
            c = str(c).strip().upper()
            if not re.fullmatch(r"[A-Z]{3}", c):
                raise BooksError(f"'{c}' is not a valid 3-letter currency code")
            if c != base_currency(org) and c not in codes:
                codes.append(c)
        cur["fx_feed_currencies"] = codes[:30]
    key = f"ledger.settings:{org.id}"
    row = db.get(m.SystemSetting, key)
    if row is None:
        db.add(m.SystemSetting(key=key, value=json.dumps(cur)))
    else:
        row.value = json.dumps(cur)
    db.flush()
    return cur


# ------------------------------------------------------------------------------------------------ GST expansion --
def _amount(v, what):
    try:
        return money(v)
    except Exception as e:
        raise BooksError(f"{what}: {e}")


def expand_lines(db, org, lines, amounts_are="no_tax", *, allow_control=False, foreign=False):
    """User-entered lines -> the lines that will actually post. Returns (lines_out, gst_total).
    inclusive : the entered amount contains GST -> the line is split into net + a GST line (journal balances as entered)
    exclusive : the entered amount is net -> a GST line is ADDED on the same side (the journal must balance after GST)
    no_tax    : nothing is calculated; a tax code that charges GST is refused rather than silently ignored"""
    if amounts_are not in AMOUNTS_ARE:
        raise BooksError("amounts_are must be no_tax, inclusive or exclusive")
    if not lines:
        raise BooksError("A journal needs at least two lines")
    gst = db.query(m.LedgerAccount).filter_by(org_id=org.id, system_key="gst").first()
    out, gst_by, tax_cache = [], defaultdict(lambda: Z), {}
    for i, l in enumerate(lines, start=1):
        ref = l.get("account_id") if l.get("account_id") not in (None, "") else l.get("account")
        acc = get_account(db, org, ref, what=f"Line {i} account")      # an int is an id; a string is a code or name (CSV import)
        if acc.system_key in CONTROL_KEYS and not allow_control:
            raise BooksError(f"Line {i}: {acc.code} {acc.name} is a control account. Use an invoice, bill or payment (a manual journal here leaves the "
                             "receivables/payables sub-ledger out of step with the ledger)")
        dr, cr = _amount(l.get("debit"), f"Line {i} debit"), _amount(l.get("credit"), f"Line {i} credit")
        if dr < 0 or cr < 0:
            raise BooksError(f"Line {i}: amounts cannot be negative")
        if (dr == 0) == (cr == 0):
            raise BooksError(f"Line {i}: enter either a debit or a credit")
        side, amt = ("debit", dr) if dr else ("credit", cr)
        tax = None
        tid = l.get("tax_code_id") or l.get("tax_code")
        if tid not in (None, ""):
            key = str(tid)
            if key not in tax_cache:
                tax_cache[key] = get_tax(db, org, tid)
            tax = tax_cache[key]
        explicit = _amount(l.get("tax_amount"), f"Line {i} tax")
        rate = Decimal(tax.rate) if (tax is not None and org.gst_registered) else Decimal(0)
        entry = dict(account_id=acc.id, description=(l.get("description") or None), debit=dr, credit=cr, tax_code_id=tax.id if tax else None, tax_amount=explicit,
                     tracking_option_ids=[int(x) for x in (l.get("tracking_option_ids") or [])] or None, contact_name=(l.get("contact_name") or None))
        if tax is not None and rate > 0 and explicit == 0:
            if amounts_are == "no_tax":
                raise BooksError(f"Line {i}: tax code '{tax.name}' charges GST. Choose 'GST inclusive' or 'GST exclusive' for this journal "
                                 "(otherwise the GST would be missing from your BAS)")
            if gst is None:
                raise BooksError("This organisation has no GST account", 500)
            t = money(amt * rate / (1 + rate)) if amounts_are == "inclusive" else money(amt * rate)
            entry[side] = amt - t if amounts_are == "inclusive" else amt
            entry["tax_amount"] = t
            if t:
                gst_by[(tax.id, side)] += t
        if l.get("allocations"):
            out.extend(_split_line(entry, side, amt, l["allocations"], i))      # MYOB-style: one line allocated across several jobs / tracking options
        else:
            out.append(entry)
    for (tid, side), amt in gst_by.items():
        out.append(dict(account_id=gst.id, description="GST", debit=amt if side == "debit" else Z, credit=amt if side == "credit" else Z, tax_code_id=tid,
                        tax_amount=Z, tracking_option_ids=None, contact_name=None, gst_line=True))
    return out, sum(gst_by.values(), Z)


def _split_line(entry, side, entered, allocs, i):
    """Split one journal line across several tracking options (jobs, regions, departments) by percentage or by amount.
    The parts always add back to the line EXACTLY (the last part takes the rounding), and GST is split in the same proportions."""
    if not isinstance(allocs, list) or not (2 <= len(allocs) <= 20):
        raise BooksError(f"Line {i}: a split needs between 2 and 20 parts")
    modes = {("percent" if a.get("percent") not in (None, "") else "amount" if a.get("amount") not in (None, "") else None) for a in allocs}
    if len(modes) != 1 or None in modes:
        raise BooksError(f"Line {i}: give every part of the split either a percentage or an amount (not a mix)")
    mode = modes.pop()
    try:
        vals = [Decimal(str(a[mode])) for a in allocs]
    except Exception:
        raise BooksError(f"Line {i}: a split value is not a number")
    if any(v <= 0 for v in vals):
        raise BooksError(f"Line {i}: every part of a split must be greater than zero")
    if mode == "percent" and abs(sum(vals) - 100) > Decimal("0.0001"):
        raise BooksError(f"Line {i}: the split percentages add up to {sum(vals)}%, not 100%")
    if mode == "amount" and sum(vals) != entered:
        raise BooksError(f"Line {i}: the split amounts add up to {sum(vals)}, but the line is {entered}")
    weights = [v / 100 if mode == "percent" else v / entered for v in vals]
    net, tax = entry[side], entry["tax_amount"]
    parts, left_net, left_tax = [], net, tax
    for k, (a, w) in enumerate(zip(allocs, weights)):
        last = k == len(allocs) - 1
        pn = left_net if last else money(net * w)
        pt = left_tax if last else money(tax * w)
        left_net, left_tax = left_net - pn, left_tax - pt
        if pn <= 0:
            raise BooksError(f"Line {i}: part {k + 1} of the split rounds to nothing - use fewer parts or larger shares")
        opts = sorted({int(o) for o in (entry.get("tracking_option_ids") or [])} | {int(o) for o in (a.get("tracking_option_ids") or [])})
        parts.append(dict(entry, **{side: pn}, tax_amount=pt, tracking_option_ids=opts or None))
    return parts


def _names(db, org):
    return {a.id: a for a in db.query(m.LedgerAccount).filter_by(org_id=org.id)}


def journal_warnings(db, org, jdate, lines, accs=None):
    accs = accs or _names(db, org)
    w, today = [], date.today()
    if jdate > today + timedelta(days=0):
        w.append(f"Dated in the future ({jdate.isoformat()}); it will not appear in reports until that date.")
    if jdate < today - timedelta(days=365):
        w.append("Dated more than 12 months ago - check this is intended.")
    for l in lines:
        a = accs.get(l["account_id"])
        if a and a.account_type in ("bank", "credit_card"):
            w.append(f"{a.code} {a.name} is a bank/card account: a manual entry will not match a bank statement line. Code it from Reconciliation where you can.")
            break
    for l in lines:
        a = accs.get(l["account_id"])
        if a and a.system_key == "suspense":
            w.append("Posting to Suspense - these items still need a proper account.")
            break
    return w


# ------------------------------------------------------------------------------------------------ multi-currency --
def base_currency(org):
    return (org.base_currency or "AUD").upper()


def latest_rate(db, org, currency, on_date):
    r = db.query(FxRate).filter(FxRate.org_id == org.id, FxRate.currency == currency, FxRate.rate_date <= on_date).order_by(FxRate.rate_date.desc()).first()
    return Decimal(r.rate) if r else None


def fx_context(db, org, currency, rate, on_date):
    """(currency, rate) for a foreign-currency journal, or (None, None) for a base-currency one. A rate is ALWAYS explicit or from the organisation's own table -
    AccFino never falls back to a guessed rate."""
    cur = (currency or "").strip().upper() or None
    if not cur or cur == base_currency(org):
        return None, None
    if not re.fullmatch(r"[A-Z]{3}", cur):
        raise BooksError(f"'{currency}' is not a valid 3-letter currency code")
    if rate in (None, ""):
        rate = latest_rate(db, org, cur, on_date)
        if rate is None:
            raise BooksError(f"There is no {cur} exchange rate on or before {on_date.isoformat()}. Enter the rate for this journal (1 {cur} = ? {base_currency(org)}) or add it under Exchange rates")
    try:
        rate = Decimal(str(rate))
    except Exception:
        raise BooksError("The exchange rate is not a number")
    if not (Decimal("0.00000001") <= rate <= Decimal("1000000")):
        raise BooksError("The exchange rate is outside a sensible range")
    return cur, rate.quantize(Decimal("0.00000001"))


def tax_rate_map(db, org, lines):
    ids = {int(l["tax_code_id"]) for l in lines if l.get("tax_code_id")}
    return {t.id: Decimal(t.rate) for t in db.query(m.TaxCode).filter(m.TaxCode.org_id == org.id, m.TaxCode.id.in_(ids))} if ids else {}


def convert_to_base(lines, rate, tax_rates=None):
    """Foreign lines -> base-currency lines that still carry the original amounts. The journal must balance in the FOREIGN currency first (GST included).
    GST is then RE-COMPUTED IN BASE CURRENCY on each converted net amount (the BAS is in dollars, so the tax is 10% of the converted amount, not the converted
    tax); the GST account line is the sum of those. Any cents left over from converting each line are absorbed by the largest non-GST line on the heavier side."""
    tax_rates = tax_rates or {}
    fd, fc = sum((l["debit"] for l in lines), Z), sum((l["credit"] for l in lines), Z)
    if fd != fc:
        raise BooksError(f"The journal must balance in the foreign currency: debits {fd}, credits {fc}")
    out = []
    for l in lines:
        out.append(dict(l, debit=money(l["debit"] * rate), credit=money(l["credit"] * rate), orig_debit=l["debit"], orig_credit=l["credit"],
                        tax_amount=Z if l.get("gst_line") else money(l.get("tax_amount") or 0) * 1))
    gst_by = defaultdict(lambda: Z)
    for l in out:
        if l.get("gst_line") or not l["tax_amount"]:
            continue
        r = tax_rates.get(l.get("tax_code_id"))
        base_net = l["debit"] or l["credit"]
        l["tax_amount"] = money(base_net * r) if r else money(l["tax_amount"] * rate)         # GST in dollars, on the converted amount
        gst_by[(l["tax_code_id"], "debit" if l["debit"] else "credit")] += l["tax_amount"]
    for l in out:
        if l.get("gst_line"):
            side = "debit" if l["debit"] else "credit"
            new = gst_by.get((l["tax_code_id"], side), Z)
            l["debit" if side == "debit" else "credit"] = new
    out = [l for l in out if not (l.get("gst_line") and l["debit"] == 0 and l["credit"] == 0)]         # GST that rounds to nothing in dollars
    bd, bc = sum((l["debit"] for l in out), Z), sum((l["credit"] for l in out), Z)
    res = bd - bc
    if res:
        if abs(res) > Decimal("0.01") * (len(out) + 1):
            raise BooksError("Converting at this rate leaves an unexpected difference; check the amounts and the rate")
        side = "debit" if res > 0 else "credit"
        cands = [l for l in out if l[side] > 0 and not l.get("gst_line")] or [l for l in out if l[side] > 0]
        target = max(cands, key=lambda l: l[side])
        target[side] = target[side] - abs(res)
    return out, res


def set_fx_rate(db, org, ctx, currency, rate_date, rate, source=None):
    cur = (currency or "").strip().upper()
    if not re.fullmatch(r"[A-Z]{3}", cur) or cur == base_currency(org):
        raise BooksError(f"Enter a foreign currency code (3 letters, not {base_currency(org)})")
    d = as_date_(rate_date, "rate date")
    try:
        r = Decimal(str(rate))
    except Exception:
        raise BooksError("The exchange rate is not a number")
    if not (Decimal("0.00000001") <= r <= Decimal("1000000")):
        raise BooksError("The exchange rate is outside a sensible range")
    row = db.query(FxRate).filter_by(org_id=org.id, currency=cur, rate_date=d).one_or_none()
    if row is None:
        row = FxRate(org_id=org.id, currency=cur, rate_date=d, rate=r, source=(source or "manual")[:60], created_by=ctx.user_id)
        db.add(row)
    else:
        row.rate, row.source = r, (source or row.source)
    db.flush()
    return row


def fx_dict(r):
    return dict(id=r.id, currency=r.currency, date=r.rate_date.isoformat(), rate=str(r.rate), source=r.source)


def preview(db, org, data):
    """What WILL post: expanded lines, totals, balance, warnings. Never raises for business-rule problems - returns errors[] instead."""
    res = dict(lines=[], total_debit=_s(Z), total_credit=_s(Z), balanced=False, difference=_s(Z), gst_total=_s(Z), warnings=[], errors=[], fx=None)
    try:
        jdate = as_date_(data.get("date"), "date")
        cur, rate = fx_context(db, org, data.get("currency"), data.get("exchange_rate"), jdate)
        lines, gst_total = expand_lines(db, org, data.get("lines") or [], data.get("amounts_are") or "no_tax", foreign=bool(cur))
        fx = None
        if cur:
            ftd, ftc = sum((l["debit"] for l in lines), Z), sum((l["credit"] for l in lines), Z)
            if ftd != ftc:
                res["errors"].append(f"Out of balance in {cur} by {abs(ftd - ftc)} (debits {ftd}, credits {ftc}).")
                res["fx"] = dict(currency=cur, rate=str(rate), foreign_total=_s(ftd), rounding="0.00")
                return res
            lines, rounding = convert_to_base(lines, rate, tax_rate_map(db, org, lines))
            gst_total = sum((l["debit"] or l["credit"] for l in lines if l.get("gst_line")), Z)              # GST in dollars, as it will reach the BAS
            fx = dict(currency=cur, rate=str(rate), foreign_total=_s(ftd), rounding=_s(rounding), base=base_currency(org), gst_base=_s(gst_total))
    except BooksError as e:
        res["errors"].append(str(e))
        return res
    accs = _names(db, org)
    td, tc = sum((l["debit"] for l in lines), Z), sum((l["credit"] for l in lines), Z)
    res.update(lines=[dict(account_id=l["account_id"], account_code=accs[l["account_id"]].code, account_name=accs[l["account_id"]].name, description=l["description"],
                           debit=_s(l["debit"]), credit=_s(l["credit"]), tax_code_id=l["tax_code_id"], tax_amount=_s(l["tax_amount"]), is_gst=(accs[l["account_id"]].system_key == "gst"),
                           orig_debit=_s(l["orig_debit"]) if l.get("orig_debit") is not None else None, orig_credit=_s(l["orig_credit"]) if l.get("orig_credit") is not None else None,
                           tracking_option_ids=l.get("tracking_option_ids"))
                      for l in lines], total_debit=_s(td), total_credit=_s(tc), balanced=(td == tc and td > 0), difference=_s(td - tc), gst_total=_s(gst_total), fx=fx)
    if td != tc:
        res["errors"].append(f"Out of balance by {abs(td - tc)} (debits {td}, credits {tc}).")
    if org.lock_date and jdate <= org.lock_date:
        res["errors"].append(f"{jdate.isoformat()} is on or before the lock date {org.lock_date.isoformat()}.")
    ard = data.get("auto_reverse_date")
    if ard:
        try:
            ard = as_date_(ard, "auto-reverse date")
            if ard <= jdate:
                res["errors"].append("The auto-reversing date must be after the journal date.")
            elif org.lock_date and ard <= org.lock_date:
                res["errors"].append("The auto-reversing date is on or before the lock date.")
        except BooksError as e:
            res["errors"].append(str(e))
    res["warnings"] = journal_warnings(db, org, jdate, lines, accs)
    if fx and Decimal(fx["rounding"]) != 0:
        res["warnings"].append(f"Converting to {fx['base']} left {abs(Decimal(fx['rounding']))} of rounding, absorbed in the largest line.")
    return res


def as_date_(v, what="date"):
    if isinstance(v, datetime):
        return v.date()
    if isinstance(v, date):
        return v
    try:
        return date.fromisoformat(str(v)[:10])
    except Exception:
        raise BooksError(f"Invalid {what}: {v!r}")


# ------------------------------------------------------------------------------------------------ posting --
def post_journal_full(db, org, user_id, *, journal_date, narration, lines, reference=None, amounts_are="no_tax", auto_reverse_date=None,
                      source_type="manual", source_ref=None, allow_control=False, currency=None, exchange_rate=None):
    """Post a journal (GST-expanded) and, if asked, its auto-reversing journal. Returns (journal, reversal_or_None). Caller commits."""
    journal_date = as_date_(journal_date)
    if not (narration or "").strip():
        raise BooksError("A journal needs a narration")
    if auto_reverse_date:
        auto_reverse_date = as_date_(auto_reverse_date, "auto-reverse date")
        if auto_reverse_date <= journal_date:
            raise BooksError("The auto-reversing date must be after the journal date")
    cur, rate = fx_context(db, org, currency, exchange_rate, journal_date)
    exp, _ = expand_lines(db, org, lines, amounts_are, allow_control=allow_control, foreign=bool(cur))
    if cur:
        exp, _rounding = convert_to_base(exp, rate, tax_rate_map(db, org, exp))
    try:
        j = L.post_journal(db, org, journal_date=journal_date, lines=exp, narration=narration, reference=reference, source_type=source_type,
                           source_ref=source_ref, created_by=user_id, currency=cur, exchange_rate=rate)
    except L.LedgerError as e:
        raise _err(e)
    rj = None
    if auto_reverse_date:
        rev = [dict(account_id=l.account_id, debit=l.credit, credit=l.debit, tax_code_id=l.tax_code_id, tax_amount=l.tax_amount, description=l.description,
                    tracking_option_ids=l.tracking_option_ids, contact_name=l.contact_name, orig_debit=l.orig_credit, orig_credit=l.orig_debit) for l in j.lines]
        try:
            rj = L.post_journal(db, org, journal_date=auto_reverse_date, lines=rev, narration=f"Auto-reversal of journal {j.journal_no}: {narration}"[:500], reference=reference,
                                source_type="auto_reversal", source_ref=f"journal:{j.id}", created_by=user_id, reversal_of_id=j.id, currency=cur, exchange_rate=rate)
        except L.LedgerError as e:
            raise _err(e)
        j.reversed_by_id = rj.id                  # status stays 'posted' (the reversal has not happened yet); allowed by the journal guard trigger
        db.flush()
    return j, rj


# ------------------------------------------------------------------------------------------------ drafts --
def _clean_lines(db, org, lines):
    """Light validation for a draft: accounts/tax codes/tracking belong to the org. Balance is NOT required until it is posted."""
    if not isinstance(lines, list):
        raise BooksError("lines must be a list")
    out = []
    ids = {int(l["account_id"]) for l in lines if l.get("account_id") not in (None, "")}
    ok = {a.id for a in db.query(m.LedgerAccount.id).filter(m.LedgerAccount.org_id == org.id, m.LedgerAccount.id.in_(ids))} if ids else set()
    for i, l in enumerate(lines, start=1):
        if l.get("account_id") in (None, "") and not (l.get("debit") or l.get("credit")):
            continue                                  # blank spare row
        if l.get("account_id") in (None, "") or int(l["account_id"]) not in ok:
            raise BooksError(f"Line {i}: choose an account from this organisation")
        dr, cr = _amount(l.get("debit") or 0, f"Line {i} debit"), _amount(l.get("credit") or 0, f"Line {i} credit")
        if dr < 0 or cr < 0 or (dr and cr):
            raise BooksError(f"Line {i}: enter either a debit or a credit (not negative)")
        tid = l.get("tax_code_id")
        if tid not in (None, ""):
            get_tax(db, org, tid)
        alloc = None
        if l.get("allocations"):
            if not isinstance(l["allocations"], list):
                raise BooksError(f"Line {i}: the split must be a list")
            alloc = [dict(tracking_option_ids=[int(x) for x in (a.get("tracking_option_ids") or [])],
                          **({"percent": _s(a["percent"])} if a.get("percent") not in (None, "") else {"amount": _s(a.get("amount"))})) for a in l["allocations"]]
        out.append(dict(account_id=int(l["account_id"]), description=(l.get("description") or None), debit=_s(dr), credit=_s(cr),
                        tax_code_id=int(tid) if tid not in (None, "") else None, tracking_option_ids=[int(x) for x in (l.get("tracking_option_ids") or [])] or None,
                        contact_name=(l.get("contact_name") or None), allocations=alloc))
    return out


def _cur_rate(data):
    cur = (data.get("currency") or "").strip().upper() or None
    rate = None
    if cur and data.get("exchange_rate") not in (None, ""):
        try:
            rate = Decimal(str(data["exchange_rate"]))
        except Exception:
            raise BooksError("The exchange rate is not a number")
        if rate <= 0:
            raise BooksError("The exchange rate must be greater than zero")
    return cur, rate


def create_draft(db, org, ctx, data, *, kind="manual", source_ref=None, payload=None, confidence=None, reason=None, status="draft"):
    cur, rate = _cur_rate(data)
    d = JournalDraft(currency=cur, exchange_rate=rate, org_id=org.id, kind=kind, status=status, journal_date=as_date_(data.get("date") or date.today()), narration=(data.get("narration") or "").strip()[:500],
                     reference=((data.get("reference") or "").strip()[:100] or None), amounts_are=data.get("amounts_are") or "no_tax",
                     auto_reverse_date=as_date_(data["auto_reverse_date"], "auto-reverse date") if data.get("auto_reverse_date") else None,
                     lines=_clean_lines(db, org, data.get("lines") or []) if kind != "ai_bank" else (data.get("lines") or []), payload=payload, confidence=confidence, reason=reason,
                     source_ref=source_ref, created_by=ctx.user_id, created_by_name=ctx.username, submitted_at=datetime.utcnow() if status == "submitted" else None)
    if d.amounts_are not in AMOUNTS_ARE:
        raise BooksError("amounts_are must be no_tax, inclusive or exclusive")
    db.add(d)
    db.flush()
    return d


def _own_or_approver(ctx, d):
    if d.created_by != ctx.user_id and not can_approve(ctx):
        raise BooksError("Only the person who created this draft (or an approver) can change it", 403)


def update_draft(db, org, ctx, d, data):
    reviewing = d.kind == "ai_bank" and d.status == "submitted"        # a reviewer may correct a pending AI suggestion before approving it
    if d.status not in ("draft", "rejected") and not reviewing:
        raise BooksError(f"A {d.status} journal cannot be edited", 409)
    if reviewing and not can_approve(ctx):
        raise BooksError("Only an approver can adjust a suggestion under review", 403)
    _own_or_approver(ctx, d)
    if d.kind == "ai_bank":
        p = dict(d.payload or {})
        if p.get("kind") != "coding":
            raise BooksError("Only a coding suggestion can be adjusted; approve or reject a match suggestion as it stands", 409)
        if data.get("account_id") or data.get("account"):
            acc = get_account(db, org, data.get("account_id") or data.get("account"))
            p["account_id"] = acc.id
        if "tax_code_id" in data or "tax_code" in data:
            tid = data.get("tax_code_id") or data.get("tax_code")
            p["tax_code_id"] = get_tax(db, org, tid).id if tid not in (None, "") else None
        if "contact_name" in data:
            p["contact_name"] = data.get("contact_name") or None
        line = db.get(b.BankLine, p["bank_line_id"])
        d.payload = p
        d.lines = _coding_lines(db, org, line, p["account_id"], p.get("tax_code_id"), p.get("contact_name"))
        d.reason = "Adjusted by a reviewer"
    else:
        if data.get("date"):
            d.journal_date = as_date_(data["date"])
        if "narration" in data:
            d.narration = (data.get("narration") or "").strip()[:500]
        if "reference" in data:
            d.reference = ((data.get("reference") or "").strip()[:100] or None)
        if data.get("amounts_are"):
            if data["amounts_are"] not in AMOUNTS_ARE:
                raise BooksError("amounts_are must be no_tax, inclusive or exclusive")
            d.amounts_are = data["amounts_are"]
        if "auto_reverse_date" in data:
            d.auto_reverse_date = as_date_(data["auto_reverse_date"], "auto-reverse date") if data.get("auto_reverse_date") else None
        if "currency" in data:
            d.currency, d.exchange_rate = _cur_rate(data)
        if data.get("lines") is not None:
            d.lines = _clean_lines(db, org, data["lines"])
    if d.status == "rejected":
        d.status, d.rejected_reason = ("submitted" if d.kind == "ai_bank" else "draft"), None
    db.flush()
    return d


def _draft_as_data(d):
    return dict(date=d.journal_date, narration=d.narration, reference=d.reference, amounts_are=d.amounts_are, auto_reverse_date=d.auto_reverse_date, lines=d.lines,
                currency=d.currency, exchange_rate=d.exchange_rate)


def submit_draft(db, org, ctx, d):
    if d.status not in ("draft", "rejected"):
        raise BooksError(f"A {d.status} journal cannot be submitted", 409)
    _own_or_approver(ctx, d)
    if d.kind != "ai_bank":
        pv = preview(db, org, _draft_as_data(d))
        if pv["errors"]:
            raise BooksError("Fix before submitting: " + " ".join(pv["errors"]))
    d.status, d.submitted_at, d.rejected_reason = "submitted", datetime.utcnow(), None
    db.flush()
    return d


def _move_attachments(db, d, journal_id):
    for a in db.query(b.Attachment).filter_by(org_id=d.org_id, owner_kind="journal_draft", owner_id=d.id):
        a.owner_kind, a.owner_id = "journal", journal_id


def approve_draft(db, org, ctx, d, *, post_date=None):
    """Post a draft/submitted journal to the ledger. Approvers only; you cannot approve your own draft unless you are the owner/admin."""
    if not can_approve(ctx):
        raise BooksError(f"Your role '{ctx.role}' cannot approve journals", 403)
    if d.status not in ("draft", "submitted"):
        raise BooksError(f"Only draft or submitted journals can be approved (this one is {d.status})", 409)
    if d.created_by == ctx.user_id and d.kind == "manual" and ctx.role not in ("owner", "admin") and not ctx.is_admin:
        raise BooksError("You cannot approve your own journal; ask another approver (segregation of duties)", 403)
    if d.kind == "ai_bank":
        _approve_ai(db, org, ctx, d)
        journal_id = d.posted_journal_id
    else:
        jd = as_date_(post_date) if post_date else d.journal_date
        j, rj = post_journal_full(db, org, ctx.user_id, journal_date=jd, narration=d.narration, lines=d.lines, reference=d.reference, amounts_are=d.amounts_are,
                                  auto_reverse_date=d.auto_reverse_date, currency=d.currency, exchange_rate=d.exchange_rate, source_type="repeating" if d.kind == "repeating" else "manual",
                                  source_ref=d.source_ref if d.kind == "repeating" else f"draft:{d.id}")
        d.posted_journal_id, journal_id = j.id, j.id
    d.status, d.decided_by, d.decided_by_name, d.decided_at, d.rejected_reason = "posted", ctx.user_id, ctx.username, datetime.utcnow(), None
    _move_attachments(db, d, journal_id)
    db.flush()
    return d


def reject_draft(db, ctx, d, reason):
    if not can_approve(ctx):
        raise BooksError(f"Your role '{ctx.role}' cannot reject journals", 403)
    if d.status not in ("draft", "submitted"):
        raise BooksError(f"Only draft or submitted journals can be rejected (this one is {d.status})", 409)
    if not (reason or "").strip():
        raise BooksError("Give the preparer a reason")
    d.status, d.rejected_reason, d.decided_by, d.decided_by_name, d.decided_at = "rejected", reason.strip()[:300], ctx.user_id, ctx.username, datetime.utcnow()
    db.flush()
    return d


def delete_draft(db, ctx, d):
    if d.status == "posted":
        raise BooksError("A posted journal cannot be deleted; reverse it instead", 409)
    if d.status == "submitted" and not can_approve(ctx):
        raise BooksError("A submitted journal can only be withdrawn by an approver", 409)
    _own_or_approver(ctx, d)
    for a in db.query(b.Attachment).filter_by(org_id=d.org_id, owner_kind="journal_draft", owner_id=d.id):
        db.delete(a)
    db.delete(d)
    db.flush()


def draft_dict(db, d, accs=None):
    accs = accs or {}
    lines = []
    for l in d.lines or []:
        a = accs.get(l.get("account_id"))
        lines.append(dict(l, account_code=a.code if a else None, account_name=a.name if a else None))
    p = d.payload or {}
    bl = db.get(b.BankLine, p["bank_line_id"]) if p.get("bank_line_id") else None
    return dict(id=d.id, kind=d.kind, status=d.status, date=d.journal_date.isoformat(), narration=d.narration, reference=d.reference, amounts_are=d.amounts_are,
                auto_reverse_date=d.auto_reverse_date.isoformat() if d.auto_reverse_date else None, currency=d.currency,
                exchange_rate=_s(d.exchange_rate) if d.exchange_rate is not None else None, lines=lines, confidence=_s(d.confidence) if d.confidence is not None else None,
                reason=d.reason, source_ref=d.source_ref, created_by=d.created_by_name, created_at=d.created_at.isoformat() if d.created_at else None,
                submitted_at=d.submitted_at.isoformat() if d.submitted_at else None, decided_by=d.decided_by_name, decided_at=d.decided_at.isoformat() if d.decided_at else None,
                rejected_reason=d.rejected_reason, posted_journal_id=d.posted_journal_id,
                total=_s(sum((Decimal(str(l.get("debit") or 0)) for l in d.lines or []), Z)),
                suggestion=dict(type=p.get("kind"), account_id=p.get("account_id"), tax_code_id=p.get("tax_code_id"), contact_name=p.get("contact_name"), source=p.get("source"),
                                bank_line=dict(id=bl.id, date=bl.line_date.isoformat(), description=bl.description, amount=_s(bl.amount), status=bl.status,
                                               account_id=bl.bank_account_id) if bl else None,
                                match=(p.get("suggestion") or {}).get("reference")) if d.kind == "ai_bank" else None)


def list_drafts(db, org, *, status=None, kind=None, limit=500):
    q = db.query(JournalDraft).filter(JournalDraft.org_id == org.id)
    if status:
        q = q.filter(JournalDraft.status == status)
    if kind:
        q = q.filter(JournalDraft.kind == kind)
    counts = {f"{k}:{s}": n for k, s, n in db.query(JournalDraft.kind, JournalDraft.status, func.count()).filter(JournalDraft.org_id == org.id).group_by(JournalDraft.kind, JournalDraft.status)}
    rows = q.order_by(JournalDraft.id.desc()).limit(limit).all()
    rows.sort(key=lambda d: (d.confidence is None, -(d.confidence or 0)))       # most confident suggestions first; manual drafts by newest
    accs = _names(db, org)
    return dict(items=[draft_dict(db, d, accs) for d in rows], counts=counts,
                pending=sum(n for k, n in counts.items() if k.endswith(":submitted")), drafts=sum(n for k, n in counts.items() if k.endswith(":draft")))


# ------------------------------------------------------------------------------------------------ AI / rule bank suggestions --
def _coding_lines(db, org, line, account_id, tax_code_id, contact_name=None):
    """Preview of what 'spend / receive money' posts for a bank line (bank amounts are GST-inclusive) - mirrors banking.create_from_line."""
    money_in = line.amount > 0
    gross = abs(line.amount)
    acc = db.get(m.LedgerAccount, account_id)
    tax = db.get(m.TaxCode, tax_code_id) if tax_code_id else (db.get(m.TaxCode, acc.default_tax_code_id) if acc.default_tax_code_id else None)
    rate = Decimal(tax.rate) if (tax is not None and org.gst_registered) else Decimal(0)
    t = money(gross * rate / (1 + rate)) if rate else Z
    side, opp = ("credit", "debit") if money_in else ("debit", "credit")
    gst = db.query(m.LedgerAccount).filter_by(org_id=org.id, system_key="gst").first()
    out = [{"account_id": line.bank_account_id, "description": line.description[:200], opp: _s(gross), side: "0.00", "tax_code_id": None}]
    out.append({"account_id": account_id, "description": line.description[:200], side: _s(gross - t), opp: "0.00", "tax_code_id": tax.id if tax else None, "contact_name": contact_name})
    if t and gst:
        out.append({"account_id": gst.id, "description": "GST", side: _s(t), opp: "0.00", "tax_code_id": tax.id})
    return out


def _match_lines(db, org, line, s):
    ar = db.query(m.LedgerAccount).filter_by(org_id=org.id, system_key="ar_control" if line.amount > 0 else "ap_control").first()
    gross = abs(line.amount)
    if line.amount > 0:
        return [{"account_id": line.bank_account_id, "debit": _s(gross), "credit": "0.00", "description": line.description[:200]},
                {"account_id": ar.id, "debit": "0.00", "credit": _s(gross), "description": f"Receipt against {s.get('reference') or 'invoice'} - {s.get('contact')}"}]
    return [{"account_id": ar.id, "debit": _s(gross), "credit": "0.00", "description": f"Payment of {s.get('reference') or 'bill'} - {s.get('contact')}"},
            {"account_id": line.bank_account_id, "debit": "0.00", "credit": _s(gross), "description": line.description[:200]}]


def _learned_confidence(db, org, description):
    key = K.merchant_key(description)
    mem = db.query(b.ClassifierMemory).filter_by(org_id=org.id, key=key).one_or_none() if key else None
    return min(Decimal("0.95"), Decimal("0.70") + Decimal("0.05") * (mem.hits if mem else 0))


def suggest_bank_journals(db, org, ctx, *, limit=300):
    """Turn unreconciled bank lines into REVIEWABLE suggestions. Nothing posts until a person approves.
    Order of evidence: (1) an open invoice/bill/payment that matches the line (0.90-0.99), (2) a bank rule (0.95), (3) what this organisation has taught the
    classifier (0.75-0.95, rising with each confirmation). Anything else is left alone - a wrong guess is worse than none."""
    busy = {r[0] for r in db.query(JournalDraft.source_ref).filter(JournalDraft.org_id == org.id, JournalDraft.kind == "ai_bank", JournalDraft.status.in_(("draft", "submitted", "rejected")))}
    lines = db.query(b.BankLine).filter(b.BankLine.org_id == org.id, b.BankLine.status == "unreconciled").order_by(b.BankLine.line_date.desc(), b.BankLine.id.desc()).limit(limit).all()
    made = dict(created=0, matches=0, coded=0, rdr=0, llm=0, llm_calls=0, llm_enabled=False, llm_unavailable=None, skipped_existing=0, no_evidence=0, locked=0)
    cache = {}
    made["llm_enabled"] = use_llm = bool(get_settings(db, org)["llm_suggestions"])
    ai_state = AI.new_state()
    for l in lines:
        ref = f"bankline:{l.id}"
        if ref in busy:
            made["skipped_existing"] += 1
            continue
        if org.lock_date and l.line_date <= org.lock_date:
            made["locked"] += 1
            continue
        s = K.suggest_match(db, org, dict(date=l.line_date, description=l.description, amount=l.amount), l.bank_account_id, _cache=cache)
        if s:
            create_draft(db, org, ctx, dict(date=l.line_date, narration=f"{'Receipt' if l.amount > 0 else 'Payment'}: {l.description}"[:500], lines=_match_lines(db, org, l, s)), kind="ai_bank",
                         source_ref=ref, payload=dict(kind="match", bank_line_id=l.id, suggestion=s), confidence=Decimal(s["confidence"]), reason=s["reason"], status="submitted")
            made["created"] += 1
            made["matches"] += 1
            continue
        c = K.classify(db, org, l.description, l.amount)
        if not (c and c.get("account_id")):
            c = AI.rdr_suggest(db, org, l.description, l.amount)                       # platform RDR rules (deterministic)
        if not c and use_llm:
            c = AI.llm_suggest(db, org, l.description, l.amount, ai_state)             # Groq via the shared pool - opt-in per organisation
        if c and c.get("account_id"):
            tax = db.get(m.TaxCode, c["tax_code_id"]) if c.get("tax_code_id") else None
            if tax is not None and tax.applies_to not in (("sales", "both") if l.amount > 0 else ("purchases", "both")):
                made["no_evidence"] += 1
                continue
            src = str(c["source"])
            conf = Decimal("0.95") if src.startswith("rule") else _learned_confidence(db, org, l.description) if src == "learned" else Decimal(str(c["confidence"]))
            if src in ("rdr", "llm"):
                made[src] += 1
            create_draft(db, org, ctx, dict(date=l.line_date, narration=f"{'Receive' if l.amount > 0 else 'Spend'} money: {l.description}"[:500],
                                            lines=_coding_lines(db, org, l, c["account_id"], c.get("tax_code_id"), c.get("contact_name"))), kind="ai_bank", source_ref=ref,
                         payload=dict(kind="coding", bank_line_id=l.id, account_id=c["account_id"], tax_code_id=c.get("tax_code_id"), contact_name=c.get("contact_name"),
                                      source=c["source"], why=c["why"]), confidence=conf, reason=f"{c['why']} -> {c['account_code']} {c['account_name']}"[:300], status="submitted")
            made["created"] += 1
            made["coded"] += 1
        else:
            made["no_evidence"] += 1
    made["llm_calls"], made["llm_unavailable"] = ai_state["calls"], ai_state["unavailable_reason"]
    db.flush()
    return made


def _approve_ai(db, org, ctx, d):
    p = d.payload or {}
    line = db.query(b.BankLine).filter_by(org_id=org.id, id=p.get("bank_line_id")).with_for_update().one_or_none()
    if line is None:
        raise BooksError("The bank line for this suggestion no longer exists", 404)
    if line.status != "unreconciled":
        raise BooksError(f"That bank line is already {line.status}; discard this suggestion", 409)
    if p.get("kind") == "match":
        K.apply_suggestion(db, org, ctx.user_id, line, p["suggestion"])
        d.posted_journal_id = line.journal_id
    else:
        j = K.create_from_line(db, org, ctx.user_id, line, account=p["account_id"], tax_code=p.get("tax_code_id"), contact=p.get("contact_name"), learn=True)
        d.posted_journal_id = j.id


def bulk_approve(db, org, ctx, *, min_confidence=Decimal("0.95"), ids=None):
    """Approve many AI suggestions at once (those at/above the confidence threshold). Commits after each so one failure cannot undo the rest."""
    if not can_approve(ctx):
        raise BooksError(f"Your role '{ctx.role}' cannot approve journals", 403)
    q = db.query(JournalDraft).filter(JournalDraft.org_id == org.id, JournalDraft.kind == "ai_bank", JournalDraft.status == "submitted", JournalDraft.confidence >= Decimal(str(min_confidence)))
    if ids:
        q = q.filter(JournalDraft.id.in_(list(ids)))
    todo = [d.id for d in q.order_by(JournalDraft.id)]
    ok, failed = 0, []
    for did in todo:
        d = db.get(JournalDraft, did)
        try:
            approve_draft(db, org, ctx, d)
            db.commit()
            ok += 1
        except BooksError as e:
            db.rollback()
            failed.append(dict(id=did, error=str(e)))
    return dict(approved=ok, failed=failed, considered=len(todo))


# ------------------------------------------------------------------------------------------------ repeating journals --
def _add_months(d, n, anchor):
    y, mo = divmod(d.month - 1 + n, 12)
    y, mo = d.year + y, mo + 1
    return date(y, mo, min(anchor, monthrange(y, mo)[1]))


def advance(d, frequency, anchor):
    if frequency == "weekly":
        return d + timedelta(days=7)
    if frequency == "fortnightly":
        return d + timedelta(days=14)
    n = {"monthly": 1, "quarterly": 3, "yearly": 12}[frequency]
    return _add_months(d, n, anchor)


def fy_label(org, d):
    end_m = org.fy_end_month or 6
    fy_end_year = d.year if d.month <= end_m else d.year + 1
    start_m = end_m % 12 + 1
    months_in = (d.month - start_m) % 12
    return f"FY{str(fy_end_year)[2:]}", f"Q{months_in // 3 + 1}"


def apply_labels(text, org, d):
    prev = (d.replace(day=1) - timedelta(days=1))
    fy, q = fy_label(org, d)
    reps = {"{month}": d.strftime("%B"), "{mon}": d.strftime("%b"), "{year}": str(d.year), "{prev_month}": prev.strftime("%B"), "{prev_year}": str(prev.year),
            "{fy}": fy, "{quarter}": q, "{date}": d.isoformat()}
    for k, v in reps.items():
        text = (text or "").replace(k, v)
    return text


def repeating_dict(r, accs=None, next_preview=None):
    return dict(id=r.id, name=r.name, frequency=r.frequency, next_date=r.next_date.isoformat(), end_date=r.end_date.isoformat() if r.end_date else None, mode=r.mode,
                narration=r.narration, reference=r.reference, amounts_are=r.amounts_are, reverse_after_days=r.reverse_after_days, lines=r.lines, is_active=r.is_active, currency=r.currency, auto_run=r.auto_run,
                last_run_date=r.last_run_date.isoformat() if r.last_run_date else None, runs=r.runs, last_error=r.last_error,
                next_narration=apply_labels(r.narration, next_preview, r.next_date) if next_preview is not None else None)


def save_repeating(db, org, ctx, data, r=None):
    name = (data.get("name") or "").strip()
    if not name:
        raise BooksError("Give the repeating journal a name")
    freq = data.get("frequency") or "monthly"
    if freq not in FREQUENCIES:
        raise BooksError("frequency must be " + ", ".join(FREQUENCIES))
    nd = as_date_(data.get("next_date"), "next date")
    mode = data.get("mode") or "draft"
    if mode not in ("draft", "post"):
        raise BooksError("mode must be draft or post")
    if mode == "post" and not can_approve(ctx):
        raise BooksError("Only an approver can set a repeating journal to post automatically; use 'draft' so it is reviewed first", 403)
    lines = _clean_lines(db, org, data.get("lines") or [])
    if len(lines) < 2:
        raise BooksError("A repeating journal needs at least two lines")
    amounts = data.get("amounts_are") or "no_tax"
    cur = (data.get("currency") or "").strip().upper() or None
    pv = preview(db, org, dict(date=nd, lines=lines, amounts_are=amounts, currency=cur, exchange_rate="1" if cur else None))
    bad = [e for e in pv["errors"] if "lock date" not in e]
    if bad:
        raise BooksError("The template does not produce a valid journal: " + " ".join(bad))
    rd = data.get("reverse_after_days")
    if rd not in (None, "") and int(rd) < 1:
        raise BooksError("Auto-reverse days must be 1 or more")
    end = as_date_(data["end_date"], "end date") if data.get("end_date") else None
    if end and end < nd:
        raise BooksError("The end date is before the next date")
    fields = dict(name=name[:120], frequency=freq, next_date=nd, anchor_day=nd.day, end_date=end, mode=mode, narration=(data.get("narration") or name)[:500],
                  reference=((data.get("reference") or "").strip()[:100] or None), amounts_are=amounts, reverse_after_days=int(rd) if rd not in (None, "") else None, lines=lines,
                  is_active=bool(data.get("is_active", True)), currency=cur if cur and cur != base_currency(org) else None, auto_run=bool(data.get("auto_run", False)))
    if r is None:
        r = RepeatingJournal(org_id=org.id, created_by=ctx.user_id, **fields)
        db.add(r)
    else:
        for k, v in fields.items():
            setattr(r, k, v)
        r.last_error = None
    db.flush()
    return r


def run_repeating(db, org, ctx, *, as_at=None, template_id=None, max_per_template=36, only_auto=False):
    """Create every occurrence that is due on/before as_at. Commits after each occurrence (a failure stops only that template and is recorded on it).
    Safe to run from several workers at once: each template row is locked (SKIP LOCKED on PostgreSQL) and an occurrence that already exists is never created twice."""
    as_at = as_at or date.today()
    q = db.query(RepeatingJournal).filter(RepeatingJournal.org_id == org.id, RepeatingJournal.is_active.is_(True), RepeatingJournal.next_date <= as_at)
    if template_id:
        q = q.filter(RepeatingJournal.id == template_id)
    if only_auto:
        q = q.filter(RepeatingJournal.auto_run.is_(True))
    res = dict(as_at=as_at.isoformat(), drafts=0, posted=0, errors=[], templates=0, skipped_existing=0)
    for tid in [r.id for r in q.order_by(RepeatingJournal.id)]:
        res["templates"] += 1
        for _ in range(max_per_template):
            r = db.query(RepeatingJournal).filter(RepeatingJournal.id == tid).with_for_update(skip_locked=True).one_or_none()
            if r is None:                                              # another worker holds it right now
                db.rollback()
                break
            if not r.is_active or r.next_date > as_at or (r.end_date and r.next_date > r.end_date):
                db.rollback()
                break
            when, ref = r.next_date, f"repeating:{r.id}"
            try:
                exists = (db.query(m.Journal.id).filter(m.Journal.org_id == org.id, m.Journal.source_ref == ref, m.Journal.journal_date == when).first()
                          or db.query(JournalDraft.id).filter(JournalDraft.org_id == org.id, JournalDraft.source_ref == ref, JournalDraft.journal_date == when).first())
                if exists:                                             # already generated (e.g. by another worker): just move on
                    res["skipped_existing"] += 1
                else:
                    data = dict(date=when, narration=apply_labels(r.narration, org, when), reference=apply_labels(r.reference, org, when) if r.reference else None,
                                amounts_are=r.amounts_are, lines=[dict(l, description=apply_labels(l.get("description"), org, when)) for l in r.lines],
                                auto_reverse_date=when + timedelta(days=r.reverse_after_days) if r.reverse_after_days else None, currency=r.currency)
                    if r.currency:                                     # the rate is the organisation's own rate for that date - never a guess
                        data["exchange_rate"] = str(fx_context(db, org, r.currency, None, when)[1])
                    mode = r.mode
                    if mode == "post" and not can_approve(ctx):
                        if only_auto:                                  # the creator lost approver rights: fall back to a draft rather than post unattended
                            mode = "draft"
                        else:
                            raise BooksError("Only an approver can run a repeating journal that posts automatically", 403)
                    if mode == "post":
                        post_journal_full(db, org, ctx.user_id, journal_date=when, narration=data["narration"], lines=data["lines"], reference=data["reference"], amounts_are=r.amounts_are,
                                          auto_reverse_date=data["auto_reverse_date"], source_type="repeating", source_ref=ref, currency=r.currency,
                                          exchange_rate=data.get("exchange_rate"))
                        res["posted"] += 1
                    else:
                        create_draft(db, org, ctx, data, kind="repeating", source_ref=ref, status="draft")
                        res["drafts"] += 1
                r.last_run_date, r.runs, r.last_error = when, (r.runs or 0) + 1, None
                r.next_date = advance(when, r.frequency, r.anchor_day)
                db.commit()
            except BooksError as e:
                db.rollback()
                r = db.get(RepeatingJournal, tid)
                r.last_error = f"{when.isoformat()}: {e}"[:300]
                db.commit()
                res["errors"].append(dict(id=tid, name=r.name, date=when.isoformat(), error=str(e)))
                break
    return res


# ------------------------------------------------------------------------------------------------ CSV import --
_ALIASES = {"date": ("date", "journal date", "journaldate"), "narration": ("narration", "description of journal", "journal narration", "memo"), "reference": ("reference", "ref"),
            "journal": ("journal", "journal no", "journal number", "journal id"), "account": ("account", "account code", "accountcode", "account name", "code"),
            "description": ("description", "line description", "details"), "debit": ("debit", "dr"), "credit": ("credit", "cr"), "amount": ("amount", "net amount"),
            "tax": ("tax code", "taxcode", "tax", "gst", "tax type"), "contact": ("contact", "name", "customer", "supplier", "party"),
            "tracking": ("tracking", "tracking options", "region", "department", "job", "dimension"),
            "currency": ("currency", "currency code", "ccy"), "rate": ("rate", "exchange rate", "fx rate")}
_DATE_FORMATS = ("%Y-%m-%d", "%d/%m/%Y", "%d/%m/%y", "%d-%m-%Y", "%d %b %Y", "%d-%b-%Y", "%d %B %Y")


def _pd(s):
    s = (s or "").strip()
    for f in _DATE_FORMATS:
        try:
            return datetime.strptime(s, f).date()
        except ValueError:
            pass
    return None


def _num(s):
    s = (s or "").strip().replace(",", "").replace("$", "")
    if not s:
        return None
    neg = s.startswith("(") and s.endswith(")")
    s = s.strip("()")
    v = Decimal(s)
    return -v if neg else v


def parse_journal_csv(text):
    text = text.lstrip("\ufeff")
    rows = list(csv.reader(io.StringIO(text)))
    rows = [r for r in rows if any((c or "").strip() for c in r)]
    if not rows:
        raise BooksError("The file is empty")
    head = [h.strip().lower() for h in rows[0]]
    idx = {}
    for key, names in _ALIASES.items():
        for n in names:
            if n in head and key not in idx:
                idx[key] = head.index(n)
    if "account" not in idx or "date" not in idx:
        raise BooksError("The file needs at least Date and Account columns (plus Debit/Credit or Amount). Columns found: " + ", ".join(rows[0]))
    if "amount" not in idx and "debit" not in idx and "credit" not in idx:
        raise BooksError("The file needs Debit and Credit columns (or a signed Amount column)")
    if len(rows) - 1 > MAX_IMPORT_LINES:
        raise BooksError(f"Too many lines ({len(rows) - 1}); the limit is {MAX_IMPORT_LINES} per file")
    g = lambda r, k: (r[idx[k]].strip() if k in idx and idx[k] < len(r) else "")
    journals, cur = [], None
    for n, r in enumerate(rows[1:], start=2):
        d_raw, nar, jn = g(r, "date"), g(r, "narration"), g(r, "journal")
        new = False
        if "journal" in idx and jn:
            new = cur is None or cur["key"] != jn
        elif d_raw or nar:
            new = True
        if new or cur is None:
            cur = dict(key=jn or f"row{n}", row=n, date_raw=d_raw, date=_pd(d_raw), narration=nar, reference=g(r, "reference"), lines=[], errors=[], warnings=[],
                       currency=None, rate=None)
            journals.append(cur)
        if not cur["narration"] and nar:
            cur["narration"] = nar
        if not cur["reference"] and g(r, "reference"):
            cur["reference"] = g(r, "reference")
        c_raw, x_raw = g(r, "currency").upper(), g(r, "rate")
        if c_raw:
            if not re.fullmatch(r"[A-Z]{3}", c_raw):
                cur["errors"].append(f"Row {n}: '{c_raw}' is not a valid 3-letter currency code")
            elif cur["currency"] and cur["currency"] != c_raw:
                cur["errors"].append(f"Row {n}: a journal can only be in one currency ({cur['currency']} above, {c_raw} here)")
            else:
                cur["currency"] = cur["currency"] or c_raw
        if x_raw:
            try:
                xr = Decimal(x_raw.replace(",", ""))
                if xr <= 0:
                    raise ValueError
                if cur["rate"] and cur["rate"] != xr:
                    cur["errors"].append(f"Row {n}: a journal can only have one exchange rate ({cur['rate']} above, {xr} here)")
                cur["rate"] = cur["rate"] or xr
            except Exception:
                cur["errors"].append(f"Row {n}: the exchange rate is not a valid positive number")
        try:
            dr, cr = _num(g(r, "debit")), _num(g(r, "credit"))
            if "amount" in idx and dr is None and cr is None:
                a = _num(g(r, "amount"))
                dr, cr = (a, None) if (a is not None and a >= 0) else (None, -a if a is not None else None)
        except Exception:
            cur["errors"].append(f"Row {n}: the amount is not a number")
            continue
        tr = [t.strip() for t in re.split(r"[;|]", g(r, "tracking")) if t.strip()]
        cur["lines"].append(dict(row=n, account=g(r, "account"), description=g(r, "description") or None, debit=dr or Z, credit=cr or Z, tax_code=g(r, "tax") or None,
                                 contact_name=g(r, "contact") or None, tracking_names=tr))
    if len(journals) > MAX_IMPORT_JOURNALS:
        raise BooksError(f"Too many journals ({len(journals)}); the limit is {MAX_IMPORT_JOURNALS} per file")
    return journals


def _resolve_tracking(db, org):
    return {o.name.strip().lower(): o.id for o in db.query(m.TrackingOption).join(m.TrackingCategory).filter(m.TrackingCategory.org_id == org.id)}


def import_journals(db, org, ctx, text, *, mode="draft", amounts_are="no_tax", dry_run=True):
    """mode: draft (default) or post. Validates EVERY journal first; if any has an error nothing is saved (a partial import is worse than none)."""
    if mode not in ("draft", "post"):
        raise BooksError("mode must be draft or post")
    if mode == "post" and not dry_run and not can_approve(ctx):
        raise BooksError("Only an approver can post imported journals directly; import them as drafts for review", 403)
    journals = parse_journal_csv(text)
    tracking = _resolve_tracking(db, org)
    accs = _names(db, org)
    prepared = []
    for j in journals:
        errs, lines = list(j["errors"]), []
        if j["date"] is None:
            errs.append(f"Row {j['row']}: '{j['date_raw']}' is not a valid date (use DD/MM/YYYY or YYYY-MM-DD)")
        if not j["narration"]:
            errs.append(f"Row {j['row']}: a journal needs a narration")
        for l in j["lines"]:
            tids, allocs = [], []
            parsed = [(re.fullmatch(r"(.+?)\s*:\s*(\d+(?:\.\d+)?)\s*%?", tn), tn) for tn in l["tracking_names"]]
            split_mode = any(mt for mt, _ in parsed)
            if split_mode and not all(mt for mt, _ in parsed):
                errs.append(f"Row {l['row']}: to split a line give every tracking option a share, like Sydney:60;Melbourne:40")
            for mt, tn in parsed:
                nm, share = (mt.group(1), mt.group(2)) if mt else (tn, None)
                if nm.lower() not in tracking:
                    errs.append(f"Row {l['row']}: tracking option '{nm}' does not exist")
                elif split_mode and mt:
                    allocs.append(dict(tracking_option_ids=[tracking[nm.lower()]], percent=share))     # Job:percent -> a MYOB-style split of this line
                else:
                    tids.append(tracking[nm.lower()])
            lines.append(dict(account=l["account"], description=l["description"], debit=l["debit"], credit=l["credit"], tax_code=l["tax_code"], contact_name=l["contact_name"],
                              tracking_option_ids=tids or None, allocations=allocs or None))
        pv = dict(warnings=[])
        if j["date"] and lines and not errs:
            pv = preview(db, org, dict(date=j["date"], lines=lines, amounts_are=amounts_are, currency=j.get("currency"), exchange_rate=str(j["rate"]) if j.get("rate") else None))
            errs += [f"Journal at row {j['row']}: {e}" for e in pv["errors"]]
        fxi = pv.get("fx") or {}
        prepared.append(dict(row=j["row"], date=j["date"], narration=j["narration"], reference=j["reference"] or None, lines=lines, errors=errs, warnings=pv.get("warnings", []),
                             total=_s(pv.get("total_debit", "0.00")), currency=j.get("currency") if fxi else None, rate=fxi.get("rate")))
    summary = [dict(row=p["row"], date=p["date"].isoformat() if p["date"] else None, narration=p["narration"], reference=p["reference"], lines=len(p["lines"]), total=p["total"],
                    errors=p["errors"], warnings=p["warnings"], currency=p["currency"], rate=p["rate"]) for p in prepared]
    n_err = sum(1 for p in prepared if p["errors"])
    res = dict(journals=summary, count=len(prepared), invalid=n_err, valid=len(prepared) - n_err, mode=mode, dry_run=dry_run, saved=0, posted=0)
    if dry_run or n_err:
        if not dry_run and n_err:
            res["error"] = f"{n_err} journal(s) have errors; nothing was imported. Fix the file and try again."
        return res
    for p in prepared:
        data = dict(date=p["date"], narration=p["narration"], reference=p["reference"], amounts_are=amounts_are, currency=p["currency"], exchange_rate=p["rate"], lines=[
            dict(l, account_id=get_account(db, org, l["account"]).id, tax_code_id=get_tax(db, org, l["tax_code"]).id if l.get("tax_code") else None) for l in p["lines"]])
        if mode == "post":
            post_journal_full(db, org, ctx.user_id, journal_date=p["date"], narration=p["narration"], lines=p["lines"], reference=p["reference"], amounts_are=amounts_are, source_type="manual",
                              source_ref="import", currency=p["currency"], exchange_rate=p["rate"])
            res["posted"] += 1
        else:
            create_draft(db, org, ctx, data, kind="import", source_ref="import")
            res["saved"] += 1
    db.flush()
    return res


# ------------------------------------------------------------------------------------------------ source, history, sources --
def describe_source(db, org, j):
    ref = j.source_ref or ""
    kind, _, ident = ref.partition(":")
    out = dict(kind=j.source_type, label=j.source_type.replace("_", " "), id=None)
    try:
        n = int(ident)
    except ValueError:
        n = None
    if kind == "doc" and n:
        d = db.query(b.Doc).filter_by(org_id=org.id, id=n).first()
        if d:
            out.update(kind="doc", doc_type=d.doc_type, id=d.id, number=d.number, contact=d.contact.name, status=d.status, total=_s(d.total),
                       label=f"{d.doc_type.replace('_', ' ').title()} {d.number} - {d.contact.name}")
    elif kind == "payment" and n:
        p = db.query(b.Payment).filter_by(org_id=org.id, id=n).first()
        if p:
            out.update(kind="payment", id=p.id, contact=p.contact.name, status=p.status, total=_s(p.amount), label=f"{p.kind.replace('_', ' ').title()} {p.contact.name} ({_s(p.amount)})")
    elif kind == "bankline" and n:
        bl = db.query(b.BankLine).filter_by(org_id=org.id, id=n).first()
        if bl:
            out.update(kind="bank_line", id=bl.id, status=bl.status, total=_s(bl.amount), label=f"Bank line {bl.line_date.isoformat()}: {bl.description}")
    elif kind == "claim" and n:
        c = db.query(b.ExpenseClaim).filter_by(org_id=org.id, id=n).first()
        if c:
            out.update(kind="expense_claim", id=c.id, number=c.number, status=c.status, total=_s(c.total), label=f"Expense claim {c.number} - {c.claimant_name}")
    elif kind == "asset" and n:
        from accfino_core.assets.models import FixedAsset
        a = db.query(FixedAsset).filter_by(org_id=org.id, id=n).first()
        if a:
            out.update(kind="asset", id=a.id, number=a.number, label=f"Fixed asset {a.number} - {a.name}")
    elif kind == "item" and n:
        from accfino_core.inventory.models import StockItem
        it = db.query(StockItem).filter_by(org_id=org.id, id=n).first()
        if it:
            out.update(kind="stock_item", id=it.id, label=f"Stock item {it.sku} - {it.name}")
    elif kind == "journal" and n:
        o = db.query(m.Journal).filter_by(org_id=org.id, id=n).first()
        if o:
            out.update(kind="journal", id=o.id, number=o.journal_no, label=f"Journal {o.journal_no}")
    elif kind == "draft" and n:
        d = db.get(JournalDraft, n)
        if d and d.org_id == org.id:
            out.update(kind="journal_draft", id=d.id, label=f"Approved draft #{d.id} (prepared by {d.created_by_name}, approved by {d.decided_by_name})")
    elif kind == "repeating" and n:
        r = db.get(RepeatingJournal, n)
        if r and r.org_id == org.id:
            out.update(kind="repeating", id=r.id, label=f"Repeating journal '{r.name}'")
    return out


def journal_history(db, org, journal_id):
    j = db.query(m.Journal).filter_by(org_id=org.id, id=journal_id).one_or_none()
    if j is None:
        raise BooksError("Journal not found", 404)
    ids = [("journal", str(j.id))]
    drafts = db.query(JournalDraft).filter(JournalDraft.org_id == org.id, JournalDraft.posted_journal_id == j.id).all()
    ids += [("journal_draft", str(d.id)) for d in drafts]
    q = db.query(m.AuditLog).filter(m.AuditLog.org_id == org.id, or_(*[(m.AuditLog.entity == e) & (m.AuditLog.entity_id == i) for e, i in ids])).order_by(m.AuditLog.occurred_at)
    events = [dict(at=(j.created_at.isoformat() + "Z") if j.created_at else None, who=None, action="created", detail=f"Journal {j.journal_no} posted ({j.source_type.replace('_', ' ')})")]
    for d in drafts:
        events.insert(0, dict(at=(d.created_at.isoformat() + "Z") if d.created_at else None, who=d.created_by_name, action="draft prepared", detail=d.narration))
        if d.submitted_at:
            events.append(dict(at=d.submitted_at.isoformat() + "Z", who=d.created_by_name, action="submitted for approval", detail=None))
        if d.decided_at:
            events.append(dict(at=d.decided_at.isoformat() + "Z", who=d.decided_by_name, action="approved and posted", detail=None))
    for a in q:
        events.append(dict(at=a.occurred_at.isoformat() + "Z", who=a.username, action=a.action.replace("ledger.", "").replace(".", " "), detail=json.dumps(a.detail) if a.detail else None))
    for x in db.query(m.Journal).filter(m.Journal.org_id == org.id, m.Journal.reversal_of_id == j.id):
        events.append(dict(at=(x.created_at.isoformat() + "Z") if x.created_at else None, who=None,
                           action="auto-reversal scheduled" if x.source_type == "auto_reversal" and x.journal_date > date.today() else "reversed",
                           detail=f"Journal {x.journal_no} dated {x.journal_date.isoformat()}"))
    events.sort(key=lambda e: e["at"] or "")
    return dict(journal_id=j.id, journal_no=j.journal_no, events=events)


def journal_sources(db, org):
    rows = db.query(m.Journal.source_type, func.count()).filter(m.Journal.org_id == org.id).group_by(m.Journal.source_type).order_by(func.count().desc()).all()
    nice = {"manual": "Manual journals", "bank_txn": "Bank sync", "bank_line": "Bank reconciliation", "reversal": "Reversals", "auto_reversal": "Auto-reversals", "opening_balance": "Opening balances",
            "doc_invoice": "Sales invoices", "doc_credit_note": "Credit notes", "doc_bill": "Purchase bills", "doc_supplier_credit": "Supplier credits", "payment": "Payments",
            "payroll_run": "Payroll runs", "payg_remittance": "PAYG remittances", "super_payment": "Superannuation payments", "bas_payment": "BAS payments",
            "asset_depreciation": "Depreciation", "asset_disposal": "Asset disposals", "expense_claim": "Expense claims", "expense_payment": "Expense reimbursements",
            "inventory_buy": "Stock purchases", "inventory_sell": "Stock sales", "inventory_adjustment": "Stock adjustments", "inventory_opening": "Opening stock",
            "loan_repayment": "Loan repayments", "repeating": "Repeating journals"}
    return [dict(source=s, label=nice.get(s, s.replace("_", " ").capitalize()), count=n) for s, n in rows]


# ------------------------------------------------------------------------------------------------ detailed general ledger --
def general_ledger_detail(db, org, date_from, date_to, *, account_ids=None, contact=None, tracking_option_ids=None, source_type=None, group_by="account",
                          consolidate=False, q=None, min_amount=None, max_amount=None, include_reversed=True, limit=5000):
    if date_from > date_to:
        raise BooksError("The 'from' date is after the 'to' date")
    if group_by not in ("account", "voucher", "party", "tracking", "source", "month", "none"):
        raise BooksError("group_by must be account, voucher, party, tracking, source, month or none")
    accs = _names(db, org)
    topts = {o.id: (o.name, o.category.name) for o in db.query(m.TrackingOption).join(m.TrackingCategory).filter(m.TrackingCategory.org_id == org.id)}
    qry = db.query(m.JournalLine, m.Journal).join(m.Journal, m.Journal.id == m.JournalLine.journal_id).filter(m.JournalLine.org_id == org.id, m.Journal.journal_date.between(date_from, date_to))
    if account_ids:
        qry = qry.filter(m.JournalLine.account_id.in_([int(a) for a in account_ids]))
    if contact:
        qry = qry.filter(func.lower(m.JournalLine.contact_name).like(f"%{contact.strip().lower()}%"))
    if source_type:
        qry = qry.filter(m.Journal.source_type == source_type)
    if not include_reversed:
        qry = qry.filter(m.Journal.status == "posted", m.Journal.reversal_of_id.is_(None))
    if q:
        like = f"%{q.strip().lower()}%"
        qry = qry.filter(or_(func.lower(func.coalesce(m.JournalLine.description, "")).like(like), func.lower(func.coalesce(m.Journal.narration, "")).like(like),
                             func.lower(func.coalesce(m.Journal.reference, "")).like(like), func.lower(func.coalesce(m.JournalLine.contact_name, "")).like(like)))
    if min_amount is not None:
        qry = qry.filter((m.JournalLine.debit + m.JournalLine.credit) >= Decimal(str(min_amount)))
    if max_amount is not None:
        qry = qry.filter((m.JournalLine.debit + m.JournalLine.credit) <= Decimal(str(max_amount)))
    want_t = {int(t) for t in (tracking_option_ids or [])}
    qry = qry.order_by(m.Journal.journal_date, m.Journal.journal_no, m.JournalLine.line_no)
    total_lines = qry.count() if not want_t else None
    if total_lines is not None and total_lines > limit:
        truncated_rows = qry.limit(limit).all()
    else:
        truncated_rows = None
    pairs = truncated_rows if truncated_rows is not None else qry.all()
    rows = []
    for jl, j in pairs:
        opts = [int(x) for x in (jl.tracking_option_ids or [])]
        if want_t and not (want_t & set(opts)):
            continue
        a = accs[jl.account_id]
        rows.append(dict(_dr=jl.debit, _cr=jl.credit, date=j.journal_date, journal_id=j.id, journal_no=j.journal_no, account_id=a.id, account_code=a.code, account_name=a.name, cls=a.account_class,
                         description=jl.description or j.narration, narration=j.narration, reference=j.reference, contact=jl.contact_name, source_type=j.source_type, status=j.status,
                         tax_code=jl.tax_code.code if jl.tax_code else None, tax_amount=jl.tax_amount, currency=j.currency, rate=j.exchange_rate, od=jl.orig_debit, oc=jl.orig_credit, tracking=[topts[o][0] for o in opts if o in topts], tracking_ids=opts))
    truncated = truncated_rows is not None and total_lines > limit
    # only the plain per-account view can carry a true opening balance; any other filter makes "opening" meaningless
    plain = not (contact or want_t or source_type or q or min_amount is not None or max_amount is not None)
    opening = {}
    if group_by == "account" and plain:
        fy = L._fy_start(org, date_from)
        bs_open = L._sums(db, org, date_to=date_from - timedelta(days=1))
        pl_open = L._sums(db, org, date_from=fy, date_to=date_from - timedelta(days=1)) if fy < date_from else {}
        for aid in ({r["account_id"] for r in rows} | (set(int(a) for a in account_ids) if account_ids else set())):
            a = accs[aid]
            dr, cr = (pl_open if a.account_class in ("revenue", "expense") else bs_open).get(aid, (Z, Z))
            opening[aid] = (dr - cr) if a.account_class in ("asset", "expense") else (cr - dr)
    groups = {}
    order = []

    def key_of(r):
        if group_by == "account":
            return [(r["account_id"], f"{r['account_code']} · {r['account_name']}")]
        if group_by == "voucher":
            return [(r["journal_id"], f"Journal {r['journal_no']} · {r['date'].isoformat()} · {r['narration'] or ''}")]
        if group_by == "party":
            return [(r["contact"] or "", r["contact"] or "(no party)")]
        if group_by == "tracking":
            return [(o, topts[o][0]) for o in r["tracking_ids"] if o in topts] or [(0, "(no tracking)")]
        if group_by == "source":
            return [(r["source_type"], r["source_type"].replace("_", " "))]
        if group_by == "month":
            return [(r["date"].strftime("%Y-%m"), r["date"].strftime("%B %Y"))]
        return [("all", "All transactions")]
    for r in rows:
        for k, label in key_of(r):
            if k not in groups:
                groups[k] = dict(key=str(k), label=label, rows=[], account_id=r["account_id"] if group_by == "account" else None)
                order.append(k)
            groups[k]["rows"].append(r)
    out_groups = []
    tot_dr = tot_cr = Z
    for k in order:
        g = groups[k]
        items = g["rows"]
        if consolidate and group_by != "account":
            merged = {}
            for r in items:
                mk = (r["journal_id"], r["account_id"])
                if mk in merged:
                    merged[mk]["_dr"] += r["_dr"]
                    merged[mk]["_cr"] += r["_cr"]
                else:
                    merged[mk] = dict(r)
            items = list(merged.values())
        acc = accs.get(g["account_id"]) if g["account_id"] else None
        debit_normal = acc is None or acc.account_class in ("asset", "expense")
        bal = opening.get(g["account_id"], Z) if group_by == "account" else Z
        open_bal = bal
        gd = gc = Z
        rr = []
        for r in items:
            gd += r["_dr"]
            gc += r["_cr"]
            bal += (r["_dr"] - r["_cr"]) if debit_normal else (r["_cr"] - r["_dr"])
            rr.append(dict(date=r["date"].isoformat(), journal_id=r["journal_id"], journal_no=r["journal_no"], account=f"{r['account_code']} {r['account_name']}", account_id=r["account_id"],
                           description=r["description"], reference=r["reference"], contact=r["contact"], source_type=r["source_type"], status=r["status"], tax_code=r["tax_code"],
                           tax_amount=_s(r["tax_amount"]), tracking=r["tracking"],
                           original=(f"{r['currency']} {_s(r['od'] if r['od'] else r['oc'])} @ {r['rate']}" if r.get("currency") else None), debit=_s(r["_dr"]), credit=_s(r["_cr"]), balance=_s(bal)))
        out_groups.append(dict(key=g["key"], label=g["label"], account_id=g["account_id"], opening=_s(open_bal) if group_by == "account" and plain else None, debit=_s(gd), credit=_s(gc),
                               net=_s(gd - gc), closing=_s(bal) if group_by == "account" else None, count=len(rr), rows=rr))
    for r in rows:
        tot_dr += r["_dr"]
        tot_cr += r["_cr"]
    if group_by == "account" and account_ids and plain:
        present = {g["account_id"] for g in out_groups}
        for aid in [int(a) for a in account_ids if int(a) not in present]:
            a = accs[aid]
            out_groups.append(dict(key=str(aid), label=f"{a.code} · {a.name}", account_id=aid, opening=_s(opening.get(aid, Z)), debit="0.00", credit="0.00", net="0.00",
                                   closing=_s(opening.get(aid, Z)), count=0, rows=[]))
    return dict(date_from=date_from.isoformat(), date_to=date_to.isoformat(), group_by=group_by, consolidate=consolidate, groups=out_groups, group_count=len(out_groups),
                line_count=len(rows), total_debit=_s(tot_dr), total_credit=_s(tot_cr), balanced=(tot_dr == tot_cr) if not (account_ids or contact or want_t or q) else None,
                opening_applies=(group_by == "account" and plain), truncated=truncated, limit=limit,
                note=("Balances shown are running balances within each group." if group_by != "account" else
                      "Opening balances are shown when only accounts and dates are filtered; with other filters the balance starts at zero within the filtered lines.")
                + (" A line with several tracking options appears under each of them, so group totals can add up to more than the ledger total." if group_by == "tracking" else ""))


# ------------------------------------------------------------------------------------------------ health --
def ledger_health(db, org, today=None):
    today = today or date.today()
    fy = L._fy_start(org, today)
    d = {f"{k}:{s}": n for k, s, n in db.query(JournalDraft.kind, JournalDraft.status, func.count()).filter(JournalDraft.org_id == org.id).group_by(JournalDraft.kind, JournalDraft.status)}
    tot = lambda pred: sum(n for k, n in d.items() if pred(*k.split(":")))
    susp = db.query(m.LedgerAccount).filter_by(org_id=org.id, system_key="suspense").first()
    susp_bal = Z
    if susp:
        r = db.query(func.coalesce(func.sum(m.JournalLine.credit - m.JournalLine.debit), 0)).join(m.Journal, m.Journal.id == m.JournalLine.journal_id) \
            .filter(m.JournalLine.org_id == org.id, m.JournalLine.account_id == susp.id, m.Journal.journal_date <= today).scalar()
        susp_bal = money(r)
    jq = db.query(func.count(m.Journal.id)).filter(m.Journal.org_id == org.id)
    manual_fy = jq.filter(m.Journal.source_type == "manual", m.Journal.journal_date >= fy, m.Journal.journal_date <= today).scalar()
    future = jq.filter(m.Journal.journal_date > today).scalar()
    unrec = db.query(func.count(b.BankLine.id)).filter_by(org_id=org.id, status="unreconciled").scalar()
    due = db.query(func.count(RepeatingJournal.id)).filter(RepeatingJournal.org_id == org.id, RepeatingJournal.is_active.is_(True), RepeatingJournal.next_date <= today).scalar()
    last = db.query(func.max(m.Journal.journal_date)).filter(m.Journal.org_id == org.id, m.Journal.journal_date <= today).scalar()
    return dict(as_at=today.isoformat(), drafts=tot(lambda k, s: s == "draft" and k != "ai_bank"), awaiting_approval=tot(lambda k, s: s == "submitted" and k != "ai_bank"),
                ai_suggestions=tot(lambda k, s: k == "ai_bank" and s == "submitted"), rejected=tot(lambda k, s: s == "rejected"), suspense_balance=_s(susp_bal),
                future_dated=future, manual_journals_this_fy=manual_fy, unreconciled_bank_lines=unrec, repeating_due=due, lock_date=org.lock_date.isoformat() if org.lock_date else None,
                last_journal_date=last.isoformat() if last else None, require_approval=get_settings(db, org)["require_journal_approval"])


# ------------------------------------------------------------------------------------------------ P&L by tracking option --
_PL_SECTIONS = (("revenue", "Income"), ("direct_costs", "Cost of sales"), ("expense", "Operating expenses"), ("other_income", "Other income"), ("other_expense", "Other expenses"))


def profit_loss_by_tracking(db, org, date_from, date_to, category_id):
    """Profit & loss with one column per option of a tracking category (plus 'Unassigned') and a total. A line tagged with several options of the SAME
    category is shared equally between them; the columns always add up to the ordinary Profit & Loss (checked and reported)."""
    if date_from > date_to:
        raise BooksError("The 'from' date is after the 'to' date")
    cat = db.query(m.TrackingCategory).filter_by(org_id=org.id, id=category_id).one_or_none()
    if cat is None:
        raise BooksError("Tracking category not found", 404)
    opts = sorted([(o.id, o.name) for o in cat.options], key=lambda x: x[1].lower())
    ids = {i for i, _ in opts}
    cols = [dict(key=str(i), name=n) for i, n in opts] + [dict(key="none", name="Unassigned")]
    accs = _names(db, org)
    pl_ids = [a.id for a in accs.values() if a.account_class in ("revenue", "expense")]
    data = defaultdict(lambda: defaultdict(lambda: Z))
    if pl_ids:
        q = db.query(m.JournalLine, m.Journal).join(m.Journal, m.Journal.id == m.JournalLine.journal_id).filter(
            m.JournalLine.org_id == org.id, m.JournalLine.account_id.in_(pl_ids), m.Journal.journal_date.between(date_from, date_to))
        for jl, j in q:
            a = accs[jl.account_id]
            amt = (jl.credit - jl.debit) if a.account_class == "revenue" else (jl.debit - jl.credit)
            mine = [int(o) for o in (jl.tracking_option_ids or []) if int(o) in ids]
            if not mine:
                data[a.id]["none"] += amt
            elif len(mine) == 1:
                data[a.id][str(mine[0])] += amt
            else:
                share = (amt / len(mine)).quantize(Decimal("0.01"), rounding="ROUND_DOWN")
                for k, o in enumerate(mine):
                    data[a.id][str(o)] += share if k else amt - share * (len(mine) - 1)
    keys = [c["key"] for c in cols]
    sections, tot = [], {t: defaultdict(lambda: Z) for t, _ in _PL_SECTIONS}
    for t, label in _PL_SECTIONS:
        rows = []
        for a in sorted((x for x in accs.values() if x.account_type == t and x.id in data), key=lambda x: x.code):
            per = {k: data[a.id].get(k, Z) for k in keys}
            if all(v == 0 for v in per.values()):
                continue
            rows.append(dict(account_id=a.id, code=a.code, name=a.name, amounts={k: _s(v) for k, v in per.items()}, total=_s(sum(per.values(), Z))))
            for k in keys:
                tot[t][k] += per[k]
        sections.append(dict(key=t, label=label, rows=rows, totals={**{k: _s(tot[t][k]) for k in keys}, "total": _s(sum((tot[t][k] for k in keys), Z))}))
    g = lambda t, k: tot[t][k]
    def line(fn):
        v = {k: fn(k) for k in keys}
        return {**{k: _s(x) for k, x in v.items()}, "total": _s(sum(v.values(), Z))}
    gross = line(lambda k: g("revenue", k) - g("direct_costs", k))
    operating = line(lambda k: g("revenue", k) - g("direct_costs", k) - g("expense", k))
    net = line(lambda k: g("revenue", k) - g("direct_costs", k) - g("expense", k) + g("other_income", k) - g("other_expense", k))
    plain = L.profit_and_loss(db, org, date_from, date_to)
    return dict(**{"from": date_from.isoformat(), "to": date_to.isoformat()}, category=dict(id=cat.id, name=cat.name), columns=cols, sections=sections, gross_profit=gross,
                operating_profit=operating, net_profit=net, profit_loss_net=plain["net_profit"], matches_profit_loss=(net["total"] == plain["net_profit"]))
