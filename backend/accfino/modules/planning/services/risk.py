"""Risk and anomaly detection service: runs the rule engine over ledger activity and stores alerts with a review workflow.
Alerts say 'unusual - please review'; they never block or change a transaction and never accuse anyone of wrongdoing."""
import datetime as dt
from collections import defaultdict
from decimal import Decimal
from typing import List, Optional

import accfino.modules.accounting.public as acc
from accfino.modules.planning.engine import anomaly as AN
from accfino.modules.planning.engine.money import D, q2, s, ZERO
from accfino.modules.planning.models import plan as P
from . import budgets, core, forecast as FC, reports as RP

SCAN_WINDOW_DAYS = 35
EXCLUDED_SOURCES = ("reversal", "auto_reversal", "opening_balance", "fx_reval", "fx_reval_reversal")


def config(db, ctx) -> dict:
    return dict(AN.DEFAULTS, **(core.settings(db, ctx).risk_cfg or {}))


def save_config(db, ctx, a, cfg: dict) -> dict:
    a.require("config")
    bad = [k for k in cfg if k not in AN.DEFAULTS]
    if bad:
        raise core.PlanError(f"Unknown risk setting(s): {', '.join(bad)}")
    clean = {}
    for k, v in cfg.items():
        try:
            d = D(v)
        except ValueError:
            raise core.PlanError(f"{k} must be a number")
        if d < 0 or d > 100_000_000:
            raise core.PlanError(f"{k} must be between 0 and 100,000,000")
        clean[k] = float(d) if d % 1 else int(d)
    st = core.settings(db, ctx)
    st.risk_cfg = clean
    db.flush()
    core.audit(db, ctx, "risk.config", "plan_settings", ctx.org.id, risk_cfg=clean)
    return dict(thresholds=config(db, ctx))


def _outflows(lines):
    """Cash payments out of bank accounts, one per journal: {id, date, contact, amount, label, ref}. Transfers between own bank accounts (no counter-account) are excluded."""
    by = defaultdict(list)
    for ln in lines:
        if ln["source_type"] in EXCLUDED_SOURCES:
            continue
        by[ln["journal_id"]].append(ln)
    out, inflow = [], []
    for jid, ls in by.items():
        bank = [x for x in ls if x["account_type"] == "bank"]
        other = [x for x in ls if x["account_type"] != "bank"]
        if not bank or not other:
            continue
        net = sum((x["credit"] - x["debit"] for x in bank), ZERO)
        contact = next((x["contact_name"] for x in other if x["contact_name"]), "")
        rec = dict(id=jid, date=ls[0]["date"], contact=contact, amount=abs(net), label=ls[0]["narration"] or contact, ref=ls[0]["reference"])
        if net > 0:
            out.append(rec)
    return sorted(out, key=lambda r: (r["date"], r["id"]))


