"""State payroll tax MONITOR (not a liability calculator). Compares wages from Payroll with the state's registration threshold and says how close the business is.
Why not a calculator: thresholds taper or are adjusted at higher wage levels (VIC, QLD, WA), regional rates and surcharges apply, and liability depends on grouping, interstate
wages, contractor deeming, fringe benefits and allowances that AccFino does not hold. An indicative amount is produced ONLY where the rule is a flat rate above the threshold (NSW).
Pure functions; every parameter comes from the rule set (payroll_tax.states.<STATE>)."""
from decimal import Decimal
from typing import Optional

from accfino.modules.taxation.engine.money import ZERO, D, q2
from accfino.modules.taxation.engine.rules import TaxRuleSet

NOT_ASSESSED = ["Grouping of related businesses (the threshold is shared)", "Interstate wages and apportionment between jurisdictions", "Contractor payments deemed to be wages",
                "Allowances, fringe benefits, employee share schemes, termination payments", "Exemptions (apprentices, parental leave, charities)", "Tapering of the threshold at higher wage levels, regional rates and surcharges",
                "Wages paid by other employers in the group, and part-year registration"]


def assess(rs: TaxRuleSet, state: Optional[str], wages_ytd, months_elapsed: int, *, approach_ratio: Decimal = Decimal("0.8")) -> dict:
    """wages_ytd: wages (and super) paid so far this income year per Payroll. months_elapsed 1..12. Returns the status and the working."""
    out = dict(state=state, status="no_state", threshold=None, rate=None, wages_ytd=str(q2(wages_ytd)), projected_wages=None, ratio=None, indicative_tax=None, message="", not_assessed=NOT_ASSESSED)
    if not state:
        out["message"] = "No state or territory is set in the tax profile, so no payroll tax threshold can be applied."
        return out
    cfg = rs.get(f"payroll_tax.states.{state}")
    if not isinstance(cfg, dict) or cfg.get("annual_threshold") is None:
        out.update(status="not_loaded", message=f"The 2026-27 payroll tax threshold for {state} is not loaded (sources conflict). Enter it from the {state} revenue office under Rates & Settings.")
        return out
    thr = D(cfg["annual_threshold"])
    months = min(max(int(months_elapsed), 1), 12)
    projected = q2(D(wages_ytd) / months * 12)
    ratio = (projected / thr) if thr else ZERO
    out.update(threshold=str(q2(thr)), rate=str(D(cfg["rate"])) if cfg.get("rate") is not None else None, projected_wages=str(projected), ratio=str(ratio.quantize(Decimal("0.001"))))
    if ratio >= 1:
        out["status"] = "above"
        out["message"] = (f"Projected annual wages ({q2(projected)}) are at or above the {state} threshold ({q2(thr)}). Registration is generally required within days of the month in which wages first exceed the monthly threshold: "
                          "check with the revenue office now.")
    elif ratio >= approach_ratio:
        out["status"] = "approaching"
        out["message"] = f"Projected annual wages are {ratio * 100:.0f}% of the {state} threshold. Plan for registration."
    else:
        out["status"] = "below"
        out["message"] = f"Projected annual wages are {ratio * 100:.0f}% of the {state} threshold. No payroll tax is expected on Payroll wages alone."
    if out["status"] == "above" and cfg.get("flat") and cfg.get("rate") is not None:
        out["indicative_tax"] = str(q2((projected - thr) * D(cfg["rate"])))
        out["indicative_note"] = "Flat-rate estimate on Payroll wages only. Taxable wages usually include more (see not assessed): the revenue office assessment governs."
    elif out["status"] == "above":
        out["indicative_note"] = f"{state} uses tapering or tiered rates at higher wage levels, so no estimate is shown: use the revenue office calculator."
    return out
