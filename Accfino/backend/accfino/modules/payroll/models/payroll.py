"""
accfino.modules.payroll.models.payroll
--------------------------------------
Payroll tables (prefix pay_). Every row belongs to an organisation (org_id). Money is NUMERIC(18,2), hours NUMERIC(12,4).
Sensitive values (TFN, bank account number) are stored SEALED (Fernet) with only a short masked tail kept in clear for display.
Finalised pay-run data is never edited: corrections are made by a reversal run (see services/payruns.py).
The legacy tables (payroll_employees, payroll_runs, payroll_timesheets, payslips, stp_submissions) are left untouched for rollback.
"""
from datetime import datetime

from sqlalchemy import (JSON, BigInteger, Boolean, CheckConstraint, Column, Date, DateTime, ForeignKey, Index, Integer, Numeric, String,
                        Text, UniqueConstraint, text)

from accfino.shared.db.base import Base
from accfino.shared.db.types import MONEY

HOURS = Numeric(12, 4)
RATE4 = Numeric(18, 4)
_ORG = lambda: Column(Integer, ForeignKey("organisations.id", ondelete="CASCADE"), nullable=False, index=True)


def _in(col, values):
    return f"{col} IN ({', '.join(repr(v) for v in values)})"


EMPLOYMENT_TYPES = ("full_time", "part_time", "casual", "contractor")
EMP_STATUSES = ("active", "inactive", "terminated")
FREQUENCIES = ("weekly", "fortnightly", "monthly")
RUN_STATUSES = ("draft", "processing", "review", "approved", "finalised", "paid", "voided")
RUN_TYPES = ("regular", "off_cycle", "termination", "reversal")
ITEM_KINDS = ("earnings", "overtime", "penalty", "allowance", "bonus", "commission", "back_pay", "leave", "leave_loading", "termination_leave",
              "etp", "salary_adjustment", "unpaid_leave", "deduction_pretax", "salary_sacrifice_super", "deduction_posttax",
              "employee_super_after_tax", "employer_super_additional", "reimbursement")
TS_STATUSES = ("draft", "submitted", "approved", "rejected", "processed")
LEAVE_STATUSES = ("pending", "approved", "rejected", "cancelled")


class PaySettings(Base):
    __tablename__ = "pay_settings"
    org_id = Column(Integer, ForeignKey("organisations.id", ondelete="CASCADE"), primary_key=True)
    employer_name = Column(String(255))                    # defaults to the organisation's legal name
    abn = Column(String(20))
    default_frequency = Column(String(12), nullable=False, default="fortnightly")
    standard_hours_per_week = Column(Numeric(6, 2), nullable=False, default=38)
    employee_prefix = Column(String(10), nullable=False, default="E")
    next_employee_no = Column(Integer, nullable=False, default=1)
    run_prefix = Column(String(10), nullable=False, default="PR")
    next_run_no = Column(Integer, nullable=False, default=1)
    payslip_config = Column(JSON)                          # {"show_ytd":true,"show_leave":true,"footer":"..."}
    payment_config = Column(JSON)                          # {"bsb","account","account_name","apca_user_id","bank_abbrev","description"}
    accounting_map = Column(JSON)                          # {"wages_expense":<ledger account id>, ...}
    stp_config = Column(JSON)                              # {"bms_id","branch_code"}
    leave_config = Column(JSON)                            # org-wide leave defaults
    controls = Column(JSON)                                # {"require_separate_approver": bool}
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class PayDepartment(Base):
    __tablename__ = "pay_departments"
    id = Column(Integer, primary_key=True)
    org_id = _ORG()
    code = Column(String(20), nullable=False)
    name = Column(String(100), nullable=False)
    is_active = Column(Boolean, nullable=False, default=True)
    __table_args__ = (UniqueConstraint("org_id", "code", name="uq_pay_dept_code"),)


class PayLocation(Base):
    __tablename__ = "pay_locations"
    id = Column(Integer, primary_key=True)
    org_id = _ORG()
    code = Column(String(20), nullable=False)
    name = Column(String(100), nullable=False)
    state = Column(String(3))
    is_active = Column(Boolean, nullable=False, default=True)
    __table_args__ = (UniqueConstraint("org_id", "code", name="uq_pay_loc_code"),)


class PayCalendar(Base):
    """A pay schedule: periods are generated from the anchor date (weekly 7d, fortnightly 14d, monthly = calendar months)."""
    __tablename__ = "pay_calendars"
    id = Column(Integer, primary_key=True)
    org_id = _ORG()
    name = Column(String(100), nullable=False)
    frequency = Column(String(12), nullable=False)
    anchor_start = Column(Date, nullable=False)            # the first day of any one period
    pay_offset_days = Column(Integer, nullable=False, default=5)   # pay date = period end + offset
    is_default = Column(Boolean, nullable=False, default=False)
    is_active = Column(Boolean, nullable=False, default=True)
    __table_args__ = (UniqueConstraint("org_id", "name", name="uq_pay_cal_name"), CheckConstraint(_in("frequency", FREQUENCIES), name="ck_pay_cal_freq"))


