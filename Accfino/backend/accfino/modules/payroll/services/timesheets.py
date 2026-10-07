"""Timesheets for hourly employees: weekly sheets of daily lines (pay category, hours, breaks), with draft -> submitted -> approved/rejected -> processed."""
import re
from collections import defaultdict
from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import Optional

from accfino.modules.payroll.models.payroll import PayEmployee, PayItem, PayLeaveType, PayTimesheet, PayTimesheetLine
from accfino.modules.payroll.services import audit, notify
from accfino.modules.payroll.services.employees import _date, _dec, display_name, get_employee
from accfino.modules.payroll.services.errors import Conflict, Forbidden, NotFound, PayrollError

HOURLY_KINDS = {"earnings", "overtime", "penalty", "leave"}
Z = Decimal(0)


def week_bounds(d: date):
    start = d - timedelta(days=d.weekday())                    # Monday
    return start, start + timedelta(days=6)


def _hm(s) -> Optional[int]:
    if not s:
        return None
    m = re.fullmatch(r"([01]\d|2[0-3]):([0-5]\d)", str(s))
    if not m:
        raise PayrollError(f"Time '{s}' is not valid (use 24-hour HH:MM)")
    return int(m.group(1)) * 60 + int(m.group(2))


def ser(db, ts: PayTimesheet, e: PayEmployee, lines=True) -> dict:
    out = {"id": ts.id, "employee_id": e.id, "employee": display_name(e), "employee_number": e.employee_number, "week_start": ts.week_start.isoformat(),
           "week_end": ts.week_end.isoformat(), "status": ts.status, "notes": ts.notes, "reject_reason": ts.reject_reason,
           "submitted_at": ts.submitted_at.isoformat() if ts.submitted_at else None, "decided_at": ts.decided_at.isoformat() if ts.decided_at else None,
           "processed_run_id": ts.processed_run_id}
    ls = db.query(PayTimesheetLine, PayItem).join(PayItem, PayItem.id == PayTimesheetLine.pay_item_id).filter(PayTimesheetLine.timesheet_id == ts.id) \
        .order_by(PayTimesheetLine.work_date, PayTimesheetLine.id).all()
    tot = defaultdict(lambda: Z)
    for l, it in ls:
        tot["leave" if it.kind == "leave" else "overtime" if it.kind == "overtime" else "ordinary"] += l.hours
    out["totals"] = {"ordinary": str(tot["ordinary"]), "overtime": str(tot["overtime"]), "leave": str(tot["leave"]), "total": str(sum(tot.values(), Z))}
    if lines:
        out["lines"] = [{"id": l.id, "work_date": l.work_date.isoformat(), "pay_item_id": it.id, "pay_item": it.name, "pay_item_code": it.code, "kind": it.kind,
                         "leave_type_id": l.leave_type_id, "hours": str(l.hours), "break_minutes": l.break_minutes, "start_time": l.start_time, "end_time": l.end_time,
                         "notes": l.notes, "processed": l.processed_run_id is not None} for l, it in ls]
    return out


