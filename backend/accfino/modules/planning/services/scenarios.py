"""Scenario planning service. A scenario = named assumptions + a base plan (ledger run-rate or a budget). Running one reads the ledger and stores a result;
it NEVER posts a journal or edits any accounting record."""
import datetime as dt
import re
from collections import defaultdict
from decimal import Decimal
from typing import List, Optional

import accfino.modules.accounting.public as acc
import accfino.modules.lending.public as lend
from accfino.modules.planning.engine import scenario as S, budget as B
from accfino.modules.planning.engine.money import D, q2, s, ZERO
from accfino.modules.planning.models import plan as P
from . import core

PAYROLL_RE = re.compile(r"wage|salar|superannuation|payroll|workcover|workers comp|leave", re.I)


def _month_list(start_month: dt.date, n: int) -> List[str]:
    out, y, m = [], start_month.year, start_month.month
    for _ in range(n):
        out.append(f"{y:04d}-{m:02d}")
        m += 1
        if m == 13:
            y, m = y + 1, 1
    return out


def _category(a) -> str:
    if a["class"] == "revenue":
        return "revenue"
    if a["type"] == "direct_costs":
        return "direct_costs"
    if PAYROLL_RE.search(a["name"]):
        return "payroll"
    return "opex"


def base_plan(db, ctx, base_source: str, n_months: int, as_at: dt.date) -> dict:
    """The base the assumptions are applied to. 'run_rate' = average of the last 3 complete ledger months; 'budget:<name>' = that budget's monthly lines."""
    first_future = dt.date(as_at.year + (as_at.month == 12), as_at.month % 12 + 1, 1)
    months = _month_list(first_future, n_months)
    cats = {"revenue": ZERO, "direct_costs": ZERO, "payroll": ZERO, "opex": ZERO}
    accs = {x["id"]: dict(x, **{"class": "revenue" if x["type"] in ("revenue", "other_income") else "expense"}) for x in acc.ledger_accounts(db, ctx.org.id, active_only=False)}
    per_month = []
    if base_source == "run_rate":
        eom = dt.date(as_at.year + (as_at.month == 12), as_at.month % 12 + 1, 1) - dt.timedelta(days=1)
        hist_to = as_at if as_at == eom else dt.date(as_at.year, as_at.month, 1) - dt.timedelta(days=1)       # the last COMPLETE month
        y, m = hist_to.year, hist_to.month - 2
        if m < 1:
            y, m = y - 1, m + 12
        hist_from = dt.date(y, m, 1)
        pl = acc.monthly_pl(db, ctx.org.id, hist_from, hist_to)
        hmonths = sorted({mo for r in pl for mo in r["months"]})
        if not hmonths:
            raise core.PlanError("There is no ledger profit-and-loss activity in the last 3 complete months to base a scenario on. Choose a budget as the base instead.")
        denom = Decimal(len(_month_list(hist_from, 3)))
        for r in pl:
            c = _category(accs[r["account_id"]])
            cats[c] += sum(r["months"].values(), ZERO)
        monthly = {k: v / denom for k, v in cats.items()}
        per_month = [dict(month=mo, **{k: q2(v) for k, v in monthly.items()}) for mo in months]
        prov = dict(source="ledger run-rate", detail=f"average of the 3 complete months {hist_from.strftime('%Y-%m')} to {hist_to.strftime('%Y-%m')}", months_with_activity=len(hmonths))
    elif base_source.startswith("budget:"):
        name = base_source.split(":", 1)[1]
        meta = db.query(P.PlanBudget).filter_by(org_id=ctx.org.id, name=name).first()
        if meta is None:
            raise core.NotFound("Budget")
        covered = set(B.fy_months(meta.fy_start))
        if not set(months) <= covered:
            raise core.PlanError(f"Budget '{name}' only covers {min(covered)} to {max(covered)}; choose fewer months or a different base.")
        grid = acc.budget_lines(db, ctx.org, name, meta.fy_start)
        for mo in months:
            row = {k: ZERO for k in cats}
            for r in grid["accounts"]:
                row[_category(accs[r["account_id"]])] += D(r["periods"].get(mo, 0))
            per_month.append(dict(month=mo, **{k: q2(v) for k, v in row.items()}))
        prov = dict(source=f"budget '{name}' ({meta.status})", detail=f"monthly budget lines {months[0]} to {months[-1]}")
    else:
        raise core.PlanError("base_source must be 'run_rate' or 'budget:<name>'")
    ds = defaultdict(lambda: ZERO)
    end = dt.date.fromisoformat(months[-1] + "-28") + dt.timedelta(days=4)
    for f in lend.treasury_flows(db, ctx, as_at + dt.timedelta(days=1), end):
        if f["source"] in ("loan", "facility") and D(f["amount"]) < 0:
            ds[f["date"].strftime("%Y-%m")] += -D(f["amount"])
    for p_ in per_month:
        p_["debt_service"] = q2(ds.get(p_["month"], ZERO))
    opening = sum((r["ledger_balance"] for r in acc.bank_reconciliation_status(db, ctx.org, as_at)), ZERO)
    return dict(opening_cash=q2(opening), months=per_month, provenance=prov, as_at=as_at.isoformat(),
                categories_note="Payroll = accounts whose name mentions wages, salary, super, payroll tax, workcover or leave; direct costs = 'direct costs' accounts; everything else is operating expenses.")


