"""Return maths. XIRR is the money-weighted annual return: the rate r that makes the dated cash flows sum to zero (investor's view: purchases negative; sales, income and the closing value positive)."""
from datetime import date
from typing import List, Optional, Tuple

from accfino.modules.investments.engine.money import D


def xirr(flows: List[Tuple[date, object]], guess: float = 0.1) -> Optional[float]:
    fl = sorted(((d, float(D(a))) for d, a in flows if D(a) != 0), key=lambda x: x[0])
    if len(fl) < 2 or not any(a > 0 for _, a in fl) or not any(a < 0 for _, a in fl):
        return None
    d0 = fl[0][0]

    def f(r):
        return sum(a / (1 + r) ** ((d - d0).days / 365.0) for d, a in fl)

    if (fl[-1][0] - d0).days < 1:
        return None
    lo, hi = -0.9999, 100.0
    flo, fhi = f(lo), f(hi)
    if flo * fhi > 0:
        return None
    for _ in range(300):                                          # bisection: slow but cannot fail to converge
        mid = (lo + hi) / 2
        fm = f(mid)
        if abs(fm) < 1e-9 or (hi - lo) < 1e-12:
            return mid
        if flo * fm < 0:
            hi, fhi = mid, fm
        else:
            lo, flo = mid, fm
    return (lo + hi) / 2


def simple_return(invested, value_now, income=0, realised=0) -> Optional[float]:
    """(closing value + income + proceeds taken out - money put in) / money put in."""
    inv = float(D(invested))
    if inv <= 0:
        return None
    return (float(D(value_now)) + float(D(income)) + float(D(realised)) - inv) / inv