def _clean_lines(db, ctx, e: PayEmployee, week_start: date, week_end: date, raw: list) -> list:
    if not isinstance(raw, list):
        raise PayrollError("Timesheet lines must be a list")
    if len(raw) > 200:
        raise PayrollError("Too many lines on one timesheet (maximum 200)")
    out, per_day, seen = [], defaultdict(lambda: Z), set()
    for i, l in enumerate(raw, start=1):
        tag = f"Line {i}"
        d = _date(l.get("work_date"), f"{tag}: date", True)
        if not week_start <= d <= week_end:
            raise PayrollError(f"{tag}: {d.isoformat()} is outside the week {week_start.isoformat()} to {week_end.isoformat()}")
        if d < e.start_date or (e.end_date and d > e.end_date):
            raise PayrollError(f"{tag}: {d.isoformat()} is outside {display_name(e)}'s employment dates")
        it = db.query(PayItem).filter_by(id=l.get("pay_item_id"), org_id=ctx.org.id, is_active=True).first()
        if it is None or it.kind not in HOURLY_KINDS or it.calc_method != "hours_x_rate":
            raise PayrollError(f"{tag}: choose an hourly pay category (ordinary, overtime, penalty or leave)")
        lt_id = None
        if it.kind == "leave":
            lt_id = l.get("leave_type_id") or it.leave_type_id
            if not lt_id or not db.query(PayLeaveType.id).filter_by(id=lt_id, org_id=ctx.org.id).first():
                raise PayrollError(f"{tag}: choose the leave type")
        st, en, brk = _hm(l.get("start_time")), _hm(l.get("end_time")), int(_dec(l.get("break_minutes", 0), f"{tag}: break", min_=Z, max_=Decimal(720)) or 0)
        hours = _dec(l.get("hours"), f"{tag}: hours")
        if st is not None and en is not None:
            span = (en - st) - brk
            if span <= 0:
                raise PayrollError(f"{tag}: finish time must be after the start time (after breaks)")
            calc = (Decimal(span) / 60).quantize(Decimal("0.01"))
            if hours is None:
                hours = calc
            elif abs(hours - calc) > Decimal("0.01"):
                raise PayrollError(f"{tag}: hours ({hours}) do not match start, finish and breaks ({calc})")
        if hours is None or hours <= 0:
            raise PayrollError(f"{tag}: hours must be greater than zero")
        if hours > 24:
            raise PayrollError(f"{tag}: more than 24 hours in a day")
        key = (d, it.id, lt_id)
        if key in seen:
            raise PayrollError(f"{tag}: {it.name} is entered twice for {d.isoformat()}: combine the hours into one line")
        seen.add(key)
        per_day[d] += hours
        if per_day[d] > 24:
            raise PayrollError(f"{d.isoformat()}: more than 24 hours across all lines")
        out.append(dict(work_date=d, pay_item_id=it.id, leave_type_id=lt_id, hours=hours, break_minutes=brk, start_time=l.get("start_time") or None,
                        end_time=l.get("end_time") or None, notes=(l.get("notes") or "")[:300] or None))
    return out


def _visible(access, emp_id: int, cap: str) -> bool:
    return access.can_act_on(cap, emp_id)


def save(db, ctx, access, body: dict, ts_id: Optional[int] = None) -> PayTimesheet:
    ts = db.query(PayTimesheet).filter_by(id=ts_id, org_id=ctx.org.id).first() if ts_id else None
    if ts_id and ts is None:
        raise NotFound("Timesheet")
    emp_id = ts.employee_id if ts else (body.get("employee_id") or (access.employee.id if access.employee else None))
    if not emp_id:
        raise PayrollError("Choose the employee")
    if not access.can_act_on("timesheets_manage", int(emp_id)):
        raise Forbidden("You can only enter your own timesheets")
    e = get_employee(db, ctx.org.id, int(emp_id))
    if e.status == "terminated" and not e.end_date:
        raise PayrollError("Employee is terminated")
    if e.pay_basis != "hourly":
        raise PayrollError(f"{display_name(e)} is salaried: timesheets are for hourly employees (record leave through a leave request)")
    if ts is not None and ts.status not in ("draft", "rejected"):
        raise Conflict(f"This timesheet is {ts.status} and can no longer be edited")
    if ts is None:
        ws, we = week_bounds(_date(body.get("week_start"), "Week start", True))
        if db.query(PayTimesheet.id).filter_by(org_id=ctx.org.id, employee_id=e.id, week_start=ws).first():
            raise Conflict(f"A timesheet for the week starting {ws.isoformat()} already exists for {display_name(e)}")
    else:
        ws, we = ts.week_start, ts.week_end
    lines = _clean_lines(db, ctx, e, ws, we, body["lines"]) if "lines" in body else None    # validate EVERYTHING before touching the database
    if ts is None:
        ts = PayTimesheet(org_id=ctx.org.id, employee_id=e.id, week_start=ws, week_end=we, status="draft", created_by=ctx.user_id)
        db.add(ts)
        db.flush()
        action = "timesheet.create"
    else:
        action = "timesheet.update"
    if lines is not None:
        db.query(PayTimesheetLine).filter_by(timesheet_id=ts.id).delete()
        for l in lines:
            db.add(PayTimesheetLine(org_id=ctx.org.id, timesheet_id=ts.id, **l))
    if "notes" in body:
        ts.notes = (body["notes"] or "")[:1000] or None
    if ts.status == "rejected":
        ts.status, ts.reject_reason = "draft", None
    db.flush()
    audit.record(db, ctx, action, "timesheet", ts.id, f"{e.employee_number} {display_name(e)}", f"Week of {ts.week_start.isoformat()}")
    return ts


