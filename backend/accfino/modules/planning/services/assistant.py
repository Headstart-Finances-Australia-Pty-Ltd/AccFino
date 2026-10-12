"""AI Financial Assistant (read-only). Natural-language questions are mapped to a fixed set of parameterised tools that call the existing report, forecast, budget,
scenario and alert services under the caller's own organisation and permissions. The answer text is assembled ONLY from tool results and every number in it is
checked against those results before it is returned; if a tool fails the assistant says so and gives no number.
No language model is used in this release, so the user's text can never act as an instruction: it is only matched against intent patterns and parameter patterns.
It cannot post, change or delete anything - there is no write tool."""
import calendar
import datetime as dt
import hashlib
import os
import re
import time
from decimal import Decimal, InvalidOperation
from typing import Callable, Dict, List, Optional, Tuple

import accfino.modules.accounting.public as acc
from accfino.modules.planning.engine import scenario as SE
from accfino.modules.planning.engine.money import D, s, pct, q2, ZERO
from accfino.modules.planning.models import plan as P
from . import budgets, core, forecast as FC, insights as INS, reports as RP, risk as RK, scenarios as SC

MAX_Q = 500
MAX_ROWS = 5
MAX_ANSWER = 1800
LABEL = "AI assistant (read-only). Answers are assembled from AccFino reports; nothing is estimated by a language model."
MONTHS = {m.lower(): i for i, m in enumerate(calendar.month_name) if m}
MONTHS.update({m.lower(): i for i, m in enumerate(calendar.month_abbr) if m})

MUTATE = re.compile(r"\b(post|create|add|delete|remove|update|change|edit|approve|submit|pay|transfer|void|reverse|write[- ]?off|record|enter|lodge|set)\b.{0,40}\b(journal|invoice|bill|budget|payment|entry|transaction|account|contact|payroll|alert|scenario|forecast|setting|threshold)s?\b", re.I)
CROSS = re.compile(r"\b(other|another|all|different|every|any)\s+(org|organi[sz]ations?|compan(?:y|ies)|tenants?|clients?|customers?\s+of\s+accfino)\b|\borg(?:ani[sz]ation)?[_ ]?id\s*[:=]?\s*\d+|\btenant\b", re.I)
INJECT = re.compile(r"(ignore|disregard|forget)\s+(all\s+|any\s+|the\s+|your\s+)?(previous|prior|above|earlier|instructions|rules)|system\s+prompt|developer\s+message|you\s+are\s+now|act\s+as|pretend|jailbreak|reveal\s+(your|the)|api[_ ]?key|password|secret|\bselect\b.+\bfrom\b|drop\s+table|union\s+select|;\s*--", re.I)
NUM = re.compile(r"\d[\d,]*(?:\.\d+)?")
ISO = re.compile(r"\d{4}-\d{2}(?:-\d{2})?")
MONTH_YEAR = re.compile(r"\b(?:jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\.?\s+20\d{2}\b", re.I)


class Refusal(Exception):
    def __init__(self, text, code="refused"):
        super().__init__(text)
        self.text, self.code = text, code


def mask(text: str) -> str:
    t = re.sub(r"[\w.+-]+@[\w-]+\.[\w.]+", "***", text or "")
    t = re.sub(r"\d{9,}", "***", t)
    return re.sub(r"[\x00-\x1f\x7f]", " ", t)[:MAX_Q]


# ------------------------------------------------------------------------------------------------------------------------ period parsing
def _fy_bounds(org, d: dt.date):
    f = core.fy_start_for(org, d)
    return f, dt.date(f.year + 1, f.month, 1) - dt.timedelta(days=1)


def _month_bounds(y, m):
    return dt.date(y, m, 1), dt.date(y + (m == 12), m % 12 + 1, 1) - dt.timedelta(days=1)


