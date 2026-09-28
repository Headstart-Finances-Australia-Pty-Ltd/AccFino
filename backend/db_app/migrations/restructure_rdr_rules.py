"""
Migration: restructure rdr_rules from a single `if_condition` JSON blob
column into real per-field columns (contains_any, regex_any, debit_gt,
credit_gt, debit_only, credit_only).

Runs from react_api.py's startup hook -- idempotent, safe on every boot.
Fully supersedes db_app/migrations/migrate_rdr_rules.py (which created
the table with the old `if_condition` blob shape) -- that file's logic
has been folded in here so there's one migration owning this table, not
two managing different schemas for it.
"""
import json
import logging
from pathlib import Path

logger = logging.getLogger(__name__)

_ROOT = Path(__file__).resolve().parents[2]
_RDR_CANDIDATES = [
    _ROOT / "main_app" / "data" / "rdr_rules.json",
    _ROOT / "data" / "rdr_rules.json",
    _ROOT / "rdr_rules.json",
]


def _first_existing(paths):
    for p in paths:
        if p.exists():
            return p
    return None


_NEW_COLUMNS = {
    "keywords": "TEXT",
    "regex_any": "JSON",
    "debit_gt": "FLOAT",
    "credit_gt": "FLOAT",
    "debit_only": "BOOLEAN DEFAULT FALSE",
    "credit_only": "BOOLEAN DEFAULT FALSE",
}


def run(engine):
    from sqlalchemy import text, inspect

    insp = inspect(engine)

    if not insp.has_table("rdr_rules"):
        with engine.begin() as conn:
            cols_sql = ",\n".join(f"{name} {sqltype}" for name, sqltype in _NEW_COLUMNS.items())
            conn.execute(text(f"""
                CREATE TABLE rdr_rules (
                    id VARCHAR(64) PRIMARY KEY,
                    name VARCHAR(200),
                    priority INTEGER NOT NULL DEFAULT 100,
                    {cols_sql},
                    "then" VARCHAR(200),
                    then_gst_category VARCHAR(100),
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """))
        logger.info("Migration: created rdr_rules table (new column shape)")
    else:
        existing_cols = {c["name"] for c in insp.get_columns("rdr_rules")}
        had_old_blob = "if_condition" in existing_cols
        had_old_contains_any = "contains_any" in existing_cols
        with engine.begin() as conn:
            for name, sqltype in _NEW_COLUMNS.items():
                if name not in existing_cols:
                    conn.execute(text(f"ALTER TABLE rdr_rules ADD COLUMN {name} {sqltype}"))

            if had_old_blob:
                logger.info("Migration: rdr_rules has old `if_condition` blob column -- backfilling new columns from it")
                rows = conn.execute(text("SELECT id, if_condition FROM rdr_rules")).fetchall()
                for rule_id, cond in rows:
                    cond = cond or {}
                    kws = cond.get("contains_any", []) or []
                    conn.execute(text("""
                        UPDATE rdr_rules SET
                            keywords = :keywords, regex_any = :regex_any,
                            debit_gt = :debit_gt, credit_gt = :credit_gt,
                            debit_only = :debit_only, credit_only = :credit_only
                        WHERE id = :id
                    """), {
                        "id": rule_id,
                        "keywords": "|".join(str(k).strip() for k in kws if str(k).strip()) or None,
                        "regex_any": json.dumps(cond.get("regex_any", [])),
                        "debit_gt": cond.get("debit_gt"),
                        "credit_gt": cond.get("credit_gt"),
                        "debit_only": bool(cond.get("debit_only", False)),
                        "credit_only": bool(cond.get("credit_only", False)),
                    })
                conn.execute(text("ALTER TABLE rdr_rules DROP COLUMN if_condition"))
                logger.info(f"Migration: backfilled {len(rows)} rdr_rules row(s) into new columns, dropped old if_condition column")

            elif had_old_contains_any:
                # Table already had the first-round split (contains_any as
                # a JSON array column) -- convert that array into the
                # pipe-delimited keywords column and drop contains_any.
                logger.info("Migration: rdr_rules has old `contains_any` JSON array column -- converting to pipe-delimited `keywords`")
                rows = conn.execute(text("SELECT id, contains_any FROM rdr_rules")).fetchall()
                for rule_id, kws in rows:
                    kws = kws or []
                    conn.execute(text("UPDATE rdr_rules SET keywords = :keywords WHERE id = :id"), {
                        "id": rule_id,
                        "keywords": "|".join(str(k).strip() for k in kws if str(k).strip()) or None,
                    })
                conn.execute(text("ALTER TABLE rdr_rules DROP COLUMN contains_any"))
                logger.info(f"Migration: converted {len(rows)} rdr_rules row(s) from contains_any array to keywords text, dropped contains_any column")

    # Reconcile from rdr_rules.json every run (same self-healing pattern
    # as pricing_plans/chart_of_accounts) -- a rule added to the JSON file
    # after this migration already ran still needs to reach Postgres.
    rdr_path = _first_existing(_RDR_CANDIDATES)
    if not rdr_path:
        return
    try:
        rules = json.loads(rdr_path.read_text(encoding="utf-8"))
    except Exception as e:
        logger.warning(f"Migration: could not parse {rdr_path}: {e}")
        return
    if not isinstance(rules, list):
        return

    synced = 0
    with engine.begin() as conn:
        for rule in rules:
            rule_id = rule.get("id")
            if not rule_id:
                continue
            existing = conn.execute(text("SELECT 1 FROM rdr_rules WHERE id = :id"), {"id": rule_id}).first()
            if existing:
                continue  # don't overwrite admin edits made directly in Postgres
            cond = rule.get("if", {}) or {}
            kws = cond.get("contains_any", []) or []
            conn.execute(text("""
                INSERT INTO rdr_rules
                    (id, name, priority, keywords, regex_any, debit_gt, credit_gt,
                     debit_only, credit_only, "then", then_gst_category)
                VALUES
                    (:id, :name, :priority, :keywords, :regex_any, :debit_gt, :credit_gt,
                     :debit_only, :credit_only, :then, :then_gst_category)
            """), {
                "id": rule_id,
                "name": rule.get("name"),
                "priority": int(rule.get("priority", 100) or 100),
                "keywords": "|".join(str(k).strip() for k in kws if str(k).strip()) or None,
                "regex_any": json.dumps(cond.get("regex_any", [])),
                "debit_gt": cond.get("debit_gt"),
                "credit_gt": cond.get("credit_gt"),
                "debit_only": bool(cond.get("debit_only", False)),
                "credit_only": bool(cond.get("credit_only", False)),
                "then": rule.get("then"),
                "then_gst_category": rule.get("then_gst_category"),
            })
            synced += 1
    if synced:
        logger.info(f"Migration: synced {synced} missing rdr rule(s) from {rdr_path} into Postgres")
