"""Reconciliation module manifest: statement pipeline, classification (ML/LLM/RDR), sessions, company directory, legacy transactions."""
from accfino.shared.contracts.registry import ModuleSpec, register


def _upgrade_currency_loan(engine):
    from accfino.modules.reconciliation.migrations.add_currency_loan_columns import run
    run(engine)


def _upgrade_account_balances(engine):
    from accfino.modules.reconciliation.migrations.create_account_balances import run
    run(engine)


def _seed_companies(session_local):
    from accfino.modules.reconciliation.seeding import seed_companies_safe
    seed_companies_safe(session_local)


def _step(modname):
    def run(engine):
        import importlib
        importlib.import_module(f"accfino.modules.reconciliation.migrations.{modname}").run(engine)
    run.__module__ = f"accfino.modules.reconciliation.migrations.{modname}"
    return run


register(ModuleSpec(
    name="reconciliation", title="Reconciliation",
    models=("accfino.modules.reconciliation.models.transaction", "accfino.modules.reconciliation.models.company",
            "accfino.modules.reconciliation.models.rdr_rule", "accfino.modules.reconciliation.models.reconciliation_session",
            "accfino.modules.reconciliation.models.reference"),
    raw_sql_tables=("account_balances",),
    init_upgrade_steps=(_upgrade_currency_loan, _upgrade_account_balances),
    init_seeds=(_seed_companies,),
    startup_steps=(_step("add_currency_loan_columns"), _step("create_account_balances"), _step("restructure_rdr_rules"),
                   _step("create_reconciliation_sessions"), _step("reference_data"), _step("create_classifier_cache")),
))
