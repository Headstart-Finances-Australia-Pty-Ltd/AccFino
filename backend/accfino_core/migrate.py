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
ALTER TABLE org_memberships ADD COLUMN IF NOT EXISTS suspended_at TIMESTAMP;
ALTER TABLE org_memberships ADD COLUMN IF NOT EXISTS suspended_reason VARCHAR(300);
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
def run(engine, SessionLocal) -> None:
    """Called from db_app.init_db on every start. Never raises for already-applied steps."""
    m.Base.metadata.create_all(bind=engine, tables=NEW_TABLES, checkfirst=True)

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
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()
