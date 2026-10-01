"""
Migration: create chart_of_accounts, knowledge_base, lending_classifications,
pricing_plans, trading_cost_base tables + one-time import of their legacy
file-based data. Called from react_api.py's startup hook -- idempotent.
"""
import csv
import json
import logging
from pathlib import Path

logger = logging.getLogger(__name__)

_ROOT = Path(__file__).resolve().parents[2]  # AccFino-main/
_COA_CANDIDATES = [_ROOT / "main_app" / "data" / "ChartOfAccounts.csv", _ROOT / "data" / "ChartOfAccounts.csv"]
_KB_CANDIDATES = [_ROOT / "main_app" / "data" / "knowledge_base.json", _ROOT / "data" / "knowledge_base.json"]
_LENDING_CANDIDATES = [_ROOT / "main_app" / "data" / "lending_classifications.json"]
_PRICING_CANDIDATES = [_ROOT / "main_app" / "data" / "pricing.json"]
_COST_BASE_CANDIDATES = [_ROOT / "main_app" / "backend" / "trading" / "data" / "local_cost_base_db.json"]


def _first_existing(paths):
    return next((p for p in paths if p.exists()), None)


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
    coa_path = _first_existing(_COA_CANDIDATES)
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

        kb_path = _first_existing(_KB_CANDIDATES)
        data = {}
        if kb_path:
            try:
                data = json.loads(kb_path.read_text(encoding="utf-8"))
            except Exception as e:
                logger.warning(f"Migration: could not parse {kb_path}: {e}")
        with engine.begin() as conn:
            conn.execute(text("INSERT INTO knowledge_base (id, data) VALUES (1, :d)"), {"d": json.dumps(data)})
        logger.info(f"Migration: seeded knowledge_base row 1 from {kb_path}")

    # -- lending_classifications --------------------------------------------
    if not insp.has_table("lending_classifications"):
        with engine.begin() as conn:
            conn.execute(text(f"""
                CREATE TABLE lending_classifications (
                    {id_col},
                    keyword VARCHAR(300) NOT NULL,
                    category VARCHAR(100),
                    exp_type VARCHAR(10),
                    in_or_out VARCHAR(10),
                    weight INTEGER DEFAULT 0,
                    source VARCHAR(50)
                )
            """))
            conn.execute(text("CREATE INDEX idx_lending_keyword ON lending_classifications(keyword)"))
        logger.info("Migration: created lending_classifications table")

    # Reconcile every startup, not just at table-creation -- same
    # dedup-by-content approach as the other sections above, since this
    # table has no natural unique column to key off (keyword can repeat
    # with different categories).
    lending_path = _first_existing(_LENDING_CANDIDATES)
    if lending_path:
        try:
            rows = json.loads(lending_path.read_text(encoding="utf-8"))
        except Exception as e:
            rows = []
            logger.warning(f"Migration: could not parse {lending_path}: {e}")
        imported = 0
        with engine.begin() as conn:
            for r in rows:
                keyword = r.get("keyword", "")
                category = r.get("category")
                existing = conn.execute(
                    text("SELECT 1 FROM lending_classifications WHERE keyword = :k AND category IS NOT DISTINCT FROM :c"),
                    {"k": keyword, "c": category},
                ).first()
                if existing:
                    continue
                conn.execute(text("""
                    INSERT INTO lending_classifications (keyword, category, exp_type, in_or_out, weight, source)
                    VALUES (:keyword, :category, :exp_type, :in_or_out, :weight, :source)
                """), {
                    "keyword": keyword, "category": category,
                    "exp_type": r.get("exp_type"), "in_or_out": r.get("in_or_out"),
                    "weight": int(r.get("weight", 0) or 0), "source": r.get("source"),
                })
                imported += 1
        if imported:
            logger.info(f"Migration: synced {imported} new lending classification row(s) from {lending_path}")

    # pricing_plans is now handled entirely by
    # db_app/migrations/restructure_pricing_plans.py (real columns instead
    # of one JSON blob) -- removed from here to avoid two migrations
    # managing the same table with two different schemas.

    # -- trading_cost_base -----------------------------------------------------
    if not insp.has_table("trading_cost_base"):
        with engine.begin() as conn:
            conn.execute(text(f"CREATE TABLE trading_cost_base ({id_col}, data {json_col} NOT NULL)"))
        logger.info("Migration: created trading_cost_base table")

        cb_path = _first_existing(_COST_BASE_CANDIDATES)
        data = {"version": "1.0", "historical_lots": [], "resolution_log": []}
        if cb_path:
            try:
                data = json.loads(cb_path.read_text(encoding="utf-8"))
            except Exception as e:
                logger.warning(f"Migration: could not parse {cb_path}: {e}")
        with engine.begin() as conn:
            conn.execute(text("INSERT INTO trading_cost_base (id, data) VALUES (1, :d)"), {"d": json.dumps(data)})
        logger.info(f"Migration: seeded trading_cost_base row 1 from {cb_path}")