def _row(r: "P.PlanScenario") -> dict:
    return dict(id=r.id, name=r.name, kind=r.kind, status=r.status, assumptions=r.assumptions or {}, base_source=r.base_source, months=r.months, version=r.version, parent_id=r.parent_id,
                notes=r.notes, updated_at=r.updated_at.isoformat() if r.updated_at else None)


def _get(db, ctx, sid) -> "P.PlanScenario":
    r = db.query(P.PlanScenario).filter_by(org_id=ctx.org.id, id=sid).first()
    if r is None:
        raise core.NotFound("Scenario")
    return r


def templates() -> dict:
    return {k: dict(label=v["label"], note=v["note"], assumptions=v["assumptions"]) for k, v in S.TEMPLATES.items()}


def _check(assumptions: dict) -> dict:
    try:
        S.validate(assumptions)
        S.validate_hires(assumptions.get("hires"))
    except ValueError as e:
        raise core.PlanError(str(e))
    return core.plain(assumptions)


def listing(db, ctx, a, include_archived: bool = False) -> List[dict]:
    a.require("view")
    q = db.query(P.PlanScenario).filter_by(org_id=ctx.org.id)
    if not include_archived:
        q = q.filter(P.PlanScenario.status == "active")
    return [_row(r) for r in q.order_by(P.PlanScenario.name)]


def create(db, ctx, a, body: dict) -> dict:
    a.require("edit")
    kind = body.get("kind") or "custom"
    if kind not in P.SCENARIO_KINDS:
        raise core.PlanError("kind must be base, optimistic, downside or custom")
    name = (body.get("name") or "").strip()
    if not name or len(name) > 80:
        raise core.PlanError("A scenario needs a name of 1 to 80 characters")
    if db.query(P.PlanScenario).filter_by(org_id=ctx.org.id, name=name).first():
        raise core.Conflict(f"A scenario called '{name}' already exists")
    assumptions = body.get("assumptions")
    if assumptions is None:
        assumptions = dict(S.TEMPLATES[kind]["assumptions"]) if kind in S.TEMPLATES else {}
    assumptions = _check(assumptions)
    n = int(body.get("months") or 12)
    if n < 1 or n > 36:
        raise core.PlanError("months must be 1 to 36")
    r = P.PlanScenario(org_id=ctx.org.id, name=name, kind=kind, assumptions=assumptions, base_source=body.get("base_source") or "run_rate", months=n, notes=body.get("notes"), created_by=ctx.user_id)
    db.add(r)
    db.flush()
    core.audit(db, ctx, "scenario.create", "plan_scenario", r.id, name=name, kind=kind)
    return _row(r)


