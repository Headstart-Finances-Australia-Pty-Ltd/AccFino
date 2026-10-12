"""Cash-flow forecasting engines (pure, deterministic, Decimal): bucket projection, minimum balance/shortfall, a statistical baseline with
time-based backtesting (no leakage), forecast-vs-actual accuracy, and a confidence label. No database access here."""
import datetime as dt
from decimal import Decimal
from typing import Dict, List, Optional, Sequence

from .money import D, q2, s, ZERO

# ------------------------------------------------------------------------------------------------------------------------ buckets
def week_buckets(start: dt.date, weeks: int) -> List[dict]:
    """`weeks` consecutive 7-day buckets, the first starting the day AFTER `start` (the as-at date)."""
    if weeks < 1 or weeks > 104:
        raise ValueError("weeks must be between 1 and 104")
    out = []
    for i in range(weeks):
        f = start + dt.timedelta(days=1 + 7 * i)
        out.append(dict(index=i + 1, label=f"Week {i + 1}", date_from=f, date_to=f + dt.timedelta(days=6)))
    return out


def _month_end(d: dt.date) -> dt.date:
    nxt = dt.date(d.year + (d.month == 12), d.month % 12 + 1, 1)
    return nxt - dt.timedelta(days=1)


def month_buckets(start: dt.date, months: int) -> List[dict]:
    """`months` calendar-month buckets; the first runs from the day after `start` to the end of that month (a partial month when start is mid-month)."""
    if months < 1 or months > 36:
        raise ValueError("months must be between 1 and 36")
    out, f = [], start + dt.timedelta(days=1)
    for i in range(months):
        t = _month_end(f)
        out.append(dict(index=i + 1, label=f.strftime("%b %Y"), date_from=f, date_to=t))
        f = t + dt.timedelta(days=1)
    return out


# ------------------------------------------------------------------------------------------------------------------------ projection
def effective(flow: dict) -> Decimal:
    """Signed cash effect of a flow: amount x weight (probability the cash arrives/leaves), rounded to cents."""
    return q2(D(flow["amount"]) * D(flow.get("weight", 1)))


def project(opening, flows: Sequence[dict], buckets: List[dict], threshold=ZERO) -> dict:
    """Roll an opening cash balance through the buckets.
    flow = {date, amount (signed: inflow +, outflow -), weight (0..1, default 1), source, label, kind, ref?}. A flow with a `ref` already seen is ignored (duplicates are safe).
    Flows outside the buckets are counted in `outside_horizon`, never silently dropped into a bucket."""
    opening, threshold = q2(opening), q2(threshold)
    seen, rows, outside, dups = set(), [], 0, 0
    clean = []
    for f in flows:
        ref = f.get("ref")
        if ref is not None:
            if ref in seen:
                dups += 1
                continue
            seen.add(ref)
        clean.append(f)
    bal = opening
    for b in buckets:
        inn = out = ZERO
        by_source: Dict[str, Decimal] = {}
        items = []
        for f in clean:
            if b["date_from"] <= f["date"] <= b["date_to"]:
                e = effective(f)
                if e > 0:
                    inn += e
                else:
                    out += -e
                by_source[f.get("source", "other")] = by_source.get(f.get("source", "other"), ZERO) + e
                items.append(f)
        net = inn - out
        rows.append(dict(index=b["index"], label=b["label"], date_from=b["date_from"], date_to=b["date_to"], opening=bal, receipts=inn, payments=out, net=net,
                         closing=bal + net, by_source={k: q2(v) for k, v in sorted(by_source.items())}, count=len(items)))
        bal = bal + net
    lo, hi = buckets[0]["date_from"], buckets[-1]["date_to"]
    outside = sum(1 for f in clean if not (lo <= f["date"] <= hi))
    low = min(rows, key=lambda r: (r["closing"], r["index"]))
    breaches = [dict(index=r["index"], label=r["label"], closing=r["closing"], shortfall=q2(threshold - r["closing"])) for r in rows if r["closing"] < threshold]
    return dict(opening=opening, closing=rows[-1]["closing"], rows=rows, threshold=threshold,
                minimum=dict(balance=low["closing"], index=low["index"], label=low["label"], date_to=low["date_to"]),
                shortfall=dict(max_shortfall=q2(threshold - low["closing"]) if low["closing"] < threshold else ZERO, first_breach=breaches[0] if breaches else None,
                               breaches=breaches, goes_negative=any(r["closing"] < 0 for r in rows)),
                total_receipts=sum((r["receipts"] for r in rows), ZERO), total_payments=sum((r["payments"] for r in rows), ZERO),
                outside_horizon=outside, duplicates_ignored=dups)


