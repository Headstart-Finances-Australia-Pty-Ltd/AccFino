"""Division 7A loans register, repayments, minimum-yearly-repayment schedule and shortfall flags, with reconciliation to a ledger loan account."""
from datetime import date
from typing import Optional

import accfino.modules.accounting.public as accounting
from accfino.modules.taxation.engine import div7a as E, rules as R
from accfino.modules.taxation.engine.money import ZERO, D, q2
from accfino.modules.taxation.models import tax as T
from accfino.modules.taxation.services import core
from accfino.modules.taxation.services.core import NotFound, TaxError


def l_dict(l: T.TaxDiv7aLoan) -> dict:
    return dict(id=l.id, borrower=l.borrower, advance_date=l.advance_date.isoformat(), principal=str(l.principal), term_years=l.term_years, secured=l.secured, status=l.status,
                agreement_date=core.plain(l.agreement_date), ledger_account_id=l.ledger_account_id, notes=l.notes)


def loans(db, ctx):
    return [l_dict(l) for l in db.query(T.TaxDiv7aLoan).filter_by(org_id=ctx.org.id).order_by(T.TaxDiv7aLoan.advance_date, T.TaxDiv7aLoan.id)]


def _get(db, ctx, lid):
    l = db.query(T.TaxDiv7aLoan).filter_by(org_id=ctx.org.id, id=lid).first()
    if l is None:
        raise NotFound("Division 7A loan")
    return l


def save_loan(db, ctx, a: core.Access, body: dict, lid: Optional[int] = None) -> T.TaxDiv7aLoan:
    a.require("prepare")
    if not (body.get("borrower") or "").strip():
        raise TaxError("borrower is required")
    adv = core.parse_date(body.get("advance_date"), "advance_date")
    if adv is None:
        raise TaxError("advance_date is required")
    principal = core.money_in(body.get("principal"), "principal", required=True)
    if principal <= 0:
        raise TaxError("principal must be greater than zero")
    term, secured = int(body.get("term_years") or 7), bool(body.get("secured"))
    if term < 1 or term > 25:
        raise TaxError("term_years must be between 1 and 25")
    if term > 7 and not secured:
        raise TaxError("An unsecured loan cannot exceed 7 years; a loan of up to 25 years must be secured by a registered mortgage over real property.")
    l = _get(db, ctx, lid) if lid else T.TaxDiv7aLoan(org_id=ctx.org.id, created_by=ctx.user_id)
    before = l_dict(l) if lid else None
    l.borrower, l.advance_date, l.principal, l.term_years, l.secured = body["borrower"].strip()[:200], adv, principal, term, secured
    l.agreement_date = core.parse_date(body.get("agreement_date"), "agreement_date")
    l.ledger_account_id, l.notes = body.get("ledger_account_id") or None, (body.get("notes") or "")[:500] or None
    if body.get("status") in ("active", "repaid", "deemed_dividend"):
        l.status = body["status"]
    if not lid:
        db.add(l)
    db.flush()
    core.record(db, ctx, "div7a.loan.save", "tax_div7a_loan", l.id, f"Division 7A loan to {l.borrower} {principal} saved", before, l_dict(l))
    return l


def delete_loan(db, ctx, a: core.Access, lid: int):
    a.require("prepare")
    l = _get(db, ctx, lid)
    core.record(db, ctx, "div7a.loan.delete", "tax_div7a_loan", l.id, f"Loan to {l.borrower} deleted", l_dict(l), None)
    db.delete(l)


def add_payment(db, ctx, a: core.Access, lid: int, body: dict) -> T.TaxDiv7aPayment:
    a.require("prepare")
    l = _get(db, ctx, lid)
    on, amt = core.parse_date(body.get("paid_on"), "paid_on"), core.money_in(body.get("amount"), "amount", required=True)
    if on is None or amt <= 0:
        raise TaxError("paid_on and a positive amount are required")
    if on < l.advance_date:
        raise TaxError("A payment cannot be dated before the loan was advanced")
    kind = body.get("kind") or "repayment"
    if kind not in ("repayment", "interest"):
        raise TaxError("kind must be repayment or interest")
    p = T.TaxDiv7aPayment(org_id=ctx.org.id, loan_id=l.id, paid_on=on, amount=amt, kind=kind, note=(body.get("note") or "")[:300] or None)
    db.add(p)
    db.flush()
    core.record(db, ctx, "div7a.payment.add", "tax_div7a_payment", p.id, f"{kind} of {amt} on {on} for loan to {l.borrower}", None, dict(amount=str(amt)))
    return p


def payments(db, ctx, lid: int):
    _get(db, ctx, lid)
    return [dict(id=p.id, paid_on=p.paid_on.isoformat(), amount=str(p.amount), kind=p.kind, note=p.note) for p in db.query(T.TaxDiv7aPayment).filter_by(org_id=ctx.org.id, loan_id=lid).order_by(T.TaxDiv7aPayment.paid_on)]


def delete_payment(db, ctx, a: core.Access, lid: int, pid: int):
    a.require("prepare")
    p = db.query(T.TaxDiv7aPayment).filter_by(org_id=ctx.org.id, loan_id=lid, id=pid).first()
    if p is None:
        raise NotFound("Payment")
    core.record(db, ctx, "div7a.payment.delete", "tax_div7a_payment", p.id, "Payment deleted", dict(amount=str(p.amount)), None)
    db.delete(p)


def schedule(db, ctx, lid: int, through_fy: Optional[str] = None) -> dict:
    l = _get(db, ctx, lid)
    fo = ctx.org.fy_end_month or 6
    fy_of = lambda d: R.fy_of(d, fo)
    through = through_fy or fy_of(date.today())
    core.check_fy(ctx, through)
    book = R.rulebook()
    bench = dict(book.div7a_history)
    for rs in book.sets:                                                             # the rule set's own rate wins for its year
        v = rs.dec("div7a.benchmark_rate")
        if v is not None:
            bench[rs.id] = v
    pays, ints = {}, {}
    for p in db.query(T.TaxDiv7aPayment).filter_by(org_id=ctx.org.id, loan_id=lid):
        tgt = pays if p.kind == "repayment" else ints
        tgt[fy_of(p.paid_on)] = tgt.get(fy_of(p.paid_on), ZERO) + p.amount
    res = E.schedule(advance_date=l.advance_date, principal=l.principal, term_years=l.term_years, benchmark_by_fy=bench, repayments_by_fy=pays, fy_of=fy_of, through_fy=through,
                     agreement_date=l.agreement_date, interest_charged_by_fy=ints)
    res["loan"] = l_dict(l)
    if l.ledger_account_id:
        bal = accounting.account_balance(db, ctx.org, l.ledger_account_id, date.today())
        res["ledger_balance"] = bal
        if bal is not None and D(bal) != D(res["closing_balance"]):
            res["flags"].append(dict(severity="warn", message=f"The linked ledger account balance (${D(bal):,.2f}) differs from the Division 7A schedule closing balance (${D(res['closing_balance']):,.2f}). Reconcile interest and repayments."))
    res["shortfall_total"] = str(q2(sum((D(r["shortfall"]) for r in res["rows"]), ZERO)))
    return res