def _total(db, ts) -> Decimal:
    return sum((l.hours for l in db.query(PayTimesheetLine).filter_by(timesheet_id=ts.id)), Z)


def submit(db, ctx, access, ts_id: int) -> PayTimesheet:
    ts = _get(db, ctx, ts_id)
    if not access.can_act_on("timesheets_manage", ts.employee_id):
        raise Forbidden("You can only submit your own timesheets")
    if ts.status not in ("draft", "rejected"):
        raise Conflict(f"This timesheet is already {ts.status}")
    if _total(db, ts) <= 0:
        raise PayrollError("A timesheet needs at least one line of hours before it can be submitted")
    ts.status, ts.submitted_at, ts.submitted_by, ts.reject_reason = "submitted", datetime.utcnow(), ctx.user_id, None
    e = db.get(PayEmployee, ts.employee_id)
    audit.record(db, ctx, "timesheet.submit", "timesheet", ts.id, f"{e.employee_number} {display_name(e)}", f"Week of {ts.week_start.isoformat()} submitted")
    db.flush()
    notify.queue(db, ctx, notify.approver_user_ids(db, ctx.org.id, e), "timesheet_submitted", f"Timesheet to approve: {display_name(e)}",
                 f"{display_name(e)} submitted {_total(db, ts)} hours for the week of {ts.week_start.isoformat()}.", "timesheet", ts.id, "timeleave", "timesheets")
    return ts


def decide(db, ctx, access, ts_id: int, approve: bool, reason: str = "") -> PayTimesheet:
    ts = _get(db, ctx, ts_id)
    if not access.can_act_on("timesheets_approve", ts.employee_id, include_self=False):
        raise Forbidden("You cannot approve or reject this timesheet (managers approve their direct reports; you cannot approve your own)")
    if ts.status != "submitted":
        raise Conflict(f"Only a submitted timesheet can be approved or rejected (this one is {ts.status})")
    if not approve and not reason.strip():
        raise PayrollError("Give a reason when rejecting a timesheet")
    ts.status, ts.decided_at, ts.decided_by = ("approved" if approve else "rejected"), datetime.utcnow(), ctx.user_id
    ts.reject_reason = None if approve else reason[:300]
    e = db.get(PayEmployee, ts.employee_id)
    audit.record(db, ctx, "timesheet.approve" if approve else "timesheet.reject", "timesheet", ts.id, f"{e.employee_number} {display_name(e)}",
                 f"Week of {ts.week_start.isoformat()} {ts.status}", after={"reason": reason} if reason else None)
    db.flush()
    notify.queue(db, ctx, [e.user_id], f"timesheet_{ts.status}", f"Your timesheet was {ts.status}",
                 f"Week of {ts.week_start.isoformat()}." + (f" Reason: {ts.reject_reason}. You can edit and resubmit it." if ts.reject_reason else ""),
                 "timesheet", ts.id, "mypay", "")
    return ts


def reopen(db, ctx, access, ts_id: int) -> PayTimesheet:
    """Return an approved (not yet paid) timesheet to draft so it can be corrected."""
    access.require("timesheets_approve")
    ts = _get(db, ctx, ts_id)
    if ts.status == "processed" or db.query(PayTimesheetLine.id).filter(PayTimesheetLine.timesheet_id == ts.id, PayTimesheetLine.processed_run_id.isnot(None)).first():
        raise Conflict("This timesheet has been paid in a pay run and cannot be reopened")
    if ts.status not in ("approved", "submitted"):
        raise Conflict(f"A {ts.status} timesheet cannot be reopened")
    ts.status = "draft"
    e = db.get(PayEmployee, ts.employee_id)
    audit.record(db, ctx, "timesheet.reopen", "timesheet", ts.id, f"{e.employee_number} {display_name(e)}", "Returned to draft")
    db.flush()
    return ts


