"""Billing arithmetic (pure, Decimal). Time -> amount -> tax -> totals, with explicit half-up rounding to cents at the line level (matches the books' line rounding)."""
from decimal import Decimal, ROUND_HALF_UP
from typing import List, Optional, Sequence

CENT = Decimal("0.01")
ZERO = Decimal("0")


def D(v) -> Decimal:
    return v if isinstance(v, Decimal) else Decimal(str(v))


def q2(v) -> Decimal:
    return D(v).quantize(CENT, rounding=ROUND_HALF_UP)


def hours(minutes: int) -> Decimal:
    return (Decimal(minutes) / Decimal(60))


def time_amount(minutes: int, rate) -> Decimal:
    """minutes x hourly rate / 60, rounded to the cent. 210 min at 180 = 630.00."""
    if minutes <= 0:
        raise ValueError("minutes must be positive")
    return q2(hours(minutes) * D(rate))


def line_totals(amount_ex_tax, tax_rate) -> dict:
    a = q2(amount_ex_tax)
    t = q2(a * D(tax_rate))
    return dict(net=a, tax=t, gross=a + t)


def invoice_totals(lines: Sequence[dict]) -> dict:
    """lines: [{amount (ex tax, may be negative for discounts), tax_rate}] -> {net, tax, total}. Tax is computed per line then summed."""
    net = tax = ZERO
    for l in lines:
        t = line_totals(l["amount"], l.get("tax_rate", 0))
        net += t["net"]; tax += t["tax"]
    return dict(net=net, tax=tax, total=net + tax)


def pick_rate(rates: Sequence[dict], *, user_id, client_id, service_type, on_date) -> Optional[dict]:
    """Most specific effective rate wins: client+user > client > user+service > user > service > default. Ties: latest effective_from."""
    best, best_key = None, None
    for r in rates:
        if r["effective_from"] > on_date or (r.get("effective_to") and r["effective_to"] < on_date):
            continue
        spec = 0
        for field, want, w in (("client_id", client_id, 8), ("user_id", user_id, 4), ("service_type", service_type, 2)):
            if r.get(field) is not None:
                if r[field] != want:
                    spec = None
                    break
                spec += w
        if spec is None:
            continue
        key = (spec, r["effective_from"])
        if best_key is None or key > best_key:
            best, best_key = r, key
    return best


def realisation(billed, worked_value) -> Optional[Decimal]:
    w = D(worked_value)
    return None if w == 0 else (D(billed) / w * 100).quantize(Decimal("0.1"), rounding=ROUND_HALF_UP)
