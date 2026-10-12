"""Management reporting: P&L, balance sheet, cash, budget vs actual, ageing, working capital, KPIs, forecast vs actual, scenario comparison and a board pack.
Everything is computed from the ledger through existing report functions; identical inputs give identical outputs (the payload carries no generation timestamp).
These are MANAGEMENT reports, not statutory financial statements."""
import csv
import datetime as dt
import io
from decimal import Decimal
from typing import List, Optional

import accfino.modules.accounting.public as acc
from accfino.modules.planning.engine.money import D, q2, s, pct, ZERO
from accfino.modules.planning.models import plan as P
from . import budgets, core, forecast as FC, scenarios as SC

DISCLAIMER = "Management report: prepared from the AccFino ledger for internal decision-making. It is not a statutory financial statement and has not been audited or reviewed."
CURRENT_BANK = ("bank", "current_asset", "inventory")
CURRENT_LIAB = ("credit_card", "current_liability")


def _days(df, dt_):
    return (dt_ - df).days + 1


def _prior_period(df, dt_):
    n = _days(df, dt_)
    return df - dt.timedelta(days=n), df - dt.timedelta(days=1)


def _base(ctx, kind, title, df, dt_, cdf=None, cdt=None, source="ledger"):
    return dict(kind=kind, title=title, disclaimer=DISCLAIMER, basis="ACTUAL (ledger)", **core.stamp(ctx, period_from=df.isoformat(), period_to=dt_.isoformat(),
                comparison_from=cdf.isoformat() if cdf else None, comparison_to=cdt.isoformat() if cdt else None, source=source), flags=[])


def _flags(db, ctx, rep, df, dt_):
    """Stale / incomplete data markers that travel with the report."""
    st = core.settings(db, ctx)
    today = core.business_today()
    recon = acc.bank_reconciliation_status(db, ctx.org, dt_)
    unrec = sum(r["unreconciled_count"] for r in recon)
    if unrec:
        rep["flags"].append(dict(code="unreconciled", text=f"{unrec} bank lines up to {dt_.isoformat()} are not reconciled; cash-based figures may change."))
    last = max([r["last_line_date"] for r in recon if r["last_line_date"]], default=None)
    if last and (min(dt_, today) - last).days > st.stale_days:
        rep["flags"].append(dict(code="stale", text=f"Bank data is stale: the latest imported bank line is {last.isoformat()}."))
    if dt_ > today:
        rep["flags"].append(dict(code="future", text="The period ends in the future; figures include only what is posted today (incomplete)."))
    act = acc.ledger_activity_dates(db, ctx.org.id)
    point_in_time = df == dt_                       # balance sheet / ageing: "as at" a date, so only activity BEFORE the date matters
    if act["first"] is None or act["first"] > dt_ or (not point_in_time and act["last"] < df):
        rep["flags"].append(dict(code="no_data", text="There is no ledger activity in this period." if not point_in_time else "There is no ledger activity on or before this date."))
    return rep


def _merge_pl(cur, prev):
    rows = {}
    for kind in ("revenue", "expenses"):
        for r in cur[kind]:
            rows.setdefault((kind, r["code"]), dict(section=kind, code=r["code"], name=r["name"], current=D(r["amount"]), previous=ZERO))
        for r in (prev or {}).get(kind, []):
            e = rows.setdefault((kind, r["code"]), dict(section=kind, code=r["code"], name=r["name"], current=ZERO, previous=ZERO))
            e["previous"] = D(r["amount"])
    out = []
    for (kind, code), r in sorted(rows.items(), key=lambda kv: (kv[0][0] != "revenue", kv[0][1])):
        ch = r["current"] - r["previous"]
        out.append(dict(section=r["section"], code=code, name=r["name"], current=s(r["current"]), previous=s(r["previous"]) if prev else None, change=s(ch) if prev else None,
                        change_pct=(None if not prev or r["previous"] == 0 else str(pct(ch, abs(r["previous"]))))))
    return out


