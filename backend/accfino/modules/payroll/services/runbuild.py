"""Builds the engine's inputs for one employee in one pay run from the database. Pure reads: nothing here writes.
The returned fingerprint changes whenever anything that affects the pay changes - the run uses it to detect a stale calculation."""
import hashlib
import json
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, timedelta
from decimal import Decimal
from typing import Dict, List, Optional

from sqlalchemy import func

from accfino.modules.payroll.engine import payg
from accfino.modules.payroll.engine.calc import EmployeeInput, ItemDef, LineInput, PeriodInput, Ytd
from accfino.modules.payroll.engine.leave import AccrualDef
from accfino.modules.payroll.models.payroll import (PayEmployee, PayEmployeeBank, PayEmployeeItem, PayEmployeeSuper, PayEmployeeTax, PayItem, PayLeaveType,
                                                    PayRun, PayRunEmployee, PayRunInput)
from accfino.modules.payroll.services import leave as leave_svc
from accfino.modules.payroll.services import timesheets as ts_svc

Z = Decimal(0)


def fy_label(d: date, fy_end_month: int = 6) -> str:
    start_year = d.year if d.month > fy_end_month else d.year - 1
    return f"{start_year}-{str(start_year + 1)[2:]}"


def fy_start(d: date, fy_end_month: int = 6) -> date:
    m = fy_end_month % 12 + 1
    y = d.year if d.month >= m else d.year - 1
    return date(y, m, 1)


def item_def(it: PayItem) -> ItemDef:
    return ItemDef(id=it.id, code=it.code, name=it.name, kind=it.kind, calc_method=it.calc_method, rate=it.rate, multiplier=Decimal(it.multiplier or 1),
                   default_amount=it.default_amount, percent=it.percent, taxable=it.taxable, payg_treatment=it.payg_treatment,
                   super_treatment=it.super_treatment, leave_type_id=it.leave_type_id, reportable_fringe=it.reportable_fringe)


@dataclass
class Built:
    emp: EmployeeInput
    period: PeriodInput
    lines: List[LineInput]
    ytd: Ytd
    accrual_defs: List[AccrualDef]
    balances: Dict[str, Decimal]
    notes: List[dict] = field(default_factory=list)       # extra errors / warnings found while building: {"severity", "code", "message"}
    fingerprint: str = ""
    timesheet_line_ids: List[int] = field(default_factory=list)
    leave_request_ids: List[int] = field(default_factory=list)
    leave_hours: Dict[int, Decimal] = field(default_factory=dict)   # leave_type_id -> hours paid in this run


def proration(e: PayEmployee, start: date, end: date) -> Decimal:
    """Share of the period's scheduled hours that fall within employment (new starters / leavers)."""
    probe = PayEmployee(work_pattern=e.work_pattern, hours_per_week=e.hours_per_week, start_date=date(1900, 1, 1), end_date=None)
    full = sum(leave_svc.daily_hours(probe, start, end).values(), Z)
    got = sum(leave_svc.daily_hours(e, start, end).values(), Z)
    if full == 0:
        return Z
    return (got / full).quantize(Decimal("0.000001"))


def ytd_before(db, org, e: PayEmployee, run: PayRun) -> Ytd:
    """Finalised pays (including reversal runs, which net the originals to zero) in the same financial year and strictly before this run, plus opening balances."""
    fym = org.fy_end_month or 6
    fs = fy_start(run.pay_date, fym)
    rows = (db.query(PayRunEmployee, PayRun).join(PayRun, PayRun.id == PayRunEmployee.run_id)
            .filter(PayRunEmployee.employee_id == e.id, PayRunEmployee.org_id == org.id, PayRunEmployee.status == "included",
                    PayRun.status.in_(("finalised", "paid")), PayRun.pay_date >= fs, PayRun.id != run.id,
                    (PayRun.pay_date < run.pay_date) | ((PayRun.pay_date == run.pay_date) & (PayRun.id < (run.id or 10**12)))).all())
    y = Ytd()
    for r, _ in rows:
        y.gross += r.gross; y.taxable += r.taxable; y.tax += r.payg; y.study_loan += r.study_loan
        y.qualifying_earnings += r.qualifying_earnings; y.super_guarantee += r.super_guarantee; y.super_total += r.super_total
        y.salary_sacrifice += r.sacrifice_super; y.deductions += r.pretax_deductions + r.posttax_deductions
        y.reimbursements += r.reimbursements; y.etp_taxable += r.etp_taxable; y.net += r.net
    t = db.get(PayEmployeeTax, e.id)
    op = (t.ytd_opening or {}) if t else {}
    if op.get("fy") == fy_label(run.pay_date, fym):
        g = lambda k: Decimal(str(op.get(k, 0) or 0))
        y.gross += g("gross"); y.taxable += g("taxable"); y.tax += g("tax"); y.study_loan += g("study_loan")
        y.qualifying_earnings += g("qualifying_earnings"); y.super_guarantee += g("super_guarantee"); y.super_total += g("super_total")
        y.salary_sacrifice += g("salary_sacrifice"); y.net += g("net")
    return y


