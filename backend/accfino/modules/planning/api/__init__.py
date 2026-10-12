"""Planning & Intelligence HTTP API (mounted at /planning, one sub-router per capability so each is plan-gated by its own module id).
The API layer only validates, authorises and calls services; calculations live in engine/, orchestration in services/."""
from datetime import date
from typing import Optional

from fastapi import APIRouter, Body, Depends, Query
from fastapi.responses import Response
from sqlalchemy.orm import Session

from accfino.core.security.context import OrgContext, current_org
from accfino.modules.planning.api.deps import access
from accfino.modules.planning.services import assistant, budgets, core, forecast, insights, overview, reports, risk, scenarios, settings
from accfino.modules.planning.services.core import Access
from accfino.shared.db.database import get_db

Ctx, Db, Acc = Depends(current_org), Depends(get_db), Depends(access)
_d = core.parse_date

# ---------------------------------------------------------------------------------------------------------------- landing (any planning module)
home_router = APIRouter()


@home_router.get("/me")
def me(a: Access = Acc):
    return a.summary()


@home_router.get("/overview")
def get_overview(ctx: OrgContext = Ctx, db: Session = Db, a: Access = Acc):
    return overview.overview(db, ctx, a)


@home_router.get("/settings")
def get_settings(ctx: OrgContext = Ctx, db: Session = Db, a: Access = Acc):
    return settings.get(db, ctx, a)


@home_router.put("/settings")
def put_settings(body: dict = Body(...), ctx: OrgContext = Ctx, db: Session = Db, a: Access = Acc):
    out = settings.save(db, ctx, a, body)
    db.commit()
    return out


@home_router.get("/drilldown")
def drilldown(account_id: int, date_from: str = Query(..., alias="from"), date_to: str = Query(..., alias="to"), limit: int = 200, ctx: OrgContext = Ctx, db: Session = Db, a: Access = Acc):
    return budgets.drilldown(db, ctx, a, account_id, _d(date_from, "from"), _d(date_to, "to"), limit)


# ---------------------------------------------------------------------------------------------------------------- cash flow forecasting
forecast_router = APIRouter()


@forecast_router.get("/forecast")
def get_forecast(as_at: Optional[str] = None, granularity: str = "week", periods: Optional[int] = None, ctx: OrgContext = Ctx, db: Session = Db, a: Access = Acc):
    out = forecast.build(db, ctx, a, _d(as_at, "as_at"), granularity, periods)
    return out


@forecast_router.post("/forecast/snapshots")
def save_snapshot(body: dict = Body(default={}), ctx: OrgContext = Ctx, db: Session = Db, a: Access = Acc):
    out = forecast.build(db, ctx, a, _d(body.get("as_at"), "as_at"), body.get("granularity", "week"), body.get("periods"), save=True, label=body.get("label", ""))
    db.commit()
    return out


@forecast_router.get("/forecast/snapshots")
def list_snapshots(ctx: OrgContext = Ctx, db: Session = Db, a: Access = Acc):
    return forecast.snapshots(db, ctx, a)


@forecast_router.get("/forecast/snapshots/{sid}")
def get_snapshot(sid: int, ctx: OrgContext = Ctx, db: Session = Db, a: Access = Acc):
    return forecast.snapshot_get(db, ctx, a, sid)


@forecast_router.get("/forecast/snapshots/{sid}/vs-actual")
def snapshot_vs_actual(sid: int, ctx: OrgContext = Ctx, db: Session = Db, a: Access = Acc):
    return forecast.vs_actual(db, ctx, a, sid)


# ---------------------------------------------------------------------------------------------------------------- budgeting
budget_router = APIRouter()


@budget_router.get("/budgets")
def list_budgets(include_archived: bool = False, ctx: OrgContext = Ctx, db: Session = Db, a: Access = Acc):
    out = budgets.listing(db, ctx, a, include_archived)
    db.commit()                                            # adopting pre-existing budgets writes workflow rows
    return out


@budget_router.post("/budgets")
def create_budget(body: dict = Body(...), ctx: OrgContext = Ctx, db: Session = Db, a: Access = Acc):
    out = budgets.create(db, ctx, a, body)
    db.commit()
    return out


@budget_router.get("/budgets/{bid}")
def get_budget(bid: int, ctx: OrgContext = Ctx, db: Session = Db, a: Access = Acc):
    return budgets.get(db, ctx, a, bid)


