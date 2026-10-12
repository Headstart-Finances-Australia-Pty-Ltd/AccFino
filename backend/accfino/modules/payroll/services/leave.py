"""Leave: balances (a ledger of accruals / leave taken), requests, approval, cancellation, manual adjustments and the liability valuation."""
from collections import defaultdict
from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import Dict, Optional

from sqlalchemy import func

from accfino.modules.payroll.models.payroll import PayEmployee, PayLeaveRequest, PayLeaveTxn, PayLeaveType
from accfino.modules.payroll.services import audit, notify
from accfino.modules.payroll.services.employees import _date, _dec, display_name, get_employee
from accfino.modules.payroll.services.errors import Conflict, Forbidden, NotFound, PayrollError

DAYS = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")
Z = Decimal(0)


def daily_hours(e: PayEmployee, start: date, end: date) -> Dict[date, Decimal]:
    """Scheduled hours per day between start and end inclusive (work pattern, else hours_per_week over Mon-Fri). Days outside employment are zero."""
    pat = e.work_pattern or {}
    default = (Decimal(e.hours_per_week) / 5).quantize(Decimal("0.0001"))
    out, d = {}, start
    while d <= end:
        key = DAYS[d.weekday()]
        h = Decimal(str(pat[key])) if pat else (default if d.weekday() < 5 else Z)
        if d < e.start_date or (e.end_date and d > e.end_date):
            h = Z
        out[d] = h
        d += timedelta(days=1)
    return out


def balances(db, org_id: int, employee_id: int, as_at: Optional[date] = None) -> Dict[int, Decimal]:
    q = db.query(PayLeaveTxn.leave_type_id, func.coalesce(func.sum(PayLeaveTxn.hours), 0)).filter(PayLeaveTxn.org_id == org_id, PayLeaveTxn.employee_id == employee_id)
    if as_at:
        q = q.filter(PayLeaveTxn.txn_date <= as_at)
    return {lt: Decimal(str(h)) for lt, h in q.group_by(PayLeaveTxn.leave_type_id)}


def committed_hours(db, org_id: int, employee_id: int, leave_type_id: int, exclude_request: Optional[int] = None) -> Decimal:
    """Hours in pending or approved-but-not-yet-paid requests (they will draw on the balance)."""
    q = db.query(func.coalesce(func.sum(PayLeaveRequest.hours), 0)).filter(
        PayLeaveRequest.org_id == org_id, PayLeaveRequest.employee_id == employee_id, PayLeaveRequest.leave_type_id == leave_type_id,
        PayLeaveRequest.status.in_(("pending", "approved")), PayLeaveRequest.paid_run_id.is_(None))
    if exclude_request:
        q = q.filter(PayLeaveRequest.id != exclude_request)
    return Decimal(str(q.scalar()))


def service_years(e: PayEmployee, on: date) -> Decimal:
    return Decimal((on - e.start_date).days) / Decimal("365.25")


def ser_request(r: PayLeaveRequest, e: PayEmployee, lt: PayLeaveType) -> dict:
    return {"id": r.id, "employee_id": e.id, "employee": display_name(e), "employee_number": e.employee_number, "leave_type_id": lt.id, "leave_type": lt.name,
            "leave_code": lt.code, "start_date": r.start_date.isoformat(), "end_date": r.end_date.isoformat(), "hours": str(r.hours), "reason": r.reason,
            "status": r.status, "decided_at": r.decided_at.isoformat() if r.decided_at else None, "decision_note": r.decision_note,
            "paid": r.paid_run_id is not None, "paid_run_id": r.paid_run_id, "created_at": r.created_at.isoformat() if r.created_at else None}