def update(db, ctx, a, sid: int, body: dict) -> dict:
    a.require("edit")
    r = _get(db, ctx, sid)
    if r.status == "archived":
        raise core.Conflict("An archived scenario cannot be edited; duplicate it first")
    before = dict(assumptions=r.assumptions, base_source=r.base_source, months=r.months)
    if "assumptions" in body:
        r.assumptions = _check(body["assumptions"])
    if body.get("base_source"):
        r.base_source = body["base_source"]
    if body.get("months"):
        if not 1 <= int(body["months"]) <= 36:
            raise core.PlanError("months must be 1 to 36")
        r.months = int(body["months"])
    if "notes" in body:
        r.notes = body["notes"]
    if body.get("name") and body["name"].strip() != r.name:
        nm = body["name"].strip()
        if db.query(P.PlanScenario).filter(P.PlanScenario.org_id == ctx.org.id, P.PlanScenario.name == nm, P.PlanScenario.id != r.id).first():
            raise core.Conflict(f"A scenario called '{nm}' already exists")
        r.name = nm[:80]
    r.version += 1
    db.flush()
    core.audit(db, ctx, "scenario.update", "plan_scenario", r.id, name=r.name, version=r.version, before=before)
    return _row(r)


def duplicate(db, ctx, a, sid: int, name: Optional[str] = None) -> dict:
    a.require("edit")
    src = _get(db, ctx, sid)
    nm = (name or f"{src.name} (copy)")[:80]
    if db.query(P.PlanScenario).filter_by(org_id=ctx.org.id, name=nm).first():
        raise core.Conflict(f"A scenario called '{nm}' already exists")
    r = P.PlanScenario(org_id=ctx.org.id, name=nm, kind="custom", assumptions=dict(src.assumptions or {}), base_source=src.base_source, months=src.months, parent_id=src.id,
                       notes=f"Duplicated from '{src.name}' v{src.version}", created_by=ctx.user_id)
    db.add(r)
    db.flush()
    core.audit(db, ctx, "scenario.duplicate", "plan_scenario", r.id, source=src.name)
    return _row(r)


def archive(db, ctx, a, sid: int) -> dict:
    a.require("edit")
    r = _get(db, ctx, sid)
    r.status = "archived"
    core.audit(db, ctx, "scenario.archive", "plan_scenario", r.id, name=r.name)
    return _row(r)


def _result_json(res: dict) -> dict:
    return core.plain(res)


def run(db, ctx, a, sid: int, as_at: Optional[dt.date] = None, save: bool = True, compare_budget: Optional[str] = None) -> dict:
    a.require("view")
    if save:
        a.require("edit")
    r = _get(db, ctx, sid)
    as_at = as_at or core.business_today()
    base = base_plan(db, ctx, r.base_source, r.months, as_at)
    assumptions = dict(r.assumptions or {})
    hires = assumptions.get("hires")
    res = S.run(base, {k: v for k, v in assumptions.items() if k != "hires"}, hires)
    out = dict(kind="scenario_run", basis="SCENARIO (hypothetical, not actual and not a forecast)", **core.stamp(ctx, as_at=as_at.isoformat(), period_from=base["months"][0]["month"], period_to=base["months"][-1]["month"],
                                                                                                                 source=base["provenance"]["source"]),
               scenario=_row(r), base=dict(opening_cash=s(base["opening_cash"]), provenance=base["provenance"], note=base["categories_note"]),
               months=[{k: (s(v) if isinstance(v, Decimal) else v) for k, v in m.items()} for m in res["months"]],
               summary=core.plain(res["summary"]), assumptions=res["assumptions"], hires=res["hires"], limitations=res["limitations"])
    if compare_budget:
        meta = db.query(P.PlanBudget).filter_by(org_id=ctx.org.id, name=compare_budget).first()
        if meta is None:
            raise core.NotFound("Budget")
        bb = base_plan(db, ctx, f"budget:{compare_budget}", r.months, as_at)
        bprofit = sum((D(m["revenue"]) - D(m["direct_costs"]) - D(m["payroll"]) - D(m["opex"]) for m in bb["months"]), ZERO)
        out["budget_variance"] = dict(budget=compare_budget, budget_profit=s(bprofit), scenario_profit=out["summary"]["profit"], variance=s(D(out["summary"]["profit"]) - bprofit), note="Scenario profit minus budget profit over the same months (positive = scenario above budget).")
    out["input_hash"] = core.digest(dict(base=base, a=assumptions, v=r.version))
    if save:
        run_ = P.PlanScenarioRun(org_id=ctx.org.id, scenario_id=r.id, scenario_version=r.version, as_at=as_at, assumptions=core.plain(assumptions), base=core.plain(base), result=core.plain(out), input_hash=out["input_hash"], created_by=ctx.user_id)
        db.add(run_)
        db.flush()
        out["run_id"] = run_.id
        core.audit(db, ctx, "scenario.run", "plan_scenario", r.id, run_id=run_.id, version=r.version, profit=out["summary"]["profit"], closing_cash=out["summary"]["closing_cash"])
    return out


