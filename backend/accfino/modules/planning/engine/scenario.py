"""Scenario engine (pure, deterministic). A scenario is a set of assumptions applied to a BASE plan; it never touches the ledger. Everything is Decimal."""
import copy
from decimal import Decimal
from typing import Dict, List, Optional, Sequence

from .money import D, q2, s, pct, ZERO

# assumption keys and bounds (percent values are percentage points, e.g. -10 = minus 10%)
SCHEMA = {
    "revenue_change_pct": (-100, 500), "expense_change_pct": (-100, 500), "inflation_pct": (0, 50), "payroll_change_pct": (-100, 500),
    "payment_delay_days": (-60, 180), "loan_extra_monthly": (0, 10_000_000), "new_loan_amount": (0, 1_000_000_000), "new_loan_month": (1, 36),
    "new_loan_monthly_repayment": (0, 10_000_000), "interest_rate_change_pp": (-20, 20), "debt_balance": (0, 1_000_000_000),
}
TEMPLATES = {
    "base": dict(label="Base", note="No changes: the plan continues at its current run-rate.", assumptions={}),
    "optimistic": dict(label="Optimistic", note="A template to adjust: revenue +10%, costs +2%, customers pay 5 days sooner. These are illustrative defaults, not forecasts.",
                       assumptions=dict(revenue_change_pct=10, expense_change_pct=2, payment_delay_days=-5)),
    "downside": dict(label="Downside", note="A template to adjust: revenue -15%, costs +3%, inflation 4%, customers pay 15 days later. These are illustrative defaults, not forecasts.",
                     assumptions=dict(revenue_change_pct=-15, expense_change_pct=3, inflation_pct=4, payment_delay_days=15)),
}
LIMITATIONS = [
    "A scenario applies your assumptions to a base plan; it is not a prediction.",
    "Base cash assumes profit converts to cash in the same month (steady state); only the payment-delay assumption moves cash timing.",
    "Interest effects need the debt balance you enter; AccFino does not infer it.",
    "Tax, GST and one-off items are not modelled unless included in the base plan.",
]


def validate(assumptions: dict) -> dict:
    """Return the assumptions as Decimals (hires validated separately). Raises ValueError with a readable message for unknown keys, non-numbers or out-of-range values."""
    out = {}
    for k, v in (assumptions or {}).items():
        if k == "hires":
            continue
        if k not in SCHEMA:
            raise ValueError(f"Unknown assumption '{k}'")
        d = D(v)
        lo, hi = SCHEMA[k]
        if d < lo or d > hi:
            raise ValueError(f"'{k}' must be between {lo} and {hi}")
        out[k] = d
    return out


def validate_hires(hires) -> List[dict]:
    out = []
    for h in hires or []:
        n, start, cost = int(D(h.get("count", 1))), int(D(h.get("start_month", 1))), D(h.get("monthly_cost", 0))
        if n < 1 or n > 500 or start < 1 or start > 36 or cost < 0 or cost > 1_000_000:
            raise ValueError("hire needs count 1-500, start_month 1-36 and monthly_cost 0-1,000,000 (loaded cost incl. super)")
        out.append(dict(count=n, start_month=start, monthly_cost=q2(cost), label=str(h.get("label") or "New hire")[:60]))
    return out


def _delay(series: List[Decimal], days: Decimal) -> (List[Decimal], Decimal):
    """Shift receipts later (days>0) or earlier (days<0). Returns (receipts by month, amount that moved beyond the horizon = extra receivables). Earlier is limited to month 1."""
    n = len(series)
    k, rem = divmod(int(abs(days)), 30)
    frac = Decimal(rem) / 30
    out = [ZERO] * n
    beyond = ZERO
    sign = 1 if days >= 0 else -1
    for i, v in enumerate(series):
        a, b = v * (1 - frac), v * frac
        for amt, shift in ((a, sign * k), (b, sign * (k + 1) if sign > 0 else sign * (k + 1))):
            j = i + shift
            if j < 0:
                j = 0
            if j >= n:
                beyond += amt
            else:
                out[j] += amt
    return out, beyond


