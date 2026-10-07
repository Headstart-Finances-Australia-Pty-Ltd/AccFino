"""Superannuation guarantee under Payday Super: SG = rate x qualifying earnings, limited by the ANNUAL maximum contribution base applied to
year-to-date qualifying earnings. Salary sacrifice is deducted from pay but remains in the qualifying-earnings base (it is a deduction from
earnings that were counted before sacrifice)."""
from datetime import date, timedelta
from decimal import Decimal
from typing import Iterable

from accfino.modules.payroll.engine.money import ZERO, D, r2
from accfino.modules.payroll.engine.rules import RuleSet


def qualifying_earnings_in_cap(rules: RuleSet, qe_this_pay, ytd_qe_before) -> Decimal:
    """The part of this pay's qualifying earnings that still attracts SG (annual cap on YTD qualifying earnings)."""
    qe, ytd = max(ZERO, D(qe_this_pay)), max(ZERO, D(ytd_qe_before))
    room = max(ZERO, rules.mcb_annual - ytd)
    return min(qe, room)


def super_guarantee(rules: RuleSet, qe_this_pay, ytd_qe_before) -> Decimal:
    return r2(qualifying_earnings_in_cap(rules, qe_this_pay, ytd_qe_before) * rules.sg_rate)


def add_business_days(start: date, n: int, holidays: Iterable[date] = ()) -> date:
    hol = set(holidays)
    d, left = start, int(n)
    while left > 0:
        d += timedelta(days=1)
        if d.weekday() < 5 and d not in hol:
            left -= 1
    return d


def super_due_date(rules: RuleSet, pay_date: date, holidays: Iterable[date] = ()) -> date:
    """Date by which the fund must RECEIVE the contribution (Payday Super: 7 business days after payday)."""
    return add_business_days(pay_date, rules.super_due_business_days, holidays)
