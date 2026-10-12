"""
Migration: create platform_settings table (Admin Console > API Keys ->
Database, S3 Bucket Storage, System Email, Calendly, Meeting Link panels).
Called from react_api.py's startup hook -- idempotent, safe to run every boot.
"""
import logging

logger = logging.getLogger(__name__)


def run(engine):
    from sqlalchemy import text, inspect

    insp = inspect(engine)
    if insp.has_table("platform_settings"):
        logger.info("Migration: platform_settings already exists — skipping")
        return

    dialect = engine.dialect.name  # "postgresql" | "sqlite" | "mysql"
    if dialect == "postgresql":
        id_col = "id SERIAL PRIMARY KEY"
    elif dialect == "sqlite":
        id_col = "id INTEGER PRIMARY KEY AUTOINCREMENT"
    else:
        id_col = "id INT AUTO_INCREMENT PRIMARY KEY"

    with engine.begin() as conn:
        conn.execute(text(f"""
            CREATE TABLE platform_settings (
                {id_col},
                service    VARCHAR(50) NOT NULL,
                key_name   VARCHAR(100) NOT NULL,
                key_value  TEXT NOT NULL,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                CONSTRAINT uq_platform_setting_service_key UNIQUE (service, key_name)
            )
        """))
        conn.execute(text("CREATE INDEX ix_platform_settings_service ON platform_settings (service)"))
    logger.info("Migration: created platform_settings table")
