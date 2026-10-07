"""
accfino_core.models
-------------------
Platform data model: organisations, memberships, security, sessions, access policy and audit.
The double-entry ledger tables now live in accfino.modules.accounting.models.ledger.

Design rules
  * Every financial record belongs to an organisation (org_id), not a user.
  * All money columns are NUMERIC(18,2) and handled as Decimal in Python.
  * Posted journals are immutable. Corrections are made by reversal. This is
    enforced in the service layer AND by PostgreSQL triggers (see migrate.py).
  * Legacy tables (transactions, accounting_documents, ...) are untouched and
    remain user-scoped; they feed the ledger through sync services.
"""
from datetime import datetime

from sqlalchemy import (
    Boolean, CheckConstraint, Column, Date, DateTime, ForeignKey, Index, Integer,
    JSON, Numeric, String, Text, UniqueConstraint, text,
)
from sqlalchemy.orm import relationship

from accfino.shared.db.base import Base

from accfino.shared.db.types import MONEY, RATE, FXRATE  # noqa: F401  (re-exported: m.MONEY etc.)


# ---------------------------------------------------------------- tenancy ---
class Organisation(Base):
    __tablename__ = "organisations"

    id = Column(Integer, primary_key=True)
    name = Column(String(255), nullable=False)
    legal_name = Column(String(255), nullable=True)
    abn = Column(String(20), nullable=True)
    entity_type = Column(String(30), nullable=True)      # company|trust|partnership|sole_trader|smsf|other
    base_currency = Column(String(3), nullable=False, default="AUD")
    gst_registered = Column(Boolean, nullable=False, default=True)
    gst_basis = Column(String(10), nullable=False, default="accrual")  # accrual|cash
    fy_end_month = Column(Integer, nullable=False, default=6)          # June year end
    lock_date = Column(Date, nullable=True)            # no postings on/before this date
    next_journal_no = Column(Integer, nullable=False, default=1)
    # The user whose pre-Phase-0 personal data (bank transactions etc.) belongs to this org
    legacy_user_id = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True)
    # THE Organisation Admin / Account Owner: the one person who administers this organisation and receives its account, licence,
    # billing and security communications. Always the user holding the single 'owner' membership (kept in step by accfino_core.org_admin).
    admin_user_id = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True)
    is_active = Column(Boolean, nullable=False, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    memberships = relationship("OrgMembership", back_populates="organisation", cascade="all, delete-orphan")


ORG_ROLES = ("owner", "admin", "accountant", "bookkeeper", "payroll", "readonly", "payroll_admin", "employee")
# 'owner' IS the Organisation Admin: exactly one per organisation (enforced by a unique index), it cannot be handed out through an invitation,
# a role change or "add member" - only by transferring the organisation (accfino_core.org_admin.transfer_admin).
ADMIN_ROLE = "owner"
# Roles an Organisation Admin may give to the people they invite (the "Organisation User" roles). The legacy 'admin' role is kept in the database
# so old rows stay valid, but it no longer carries any organisation-administration rights and can no longer be assigned.
# payroll = Payroll Manager; payroll_admin = Payroll Administrator; employee = self-service only (NO ledger access: see context.ROLE_PERMS)
ASSIGNABLE_ROLES = ("accountant", "bookkeeper", "payroll", "readonly", "payroll_admin", "employee")


class OrgMembership(Base):
    __tablename__ = "org_memberships"

    id = Column(Integer, primary_key=True)
    org_id = Column(Integer, ForeignKey("organisations.id", ondelete="CASCADE"), nullable=False, index=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    role = Column(String(20), nullable=False, default="owner")
    is_default = Column(Boolean, nullable=False, default=False)     # the member's HOME organisation
    suspended_at = Column(DateTime, nullable=True)                  # access to THIS organisation suspended
    suspended_reason = Column(String(300), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    organisation = relationship("Organisation", back_populates="memberships")

    __table_args__ = (
        UniqueConstraint("org_id", "user_id", name="uq_org_member"),
        CheckConstraint(f"role IN {ORG_ROLES}", name="ck_org_member_role"),
        # One primary Organisation Admin per organisation, guaranteed by the database itself.
        Index("uq_org_one_owner", "org_id", unique=True,
              postgresql_where=text("role = 'owner'"), sqlite_where=text("role = 'owner'")),
    )


# --------------------------------------------------------------- security ---
class UserSecurity(Base):
    """Security state kept beside the legacy users table (which is not altered)."""
    __tablename__ = "user_security"

    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    token_version = Column(Integer, nullable=False, default=1)   # bump to revoke all tokens
    mfa_secret = Column(String(64), nullable=True)
    mfa_enabled = Column(Boolean, nullable=False, default=False)
    mfa_recovery_hashes = Column(JSON, nullable=True)             # list of bcrypt hashes
    failed_logins = Column(Integer, nullable=False, default=0)
    locked_until = Column(DateTime, nullable=True)
    last_login_at = Column(DateTime, nullable=True)
    password_changed_at = Column(DateTime, nullable=True)
    # Additional MFA methods (authenticator app = mfa_enabled/mfa_secret above)
    phone_e164 = Column(String(20), nullable=True)
    sms_mfa_enabled = Column(Boolean, nullable=False, default=False)
    email_mfa_enabled = Column(Boolean, nullable=False, default=False)
    # IAM step 2: account state managed by administrators
    disabled_at = Column(DateTime, nullable=True)
    disabled_reason = Column(String(300), nullable=True)
    must_change_password = Column(Boolean, nullable=False, default=False)
    # Contact verification: when the person proved they control their email address / phone number (accfino_core.security.contact_verify)
    email_verified_at = Column(DateTime, nullable=True)
    phone_verified_at = Column(DateTime, nullable=True)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class WebAuthnCredential(Base):
    """A passkey: Face ID / Touch ID / Windows Hello / Android biometrics or a security key.
    Only the public key is stored - biometric data never leaves the user's device."""
    __tablename__ = "webauthn_credentials"

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    credential_id = Column(String(512), nullable=False, unique=True)     # base64url
    public_key = Column(Text, nullable=False)                           # base64url COSE key
    sign_count = Column(Integer, nullable=False, default=0)
    transports = Column(JSON, nullable=True)
    name = Column(String(100), nullable=False, default="Passkey")
    aaguid = Column(String(64), nullable=True)
    backed_up = Column(Boolean, nullable=False, default=False)          # synced passkey (iCloud/Google)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    last_used_at = Column(DateTime, nullable=True)


class MfaChallenge(Base):
    """Short-lived one-time codes (SMS/email) and WebAuthn ceremony challenges."""
    __tablename__ = "mfa_challenges"

    id = Column(String(40), primary_key=True)                           # random id
    user_id = Column(Integer, nullable=True, index=True)                # null for passwordless passkey sign-in
    kind = Column(String(30), nullable=False)    # login_sms|login_email|enrol_sms|enrol_email|passkey_register|passkey_auth
    code_hash = Column(String(128), nullable=True)
    challenge = Column(String(256), nullable=True)                      # WebAuthn challenge (base64url)
    destination = Column(String(255), nullable=True)
    attempts = Column(Integer, nullable=False, default=0)
    expires_at = Column(DateTime, nullable=False)
    consumed_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)


class UserSession(Base):
    """One signed-in device/browser. Every access token carries its session id ("sid");
    revoking the session ends that device's access (Entra-style "sign out this device")."""
    __tablename__ = "user_sessions"

    id = Column(String(40), primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    last_seen_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    expires_at = Column(DateTime, nullable=False)
    ip = Column(String(64), nullable=True)
    user_agent = Column(String(400), nullable=True)
    auth_methods = Column(JSON, nullable=True)          # e.g. ["pwd","passkey"]
    revoked_at = Column(DateTime, nullable=True)
    revoked_reason = Column(String(100), nullable=True)


class AccessPolicy(Base):
    """Organisation Conditional Access policy (one row per organisation).
    state: off | report (log only) | on (enforced)."""
    __tablename__ = "access_policies"

    org_id = Column(Integer, ForeignKey("organisations.id", ondelete="CASCADE"), primary_key=True)
    state = Column(String(10), nullable=False, default="off")
    applies_to = Column(String(10), nullable=False, default="all")      # all | admins (owner/admin roles)
    require_mfa = Column(Boolean, nullable=False, default=False)
    allowed_mfa_methods = Column(JSON, nullable=True)                   # null = any; e.g. ["passkey","totp"]
    ip_allowlist = Column(JSON, nullable=True)                          # CIDRs; null/empty = anywhere
    max_session_hours = Column(Integer, nullable=True)                  # sign-in frequency
    updated_by = Column(Integer, nullable=True)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class SystemSetting(Base):
    __tablename__ = "system_settings"

    key = Column(String(100), primary_key=True)
    value = Column(Text, nullable=True)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class AuditLog(Base):
    """Append-only. UPDATE and DELETE are blocked by a database trigger."""
    __tablename__ = "audit_log"

    id = Column(Integer, primary_key=True)
    occurred_at = Column(DateTime, nullable=False, default=datetime.utcnow, index=True)
    org_id = Column(Integer, nullable=True, index=True)
    user_id = Column(Integer, nullable=True, index=True)
    username = Column(String(100), nullable=True)
    action = Column(String(80), nullable=False, index=True)    # e.g. auth.login, ledger.journal.post, http.write
    entity = Column(String(80), nullable=True)
    entity_id = Column(String(80), nullable=True)
    ip = Column(String(64), nullable=True)
    method = Column(String(10), nullable=True)
    path = Column(String(500), nullable=True)
    status_code = Column(Integer, nullable=True)
    detail = Column(JSON, nullable=True)


# Register the subscription tables on this Base so every schema builder (migrate, offline seeder, tests) creates them.
from accfino.core.subscription import models as _subscription_models  # noqa: E402,F401
from accfino.core.tenancy import models as _tenancy_models  # noqa: E402,F401   (tenant profile / invitation tables)
# Register the identity tables (users, roles, permissions, ...) on this Base too: organisations / memberships reference users.id.
from accfino.core.identity import user as _user_model, role as _role_model, permission as _perm_model  # noqa: E402,F401
from accfino.core.identity import association as _assoc_model, password_reset_token as _prt_model  # noqa: E402,F401
