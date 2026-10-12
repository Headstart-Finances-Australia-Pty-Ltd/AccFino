"""Budgeting service: named budgets with owner, version and approval workflow wrapped around Accounting's monthly budget lines (reused, not duplicated).
Actuals always come from the ledger; a budget never changes a journal."""
import csv
import datetime as dt
import io
from decimal import Decimal
from typing import List, Optional

import accfino.modules.accounting.public as acc
from accfino.modules.planning.engine import budget as B
from accfino.modules.planning.engine.money import D, q2, s, pct, ZERO
from accfino.modules.planning.models import plan as P
from . import core

MAX_IMPORT_ROWS = 5000


def _month_end(d: dt.date) -> dt.date:
    return dt.date(d.year + (d.month == 12), d.month % 12 + 1, 1) - dt.timedelta(days=1)


def _meta(db, ctx, bid: int) -> "P.PlanBudget":
    r = db.query(P.PlanBudget).filter_by(org_id=ctx.org.id, id=bid).first()
    if r is None:
        raise core.NotFound("Budget")
    return r


def _row(m: "P.PlanBudget", lines=0, total=None) -> dict:
    return dict(id=m.id, name=m.name, fy_start=m.fy_start.isoformat(), interval=m.interval, status=m.status, version=m.version, parent_id=m.parent_id, owner=m.owner_name, owner_id=m.owner_id,
                notes=m.notes, submitted_at=m.submitted_at.isoformat() if m.submitted_at else None, approved_at=m.approved_at.isoformat() if m.approved_at else None,
                approved_by=m.approved_by, lines=lines, annual=total)


def _adopt_existing(db, ctx):
    """Budgets saved before Planning existed (Accounting > Reports > Budget) get a workflow record, status 'approved' (they were already in use); their lines are untouched."""
    have = {m.name for m in db.query(P.PlanBudget.name).filter_by(org_id=ctx.org.id)}
    for sc in acc.budget_scenarios(db, ctx.org.id):
        if sc["scenario"] in have:
            continue
        fy = core.fy_start_for(ctx.org, sc["first_period"])
        db.add(P.PlanBudget(org_id=ctx.org.id, name=sc["scenario"], fy_start=fy, interval="monthly", status="approved", version=1, notes="Existing budget adopted into the Planning workflow (no lines changed)."))
    db.flush()


def listing(db, ctx, a, include_archived: bool = False) -> List[dict]:
    a.require("view")
    _adopt_existing(db, ctx)
    out = []
    counts = {r["scenario"]: r for r in acc.budget_scenarios(db, ctx.org.id)}
    q = db.query(P.PlanBudget).filter_by(org_id=ctx.org.id)
    if not include_archived:
        q = q.filter(P.PlanBudget.status != "archived")
    for m in q.order_by(P.PlanBudget.name):
        out.append(_row(m, counts.get(m.name, {}).get("lines", 0)))
    return out


def _grid(db, ctx, m):
    g = acc.budget_lines(db, ctx.org, m.name, m.fy_start)
    months = B.fy_months(m.fy_start)
    accounts = []
    for r in g["accounts"]:
        accounts.append(dict(account_id=r["account_id"], code=r["code"], name=r["name"], type=r["type"], months={k: r["periods"].get(k, "0.00") for k in months},
                             annual=s(sum((D(v) for v in r["periods"].values()), ZERO))))
    return dict(months=months, accounts=accounts)


def get(db, ctx, a, bid: int) -> dict:
    a.require("view")
    m = _meta(db, ctx, bid)
    g = _grid(db, ctx, m)
    return dict(**_row(m, sum(1 for r in g["accounts"] for v in r["months"].values() if D(v) != 0)), **g, **core.stamp(ctx, source="Accounting budget lines (org_budget_lines)"))


def _account_lookup(db, ctx):
    out = {}
    for x in acc.ledger_accounts(db, ctx.org.id):
        out[x["code"]] = x
        out[x["id"]] = x
    return out