def runs(db, ctx, a, sid: int) -> List[dict]:
    a.require("view")
    _get(db, ctx, sid)
    return [dict(id=x.id, scenario_version=x.scenario_version, as_at=x.as_at.isoformat(), input_hash=x.input_hash, created_at=x.created_at.isoformat(), summary=x.result.get("summary"))
            for x in db.query(P.PlanScenarioRun).filter_by(org_id=ctx.org.id, scenario_id=sid).order_by(P.PlanScenarioRun.id.desc()).limit(50)]


def run_get(db, ctx, a, sid: int, run_id: int) -> dict:
    a.require("view")
    x = db.query(P.PlanScenarioRun).filter_by(org_id=ctx.org.id, scenario_id=sid, id=run_id).first()
    if x is None:
        raise core.NotFound("Scenario run")
    return dict(x.result, run_id=x.id, stored=True)


def compare(db, ctx, a, ids: List[int], as_at: Optional[dt.date] = None, reference: Optional[int] = None) -> dict:
    """Side-by-side of 2-6 scenarios on the same as-at date (nothing is stored)."""
    a.require("view")
    if not 2 <= len(ids) <= 6:
        raise core.PlanError("Choose between 2 and 6 scenarios to compare")
    if len(set(ids)) != len(ids):
        raise core.PlanError("Each scenario can only be chosen once")
    as_at = as_at or core.business_today()
    results = {}
    names = {}
    for i in ids:
        out = run(db, ctx, a, i, as_at=as_at, save=False)
        nm = out["scenario"]["name"]
        names[i] = nm
        results[nm] = dict(summary={k: (D(v) if isinstance(v, str) and k in ("revenue", "expenses", "profit", "closing_cash", "net_cash") else v) for k, v in out["summary"].items()}, months=out["months"])
    ref = names[reference] if reference in names else names[ids[0]]
    cmp_ = S.compare(results, ref)
    return dict(kind="scenario_comparison", basis="SCENARIO COMPARISON (hypothetical)", **core.stamp(ctx, as_at=as_at.isoformat(), source="scenario engine on the ledger base"), reference=ref,
                rows=[dict(r, revenue=s(r["revenue"]), expenses=s(r["expenses"]), profit=s(r["profit"]), closing_cash=s(r["closing_cash"]), d_profit=s(r["d_profit"]), d_closing_cash=s(r["d_closing_cash"]),
                           lowest_cash=core.plain(r["lowest_cash"])) for r in cmp_], limitations=S.LIMITATIONS)


def sensitivity(db, ctx, a, sid: int, as_at: Optional[dt.date] = None) -> dict:
    a.require("view")
    r = _get(db, ctx, sid)
    as_at = as_at or core.business_today()
    base = base_plan(db, ctx, r.base_source, r.months, as_at)
    rows = S.sensitivity(base, dict(r.assumptions or {}))
    return dict(kind="sensitivity", basis="SCENARIO SENSITIVITY (hypothetical)", **core.stamp(ctx, as_at=as_at.isoformat(), source=base["provenance"]["source"]), scenario=_row(r),
                rows=[dict(x, profit_delta=s(x["profit_delta"]), closing_cash_delta=s(x["closing_cash_delta"])) for x in rows],
                note="Each row moves ONE driver (revenue, expenses, payroll: +/-10 percentage points; payment timing: +/-10 days) and shows the change versus this scenario.")
