"""
Migration: create account_balances table.
Called from init_db.py on startup — idempotent.
"""
import logging
logger = logging.getLogger(__name__)


def run(engine):
    from sqlalchemy import text, inspect

    insp = inspect(engine)
    if insp.has_table("account_balances"):
        logger.info("Migration: account_balances already exists — skipping")
        return

    # Detect dialect so we use the right serial/autoincrement syntax
    dialect = engine.dialect.name  # "postgresql" | "sqlite" | "mysql"

    if dialect == "postgresql":
        id_col = "id         SERIAL PRIMARY KEY"
        bool_default = "DEFAULT FALSE"
    elif dialect == "sqlite":
        id_col = "id         INTEGER PRIMARY KEY AUTOINCREMENT"
        bool_default = "DEFAULT 0"
    else:
        id_col = "id         INT AUTO_INCREMENT PRIMARY KEY"
        bool_default = "DEFAULT 0"

    with engine.begin() as conn:
        conn.execute(text(f"""
            CREATE TABLE account_balances (
                {id_col},
                user_id    INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                bank       VARCHAR(100) NOT NULL,
                account    VARCHAR(100) NOT NULL,
                year       INTEGER NOT NULL,
                month      INTEGER NOT NULL,
                balance    FLOAT NOT NULL,
                is_manual  BOOLEAN {bool_default},
                source     VARCHAR(50) DEFAULT 'csv',
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(user_id, bank, account, year, month)
            )
        """))
        logger.info("Migration: created account_balances table")