def create(db, ctx, a, body: dict) -> dict:
    a.require("edit")
    name = (body.get("name") or "").strip()
    if not name or len(name) > 40:
        raise core.PlanError("A budget needs a name of 1 to 40 characters")
    if db.query(P.PlanBudget).filter_by(org_id=ctx.org.id, name=name).first() or any(x["scenario"] == name for x in acc.budget_scenarios(db, ctx.org.id)):
        raise core.Conflict(f"A budget called '{name}' already exists")
    fy = core.parse_date(body.get("fy_start"), "fy_start")
    if fy is None or fy.day != 1:
        raise core.PlanError("fy_start must be the first day of a month (the start of the budget year)")
    interval = body.get("interval") or "monthly"
    if interval not in ("monthly", "quarterly", "annual"):
        raise core.PlanError("interval must be monthly, quarterly or annual")
    m = P.PlanBudget(org_id=ctx.org.id, name=name, fy_start=fy, interval=interval, status="draft", version=1, owner_id=body.get("owner_id") or ctx.user_id,
                     owner_name=(body.get("owner_name") or ctx.username)[:100], notes=(body.get("notes") or None), created_by=ctx.user_id)
    db.add(m)
    db.flush()
    gen = acc.budget_generate(db, ctx.org, name, fy, D(body.get("uplift_pct", 0))) if body.get("from_actuals") else None
    core.audit(db, ctx, "budget.create", "plan_budget", m.id, name=name, fy_start=fy, interval=interval, from_actuals=bool(body.get("from_actuals")))
    return dict(get(db, ctx, a, m.id), generated=gen)


def save_lines(db, ctx, a, bid: int, lines: list) -> dict:
    """lines: [{account: id|code, month: 'YYYY-MM', amount}] at the budget's interval: quarterly/annual amounts are spread cent-exact over 3/12 months starting at `month`."""
    a.require("edit")
    m = _meta(db, ctx, bid)
    if m.status != "draft":
        raise core.Conflict(f"Budget '{m.name}' is {m.status}: only a draft can be edited. Copy it to a new version to change it.")
    lk = _account_lookup(db, ctx)
    months = B.fy_months(m.fy_start)
    out, seen = [], set()
    for i, ln in enumerate(lines or [], start=1):
        acct = lk.get(ln.get("account"))
        if acct is None:
            raise core.PlanError(f"Line {i}: unknown account {ln.get('account')!r}")
        if acct["type"] not in ("revenue", "other_income", "direct_costs", "expense", "other_expense"):
            raise core.PlanError(f"Line {i}: {acct['code']} {acct['name']} is a balance-sheet account; budgets are for income and expense accounts")
        month = str(ln.get("month") or ln.get("period") or "")[:7]
        if month not in months:
            raise core.PlanError(f"Line {i}: month {month!r} is outside the budget year {months[0]} to {months[-1]}")
        try:
            amt = D(ln.get("amount"))
        except ValueError:
            raise core.PlanError(f"Line {i}: amount is not a number")
        parts = {"monthly": 1, "quarterly": 3, "annual": 12}[ln.get("interval") or m.interval]
        spread = B.spread_interval(amt, ln.get("interval") or m.interval)
        start_idx = months.index(month)
        if start_idx + parts > 12:
            raise core.PlanError(f"Line {i}: a {ln.get('interval') or m.interval} amount starting {month} runs past the end of the budget year")
        for k, part in enumerate(spread):
            key = (acct["id"], months[start_idx + k])
            if key in seen:
                raise core.PlanError(f"Line {i}: {acct['code']} {months[start_idx + k]} appears twice in this save")
            seen.add(key)
            out.append(dict(account=acct["id"], period=months[start_idx + k], amount=part))
    res = acc.budget_save(db, ctx.org, m.name, out)
    core.audit(db, ctx, "budget.save_lines", "plan_budget", m.id, name=m.name, lines=len(out))
    return dict(saved=res["saved"], budget=get(db, ctx, a, bid))


