from sqlalchemy import Column, Integer, String, Float, Boolean, ForeignKey, TIMESTAMP, UniqueConstraint
from sqlalchemy.orm import relationship
from datetime import datetime
from .base import Base

class Transaction(Base):
    __tablename__ = 'transactions'

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey('users.id', ondelete='CASCADE'), nullable=False)

    date = Column(TIMESTAMP, nullable=False)
    bank = Column(String(100), nullable=False)
    account = Column(String(100), nullable=False)
    description = Column(String(255), nullable=False)

    # Amounts stored in AUD (converted at processing time)
    debit = Column(Float, default=0.0)
    credit = Column(Float, default=0.0)
    bank_balance = Column(Float, nullable=True)           # balance from bank CSV (AUD)

    # Original currency data
    currency = Column(String(10), default='AUD')         # e.g. 'AUD', 'USD', 'INR'
    amount_original = Column(Float, nullable=True)        # original amount before conversion
    exchange_rate = Column(Float, nullable=True)          # rate used: 1 <currency> = X AUD

    classification = Column(String(100), nullable=True)
    pair_id = Column(String(100), nullable=True)
    gl_account = Column(String(100), nullable=True)
    gst = Column(Float, default=0.0)
    gst_category = Column(String(100), nullable=True)
    who = Column(String(100), nullable=True)

    # Loan payment split
    is_loan_payment = Column(Boolean, default=False)
    loan_principal = Column(Float, nullable=True)         # principal portion (AUD)
    loan_interest = Column(Float, nullable=True)          # interest portion (AUD)
    loan_interest_rate = Column(Float, nullable=True)     # annual interest rate % (e.g. 6.5)
    loan_principal_gl = Column(String(100), nullable=True)
    loan_interest_gl = Column(String(100), nullable=True)

    uploaded_at = Column(TIMESTAMP, default=datetime.now)

    user = relationship("User", back_populates="transactions")

    __table_args__ = (
        UniqueConstraint(
            'user_id', 'date', 'bank', 'account', 'description', 'debit', 'credit', 'currency',
            name='uq_transaction'
        ),
    )