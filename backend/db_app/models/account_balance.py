from sqlalchemy import Column, Integer, String, Float, Boolean, ForeignKey, TIMESTAMP, UniqueConstraint
from sqlalchemy.sql import func
from .base import Base


class AccountBalance(Base):
    """
    Stores the opening (initial) balance for a given bank account per calendar month.

    The opening balance for month M is the closing balance of month M-1.
    Sources (in priority order):
      1. Last `bank_balance` value from the transaction CSV for the previous month
      2. Manual entry by the user on the reconciliation output page
    """
    __tablename__ = "account_balances"

    id         = Column(Integer, primary_key=True, autoincrement=True)
    user_id    = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    bank       = Column(String(100), nullable=False)
    account    = Column(String(100), nullable=False)
    year       = Column(Integer, nullable=False)
    month      = Column(Integer, nullable=False)          # 1-12
    balance    = Column(Float, nullable=False)            # AUD
    is_manual  = Column(Boolean, default=False)           # True = user typed it in
    source     = Column(String(50), default="csv")        # "csv" | "manual" | "derived"
    updated_at = Column(TIMESTAMP, server_default=func.now(), onupdate=func.now())

    __table_args__ = (
        UniqueConstraint("user_id", "bank", "account", "year", "month",
                         name="uq_account_balance"),
    )