def import_csv(db, ctx, a, bid: int, text: str, apply: bool = True, strict: bool = True) -> dict:
    """CSV columns: account_code, month (YYYY-MM), amount. Row-level validation; duplicate (account, month) rows are rejected. With strict=True nothing is saved if any row fails."""
    a.require("edit")
    m = _meta(db, ctx, bid)
    if m.status != "draft":
        raise core.Conflict(f"Budget '{m.name}' is {m.status}: only a draft can be imported into")
    rdr = csv.DictReader(io.StringIO(text or ""))
    cols = {(c or "").strip().lower() for c in (rdr.fieldnames or [])}
    if not {"account_code", "month", "amount"} <= cols:
        raise core.PlanError("CSV needs the columns account_code, month, amount")
    lk, months = _account_lookup(db, ctx), B.fy_months(m.fy_start)
    good, errs, seen = [], [], {}
    for n, raw in enumerate(rdr, start=2):
        if n - 1 > MAX_IMPORT_ROWS:
            errs.append(dict(row=n, error=f"More than {MAX_IMPORT_ROWS} rows; split the file"))
            break
        r = {(k or "").strip().lower(): (v or "").strip() for k, v in raw.items()}
        code, month, amt = r.get("account_code", ""), r.get("month", "")[:7], r.get("amount", "")
        acct = lk.get(code)
        if acct is None:
            errs.append(dict(row=n, error=f"Unknown account code {code!r}"))
            continue
        if acct["type"] not in ("revenue", "other_income", "direct_costs", "expense", "other_expense"):
            errs.append(dict(row=n, error=f"{code} is a balance-sheet account"))
            continue
        if month not in months:
            errs.append(dict(row=n, error=f"Month {month!r} is outside the budget year {months[0]} to {months[-1]}"))
            continue
        try:
            v = q2(D(amt))
        except ValueError:
            errs.append(dict(row=n, error=f"Amount {amt!r} is not a number"))
            continue
        if (acct["id"], month) in seen:
            errs.append(dict(row=n, error=f"Duplicate of row {seen[(acct['id'], month)]} ({code} {month})"))
            continue
        seen[(acct["id"], month)] = n
        good.append(dict(account=acct["id"], period=month, amount=v, row=n))
    applied = 0
    if apply and good and not (strict and errs):
        acc.budget_save(db, ctx.org, m.name, [dict(account=g["account"], period=g["period"], amount=g["amount"]) for g in good])
        applied = len(good)
        core.audit(db, ctx, "budget.import", "plan_budget", m.id, name=m.name, applied=applied, rejected=len(errs))
    return dict(valid_rows=len(good), rejected=errs, applied=applied, dry_run=not apply, strict=strict)


def export_csv(db, ctx, a, bid: int) -> str:
    a.require("view")
    m = _meta(db, ctx, bid)
    g = _grid(db, ctx, m)
    buf = io.StringIO()
    w = csv.writer(buf, lineterminator="\n")
    w.writerow(["account_code", "account_name", "month", "amount"])
    for r in g["accounts"]:
        for mo in g["months"]:
            if D(r["months"][mo]) != 0:
                w.writerow([r["code"], r["name"], mo, r["months"][mo]])
    return buf.getvalue()


def copy(db, ctx, a, bid: int, name: Optional[str] = None) -> dict:
    a.require("edit")
    src = _meta(db, ctx, bid)
    name = (name or f"{src.name.split(' v')[0]} v{src.version + 1}")[:40]
    if db.query(P.PlanBudget).filter_by(org_id=ctx.org.id, name=name).first():
        raise core.Conflict(f"A budget called '{name}' already exists")
    new = P.PlanBudget(org_id=ctx.org.id, name=name, fy_start=src.fy_start, interval=src.interval, status="draft", version=src.version + 1, parent_id=src.id, owner_id=ctx.user_id,
                       owner_name=ctx.username, notes=f"Copied from '{src.name}'", created_by=ctx.user_id)
    db.add(new)
    db.flush()
    g = acc.budget_lines(db, ctx.org, src.name, src.fy_start)
    lines = [dict(account=r["account_id"], period=k, amount=D(v)) for r in g["accounts"] for k, v in r["periods"].items() if D(v) != 0]
    if lines:
        acc.budget_save(db, ctx.org, name, lines)
    core.audit(db, ctx, "budget.copy", "plan_budget", new.id, source=src.name, name=name, lines=len(lines))
    return get(db, ctx, a, new.id)


