"""Taxation & Compliance module manifest."""
from accfino.shared.contracts.registry import ModuleSpec, register


def _tables():
    from accfino.modules.taxation.models.tax import TAX_TABLES
    return list(TAX_TABLES)


def _pg_schema(conn):
    """Columns added after the first Taxation release (idempotent). A fresh database gets them from create_all; an existing one needs the ALTER."""
    from sqlalchemy import text
    conn.execute(text("ALTER TABLE IF EXISTS tax_bas_statements ADD COLUMN IF NOT EXISTS source VARCHAR(12) NOT NULL DEFAULT 'calculated'"))


register(ModuleSpec(name="taxation", title="Taxation & Compliance", models=("accfino.modules.taxation.models.tax",), tables=_tables, pg_schema=(_pg_schema,)))
