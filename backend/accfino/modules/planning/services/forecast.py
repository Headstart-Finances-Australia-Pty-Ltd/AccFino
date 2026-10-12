"""Cash-flow forecast service: gathers ledger, sub-ledger, treasury and tax data through the module facades, runs the pure engines, stores snapshots for accuracy tracking.
Read-only toward the ledger: a forecast never posts a journal."""
import datetime as dt
import statistics
from collections import defaultdict
from decimal import Decimal
from typing import List, Optional

import accfino.modules.accounting.public as acc
import accfino.modules.lending.public as lend
import accfino.modules.taxation.public as tax
from accfino.modules.planning.engine import forecast as F, recurring as RC
from accfino.modules.planning.engine.money import D, q2, s, ZERO
from accfino.modules.planning.models import plan as P
from . import core

DIRECT_SOURCES = ("bank_line", "manual", "repeating", "payroll", "payroll_payment", "expense_payment", "expense_claim")


def _history_lines(db, ctx, as_at, days=400):
    return acc.ledger_lines(db, ctx.org.id, as_at - dt.timedelta(days=days), as_at, bank_touching=True, limit=50000)


def detect_recurring(lines, as_at):
    """Recurring direct bank payments/receipts (rent, subscriptions, payroll...) from bank-touching ledger lines. -> (series, {key: latest posting date})."""
    items, latest_post = [], {}
    for ln in lines:
        if ln["account_type"] == "bank" or ln["source_type"] not in DIRECT_SOURCES:
            continue
        eff = ln["credit"] - ln["debit"]
        key = f"{ln['account_code']}|{RC.normalise_key(ln['narration'] or ln['contact_name'])}"
        items.append(dict(date=ln["date"], key=key, amount=eff, label=(ln["narration"] or ln["contact_name"] or ln["account_name"])[:60], source="payroll" if ln["source_type"].startswith("payroll") else "recurring"))
        latest_post[key] = max(latest_post.get(key, ln["date"]), ln["date"])
    return RC.detect(items, as_at), latest_post