def _transition(db, ctx, a, bid, cap, frm, to, action, note=None):
    a.require(cap)
    m = _meta(db, ctx, bid)
    if m.status not in frm:
        raise core.Conflict(f"Budget '{m.name}' is {m.status}; it must be {' or '.join(frm)} to {action}")
    return m


def submit(db, ctx, a, bid: int) -> dict:
    m = _transition(db, ctx, a, bid, "edit", ("draft",), "submitted", "submit")
    if not acc.budget_lines(db, ctx.org, m.name, m.fy_start)["line_count"]:
        raise core.PlanError("An empty budget cannot be submitted")
    m.status, m.submitted_by, m.submitted_at = "submitted", ctx.user_id, dt.datetime.utcnow()
    core.audit(db, ctx, "budget.submit", "plan_budget", m.id, name=m.name)
    return get(db, ctx, a, bid)


def approve(db, ctx, a, bid: int) -> dict:
    m = _transition(db, ctx, a, bid, "approve", ("submitted",), "approved", "approve")
    self_ok = ctx.role == "owner" or ctx.is_admin
    if m.submitted_by == ctx.user_id and not self_ok:
        raise core.Forbidden("Separation of duties: the person who submitted this budget cannot approve it. Another authorised user must approve (the Organisation Admin may self-approve).")
    m.status, m.approved_by, m.approved_at = "approved", ctx.user_id, dt.datetime.utcnow()
    core.audit(db, ctx, "budget.approve", "plan_budget", m.id, name=m.name, self_approved=bool(m.submitted_by == ctx.user_id))
    return get(db, ctx, a, bid)


def reject(db, ctx, a, bid: int, note: str = "") -> dict:
    m = _transition(db, ctx, a, bid, "approve", ("submitted",), "draft", "return to draft")
    m.status = "draft"
    core.audit(db, ctx, "budget.reject", "plan_budget", m.id, name=m.name, note=(note or "")[:300])
    return get(db, ctx, a, bid)


def archive(db, ctx, a, bid: int) -> dict:
    m = _transition(db, ctx, a, bid, "edit", ("draft", "submitted", "approved"), "archived", "archive")
    m.status = "archived"
    core.audit(db, ctx, "budget.archive", "plan_budget", m.id, name=m.name)
    return _row(m)


def discard_draft(db, ctx, a, bid: int) -> dict:
    """Delete an unapproved draft and its lines (approved/submitted budgets can only be archived)."""
    a.require("edit")
    m = _meta(db, ctx, bid)
    if m.status != "draft":
        raise core.Conflict("Only a draft can be deleted; archive other budgets")
    n = acc.delete_budget_scenario(db, ctx.org.id, m.name)
    db.delete(m)
    db.flush()
    core.audit(db, ctx, "budget.discard", "plan_budget", bid, name=m.name, lines=n)
    return dict(deleted=True, lines=n)


