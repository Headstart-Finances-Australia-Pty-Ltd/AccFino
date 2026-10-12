"""Practice & Client Services module manifest."""
from accfino.shared.contracts.registry import ModuleSpec, register


def _tables():
    from accfino.modules.practice.models.practice import PRACTICE_TABLES
    return list(PRACTICE_TABLES)


register(ModuleSpec(name="practice", title="Practice & Client Services", models=("accfino.modules.practice.models.practice",), tables=_tables))
