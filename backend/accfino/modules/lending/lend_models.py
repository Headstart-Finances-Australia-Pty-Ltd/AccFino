"""Smart Lending, Credit & Treasury data model (tables lend_*). Every table carries org_id and every query filters on it.

Applicants are EXISTING contacts (a profile adds only the lending-specific facts). Loan balances, arrears and schedules are NOT stored: they are recomputed from the loan's terms, rate changes and repayments
(engine/amort.py), so they cannot drift. Decisions (status changes, assessments, overrides) are immutable events with who, when and why."""
from datetime import datetime

from sqlalchemy import JSON, Boolean, Column, Date, DateTime, ForeignKey, Index, Integer, Numeric, String, Text, UniqueConstraint

from accfino.shared.db.base import Base

MONEY, RATE = Numeric(18, 2), Numeric(9, 6)
APP_STATUSES = ("draft", "submitted", "assessing", "more_information", "approved", "declined", "settled", "withdrawn")
LOAN_TYPES = ("term_loan", "interest_only", "line_of_credit", "overdraft", "car_loan", "personal_loan", "home_loan", "business_loan", "equipment_lease", "hire_purchase", "other")
FREQUENCIES = ("weekly", "fortnightly", "monthly", "quarterly")
LOAN_STATUSES = ("active", "paid_out", "refinanced", "written_off", "cancelled")
# EXACTLY the households the HEM benchmark table (metrics.HEM_BENCHMARKS) has a figure for: an unknown key would silently fall back to the single-person benchmark and flatter a family.
HOUSEHOLDS = ("single_no_children", "couple_no_children", "couple_1_child", "couple_2_children")
EMPLOYMENT = ("paye_full_time", "paye_part_time", "casual", "self_employed", "contractor", "retired", "unemployed", "other")
COLLECTION_KINDS = ("call", "sms", "email", "letter", "visit", "promise_to_pay", "note", "escalated")
HARDSHIP_STATUSES = ("requested", "assessing", "approved", "declined", "active", "completed")
ARRANGEMENT_STATUSES = ("active", "completed", "broken", "cancelled")
FACILITY_TYPES = ("overdraft", "line_of_credit", "term_loan", "invoice_finance", "equipment_finance", "credit_card", "other")
COMMITMENT_KINDS = ("home_loan", "investment_loan", "car_loan", "personal_loan", "credit_card", "hecs_help", "buy_now_pay_later", "child_support", "other")


class Org:
    org_id = Column(Integer, nullable=False, index=True)


class LendSettings(Base):
    __tablename__ = "lend_settings"
    org_id = Column(Integer, primary_key=True)
    policy = Column(JSON, nullable=False, default=dict)               # overrides of engine.credit.POLICY (dti_limit, serviceability_buffer, max_lti, lvr_cap ...)
    min_cash_buffer = Column(Numeric(18, 2), nullable=False, default=0)
    updated_by = Column(Integer)
    updated_at = Column(DateTime, default=datetime.utcnow)


class LendApplicantProfile(Base, Org):
    __tablename__ = "lend_applicant_profiles"
    id = Column(Integer, primary_key=True)
    contact_id = Column(Integer, nullable=False)
    household_type = Column(String(30), nullable=False, default="single_no_children")
    dependants = Column(Integer, nullable=False, default=0)
    employment_type = Column(String(30))
    employer = Column(String(200))
    employment_months = Column(Integer)
    residency = Column(String(40))
    notes = Column(Text)
    created_by = Column(Integer)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    __table_args__ = (UniqueConstraint("org_id", "contact_id", name="uq_lend_profile_contact"),)


class LendCommitment(Base, Org):
    """An existing debt of an applicant: declared by them, or detected in their statements and confirmed by the agent."""
    __tablename__ = "lend_commitments"
    id = Column(Integer, primary_key=True)
    contact_id = Column(Integer, nullable=False, index=True)
    kind = Column(String(30), nullable=False)
    lender = Column(String(200))
    limit_amount = Column(MONEY)
    balance = Column(MONEY)
    monthly_repayment = Column(MONEY, nullable=False, default=0)
    interest_rate = Column(RATE)
    source = Column(String(12), nullable=False, default="declared")      # declared | detected
    notes = Column(Text)
    created_by = Column(Integer)
    created_at = Column(DateTime, default=datetime.utcnow)


