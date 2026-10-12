"""Planning & Intelligence module manifest."""
from accfino.shared.contracts.registry import ModuleSpec, register


def _tables():
    from accfino.modules.planning.models.plan import PLAN_TABLES
    return list(PLAN_TABLES)


register(ModuleSpec(name="planning", title="Planning & Intelligence", models=("accfino.modules.planning.models.plan",), tables=_tables))
