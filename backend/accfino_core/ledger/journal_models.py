"""
Journal workflow tables. Deliberately SEPARATE from the immutable `journals` / `journal_lines` tables:
a draft, a pending approval, an AI suggestion or a repeating template has NO effect on the ledger or on any report until it is
posted through ledger.service.post_journal, so nothing here can ever put the books out of balance.

  ledger_journal_drafts       manual drafts, imported drafts, repeating-journal drafts, and AI/rule bank-coding suggestions awaiting review
  ledger_repeating_journals   templates that generate a draft or a posted journal on a schedule (MYOB "recurring", Xero "repeating")
"""
from datetime import datetime

from sqlalchemy import JSON, Boolean, Column, Date, DateTime, ForeignKey, Index, Integer, Numeric, String, Text

from accfino_core.models import FXRATE, MONEY
from db_app.models.base import Base

DRAFT_STATUSES = ("draft", "submitted", "rejected", "posted")
DRAFT_KINDS = ("manual", "import", "repeating", "ai_bank")
FREQUENCIES = ("weekly", "fortnightly", "monthly", "quarterly", "yearly")
AMOUNTS_ARE = ("no_tax", "inclusive", "exclusive")


class JournalDraft(Base):
    __tablename__ = "ledger_journal_drafts"
    id = Column(Integer, primary_key=True)
    org_id = Column(Integer, ForeignKey("organisations.id", ondelete="CASCADE"), nullable=False, index=True)
    kind = Column(String(12), nullable=False, default="manual")
    status = Column(String(12), nullable=False, default="draft")
    journal_date = Column(Date, nullable=False)
    narration = Column(String(500), nullable=False, default="")
    reference = Column(String(100), nullable=True)
    amounts_are = Column(String(10), nullable=False, default="no_tax")
    auto_reverse_date = Column(Date, nullable=True)
    currency = Column(String(3), nullable=True)                  # foreign currency the draft is entered in (NULL = base)
    exchange_rate = Column(FXRATE, nullable=True)
    lines = Column(JSON, nullable=False, default=list)           # [{account_id, description, debit, credit, tax_code_id, tracking_option_ids, contact_name}] as entered
    payload = Column(JSON, nullable=True)                        # ai_bank: {kind: coding|match, bank_line_id, account_id, tax_code_id, contact_name, suggestion, source, why}
    confidence = Column(Numeric(5, 4), nullable=True)            # ai_bank only
    reason = Column(String(300), nullable=True)                  # ai_bank: why it was suggested
    source_ref = Column(String(100), nullable=True, index=True)  # e.g. bankline:123, repeating:7
    created_by = Column(Integer, nullable=True)
    created_by_name = Column(String(100), nullable=True)
    submitted_at = Column(DateTime, nullable=True)
    decided_by = Column(Integer, nullable=True)
    decided_by_name = Column(String(100), nullable=True)
    decided_at = Column(DateTime, nullable=True)
    rejected_reason = Column(String(300), nullable=True)
    posted_journal_id = Column(Integer, ForeignKey("journals.id"), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    __table_args__ = (Index("ix_ledger_draft_org_status", "org_id", "status", "kind"),)


class RepeatingJournal(Base):
    __tablename__ = "ledger_repeating_journals"
    id = Column(Integer, primary_key=True)
    org_id = Column(Integer, ForeignKey("organisations.id", ondelete="CASCADE"), nullable=False, index=True)
    name = Column(String(120), nullable=False)
    frequency = Column(String(12), nullable=False, default="monthly")
    next_date = Column(Date, nullable=False)
    anchor_day = Column(Integer, nullable=False, default=1)      # day of month to keep (clamped to month end)
    end_date = Column(Date, nullable=True)
    mode = Column(String(6), nullable=False, default="draft")    # draft (needs review) | post (straight to the ledger)
    narration = Column(String(500), nullable=False)
    reference = Column(String(100), nullable=True)
    amounts_are = Column(String(10), nullable=False, default="no_tax")
    reverse_after_days = Column(Integer, nullable=True)          # auto-reverse each occurrence N days after its date (accruals)
    currency = Column(String(3), nullable=True)                  # foreign currency: the rate is looked up in ledger_fx_rates for each occurrence's date
    auto_run = Column(Boolean, nullable=False, default=False)    # opt in: the background scheduler runs this template when it falls due
    lines = Column(JSON, nullable=False, default=list)
    is_active = Column(Boolean, nullable=False, default=True)
    last_run_date = Column(Date, nullable=True)
    runs = Column(Integer, nullable=False, default=0)
    last_error = Column(String(300), nullable=True)
    created_by = Column(Integer, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)


class FxRate(Base):
    """Exchange rates the ORGANISATION has entered (or imported). AccFino never invents a rate: a foreign-currency journal needs one of these or an explicit rate."""
    __tablename__ = "ledger_fx_rates"
    id = Column(Integer, primary_key=True)
    org_id = Column(Integer, ForeignKey("organisations.id", ondelete="CASCADE"), nullable=False, index=True)
    currency = Column(String(3), nullable=False)
    rate_date = Column(Date, nullable=False)
    rate = Column(FXRATE, nullable=False)                        # base units per 1 foreign unit
    source = Column(String(60), nullable=True)                   # e.g. "RBA", "bank", "manual"
    created_by = Column(Integer, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    __table_args__ = (Index("ux_ledger_fx_rate", "org_id", "currency", "rate_date", unique=True),)


JOURNAL_TABLES = [JournalDraft.__table__, RepeatingJournal.__table__, FxRate.__table__]
