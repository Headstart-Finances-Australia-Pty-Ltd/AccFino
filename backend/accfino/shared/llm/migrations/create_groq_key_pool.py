"""
Migration: create groq_key_pool table.
Called from react_api.py's startup hook -- idempotent, safe to run every boot.
"""
import logging

logger = logging.getLogger(__name__)


def run(engine):
    from sqlalchemy import text, inspect

    insp = inspect(engine)
    if insp.has_table("groq_key_pool"):
        logger.info("Migration: groq_key_pool already exists — skipping")
        return

    dialect = engine.dialect.name  # "postgresql" | "sqlite" | "mysql"
    if dialect == "postgresql":
        id_col = "id SERIAL PRIMARY KEY"
        bool_default = "DEFAULT TRUE"
    elif dialect == "sqlite":
        id_col = "id INTEGER PRIMARY KEY AUTOINCREMENT"
        bool_default = "DEFAULT 1"
    else:
        id_col = "id INT AUTO_INCREMENT PRIMARY KEY"
        bool_default = "DEFAULT 1"

    with engine.begin() as conn:
        conn.execute(text(f"""
            CREATE TABLE groq_key_pool (
                {id_col},
                key_value          TEXT NOT NULL UNIQUE,
                model              VARCHAR(200),
                is_active          BOOLEAN NOT NULL {bool_default},
                consecutive_errors INTEGER NOT NULL DEFAULT 0,
                cooldown_until     TIMESTAMP,
                last_used_at       TIMESTAMP,
                added_at           TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """))
    logger.info("Migration: created groq_key_pool table")