class LendAnalysis(Base, Org):
    """A saved statement analysis: the classified lines (LendAnalysisLine), the metrics from the existing engine, the Applicant Financial Summary and the gap report."""
    __tablename__ = "lend_analyses"
    id = Column(Integer, primary_key=True)
    contact_id = Column(Integer, nullable=False, index=True)
    application_id = Column(Integer, index=True)
    source = Column(String(12), nullable=False, default="upload")        # upload | books
    label = Column(String(200))
    period_from = Column(Date)
    period_to = Column(Date)
    months = Column(Integer, nullable=False, default=0)
    tx_count = Column(Integer, nullable=False, default=0)
    metrics = Column(JSON, nullable=False, default=dict)                  # the flat LendingMetrics fields
    summary = Column(JSON, nullable=False, default=dict)
    reviewed = Column(JSON, nullable=False, default=list)                 # credits treated as transfers rather than income, for the agent to confirm
    gap_report = Column(JSON, nullable=False, default=dict)
    inputs = Column(JSON, nullable=False, default=dict)                   # household type, proposed loan used
    superseded = Column(Boolean, nullable=False, default=False)
    created_by = Column(Integer)
    created_at = Column(DateTime, default=datetime.utcnow)


class LendAnalysisLine(Base, Org):
    __tablename__ = "lend_analysis_lines"
    id = Column(Integer, primary_key=True)
    analysis_id = Column(Integer, ForeignKey("lend_analyses.id"), nullable=False, index=True)
    line_date = Column(Date)
    description = Column(String(500))
    debit = Column(MONEY, nullable=False, default=0)
    credit = Column(MONEY, nullable=False, default=0)
    balance = Column(MONEY)
    category = Column(String(80))
    hem_group = Column(String(60))
    exp_type = Column(String(2))
    is_income = Column(Boolean, nullable=False, default=False)
    reclassified = Column(String(300))                                    # set by the system when a credit is treated as a transfer
    override_category = Column(String(80))                                # set by the agent
    override_reason = Column(String(300))
    override_by = Column(Integer)
    source_file = Column(String(200))


class LendApplication(Base, Org):
    __tablename__ = "lend_applications"
    id = Column(Integer, primary_key=True)
    number = Column(String(20), nullable=False)
    contact_id = Column(Integer, nullable=False, index=True)
    purpose = Column(String(300))
    loan_type = Column(String(30), nullable=False, default="term_loan")
    amount = Column(MONEY, nullable=False, default=0)
    term_months = Column(Integer, nullable=False, default=0)
    rate = Column(RATE)
    repayment_frequency = Column(String(12), nullable=False, default="monthly")
    interest_only = Column(Boolean, nullable=False, default=False)
    lender = Column(String(200))
    security_description = Column(String(300))
    security_value = Column(MONEY)
    status = Column(String(20), nullable=False, default="draft", index=True)
    assigned_to = Column(Integer)
    submitted_at = Column(DateTime)
    decided_at = Column(DateTime)
    decided_by = Column(Integer)
    decision_reason = Column(Text)
    loan_id = Column(Integer)
    notes = Column(Text)
    created_by = Column(Integer)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    __table_args__ = (UniqueConstraint("org_id", "number", name="uq_lend_app_number"),)


class LendApplicationEvent(Base, Org):
    """Immutable history of an application: status changes, notes, assessments, decisions and overrides, each with who, when and why."""
    __tablename__ = "lend_application_events"
    id = Column(Integer, primary_key=True)
    application_id = Column(Integer, nullable=False, index=True)
    at = Column(DateTime, nullable=False, default=datetime.utcnow)
    by_user_id = Column(Integer)
    by_name = Column(String(100))
    kind = Column(String(20), nullable=False)                             # status | note | assessment | decision | override | document
    from_status = Column(String(20))
    to_status = Column(String(20))
    reason = Column(Text)
    detail = Column(JSON)