def parse_period(q: str, today: dt.date, org) -> Optional[Tuple[dt.date, dt.date, str]]:
    t = q.lower()
    fy_s, fy_e = _fy_bounds(org, today)
    if re.search(r"\bthis month\b|\bmonth to date\b|\bmtd\b", t):
        return today.replace(day=1), today, "this month to date"
    if re.search(r"\blast month\b|\bprevious month\b", t):
        y, m = (today.year, today.month - 1) if today.month > 1 else (today.year - 1, 12)
        a, b = _month_bounds(y, m)
        return a, b, f"{a.strftime('%B %Y')}"
    if re.search(r"\blast (financial )?year\b|\blast fy\b|\bprevious (financial )?year\b|\bprior (financial )?year\b", t):
        a, b = _fy_bounds(org, fy_s - dt.timedelta(days=1))
        return a, b, f"last financial year ({a.isoformat()} to {b.isoformat()})"
    if re.search(r"\bthis (financial )?year\b|\bthis fy\b|\bytd\b|\byear to date\b|\bfinancial year to date\b", t):
        return fy_s, today, "financial year to date"
    m = re.search(r"\blast (\d{1,3}) (day|week|month)s?\b", t)
    if m:
        n, unit = int(m.group(1)), m.group(2)
        if unit == "day":
            return today - dt.timedelta(days=n - 1), today, f"last {n} days"
        if unit == "week":
            return today - dt.timedelta(days=7 * n - 1), today, f"last {n} weeks"
        y, mo = today.year, today.month - n
        while mo < 1:
            y, mo = y - 1, mo + 12
        a = dt.date(y, mo, 1)
        b = today.replace(day=1) - dt.timedelta(days=1)
        return a, b, f"last {n} complete months"
    if re.search(r"\bthis quarter\b|\blast quarter\b", t):
        qi = ((today.month - fy_s.month) % 12) // 3
        qs_y, qs_m = fy_s.year, fy_s.month + 3 * qi
        while qs_m > 12:
            qs_y, qs_m = qs_y + 1, qs_m - 12
        qs = dt.date(qs_y, qs_m, 1)
        if "last quarter" in t:
            pe = qs - dt.timedelta(days=1)
            ps_m, ps_y = pe.month - 2, pe.year
            if ps_m < 1:
                ps_m, ps_y = ps_m + 12, ps_y - 1
            return dt.date(ps_y, ps_m, 1), pe, "last quarter"
        return qs, today, "this quarter to date"
    m = re.search(r"\b(20\d{2})-(0[1-9]|1[0-2])\b", t)
    if m:
        a, b = _month_bounds(int(m.group(1)), int(m.group(2)))
        return a, b, a.strftime("%B %Y")
    m = re.search(r"\b(" + "|".join(sorted(MONTHS, key=len, reverse=True)) + r")\b(?:\s+(20\d{2}))?", t)
    if m and not re.search(r"\bmay\s+(i|we|you)\b", t):
        mo = MONTHS[m.group(1)]
        y = int(m.group(2)) if m.group(2) else (today.year if mo <= today.month else today.year - 1)
        a, b = _month_bounds(y, mo)
        return a, b, a.strftime("%B %Y")
    return None


# ------------------------------------------------------------------------------------------------------------------------ tools
class Ctx:
    def __init__(self, db, ctx, a, deadline):
        self.db, self.ctx, self.a, self.deadline, self.calls = db, ctx, a, deadline, []

    def tool(self, name: str, fn: Callable, cap: str, **params):
        if time.monotonic() > self.deadline:
            raise Refusal("That took too long, so I stopped without an answer. Please try a narrower question.", "timeout")
        self.a.require(cap)                                                 # permission is checked on EVERY invocation
        t0 = time.monotonic()
        try:
            data = fn(**params)
            self.calls.append(dict(tool=name, params={k: str(v) for k, v in params.items()}, ok=True, ms=int((time.monotonic() - t0) * 1000)))
            return data
        except core.PlanError as e:
            self.calls.append(dict(tool=name, params={k: str(v) for k, v in params.items()}, ok=False, ms=int((time.monotonic() - t0) * 1000), error=e.message[:200]))
            raise Refusal(f"I couldn't get that from {name.replace('_', ' ')}: {e.message}. I haven't estimated a figure.", "tool_error")
        except Exception as e:                                              # noqa: BLE001  never leak internals or guess a number
            self.calls.append(dict(tool=name, params={k: str(v) for k, v in params.items()}, ok=False, ms=int((time.monotonic() - t0) * 1000), error=type(e).__name__))
            raise Refusal(f"The {name.replace('_', ' ')} data is not available right now, so I can't answer. I haven't estimated a figure.", "tool_error")


