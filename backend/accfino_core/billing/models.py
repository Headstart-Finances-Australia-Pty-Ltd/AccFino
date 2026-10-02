"""Billing state per organisation. NO card numbers are ever stored: the card is tokenised in the browser by Square's own secure form and we keep only
Square's customer/card ids and the last four digits (so people can recognise the card)."""
from datetime import datetime

from sqlalchemy import BigInteger, Boolean, Column, Date, DateTime, ForeignKey, Integer, String, Text

from accfino_core.models import Base


class OrgBilling(Base):
    __tablename__ = "org_billing"
    org_id = Column(Integer, ForeignKey("organisations.id", ondelete="CASCADE"), primary_key=True)
    square_customer_id = Column(String(64), nullable=True)
    card_id = Column(String(64), nullable=True)
    card_brand = Column(String(30), nullable=True)
    card_last4 = Column(String(4), nullable=True)
    card_exp_month = Column(Integer, nullable=True)
    card_exp_year = Column(Integer, nullable=True)
    auto_renew = Column(Boolean, nullable=False, default=False)
    failure_count = Column(Integer, nullable=False, default=0)           # failed attempts for the current renewal
    next_attempt_on = Column(Date, nullable=True)
    last_error = Column(String(300), nullable=True)
    updated_by = Column(Integer, nullable=True)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class BillingCharge(Base):
    """One row per attempt to take money. Inserted BEFORE Square is called (unique key) so two workers can never charge the same renewal twice."""
    __tablename__ = "billing_charges"
    id = Column(Integer, primary_key=True)
    org_id = Column(Integer, ForeignKey("organisations.id", ondelete="CASCADE"), nullable=False, index=True)
    idempotency_key = Column(String(120), nullable=False, unique=True)
    amount_cents = Column(BigInteger, nullable=False)
    currency = Column(String(3), nullable=False, default="AUD")
    plan_id = Column(String(40), nullable=True)
    billing_period = Column(String(10), nullable=True)
    period_start = Column(Date, nullable=True)
    period_end = Column(Date, nullable=True)
    status = Column(String(12), nullable=False, default="pending")      # pending | paid | failed
    square_payment_id = Column(String(64), nullable=True)
    receipt_url = Column(String(300), nullable=True)
    error = Column(String(300), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    settled_at = Column(DateTime, nullable=True)


BILLING_TABLES = [OrgBilling.__table__, BillingCharge.__table__]
