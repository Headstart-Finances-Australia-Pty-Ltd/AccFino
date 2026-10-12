"""Payroll reports. Every report reads FINALISED pay data (finalised, paid and the reversal runs that net them out), supports date / employee / department / pay-run
filters, returns {columns, rows, totals, control} and exports to CSV. `control` reconciles the report's total to an independent source (payroll lines, payslips,
ledger journal or super contributions) so a tester can prove the report agrees with the transactions behind it."""
import csv
import io
from collections import defaultdict
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Callable, Optional

from sqlalchemy import func

from accfino.modules.payroll.models.payroll import (PayAudit, PayCalendar, PayDepartment, PayEmployee, PayItem, PayJournal, PayJournalLine, PayLeaveType, PayPayslip,
                                                    PayRun, PayRunEmployee, PayRunLine, PaySuperContribution, PaySuperFund, PayTimesheet, PayTimesheetLine)
from accfino.modules.payroll.services import leave as leave_svc, runbuild
from accfino.modules.payroll.services.errors import NotFound, PayrollError

Z = Decimal(0)
EARN = {"earnings", "overtime", "penalty", "allowance", "bonus", "commission", "back_pay", "leave", "leave_loading", "termination_leave", "etp", "salary_adjustment", "unpaid_leave"}
DEDUCT = {"deduction_pretax", "deduction_posttax", "salary_sacrifice_super", "employee_super_after_tax"}


@dataclass
class Filters:
    date_from: Optional[date] = None
    date_to: Optional[date] = None
    employee_id: int = 0
    department_id: int = 0
    run_id: int = 0


def _s(v):
    return str(v if v is not None else 0)


def _rows(db, ctx, f: Filters):
    q = (db.query(PayRunEmployee, PayRun).join(PayRun, PayRun.id == PayRunEmployee.run_id)
         .filter(PayRun.org_id == ctx.org.id, PayRun.status.in_(("finalised", "paid")), PayRunEmployee.status == "included"))
    if f.date_from:
        q = q.filter(PayRun.pay_date >= f.date_from)
    if f.date_to:
        q = q.filter(PayRun.pay_date <= f.date_to)
    if f.employee_id:
        q = q.filter(PayRunEmployee.employee_id == f.employee_id)
    if f.department_id:
        q = q.filter(PayRunEmployee.department_id == f.department_id)
    if f.run_id:
        q = q.filter(PayRun.id == f.run_id)
    return q.order_by(PayRun.pay_date, PayRun.id, PayRunEmployee.employee_number).all()


def _lines(db, ctx, f: Filters, kinds=None):
    q = (db.query(PayRunLine, PayRun, PayRunEmployee).join(PayRun, PayRun.id == PayRunLine.run_id).join(PayRunEmployee, PayRunEmployee.id == PayRunLine.run_employee_id)
         .filter(PayRun.org_id == ctx.org.id, PayRun.status.in_(("finalised", "paid"))))
    if kinds:
        q = q.filter(PayRunLine.kind.in_(kinds))
    if f.date_from:
        q = q.filter(PayRun.pay_date >= f.date_from)
    if f.date_to:
        q = q.filter(PayRun.pay_date <= f.date_to)
    if f.employee_id:
        q = q.filter(PayRunLine.employee_id == f.employee_id)
    if f.department_id:
        q = q.filter(PayRunEmployee.department_id == f.department_id)
    if f.run_id:
        q = q.filter(PayRun.id == f.run_id)
    return q.order_by(PayRun.pay_date, PayRunLine.employee_id, PayRunLine.line_no).all()


def _col(key, label, typ="text"):
    return {"key": key, "label": label, "type": typ}


M = "money"
H = "hours"


def _rep(key, title, cols, rows, totals=None, control=None, note=""):
    return {"key": key, "title": title, "columns": cols, "rows": rows, "totals": totals or {}, "control": control, "note": note, "row_count": len(rows)}


def _sum(rows, k):
    return sum((Decimal(str(r.get(k) or 0)) for r in rows), Z)


def _ctl(label, report_total, source_total, source):
    d = Decimal(str(report_total)) - Decimal(str(source_total))
    return {"label": label, "report": _s(report_total), "source": _s(source_total), "difference": _s(d), "reconciled": d == 0, "source_name": source}