def profit_loss(db, ctx, a, df, dt_, cdf=None, cdt=None) -> dict:
    a.require("view")
    cur = acc.profit_and_loss(db, ctx.org, df, dt_)
    cdf, cdt = (cdf, cdt) if cdf and cdt else _prior_period(df, dt_)
    prev = acc.profit_and_loss(db, ctx.org, cdf, cdt)
    rep = _base(ctx, "profit_loss", "Profit and loss", df, dt_, cdf, cdt, "ledger journals (posted)")
    rep.update(rows=_merge_pl(cur, prev), totals=dict(revenue=dict(current=cur["revenue_total"], previous=prev["revenue_total"]), expenses=dict(current=cur["expense_total"], previous=prev["expense_total"]),
                                                          net_profit=dict(current=cur["net_profit"], previous=prev["net_profit"])))
    return _flags(db, ctx, rep, df, dt_)


def balance_sheet(db, ctx, a, as_at, compare_at=None) -> dict:
    a.require("view")
    cur = acc.balance_sheet(db, ctx.org, as_at)
    prev = acc.balance_sheet(db, ctx.org, compare_at) if compare_at else None
    rep = _base(ctx, "balance_sheet", "Balance sheet", as_at, as_at, None, compare_at, "ledger journals (posted)")
    rep["period_from"] = as_at.isoformat()
    rep.update(current=cur, comparison=prev, totals=dict(assets=cur["total_assets"], liabilities=cur["total_liabilities"], net_assets=cur["net_assets"], equity=cur["total_equity"], balanced=cur["balanced"]))
    if not cur["balanced"]:
        rep["flags"].append(dict(code="unbalanced", text="Assets less liabilities do not equal equity: contact support, this should not happen in a double-entry ledger."))
    return _flags(db, ctx, rep, as_at, as_at)


def cash(db, ctx, a, df, dt_) -> dict:
    a.require("view")
    cs = acc.cash_summary(db, ctx.org, df, dt_)
    rep = _base(ctx, "cash", "Cash summary", df, dt_, source="ledger bank accounts")
    rep.update(summary={k: cs[k] for k in ("opening_cash", "closing_cash", "total_receipts", "total_payments", "net_movement", "reconciled", "difference")}, months=cs["months"], sections=cs["sections"], has_bank=cs["has_bank"])
    if not cs["has_bank"]:
        rep["flags"].append(dict(code="no_bank", text="No bank account exists in the ledger."))
    return _flags(db, ctx, rep, df, dt_)


def ageing(db, ctx, a, as_at) -> dict:
    a.require("view")
    out = {}
    for side in ("sales", "purchases"):
        ag = acc.aged_report(db, ctx.org, side, as_at)
        out[side] = dict(totals=ag.get("totals"), buckets=ag.get("buckets"), total=ag.get("total"), control=ag.get("control"), contacts=[dict(contact=c["contact"], total=c.get("total"), buckets={k: c.get(k) for k in (ag.get("buckets") or {})}, docs=c.get("docs", [])[:50]) for c in ag["contacts"]][:100])
    rep = _base(ctx, "ageing", "Receivables and payables ageing", as_at, as_at, source="sub-ledger documents with control-account reconciliation")
    rep["period_from"] = as_at.isoformat()
    rep.update(receivables=out["sales"], payables=out["purchases"])
    return _flags(db, ctx, rep, as_at, as_at)


def _bs_group(bs, kinds, section):
    return sum((D(r["amount"]) for k in kinds for r in bs[section].get(k, [])), ZERO)


def working_capital(db, ctx, a, df, dt_) -> dict:
    a.require("view")
    bs = acc.balance_sheet(db, ctx.org, dt_)
    pl = acc.profit_and_loss(db, ctx.org, df, dt_)
    ca = _bs_group(bs, CURRENT_BANK, "assets")
    cl = _bs_group(bs, CURRENT_LIAB, "liabilities")
    cashv = _bs_group(bs, ("bank",), "assets")
    inv = _bs_group(bs, ("inventory",), "assets")
    ar = D(acc.aged_report(db, ctx.org, "sales", dt_).get("total") or 0)
    ap = D(acc.aged_report(db, ctx.org, "purchases", dt_).get("total") or 0)
    rev, exp = D(pl["revenue_total"]), D(pl["expense_total"])
    n = _days(df, dt_)
    dso = (ar / rev * n).quantize(Decimal("0.1")) if rev > 0 else None
    dpo = (ap / exp * n).quantize(Decimal("0.1")) if exp > 0 else None
    rep = _base(ctx, "working_capital", "Working capital", df, dt_, source="balance sheet + ageing + profit and loss")
    rep.update(metrics=dict(current_assets=s(ca), current_liabilities=s(cl), net_working_capital=s(ca - cl), current_ratio=None if cl <= 0 else str((ca / cl).quantize(Decimal("0.01"))),
                            quick_ratio=None if cl <= 0 else str(((ca - inv) / cl).quantize(Decimal("0.01"))), cash=s(cashv), receivables=s(ar), payables=s(ap),
                            dso_days=None if dso is None else str(dso), dpo_days=None if dpo is None else str(dpo)),
               definitions=dict(current_assets="bank + current assets + inventory accounts", current_liabilities="credit cards + current liabilities", dso="receivables / revenue x days in period", dpo="payables / expenses x days in period",
                                quick_ratio="(current assets - inventory) / current liabilities"))
    return _flags(db, ctx, rep, df, dt_)


