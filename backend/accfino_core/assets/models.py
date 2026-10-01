"""
Fixed asset register (organisation-scoped).

An asset's cost is assumed already posted to the ledger (typically via a bill in Purchases, coded
to the asset's own account) - registering an asset here does not post anything. Only a depreciation
run or a disposal touches the ledger.
"""
from datetime import date, datetime

from sqlalchemy import Column, Date, DateTime, ForeignKey, Integer, Numeric, String, Text
from sqlalchemy.orm import relationship

from accfino_core.models import MONEY
from db_app.models.base import Base

METHODS = ("straight_line", "diminishing_value")
STATUSES = ("active", "disposed")


class FixedAsset(Base):
    __tablename__ = "fixed_assets"
    id = Column(Integer, primary_key=True)
    org_id = Column(Integer, ForeignKey("organisations.id", ondelete="CASCADE"), nullable=False, index=True)
    number = Column(String(30), nullable=False)
    name = Column(String(255), nullable=False)
    category = Column(String(40), nullable=True)                 # a label only (office_equipment/computer_equipment/motor_vehicle/other)
    asset_account_id = Column(Integer, ForeignKey("ledger_accounts.id"), nullable=False)
    depreciation_account_id = Column(Integer, ForeignKey("ledger_accounts.id"), nullable=False)   # the contra (accumulated depreciation)
    expense_account_id = Column(Integer, ForeignKey("ledger_accounts.id"), nullable=False)         # Depreciation expense (416 by default)
    purchase_date = Column(Date, nullable=False)
    cost = Column(MONEY, nullable=False)
    residual_value = Column(MONEY, nullable=False, default=0)
    method = Column(String(20), nullable=False, default="straight_line")
    effective_life_months = Column(Integer, nullable=True)        # required for straight_line
    dv_rate_pct = Column(Numeric(7, 4), nullable=True)             # annual %, required for diminishing_value
    opening_accumulated_depreciation = Column(MONEY, nullable=False, default=0)   # already depreciated before entering the register
    accumulated_depreciation = Column(MONEY, nullable=False, default=0)          # running total this register has posted (+ opening)
    last_depreciation_date = Column(Date, nullable=True)
    status = Column(String(20), nullable=False, default="active")
    disposal_date = Column(Date, nullable=True)
    disposal_proceeds = Column(MONEY, nullable=True)
    disposal_journal_id = Column(Integer, ForeignKey("journals.id"), nullable=True)
    notes = Column(Text, nullable=True)
    created_by = Column(Integer, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    asset_account = relationship("LedgerAccount", foreign_keys=[asset_account_id])
    depreciation_account = relationship("LedgerAccount", foreign_keys=[depreciation_account_id])
    expense_account = relationship("LedgerAccount", foreign_keys=[expense_account_id])
    runs = relationship("DepreciationRun", back_populates="asset", order_by="DepreciationRun.as_at", cascade="all, delete-orphan")


class DepreciationRun(Base):
    """One posted depreciation entry for one asset (the audit trail behind the running total)."""
    __tablename__ = "asset_depreciation_runs"
    id = Column(Integer, primary_key=True)
    org_id = Column(Integer, ForeignKey("organisations.id", ondelete="CASCADE"), nullable=False, index=True)
    asset_id = Column(Integer, ForeignKey("fixed_assets.id", ondelete="CASCADE"), nullable=False, index=True)
    as_at = Column(Date, nullable=False)
    amount = Column(MONEY, nullable=False)
    accumulated_after = Column(MONEY, nullable=False)
    journal_id = Column(Integer, ForeignKey("journals.id"), nullable=True)
    created_by = Column(Integer, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    asset = relationship("FixedAsset", back_populates="runs")


ASSETS_TABLES = [FixedAsset.__table__, DepreciationRun.__table__]
