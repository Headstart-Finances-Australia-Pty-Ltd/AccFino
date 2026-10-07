"""
Inventory (organisation-scoped). One weighted-average cost per item: every purchase blends into
the average, every sale (or write-off) draws COGS at the current average - the same method Xero
and MYOB use for tracked inventory.

  stock_items       SKU/name/accounts/tax codes/quantity on hand/weighted-average unit cost
  stock_movements   every buy, sell, and stocktake adjustment, each linked to the journal it posted
"""
from datetime import datetime

from sqlalchemy import Boolean, Column, Date, DateTime, ForeignKey, Integer, Numeric, String, Text, UniqueConstraint
from sqlalchemy.orm import relationship

from accfino.core.models import MONEY
from accfino.shared.db.base import Base

QTY = Numeric(18, 4)
MOVEMENT_KINDS = ("buy", "sell", "adjustment", "opening")


class StockItem(Base):
    __tablename__ = "stock_items"
    __table_args__ = (UniqueConstraint("org_id", "sku", name="uq_stock_item_org_sku"),)
    id = Column(Integer, primary_key=True)
    org_id = Column(Integer, ForeignKey("organisations.id", ondelete="CASCADE"), nullable=False, index=True)
    sku = Column(String(60), nullable=False)
    name = Column(String(255), nullable=False)
    description = Column(Text, nullable=True)
    inventory_account_id = Column(Integer, ForeignKey("ledger_accounts.id"), nullable=False)   # 630 Inventory by default
    cogs_account_id = Column(Integer, ForeignKey("ledger_accounts.id"), nullable=False)         # 310 Cost of Goods Sold by default
    sales_account_id = Column(Integer, ForeignKey("ledger_accounts.id"), nullable=True)         # for when the item is sold on an invoice line
    purchase_tax_code_id = Column(Integer, ForeignKey("tax_codes.id"), nullable=True)
    sales_tax_code_id = Column(Integer, ForeignKey("tax_codes.id"), nullable=True)
    sale_price = Column(MONEY, nullable=True)
    quantity_on_hand = Column(QTY, nullable=False, default=0)
    average_cost = Column(Numeric(18, 6), nullable=False, default=0)     # extra dp: an average blended over many units needs the precision
    value_on_hand = Column(MONEY, nullable=False, default=0)             # quantity_on_hand * average_cost, kept in step explicitly (rounding-safe)
    is_active = Column(Boolean, nullable=False, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    inventory_account = relationship("LedgerAccount", foreign_keys=[inventory_account_id])
    cogs_account = relationship("LedgerAccount", foreign_keys=[cogs_account_id])
    sales_account = relationship("LedgerAccount", foreign_keys=[sales_account_id])
    movements = relationship("StockMovement", back_populates="item", order_by="StockMovement.id", cascade="all, delete-orphan")


class StockMovement(Base):
    __tablename__ = "stock_movements"
    id = Column(Integer, primary_key=True)
    org_id = Column(Integer, ForeignKey("organisations.id", ondelete="CASCADE"), nullable=False, index=True)
    item_id = Column(Integer, ForeignKey("stock_items.id", ondelete="CASCADE"), nullable=False, index=True)
    kind = Column(String(20), nullable=False)
    movement_date = Column(Date, nullable=False)
    quantity = Column(QTY, nullable=False)                     # always positive; direction comes from `kind`
    unit_cost = Column(Numeric(18, 6), nullable=True)          # given for buy/opening; computed (the average) for sell/adjustment-down
    amount = Column(MONEY, nullable=False)                     # quantity * unit_cost, the value that moved
    quantity_after = Column(QTY, nullable=False)
    average_cost_after = Column(Numeric(18, 6), nullable=False)
    reference = Column(String(200), nullable=True)
    note = Column(Text, nullable=True)
    journal_id = Column(Integer, ForeignKey("journals.id"), nullable=True)
    created_by = Column(Integer, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    item = relationship("StockItem", back_populates="movements")


INVENTORY_TABLES = [StockItem.__table__, StockMovement.__table__]
