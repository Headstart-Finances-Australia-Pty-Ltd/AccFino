"""
accfino.modules.taxation.models.tax
-----------------------------------
Taxation & Compliance tables (prefix tax_). Every row belongs to an organisation (org_id). Money is NUMERIC(18,2).
Principles: the ledger remains the only source of financial data, so these tables hold only what the ledger cannot: the tax profile, obligations, user
adjustments and overrides, workpapers and evidence, snapshots of what was reviewed/approved/lodged, and a tamper-evident audit trail. A TFN is NEVER stored.
"""
from datetime import datetime

from sqlalchemy import (JSON, Boolean, CheckConstraint, Column, Date, DateTime, ForeignKey, Index, Integer, LargeBinary, Numeric, String, Text,
                        UniqueConstraint)

from accfino.shared.db.base import Base
from accfino.shared.db.types import MONEY

_ORG = lambda: Column(Integer, ForeignKey("organisations.id", ondelete="CASCADE"), nullable=False, index=True)


def _in(col, values):
    return f"{col} IN ({', '.join(repr(v) for v in values)})"


ENTITY_TYPES = ("individual", "sole_trader", "company", "partnership", "trust", "smsf")
BAS_FREQUENCIES = ("monthly", "quarterly", "annual", "none")
INSTALMENT_METHODS = ("none", "amount", "rate")
WORKFLOW = ("draft", "prepared", "approved", "lodged", "paid", "void")
OBLIGATION_STATUSES = ("upcoming", "in_progress", "prepared", "lodged", "paid", "completed", "not_required")
OBLIGATION_KINDS = ("bas", "ias", "fbt_return", "income_tax_return", "tpar", "div7a_repayment", "div7a_agreement", "payroll_tax", "asic_review", "custom")
ADJ_CATEGORIES = ("user_entered", "calculated", "assumption", "estimate")
WORKPAPER_AREAS = ("bas", "income_tax", "cgt", "fbt", "div7a", "assets", "payroll", "gst", "general")
WORKPAPER_STATUSES = ("draft", "prepared", "reviewed", "approved")
EVIDENCE_KINDS = ("file", "attachment", "ledger_ref", "url", "note")
CGT_HOLDERS = ("individual", "trust", "company", "super")
CGT_CLASSES = ("shares", "etf", "crypto", "property", "business_asset", "other")
FBT_TYPES = ("car", "loan", "expense_payment", "property", "residual", "entertainment", "other")
SIGNOFF_CAPACITIES = ("taxpayer", "tax_agent", "bas_agent")
SIGNOFF_DOC_TYPES = ("bas_statement", "tax_return", "fbt_return")
LODGEMENT_POLICIES = ("self_declaration", "agent_signoff_required")
LODGEMENT_PROVIDERS = ("manual", "agent_pack", "sandbox", "sbr_gateway")
LODGEMENT_STATUSES = ("handed_off", "submitted", "accepted", "rejected", "failed", "simulated")
REGISTRATION_KINDS = ("abn", "gst", "payg_withholding", "payg_instalments", "fbt", "stp", "fuel_tax_credits", "wet", "lct", "payroll_tax", "land_tax", "asic", "workers_comp", "other")


