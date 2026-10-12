"""
Pay run lifecycle:  draft -> (calculate) -> review -> (approve) -> approved -> (finalise) -> finalised -> (payment complete) -> paid
                    draft/review/approved -> voided (cancelled).   finalised/paid -> corrected ONLY by a reversal run.

Integrity rules enforced here
  * finalised data is never edited or deleted: every mutator refuses a run that is not draft/review
  * approve and finalise re-read the inputs and refuse a calculation that is stale (anything affecting pay changed after calculating)
  * finalise is all-or-nothing in one transaction (payslips, leave ledger, super, ledger journal); a second finalise returns 409
  * one live regular run per calendar period (service check AND a partial unique index in the database)
"""
import hashlib
import json
from datetime import date, datetime
from decimal import Decimal
from typing import Optional

from sqlalchemy import func
from sqlalchemy.exc import IntegrityError

from accfino.modules.payroll.engine import calc as engine
from accfino.modules.payroll.engine.rules import RulesError, rulebook
from accfino.modules.payroll.engine.superannuation import super_due_date
from accfino.modules.payroll.models.payroll import (PayCalendar, PayEmployee, PayEmployeeSuper, PayItem, PayLeaveRequest, PayLeaveTxn, PayLeaveType, PayPayment,
                                                    PayRun, PayRunEmployee, PayRunInput, PayRunLine, PaySuperContribution, PayTimesheet, PayTimesheetLine)
from accfino.modules.payroll.services import audit, config, runbuild
from accfino.modules.payroll.services import leave as leave_svc
from accfino.modules.payroll.services.employees import display_name, get_employee
from accfino.modules.payroll.services.errors import Conflict, Forbidden, NotFound, PayrollError
from accfino.modules.payroll.services.setup import get_settings, next_number

Z = Decimal(0)
EDITABLE = ("draft", "review")
SUM_FIELDS = ["gross", "taxable", "payg", "study_loan", "pretax_deductions", "posttax_deductions", "sacrifice_super", "reimbursements", "net", "qualifying_earnings",
              "etp_taxable", "super_guarantee", "super_additional", "super_total", "employer_cost", "ordinary_hours", "overtime_hours", "leave_hours"]


def get_run(db, org_id: int, run_id: int, lock: bool = False) -> PayRun:
    q = db.query(PayRun).filter(PayRun.org_id == org_id, PayRun.id == run_id)
    r = (q.with_for_update() if lock else q).first()
    if r is None:
        raise NotFound("Pay run")
    return r


# ---- serialisation ------------------------------------------------------------------------------------------------------------------
def ser_run(r: PayRun) -> dict:
    f = lambda v: str(v if v is not None else 0)
    return {"id": r.id, "run_no": r.run_no, "name": r.name, "run_type": r.run_type, "calendar_id": r.calendar_id, "frequency": r.frequency,
            "period_start": r.period_start.isoformat(), "period_end": r.period_end.isoformat(), "pay_date": r.pay_date.isoformat(), "status": r.status,
            "rule_set": r.rule_set, "employee_count": r.employee_count, "total_gross": f(r.total_gross), "total_taxable": f(r.total_taxable), "total_payg": f(r.total_payg),
            "total_study_loan": f(r.total_study_loan), "total_deductions": f(r.total_deductions), "total_sacrifice": f(r.total_sacrifice),
            "total_reimbursements": f(r.total_reimbursements), "total_net": f(r.total_net), "total_super": f(r.total_super),
            "total_employer_cost": f(r.total_employer_cost), "error_count": r.error_count, "warning_count": r.warning_count,
            "calculated_at": r.calculated_at.isoformat() if r.calculated_at else None, "approved_at": r.approved_at.isoformat() if r.approved_at else None,
            "finalised_at": r.finalised_at.isoformat() if r.finalised_at else None, "paid_at": r.paid_at.isoformat() if r.paid_at else None,
            "void_reason": r.void_reason, "reverses_run_id": r.reverses_run_id, "reversed_by_run_id": r.reversed_by_run_id, "notes": r.notes,
            "created_at": r.created_at.isoformat() if r.created_at else None, "locked": r.status in ("finalised", "paid") or r.run_type == "reversal"}


