"""Decimal helpers for every Planning engine. All money maths is Decimal with explicit half-up rounding; floats are never used for money."""
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation

ZERO = Decimal("0")
CENT = Decimal("0.01")
HUNDRED = Decimal("100")


def D(v) -> Decimal:
    """Any number-like value -> Decimal ('' / None -> 0). Raises ValueError for text that is not a number."""
    if isinstance(v, Decimal):
        return v
    if v is None or v == "":
        return ZERO
    if isinstance(v, bool):
        raise ValueError(f"not a number: {v!r}")
    try:
        d = Decimal(str(v).replace(",", "").replace("$", "").strip())
    except InvalidOperation:
        raise ValueError(f"not a number: {v!r}")
    if not d.is_finite():
        raise ValueError(f"not a finite number: {v!r}")
    return d


def q2(v) -> Decimal:
    """Round to cents, half up."""
    return D(v).quantize(CENT, rounding=ROUND_HALF_UP)


def s(v) -> str:
    """Decimal -> '1234.50' (JSON-safe string with exactly 2 decimals)."""
    return str(q2(v))


def pct(numerator, denominator, places: int = 1):
    """numerator / denominator * 100 rounded half-up to `places`, or None when the denominator is zero (never a fake 0%)."""
    n, d = D(numerator), D(denominator)
    if d == 0:
        return None
    return (n / d * HUNDRED).quantize(Decimal(1).scaleb(-places), rounding=ROUND_HALF_UP)


def spread(total, parts: int):
    """Split `total` into `parts` cent-exact amounts that add back to total (remainder cents go to the first parts)."""
    t = q2(total)
    if parts < 1:
        raise ValueError("parts must be at least 1")
    cents = int((t * 100).to_integral_value())
    base, rem = divmod(abs(cents), parts)
    sign = -1 if cents < 0 else 1
    return [Decimal(sign * (base + (1 if i < rem else 0))) / 100 for i in range(parts)]
