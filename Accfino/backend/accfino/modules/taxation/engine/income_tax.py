"""Income-tax engine (pure functions, Decimal, no database). Every function returns the number AND the working, so the UI can explain it:
steps are tagged  calculated | input | assumption | warning | review  (the taxonomy the Tax workpapers use).
It never contains a rate: everything comes from the TaxRuleSet."""
from decimal import Decimal
from typing import Dict, List, Optional, Tuple

from accfino.modules.taxation.engine.money import ZERO, D, q2
from accfino.modules.taxation.engine.rules import TaxRuleSet


def step(key, label, amount, kind="calculated", note="") -> dict:
    return dict(key=key, label=label, amount=str(q2(amount)) if amount is not None else None, kind=kind, note=note)


def progressive_tax(brackets: List[Tuple[Optional[Decimal], Decimal]], income: Decimal) -> Decimal:
    """Tax on `income` using bracket rows (upper limit or None, marginal rate). Income at/below the first limit with rate 0 is tax free."""
    income = max(D(income), ZERO)
    tax, lower = ZERO, ZERO
    for upper, rate in brackets:
        top = income if upper is None else min(income, upper)
        if top > lower:
            tax += (top - lower) * rate
        if upper is None or income <= upper:
            break
        lower = upper
    return q2(tax)


def marginal_rate(brackets, income) -> Decimal:
    income = max(D(income), ZERO)
    for upper, rate in brackets:
        if upper is None or income <= upper:
            return rate
    return brackets[-1][1]


def lito(rs: TaxRuleSet, taxable_income) -> Decimal:
    """Low income tax offset (residents)."""
    ti = D(taxable_income)
    mx, u1, r1, u2, r2, z = (rs.req(f"individual.lito.{k}") for k in ("max", "step1_upper", "step1_rate", "step2_upper", "step2_rate", "zero_at"))
    if ti <= u1:
        return q2(mx)
    if ti <= u2:
        return q2(max(mx - (ti - u1) * r1, ZERO))
    base = mx - (u2 - u1) * r1
    if ti <= z:
        return q2(max(base - (ti - u2) * r2, ZERO))
    return ZERO


def medicare_levy(rs: TaxRuleSet, taxable_income, resident: bool = True) -> Tuple[Decimal, List[dict]]:
    """2% levy with the SINGLE low-income reduction. Thresholds not loaded -> full 2% plus a review warning (never a guess). Thresholds loaded but flagged provisional
    (the latest published year carried forward) -> used, and labelled an assumption on the return. Family, seniors/pensioner and dependant thresholds are never assessed."""
    notes: List[dict] = []
    if not resident:
        return q2(ZERO), [step("medicare_foreign", "Medicare levy", 0, "assumption", "Foreign residents are not liable for the Medicare levy (confirm residency).")]
    ti = max(D(taxable_income), ZERO)
    rate = rs.req("individual.medicare.rate")
    full = q2(ti * rate)
    lower = rs.dec("individual.medicare.low_income_single_threshold")
    if lower is None:
        notes.append(step("medicare_thresholds", "Medicare levy low-income reduction", None, "review",
                          "The low-income thresholds are not loaded, so the full levy is shown. Load them under Rates & Settings or have a tax agent review."))
        return full, notes
    notes.append(step("medicare_scope", "Medicare levy: scope", None, "review",
                      "Only the single low-income reduction is assessed. Family income, dependants, seniors and pensioner (SAPTO) thresholds, exemptions and the Medicare levy surcharge are not: a tax agent must review."))
    if rs.get("individual.medicare.provisional"):
        notes.append(step("medicare_provisional", "Medicare levy thresholds are provisional", None, "assumption",
                          f"The 2026-27 low-income thresholds are not yet published. The latest published figures ({q2(lower)} no levy) are carried forward; the levy may change when the ATO publishes them."))
    if ti <= lower:
        return q2(ZERO), notes
    reduced = q2((ti - lower) * rs.req("individual.medicare.phase_in_rate"))
    return min(full, reduced), notes


def standard_deduction(rs: TaxRuleSet, fy: str, labour_income, itemised_covered_expenses) -> Tuple[Decimal, List[dict]]:
    """The $1,000 standard (instant) deduction for work-related expenses, where it applies."""
    cfg = rs.get("individual.standard_deduction") or {}
    if not cfg.get("enabled") or fy < cfg.get("first_income_year", "9999-99"):
        return ZERO, []
    amt = D(cfg["amount"])
    li = max(D(labour_income), ZERO)
    covered = max(D(itemised_covered_expenses), ZERO)
    value = max(min(amt, li) - covered, ZERO) if cfg.get("reduced_by_itemised_work_expenses") else min(amt, li)
    notes = [step("standard_deduction", "Standard deduction for work-related expenses", value, "review",
                  "ATO: first applies to the 2026-27 return. Reduced by itemised covered work expenses claimed. Legislative status is reported inconsistently by secondary sources - confirm before lodging.")]
    return q2(value), notes