def kpis(db, ctx, a, df, dt_, cdf=None, cdt=None) -> dict:
    a.require("view")
    cdf, cdt = (cdf, cdt) if cdf and cdt else _prior_period(df, dt_)
    cur, prev = acc.profit_and_loss(db, ctx.org, df, dt_), acc.profit_and_loss(db, ctx.org, cdf, cdt)
    cs = acc.cash_summary(db, ctx.org, df, dt_)
    wc = working_capital(db, ctx, a, df, dt_)["metrics"]

    def direct(p):
        return sum((D(r["amount"]) for r in p["expenses"] if r["type"] == "direct_costs"), ZERO)

    def mk(label, value, prior=None, unit="AUD", calc=""):
        return dict(label=label, value=value, previous=prior, unit=unit, calculation=calc)
    rev, prv = D(cur["revenue_total"]), D(prev["revenue_total"])
    gm = pct(rev - direct(cur), rev)
    pgm = pct(prv - direct(prev), prv)
    nm, pnm = pct(D(cur["net_profit"]), rev), pct(D(prev["net_profit"]), prv)
    items = [mk("Revenue", cur["revenue_total"], prev["revenue_total"], calc="sum of revenue accounts"), mk("Net profit", cur["net_profit"], prev["net_profit"], calc="revenue - expenses"),
             mk("Gross margin %", None if gm is None else str(gm), None if pgm is None else str(pgm), "%", "(revenue - direct costs) / revenue"),
             mk("Net margin %", None if nm is None else str(nm), None if pnm is None else str(pnm), "%", "net profit / revenue"),
             mk("Net cash movement", cs["net_movement"], None, calc="bank receipts - bank payments"), mk("Closing cash", cs["closing_cash"], None, calc="ledger bank balance at period end"),
             mk("Current ratio", wc["current_ratio"], None, "x", "current assets / current liabilities"), mk("DSO (days)", wc["dso_days"], None, "days", "receivables / revenue x days"),
             mk("DPO (days)", wc["dpo_days"], None, "days", "payables / expenses x days")]
    rep = _base(ctx, "kpis", "Key performance indicators", df, dt_, cdf, cdt, "profit and loss + cash summary + balance sheet")
    rep["kpis"] = items
    return _flags(db, ctx, rep, df, dt_)


def commentary(rep: dict) -> List[str]:
    """Deterministic commentary: each sentence restates figures already in the report. Nothing is inferred beyond the arithmetic."""
    out, k = [], rep["kind"]
    per = f"{rep['period_from']} to {rep['period_to']}"
    if k == "profit_loss":
        t = rep["totals"]
        out.append(f"Revenue for {per} was {t['revenue']['current']} (prior period {t['revenue']['previous']}); expenses were {t['expenses']['current']} (prior {t['expenses']['previous']}); net profit was {t['net_profit']['current']} (prior {t['net_profit']['previous']}).")
        moves = sorted([r for r in rep["rows"] if r["change"] is not None and D(r["change"]) != 0], key=lambda r: (-abs(D(r["change"])), r["code"]))[:3]
        for r in moves:
            out.append(f"{r['code']} {r['name']} moved by {r['change']} to {r['current']}.")
    elif k == "cash":
        m = rep["summary"]
        out.append(f"Cash moved from {m['opening_cash']} to {m['closing_cash']} ({m['net_movement']} net) over {per}: receipts {m['total_receipts']}, payments {m['total_payments']}.")
    elif k == "budget_vs_actual":
        p = rep["totals"]["profit"]
        out.append(f"Profit was {p['actual']} against a budget of {p['budget']} for {per} (variance {p['variance']}; positive is favourable).")
    elif k == "kpis":
        for i in rep["kpis"][:2]:
            out.append(f"{i['label']}: {i['value']} (prior {i['previous']}).")
    elif k == "working_capital":
        m = rep["metrics"]
        out.append(f"Net working capital was {m['net_working_capital']}; current ratio {m['current_ratio'] or 'n/a (no current liabilities)'}; receivables {m['receivables']}, payables {m['payables']}.")
    for f in rep.get("flags", []):
        out.append("Data note: " + f["text"])
    return out