def money(v) -> str:
    d = D(v)
    return ("-" if d < 0 else "") + "${:,.2f}".format(abs(d))


def _cite(report, metric, period, calc, source, basis="ACTUAL"):
    return dict(report=report, metric=metric, period=period, calculation=calc, source=source, basis=basis)


def t_cash_position(c: Ctx, as_at):
    recon = acc.bank_reconciliation_status(c.db, c.ctx.org, as_at)
    total = sum((r["ledger_balance"] for r in recon), ZERO)
    unrec = sum(r["unreconciled_count"] for r in recon)
    return dict(total=s(total), accounts=[dict(name=f"{r['code']} {r['name']}", balance=s(r["ledger_balance"])) for r in recon][:MAX_ROWS], account_count=len(recon), unreconciled=unrec, as_at=as_at.isoformat())


def t_profit_loss(c: Ctx, df, dt_):
    r = RP.profit_loss(c.db, c.ctx, c.a, df, dt_)
    return dict(revenue=r["totals"]["revenue"]["current"], expenses=r["totals"]["expenses"]["current"], net_profit=r["totals"]["net_profit"]["current"], prior_revenue=r["totals"]["revenue"]["previous"],
                prior_net_profit=r["totals"]["net_profit"]["previous"], prior_period=f"{r['comparison_from']} to {r['comparison_to']}", flags=[f["text"] for f in r["flags"]][:3])


def t_budget_status(c: Ctx, df, dt_):
    m = RP._default_budget(c.db, c.ctx, df, dt_)
    if m is None:
        raise core.PlanError("No approved budget covers that period")
    v = budgets.vs_actual(c.db, c.ctx, c.a, m.id, max(df, m.fy_start), dt_)
    tops = sorted([r for r in v["rows"] if r["account_class"] == "expense"], key=lambda r: D(r["variance"]))[:3]
    return dict(budget=m.name, revenue=v["totals"]["revenue"], expenses=v["totals"]["expenses"], profit=v["totals"]["profit"], worst_expenses=[dict(account=f"{r['code']} {r['name']}", variance=r["variance"], budget=r["budget"], actual=r["actual"]) for r in tops],
                period=f"{v['period_from']} to {v['period_to']}")


def t_forecast(c: Ctx, weeks):
    f = FC.build(c.db, c.ctx, c.a, granularity="week", periods=weeks)
    return dict(as_at=f["as_at"], weeks=f["periods"], opening=f["opening"]["balance"], closing=f["closing"], minimum=f["minimum"]["balance"], minimum_label=f["minimum"]["label"], threshold=f["threshold"],
                max_shortfall=f["shortfall"]["max_shortfall"], goes_negative=f["shortfall"]["goes_negative"], confidence=f["confidence"]["level"], confidence_reasons=f["confidence"]["reasons"][:3], warnings=f["warnings"][:3])


