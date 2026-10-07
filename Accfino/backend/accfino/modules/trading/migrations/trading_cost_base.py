"""Migration: trading_cost_base table + one-time import of the cost-base file (idempotent)."""
import json
import logging

from accfino.shared import paths

logger = logging.getLogger(__name__)

def _first_existing(paths_):
    return next((p for p in paths_ if p.exists()), None)


_COST_BASE_CANDIDATES = lambda: [paths.module_dir("trading", "cost_base") / "local_cost_base_db.json"]


def run(engine):
    from sqlalchemy import text, inspect

    insp = inspect(engine)
    dialect = engine.dialect.name
    json_col = "JSON" if dialect != "sqlite" else "TEXT"
    id_col = {
        "postgresql": "id SERIAL PRIMARY KEY",
        "sqlite": "id INTEGER PRIMARY KEY AUTOINCREMENT",
    }.get(dialect, "id INT AUTO_INCREMENT PRIMARY KEY")

    # -- trading_cost_base -----------------------------------------------------
    if not insp.has_table("trading_cost_base"):
        with engine.begin() as conn:
            conn.execute(text(f"CREATE TABLE trading_cost_base ({id_col}, data {json_col} NOT NULL)"))
        logger.info("Migration: created trading_cost_base table")

        cb_path = _first_existing(_COST_BASE_CANDIDATES())
        data = {"version": "1.0", "historical_lots": [], "resolution_log": []}
        if cb_path:
            try:
                data = json.loads(cb_path.read_text(encoding="utf-8"))
            except Exception as e:
                logger.warning(f"Migration: could not parse {cb_path}: {e}")
        with engine.begin() as conn:
            conn.execute(text("INSERT INTO trading_cost_base (id, data) VALUES (1, :d)"), {"d": json.dumps(data)})
        logger.info(f"Migration: seeded trading_cost_base row 1 from {cb_path}")