def drivers(flows: Sequence[dict], buckets: List[dict]) -> List[dict]:
    """Which sources move the forecast: [{source, inflow, outflow, net, count}], biggest absolute net first (ties by name)."""
    lo, hi = buckets[0]["date_from"], buckets[-1]["date_to"]
    agg: Dict[str, dict] = {}
    for f in flows:
        if not (lo <= f["date"] <= hi):
            continue
        e = effective(f)
        a = agg.setdefault(f.get("source", "other"), dict(source=f.get("source", "other"), inflow=ZERO, outflow=ZERO, net=ZERO, count=0))
        a["inflow" if e > 0 else "outflow"] += abs(e)
        a["net"] += e
        a["count"] += 1
    return sorted(agg.values(), key=lambda a: (-abs(a["net"]), a["source"]))


# ------------------------------------------------------------------------------------------------------------------------ statistical baseline + backtest
def week_index(d: dt.date, origin: dt.date) -> int:
    return (d - origin).days // 7


def weekly_series(items: Sequence[dict], origin: dt.date, end: dt.date) -> List[Decimal]:
    """Net amount per 7-day week from `origin` through `end` (items: {date, amount}); empty weeks are 0. Only COMPLETE weeks are returned."""
    n = ((end - origin).days + 1) // 7
    out = [ZERO] * max(n, 0)
    for it in items:
        k = week_index(it["date"], origin)
        if 0 <= k < n:
            out[k] += D(it["amount"])
    return [q2(x) for x in out]


def _mean(xs: Sequence[Decimal]) -> Decimal:
    return sum(xs, ZERO) / len(xs) if xs else ZERO


def _trend(xs: Sequence[Decimal], h: int, window: int = 12) -> Decimal:
    w = list(xs[-window:])
    n = len(w)
    if n < 3:
        return _mean(w)
    xm = Decimal(n - 1) / 2
    ym = _mean(w)
    num = sum((Decimal(i) - xm) * (y - ym) for i, y in enumerate(w))
    den = sum((Decimal(i) - xm) ** 2 for i in range(n))
    slope = num / den if den else ZERO
    return ym + slope * (Decimal(n - 1 + h) - xm)


MODELS = {
    "mean4": lambda xs, h: _mean(xs[-4:]),
    "mean8": lambda xs, h: _mean(xs[-8:]),
    "trend12": _trend,
    "seasonal4": lambda xs, h: xs[-4 + ((h - 1) % 4)] if len(xs) >= 4 else _mean(xs),
}
MODEL_LABELS = {"mean4": "Average of the last 4 weeks", "mean8": "Average of the last 8 weeks", "trend12": "Linear trend over the last 12 weeks", "seasonal4": "Repeat the last 4-week pattern"}


def predict(model: str, history: Sequence[Decimal], steps: int) -> List[Decimal]:
    """Forecast `steps` weeks ahead using ONLY `history` (the function cannot see anything later)."""
    f = MODELS[model]
    hist = list(history)
    return [q2(f(hist, h)) for h in range(1, steps + 1)]