def request_leave(db, ctx, access, body: dict) -> PayLeaveRequest:
    emp_id = body.get("employee_id") or (access.employee.id if access.employee else None)
    if not emp_id:
        raise PayrollError("Choose the employee the leave is for")
    if not access.can_act_on("leave_manage", int(emp_id)):
        raise Forbidden("You can only request leave for yourself")
    e = get_employee(db, ctx.org.id, int(emp_id))
    if e.status != "active":
        raise PayrollError("Leave can only be requested for an active employee")
    lt = db.query(PayLeaveType).filter_by(id=body.get("leave_type_id"), org_id=ctx.org.id, is_active=True).first()
    if lt is None:
        raise PayrollError("Leave type not found (or inactive)")
    start, end = _date(body.get("start_date"), "Start date", True), _date(body.get("end_date"), "End date", True)
    if end < start:
        raise PayrollError("End date cannot be before the start date")
    if (end - start).days > 366:
        raise PayrollError("A leave request cannot span more than a year")
    if start < e.start_date:
        raise PayrollError("Leave cannot start before the employee's start date")
    if lt.applies_to and e.employment_type not in lt.applies_to and lt.accrual_method != "none":
        raise PayrollError(f"{lt.name} does not apply to {e.employment_type.replace('_', ' ')} employees")
    sched = daily_hours(e, start, end)
    scheduled = sum(sched.values(), Z)
    hours = _dec(body.get("hours"), "Hours", min_=Decimal("0.01"), max_=Decimal(2000)) or scheduled
    if hours <= 0:
        raise PayrollError("There are no scheduled working hours between those dates: nothing to take leave against")
    if scheduled and hours > scheduled:
        raise PayrollError(f"Requested hours ({hours}) exceed the scheduled hours in that period ({scheduled})")
    clash = db.query(PayLeaveRequest).filter(PayLeaveRequest.org_id == ctx.org.id, PayLeaveRequest.employee_id == e.id,
                                             PayLeaveRequest.status.in_(("pending", "approved")), PayLeaveRequest.start_date <= end,
                                             PayLeaveRequest.end_date >= start).first()
    if clash:
        raise Conflict(f"This overlaps an existing {clash.status} leave request ({clash.start_date.isoformat()} to {clash.end_date.isoformat()})")
    _check_balance(db, ctx, e, lt, hours, start)
    r = PayLeaveRequest(org_id=ctx.org.id, employee_id=e.id, leave_type_id=lt.id, start_date=start, end_date=end, hours=hours,
                        reason=(body.get("reason") or "")[:300] or None, status="pending", requested_by=ctx.user_id)
    db.add(r)
    db.flush()
    audit.record(db, ctx, "leave.request", "leave_request", r.id, f"{e.employee_number} {display_name(e)}", f"{lt.name} {start.isoformat()} to {end.isoformat()} ({hours}h)",
                 after={"leave_type": lt.code, "hours": hours})
    notify.queue(db, ctx, notify.approver_user_ids(db, ctx.org.id, e), "leave_requested", f"Leave to approve: {display_name(e)}",
                 f"{display_name(e)} requested {lt.name}, {start.isoformat()} to {end.isoformat()} ({hours} h)." + (f" Reason: {r.reason}" if r.reason else ""),
                 "leave_request", r.id, "timeleave", "leave")
    return r


def _check_balance(db, ctx, e, lt, hours, start, exclude=None):
    if lt.category == "long_service" and lt.min_service_years and service_years(e, start) < lt.min_service_years:
        raise PayrollError(f"Long service leave needs {lt.min_service_years} years of service (this employee has {service_years(e, start):.1f})")
    if lt.allow_negative or not lt.is_paid and lt.accrual_method == "none":
        return
    avail = balances(db, ctx.org.id, e.id).get(lt.id, Z) - committed_hours(db, ctx.org.id, e.id, lt.id, exclude)
    if hours > avail:
        raise PayrollError(f"Insufficient {lt.name} balance: {avail.quantize(Decimal('0.01'))} hours available (after other pending/approved requests), {hours} requested")


def decide(db, ctx, access, req_id: int, approve: bool, note: str = "") -> PayLeaveRequest:
    r = db.query(PayLeaveRequest).filter_by(id=req_id, org_id=ctx.org.id).first()
    if r is None:
        raise NotFound("Leave request")
    if not access.can_act_on("leave_approve", r.employee_id, include_self=False):
        raise Forbidden("You cannot approve or reject this leave request (you cannot decide your own, and managers decide only their direct reports)")
    if r.status != "pending":
        raise Conflict(f"This request is already {r.status}")
    e, lt = db.get(PayEmployee, r.employee_id), db.get(PayLeaveType, r.leave_type_id)
    if approve:
        _check_balance(db, ctx, e, lt, r.hours, r.start_date, exclude=r.id)
    elif not note.strip():
        raise PayrollError("Give a reason when rejecting leave")
    r.status, r.decided_by, r.decided_at, r.decision_note = ("approved" if approve else "rejected"), ctx.user_id, datetime.utcnow(), (note or "")[:300] or None
    audit.record(db, ctx, "leave.approve" if approve else "leave.reject", "leave_request", r.id, f"{e.employee_number} {display_name(e)}",
                 f"{lt.name} {r.start_date.isoformat()} to {r.end_date.isoformat()} {r.status}", after={"status": r.status, "note": note})
    db.flush()                                    # sessions run with autoflush off: make the new status visible to the next query
    notify.queue(db, ctx, [e.user_id], f"leave_{r.status}", f"Your {lt.name} request was {r.status}",
                 f"{r.start_date.isoformat()} to {r.end_date.isoformat()}." + (f" Note: {r.decision_note}" if r.decision_note else ""), "leave_request", r.id, "mypay", "")
    return r


