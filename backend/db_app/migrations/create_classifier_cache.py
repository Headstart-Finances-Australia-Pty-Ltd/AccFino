"""
Migration: create classifier_cache table.
Called from react_api.py's startup hook -- idempotent, safe to run every boot.
Replaces ollama_cache.json (classify_category.py's disk cache).
"""
import logging

logger = logging.getLogger(__name__)


def run(engine):
    from sqlalchemy import text, inspect

    insp = inspect(engine)
    if insp.has_table("classifier_cache"):
        return

    dialect = engine.dialect.name
    with engine.begin() as conn:
        conn.execute(text("""
            CREATE TABLE classifier_cache (
                cache_key    VARCHAR(64) PRIMARY KEY,
                category     VARCHAR(100),
                gst_category VARCHAR(100),
                updated_at   TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """))
    logger.info("Migration: created classifier_cache table")

    # One-time import from the legacy ollama_cache.json, if present.
    import json
    from pathlib import Path
    legacy = Path("ollama_cache.json")
    if not legacy.exists():
        return
    try:
        data = json.loads(legacy.read_text("utf-8"))
    except Exception as e:
        logger.warning(f"Migration: could not parse {legacy}: {e}")
        return
    if not isinstance(data, dict):
        return
    imported = 0
    with engine.begin() as conn:
        for key, val in data.items():
            if not isinstance(val, dict):
                continue
            existing = conn.execute(text("SELECT 1 FROM classifier_cache WHERE cache_key = :k"), {"k": key}).first()
            if existing:
                continue
            conn.execute(
                text("INSERT INTO classifier_cache (cache_key, category, gst_category) VALUES (:k, :c, :g)"),
                {"k": key, "c": val.get("category"), "g": val.get("gst_category")},
            )
            imported += 1
    if imported:
        logger.info(f"Migration: imported {imported} cache entr(ies) from {legacy}")