def t_overdue(c: Ctx, as_at):
    items = [i for i in acc.open_items(c.db, c.ctx.org, as_at) if i["side"] == "receivable"]
    over = [i for i in items if i["days_overdue"] > 0]
    by = {}
    for i in over:
        by[i["contact"]] = by.get(i["contact"], ZERO) + i["amount"]
    top = sorted(by.items(), key=lambda kv: (-kv[1], kv[0]))[:MAX_ROWS]
    return dict(total_receivable=s(sum((i["amount"] for i in items), ZERO)), overdue=s(sum((i["amount"] for i in over), ZERO)), overdue_invoices=len(over), top=[dict(customer=k, amount=s(v)) for k, v in top], as_at=as_at.isoformat())


def t_alerts(c: Ctx):
    r = RK.listing(c.db, c.ctx, c.a, status="new", limit=50)
    return dict(open=r["counts"]["new"], acknowledged=r["counts"]["acknowledged"], top=[dict(severity=a["severity"], title=a["title"], reason=a["reason"]) for a in r["alerts"][:MAX_ROWS]])


def t_insights(c: Ctx, df, dt_):
    r = INS.evaluate(c.db, c.ctx, c.a, df, dt_)
    return dict(counts=r["counts"], top=[dict(severity=i["severity"], title=i["title"], metric=i["metric"], actual=i["actual"], rule=i["rule"]) for i in r["insights"][:MAX_ROWS]], period=r["period_from"] + " to " + r["period_to"])


def t_kpis(c: Ctx, df, dt_):
    r = RP.kpis(c.db, c.ctx, c.a, df, dt_)
    return dict(kpis=[dict(label=k["label"], value=k["value"], previous=k["previous"], unit=k["unit"]) for k in r["kpis"]], period=f"{df.isoformat()} to {dt_.isoformat()}")


def t_whatif(c: Ctx, rev_pct, exp_pct):
    base = SC.base_plan(c.db, c.ctx, "run_rate", 12, core.business_today())
    a0 = SE.run(base, {})["summary"]
    a1 = SE.run(base, dict(revenue_change_pct=rev_pct, expense_change_pct=exp_pct))["summary"]
    return dict(months=12, base_profit=s(a0["profit"]), scenario_profit=s(a1["profit"]), profit_change=s(a1["profit"] - a0["profit"]), base_closing_cash=s(a0["closing_cash"]), scenario_closing_cash=s(a1["closing_cash"]),
                closing_cash_change=s(a1["closing_cash"] - a0["closing_cash"]), revenue_change_pct=str(rev_pct), expense_change_pct=str(exp_pct), base_source=base["provenance"]["detail"])


# ------------------------------------------------------------------------------------------------------------------------ intents
def _has(t, *words):
    return any(re.search(w, t) for w in words)


def classify(q: str) -> str:
    t = q.lower()
    if _has(t, r"\bwhat if\b", r"\bscenario", r"\bsuppose\b", r"\bif (our |the )?(revenue|sales|costs?|expenses?)\b"):
        return "whatif"
    if _has(t, r"\bforecast\b", r"\brunway\b", r"\bnext (\d+ )?(weeks?|13)", r"\brun out of (cash|money)", r"\blowest (cash|bank) ", r"\bshortfall\b", r"\bcash flow\b"):
        return "forecast"
    if _has(t, r"\bbudget", r"\bover budget\b", r"\bunder budget\b", r"\bvariance"):
        return "budget"
    if _has(t, r"\boverdue\b", r"\bowe(s|d)? us\b", r"\bwho owes\b", r"\breceivables?\b", r"\bunpaid invoices?\b", r"\bdebtors?\b"):
        return "overdue"
    if _has(t, r"\balerts?\b", r"\banomal", r"\bunusual\b", r"\bsuspicious\b", r"\bdupl", r"\brisk"):
        return "alerts"
    if _has(t, r"\binsights?\b", r"\badvice\b", r"\bhow (are|is) (we|the business|things)\b", r"\bany concerns\b", r"\bwhat should i (know|worry)"):
        return "insights"
    if _has(t, r"\bkpis?\b", r"\bmargin", r"\bratio\b", r"\bdso\b", r"\bdpo\b"):
        return "kpis"
    if _has(t, r"\bprofit", r"\brevenue\b", r"\bsales\b", r"\bincome\b", r"\bexpenses?\b", r"\bspend", r"\bturnover\b", r"\bloss\b"):
        return "profit"
    if _has(t, r"\bcash\b", r"\bbank\b", r"\bbalance\b", r"\bhow much money\b"):
        return "cash"
    return "unknown"