# ---- 1-5 core ---------------------------------------------------------------------------------------------------------------------
def payroll_summary(db, ctx, f):
    runs = defaultdict(lambda: dict(employees=0, gross=Z, payg=Z, study_loan=Z, deductions=Z, sacrifice=Z, reimbursements=Z, net=Z, super=Z, cost=Z))
    meta = {}
    for r, run in _rows(db, ctx, f):
        d = runs[run.id]
        meta[run.id] = run
        d["employees"] += 1
        d["gross"] += r.gross; d["payg"] += r.payg; d["study_loan"] += r.study_loan; d["deductions"] += r.pretax_deductions + r.posttax_deductions
        d["sacrifice"] += r.sacrifice_super; d["reimbursements"] += r.reimbursements; d["net"] += r.net; d["super"] += r.super_total; d["cost"] += r.employer_cost
    rows = [dict(run_no=meta[i].run_no, type=meta[i].run_type, period=f"{meta[i].period_start.isoformat()} to {meta[i].period_end.isoformat()}", pay_date=meta[i].pay_date.isoformat(),
                 status=meta[i].status, **{k: (v if k == "employees" else _s(v)) for k, v in d.items()}) for i, d in runs.items()]
    rows.sort(key=lambda x: (x["pay_date"], x["run_no"]))
    tot = {k: _s(_sum(rows, k)) for k in ("gross", "payg", "study_loan", "deductions", "sacrifice", "reimbursements", "net", "super", "cost")}
    line_gross = sum((l.amount for l, run, re_ in _lines(db, ctx, f, EARN)), Z)
    slip_net = sum((Decimal(p.snapshot["totals"]["net"]) for p in db.query(PayPayslip).join(PayRun, PayRun.id == PayPayslip.run_id).filter(
        PayRun.org_id == ctx.org.id, *( [PayRun.pay_date >= f.date_from] if f.date_from else []), *( [PayRun.pay_date <= f.date_to] if f.date_to else []),
        *( [PayPayslip.employee_id == f.employee_id] if f.employee_id else []), *( [PayRun.id == f.run_id] if f.run_id else []))), Z) if not f.department_id else None
    ctl = [_ctl("Gross = sum of payroll earnings lines", tot["gross"], line_gross, "pay_run_lines")]
    if slip_net is not None:
        ctl.append(_ctl("Net (excluding reversal runs) = sum of payslips", _sum([r for r in rows if r["type"] != "reversal"], "net"), slip_net, "payslips"))
    return _rep("payroll_summary", "Payroll Summary", [_col("run_no", "Pay run"), _col("period", "Period"), _col("pay_date", "Pay date"), _col("employees", "Employees", "int"), _col("gross", "Gross", M),
                _col("payg", "PAYG", M), _col("study_loan", "Study loan", M), _col("deductions", "Deductions", M), _col("net", "Net pay", M), _col("super", "Super", M), _col("cost", "Employer cost", M)],
                rows, tot, ctl)


def payroll_register(db, ctx, f):
    rows = [dict(pay_date=run.pay_date.isoformat(), run_no=run.run_no, employee_number=r.employee_number, employee=r.employee_name, gross=_s(r.gross), taxable=_s(r.taxable), payg=_s(r.payg),
                 study_loan=_s(r.study_loan), deductions=_s(r.pretax_deductions + r.posttax_deductions), sacrifice=_s(r.sacrifice_super), reimbursements=_s(r.reimbursements), net=_s(r.net),
                 super=_s(r.super_total)) for r, run in _rows(db, ctx, f)]
    tot = {k: _s(_sum(rows, k)) for k in ("gross", "taxable", "payg", "study_loan", "deductions", "sacrifice", "reimbursements", "net", "super")}
    return _rep("payroll_register", "Payroll Register", [_col("pay_date", "Pay date"), _col("run_no", "Run"), _col("employee_number", "No."), _col("employee", "Employee"), _col("gross", "Gross", M),
                _col("taxable", "Taxable", M), _col("payg", "PAYG", M), _col("study_loan", "Study loan", M), _col("deductions", "Deductions", M), _col("net", "Net", M), _col("super", "Super", M)],
                rows, tot, [_ctl("Gross = payroll lines", tot["gross"], sum((l.amount for l, _, _ in _lines(db, ctx, f, EARN)), Z), "pay_run_lines")])


