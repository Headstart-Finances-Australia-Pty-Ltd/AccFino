"""Open Banking module manifest: Basiq + OpenFeed (CDR) bank feeds."""
from accfino.shared.contracts.registry import ModuleSpec, register


def _tables():
    from accfino.modules.open_banking.openfeed import OPENFEED_TABLES
    return list(OPENFEED_TABLES)


register(ModuleSpec(name="open_banking", title="Open Banking", models=("accfino.modules.open_banking.openfeed",), tables=_tables))
