"""CFO insights (pure). Every insight is the result of a named rule over supplied facts; nothing is estimated or invented, and no external benchmark is used unless
the organisation configured one WITH a citation. Clean data produces no high-severity insight."""
from decimal import Decimal
from typing import Dict, List, Optional

from .money import D, pct, q2, s, ZERO

RULESET_VERSION = "insights-1.0"
DEFAULTS = dict(runway_high_months=3, runway_medium_months=6, overdue_medium_pct=30, overdue_high_pct=50, margin_drop_pp=5, revenue_decline_pct=15, expense_growth_pct=20,
                concentration_pct=40, budget_profit_shortfall_pct=10, min_history_months=3, min_revenue=1000)
SEV_ORDER = {"high": 0, "medium": 1, "low": 2, "info": 3}


def _ins(rule, severity, title, metric, facts, actual, comparison, calc, sources, why, rec, confidence="medium", limitations=None):
    return dict(rule=rule, rule_version=RULESET_VERSION, severity=severity, title=title, metric=metric, period=facts["period"], actual=actual, comparison=comparison, calculation=calc,
                sources=sources, why_it_matters=why, recommendation=dict(label="Recommendation", text=rec), confidence=confidence, limitations=limitations or [])


def evaluate(f: dict, cfg: Optional[dict] = None) -> List[dict]:
    """f = facts dict (see services.insights.gather_facts). cfg overrides DEFAULTS. Returns insights sorted by severity then rule id (deterministic)."""
    c = dict(DEFAULTS, **(cfg or {}))
    out: List[dict] = []
    src = f.get("sources", {})
    hist = f.get("months_of_history", 0)
    rev, prev = D(f.get("revenue", 0)), D(f.get("prior_revenue", 0))
    exp, pexp = D(f.get("expenses", 0)), D(f.get("prior_expenses", 0))
    profit, pprofit = D(f.get("net_profit", 0)), D(f.get("prior_profit", 0))
    cash = f.get("cash_closing")
    cash = D(cash) if cash is not None else None

    if cash is not None and cash < 0:
        out.append(_ins("CF-NEG-CASH", "high", "Bank balance is negative", "Closing cash", f, s(cash), "0.00", "closing bank balance < 0", [src.get("cash")],
                        "A negative bank balance usually means an overdraft or unreconciled entries.", "Review bank reconciliation and arrange funding if the overdraft is real.", "high"))
    burn = f.get("avg_monthly_burn")
    if cash is not None and burn is not None and D(burn) > 0 and hist >= c["min_history_months"] and cash >= 0:
        runway = (cash / D(burn)).quantize(Decimal("0.1"))
        sev = "high" if runway < c["runway_high_months"] else "medium" if runway < c["runway_medium_months"] else None
        if sev:
            out.append(_ins("CF-RUNWAY", sev, f"Cash covers about {runway} months at the current burn", "Cash runway (months)", f, str(runway), f">= {c['runway_medium_months']} months",
                            f"closing cash {s(cash)} / average monthly net cash outflow {s(burn)} over {hist} months", [src.get("cash")],
                            "A short runway limits time to act if income slips.", "Review upcoming payments and consider timing, funding or cost options.", "medium",
                            ["Assumes the recent average outflow continues; irregular large payments can distort it."]))
    sf = f.get("forecast_shortfall")
    if sf is not None and D(sf.get("max_shortfall", 0)) > 0:
        sev = "high" if sf.get("goes_negative") else "medium"
        out.append(_ins("CF-SHORTFALL", sev, "The cash forecast dips below your minimum balance", "Forecast minimum balance", f, s(sf["minimum"]), s(sf["threshold"]),
                        f"lowest projected closing balance {s(sf['minimum'])} vs minimum {s(sf['threshold'])} ({sf.get('label')})", [src.get("forecast")],
                        "A projected shortfall is the earliest warning that payments may not be covered.", "Review the weeks around the low point: chase receivables, defer discretionary payments, or arrange funding.",
                        sf.get("confidence", "medium"), ["Forecast is indicative when history is short; see the forecast assumptions."]))
    if rev >= c["min_revenue"] and profit < 0:
        out.append(_ins("PR-LOSS", "medium", "The period shows a loss", "Net profit", f, s(profit), s(pprofit), f"revenue {s(rev)} - expenses {s(exp)} = {s(profit)}", [src.get("pl")],
                        "Sustained losses draw down cash and equity.", "Review the largest expense lines against budget and last period.", "high"))
    gm, pgm = f.get("gross_margin_pct"), f.get("prior_gross_margin_pct")
    if gm is not None and pgm is not None and D(pgm) - D(gm) >= c["margin_drop_pp"] and rev >= c["min_revenue"]:
        out.append(_ins("PR-MARGIN", "medium", "Gross margin fell", "Gross margin %", f, f"{gm}%", f"{pgm}% prior period", f"(revenue - direct costs) / revenue: {gm}% vs {pgm}%", [src.get("pl")],
                        "A falling margin means each dollar of sales leaves less to cover overheads.", "Check pricing and direct-cost lines for the period.", "high"))
    if prev >= c["min_revenue"]:
        ch = pct(rev - prev, prev)
        if ch is not None and ch <= -D(c["revenue_decline_pct"]):
            out.append(_ins("RV-DECLINE", "medium", "Revenue is down on the prior period", "Revenue change %", f, f"{ch}%", f"prior {s(prev)}", f"({s(rev)} - {s(prev)}) / {s(prev)}", [src.get("pl")],
                            "A falling top line is the main driver of cash pressure.", "Look at which customers or products moved.", "high"))
    if pexp >= c["min_revenue"]:
        eg = pct(exp - pexp, pexp)
        rg = pct(rev - prev, prev) if prev else None
        if eg is not None and eg >= D(c["expense_growth_pct"]) and (rg is None or rg < eg / 2):
            out.append(_ins("EX-GROWTH", "medium", "Expenses grew faster than revenue", "Expense change %", f, f"{eg}%", f"revenue change {rg}%" if rg is not None else "no revenue comparison",
                            f"({s(exp)} - {s(pexp)}) / {s(pexp)}", [src.get("pl")], "Costs growing faster than sales squeeze profit.", "Review the accounts with the biggest increases.", "high"))
    ar, ao = D(f.get("ar_total", 0)), D(f.get("ar_overdue", 0))
    if ar > 0:
        op = pct(ao, ar)
        if op is not None and op >= c["overdue_medium_pct"]:
            out.append(_ins("AR-OVERDUE", "high" if op >= c["overdue_high_pct"] else "medium", "A large share of receivables is overdue", "Overdue receivables %", f, f"{op}%",
                            f"{c['overdue_medium_pct']}% threshold", f"overdue {s(ao)} / total receivables {s(ar)}", [src.get("ar")],
                            "Overdue invoices delay cash you have already earned.", "Follow up the oldest invoices first.", "high"))
    cs = f.get("top_customer_share")
    if cs and D(cs["pct"]) >= c["concentration_pct"]:
        out.append(_ins("CONC-CUSTOMER", "low", "Revenue depends heavily on one customer", "Top customer share", f, f"{cs['pct']}%", f"{c['concentration_pct']}% threshold",
                        f"revenue booked to '{cs['name']}' / total revenue", [src.get("pl")], "Losing a dominant customer would hit income sharply.", "Consider diversification and payment terms for this customer.", "medium",
                        ["Based on the contact name recorded on ledger revenue lines; lines without a contact are not attributed."]))
    ca, cl = f.get("current_assets"), f.get("current_liabilities")
    if ca is not None and cl is not None and D(cl) > 0 and D(ca) / D(cl) < 1:
        ratio = (D(ca) / D(cl)).quantize(Decimal("0.01"))
        out.append(_ins("LIQ-CURRENT", "medium", "Current liabilities exceed current assets", "Current ratio", f, str(ratio), "1.00", f"current assets {s(ca)} / current liabilities {s(cl)}", [src.get("bs")],
                        "A ratio below 1 means short-term obligations exceed short-term resources.", "Review payment timing and funding.", "medium",
                        ["Current/non-current classification follows your chart-of-accounts types."]))
    bv = f.get("budget_profit")
    if bv and bv.get("budget") is not None and D(bv["budget"]) != 0:
        p_ = pct(D(bv["variance"]), abs(D(bv["budget"])))
        if p_ is not None and p_ <= -D(c["budget_profit_shortfall_pct"]):
            out.append(_ins("BUD-PROFIT", "medium", "Profit is behind budget", "Profit vs budget", f, s(bv["actual"]), s(bv["budget"]), f"actual {s(bv['actual'])} vs budget {s(bv['budget'])} ({p_}%)", [src.get("budget")],
                            "Being behind budget reduces the room to absorb surprises.", "See Budgeting for the accounts driving the gap.", "high"))
    dq = f.get("data_quality", {})
    issues = []
    if dq.get("unreconciled_bank_lines"):
        issues.append(f"{dq['unreconciled_bank_lines']} unreconciled bank lines")
    if dq.get("suspense_balance") and D(dq["suspense_balance"]) != 0:
        issues.append(f"suspense account holds {s(dq['suspense_balance'])}")
    if issues:
        out.append(_ins("DQ-BOOKS", "low", "Bookkeeping needs attention before relying on these figures", "Data quality", f, "; ".join(issues), "none", "counts from bank lines and the suspense account", [src.get("cash")],
                        "Unreconciled items make every cash-based figure less reliable.", "Reconcile bank lines and clear the suspense account.", "high"))
    if hist < c["min_history_months"]:
        out.append(_ins("DATA-HISTORY", "info", "Not enough history for trend-based insights", "Months of history", f, str(hist), f">= {c['min_history_months']}", "months with ledger activity", [src.get("pl")],
                        "Trend rules (runway, comparisons) are withheld until there is enough history.", "Insights will appear as more months are recorded.", "high"))
    return sorted(out, key=lambda i: (SEV_ORDER[i["severity"]], i["rule"]))


def validate_benchmarks(items) -> List[dict]:
    """A benchmark is accepted ONLY with a metric, a numeric value, an as-of year, a source name and an http(s) URL. Anything else is rejected."""
    out = []
    for b in items or []:
        try:
            val = D(b.get("value"))
        except ValueError:
            raise ValueError("benchmark value must be a number")
        src, url = str(b.get("source") or "").strip(), str(b.get("source_url") or "").strip()
        if not b.get("metric") or not src or not url.startswith(("http://", "https://")) or not b.get("as_of"):
            raise ValueError("A benchmark needs a metric, value, as_of, source and a source_url (http/https). Unsourced benchmarks are not accepted.")
        out.append(dict(metric=str(b["metric"])[:60], value=str(val), as_of=str(b["as_of"])[:20], source=src[:200], source_url=url[:400], note=str(b.get("note") or "")[:200]))
    return out
