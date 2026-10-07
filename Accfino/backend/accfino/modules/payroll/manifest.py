"""Payroll module manifest. Legacy raw-SQL tables are still created (they are left in place, unused, so a rollback loses nothing)."""
from accfino.shared.contracts.registry import ModuleSpec, register


def _tables():
    from accfino.modules.payroll.models.payroll import PAYROLL_TABLES
    return list(PAYROLL_TABLES)


def _legacy_tables(engine):
    from accfino.modules.payroll.migrations.create_payroll_tables import run
    run(engine)


def _provision(db, org):
    from accfino.modules.payroll.services.setup import provision_org
    provision_org(db, org)


register(ModuleSpec(name="payroll", title="Payroll & Workforce",
                    models=("accfino.modules.payroll.models.payroll",), tables=_tables,
                    raw_sql_tables=("payroll_employees", "payroll_runs", "payroll_timesheets", "payslips", "stp_submissions"),
                    org_provision=(_provision,), startup_steps=(_legacy_tables,)))
