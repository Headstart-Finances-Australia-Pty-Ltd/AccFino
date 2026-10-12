from decimal import ROUND_HALF_UP, Decimal

ZERO = Decimal(0)
C = Decimal("0.01")
U = Decimal("0.00000001")


def D(v) -> Decimal:
    if v is None or v == "":
        return ZERO
    return v if isinstance(v, Decimal) else Decimal(str(v))


def q2(v) -> Decimal:
    return D(v).quantize(C, ROUND_HALF_UP)


def q8(v) -> Decimal:
    return D(v).quantize(U, ROUND_HALF_UP)


def add_months(d, n: int):
    """The same day n months later (month-end safe): used for the 12-month CGT discount test."""
    import calendar
    y, m = divmod(d.month - 1 + n, 12)
    y, m = d.year + y, m + 1
    return d.replace(year=y, month=m, day=min(d.day, calendar.monthrange(y, m)[1]))
