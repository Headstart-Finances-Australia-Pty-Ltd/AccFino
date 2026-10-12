"""
accfino.modules.accounting.migrations.ledger_schema
---------------------------------------------------
PostgreSQL integrity triggers and added columns for the double-entry ledger (moved verbatim out of core.migrate).
Registered through the accounting manifest and executed by Core's platform migration inside the same transaction.
"""
import logging

from sqlalchemy import inspect, text

log = logging.getLogger("accfino.migrate")

TRIGGERS_SQL = r"""
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

ADDED_COLUMNS_SQL = """
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


def pg_schema(conn) -> None:
    """Ledger triggers (needs accfino_block_change() from the Core triggers), ledger columns, legacy invoice owner column."""
    conn.execute(text(TRIGGERS_SQL))
    conn.execute(text(ADDED_COLUMNS_SQL))
    cols = [c["name"] for c in inspect(conn).get_columns("business_details")] \
        if inspect(conn).has_table("business_details") else []
    if cols and "owner_user_id" not in cols:
        conn.execute(text("ALTER TABLE business_details ADD COLUMN owner_user_id INTEGER"))
        log.info("migrate: added business_details.owner_user_id")


def drop_stale_tables(engine, expected_org_scoped: list[str]) -> None:
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


def pre_schema(engine) -> None:
    drop_stale_tables(engine, ["stock_items", "stock_movements", "fixed_assets", "asset_depreciation_runs"])
