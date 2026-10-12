"""Deadline arithmetic (pure). Dates only; the caller supplies holidays. A computed date is an INTERNAL ESTIMATE until a person verifies it against a source."""
import datetime as dt
from typing import Iterable, Optional, Set

import calendar


def is_business_day(d: dt.date, holidays: Set[dt.date] = frozenset()) -> bool:
    return d.weekday() < 5 and d not in holidays


def roll_forward(d: dt.date, holidays: Set[dt.date] = frozenset()) -> dt.date:
    while not is_business_day(d, holidays):
        d += dt.timedelta(days=1)
    return d


def roll_back(d: dt.date, holidays: Set[dt.date] = frozenset()) -> dt.date:
    while not is_business_day(d, holidays):
        d -= dt.timedelta(days=1)
    return d


def add_months(d: dt.date, n: int) -> dt.date:
    y, m = divmod(d.month - 1 + n, 12)
    y += d.year
    return dt.date(y, m + 1, min(d.day, calendar.monthrange(y, m + 1)[1]))


def add_business_days(d: dt.date, n: int, holidays: Set[dt.date] = frozenset()) -> dt.date:
    step = 1 if n >= 0 else -1
    left = abs(n)
    while left:
        d += dt.timedelta(days=step)
        if is_business_day(d, holidays):
            left -= 1
    return d


def business_days_between(a: dt.date, b: dt.date, holidays: Set[dt.date] = frozenset()) -> int:
    """Business days in (a, b] (positive when b after a)."""
    if a == b:
        return 0
    s, e, sign = (a, b, 1) if a < b else (b, a, -1)
    n, d = 0, s
    while d < e:
        d += dt.timedelta(days=1)
        if is_business_day(d, holidays):
            n += 1
    return n * sign


def from_rule(rule: dict, period_end: dt.date, holidays: Set[dt.date] = frozenset()) -> dt.date:
    """rule: {basis: 'period_end'|'fixed', months: int, days: int, day_of_month: int|None, month: int|None, adjust: 'none'|'next_business_day'|'prev_business_day'}.
    period_end + months (+ days), or the next occurrence of a fixed day/month on or after the period end. Weekend/holiday adjustment is explicit."""
    basis = rule.get("basis", "period_end")
    if basis == "fixed":
        m, dom = int(rule["month"]), int(rule["day_of_month"])
        y = period_end.year
        cand = dt.date(y, m, min(dom, calendar.monthrange(y, m)[1]))
        if cand <= period_end:
            cand = dt.date(y + 1, m, min(dom, calendar.monthrange(y + 1, m)[1]))
    else:
        cand = add_months(period_end, int(rule.get("months", 0))) + dt.timedelta(days=int(rule.get("days", 0)))
        if rule.get("day_of_month"):
            cand = dt.date(cand.year, cand.month, min(int(rule["day_of_month"]), calendar.monthrange(cand.year, cand.month)[1]))
    adj = rule.get("adjust", "none")
    return roll_forward(cand, holidays) if adj == "next_business_day" else roll_back(cand, holidays) if adj == "prev_business_day" else cand


def classify(due: dt.date, today: dt.date, completed: bool, soon_days: int = 14) -> str:
    if completed:
        return "completed"
    if due < today:
        return "overdue"
    return "due_soon" if (due - today).days <= soon_days else "upcoming"


def next_period_end(d: dt.date, freq: str) -> dt.date:
    n = dict(monthly=1, quarterly=3, annual=12).get(freq)
    if not n:
        raise ValueError("frequency must be monthly, quarterly or annual")
    e = add_months(d.replace(day=1), n + 1) - dt.timedelta(days=1) if d.day == calendar.monthrange(d.year, d.month)[1] else add_months(d, n)
    return e