class PayItem(Base):
    __tablename__ = "pay_items"
    id = Column(Integer, primary_key=True)
    org_id = _ORG()
    code = Column(String(20), nullable=False)
    name = Column(String(100), nullable=False)
    kind = Column(String(30), nullable=False)
    description = Column(String(300))
    calc_method = Column(String(20), nullable=False, default="fixed")      # fixed | hours_x_rate | percent_of_base | percent_of_gross
    rate = Column(RATE4)
    multiplier = Column(Numeric(9, 4), nullable=False, default=1)
    default_amount = Column(MONEY)
    percent = Column(Numeric(9, 4))
    taxable = Column(Boolean, nullable=False, default=True)
    payg_treatment = Column(String(20), nullable=False, default="regular")   # regular | additional | none | termination_leave | etp
    super_treatment = Column(String(10), nullable=False, default="none")     # ote | none
    reportable_fringe = Column(Boolean, nullable=False, default=False)
    expense_account_id = Column(Integer, ForeignKey("ledger_accounts.id", ondelete="SET NULL"))     # earnings -> expense; deductions -> liability
    leave_type_id = Column(Integer)
    is_system = Column(Boolean, nullable=False, default=False)            # required by the engine (base salary, loading, ...): cannot be deleted
    is_default = Column(Boolean, nullable=False, default=False)
    is_active = Column(Boolean, nullable=False, default=True)
    sort = Column(Integer, nullable=False, default=100)
    __table_args__ = (UniqueConstraint("org_id", "code", name="uq_pay_item_code"), CheckConstraint(_in("kind", ITEM_KINDS), name="ck_pay_item_kind"))


class PayLeaveType(Base):
    __tablename__ = "pay_leave_types"
    id = Column(Integer, primary_key=True)
    org_id = _ORG()
    code = Column(String(20), nullable=False)
    name = Column(String(100), nullable=False)
    category = Column(String(20), nullable=False, default="other")      # annual|personal|compassionate|long_service|parental|unpaid|other
    is_paid = Column(Boolean, nullable=False, default=True)
    accrual_method = Column(String(20), nullable=False, default="none")  # none | per_ordinary_hour | fixed_per_year
    accrual_annual_hours = Column(HOURS, nullable=False, default=0)      # hours per year for a standard 38h week
    accrue_on_paid_leave = Column(Boolean, nullable=False, default=True)
    applies_to = Column(JSON)                                            # employment types that accrue; null = all
    loading_pct = Column(Numeric(6, 2), nullable=False, default=0)
    max_balance = Column(HOURS)
    min_service_years = Column(Numeric(5, 2), nullable=False, default=0)  # long service leave eligibility
    allow_negative = Column(Boolean, nullable=False, default=False)
    is_active = Column(Boolean, nullable=False, default=True)
    __table_args__ = (UniqueConstraint("org_id", "code", name="uq_pay_leave_code"),)


class PaySuperFund(Base):
    __tablename__ = "pay_super_funds"
    id = Column(Integer, primary_key=True)
    org_id = _ORG()
    name = Column(String(150), nullable=False)
    fund_type = Column(String(10), nullable=False, default="apra")      # apra | smsf
    usi = Column(String(30))
    abn = Column(String(20))
    smsf_bsb = Column(String(7))
    smsf_account = Column(String(20))
    smsf_account_name = Column(String(100))
    esa = Column(String(50))
    is_default = Column(Boolean, nullable=False, default=False)         # the employer default (MySuper) fund
    is_active = Column(Boolean, nullable=False, default=True)
    __table_args__ = (UniqueConstraint("org_id", "name", name="uq_pay_fund_name"), CheckConstraint(_in("fund_type", ("apra", "smsf")), name="ck_pay_fund_type"))


