"""calculate_employee(): one employee, one pay period -> a complete, deterministic PayResult. No database, no clock, no I/O.

Order: lines -> gross -> taxable -> PAYG (+ study loan) -> super -> deductions -> net -> YTD -> leave accruals -> validation."""
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from typing import Dict, List, Optional

from accfino.modules.payroll.engine import payg
from accfino.modules.payroll.engine.leave import AccrualDef, accrual_hours
from accfino.modules.payroll.engine.money import ZERO, D, r2, r_dollar
from accfino.modules.payroll.engine.rules import RuleSet
from accfino.modules.payroll.engine.superannuation import qualifying_earnings_in_cap, super_guarantee

# ---- pay item kinds --------------------------------------------------------------------------------------------------------------
EARNING_KINDS = {"earnings", "overtime", "penalty", "allowance", "bonus", "commission", "back_pay", "leave", "leave_loading",
                 "termination_leave", "etp", "salary_adjustment", "unpaid_leave"}
DEDUCTION_PRETAX = "deduction_pretax"             # reduces taxable income (non-super salary sacrifice)
SACRIFICE_SUPER = "salary_sacrifice_super"        # reduces taxable income, paid into super
DEDUCTION_POSTTAX = "deduction_posttax"           # taken from net pay (union, loan, child support, charity)
EMPLOYEE_SUPER_AFTER_TAX = "employee_super_after_tax"   # taken from net pay, paid into super as a personal contribution
EMPLOYER_SUPER_EXTRA = "employer_super_additional"      # employer-paid extra contribution (no effect on pay)
REIMBURSEMENT = "reimbursement"
ALL_KINDS = EARNING_KINDS | {DEDUCTION_PRETAX, SACRIFICE_SUPER, DEDUCTION_POSTTAX, EMPLOYEE_SUPER_AFTER_TAX, EMPLOYER_SUPER_EXTRA, REIMBURSEMENT}


@dataclass
class ItemDef:
    id: Optional[int]
    code: str
    name: str
    kind: str
    calc_method: str = "fixed"                   # fixed | hours_x_rate | percent_of_base | percent_of_gross
    rate: Optional[Decimal] = None               # absolute $/hour (hours_x_rate)
    multiplier: Decimal = Decimal("1")           # x employee base hourly rate
    default_amount: Optional[Decimal] = None
    percent: Optional[Decimal] = None            # for percent_* methods, e.g. 5 = 5%
    taxable: bool = True
    payg_treatment: str = "regular"              # regular | additional (Method A) | none | termination_leave | etp
    super_treatment: str = "none"                # ote | none
    leave_type_id: Optional[int] = None
    reportable_fringe: bool = False


@dataclass
class LineInput:
    item: ItemDef
    hours: Optional[Decimal] = None
    rate: Optional[Decimal] = None
    amount: Optional[Decimal] = None
    loading_pct: Optional[Decimal] = None        # leave lines: leave loading %
    source: str = "manual"
    ref: str = ""
    note: str = ""
    leave_pre1993: bool = False                  # termination_leave: balance accrued before 18 Aug 1993
    genuine_redundancy: bool = False             # etp: genuine redundancy (tax-free limit applies)
    periods: Optional[int] = None                # additional payments: periods the payment relates to (default periods in the year)


@dataclass
class EmployeeInput:
    employee_id: int
    employment_type: str                         # full_time | part_time | casual | contractor
    pay_basis: str                               # salary | hourly
    annual_salary: Decimal = ZERO
    hourly_rate: Decimal = ZERO
    hours_per_week: Decimal = Decimal("38")
    proration: Decimal = Decimal("1")            # 0..1 share of the period employed (new starter / leaver); salary only
    tfn_provided: bool = True
    residency: str = "resident"                  # resident | foreign_resident
    claims_tft: bool = True
    study_loan: bool = False
    medicare_variation: str = "none"             # none | half | full
    tax_offset_annual: Decimal = ZERO
    variation_pct: Optional[Decimal] = None      # ATO-approved withholding variation (rate)
    extra_withholding: Decimal = ZERO            # additional $ per period requested by the employee
    super_fund_present: bool = True
    completed_years_service: int = 0
    at_or_over_preservation_age: bool = False
    base_item: Optional[ItemDef] = None          # pay item that books the base salary (required for salary basis)
    loading_item: Optional[ItemDef] = None       # pay item that books leave loading (required if any leave line has loading)
    adjustment_item: Optional[ItemDef] = None    # pay item for salary adjustments (leave / unpaid) - defaults to a synthetic one


