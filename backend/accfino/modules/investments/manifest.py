"""Assets, Investments & Wealth module manifest."""
from accfino.shared.contracts.registry import ModuleSpec, register


def _tables():
    from accfino.modules.investments.models.inv import INV_TABLES
    return list(INV_TABLES)


register(ModuleSpec(name="investments", title="Assets, Investments & Wealth", models=("accfino.modules.investments.models.inv",), tables=_tables))