class PayEmployee(Base):
    __tablename__ = "pay_employees"
    id = Column(Integer, primary_key=True)
    org_id = _ORG()
    user_id = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), index=True)   # login that may view this employee's own pay
    employee_number = Column(String(30), nullable=False)
    first_name = Column(String(100), nullable=False)
    middle_name = Column(String(100))
    last_name = Column(String(100), nullable=False)
    preferred_name = Column(String(100))
    date_of_birth = Column(Date)
    email = Column(String(255))
    phone = Column(String(40))
    address_line1 = Column(String(200))
    address_line2 = Column(String(200))
    suburb = Column(String(100))
    state = Column(String(3))
    postcode = Column(String(4))
    start_date = Column(Date, nullable=False)
    end_date = Column(Date)
    termination_reason = Column(String(200))
    status = Column(String(12), nullable=False, default="active")
    employment_type = Column(String(12), nullable=False, default="full_time")
    position = Column(String(150))
    department_id = Column(Integer, ForeignKey("pay_departments.id", ondelete="SET NULL"))
    location_id = Column(Integer, ForeignKey("pay_locations.id", ondelete="SET NULL"))
    manager_id = Column(Integer, ForeignKey("pay_employees.id", ondelete="SET NULL"), index=True)
    calendar_id = Column(Integer, ForeignKey("pay_calendars.id", ondelete="SET NULL"))
    pay_frequency = Column(String(12), nullable=False, default="fortnightly")
    pay_basis = Column(String(10), nullable=False, default="salary")    # salary | hourly
    annual_salary = Column(MONEY)
    hourly_rate = Column(RATE4)
    hours_per_week = Column(Numeric(6, 2), nullable=False, default=38)
    work_pattern = Column(JSON)                                         # {"mon":7.6,"tue":7.6,...}
    pay_standard_hours = Column(Boolean, nullable=False, default=False)  # hourly staff paid standard hours without a timesheet
    is_demo = Column(Boolean, nullable=False, default=False)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    __table_args__ = (
        UniqueConstraint("org_id", "employee_number", name="uq_pay_emp_number"),
        CheckConstraint(_in("status", EMP_STATUSES), name="ck_pay_emp_status"),
        CheckConstraint(_in("employment_type", EMPLOYMENT_TYPES), name="ck_pay_emp_type"),
        CheckConstraint(_in("pay_frequency", FREQUENCIES), name="ck_pay_emp_freq"),
        CheckConstraint(_in("pay_basis", ("salary", "hourly")), name="ck_pay_emp_basis"),
        Index("ix_pay_emp_org_status", "org_id", "status"),
    )


class PayEmployeeTax(Base):
    """Tax declaration. TFN is sealed; only the last three digits are kept in clear."""
    __tablename__ = "pay_employee_tax"
    employee_id = Column(Integer, ForeignKey("pay_employees.id", ondelete="CASCADE"), primary_key=True)
    org_id = _ORG()
    tfn_enc = Column(Text)
    tfn_last3 = Column(String(3))
    tfn_status = Column(String(12), nullable=False, default="not_provided")   # provided | pending | exempt | not_provided
    residency = Column(String(20), nullable=False, default="resident")        # resident | foreign_resident
    claims_tft = Column(Boolean, nullable=False, default=True)
    has_study_loan = Column(Boolean, nullable=False, default=False)
    study_loan_type = Column(String(20))                                      # HELP | VSL | SSL | TSL | SFSS
    medicare_variation = Column(String(8), nullable=False, default="none")    # none | half | full
    tax_offset_annual = Column(MONEY, nullable=False, default=0)
    variation_pct = Column(Numeric(6, 2))                                     # ATO-approved withholding variation (percentage)
    extra_withholding = Column(MONEY, nullable=False, default=0)
    declaration_date = Column(Date)
    ytd_opening = Column(JSON)                                                # {"fy":"2026-27","gross":..,"tax":..,"super":..,"qualifying_earnings":..} migrated balances
    __table_args__ = (CheckConstraint(_in("tfn_status", ("provided", "pending", "exempt", "not_provided")), name="ck_pay_tax_tfn"),
                      CheckConstraint(_in("residency", ("resident", "foreign_resident")), name="ck_pay_tax_res"),
                      CheckConstraint(_in("medicare_variation", ("none", "half", "full")), name="ck_pay_tax_med"))


class PayEmployeeSuper(Base):
    __tablename__ = "pay_employee_super"
    id = Column(Integer, primary_key=True)
    org_id = _ORG()
    employee_id = Column(Integer, ForeignKey("pay_employees.id", ondelete="CASCADE"), nullable=False, index=True)
    fund_id = Column(Integer, ForeignKey("pay_super_funds.id", ondelete="RESTRICT"), nullable=False)
    member_number = Column(String(40))
    allocation_pct = Column(Numeric(6, 2), nullable=False, default=100)
    is_default_fund = Column(Boolean, nullable=False, default=False)          # employer default fund used (no choice made)
    choice_form_date = Column(Date)                                           # standard choice form received
    effective_from = Column(Date)
    is_active = Column(Boolean, nullable=False, default=True)


class PayEmployeeBank(Base):
    __tablename__ = "pay_employee_bank"
    id = Column(Integer, primary_key=True)
    org_id = _ORG()
    employee_id = Column(Integer, ForeignKey("pay_employees.id", ondelete="CASCADE"), nullable=False, index=True)
    account_name = Column(String(100), nullable=False)
    bsb = Column(String(7), nullable=False)                                   # 123-456
    account_enc = Column(Text, nullable=False)                                # sealed account number
    account_last4 = Column(String(4), nullable=False)
    allocation_type = Column(String(10), nullable=False, default="remainder")  # fixed | percent | remainder
    allocation_value = Column(MONEY, nullable=False, default=0)
    priority = Column(Integer, nullable=False, default=1)
    reference = Column(String(18))
    is_active = Column(Boolean, nullable=False, default=True)
    __table_args__ = (CheckConstraint(_in("allocation_type", ("fixed", "percent", "remainder")), name="ck_pay_bank_alloc"),)


