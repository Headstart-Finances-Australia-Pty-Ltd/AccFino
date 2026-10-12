"""Treasury and liquidity: a 30 / 60 / 90 day projection that keeps the three kinds of money separate.

ACTUAL    the cash held today (ledger bank balances)
COMMITTED flows that are contractually due: loan and facility repayments, invoices and bills with a due date
FORECAST  flows someone expects but nobody is bound to: entered by the user

The projection never blends them: it reports the balance on committed flows alone, and the balance if the forecast also happens."""
from collections import defaultdict
from datetime import date, timedelta
from typing import Dict, List, Optional

KINDS = ("committed", "forecast")
HORIZONS = (30, 60, 90)


def project(opening_cash: float, items: List[Dict], start: date, horizon_days: int = 90, min_buffer: float = 0.0, facilities: Optional[List[Dict]] = None) -> Dict:
    """items: [{date, amount (inflow +, outflow -), kind: committed|forecast, label, source}]. Items dated before `start` or after the horizon are ignored."""
    end = start + timedelta(days=horizon_days)
    live = [dict(i, date=i["date"]) for i in items if i.get("kind") in KINDS and start <= i["date"] <= end and abs(float(i.get("amount") or 0)) > 0]
    live.sort(key=lambda i: (i["date"], i["kind"]))
    by_day = defaultdict(lambda: dict(committed=0.0, forecast=0.0))
    for i in live:
        by_day[i["date"]][i["kind"]] += float(i["amount"])
    days, c_bal, f_bal = [], float(opening_cash), float(opening_cash)
    for n in range(horizon_days + 1):
        d = start + timedelta(days=n)
        c_bal += by_day[d]["committed"] if d in by_day else 0.0
        f_bal += (by_day[d]["committed"] + by_day[d]["forecast"]) if d in by_day else 0.0
        days.append(dict(date=d, committed_balance=round(c_bal, 2), forecast_balance=round(f_bal, 2)))
    head = sum(max(0.0, float(f.get("limit") or 0) - float(f.get("drawn") or 0)) for f in (facilities or []) if (f.get("status") or "active") == "active")
    out = dict(start=start, opening_cash=round(float(opening_cash), 2), min_buffer=float(min_buffer), facility_headroom=round(head, 2), windows=[])
    for h in HORIZONS:
        if h > horizon_days:
            continue
        w = [d for d in days if (d["date"] - start).days <= h]
        win = [i for i in live if (i["date"] - start).days <= h]
        agg = {k: dict(inflow=round(sum(i["amount"] for i in win if i["kind"] == k and i["amount"] > 0), 2), outflow=round(-sum(i["amount"] for i in win if i["kind"] == k and i["amount"] < 0), 2)) for k in KINDS}
        res = dict(days=h, actual=dict(cash=round(float(opening_cash), 2)), committed=agg["committed"], forecast=agg["forecast"],
                   closing_committed=w[-1]["committed_balance"], closing_forecast=w[-1]["forecast_balance"])
        for tag, key in (("committed", "committed_balance"), ("forecast", "forecast_balance")):
            lo = min(w, key=lambda d: d[key])
            below = [d for d in w if d[key] < min_buffer]
            need = max(0.0, min_buffer - lo[key])
            res[f"lowest_{tag}"] = dict(balance=lo[key], date=lo["date"])
            res[f"shortfall_{tag}"] = dict(days_below_buffer=len(below), first_date=below[0]["date"] if below else None, funding_required=round(need, 2), covered_by_facilities=round(min(need, head), 2), uncovered=round(max(0.0, need - head), 2))
        res["status"] = "short" if res["shortfall_committed"]["funding_required"] > 0 else ("watch" if res["shortfall_forecast"]["funding_required"] > 0 else "healthy")
        out["windows"].append(res)
    out["days"] = days
    out["flows"] = live
    weeks = defaultdict(lambda: dict(committed=0.0, forecast=0.0))
    for i in live:
        k = (i["date"] - start).days // 7
        weeks[k][i["kind"]] += float(i["amount"])
    out["weekly"] = [dict(week=k + 1, from_date=start + timedelta(days=7 * k), committed_net=round(v["committed"], 2), forecast_net=round(v["forecast"], 2)) for k, v in sorted(weeks.items())]
    return out