@budget_router.put("/budgets/{bid}/lines")
def put_budget_lines(bid: int, body: dict = Body(...), ctx: OrgContext = Ctx, db: Session = Db, a: Access = Acc):
    out = budgets.save_lines(db, ctx, a, bid, body.get("lines") or [])
    db.commit()
    return out


@budget_router.post("/budgets/{bid}/import")
def import_budget(bid: int, body: dict = Body(...), ctx: OrgContext = Ctx, db: Session = Db, a: Access = Acc):
    out = budgets.import_csv(db, ctx, a, bid, body.get("csv", ""), apply=bool(body.get("apply", True)), strict=bool(body.get("strict", True)))
    db.commit()
    return out


@budget_router.get("/budgets/{bid}/export")
def export_budget(bid: int, ctx: OrgContext = Ctx, db: Session = Db, a: Access = Acc):
    m = budgets._meta(db, ctx, bid)
    text = budgets.export_csv(db, ctx, a, bid)
    safe = "".join(ch if ch.isalnum() or ch in "-_" else "_" for ch in m.name)
    return Response(text, media_type="text/csv; charset=utf-8", headers={"Content-Disposition": f'attachment; filename="budget_{safe}.csv"', "X-Content-Type-Options": "nosniff"})


@budget_router.post("/budgets/{bid}/copy")
def copy_budget(bid: int, body: dict = Body(default={}), ctx: OrgContext = Ctx, db: Session = Db, a: Access = Acc):
    out = budgets.copy(db, ctx, a, bid, body.get("name"))
    db.commit()
    return out


@budget_router.post("/budgets/{bid}/submit")
def submit_budget(bid: int, ctx: OrgContext = Ctx, db: Session = Db, a: Access = Acc):
    out = budgets.submit(db, ctx, a, bid)
    db.commit()
    return out


@budget_router.post("/budgets/{bid}/approve")
def approve_budget(bid: int, ctx: OrgContext = Ctx, db: Session = Db, a: Access = Acc):
    out = budgets.approve(db, ctx, a, bid)
    db.commit()
    return out


@budget_router.post("/budgets/{bid}/reject")
def reject_budget(bid: int, body: dict = Body(default={}), ctx: OrgContext = Ctx, db: Session = Db, a: Access = Acc):
    out = budgets.reject(db, ctx, a, bid, body.get("note", ""))
    db.commit()
    return out


@budget_router.post("/budgets/{bid}/archive")
def archive_budget(bid: int, ctx: OrgContext = Ctx, db: Session = Db, a: Access = Acc):
    out = budgets.archive(db, ctx, a, bid)
    db.commit()
    return out


@budget_router.delete("/budgets/{bid}")
def delete_budget(bid: int, ctx: OrgContext = Ctx, db: Session = Db, a: Access = Acc):
    out = budgets.discard_draft(db, ctx, a, bid)
    db.commit()
    return out


@budget_router.get("/budgets/{bid}/vs-actual")
def budget_vs_actual(bid: int, date_from: Optional[str] = Query(None, alias="from"), date_to: Optional[str] = Query(None, alias="to"), ctx: OrgContext = Ctx, db: Session = Db, a: Access = Acc):
    return budgets.vs_actual(db, ctx, a, bid, _d(date_from, "from"), _d(date_to, "to"))


# ---------------------------------------------------------------------------------------------------------------- scenario planning
scenario_router = APIRouter()


@scenario_router.get("/scenarios/templates")
def scenario_templates(a: Access = Acc):
    return scenarios.templates()


@scenario_router.get("/scenarios")
def list_scenarios(include_archived: bool = False, ctx: OrgContext = Ctx, db: Session = Db, a: Access = Acc):
    return scenarios.listing(db, ctx, a, include_archived)


@scenario_router.post("/scenarios")
def create_scenario(body: dict = Body(...), ctx: OrgContext = Ctx, db: Session = Db, a: Access = Acc):
    out = scenarios.create(db, ctx, a, body)
    db.commit()
    return out


@scenario_router.post("/scenarios/compare")
def compare_scenarios(body: dict = Body(...), ctx: OrgContext = Ctx, db: Session = Db, a: Access = Acc):
    return scenarios.compare(db, ctx, a, [int(i) for i in body.get("ids", [])], _d(body.get("as_at"), "as_at"), body.get("reference"))