SUGGESTIONS = ["What is our bank balance?", "What was our profit last month?", "Will we run out of cash in the next 13 weeks?", "Which customers are overdue?", "How are we tracking against budget this financial year?",
               "What if revenue drops 10%?", "Are there any unusual transactions?", "Any concerns I should know about?"]


def _period_options(q: str):
    base = re.sub(r"[?.!]+$", "", q.strip())
    return [f"{base} last month", f"{base} this financial year", f"{base} this month"]


def _clarify(msg, options):
    return dict(status="clarify", answer=msg, clarification=dict(question=msg, options=options), citations=[], figures=[])


def _answer(intent, c: Ctx, q: str, today: dt.date) -> dict:
    org = c.ctx.org
    per = parse_period(q, today, org)
    if intent == "cash":
        d = c.tool("cash_position", lambda: t_cash_position(c, today), "view")
        txt = f"Your ledger bank balance at {d['as_at']} is {money(d['total'])} across {d['account_count']} bank account(s)."
        if d["unreconciled"]:
            txt += f" Note: {d['unreconciled']} bank lines are not reconciled yet."
        return dict(status="ok", answer=txt, data=d, citations=[_cite("Bank balances", "Ledger bank balance", f"as at {d['as_at']}", "sum of bank account ledger balances", "ledger journals (posted)")])
    if intent == "profit":
        if per is None:
            return _clarify("Which period do you mean?", _period_options(q))
        df, dt_, label = per
        d = c.tool("profit_loss", lambda: t_profit_loss(c, df, dt_), "view")
        t = q.lower()
        parts = []
        if re.search(r"\brevenue\b|\bsales\b|\bincome\b|\bturnover\b", t):
            parts.append(f"revenue was {money(d['revenue'])}")
        if re.search(r"\bexpenses?\b|\bspend", t):
            parts.append(f"expenses were {money(d['expenses'])}")
        if re.search(r"\bprofit\b|\bloss\b", t) or not parts:
            parts.append(f"net profit was {money(d['net_profit'])}")
        txt = f"For {label} ({df.isoformat()} to {dt_.isoformat()}), " + " and ".join(parts) + f". The previous period of equal length ({d['prior_period']}) had revenue {money(d['prior_revenue'])} and net profit {money(d['prior_net_profit'])}."
        if d["flags"]:
            txt += " Data note: " + d["flags"][0]
        return dict(status="ok", answer=txt, data=d, citations=[_cite("Profit and loss", "Revenue, expenses, net profit", f"{df.isoformat()} to {dt_.isoformat()}", "revenue - expenses", "ledger journals (posted)")])
    if intent == "budget":
        if per is None:
            return _clarify("Which period should I compare with the budget?", _period_options(q))
        df, dt_, label = per
        d = c.tool("budget_status", lambda: t_budget_status(c, df, dt_), "view")
        p = d["profit"]
        txt = f"Against budget '{d['budget']}' for {label}: profit was {money(p['actual'])} versus a budget of {money(p['budget'])} (variance {money(p['variance'])}; positive is favourable)."
        if d["worst_expenses"]:
            w = d["worst_expenses"][0]
            txt += f" The expense line furthest from budget is {w['account']} (variance {money(w['variance'])})."
        return dict(status="ok", answer=txt, data=d, citations=[_cite("Budget vs actual", "Profit variance", d["period"], "actual profit - budget profit", f"budget '{d['budget']}' + ledger actuals")])
    if intent == "forecast":
        m = re.search(r"\b(\d{1,2})[ -]?weeks?\b", q.lower())
        weeks = int(m.group(1)) if m else 13
        if not 1 <= weeks <= 52:
            return _clarify("How many weeks ahead (1 to 52)?", ["Will we run out of cash in the next 13 weeks?", "What is the cash forecast for 26 weeks?"])
        d = c.tool("cash_forecast", lambda: t_forecast(c, weeks), "view")
        txt = f"FORECAST (not actual), {d['weeks']} weeks from {d['as_at']}: cash is projected to move from {money(d['opening'])} to {money(d['closing'])}; the lowest projected balance is {money(d['minimum'])} ({d['minimum_label']})."
        txt += (f" That is {money(d['max_shortfall'])} below your minimum of {money(d['threshold'])}." if D(d["max_shortfall"]) > 0 else " It stays above your minimum balance.")
        txt += f" Confidence: {d['confidence']}" + (" - " + "; ".join(d["confidence_reasons"]) if d["confidence"] == "indicative" else "") + "."
        return dict(status="ok", answer=txt, data=d, citations=[_cite("13-week cash forecast", "Projected closing and minimum balance", f"{d['weeks']} weeks from {d['as_at']}", "opening + committed and expected receipts - payments", "ledger, open invoices/bills, loans, tax obligations", "FORECAST")])
    if intent == "overdue":
        d = c.tool("overdue_receivables", lambda: t_overdue(c, today), "view")
        txt = f"At {d['as_at']}, receivables total {money(d['total_receivable'])} of which {money(d['overdue'])} is overdue across {d['overdue_invoices']} invoice(s)."
        if d["top"]:
            txt += " Largest overdue customers: " + "; ".join(f"{x['customer']} {money(x['amount'])}" for x in d["top"]) + "."
        return dict(status="ok", answer=txt, data=d, citations=[_cite("Receivables ageing", "Overdue receivables", f"as at {d['as_at']}", "sum of open invoices past due date", "sales sub-ledger")])
    if intent == "alerts":
        d = c.tool("open_alerts", lambda: t_alerts(c), "view")
        txt = f"There are {d['open']} new alert(s) awaiting review and {d['acknowledged']} acknowledged. Alerts mean 'unusual, please review', not that something is wrong."
        if d["top"]:
            txt += " Top items: " + "; ".join(f"[{x['severity']}] {x['title']}" for x in d["top"]) + "."
        return dict(status="ok", answer=txt, data=d, citations=[_cite("Risk & anomaly alerts", "Open alerts", "current", "rule engine results awaiting review", "plan_alerts")])
    if intent == "insights":
        df, dt_, label = per if per else (core.fy_start_for(org, today), today, "financial year to date")
        d = c.tool("cfo_insights", lambda: t_insights(c, df, dt_), "view")
        txt = f"For {label}: {d['counts']['high']} high, {d['counts']['medium']} medium and {d['counts']['low']} low priority insight(s)."
        if d["top"]:
            txt += " Most important: " + "; ".join(f"[{x['severity']}] {x['title']}" for x in d["top"][:3]) + "."
        else:
            txt += " No rule was triggered."
        return dict(status="ok", answer=txt, data=d, citations=[_cite("CFO insights", "Rule results", d["period"], "named rules over ledger facts (see Insights)", "ledger, budgets, forecast")])
    if intent == "kpis":
        if per is None:
            return _clarify("Which period should the KPIs cover?", _period_options(q))
        df, dt_, label = per
        d = c.tool("kpis", lambda: t_kpis(c, df, dt_), "view")
        txt = f"KPIs for {label}: " + "; ".join(f"{k['label']} {k['value'] if k['value'] is not None else 'n/a'}" for k in d["kpis"][:6]) + "."
        return dict(status="ok", answer=txt, data=d, citations=[_cite("KPIs", "Key performance indicators", d["period"], "see KPI calculations in Reports", "ledger")])
    if intent == "whatif":
        t = q.lower()
        rev = exp = None
        m = re.search(r"(revenue|sales|income)[^.\d%-]{0,40}?(drop|fall|fell|decrease|decline|down|reduce|lower|increase|rise|grow|up|by)?[^.\d%-]{0,15}?(-?\d{1,3}(?:\.\d+)?)\s*%", t)
        if m:
            v = Decimal(m.group(3))
            rev = -abs(v) if re.search(r"drop|fall|fell|decreas|declin|down|reduc|lower", m.group(0)) else abs(v) if re.search(r"increas|rise|grow|\bup\b", m.group(0)) else v
        m = re.search(r"(costs?|expenses?|spend)[^.\d%-]{0,40}?(drop|fall|decrease|decline|down|reduce|lower|increase|rise|grow|up|by)?[^.\d%-]{0,15}?(-?\d{1,3}(?:\.\d+)?)\s*%", t)
        if m:
            v = Decimal(m.group(3))
            exp = -abs(v) if re.search(r"drop|fall|decreas|declin|down|reduc|lower", m.group(0)) else abs(v) if re.search(r"increas|rise|grow|\bup\b", m.group(0)) else v
        if rev is None and exp is None:
            return _clarify("Which assumption should I test, and by how much?", ["What if revenue drops 10%?", "What if costs increase 5%?", "What if revenue falls 15% and costs rise 3%?"])
        d = c.tool("adhoc_scenario", lambda: t_whatif(c, rev or ZERO, exp or ZERO), "view")
        txt = (f"HYPOTHETICAL (not a forecast), 12 months on the {d['base_source']}: with revenue {d['revenue_change_pct']}% and expenses {d['expense_change_pct']}%, profit would be {money(d['scenario_profit'])} "
               f"versus {money(d['base_profit'])} ({money(d['profit_change'])}), and closing cash {money(d['scenario_closing_cash'])} versus {money(d['base_closing_cash'])}. Save it in Scenario Planning to keep it.")
        return dict(status="ok", answer=txt, data=d, citations=[_cite("Scenario engine", "Profit and closing cash change", "next 12 months", "base plan with assumptions applied (not saved)", d["base_source"], "SCENARIO (hypothetical)")])
    return _clarify("I can answer questions about your cash, profit and revenue, budget, forecast, overdue invoices, alerts, KPIs and simple what-ifs. What would you like to know?", SUGGESTIONS[:5])


