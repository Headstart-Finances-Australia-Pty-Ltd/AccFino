"""
accfino_core.migrate
--------------------
Idempotent Phase 0 migration. Safe to run on every startup.

  1. Create the new tables (organisations, ledger, audit, security).
  2. Install PostgreSQL integrity triggers:
       * audit_log is append-only
       * posted journal lines can never be updated or deleted
       * journals cannot be deleted; only status posted -> reversed may change
       * every journal must balance (deferred constraint trigger, checked at commit)
       * journal lines must use accounts of the same organisation
  3. Add owner_user_id to the legacy business_details table (tenant isolation fix).
  4. Backfill: one organisation per existing user, security rows, seeded COA and tax codes.
  5. Organisation Admin: every organisation gets exactly ONE owner (organisations.admin_user_id + a unique index), and users.email / users.phone
     are protected by a PostgreSQL trigger (a valid email and phone are mandatory for every account; existing incomplete accounts are left alone
     and asked to complete their profile at next sign-in).
"""
import logging
import secrets
from decimal import Decimal

from sqlalchemy import inspect, text

from accfino.core import models as m
from accfino.shared.contracts import registry

log = logging.getLogger("accfino.migrate")

NEW_TABLES = [
    m.Organisation.__table__, m.OrgMembership.__table__, m.UserSecurity.__table__,
    m.SystemSetting.__table__, m.AuditLog.__table__,
    m.WebAuthnCredential.__table__, m.MfaChallenge.__table__,
    m.UserSession.__table__, m.AccessPolicy.__table__,
]

# Columns added after the first Phase 0 build (ALTER is idempotent)
ADDED_COLUMNS_SQL = """
ALTER TABLE user_security ADD COLUMN IF NOT EXISTS phone_e164 VARCHAR(20);
ALTER TABLE user_security ADD COLUMN IF NOT EXISTS sms_mfa_enabled BOOLEAN NOT NULL DEFAULT FALSE;
ALTER TABLE user_security ADD COLUMN IF NOT EXISTS email_mfa_enabled BOOLEAN NOT NULL DEFAULT FALSE;
ALTER TABLE user_security ADD COLUMN IF NOT EXISTS disabled_at TIMESTAMP;
ALTER TABLE user_security ADD COLUMN IF NOT EXISTS disabled_reason VARCHAR(300);
ALTER TABLE user_security ADD COLUMN IF NOT EXISTS must_change_password BOOLEAN NOT NULL DEFAULT FALSE;
ALTER TABLE user_security ADD COLUMN IF NOT EXISTS email_verified_at TIMESTAMP;
ALTER TABLE user_security ADD COLUMN IF NOT EXISTS phone_verified_at TIMESTAMP;
ALTER TABLE org_memberships ADD COLUMN IF NOT EXISTS suspended_at TIMESTAMP;
ALTER TABLE org_memberships ADD COLUMN IF NOT EXISTS suspended_reason VARCHAR(300);
"""

# Organisation Admin: the one user who administers an organisation. Added BEFORE anything reads Organisation rows (the model now selects this column).
ORG_ADMIN_COLUMN_SQL = """
ALTER TABLE organisations ADD COLUMN IF NOT EXISTS admin_user_id INTEGER REFERENCES users(id) ON DELETE SET NULL;
CREATE INDEX IF NOT EXISTS ix_organisations_admin_user_id ON organisations (admin_user_id);
"""
# After sync_org_admins has left every organisation with at most one owner: the database itself now refuses a second one.
ONE_ADMIN_INDEX_SQL = "CREATE UNIQUE INDEX IF NOT EXISTS uq_org_one_owner ON org_memberships (org_id) WHERE role = 'owner';"

# A valid email and phone number are mandatory for every NEW user and for any CHANGE to them. Existing incomplete rows may still be updated for other
# reasons (password change, last login...) so nobody is locked out by the migration. Bootstrap code can lift it for one transaction with
# SET LOCAL accfino.allow_incomplete_contact = 'on' (see security.contact.allow_incomplete_contact). The app stores phones in E.164.
USER_CONTACT_TRIGGER_SQL = r"""
CREATE OR REPLACE FUNCTION accfino_user_contact_guard() RETURNS trigger AS $$
BEGIN
  IF COALESCE(current_setting('accfino.allow_incomplete_contact', true), '') = 'on' THEN
    RETURN NEW;
  END IF;
  IF TG_OP = 'INSERT' OR NEW.email IS DISTINCT FROM OLD.email THEN
    IF NEW.email IS NULL OR NEW.email !~ '^[^@\s]+@[^@\s]+\.[^@\s]{2,}$' THEN
      RAISE EXCEPTION 'accfino: a valid email address is required for every user' USING ERRCODE = 'check_violation';
    END IF;
  END IF;
  IF TG_OP = 'INSERT' OR NEW.phone IS DISTINCT FROM OLD.phone THEN
    IF NEW.phone IS NULL OR NEW.phone !~ '^\+[1-9][0-9]{7,14}$' THEN
      RAISE EXCEPTION 'accfino: a valid phone number (international format, e.g. +61412345678) is required for every user' USING ERRCODE = 'check_violation';
    END IF;
  END IF;
  RETURN NEW;
END; $$ LANGUAGE plpgsql;

-- Only created when missing: on every later start this changes nothing and takes no lock on "users"
-- (the function body above is refreshed by CREATE OR REPLACE, which does not lock the table).
DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_trigger WHERE tgname = 'trg_users_contact_guard' AND tgrelid = 'users'::regclass) THEN
    CREATE TRIGGER trg_users_contact_guard BEFORE INSERT OR UPDATE ON users
      FOR EACH ROW EXECUTE FUNCTION accfino_user_contact_guard();
  END IF;
END $$;
"""

