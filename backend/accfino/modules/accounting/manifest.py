"""Accounting module manifest: ledger, books (sales/purchases/banking), assets, inventory, invoices, legacy accounting documents."""
from accfino.shared.contracts.registry import ModuleSpec, register


def _tables():
    from accfino.modules.accounting.assets.models import ASSETS_TABLES
    from accfino.modules.accounting.books.models import BOOKS_TABLES
    from accfino.modules.accounting.inventory.models import INVENTORY_TABLES
    from accfino.modules.accounting.ledger.journal_models import JOURNAL_TABLES
    from accfino.modules.accounting.models import ledger as lm
    return [lm.TaxCode.__table__, lm.LedgerAccount.__table__, lm.TrackingCategory.__table__, lm.TrackingOption.__table__,
            lm.Journal.__table__, lm.JournalLine.__table__, lm.LedgerSourceLink.__table__,
            *BOOKS_TABLES, *ASSETS_TABLES, *INVENTORY_TABLES, *JOURNAL_TABLES]


def _pre_schema(engine):
    from accfino.modules.accounting.migrations.ledger_schema import pre_schema
    pre_schema(engine)


def _pg_schema(conn):
    from accfino.modules.accounting.migrations.ledger_schema import pg_schema
    pg_schema(conn)


def _money_migration(engine):
    from accfino.modules.accounting.books import money_migration
    money_migration.run(engine)


def _provision(db, org):
    from accfino.modules.accounting.ledger.seed import seed_org_ledger
    seed_org_ledger(db, org)


def _legacy_tables(engine):
    from accfino.modules.accounting.migrations.create_accounting_tables import run
    run(engine)


register(ModuleSpec(
    name="accounting", title="Books and Accounting",
    models=("accfino.modules.accounting.models.ledger", "accfino.modules.accounting.models.invoice",
            "accfino.modules.accounting.models.legacy_documents", "accfino.modules.accounting.books.models",
            "accfino.modules.accounting.assets.models", "accfino.modules.accounting.inventory.models",
            "accfino.modules.accounting.ledger.journal_models"),
    tables=_tables,
    raw_sql_tables=("accounting_customers", "accounting_documents", "accounting_line_items", "accounting_suppliers"),
    pre_schema=(_pre_schema,), pg_schema=(_pg_schema,), post_schema=(_money_migration,),
    org_provision=(_provision,), protected_trigger_tables=("journal_lines", "journals"),
    startup_steps=(_legacy_tables,),
))
