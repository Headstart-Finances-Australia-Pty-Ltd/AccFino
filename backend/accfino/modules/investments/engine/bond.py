"""Fixed-interest maths for bonds and term deposits. Conventions are explicit and selectable because they vary by issuer: coupon frequency (1, 2, 4, 12 a year) and day count
('act/act' = actual days in the coupon period, 'act/365'). Confirm them against the issue's terms. Yields are annualised, compounded at the coupon frequency (street convention)."""
from datetime import date
from typing import List, Optional, Tuple

from accfino.modules.investments.engine.money import D, add_months, q2


def _step(freq: int) -> int:
    if freq not in (1, 2, 4, 12):
        raise ValueError("coupon frequency must be 1, 2, 4 or 12 payments a year")
    return 12 // freq


def neighbours(settle: date, maturity: date, freq: int) -> Tuple[date, date]:
    """(previous coupon date, next coupon date) around settlement, stepping back from maturity."""
    if settle >= maturity:
        raise ValueError("settlement must be before maturity")
    m = _step(freq)
    n, k = maturity, 0
    while add_months(maturity, -m * (k + 1)) > settle:
        k += 1
    nxt, prev = add_months(maturity, -m * k), add_months(maturity, -m * (k + 1))
    return prev, nxt


def accrued_interest(face, rate, freq: int, settle: date, maturity: date, day_count: str = "act/act") -> float:
    prev, nxt = neighbours(settle, maturity, freq)
    face, rate = float(D(face)), float(D(rate))
    if day_count == "act/365":
        return face * rate * (settle - prev).days / 365.0
    return face * rate / freq * (settle - prev).days / (nxt - prev).days


def cashflows(face, rate, freq: int, settle: date, maturity: date) -> List[Tuple[date, float]]:
    face, rate, m = float(D(face)), float(D(rate)), _step(freq)
    _, nxt = neighbours(settle, maturity, freq)
    out, k = [], 0
    while True:
        d = add_months(nxt, m * k)
        if d > maturity:
            break
        out.append((d, face * rate / freq + (face if d == maturity else 0.0)))
        if d == maturity:
            break
        k += 1
    return out


def dirty_price(yld: float, face, rate, freq: int, settle: date, maturity: date) -> float:
    prev, nxt = neighbours(settle, maturity, freq)
    w = (nxt - settle).days / (nxt - prev).days
    return sum(cf / (1 + yld / freq) ** (w + i) for i, (_, cf) in enumerate(cashflows(face, rate, freq, settle, maturity)))


def clean_price(yld: float, face, rate, freq: int, settle: date, maturity: date, day_count: str = "act/act") -> float:
    return dirty_price(yld, face, rate, freq, settle, maturity) - accrued_interest(face, rate, freq, settle, maturity, day_count)


def ytm(clean: float, face, rate, freq: int, settle: date, maturity: date, day_count: str = "act/act") -> Optional[float]:
    """Yield to maturity from a CLEAN price (same units as face). Bisection."""
    lo, hi = -0.5, 3.0
    f = lambda y: clean_price(y, face, rate, freq, settle, maturity, day_count) - clean
    if f(lo) * f(hi) > 0:
        return None
    for _ in range(200):
        mid = (lo + hi) / 2
        if f(lo) * f(mid) <= 0:
            hi = mid
        else:
            lo = mid
        if hi - lo < 1e-12:
            break
    return (lo + hi) / 2


def duration(yld: float, face, rate, freq: int, settle: date, maturity: date) -> Tuple[float, float]:
    """(Macaulay, modified) duration in years."""
    prev, nxt = neighbours(settle, maturity, freq)
    w = (nxt - settle).days / (nxt - prev).days
    cfs = cashflows(face, rate, freq, settle, maturity)
    pv = [cf / (1 + yld / freq) ** (w + i) for i, (_, cf) in enumerate(cfs)]
    tot = sum(pv)
    mac = sum(((w + i) / freq) * p for i, p in enumerate(pv)) / tot
    return mac, mac / (1 + yld / freq)


def term_deposit_interest(principal, rate, start: date, end: date, as_at: date) -> dict:
    """Simple interest, actual/365, paid at maturity: accrued to `as_at` and total at maturity."""
    p, r = float(D(principal)), float(D(rate))
    days_total, days_acc = max((end - start).days, 0), max(min((as_at - start).days, (end - start).days), 0)
    return dict(accrued=q2(p * r * days_acc / 365.0), at_maturity=q2(p * r * days_total / 365.0), days_to_maturity=max((end - as_at).days, 0))
