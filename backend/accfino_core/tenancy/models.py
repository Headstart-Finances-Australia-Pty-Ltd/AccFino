"""Tenancy tables: the public profile + URL name of each organisation, its access/invitation codes, and signup attempt tracking."""
from datetime import datetime

from sqlalchemy import Boolean, Column, DateTime, ForeignKey, Integer, String, Text

from accfino_core.models import Base


class OrgProfile(Base):
    __tablename__ = "org_profiles"
    org_id = Column(Integer, ForeignKey("organisations.id", ondelete="CASCADE"), primary_key=True)
    slug = Column(String(40), nullable=False, unique=True, index=True)     # the tenant URL name: https://<slug>.<base domain>
    acn = Column(String(20), nullable=True)
    other_id = Column(String(60), nullable=True)                           # another organisation identifier (non-Australian entities)
    address = Column(Text, nullable=True)
    city = Column(String(100), nullable=True)                              # shown (with state) in "join an organisation" search results
    state = Column(String(30), nullable=True)
    postcode = Column(String(10), nullable=True)
    phone = Column(String(40), nullable=True)
    contact_email = Column(String(200), nullable=True)
    industry = Column(String(100), nullable=True)
    discoverable = Column(Boolean, nullable=False, default=True)           # appear in the join-organisation search (exact web address always works)
    created_at = Column(DateTime, default=datetime.utcnow)


class OrgInvite(Base):
    __tablename__ = "org_invites"
    id = Column(Integer, primary_key=True)
    org_id = Column(Integer, ForeignKey("organisations.id", ondelete="CASCADE"), nullable=False, index=True)
    code_hash = Column(String(64), nullable=False, unique=True, index=True)  # HMAC-SHA256 of the code. The code itself is never stored.
    code_hint = Column(String(20), nullable=False)                           # first characters only, so the admin can recognise a code ("ABC-7F4K-....")
    role = Column(String(20), nullable=False, default="bookkeeper")
    label = Column(String(100), nullable=True)
    created_by = Column(Integer, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    expires_at = Column(DateTime, nullable=False)
    max_uses = Column(Integer, nullable=False, default=1)                    # single use unless explicitly configured otherwise
    used_count = Column(Integer, nullable=False, default=0)
    last_used_by = Column(Integer, nullable=True)
    last_used_at = Column(DateTime, nullable=True)
    revoked_at = Column(DateTime, nullable=True)
    revoked_by = Column(Integer, nullable=True)


class SignupAttempt(Base):
    __tablename__ = "signup_attempts"
    id = Column(Integer, primary_key=True)
    created_at = Column(DateTime, default=datetime.utcnow, index=True)
    ip = Column(String(64), nullable=False, index=True)
    org_id = Column(Integer, nullable=True, index=True)
    kind = Column(String(20), nullable=False)                                # code | lookup | create
    success = Column(Boolean, nullable=False, default=False)
    reason = Column(String(40), nullable=True)


TENANCY_TABLES = [OrgProfile.__table__, OrgInvite.__table__, SignupAttempt.__table__]