def run(base: dict, assumptions: dict, hires=None) -> dict:
    """base = {opening_cash, months: [{month, revenue, direct_costs, payroll, opex, debt_service}]} (natural positive amounts; debt_service = scheduled cash repayments).
    Returns monthly results and a summary. Pure function: the same inputs always give the same output."""
    a = validate(assumptions)
    hires = validate_hires(hires if hires is not None else (assumptions or {}).get("hires"))
    g = lambda k: a.get(k, ZERO)
    months = base["months"]
    n = len(months)
    infl = g("inflation_pct") / 100
    rows, rev_series = [], []
    for i, m in enumerate(months):
        rev = D(m["revenue"]) * (1 + g("revenue_change_pct") / 100)
        f_infl = (1 + infl / 12) ** (i + 1) if infl else Decimal(1)
        dc = D(m["direct_costs"]) * (1 + g("expense_change_pct") / 100) * f_infl
        opx = D(m["opex"]) * (1 + g("expense_change_pct") / 100) * f_infl
        pay = D(m["payroll"]) * (1 + g("payroll_change_pct") / 100) * f_infl
        hire_cost = sum((h["monthly_cost"] * h["count"] for h in hires if i + 1 >= h["start_month"]), ZERO)
        interest_delta = g("debt_balance") * g("interest_rate_change_pp") / 100 / 12
        exp = dc + opx + pay + hire_cost + interest_delta
        rows.append(dict(month=m["month"], revenue=rev, direct_costs=dc, opex=opx, payroll=pay, hires=hire_cost, interest_change=interest_delta, expenses=exp, profit=rev - exp,
                         debt_service=D(m.get("debt_service", 0)) + g("loan_extra_monthly") + (g("new_loan_monthly_repayment") if g("new_loan_amount") and i + 1 > g("new_loan_month") else ZERO)))
        rev_series.append(rev)
    receipts, beyond = _delay(rev_series, g("payment_delay_days")) if g("payment_delay_days") else (rev_series, ZERO)
    bal = D(base["opening_cash"])
    lowest = None
    for i, r in enumerate(rows):
        loan_in = g("new_loan_amount") if g("new_loan_amount") and i + 1 == int(g("new_loan_month") or 1) else ZERO
        r["cash_receipts"] = receipts[i]
        r["cash_in_loan"] = loan_in
        r["net_cash"] = receipts[i] + loan_in - r["expenses"] - r["debt_service"]
        bal += r["net_cash"]
        r["closing_cash"] = bal
        if lowest is None or bal < lowest[1]:
            lowest = (r["month"], bal)
    tot = lambda k: sum((r[k] for r in rows), ZERO)
    for r in rows:
        for k in list(r):
            if k != "month":
                r[k] = q2(r[k])
    summary = dict(revenue=q2(tot("revenue")), expenses=q2(tot("expenses")), profit=q2(tot("profit")), net_cash=q2(tot("net_cash")), closing_cash=q2(bal),
                   lowest_cash=dict(month=lowest[0], balance=q2(lowest[1])) if lowest else None, receivables_increase=q2(beyond), months=n,
                   profit_margin_pct=pct(tot("profit"), tot("revenue")))
    return dict(months=rows, summary=summary, assumptions={k: str(v) for k, v in a.items()}, hires=[dict(h, monthly_cost=str(h["monthly_cost"])) for h in hires], limitations=LIMITATIONS)


def compare(results: Dict[str, dict], reference: str) -> List[dict]:
    """Side-by-side deltas against a reference result: [{name, revenue, profit, closing_cash, lowest_cash, d_profit, d_closing_cash}]."""
    ref = results[reference]["summary"]
    out = []
    for name, r in results.items():
        sm = r["summary"]
        out.append(dict(name=name, revenue=sm["revenue"], expenses=sm["expenses"], profit=sm["profit"], closing_cash=sm["closing_cash"], lowest_cash=sm["lowest_cash"],
                        d_profit=q2(sm["profit"] - ref["profit"]), d_closing_cash=q2(sm["closing_cash"] - ref["closing_cash"]), is_reference=(name == reference)))
    return out


def sensitivity(base: dict, assumptions: dict, steps: Sequence[Decimal] = (Decimal(-10), Decimal(10))) -> List[dict]:
    """One-at-a-time sensitivity around the scenario: revenue, expenses, payroll move by each step (percentage points); payment timing by +/-10 days.
    Returns rows ranked by absolute profit impact (ties by name): [{driver, step, profit_delta, closing_cash_delta}]."""
    ref = run(base, assumptions)["summary"]
    out = []
    for key in ("revenue_change_pct", "expense_change_pct", "payroll_change_pct"):
        for st in steps:
            a = dict(assumptions)
            a[key] = D(a.get(key, 0)) + st
            sm = run(base, {k: v for k, v in a.items() if k != "hires"}, assumptions.get("hires"))["summary"]
            out.append(dict(driver=key, step=str(st), profit_delta=q2(sm["profit"] - ref["profit"]), closing_cash_delta=q2(sm["closing_cash"] - ref["closing_cash"])))
    for dd in (Decimal(-10), Decimal(10)):
        a = dict(assumptions)
        a["payment_delay_days"] = D(a.get("payment_delay_days", 0)) + dd
        sm = run(base, {k: v for k, v in a.items() if k != "hires"}, assumptions.get("hires"))["summary"]
        out.append(dict(driver="payment_delay_days", step=str(dd), profit_delta=q2(sm["profit"] - ref["profit"]), closing_cash_delta=q2(sm["closing_cash"] - ref["closing_cash"])))
    return sorted(out, key=lambda r: (-max(abs(r["profit_delta"]), abs(r["closing_cash_delta"])), r["driver"], D(r["step"])))