class Workflow:
    """Preparer -> reviewer/approver -> lodged (recorded by the user: AccFino does not transmit to the ATO) -> paid."""
    status = Column(String(12), nullable=False, default="draft")
    prepared_by = Column(Integer)
    prepared_at = Column(DateTime)
    approved_by = Column(Integer)
    approved_at = Column(DateTime)
    approval_note = Column(String(500))
    lodged_on = Column(Date)
    lodged_by = Column(Integer)
    lodgement_method = Column(String(40))       # ato_online_services | tax_agent | other
    lodgement_reference = Column(String(80))    # the ATO receipt / reference the user recorded
    paid_on = Column(Date)
    version = Column(Integer, nullable=False, default=1)
    created_by = Column(Integer)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class TaxProfile(Base):
    __tablename__ = "tax_profiles"
    org_id = Column(Integer, ForeignKey("organisations.id", ondelete="CASCADE"), primary_key=True)
    entity_type = Column(String(20), nullable=False, default="company")
    residency = Column(String(10), nullable=False, default="resident")                  # resident | foreign
    abn = Column(String(20))
    gst_registered = Column(Boolean, nullable=False, default=True)
    gst_basis = Column(String(10), nullable=False, default="accrual")
    bas_frequency = Column(String(10), nullable=False, default="quarterly")
    payg_withholding = Column(Boolean, nullable=False, default=False)
    payg_instalment_method = Column(String(10), nullable=False, default="none")
    payg_instalment_amount = Column(MONEY)                                               # per period, as notified by the ATO (T7)
    payg_instalment_rate = Column(Numeric(7, 4))                                         # percent, as notified by the ATO (T2)
    fbt_registered = Column(Boolean, nullable=False, default=False)
    fbt_instalment_amount = Column(MONEY)
    tpar_required = Column(Boolean, nullable=False, default=False)
    aggregated_turnover = Column(MONEY)                                                  # current-year aggregated turnover estimate / prior year actual
    aggregated_turnover_basis = Column(String(200))
    passive_income_ratio = Column(Numeric(7, 4))                                         # 0..1, companies only (base rate entity test)
    simplified_depreciation = Column(Boolean, nullable=False, default=True)
    pool_opening_balance = Column(MONEY)                                                 # small business pool opening balance for the CURRENT year
    state = Column(String(3))                                                            # NSW VIC QLD WA SA TAS ACT NT
    uses_agent_program = Column(Boolean, nullable=False, default=False)
    has_tax_agent = Column(Boolean, nullable=False, default=False)
    tax_agent_name = Column(String(200))
    tax_agent_number = Column(String(20))
    asic_review_date = Column(String(5))                                                 # MM-DD
    extra_holidays = Column(JSON)                                                        # ["2026-11-03", ...] state holidays added by the organisation
    allow_self_approval = Column(Boolean, nullable=False, default=False)                 # single-person businesses; every use is audited
    lodgement_policy = Column(String(24), nullable=False, default="self_declaration")    # self_declaration | agent_signoff_required (a registered agent must sign off before lodgement is recorded)
    notes = Column(Text)
    updated_by = Column(Integer)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    __table_args__ = (CheckConstraint(_in("entity_type", ENTITY_TYPES), name="ck_tax_prof_entity"), CheckConstraint(_in("bas_frequency", BAS_FREQUENCIES), name="ck_tax_prof_basfreq"),
                      CheckConstraint(_in("payg_instalment_method", INSTALMENT_METHODS), name="ck_tax_prof_inst"), CheckConstraint(_in("residency", ("resident", "foreign")), name="ck_tax_prof_res"))


class TaxRuleOverride(Base):
    __tablename__ = "tax_rule_overrides"
    id = Column(Integer, primary_key=True)
    org_id = _ORG()
    rule_set_id = Column(String(10), nullable=False)
    path = Column(String(120), nullable=False)
    value = Column(JSON)
    reason = Column(String(500), nullable=False)
    set_by = Column(Integer)
    set_at = Column(DateTime, default=datetime.utcnow)
    __table_args__ = (UniqueConstraint("org_id", "rule_set_id", "path", name="uq_tax_override"),)


class TaxRegistration(Base):
    __tablename__ = "tax_registrations"
    id = Column(Integer, primary_key=True)
    org_id = _ORG()
    kind = Column(String(20), nullable=False)
    authority = Column(String(60))
    identifier = Column(String(60))                                                      # e.g. ABN, state revenue number (never a TFN)
    registered_on = Column(Date)
    cancelled_on = Column(Date)
    notes = Column(String(500))
    created_by = Column(Integer)
    created_at = Column(DateTime, default=datetime.utcnow)
    __table_args__ = (CheckConstraint(_in("kind", REGISTRATION_KINDS), name="ck_tax_reg_kind"),)


class TaxObligation(Base):
    __tablename__ = "tax_obligations"
    id = Column(Integer, primary_key=True)
    org_id = _ORG()
    kind = Column(String(20), nullable=False)
    title = Column(String(200), nullable=False)
    authority = Column(String(60), default="ATO")
    fy = Column(String(7), index=True)
    period_start = Column(Date)
    period_end = Column(Date)
    due_date = Column(Date, nullable=False, index=True)
    original_due_date = Column(Date)
    agent_due_date = Column(Date)
    status = Column(String(14), nullable=False, default="upcoming")
    lodged_on = Column(Date)
    paid_on = Column(Date)
    reference = Column(String(80))
    amount = Column(MONEY)                                                               # amount payable (+) / refundable (-) once known
    linked_type = Column(String(30))                                                     # bas_statement | tax_return | fbt_return
    linked_id = Column(Integer)
    source_key = Column(String(120))                                                     # generated rows: unique per org so regeneration is idempotent
    auto_generated = Column(Boolean, nullable=False, default=True)
    note = Column(String(500))
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    __table_args__ = (CheckConstraint(_in("status", OBLIGATION_STATUSES), name="ck_tax_ob_status"), UniqueConstraint("org_id", "source_key", name="uq_tax_ob_source"))


