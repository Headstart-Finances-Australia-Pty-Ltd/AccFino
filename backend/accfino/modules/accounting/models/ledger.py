"""
accfino.modules.accounting.models.ledger
----------------------------------------
Double-entry ledger tables (chart of accounts, tax codes, tracking, journals, source links), moved out of core.models.
Posted journals are immutable: enforced in the service layer AND by PostgreSQL triggers (see accfino.modules.accounting.ledger.triggers).
Every record belongs to an organisation (org_id).
"""
from datetime import datetime

from sqlalchemy import (
    Boolean, CheckConstraint, Column, Date, DateTime, ForeignKey, Index, Integer,
    JSON, Numeric, String, Text, UniqueConstraint, text,
)
from sqlalchemy.orm import relationship

from accfino.shared.db.base import Base
from accfino.shared.db.types import MONEY, RATE, FXRATE


# ----------------------------------------------------------------- ledger ---
ACCOUNT_CLASSES = ("asset", "liability", "equity", "revenue", "expense")

# account_type -> account_class
ACCOUNT_TYPES = {
    "bank": "asset",
    "current_asset": "asset",
    "inventory": "asset",
    "fixed_asset": "asset",
    "non_current_asset": "asset",
    "credit_card": "liability",
    "current_liability": "liability",
    "non_current_liability": "liability",
    "equity": "equity",
    "revenue": "revenue",
    "other_income": "revenue",
    "direct_costs": "expense",
    "expense": "expense",
    "other_expense": "expense",
}


class TaxCode(Base):
    __tablename__ = "tax_codes"

    id = Column(Integer, primary_key=True)
    org_id = Column(Integer, ForeignKey("organisations.id", ondelete="CASCADE"), nullable=False, index=True)
    code = Column(String(30), nullable=False)          # OUTPUT, INPUT, CAPEX, FRE, ...
    name = Column(String(100), nullable=False)         # "GST on Income" (matches legacy gst_category)
    rate = Column(RATE, nullable=False, default=0)     # 0.100000 for 10%
    applies_to = Column(String(10), nullable=False, default="both")   # sales|purchases|both
    bas_labels = Column(JSON, nullable=True)           # {"sales": ["G1"], "tax": "1A"}
    is_system = Column(Boolean, nullable=False, default=True)
    is_active = Column(Boolean, nullable=False, default=True)

    __table_args__ = (
        UniqueConstraint("org_id", "code", name="uq_tax_code"),
        UniqueConstraint("org_id", "name", name="uq_tax_code_name"),
    )