def detect(db, ctx, a, as_at: Optional[dt.date] = None) -> dict:
    """Run every rule and return the candidate alerts (nothing stored). Deterministic for fixed data."""
    a.require("view")
    c = config(db, ctx)
    as_at = as_at or core.business_today()
    hist = acc.ledger_activity_dates(db, ctx.org.id, exclude_source_types=("opening_balance",))
    lines = acc.ledger_lines(db, ctx.org.id, as_at - dt.timedelta(days=420), as_at, bank_touching=True, limit=50000)
    outs = _outflows(lines)
    win_from = as_at - dt.timedelta(days=SCAN_WINDOW_DAYS)
    recent = [p for p in outs if p["date"] >= win_from]
    skipped = []
    alerts: List[dict] = []
    series, _ = FC.detect_recurring(lines, as_at)
    rec_keys = {x["key"].split("|", 1)[1] for x in series}
    alerts += AN.duplicates(recent, c)
    alerts += AN.round_sums(recent, c, rec_keys)
    lookback_start = as_at - dt.timedelta(days=int(c["new_payee_lookback_days"]))
    if hist["first"] and hist["first"] <= lookback_start - dt.timedelta(days=30):
        before = {p["contact"].strip().lower() for p in outs if p["contact"] and p["date"] < lookback_start}
        within = [p for p in recent if p["contact"]]
        alerts += AN.new_payee(within, before | {p["contact"].strip().lower() for p in outs if p["contact"] and lookback_start <= p["date"] < win_from}, c)
    else:
        skipped.append("New-payee rule skipped: there is not enough payment history before the look-back window to know who is new.")
    month_end = dt.date(as_at.year + (as_at.month == 12), as_at.month % 12 + 1, 1) - dt.timedelta(days=1)
    cur_month = as_at.strftime("%Y-%m") if as_at == month_end else (dt.date(as_at.year, as_at.month, 1) - dt.timedelta(days=1)).strftime("%Y-%m")
    pl = acc.monthly_pl(db, ctx.org.id, as_at - dt.timedelta(days=400), as_at)
    exp = {str(r["account_id"]): {k: v for k, v in r["months"].items()} for r in pl if r["class"] == "expense"}
    names = {str(r["account_id"]): f"{r['code']} {r['name']}" for r in pl}
    alerts += AN.deviations(exp, names, cur_month, c)
    alerts += AN.recurring_changes(series, c)
    alerts += AN.balances(acc.balances_by_account(db, ctx.org, as_at), as_at)
    m = RP._default_budget(db, ctx, as_at.replace(day=1) if as_at.day else as_at, as_at)
    if m is not None:
        try:
            v = budgets.vs_actual(db, ctx, a, m.id, max(m.fy_start, core.fy_start_for(ctx.org, as_at)), as_at)
            rows = [dict(r, budget=D(r["budget"]), actual=D(r["actual"])) for r in v["rows"]]
            alerts += AN.budget_overruns(rows, c, m.name)
        except core.PlanError:
            skipped.append("Budget-overrun rule skipped: no approved budget covers this date.")
    else:
        skipped.append("Budget-overrun rule skipped: no approved budget covers this date.")
    snaps = FC.snapshots(db, ctx, a, limit=2)
    if len(snaps) == 2:
        cur_s, prev_s = snaps[0], snaps[1]
        alerts += AN.forecast_movement(dict(minimum=prev_s["summary"]["minimum"]["balance"], snapshot_id=prev_s["id"]), dict(minimum=cur_s["summary"]["minimum"]["balance"], snapshot_id=cur_s["id"]), c)
    sev = {"high": 0, "medium": 1, "low": 2}
    alerts.sort(key=lambda x: (sev[x["severity"]], x["rule"], x["dedupe_key"]))
    return dict(as_at=as_at.isoformat(), alerts=alerts, skipped=skipped, ruleset=AN.RULESET_VERSION, thresholds=c)


def scan(db, ctx, a, as_at: Optional[dt.date] = None) -> dict:
    """Detect and store: new alerts are inserted, repeats only update last_seen (duplicate-alert suppression)."""
    a.require("edit")
    res = detect(db, ctx, a, as_at)
    created = suppressed = 0
    now = dt.datetime.utcnow()
    for al in res["alerts"]:
        row = db.query(P.PlanAlert).filter_by(org_id=ctx.org.id, dedupe_key=al["dedupe_key"]).first()
        if row is not None:
            row.last_seen, row.seen_count = now, (row.seen_count or 1) + 1
            suppressed += 1
            continue
        db.add(P.PlanAlert(org_id=ctx.org.id, rule=al["rule"], rule_version=al["rule_version"], ref=al["ref"], severity=al["severity"], title=al["title"][:300], reason=al["reason"],
                           evidence=core.plain(al["evidence"]), baseline=core.plain(al["baseline"]), amount=D(al["amount"]) if al["amount"] is not None else None,
                           event_date=dt.date.fromisoformat(al["event_date"]) if al["event_date"] else None, dedupe_key=al["dedupe_key"][:160], status="new", first_seen=now, last_seen=now))
        created += 1
    db.flush()
    core.audit(db, ctx, "risk.scan", "plan_alert", None, as_at=res["as_at"], created=created, suppressed=suppressed, skipped=len(res["skipped"]))
    return dict(as_at=res["as_at"], created=created, suppressed_duplicates=suppressed, skipped=res["skipped"], detected=len(res["alerts"]), ruleset=res["ruleset"])


