"""PAYG withholding per ATO Schedule 1 (formulas y = ax - b), Schedule 8 (study and training support loans) and Schedule 5 Method A (bonuses etc.).
Every function takes the RuleSet; nothing here knows a rate. Functions are pure."""
from decimal import Decimal
from typing import List, Optional

from accfino.modules.payroll.engine.money import ZERO, D, floor_dollar, r_dollar
from accfino.modules.payroll.engine.rules import Row, RuleSet

FREQ_PERIODS = {"weekly": 52, "fortnightly": 26, "monthly": 12, "quarterly": 4}
NINETY_NINE = Decimal("0.99")


def periods_per_year(freq: str) -> int:
    try:
        return FREQ_PERIODS[freq]
    except KeyError:
        raise ValueError(f"Unsupported pay frequency '{freq}' (use weekly, fortnightly or monthly)")


def weekly_equivalent_x(earnings, freq: str) -> Decimal:
    """ATO 'Working out the weekly earnings': weekly equivalent, cents ignored, plus 99 cents."""
    e = D(earnings)
    if e < 0:
        e = ZERO
    if freq == "weekly":
        w = e
    elif freq == "fortnightly":
        w = e / 2
    elif freq == "monthly":
        if (e * 100) % 100 == 33:                      # an amount ending in 33 cents: add one cent
            e += Decimal("0.01")
        w = e * 3 / 13
    elif freq == "quarterly":
        w = e / 13
    else:
        periods_per_year(freq)
        raise AssertionError
    return floor_dollar(w) + NINETY_NINE


def weekly_to_period(weekly_amount: Decimal, freq: str) -> Decimal:
    if freq == "weekly":
        return weekly_amount
    if freq == "fortnightly":
        return weekly_amount * 2
    if freq == "monthly":
        return r_dollar(weekly_amount * 13 / 3)
    return weekly_amount * 13                           # quarterly


def _apply(rows: List[Row], x: Decimal) -> Decimal:
    for upper, a, b in rows:
        if upper is None or x < upper:
            return r_dollar(max(ZERO, a * x - b))      # rounded directly to the dollar, .50 up
    return ZERO


def scale_for(tfn_provided: bool, residency: str, claims_tft: bool, medicare_variation: str) -> str:
    """Which Schedule 1 scale applies to a payee."""
    if not tfn_provided:
        return "4"
    if residency == "foreign_resident":
        return "3"
    if medicare_variation == "full":
        return "5"
    if medicare_variation == "half":
        return "6"
    return "2" if claims_tft else "1"


def scale_withholding(rules: RuleSet, earnings, freq: str, scale: str, offset_claim=ZERO) -> Decimal:
    """Withholding (whole dollars) on one period's earnings, before study loan, per Schedule 1."""
    e = D(earnings)
    if e <= 0:
        return ZERO
    if scale == "4":
        raise ValueError("Scale 4 (no TFN) has no coefficients: use scale4_withholding()")
    if scale not in rules.scales:
        raise ValueError(f"No coefficients for scale {scale} in rule set {rules.id}")
    x = weekly_equivalent_x(e, freq)
    weekly = _apply(rules.scales[scale], x)
    amount = weekly_to_period(weekly, freq)
    if scale in ("2", "5", "6") and D(offset_claim) > 0:
        pct = rules.offset_pct.get(freq)
        if pct is not None:
            amount = max(ZERO, amount - r_dollar(D(offset_claim) * pct))
    return amount


def scale4_withholding(rules: RuleSet, earnings, residency: str) -> Decimal:
    e = D(earnings)
    if e <= 0:
        return ZERO
    key = "foreign_resident" if residency == "foreign_resident" else "resident"
    return floor_dollar(floor_dollar(e) * rules.scale4[key])


def study_loan_component(rules: RuleSet, earnings, freq: str, claims_tft: bool, residency: str = "resident") -> Decimal:
    """Schedule 8 STSL component. Foreign residents use the 'tax-free threshold claimed or foreign resident' table."""
    e = D(earnings)
    if e <= 0:
        return ZERO
    rows = rules.stsl_tft if (claims_tft or residency == "foreign_resident") else rules.stsl_no_tft
    weekly = _apply(rows, weekly_equivalent_x(e, freq))
    return weekly_to_period(weekly, freq)


def total_withholding(rules: RuleSet, earnings, freq: str, *, scale: str, residency: str, claims_tft: bool,
                      study_loan: bool, offset_claim=ZERO) -> tuple:
    """(tax, study_loan_component) for one pay period's regular earnings."""
    if scale == "4":
        return scale4_withholding(rules, earnings, residency), ZERO     # no TFN: STSL component does not apply
    tax = scale_withholding(rules, earnings, freq, scale, offset_claim)
    stsl = study_loan_component(rules, earnings, freq, claims_tft, residency) if study_loan else ZERO
    return tax, stsl


def method_a(rules: RuleSet, regular_earnings, additional, freq: str, *, scale: str, residency: str, claims_tft: bool,
             study_loan: bool, offset_claim=ZERO, periods: Optional[int] = None) -> tuple:
    """ATO Schedule 5 Method A. Returns (tax_on_additional, stsl_on_additional), whole dollars.
    Steps follow the schedule: apportion the additional payment over the pay periods in the year (or the periods it relates to),
    withhold on (regular + apportioned) less withholding on regular, scale back up, then cap at 47% of the additional payment
    (the cap applies to PAYG and study-loan components combined)."""
    add = D(additional)
    if add <= 0:
        return ZERO, ZERO
    n = int(periods or periods_per_year(freq))
    reg = floor_dollar(D(regular_earnings))                                   # step 1: ignore cents
    portion = floor_dollar(add / n)                                           # step 3: ignore cents
    kw = dict(scale=scale, residency=residency, claims_tft=claims_tft, study_loan=study_loan)
    t_reg, s_reg = total_withholding(rules, reg, freq, offset_claim=offset_claim, **kw)             # step 2
    t_all, s_all = total_withholding(rules, reg + portion, freq, offset_claim=offset_claim, **kw)   # steps 4-5
    tax = max(ZERO, (t_all - t_reg) * n)                                      # steps 6-7
    stsl = max(ZERO, (s_all - s_reg) * n)
    cap = floor_dollar(add * rules.method_a_cap)                              # step 8
    if tax + stsl > cap:                                                      # step 9: the lesser, combined
        if tax + stsl > 0:
            tax_c = floor_dollar(cap * tax / (tax + stsl))
            return tax_c, cap - tax_c
    return tax, stsl


def etp_tax(rules: RuleSet, etp_taxable, *, at_or_over_preservation_age: bool, cap_used=ZERO) -> Decimal:
    """Tax withheld on the taxable component of a life-benefit ETP. No study-loan component applies."""
    amt = D(etp_taxable)
    if amt <= 0:
        return ZERO
    cap_left = max(ZERO, rules.etp["cap"] - D(cap_used))
    within, over = min(amt, cap_left), max(ZERO, amt - cap_left)
    rate = rules.etp["rate_at_or_over_preservation_age" if at_or_over_preservation_age else "rate_under_preservation_age"]
    return floor_dollar(within * rate) + floor_dollar(over * rules.etp["rate_over_cap"])


def genuine_redundancy_tax_free(rules: RuleSet, payment, completed_years: int) -> Decimal:
    limit = rules.etp["genuine_redundancy_base"] + rules.etp["genuine_redundancy_per_year"] * max(0, int(completed_years))
    return min(D(payment), limit)