def backtest(series: Sequence[Decimal], horizon: int = 4, min_train: int = 8) -> dict:
    """Rolling-origin (time-ordered) backtest. For each origin t the model is fitted on series[:t] and scored on series[t:t+horizon]; training data never includes the
    scored weeks (no leakage). Ranking is by mean absolute error, ties broken by model name, so the choice is reproducible."""
    series = list(series)
    res = []
    for name in sorted(MODELS):
        errs = []
        for t in range(min_train, len(series) - horizon + 1):
            pred = predict(name, series[:t], horizon)
            errs += [abs(p - a) for p, a in zip(pred, series[t:t + horizon])]
        res.append(dict(model=name, label=MODEL_LABELS[name], mae=q2(_mean(errs)) if errs else None, n=len(errs)))
    scored = [r for r in res if r["mae"] is not None]
    best = min(scored, key=lambda r: (r["mae"], r["model"]))["model"] if scored else None
    return dict(models=sorted(res, key=lambda r: (r["mae"] is None, r["mae"] or ZERO, r["model"])), best=best, horizon=horizon, min_train=min_train,
                origins=max(len(series) - horizon + 1 - min_train, 0), method="rolling-origin, time-ordered, training data strictly earlier than the scored weeks")


# ------------------------------------------------------------------------------------------------------------------------ accuracy + confidence
def accuracy(forecast_rows: Sequence[dict], actual_by_index: Dict[int, dict]) -> dict:
    """Compare a stored forecast with what happened. forecast_rows: [{index, label, net, closing}]; actual_by_index: {index: {net, closing}} (only buckets that have ended).
    error = actual - forecast (positive = better than forecast). Returns per-bucket errors, MAE and bias; buckets without actuals are skipped."""
    rows, errs = [], []
    for r in forecast_rows:
        a = actual_by_index.get(r["index"])
        if a is None:
            continue
        e_net = q2(D(a["net"]) - D(r["net"]))
        e_close = q2(D(a["closing"]) - D(r["closing"]))
        rows.append(dict(index=r["index"], label=r.get("label"), forecast_net=s(r["net"]), actual_net=s(a["net"]), error_net=s(e_net), forecast_closing=s(r["closing"]),
                         actual_closing=s(a["closing"]), error_closing=s(e_close)))
        errs.append((e_net, e_close))
    if not errs:
        return dict(rows=[], compared=0, mae_net=None, bias_net=None, mae_closing=None, note="No forecast period has ended yet, so there is nothing to compare.")
    n = len(errs)
    return dict(rows=rows, compared=n, mae_net=s(sum((abs(e[0]) for e in errs), ZERO) / n), bias_net=s(sum((e[0] for e in errs), ZERO) / n),
                mae_closing=s(sum((abs(e[1]) for e in errs), ZERO) / n), note="Positive error = actual better than forecast.")


def confidence(history_weeks: int, committed_share: Optional[Decimal], reconciled: bool, has_bank: bool) -> dict:
    """Plain, reproducible confidence label. 'indicative' = not enough data to rely on the numbers."""
    reasons = []
    if not has_bank:
        reasons.append("no bank account in the ledger")
    if history_weeks < 8:
        reasons.append(f"only {history_weeks} weeks of history (need 8+)")
    if not reconciled:
        reasons.append("opening balance does not agree to the bank statements")
    if reasons:
        return dict(level="indicative", reasons=reasons, rule="indicative if no bank account, <8 weeks history or the opening balance is unreconciled")
    cs = D(committed_share) if committed_share is not None else ZERO
    if history_weeks >= 26 and cs >= Decimal("0.5"):
        return dict(level="high", reasons=["26+ weeks of history", f"{int(cs * 100)}% of forecast value is already committed (invoices, bills, loans, tax)"], rule="high if 26+ weeks history and >=50% of value committed")
    return dict(level="medium", reasons=[f"{history_weeks} weeks of history", f"{int(cs * 100)}% committed"], rule="medium otherwise")