class PayEmployeeItem(Base):
    """Recurring pay item assigned to an employee (allowance, salary sacrifice, deduction ...)."""
    __tablename__ = "pay_employee_items"
    id = Column(Integer, primary_key=True)
    org_id = _ORG()
    employee_id = Column(Integer, ForeignKey("pay_employees.id", ondelete="CASCADE"), nullable=False, index=True)
    pay_item_id = Column(Integer, ForeignKey("pay_items.id", ondelete="RESTRICT"), nullable=False)
    amount = Column(MONEY)
    rate = Column(RATE4)                                                       # $/hour override or percent for percent_* items
    hours = Column(HOURS)
    effective_from = Column(Date)
    effective_to = Column(Date)
    note = Column(String(200))
    is_active = Column(Boolean, nullable=False, default=True)


class PayTimesheet(Base):
    __tablename__ = "pay_timesheets"
    id = Column(Integer, primary_key=True)
    org_id = _ORG()
    employee_id = Column(Integer, ForeignKey("pay_employees.id", ondelete="CASCADE"), nullable=False, index=True)
    week_start = Column(Date, nullable=False)
    week_end = Column(Date, nullable=False)
    status = Column(String(12), nullable=False, default="draft")
    notes = Column(Text)
    submitted_at = Column(DateTime)
    submitted_by = Column(Integer)
    decided_at = Column(DateTime)
    decided_by = Column(Integer)
    reject_reason = Column(String(300))
    processed_run_id = Column(Integer, ForeignKey("pay_runs.id", ondelete="SET NULL"))
    created_by = Column(Integer)
    created_at = Column(DateTime, default=datetime.utcnow)
    __table_args__ = (UniqueConstraint("org_id", "employee_id", "week_start", name="uq_pay_ts_week"),
                      CheckConstraint(_in("status", TS_STATUSES), name="ck_pay_ts_status"), Index("ix_pay_ts_status", "org_id", "status"))


class PayTimesheetLine(Base):
    __tablename__ = "pay_timesheet_lines"
    id = Column(Integer, primary_key=True)
    org_id = _ORG()
    timesheet_id = Column(Integer, ForeignKey("pay_timesheets.id", ondelete="CASCADE"), nullable=False, index=True)
    work_date = Column(Date, nullable=False)
    pay_item_id = Column(Integer, ForeignKey("pay_items.id", ondelete="RESTRICT"), nullable=False)   # pay category
    leave_type_id = Column(Integer, ForeignKey("pay_leave_types.id", ondelete="SET NULL"))
    hours = Column(HOURS, nullable=False)
    break_minutes = Column(Integer, nullable=False, default=0)
    start_time = Column(String(5))
    end_time = Column(String(5))
    notes = Column(String(300))
    processed_run_id = Column(Integer, ForeignKey("pay_runs.id", ondelete="SET NULL"))   # set when a pay run has paid this line


class PayLeaveRequest(Base):
    __tablename__ = "pay_leave_requests"
    id = Column(Integer, primary_key=True)
    org_id = _ORG()
    employee_id = Column(Integer, ForeignKey("pay_employees.id", ondelete="CASCADE"), nullable=False, index=True)
    leave_type_id = Column(Integer, ForeignKey("pay_leave_types.id", ondelete="RESTRICT"), nullable=False)
    start_date = Column(Date, nullable=False)
    end_date = Column(Date, nullable=False)
    hours = Column(HOURS, nullable=False)
    reason = Column(String(300))
    status = Column(String(12), nullable=False, default="pending")
    requested_by = Column(Integer)
    decided_by = Column(Integer)
    decided_at = Column(DateTime)
    decision_note = Column(String(300))
    paid_run_id = Column(Integer, ForeignKey("pay_runs.id", ondelete="SET NULL"))     # set when a finalised run has paid it
    created_at = Column(DateTime, default=datetime.utcnow)
    __table_args__ = (CheckConstraint(_in("status", LEAVE_STATUSES), name="ck_pay_leave_status"), Index("ix_pay_leave_status", "org_id", "status"))