# ------------------------------------------------------------------------------------------------------------------------ number verification
def _nums(text: str) -> set:
    out = set()
    for tok in NUM.findall(MONTH_YEAR.sub(" ", ISO.sub(" ", text or ""))):
        try:
            out.add(abs(Decimal(tok.replace(",", ""))))
        except InvalidOperation:
            pass
    return out


def _leaf_numbers(obj) -> set:
    out = set()
    if isinstance(obj, dict):
        for v in obj.values():
            out |= _leaf_numbers(v)
    elif isinstance(obj, (list, tuple)):
        for v in obj:
            out |= _leaf_numbers(v)
    elif obj is not None:
        out |= _nums(str(obj))
    return out


def verify(answer: str, data, question: str, extra: str = "") -> bool:
    """Every number in the answer must come from tool data, the user's own question or the stated period. Small word-numbers (1-2 digit) from the sentence skeleton are
    allowed only if they appear in those sources too - so a hallucinated figure cannot slip through."""
    allowed = _leaf_numbers(data) | _nums(question) | _nums(extra) | {Decimal(0)}
    return all(n in allowed for n in _nums(answer))


# ------------------------------------------------------------------------------------------------------------------------ entry point
def rate_limit() -> int:
    try:
        return max(1, int(os.getenv("ACCFINO_PLAN_AI_RATE", "30")))
    except ValueError:
        return 30


