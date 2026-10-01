"""Subscription tables: plan catalogue, add-on catalogue and one subscription row per organisation."""
from datetime import datetime

from sqlalchemy import Boolean, Column, Date, DateTime, ForeignKey, Integer, Numeric, String, Text

from accfino_core.models import Base


class Plan(Base):
    __tablename__ = "sub_plans"
    id = Column(String(40), primary_key=True)                   # starter | growth | premium | ...
    name = Column(String(100), nullable=False)
    description = Column(Text, nullable=True)
    price_monthly = Column(Numeric(12, 2), nullable=False, default=0)
    price_yearly = Column(Numeric(12, 2), nullable=False, default=0)
    seat_limit = Column(Integer, nullable=True)                 # NULL = unlimited users
    modules = Column(Text, nullable=False, default="[]")        # JSON list of module / feature ids, or ["*"] for everything
    is_active = Column(Boolean, nullable=False, default=True)   # inactive plans cannot be newly assigned
    sort_order = Column(Integer, nullable=False, default=0)


class Addon(Base):
    __tablename__ = "sub_addons"
    id = Column(String(40), primary_key=True)
    name = Column(String(100), nullable=False)
    description = Column(Text, nullable=True)
    price_monthly = Column(Numeric(12, 2), nullable=False, default=0)
    modules = Column(Text, nullable=False, default="[]")
    extra_seats = Column(Integer, nullable=False, default=0)    # a "5 more users" pack adds seats instead of modules
    is_active = Column(Boolean, nullable=False, default=True)
    sort_order = Column(Integer, nullable=False, default=0)


class OrgSubscription(Base):
    __tablename__ = "org_subscriptions"
    org_id = Column(Integer, ForeignKey("organisations.id", ondelete="CASCADE"), primary_key=True)
    plan_id = Column(String(40), nullable=False)
    addons = Column(Text, nullable=False, default="[]")         # JSON list of add-on ids
    status = Column(String(20), nullable=False, default="active")   # trial | active | past_due | cancelled | expired
    billing_period = Column(String(10), nullable=False, default="monthly")
    trial_ends = Column(Date, nullable=True)
    period_end = Column(Date, nullable=True)                    # paid up to (NULL = no end)
    stripe_customer_id = Column(String(100), nullable=True)     # reserved for the Stripe step
    stripe_sub_id = Column(String(100), nullable=True)
    notes = Column(Text, nullable=True)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    updated_by = Column(Integer, nullable=True)


SUBSCRIPTION_TABLES = [Plan.__table__, Addon.__table__, OrgSubscription.__table__]
