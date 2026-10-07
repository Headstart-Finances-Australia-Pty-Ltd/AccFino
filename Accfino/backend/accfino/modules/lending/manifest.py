"""Lending module manifest."""
from accfino.shared.contracts.registry import ModuleSpec, register


def _rules(engine):
    from accfino.modules.lending.migrations.lending_classifications import run
    run(engine)


register(ModuleSpec(name="lending", title="Smart Lending", models=("accfino.modules.lending.models",), startup_steps=(_rules,)))