def employee_payroll(db, ctx, f):
    agg = defaultdict(lambda: dict(runs=0, gross=Z, payg=Z, deductions=Z, net=Z, super=Z, hours=Z))
    names = {}
    for r, run in _rows(db, ctx, f):
        a = agg[r.employee_id]
        names[r.employee_id] = (r.employee_number, r.employee_name)
        a["runs"] += 1; a["gross"] += r.gross; a["payg"] += r.payg + r.study_loan; a["deductions"] += r.pretax_deductions + r.posttax_deductions + r.sacrifice_super
        a["net"] += r.net; a["super"] += r.super_total; a["hours"] += r.ordinary_hours + r.overtime_hours + r.leave_hours
    rows = [dict(employee_number=names[i][0], employee=names[i][1], pays=a["runs"], hours=_s(a["hours"]), gross=_s(a["gross"]), tax=_s(a["payg"]), deductions=_s(a["deductions"]),
                 net=_s(a["net"]), super=_s(a["super"])) for i, a in sorted(agg.items(), key=lambda kv: names[kv[0]][0])]
    tot = {k: _s(_sum(rows, k)) for k in ("gross", "tax", "deductions", "net", "super", "hours")}
    return _rep("employee_payroll", "Employee Payroll Report", [_col("employee_number", "No."), _col("employee", "Employee"), _col("pays", "Pays", "int"), _col("hours", "Hours", H), _col("gross", "Gross", M),
                _col("tax", "Tax withheld", M), _col("deductions", "Deductions", M), _col("net", "Net", M), _col("super", "Super", M)], rows, tot,
                [_ctl("Gross = payroll lines", tot["gross"], sum((l.amount for l, _, _ in _lines(db, ctx, f, EARN)), Z), "pay_run_lines")])


def gross_to_net(db, ctx, f):
    rows = []
    for r, run in _rows(db, ctx, f):
        calc = r.gross - r.sacrifice_super - r.pretax_deductions - r.payg - r.study_loan - r.posttax_deductions + r.reimbursements
        rows.append(dict(pay_date=run.pay_date.isoformat(), employee_number=r.employee_number, employee=r.employee_name, gross=_s(r.gross), sacrifice=_s(-r.sacrifice_super), pretax=_s(-r.pretax_deductions),
                         payg=_s(-r.payg), study_loan=_s(-r.study_loan), posttax=_s(-r.posttax_deductions), reimbursements=_s(r.reimbursements), net=_s(r.net), check=_s(calc - r.net)))
    tot = {k: _s(_sum(rows, k)) for k in ("gross", "sacrifice", "pretax", "payg", "study_loan", "posttax", "reimbursements", "net")}
    return _rep("gross_to_net", "Gross-to-Net Report", [_col("pay_date", "Pay date"), _col("employee_number", "No."), _col("employee", "Employee"), _col("gross", "Gross", M), _col("sacrifice", "Salary sacrifice", M),
                _col("pretax", "Pre-tax ded.", M), _col("payg", "PAYG", M), _col("study_loan", "Study loan", M), _col("posttax", "Post-tax ded.", M), _col("reimbursements", "Reimb.", M), _col("net", "Net pay", M)],
                rows, tot, [_ctl("Every row: gross less deductions and tax equals net (sum of differences)", _sum(rows, "check"), 0, "recomputed from components")])


def payg_withholding(db, ctx, f):
    rows = [dict(pay_date=run.pay_date.isoformat(), run_no=run.run_no, employee_number=r.employee_number, employee=r.employee_name, scale=r.tax_scale or "", taxable=_s(r.taxable), payg=_s(r.payg), study_loan=_s(r.study_loan),
                 total=_s(r.payg + r.study_loan)) for r, run in _rows(db, ctx, f)]
    tot = {k: _s(_sum(rows, k)) for k in ("taxable", "payg", "study_loan", "total")}
    jl = db.query(func.coalesce(func.sum(PayJournalLine.credit - PayJournalLine.debit), 0)).join(PayJournal, PayJournal.id == PayJournalLine.pay_journal_id).join(PayRun, PayRun.id == PayJournal.run_id) \
        .filter(PayRun.org_id == ctx.org.id, PayJournalLine.component == "payg")
    if f.date_from: jl = jl.filter(PayRun.pay_date >= f.date_from)
    if f.date_to: jl = jl.filter(PayRun.pay_date <= f.date_to)
    if f.employee_id: jl = jl.filter(PayJournalLine.employee_id == f.employee_id)
    if f.run_id: jl = jl.filter(PayRun.id == f.run_id)
    ctl = [] if f.department_id else [_ctl("PAYG total = credits to PAYG Withholdings Payable in the payroll journals", tot["total"], Decimal(str(jl.scalar())), "payroll journal")]
    return _rep("payg_withholding", "PAYG Withholding Report", [_col("pay_date", "Pay date"), _col("run_no", "Run"), _col("employee_number", "No."), _col("employee", "Employee"), _col("scale", "Scale"),
                _col("taxable", "Taxable", M), _col("payg", "PAYG", M), _col("study_loan", "Study loan", M), _col("total", "Total withheld", M)], rows, tot, ctl,
                note="Amounts withheld are reported on your BAS (W2). Study and training loan amounts are included in the total.")


