"""
Phase 1 - Books & Accounting sub-ledger (organisation-scoped, exact NUMERIC money, every posting goes through the ledger).

  contacts                   customers and suppliers (one record can be both)
  docs / doc_lines           quote, invoice, credit_note, purchase_order, bill, supplier_credit
  payments / allocations     money received/paid/refunded and how it settles documents
  bank_lines                 imported bank-statement lines and their reconciliation state
  bank_rules / classifier_memory   PER-ORGANISATION rules and learning (nothing is shared between organisations)
  expense_claims / expense_items   employee expense claims with approval and reimbursement
  attachments                receipts and supporting files (stored in the database, <= 5 MB each)
  doc_sequences              per-organisation document numbering
  legacy_links               provenance of records backfilled from the pre-Phase-1 tables (A7)
"""
from datetime import datetime

from sqlalchemy import (JSON, Boolean, CheckConstraint, Column, Date, DateTime, ForeignKey, Index, Integer, LargeBinary,
                        Numeric, String, Text, UniqueConstraint, text)
from sqlalchemy.orm import relationship

from accfino_core.models import MONEY, RATE
from db_app.models.base import Base

QTY = Numeric(18, 4)       # quantities and unit prices (Xero-style 4 dp)

DOC_TYPES = ("quote", "invoice", "credit_note", "purchase_order", "bill", "supplier_credit")
SALES_TYPES = ("quote", "invoice", "credit_note")
PURCHASE_TYPES = ("purchase_order", "bill", "supplier_credit")
DOC_STATUSES = ("draft", "sent", "accepted", "declined", "invoiced", "approved", "billed", "cancelled", "paid", "voided", "archived")
# "archived" = a record imported from the pre-Phase-1 tables: read-only history that never touches the ledger or the aged reports


