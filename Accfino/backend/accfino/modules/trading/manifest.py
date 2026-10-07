"""Trading / Capital Gains module manifest."""
from accfino.shared.contracts.registry import ModuleSpec, register


def _cost_base(engine):
    from accfino.modules.trading.migrations.trading_cost_base import run
    run(engine)


register(ModuleSpec(name="trading", title="Trading / Capital Gains", models=("accfino.modules.trading.models",),
                    startup_steps=(_cost_base,)))