class PayLeaveTxn(Base):
    """Leave ledger. Balance = SUM(hours). Accruals/taken are written when a run is finalised and reversed with it."""
    __tablename__ = "pay_leave_txns"
    id = Column(Integer, primary_key=True)
    org_id = _ORG()
    employee_id = Column(Integer, ForeignKey("pay_employees.id", ondelete="CASCADE"), nullable=False)
    leave_type_id = Column(Integer, ForeignKey("pay_leave_types.id", ondelete="RESTRICT"), nullable=False)
    txn_date = Column(Date, nullable=False)
    txn_type = Column(String(12), nullable=False)            # opening | accrual | taken | adjustment | payout | reversal
    hours = Column(HOURS, nullable=False)                    # + adds balance, - uses it
    pay_run_id = Column(Integer, ForeignKey("pay_runs.id", ondelete="SET NULL"))
    leave_request_id = Column(Integer, ForeignKey("pay_leave_requests.id", ondelete="SET NULL"))
    note = Column(String(300))
    created_by = Column(Integer)
    created_at = Column(DateTime, default=datetime.utcnow)
    __table_args__ = (Index("ix_pay_leave_txn_bal", "employee_id", "leave_type_id"),
                      CheckConstraint(_in("txn_type", ("opening", "accrual", "taken", "adjustment", "payout", "reversal")), name="ck_pay_leave_txn_type"))


class PayRun(Base):
    __tablename__ = "pay_runs"
    id = Column(Integer, primary_key=True)
    org_id = _ORG()
    run_no = Column(String(30), nullable=False)
    name = Column(String(150))
    run_type = Column(String(12), nullable=False, default="regular")
    calendar_id = Column(Integer, ForeignKey("pay_calendars.id", ondelete="SET NULL"))
    frequency = Column(String(12), nullable=False)
    period_start = Column(Date, nullable=False)
    period_end = Column(Date, nullable=False)
    pay_date = Column(Date, nullable=False)
    status = Column(String(12), nullable=False, default="draft")
    rule_set = Column(String(20))                             # statutory rule set used to calculate
    employee_count = Column(Integer, nullable=False, default=0)
    total_gross = Column(MONEY, nullable=False, default=0)
    total_taxable = Column(MONEY, nullable=False, default=0)
    total_payg = Column(MONEY, nullable=False, default=0)
    total_study_loan = Column(MONEY, nullable=False, default=0)
    total_deductions = Column(MONEY, nullable=False, default=0)
    total_sacrifice = Column(MONEY, nullable=False, default=0)
    total_reimbursements = Column(MONEY, nullable=False, default=0)
    total_net = Column(MONEY, nullable=False, default=0)
    total_super = Column(MONEY, nullable=False, default=0)
    total_employer_cost = Column(MONEY, nullable=False, default=0)
    error_count = Column(Integer, nullable=False, default=0)
    warning_count = Column(Integer, nullable=False, default=0)
    calculated_at = Column(DateTime)
    approved_at = Column(DateTime)
    approved_by = Column(Integer)
    finalised_at = Column(DateTime)
    finalised_by = Column(Integer)
    paid_at = Column(DateTime)
    voided_at = Column(DateTime)
    voided_by = Column(Integer)
    void_reason = Column(String(300))
    reverses_run_id = Column(Integer, ForeignKey("pay_runs.id"))      # NO ACTION (not RESTRICT): an original and its reversal must be deletable in one statement (org removal)      # this run is the reversal of that one
    reversed_by_run_id = Column(Integer)                                                    # set on the original once it has been reversed
    result_hash = Column(String(64))                           # SHA-256 of the finalised results: detects tampering
    notes = Column(Text)
    created_by = Column(Integer)
    created_at = Column(DateTime, default=datetime.utcnow)
    __table_args__ = (
        UniqueConstraint("org_id", "run_no", name="uq_pay_run_no"),
        CheckConstraint(_in("status", RUN_STATUSES), name="ck_pay_run_status"),
        CheckConstraint(_in("run_type", RUN_TYPES), name="ck_pay_run_type"),
        # one live regular run per calendar period: the database refuses a duplicate even if two requests race
        Index("uq_pay_run_period", "org_id", "calendar_id", "period_start", "period_end", unique=True,
              postgresql_where=text("run_type = 'regular' AND status <> 'voided' AND reversed_by_run_id IS NULL"),
              sqlite_where=text("run_type = 'regular' AND status <> 'voided' AND reversed_by_run_id IS NULL")),
        Index("ix_pay_run_pay_date", "org_id", "pay_date"),
    )


