"""Payroll payments: net pay split across each employee's bank accounts, a bank file (ABA/Cecil layout), and a SAFE MOCK completion.
Nothing here talks to a bank. Completing a batch records that the money was sent (and optionally posts Dr Wages Payable / Cr Bank to the ledger)."""
from datetime import date, datetime
from decimal import Decimal
from typing import Optional

import accfino.modules.accounting.public as accounting
from accfino.modules.payroll.models.payroll import PayEmployeeBank, PayPayment, PayPaymentItem, PayRun, PayRunEmployee
from accfino.modules.payroll.services import audit, protect
from accfino.modules.payroll.services.alloc import allocate_net
from accfino.modules.payroll.services.errors import Conflict, NotFound, PayrollError
from accfino.modules.payroll.services.setup import get_settings

Z = Decimal(0)


def ser(p: PayPayment, items=None) -> dict:
    out = {"id": p.id, "run_id": p.run_id, "batch_ref": p.batch_ref, "status": p.status, "method": p.method, "payment_date": p.payment_date.isoformat(), "total": str(p.total),
           "item_count": p.item_count, "completed_at": p.completed_at.isoformat() if p.completed_at else None, "cancel_reason": p.cancel_reason, "journal_id": p.journal_id}
    if items is not None:
        out["items"] = [{"id": i.id, "employee_id": i.employee_id, "account_name": i.account_name, "bsb": i.bsb, "account": protect.mask_account(i.account_last4), "amount": str(i.amount),
                         "reference": i.reference, "status": i.status, "failure_reason": i.failure_reason, "reconciliation": i.reconciliation,
                         "employee": db_name(i)} for i in items]
    return out


def db_name(i) -> str:
    return getattr(i, "_name", "")


def get_payment(db, org_id: int, pid: int, lock=False) -> PayPayment:
    q = db.query(PayPayment).filter_by(id=pid, org_id=org_id)
    p = (q.with_for_update() if lock else q).first()
    if p is None:
        raise NotFound("Payment batch")
    return p


def prepare(db, ctx, access, run_id: int, payment_date: Optional[date] = None, method: str = "mock") -> PayPayment:
    access.require("payments_manage")
    run = db.query(PayRun).filter_by(id=run_id, org_id=ctx.org.id).with_for_update().first()
    if run is None:
        raise NotFound("Pay run")
    if run.status != "finalised":
        raise Conflict(f"Payments can only be prepared for a finalised pay run (this one is {run.status})", "bad_state")
    if run.reversed_by_run_id or run.run_type == "reversal":
        raise Conflict("This pay run has been reversed: there is nothing to pay", "bad_state")
    if method not in ("mock", "aba"):
        raise PayrollError("Payment method must be mock or aba")
    live = db.query(PayPayment).filter(PayPayment.run_id == run.id, PayPayment.status.in_(("prepared", "completed"))).first()
    if live:
        raise Conflict(f"Payment batch {live.batch_ref} ({live.status}) already exists for this pay run", "duplicate_payment")
    pdate = payment_date or run.pay_date
    n = db.query(PayPayment).filter_by(run_id=run.id).count()
    batch = PayPayment(org_id=ctx.org.id, run_id=run.id, batch_ref=f"{run.run_no}-PAY" + (f"-{n + 1}" if n else ""), method=method, payment_date=pdate, status="prepared",
                       created_by=ctx.user_id)
    db.add(batch)
    db.flush()
    total, count = Z, 0
    for re_ in db.query(PayRunEmployee).filter_by(run_id=run.id, status="included").order_by(PayRunEmployee.employee_number):
        if re_.net <= 0:
            continue
        banks = db.query(PayEmployeeBank).filter_by(employee_id=re_.employee_id, is_active=True).all()
        if not banks:
            raise PayrollError(f"{re_.employee_name} has no bank account: add one before preparing payments")
        for b, amt in allocate_net(banks, re_.net):
            db.add(PayPaymentItem(org_id=ctx.org.id, payment_id=batch.id, run_employee_id=re_.id, employee_id=re_.employee_id, bank_id=b.id, account_name=b.account_name,
                                  bsb=b.bsb, account_last4=b.account_last4, amount=amt, reference=(b.reference or f"PAY {run.pay_date.strftime('%d%b')}")[:18]))
            total += amt
            count += 1
    if total != run.total_net - sum((r.net for r in db.query(PayRunEmployee).filter_by(run_id=run.id, status="included") if r.net <= 0), Z):
        raise PayrollError("Payment total does not equal the pay run's net pay: nothing was prepared")
    batch.total, batch.item_count = total, count
    if count == 0:
        raise PayrollError("There is no net pay to pay in this run")
    audit.record(db, ctx, "payment.prepare", "payment", batch.id, batch.batch_ref, f"{count} payments totalling {total} prepared ({method})", after={"total": total, "count": count})
    return batch