def cancel(db, ctx, access, req_id: int) -> PayLeaveRequest:
    r = db.query(PayLeaveRequest).filter_by(id=req_id, org_id=ctx.org.id).first()
    if r is None:
        raise NotFound("Leave request")
    if not access.can_act_on("leave_manage", r.employee_id):
        raise Forbidden("You can only cancel your own leave requests")
    if r.status in ("rejected", "cancelled"):
        raise Conflict(f"This request is already {r.status}")
    if r.paid_run_id is not None:
        raise Conflict("This leave has already been paid in a pay run. Reverse that pay run to cancel it.")
    taken = db.query(func.count(PayLeaveTxn.id)).filter(PayLeaveTxn.leave_request_id == r.id).scalar()
    if taken:
        raise Conflict("Part of this leave has already been paid in a pay run: it can no longer be cancelled")
    e = db.get(PayEmployee, r.employee_id)
    before = r.status
    r.status = "cancelled"
    audit.record(db, ctx, "leave.cancel", "leave_request", r.id, f"{e.employee_number} {display_name(e)}", "Leave request cancelled", before={"status": before}, after={"status": "cancelled"})
    db.flush()
    return r


def list_requests(db, ctx, access, *, status: str = "", employee_id: int = 0, mine: bool = False, limit: int = 200) -> list:
    q = db.query(PayLeaveRequest, PayEmployee, PayLeaveType).join(PayEmployee, PayEmployee.id == PayLeaveRequest.employee_id) \
        .join(PayLeaveType, PayLeaveType.id == PayLeaveRequest.leave_type_id).filter(PayLeaveRequest.org_id == ctx.org.id)
    sc = access.scope("leave_manage") if mine else access.scope("leave_approve")
    if mine:
        sc = {access.employee.id} if access.employee else set()
    if sc is not None:
        q = q.filter(PayLeaveRequest.employee_id.in_(sc or {-1}))
    if status:
        q = q.filter(PayLeaveRequest.status == status)
    if employee_id:
        q = q.filter(PayLeaveRequest.employee_id == employee_id)
    out = []
    for r, e, lt in q.order_by(PayLeaveRequest.start_date.desc()).limit(limit):
        row = ser_request(r, e, lt)
        row["can_decide"] = r.status == "pending" and access.can_act_on("leave_approve", r.employee_id, include_self=False)     # the UI shows Approve / Reject only when this is true
        out.append(row)
    return out


def adjust(db, ctx, access, employee_id: int, leave_type_id: int, hours, note: str, txn_type: str = "adjustment", txn_date: Optional[date] = None) -> PayLeaveTxn:
    access.require("leave_manage")
    if access.scope("leave_manage") is not None:
        raise Forbidden("Only payroll staff can adjust leave balances")
    e = get_employee(db, ctx.org.id, employee_id)
    lt = db.query(PayLeaveType).filter_by(id=leave_type_id, org_id=ctx.org.id).first()
    if lt is None:
        raise NotFound("Leave type")
    h = _dec(hours, "Hours", required=True, min_=Decimal(-5000), max_=Decimal(5000))
    if h == 0:
        raise PayrollError("Adjustment hours cannot be zero")
    if not (note or "").strip():
        raise PayrollError("A reason is required for a leave adjustment")
    if txn_type not in ("adjustment", "opening"):
        raise PayrollError("Adjustment type must be adjustment or opening")
    bal = balances(db, ctx.org.id, e.id).get(lt.id, Z)
    if bal + h < 0 and not lt.allow_negative:
        raise PayrollError(f"That would make the {lt.name} balance negative ({bal + h} hours)")
    t = PayLeaveTxn(org_id=ctx.org.id, employee_id=e.id, leave_type_id=lt.id, txn_date=txn_date or date.today(), txn_type=txn_type, hours=h, note=note[:300], created_by=ctx.user_id)
    db.add(t)
    db.flush()
    audit.record(db, ctx, "leave.adjust", "employee", e.id, f"{e.employee_number} {display_name(e)}", f"{lt.code} {h:+} hours: {note}", before={"balance": bal}, after={"balance": bal + h})
    return t


