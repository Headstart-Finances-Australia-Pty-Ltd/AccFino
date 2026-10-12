"""Lending module manifest."""
from accfino.shared.contracts.registry import ModuleSpec, register


def _rules(engine):
    from accfino.modules.lending.migrations.lending_classifications import run
    run(engine)


def _tables():
    from accfino.modules.lending.lend_models import LEND_TABLES                  # Table OBJECTS: the platform migration passes them to create_all(tables=...)
    return list(LEND_TABLES)


register(ModuleSpec(name="lending", title="Smart Lending, Credit & Treasury", models=("accfino.modules.lending.models", "accfino.modules.lending.lend_models"), tables=_tables, startup_steps=(_rules,)))