def aba_file(db, ctx, access, payment_id: int) -> str:
    """ABA (Cecil) bank file text. Contains full account numbers, so it needs payments_manage and every download is audited."""
    access.require("payments_manage")
    p = get_payment(db, ctx.org.id, payment_id)
    if p.status == "cancelled":
        raise Conflict("This payment batch was cancelled", "bad_state")
    cfg = get_settings(db, ctx.org).payment_config or {}
    labels = {"bsb": "company BSB", "account_enc": "company account number", "account_name": "account name", "apca_user_id": "APCA user ID", "bank_abbrev": "bank abbreviation"}
    miss = [label for k, label in labels.items() if not cfg.get(k)]
    if miss:
        raise PayrollError("The company bank details are incomplete (missing: " + ", ".join(miss) + "). Complete them in Payroll > Settings > Payments.")
    from accfino.modules.payroll.models.payroll import PayEmployeeBank
    comp_acct = protect.reveal(cfg["account_enc"]) or ""
    name = (get_settings(db, ctx.org).employer_name or ctx.org.name)
    fld = lambda v, n, right=False, pad=" ": (str(v)[:n].rjust(n, pad) if right else str(v)[:n].ljust(n, pad))
    cents = lambda d: int((Decimal(d) * 100).to_integral_value())
    lines = ["0" + " " * 17 + "01" + fld(cfg["bank_abbrev"].upper(), 3) + " " * 7 + fld(cfg.get("account_name", name), 26) + fld(cfg["apca_user_id"], 6, True, "0")
             + fld(cfg.get("description", "PAYROLL"), 12) + p.payment_date.strftime("%d%m%y") + " " * 40]
    lines[0] = lines[0].ljust(120)
    total = Z
    items = db.query(PayPaymentItem).filter_by(payment_id=p.id).order_by(PayPaymentItem.id).all()
    for i in items:
        b = db.get(PayEmployeeBank, i.bank_id)
        acct = protect.reveal(b.account_enc) if b else None
        if not acct:
            raise PayrollError(f"Bank account for {i.account_name} is unavailable: re-enter it")
        total += i.amount
        lines.append(("1" + fld(i.bsb, 7) + fld(acct, 9, True) + " " + "53" + fld(cents(i.amount), 10, True, "0") + fld(i.account_name, 32) + fld(i.reference or "", 18)
                      + fld(cfg["bsb"], 7) + fld(comp_acct, 9, True) + fld(name, 16) + "0" * 8).ljust(120))
    lines.append(("1" + fld(cfg["bsb"], 7) + fld(comp_acct, 9, True) + " " + "13" + fld(cents(total), 10, True, "0") + fld(name, 32) + fld(p.batch_ref, 18)
                  + fld(cfg["bsb"], 7) + fld(comp_acct, 9, True) + fld(name, 16) + "0" * 8).ljust(120))
    lines.append(("7" + "999-999" + " " * 12 + fld(0, 10, True, "0") + fld(cents(total), 10, True, "0") + fld(cents(total), 10, True, "0") + " " * 24 + fld(len(items) + 1, 6, True, "0")).ljust(120))
    audit.record(db, ctx, "payment.aba_download", "payment", p.id, p.batch_ref, "Bank file generated")
    return "\r\n".join(lines) + "\r\n"


def complete(db, ctx, access, payment_id: int) -> PayPayment:
    """MOCK: records that the batch was sent and the funds paid. No bank is contacted."""
    access.require("payments_manage")
    p = get_payment(db, ctx.org.id, payment_id, lock=True)
    if p.status == "completed":
        raise Conflict(f"Payment batch {p.batch_ref} is already completed", "already_completed")
    if p.status != "prepared":
        raise Conflict(f"Payment batch {p.batch_ref} is {p.status}", "bad_state")
    run = db.query(PayRun).filter_by(id=p.run_id).with_for_update().one()
    if run.status != "finalised" or run.reversed_by_run_id:
        raise Conflict(f"Pay run {run.run_no} is {run.status}{' (reversed)' if run.reversed_by_run_id else ''}: it cannot be paid", "bad_state")
    now = datetime.utcnow()
    for i in db.query(PayPaymentItem).filter_by(payment_id=p.id):
        i.status, i.paid_at = "paid", now
    p.status, p.completed_at, p.completed_by = "completed", now, ctx.user_id
    run.status, run.paid_at = "paid", now
    amap = get_settings(db, ctx.org).accounting_map or {}
    note = ""
    if amap.get("payment_bank") and amap.get("wages_payable"):
        try:
            j = accounting.post_journal(db, ctx.org, journal_date=p.payment_date, lines=[dict(account_id=amap["wages_payable"], debit=p.total, credit=0, description=f"Net pay {run.run_no}"),
                                                                                           dict(account_id=amap["payment_bank"], debit=0, credit=p.total, description=f"Net pay {run.run_no}")],
                                        narration=f"Payroll payment {p.batch_ref}", source_type="payroll_payment", source_ref=f"payment:{p.id}", created_by=ctx.user_id, reference=p.batch_ref)
        except accounting.LedgerError as e:
            raise PayrollError(f"The ledger refused the payment journal: {e}")
        p.journal_id = j.id
        note = f"; payment journal {j.journal_no} posted"
    audit.record(db, ctx, "payment.complete", "payment", p.id, p.batch_ref, f"Marked as paid: {p.total} to {p.item_count} accounts (mock, no bank contacted){note}", after={"total": p.total})
    return p


