"""Decimal helpers. All payroll arithmetic is Decimal; rounding is always ROUND_HALF_UP (the ATO rounds .50 up)."""
from decimal import ROUND_FLOOR, ROUND_HALF_UP, Decimal, InvalidOperation

ZERO = Decimal("0")
CENT = Decimal("0.01")
DOLLAR = Decimal("1")


def D(v) -> Decimal:
    if v is None or v == "":
        return ZERO
    if isinstance(v, Decimal):
        return v
    try:
        d = Decimal(str(v))
    except (InvalidOperation, ValueError):
        raise ValueError(f"Invalid number: {v!r}")
    if not d.is_finite():
        raise ValueError(f"Invalid number: {v!r}")
    return d


def r2(v) -> Decimal:
    return D(v).quantize(CENT, rounding=ROUND_HALF_UP)


def r_dollar(v) -> Decimal:
    """Round to the nearest whole dollar, .50 rounds UP (ATO rule). Applied directly, never via cents first."""
    return D(v).quantize(DOLLAR, rounding=ROUND_HALF_UP)


def floor_dollar(v) -> Decimal:
    return D(v).quantize(DOLLAR, rounding=ROUND_FLOOR)


def r4(v) -> Decimal:
    return D(v).quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP)