def expected_documents(db, ctx, as_at, end, behaviour, org_late, weight):
    """Future receipts/payments from contacts that invoice monthly at a steady amount. -> (flows, series_count)."""
    docs = acc.settled_documents(db, ctx.org.id, as_at - dt.timedelta(days=240), as_at)
    items, latest, terms = [], {}, defaultdict(list)
    for d in docs:
        key = f"{d['side']}|{d['contact']}"
        items.append(dict(date=d["issue"], key=key, amount=d["amount"] if d["side"] == "receivable" else -d["amount"], label=d["contact"], source="expected_sales" if d["side"] == "receivable" else "expected_purchases"))
        latest[key] = max(latest.get(key, d["issue"]), d["issue"])
        if d["due"]:
            terms[key].append((d["due"] - d["issue"]).days)
    for d in acc.open_document_items(db, ctx.org.id, as_at):
        key = f"{d['side']}|{d['contact']}"
        items.append(dict(date=d["issue"], key=key, amount=d["amount_due"] if d["side"] == "receivable" else -d["amount_due"], label=d["contact"], source="expected_sales" if d["side"] == "receivable" else "expected_purchases"))
        latest[key] = max(latest.get(key, d["issue"]), d["issue"])
        terms[key].append((d["due"] - d["issue"]).days)
    series = RC.detect(items, as_at)
    flows = []
    y, m = as_at.year, as_at.month
    while dt.date(y, m, 1) <= end:
        for s_ in series:
            issue = dt.date(y, m, min(s_["day"], 28))
            if issue <= as_at:
                continue                                           # the expected invoice date has already passed: do not guess
            last = latest.get(s_["key"])
            if last is not None and (last.year, last.month) == (y, m):
                continue                                           # already invoiced this month
            tk = sorted(terms.get(s_["key"]) or [14])
            term = tk[len(tk) // 2]
            late = 0
            if s_["key"].startswith("receivable|"):
                late = max(-7, min(90, behaviour.get(s_["label"], org_late)))
            when = issue + dt.timedelta(days=term + late)
            if as_at < when <= end:
                flows.append(dict(date=when, amount=s_["monthly_amount"], weight=weight, source=s_["source"], kind="expected", label=f"Expected invoice: {s_['label']}", ref=f"exp:{s_['key']}:{y}-{m:02d}"))
        m += 1
        if m == 13:
            y, m = y + 1, 1
    return flows, len(series)


def _payment_behaviour(db, ctx, as_at):
    """Average days a customer pays after the due date (negative = early), from invoices settled in the last 12 months; plus the organisation-wide median."""
    docs = [d for d in acc.settled_documents(db, ctx.org.id, as_at - dt.timedelta(days=365), as_at) if d["side"] == "receivable" and d["due"]]
    per = defaultdict(list)
    for d in docs:
        per[d["contact"]].append((d["paid"] - d["due"]).days)
    allv = [x for v in per.values() for x in v]
    org = int(statistics.median(allv)) if allv else 0
    return {c: int(round(sum(v) / len(v))) for c, v in per.items() if len(v) >= 2}, org, len(docs)


def _opening(db, ctx, as_at):
    recon = acc.bank_reconciliation_status(db, ctx.org, as_at)
    total = sum((r["ledger_balance"] for r in recon), ZERO)
    differs = [r for r in recon if r["difference"] is not None and r["difference"] != 0 and r["unreconciled_count"] == 0]
    return q2(total), recon, differs


def build(db, ctx, a, as_at: Optional[dt.date] = None, granularity: str = "week", periods: Optional[int] = None, save: bool = False, label: str = "") -> dict:
    """The forecast. granularity 'week' (default 13 weeks) or 'month' (default 12 months). Deterministic for fixed ledger data and as_at."""
    a.require("view")
    if save:
        a.require("edit")
    st = core.settings(db, ctx)
    today = core.business_today()
    as_at = as_at or today
    if granularity not in ("week", "month"):
        raise core.PlanError("granularity must be 'week' or 'month'")
    if periods is not None and not 1 <= int(periods) <= (104 if granularity == "week" else 36):
        raise core.PlanError("periods must be 1 to 104 weeks, or 1 to 36 months")
    n = int(periods) if periods is not None else int(st.horizon_weeks if granularity == "week" else 12)
    try:
        buckets = F.week_buckets(as_at, n) if granularity == "week" else F.month_buckets(as_at, n)
    except ValueError as e:
        raise core.PlanError(str(e))
    memo = None if save else db.info.get("read_memo")                # inside a landing-page request the same forecast is built once
    mkey = ("forecast", ctx.org.id, as_at, granularity, n)
    if memo is not None and mkey in memo:
        return memo[mkey]
    end = buckets[-1]["date_to"]
    threshold = q2(st.min_cash_threshold or 0)
    warnings, assumptions, sources = [], [], []

    opening, recon, differs = _opening(db, ctx, as_at)
    has_bank = bool(recon)
    if not has_bank:
        warnings.append("No bank account exists in the ledger, so the opening balance is zero and the forecast is indicative only.")
    for r in differs:
        warnings.append(f"Bank account {r['code']} {r['name']}: ledger {s(r['ledger_balance'])} differs from the statement balance {s(r['statement_balance'])} by {s(r['difference'])} with no unreconciled lines; check for missing entries.")
    unrec = sum(r["unreconciled_count"] for r in recon)
    if unrec:
        warnings.append(f"{unrec} bank lines are not yet reconciled; the ledger balance may change when they are.")
    if as_at > today:
        warnings.append("The as-at date is in the future: the opening balance is the ledger balance as currently posted.")
    last_bank = max([r["last_line_date"] for r in recon if r["last_line_date"]], default=None)
    stale = bool(last_bank and (min(as_at, today) - last_bank).days > st.stale_days)
    if stale:
        warnings.append(f"Bank data is stale: the latest imported bank line is {last_bank.isoformat()} ({(min(as_at, today) - last_bank).days} days before the as-at date).")
    sources.append(dict(name="Ledger bank balances", detail=f"bank accounts at {as_at.isoformat()}", reference="accounting.bank_reconciliation_status"))

    flows: List[dict] = []
    # --- receivables and payables from the sub-ledger
    behaviour, org_late, n_hist = _payment_behaviour(db, ctx, as_at)
    assumptions.append(f"Customers pay on average {org_late:+d} days relative to the due date (median of {n_hist} invoices settled in the last 12 months); customers with 2+ settled invoices use their own average." if n_hist else
                       "No settled invoices in the last 12 months, so invoices are assumed to be paid on their due date.")
    assumptions.append(f"Overdue receivables: {st.overdue_collection_pct}% assumed collected within {st.overdue_collection_days} days of the as-at date (setting).")
    seen_items = 0
    for it in acc.open_items(db, ctx.org, as_at):
        ref = f"{it['side']}:{it['kind']}:{it['number']}"
        seen_items += 1
        if it["side"] == "receivable":
            if it["due"] <= as_at:
                when, w = as_at + dt.timedelta(days=int(st.overdue_collection_days)), Decimal(st.overdue_collection_pct) / 100
            else:
                late = max(-7, min(90, behaviour.get(it["contact"], org_late)))
                when, w = max(it["due"] + dt.timedelta(days=late), as_at + dt.timedelta(days=1)), Decimal(1)
            flows.append(dict(date=when, amount=it["amount"], weight=w, source="receivables", kind="committed", label=f"Invoice {it['number']} ({it['contact']})", ref=ref))
        else:
            flows.append(dict(date=max(it["due"], as_at + dt.timedelta(days=1)), amount=-it["amount"], weight=Decimal(1), source="payables", kind="committed", label=f"Bill {it['number']} ({it['contact']})", ref=ref))
    sources.append(dict(name="Open invoices and bills", detail=f"{seen_items} items at {as_at.isoformat()}", reference="accounting.open_items"))
    # --- loans, facilities and expected treasury items
    for f in lend.treasury_flows(db, ctx, as_at + dt.timedelta(days=1), end):
        flows.append(dict(date=f["date"], amount=D(f["amount"]), weight=Decimal(1), source="loans" if f["source"] in ("loan", "facility") else "treasury_forecast", kind=f["kind"], label=f["label"],
                          ref=f"lend:{f['source']}:{f['label']}:{f['date'].isoformat()}"))
    sources.append(dict(name="Loan, facility and treasury items", detail="Lending > Treasury", reference="lending.treasury_flows"))
    # --- tax obligations with a known amount
    unq = []
    for o in tax.upcoming_obligations(db, ctx, as_at + dt.timedelta(days=1), end):
        if o["amount"] is None:
            unq.append(o)
            continue
        flows.append(dict(date=o["due_date"], amount=-D(o["amount"]), weight=Decimal(1), source="tax", kind="committed", label=o["title"], ref=f"tax:{o['id']}"))
    for o in unq:
        if o["kind"] in ("bas", "ias", "payg_instalment", "fbt", "income_tax") or True:
            warnings.append(f"Tax obligation '{o['title']}' due {o['due_date'].isoformat()} has no amount yet, so it is NOT in the forecast. Prepare it in Taxation to include it.")
    sources.append(dict(name="Tax obligations", detail="Taxation > Calendar (only obligations with an amount)", reference="taxation.upcoming_obligations"))
    # --- recurring direct payments (payroll, rent, subscriptions...) detected from the ledger
    lines = _history_lines(db, ctx, as_at)
    series, latest_post = detect_recurring(lines, as_at)
    rec_flows = RC.project_flows(series, as_at, end, latest_post)
    src_by_key = {x["key"]: x["source"] for x in series}
    for f in rec_flows:
        k = f["ref"].split(":", 1)[1].rsplit(":", 1)[0]
        f["source"] = src_by_key.get(k, "recurring")
    flows += rec_flows
    assumptions.append(f"Recurring direct payments and receipts ({len(series)} series, incl. payroll) repeat monthly at their median amount when seen in 3+ of the last 6 months with a stable amount (variation <= 35%). Payments already posted this month are not repeated.")
    assumptions.append("Bills and invoices not yet entered, and one-off or less-than-monthly items (quarterly super, BAS without an amount) are NOT forecast; add expected items in Lending > Treasury.")
    sources.append(dict(name="Recurring patterns", detail="bank-touching manual/bank/payroll journals, last 6 complete months", reference="accounting.ledger_lines"))

    # --- expected recurring sales and purchases: customers/suppliers that invoice every month at a steady amount but have not yet been invoiced this month
    exp_flows, n_exp = expected_documents(db, ctx, as_at, end, behaviour, org_late, Decimal(st.recurring_weight_pct if st.recurring_weight_pct is not None else 100) / 100)
    flows += exp_flows
    assumptions.append(f"Expected recurring invoices ({n_exp} customer/supplier series): a contact invoiced in 3+ of the last 6 complete months at a steady amount (variation <= 35%) is assumed to be invoiced again at the usual day of the month and paid after their usual terms plus usual lateness, at {st.recurring_weight_pct}% confidence (setting). New customers and one-off sales are not forecast.")
    sources.append(dict(name="Expected recurring invoices", detail=f"{n_exp} series from invoices/bills of the last 6 complete months", reference="accounting.settled_documents + open_document_items"))
    proj = F.project(opening, flows, buckets, threshold)
    drv = F.drivers(flows, buckets)
    inside = [f for f in flows if buckets[0]["date_from"] <= f["date"] <= end]
    tot_abs = sum((abs(F.effective(f)) for f in inside), ZERO)
    committed = sum((abs(F.effective(f)) for f in inside if f["kind"] == "committed"), ZERO)
    share = (committed / tot_abs) if tot_abs else None
    act = acc.ledger_activity_dates(db, ctx.org.id, exclude_source_types=("opening_balance",))
    hist_weeks = ((min(as_at, today) - act["first"]).days // 7) if act["first"] else 0

    # --- statistical baseline + backtest over the weekly net bank movement
    origin = as_at - dt.timedelta(days=7 * 52)
    bank_items = [dict(date=ln["date"], amount=ln["debit"] - ln["credit"]) for ln in lines if ln["account_type"] == "bank"]
    series_w = F.weekly_series(bank_items, origin + dt.timedelta(days=1), as_at)
    # drop leading empty weeks (before the first bank activity)
    first_nz = next((i for i, v in enumerate(series_w) if v != 0), len(series_w))
    series_w = series_w[first_nz:]
    bt = F.backtest(series_w)
    baseline = None
    if bt["best"] and granularity == "week":
        pred = F.predict(bt["best"], series_w, n)
        bal = opening
        rows_b = []
        for i, p in enumerate(pred):
            bal += p
            rows_b.append(dict(index=i + 1, net=s(p), closing=s(bal)))
        baseline = dict(model=bt["best"], label=F.MODEL_LABELS[bt["best"]], rows=rows_b, note="Statistical baseline: it extends recent weekly bank movement without knowing about invoices, bills or loans. Shown for comparison; the driver-based forecast is the primary view.")
    conf = F.confidence(hist_weeks, share, not differs, has_bank)
    if stale and conf["level"] != "indicative":
        conf = dict(conf, level="medium" if conf["level"] == "high" else conf["level"], reasons=conf["reasons"] + ["bank data is stale"])
    rows = [dict(index=r["index"], label=r["label"], date_from=r["date_from"].isoformat(), date_to=r["date_to"].isoformat(), opening=s(r["opening"]), receipts=s(r["receipts"]),
                 payments=s(r["payments"]), net=s(r["net"]), closing=s(r["closing"]), by_source={k: s(v) for k, v in r["by_source"].items()}, below_minimum=(r["closing"] < threshold)) for r in proj["rows"]]
    mn = proj["minimum"]
    sf = proj["shortfall"]
    out = dict(
        kind="cash_forecast", basis="indicative" if conf["level"] == "indicative" else "driver-based", label_note="FORECAST (not actual)",
        **core.stamp(ctx, as_at=as_at.isoformat(), period_from=buckets[0]["date_from"].isoformat(), period_to=end.isoformat()),
        granularity=granularity, periods=n, opening=dict(balance=s(opening), accounts=[dict(code=r["code"], name=r["name"], ledger_balance=s(r["ledger_balance"]),
                                                                                              statement_balance=None if r["statement_balance"] is None else s(r["statement_balance"]),
                                                                                              statement_date=r["statement_date"].isoformat() if r["statement_date"] else None,
                                                                                              unreconciled_lines=r["unreconciled_count"]) for r in recon],
                                                           reconciled=not differs and unrec == 0),
        rows=rows, closing=s(proj["closing"]), total_receipts=s(proj["total_receipts"]), total_payments=s(proj["total_payments"]),
        minimum=dict(balance=s(mn["balance"]), label=mn["label"], date_to=mn["date_to"].isoformat()), threshold=s(threshold),
        shortfall=dict(max_shortfall=s(sf["max_shortfall"]), goes_negative=sf["goes_negative"], first_breach=None if not sf["first_breach"] else dict(label=sf["first_breach"]["label"], closing=s(sf["first_breach"]["closing"]), shortfall=s(sf["first_breach"]["shortfall"])),
                       weeks_below=[b["label"] for b in sf["breaches"]]),
        drivers=[dict(source=d["source"], inflow=s(d["inflow"]), outflow=s(d["outflow"]), net=s(d["net"]), count=d["count"]) for d in drv],
        assumptions=assumptions, confidence=conf, committed_share=None if share is None else str(share.quantize(Decimal("0.01"))), baseline=baseline,
        backtest=dict(bt, models=[dict(m, mae=None if m["mae"] is None else s(m["mae"])) for m in bt["models"]], weeks_of_series=len(series_w)),
        warnings=warnings, sources=sources, stale=stale, duplicates_ignored=proj["duplicates_ignored"], outside_horizon=proj["outside_horizon"],
        history_weeks=hist_weeks, flows=[dict(date=f["date"].isoformat(), amount=s(F.effective(f)), source=f["source"], kind=f["kind"], label=f["label"]) for f in sorted(inside, key=lambda f: (f["date"], f["ref"]))][:500],
    )
    out["input_hash"] = core.digest(dict(opening=s(opening), flows=sorted((f["ref"], f["date"], s(F.effective(f))) for f in flows), threshold=s(threshold), g=granularity, n=n, as_at=as_at))
    if save:
        snap = P.PlanForecastSnapshot(org_id=ctx.org.id, as_at=as_at, granularity=granularity, periods=n, label=(label or "")[:100] or None,
                                      summary=core.plain(dict(minimum=out["minimum"], closing=out["closing"], threshold=out["threshold"], confidence=conf["level"], shortfall=out["shortfall"]["max_shortfall"])),
                                      result=core.plain(out), input_hash=out["input_hash"], created_by=ctx.user_id)
        db.add(snap)
        db.flush()
        out["snapshot_id"] = snap.id
        core.audit(db, ctx, "forecast.snapshot", "plan_forecast_snapshot", snap.id, as_at=as_at, granularity=granularity, minimum=out["minimum"]["balance"])
    if memo is not None:
        memo[mkey] = out
    return out


def snapshots(db, ctx, a, limit: int = 50) -> List[dict]:
    a.require("view")
    q = db.query(P.PlanForecastSnapshot).filter(P.PlanForecastSnapshot.org_id == ctx.org.id).order_by(P.PlanForecastSnapshot.id.desc()).limit(max(1, min(limit, 200)))
    return [dict(id=r.id, as_at=r.as_at.isoformat(), granularity=r.granularity, periods=r.periods, label=r.label, summary=r.summary, input_hash=r.input_hash, created_at=r.created_at.isoformat()) for r in q]


def snapshot_get(db, ctx, a, sid: int) -> dict:
    a.require("view")
    r = db.query(P.PlanForecastSnapshot).filter_by(org_id=ctx.org.id, id=sid).first()
    if r is None:
        raise core.NotFound("Forecast snapshot")
    return dict(id=r.id, created_at=r.created_at.isoformat(), **r.result)


def latest_snapshot(db, ctx, before_id: Optional[int] = None):
    q = db.query(P.PlanForecastSnapshot).filter(P.PlanForecastSnapshot.org_id == ctx.org.id)
    if before_id:
        q = q.filter(P.PlanForecastSnapshot.id < before_id)
    return q.order_by(P.PlanForecastSnapshot.id.desc()).first()


def vs_actual(db, ctx, a, sid: int, today: Optional[dt.date] = None) -> dict:
    """Compare a stored snapshot with the ledger for the buckets that have ended. Actuals = movement on bank accounts in the ledger."""
    a.require("view")
    snap = snapshot_get(db, ctx, a, sid)
    today = today or core.business_today()
    as_at = dt.date.fromisoformat(snap["as_at"])
    ended = [r for r in snap["rows"] if dt.date.fromisoformat(r["date_to"]) <= today]
    if not ended:
        return dict(snapshot_id=sid, as_at=snap["as_at"], **F.accuracy([], {}), basis="ACTUAL vs FORECAST", **core.stamp(ctx))
    last_end = dt.date.fromisoformat(ended[-1]["date_to"])
    lines = [ln for ln in acc.ledger_lines(db, ctx.org.id, as_at + dt.timedelta(days=1), last_end, bank_touching=True, limit=50000) if ln["account_type"] == "bank"]
    opening, _, _ = _opening(db, ctx, as_at)
    act, bal = {}, opening
    for r in ended:
        lo, hi = dt.date.fromisoformat(r["date_from"]), dt.date.fromisoformat(r["date_to"])
        net = sum((ln["debit"] - ln["credit"] for ln in lines if lo <= ln["date"] <= hi), ZERO)
        bal += net
        act[r["index"]] = dict(net=net, closing=bal)
    fr = [dict(index=r["index"], label=r["label"], net=D(r["net"]), closing=D(r["closing"])) for r in snap["rows"]]
    acc_ = F.accuracy(fr, act)
    return dict(snapshot_id=sid, as_at=snap["as_at"], basis="ACTUAL vs FORECAST", **acc_, **core.stamp(ctx), source="ledger bank movements", note_basis="Actual closing is rebuilt from the CURRENT ledger opening at the snapshot date, so later back-dated entries are included.")