class LendDocRequirement(Base, Org):
    """What the agent still needs for an application, and the stored document that satisfies it (an Accounting attachment)."""
    __tablename__ = "lend_doc_requirements"
    id = Column(Integer, primary_key=True)
    application_id = Column(Integer, nullable=False, index=True)
    key = Column(String(40), nullable=False)
    label = Column(String(200), nullable=False)
    required = Column(Boolean, nullable=False, default=True)
    attachment_id = Column(Integer)
    received_at = Column(DateTime)
    received_by = Column(Integer)
    __table_args__ = (UniqueConstraint("org_id", "application_id", "key", name="uq_lend_doc_req"),)


class LendAssessment(Base, Org):
    __tablename__ = "lend_assessments"
    id = Column(Integer, primary_key=True)
    application_id = Column(Integer, nullable=False, index=True)
    analysis_id = Column(Integer)
    version = Column(Integer, nullable=False, default=1)
    score = Column(Numeric(5, 1), nullable=False)
    grade = Column(String(2), nullable=False)
    outcome = Column(String(30), nullable=False)                          # the engine's recommendation
    result = Column(JSON, nullable=False, default=dict)                   # factors, flags, missing info, cash flow: everything shown to the agent
    notes = Column(Text)
    created_by = Column(Integer)
    created_at = Column(DateTime, default=datetime.utcnow)
    override_outcome = Column(String(30))                                 # an authorised person's different decision, with the reason
    override_reason = Column(Text)
    override_by = Column(Integer)
    override_by_name = Column(String(100))
    override_at = Column(DateTime)


class LendLoan(Base, Org):
    __tablename__ = "lend_loans"
    id = Column(Integer, primary_key=True)
    number = Column(String(20), nullable=False)
    contact_id = Column(Integer, nullable=False, index=True)
    application_id = Column(Integer)
    lender = Column(String(200))
    loan_type = Column(String(30), nullable=False, default="term_loan")
    purpose = Column(String(300))
    original_amount = Column(MONEY, nullable=False)
    rate = Column(RATE, nullable=False)
    term_periods = Column(Integer, nullable=False)
    frequency = Column(String(12), nullable=False, default="monthly")
    start_date = Column(Date, nullable=False)
    first_due = Column(Date, nullable=False)
    interest_only_periods = Column(Integer, nullable=False, default=0)
    balloon = Column(MONEY, nullable=False, default=0)
    status = Column(String(20), nullable=False, default="active", index=True)
    refinanced_from_id = Column(Integer)
    refinanced_to_id = Column(Integer)
    security_description = Column(String(300))
    fixed_asset_id = Column(Integer)                                      # an Accounting fixed asset (lease / hire purchase asset), if linked
    ledger_loan_account_id = Column(Integer)                              # optional: post this loan's repayments through the ledger
    ledger_interest_account_id = Column(Integer)
    ledger_bank_account_id = Column(Integer)
    notes = Column(Text)
    created_by = Column(Integer)
    created_at = Column(DateTime, default=datetime.utcnow)
    closed_at = Column(DateTime)
    __table_args__ = (UniqueConstraint("org_id", "number", name="uq_lend_loan_number"),)


class LendRateChange(Base, Org):
    __tablename__ = "lend_rate_changes"
    id = Column(Integer, primary_key=True)
    loan_id = Column(Integer, nullable=False, index=True)
    effective_date = Column(Date, nullable=False)
    rate = Column(RATE, nullable=False)
    note = Column(String(300))
    created_by = Column(Integer)
    created_at = Column(DateTime, default=datetime.utcnow)


class LendRepayment(Base, Org):
    __tablename__ = "lend_repayments"
    id = Column(Integer, primary_key=True)
    loan_id = Column(Integer, nullable=False, index=True)
    paid_date = Column(Date, nullable=False)
    amount = Column(MONEY, nullable=False)
    method = Column(String(30))
    reference = Column(String(100))
    bank_line_id = Column(Integer)                                        # the bank transaction this repayment was matched to, if any
    journal_id = Column(Integer)                                          # the ledger journal, if posted
    voided = Column(Boolean, nullable=False, default=False)
    voided_reason = Column(String(300))
    created_by = Column(Integer)
    created_at = Column(DateTime, default=datetime.utcnow)
    __table_args__ = (Index("ix_lend_repay_loan_date", "org_id", "loan_id", "paid_date"),)


