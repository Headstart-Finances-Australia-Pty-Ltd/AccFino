"""Split a net pay across an employee's bank accounts: fixed amounts and percentages first (by priority), the remainder account takes the rest."""
from decimal import Decimal

from accfino.modules.payroll.services.errors import PayrollError

CENT = Decimal("0.01")


def allocate_net(banks, net: Decimal) -> list:
    """[(bank, amount)] summing EXACTLY to net. Raises PayrollError if a fixed/percent allocation cannot be honoured."""
    net = Decimal(net)
    if net <= 0:
        return []
    if not banks:
        raise PayrollError("No bank account to pay into")
    left, out, rem = net, [], None
    for b in sorted(banks, key=lambda b: b.priority):
        if b.allocation_type == "remainder":
            rem = b
            continue
        amt = b.allocation_value if b.allocation_type == "fixed" else (net * b.allocation_value / 100).quantize(CENT)
        amt = min(amt, left)
        if amt > 0:
            out.append([b, amt])
            left -= amt
    if rem is None:
        raise PayrollError("No account receives the remainder of the net pay")
    if left > 0:
        out.append([rem, left])
    return [(b, a) for b, a in out]
