"""Planning & Intelligence landing page: real KPIs from the same services the tabs use. Nothing is cached or invented; each tile states its source and basis."""
import datetime as dt

import accfino.modules.accounting.public as acc
from accfino.modules.planning.engine.money import D, s, ZERO
from accfino.modules.planning.models import plan as P
from . import budgets, core, forecast as FC, insights as INS, reports as RP, risk as RK


def _safe(fn, default=None):
    try:
        return fn()
    except core.Forbidden:
        raise
    except Exception as e:                                       # a failing tile must not blank the page; it shows an error state instead
        return dict(error=getattr(e, "message", None) or f"{type(e).__name__}")


def overview(db, ctx, a) -> dict:
    a.require("view")
    with acc.read_memo(db):                                       # tiles ask the ledger the same read-only questions: answer each once per request
        return _overview(db, ctx, a)


def _overview(db, ctx, a) -> dict:
    today = core.business_today()
    fy_s = core.fy_start_for(ctx.org, today)
    st = core.settings(db, ctx)

    def cash():
        recon = acc.bank_reconciliation_status(db, ctx.org, today)
        last = max([r["last_line_date"] for r in recon if r["last_line_date"]], default=None)
        return dict(balance=s(sum((r["ledger_balance"] for r in recon), ZERO)), accounts=len(recon), unreconciled=sum(r["unreconciled_count"] for r in recon),
                    last_bank_line=last.isoformat() if last else None, stale=bool(last and (today - last).days > st.stale_days), basis="ACTUAL", source="ledger bank accounts", as_at=today.isoformat())

    def fc():
        f = FC.build(db, ctx, a)
        return dict(basis="FORECAST", as_at=f["as_at"], closing=f["closing"], minimum=f["minimum"], max_shortfall=f["shortfall"]["max_shortfall"], goes_negative=f["shortfall"]["goes_negative"],
                    confidence=f["confidence"]["level"], warnings=len(f["warnings"]), weeks=f["periods"])

    def pl():
        cur = acc.profit_and_loss(db, ctx.org, fy_s, today)
        mtd = acc.profit_and_loss(db, ctx.org, today.replace(day=1), today)
        return dict(basis="ACTUAL", source="ledger", period=f"{fy_s.isoformat()} to {today.isoformat()}", revenue=cur["revenue_total"], expenses=cur["expense_total"], net_profit=cur["net_profit"], mtd_net_profit=mtd["net_profit"])

    def bud():
        m = RP._default_budget(db, ctx, fy_s, today)
        if m is None:
            return dict(basis="BUDGET", status="none", note="No approved budget covers this financial year.", pending=db.query(P.PlanBudget).filter(P.PlanBudget.org_id == ctx.org.id, P.PlanBudget.status == "submitted").count())
        v = budgets.vs_actual(db, ctx, a, m.id)
        return dict(basis="BUDGET vs ACTUAL", status="ok", name=m.name, period=f"{v['period_from']} to {v['period_to']}", profit=v["totals"]["profit"],
                    pending=db.query(P.PlanBudget).filter(P.PlanBudget.org_id == ctx.org.id, P.PlanBudget.status == "submitted").count())

    def risk():
        c = RK.listing(db, ctx, a, status="new", limit=500)
        sev = {x: sum(1 for r in c["alerts"] if r["severity"] == x) for x in ("high", "medium", "low")}
        return dict(basis="RULE ALERTS", new=c["counts"]["new"], acknowledged=c["counts"]["acknowledged"], by_severity=sev)

    def ins():
        r = INS.evaluate(db, ctx, a)
        return dict(basis="RULE RESULTS", counts=r["counts"], top=[dict(severity=i["severity"], title=i["title"]) for i in r["insights"][:3]], period=f"{r['period_from']} to {r['period_to']}")

    def scen():
        n = db.query(P.PlanScenario).filter_by(org_id=ctx.org.id, status="active").count()
        last = db.query(P.PlanScenarioRun).filter_by(org_id=ctx.org.id).order_by(P.PlanScenarioRun.id.desc()).first()
        return dict(basis="SCENARIO (hypothetical)", active=n, last_run_at=last.created_at.isoformat() if last else None)

    def rep():
        n = db.query(P.PlanReportSnapshot).filter_by(org_id=ctx.org.id).count()
        return dict(snapshots=n)

    def ai():
        since = dt.datetime.utcnow() - dt.timedelta(hours=24)
        return dict(basis="AI (read-only)", questions_24h=db.query(P.PlanAiLog).filter(P.PlanAiLog.org_id == ctx.org.id, P.PlanAiLog.created_at >= since).count())

    return dict(**core.stamp(ctx, as_at=today.isoformat()), access=a.summary(), cash=_safe(cash), forecast=_safe(fc), profit=_safe(pl), budget=_safe(bud), risk=_safe(risk), insights=_safe(ins),
                scenarios=_safe(scen), reports=_safe(rep), assistant=_safe(ai), settings=core.settings_dict(st))