@dataclass
class PeriodInput:
    frequency: str
    period_start: date
    period_end: date
    pay_date: date


@dataclass
class Ytd:
    """Year-to-date BEFORE this pay (finalised pays in the same financial year + opening balances)."""
    gross: Decimal = ZERO
    taxable: Decimal = ZERO
    tax: Decimal = ZERO
    study_loan: Decimal = ZERO
    qualifying_earnings: Decimal = ZERO
    super_guarantee: Decimal = ZERO
    super_total: Decimal = ZERO
    salary_sacrifice: Decimal = ZERO
    deductions: Decimal = ZERO
    reimbursements: Decimal = ZERO
    etp_taxable: Decimal = ZERO
    net: Decimal = ZERO


@dataclass
class OutLine:
    item_id: Optional[int]
    code: str
    name: str
    kind: str
    hours: Optional[Decimal]
    rate: Optional[Decimal]
    amount: Decimal                              # signed
    taxable: bool
    payg_treatment: str
    super_treatment: str
    source: str = ""
    ref: str = ""
    note: str = ""
    leave_type_id: Optional[int] = None


@dataclass
class Issue:
    code: str
    message: str


@dataclass
class PayResult:
    lines: List[OutLine]
    gross: Decimal = ZERO
    sacrifice_super: Decimal = ZERO
    pretax_deductions: Decimal = ZERO
    taxable: Decimal = ZERO
    payg: Decimal = ZERO
    study_loan: Decimal = ZERO
    posttax_deductions: Decimal = ZERO
    employee_super_after_tax: Decimal = ZERO
    reimbursements: Decimal = ZERO
    net: Decimal = ZERO
    qualifying_earnings: Decimal = ZERO
    qualifying_earnings_in_cap: Decimal = ZERO
    super_guarantee: Decimal = ZERO
    super_additional_employer: Decimal = ZERO
    super_total: Decimal = ZERO                  # everything that goes to the fund this pay
    employer_cost: Decimal = ZERO
    ordinary_hours: Decimal = ZERO
    overtime_hours: Decimal = ZERO
    leave_hours: Decimal = ZERO
    etp_taxable: Decimal = ZERO
    etp_tax_free: Decimal = ZERO
    scale: str = ""
    accruals: List[dict] = field(default_factory=list)
    ytd_after: Optional[Ytd] = None
    errors: List[Issue] = field(default_factory=list)
    warnings: List[Issue] = field(default_factory=list)
    rule_set: str = ""

    def money(self) -> dict:
        keys = ["gross", "sacrifice_super", "pretax_deductions", "taxable", "payg", "study_loan", "posttax_deductions", "employee_super_after_tax",
                "reimbursements", "net", "qualifying_earnings", "super_guarantee", "super_additional_employer", "super_total", "employer_cost"]
        return {k: str(getattr(self, k)) for k in keys}


_UNPAID_ITEM = ItemDef(None, "UNPAIDLEAVE", "Unpaid leave", "unpaid_leave", super_treatment="ote")
_ADJ_ITEM = ItemDef(None, "SALADJ", "Salary adjustment for leave", "salary_adjustment", super_treatment="ote")


def _weeks_in_period(freq: str) -> Decimal:
    return Decimal(52) / payg.periods_per_year(freq)