def individual_tax(rs: TaxRuleSet, taxable_income, *, resident: bool = True) -> Decimal:
    key = "individual.resident_brackets" if resident else "individual.foreign_resident_brackets"
    return progressive_tax(rs.brackets(key), taxable_income)


def compute_individual(rs: TaxRuleSet, fy: str, i: dict) -> dict:
    """Individual / sole trader. Inputs (all optional, strings or numbers):
    assessable_income, business_net_income (included in assessable), labour_income, deductions_other, work_expenses_itemised,
    net_capital_gain, franking_credits, tax_withheld, instalments_paid, help_repayment, medicare_surcharge, other_offsets, losses_brought_forward,
    resident (default true), aggregated_turnover, claim_standard_deduction (default true)."""
    steps: List[dict] = []
    warnings: List[dict] = []
    resident = bool(i.get("resident", True))
    assessable = D(i.get("assessable_income"))
    ncg = D(i.get("net_capital_gain"))
    franking = D(i.get("franking_credits"))
    steps.append(step("assessable", "Assessable income (accounting profit after adjustments, other income)", assessable, "calculated"))
    if ncg:
        steps.append(step("ncg", "Net capital gain (from the CGT register)", ncg, "calculated"))
    if franking:
        steps.append(step("franking_gross_up", "Franking credits (grossed up into income)", franking, "input", "Franking credits are included in assessable income and then claimed as an offset."))
    gross = assessable + ncg + franking
    ded = D(i.get("deductions_other"))
    sd, sdn = (ZERO, [])
    if resident and i.get("claim_standard_deduction", True):
        sd, sdn = standard_deduction(rs, fy, i.get("labour_income"), i.get("work_expenses_itemised"))
        steps.extend(sdn)
    losses = D(i.get("losses_brought_forward"))
    taxable = max(gross - ded - sd - min(losses, max(gross - ded - sd, ZERO)), ZERO)
    if ded:
        steps.append(step("deductions_other", "Other deductions (not already in the accounts)", -ded, "input"))
    if losses:
        steps.append(step("losses", "Tax losses brought forward applied", -min(losses, max(gross - ded - sd, ZERO)), "input", "Loss carry-forward rules and the continuity-of-ownership tests are not assessed: tax agent review."))
    steps.append(step("taxable_income", "Taxable income", taxable, "calculated"))
    tax = individual_tax(rs, taxable, resident=resident)
    steps.append(step("income_tax", "Income tax on taxable income", tax, "calculated", "Resident rates" if resident else "Foreign resident rates"))
    mrate = marginal_rate(rs.brackets("individual.resident_brackets" if resident else "individual.foreign_resident_brackets"), taxable)
    offsets = ZERO
    if resident:
        lo = lito(rs, taxable)
        if lo:
            steps.append(step("lito", "Low income tax offset", -lo, "calculated"))
        offsets += lo
        nsbi = max(D(i.get("business_net_income")), ZERO)
        turnover = D(i.get("aggregated_turnover"))
        sb_lim = rs.dec("individual.sbito.turnover_limit")
        if nsbi and taxable > 0 and turnover and sb_lim and turnover < sb_lim:
            sb = min(rs.req("individual.sbito.cap"), q2(rs.req("individual.sbito.rate") * tax * min(nsbi / taxable, Decimal(1))))
            steps.append(step("sbito", "Small business income tax offset", -sb, "calculated", "16% of the tax on net small business income, capped. Eligibility (aggregated turnover under the limit) must be confirmed."))
            offsets += sb
        elif nsbi and not turnover:
            warnings.append(step("sbito_unknown", "Small business income tax offset", None, "review", "Business income present but aggregated turnover not entered: SBITO not calculated."))
    other_off = D(i.get("other_offsets"))
    if other_off:
        steps.append(step("other_offsets", "Other tax offsets (entered)", -other_off, "input"))
        offsets += other_off
    medicare, mnotes = medicare_levy(rs, taxable, resident)
    warnings.extend(mnotes)
    if medicare:
        steps.append(step("medicare", "Medicare levy", medicare, "calculated"))
    help_rep, mls = D(i.get("help_repayment")), D(i.get("medicare_surcharge"))
    if help_rep:
        steps.append(step("help", "HELP / study loan repayment (entered from the ATO)", help_rep, "input", "Repayment thresholds are not embedded; enter the amount from the ATO estimate."))
    if mls:
        steps.append(step("mls", "Medicare levy surcharge (entered)", mls, "input"))
    tiers = rs.get("individual.mls.single_tiers")
    if resident and tiers and not mls:
        base = D(tiers[0][0])
        if taxable > base:
            rate = next((D(r) for up, r in tiers if up is None or taxable <= D(up)), D(tiers[-1][1]))
            warnings.append(step("mls_possible", "Medicare levy surcharge", None, "review",
                                 f"Taxable income {q2(taxable)} is above the single surcharge threshold {q2(base)}. If there was no appropriate private hospital cover the surcharge (indicatively {rate * 100:.2f}% of income for surcharge purposes, "
                                 "which also includes reportable fringe benefits and super contributions) may apply: enter it above or confirm cover. Family thresholds and dependants are not assessed."))
    assessed = max(tax - min(offsets, tax), ZERO) + medicare + help_rep + mls
    steps.append(step("tax_assessed", "Tax assessed (before credits)", assessed, "calculated", "Non-refundable offsets cannot reduce income tax below nil."))
    credits = D(i.get("tax_withheld")) + D(i.get("instalments_paid")) + franking
    if D(i.get("tax_withheld")):
        steps.append(step("withheld", "PAYG tax withheld by payers (entered)", -D(i.get("tax_withheld")), "input"))
    if D(i.get("instalments_paid")):
        steps.append(step("instalments", "PAYG instalments paid (from lodged BAS/IAS)", -D(i.get("instalments_paid")), "calculated"))
    if franking:
        steps.append(step("franking_offset", "Franking credit offset", -franking, "input"))
    balance = assessed - credits
    steps.append(step("balance", "Balance: payable (+) / refundable (-)", balance, "calculated"))
    return dict(entity="individual", fy=fy, taxable_income=str(q2(taxable)), income_tax=str(tax), offsets=str(q2(min(offsets, tax))), medicare_levy=str(q2(medicare)),
                tax_assessed=str(q2(assessed)), credits=str(q2(credits)), balance=str(q2(balance)), marginal_rate=str(mrate), steps=steps, warnings=warnings, rule_set=rs.id)


