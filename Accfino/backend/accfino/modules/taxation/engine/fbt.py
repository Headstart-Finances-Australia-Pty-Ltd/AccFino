"""Fringe benefits tax engine (FBT year 1 April - 31 March). Pure functions over a TaxRuleSet.
Supported valuation: car (statutory formula), loan (benchmark interest), expense payment, property / residual (cost or market value less contributions),
meal entertainment (actual cost, percentage of cost treated as taxable), minor-benefit exemption, and employer-declared exemptions (e.g. eligible EVs) with a reason.
NOT assessed (flagged on the result): car operating cost method, housing, living-away-from-home, employee-contribution timing rules, NFP rebates and caps,
exempt body status, otherwise-deductible rule evidence, the EV exemption conditions. A tax agent must review the FBT return."""
from decimal import Decimal
from typing import List

from accfino.modules.taxation.engine.money import ZERO, D, q2
from accfino.modules.taxation.engine.rules import TaxRuleSet

BENEFIT_TYPES = ("car", "loan", "expense_payment", "property", "residual", "entertainment", "other")


def gross_up(rs: TaxRuleSet, taxable_value, type1: bool) -> Decimal:
    return q2(D(taxable_value) * rs.req("fbt.type1_gross_up" if type1 else "fbt.type2_gross_up"))


def taxable_value(rs: TaxRuleSet, b: dict) -> dict:
    """Returns {taxable_value, method, notes[], review[]} for one benefit record. b: {type, ...type-specific numbers..., employee_contribution, exempt_reason}"""
    t = b.get("type")
    notes: List[str] = []
    review: List[str] = []
    contrib = D(b.get("employee_contribution"))
    if t not in BENEFIT_TYPES:
        raise ValueError(f"Unknown benefit type '{t}'")
    if b.get("exempt_reason"):
        return dict(taxable_value="0.00", method="exempt", notes=[f"Exempt: {b['exempt_reason']}"], review=["An exemption was declared by the preparer. Confirm the legislative conditions are met and keep evidence."])
    if t == "car":
        base, days = D(b.get("base_value")), D(b.get("days_available"))
        if days <= 0 or days > 366:
            raise ValueError("days_available must be between 1 and 366")
        frac = rs.req("fbt.statutory_fraction")
        v = base * frac * days / Decimal(365) - contrib
        notes.append(f"Statutory formula: base value x {frac * 100:.0f}% x {days}/365 less employee contributions.")
        review.append("Car base value, private use and the operating-cost method alternative should be confirmed.")
        method = "car_statutory"
    elif t == "loan":
        bench = rs.dec("fbt.benchmark_loan_rate")
        if bench is None:
            raise ValueError("The FBT benchmark loan interest rate for this FBT year is not loaded. Enter it under Tax > Rates & Settings (ATO TD for the FBT year).")
        principal, interest_paid, days = D(b.get("average_balance")), D(b.get("interest_paid")), D(b.get("days"))
        v = max(principal * bench * days / Decimal(365) - interest_paid, ZERO)
        notes.append(f"Benchmark rate {bench * 100:.2f}% x average balance x {days}/365 less interest paid.")
        review.append("Check the loan is not exempt (e.g. otherwise-deductible loan reduction) and the average balance method.")
        method = "loan_benchmark"
    elif t == "expense_payment":
        actual = D(b.get("actual_cost"))
        od = D(b.get("otherwise_deductible"))
        v = actual - contrib - od
        notes.append("Actual expense less employee contribution and the otherwise-deductible amount.")
        if od:
            review.append("Otherwise-deductible reduction requires a declaration from the employee and records.")
        method = "expense_payment"
    elif t in ("property", "residual", "other"):
        cost = D(b.get("actual_cost") or b.get("market_value"))
        v = cost - contrib
        notes.append("Cost or market value less employee contribution.")
        method = t
    else:                                                        # entertainment
        cost = D(b.get("actual_cost"))
        pct = D(b.get("taxable_percent") if b.get("taxable_percent") not in (None, "") else 100)
        v = cost * pct / Decimal(100) - contrib
        notes.append(f"Meal entertainment: {pct}% of actual cost treated as taxable (50/50 split and the actual-method rules require a valid election and records).")
        review.append("Meal entertainment elections (50/50 or 12-week register) are not assessed.")
        method = "entertainment"
    v = max(v, ZERO)
    th = rs.dec("fbt.minor_benefit_threshold")
    if b.get("minor_benefit") and th is not None:
        if D(b.get("actual_cost") or v) < th:
            return dict(taxable_value="0.00", method="minor_benefit", notes=[f"Minor benefit under {q2(th)}: exempt (unlikely to recur / not a salary-packaging substitute - confirm)."],
                        review=["Minor benefit exemption must be assessed per benefit, including the 'infrequent and irregular' test."])
        review.append(f"Marked as a minor benefit but the cost is not below {q2(th)}: it is NOT exempt.")
    return dict(taxable_value=str(q2(v)), method=method, notes=notes, review=review)


def year_summary(rs: TaxRuleSet, benefits: List[dict]) -> dict:
    """benefits: [{id, employee, type1, taxable_value, ...}] (taxable_value already computed). Returns FBT payable, RFBA per employee and totals."""
    rate = rs.req("fbt.rate")
    t1 = sum((D(b["taxable_value"]) for b in benefits if b.get("type1")), ZERO)
    t2 = sum((D(b["taxable_value"]) for b in benefits if not b.get("type1")), ZERO)
    g1, g2 = gross_up(rs, t1, True), gross_up(rs, t2, False)
    fbt = q2((g1 + g2) * rate)
    thr = rs.req("fbt.rfba_threshold")
    by_emp: dict = {}
    for b in benefits:
        e = by_emp.setdefault(b.get("employee") or "(unassigned)", dict(employee=b.get("employee") or "(unassigned)", taxable_value=ZERO, grossed_up_type1=ZERO, grossed_up_type2=ZERO, reportable_grossed_up=ZERO, count=0))
        tv = D(b["taxable_value"])
        e["taxable_value"] += tv
        e["count"] += 1
        e["reportable_grossed_up"] += gross_up(rs, tv, False)             # RFBA is always grossed up with the lower (type 2) rate
        e["grossed_up_type1" if b.get("type1") else "grossed_up_type2"] += gross_up(rs, tv, bool(b.get("type1")))
    emps = []
    for e in by_emp.values():
        reportable = e["reportable_grossed_up"] > thr
        emps.append(dict(employee=e["employee"], benefits=e["count"], taxable_value=str(q2(e["taxable_value"])), reportable_grossed_up=str(q2(e["reportable_grossed_up"])),
                         rfba_reportable=reportable, rfba_amount=str(q2(e["reportable_grossed_up"])) if reportable else "0.00"))
    return dict(type1_taxable=str(q2(t1)), type2_taxable=str(q2(t2)), type1_grossed_up=str(g1), type2_grossed_up=str(g2), aggregate_fringe_benefits_amount=str(q2(g1 + g2)),
                fbt_rate=str(rate), fbt_payable=str(fbt), employees=sorted(emps, key=lambda x: x["employee"]),
                not_assessed=["Not-for-profit rebates and caps", "Employee contribution timing rules", "Car operating-cost method", "Housing and living-away-from-home allowances",
                              "EV exemption conditions (declare exempt benefits with a reason)", "FBT instalment variation"],
                deduction_note="FBT payable is generally deductible for income tax in the income year in which the FBT year ends; employee contributions are assessable. Review with a tax agent.")
