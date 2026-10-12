"""Budget maths (pure): variance with the favourable-positive convention, percent that never divides by zero, remaining budget, year-end projection, interval spreading."""
import datetime as dt
from decimal import Decimal
from typing import Dict, List, Optional, Sequence

from .money import D, q2, s, pct, spread, ZERO

REVENUE_CLASSES = ("revenue",)


def variance(account_class: str, budget, actual) -> dict:
    """Favourable is positive: revenue = actual - budget, expense = budget - actual. percent is None when the budget is zero (flagged `zero_budget`);
    a negative budget is accepted (credit/refund lines) and flagged `negative_budget`, its percent uses the absolute budget."""
    b, a = q2(budget), q2(actual)
    v = (a - b) if account_class == "revenue" else (b - a)
    flags = []
    if b == 0:
        flags.append("zero_budget" if a == 0 else "unbudgeted_actual")
    if b < 0:
        flags.append("negative_budget")
    return dict(budget=b, actual=a, variance=v, variance_pct=pct(v, abs(b)) if b != 0 else None, favourable=(v >= 0), flags=flags)


def rows_vs_actual(accounts: Sequence[dict], budget_by: Dict[int, Decimal], actual_by: Dict[int, Decimal]) -> List[dict]:
    """accounts: [{id, code, name, class}]. One row per account that has a budget or an actual, sorted by code; totals are computed by `totals`."""
    out = []
    for a in sorted(accounts, key=lambda x: x["code"]):
        b, ac = budget_by.get(a["id"], ZERO), actual_by.get(a["id"], ZERO)
        if b == 0 and ac == 0:
            continue
        out.append(dict(account_id=a["id"], code=a["code"], name=a["name"], account_class=a["class"], **variance(a["class"], b, ac)))
    return out


def totals(rows: Sequence[dict]) -> dict:
    """Revenue, expenses and profit for budget and actual, plus profit variance (actual profit - budget profit: positive = favourable)."""
    def tot(cls, key):
        return sum((r[key] for r in rows if (r["account_class"] == "revenue") == (cls == "revenue")), ZERO)
    rb, ra, eb, ea = tot("revenue", "budget"), tot("revenue", "actual"), tot("expense", "budget"), tot("expense", "actual")
    pb, pa = rb - eb, ra - ea
    return dict(revenue=dict(budget=rb, actual=ra, variance=ra - rb, variance_pct=pct(ra - rb, abs(rb)) if rb else None),
                expenses=dict(budget=eb, actual=ea, variance=eb - ea, variance_pct=pct(eb - ea, abs(eb)) if eb else None),
                profit=dict(budget=pb, actual=pa, variance=pa - pb, variance_pct=pct(pa - pb, abs(pb)) if pb else None))


def fy_months(fy_start: dt.date) -> List[str]:
    out, y, m = [], fy_start.year, fy_start.month
    for _ in range(12):
        out.append(f"{y:04d}-{m:02d}")
        m += 1
        if m == 13:
            y, m = y + 1, 1
    return out


def year_end(account_class: str, months: Sequence[str], budget_m: Dict[str, Decimal], actual_m: Dict[str, Decimal], last_closed: Optional[str]) -> dict:
    """Full-year view for one account. `last_closed` = the last month whose actuals are final ('' / None = nothing closed yet).
    annual_budget; actual_ytd (closed months); remaining_budget = annual_budget - actual_ytd (negative = overspent);
    projection_budget_basis = actual_ytd + budget of the months still to come; projection_run_rate = actual_ytd / closed months x 12 (None when no month is closed)."""
    closed = [m for m in months if last_closed and m <= last_closed]
    future = [m for m in months if m not in closed]
    annual = sum((budget_m.get(m, ZERO) for m in months), ZERO)
    ytd = sum((actual_m.get(m, ZERO) for m in closed), ZERO)
    proj_b = ytd + sum((budget_m.get(m, ZERO) for m in future), ZERO)
    run = (ytd / len(closed) * 12) if closed else None
    return dict(annual_budget=q2(annual), actual_ytd=q2(ytd), budget_ytd=q2(sum((budget_m.get(m, ZERO) for m in closed), ZERO)), remaining_budget=q2(annual - ytd),
                projection_budget_basis=q2(proj_b), projection_run_rate=q2(run) if run is not None else None, closed_months=len(closed),
                projected_variance=variance(account_class, annual, proj_b)["variance"])


def quarter_of(month: str, fy_months_: Sequence[str]) -> int:
    return fy_months_.index(month) // 3 + 1


def spread_interval(amount, interval: str):
    """Entry convenience: a quarterly amount is spread over 3 months, an annual amount over 12, cent-exact. Returns the monthly amounts."""
    n = {"monthly": 1, "quarterly": 3, "annual": 12}.get(interval)
    if n is None:
        raise ValueError("interval must be monthly, quarterly or annual")
    return spread(amount, n)
