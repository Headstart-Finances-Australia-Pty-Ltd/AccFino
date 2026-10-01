from sqlalchemy import Column, Integer, String, JSON, TIMESTAMP, LargeBinary, ForeignKey, UniqueConstraint
from sqlalchemy.orm import relationship
from datetime import datetime
from .base import Base


class ReconciliationSession(Base):
    """A bank-reconciliation session. Replaces the old per-session directory
    (main_app/data/{username}/{session_id}/) containing accounts.json,
    output/results/results.pkl (a pickled pandas DataFrame), and
    output/results/session_state.json.

    session_id keeps its original meaning (a "%Y%m%d_%H%M%S" timestamp
    string, e.g. "20260601_215431") for display/URL compatibility, but is
    no longer the primary key by itself -- (username, session_id) is
    unique instead, since a bare timestamp string is not guaranteed
    globally unique across users.
    """
    __tablename__ = "reconciliation_sessions"
    __table_args__ = (UniqueConstraint("username", "session_id", name="uq_username_session"),)

    id              = Column(Integer, primary_key=True)
    session_id      = Column(String(32), nullable=False, index=True)
    username        = Column(String(100), nullable=False, index=True)

    # [{"bank_name":..., "account_number":..., "account_name":..., "files": [str,...]}]
    accounts_meta   = Column(JSON, nullable=False, default=list)

    # The reconciliation results table, replacing results.pkl. Stored as a
    # JSON list-of-row-dicts (via df.to_json/read_json for safe NaN/dtype
    # round-tripping) rather than a rigid normalized schema, since the
    # actual column set already varies/evolves across the codebase.
    results         = Column(JSON, nullable=True)

    pending_changes = Column(JSON, nullable=False, default=dict)   # {str(row_index): {col: val}}
    updated_pages   = Column(JSON, nullable=False, default=list)    # [int, ...] (a set on the Python side)
    page_number     = Column(Integer, nullable=False, default=1)

    created_at      = Column(TIMESTAMP, default=datetime.utcnow)
    last_updated    = Column(TIMESTAMP, default=datetime.utcnow, onupdate=datetime.utcnow)

    files = relationship("SessionFile", back_populates="session", cascade="all, delete-orphan")


class SessionFile(Base):
    """A raw uploaded bank-statement file (CSV/PDF/etc), replacing
    input/files/<filename> on disk. Stored as a blob directly in Postgres
    so sessions have zero filesystem dependency."""
    __tablename__ = "session_files"

    id          = Column(Integer, primary_key=True)
    session_id  = Column(Integer, ForeignKey("reconciliation_sessions.id", ondelete="CASCADE"), nullable=False, index=True)
    filename    = Column(String(300), nullable=False)
    content     = Column(LargeBinary, nullable=False)
    uploaded_at = Column(TIMESTAMP, default=datetime.utcnow)

    session = relationship("ReconciliationSession", back_populates="files")