def ser_re(r: PayRunEmployee, lines=None) -> dict:
    f = lambda v: str(v if v is not None else 0)
    out = {"id": r.id, "employee_id": r.employee_id, "employee_number": r.employee_number, "employee_name": r.employee_name, "status": r.status,
           "exclusion_reason": r.exclusion_reason, "pay_basis": r.pay_basis, "tax_scale": r.tax_scale, "ordinary_hours": f(r.ordinary_hours), "overtime_hours": f(r.overtime_hours),
           "leave_hours": f(r.leave_hours), "gross": f(r.gross), "taxable": f(r.taxable), "payg": f(r.payg), "study_loan": f(r.study_loan),
           "pretax_deductions": f(r.pretax_deductions), "posttax_deductions": f(r.posttax_deductions), "sacrifice_super": f(r.sacrifice_super),
           "reimbursements": f(r.reimbursements), "net": f(r.net), "super_guarantee": f(r.super_guarantee), "super_additional": f(r.super_additional),
           "super_total": f(r.super_total), "employer_cost": f(r.employer_cost), "ytd": r.ytd, "errors": r.errors or [], "warnings": r.warnings or [], "manual_note": r.manual_note}
    if lines is not None:
        out["lines"] = [{"id": l.id, "txn_ref": l.txn_ref, "code": l.code, "name": l.name, "kind": l.kind, "hours": f(l.hours) if l.hours is not None else None,
                         "rate": f(l.rate) if l.rate is not None else None, "amount": f(l.amount), "taxable": l.taxable, "super_treatment": l.super_treatment,
                         "source": l.source, "note": l.note} for l in lines]
    return out


# ---- create -------------------------------------------------------------------------------------------------------------------------
def eligible_employees(db, org_id: int, cal: PayCalendar, start: date, end: date) -> list:
    q = db.query(PayEmployee).filter(PayEmployee.org_id == org_id, PayEmployee.start_date <= end,
                                     (PayEmployee.end_date.is_(None)) | (PayEmployee.end_date >= start), PayEmployee.status.in_(("active", "terminated")),
                                     PayEmployee.pay_frequency == cal.frequency, (PayEmployee.calendar_id == cal.id) | PayEmployee.calendar_id.is_(None))
    return q.order_by(PayEmployee.employee_number).all()


def create_run(db, ctx, access, body: dict) -> PayRun:
    access.require("run_create")
    cal = db.query(PayCalendar).filter_by(id=body.get("calendar_id"), org_id=ctx.org.id, is_active=True).first()
    if cal is None:
        raise PayrollError("Choose a pay calendar")
    start, end = config._date(body.get("period_start"), "Period start", True), config._date(body.get("period_end"), "Period end", True)
    p = config.valid_period(cal, start, end)
    pay_date = config._date(body.get("pay_date"), "Pay date") or p["pay_date"]
    if pay_date < start:
        raise PayrollError("Pay date cannot be before the start of the pay period")
    try:
        rs = rulebook().for_date(pay_date)
    except RulesError as e:
        raise PayrollError(str(e))
    run_type = body.get("run_type", "regular")
    if run_type not in ("regular", "off_cycle", "termination"):
        raise PayrollError("Run type must be regular, off_cycle or termination")
    if run_type == "regular":
        dup = db.query(PayRun).filter(PayRun.org_id == ctx.org.id, PayRun.calendar_id == cal.id, PayRun.period_start == start, PayRun.period_end == end,
                                      PayRun.run_type == "regular", PayRun.status != "voided", PayRun.reversed_by_run_id.is_(None)).first()
        if dup:
            raise Conflict(f"Pay run {dup.run_no} ({dup.status}) already exists for this period. Open it, or void it first to create another.", "duplicate_run")
    s = get_settings(db, ctx.org)
    emps = eligible_employees(db, ctx.org.id, cal, start, end)
    if body.get("employee_ids"):
        wanted = {int(i) for i in body["employee_ids"]}
        emps = [e for e in db.query(PayEmployee).filter(PayEmployee.org_id == ctx.org.id, PayEmployee.id.in_(wanted)).all()]
        missing = wanted - {e.id for e in emps}
        if missing:
            raise PayrollError(f"Employee(s) not found: {sorted(missing)}")
        for e in emps:
            if e.pay_frequency != cal.frequency:
                raise PayrollError(f"{display_name(e)} is paid {e.pay_frequency}, not {cal.frequency}")
    if not emps:
        raise PayrollError("No employees are eligible for this pay period (check start/end dates, frequency and calendar)")
    no = next_number(db, ctx.org, "run")
    run = PayRun(org_id=ctx.org.id, run_no=no, name=(body.get("name") or f"{cal.name} {start.strftime('%d %b')} - {end.strftime('%d %b %Y')}")[:150], run_type=run_type,
                 calendar_id=cal.id, frequency=cal.frequency, period_start=start, period_end=end, pay_date=pay_date, status="draft", rule_set=rs.id,
                 employee_count=0, created_by=ctx.user_id, notes=(body.get("notes") or None))
    db.add(run)
    try:
        db.flush()
    except IntegrityError:
        db.rollback()
        raise Conflict("A pay run for this period was created at the same moment. Refresh and open the existing one.", "duplicate_run")
    for e in emps:
        db.add(PayRunEmployee(org_id=ctx.org.id, run_id=run.id, employee_id=e.id, employee_number=e.employee_number, employee_name=display_name(e),
                              department_id=e.department_id, status="included"))
    run.employee_count = len(emps)
    db.flush()
    audit.record(db, ctx, "payrun.create", "pay_run", run.id, run.run_no, f"Created for {start.isoformat()} to {end.isoformat()}, pay date {pay_date.isoformat()} ({len(emps)} employees)",
                 after={"calendar": cal.name, "employees": len(emps), "rule_set": rs.id})
    return run


