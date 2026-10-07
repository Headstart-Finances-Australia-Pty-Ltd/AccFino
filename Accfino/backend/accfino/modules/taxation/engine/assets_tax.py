"""Small-business depreciation review: instant asset write-off (IAWO) eligibility and the simplified depreciation pool, compared with the book depreciation
in the ledger to propose income-tax adjustments. Pure functions. Only small business entities (aggregated turnover under the limit) are computed; every other
entity needs effective-life depreciation which AccFino does not determine (flagged, never guessed)."""
from datetime import date
from decimal import Decimal
from typing import List

from accfino.modules.taxation.engine.money import ZERO, D, q2
from accfino.modules.taxation.engine.rules import TaxRuleSet

NOT_DEPRECIATING = ("land", "capital_works", "building", "buildings", "goodwill")


def review(rs: TaxRuleSet, assets: List[dict], *, fy_start: date, fy_end: date, is_sbe: bool, gst_registered: bool, pool_opening=ZERO, use_simplified: bool = True) -> dict:
    """assets: [{id, number, name, category, cost, purchase_date, status, disposal_date, disposal_proceeds, business_use_pct (default 100), book_depreciation}]"""
    thr = rs.req("small_business.instant_asset_write_off.threshold")
    first_rate, later_rate, wo_below = rs.req("small_business.pool.first_year_rate"), rs.req("small_business.pool.later_year_rate"), rs.req("small_business.pool.write_off_balance_below")
    lines, warnings = [], []
    book_total = sum((D(a.get("book_depreciation")) for a in assets), ZERO)
    if not is_sbe:
        warnings.append("Not a small business entity (or turnover not confirmed): tax depreciation by effective life is NOT computed by AccFino. Book depreciation is shown only.")
        return dict(computed=False, iawo_total="0.00", pool=None, tax_depreciation="0.00", book_depreciation=str(q2(book_total)), difference="0.00", lines=[dict(asset_id=a["id"], number=a["number"], name=a["name"], treatment="not_computed", cost=str(q2(D(a["cost"]))), deduction="0.00", book=str(q2(D(a.get("book_depreciation")))), note="Needs effective-life tax depreciation (not an SBE).") for a in assets], warnings=warnings)
    iawo, additions, disposals = ZERO, ZERO, ZERO
    for a in assets:
        cost, use = D(a["cost"]), D(a.get("business_use_pct") if a.get("business_use_pct") not in (None, "") else 100) / Decimal(100)
        cat = (a.get("category") or "").lower()
        book = D(a.get("book_depreciation"))
        if cat in NOT_DEPRECIATING:
            lines.append(dict(asset_id=a["id"], number=a["number"], name=a["name"], treatment="excluded", cost=str(q2(cost)), deduction="0.00", book=str(q2(book)), note="Land, buildings and capital works are outside the instant write-off and pool (capital works deductions are separate)."))
            continue
        if a.get("disposal_date") and fy_start <= a["disposal_date"] <= fy_end:
            disposals += D(a.get("disposal_proceeds")) * use
            lines.append(dict(asset_id=a["id"], number=a["number"], name=a["name"], treatment="disposed", cost=str(q2(cost)), deduction="0.00", book=str(q2(book)), note="Disposal proceeds reduce the pool balance (a balancing adjustment applies outside the pool)."))
            continue
        if fy_start <= a["purchase_date"] <= fy_end:
            note = "Cost taken as the ledger cost; for GST-registered entities this should be the cost excluding GST." if gst_registered else "Cost including GST (not registered)."
            if cost < thr:
                ded = q2(cost * use)
                iawo += ded
                lines.append(dict(asset_id=a["id"], number=a["number"], name=a["name"], treatment="instant_asset_write_off", cost=str(q2(cost)), deduction=str(ded), book=str(q2(book)), note=note + f" Under the {q2(thr)} threshold: immediate deduction of the business-use portion."))
            elif use_simplified:
                additions += cost * use
                lines.append(dict(asset_id=a["id"], number=a["number"], name=a["name"], treatment="pool_addition", cost=str(q2(cost)), deduction="0.00", book=str(q2(book)), note=note + " Added to the small business pool."))
            else:
                lines.append(dict(asset_id=a["id"], number=a["number"], name=a["name"], treatment="not_computed", cost=str(q2(cost)), deduction="0.00", book=str(q2(book)), note="Simplified depreciation not chosen: effective-life depreciation not computed."))
        else:
            lines.append(dict(asset_id=a["id"], number=a["number"], name=a["name"], treatment="pool_existing" if use_simplified else "not_computed", cost=str(q2(cost)), deduction="0.00", book=str(q2(book)), note="Acquired in an earlier year: covered by the pool opening balance you enter (AccFino does not hold prior-year tax values)."))
    opening = D(pool_opening)
    pool = None
    if use_simplified:
        before = opening + additions - disposals
        if before < wo_below:
            pool_ded, how = max(before, ZERO), f"Pool balance before the deduction ({q2(before)}) is under {q2(wo_below)}: written off in full."
        else:
            pool_ded, how = q2(opening * later_rate + additions * first_rate), f"{later_rate * 100:.0f}% of the opening balance + {first_rate * 100:.0f}% of additions."
        pool = dict(opening=str(q2(opening)), additions=str(q2(additions)), disposals=str(q2(disposals)), balance_before_deduction=str(q2(before)), deduction=str(q2(pool_ded)), closing=str(q2(before - pool_ded)), method=how)
        if opening == 0 and any(l["treatment"] == "pool_existing" for l in lines):
            warnings.append("Assets from earlier years exist but no pool opening balance was entered: enter the closing pool balance from last year's return.")
    tax_total = iawo + D((pool or {}).get("deduction"))
    return dict(computed=True, iawo_total=str(q2(iawo)), pool=pool, tax_depreciation=str(q2(tax_total)), book_depreciation=str(q2(book_total)), difference=str(q2(tax_total - book_total)), lines=lines,
                warnings=warnings + ["Eligibility also needs: first used or installed ready for use in the year, and the business-use percentage. Check the aggregated turnover test and that the entity has not opted out of simplified depreciation."])