# ---- 6 super ----------------------------------------------------------------------------------------------------------------------
def superannuation(db, ctx, f):
    q = (db.query(PaySuperContribution, PaySuperFund, PayEmployee, PayRun).join(PaySuperFund, PaySuperFund.id == PaySuperContribution.fund_id)
         .join(PayEmployee, PayEmployee.id == PaySuperContribution.employee_id).join(PayRun, PayRun.id == PaySuperContribution.run_id)
         .filter(PaySuperContribution.org_id == ctx.org.id, PaySuperContribution.status != "reversed", PayRun.status.in_(("finalised", "paid"))))
    if f.date_from: q = q.filter(PayRun.pay_date >= f.date_from)
    if f.date_to: q = q.filter(PayRun.pay_date <= f.date_to)
    if f.employee_id: q = q.filter(PaySuperContribution.employee_id == f.employee_id)
    if f.department_id: q = q.filter(PayEmployee.department_id == f.department_id)
    if f.run_id: q = q.filter(PayRun.id == f.run_id)
    rows = [dict(pay_date=run.pay_date.isoformat(), employee_number=e.employee_number, employee=f"{e.first_name} {e.last_name}", fund=fd.name, component=c.component.replace("_", " "), qualifying_earnings=_s(c.qualifying_earnings),
                 amount=_s(c.amount), due_date=c.due_date.isoformat(), status=c.status) for c, fd, e, run in q.order_by(PayRun.pay_date, PayEmployee.employee_number, PaySuperContribution.id)]
    tot = {"amount": _s(_sum(rows, "amount")), "qualifying_earnings": _s(_sum(rows, "qualifying_earnings"))}
    rr = _rows(db, ctx, f)
    return _rep("superannuation", "Superannuation Report", [_col("pay_date", "Pay date"), _col("employee_number", "No."), _col("employee", "Employee"), _col("fund", "Fund"), _col("component", "Component"),
                _col("qualifying_earnings", "Qualifying earnings", M), _col("amount", "Amount", M), _col("due_date", "Due"), _col("status", "Status")], rows, tot,
                [_ctl("Contributions = super in the pay runs (excluding runs reversed)", tot["amount"], sum((r.super_total for r, run in rr if run.run_type != "reversal" and not run.reversed_by_run_id), Z), "pay runs")])


# ---- 7-8 leave --------------------------------------------------------------------------------------------------------------------
def _employees(db, ctx, f):
    q = db.query(PayEmployee).filter(PayEmployee.org_id == ctx.org.id)
    if f.employee_id: q = q.filter(PayEmployee.id == f.employee_id)
    if f.department_id: q = q.filter(PayEmployee.department_id == f.department_id)
    return q.order_by(PayEmployee.employee_number).all()


def leave_balance(db, ctx, f):
    as_at = f.date_to or date.today()
    lts = {l.id: l for l in db.query(PayLeaveType).filter_by(org_id=ctx.org.id)}
    rows = []
    for e in _employees(db, ctx, f):
        for lt_id, h in sorted(leave_svc.balances(db, ctx.org.id, e.id, as_at).items(), key=lambda kv: lts[kv[0]].code):
            if h != 0:
                rows.append(dict(employee_number=e.employee_number, employee=f"{e.first_name} {e.last_name}", status=e.status, leave_type=lts[lt_id].name, balance=_s(h.quantize(Decimal("0.01")))))
    return _rep("leave_balance", "Leave Balance Report", [_col("employee_number", "No."), _col("employee", "Employee"), _col("status", "Status"), _col("leave_type", "Leave type"), _col("balance", "Hours", H)],
                rows, {"balance": _s(_sum(rows, "balance"))}, None, note=f"Balances as at {as_at.isoformat()} from the leave ledger (accruals less leave taken, plus adjustments).")