# The AccFino platform administrator can NEVER be deleted - not from Users & Licence, Force delete, the database browser, or direct SQL.
# (admin@accfino.com / ADMIN_EMAIL, the username 'admin', and any user holding the legacy 'admin' role.) Built per start so ADMIN_EMAIL changes are picked up.
def platform_admin_protect_sql() -> str:
    from accfino.core.security import contact as _C
    email = _C.platform_admin_email().replace("'", "''")
    return f"""
CREATE OR REPLACE FUNCTION accfino_protect_platform_admin() RETURNS trigger AS $$
BEGIN
  IF lower(OLD.email) = '{email}' OR lower(OLD.username) = 'admin'
     OR EXISTS (SELECT 1 FROM user_roles ur JOIN roles r ON r.id = ur.role_id WHERE ur.user_id = OLD.id AND r.name = 'admin') THEN
    RAISE EXCEPTION 'accfino: the platform administrator account cannot be deleted' USING ERRCODE = 'restrict_violation';
  END IF;
  RETURN OLD;
END; $$ LANGUAGE plpgsql;

DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_trigger WHERE tgname = 'trg_users_protect_admin' AND tgrelid = 'users'::regclass) THEN
    CREATE TRIGGER trg_users_protect_admin BEFORE DELETE ON users
      FOR EACH ROW EXECUTE FUNCTION accfino_protect_platform_admin();
  END IF;
END $$;
"""


TRIGGERS_SQL = r"""
CREATE OR REPLACE FUNCTION accfino_block_change() RETURNS trigger AS $$
BEGIN
  RAISE EXCEPTION 'accfino: % on % is not permitted (immutable record)', TG_OP, TG_TABLE_NAME
    USING ERRCODE = 'check_violation';
END; $$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trg_audit_log_immutable ON audit_log;
CREATE TRIGGER trg_audit_log_immutable BEFORE UPDATE OR DELETE ON audit_log
  FOR EACH ROW EXECUTE FUNCTION accfino_block_change();
"""


# ------------------------------------------------------------------ helpers --
def get_or_create_setting(db, key: str, factory):
    row = db.get(m.SystemSetting, key)
    if row is None:
        row = m.SystemSetting(key=key, value=factory())
        db.add(row)
        db.commit()
    return row.value


def ensure_personal_org(db, user) -> "m.Organisation":
    """Every user gets a default organisation that owns their existing data."""
    mem = (db.query(m.OrgMembership)
           .filter_by(user_id=user.id, is_default=True).first()
           or db.query(m.OrgMembership).filter_by(user_id=user.id).first())
    if mem:
        return db.get(m.Organisation, mem.org_id)
    name = (getattr(user, "home_company", None) or "").strip() or \
        f"{(user.full_name or user.username)}'s organisation"
    org = m.Organisation(name=name[:255], legacy_user_id=user.id)
    db.add(org)
    db.flush()
    db.add(m.OrgMembership(org_id=org.id, user_id=user.id, role="owner", is_default=True))
    org.admin_user_id = user.id                                       # the user whose organisation this is IS its Organisation Admin
    registry.provision_org(db, org)                                   # each module provisions what it needs (Accounting: chart of accounts + tax codes)
    return org


def ensure_user_security(db, user_id: int) -> "m.UserSecurity":
    sec = db.get(m.UserSecurity, user_id)
    if sec is None:
        sec = m.UserSecurity(user_id=user_id)
        db.add(sec)
        db.flush()
    return sec


# ---------------------------------------------------------------------- run --
def _ensure_org_admin_column(engine) -> None:
    """create_all never adds a column to an existing table: add organisations.admin_user_id to databases that predate it."""
    try:
        with engine.begin() as conn:
            if engine.dialect.name == "postgresql":
                conn.execute(text(ORG_ADMIN_COLUMN_SQL))
            elif "admin_user_id" not in {c["name"] for c in inspect(conn).get_columns("organisations")}:
                conn.execute(text("ALTER TABLE organisations ADD COLUMN admin_user_id INTEGER REFERENCES users(id) ON DELETE SET NULL"))
    except Exception as e:
        log.error("migrate: could not add organisations.admin_user_id: %s", e)
        raise