def _editable(run: PayRun):
    if run.status not in EDITABLE:
        hint = " Use Reverse to correct it." if run.status in ("finalised", "paid") else ""
        raise Conflict(f"Pay run {run.run_no} is {run.status} and cannot be changed.{hint}", "run_locked")


def set_included(db, ctx, access, run_id: int, employee_id: int, include: bool, reason: str = "") -> PayRunEmployee:
    access.require("run_create")
    run = get_run(db, ctx.org.id, run_id, lock=True)
    _editable(run)
    re_ = db.query(PayRunEmployee).filter_by(run_id=run.id, employee_id=employee_id).first()
    if re_ is None:
        if not include:
            raise NotFound("Employee in this pay run")
        e = get_employee(db, ctx.org.id, employee_id)
        if e.pay_frequency != run.frequency:
            raise PayrollError(f"{display_name(e)} is paid {e.pay_frequency}: they cannot join a {run.frequency} pay run")
        if e.start_date > run.period_end or (e.end_date and e.end_date < run.period_start):
            raise PayrollError(f"{display_name(e)} was not employed during this pay period")
        re_ = PayRunEmployee(org_id=ctx.org.id, run_id=run.id, employee_id=e.id, employee_number=e.employee_number, employee_name=display_name(e), department_id=e.department_id)
        db.add(re_)
    if not include and not (reason or "").strip():
        raise PayrollError("Give a reason for excluding an employee from the pay run")
    re_.status, re_.exclusion_reason = ("included", None) if include else ("excluded", reason[:300])
    run.status = "draft" if run.status == "review" else run.status
    db.flush()
    audit.record(db, ctx, "payrun.include" if include else "payrun.exclude", "pay_run", run.id, run.run_no, f"{re_.employee_number} {re_.employee_name} {'included' if include else 'excluded'}",
                 after={"reason": reason})
    return re_


def add_input(db, ctx, access, run_id: int, body: dict) -> PayRunInput:
    access.require("run_create")
    run = get_run(db, ctx.org.id, run_id, lock=True)
    _editable(run)
    e = get_employee(db, ctx.org.id, int(body.get("employee_id") or 0))
    if not db.query(PayRunEmployee.id).filter_by(run_id=run.id, employee_id=e.id, status="included").first():
        raise PayrollError(f"{display_name(e)} is not included in this pay run")
    it = db.query(PayItem).filter_by(id=body.get("pay_item_id"), org_id=ctx.org.id, is_active=True).first()
    if it is None:
        raise PayrollError("Pay item not found (or inactive)")
    if it.is_system and it.kind in ("earnings", "salary_adjustment", "leave_loading"):
        raise PayrollError(f"'{it.name}' is generated automatically and cannot be entered manually")
    dec = config._dec
    amount, hours, rate = dec(body.get("amount"), "Amount", min_=Z, max_=Decimal(100000000)), dec(body.get("hours"), "Hours", min_=Z, max_=Decimal(10000)), dec(body.get("rate"), "Rate", min_=Z)
    if it.calc_method == "hours_x_rate" and not hours:
        raise PayrollError(f"{it.name}: enter the hours")
    if it.calc_method == "fixed" and amount is None and it.default_amount is None:
        raise PayrollError(f"{it.name}: enter an amount")
    periods = body.get("periods")
    if periods is not None:
        periods = int(dec(periods, "Pay periods", min_=Decimal(1), max_=Decimal(52)))
    row = PayRunInput(org_id=ctx.org.id, run_id=run.id, employee_id=e.id, pay_item_id=it.id, hours=hours, rate=rate, amount=amount, periods=periods,
                      leave_pre1993=bool(body.get("leave_pre1993")), genuine_redundancy=bool(body.get("genuine_redundancy")), note=(body.get("note") or "")[:300] or None,
                      created_by=ctx.user_id)
    db.add(row)
    run.status = "draft" if run.status == "review" else run.status
    db.flush()
    audit.record(db, ctx, "payrun.input_add", "pay_run", run.id, run.run_no, f"{it.code} added for {display_name(e)}", after={"item": it.code, "amount": amount, "hours": hours})
    return row


def remove_input(db, ctx, access, run_id: int, input_id: int):
    access.require("run_create")
    run = get_run(db, ctx.org.id, run_id, lock=True)
    _editable(run)
    row = db.query(PayRunInput).filter_by(id=input_id, run_id=run.id).first()
    if row is None:
        raise NotFound("Pay run input")
    it = db.get(PayItem, row.pay_item_id)
    run.status = "draft" if run.status == "review" else run.status
    audit.record(db, ctx, "payrun.input_remove", "pay_run", run.id, run.run_no, f"{it.code if it else '?'} input removed")
    db.delete(row)