@scenario_router.put("/scenarios/{sid}")
def update_scenario(sid: int, body: dict = Body(...), ctx: OrgContext = Ctx, db: Session = Db, a: Access = Acc):
    out = scenarios.update(db, ctx, a, sid, body)
    db.commit()
    return out


@scenario_router.post("/scenarios/{sid}/duplicate")
def duplicate_scenario(sid: int, body: dict = Body(default={}), ctx: OrgContext = Ctx, db: Session = Db, a: Access = Acc):
    out = scenarios.duplicate(db, ctx, a, sid, body.get("name"))
    db.commit()
    return out


@scenario_router.post("/scenarios/{sid}/archive")
def archive_scenario(sid: int, ctx: OrgContext = Ctx, db: Session = Db, a: Access = Acc):
    out = scenarios.archive(db, ctx, a, sid)
    db.commit()
    return out


@scenario_router.post("/scenarios/{sid}/run")
def run_scenario(sid: int, body: dict = Body(default={}), ctx: OrgContext = Ctx, db: Session = Db, a: Access = Acc):
    out = scenarios.run(db, ctx, a, sid, _d(body.get("as_at"), "as_at"), save=bool(body.get("save", True)), compare_budget=body.get("compare_budget"))
    db.commit()
    return out


@scenario_router.get("/scenarios/{sid}/runs")
def scenario_runs(sid: int, ctx: OrgContext = Ctx, db: Session = Db, a: Access = Acc):
    return scenarios.runs(db, ctx, a, sid)


@scenario_router.get("/scenarios/{sid}/runs/{rid}")
def scenario_run_get(sid: int, rid: int, ctx: OrgContext = Ctx, db: Session = Db, a: Access = Acc):
    return scenarios.run_get(db, ctx, a, sid, rid)


@scenario_router.get("/scenarios/{sid}/sensitivity")
def scenario_sensitivity(sid: int, as_at: Optional[str] = None, ctx: OrgContext = Ctx, db: Session = Db, a: Access = Acc):
    return scenarios.sensitivity(db, ctx, a, sid, _d(as_at, "as_at"))


# ---------------------------------------------------------------------------------------------------------------- management reporting
report_router = APIRouter()


@report_router.get("/reports/snapshots")
def list_report_snapshots(kind: str = "", ctx: OrgContext = Ctx, db: Session = Db, a: Access = Acc):
    return reports.snapshots(db, ctx, a, kind)


@report_router.get("/reports/snapshots/{sid}")
def get_report_snapshot(sid: int, ctx: OrgContext = Ctx, db: Session = Db, a: Access = Acc):
    return reports.snapshot_get(db, ctx, a, sid)


def _report(kind, date_from, date_to, compare_from, compare_to, budget_id, snapshot_id, scenario_ids, ctx, db, a):
    ids = [int(x) for x in scenario_ids.split(",") if x.strip().isdigit()] if scenario_ids else None
    return reports.generate(db, ctx, a, kind, _d(date_from, "from"), _d(date_to, "to"), _d(compare_from, "compare_from"), _d(compare_to, "compare_to"), budget_id, snapshot_id, ids)


@report_router.get("/reports/{kind}")
def get_report(kind: str, date_from: Optional[str] = Query(None, alias="from"), date_to: Optional[str] = Query(None, alias="to"), compare_from: Optional[str] = None, compare_to: Optional[str] = None,
               budget_id: Optional[int] = None, snapshot_id: Optional[int] = None, scenario_ids: Optional[str] = None, ctx: OrgContext = Ctx, db: Session = Db, a: Access = Acc):
    return _report(kind, date_from, date_to, compare_from, compare_to, budget_id, snapshot_id, scenario_ids, ctx, db, a)


@report_router.post("/reports/{kind}/snapshot")
def snapshot_report(kind: str, body: dict = Body(default={}), ctx: OrgContext = Ctx, db: Session = Db, a: Access = Acc):
    rep = _report(kind, body.get("from"), body.get("to"), body.get("compare_from"), body.get("compare_to"), body.get("budget_id"), body.get("snapshot_id"), None, ctx, db, a)
    out = reports.snapshot_save(db, ctx, a, rep, body.get("note", ""))
    db.commit()
    return out


