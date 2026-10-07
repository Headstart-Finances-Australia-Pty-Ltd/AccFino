"""Billing module manifest: Square subscription billing, Stripe checkout, payment-gateway configuration."""
from accfino.shared.contracts.registry import ModuleSpec, register


def _tables():
    from accfino.modules.billing.models import BILLING_TABLES
    return list(BILLING_TABLES)


def _start_billing_loop():
    from accfino.modules.billing.runner import start_billing_loop
    start_billing_loop()                   # automatic subscription renewals (Square); one worker at a time, see billing/runner.py


def _org_billing(db, org_id):
    from accfino.modules.billing.models import OrgBilling
    return db.get(OrgBilling, org_id)


def _plan_renamed(db, old, new):
    from accfino.modules.billing.models import BillingCharge
    for ch in db.query(BillingCharge).filter_by(plan_id=old).all():
        ch.plan_id = new


register(ModuleSpec(name="billing", title="Billing & Payments", models=("accfino.modules.billing.models",),
                    tables=_tables, plan_renamed=(_plan_renamed,), on_startup=(_start_billing_loop,), org_billing=(_org_billing,)))