# ---- calculate ----------------------------------------------------------------------------------------------------------------------
def _ctx_items(db, org_id):
    return ({i.code: i for i in db.query(PayItem).filter_by(org_id=org_id)}, db.query(PayLeaveType).filter_by(org_id=org_id, is_active=True).all())


def _issues(res: engine.PayResult, built: runbuild.Built, e: PayEmployee, db) -> tuple:
    errs = [{"code": i.code, "message": i.message} for i in res.errors] + [{"code": n["code"], "message": n["message"]} for n in built.notes if n["severity"] == "error"]
    warns = [{"code": i.code, "message": i.message} for i in res.warnings] + [{"code": n["code"], "message": n["message"]} for n in built.notes if n["severity"] == "warning"]
    if res.net > 0 and not db.query(PayEmployeeBankModel.id).filter_by(employee_id=e.id, is_active=True).first():
        errs.append({"code": "no_bank", "message": "No bank account: net pay cannot be paid"})
    if e.status == "terminated" and e.end_date and e.end_date >= built.period.period_start and not any(l.item.kind in ("termination_leave", "etp") for l in built.lines):
        warns.append({"code": "termination_payments", "message": "Employee has left: check for unused leave payout or termination payments"})
    return errs, warns


from accfino.modules.payroll.models.payroll import PayEmployeeBank as PayEmployeeBankModel  # noqa: E402


def calculate(db, ctx, access, run_id: int) -> PayRun:
    access.require("run_create")
    run = get_run(db, ctx.org.id, run_id, lock=True)
    if run.status == "approved":
        raise Conflict("This pay run is approved. Return it to review before recalculating.", "run_locked")
    _editable(run)
    try:
        rules = rulebook().for_date(run.pay_date)
    except RulesError as e:
        raise PayrollError(str(e))
    prev, run.status = run.status, "processing"
    items, ltypes = _ctx_items(db, ctx.org.id)
    for need in ("BASE", "LEAVELOAD", "SALADJ"):
        if need not in items:
            raise PayrollError(f"The system pay item {need} is missing: reopen Payroll settings to re-provision it")
    db.query(PayRunLine).filter_by(run_id=run.id).delete()
    included = db.query(PayRunEmployee).filter_by(run_id=run.id, status="included").order_by(PayRunEmployee.employee_number).all()
    if not included:
        run.status = prev
        raise PayrollError("No employees are included in this pay run")
    n_err = n_warn = 0
    for re_ in included:
        e = db.get(PayEmployee, re_.employee_id)
        built = runbuild.build(db, ctx.org, run, e, rules, items, ltypes)
        res = engine.calculate_employee(rules, built.emp, built.period, built.lines, built.ytd, built.accrual_defs, built.balances)
        errs, warns = _issues(res, built, e, db)
        re_.pay_basis, re_.rate_snapshot = e.pay_basis, (e.annual_salary if e.pay_basis == "salary" else e.hourly_rate)
        re_.employee_name, re_.employee_number, re_.department_id = display_name(e), e.employee_number, e.department_id
        re_.tax_scale = res.scale or None
        for k, src in (("ordinary_hours", res.ordinary_hours), ("overtime_hours", res.overtime_hours), ("leave_hours", res.leave_hours), ("gross", res.gross), ("taxable", res.taxable),
                       ("payg", res.payg), ("study_loan", res.study_loan), ("pretax_deductions", res.pretax_deductions), ("posttax_deductions", res.posttax_deductions + res.employee_super_after_tax),
                       ("sacrifice_super", res.sacrifice_super), ("reimbursements", res.reimbursements), ("net", res.net), ("qualifying_earnings", res.qualifying_earnings),
                       ("etp_taxable", res.etp_taxable), ("super_guarantee", res.super_guarantee), ("super_additional", res.super_additional_employer),
                       ("super_total", res.super_total), ("employer_cost", res.employer_cost)):
            setattr(re_, k, src)
        y = res.ytd_after
        re_.ytd = {k: str(v) for k, v in y.__dict__.items()} if y else None
        re_.accruals, re_.errors, re_.warnings, re_.inputs_hash = res.accruals, errs, warns, built.fingerprint
        for n, l in enumerate(res.lines, start=1):
            db.add(PayRunLine(org_id=ctx.org.id, run_id=run.id, run_employee_id=re_.id, employee_id=e.id, line_no=n, txn_ref=f"{run.run_no}-{e.employee_number}-{n:03d}",
                              pay_item_id=l.item_id, code=l.code, name=l.name, kind=l.kind, hours=l.hours, rate=l.rate, amount=l.amount, taxable=l.taxable,
                              payg_treatment=l.payg_treatment, super_treatment=l.super_treatment, leave_type_id=l.leave_type_id, source=l.source, note=l.note or None))
        n_err += 1 if errs else 0
        n_warn += 1 if warns else 0
    db.flush()
    _totals(db, run)
    run.error_count, run.warning_count, run.rule_set = n_err, n_warn, rules.id
    run.status, run.calculated_at = "review", datetime.utcnow()
    audit.record(db, ctx, "payrun.calculate", "pay_run", run.id, run.run_no, f"Calculated {len(included)} employees: gross {run.total_gross}, net {run.total_net}, {n_err} with errors, {n_warn} with warnings",
                 after={"total_gross": run.total_gross, "total_net": run.total_net, "rule_set": rules.id})
    return run