def _ensure_member_role_constraint(conn) -> None:
    """create_all never alters an existing CHECK constraint: widen ck_org_member_role to the current ORG_ROLES (idempotent; PostgreSQL)."""
    roles = ", ".join(f"'{r}'" for r in m.ORG_ROLES)
    row = conn.execute(text("SELECT pg_get_constraintdef(oid) FROM pg_constraint WHERE conname = 'ck_org_member_role'")).fetchone()
    if row and all(f"'{r}'" in row[0] for r in m.ORG_ROLES):
        return
    conn.execute(text("ALTER TABLE org_memberships DROP CONSTRAINT IF EXISTS ck_org_member_role"))
    conn.execute(text(f"ALTER TABLE org_memberships ADD CONSTRAINT ck_org_member_role CHECK (role IN ({roles}))"))


def run(engine, SessionLocal) -> None:
    """Called from db_app.init_db on every start. Never raises for already-applied steps."""
    from accfino.core.subscription.models import SUBSCRIPTION_TABLES
    from accfino.core.tenancy.models import TENANCY_TABLES
    registry.load_all()
    registry.import_all_models()
    registry.run_pre_schema(engine)
    m.Base.metadata.create_all(bind=engine, tables=NEW_TABLES + SUBSCRIPTION_TABLES + TENANCY_TABLES + registry.schema_tables())
    _ensure_org_admin_column(engine)
    try:                                          # organisations created before tenant URLs get a URL name
        from sqlalchemy.orm import Session as _S
        from accfino.core.tenancy.service import backfill_profiles
        with _S(engine) as _db:
            if backfill_profiles(_db):
                _db.commit()
    except Exception as e:
        log.error("tenant profile backfill could not run: %s", e)

    if engine.dialect.name == "postgresql":
        with engine.begin() as conn:
            conn.execute(text(TRIGGERS_SQL))
            conn.execute(text(ADDED_COLUMNS_SQL))
            _ensure_member_role_constraint(conn)
            registry.run_pg_schema(conn)                      # modules add their own triggers / columns (Accounting: ledger immutability, FX columns, ...)
    else:
        log.warning("migrate: non-PostgreSQL database; integrity triggers not installed")

    try:                                           # one price list: legacy plan table mirrors the organisation plans, old plans are retired, the administrator has the top plan
        from sqlalchemy.orm import Session as _S2
        from accfino.core.subscription.align import run_alignment
        with _S2(engine) as _adb:
            run_alignment(_adb)
            _adb.commit()
    except Exception as e:
        log.warning("plan alignment skipped: %s", e)

    # Signing up used to create a per-user "base plan" licence record (Dashboard + Reconciliation only). Licensing is per organisation now
    # (plans by business domain), so remove those auto-created records - only ones nobody has edited (default module list + default note).
    try:
        with engine.begin() as conn:
            if inspect(conn).has_table("licence_records"):
                n = conn.execute(text("DELETE FROM licence_records WHERE notes LIKE 'Auto-created on organisation signup%' "
                                      "AND (modules IS NULL OR modules = '' OR modules = '[\"dashboard\", \"reconciliation\"]')")).rowcount
                if n:
                    log.info("migrate: removed %s auto-created per-user licence record(s)", n)
    except Exception as e:
        log.warning("auto-created licence clean-up skipped: %s", e)

    registry.run_post_schema(engine)                          # modules' data migrations (Accounting: exact NUMERIC money columns, ...)

    from accfino.core.identity.user import User
    db = SessionLocal()
    try:
        get_or_create_setting(db, "jwt_secret", lambda: secrets.token_urlsafe(48))
        created = 0
        for user in db.query(User).order_by(User.id).all():
            ensure_user_security(db, user.id)
            had = db.query(m.OrgMembership).filter_by(user_id=user.id).first()
            ensure_personal_org(db, user)
            if not had:
                created += 1
        db.commit()
        if created:
            log.info("migrate: created %s organisation(s) for existing users", created)
        # top up every organisation with any standard accounts / tax codes added since it was created (idempotent)
        for org in db.query(m.Organisation).all():
            registry.provision_org(db, org)
        db.commit()
        # One Organisation Admin per organisation: normalise existing data, THEN let the database enforce it
        from accfino.core.identity.org_admin import sync_org_admins
        fixed = sync_org_admins(db)
        db.commit()
        if any(fixed.values()):
            log.warning("migrate: organisation admins normalised: %s", fixed)
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()

    if engine.dialect.name == "postgresql":
        for label, sql in (("one Organisation Admin per organisation", ONE_ADMIN_INDEX_SQL), ("mandatory user email and phone", USER_CONTACT_TRIGGER_SQL), ("platform administrator cannot be deleted", platform_admin_protect_sql())):
            try:                                      # a failure here is logged loudly but must never stop the application starting
                with engine.begin() as conn:
                    conn.execute(text("SET LOCAL lock_timeout = '10s'"))      # never wait forever for a lock at startup
                    conn.execute(text(sql))
            except Exception as e:
                log.error("migrate: could not install '%s' database protection: %s", label, e)