def cancel(db, ctx, access, payment_id: int, reason: str) -> PayPayment:
    access.require("payments_manage")
    p = get_payment(db, ctx.org.id, payment_id, lock=True)
    if p.status != "prepared":
        raise Conflict(f"Only a prepared batch can be cancelled (this one is {p.status})", "bad_state")
    if not (reason or "").strip():
        raise PayrollError("Give a reason for cancelling the batch")
    p.status, p.cancel_reason = "cancelled", reason[:300]
    audit.record(db, ctx, "payment.cancel", "payment", p.id, p.batch_ref, f"Cancelled: {reason}")
    return p


def set_item_status(db, ctx, access, payment_id: int, item_id: int, status: str, reason: str = "") -> PayPaymentItem:
    """After completion a payment can be returned by the bank. This records it (the pay run stays paid; follow it up)."""
    access.require("payments_manage")
    p = get_payment(db, ctx.org.id, payment_id)
    if p.status != "completed":
        raise Conflict("Only a completed batch has payments that can be returned or failed", "bad_state")
    i = db.query(PayPaymentItem).filter_by(id=item_id, payment_id=p.id).first()
    if i is None:
        raise NotFound("Payment")
    if status not in ("returned", "failed", "paid"):
        raise PayrollError("Status must be returned, failed or paid")
    if status != "paid" and not (reason or "").strip():
        raise PayrollError("Give the reason the payment was returned")
    before = i.status
    i.status, i.failure_reason = status, (reason or None)
    if status != "paid":
        i.reconciliation = "unreconciled"
    audit.record(db, ctx, "payment.item_status", "payment", p.id, p.batch_ref, f"{i.account_name}: {before} -> {status}", before={"status": before}, after={"status": status, "reason": reason})
    return i


def reconcile(db, ctx, access, payment_id: int, item_ids=None) -> int:
    access.require("payments_manage")
    p = get_payment(db, ctx.org.id, payment_id)
    if p.status != "completed":
        raise Conflict("Only a completed batch can be reconciled", "bad_state")
    q = db.query(PayPaymentItem).filter_by(payment_id=p.id, status="paid", reconciliation="unreconciled")
    if item_ids:
        q = q.filter(PayPaymentItem.id.in_(item_ids))
    n = 0
    for i in q:
        i.reconciliation, i.reconciled_at, i.reconciled_by = "reconciled", datetime.utcnow(), ctx.user_id
        n += 1
    audit.record(db, ctx, "payment.reconcile", "payment", p.id, p.batch_ref, f"{n} payments reconciled")
    return n


def list_payments(db, ctx, access, run_id: int = 0) -> list:
    if not (access.has("payments_manage") or access.has("reports_view")):
        access.require("payments_manage")
    q = db.query(PayPayment).filter_by(org_id=ctx.org.id)
    if run_id:
        q = q.filter_by(run_id=run_id)
    return [ser(p) for p in q.order_by(PayPayment.id.desc()).limit(200)]


def detail(db, ctx, access, pid: int) -> dict:
    if not (access.has("payments_manage") or access.has("reports_view")):
        access.require("payments_manage")
    p = get_payment(db, ctx.org.id, pid)
    items = db.query(PayPaymentItem).filter_by(payment_id=p.id).order_by(PayPaymentItem.id).all()
    from accfino.modules.payroll.models.payroll import PayEmployee
    names = {e.id: f"{e.employee_number} {e.first_name} {e.last_name}" for e in db.query(PayEmployee).filter(PayEmployee.id.in_({i.employee_id for i in items}))}
    for i in items:
        i._name = names.get(i.employee_id, "")
    return ser(p, items)