def leave_liability(db, ctx, f):
    as_at = f.date_to or date.today()
    lts = {l.id: l for l in db.query(PayLeaveType).filter_by(org_id=ctx.org.id)}
    from accfino.modules.payroll.engine.rules import RulesError, rulebook
    rule = None
    try:
        rule = rulebook().for_date(as_at)
    except RulesError:                      # no statutory rules for this date: the super on-cost is NOT estimated (and the report says so)
        rule = None
    sg = rule.sg_rate if rule else Z
    rows = []
    for e in _employees(db, ctx, f):
        if e.status == "terminated" and not (e.end_date and e.end_date >= as_at):
            continue
        rate = (Decimal(e.hourly_rate) if e.pay_basis == "hourly" else Decimal(e.annual_salary or 0) / (52 * Decimal(e.hours_per_week))) if (e.hourly_rate or e.annual_salary) else Z
        for lt_id, h in leave_svc.balances(db, ctx.org.id, e.id, as_at).items():
            lt = lts[lt_id]
            if lt.category not in ("annual", "long_service") or h <= 0:
                continue
            base = (h * rate).quantize(Decimal("0.01"))
            load = (base * Decimal(lt.loading_pct) / 100).quantize(Decimal("0.01"))
            sup = ((base + load) * sg).quantize(Decimal("0.01")) if lt.category == "annual" else Z
            rows.append(dict(employee_number=e.employee_number, employee=f"{e.first_name} {e.last_name}", leave_type=lt.name, hours=_s(h.quantize(Decimal("0.01"))), rate=_s(rate.quantize(Decimal("0.0001"))),
                             value=_s(base), loading=_s(load), super=_s(sup), total=_s(base + load + sup)))
    tot = {k: _s(_sum(rows, k)) for k in ("hours", "value", "loading", "super", "total")}
    return _rep("leave_liability", "Leave Liability Report", [_col("employee_number", "No."), _col("employee", "Employee"), _col("leave_type", "Leave type"), _col("hours", "Hours", H), _col("rate", "Hourly rate", M),
                _col("value", "Value", M), _col("loading", "Loading", M), _col("super", "Super on-cost", M), _col("total", "Total liability", M)], rows, tot, None,
                note=f"Annual and long service leave at current pay rates as at {as_at.isoformat()}, plus leave loading and super on-cost. A management estimate, not a ledger balance."
                     + ("" if rule else " NO STATUTORY RULES COVER THIS DATE: the super on-cost is not included."))


# ---- 9 timesheets -----------------------------------------------------------------------------------------------------------------
def timesheet_report(db, ctx, f):
    q = (db.query(PayTimesheetLine, PayTimesheet, PayEmployee, PayItem).join(PayTimesheet, PayTimesheet.id == PayTimesheetLine.timesheet_id)
         .join(PayEmployee, PayEmployee.id == PayTimesheet.employee_id).join(PayItem, PayItem.id == PayTimesheetLine.pay_item_id).filter(PayTimesheet.org_id == ctx.org.id))
    if f.date_from: q = q.filter(PayTimesheetLine.work_date >= f.date_from)
    if f.date_to: q = q.filter(PayTimesheetLine.work_date <= f.date_to)
    if f.employee_id: q = q.filter(PayTimesheet.employee_id == f.employee_id)
    if f.department_id: q = q.filter(PayEmployee.department_id == f.department_id)
    rows = [dict(work_date=l.work_date.isoformat(), employee_number=e.employee_number, employee=f"{e.first_name} {e.last_name}", pay_category=it.name, hours=_s(l.hours), break_minutes=l.break_minutes,
                 status=ts.status, notes=l.notes or "") for l, ts, e, it in q.order_by(PayTimesheetLine.work_date, PayEmployee.employee_number)]
    return _rep("timesheet", "Timesheet Report", [_col("work_date", "Date"), _col("employee_number", "No."), _col("employee", "Employee"), _col("pay_category", "Pay category"), _col("hours", "Hours", H),
                _col("break_minutes", "Break (min)", "int"), _col("status", "Status"), _col("notes", "Notes")], rows, {"hours": _s(_sum(rows, "hours"))})


# ---- 10-11 deductions, earnings ---------------------------------------------------------------------------------------------------
def _by_item(db, ctx, f, kinds, key, title, label):
    agg = defaultdict(lambda: [Z, Z, set()])
    for l, run, re_ in _lines(db, ctx, f, kinds):
        k = (l.code, l.name, l.kind, l.employee_id, re_.employee_number, re_.employee_name)
        agg[k][0] += l.amount
        agg[k][1] += l.hours or Z
    rows = [dict(code=k[0], item=k[1], type=k[2].replace("_", " "), employee_number=k[4], employee=k[5], hours=_s(v[1]), amount=_s(v[0])) for k, v in sorted(agg.items(), key=lambda kv: (kv[0][0], kv[0][4]))]
    tot = {"amount": _s(_sum(rows, "amount")), "hours": _s(_sum(rows, "hours"))}
    return _rep(key, title, [_col("code", "Code"), _col("item", label), _col("type", "Type"), _col("employee_number", "No."), _col("employee", "Employee"), _col("hours", "Hours", H), _col("amount", "Amount", M)], rows, tot,
                [_ctl(f"{label} total = payroll lines", tot["amount"], sum((l.amount for l, _, _ in _lines(db, ctx, f, kinds)), Z), "pay_run_lines")])


