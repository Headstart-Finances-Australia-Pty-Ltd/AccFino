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

from accfino_core import models as m
from accfino_core.coa.au_standard import ACCOUNTS, LEGACY_TYPE_MAP, TAX_CODES

log = logging.getLogger("accfino.migrate")

NEW_TABLES = [
    m.Organisation.__table__, m.OrgMembership.__table__, m.UserSecurity.__table__,
    m.SystemSetting.__table__, m.AuditLog.__table__, m.TaxCode.__table__,
    m.LedgerAccount.__table__, m.TrackingCategory.__table__, m.TrackingOption.__table__,
    m.Journal.__table__, m.JournalLine.__table__, m.LedgerSourceLink.__table__,
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
ALTER TABLE journals ADD COLUMN IF NOT EXISTS reference VARCHAR(100);
ALTER TABLE journals ADD COLUMN IF NOT EXISTS currency VARCHAR(3);
ALTER TABLE ledger_accounts ADD COLUMN IF NOT EXISTS foreign_currency VARCHAR(3);
ALTER TABLE journals ADD COLUMN IF NOT EXISTS exchange_rate NUMERIC(18,8);
ALTER TABLE journal_lines ADD COLUMN IF NOT EXISTS orig_debit NUMERIC(18,2);
ALTER TABLE journal_lines ADD COLUMN IF NOT EXISTS orig_credit NUMERIC(18,2);
ALTER TABLE ledger_journal_drafts ADD COLUMN IF NOT EXISTS currency VARCHAR(3);
ALTER TABLE ledger_journal_drafts ADD COLUMN IF NOT EXISTS exchange_rate NUMERIC(18,8);
ALTER TABLE ledger_repeating_journals ADD COLUMN IF NOT EXISTS currency VARCHAR(3);
ALTER TABLE ledger_repeating_journals ADD COLUMN IF NOT EXISTS auto_run BOOLEAN NOT NULL DEFAULT FALSE;
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
    from accfino_core.security import contact as _C
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

DROP TRIGGER IF EXISTS trg_journal_lines_immutable ON journal_lines;
CREATE TRIGGER trg_journal_lines_immutable BEFORE UPDATE OR DELETE ON journal_lines
  FOR EACH ROW EXECUTE FUNCTION accfino_block_change();

CREATE OR REPLACE FUNCTION accfino_journal_guard() RETURNS trigger AS $$
BEGIN
  IF TG_OP = 'DELETE' THEN
    RAISE EXCEPTION 'accfino: journals cannot be deleted; post a reversal instead'
      USING ERRCODE = 'check_violation';
  END IF;
  IF NEW.org_id <> OLD.org_id OR NEW.journal_no <> OLD.journal_no
     OR NEW.journal_date <> OLD.journal_date OR NEW.total <> OLD.total
     OR NEW.source_type <> OLD.source_type
     OR COALESCE(NEW.source_ref,'') <> COALESCE(OLD.source_ref,'')
     OR COALESCE(NEW.reversal_of_id,0) <> COALESCE(OLD.reversal_of_id,0) THEN
    RAISE EXCEPTION 'accfino: posted journal % is immutable', OLD.id
      USING ERRCODE = 'check_violation';
  END IF;
  IF NOT (OLD.status = 'posted' AND NEW.status IN ('posted','reversed')) THEN
    RAISE EXCEPTION 'accfino: invalid journal status change % -> %', OLD.status, NEW.status
      USING ERRCODE = 'check_violation';
  END IF;
  RETURN NEW;
END; $$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trg_journal_guard ON journals;
CREATE TRIGGER trg_journal_guard BEFORE UPDATE OR DELETE ON journals
  FOR EACH ROW EXECUTE FUNCTION accfino_journal_guard();

CREATE OR REPLACE FUNCTION accfino_journal_balanced() RETURNS trigger AS $$
DECLARE
  d NUMERIC; c NUMERIC; n INTEGER; bad INTEGER; jorg INTEGER; jtotal NUMERIC;
BEGIN
  SELECT org_id, total INTO jorg, jtotal FROM journals WHERE id = NEW.journal_id;
  SELECT COALESCE(SUM(debit),0), COALESCE(SUM(credit),0), COUNT(*)
    INTO d, c, n FROM journal_lines WHERE journal_id = NEW.journal_id;
  IF n < 2 THEN
    RAISE EXCEPTION 'accfino: journal % needs at least two lines', NEW.journal_id USING ERRCODE = 'check_violation';
  END IF;
  IF d <> c THEN
    RAISE EXCEPTION 'accfino: journal % does not balance (debits %, credits %)', NEW.journal_id, d, c
      USING ERRCODE = 'check_violation';
  END IF;
  IF d <> jtotal THEN
    RAISE EXCEPTION 'accfino: journal % total % does not match lines %', NEW.journal_id, jtotal, d
      USING ERRCODE = 'check_violation';
  END IF;
  SELECT COUNT(*) INTO bad FROM journal_lines l JOIN ledger_accounts a ON a.id = l.account_id
    WHERE l.journal_id = NEW.journal_id AND (a.org_id <> jorg OR l.org_id <> jorg);
  IF bad > 0 THEN
    RAISE EXCEPTION 'accfino: journal % uses accounts from another organisation', NEW.journal_id
      USING ERRCODE = 'check_violation';
  END IF;
  RETURN NULL;
END; $$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trg_journal_balanced ON journal_lines;
CREATE CONSTRAINT TRIGGER trg_journal_balanced AFTER INSERT ON journal_lines
  DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION accfino_journal_balanced();
"""


# ------------------------------------------------------------------ helpers --
def get_or_create_setting(db, key: str, factory):
    row = db.get(m.SystemSetting, key)
    if row is None:
        row = m.SystemSetting(key=key, value=factory())
        db.add(row)
        db.commit()
    return row.value


def seed_org_ledger(db, org: "m.Organisation") -> None:
    """Seed tax codes and the AU standard COA for an organisation (idempotent)."""
    existing_tax = {t.name: t for t in db.query(m.TaxCode).filter_by(org_id=org.id)}
    for code, name, rate, applies, labels in TAX_CODES:
        if name not in existing_tax:
            t = m.TaxCode(org_id=org.id, code=code, name=name, rate=Decimal(rate),
                          applies_to=applies, bas_labels=labels, is_system=True)
            db.add(t)
            existing_tax[name] = t
    db.flush()

    existing = {a.name.lower(): a for a in db.query(m.LedgerAccount).filter_by(org_id=org.id)}
    codes = {a.code for a in existing.values()}
    for code, name, atype, tax_name, sys_key in ACCOUNTS:
        if name.lower() in existing or code in codes:
            continue
        acc = m.LedgerAccount(
            org_id=org.id, code=code, name=name, account_type=atype,
            account_class=m.ACCOUNT_TYPES[atype],
            default_tax_code_id=existing_tax[tax_name].id if tax_name in existing_tax else None,
            system_key=sys_key,
        )
        db.add(acc)
        existing[name.lower()] = acc
        codes.add(code)
    db.flush()

    # Accounts users previously added to the legacy (global) chart_of_accounts table
    try:
        legacy = db.execute(text("SELECT name, type FROM chart_of_accounts")).fetchall()
    except Exception:
        db.rollback()
        legacy = []
    n = 1
    for name, ltype in legacy:
        if not name or name.lower() in existing:
            continue
        atype = LEGACY_TYPE_MAP.get((ltype or "").strip().lower(), "expense")
        while f"U{n:03d}" in codes:
            n += 1
        code = f"U{n:03d}"
        acc = m.LedgerAccount(org_id=org.id, code=code, name=name[:200], account_type=atype,
                              account_class=m.ACCOUNT_TYPES[atype],
                              description="Imported from legacy chart of accounts")
        db.add(acc)
        existing[name.lower()] = acc
        codes.add(code)
    db.flush()


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
    seed_org_ledger(db, org)
    return org


def ensure_user_security(db, user_id: int) -> "m.UserSecurity":
    sec = db.get(m.UserSecurity, user_id)
    if sec is None:
        sec = m.UserSecurity(user_id=user_id)
        db.add(sec)
        db.flush()
    return sec


# ---------------------------------------------------------------------- run --
def _drop_stale_tables(engine, expected_org_scoped: list[str]) -> None:
    """create_all(checkfirst=True) only creates tables that don't exist yet - it never adds a
    column to a table that's already there. If any of these tables exists from an older,
    incompatible version of the code (missing org_id, the column every query here filters on),
    leaving it in place means every request against it fails forever with UndefinedColumn. These
    tables are new (Phase 1/3) and, wherever this happens, empty or from an abandoned attempt, so
    it's always safe to drop and let create_all recreate them with the current schema right after."""
    if engine.dialect.name != "postgresql":
        return
    with engine.begin() as conn:
        insp = inspect(conn)
        stale = [t for t in expected_org_scoped if insp.has_table(t) and "org_id" not in {c["name"] for c in insp.get_columns(t)}]
        for t in stale:
            conn.execute(text(f'DROP TABLE "{t}" CASCADE'))
            log.warning(f"migrate: dropped stale table '{t}' (created by an older schema with no org_id) so it can be recreated correctly")


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


def run(engine, SessionLocal) -> None:
    """Called from db_app.init_db on every start. Never raises for already-applied steps."""
    from accfino_core.books.models import BOOKS_TABLES
    from accfino_core.assets.models import ASSETS_TABLES
    from accfino_core.inventory.models import INVENTORY_TABLES
    from accfino_core.ledger.journal_models import JOURNAL_TABLES
    from accfino_core.subscription.models import SUBSCRIPTION_TABLES
    from accfino_core.tenancy.models import TENANCY_TABLES
    from accfino_core.openfeed_cdr import OPENFEED_TABLES
    from accfino_core.billing.models import BILLING_TABLES
    _drop_stale_tables(engine, ["stock_items", "stock_movements", "fixed_assets", "asset_depreciation_runs"])
    m.Base.metadata.create_all(bind=engine, tables=NEW_TABLES + BOOKS_TABLES + ASSETS_TABLES + INVENTORY_TABLES + JOURNAL_TABLES + SUBSCRIPTION_TABLES + TENANCY_TABLES + OPENFEED_TABLES + BILLING_TABLES, checkfirst=True)
    _ensure_org_admin_column(engine)
    try:                                          # organisations created before tenant URLs get a URL name
        from sqlalchemy.orm import Session as _S
        from accfino_core.tenancy.service import backfill_profiles
        with _S(engine) as _db:
            if backfill_profiles(_db):
                _db.commit()
    except Exception as e:
        log.error("tenant profile backfill could not run: %s", e)

    if engine.dialect.name == "postgresql":
        with engine.begin() as conn:
            conn.execute(text(TRIGGERS_SQL))
            conn.execute(text(ADDED_COLUMNS_SQL))
            cols = [c["name"] for c in inspect(conn).get_columns("business_details")] \
                if inspect(conn).has_table("business_details") else []
            if cols and "owner_user_id" not in cols:
                conn.execute(text("ALTER TABLE business_details ADD COLUMN owner_user_id INTEGER"))
                log.info("migrate: added business_details.owner_user_id")
    else:
        log.warning("migrate: non-PostgreSQL database; integrity triggers not installed")

    try:                                           # one price list: legacy plan table mirrors the organisation plans, old plans are retired, the administrator has the top plan
        from sqlalchemy.orm import Session as _S2
        from accfino_core.subscription.align import run_alignment
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

    # A1: exact NUMERIC money columns (no-op on a fresh database; converts + reconciles an existing one)
    try:
        from accfino_core.books import money_migration
        money_migration.run(engine)
    except Exception as e:                       # never stop the app from starting; the admin report shows what is pending
        log.error("money migration could not run: %s", e)

    from db_app.models.user import User
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
            seed_org_ledger(db, org)
        db.commit()
        # One Organisation Admin per organisation: normalise existing data, THEN let the database enforce it
        from accfino_core.org_admin import sync_org_admins
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
