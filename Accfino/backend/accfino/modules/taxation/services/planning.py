"""Tax planning and estimates. Projects the year-end result from the ledger year-to-date (an ASSUMPTION, labelled as such: straight-line by months elapsed unless the user
overrides), applies levers (extra deductions / income), and runs the same income-tax engine as the return. Saves scenarios for comparison. Not tax advice."""
from datetime import date
from typing import List, Optional

import accfino.modules.accounting.public as accounting
from accfino.modules.taxation.engine import income_tax as E, rules as R
from accfino.modules.taxation.engine.money import ZERO, D, q2
from accfino.modules.taxation.models import tax as T
from accfino.modules.taxation.services import cgt as CGT, core, profile as P
from accfino.modules.taxation.services.core import NotFound, TaxError


def _months_elapsed(start: date, as_at: date) -> int:
    return max(1, min(12, (as_at.year - start.year) * 12 + as_at.month - start.month + 1))


def estimate(db, ctx, fy: str, as_at: Optional[date] = None, levers: Optional[List[dict]] = None, projected_profit: Optional[str] = None, other_income: str = "0") -> dict:
    core.check_fy(ctx, fy)
    p = P.get(db, ctx)
    rs = core.rules_for_fy(db, ctx, fy)
    start, end = R.fy_bounds(fy, ctx.org.fy_end_month or 6)
    as_at = min(max(as_at or date.today(), start), end)
    pl = accounting.profit_and_loss(db, ctx.org, start, as_at)
    ytd, months = D(pl["net_profit"]), _months_elapsed(start, as_at)
    steps = []
    if projected_profit not in (None, ""):
        full, how = core.money_in(projected_profit, "projected_profit", allow_negative=True), "user_entered"
        steps.append(E.step("projection", "Projected full-year profit (entered)", full, "user_entered"))
    elif as_at >= end:
        full, how = ytd, "source"
        steps.append(E.step("projection", "Actual full-year profit from the ledger", full, "source"))
    else:
        full, how = q2(ytd / months * 12), "assumption"
        steps.append(E.step("projection", f"Projected full-year profit: {q2(ytd)} year-to-date over {months} month(s), scaled to 12", full, "assumption",
                            "Straight-line projection: ignores seasonality, one-off items and unposted transactions. Override with your own forecast."))
    lev_add = lev_ded = ZERO
    for lv in levers or []:
        amt = core.money_in(lv.get("amount"), "lever amount", required=True)
        if lv.get("direction") == "deduct":
            lev_ded += amt
        elif lv.get("direction") == "add":
            lev_add += amt
        else:
            raise TaxError("lever direction must be add or deduct")
        steps.append(E.step("lever", lv.get("label") or "Lever", -amt if lv.get("direction") == "deduct" else amt, "user_entered", "Planning lever (not in the ledger)"))
    adds = sum((x.amount for x in db.query(T.TaxAdjustment).filter_by(org_id=ctx.org.id, fy=fy, direction="add")), ZERO)
    deds = sum((x.amount for x in db.query(T.TaxAdjustment).filter_by(org_id=ctx.org.id, fy=fy, direction="deduct")), ZERO)
    ncg = D(CGT.compute(db, ctx, fy)["net_capital_gain"])
    inst = sum((D(((s.final or {}).get("5A") or {}).get("value")) for s in db.query(T.TaxBasStatement).filter(T.TaxBasStatement.org_id == ctx.org.id, T.TaxBasStatement.fy == fy,
                                                                                                         T.TaxBasStatement.status.in_(("lodged", "paid")))), ZERO)
    inp = dict(assessable_income=full + D(other_income) + adds + lev_add, deductions_other=deds + lev_ded, net_capital_gain=ncg, instalments_paid=inst, resident=(p.residency == "resident"),
               aggregated_turnover=p.aggregated_turnover, business_net_income=max(full, ZERO), passive_income_ratio=p.passive_income_ratio or 0, claim_standard_deduction=False)
    try:
        comp = E.compute_return(rs, fy, p.entity_type, inp)
    except (ValueError, R.RulesError) as e:
        raise TaxError(str(e))
    comp["steps"] = steps + comp["steps"]
    comp["warnings"].append(E.step("estimate", "Estimate", None, "estimate", "An estimate for planning only. It excludes items you have not entered and the review items listed. It is not tax advice."))
    return dict(fy=fy, as_at=as_at.isoformat(), months_elapsed=months, ytd_profit=str(q2(ytd)), projected_profit=str(q2(full)), projection_basis=how, result=comp,
                instalments_paid=str(q2(inst)), expected_balance=comp["balance"], year_end_considerations=considerations(db, ctx, fy, p, end))


def considerations(db, ctx, fy: str, p: T.TaxProfile, end: date) -> List[dict]:
    """Data-driven prompts to discuss with a tax agent before year end. Not recommendations."""
    out = []
    add = lambda key, msg: out.append(dict(key=key, message=msg))
    add("super", f"Employer super must be received by the fund by the due date to be deductible in {fy}; check Payroll > Superannuation for contributions still payable at {end.strftime('%d %b %Y')}.")
    if p.simplified_depreciation:
        add("assets", "Review assets purchased this year and the instant asset write-off threshold (see the Assets review tab).")
    if db.query(T.TaxDiv7aLoan.id).filter_by(org_id=ctx.org.id, status="active").first():
        add("div7a", f"Division 7A minimum yearly repayments must be paid by {end.strftime('%d %b %Y')} (see the Division 7A tab).")
    if p.entity_type == "trust":
        add("trust", "Trustee distribution resolutions are generally needed by 30 June: take advice before year end.")
    if p.fbt_registered:
        add("fbt", "The FBT year ended on 31 March: confirm the FBT return and payment (due 21 May) are done.")
    add("losses", "Review debtors for bad debts and unrealised capital losses or gains that you may want to crystallise: tax agent advice recommended.")
    return out


def save_scenario(db, ctx, a: core.Access, fy: str, name: str, levers: list, projected_profit=None) -> T.TaxScenario:
    a.require("prepare")
    if not (name or "").strip():
        raise TaxError("name is required")
    res = estimate(db, ctx, fy, levers=levers, projected_profit=projected_profit)
    s = T.TaxScenario(org_id=ctx.org.id, fy=fy, name=name.strip()[:120], levers=core.plain(levers), result=core.plain(dict(projected_profit=res["projected_profit"], taxable_income=res["result"]["taxable_income"],
                      tax_assessed=res["result"]["tax_assessed"], balance=res["result"]["balance"], basis=res["projection_basis"])), created_by=ctx.user_id)
    db.add(s)
    db.flush()
    core.record(db, ctx, "planning.scenario", "tax_scenario", s.id, f"Scenario '{s.name}' saved: assessed {s.result['tax_assessed']}", None, s.result)
    return s


def scenarios(db, ctx, fy: str):
    return [dict(id=s.id, fy=s.fy, name=s.name, levers=s.levers, result=s.result, created_at=core.plain(s.created_at)) for s in
            db.query(T.TaxScenario).filter_by(org_id=ctx.org.id, fy=fy).order_by(T.TaxScenario.id)]


def delete_scenario(db, ctx, a: core.Access, sid: int):
    a.require("prepare")
    s = db.query(T.TaxScenario).filter_by(org_id=ctx.org.id, id=sid).first()
    if s is None:
        raise NotFound("Scenario")
    db.delete(s)
