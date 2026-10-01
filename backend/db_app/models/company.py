"""
db_app/models/company.py
-----------------------------------------------------------------------------
Company / Organisation database - Australian and worldwide.

Two tables:
  companies       - canonical company records (name, ABN, category, country)
  company_aliases - alternate names / abbreviations - company_id mapping

Populated at startup from seed data in db_app/company_seed.py.
New companies are auto-captured during reconciliation when the Who column
identifies a previously unseen entity - admin can approve them.
"""
from datetime import datetime
from sqlalchemy import (
    Column, Integer, String, Boolean, TIMESTAMP,
    ForeignKey, Index, UniqueConstraint,
)
from sqlalchemy.orm import relationship
from .base import Base


class Company(Base):
    __tablename__ = "companies"

    id           = Column(Integer, primary_key=True, index=True)
    # Canonical display name  e.g. "Commonwealth Bank of Australia"
    name         = Column(String(255), nullable=False, unique=True)
    # Short name / trading name  e.g. "CommBank"
    short_name   = Column(String(100), nullable=True)
    # Category  e.g. "Bank", "Government", "Retail", "Food & Beverage", etc.
    category     = Column(String(100), nullable=False, default="Other")
    # Sub-category  e.g. "Big 4 Bank", "Federal Government", "Supermarket"
    subcategory  = Column(String(100), nullable=True)
    # ISO 3166-1 alpha-2 country code  e.g. "AU", "US", "GB"
    country      = Column(String(2),   nullable=False, default="AU")
    # ABN / ACN for Australian entities (blank for overseas)
    abn          = Column(String(20),  nullable=True)
    # Whether this is an Australian Government entity (ATO, ASIC, ABS, etc.)
    is_government= Column(Boolean,     default=False)
    # Approved by admin (auto-captured companies start as False)
    approved     = Column(Boolean,     default=True)
    # Timestamps
    created_at   = Column(TIMESTAMP,   default=datetime.utcnow)
    updated_at   = Column(TIMESTAMP,   default=datetime.utcnow, onupdate=datetime.utcnow)

    aliases      = relationship("CompanyAlias", back_populates="company",
                                cascade="all, delete-orphan")

    def __repr__(self):
        return f"<Company {self.name} [{self.category}/{self.country}]>"


class CompanyAlias(Base):
    """
    Maps alternate name fragments to a canonical company.
    The reconciliation engine searches aliases (case-insensitive substring)
    to identify the Who field from transaction descriptions.
    """
    __tablename__ = "company_aliases"

    id         = Column(Integer, primary_key=True, index=True)
    company_id = Column(Integer, ForeignKey("companies.id", ondelete="CASCADE"),
                        nullable=False)
    # Alias keyword - stored lower-case, used for substring matching
    alias      = Column(String(200), nullable=False)
    # Higher priority aliases are checked first (default 0)
    priority   = Column(Integer, default=0)

    company    = relationship("Company", back_populates="aliases")

    __table_args__ = (
        UniqueConstraint("company_id", "alias", name="uq_company_alias"),
        Index("ix_company_alias_alias", "alias"),
    )

    def __repr__(self):
        return f"<CompanyAlias '{self.alias}' - {self.company_id}>"