def deductions(db, ctx, f):
    return _by_item(db, ctx, f, DEDUCT, "deductions", "Deduction Report", "Deduction")


def earnings(db, ctx, f):
    return _by_item(db, ctx, f, EARN, "earnings", "Earnings Report", "Earnings item")


# ---- 12 journal -------------------------------------------------------------------------------------------------------------------
def payroll_journal(db, ctx, f):
    q = (db.query(PayJournalLine, PayJournal, PayRun).join(PayJournal, PayJournal.id == PayJournalLine.pay_journal_id).join(PayRun, PayRun.id == PayJournal.run_id).filter(PayRun.org_id == ctx.org.id))
    if f.date_from: q = q.filter(PayRun.pay_date >= f.date_from)
    if f.date_to: q = q.filter(PayRun.pay_date <= f.date_to)
    if f.run_id: q = q.filter(PayRun.id == f.run_id)
    if f.employee_id: q = q.filter(PayJournalLine.employee_id == f.employee_id)
    agg = defaultdict(lambda: [Z, Z])
    for l, pj, run in q:
        k = (run.run_no, run.pay_date.isoformat(), l.account_code, l.account_name, pj.ledger_journal_id)
        agg[k][0] += l.debit; agg[k][1] += l.credit
    rows = [dict(run_no=k[0], pay_date=k[1], account=f"{k[2]} {k[3]}", ledger_journal=k[4], debit=_s(v[0]), credit=_s(v[1])) for k, v in sorted(agg.items())]
    tot = {"debit": _s(_sum(rows, "debit")), "credit": _s(_sum(rows, "credit"))}
    return _rep("payroll_journal", "Payroll Journal", [_col("run_no", "Pay run"), _col("pay_date", "Date"), _col("account", "Account"), _col("ledger_journal", "Ledger journal #", "int"), _col("debit", "Debit", M), _col("credit", "Credit", M)],
                rows, tot, [_ctl("Total debits = total credits", tot["debit"], tot["credit"], "journal balance")])


# ---- 13-15 cost -------------------------------------------------------------------------------------------------------------------
def _cost(db, ctx, f, keyfn, labels, key, title):
    agg = defaultdict(lambda: dict(gross=Z, super=Z, reimb=Z, cost=Z, n=set()))
    for r, run in _rows(db, ctx, f):
        k = keyfn(r, run)
        a = agg[k]
        a["gross"] += r.gross; a["super"] += r.super_guarantee + r.super_additional; a["reimb"] += r.reimbursements; a["cost"] += r.employer_cost; a["n"].add(r.employee_id)
    rows = [dict(group=k, employees=len(v["n"]), gross=_s(v["gross"]), super=_s(v["super"]), reimbursements=_s(v["reimb"]), cost=_s(v["cost"])) for k, v in sorted(agg.items(), key=lambda kv: str(kv[0]))]
    tot = {k: _s(_sum(rows, k)) for k in ("gross", "super", "reimbursements", "cost")}
    return _rep(key, title, [_col("group", labels), _col("employees", "Employees", "int"), _col("gross", "Gross wages", M), _col("super", "Employer super", M), _col("reimbursements", "Reimbursements", M), _col("cost", "Employer cost", M)],
                rows, tot, [_ctl("Total cost = sum of pay runs' employer cost", tot["cost"], sum((r.employer_cost for r, _ in _rows(db, ctx, f)), Z), "pay runs")])


def cost_by_department(db, ctx, f):
    d = {x.id: x.name for x in db.query(PayDepartment).filter_by(org_id=ctx.org.id)}
    return _cost(db, ctx, f, lambda r, run: d.get(r.department_id, "(No department)"), "Department", "cost_by_department", "Payroll Cost by Department")


def cost_by_employee(db, ctx, f):
    return _cost(db, ctx, f, lambda r, run: f"{r.employee_number} {r.employee_name}", "Employee", "cost_by_employee", "Payroll Cost by Employee")


def cost_by_period(db, ctx, f):
    return _cost(db, ctx, f, lambda r, run: f"{run.pay_date.isoformat()} ({run.period_start.isoformat()} to {run.period_end.isoformat()})", "Pay period", "cost_by_period", "Payroll Cost by Pay Period")