class Contact(Base):
    __tablename__ = "contacts"
    id = Column(Integer, primary_key=True)
    org_id = Column(Integer, ForeignKey("organisations.id", ondelete="CASCADE"), nullable=False, index=True)
    name = Column(String(255), nullable=False)
    is_customer = Column(Boolean, nullable=False, default=False)
    is_supplier = Column(Boolean, nullable=False, default=False)
    email = Column(String(255), nullable=True)
    phone = Column(String(50), nullable=True)
    abn = Column(String(20), nullable=True)
    address = Column(Text, nullable=True)
    terms_days = Column(Integer, nullable=False, default=14)
    default_account_id = Column(Integer, ForeignKey("ledger_accounts.id", ondelete="SET NULL"), nullable=True)
    default_tax_code_id = Column(Integer, ForeignKey("tax_codes.id", ondelete="SET NULL"), nullable=True)
    credit_limit = Column(MONEY, nullable=True)
    notes = Column(Text, nullable=True)
    is_active = Column(Boolean, nullable=False, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    __table_args__ = (UniqueConstraint("org_id", "name", name="uq_contact_name"),
                      CheckConstraint("is_customer OR is_supplier", name="ck_contact_role"))


class Doc(Base):
    __tablename__ = "docs"
    id = Column(Integer, primary_key=True)
    org_id = Column(Integer, ForeignKey("organisations.id", ondelete="CASCADE"), nullable=False, index=True)
    doc_type = Column(String(20), nullable=False)
    number = Column(String(60), nullable=False)
    contact_id = Column(Integer, ForeignKey("contacts.id", ondelete="RESTRICT"), nullable=False, index=True)
    status = Column(String(20), nullable=False, default="draft")
    issue_date = Column(Date, nullable=False)
    due_date = Column(Date, nullable=True)                       # due date / quote expiry
    reference = Column(String(100), nullable=True)               # supplier's invoice number for bills; PO/reference for sales
    amounts_are = Column(String(10), nullable=False, default="exclusive")     # exclusive | inclusive | no_tax
    currency = Column(String(3), nullable=False, default="AUD")
    subtotal = Column(MONEY, nullable=False, default=0)
    tax_total = Column(MONEY, nullable=False, default=0)
    total = Column(MONEY, nullable=False, default=0)
    amount_paid = Column(MONEY, nullable=False, default=0)       # payments allocated
    amount_credited = Column(MONEY, nullable=False, default=0)   # credit notes allocated (invoices/bills) / applied+refunded (credit docs)
    journal_id = Column(Integer, ForeignKey("journals.id"), nullable=True)
    parent_id = Column(Integer, ForeignKey("docs.id"), nullable=True)     # quote -> invoice, purchase order -> bill
    notes = Column(Text, nullable=True)
    terms = Column(Text, nullable=True)
    source = Column(String(40), nullable=False, default="manual")         # manual | ocr | legacy
    sent_at = Column(DateTime, nullable=True)
    approved_at = Column(DateTime, nullable=True)
    approved_by = Column(Integer, nullable=True)
    voided_at = Column(DateTime, nullable=True)
    created_by = Column(Integer, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    contact = relationship("Contact")
    lines = relationship("DocLine", back_populates="doc", cascade="all, delete-orphan", order_by="DocLine.line_no")

    __table_args__ = (
        UniqueConstraint("org_id", "doc_type", "number", name="uq_doc_number"),
        Index("ix_docs_org_type_status", "org_id", "doc_type", "status"),
        # a supplier's own invoice number can only be entered once per supplier (duplicate-bill protection)
        Index("uq_doc_supplier_reference", "org_id", "contact_id", "reference", unique=True,
              postgresql_where=text("doc_type IN ('bill','supplier_credit') AND reference IS NOT NULL AND status <> 'voided'")),
        CheckConstraint(f"doc_type IN {DOC_TYPES}", name="ck_doc_type"),
        CheckConstraint(f"status IN {DOC_STATUSES}", name="ck_doc_status"),
        CheckConstraint("amounts_are IN ('exclusive','inclusive','no_tax')", name="ck_doc_amounts_are"),
        CheckConstraint("amount_paid >= 0 AND amount_credited >= 0", name="ck_doc_settled_non_negative"),
        # database-level guarantee that a document can never be over-settled (defence in depth behind the service checks)
        CheckConstraint("amount_paid + amount_credited <= total", name="ck_doc_not_over_settled"),
    )

    @property
    def amount_due(self):
        return (self.total or 0) - (self.amount_paid or 0) - (self.amount_credited or 0)


class DocLine(Base):
    __tablename__ = "doc_lines"
    id = Column(Integer, primary_key=True)
    doc_id = Column(Integer, ForeignKey("docs.id", ondelete="CASCADE"), nullable=False, index=True)
    org_id = Column(Integer, nullable=False, index=True)
    line_no = Column(Integer, nullable=False)
    description = Column(String(500), nullable=False)
    qty = Column(QTY, nullable=False, default=1)
    unit_price = Column(QTY, nullable=False, default=0)
    discount_pct = Column(Numeric(9, 4), nullable=False, default=0)
    account_id = Column(Integer, ForeignKey("ledger_accounts.id", ondelete="RESTRICT"), nullable=True)
    tax_code_id = Column(Integer, ForeignKey("tax_codes.id", ondelete="RESTRICT"), nullable=True)
    net = Column(MONEY, nullable=False, default=0)
    tax = Column(MONEY, nullable=False, default=0)
    gross = Column(MONEY, nullable=False, default=0)
    tracking_option_ids = Column(JSON, nullable=True)

    doc = relationship("Doc", back_populates="lines")
    account = relationship("LedgerAccount")
    tax_code = relationship("TaxCode")


class Payment(Base):
    """kind: receive (from a customer), pay (to a supplier), refund_out (we refund a customer), refund_in (a supplier refunds us)."""
    __tablename__ = "payments"
    id = Column(Integer, primary_key=True)
    org_id = Column(Integer, ForeignKey("organisations.id", ondelete="CASCADE"), nullable=False, index=True)
    kind = Column(String(12), nullable=False)
    contact_id = Column(Integer, ForeignKey("contacts.id", ondelete="RESTRICT"), nullable=False, index=True)
    payment_date = Column(Date, nullable=False)
    amount = Column(MONEY, nullable=False)
    bank_account_id = Column(Integer, ForeignKey("ledger_accounts.id", ondelete="RESTRICT"), nullable=False)
    reference = Column(String(200), nullable=True)
    journal_id = Column(Integer, ForeignKey("journals.id"), nullable=True)
    status = Column(String(10), nullable=False, default="posted")           # posted | reversed
    bank_line_id = Column(Integer, nullable=True, index=True)               # set when reconciled to a bank-statement line
    created_by = Column(Integer, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    contact = relationship("Contact")
    allocations = relationship("Allocation", back_populates="payment", cascade="all, delete-orphan")

    __table_args__ = (CheckConstraint("amount > 0", name="ck_payment_positive"),
                      CheckConstraint("kind IN ('receive','pay','refund_out','refund_in')", name="ck_payment_kind"),
                      CheckConstraint("status IN ('posted','reversed')", name="ck_payment_status"))


class Allocation(Base):
    """Settles part of a document with a payment OR with a credit document. No ledger effect of its own
    (the payment / credit already posted); it is the sub-ledger matching that drives amount_due and the aged reports."""
    __tablename__ = "allocations"
    id = Column(Integer, primary_key=True)
    org_id = Column(Integer, nullable=False, index=True)
    payment_id = Column(Integer, ForeignKey("payments.id", ondelete="CASCADE"), nullable=True, index=True)
    credit_doc_id = Column(Integer, ForeignKey("docs.id", ondelete="RESTRICT"), nullable=True, index=True)
    doc_id = Column(Integer, ForeignKey("docs.id", ondelete="RESTRICT"), nullable=True, index=True)   # null for refunds of a credit note
    amount = Column(MONEY, nullable=False)
    alloc_date = Column(Date, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)

    payment = relationship("Payment", back_populates="allocations")
    __table_args__ = (CheckConstraint("amount > 0", name="ck_alloc_positive"),
                      CheckConstraint("(payment_id IS NOT NULL) <> (credit_doc_id IS NOT NULL)", name="ck_alloc_source"))


class BankLine(Base):
    __tablename__ = "bank_lines"
    id = Column(Integer, primary_key=True)
    org_id = Column(Integer, ForeignKey("organisations.id", ondelete="CASCADE"), nullable=False, index=True)
    bank_account_id = Column(Integer, ForeignKey("ledger_accounts.id", ondelete="RESTRICT"), nullable=False, index=True)
    line_date = Column(Date, nullable=False)
    description = Column(String(500), nullable=False)
    amount = Column(MONEY, nullable=False)                 # signed: + money in, - money out
    balance = Column(MONEY, nullable=True)                 # statement running balance, when supplied
    fingerprint = Column(String(64), nullable=False)
    status = Column(String(12), nullable=False, default="unreconciled")     # unreconciled | reconciled | excluded
    matched_kind = Column(String(20), nullable=True)       # payment | spend | receive | transfer
    payment_id = Column(Integer, nullable=True)
    journal_id = Column(Integer, ForeignKey("journals.id"), nullable=True)
    contact_id = Column(Integer, nullable=True)
    note = Column(String(300), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    reconciled_at = Column(DateTime, nullable=True)
    reconciled_by = Column(Integer, nullable=True)

    __table_args__ = (UniqueConstraint("org_id", "fingerprint", name="uq_bank_line_fingerprint"),
                      Index("ix_bank_line_state", "org_id", "bank_account_id", "status"),
                      CheckConstraint("amount <> 0", name="ck_bank_line_nonzero"),
                      CheckConstraint("status IN ('unreconciled','reconciled','excluded')", name="ck_bank_line_status"))


class BankRule(Base):
    """A per-organisation rule: if the line matches, propose this coding."""
    __tablename__ = "bank_rules"
    id = Column(Integer, primary_key=True)
    org_id = Column(Integer, ForeignKey("organisations.id", ondelete="CASCADE"), nullable=False, index=True)
    name = Column(String(120), nullable=False)
    priority = Column(Integer, nullable=False, default=100)               # lower runs first
    direction = Column(String(4), nullable=False, default="any")          # in | out | any
    match_type = Column(String(12), nullable=False, default="contains")   # contains | startswith | regex
    pattern = Column(String(200), nullable=False)
    min_amount = Column(MONEY, nullable=True)
    max_amount = Column(MONEY, nullable=True)
    account_id = Column(Integer, ForeignKey("ledger_accounts.id", ondelete="CASCADE"), nullable=False)
    tax_code_id = Column(Integer, ForeignKey("tax_codes.id", ondelete="SET NULL"), nullable=True)
    contact_name = Column(String(255), nullable=True)
    description = Column(String(300), nullable=True)
    is_active = Column(Boolean, nullable=False, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    __table_args__ = (CheckConstraint("direction IN ('in','out','any')", name="ck_rule_direction"),
                      CheckConstraint("match_type IN ('contains','startswith','regex')", name="ck_rule_match"))


class ClassifierMemory(Base):
    """What THIS organisation has taught the classifier: merchant token -> coding. Never shared across organisations."""
    __tablename__ = "classifier_memory"
    id = Column(Integer, primary_key=True)
    org_id = Column(Integer, ForeignKey("organisations.id", ondelete="CASCADE"), nullable=False, index=True)
    key = Column(String(120), nullable=False)
    account_id = Column(Integer, ForeignKey("ledger_accounts.id", ondelete="CASCADE"), nullable=False)
    tax_code_id = Column(Integer, ForeignKey("tax_codes.id", ondelete="SET NULL"), nullable=True)
    contact_name = Column(String(255), nullable=True)
    hits = Column(Integer, nullable=False, default=1)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    __table_args__ = (UniqueConstraint("org_id", "key", name="uq_classifier_memory"),)


class ExpenseClaim(Base):
    __tablename__ = "expense_claims"
    id = Column(Integer, primary_key=True)
    org_id = Column(Integer, ForeignKey("organisations.id", ondelete="CASCADE"), nullable=False, index=True)
    number = Column(String(40), nullable=False)
    claimant_user_id = Column(Integer, nullable=False, index=True)
    claimant_name = Column(String(200), nullable=False)
    title = Column(String(200), nullable=False)
    status = Column(String(12), nullable=False, default="draft")   # draft | submitted | approved | rejected | paid
    total = Column(MONEY, nullable=False, default=0)
    tax_total = Column(MONEY, nullable=False, default=0)
    submitted_at = Column(DateTime, nullable=True)
    approved_by = Column(Integer, nullable=True)
    approved_at = Column(DateTime, nullable=True)
    rejected_reason = Column(String(300), nullable=True)
    approval_journal_id = Column(Integer, ForeignKey("journals.id"), nullable=True)
    paid_at = Column(DateTime, nullable=True)
    payment_journal_id = Column(Integer, ForeignKey("journals.id"), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    items = relationship("ExpenseItem", back_populates="claim", cascade="all, delete-orphan", order_by="ExpenseItem.id")
    __table_args__ = (UniqueConstraint("org_id", "number", name="uq_claim_number"),
                      CheckConstraint("status IN ('draft','submitted','approved','rejected','paid')", name="ck_claim_status"))


class ExpenseItem(Base):
    __tablename__ = "expense_items"
    id = Column(Integer, primary_key=True)
    claim_id = Column(Integer, ForeignKey("expense_claims.id", ondelete="CASCADE"), nullable=False, index=True)
    org_id = Column(Integer, nullable=False, index=True)
    item_date = Column(Date, nullable=False)
    merchant = Column(String(200), nullable=True)
    description = Column(String(500), nullable=False)
    account_id = Column(Integer, ForeignKey("ledger_accounts.id", ondelete="RESTRICT"), nullable=False)
    tax_code_id = Column(Integer, ForeignKey("tax_codes.id", ondelete="RESTRICT"), nullable=True)
    kind = Column(String(10), nullable=False, default="receipt")       # receipt | mileage
    km = Column(Numeric(12, 2), nullable=True)
    rate_per_km = Column(Numeric(9, 4), nullable=True)
    gross = Column(MONEY, nullable=False)
    tax = Column(MONEY, nullable=False, default=0)
    net = Column(MONEY, nullable=False)
    claim = relationship("ExpenseClaim", back_populates="items")
    account = relationship("LedgerAccount")
    __table_args__ = (CheckConstraint("gross > 0", name="ck_item_positive"),
                      CheckConstraint("kind IN ('receipt','mileage')", name="ck_item_kind"))


class Attachment(Base):
    __tablename__ = "attachments"
    id = Column(Integer, primary_key=True)
    org_id = Column(Integer, nullable=False, index=True)
    owner_kind = Column(String(20), nullable=False)        # doc | expense_item | bank_line
    owner_id = Column(Integer, nullable=False)
    filename = Column(String(255), nullable=False)
    content_type = Column(String(100), nullable=True)
    size = Column(Integer, nullable=False)
    data = Column(LargeBinary, nullable=False)
    uploaded_by = Column(Integer, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    __table_args__ = (Index("ix_attachment_owner", "org_id", "owner_kind", "owner_id"),)


class DocSequence(Base):
    __tablename__ = "doc_sequences"
    org_id = Column(Integer, ForeignKey("organisations.id", ondelete="CASCADE"), primary_key=True)
    doc_type = Column(String(20), primary_key=True)
    prefix = Column(String(12), nullable=False)
    next_no = Column(Integer, nullable=False, default=1)


class LegacyLink(Base):
    __tablename__ = "legacy_links"
    id = Column(Integer, primary_key=True)
    org_id = Column(Integer, nullable=False, index=True)
    legacy_table = Column(String(40), nullable=False)
    legacy_id = Column(Integer, nullable=False)
    new_kind = Column(String(20), nullable=False)          # contact | doc
    new_id = Column(Integer, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)
    __table_args__ = (UniqueConstraint("org_id", "legacy_table", "legacy_id", name="uq_legacy_link"),)


class BudgetLine(Base):
    """(Table is org_budget_lines: a plain "budget_lines" table from an older schema may already exist in a database, so this one has its own name.)
    One month's budget for one P&L account (organisation-scoped). `period` is always the first day of the month.
    `scenario` lets an organisation keep more than one budget (e.g. "Budget", "Forecast")."""
    __tablename__ = "org_budget_lines"
    id = Column(Integer, primary_key=True)
    org_id = Column(Integer, ForeignKey("organisations.id", ondelete="CASCADE"), nullable=False, index=True)
    scenario = Column(String(40), nullable=False, default="Budget")
    account_id = Column(Integer, ForeignKey("ledger_accounts.id", ondelete="CASCADE"), nullable=False, index=True)
    period = Column(Date, nullable=False)
    amount = Column(MONEY, nullable=False, default=0)      # positive = income expected / expense planned, in the account's natural sign
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    account = relationship("LedgerAccount")
    __table_args__ = (UniqueConstraint("org_id", "scenario", "account_id", "period", name="uq_org_budget_line"),
                      Index("ix_org_budget_period", "org_id", "scenario", "period"))


BOOKS_TABLES = [Contact.__table__, Doc.__table__, DocLine.__table__, Payment.__table__, Allocation.__table__, BankLine.__table__,
                BankRule.__table__, ClassifierMemory.__table__, ExpenseClaim.__table__, ExpenseItem.__table__, Attachment.__table__,
                DocSequence.__table__, LegacyLink.__table__, BudgetLine.__table__]
