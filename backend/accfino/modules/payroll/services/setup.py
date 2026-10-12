"""Per-organisation payroll provisioning (idempotent): settings row, payroll ledger accounts, system pay items, default leave types."""
import logging
from decimal import Decimal

from sqlalchemy.exc import SQLAlchemyError

import accfino.modules.accounting.public as accounting
from accfino.modules.payroll.models.payroll import PayItem, PayLeaveType, PaySettings

log = logging.getLogger("accfino.payroll")

# key -> (code, name, ledger type, system_key)
LEDGER = {
    "wages_expense": ("477", "Wages and Salaries", "expense", None),
    "super_expense": ("478", "Superannuation", "expense", None),
    "reimbursement_expense": ("479", "Employee Reimbursements", "expense", "payroll_reimbursements"),
    "wages_payable": ("804", "Wages Payable - Payroll", "current_liability", "wages_payable"),
    "payg_payable": ("825", "PAYG Withholdings Payable", "current_liability", "payg_withholding"),
    "super_payable": ("826", "Superannuation Payable", "current_liability", "super_payable"),
    "deductions_payable": ("806", "Payroll Deductions Payable", "current_liability", "payroll_deductions"),
}

# code, name, kind, calc, multiplier, taxable, payg, super, system, default, sort, extra
ITEMS = [
    ("BASE", "Base salary", "earnings", "fixed", 1, True, "regular", "ote", True, True, 1, {}),
    ("ORD", "Ordinary hours", "earnings", "hours_x_rate", 1, True, "regular", "ote", True, True, 2, {}),
    ("OT15", "Overtime 1.5x", "overtime", "hours_x_rate", "1.5", True, "regular", "none", False, False, 10, {}),
    ("OT20", "Overtime 2x", "overtime", "hours_x_rate", 2, True, "regular", "none", False, False, 11, {}),
    ("SAT", "Saturday penalty 1.25x", "penalty", "hours_x_rate", "1.25", True, "regular", "ote", False, False, 12, {}),
    ("SUN", "Sunday penalty 1.5x", "penalty", "hours_x_rate", "1.5", True, "regular", "ote", False, False, 13, {}),
    ("PH", "Public holiday 2.5x", "penalty", "hours_x_rate", "2.5", True, "regular", "ote", False, False, 14, {}),
    ("TOOL", "Tool allowance", "allowance", "fixed", 1, True, "regular", "none", False, False, 20, {"default_amount": "50"}),
    ("FIRSTAID", "First aid allowance", "allowance", "fixed", 1, True, "regular", "none", False, False, 21, {"default_amount": "25"}),
    ("BONUS", "Bonus", "bonus", "fixed", 1, True, "additional", "ote", False, False, 30, {}),
    ("COMM", "Commission", "commission", "fixed", 1, True, "additional", "ote", False, False, 31, {}),
    ("BACKPAY", "Back pay", "back_pay", "fixed", 1, True, "additional", "ote", False, False, 32, {}),
    ("AL", "Annual leave", "leave", "hours_x_rate", 1, True, "regular", "ote", False, False, 40, {"leave": "AL"}),
    ("PL", "Personal/carer's leave", "leave", "hours_x_rate", 1, True, "regular", "ote", False, False, 41, {"leave": "PL"}),
    ("CL", "Compassionate leave", "leave", "hours_x_rate", 1, True, "regular", "ote", False, False, 42, {"leave": "CL"}),
    ("LSL", "Long service leave", "leave", "hours_x_rate", 1, True, "regular", "ote", False, False, 43, {"leave": "LSL"}),
    ("UNPAID", "Unpaid leave", "unpaid_leave", "hours_x_rate", 1, True, "regular", "ote", True, False, 44, {"leave": "LWP"}),
    ("LEAVELOAD", "Annual leave loading", "leave_loading", "fixed", 1, True, "regular", "ote", True, False, 45, {}),
    ("SALADJ", "Salary adjustment for leave", "salary_adjustment", "fixed", 1, True, "regular", "ote", True, False, 46, {}),
    ("TLEAVE", "Unused leave payout", "termination_leave", "fixed", 1, True, "termination_leave", "none", False, False, 50, {}),
    ("ETP", "Employment termination payment", "etp", "fixed", 1, True, "etp", "none", False, False, 51, {}),
    ("SSUPER", "Salary sacrifice - super", "salary_sacrifice_super", "fixed", 1, False, "none", "none", False, False, 60, {}),
    ("SSOTHER", "Salary sacrifice - other (pre-tax)", "deduction_pretax", "fixed", 1, False, "none", "none", False, False, 61, {}),
    ("UNION", "Union fees", "deduction_posttax", "fixed", 1, False, "none", "none", False, False, 62, {"default_amount": "20"}),
    ("LOAN", "Loan repayment", "deduction_posttax", "fixed", 1, False, "none", "none", False, False, 63, {}),
    ("CHILDSUP", "Child support (agency)", "deduction_posttax", "fixed", 1, False, "none", "none", False, False, 64, {}),
    ("GIVING", "Workplace giving", "deduction_posttax", "fixed", 1, False, "none", "none", False, False, 65, {}),
    ("EMPSUPER", "Employee super contribution (after tax)", "employee_super_after_tax", "fixed", 1, False, "none", "none", False, False, 66, {}),
    ("ADDSUPER", "Employer additional super", "employer_super_additional", "fixed", 1, False, "none", "none", False, False, 67, {}),
    ("REIMB", "Reimbursement", "reimbursement", "fixed", 1, False, "none", "none", False, False, 70, {}),
]
# code, name, category, paid, method, annual hours (38h week), applies_to, loading, min service years, allow negative
LEAVE = [
    ("AL", "Annual leave", "annual", True, "per_ordinary_hour", "152", ["full_time", "part_time"], "17.5", 0, False),
    ("PL", "Personal/carer's leave", "personal", True, "per_ordinary_hour", "76", ["full_time", "part_time"], "0", 0, False),
    ("CL", "Compassionate leave", "compassionate", True, "none", "0", None, "0", 0, True),
    ("LSL", "Long service leave", "long_service", True, "per_ordinary_hour", "32.9333", ["full_time", "part_time"], "0", 7, False),
    ("PAR", "Parental leave (unpaid)", "parental", False, "none", "0", None, "0", 0, True),
    ("LWP", "Leave without pay", "unpaid", False, "none", "0", None, "0", 0, True),
]


