"""Superannuation contributions: what is owed to each fund, when it is due (Payday Super: 7 business days after payday) and whether it has been paid."""
from datetime import date, datetime
from decimal import Decimal
from typing import Optional

from accfino.modules.payroll.models.payroll import PayEmployee, PaySuperContribution, PaySuperFund
from accfino.modules.payroll.services import audit
from accfino.modules.payroll.services.errors import Conflict, PayrollError

Z = Decimal(0)


def listing(db, ctx, access, *, status: str = "", fund_id: int = 0, date_from: Optional[date] = None, date_to: Optional[date] = None, today: Optional[date] = None, limit: int = 500) -> dict:
    access.require("reports_view")
    today = today or date.today()
    q = db.query(PaySuperContribution, PaySuperFund, PayEmployee).join(PaySuperFund, PaySuperFund.id == PaySuperContribution.fund_id) \
        .join(PayEmployee, PayEmployee.id == PaySuperContribution.employee_id).filter(PaySuperContribution.org_id == ctx.org.id)
    if status == "overdue":
        q = q.filter(PaySuperContribution.status == "pending", PaySuperContribution.due_date < today)
    elif status:
        q = q.filter(PaySuperContribution.status == status)
    if fund_id:
        q = q.filter(PaySuperContribution.fund_id == fund_id)
    if date_from:
        q = q.filter(PaySuperContribution.due_date >= date_from)
    if date_to:
        q = q.filter(PaySuperContribution.due_date <= date_to)
    rows = q.order_by(PaySuperContribution.due_date, PaySuperContribution.id).limit(limit).all()
    items = [{"id": c.id, "run_id": c.run_id, "employee_id": e.id, "employee": f"{e.first_name} {e.last_name}", "employee_number": e.employee_number, "fund_id": f.id, "fund": f.name,
              "component": c.component, "amount": str(c.amount), "due_date": c.due_date.isoformat(), "status": c.status, "overdue": c.status == "pending" and c.due_date < today,
              "paid_at": c.paid_at.isoformat() if c.paid_at else None, "payment_ref": c.payment_ref} for c, f, e in rows]
    tot = lambda pred: str(sum((Decimal(i["amount"]) for i in items if pred(i)), Z))
    return {"items": items, "totals": {"all": tot(lambda i: True), "pending": tot(lambda i: i["status"] == "pending"), "overdue": tot(lambda i: i["overdue"]), "paid": tot(lambda i: i["status"] == "paid")}}


def mark_paid(db, ctx, access, ids: list, reference: str) -> int:
    access.require("payments_manage")
    if not (reference or "").strip():
        raise PayrollError("Enter the payment reference from your clearing house or bank")
    rows = db.query(PaySuperContribution).filter(PaySuperContribution.org_id == ctx.org.id, PaySuperContribution.id.in_(ids or [-1])).all()
    if len(rows) != len(set(ids)):
        raise PayrollError("Some contributions were not found")
    bad = [r.id for r in rows if r.status != "pending"]
    if bad:
        raise Conflict(f"Contributions already paid or reversed cannot be paid again: {bad}", "bad_state")
    now = datetime.utcnow()
    for r in rows:
        r.status, r.paid_at, r.payment_ref = "paid", now, reference[:60]
    audit.record(db, ctx, "super.mark_paid", "super", None, reference, f"{len(rows)} contributions totalling {sum((r.amount for r in rows), Z)} marked paid")
    return len(rows)