# ------------------------------------------------------------------------------------------------------------------------ actual vs budget
def vs_actual(db, ctx, a, bid: int, date_from: Optional[dt.date] = None, date_to: Optional[dt.date] = None, today: Optional[dt.date] = None) -> dict:
    """Budget vs ledger actuals for a period inside the budget year, plus remaining annual budget, year-end projections and the forecast overlay.
    Variance is favourable-positive. Zero budgets show no percent; negative budgets are flagged."""
    a.require("view")
    m = _meta(db, ctx, bid)
    today = today or core.business_today()
    months = B.fy_months(m.fy_start)
    fy_end = _month_end(dt.date.fromisoformat(months[-1] + "-01"))
    if date_to is None:
        date_to = min(today, fy_end)
        date_to = (m.fy_start - dt.timedelta(days=1)) if date_to < m.fy_start else date_to
        if date_to != _month_end(date_to):
            date_to = dt.date(date_to.year, date_to.month, 1) - dt.timedelta(days=1)       # last COMPLETE month
    date_from = date_from or m.fy_start
    if date_from > date_to or date_from < m.fy_start or date_to > fy_end:
        raise core.PlanError(f"The period must lie inside the budget year {m.fy_start.isoformat()} to {fy_end.isoformat()} and start before it ends")
    accs = {x["id"]: x for x in acc.ledger_accounts(db, ctx.org.id, active_only=False)}
    pl = acc.monthly_pl(db, ctx.org.id, m.fy_start, fy_end)
    grid = acc.budget_lines(db, ctx.org, m.name, m.fy_start)
    bud_m = {r["account_id"]: {k: D(v) for k, v in r["periods"].items()} for r in grid["accounts"]}
    act_m = {r["account_id"]: r["months"] for r in pl}
    ids = sorted(set(bud_m) | set(act_m), key=lambda i: accs[i]["code"])
    meta_accs = [dict(id=i, code=accs[i]["code"], name=accs[i]["name"], **{"class": "revenue" if accs[i]["type"] in ("revenue", "other_income") else "expense"}) for i in ids]
    in_p = [mo for mo in months if date_from <= _month_end(dt.date.fromisoformat(mo + "-01")) and dt.date.fromisoformat(mo + "-01") <= date_to]
    bud_p = {i: sum((bud_m.get(i, {}).get(mo, ZERO) for mo in in_p), ZERO) for i in ids}
    act_p = {i: sum((act_m.get(i, {}).get(mo, ZERO) for mo in in_p), ZERO) for i in ids}
    rows = B.rows_vs_actual(meta_accs, bud_p, act_p)
    last_closed = max((mo for mo in months if _month_end(dt.date.fromisoformat(mo + "-01")) <= min(date_to, today)), default=None)
    ye = []
    for ma in meta_accs:
        r = B.year_end(ma["class"], months, bud_m.get(ma["id"], {}), act_m.get(ma["id"], {}), last_closed)
        if r["annual_budget"] != 0 or r["actual_ytd"] != 0:
            ye.append(dict(account_id=ma["id"], code=ma["code"], name=ma["name"], account_class=ma["class"], **{k: (s(v) if isinstance(v, Decimal) else v) for k, v in r.items()}))
    tot = B.totals(rows)
    fmt = lambda t: {k: {kk: (s(vv) if isinstance(vv, Decimal) else vv) for kk, vv in v.items()} for k, v in t.items()}
    ser = lambda r: dict(r, budget=s(r["budget"]), actual=s(r["actual"]), variance=s(r["variance"]), variance_pct=None if r["variance_pct"] is None else str(r["variance_pct"]))
    return dict(kind="budget_vs_actual", basis="BUDGET vs ACTUAL", **core.stamp(ctx, period_from=date_from.isoformat(), period_to=date_to.isoformat(), source="ledger actuals vs Accounting budget lines"),
                budget=_row(m), convention="Variance is favourable-positive: revenue above budget and expenses below budget are positive.", rows=[ser(r) for r in rows], totals=fmt(tot),
                year_end=dict(rows=ye, last_closed_month=last_closed, note="FORECAST: the projection adds the remaining budget (or the run-rate) to closed-month actuals. It is an extrapolation, not a commitment.",
                              basis_note="projection_budget_basis = actual to date + budget for the remaining months; projection_run_rate = average closed month x 12."),
                approval_note=None if m.status == "approved" else f"This budget is {m.status}; figures are shown for review.")


def drilldown(db, ctx, a, account_id: int, date_from: dt.date, date_to: dt.date, limit: int = 200) -> dict:
    """The ledger lines behind a number: every posted journal line on one account in a period (org-scoped)."""
    a.require("view")
    if date_from > date_to:
        raise core.PlanError("from must not be after to")
    lines = acc.ledger_lines(db, ctx.org.id, date_from, date_to, account_id=account_id, limit=max(1, min(limit, 1000)))
    return dict(account_id=account_id, period_from=date_from.isoformat(), period_to=date_to.isoformat(), count=len(lines),
                lines=[dict(journal_id=x["journal_id"], journal_no=x["journal_no"], date=x["date"].isoformat(), source=x["source_type"], narration=x["narration"], contact=x["contact_name"],
                            debit=s(x["debit"]), credit=s(x["credit"]), account=f"{x['account_code']} {x['account_name']}") for x in lines], **core.stamp(ctx, source="ledger journal lines"))