class LendCollectionActivity(Base, Org):
    __tablename__ = "lend_collection_activities"
    id = Column(Integer, primary_key=True)
    loan_id = Column(Integer, nullable=False, index=True)
    activity_date = Column(Date, nullable=False)
    kind = Column(String(20), nullable=False)
    outcome = Column(String(200))
    notes = Column(Text)
    next_action_date = Column(Date)
    created_by = Column(Integer)
    created_at = Column(DateTime, default=datetime.utcnow)


class LendArrangement(Base, Org):
    """A payment arrangement agreed to clear arrears."""
    __tablename__ = "lend_arrangements"
    id = Column(Integer, primary_key=True)
    loan_id = Column(Integer, nullable=False, index=True)
    start_date = Column(Date, nullable=False)
    end_date = Column(Date)
    amount_per_period = Column(MONEY, nullable=False)
    frequency = Column(String(12), nullable=False, default="fortnightly")
    arrears_at_start = Column(MONEY, nullable=False, default=0)
    status = Column(String(12), nullable=False, default="active")
    notes = Column(Text)
    created_by = Column(Integer)
    created_at = Column(DateTime, default=datetime.utcnow)


class LendHardship(Base, Org):
    __tablename__ = "lend_hardship"
    id = Column(Integer, primary_key=True)
    loan_id = Column(Integer, nullable=False, index=True)
    requested_date = Column(Date, nullable=False)
    reason = Column(String(300), nullable=False)
    status = Column(String(12), nullable=False, default="requested")
    relief = Column(String(60))                                           # e.g. reduced repayments, pause, extended term
    outcome = Column(Text)
    review_date = Column(Date)
    arrangement_id = Column(Integer)
    decided_by = Column(Integer)
    decided_at = Column(DateTime)
    notes = Column(Text)
    created_by = Column(Integer)
    created_at = Column(DateTime, default=datetime.utcnow)


class LendFacility(Base, Org):
    """A funding facility the organisation holds: its limit, how much is drawn, and its repayments."""
    __tablename__ = "lend_facilities"
    id = Column(Integer, primary_key=True)
    name = Column(String(200), nullable=False)
    lender = Column(String(200))
    facility_type = Column(String(30), nullable=False, default="line_of_credit")
    limit_amount = Column(MONEY, nullable=False)
    drawn_amount = Column(MONEY, nullable=False, default=0)
    ledger_account_id = Column(Integer)                                   # if linked, the drawn amount is read from the ledger instead
    interest_rate = Column(RATE)
    expiry_date = Column(Date)
    repayment_amount = Column(MONEY)
    repayment_frequency = Column(String(12))
    next_repayment_date = Column(Date)
    status = Column(String(12), nullable=False, default="active")
    notes = Column(Text)
    created_by = Column(Integer)
    created_at = Column(DateTime, default=datetime.utcnow)


class LendForecastItem(Base, Org):
    """A cash movement someone EXPECTS but nobody is bound to (kept apart from committed flows)."""
    __tablename__ = "lend_forecast_items"
    id = Column(Integer, primary_key=True)
    item_date = Column(Date, nullable=False)
    amount = Column(MONEY, nullable=False)                                # inflow positive, outflow negative
    description = Column(String(200), nullable=False)
    category = Column(String(60))
    status = Column(String(12), nullable=False, default="expected")      # expected | received | cancelled
    created_by = Column(Integer)
    created_at = Column(DateTime, default=datetime.utcnow)


LEND_TABLES = [m.__table__ for m in (LendSettings, LendApplicantProfile, LendCommitment, LendAnalysis, LendAnalysisLine, LendApplication, LendApplicationEvent, LendDocRequirement, LendAssessment, LendLoan, LendRateChange,
                                     LendRepayment, LendCollectionActivity, LendArrangement, LendHardship, LendFacility, LendForecastItem)]