class PayRunEmployee(Base):
    __tablename__ = "pay_run_employees"
    id = Column(Integer, primary_key=True)
    org_id = _ORG()
    run_id = Column(Integer, ForeignKey("pay_runs.id", ondelete="CASCADE"), nullable=False, index=True)
    employee_id = Column(Integer, ForeignKey("pay_employees.id", ondelete="RESTRICT"), nullable=False, index=True)
    employee_number = Column(String(30))
    employee_name = Column(String(220))
    department_id = Column(Integer)
    status = Column(String(10), nullable=False, default="included")     # included | excluded
    exclusion_reason = Column(String(300))
    pay_basis = Column(String(10))
    rate_snapshot = Column(MONEY)                                       # annual salary or hourly rate used
    tax_scale = Column(String(2))
    ordinary_hours = Column(HOURS, nullable=False, default=0)
    overtime_hours = Column(HOURS, nullable=False, default=0)
    leave_hours = Column(HOURS, nullable=False, default=0)
    gross = Column(MONEY, nullable=False, default=0)
    taxable = Column(MONEY, nullable=False, default=0)
    payg = Column(MONEY, nullable=False, default=0)
    study_loan = Column(MONEY, nullable=False, default=0)
    pretax_deductions = Column(MONEY, nullable=False, default=0)
    posttax_deductions = Column(MONEY, nullable=False, default=0)
    sacrifice_super = Column(MONEY, nullable=False, default=0)
    reimbursements = Column(MONEY, nullable=False, default=0)
    net = Column(MONEY, nullable=False, default=0)
    qualifying_earnings = Column(MONEY, nullable=False, default=0)
    etp_taxable = Column(MONEY, nullable=False, default=0)
    super_guarantee = Column(MONEY, nullable=False, default=0)
    super_additional = Column(MONEY, nullable=False, default=0)
    super_total = Column(MONEY, nullable=False, default=0)
    employer_cost = Column(MONEY, nullable=False, default=0)
    ytd = Column(JSON)                                                  # YTD after this pay
    accruals = Column(JSON)
    errors = Column(JSON)
    warnings = Column(JSON)
    inputs_hash = Column(String(64))
    manual_note = Column(String(300))
    __table_args__ = (UniqueConstraint("run_id", "employee_id", name="uq_pay_run_emp"),
                      CheckConstraint(_in("status", ("included", "excluded")), name="ck_pay_re_status"))


class PayRunInput(Base):
    """A manual pay-run input for one employee (bonus, back pay, reimbursement, termination payment ...). Consumed by calculation."""
    __tablename__ = "pay_run_inputs"
    id = Column(Integer, primary_key=True)
    org_id = _ORG()
    run_id = Column(Integer, ForeignKey("pay_runs.id", ondelete="CASCADE"), nullable=False, index=True)
    employee_id = Column(Integer, ForeignKey("pay_employees.id", ondelete="CASCADE"), nullable=False)
    pay_item_id = Column(Integer, ForeignKey("pay_items.id", ondelete="RESTRICT"), nullable=False)
    hours = Column(HOURS)
    rate = Column(RATE4)
    amount = Column(MONEY)
    periods = Column(Integer)                                           # additional payments: pay periods the payment relates to
    leave_pre1993 = Column(Boolean, nullable=False, default=False)
    genuine_redundancy = Column(Boolean, nullable=False, default=False)
    note = Column(String(300))
    created_by = Column(Integer)


class PayRunLine(Base):
    """One payroll transaction (an amount of one pay item for one employee in one run). Immutable once the run is finalised."""
    __tablename__ = "pay_run_lines"
    id = Column(BigInteger().with_variant(Integer, "sqlite"), primary_key=True, autoincrement=True)
    org_id = _ORG()
    run_id = Column(Integer, ForeignKey("pay_runs.id", ondelete="CASCADE"), nullable=False, index=True)
    run_employee_id = Column(Integer, ForeignKey("pay_run_employees.id", ondelete="CASCADE"), nullable=False, index=True)
    employee_id = Column(Integer, nullable=False, index=True)
    line_no = Column(Integer, nullable=False)
    txn_ref = Column(String(60), nullable=False)                       # PR-0001-E1001-003: stable, human-readable
    pay_item_id = Column(Integer)
    code = Column(String(20), nullable=False)
    name = Column(String(100), nullable=False)
    kind = Column(String(30), nullable=False)
    hours = Column(HOURS)
    rate = Column(RATE4)
    amount = Column(MONEY, nullable=False)
    taxable = Column(Boolean, nullable=False, default=True)
    payg_treatment = Column(String(20))
    super_treatment = Column(String(10))
    leave_type_id = Column(Integer)
    source = Column(String(60))
    note = Column(String(300))
    __table_args__ = (UniqueConstraint("run_id", "txn_ref", name="uq_pay_line_ref"),)


class PayPayslip(Base):
    __tablename__ = "pay_payslips"
    id = Column(Integer, primary_key=True)
    org_id = _ORG()
    run_id = Column(Integer, ForeignKey("pay_runs.id", ondelete="CASCADE"), nullable=False, index=True)
    run_employee_id = Column(Integer, ForeignKey("pay_run_employees.id", ondelete="CASCADE"), nullable=False, unique=True)
    employee_id = Column(Integer, nullable=False, index=True)
    payslip_no = Column(String(40), nullable=False)
    pay_date = Column(Date, nullable=False)
    snapshot = Column(JSON, nullable=False)                             # the frozen payslip content (incl. YTD) as at finalisation
    generated_at = Column(DateTime, default=datetime.utcnow)
    generated_by = Column(Integer)
    __table_args__ = (UniqueConstraint("org_id", "payslip_no", name="uq_pay_payslip_no"),)


