"""Leave accrual and leave-pay helpers (pure)."""
from dataclasses import dataclass, field
from decimal import Decimal
from typing import List, Optional

from accfino.modules.payroll.engine.money import ZERO, D, r4
from accfino.modules.payroll.engine.rules import RuleSet


@dataclass
class AccrualDef:
    leave_type_id: int
    code: str
    method: str                       # per_ordinary_hour | fixed_per_year | none
    annual_hours: Decimal             # hours per year for a STANDARD week (e.g. 152 annual leave for 38h)
    applies_to: List[str] = field(default_factory=list)   # employment types; empty = all
    accrue_on_paid_leave: bool = True
    max_balance: Optional[Decimal] = None


def accrual_hours(rules: RuleSet, d: AccrualDef, *, employment_type: str, ordinary_hours: Decimal, paid_leave_hours: Decimal,
                  hours_per_week: Decimal, periods_per_year: int, proration: Decimal, balance: Decimal = ZERO) -> Decimal:
    if d.method == "none" or (d.applies_to and employment_type not in d.applies_to):
        return ZERO
    std = rules.leave_defaults["standard_week_hours"]
    if d.method == "per_ordinary_hour":
        basis = D(ordinary_hours) + (D(paid_leave_hours) if d.accrue_on_paid_leave else ZERO)
        h = basis * d.annual_hours / (52 * std)
    elif d.method == "fixed_per_year":
        h = d.annual_hours * (D(hours_per_week) / std) / periods_per_year * D(proration)
    else:
        raise ValueError(f"Unknown accrual method '{d.method}' for leave type {d.code}")
    h = r4(max(ZERO, h))
    if d.max_balance is not None:                                  # never accrue beyond the cap
        h = min(h, max(ZERO, D(d.max_balance) - D(balance)))
    return h
