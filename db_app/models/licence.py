from sqlalchemy import Column, Integer, String, ForeignKey
from sqlalchemy.orm import relationship
from .base import Base


class LicenceRecord(Base):
    __tablename__ = "licence_records"

    id                 = Column(Integer, primary_key=True)
    user_id            = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    licence_type       = Column(String(50),   default="demo")   # demo | basic | premium | custom
    plan_id            = Column(String(50),   default="demo")   # matches PLANS key
    billing_period     = Column(String(10),   default="")       # monthly | yearly
    payment_mode       = Column(String(50),   default="")       # card | bank | invoice
    start_date         = Column(String(20),   default="")
    end_date           = Column(String(20),   default="")
    notes              = Column(String(500),  default="")
    modules            = Column(String(1000), default="")       # JSON list of enabled module keys
    stripe_customer_id = Column(String(100),  default="")       # Stripe customer ID
    stripe_sub_id      = Column(String(100),  default="")       # Stripe subscription ID
    amount_paid        = Column(String(20),   default="")       # last payment amount AUD

    user = relationship("User", backref="licence_records")