def _totals(db, run: PayRun):
    rows = db.query(PayRunEmployee).filter_by(run_id=run.id, status="included").all()
    run.employee_count = len(rows)
    s = lambda f: sum((getattr(r, f) or Z for r in rows), Z)
    run.total_gross, run.total_taxable, run.total_payg, run.total_study_loan = s("gross"), s("taxable"), s("payg"), s("study_loan")
    run.total_deductions, run.total_sacrifice, run.total_reimbursements = s("pretax_deductions") + s("posttax_deductions"), s("sacrifice_super"), s("reimbursements")
    run.total_net, run.total_super, run.total_employer_cost = s("net"), s("super_total"), s("employer_cost")


# ---- approve / return / void --------------------------------------------------------------------------------------------------------
def _stale_employees(db, ctx, run: PayRun) -> list:
    rules = rulebook().for_date(run.pay_date)
    items, ltypes = _ctx_items(db, ctx.org.id)
    stale = []
    for re_ in db.query(PayRunEmployee).filter_by(run_id=run.id, status="included"):
        e = db.get(PayEmployee, re_.employee_id)
        if runbuild.build(db, ctx.org, run, e, rules, items, ltypes).fingerprint != re_.inputs_hash:
            stale.append(re_.employee_name)
    return stale


def approve(db, ctx, access, run_id: int) -> PayRun:
    access.require("run_approve")
    run = get_run(db, ctx.org.id, run_id, lock=True)
    if run.status != "review":
        raise Conflict(f"Only a pay run in review can be approved (this one is {run.status}). Calculate it first." if run.status == "draft" else f"Pay run is {run.status}.", "bad_state")
    if run.error_count:
        raise PayrollError(f"{run.error_count} employee(s) have errors. Fix them (or exclude those employees) and recalculate before approving.")
    if not db.query(PayRunEmployee.id).filter_by(run_id=run.id, status="included").first():
        raise PayrollError("No employees are included in this pay run")
    if get_settings(db, ctx.org).controls.get("require_separate_approver") and run.created_by == ctx.user_id and not ctx.is_admin:
        raise Forbidden("Separation of duties is on: the person who created the pay run cannot approve it")
    stale = _stale_employees(db, ctx, run)
    if stale:
        raise Conflict(f"Pay inputs changed since this run was calculated ({', '.join(stale[:5])}{'...' if len(stale) > 5 else ''}). Recalculate before approving.", "stale")
    run.status, run.approved_at, run.approved_by = "approved", datetime.utcnow(), ctx.user_id
    audit.record(db, ctx, "payrun.approve", "pay_run", run.id, run.run_no, f"Approved: gross {run.total_gross}, net {run.total_net}", after={"total_net": run.total_net})
    return run


def return_to_review(db, ctx, access, run_id: int) -> PayRun:
    access.require("run_approve")
    run = get_run(db, ctx.org.id, run_id, lock=True)
    if run.status != "approved":
        raise Conflict(f"Only an approved pay run can be returned to review (this one is {run.status})", "bad_state")
    run.status, run.approved_at, run.approved_by = "review", None, None
    audit.record(db, ctx, "payrun.unapprove", "pay_run", run.id, run.run_no, "Returned to review")
    return run


def void(db, ctx, access, run_id: int, reason: str) -> PayRun:
    access.require("run_create")
    run = get_run(db, ctx.org.id, run_id, lock=True)
    if run.status in ("finalised", "paid"):
        raise Conflict("A finalised pay run cannot be cancelled: reverse it instead.", "run_locked")
    if run.status == "voided":
        raise Conflict("This pay run is already cancelled", "bad_state")
    if not (reason or "").strip():
        raise PayrollError("Give a reason for cancelling the pay run")
    before = run.status
    run.status, run.voided_at, run.voided_by, run.void_reason = "voided", datetime.utcnow(), ctx.user_id, reason[:300]
    audit.record(db, ctx, "payrun.void", "pay_run", run.id, run.run_no, f"Cancelled: {reason}", before={"status": before}, after={"status": "voided"})
    return run