class PayPayment(Base):
    __tablename__ = "pay_payments"
    id = Column(Integer, primary_key=True)
    org_id = _ORG()
    run_id = Column(Integer, ForeignKey("pay_runs.id", ondelete="RESTRICT"), nullable=False, index=True)
    batch_ref = Column(String(40), nullable=False)
    status = Column(String(12), nullable=False, default="prepared")     # prepared | completed | cancelled | failed
    method = Column(String(10), nullable=False, default="mock")         # mock | aba
    payment_date = Column(Date, nullable=False)
    total = Column(MONEY, nullable=False, default=0)
    item_count = Column(Integer, nullable=False, default=0)
    created_by = Column(Integer)
    created_at = Column(DateTime, default=datetime.utcnow)
    completed_at = Column(DateTime)
    completed_by = Column(Integer)
    journal_id = Column(Integer)                                        # ledger journal posted when the payment was completed (optional)
    cancel_reason = Column(String(300))
    __table_args__ = (UniqueConstraint("org_id", "batch_ref", name="uq_pay_batch"),
                      CheckConstraint(_in("status", ("prepared", "completed", "cancelled", "failed")), name="ck_pay_payment_status"),
                      Index("uq_pay_payment_live", "run_id", unique=True, postgresql_where=text("status IN ('prepared','completed')"),
                            sqlite_where=text("status IN ('prepared','completed')")))


class PayPaymentItem(Base):
    __tablename__ = "pay_payment_items"
    id = Column(Integer, primary_key=True)
    org_id = _ORG()
    payment_id = Column(Integer, ForeignKey("pay_payments.id", ondelete="CASCADE"), nullable=False, index=True)
    run_employee_id = Column(Integer, ForeignKey("pay_run_employees.id", ondelete="RESTRICT"), nullable=False)
    employee_id = Column(Integer, nullable=False, index=True)
    bank_id = Column(Integer, ForeignKey("pay_employee_bank.id", ondelete="SET NULL"))
    account_name = Column(String(100))
    bsb = Column(String(7))
    account_last4 = Column(String(4))
    amount = Column(MONEY, nullable=False)
    reference = Column(String(18))
    status = Column(String(10), nullable=False, default="pending")      # pending | paid | failed | returned
    paid_at = Column(DateTime)
    failure_reason = Column(String(200))
    reconciliation = Column(String(12), nullable=False, default="unreconciled")   # unreconciled | reconciled
    reconciled_at = Column(DateTime)
    reconciled_by = Column(Integer)
    __table_args__ = (CheckConstraint(_in("status", ("pending", "paid", "failed", "returned")), name="ck_pay_pi_status"),)


class PaySuperContribution(Base):
    __tablename__ = "pay_super_contribs"
    id = Column(Integer, primary_key=True)
    org_id = _ORG()
    run_id = Column(Integer, ForeignKey("pay_runs.id", ondelete="CASCADE"), nullable=False, index=True)
    run_employee_id = Column(Integer, ForeignKey("pay_run_employees.id", ondelete="CASCADE"), nullable=False)
    employee_id = Column(Integer, nullable=False, index=True)
    fund_id = Column(Integer, ForeignKey("pay_super_funds.id", ondelete="RESTRICT"), nullable=False)
    component = Column(String(20), nullable=False)                      # sg | salary_sacrifice | employer_additional | employee_after_tax
    amount = Column(MONEY, nullable=False)
    qualifying_earnings = Column(MONEY, nullable=False, default=0)
    due_date = Column(Date, nullable=False)
    status = Column(String(10), nullable=False, default="pending")      # pending | paid | reversed
    paid_at = Column(DateTime)
    payment_ref = Column(String(60))
    __table_args__ = (CheckConstraint(_in("component", ("sg", "salary_sacrifice", "employer_additional", "employee_after_tax")), name="ck_pay_sc_comp"),
                      CheckConstraint(_in("status", ("pending", "paid", "reversed")), name="ck_pay_sc_status"),
                      Index("ix_pay_sc_due", "org_id", "status", "due_date"))


class PayJournal(Base):
    """Links a pay run to the general-ledger journal it produced (Company -> Pay Run -> Employee -> Payroll transaction)."""
    __tablename__ = "pay_journals"
    id = Column(Integer, primary_key=True)
    org_id = _ORG()
    run_id = Column(Integer, ForeignKey("pay_runs.id", ondelete="RESTRICT"), nullable=False, unique=True)
    ledger_journal_id = Column(Integer, nullable=False)
    reversal_journal_id = Column(Integer)
    status = Column(String(10), nullable=False, default="posted")       # posted | reversed
    total_debit = Column(MONEY, nullable=False)
    total_credit = Column(MONEY, nullable=False)
    posted_at = Column(DateTime, default=datetime.utcnow)
    posted_by = Column(Integer)


