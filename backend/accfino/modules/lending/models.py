"""Lending data model."""
from datetime import datetime

from sqlalchemy import Column, Integer, String, Float, Boolean, JSON, TIMESTAMP

from accfino.shared.db.base import Base


class LendingClassification(Base):
    """Replaces lending_classifications.json (a flat list of keyword rules).
    Fully relational -- the lending module's reader is shallow enough that
    this is a safe, direct conversion with no bridge file needed."""
    __tablename__ = "lending_classifications"

    id         = Column(Integer, primary_key=True)
    keyword    = Column(String(300), nullable=False, index=True)
    category   = Column(String(100), nullable=True)
    exp_type   = Column(String(10), nullable=True)
    in_or_out  = Column(String(10), nullable=True)
    weight     = Column(Integer, default=0)
    source     = Column(String(50), nullable=True)