class TaxBasStatement(Base, Workflow):
    __tablename__ = "tax_bas_statements"
    id = Column(Integer, primary_key=True)
    org_id = _ORG()
    kind = Column(String(4), nullable=False, default="bas")                              # bas | ias
    fy = Column(String(7), nullable=False, index=True)
    period_start = Column(Date, nullable=False)
    period_end = Column(Date, nullable=False)
    frequency = Column(String(10))
    basis = Column(String(10))                                                           # accrual | cash (the GST basis used)
    labels = Column(JSON)                                                                # calculated labels {label: {value, kind, source, note}}
    overrides = Column(JSON)                                                             # {label: {value, reason, by, at}}
    final = Column(JSON)                                                                 # labels after overrides
    snapshot = Column(JSON)                                                              # inputs + checks captured at calculation time
    findings = Column(JSON)                                                              # validation result at last calculation
    amount_payable = Column(MONEY)                                                       # label 9 (final)
    due_date = Column(Date)
    obligation_id = Column(Integer, ForeignKey("tax_obligations.id", ondelete="SET NULL"))
    void_reason = Column(String(300))
    calc_hash = Column(String(64))
    __table_args__ = (CheckConstraint(_in("status", WORKFLOW), name="ck_tax_bas_status"), CheckConstraint(_in("kind", ("bas", "ias")), name="ck_tax_bas_kind"),
                      Index("ix_tax_bas_period", "org_id", "period_start", "period_end"))


class TaxAdjustment(Base):
    __tablename__ = "tax_adjustments"
    id = Column(Integer, primary_key=True)
    org_id = _ORG()
    fy = Column(String(7), nullable=False, index=True)
    code = Column(String(40), nullable=False)
    description = Column(String(300), nullable=False)
    direction = Column(String(6), nullable=False)                                        # add (increases taxable income) | deduct
    amount = Column(MONEY, nullable=False)
    category = Column(String(14), nullable=False, default="user_entered")
    source = Column(String(30), default="manual")                                        # manual | assets_review | fbt | cgt | import
    source_key = Column(String(120))                                                     # generated rows: replaced, not duplicated, on re-run
    requires_review = Column(Boolean, nullable=False, default=False)
    review_note = Column(String(500))
    reviewed_by = Column(Integer)
    reviewed_at = Column(DateTime)
    workpaper_id = Column(Integer, ForeignKey("tax_workpapers.id", ondelete="SET NULL"))
    created_by = Column(Integer)
    created_at = Column(DateTime, default=datetime.utcnow)
    __table_args__ = (CheckConstraint(_in("direction", ("add", "deduct")), name="ck_tax_adj_dir"), CheckConstraint(_in("category", ADJ_CATEGORIES), name="ck_tax_adj_cat"),
                      CheckConstraint("amount >= 0", name="ck_tax_adj_amt"), Index("ix_tax_adj_src", "org_id", "fy", "source_key"))


class TaxReturn(Base, Workflow):
    __tablename__ = "tax_returns"
    id = Column(Integer, primary_key=True)
    org_id = _ORG()
    fy = Column(String(7), nullable=False)
    entity_type = Column(String(20), nullable=False)
    inputs = Column(JSON)                                                                # user-entered inputs (other income, offsets, losses, allocations...)
    accounting = Column(JSON)                                                            # ledger profit snapshot used
    computation = Column(JSON)                                                           # engine output (steps, warnings)
    findings = Column(JSON)
    taxable_income = Column(MONEY)
    tax_payable = Column(MONEY)                                                          # balance payable(+)/refundable(-)
    assessed_amount = Column(MONEY)                                                      # the ATO notice of assessment amount the user recorded
    assessed_on = Column(Date)
    due_date = Column(Date)
    obligation_id = Column(Integer, ForeignKey("tax_obligations.id", ondelete="SET NULL"))
    calc_hash = Column(String(64))
    void_reason = Column(String(300))
    __table_args__ = (CheckConstraint(_in("status", WORKFLOW), name="ck_tax_ret_status"), CheckConstraint(_in("entity_type", ENTITY_TYPES), name="ck_tax_ret_entity"),
                      UniqueConstraint("org_id", "fy", "entity_type", "version", name="uq_tax_ret_version"))