def _default_budget(db, ctx, df, dt_):
    for m in db.query(P.PlanBudget).filter(P.PlanBudget.org_id == ctx.org.id, P.PlanBudget.status == "approved").order_by(P.PlanBudget.fy_start.desc(), P.PlanBudget.version.desc()):
        if m.fy_start <= df and df < dt.date(m.fy_start.year + 1, m.fy_start.month, 1):
            return m
    return None


def generate(db, ctx, a, kind: str, date_from=None, date_to=None, compare_from=None, compare_to=None, budget_id=None, snapshot_id=None, scenario_ids=None) -> dict:
    a.require("view")
    today = core.business_today()
    dt_ = date_to or today
    df = date_from or core.fy_start_for(ctx.org, dt_)
    if df > dt_:
        raise core.PlanError("from must not be after to")
    if (dt_ - df).days > 3660:
        raise core.PlanError("The period is too long (max 10 years)")
    if kind == "profit_loss":
        rep = profit_loss(db, ctx, a, df, dt_, compare_from, compare_to)
    elif kind == "balance_sheet":
        rep = balance_sheet(db, ctx, a, dt_, compare_to)
    elif kind == "cash":
        rep = cash(db, ctx, a, df, dt_)
    elif kind == "ageing":
        rep = ageing(db, ctx, a, dt_)
    elif kind == "working_capital":
        rep = working_capital(db, ctx, a, df, dt_)
    elif kind == "kpis":
        rep = kpis(db, ctx, a, df, dt_, compare_from, compare_to)
    elif kind == "budget_vs_actual":
        m = db.query(P.PlanBudget).filter_by(org_id=ctx.org.id, id=budget_id).first() if budget_id else _default_budget(db, ctx, df, dt_)
        if m is None:
            rep = _base(ctx, "budget_vs_actual", "Budget vs actual", df, dt_, source="Accounting budget lines")
            rep.update(rows=[], totals=None, flags=[dict(code="no_budget", text="No approved budget covers this period. Create and approve one in Budgeting.")])
        else:
            rep = budgets.vs_actual(db, ctx, a, m.id, max(df, m.fy_start), dt_)
            rep.update(title="Budget vs actual", disclaimer=DISCLAIMER, flags=[])
            _flags(db, ctx, rep, df, dt_)
    elif kind == "forecast_vs_actual":
        snap = FC.latest_snapshot(db, ctx) if not snapshot_id else None
        sid = snapshot_id or (snap.id if snap else None)
        rep = _base(ctx, "forecast_vs_actual", "Forecast vs actual", df, dt_, source="stored forecast snapshot vs ledger bank movements")
        if sid is None:
            rep.update(rows=[], compared=0, flags=[dict(code="no_snapshot", text="No forecast snapshot has been saved yet. Save one in Cash Flow to track accuracy.")])
        else:
            va = FC.vs_actual(db, ctx, a, sid, today)
            rep.update(snapshot_id=sid, rows=va["rows"], compared=va["compared"], mae_net=va["mae_net"], bias_net=va["bias_net"], mae_closing=va["mae_closing"], note=va["note"], basis="ACTUAL vs FORECAST")
    elif kind == "scenario_comparison":
        rep = _base(ctx, "scenario_comparison", "Scenario comparison", df, dt_, source="scenario engine")
        ids = list(scenario_ids or [])
        if not ids:                                  # default selection: the first three scenarios that can actually run (one with an expired base must not blank the report)
            for x in SC.listing(db, ctx, a):
                try:
                    SC.run(db, ctx, a, x["id"], as_at=dt_, save=False)
                except core.PlanError as e:
                    rep["flags"].append(dict(code="scenario_skipped", text=f"Scenario '{x['name']}' was left out: {e.message}"))
                    continue
                ids.append(x["id"])
                if len(ids) == 3:
                    break
        if len(ids) < 2:
            rep["rows"] = []
            rep["flags"].append(dict(code="few_scenarios", text="Create at least two scenarios that can run to compare them."))
        else:
            cmp_ = SC.compare(db, ctx, a, list(ids), dt_)
            rep.update(rows=cmp_["rows"], reference=cmp_["reference"], limitations=cmp_["limitations"], basis="SCENARIO (hypothetical)")
    elif kind == "board_pack":
        return board_pack(db, ctx, a, df, dt_, compare_from, compare_to, budget_id)
    else:
        raise core.PlanError(f"Unknown report '{kind}'")
    rep["commentary"] = commentary(rep)
    rep["input_hash"] = core.digest({k: v for k, v in rep.items() if k != "commentary"})
    return rep


