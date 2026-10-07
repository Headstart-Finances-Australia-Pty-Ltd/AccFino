"""Payroll dashboard: every figure is computed from actual payroll data (pay runs, employees, timesheets, leave, super, payments) - nothing is hard-coded."""
from datetime import date, timedelta
from decimal import Decimal
from typing import Optional

from sqlalchemy import func

from accfino.modules.payroll.engine.rules import RulesError, rulebook
from accfino.modules.payroll.models.payroll import (PayCalendar, PayEmployee, PayEmployeeBank, PayEmployeeSuper, PayEmployeeTax, PayLeaveRequest, PayPayment, PayRun,
                                                    PaySuperContribution, PayTimesheet)
from accfino.modules.payroll.services import config, employees as emp_svc, runbuild
from accfino.modules.payroll.services.payruns import ser_run

Z = Decimal(0)
S = lambda v: str(v if v is not None else 0)


def build(db, ctx, access, today: Optional[date] = None) -> dict:
    access.require("view")
    today = today or date.today()
    org = ctx.org.id
    fym = ctx.org.fy_end_month or 6
    fs = runbuild.fy_start(today, fym)
    live = [PayRun.org_id == org, PayRun.status.in_(("finalised", "paid"))]
    active = db.query(PayEmployee).filter_by(org_id=org, status="active")
    out = {"today": today.isoformat(), "financial_year": runbuild.fy_label(today, fym), "fy_start": fs.isoformat()}

    # employees
    emps = active.all()
    by_type = {}
    for e in emps:
        by_type[e.employment_type] = by_type.get(e.employment_type, 0) + 1
    attention = []
    for e in emps:
        issues = emp_svc.readiness(db, e)
        if issues:
            attention.append({"employee_id": e.id, "employee_number": e.employee_number, "name": emp_svc.display_name(e), "issues": issues})
    out["employees"] = {"active": len(emps), "by_type": by_type, "terminated": db.query(PayEmployee).filter_by(org_id=org, status="terminated").count(),
                        "requiring_attention": len(attention), "attention": attention[:12]}

    # calendars: current period, next pay date, run status
    cals = db.query(PayCalendar).filter_by(org_id=org, is_active=True).all()
    periods, upcoming = [], []
    for c in cals:
        p = config.period_containing(c, today)
        run = db.query(PayRun).filter(PayRun.org_id == org, PayRun.calendar_id == c.id, PayRun.period_start == p["period_start"], PayRun.run_type == "regular",
                                      PayRun.status != "voided", PayRun.reversed_by_run_id.is_(None)).first()
        last_closed = config.prev_period(c, p)
        prev_run = db.query(PayRun).filter(PayRun.org_id == org, PayRun.calendar_id == c.id, PayRun.period_start == last_closed["period_start"], PayRun.run_type == "regular",
                                           PayRun.status != "voided", PayRun.reversed_by_run_id.is_(None)).first()
        periods.append({"calendar_id": c.id, "calendar": c.name, "frequency": c.frequency, "period_start": p["period_start"].isoformat(), "period_end": p["period_end"].isoformat(),
                        "pay_date": p["pay_date"].isoformat(), "run_status": run.status if run else "not_started", "run_id": run.id if run else None,
                        "previous_period": {"period_start": last_closed["period_start"].isoformat(), "period_end": last_closed["period_end"].isoformat(), "pay_date": last_closed["pay_date"].isoformat(),
                                            "run_status": prev_run.status if prev_run else "not_started", "run_id": prev_run.id if prev_run else None,
                                            "overdue": (prev_run is None or prev_run.status not in ("finalised", "paid")) and last_closed["pay_date"] < today}})
        q = p
        for _ in range(4):
            if q["pay_date"] >= today:
                upcoming.append({"calendar": c.name, "pay_date": q["pay_date"].isoformat(), "period_end": q["period_end"].isoformat(), "days": (q["pay_date"] - today).days})
            q = config.next_period(c, q)
    out["periods"] = periods
    out["upcoming_pay_dates"] = sorted(upcoming, key=lambda x: x["pay_date"])[:8]
    nxt = sorted([p for p in periods], key=lambda p: p["pay_date"])
    out["next_pay_run"] = nxt[0] if nxt else None

    # runs
    last = db.query(PayRun).filter(*live, PayRun.run_type != "reversal", PayRun.reversed_by_run_id.is_(None)).order_by(PayRun.pay_date.desc(), PayRun.id.desc()).first()
    out["last_run"] = ser_run(last) if last else None
    out["recent_runs"] = [ser_run(r) for r in db.query(PayRun).filter(PayRun.org_id == org).order_by(PayRun.pay_date.desc(), PayRun.id.desc()).limit(6)]
    t = db.query(func.coalesce(func.sum(PayRun.total_gross), 0), func.coalesce(func.sum(PayRun.total_payg + PayRun.total_study_loan), 0), func.coalesce(func.sum(PayRun.total_super), 0),
                 func.coalesce(func.sum(PayRun.total_net), 0), func.coalesce(func.sum(PayRun.total_employer_cost), 0)).filter(*live, PayRun.pay_date >= fs, PayRun.pay_date <= today).one()
    out["ytd"] = {"gross": S(t[0]), "payg": S(t[1]), "super": S(t[2]), "net": S(t[3]), "employer_cost": S(t[4])}
    trend = []
    for r in db.query(PayRun).filter(*live, PayRun.run_type != "reversal", PayRun.reversed_by_run_id.is_(None)).order_by(PayRun.pay_date.desc(), PayRun.id.desc()).limit(12):
        trend.append({"pay_date": r.pay_date.isoformat(), "run_no": r.run_no, "gross": S(r.total_gross), "payg": S(r.total_payg + r.total_study_loan), "super": S(r.total_super), "net": S(r.total_net)})
    out["trend"] = list(reversed(trend))

    # pending actions
    ts_sub = db.query(PayTimesheet).filter_by(org_id=org, status="submitted").count()
    lv_pen = db.query(PayLeaveRequest).filter_by(org_id=org, status="pending").count()
    runs_open = db.query(PayRun).filter(PayRun.org_id == org, PayRun.status.in_(("draft", "review", "approved"))).count()
    pay_unpaid = db.query(PayRun).filter(PayRun.org_id == org, PayRun.status == "finalised", PayRun.run_type != "reversal", PayRun.reversed_by_run_id.is_(None)).count()
    super_over = db.query(PaySuperContribution).filter(PaySuperContribution.org_id == org, PaySuperContribution.status == "pending", PaySuperContribution.due_date < today).count()
    super_pending = db.query(PaySuperContribution).filter(PaySuperContribution.org_id == org, PaySuperContribution.status == "pending").count()
    out["pending"] = {"timesheets_to_approve": ts_sub, "leave_to_approve": lv_pen, "runs_in_progress": runs_open, "runs_awaiting_payment": pay_unpaid, "super_overdue": super_over, "super_unpaid": super_pending}

    # alerts and reminders
    alerts = []
    if super_over:
        alerts.append({"level": "danger", "code": "super_overdue", "message": f"{super_over} super contribution(s) are past their Payday Super due date"})
    for p in periods:
        if p["previous_period"]["overdue"]:
            alerts.append({"level": "warning", "code": "run_overdue", "message": f"No finalised pay run for {p['calendar']} period ending {p['previous_period']['period_end']} (pay date {p['previous_period']['pay_date']} has passed)"})
    if attention:
        alerts.append({"level": "warning", "code": "employee_setup", "message": f"{len(attention)} employee(s) have incomplete payroll set-up"})
    if db.query(PayEmployee).filter(PayEmployee.org_id == org, PayEmployee.status == "active", PayEmployee.end_date.isnot(None), PayEmployee.end_date < today).count():
        alerts.append({"level": "warning", "code": "ended_active", "message": "Some employees have an end date in the past but are still marked active"})
    try:
        rulebook().for_date(today + timedelta(days=45))
    except RulesError:
        alerts.append({"level": "warning", "code": "rules_expiring", "message": "Statutory payroll rules for the coming financial year are not loaded yet: update the rules file before your first pay run in that year"})
    if not cals:
        alerts.append({"level": "info", "code": "no_calendar", "message": "No pay calendar yet: create one in Settings to start a pay run"})
    out["alerts"] = alerts
    rem = []
    for y in (today.year, today.year + 1):
        for d, label in ((date(y, 2, 28), "Quarterly BAS (PAYG withholding): October-December quarter"), (date(y, 4, 28), "Quarterly BAS (PAYG withholding): January-March quarter"),
                         (date(y, 7, 28), "Quarterly BAS (PAYG withholding): April-June quarter"), (date(y, 10, 28), "Quarterly BAS (PAYG withholding): July-September quarter"),
                         (date(y, 7, 14), "STP finalisation declaration for the financial year ended 30 June")):
            if today <= d and (d - today).days <= 75:
                rem.append({"date": d.isoformat(), "days": (d - today).days, "message": label})
    out["reminders"] = sorted(rem, key=lambda r: r["date"]) + [{"date": None, "days": None, "message": "Payday Super: contributions must reach each fund within 7 business days of payday"}]
    return out