class TaxCgtEvent(Base):
    __tablename__ = "tax_cgt_events"
    id = Column(Integer, primary_key=True)
    org_id = _ORG()
    fy = Column(String(7), nullable=False, index=True)
    asset_class = Column(String(20), nullable=False, default="shares")
    asset_name = Column(String(200), nullable=False)
    quantity = Column(Numeric(24, 8))
    acquire_date = Column(Date, nullable=False)
    dispose_date = Column(Date, nullable=False)
    proceeds = Column(MONEY, nullable=False)
    acquisition_cost = Column(MONEY, nullable=False, default=0)
    incidental_costs = Column(MONEY, nullable=False, default=0)
    ownership_costs = Column(MONEY, nullable=False, default=0)
    capital_improvements = Column(MONEY, nullable=False, default=0)
    disposal_costs = Column(MONEY, nullable=False, default=0)
    pre_cgt = Column(Boolean, nullable=False, default=False)
    main_residence_exempt = Column(Boolean, nullable=False, default=False)
    small_business = Column(JSON)                                                        # {active_asset_reduction, exempt_15yr, retirement_exemption, rollover}
    source = Column(String(20), nullable=False, default="manual")                        # manual | trading_import | csv_import | property
    source_ref = Column(String(120))
    excluded = Column(Boolean, nullable=False, default=False)
    notes = Column(String(500))
    created_by = Column(Integer)
    created_at = Column(DateTime, default=datetime.utcnow)
    __table_args__ = (CheckConstraint(_in("asset_class", CGT_CLASSES), name="ck_tax_cgt_class"), CheckConstraint("dispose_date >= acquire_date", name="ck_tax_cgt_dates"),
                      Index("ix_tax_cgt_src", "org_id", "source", "source_ref"))


class TaxCapitalLoss(Base):
    __tablename__ = "tax_capital_losses"
    id = Column(Integer, primary_key=True)
    org_id = _ORG()
    fy_incurred = Column(String(7), nullable=False)
    amount = Column(MONEY, nullable=False)
    note = Column(String(300))
    created_by = Column(Integer)
    created_at = Column(DateTime, default=datetime.utcnow)
    __table_args__ = (CheckConstraint("amount >= 0", name="ck_tax_closs_amt"),)


class TaxFbtBenefit(Base):
    __tablename__ = "tax_fbt_benefits"
    id = Column(Integer, primary_key=True)
    org_id = _ORG()
    fbt_year = Column(String(8), nullable=False, index=True)                              # FBT2027 = 1 Apr 2026 - 31 Mar 2027
    employee = Column(String(200))
    employee_id = Column(Integer)                                                        # pay_employees.id when picked from Payroll (no FK: module boundary)
    benefit_type = Column(String(20), nullable=False)
    description = Column(String(300))
    type1 = Column(Boolean, nullable=False, default=True)                                 # employer entitled to a GST credit
    inputs = Column(JSON)                                                                # valuation inputs
    taxable_value = Column(MONEY, nullable=False, default=0)
    method = Column(String(30))
    notes = Column(JSON)
    created_by = Column(Integer)
    created_at = Column(DateTime, default=datetime.utcnow)
    __table_args__ = (CheckConstraint(_in("benefit_type", FBT_TYPES), name="ck_tax_fbt_type"),)


class TaxFbtReturn(Base, Workflow):
    __tablename__ = "tax_fbt_returns"
    id = Column(Integer, primary_key=True)
    org_id = _ORG()
    fbt_year = Column(String(8), nullable=False)
    summary = Column(JSON)
    fbt_payable = Column(MONEY)
    due_date = Column(Date)
    calc_hash = Column(String(64))
    obligation_id = Column(Integer, ForeignKey("tax_obligations.id", ondelete="SET NULL"))
    __table_args__ = (CheckConstraint(_in("status", WORKFLOW), name="ck_tax_fbtr_status"), UniqueConstraint("org_id", "fbt_year", name="uq_tax_fbt_return"))


