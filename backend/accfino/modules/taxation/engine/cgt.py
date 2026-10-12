"""Capital gains engine (CGT events A1 etc. summarised as: proceeds less cost base). Pure functions.
Order applied, per ATO method statement: current-year capital losses against gains, then prior-year net capital losses, then the CGT discount on the
remaining discountable gains, then small business concessions. Losses are applied to NON-discountable gains first (the taxpayer-favourable ordering).
Assumptions made explicit: a 12-month holding requires disposal STRICTLY AFTER the first anniversary of acquisition (conservative); foreign residents get no discount
(the 2012 apportionment rules are not assessed); disposals on/after the announced reform date are flagged for review and shown under current law for information only."""
from datetime import date
from decimal import Decimal
from typing import Dict, List, Optional

from accfino.modules.taxation.engine.money import ZERO, D, q2
from accfino.modules.taxation.engine.rules import TaxRuleSet

HOLDERS = ("individual", "trust", "company", "super")
DISCOUNT_KEY = {"individual": "cgt.discount_individual", "trust": "cgt.discount_trust", "company": "cgt.discount_company", "super": "cgt.discount_super"}


def add_months(d: date, months: int) -> date:
    y, m = divmod(d.month - 1 + months, 12)
    y, m = d.year + y, m + 1
    import calendar
    return date(y, m, min(d.day, calendar.monthrange(y, m)[1]))


def held_long_enough(acquire: date, dispose: date, months: int = 12) -> bool:
    return dispose > add_months(acquire, months)


def cost_base(e: dict) -> Decimal:
    return sum((D(e.get(k)) for k in ("acquisition_cost", "incidental_costs", "ownership_costs", "capital_improvements", "disposal_costs")), ZERO)


def event_result(rs: TaxRuleSet, e: dict, holder: str, foreign_resident: bool = False) -> dict:
    """e: acquire_date, dispose_date (dates), proceeds, acquisition_cost, incidental_costs, ownership_costs, capital_improvements, disposal_costs,
    pre_cgt (bool), main_residence_exempt (bool), small_business: {active_asset_reduction: bool, exempt_15yr: bool, retirement_exemption: amount, rollover: amount}."""
    notes, review = [], []
    proceeds, cb = D(e.get("proceeds")), cost_base(e)
    gain = proceeds - cb
    reform = rs.get("cgt.reform") or {}
    if reform.get("effective_from") and e["dispose_date"] >= date.fromisoformat(reform["effective_from"]):
        review.append("Disposal on/after the announced 1 July 2027 CGT reform date: the result below is under CURRENT law for information only. " + reform.get("description", ""))
    if e.get("pre_cgt"):
        return dict(gain="0.00", loss="0.00", cost_base=str(q2(cb)), discountable=False, discount_rate="0", status="exempt", notes=["Pre-CGT asset (acquired before 20 Sept 1985): disregarded."], review=review)
    if e.get("main_residence_exempt"):
        return dict(gain="0.00", loss="0.00", cost_base=str(q2(cb)), discountable=False, discount_rate="0", status="exempt",
                    notes=["Main residence exemption claimed by the preparer (partial exemptions, absence rules and the 6-year rule are not assessed)."], review=review + ["Confirm full main-residence exemption conditions."])
    held = held_long_enough(e["acquire_date"], e["dispose_date"], int(rs.get("cgt.hold_months") or 12))
    holder_rate = rs.req(DISCOUNT_KEY[holder])
    discountable = gain > 0 and held and not foreign_resident and holder_rate > 0
    if gain > 0 and not held:
        notes.append("Held 12 months or less (or disposal not strictly after the first anniversary): no CGT discount.")
    if foreign_resident and gain > 0:
        review.append("Foreign resident: no discount applied; the apportionment of pre-May-2012 gains is not assessed.")
    if holder == "company" and gain > 0:
        notes.append("Companies are not entitled to the CGT discount.")
    return dict(gain=str(q2(max(gain, ZERO))), loss=str(q2(max(-gain, ZERO))), cost_base=str(q2(cb)), discountable=discountable, discount_rate=str(holder_rate if discountable else 0),
                status="review" if review else "calculated", holding_days=(e["dispose_date"] - e["acquire_date"]).days, notes=notes, review=review)