def _row(r: "P.PlanAlert") -> dict:
    return dict(id=r.id, rule=r.rule, rule_name=AN.RULES.get(r.rule, r.rule), rule_version=r.rule_version, ref=r.ref, severity=r.severity, title=r.title, reason=r.reason, evidence=r.evidence, baseline=r.baseline,
                amount=None if r.amount is None else s(r.amount), event_date=r.event_date.isoformat() if r.event_date else None, status=r.status, reviewer=r.reviewer_name, review_note=r.review_note,
                reviewed_at=r.reviewed_at.isoformat() if r.reviewed_at else None, first_seen=r.first_seen.isoformat() if r.first_seen else None, last_seen=r.last_seen.isoformat() if r.last_seen else None, seen_count=r.seen_count,
                disclaimer="An alert means 'unusual, please review'. It is not a finding of error or wrongdoing.")


def listing(db, ctx, a, status: str = "", severity: str = "", rule: str = "", limit: int = 200) -> dict:
    a.require("view")
    q = db.query(P.PlanAlert).filter_by(org_id=ctx.org.id)
    if status:
        if status not in P.ALERT_STATUSES:
            raise core.PlanError("status must be new, acknowledged, dismissed or resolved")
        q = q.filter(P.PlanAlert.status == status)
    if severity:
        q = q.filter(P.PlanAlert.severity == severity)
    if rule:
        q = q.filter(P.PlanAlert.rule == rule)
    rows = q.order_by(P.PlanAlert.id.desc()).limit(max(1, min(limit, 500))).all()
    sev = {"high": 0, "medium": 1, "low": 2}
    rows.sort(key=lambda r: (r.status in ("dismissed", "resolved"), sev[r.severity], -r.id))
    counts = {st: db.query(P.PlanAlert).filter_by(org_id=ctx.org.id, status=st).count() for st in P.ALERT_STATUSES}
    return dict(alerts=[_row(r) for r in rows], counts=counts, rules={k: v for k, v in AN.RULES.items()}, **core.stamp(ctx, source="rule engine over ledger activity"))


TRANSITIONS = {"new": {"acknowledged", "dismissed", "resolved"}, "acknowledged": {"dismissed", "resolved", "new"}, "dismissed": {"new"}, "resolved": {"new"}}


def review(db, ctx, a, alert_id: int, status: str, note: str = "") -> dict:
    a.require("review")
    r = db.query(P.PlanAlert).filter_by(org_id=ctx.org.id, id=alert_id).first()
    if r is None:
        raise core.NotFound("Alert")
    if status not in P.ALERT_STATUSES:
        raise core.PlanError("status must be new, acknowledged, dismissed or resolved")
    if status not in TRANSITIONS[r.status]:
        raise core.Conflict(f"An alert that is {r.status} cannot move to {status}")
    note = (note or "").strip()
    if status in ("dismissed", "resolved") and len(note) < 3:
        raise core.PlanError("Please add a short note explaining why the alert is being " + status)
    before = r.status
    r.status, r.reviewer_id, r.reviewer_name, r.review_note, r.reviewed_at = status, ctx.user_id, ctx.username, note[:1000] or None, dt.datetime.utcnow()
    db.flush()
    core.audit(db, ctx, "risk.review", "plan_alert", r.id, rule=r.rule, before=before, after=status, note=note[:300])
    return _row(r)