def company_rate(rs: TaxRuleSet, aggregated_turnover, passive_income_ratio) -> Tuple[Decimal, str]:
    lim, pmax = rs.req("company.base_rate_turnover_limit"), rs.req("company.base_rate_passive_income_max")
    if D(aggregated_turnover) < lim and D(passive_income_ratio) <= pmax:
        return rs.req("company.base_rate"), "Base rate entity (aggregated turnover under the limit and passive income share within the limit)"
    return rs.req("company.standard_rate"), "Standard company rate (not a base rate entity)"


def compute_company(rs: TaxRuleSet, fy: str, i: dict) -> dict:
    """Company or complying SMSF (accumulation phase). Inputs: assessable_income, deductions_other, net_capital_gain, losses_brought_forward,
    aggregated_turnover, passive_income_ratio, instalments_paid, franking_credits, entity_kind ('company' | 'smsf')."""
    steps, warnings = [], []
    kind = i.get("entity_kind", "company")
    gross = D(i.get("assessable_income")) + D(i.get("net_capital_gain")) + D(i.get("franking_credits"))
    ded = D(i.get("deductions_other"))
    losses = D(i.get("losses_brought_forward"))
    steps.append(step("assessable", "Assessable income (accounting profit after adjustments)", D(i.get("assessable_income")), "calculated"))
    if D(i.get("net_capital_gain")):
        steps.append(step("ncg", "Net capital gain (companies get no CGT discount)", D(i.get("net_capital_gain")), "calculated"))
    if ded:
        steps.append(step("deductions_other", "Other deductions", -ded, "input"))
    before_loss = max(gross - ded, ZERO)
    used = min(losses, before_loss)
    if used:
        steps.append(step("losses", "Tax losses brought forward applied", -used, "input", "Company loss rules (continuity of ownership / same business test) are not assessed: tax agent review."))
        warnings.append(step("loss_tests", "Loss utilisation", None, "review", "Confirm the continuity of ownership test or same/similar business test is met."))
    taxable = before_loss - used
    steps.append(step("taxable_income", "Taxable income", taxable, "calculated"))
    if kind == "smsf":
        rate, why = rs.req("company.smsf_accumulation_rate"), "Complying SMSF accumulation-phase rate (pension-phase exempt income NOT assessed): specialist review required"
        warnings.append(step("smsf", "SMSF", None, "review", "Exempt pension income, segregation and the SMSF annual return are not assessed."))
    else:
        rate, why = company_rate(rs, i.get("aggregated_turnover"), i.get("passive_income_ratio"))
        if not D(i.get("aggregated_turnover")):
            warnings.append(step("turnover_missing", "Aggregated turnover", None, "review", "Aggregated turnover not entered: the standard company rate is used only if you confirm it; enter turnover to test base-rate-entity status."))
    tax = q2(taxable * rate)
    steps.append(step("income_tax", f"Income tax at {rate * 100:.0f}%", tax, "calculated", why))
    franking = D(i.get("franking_credits"))
    inst = D(i.get("instalments_paid"))
    credits = franking + inst
    if inst:
        steps.append(step("instalments", "PAYG instalments paid (from lodged BAS/IAS)", -inst, "calculated"))
    if franking:
        steps.append(step("franking_offset", "Franking credit offset", -franking, "input"))
    balance = tax - credits
    steps.append(step("balance", "Balance: payable (+) / refundable (-)", balance, "calculated"))
    return dict(entity=kind, fy=fy, taxable_income=str(q2(taxable)), income_tax=str(tax), offsets="0.00", medicare_levy="0.00", tax_assessed=str(tax), credits=str(q2(credits)),
                balance=str(q2(balance)), rate=str(rate), steps=steps, warnings=warnings, rule_set=rs.id,
                franking_note="Franking account (credits and debits, benchmark rule, distribution statements) is not maintained by AccFino: tax agent review.")


