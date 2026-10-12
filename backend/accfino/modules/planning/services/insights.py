"""CFO insights service: gathers facts from the ledger/reports/forecast, runs the rule engine, attaches only cited benchmarks. Read-only."""
import datetime as dt
from collections import defaultdict
from decimal import Decimal
from typing import Optional

import accfino.modules.accounting.public as acc
from accfino.modules.planning.engine import insights as IE
from accfino.modules.planning.engine.money import D, q2, s, pct, ZERO
from . import budgets, core, forecast as FC, reports as RP


def _month_back(d: dt.date, n: int) -> dt.date:
    y, m = d.year, d.month - n
    while m < 1:
        y, m = y - 1, m + 12
    return dt.date(y, m, 1)


def gather_facts(db, ctx, a, df: dt.date, dt_: dt.date, with_forecast: bool = True) -> dict:
    cdf, cdt = RP._prior_period(df, dt_)
    cur, prev = acc.profit_and_loss(db, ctx.org, df, dt_), acc.profit_and_loss(db, ctx.org, cdf, cdt)
    direct = lambda p: sum((D(r["amount"]) for r in p["expenses"] if r["type"] == "direct_costs"), ZERO)
    rev, prv = D(cur["revenue_total"]), D(prev["revenue_total"])
    cs = acc.cash_summary(db, ctx.org, df, dt_)
    # burn: average net cash outflow over the last 3 complete months
    hist = acc.ledger_activity_dates(db, ctx.org.id, exclude_source_types=("opening_balance",))
    m_end = dt.date(dt_.year, dt_.month, 1) - dt.timedelta(days=1)
    m_start = _month_back(dt_, 3)
    burn = None
    months_hist = hist["months"]
    if hist["first"] and hist["first"] <= m_start:
        c3 = acc.cash_summary(db, ctx.org, m_start, m_end)
        burn = (-D(c3["net_movement"]) / 3) if c3["has_bank"] else None
    recon = acc.bank_reconciliation_status(db, ctx.org, dt_)
    ar_open = [i for i in acc.open_items(db, ctx.org, dt_) if i["side"] == "receivable"]
    ar_total = sum((i["amount"] for i in ar_open), ZERO)
    ar_over = sum((i["amount"] for i in ar_open if i["days_overdue"] > 0), ZERO)
    # concentration: revenue lines carry the customer name
    by = defaultdict(lambda: ZERO)
    attributed = ZERO
    for ln in acc.ledger_lines(db, ctx.org.id, df, dt_, account_classes=("revenue",), limit=50000):
        v = ln["credit"] - ln["debit"]
        if ln["contact_name"]:
            by[ln["contact_name"]] += v
            attributed += v
    top = None
    if rev > 0 and attributed >= rev * Decimal("0.5") and by:
        nm, v = max(by.items(), key=lambda kv: (kv[1], kv[0]))
        top = dict(name=nm, pct=str(pct(v, rev)))
    bs = acc.balance_sheet(db, ctx.org, dt_)
    ca = sum((D(r["amount"]) for k in RP.CURRENT_BANK for r in bs["assets"].get(k, [])), ZERO)
    cl = sum((D(r["amount"]) for k in RP.CURRENT_LIAB for r in bs["liabilities"].get(k, [])), ZERO)
    bp = None
    m = RP._default_budget(db, ctx, df, dt_)
    if m is not None:
        try:
            v = budgets.vs_actual(db, ctx, a, m.id, max(df, m.fy_start), dt_)
            if v["totals"]:
                bp = dict(budget=v["totals"]["profit"]["budget"], actual=v["totals"]["profit"]["actual"], variance=v["totals"]["profit"]["variance"], name=m.name)
        except core.PlanError:
            bp = None
    sf = None
    if with_forecast:
        fc = FC.build(db, ctx, a, as_at=min(dt_, core.business_today()))
        sf = dict(max_shortfall=fc["shortfall"]["max_shortfall"], goes_negative=fc["shortfall"]["goes_negative"], minimum=fc["minimum"]["balance"], threshold=fc["threshold"], label=fc["minimum"]["label"], confidence=fc["confidence"]["level"])
    per = f"{df.isoformat()} to {dt_.isoformat()}"
    return dict(period=per, prior_period=f"{cdf.isoformat()} to {cdt.isoformat()}", revenue=cur["revenue_total"], prior_revenue=prev["revenue_total"], expenses=cur["expense_total"], prior_expenses=prev["expense_total"],
                net_profit=cur["net_profit"], prior_profit=prev["net_profit"],
                gross_margin_pct=None if rev <= 0 else str(pct(rev - direct(cur), rev)), prior_gross_margin_pct=None if prv <= 0 else str(pct(prv - direct(prev), prv)),
                cash_closing=cs["closing_cash"] if cs["has_bank"] else None, avg_monthly_burn=None if burn is None else s(burn), months_of_history=months_hist,
                ar_total=s(ar_total), ar_overdue=s(ar_over), top_customer_share=top, current_assets=s(ca), current_liabilities=s(cl), budget_profit=bp, forecast_shortfall=sf,
                data_quality=dict(unreconciled_bank_lines=sum(r["unreconciled_count"] for r in recon), suspense_balance=acc.system_account_balance(db, ctx.org, "suspense", dt_)),
                sources=dict(pl=f"Profit and loss {per} (ledger)", cash=f"Cash summary / bank balances {per} (ledger)", ar=f"Open invoices at {dt_.isoformat()} (sub-ledger)", bs=f"Balance sheet at {dt_.isoformat()} (ledger)",
                             budget=f"Budget vs actual {per}", forecast="13-week cash forecast (see Cash Flow)"))