def delete(db, ctx, access, ts_id: int):
    ts = _get(db, ctx, ts_id)
    if not access.can_act_on("timesheets_manage", ts.employee_id):
        raise Forbidden("You can only delete your own timesheets")
    if ts.status not in ("draft", "rejected"):
        raise Conflict(f"A {ts.status} timesheet cannot be deleted")
    e = db.get(PayEmployee, ts.employee_id)
    audit.record(db, ctx, "timesheet.delete", "timesheet", ts.id, f"{e.employee_number} {display_name(e)}", f"Week of {ts.week_start.isoformat()} deleted")
    db.query(PayTimesheetLine).filter_by(timesheet_id=ts.id).delete()
    db.delete(ts)


def _get(db, ctx, ts_id) -> PayTimesheet:
    ts = db.query(PayTimesheet).filter_by(id=ts_id, org_id=ctx.org.id).first()
    if ts is None:
        raise NotFound("Timesheet")
    return ts


def get(db, ctx, access, ts_id: int) -> dict:
    ts = _get(db, ctx, ts_id)
    if not (access.can_act_on("timesheets_manage", ts.employee_id) or access.can_act_on("timesheets_approve", ts.employee_id)):
        raise Forbidden("You cannot view this timesheet")
    return ser(db, ts, db.get(PayEmployee, ts.employee_id))


def listing(db, ctx, access, *, status: str = "", employee_id: int = 0, date_from: Optional[date] = None, date_to: Optional[date] = None, mine: bool = False,
            limit: int = 300) -> list:
    q = db.query(PayTimesheet, PayEmployee).join(PayEmployee, PayEmployee.id == PayTimesheet.employee_id).filter(PayTimesheet.org_id == ctx.org.id)
    sc = access.scope("timesheets_manage")
    sc2 = access.scope("timesheets_approve")
    visible = None if (sc is None or sc2 is None) else (sc | sc2)
    if mine:                                                        # "My Pay": only the caller's own sheets, even for a manager or payroll administrator
        visible = {access.employee.id} if access.employee else set()
    if visible is not None:
        q = q.filter(PayTimesheet.employee_id.in_(visible or {-1}))
    if status:
        q = q.filter(PayTimesheet.status == status)
    if employee_id:
        q = q.filter(PayTimesheet.employee_id == employee_id)
    if date_from:
        q = q.filter(PayTimesheet.week_end >= date_from)
    if date_to:
        q = q.filter(PayTimesheet.week_start <= date_to)
    out = []
    for ts, e in q.order_by(PayTimesheet.week_start.desc(), PayEmployee.last_name).limit(limit):
        row = ser(db, ts, e, lines=False)
        row["can_decide"] = ts.status == "submitted" and access.can_act_on("timesheets_approve", ts.employee_id, include_self=False)    # the UI shows Approve / Reject only when this is true
        row["can_edit"] = ts.status in ("draft", "rejected") and access.can_act_on("timesheets_manage", ts.employee_id)               # Edit / Submit / Delete only for the owner of a draft
        out.append(row)
    return out


def approved_lines(db, org_id: int, employee_id: int, start: date, end: date) -> list:
    """Approved, not-yet-paid timesheet lines for the pay period -> [(line, item)]."""
    return (db.query(PayTimesheetLine, PayItem).join(PayTimesheet, PayTimesheet.id == PayTimesheetLine.timesheet_id)
            .join(PayItem, PayItem.id == PayTimesheetLine.pay_item_id)
            .filter(PayTimesheet.org_id == org_id, PayTimesheet.employee_id == employee_id, PayTimesheet.status == "approved",
                    PayTimesheetLine.processed_run_id.is_(None), PayTimesheetLine.work_date >= start, PayTimesheetLine.work_date <= end)
            .order_by(PayTimesheetLine.work_date).all())


def unapproved_in_period(db, org_id: int, employee_id: int, start: date, end: date) -> int:
    """Timesheets that touch the period but are not approved yet (a pay run warns about them)."""
    return (db.query(PayTimesheet.id).filter(PayTimesheet.org_id == org_id, PayTimesheet.employee_id == employee_id,
                                             PayTimesheet.status.in_(("draft", "submitted", "rejected")), PayTimesheet.week_end >= start,
                                             PayTimesheet.week_start <= end).count())