def net_capital_gain(rs: TaxRuleSet, events: List[dict], holder: str, *, prior_losses=ZERO, foreign_resident: bool = False) -> dict:
    """events as for event_result (each may carry 'id'). Returns per-event results and the net capital gain / losses carried forward."""
    rows, gains_disc, gains_non, losses = [], ZERO, ZERO, ZERO
    sb_events = []
    for e in events:
        r = event_result(rs, e, holder, foreign_resident)
        rows.append(dict(id=e.get("id"), name=e.get("asset_name"), dispose_date=e["dispose_date"].isoformat(), **r))
        g, l = D(r["gain"]), D(r["loss"])
        losses += l
        if g > 0:
            if r["discountable"]:
                gains_disc += g
            else:
                gains_non += g
            if e.get("small_business"):
                sb_events.append((e, r))
    remaining_losses = losses
    use = min(remaining_losses, gains_non)
    gains_non -= use
    remaining_losses -= use
    use = min(remaining_losses, gains_disc)
    gains_disc -= use
    remaining_losses -= use
    cy_losses_used = losses - remaining_losses
    prior = D(prior_losses)
    use_p_non = min(prior, gains_non)
    gains_non -= use_p_non
    use_p_disc = min(prior - use_p_non, gains_disc)
    gains_disc -= use_p_disc
    prior_used = use_p_non + use_p_disc
    rate = rs.req(DISCOUNT_KEY[holder])
    discount = q2(gains_disc * rate)
    after_discount = gains_disc - discount
    ncg = gains_non + after_discount
    sb_note, sb_total_reduction = [], ZERO
    for e, r in sb_events:
        sbc = e["small_business"]
        g = D(r["gain"])
        if sbc.get("exempt_15yr"):
            sb_total_reduction += g
            sb_note.append(f"{e.get('asset_name')}: 15-year exemption claimed (basic conditions NOT assessed)")
        else:
            if sbc.get("active_asset_reduction"):
                red = q2(g * rs.req("cgt.active_asset_reduction"))
                sb_total_reduction += red
                sb_note.append(f"{e.get('asset_name')}: 50% active asset reduction (basic conditions NOT assessed)")
            for k, lab in (("retirement_exemption", "retirement exemption"), ("rollover", "rollover")):
                if D(sbc.get(k)):
                    sb_total_reduction += D(sbc[k])
                    sb_note.append(f"{e.get('asset_name')}: {lab} {q2(D(sbc[k]))} (cap, 55+/retirement and CGT concession stakeholder tests NOT assessed)")
    ncg_final = max(ncg - sb_total_reduction, ZERO)
    flags = [r for row in rows for r in row.get("review", [])]
    if sb_note:
        flags.append("Small business CGT concessions need the basic conditions (turnover/net asset value test, active asset test) confirmed by a tax agent.")
    return dict(holder=holder, events=rows, total_gains_before_losses=str(q2(sum((D(r["gain"]) for r in rows), ZERO))), current_year_losses=str(q2(losses)),
                current_year_losses_applied=str(q2(cy_losses_used)), prior_losses_applied=str(q2(prior_used)), discount_applied=str(discount),
                small_business_reductions=str(q2(sb_total_reduction)), small_business_notes=sb_note, net_capital_gain=str(q2(ncg_final)),
                losses_carried_forward=str(q2(remaining_losses + (prior - prior_used))), review=sorted(set(flags)),
                assumption="12-month rule requires disposal strictly after the first anniversary. Losses applied to non-discount gains first.")