def board_pack(db, ctx, a, df, dt_, cdf=None, cdt=None, budget_id=None) -> dict:
    sections = [generate(db, ctx, a, k, df, dt_, cdf, cdt, budget_id) for k in ("kpis", "profit_loss", "balance_sheet", "cash", "budget_vs_actual", "working_capital", "ageing")]
    fc = FC.build(db, ctx, a, as_at=min(dt_, core.business_today()), granularity="week")
    pack = _base(ctx, "board_pack", f"Board pack {df.isoformat()} to {dt_.isoformat()}", df, dt_, source="ledger + budgets + cash forecast")
    pack["sections"] = sections
    pack["forecast"] = dict(basis="FORECAST", as_at=fc["as_at"], closing=fc["closing"], minimum=fc["minimum"], confidence=fc["confidence"], shortfall=fc["shortfall"], warnings=fc["warnings"])
    pack["flags"] = [f for sct in sections for f in sct.get("flags", [])]
    seen, uniq = set(), []
    for f in pack["flags"]:
        if f["text"] not in seen:
            seen.add(f["text"])
            uniq.append(f)
    pack["flags"] = uniq
    pack["commentary"] = [c for sct in sections for c in sct.get("commentary", [])]
    pack["input_hash"] = core.digest({k: v for k, v in pack.items() if k not in ("commentary",)})
    return pack


# ------------------------------------------------------------------------------------------------------------------------ snapshots and export
def snapshot_save(db, ctx, a, rep: dict, note: str = "") -> dict:
    a.require("edit")
    r = P.PlanReportSnapshot(org_id=ctx.org.id, kind=rep["kind"], title=rep["title"][:200], period_from=dt.date.fromisoformat(rep["period_from"]), period_to=dt.date.fromisoformat(rep["period_to"]),
                             params=None, payload=core.plain(rep), input_hash=rep["input_hash"], commentary=(note or "")[:4000] or None, created_by=ctx.user_id)
    db.add(r)
    db.flush()
    core.audit(db, ctx, "report.snapshot", "plan_report_snapshot", r.id, kind=rep["kind"], period_from=rep["period_from"], period_to=rep["period_to"], input_hash=rep["input_hash"])
    return dict(id=r.id, kind=r.kind, title=r.title, input_hash=r.input_hash)


def snapshots(db, ctx, a, kind: str = "") -> List[dict]:
    a.require("view")
    q = db.query(P.PlanReportSnapshot).filter_by(org_id=ctx.org.id)
    if kind:
        q = q.filter(P.PlanReportSnapshot.kind == kind)
    return [dict(id=r.id, kind=r.kind, title=r.title, period_from=r.period_from.isoformat(), period_to=r.period_to.isoformat(), input_hash=r.input_hash, created_at=r.created_at.isoformat(), note=r.commentary)
            for r in q.order_by(P.PlanReportSnapshot.id.desc()).limit(100)]


def snapshot_get(db, ctx, a, sid: int) -> dict:
    a.require("view")
    r = db.query(P.PlanReportSnapshot).filter_by(org_id=ctx.org.id, id=sid).first()
    if r is None:
        raise core.NotFound("Report snapshot")
    return dict(r.payload, snapshot_id=r.id, frozen=True, snapshot_note=r.commentary, snapshot_at=r.created_at.isoformat())