def compute_flow_through(rs: TaxRuleSet, fy: str, i: dict, kind: str) -> dict:
    """Partnership or trust: the entity does not pay income tax on distributed income. Computes net income and the allocation among partners /
    beneficiaries by the percentages entered. Beneficiary tax depends on their own circumstances and is NOT computed here.
    Inputs: assessable_income, deductions_other, net_capital_gain, allocations:[{name, percent}]"""
    steps, warnings = [], []
    net = D(i.get("assessable_income")) + D(i.get("net_capital_gain")) - D(i.get("deductions_other"))     # may be negative: a partnership / trust loss
    steps.append(step("net_income", "Net income / (partnership or trust loss)", net, "calculated"))
    allocs = i.get("allocations") or []
    total_pct = sum((D(a.get("percent")) for a in allocs), ZERO)
    rows, undistributed = [], ZERO
    for a in allocs:
        share = q2(net * D(a.get("percent")) / Decimal(100))
        rows.append(dict(name=a.get("name", ""), percent=str(D(a.get("percent"))), amount=str(share)))
    if allocs and total_pct != Decimal(100):
        warnings.append(step("alloc_total", "Allocation", None, "warning", f"Allocations total {total_pct}% - they must total 100% (any shortfall is undistributed income)."))
    if not allocs:
        warnings.append(step("no_alloc", "Allocation", None, "warning", "No partner/beneficiary allocations entered."))
    if kind == "trust":
        undistributed = q2(net * (Decimal(100) - total_pct) / Decimal(100)) if net > 0 and total_pct < 100 else ZERO
        warnings.append(step("trust_review", "Trust distributions", None, "review", "Trustee resolutions by 30 June, present entitlement, section 100A and the trustee beneficiary reporting rules are NOT assessed. Undistributed income can be taxed to the trustee at the top rate: tax agent review."))
    else:
        warnings.append(step("partnership_review", "Partnership", None, "review", "Partner interests, salary/interest agreements and partner-level concessions are not assessed."))
    return dict(entity=kind, fy=fy, taxable_income=str(q2(net)), income_tax="0.00", offsets="0.00", medicare_levy="0.00", tax_assessed="0.00", credits="0.00", balance="0.00",
                allocations=rows, undistributed=str(undistributed), steps=steps, warnings=warnings, rule_set=rs.id)


def compute_return(rs: TaxRuleSet, fy: str, entity_type: str, inputs: dict) -> dict:
    et = (entity_type or "").lower()
    if et in ("individual", "sole_trader"):
        return compute_individual(rs, fy, inputs)
    if et in ("company", "smsf"):
        return compute_company(rs, fy, dict(inputs, entity_kind="smsf" if et == "smsf" else "company"))
    if et in ("partnership", "trust"):
        return compute_flow_through(rs, fy, inputs, et)
    raise ValueError(f"Unsupported entity type '{entity_type}' (individual, sole_trader, company, partnership, trust, smsf)")
