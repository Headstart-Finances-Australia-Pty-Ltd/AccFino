"""Property maths (ATO guidance on rental properties and CGT).

Cost base has five elements: (1) money paid / market value given, (2) incidental costs of acquiring and disposing (stamp duty, legal fees, agent fees, valuation, borrowing costs),
(3) costs of owning that are not deducted, (4) capital costs of improving, (5) capital costs of preserving or defending title. Plant and equipment (depreciating assets) inside the price is
NOT part of the CGT cost base, and capital works deductions that were claimed are SUBTRACTED. The CGT event for a sale is the contract date.
Main residence: exempt while it is the main residence; a former home rented out can keep the exemption for up to 6 years of absence (if no other home is nominated).
The estimate below is an ESTIMATE for planning: the partial-exemption rules (including the market-value-at-first-income rule) need a tax agent's confirmation."""
from datetime import date, timedelta
from decimal import Decimal
from typing import Optional

from accfino.modules.investments.engine.money import ZERO, D, add_months, q2


def cost_base(p: dict, improvements=ZERO, capital_works_claimed=ZERO, ownership_costs=ZERO, title_costs=ZERO, include_selling_costs=True) -> dict:
    """p: purchase_price, depreciating_assets_value, stamp_duty, legal_costs, other_acq_costs, selling_costs, ownership_pct. Elements are for YOUR share."""
    share = D(p.get("ownership_pct", 100)) / D(100)
    e1 = D(p.get("purchase_price")) - D(p.get("depreciating_assets_value"))
    e2 = D(p.get("stamp_duty")) + D(p.get("legal_costs")) + D(p.get("other_acq_costs")) + (D(p.get("selling_costs")) if include_selling_costs else ZERO)
    e3, e4, e5 = D(ownership_costs), D(improvements), D(title_costs)
    cw = D(capital_works_claimed)
    total = (e1 + e2 + e3 + e4 + e5 - cw) * share
    return dict(element1_price=q2(e1 * share), element2_incidental=q2(e2 * share), element3_ownership=q2(e3 * share), element4_improvements=q2(e4 * share), element5_title=q2(e5 * share),
                capital_works_claimed=q2(cw * share), cost_base=q2(total), ownership_share=share)


def capital_works_deduction(construction_cost, rate, construction_date: Optional[date], period_start: date, period_end: date) -> Decimal:
    """Rate x construction cost x days in the period / days in the year, stopping when the 40 (2.5%) or 25 (4%) year life ends. ATO example: 30,000 x 2.5% x 124/365 = 254.79."""
    if not construction_cost or not construction_date:
        return ZERO
    life_years = 40 if D(rate) <= D("0.025") else 25
    end = min(period_end, add_months(construction_date, 12 * life_years))
    start = max(period_start, construction_date)
    days = max((end - start).days + 1, 0)
    return q2(D(construction_cost) * D(rate) * Decimal(days) / Decimal(366 if (period_end.year % 4 == 0) else 365))


def main_residence_fraction(use: str, owned_from: Optional[date], sold: Optional[date], mr_from: Optional[date], mr_until: Optional[date], first_income: Optional[date]) -> dict:
    """Share of the ownership period treated as main residence (exempt). Returns {fraction, notes[]}. Estimate only."""
    notes = []
    if not owned_from or not sold or sold <= owned_from:
        return dict(fraction=Decimal(0), notes=["Purchase (contract) and sale dates are needed to estimate the main residence exemption"])
    total = (sold - owned_from).days
    if use == "main_residence" and not first_income:
        return dict(fraction=Decimal(1), notes=["Main residence for the whole ownership period: generally fully exempt"])
    exempt_days = 0
    if mr_from and mr_until and mr_until > mr_from:
        exempt_days = (min(mr_until, sold) - max(mr_from, owned_from)).days
        absence_end = sold
        if first_income and first_income >= mr_until - timedelta(days=1):
            absent = (min(absence_end, add_months(mr_until, 72)) - mr_until).days
            exempt_days += max(absent, 0)
            notes.append("The 6-year rule is assumed to be chosen: up to 6 years of absence while rented is treated as main residence, provided no other home is nominated")
            if absence_end > add_months(mr_until, 72):
                notes.append("The property was rented for more than 6 years after you moved out: the days beyond 6 years are NOT exempt")
        elif not first_income:
            exempt_days += max((absence_end - mr_until).days, 0)
            notes.append("Vacant (not used to produce income) after moving out: the exemption can continue without a time limit if you choose")
    elif use != "main_residence":
        notes.append("No main residence period recorded: no exemption assumed")
    notes.append("Estimate by days of ownership. If the home was first rented after 20 August 1996, the ATO's market-value-at-first-income rule applies to the part of the gain: confirm with a tax agent")
    return dict(fraction=min(Decimal(exempt_days) / Decimal(total), Decimal(1)) if exempt_days > 0 else Decimal(0), notes=notes)


DISCOUNT = {"individual": Decimal("0.5"), "trust": Decimal("0.5"), "super": Decimal(1) / Decimal(3), "company": Decimal(0)}


def cgt_estimate(p: dict, cost: dict, holder: str, sale_price, sale_date: Optional[date]) -> dict:
    """Gain = capital proceeds - cost base (which already includes selling costs and is net of capital works claimed). Discount: more than 12 months from the CONTRACT date."""
    contract = p.get("contract_date")
    proceeds = D(sale_price) * D(p.get("ownership_pct", 100)) / D(100)
    gain = proceeds - cost["cost_base"]
    mr = main_residence_fraction(p.get("use", ""), contract, sale_date, p.get("main_residence_from"), p.get("main_residence_until"), p.get("first_income_date"))
    taxable_gain = gain * (1 - mr["fraction"]) if gain > 0 else gain
    held = bool(contract and sale_date and sale_date > add_months(contract, 12))
    disc = DISCOUNT.get(holder, Decimal(0)) if (held and taxable_gain > 0) else ZERO
    return dict(capital_proceeds=q2(proceeds), cost_base=cost["cost_base"], capital_gain_or_loss=q2(gain), main_residence_fraction=mr["fraction"].quantize(Decimal("0.0001")), exempt_amount=q2(gain - taxable_gain) if gain > 0 else ZERO,
                taxable_gain_before_discount=q2(taxable_gain), discount_applied=q2(taxable_gain * disc), net_capital_gain=q2(taxable_gain - taxable_gain * disc) if taxable_gain > 0 else q2(taxable_gain), held_over_12_months=held,
                holder=holder, notes=mr["notes"])


def performance(value, loan, rent, expenses, interest, purchase_total, years_held: Optional[float]) -> dict:
    """Yields and cash flow for a period. Gross yield = rent / value; net yield = (rent - running costs) / value (interest excluded); cash flow = rent - costs - interest; LVR and equity."""
    value, loan, rent, exp, intr = D(value), D(loan), D(rent), D(expenses), D(interest)
    out = dict(gross_yield=None if value <= 0 else float(rent / value), net_yield=None if value <= 0 else float((rent - exp) / value), cash_flow_before_interest=q2(rent - exp), cash_flow_after_interest=q2(rent - exp - intr),
               lvr=None if value <= 0 else float(loan / value), equity=q2(value - loan), capital_growth=q2(value - D(purchase_total)), cagr=None)
    out["negatively_geared"] = (rent - exp - intr) < 0
    if purchase_total and D(purchase_total) > 0 and value > 0 and years_held and years_held >= 0.5:
        out["cagr"] = float((value / D(purchase_total))) ** (1 / years_held) - 1
    return out