class TaxDiv7aLoan(Base):
    __tablename__ = "tax_div7a_loans"
    id = Column(Integer, primary_key=True)
    org_id = _ORG()
    borrower = Column(String(200), nullable=False)                                       # shareholder or associate
    advance_date = Column(Date, nullable=False)
    principal = Column(MONEY, nullable=False)
    term_years = Column(Integer, nullable=False, default=7)
    secured = Column(Boolean, nullable=False, default=False)
    agreement_date = Column(Date)                                                        # written agreement
    ledger_account_id = Column(Integer)                                                  # loan account in the chart of accounts (for reconciliation)
    status = Column(String(10), nullable=False, default="active")                        # active | repaid | deemed_dividend
    notes = Column(String(500))
    created_by = Column(Integer)
    created_at = Column(DateTime, default=datetime.utcnow)
    __table_args__ = (CheckConstraint("principal > 0", name="ck_tax_d7a_principal"),)


class TaxDiv7aPayment(Base):
    __tablename__ = "tax_div7a_payments"
    id = Column(Integer, primary_key=True)
    org_id = _ORG()
    loan_id = Column(Integer, ForeignKey("tax_div7a_loans.id", ondelete="CASCADE"), nullable=False, index=True)
    paid_on = Column(Date, nullable=False)
    amount = Column(MONEY, nullable=False)
    kind = Column(String(12), nullable=False, default="repayment")                       # repayment | interest
    note = Column(String(300))
    __table_args__ = (CheckConstraint(_in("kind", ("repayment", "interest")), name="ck_tax_d7a_kind"), CheckConstraint("amount > 0", name="ck_tax_d7a_pay"))


class TaxWorkpaper(Base):
    __tablename__ = "tax_workpapers"
    id = Column(Integer, primary_key=True)
    org_id = _ORG()
    fy = Column(String(8), nullable=False, index=True)
    area = Column(String(14), nullable=False)
    title = Column(String(200), nullable=False)
    reference = Column(String(30))
    status = Column(String(10), nullable=False, default="draft")
    content = Column(JSON)                                                               # {"lines":[{label, amount, kind, source, note}], "conclusion": "..."}
    linked_type = Column(String(30))
    linked_id = Column(Integer)
    prepared_by = Column(Integer)
    prepared_at = Column(DateTime)
    reviewed_by = Column(Integer)
    reviewed_at = Column(DateTime)
    review_note = Column(String(500))
    created_by = Column(Integer)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    __table_args__ = (CheckConstraint(_in("area", WORKPAPER_AREAS), name="ck_tax_wp_area"), CheckConstraint(_in("status", WORKPAPER_STATUSES), name="ck_tax_wp_status"))


class TaxEvidence(Base):
    __tablename__ = "tax_evidence"
    id = Column(Integer, primary_key=True)
    org_id = _ORG()
    workpaper_id = Column(Integer, ForeignKey("tax_workpapers.id", ondelete="CASCADE"), index=True)
    linked_type = Column(String(30))                                                     # bas_statement | tax_return | cgt_event | fbt_benefit | div7a_loan | adjustment
    linked_id = Column(Integer)
    kind = Column(String(12), nullable=False)
    title = Column(String(200), nullable=False)
    note = Column(String(500))
    url = Column(String(500))
    attachment_id = Column(Integer)                                                      # accounting attachments.id (an existing Documents record), no FK: module boundary
    ledger_ref = Column(String(120))                                                     # e.g. "journal:J-00042"
    file_name = Column(String(255))
    content_type = Column(String(100))
    size = Column(Integer)
    sha256 = Column(String(64))
    data = Column(LargeBinary)
    uploaded_by = Column(Integer)
    created_at = Column(DateTime, default=datetime.utcnow)
    __table_args__ = (CheckConstraint(_in("kind", EVIDENCE_KINDS), name="ck_tax_ev_kind"), Index("ix_tax_ev_link", "org_id", "linked_type", "linked_id"))