# ---- 16 YTD -----------------------------------------------------------------------------------------------------------------------
def ytd(db, ctx, f):
    as_at = f.date_to or date.today()
    fym = ctx.org.fy_end_month or 6
    fs = runbuild.fy_start(as_at, fym)
    f2 = Filters(date_from=fs, date_to=as_at, employee_id=f.employee_id, department_id=f.department_id)
    agg = defaultdict(lambda: dict(gross=Z, taxable=Z, tax=Z, sacrifice=Z, deductions=Z, net=Z, super=Z, pays=0))
    names = {}
    for r, run in _rows(db, ctx, f2):
        a = agg[r.employee_id]; names[r.employee_id] = (r.employee_number, r.employee_name)
        a["gross"] += r.gross; a["taxable"] += r.taxable; a["tax"] += r.payg + r.study_loan; a["sacrifice"] += r.sacrifice_super
        a["deductions"] += r.pretax_deductions + r.posttax_deductions; a["net"] += r.net; a["super"] += r.super_total; a["pays"] += 1
    rows = [dict(employee_number=names[i][0], employee=names[i][1], pays=a["pays"], gross=_s(a["gross"]), taxable=_s(a["taxable"]), tax=_s(a["tax"]), sacrifice=_s(a["sacrifice"]),
                 deductions=_s(a["deductions"]), net=_s(a["net"]), super=_s(a["super"])) for i, a in sorted(agg.items(), key=lambda kv: names[kv[0]][0])]
    tot = {k: _s(_sum(rows, k)) for k in ("gross", "taxable", "tax", "sacrifice", "deductions", "net", "super")}
    return _rep("ytd", "Year-to-Date Payroll Report", [_col("employee_number", "No."), _col("employee", "Employee"), _col("pays", "Pays", "int"), _col("gross", "Gross", M), _col("taxable", "Taxable", M), _col("tax", "Tax withheld", M),
                _col("sacrifice", "Salary sacrifice", M), _col("deductions", "Deductions", M), _col("net", "Net", M), _col("super", "Super", M)], rows, tot,
                [_ctl("YTD gross = payroll lines for the year", tot["gross"], sum((l.amount for l, _, _ in _lines(db, ctx, f2, EARN)), Z), "pay_run_lines")],
                note=f"Financial year from {fs.isoformat()} to {as_at.isoformat()}. Opening balances migrated into the system are not included here; payslip YTD figures include them.")


# ---- 17 termination ---------------------------------------------------------------------------------------------------------------
def termination(db, ctx, f):
    q = db.query(PayEmployee).filter(PayEmployee.org_id == ctx.org.id, PayEmployee.status == "terminated")
    if f.date_from: q = q.filter(PayEmployee.end_date >= f.date_from)
    if f.date_to: q = q.filter(PayEmployee.end_date <= f.date_to)
    if f.employee_id: q = q.filter(PayEmployee.id == f.employee_id)
    if f.department_id: q = q.filter(PayEmployee.department_id == f.department_id)
    rows = []
    for e in q.order_by(PayEmployee.end_date):
        sums = db.query(PayRunLine.kind, func.coalesce(func.sum(PayRunLine.amount), 0)).join(PayRun, PayRun.id == PayRunLine.run_id).filter(
            PayRunLine.employee_id == e.id, PayRun.status.in_(("finalised", "paid")), PayRunLine.kind.in_(("termination_leave", "etp"))).group_by(PayRunLine.kind).all()
        sm = {k: Decimal(str(v)) for k, v in sums}
        bal = sum((h for h in leave_svc.balances(db, ctx.org.id, e.id).values() if h > 0), Z)
        last = db.query(func.max(PayRun.pay_date)).join(PayRunEmployee, PayRunEmployee.run_id == PayRun.id).filter(PayRunEmployee.employee_id == e.id, PayRun.status.in_(("finalised", "paid"))).scalar()
        rows.append(dict(employee_number=e.employee_number, employee=f"{e.first_name} {e.last_name}", start_date=e.start_date.isoformat(), end_date=e.end_date.isoformat() if e.end_date else "", reason=e.termination_reason or "",
                         last_pay=last.isoformat() if last else "", unused_leave_paid=_s(sm.get("termination_leave", Z)), etp=_s(sm.get("etp", Z)), leave_balance_remaining=_s(bal.quantize(Decimal("0.01")))))
    return _rep("termination", "Termination Report", [_col("employee_number", "No."), _col("employee", "Employee"), _col("start_date", "Start"), _col("end_date", "End"), _col("reason", "Reason"), _col("last_pay", "Last pay"),
                _col("unused_leave_paid", "Unused leave paid", M), _col("etp", "ETP", M), _col("leave_balance_remaining", "Leave still on balance (h)", H)], rows,
                {"unused_leave_paid": _s(_sum(rows, "unused_leave_paid")), "etp": _s(_sum(rows, "etp"))}, None,
                note="A leave balance remaining after termination usually means unused leave still needs to be paid out.")