def calculate_employee(rules: RuleSet, emp: EmployeeInput, period: PeriodInput, inputs: List[LineInput], ytd: Optional[Ytd] = None,
                       accrual_defs: Optional[List[AccrualDef]] = None, leave_balances: Optional[Dict[str, Decimal]] = None) -> PayResult:
    ytd = ytd or Ytd()
    freq = period.frequency
    ppy = payg.periods_per_year(freq)
    res = PayResult(lines=[], rule_set=rules.id)
    err, warn = res.errors.append, res.warnings.append

    # ---- basic validation of the employee set-up ---------------------------------------------------------------------------------
    if emp.pay_basis not in ("salary", "hourly"):
        err(Issue("bad_basis", f"Pay basis '{emp.pay_basis}' is not valid"))
        return res
    if emp.hours_per_week <= 0:
        err(Issue("bad_hours", "Ordinary hours per week must be greater than zero"))
        return res
    if emp.pay_basis == "salary" and emp.annual_salary <= 0:
        err(Issue("bad_salary", "Annual salary must be greater than zero for a salaried employee"))
        return res
    if emp.pay_basis == "hourly" and emp.hourly_rate <= 0:
        err(Issue("bad_rate", "Hourly rate must be greater than zero for an hourly employee"))
        return res
    if not (ZERO <= emp.proration <= 1):
        err(Issue("bad_proration", "Proration must be between 0 and 1"))
        return res
    for li in inputs:
        if li.item.kind not in ALL_KINDS:
            err(Issue("bad_item", f"Pay item {li.item.code} has an unknown type '{li.item.kind}'"))
            return res

    base_hourly = (emp.hourly_rate if emp.pay_basis == "hourly"
                   else emp.annual_salary / (52 * emp.hours_per_week))
    lines: List[OutLine] = []

    def add(item: ItemDef, amount, *, hours=None, rate=None, source="", ref="", note="") -> OutLine:
        ol = OutLine(item.id, item.code, item.name, item.kind, hours, rate, r2(amount), item.taxable, item.payg_treatment,
                     item.super_treatment, source, ref, note, item.leave_type_id)
        lines.append(ol)
        return ol

    # ---- base salary --------------------------------------------------------------------------------------------------------------
    base_amount = ZERO
    if emp.pay_basis == "salary":
        if emp.base_item is None:
            err(Issue("no_base_item", "No base salary pay item is configured"))
            return res
        base_amount = r2(emp.annual_salary / ppy * emp.proration)
        add(emp.base_item, base_amount, source="salary", ref="base")

    # ---- caller-supplied lines ----------------------------------------------------------------------------------------------------
    paid_leave_h = unpaid_h = ordinary_h = overtime_h = ZERO
    deferred = []                                                       # percent_of_gross lines need gross first
    for li in inputs:
        it = li.item
        m = it.calc_method
        if m == "percent_of_gross":
            deferred.append(li)
            continue
        if m == "hours_x_rate":
            if li.hours is None or D(li.hours) <= 0:
                err(Issue("no_hours", f"{it.name}: hours must be greater than zero"))
                continue
            rate = li.rate if li.rate is not None else (it.rate if it.rate is not None else base_hourly * it.multiplier)
            amount = D(li.hours) * D(rate)
            hrs, rt = D(li.hours), r2(rate) if rate is not None else None
        elif m == "percent_of_base":
            pct = D(li.rate if li.rate is not None else it.percent)
            basis = base_amount if emp.pay_basis == "salary" else sum((l.amount for l in lines if l.kind == "earnings"), ZERO)
            amount, hrs, rt = basis * pct / 100, None, None
        elif m == "fixed":
            amt = li.amount if li.amount is not None else it.default_amount
            if amt is None:
                err(Issue("no_amount", f"{it.name}: an amount is required"))
                continue
            amount, hrs, rt = D(amt), (D(li.hours) if li.hours is not None else None), None
        else:
            err(Issue("bad_method", f"{it.name}: unknown calculation method '{m}'"))
            continue
        if amount < 0 and it.kind not in ("back_pay", "salary_adjustment"):
            err(Issue("negative_item", f"{it.name}: amount cannot be negative"))
            continue
        if it.kind == "unpaid_leave":
            hrs_u = D(li.hours or 0)
            unpaid_h += hrs_u
            if emp.pay_basis != "salary":                               # hourly staff are simply not paid for hours not worked
                continue
            amount = -abs(amount)                                       # salaried: take the unpaid hours back out of the salary
        ol = add(it, amount, hours=hrs, rate=rt, source=li.source, ref=li.ref, note=li.note)
        ol.__dict__["_li"] = li
        if it.kind == "leave":
            paid_leave_h += D(li.hours or 0)
            if emp.pay_basis == "salary":                               # salary already pays these hours: take them back out, leave pay replaces them
                adj = emp.adjustment_item or _ADJ_ITEM
                add(adj, -(D(li.hours or 0) * base_hourly), hours=-D(li.hours or 0), source=li.source, ref=li.ref,
                    note=f"Replaced by {it.name}")
            if li.loading_pct and D(li.loading_pct) > 0:
                if emp.loading_item is None:
                    err(Issue("no_loading_item", "Leave loading is required but no leave loading pay item is configured"))
                else:
                    add(emp.loading_item, amount * D(li.loading_pct) / 100, hours=hrs, source=li.source, ref=li.ref,
                        note=f"{li.loading_pct}% loading on {it.name}")
        elif it.kind in ("earnings",) and hrs is not None and emp.pay_basis == "hourly":
            ordinary_h += hrs
        elif it.kind in ("overtime", "penalty") and hrs is not None:
            overtime_h += hrs if it.kind == "overtime" else ZERO
            ordinary_h += hrs if it.kind == "penalty" else ZERO
    if emp.pay_basis == "salary":
        ordinary_h = max(ZERO, emp.hours_per_week * _weeks_in_period(freq) * emp.proration - unpaid_h - paid_leave_h)

    earn_lines = lambda: [l for l in lines if l.kind in EARNING_KINDS]
    gross_so_far = sum((l.amount for l in earn_lines()), ZERO)

    for li in deferred:                                                 # e.g. union fee 1% of gross, salary sacrifice 10% of gross
        it = li.item
        pct = D(li.rate if li.rate is not None else it.percent)
        basis = sum((l.amount for l in earn_lines() if l.super_treatment == "ote"), ZERO) if it.kind in (SACRIFICE_SUPER, EMPLOYER_SUPER_EXTRA) \
            else gross_so_far
        if pct <= 0:
            err(Issue("bad_percent", f"{it.name}: percentage must be greater than zero"))
            continue
        add(it, max(ZERO, basis) * pct / 100, source=li.source, ref=li.ref, note=f"{pct}% of {'ordinary earnings' if it.kind in (SACRIFICE_SUPER, EMPLOYER_SUPER_EXTRA) else 'gross'}")

    # ---- totals -------------------------------------------------------------------------------------------------------------------
    S = lambda pred: sum((l.amount for l in lines if pred(l)), ZERO)
    res.lines = lines
    res.gross = S(lambda l: l.kind in EARNING_KINDS)
    res.sacrifice_super = S(lambda l: l.kind == SACRIFICE_SUPER)
    res.pretax_deductions = S(lambda l: l.kind == DEDUCTION_PRETAX)
    res.posttax_deductions = S(lambda l: l.kind == DEDUCTION_POSTTAX)
    res.employee_super_after_tax = S(lambda l: l.kind == EMPLOYEE_SUPER_AFTER_TAX)
    res.reimbursements = S(lambda l: l.kind == REIMBURSEMENT)
    res.super_additional_employer = S(lambda l: l.kind == EMPLOYER_SUPER_EXTRA)
    res.ordinary_hours, res.overtime_hours, res.leave_hours = ordinary_h, overtime_h, paid_leave_h
    taxable_lines = [l for l in lines if l.kind in EARNING_KINDS and l.taxable]
    res.taxable = max(ZERO, sum((l.amount for l in taxable_lines), ZERO) - res.sacrifice_super - res.pretax_deductions)

    # ---- PAYG ---------------------------------------------------------------------------------------------------------------------
    scale = payg.scale_for(emp.tfn_provided, emp.residency, emp.claims_tft, emp.medicare_variation)
    res.scale = scale
    if not emp.tfn_provided:
        warn(Issue("no_tfn", "No TFN on file: tax is withheld at the no-TFN rate (Scale 4)"))
    regular = sum((l.amount for l in taxable_lines if l.payg_treatment == "regular"), ZERO) - res.sacrifice_super - res.pretax_deductions
    regular = max(ZERO, regular)
    additional = [l for l in taxable_lines if l.payg_treatment == "additional"]
    term_leave = [l for l in taxable_lines if l.payg_treatment == "termination_leave"]
    etps = [l for l in taxable_lines if l.payg_treatment == "etp"]
    kw = dict(scale=scale, residency=emp.residency, claims_tft=emp.claims_tft, study_loan=emp.study_loan and emp.tfn_provided)
    offset = emp.tax_offset_annual

    tax, stsl = payg.total_withholding(rules, regular, freq, offset_claim=offset, **kw) if scale != "4" else (payg.scale4_withholding(rules, regular, emp.residency), ZERO)
    if emp.study_loan and emp.tfn_provided is False:
        warn(Issue("stsl_no_tfn", "Study loan debt noted but no TFN: the study loan component cannot be applied"))
    if emp.variation_pct is not None and scale != "4":
        tax = r_dollar(regular * D(emp.variation_pct) / 100)             # approved variation replaces the schedule rate

    def _extra(li_group, prefix):
        nonlocal tax, stsl
        for l in li_group:
            li = l.__dict__.get("_li")
            periods = li.periods if li and li.periods else None
            if scale == "4":
                tax += payg.scale4_withholding(rules, l.amount, emp.residency)
                continue
            t, s = payg.method_a(rules, regular, l.amount, freq, offset_claim=offset, periods=periods, **kw)
            tax += t
            stsl += s

    _extra(additional, "additional")
    for l in term_leave:                                                # unused leave on termination
        li = l.__dict__.get("_li")
        if li and li.leave_pre1993:
            tax += payg.floor_dollar(l.amount * rules.term_leave_pre1993_rate)
        else:
            t, _ = payg.method_a(rules, regular, l.amount, freq, offset_claim=offset, **{**kw, "study_loan": False}) if scale != "4" \
                else (payg.scale4_withholding(rules, l.amount, emp.residency), ZERO)
            tax += t
    for l in etps:
        li = l.__dict__.get("_li")
        taxable_part = l.amount
        if li and li.genuine_redundancy:
            free = payg.genuine_redundancy_tax_free(rules, l.amount, emp.completed_years_service)
            res.etp_tax_free += free
            taxable_part = l.amount - free
        res.etp_taxable += taxable_part
        tax += payg.etp_tax(rules, taxable_part, at_or_over_preservation_age=emp.at_or_over_preservation_age, cap_used=ytd.etp_taxable)
    tax += D(emp.extra_withholding)
    res.payg, res.study_loan = r2(tax), r2(stsl)

    # ---- superannuation -----------------------------------------------------------------------------------------------------------
    res.qualifying_earnings = max(ZERO, S(lambda l: l.kind in EARNING_KINDS and l.super_treatment == "ote"))
    res.qualifying_earnings_in_cap = qualifying_earnings_in_cap(rules, res.qualifying_earnings, ytd.qualifying_earnings)
    res.super_guarantee = super_guarantee(rules, res.qualifying_earnings, ytd.qualifying_earnings)
    res.super_total = r2(res.super_guarantee + res.sacrifice_super + res.super_additional_employer + res.employee_super_after_tax)
    if res.super_total > 0 and not emp.super_fund_present:
        err(Issue("no_super_fund", "Superannuation is payable but the employee has no super fund recorded"))

    # ---- net ----------------------------------------------------------------------------------------------------------------------
    res.net = r2(res.gross - res.sacrifice_super - res.pretax_deductions - res.payg - res.study_loan
                 - res.posttax_deductions - res.employee_super_after_tax + res.reimbursements)
    res.employer_cost = r2(res.gross + res.super_guarantee + res.super_additional_employer + res.reimbursements)
    if res.net < 0:
        err(Issue("negative_net", f"Deductions exceed pay: net pay would be {res.net}"))
    if res.gross == 0 and not any(l.kind == REIMBURSEMENT for l in lines):
        warn(Issue("zero_earnings", "Zero earnings this period (no hours, leave or salary recorded)"))
    if emp.pay_basis == "hourly" and ordinary_h == 0 and overtime_h == 0 and paid_leave_h == 0:
        warn(Issue("no_hours", "Hourly employee has no approved hours for this period"))

    # ---- year to date ---------------------------------------------------------------------------------------------------------------
    res.ytd_after = Ytd(
        gross=ytd.gross + res.gross, taxable=ytd.taxable + res.taxable, tax=ytd.tax + res.payg, study_loan=ytd.study_loan + res.study_loan,
        qualifying_earnings=ytd.qualifying_earnings + res.qualifying_earnings, super_guarantee=ytd.super_guarantee + res.super_guarantee,
        super_total=ytd.super_total + res.super_total, salary_sacrifice=ytd.salary_sacrifice + res.sacrifice_super,
        deductions=ytd.deductions + res.posttax_deductions + res.pretax_deductions, reimbursements=ytd.reimbursements + res.reimbursements,
        etp_taxable=ytd.etp_taxable + res.etp_taxable, net=ytd.net + res.net)

    # ---- leave accruals -----------------------------------------------------------------------------------------------------------
    for d in accrual_defs or []:
        h = accrual_hours(rules, d, employment_type=emp.employment_type, ordinary_hours=ordinary_h, paid_leave_hours=paid_leave_h,
                          hours_per_week=emp.hours_per_week, periods_per_year=ppy, proration=emp.proration,
                          balance=(leave_balances or {}).get(d.code, ZERO))
        if h > 0:
            res.accruals.append({"leave_type_id": d.leave_type_id, "code": d.code, "hours": str(h)})
    for l in lines:                                                     # strip the private back-reference so results are plain data
        l.__dict__.pop("_li", None)
    return res