def _ser(o):
    if isinstance(o, Decimal):
        return str(o)
    if isinstance(o, date):
        return o.isoformat()
    raise TypeError(type(o))


def build(db, org, run: PayRun, e: PayEmployee, rules, items_by_code: Dict[str, PayItem], leave_types: List[PayLeaveType]) -> Built:
    tax = db.get(PayEmployeeTax, e.id)
    notes: List[dict] = []
    has_fund = db.query(PayEmployeeSuper.id).filter_by(employee_id=e.id, is_active=True).first() is not None
    dob = e.date_of_birth
    age = None
    if dob:
        ref = min(run.pay_date, e.end_date or run.pay_date)
        age = ref.year - dob.year - ((ref.month, ref.day) < (dob.month, dob.day))
    elif e.status == "terminated":
        notes.append({"severity": "warning", "code": "no_dob", "message": "No date of birth: ETP tax assumes the employee is under preservation age"})
    end_ref = e.end_date or run.pay_date
    years = max(0, int((end_ref - e.start_date).days // 365.25))
    base, loading, adj = items_by_code.get("BASE"), items_by_code.get("LEAVELOAD"), items_by_code.get("SALADJ")
    emp = EmployeeInput(
        employee_id=e.id, employment_type=e.employment_type, pay_basis=e.pay_basis, annual_salary=Decimal(e.annual_salary or 0), hourly_rate=Decimal(e.hourly_rate or 0),
        hours_per_week=Decimal(e.hours_per_week), proration=proration(e, run.period_start, run.period_end),
        tfn_provided=bool(tax and tax.tfn_status in ("provided", "exempt") and (tax.tfn_enc or tax.tfn_status == "exempt")),
        residency=tax.residency if tax else "resident", claims_tft=bool(tax.claims_tft) if tax else True, study_loan=bool(tax and tax.has_study_loan),
        medicare_variation=tax.medicare_variation if tax else "none", tax_offset_annual=Decimal(tax.tax_offset_annual or 0) if tax else Z,
        variation_pct=Decimal(tax.variation_pct) if tax and tax.variation_pct is not None else None, extra_withholding=Decimal(tax.extra_withholding or 0) if tax else Z,
        super_fund_present=has_fund, completed_years_service=years, at_or_over_preservation_age=bool(age is not None and age >= rules.preservation_age),
        base_item=item_def(base) if base else None, loading_item=item_def(loading) if loading else None, adjustment_item=item_def(adj) if adj else None)
    period = PeriodInput(run.frequency, run.period_start, run.period_end, run.pay_date)
    lines: List[LineInput] = []
    built = Built(emp=emp, period=period, lines=lines, ytd=Ytd(), accrual_defs=[], balances={}, notes=notes)   # share the list: issues found below must reach the run
    lt_by_id = {l.id: l for l in leave_types}
    item_for_leave = {}
    for it in items_by_code.values():
        if it.leave_type_id and it.kind in ("leave", "unpaid_leave"):
            item_for_leave.setdefault(it.leave_type_id, it)

    # 1. timesheets (hourly employees)
    ts_leave_types = set()
    if e.pay_basis == "hourly":
        grouped = defaultdict(lambda: [Z, []])
        for l, it in ts_svc.approved_lines(db, org.id, e.id, run.period_start, run.period_end):
            key = (it.id, l.leave_type_id if it.kind == "leave" else None)
            grouped[key][0] += l.hours
            grouped[key][1].append(l.id)
            built.timesheet_line_ids.append(l.id)
            if it.kind == "leave":
                ts_leave_types.add(l.leave_type_id)
        for (item_id, lt_id), (hrs, ids) in grouped.items():
            it = db.get(PayItem, item_id)
            li = LineInput(item_def(it), hours=hrs, source="timesheet", ref=",".join(map(str, ids[:20])))
            if it.kind == "leave":
                li.item = ItemDef(**{**item_def(it).__dict__, "leave_type_id": lt_id})
                li.loading_pct = Decimal(lt_by_id[lt_id].loading_pct) if lt_id in lt_by_id else None
                built.leave_hours[lt_id] = built.leave_hours.get(lt_id, Z) + hrs
            lines.append(li)
        n_unapproved = ts_svc.unapproved_in_period(db, org.id, e.id, run.period_start, run.period_end)
        if n_unapproved:
            notes.append({"severity": "warning", "code": "unapproved_timesheets", "message": f"{n_unapproved} timesheet(s) for this period are not approved and are NOT included"})
        if not grouped and e.pay_standard_hours and "ORD" in items_by_code:
            weeks = Decimal(52) / payg.periods_per_year(run.frequency)
            hrs = (Decimal(e.hours_per_week) * weeks * emp.proration).quantize(Decimal("0.01"))
            if hrs > 0:
                lines.append(LineInput(item_def(items_by_code["ORD"]), hours=hrs, source="standard_hours", note="Standard hours (no timesheet)"))

    # 2. approved leave requests
    for lt_id, info in leave_svc.hours_for_period(db, org.id, e, run.period_start, run.period_end).items():
        lt = lt_by_id.get(lt_id)
        if lt is None or (e.pay_basis == "hourly" and lt_id in ts_leave_types):
            continue                                                  # the timesheet already carries this leave
        it = item_for_leave.get(lt_id)
        if it is None:
            notes.append({"severity": "error", "code": "no_leave_item", "message": f"No pay item is linked to leave type {lt.code}: add one in Pay Items"})
            continue
        li = LineInput(item_def(it), hours=info["hours"], source="leave_request", ref=",".join(map(str, info["requests"])))
        if it.kind == "leave":
            li.loading_pct = Decimal(lt.loading_pct) if lt.loading_pct else None
        lines.append(li)
        built.leave_request_ids += info["requests"]
        if it.kind == "leave":
            built.leave_hours[lt_id] = built.leave_hours.get(lt_id, Z) + info["hours"]

    # 3. recurring items
    for r, it in (db.query(PayEmployeeItem, PayItem).join(PayItem, PayItem.id == PayEmployeeItem.pay_item_id)
                  .filter(PayEmployeeItem.employee_id == e.id, PayEmployeeItem.is_active.is_(True), PayItem.is_active.is_(True)).order_by(PayItem.sort, PayItem.id)):
        if (r.effective_from and r.effective_from > run.period_end) or (r.effective_to and r.effective_to < run.period_start):
            continue
        d = item_def(it)
        if it.calc_method == "hours_x_rate":
            li = LineInput(d, hours=r.hours, rate=r.rate, source="recurring", ref=str(r.id))
        elif it.calc_method.startswith("percent"):
            li = LineInput(d, rate=r.rate if r.rate is not None else it.percent, source="recurring", ref=str(r.id))
        else:
            li = LineInput(d, amount=r.amount if r.amount is not None else it.default_amount, source="recurring", ref=str(r.id))
        lines.append(li)

    # 4. manual inputs entered on the run
    for r in db.query(PayRunInput).filter_by(run_id=run.id, employee_id=e.id).order_by(PayRunInput.id):
        it = db.get(PayItem, r.pay_item_id)
        lines.append(LineInput(item_def(it), hours=r.hours, rate=r.rate, amount=r.amount, source="manual", ref=str(r.id), note=r.note or "",
                               leave_pre1993=r.leave_pre1993, genuine_redundancy=r.genuine_redundancy, periods=r.periods,
                               loading_pct=None))

    built.ytd = ytd_before(db, org, e, run)
    for lt in leave_types:
        if lt.accrual_method != "none":
            built.accrual_defs.append(AccrualDef(lt.id, lt.code, lt.accrual_method, Decimal(lt.accrual_annual_hours), list(lt.applies_to or []),
                                                 lt.accrue_on_paid_leave, Decimal(lt.max_balance) if lt.max_balance is not None else None))
    bal = leave_svc.balances(db, org.id, e.id)          # the current ledger balance (earlier pays' accruals and any adjustments count)
    built.balances = {lt.code: bal.get(lt.id, Z) for lt in leave_types}
    for lt_id, hrs in built.leave_hours.items():
        lt = lt_by_id[lt_id]
        if not lt.allow_negative and lt.is_paid and bal.get(lt_id, Z) - hrs < 0:
            notes.append({"severity": "error", "code": "leave_balance", "message": f"{lt.name}: {hrs} hours would take the balance below zero (balance {bal.get(lt_id, Z):.2f})"})
    built.fingerprint = _fingerprint(built, e, tax)
    return built


def _fingerprint(b: Built, e: PayEmployee, tax) -> str:
    payload = {"emp": {k: v for k, v in b.emp.__dict__.items() if k not in ("base_item", "loading_item", "adjustment_item")},
               "period": b.period.__dict__, "ytd": b.ytd.__dict__, "balances": b.balances,
               "lines": [{"item": l.item.__dict__, "h": l.hours, "r": l.rate, "a": l.amount, "load": l.loading_pct, "src": l.source, "ref": l.ref, "p1993": l.leave_pre1993,
                          "gr": l.genuine_redundancy, "per": l.periods} for l in b.lines],
               "accrual": [a.__dict__ for a in b.accrual_defs], "notes": b.notes}
    return hashlib.sha256(json.dumps(payload, sort_keys=True, default=_ser).encode()).hexdigest()