# ---- 18 audit ---------------------------------------------------------------------------------------------------------------------
def audit_report(db, ctx, f, limit=1000):
    q = db.query(PayAudit).filter(PayAudit.org_id == ctx.org.id)
    if f.date_from: q = q.filter(PayAudit.occurred_at >= f.date_from)
    if f.date_to: q = q.filter(PayAudit.occurred_at < date.fromordinal(f.date_to.toordinal() + 1))
    rows = [dict(occurred_at=a.occurred_at.strftime("%Y-%m-%d %H:%M:%S"), user=a.username or "", action=a.action, entity=f"{a.entity_type} {a.entity_label or a.entity_id or ''}".strip(), summary=a.summary or "")
            for a in q.order_by(PayAudit.id.desc()).limit(limit)]
    return _rep("audit", "Payroll Audit Report", [_col("occurred_at", "When (UTC)"), _col("user", "User"), _col("action", "Action"), _col("entity", "Record"), _col("summary", "Summary")], rows, {}, None,
                note=f"Most recent {limit} events. Open Audit Trail for before/after values.")


REPORTS = {
    "payroll_summary": ("Payroll Summary", payroll_summary), "payroll_register": ("Payroll Register", payroll_register), "employee_payroll": ("Employee Payroll Report", employee_payroll),
    "gross_to_net": ("Gross-to-Net Report", gross_to_net), "payg_withholding": ("PAYG Withholding Report", payg_withholding), "superannuation": ("Superannuation Report", superannuation),
    "leave_balance": ("Leave Balance Report", leave_balance), "leave_liability": ("Leave Liability Report", leave_liability), "timesheet": ("Timesheet Report", timesheet_report),
    "deductions": ("Deduction Report", deductions), "earnings": ("Earnings Report", earnings), "payroll_journal": ("Payroll Journal", payroll_journal),
    "cost_by_department": ("Payroll Cost by Department", cost_by_department), "cost_by_employee": ("Payroll Cost by Employee", cost_by_employee), "cost_by_period": ("Payroll Cost by Pay Period", cost_by_period),
    "ytd": ("Year-to-Date Payroll Report", ytd), "termination": ("Termination Report", termination), "audit": ("Payroll Audit Report", audit_report),
}


def catalogue() -> list:
    return [{"key": k, "title": t} for k, (t, _) in REPORTS.items()]


def run_report(db, ctx, access, key: str, f: Filters) -> dict:
    access.require("audit_view" if key == "audit" else "reports_view")
    if key not in REPORTS:
        raise NotFound("Report")
    if f.date_from and f.date_to and f.date_from > f.date_to:
        raise PayrollError("The 'from' date is after the 'to' date")
    if f.employee_id and not db.query(PayEmployee.id).filter_by(id=f.employee_id, org_id=ctx.org.id).first():
        raise PayrollError("Employee not found")
    out = REPORTS[key][1](db, ctx, f)
    out["filters"] = {"date_from": f.date_from.isoformat() if f.date_from else None, "date_to": f.date_to.isoformat() if f.date_to else None, "employee_id": f.employee_id or None,
                      "department_id": f.department_id or None, "run_id": f.run_id or None}
    return out


def to_csv(rep: dict) -> str:
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow([rep["title"]])
    w.writerow(["Filters"] + [f"{k}={v}" for k, v in rep["filters"].items() if v])
    w.writerow([c["label"] for c in rep["columns"]])
    for r in rep["rows"]:
        w.writerow([_safe(r.get(c["key"], "")) for c in rep["columns"]])
    if rep["totals"]:
        w.writerow(["Totals"] + [rep["totals"].get(c["key"], "") for c in rep["columns"][1:]])
    return buf.getvalue()


def _safe(v):
    """Neutralise spreadsheet formula injection in exported text."""
    s = "" if v is None else str(v)
    return "'" + s if s[:1] in ("=", "+", "@") or (s[:1] == "-" and not s[1:2].isdigit() and not s[1:2] == ".") else s