# ---- finalise -----------------------------------------------------------------------------------------------------------------------
def _hash_run(db, run: PayRun) -> str:
    rows = db.query(PayRunEmployee).filter_by(run_id=run.id).order_by(PayRunEmployee.employee_id).all()
    ls = db.query(PayRunLine).filter_by(run_id=run.id).order_by(PayRunLine.txn_ref).all()
    payload = {"run": [run.run_no, str(run.pay_date), str(run.total_gross), str(run.total_net), str(run.total_payg), str(run.total_super)],
               "emps": [[r.employee_id, r.status] + [str(getattr(r, f) or 0) for f in SUM_FIELDS] for r in rows], "lines": [[l.txn_ref, l.code, str(l.amount), str(l.hours)] for l in ls]}
    return hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()


def verify_integrity(db, ctx, access, run_id: int) -> dict:
    access.require("reports_view")
    run = get_run(db, ctx.org.id, run_id)
    if run.status not in ("finalised", "paid"):
        return {"run_id": run.id, "checked": False, "reason": f"Run is {run.status}: results are only sealed at finalisation"}
    ok = run.result_hash == _hash_run(db, run)
    return {"run_id": run.id, "checked": True, "intact": ok, "message": "Finalised results are unchanged since finalisation" if ok else "FINALISED RESULTS HAVE BEEN ALTERED since finalisation"}


def finalise(db, ctx, access, run_id: int) -> PayRun:
    access.require("run_finalise")
    from accfino.modules.payroll.services import journals, payslips
    run = get_run(db, ctx.org.id, run_id, lock=True)
    if run.status in ("finalised", "paid"):
        raise Conflict(f"Pay run {run.run_no} is already {run.status}: it was not processed again.", "already_finalised")
    if run.status != "approved":
        raise Conflict(f"Only an approved pay run can be finalised (this one is {run.status}).", "bad_state")
    stale = _stale_employees(db, ctx, run)
    if stale:
        raise Conflict(f"Pay inputs changed since approval ({', '.join(stale[:5])}). Return the run to review and recalculate.", "stale")
    rules = rulebook().for_date(run.pay_date)
    included = db.query(PayRunEmployee).filter_by(run_id=run.id, status="included").order_by(PayRunEmployee.employee_number).all()
    if db.query(PayLeaveTxn.id).filter_by(pay_run_id=run.id).first():
        raise Conflict("Leave has already been posted for this run: it cannot be finalised again", "already_finalised")
    items, ltypes = _ctx_items(db, ctx.org.id)
    for re_ in included:
        e = db.get(PayEmployee, re_.employee_id)
        _post_leave(db, ctx, run, re_, e, rules, items, ltypes)
        _post_super(db, ctx, run, re_, rules)
    payslips.generate_for_run(db, ctx, run)
    journals.post_run(db, ctx, run)
    run.status, run.finalised_at, run.finalised_by = "finalised", datetime.utcnow(), ctx.user_id
    db.flush()
    run.result_hash = _hash_run(db, run)
    audit.record(db, ctx, "payrun.finalise", "pay_run", run.id, run.run_no, f"Finalised: gross {run.total_gross}, PAYG {run.total_payg}, super {run.total_super}, net {run.total_net}",
                 after={"result_hash": run.result_hash})
    return run