def ledger_map(db, org) -> dict:
    """Ensure the payroll ledger accounts exist and return {key: account id}. Safe to call repeatedly."""
    out = {}
    for key, (code, name, typ, sk) in LEDGER.items():
        out[key] = accounting.ensure_ledger_account(db, org.id, code=code, name=name, account_type=typ, system_key=sk)["id"]
    return out


def provision_org(db, org) -> None:
    s = db.get(PaySettings, org.id)
    if s is None:
        s = PaySettings(org_id=org.id, employer_name=org.legal_name or org.name, abn=org.abn, payslip_config={"show_ytd": True, "show_leave": True, "footer": ""},
                        payment_config={}, stp_config={}, controls={"require_separate_approver": False}, accounting_map={})
        db.add(s)
        db.flush()
    try:
        s.accounting_map = {**(s.accounting_map or {}), **ledger_map(db, org)}
    except (SQLAlchemyError, accounting.LedgerError) as e:             # a missing / locked chart must never stop organisation set-up (logged, retried at next start)
        log.warning("payroll: ledger accounts not provisioned for org %s: %s", org.id, e)
    existing = {i.code: i for i in db.query(PayItem).filter_by(org_id=org.id)}
    leave = {l.code: l for l in db.query(PayLeaveType).filter_by(org_id=org.id)}
    for code, name, cat, paid, method, hrs, applies, loading, years, neg in LEAVE:
        if code not in leave:
            leave[code] = PayLeaveType(org_id=org.id, code=code, name=name, category=cat, is_paid=paid, accrual_method=method,
                                       accrual_annual_hours=Decimal(hrs), applies_to=applies, loading_pct=Decimal(loading), min_service_years=years,
                                       allow_negative=neg)
            db.add(leave[code])
    db.flush()
    m = s.accounting_map or {}
    for code, name, kind, calc, mult, tax, payg, sup, system, default, sort, extra in ITEMS:
        if code in existing:
            continue
        acct = (m.get("reimbursement_expense") if kind == "reimbursement" else
                m.get("deductions_payable") if kind in ("deduction_pretax", "deduction_posttax") else
                m.get("super_payable") if kind in ("salary_sacrifice_super", "employee_super_after_tax") else
                m.get("super_expense") if kind == "employer_super_additional" else m.get("wages_expense"))
        db.add(PayItem(org_id=org.id, code=code, name=name, kind=kind, calc_method=calc, multiplier=Decimal(str(mult)), taxable=tax, payg_treatment=payg,
                       super_treatment=sup, is_system=system, is_default=default, sort=sort, expense_account_id=acct,
                       default_amount=Decimal(extra["default_amount"]) if "default_amount" in extra else None,
                       leave_type_id=leave[extra["leave"]].id if "leave" in extra else None))
    db.flush()


def get_settings(db, org) -> PaySettings:
    s = db.get(PaySettings, org.id)
    if s is None:
        provision_org(db, org)
        s = db.get(PaySettings, org.id)
    return s


def next_number(db, org, kind: str) -> str:
    """Allocate the next employee or run number under a row lock (no two requests can receive the same number)."""
    s = db.query(PaySettings).filter(PaySettings.org_id == org.id).with_for_update().one()
    if kind == "employee":
        n, s.next_employee_no = s.next_employee_no, s.next_employee_no + 1
        return f"{s.employee_prefix}{n:04d}"
    n, s.next_run_no = s.next_run_no, s.next_run_no + 1
    return f"{s.run_prefix}-{n:04d}"