class LedgerAccount(Base):
    __tablename__ = "ledger_accounts"

    id = Column(Integer, primary_key=True)
    org_id = Column(Integer, ForeignKey("organisations.id", ondelete="CASCADE"), nullable=False, index=True)
    code = Column(String(20), nullable=False)
    name = Column(String(200), nullable=False)
    account_type = Column(String(30), nullable=False)
    account_class = Column(String(20), nullable=False)
    description = Column(Text, nullable=True)
    default_tax_code_id = Column(Integer, ForeignKey("tax_codes.id", ondelete="SET NULL"), nullable=True)
    system_key = Column(String(40), nullable=True)      # ar_control, ap_control, gst, suspense, ...
    bank_name = Column(String(100), nullable=True)      # for bank accounts synced from legacy data
    bank_account_ref = Column(String(100), nullable=True)
    currency = Column(String(3), nullable=False, default="AUD")
    foreign_currency = Column(String(3), nullable=True)   # NULL = held in the base currency. Set = a foreign-currency account (bank, card, loan...): every posting carries the amount in this currency, and it is revalued at period end
    is_active = Column(Boolean, nullable=False, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    default_tax_code = relationship("TaxCode")

    __table_args__ = (
        UniqueConstraint("org_id", "code", name="uq_ledger_account_code"),
        UniqueConstraint("org_id", "name", name="uq_ledger_account_name"),
        Index("ix_ledger_account_system", "org_id", "system_key", unique=True,
              postgresql_where="system_key IS NOT NULL"),
        CheckConstraint(f"account_class IN {ACCOUNT_CLASSES}", name="ck_account_class"),
        CheckConstraint(f"account_type IN {tuple(ACCOUNT_TYPES)}", name="ck_account_type"),
    )


class TrackingCategory(Base):
    __tablename__ = "tracking_categories"

    id = Column(Integer, primary_key=True)
    org_id = Column(Integer, ForeignKey("organisations.id", ondelete="CASCADE"), nullable=False, index=True)
    name = Column(String(100), nullable=False)
    is_active = Column(Boolean, nullable=False, default=True)
    options = relationship("TrackingOption", back_populates="category", cascade="all, delete-orphan",
                           order_by="TrackingOption.name")

    __table_args__ = (UniqueConstraint("org_id", "name", name="uq_tracking_category"),)


class TrackingOption(Base):
    __tablename__ = "tracking_options"

    id = Column(Integer, primary_key=True)
    category_id = Column(Integer, ForeignKey("tracking_categories.id", ondelete="CASCADE"), nullable=False, index=True)
    name = Column(String(100), nullable=False)
    is_active = Column(Boolean, nullable=False, default=True)
    category = relationship("TrackingCategory", back_populates="options")

    __table_args__ = (UniqueConstraint("category_id", "name", name="uq_tracking_option"),)


class Journal(Base):
    __tablename__ = "journals"

    id = Column(Integer, primary_key=True)
    org_id = Column(Integer, ForeignKey("organisations.id", ondelete="RESTRICT"), nullable=False, index=True)
    journal_no = Column(Integer, nullable=False)
    journal_date = Column(Date, nullable=False, index=True)
    narration = Column(String(500), nullable=True)
    reference = Column(String(100), nullable=True)                       # free reference (cheque no., workpaper ref, source doc no.)
    source_type = Column(String(40), nullable=False, default="manual")   # manual|bank_txn|reversal|opening_balance|auto_reversal|...
    source_ref = Column(String(100), nullable=True)
    status = Column(String(20), nullable=False, default="posted")        # posted|reversed
    reversal_of_id = Column(Integer, ForeignKey("journals.id"), nullable=True)
    reversed_by_id = Column(Integer, ForeignKey("journals.id"), nullable=True)
    total = Column(MONEY, nullable=False, default=0)
    currency = Column(String(3), nullable=True)                          # NULL = the organisation's base currency; else the currency the journal was ENTERED in
    exchange_rate = Column(FXRATE, nullable=True)                        # base units per 1 foreign unit, fixed at posting
    created_by = Column(Integer, nullable=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)

    lines = relationship("JournalLine", back_populates="journal", cascade="save-update, merge",
                         order_by="JournalLine.line_no", passive_deletes="all")

    __table_args__ = (
        UniqueConstraint("org_id", "journal_no", name="uq_journal_no"),
        CheckConstraint("status IN ('posted','reversed')", name="ck_journal_status"),
        Index("ix_journal_source", "org_id", "source_type", "source_ref"),
    )


class JournalLine(Base):
    __tablename__ = "journal_lines"

    id = Column(Integer, primary_key=True)
    journal_id = Column(Integer, ForeignKey("journals.id", ondelete="RESTRICT"), nullable=False, index=True)
    org_id = Column(Integer, nullable=False, index=True)
    line_no = Column(Integer, nullable=False)
    account_id = Column(Integer, ForeignKey("ledger_accounts.id", ondelete="RESTRICT"), nullable=False, index=True)
    description = Column(String(500), nullable=True)
    debit = Column(MONEY, nullable=False, default=0)
    credit = Column(MONEY, nullable=False, default=0)
    tax_code_id = Column(Integer, ForeignKey("tax_codes.id", ondelete="RESTRICT"), nullable=True)
    tax_amount = Column(MONEY, nullable=False, default=0)   # GST component carried for BAS
    tracking_option_ids = Column(JSON, nullable=True)
    contact_name = Column(String(255), nullable=True)
    orig_debit = Column(MONEY, nullable=True)                            # foreign-currency journals: the amount as entered (debit/credit above are always BASE currency)
    orig_credit = Column(MONEY, nullable=True)

    journal = relationship("Journal", back_populates="lines")
    account = relationship("LedgerAccount")
    tax_code = relationship("TaxCode")

    __table_args__ = (
        CheckConstraint("debit >= 0 AND credit >= 0", name="ck_line_non_negative"),
        CheckConstraint("(debit = 0) <> (credit = 0)", name="ck_line_one_side"),
    )


class LedgerSourceLink(Base):
    """Links a legacy source record (e.g. a bank transaction) to the journal it produced,
    so syncs are idempotent and changed sources are reversed and re-posted."""
    __tablename__ = "ledger_source_links"

    id = Column(Integer, primary_key=True)
    org_id = Column(Integer, nullable=False, index=True)
    source_type = Column(String(40), nullable=False)
    source_id = Column(String(80), nullable=False)
    journal_id = Column(Integer, ForeignKey("journals.id"), nullable=True)
    fingerprint = Column(String(64), nullable=False)
    status = Column(String(20), nullable=False, default="posted")   # posted|skipped|locked
    note = Column(String(300), nullable=True)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    __table_args__ = (UniqueConstraint("org_id", "source_type", "source_id", name="uq_source_link"),)