def _post_leave(db, ctx, run, re_, e, rules, items, ltypes):
    built = runbuild.build(db, ctx.org, run, e, rules, items, ltypes)
    for a in re_.accruals or []:
        db.add(PayLeaveTxn(org_id=ctx.org.id, employee_id=e.id, leave_type_id=a["leave_type_id"], txn_date=run.pay_date, txn_type="accrual", hours=Decimal(a["hours"]),
                           pay_run_id=run.id, note=f"Accrual {run.run_no}", created_by=ctx.user_id))
    by_req = {}
    for lt_id, info in leave_svc.hours_for_period(db, ctx.org.id, e, run.period_start, run.period_end).items():
        for req_id, h in info["detail"]:
            by_req[req_id] = (lt_id, h)
    covered = set()
    for req_id, (lt_id, h) in by_req.items():
        if any(l.leave_type_id == lt_id and l.kind in ("leave", "unpaid_leave") and l.source == "leave_request" for l in db.query(PayRunLine).filter_by(run_employee_id=re_.id)):
            db.add(PayLeaveTxn(org_id=ctx.org.id, employee_id=e.id, leave_type_id=lt_id, txn_date=run.pay_date, txn_type="taken", hours=-h, pay_run_id=run.id,
                               leave_request_id=req_id, note=f"Leave paid {run.run_no}", created_by=ctx.user_id))
            covered.add((lt_id, req_id))
    db.flush()
    for req_id in {r for _, r in covered}:
        r = db.get(PayLeaveRequest, req_id)
        taken = -(db.query(func.coalesce(func.sum(PayLeaveTxn.hours), 0)).filter(PayLeaveTxn.leave_request_id == req_id, PayLeaveTxn.txn_type.in_(("taken", "reversal"))).scalar() or 0)
        if Decimal(str(taken)) >= r.hours - Decimal("0.005"):
            r.paid_run_id = run.id
    ts_taken = {}
    for l in db.query(PayRunLine).filter_by(run_employee_id=re_.id, source="timesheet"):
        if l.kind == "leave" and l.leave_type_id:
            ts_taken[l.leave_type_id] = ts_taken.get(l.leave_type_id, Z) + (l.hours or Z)
    for lt_id, h in ts_taken.items():
        db.add(PayLeaveTxn(org_id=ctx.org.id, employee_id=e.id, leave_type_id=lt_id, txn_date=run.pay_date, txn_type="taken", hours=-h, pay_run_id=run.id,
                           note=f"Timesheet leave {run.run_no}", created_by=ctx.user_id))
    if built.timesheet_line_ids:
        for l in db.query(PayTimesheetLine).filter(PayTimesheetLine.id.in_(built.timesheet_line_ids)):
            l.processed_run_id = run.id
        db.flush()
        for ts_id in {l.timesheet_id for l in db.query(PayTimesheetLine).filter(PayTimesheetLine.id.in_(built.timesheet_line_ids))}:
            ts = db.get(PayTimesheet, ts_id)
            if not db.query(PayTimesheetLine.id).filter(PayTimesheetLine.timesheet_id == ts_id, PayTimesheetLine.processed_run_id.is_(None)).first():
                ts.status, ts.processed_run_id = "processed", run.id


def _post_super(db, ctx, run, re_, rules):
    funds = (db.query(PayEmployeeSuper).filter_by(employee_id=re_.employee_id, is_active=True).all())
    if not funds or re_.super_total <= 0:
        return
    due = super_due_date(rules, run.pay_date)
    lines = db.query(PayRunLine).filter_by(run_employee_id=re_.id).all()
    comp = {"sg": re_.super_guarantee, "salary_sacrifice": re_.sacrifice_super,
            "employer_additional": sum((l.amount for l in lines if l.kind == "employer_super_additional"), Z),
            "employee_after_tax": sum((l.amount for l in lines if l.kind == "employee_super_after_tax"), Z)}
    for name, amt in comp.items():
        if amt <= 0:
            continue
        allocated = Z
        for i, f in enumerate(funds):
            share = (amt * f.allocation_pct / 100).quantize(Decimal("0.01")) if i < len(funds) - 1 else amt - allocated    # last fund takes the rounding remainder
            allocated += share
            if share > 0:
                db.add(PaySuperContribution(org_id=ctx.org.id, run_id=run.id, run_employee_id=re_.id, employee_id=re_.employee_id, fund_id=f.fund_id, component=name,
                                            amount=share, qualifying_earnings=re_.qualifying_earnings if name == "sg" else Z, due_date=due))


