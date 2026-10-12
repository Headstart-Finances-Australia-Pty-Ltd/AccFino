"""Migration: chart_of_accounts + knowledge_base tables and the one-time import of their reference files (idempotent)."""
import csv
import json
import logging

from accfino.shared import paths

logger = logging.getLogger(__name__)

def _first_existing(paths_):
    return next((p for p in paths_ if p.exists()), None)


_COA_CANDIDATES = lambda: [paths.reference_file("ChartOfAccounts.csv")]
_KB_CANDIDATES = lambda: [paths.reference_file("knowledge_base.json")]


def run(engine):
    from sqlalchemy import text, inspect

    insp = inspect(engine)
    dialect = engine.dialect.name
    json_col = "JSON" if dialect != "sqlite" else "TEXT"
    id_col = {
        "postgresql": "id SERIAL PRIMARY KEY",
        "sqlite": "id INTEGER PRIMARY KEY AUTOINCREMENT",
    }.get(dialect, "id INT AUTO_INCREMENT PRIMARY KEY")

    # -- chart_of_accounts ----------------------------------------------------
    if not insp.has_table("chart_of_accounts"):
        with engine.begin() as conn:
            conn.execute(text(f"""
                CREATE TABLE chart_of_accounts (
                    {id_col},
                    name VARCHAR(300) NOT NULL UNIQUE,
                    type VARCHAR(100)
                )
            """))
        logger.info("Migration: created chart_of_accounts table")

    # Reconcile every startup, not just at table-creation -- a GL account
    # added to ChartOfAccounts.csv after the table already exists would
    # otherwise never reach Postgres once Postgres is authoritative.
    coa_path = _first_existing(_COA_CANDIDATES())
    if coa_path:
        imported = 0
        with engine.begin() as conn:
            with open(coa_path, newline="", encoding="utf-8-sig") as f:
                for row in csv.DictReader(f):
                    name = (row.get("*Name") or row.get("Name") or "").strip()
                    atype = (row.get("*Type") or row.get("Type") or "").strip()
                    if not name:
                        continue
                    existing = conn.execute(text("SELECT 1 FROM chart_of_accounts WHERE name = :n"), {"n": name}).first()
                    if existing:
                        continue
                    conn.execute(text("INSERT INTO chart_of_accounts (name, type) VALUES (:n, :t)"), {"n": name, "t": atype})
                    imported += 1
        if imported:
            logger.info(f"Migration: synced {imported} new chart-of-accounts row(s) from {coa_path}")

    # -- knowledge_base ---------------------------------------------------------
    if not insp.has_table("knowledge_base"):
        with engine.begin() as conn:
            conn.execute(text(f"CREATE TABLE knowledge_base ({id_col}, data {json_col} NOT NULL)"))
        logger.info("Migration: created knowledge_base table")

        kb_path = _first_existing(_KB_CANDIDATES())
        data = {}
        if kb_path:
            try:
                data = json.loads(kb_path.read_text(encoding="utf-8"))
            except Exception as e:
                logger.warning(f"Migration: could not parse {kb_path}: {e}")
        with engine.begin() as conn:
            conn.execute(text("INSERT INTO knowledge_base (id, data) VALUES (1, :d)"), {"d": json.dumps(data)})
        logger.info(f"Migration: seeded knowledge_base row 1 from {kb_path}")