def employee_balances(db, ctx, access, employee_id: int) -> list:
    if not (access.can_act_on("employees_view", employee_id) or access.can_act_on("leave_manage", employee_id)):
        raise Forbidden("You cannot view this employee's leave")
    e = get_employee(db, ctx.org.id, employee_id)
    bal = balances(db, ctx.org.id, e.id)
    out = []
    for lt in db.query(PayLeaveType).filter_by(org_id=ctx.org.id, is_active=True).order_by(PayLeaveType.code):
        taken = db.query(func.coalesce(func.sum(-PayLeaveTxn.hours), 0)).filter(PayLeaveTxn.employee_id == e.id, PayLeaveTxn.leave_type_id == lt.id,
                                                                                PayLeaveTxn.txn_type == "taken").scalar()
        accrued = db.query(func.coalesce(func.sum(PayLeaveTxn.hours), 0)).filter(PayLeaveTxn.employee_id == e.id, PayLeaveTxn.leave_type_id == lt.id,
                                                                                 PayLeaveTxn.txn_type.in_(("accrual", "opening"))).scalar()
        pending = committed_hours(db, ctx.org.id, e.id, lt.id)
        b = bal.get(lt.id, Z)
        if b == 0 and not accrued and not taken and not pending and lt.accrual_method == "none":
            continue
        out.append({"leave_type_id": lt.id, "code": lt.code, "name": lt.name, "balance": str(b.quantize(Decimal("0.0001"))), "accrued": str(Decimal(str(accrued))),
                    "taken": str(Decimal(str(taken))), "committed": str(pending), "available": str((b - pending).quantize(Decimal("0.0001")))})
    return out


def history(db, ctx, access, employee_id: int, limit: int = 200) -> list:
    if not (access.can_act_on("employees_view", employee_id) or access.can_act_on("leave_manage", employee_id)):
        raise Forbidden("You cannot view this employee's leave")
    e = get_employee(db, ctx.org.id, employee_id)
    rows = db.query(PayLeaveTxn, PayLeaveType).join(PayLeaveType, PayLeaveType.id == PayLeaveTxn.leave_type_id).filter(PayLeaveTxn.employee_id == e.id) \
        .order_by(PayLeaveTxn.txn_date.desc(), PayLeaveTxn.id.desc()).limit(limit).all()
    return [{"id": t.id, "date": t.txn_date.isoformat(), "type": t.txn_type, "leave_type": lt.name, "code": lt.code, "hours": str(t.hours), "note": t.note,
             "pay_run_id": t.pay_run_id} for t, lt in rows]


def hours_for_period(db, org_id: int, e: PayEmployee, start: date, end: date) -> Dict[int, dict]:
    """Approved, unpaid leave falling in [start, end] -> {leave_type_id: {"hours": Decimal, "requests": [ids]}}. Uses the scheduled days in the period
    (a request spanning two pay periods is paid across them) and never pays more than the request's remaining hours."""
    out: Dict[int, dict] = {}
    reqs = db.query(PayLeaveRequest).filter(PayLeaveRequest.org_id == org_id, PayLeaveRequest.employee_id == e.id, PayLeaveRequest.status == "approved",
                                            PayLeaveRequest.paid_run_id.is_(None), PayLeaveRequest.start_date <= end, PayLeaveRequest.end_date >= start).all()
    for r in reqs:
        sched_all = daily_hours(e, r.start_date, r.end_date)
        total_sched = sum(sched_all.values(), Z)
        scale = (r.hours / total_sched) if total_sched else Z
        in_period = sum((h for d, h in sched_all.items() if start <= d <= end), Z) * scale
        taken = Decimal(str(-(db.query(func.coalesce(func.sum(PayLeaveTxn.hours), 0)).filter(PayLeaveTxn.leave_request_id == r.id,
                                                                                            PayLeaveTxn.txn_type.in_(("taken", "reversal"))).scalar() or 0)))
        h = min(in_period, max(Z, r.hours - taken)).quantize(Decimal("0.01"))
        if h > 0:
            slot = out.setdefault(r.leave_type_id, {"hours": Z, "requests": [], "detail": []})
            slot["hours"] += h
            slot["requests"].append(r.id)
            slot["detail"].append((r.id, h))
    return out


def payout_suggestion(db, ctx, access, employee_id: int) -> list:
    """Unused annual and long service leave valued at the employee's current rate: a starting point for the termination pay (the payroll manager adds it to the run)."""
    access.require("run_create")
    e = get_employee(db, ctx.org.id, employee_id)
    rate = (Decimal(e.hourly_rate) if e.pay_basis == "hourly" else Decimal(e.annual_salary or 0) / (52 * Decimal(e.hours_per_week)))
    out = []
    bal = balances(db, ctx.org.id, e.id)
    for lt in db.query(PayLeaveType).filter_by(org_id=ctx.org.id, is_active=True):
        h = bal.get(lt.id, Z)
        if lt.category in ("annual", "long_service") and h > 0:
            if lt.category == "long_service" and lt.min_service_years and service_years(e, e.end_date or date.today()) < lt.min_service_years:
                continue                                                  # not yet eligible: nothing to pay out
            out.append({"leave_type_id": lt.id, "leave_type": lt.name, "hours": str(h.quantize(Decimal("0.01"))), "hourly_rate": str(rate.quantize(Decimal("0.0001"))),
                        "amount": str((h * rate).quantize(Decimal("0.01"))), "pay_item_code": "TLEAVE"})
    return out