def _flatten(rep: dict) -> List[List[str]]:
    rows: List[List[str]] = [[rep["title"]], [DISCLAIMER], ["Organisation", rep.get("organisation", "")], ["Currency", rep.get("currency", "")], ["Period", f"{rep.get('period_from')} to {rep.get('period_to')}"], ["Source", rep.get("source", "")], []]
    k = rep["kind"]

    def table(head, data):
        rows.append(head)
        rows.extend(data)
        rows.append([])
    if k == "profit_loss":
        table(["Section", "Code", "Account", "Current", "Previous", "Change"], [[r["section"], r["code"], r["name"], r["current"], r["previous"], r["change"]] for r in rep["rows"]])
        table(["Total", "Current", "Previous"], [[n, v["current"], v["previous"]] for n, v in rep["totals"].items()])
    elif k == "balance_sheet":
        cur = rep["current"]
        data = [[g, r["code"], r["name"], r["amount"]] for sec in ("assets", "liabilities") for g, rs in cur[sec].items() for r in rs] + [["equity", r["code"], r["name"], r["amount"]] for r in cur["equity"]]
        table(["Group", "Code", "Account", "Amount"], data)
        table(["Total", "Amount"], [["Assets", cur["total_assets"]], ["Liabilities", cur["total_liabilities"]], ["Equity", cur["total_equity"]]])
    elif k == "cash":
        table(["Month", "Receipts", "Payments", "Net", "Closing"], [[m["month"], m["receipts"], m["payments"], m["net"], m["closing"]] for m in rep["months"]])
    elif k == "budget_vs_actual":
        table(["Code", "Account", "Budget", "Actual", "Variance", "Variance %"], [[r["code"], r["name"], r["budget"], r["actual"], r["variance"], r["variance_pct"]] for r in rep.get("rows", [])])
    elif k == "kpis":
        table(["KPI", "Value", "Previous", "Unit", "Calculation"], [[i["label"], i["value"], i["previous"], i["unit"], i["calculation"]] for i in rep["kpis"]])
    elif k == "working_capital":
        table(["Metric", "Value"], [[n, v] for n, v in rep["metrics"].items()])
    elif k == "ageing":
        for side in ("receivables", "payables"):
            table([side.title(), "Total"], [[c["contact"], c["total"]] for c in rep[side]["contacts"]])
    elif k in ("forecast_vs_actual",):
        table(["Period", "Forecast net", "Actual net", "Error", "Forecast closing", "Actual closing"], [[r["label"], r["forecast_net"], r["actual_net"], r["error_net"], r["forecast_closing"], r["actual_closing"]] for r in rep.get("rows", [])])
    elif k == "scenario_comparison":
        table(["Scenario", "Revenue", "Expenses", "Profit", "Closing cash"], [[r["name"], r["revenue"], r["expenses"], r["profit"], r["closing_cash"]] for r in rep.get("rows", [])])
    elif k == "board_pack":
        for sct in rep["sections"]:
            rows.extend(_flatten(sct))
    rows.append(["Notes"])
    rows.extend([[c] for c in rep.get("commentary", [])])
    return rows


def _safe(v):
    v = "" if v is None else str(v)
    return "'" + v if v[:1] in ("=", "+", "-", "@") and not _is_number(v) else v      # spreadsheet formula-injection guard


def _is_number(v):
    try:
        float(v)
        return True
    except ValueError:
        return False


def export_csv(rep: dict) -> str:
    buf = io.StringIO()
    w = csv.writer(buf, lineterminator="\n")
    for r in _flatten(rep):
        w.writerow([_safe(x) for x in r])
    return buf.getvalue()


def export_xlsx(rep: dict) -> bytes:
    from openpyxl import Workbook
    from openpyxl.styles import Font
    wb = Workbook()
    ws = wb.active
    ws.title = rep["kind"][:30]
    for i, r in enumerate(_flatten(rep), start=1):
        for j, x in enumerate(r, start=1):
            c = ws.cell(row=i, column=j, value=_safe(x))
            if i == 1:
                c.font = Font(bold=True, size=13)
    ws.column_dimensions["A"].width = 38
    out = io.BytesIO()
    wb.save(out)
    return out.getvalue()