@report_router.get("/reports/{kind}/export")
def export_report(kind: str, fmt: str = Query("csv", alias="format"), date_from: Optional[str] = Query(None, alias="from"), date_to: Optional[str] = Query(None, alias="to"), compare_from: Optional[str] = None,
                  compare_to: Optional[str] = None, budget_id: Optional[int] = None, snapshot_id: Optional[int] = None, scenario_ids: Optional[str] = None,
                  ctx: OrgContext = Ctx, db: Session = Db, a: Access = Acc):
    rep = _report(kind, date_from, date_to, compare_from, compare_to, budget_id, snapshot_id, scenario_ids, ctx, db, a)
    name = f"{kind}_{rep['period_from']}_{rep['period_to']}"
    core.audit(db, ctx, "report.export", "report", kind, format=fmt, period_from=rep["period_from"], period_to=rep["period_to"])
    db.commit()
    if fmt == "csv":
        return Response(reports.export_csv(rep), media_type="text/csv; charset=utf-8", headers={"Content-Disposition": f'attachment; filename="{name}.csv"', "X-Content-Type-Options": "nosniff"})
    if fmt == "xlsx":
        return Response(reports.export_xlsx(rep), media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", headers={"Content-Disposition": f'attachment; filename="{name}.xlsx"', "X-Content-Type-Options": "nosniff"})
    raise core.PlanError("format must be csv or xlsx (use the browser's Print > Save as PDF for a PDF)")


# ---------------------------------------------------------------------------------------------------------------- CFO insights
insight_router = APIRouter()


@insight_router.get("/insights")
def get_insights(date_from: Optional[str] = Query(None, alias="from"), date_to: Optional[str] = Query(None, alias="to"), ctx: OrgContext = Ctx, db: Session = Db, a: Access = Acc):
    return insights.evaluate(db, ctx, a, _d(date_from, "from"), _d(date_to, "to"))


@insight_router.put("/insights/config")
def put_insight_config(body: dict = Body(...), ctx: OrgContext = Ctx, db: Session = Db, a: Access = Acc):
    out = insights.save_config(db, ctx, a, body.get("thresholds"), body.get("benchmarks"))
    db.commit()
    return out


# ---------------------------------------------------------------------------------------------------------------- AI financial assistant
assistant_router = APIRouter()


@assistant_router.post("/assistant/ask")
def ask(body: dict = Body(...), ctx: OrgContext = Ctx, db: Session = Db, a: Access = Acc):
    out = assistant.ask(db, ctx, a, str(body.get("question", "")))
    db.commit()
    return out


@assistant_router.get("/assistant/suggestions")
def suggestions(a: Access = Acc):
    return dict(suggestions=assistant.SUGGESTIONS, label=assistant.LABEL, read_only=True, limit_per_hour=assistant.rate_limit())


@assistant_router.get("/assistant/history")
def ai_history(ctx: OrgContext = Ctx, db: Session = Db, a: Access = Acc):
    return assistant.history(db, ctx, a)


# ---------------------------------------------------------------------------------------------------------------- risk & anomaly detection
risk_router = APIRouter()


@risk_router.get("/risk/alerts")
def list_alerts(status: str = "", severity: str = "", rule: str = "", ctx: OrgContext = Ctx, db: Session = Db, a: Access = Acc):
    return risk.listing(db, ctx, a, status, severity, rule)


@risk_router.get("/risk/preview")
def preview_alerts(as_at: Optional[str] = None, ctx: OrgContext = Ctx, db: Session = Db, a: Access = Acc):
    return risk.detect(db, ctx, a, _d(as_at, "as_at"))


@risk_router.post("/risk/scan")
def scan_alerts(body: dict = Body(default={}), ctx: OrgContext = Ctx, db: Session = Db, a: Access = Acc):
    out = risk.scan(db, ctx, a, _d(body.get("as_at"), "as_at"))
    db.commit()
    return out


@risk_router.post("/risk/alerts/{aid}/review")
def review_alert(aid: int, body: dict = Body(...), ctx: OrgContext = Ctx, db: Session = Db, a: Access = Acc):
    out = risk.review(db, ctx, a, aid, body.get("status", ""), body.get("note", ""))
    db.commit()
    return out


@risk_router.get("/risk/config")
def get_risk_config(ctx: OrgContext = Ctx, db: Session = Db, a: Access = Acc):
    return dict(thresholds=risk.config(db, ctx))


@risk_router.put("/risk/config")
def put_risk_config(body: dict = Body(...), ctx: OrgContext = Ctx, db: Session = Db, a: Access = Acc):
    out = risk.save_config(db, ctx, a, body.get("thresholds") or {})
    db.commit()
    return out