class PayJournalLine(Base):
    __tablename__ = "pay_journal_lines"
    id = Column(Integer, primary_key=True)
    org_id = _ORG()
    pay_journal_id = Column(Integer, ForeignKey("pay_journals.id", ondelete="CASCADE"), nullable=False, index=True)
    component = Column(String(30), nullable=False)
    account_id = Column(Integer, nullable=False)
    account_code = Column(String(20))
    account_name = Column(String(200))
    employee_id = Column(Integer, index=True)
    run_employee_id = Column(Integer)
    pay_item_id = Column(Integer)
    txn_ref = Column(String(60))
    debit = Column(MONEY, nullable=False, default=0)
    credit = Column(MONEY, nullable=False, default=0)
    description = Column(String(300))


class PayAudit(Base):
    __tablename__ = "pay_audit"
    id = Column(BigInteger().with_variant(Integer, "sqlite"), primary_key=True, autoincrement=True)
    org_id = _ORG()
    occurred_at = Column(DateTime, nullable=False, default=datetime.utcnow, index=True)
    user_id = Column(Integer)
    username = Column(String(255))
    action = Column(String(60), nullable=False, index=True)
    entity_type = Column(String(40), nullable=False)
    entity_id = Column(String(40))
    entity_label = Column(String(200))
    summary = Column(String(500))
    before = Column(JSON)
    after = Column(JSON)
    __table_args__ = (Index("ix_pay_audit_entity", "org_id", "entity_type", "entity_id"),)


class PayStpEvent(Base):
    __tablename__ = "pay_stp_events"
    id = Column(Integer, primary_key=True)
    org_id = _ORG()
    event_type = Column(String(20), nullable=False)                     # pay_event | update_event | finalisation
    run_id = Column(Integer, ForeignKey("pay_runs.id", ondelete="SET NULL"))
    fy = Column(String(7), nullable=False)
    status = Column(String(14), nullable=False, default="draft")        # draft | mock_submitted
    payload = Column(JSON, nullable=False)
    mock_reference = Column(String(40))
    created_by = Column(Integer)
    created_at = Column(DateTime, default=datetime.utcnow)
    submitted_at = Column(DateTime)
    __table_args__ = (CheckConstraint(_in("status", ("draft", "mock_submitted")), name="ck_pay_stp_status"),)


class PayStpFinalisation(Base):
    __tablename__ = "pay_stp_final"
    id = Column(Integer, primary_key=True)
    org_id = _ORG()
    employee_id = Column(Integer, ForeignKey("pay_employees.id", ondelete="CASCADE"), nullable=False)
    fy = Column(String(7), nullable=False)
    gross = Column(MONEY, nullable=False, default=0)
    tax = Column(MONEY, nullable=False, default=0)
    super_total = Column(MONEY, nullable=False, default=0)
    finalised_at = Column(DateTime, default=datetime.utcnow)
    finalised_by = Column(Integer)
    __table_args__ = (UniqueConstraint("org_id", "employee_id", "fy", name="uq_pay_stp_final"),)


class PayNotification(Base):
    """In-app notification for a login (approver asked to decide, employee told of a decision). Email copies are sent best-effort alongside."""
    __tablename__ = "pay_notifications"
    id = Column(Integer, primary_key=True)
    org_id = _ORG()
    recipient_id = Column(Integer, nullable=False, index=True)          # the login (users.id) that should see it
    kind = Column(String(30), nullable=False)                           # timesheet_submitted | timesheet_approved | timesheet_rejected | leave_requested | leave_approved | leave_rejected
    title = Column(String(200), nullable=False)
    body = Column(String(500))
    entity_type = Column(String(30))
    entity_id = Column(Integer)
    link_tab = Column(String(20))                                       # where the bell takes the person: payroll tab + sub-tab
    link_sub = Column(String(20))
    is_read = Column(Boolean, nullable=False, default=False)
    emailed = Column(Boolean, nullable=False, default=False)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    __table_args__ = (Index("ix_pay_notif_user", "org_id", "recipient_id", "is_read"),)


PAYROLL_TABLES = [c.__table__ for c in (
    PaySettings, PayDepartment, PayLocation, PayCalendar, PayItem, PayLeaveType, PaySuperFund, PayEmployee, PayEmployeeTax, PayEmployeeSuper,
    PayEmployeeBank, PayEmployeeItem, PayRun, PayTimesheet, PayTimesheetLine, PayLeaveRequest, PayLeaveTxn, PayRunEmployee, PayRunInput, PayRunLine,
    PayPayslip, PayPayment, PayPaymentItem, PaySuperContribution, PayJournal, PayJournalLine, PayAudit, PayStpEvent, PayStpFinalisation, PayNotification)]