def ask(db, ctx, a, question: str, today: Optional[dt.date] = None) -> dict:
    """Answer one question. Identity (organisation, user, role) comes from the signed-in context only; nothing in `question` can change it."""
    a.require("ai")
    q = (question or "").strip()
    if not q:
        raise core.PlanError("Please type a question")
    if len(q) > MAX_Q:
        raise core.PlanError(f"Please keep the question under {MAX_Q} characters")
    since = dt.datetime.utcnow() - dt.timedelta(hours=1)
    used = db.query(P.PlanAiLog).filter(P.PlanAiLog.org_id == ctx.org.id, P.PlanAiLog.user_id == ctx.user_id, P.PlanAiLog.created_at >= since).count()
    if used >= rate_limit():
        raise core.PlanError(f"Assistant limit reached ({rate_limit()} questions per hour). Please try again later.", 429, "rate_limited")
    today = today or core.business_today()
    t0 = time.monotonic()
    c = Ctx(db, ctx, a, t0 + float(os.getenv("ACCFINO_PLAN_AI_TIMEOUT", "20")))
    intent, res = "unknown", None
    try:
        if INJECT.search(q):
            raise Refusal("I only answer questions about this organisation's own financial data, and I can't follow instructions that change how I work.", "refused_injection")
        if CROSS.search(q):
            raise Refusal("I can only see the organisation you are signed in to. I can't look at other organisations or tenants.", "refused_scope")
        if MUTATE.search(q):
            raise Refusal("I'm read-only: I can't post, change, approve or delete anything. I can show you the figures so you can make the change yourself in the right screen.", "refused_write")
        intent = classify(q)
        res = _answer(intent, c, q, today)
        if res["status"] == "ok":
            extra = " ".join(str(v) for v in res.get("data", {}).values() if isinstance(v, str)) + " " + " ".join(x.get("period", "") for x in res["citations"])
            if not verify(res["answer"], res.get("data"), q, extra):
                c.calls.append(dict(tool="verify", ok=False))
                res = dict(status="error", answer="I couldn't verify every number in my answer against your reports, so I'm not showing it. Please open the report directly.", citations=[], figures=[])
    except Refusal as r:
        status = "refused" if r.code.startswith("refused") else ("limited" if r.code == "timeout" else "error")
        res = dict(status=status, answer=r.text, citations=[], figures=[])
    except core.Forbidden:
        raise
    res.setdefault("citations", [])
    res["answer"] = res["answer"][:MAX_ANSWER]
    res.update(intent=intent, read_only=True, label=LABEL, tools=c.calls, organisation=ctx.org.name, user=ctx.username)
    res.pop("figures", None)
    ms = int((time.monotonic() - t0) * 1000)
    db.add(P.PlanAiLog(org_id=ctx.org.id, user_id=ctx.user_id, question=mask(q), intent=intent, tools=core.plain(c.calls), status={"ok": "ok", "clarify": "clarify", "refused": "refused", "limited": "limited"}.get(res["status"], "error"),
                       answer_hash=hashlib.sha256(res["answer"].encode()).hexdigest(), duration_ms=ms))
    core.audit(db, ctx, "ai.ask", "plan_ai_log", None, intent=intent, status=res["status"], tools=[x["tool"] for x in c.calls], ms=ms)
    return res


def history(db, ctx, a, limit: int = 30) -> List[dict]:
    a.require("ai")
    q = db.query(P.PlanAiLog).filter_by(org_id=ctx.org.id)
    if not (a.has("config")):
        q = q.filter(P.PlanAiLog.user_id == ctx.user_id)             # people see their own questions; admins/accountants see all
    return [dict(id=r.id, question=r.question, intent=r.intent, status=r.status, tools=[t.get("tool") for t in (r.tools or [])], at=r.created_at.isoformat()) for r in q.order_by(P.PlanAiLog.id.desc()).limit(max(1, min(limit, 100)))]
