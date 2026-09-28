"""
accfino_core.models
-------------------
Phase 0 data model: organisations, security, audit, and the double-entry ledger.

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
    JSON, Numeric, String, Text, UniqueConstraint,
)
from sqlalchemy.orm import relationship

from db_app.models.base import Base

MONEY = Numeric(18, 2)
RATE = Numeric(9, 6)


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
    is_active = Column(Boolean, nullable=False, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    memberships = relationship("OrgMembership", back_populates="organisation", cascade="all, delete-orphan")


ORG_ROLES = ("owner", "admin", "accountant", "bookkeeper", "payroll", "readonly")


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


# ----------------------------------------------------------------- ledger ---
ACCOUNT_CLASSES = ("asset", "liability", "equity", "revenue", "expense")

# account_type -> account_class
ACCOUNT_TYPES = {
    "bank": "asset",
    "current_asset": "asset",
    "inventory": "asset",
    "fixed_asset": "asset",
    "non_current_asset": "asset",
    "credit_card": "liability",
    "current_liability": "liability",
    "non_current_liability": "liability",
    "equity": "equity",
    "revenue": "revenue",
    "other_income": "revenue",
    "direct_costs": "expense",
    "expense": "expense",
    "other_expense": "expense",
}


class TaxCode(Base):
    __tablename__ = "tax_codes"

    id = Column(Integer, primary_key=True)
    org_id = Column(Integer, ForeignKey("organisations.id", ondelete="CASCADE"), nullable=False, index=True)
    code = Column(String(30), nullable=False)          # OUTPUT, INPUT, CAPEX, FRE, ...
    name = Column(String(100), nullable=False)         # "GST on Income" (matches legacy gst_category)
    rate = Column(RATE, nullable=False, default=0)     # 0.100000 for 10%
    applies_to = Column(String(10), nullable=False, default="both")   # sales|purchases|both
    bas_labels = Column(JSON, nullable=True)           # {"sales": ["G1"], "tax": "1A"}
    is_system = Column(Boolean, nullable=False, default=True)
    is_active = Column(Boolean, nullable=False, default=True)

    __table_args__ = (
        UniqueConstraint("org_id", "code", name="uq_tax_code"),
        UniqueConstraint("org_id", "name", name="uq_tax_code_name"),
    )


class LedgerAccount(Base):
    __tablename__ = "ledger_accounts"

    id = Column(Integer, primary_key=True)
    org_id = Column(Integer, ForeignKey("organisations.id", ondelete="CASCADE"), nullable=False, index=True)
    code = Column(String(20), nullable=False)
    name = Column(String(200), nullable=False)
    account_type = Column(String(30), nullable=False)
    account_class = Column(String(20), nullable=False)
    description = Column(Text, nullable=True)
    default_tax_code_id = Column(Integer, ForeignKey("tax_codes.id", ondelete="SET NULL"), nullable=True)
    system_key = Column(String(40), nullable=True)      # ar_control, ap_control, gst, suspense, ...
    bank_name = Column(String(100), nullable=True)      # for bank accounts synced from legacy data
    bank_account_ref = Column(String(100), nullable=True)
    currency = Column(String(3), nullable=False, default="AUD")
    is_active = Column(Boolean, nullable=False, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    default_tax_code = relationship("TaxCode")

    __table_args__ = (
        UniqueConstraint("org_id", "code", name="uq_ledger_account_code"),
        UniqueConstraint("org_id", "name", name="uq_ledger_account_name"),
        Index("ix_ledger_account_system", "org_id", "system_key", unique=True,
              postgresql_where="system_key IS NOT NULL"),
        CheckConstraint(f"account_class IN {ACCOUNT_CLASSES}", name="ck_account_class"),
        CheckConstraint(f"account_type IN {tuple(ACCOUNT_TYPES)}", name="ck_account_type"),
    )


class TrackingCategory(Base):
    __tablename__ = "tracking_categories"

    id = Column(Integer, primary_key=True)
    org_id = Column(Integer, ForeignKey("organisations.id", ondelete="CASCADE"), nullable=False, index=True)
    name = Column(String(100), nullable=False)
    is_active = Column(Boolean, nullable=False, default=True)
    options = relationship("TrackingOption", back_populates="category", cascade="all, delete-orphan",
                           order_by="TrackingOption.name")

    __table_args__ = (UniqueConstraint("org_id", "name", name="uq_tracking_category"),)


class TrackingOption(Base):
    __tablename__ = "tracking_options"

    id = Column(Integer, primary_key=True)
    category_id = Column(Integer, ForeignKey("tracking_categories.id", ondelete="CASCADE"), nullable=False, index=True)
    name = Column(String(100), nullable=False)
    is_active = Column(Boolean, nullable=False, default=True)
    category = relationship("TrackingCategory", back_populates="options")

    __table_args__ = (UniqueConstraint("category_id", "name", name="uq_tracking_option"),)


class Journal(Base):
    __tablename__ = "journals"

    id = Column(Integer, primary_key=True)
    org_id = Column(Integer, ForeignKey("organisations.id", ondelete="RESTRICT"), nullable=False, index=True)
    journal_no = Column(Integer, nullable=False)
    journal_date = Column(Date, nullable=False, index=True)
    narration = Column(String(500), nullable=True)
    source_type = Column(String(40), nullable=False, default="manual")   # manual|bank_txn|reversal|opening_balance
    source_ref = Column(String(100), nullable=True)
    status = Column(String(20), nullable=False, default="posted")        # posted|reversed
    reversal_of_id = Column(Integer, ForeignKey("journals.id"), nullable=True)
    reversed_by_id = Column(Integer, ForeignKey("journals.id"), nullable=True)
    total = Column(MONEY, nullable=False, default=0)
    created_by = Column(Integer, nullable=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)

    lines = relationship("JournalLine", back_populates="journal", cascade="save-update, merge",
                         order_by="JournalLine.line_no", passive_deletes="all")

    __table_args__ = (
        UniqueConstraint("org_id", "journal_no", name="uq_journal_no"),
        CheckConstraint("status IN ('posted','reversed')", name="ck_journal_status"),
        Index("ix_journal_source", "org_id", "source_type", "source_ref"),
    )


class JournalLine(Base):
    __tablename__ = "journal_lines"

    id = Column(Integer, primary_key=True)
    journal_id = Column(Integer, ForeignKey("journals.id", ondelete="RESTRICT"), nullable=False, index=True)
    org_id = Column(Integer, nullable=False, index=True)
    line_no = Column(Integer, nullable=False)
    account_id = Column(Integer, ForeignKey("ledger_accounts.id", ondelete="RESTRICT"), nullable=False, index=True)
    description = Column(String(500), nullable=True)
    debit = Column(MONEY, nullable=False, default=0)
    credit = Column(MONEY, nullable=False, default=0)
    tax_code_id = Column(Integer, ForeignKey("tax_codes.id", ondelete="RESTRICT"), nullable=True)
    tax_amount = Column(MONEY, nullable=False, default=0)   # GST component carried for BAS
    tracking_option_ids = Column(JSON, nullable=True)
    contact_name = Column(String(255), nullable=True)

    journal = relationship("Journal", back_populates="lines")
    account = relationship("LedgerAccount")
    tax_code = relationship("TaxCode")

    __table_args__ = (
        CheckConstraint("debit >= 0 AND credit >= 0", name="ck_line_non_negative"),
        CheckConstraint("(debit = 0) <> (credit = 0)", name="ck_line_one_side"),
    )


class LedgerSourceLink(Base):
    """Links a legacy source record (e.g. a bank transaction) to the journal it produced,
    so syncs are idempotent and changed sources are reversed and re-posted."""
    __tablename__ = "ledger_source_links"

    id = Column(Integer, primary_key=True)
    org_id = Column(Integer, nullable=False, index=True)
    source_type = Column(String(40), nullable=False)
    source_id = Column(String(80), nullable=False)
    journal_id = Column(Integer, ForeignKey("journals.id"), nullable=True)
    fingerprint = Column(String(64), nullable=False)
    status = Column(String(20), nullable=False, default="posted")   # posted|skipped|locked
    note = Column(String(300), nullable=True)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    __table_args__ = (UniqueConstraint("org_id", "source_type", "source_id", name="uq_source_link"),)