# ---- reverse ------------------------------------------------------------------------------------------------------------------------
def reverse(db, ctx, access, run_id: int, reason: str, reversal_date: Optional[date] = None) -> PayRun:
    """Correct a finalised/paid run: a NEW run with every amount negated is finalised, the ledger journal is reversed, leave and timesheets are released.
    The original is kept untouched (history preserved); a corrected regular run can then be created for the same period."""
    access.require("run_reverse")
    from accfino.modules.payroll.services import journals
    orig = get_run(db, ctx.org.id, run_id, lock=True)
    if orig.status not in ("finalised", "paid"):
        raise Conflict(f"Only a finalised or paid pay run can be reversed (this one is {orig.status}).", "bad_state")
    if orig.run_type == "reversal":
        raise Conflict("A reversal run cannot itself be reversed", "bad_state")
    if orig.reversed_by_run_id:
        raise Conflict(f"Pay run {orig.run_no} has already been reversed", "already_reversed")
    if not (reason or "").strip():
        raise PayrollError("Give a reason for reversing the pay run")
    no = next_number(db, ctx.org, "run")
    rev = PayRun(org_id=ctx.org.id, run_no=no, name=f"Reversal of {orig.run_no}", run_type="reversal", calendar_id=orig.calendar_id, frequency=orig.frequency,
                 period_start=orig.period_start, period_end=orig.period_end, pay_date=orig.pay_date, status="finalised", rule_set=orig.rule_set,
                 reverses_run_id=orig.id, created_by=ctx.user_id, finalised_at=datetime.utcnow(), finalised_by=ctx.user_id, notes=reason[:300])
    db.add(rev)
    db.flush()
    neg = ["ordinary_hours", "overtime_hours", "leave_hours"] + SUM_FIELDS
    for r in db.query(PayRunEmployee).filter_by(run_id=orig.id, status="included").all():
        c = PayRunEmployee(org_id=ctx.org.id, run_id=rev.id, employee_id=r.employee_id, employee_number=r.employee_number, employee_name=r.employee_name,
                           department_id=r.department_id, status="included", pay_basis=r.pay_basis, rate_snapshot=r.rate_snapshot, tax_scale=r.tax_scale,
                           manual_note=f"Reversal of {orig.run_no}")
        for f in set(neg):
            setattr(c, f, -(getattr(r, f) or Z))
        db.add(c)
        db.flush()
        for i, l in enumerate(db.query(PayRunLine).filter_by(run_employee_id=r.id).order_by(PayRunLine.line_no), start=1):
            db.add(PayRunLine(org_id=ctx.org.id, run_id=rev.id, run_employee_id=c.id, employee_id=l.employee_id, line_no=i, txn_ref=f"{rev.run_no}-{r.employee_number}-{i:03d}",
                              pay_item_id=l.pay_item_id, code=l.code, name=l.name, kind=l.kind, hours=-l.hours if l.hours is not None else None, rate=l.rate, amount=-l.amount,
                              taxable=l.taxable, payg_treatment=l.payg_treatment, super_treatment=l.super_treatment, leave_type_id=l.leave_type_id, source="reversal",
                              note=f"Reverses {l.txn_ref}"))
    for t in db.query(PayLeaveTxn).filter_by(pay_run_id=orig.id).all():
        db.add(PayLeaveTxn(org_id=ctx.org.id, employee_id=t.employee_id, leave_type_id=t.leave_type_id, txn_date=date.today(), txn_type="reversal", hours=-t.hours, pay_run_id=rev.id,
                           leave_request_id=t.leave_request_id, note=f"Reversal of {orig.run_no}", created_by=ctx.user_id))
    db.query(PayLeaveRequest).filter_by(paid_run_id=orig.id).update({PayLeaveRequest.paid_run_id: None})
    db.query(PayTimesheetLine).filter_by(processed_run_id=orig.id).update({PayTimesheetLine.processed_run_id: None})
    db.query(PayTimesheet).filter_by(processed_run_id=orig.id).update({PayTimesheet.processed_run_id: None, PayTimesheet.status: "approved"})
    db.query(PaySuperContribution).filter_by(run_id=orig.id).update({PaySuperContribution.status: "reversed"})
    recover = False
    for p in db.query(PayPayment).filter_by(run_id=orig.id).all():
        if p.status == "prepared":
            p.status, p.cancel_reason = "cancelled", f"Pay run reversed: {reason[:200]}"
        elif p.status == "completed":
            recover = True
    journals.reverse_run(db, ctx, orig, rev, reversal_date or date.today())
    _totals(db, rev)
    db.flush()
    rev.result_hash = _hash_run(db, rev)
    orig.reversed_by_run_id = rev.id
    audit.record(db, ctx, "payrun.reverse", "pay_run", orig.id, orig.run_no, f"Reversed by {rev.run_no}: {reason}" + (" (payment had been made: recover the funds)" if recover else ""),
                 before={"status": orig.status}, after={"reversal_run": rev.run_no, "payment_recovery_required": recover})
    rev.warning_count = 1 if recover else 0
    return rev


# ---- read ---------------------------------------------------------------------------------------------------------------------------
def list_runs(db, ctx, access, *, status: str = "", limit: int = 100) -> list:
    access.require("reports_view")
    q = db.query(PayRun).filter(PayRun.org_id == ctx.org.id)
    if status:
        q = q.filter(PayRun.status == status)
    return [ser_run(r) for r in q.order_by(PayRun.pay_date.desc(), PayRun.id.desc()).limit(limit)]


def run_detail(db, ctx, access, run_id: int, with_lines: bool = True) -> dict:
    access.require("reports_view")
    run = get_run(db, ctx.org.id, run_id)
    out = ser_run(run)
    emps = db.query(PayRunEmployee).filter_by(run_id=run.id).order_by(PayRunEmployee.employee_number).all()
    by_emp = {}
    if with_lines:
        for l in db.query(PayRunLine).filter_by(run_id=run.id).order_by(PayRunLine.run_employee_id, PayRunLine.line_no):
            by_emp.setdefault(l.run_employee_id, []).append(l)
    out["employees"] = [ser_re(r, by_emp.get(r.id, []) if with_lines else None) for r in emps]
    out["inputs"] = [{"id": i.id, "employee_id": i.employee_id, "pay_item_id": i.pay_item_id, "hours": str(i.hours) if i.hours is not None else None,
                      "amount": str(i.amount) if i.amount is not None else None, "note": i.note} for i in db.query(PayRunInput).filter_by(run_id=run.id)]
    out["stale"] = False
    return out
