"""
Migration: add currency, amount_original, exchange_rate, is_loan_payment,
loan_principal, loan_interest columns to the transactions table.

Run once on startup (called from init_db.py) or directly:
    python -m db_app.migrations.add_currency_loan_columns
"""
import logging
logger = logging.getLogger(__name__)


def run(engine):
    """Apply migration idempotently using raw SQL (SQLite + Postgres safe)."""
    from sqlalchemy import text, inspect

    insp = inspect(engine)
    existing = {col["name"] for col in insp.get_columns("transactions")}

    new_columns = [
        ("currency",           "VARCHAR(10)  DEFAULT 'AUD'"),
        ("amount_original",    "FLOAT"),
        ("exchange_rate",      "FLOAT"),
        ("bank_balance",       "FLOAT"),
        ("is_loan_payment",    "BOOLEAN DEFAULT FALSE"),
        ("loan_principal",     "FLOAT"),
        ("loan_interest",      "FLOAT"),
        ("loan_interest_rate", "FLOAT"),
        ("loan_principal_gl",  "VARCHAR(100)"),
        ("loan_interest_gl",   "VARCHAR(100)"),
    ]

    with engine.begin() as conn:
        for col_name, col_def in new_columns:
            if col_name not in existing:
                try:
                    conn.execute(text(
                        f"ALTER TABLE transactions ADD COLUMN {col_name} {col_def}"
                    ))
                    logger.info(f"Migration: added transactions.{col_name}")
                except Exception as e:
                    logger.warning(f"Migration skipped {col_name}: {e}")