class TaxSignoff(Base):
    """A declaration that the figures on a document are true and correct, by the taxpayer / authorised person or by a registered tax or BAS agent. It is bound to the document's
    calculation fingerprint: if the figures change afterwards the sign-off no longer counts. AccFino records it; the ATO's own declaration is made in the lodgement channel."""
    __tablename__ = "tax_signoffs"
    id = Column(Integer, primary_key=True)
    org_id = _ORG()
    doc_type = Column(String(20), nullable=False)
    doc_id = Column(Integer, nullable=False)
    capacity = Column(String(12), nullable=False)
    signer_user_id = Column(Integer)
    signer_name = Column(String(200), nullable=False)
    agent_number = Column(String(20))                                                    # registered tax / BAS agent number as DECLARED (not verified by AccFino)
    declaration_version = Column(String(20), nullable=False)
    declaration_text = Column(Text, nullable=False)
    doc_hash = Column(String(64), nullable=False)
    status = Column(String(12), nullable=False, default="valid")                         # valid | superseded | revoked
    note = Column(String(500))
    signed_at = Column(DateTime, default=datetime.utcnow)
    ended_at = Column(DateTime)
    ended_by = Column(Integer)
    end_reason = Column(String(300))
    __table_args__ = (CheckConstraint(_in("capacity", SIGNOFF_CAPACITIES), name="ck_tax_so_cap"), CheckConstraint(_in("doc_type", SIGNOFF_DOC_TYPES), name="ck_tax_so_doc"),
                      CheckConstraint(_in("status", ("valid", "superseded", "revoked")), name="ck_tax_so_status"), Index("ix_tax_so_doc", "org_id", "doc_type", "doc_id"))


class TaxLodgement(Base):
    """One attempt to hand a document to a lodgement provider (manual record, agent hand-off pack, sandbox simulation or an accredited gateway)."""
    __tablename__ = "tax_lodgements"
    id = Column(Integer, primary_key=True)
    org_id = _ORG()
    doc_type = Column(String(20), nullable=False)
    doc_id = Column(Integer, nullable=False)
    provider = Column(String(14), nullable=False)
    status = Column(String(12), nullable=False)
    simulated = Column(Boolean, nullable=False, default=False)                           # TRUE = nothing reached the ATO
    signoff_id = Column(Integer, ForeignKey("tax_signoffs.id", ondelete="SET NULL"))
    payload_hash = Column(String(64))
    receipt_reference = Column(String(80))
    message = Column(String(500))
    response = Column(JSON)
    submitted_by = Column(Integer)
    submitted_at = Column(DateTime, default=datetime.utcnow)
    __table_args__ = (CheckConstraint(_in("provider", LODGEMENT_PROVIDERS), name="ck_tax_lodg_prov"), CheckConstraint(_in("status", LODGEMENT_STATUSES), name="ck_tax_lodg_status"),
                      Index("ix_tax_lodg_doc", "org_id", "doc_type", "doc_id"))


class TaxScenario(Base):
    __tablename__ = "tax_scenarios"
    id = Column(Integer, primary_key=True)
    org_id = _ORG()
    fy = Column(String(7), nullable=False)
    name = Column(String(120), nullable=False)
    levers = Column(JSON)                                                                # [{label, amount, direction}]
    result = Column(JSON)
    created_by = Column(Integer)
    created_at = Column(DateTime, default=datetime.utcnow)


class TaxAudit(Base):
    """Append-only, hash-chained: each row stores the hash of the previous row for the organisation, so edits or deletions are detectable (verify endpoint)."""
    __tablename__ = "tax_audit"
    id = Column(Integer, primary_key=True)
    org_id = _ORG()
    seq = Column(Integer, nullable=False)
    at = Column(DateTime, nullable=False, default=datetime.utcnow)
    user_id = Column(Integer)
    username = Column(String(120))
    action = Column(String(60), nullable=False)
    entity_type = Column(String(40), nullable=False)
    entity_id = Column(String(40))
    summary = Column(String(500))
    before = Column(JSON)
    after = Column(JSON)
    prev_hash = Column(String(64))
    hash = Column(String(64), nullable=False)
    __table_args__ = (UniqueConstraint("org_id", "seq", name="uq_tax_audit_seq"),)


TAX_TABLES = [c.__table__ for c in (TaxProfile, TaxRuleOverride, TaxRegistration, TaxObligation, TaxBasStatement, TaxAdjustment, TaxReturn, TaxCgtEvent, TaxCapitalLoss,
                                    TaxFbtBenefit, TaxFbtReturn, TaxDiv7aLoan, TaxDiv7aPayment, TaxWorkpaper, TaxEvidence, TaxScenario, TaxAudit, TaxSignoff, TaxLodgement)]
