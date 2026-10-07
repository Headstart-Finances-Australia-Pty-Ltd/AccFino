"""Cash Flow module manifest: forecasting pipeline (no tables of its own; outputs go to ACCFINO_DATA_ROOT/modules/cashflow)."""
from accfino.shared.contracts.registry import ModuleSpec, register

register(ModuleSpec(name="cashflow", title="Cash Flow"))