BENCHMARK_METRICS = ("gross_margin_pct", "net_margin_pct")


def evaluate(db, ctx, a, df=None, dt_=None) -> dict:
    a.require("view")
    dt_ = dt_ or core.business_today()
    df = df or core.fy_start_for(ctx.org, dt_)
    if df > dt_:
        raise core.PlanError("from must not be after to")
    st = core.settings(db, ctx)
    facts = gather_facts(db, ctx, a, df, dt_)
    items = IE.evaluate(facts, st.insight_cfg or {})
    bm = []
    net_margin = pct(D(facts.get("net_profit", 0)), D(facts.get("revenue", 0)))
    for b in (st.benchmarks or []):
        metric = b["metric"]
        mine = {"gross_margin_pct": facts.get("gross_margin_pct"), "net_margin_pct": None if net_margin is None else str(net_margin)}.get(metric)
        if mine is not None:
            bm.append(dict(b, your_value=mine, period=facts["period"]))
    return dict(kind="cfo_insights", basis="ACTUAL-derived rule results", **core.stamp(ctx, period_from=df.isoformat(), period_to=dt_.isoformat(), source="ledger, budgets and cash forecast"),
                ruleset=IE.RULESET_VERSION, insights=items, counts={sv: sum(1 for i in items if i["severity"] == sv) for sv in ("high", "medium", "low", "info")},
                benchmarks=bm, benchmark_note=("Benchmarks shown are organisation-configured entries with a cited source." if st.benchmarks else
                                               "No industry benchmarks are shown: AccFino has no verified, cited benchmark source configured. Add one with its source URL in Settings to enable comparison."),
                thresholds=dict(IE.DEFAULTS, **(st.insight_cfg or {})), facts_used={k: v for k, v in facts.items() if k not in ("sources",)})


def save_config(db, ctx, a, cfg: Optional[dict], benchmarks: Optional[list]) -> dict:
    a.require("config")
    st = core.settings(db, ctx)
    if cfg is not None:
        bad = [k for k in cfg if k not in IE.DEFAULTS]
        if bad:
            raise core.PlanError(f"Unknown insight setting(s): {', '.join(bad)}")
        clean = {}
        for k, v in cfg.items():
            try:
                d = D(v)
            except ValueError:
                raise core.PlanError(f"{k} must be a number")
            if d < 0 or d > 1_000_000:
                raise core.PlanError(f"{k} must be between 0 and 1,000,000")
            clean[k] = float(d) if d % 1 else int(d)
        st.insight_cfg = clean
    if benchmarks is not None:
        try:
            clean_bm = IE.validate_benchmarks(benchmarks)
        except ValueError as e:
            raise core.PlanError(str(e))
        bad = [b["metric"] for b in clean_bm if b["metric"] not in BENCHMARK_METRICS]
        if bad:
            raise core.PlanError(f"Benchmark metric must be one of {', '.join(BENCHMARK_METRICS)} (AccFino can only compare metrics it calculates); got {', '.join(bad)}")
        st.benchmarks = clean_bm
    db.flush()
    core.audit(db, ctx, "insights.config", "plan_settings", ctx.org.id, insight_cfg=st.insight_cfg, benchmarks=len(st.benchmarks or []))
    return dict(insight_cfg=st.insight_cfg or {}, benchmarks=st.benchmarks or [])
