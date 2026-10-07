"""Legacy pricing_plans table (mirrors the organisation plans; see subscription.align)."""
from datetime import datetime

from sqlalchemy import Column, Integer, String, Float, Boolean, JSON, TIMESTAMP

from accfino.shared.db.base import Base


class PricingPlan(Base):
    """Replaces pricing.json. One row per plan slug ("base", "pro", etc.).

    Split into real columns (rather than one opaque JSON blob) so the
    plan is actually browsable/editable field-by-field in the Tables
    admin UI -- previously `data` held the whole payload as one JSON
    value and showed as "[object Object]" in any plain table view.

    `features` and `modules` stay as JSON columns since they're genuinely
    variable-length lists, not scalar fields -- everything else that's a
    single value in pricing.json gets its own column."""
    __tablename__ = "pricing_plans"

    slug                  = Column(String(50), primary_key=True)
    name                  = Column(String(200), nullable=True)
    description           = Column(String(1000), nullable=True)
    price_monthly         = Column(Integer, default=0)
    price_yearly          = Column(Integer, default=0)
    badge                 = Column(String(50), nullable=True)
    highlight             = Column(Boolean, default=False)
    category              = Column(String(50), nullable=True)
    features              = Column(JSON, nullable=False, default=list)
    modules               = Column(JSON, nullable=False, default=list)
    price_effective_from  = Column(String(20), nullable=True)  # kept as text ("2026-06-27") to match the JSON exactly, no date-parsing risk
    sort_order            = Column(Integer, default=0)
    updated_at            = Column(TIMESTAMP, default=datetime.utcnow, onupdate=datetime.utcnow)

    def to_dict(self) -> dict:
        """Reconstructs the exact same nested-dict shape every consumer
        (react_api.py, payments.py) already expects -- callers don't need
        to change just because storage moved from one JSON blob to real
        columns."""
        return {
            "name": self.name,
            "description": self.description,
            "price_monthly": self.price_monthly,
            "price_yearly": self.price_yearly,
            "badge": self.badge,
            "highlight": self.highlight,
            "category": self.category,
            "features": self.features or [],
            "modules": self.modules or [],
            "price_effective_from": self.price_effective_from,
        }
