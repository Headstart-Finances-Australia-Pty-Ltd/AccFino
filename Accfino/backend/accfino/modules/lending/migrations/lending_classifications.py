"""Migration: lending_classifications table and its keyword rules (idempotent)."""
import json
import logging

from accfino.shared import paths

logger = logging.getLogger(__name__)

def _first_existing(paths_):
    return next((p for p in paths_ if p.exists()), None)


_LENDING_CANDIDATES = lambda: [paths.reference_file("lending_classifications.json")]


def run(engine):
    from sqlalchemy import text, inspect

    insp = inspect(engine)
    dialect = engine.dialect.name
    json_col = "JSON" if dialect != "sqlite" else "TEXT"
    id_col = {
        "postgresql": "id SERIAL PRIMARY KEY",
        "sqlite": "id INTEGER PRIMARY KEY AUTOINCREMENT",
    }.get(dialect, "id INT AUTO_INCREMENT PRIMARY KEY")

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
    lending_path = _first_existing(_LENDING_CANDIDATES())
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
