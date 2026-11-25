"""
Accounting module DB models.

Tables
------
  accounting_documents   Parent: Quote / Invoice (Sale) or Bill / Receipt (Purchase)
  accounting_line_items  Line items for each document
  accounting_suppliers   Supplier/vendor master (for Purchase side)
  accounting_extractions Raw OCR/extraction results for Bills and Receipts

Design principles
-----------------
- Fully separate from the reconciliation Transaction model.
- document_type distinguishes the four document kinds:
    'quote'    - Sale › Quote (not yet invoiced)
    'invoice'  - Sale › Invoice (tax invoice, GST-compliant)
    'bill'     - Purchase › Bill  (extracted from supplier PDF/image)
    'receipt'  - Purchase › Receipt (extracted from receipt PDF/image)
- user_id ties every record to the logged-in user for strict data isolation.
- No CASCADE deletions from users table are needed — documents remain even
  if a user is deactivated (admin can review).
"""

from datetime import datetime
from sqlalchemy import (
    Boolean, Column, DateTime, Float, ForeignKey,
    Integer, String, Text, JSON,
)
from sqlalchemy.orm import relationship
from db_app.models.base import Base


class AccountingDocument(Base):
    """One Quote, Invoice, Bill or Receipt."""
    __tablename__ = "accounting_documents"

    id              = Column(Integer, primary_key=True, index=True)
    user_id         = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True)

    # ── Document kind ─────────────────────────────────────────────────────────
    document_type   = Column(String(20), nullable=False, index=True)
    # 'quote' | 'invoice' | 'bill' | 'receipt'

    document_number = Column(String(80), nullable=True, index=True)
    # e.g. "INV-2024-001", "QTE-001", "BILL-0042"

    status          = Column(String(30), default="draft")
    # quote: draft | sent | accepted | declined | expired
    # invoice: draft | sent | paid | overdue | void
    # bill: pending | approved | paid | disputed
    # receipt: unmatched | matched | reconciled

    # ── Dates ─────────────────────────────────────────────────────────────────
    document_date   = Column(DateTime, nullable=True)   # issue / receipt date
    due_date        = Column(DateTime, nullable=True)   # due / expiry date
    paid_date       = Column(DateTime, nullable=True)

    # ── Party info ─────────────────────────────────────────────────────────────
    # Sale side: the customer we're billing
    # Purchase side: the supplier we're paying
    party_name      = Column(String(255), nullable=True)
    party_email     = Column(String(255), nullable=True)
    party_phone     = Column(String(50),  nullable=True)
    party_address   = Column(Text,        nullable=True)
    party_abn       = Column(String(20),  nullable=True)   # ABN / tax ID

    # Our business info (Sale side mainly; stored so PDF looks right)
    business_name   = Column(String(255), nullable=True)
    business_id     = Column(Integer, ForeignKey("business_details.id", ondelete="SET NULL"), nullable=True)

    # ── Amounts ────────────────────────────────────────────────────────────────
    subtotal        = Column(Float, default=0.0)
    tax_percent     = Column(Float, default=10.0)  # GST %
    tax_amount      = Column(Float, default=0.0)
    discount_amount = Column(Float, default=0.0)
    total_amount    = Column(Float, default=0.0)
    currency        = Column(String(10), default="AUD")

    # ── GL / reconciliation linkage ───────────────────────────────────────────
    gl_account      = Column(String(200), nullable=True)
    gst_category    = Column(String(100), nullable=True)
    reconciled      = Column(Boolean, default=False)
    reconcile_txn_id = Column(Integer, nullable=True)   # links to transactions.id

    # ── Misc ───────────────────────────────────────────────────────────────────
    notes           = Column(Text, nullable=True)
    payment_terms   = Column(String(255), nullable=True)
    source_file     = Column(String(500), nullable=True)  # original uploaded filename
    source_text     = Column(Text, nullable=True)         # raw OCR text (bills/receipts)
    extracted_data  = Column(JSON, nullable=True)         # full extraction JSON blob

    created_at      = Column(DateTime, default=datetime.utcnow)
    updated_at      = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # ── Relationships ──────────────────────────────────────────────────────────
    line_items = relationship(
        "AccountingLineItem",
        back_populates="document",
        cascade="all, delete-orphan",
        order_by="AccountingLineItem.sort_order",
    )


class AccountingLineItem(Base):
    """One line on a Quote / Invoice / Bill / Receipt."""
    __tablename__ = "accounting_line_items"

    id           = Column(Integer, primary_key=True, index=True)
    document_id  = Column(Integer, ForeignKey("accounting_documents.id", ondelete="CASCADE"), nullable=False, index=True)
    sort_order   = Column(Integer, default=0)

    description  = Column(String(500), nullable=False)
    quantity     = Column(Float, nullable=False, default=1.0)
    unit_price   = Column(Float, nullable=False, default=0.0)
    line_total   = Column(Float, nullable=False, default=0.0)

    # Optional per-line GL (useful for split bills)
    gl_account   = Column(String(200), nullable=True)
    gst_category = Column(String(100), nullable=True)

    created_at   = Column(DateTime, default=datetime.utcnow)

    document = relationship("AccountingDocument", back_populates="line_items")


class AccountingSupplier(Base):
    """
    Supplier master list (Purchase side).
    Populated automatically when bills/receipts are extracted and can be
    managed manually. Mirrors Customer on the Sale side.
    """
    __tablename__ = "accounting_suppliers"

    id           = Column(Integer, primary_key=True, index=True)
    user_id      = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True)

    name         = Column(String(255), nullable=False)
    email        = Column(String(255), nullable=True)
    phone        = Column(String(50),  nullable=True)
    address      = Column(Text,        nullable=True)
    abn          = Column(String(20),  nullable=True)
    website      = Column(String(255), nullable=True)
    gl_account   = Column(String(200), nullable=True)   # default GL for this supplier
    gst_category = Column(String(100), nullable=True)
    is_active    = Column(Boolean, default=True)

    created_at   = Column(DateTime, default=datetime.utcnow)
    updated_at   = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class AccountingCustomer(Base):
    """
    Customer master list (Sales side).
    Populated manually or via CSV upload. Mirrors AccountingSupplier on the Purchase side.
    """
    __tablename__ = "accounting_customers"

    id           = Column(Integer, primary_key=True, index=True)
    user_id      = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True)

    name         = Column(String(255), nullable=False)
    email        = Column(String(255), nullable=True)
    phone        = Column(String(50),  nullable=True)
    address      = Column(Text,        nullable=True)
    city         = Column(String(100), nullable=True)
    state        = Column(String(20),  nullable=True)
    postcode     = Column(String(10),  nullable=True)
    abn          = Column(String(20),  nullable=True)
    website      = Column(String(255), nullable=True)
    contact_name = Column(String(255), nullable=True)
    notes        = Column(Text,        nullable=True)
    gl_account   = Column(String(200), nullable=True)   # default GL for this customer
    gst_category = Column(String(100), nullable=True)
    is_active    = Column(Boolean, default=True)

    created_at   = Column(DateTime, default=datetime.utcnow)
    updated_at   = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
