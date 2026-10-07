"""Decimal helpers shared by every taxation engine. All tax maths is Decimal; floats are never used."""
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation

ZERO = Decimal("0")
CENT = Decimal("0.01")


def D(v) -> Decimal:
    """Any number-like value -> Decimal ('' / None -> 0). Raises ValueError for text that is not a number."""
    if isinstance(v, Decimal):
        return v
    if v is None or v == "":
        return ZERO
    try:
        return Decimal(str(v).replace(",", "").replace("$", "").strip())
    except InvalidOperation:
        raise ValueError(f"not a number: {v!r}")


def q2(v) -> Decimal:
    """Round to cents, half up (the convention used on ATO forms)."""
    return D(v).quantize(CENT, rounding=ROUND_HALF_UP)


def whole(v) -> Decimal:
    """Round to whole dollars, half up (BAS amounts are lodged in whole dollars)."""
    return D(v).quantize(Decimal("1"), rounding=ROUND_HALF_UP)


def s(v) -> str:
    return str(q2(v))
