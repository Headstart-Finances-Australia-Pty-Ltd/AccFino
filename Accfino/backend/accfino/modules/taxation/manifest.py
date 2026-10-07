"""Taxation & Compliance module manifest."""
from accfino.shared.contracts.registry import ModuleSpec, register


def _tables():
    from accfino.modules.taxation.models.tax import TAX_TABLES
    return list(TAX_TABLES)


register(ModuleSpec(name="taxation", title="Taxation & Compliance", models=("accfino.modules.taxation.models.tax",), tables=_tables))
