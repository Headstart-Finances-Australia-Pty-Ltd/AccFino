"""State payroll tax monitor service: wages from Payroll (via its public facade) against the state's registration threshold. See engine/payroll_tax.py for why it is a monitor."""
from datetime import date
from typing import Optional

import accfino.modules.payroll.public as payroll
from accfino.modules.taxation.engine import payroll_tax as E, rules as R
from accfino.modules.taxation.engine.money import D
from accfino.modules.taxation.models import tax as T
from accfino.modules.taxation.services import core, profile as P


def watch(db, ctx, fy: str, today: Optional[date] = None) -> dict:
    core.check_fy(ctx, fy)
    today = today or date.today()
    p = P.get(db, ctx)
    rs = core.rules_for_fy(db, ctx, fy)
    start, end = R.fy_bounds(fy, ctx.org.fy_end_month or 6)
    upto = min(max(today, start), end)
    months = max(1, min(12, (upto.year - start.year) * 12 + upto.month - start.month + 1))
    run = payroll.withholding_for_period(db, ctx.org.id, start, upto)
    wages = D(run["gross"]) + D(run["super"])                       # Payroll gross wages plus super: closer to taxable wages than gross alone, still a floor
    res = E.assess(rs, p.state, wages, months if upto < end else 12)
    registered = db.query(T.TaxRegistration.id).filter(T.TaxRegistration.org_id == ctx.org.id, T.TaxRegistration.kind == "payroll_tax", T.TaxRegistration.cancelled_on.is_(None)).first() is not None
    res.update(fy=fy, as_at=upto.isoformat(), months_elapsed=months, registered=registered, pay_runs=run["runs"], rule_set=rs.id,
               basis="Payroll gross wages plus employer super for finalised pay runs in the year, scaled to 12 months (an assumption). Contractor payments, allowances and other taxable wages are not included.")
    if res["status"] in ("above", "approaching") and not registered:
        res["action"] = "No payroll tax registration is recorded. If you are registered with the revenue office, add it under Calendar > Registrations so the monthly return dates are generated."
    if registered and res["status"] == "no_state":
        res["action"] = "Set the state in the tax profile to generate payroll tax return dates."
    return res
