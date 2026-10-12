"""Recurring-payment detection from ledger history (pure). A series is 'recurring' when it appears in enough complete months with a stable monthly total."""
import datetime as dt
import re
import statistics
from collections import defaultdict
from decimal import Decimal
from typing import Dict, List, Sequence

from .money import D, q2, ZERO


def normalise_key(text: str) -> str:
    """Narration -> stable merchant key: lower-case, digits/punctuation removed (invoice numbers and dates vary), first 40 chars."""
    t = re.sub(r"[^a-z ]+", " ", (text or "").lower())
    return re.sub(r"\s+", " ", t).strip()[:40]


def month_key(d: dt.date) -> str:
    return d.strftime("%Y-%m")


def prev_months(as_at: dt.date, n: int) -> List[str]:
    """The `n` complete calendar months before the month of `as_at`, oldest first."""
    y, m = as_at.year, as_at.month
    out = []
    for _ in range(n):
        m -= 1
        if m == 0:
            y, m = y - 1, 12
        out.append(f"{y:04d}-{m:02d}")
    return list(reversed(out))


def detect(items: Sequence[dict], as_at: dt.date, months: int = 6, min_months: int = 3, cv_max: Decimal = Decimal("0.35")) -> List[dict]:
    """items: {date, key, amount (signed: in +, out -), label, source}. Returns recurring series:
    {key, label, source, direction, monthly_amount (median of monthly totals), day (median day-of-month, max 28), months_seen, cv, last_month, latest_amount}.
    Active = seen in each of the last 2 complete months OR (min_months seen and the latest complete month seen)."""
    window = prev_months(as_at, months)
    by: Dict[str, Dict[str, Decimal]] = defaultdict(lambda: defaultdict(lambda: ZERO))
    days: Dict[str, List[int]] = defaultdict(list)
    meta: Dict[str, dict] = {}
    for it in items:
        mk = month_key(it["date"])
        if mk not in window:
            continue
        by[it["key"]][mk] += D(it["amount"])
        days[it["key"]].append(min(it["date"].day, 28))
        meta.setdefault(it["key"], dict(label=it.get("label") or it["key"], source=it.get("source", "other")))
    out = []
    for key, m in sorted(by.items()):
        vals = [m[k] for k in window if k in m]
        if len(vals) < min_months:
            continue
        if not (window[-1] in m or (window[-2] in m and len(vals) >= min_months)):
            continue
        if any((v > 0) != (vals[0] > 0) for v in vals):
            continue                                  # sign flips: not a steady stream
        mags = [abs(v) for v in vals]
        mean = sum(mags, ZERO) / len(mags)
        if mean == 0:
            continue
        sd = Decimal(str(statistics.pstdev([float(x) for x in mags]))) if len(mags) > 1 else ZERO
        cv = (sd / mean).quantize(Decimal("0.001"))
        if cv > cv_max:
            continue
        med = Decimal(str(statistics.median([float(x) for x in mags]))).quantize(Decimal("0.01"))
        latest = m.get(window[-1], m.get(window[-2]))
        out.append(dict(key=key, label=meta[key]["label"], source=meta[key]["source"], direction="in" if vals[0] > 0 else "out", monthly_amount=q2(med if vals[0] > 0 else -med),
                        day=int(statistics.median(days[key])), months_seen=len(vals), cv=cv, last_month=max(m), latest_amount=q2(latest)))
    return out


def project_flows(series: Sequence[dict], start: dt.date, end: dt.date, already_posted: Dict[str, dt.date] = None) -> List[dict]:
    """Future dated flows for recurring series between start (exclusive) and end (inclusive). A month in which the series has ALREADY posted (after the
    first of that month) is skipped so nothing is double counted. already_posted: {key: latest posting date}."""
    already_posted = already_posted or {}
    flows = []
    y, m = start.year, start.month
    while True:
        first = dt.date(y, m, 1)
        if first > end:
            break
        for s_ in series:
            day = min(s_["day"], 28)
            d = dt.date(y, m, day)
            if d <= start or d > end:
                continue
            posted = already_posted.get(s_["key"])
            if posted is not None and (posted.year, posted.month) == (y, m):
                continue
            flows.append(dict(date=d, amount=s_["monthly_amount"], source="recurring", kind="expected", label=f"Recurring: {s_['label']}", ref=f"rec:{s_['key']}:{y}-{m:02d}", weight=Decimal(1)))
        m += 1
        if m == 13:
            y, m = y + 1, 1
    return flows
