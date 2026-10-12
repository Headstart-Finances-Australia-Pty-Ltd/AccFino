"""Explainable credit assessment: Score -> Risk grade -> Key factors -> Recommendation. A pure function; no model, no hidden weights.

Nine factors with FIXED maximum points that add up to 100 (higher = lower risk). Each factor reports its value, its points and a plain-English sentence. Data-quality adjustments are listed as adjustments, never hidden.
The recommendation is a RECOMMENDATION: a person approves, declines or overrides it (that is recorded elsewhere, with the reason)."""
from typing import Dict, List, Optional

from accfino.modules.lending.engine import amort as A

POLICY = dict(
    dti_limit=0.43, serviceability_buffer=0.03, min_umi=200.0, max_lti=6.0, gambling_threshold=0.05, lvr_cap=0.80, min_months=3, min_classification=0.85, min_recurring_share=0.5,
    required_documents=("photo_id", "income_evidence"), grades=((80, "A", "Very low risk"), (65, "B", "Low risk"), (50, "C", "Moderate risk"), (35, "D", "High risk"), (0, "E", "Very high risk")),
)
MAX_POINTS = dict(serviceability=30, debt_service=15, expenses_vs_hem=10, income_stability=7, employment=3, surplus_buffer=5, conduct=10, loan_size=10, security=10)
LABELS = dict(serviceability="Can afford the repayment (at the assessment rate)", debt_service="Total debt repayments against income", expenses_vs_hem="Living expenses against the HEM benchmark", income_stability="Regular income",
              employment="Time in current employment", surplus_buffer="Surplus today", conduct="Account conduct", loan_size="Loan size against income", security="Security / loan to value")
assert sum(MAX_POINTS.values()) == 100


def lin(x: float, x0: float, x1: float, p0: float, p1: float) -> float:
    """Points rising (or falling) in a straight line from (x0, p0) to (x1, p1), held flat outside that range."""
    if x0 == x1:
        return p1
    f = (x - x0) / (x1 - x0)
    f = 0.0 if f < 0 else 1.0 if f > 1 else f
    return p0 + (p1 - p0) * f


def _f(v, d=0.0) -> float:
    try:
        return float(v)
    except (TypeError, ValueError):
        return d


def grade_for(score: float, grades=POLICY["grades"]):
    """(grade, band) for a score: A 80+, B 65+, C 50+, D 35+, E below."""
    return next((g_, b_) for cut, g_, b_ in grades if score >= cut)


def money(v: float) -> str:
    return f"${abs(v):,.2f}" if v >= 0 else f"-${abs(v):,.2f}"


def pv_of_payment(payment: float, annual_rate: float, periods: int) -> float:
    """The loan a monthly payment can carry."""
    r = annual_rate / 12
    if payment <= 0 or periods <= 0:
        return 0.0
    return payment * periods if r == 0 else payment * (1 - (1 + r) ** -periods) / r


def repayment(amount: float, annual_rate: float, term_months: int, io: bool = False) -> float:
    if amount <= 0 or term_months <= 0:
        return 0.0
    if io:
        return round(amount * annual_rate / 12, 2)
    return float(A.pmt(A.D(str(amount)), A.D(str(annual_rate)) / 12, term_months))


def cash_flow(m: Dict, amount: float, rate: float, term_months: int, buffer: float, io: bool = False, hem_gap: float = 0.0) -> Dict:
    """What happens to the applicant's monthly cash flow if the loan is added (Income -> Expenses -> Commitments -> Surplus)."""
    income = _f(m.get("total_income_monthly"))
    surplus_now = _f(m.get("umi")) - hem_gap
    actual = repayment(amount, rate, term_months, io)
    assessed = repayment(amount, rate + buffer, term_months, io)
    return dict(income_monthly=round(income, 2), expenses_monthly=round(_f(m.get("total_expenses_monthly")), 2), existing_commitments_monthly=round(_f(m.get("loans_monthly")) + _f(m.get("credit_card_monthly")), 2),
                surplus_before=round(surplus_now, 2), new_repayment_actual=actual, new_repayment_assessed=assessed, assessment_rate=round(rate + buffer, 6),
                surplus_after_actual=round(surplus_now - actual, 2), surplus_after_assessed=round(surplus_now - assessed, 2),
                surplus_after_assessed_pct_of_income=round((surplus_now - assessed) / income * 100, 1) if income > 0 else None)


def assess(metrics: Dict, application: Dict, profile: Optional[Dict] = None, extras: Optional[Dict] = None, policy: Optional[Dict] = None) -> Dict:
    p = dict(POLICY, **(policy or {}))
    profile, extras = profile or {}, extras or {}
    m = metrics or {}
    amount, term, rate = _f(application.get("amount")), int(_f(application.get("term_months"))), _f(application.get("rate"), 0.065)
    io = bool(application.get("interest_only"))
    sec = _f(application.get("security_value"))
    income = _f(m.get("total_income_monthly"))
    annual = income * 12
    flags: List[Dict] = [dict(severity="warning", text=str(x)) for x in (m.get("flags") or [])]
    missing: List[str] = []
    adjustments: List[Dict] = []
    factors: List[Dict] = []

    # ---- what we are missing -------------------------------------------------------------------------------------------------------------
    months = _f(m.get("months_analysed"))
    have_statements = bool(extras.get("has_analysis", True)) and _f(m.get("total_transactions")) > 0
    if not have_statements:
        missing.append("Bank statements have not been analysed")
    elif months < p["min_months"]:
        missing.append(f"Statements cover {months:g} month(s): {p['min_months']} are needed")
    cls = _f(m.get("classification_rate"))                                   # a fraction (0.92 = 92% of transactions categorised)
    cls = cls / 100 if cls > 1 else cls
    if have_statements and cls < p["min_classification"]:
        missing.append(f"Only {cls * 100:.0f}% of transactions could be categorised ({p['min_classification'] * 100:.0f}% needed): review the uncategorised ones")
    if amount <= 0 or term <= 0:
        missing.append("The loan amount and term are required")
    received = set(extras.get("documents_received") or [])
    needed = list(p["required_documents"]) + (["security_valuation"] if (application.get("security") or sec > 0) else [])
    for d in needed:
        if d not in received:
            missing.append({"photo_id": "Photo identification", "income_evidence": "Evidence of income (payslips, tax return or BAS)", "security_valuation": "A valuation of the security"}.get(d, d.replace("_", " ").capitalize()) + " has not been received")
    if application.get("security") and sec <= 0:
        missing.append("The value of the security has not been entered")
    for k, lab in (("employment_type", "Employment type"), ("employment_months", "Time in current employment")):
        if profile.get(k) in (None, ""):
            missing.append(f"{lab} has not been entered")

    # ---- the cash flow with the loan added -------------------------------------------------------------------------------------------------
    hem = _f(m.get("hem_benchmark_monthly"))
    # HEM measures LIVING costs and excludes debt, so the applicant's living costs are their total spending less loan and card repayments.
    living = max(0.0, _f(m.get("total_expenses_monthly")) - _f(m.get("loans_monthly")) - _f(m.get("credit_card_monthly")))
    vs = (living - hem) / hem * 100 if hem > 0 else 0.0
    hem_gap = max(0.0, hem - living) if hem > 0 else 0.0                     # lenders assess at the HIGHER of the applicant's own spending and the HEM benchmark
    cf = cash_flow(m, amount, rate, term, p["serviceability_buffer"], io, hem_gap)
    surplus_after = cf["surplus_after_assessed"]
    margin = surplus_after / income if income > 0 else -1.0

    def add(key, value, points, detail):
        factors.append(dict(key=key, label=LABELS[key], value=value, points=round(max(0.0, min(points, MAX_POINTS[key])), 1), max=MAX_POINTS[key], detail=detail))

    # 1 serviceability
    pts = lin(margin, 0.0, 0.20, 0.0, 30.0) if surplus_after > 0 else 0.0
    if 0 < surplus_after < p["min_umi"]:
        pts = min(pts, 8.0)
    add("serviceability", round(surplus_after, 2), pts, f"After the new repayment of {money(cf['new_repayment_assessed'])} a month (assessed at {cf['assessment_rate'] * 100:.2f}%, the loan rate plus the {p['serviceability_buffer'] * 100:.0f}% buffer) the applicant has {money(surplus_after)} a month left" +
        (f" ({margin * 100:.0f}% of income)." if income > 0 else ".") + (f" Their spending is {money(hem_gap)} a month below the HEM benchmark, so the benchmark was used." if hem_gap > 0 else ""))
    # 2 debt service
    commit = _f(m.get("loans_monthly")) + _f(m.get("credit_card_monthly")) + cf["new_repayment_assessed"]
    dsr = commit / income if income > 0 else 1.0
    add("debt_service", round(dsr * 100, 1), lin(dsr, 0.25, p["dti_limit"], 15.0, 0.0), f"Existing loan and card repayments plus the new repayment are {dsr * 100:.0f}% of income (guide limit {p['dti_limit'] * 100:.0f}%).")
    if dsr > p["dti_limit"]:
        flags.append(dict(severity="high", text=f"Debt repayments would be {dsr * 100:.0f}% of income, above the {p['dti_limit'] * 100:.0f}% guide"))
    # 3 expenses against HEM
    if hem > 0:
        add("expenses_vs_hem", round(vs, 1), 10.0 if vs >= -10 else lin(vs, -40, -10, 3.0, 10.0), f"Living expenses are {vs:+.0f}% against the HEM benchmark of {money(hem)} a month" + ("." if vs >= -10 else ": that looks understated, so the benchmark is used in the affordability test."))
        if vs < -10:
            flags.append(dict(severity="warning", text=f"Declared living expenses are {abs(vs):.0f}% below the HEM benchmark"))
    else:
        add("expenses_vs_hem", None, 5.0, "No HEM benchmark was available for this household, so this factor is neutral.")
    # 4 income stability
    tot = income
    if extras.get("recurring_income_monthly") is not None:
        reg, how = min(_f(extras.get("recurring_income_monthly")), tot), "recurs every pay cycle"      # evidenced by the statements, not just labelled regular by the classifier
    else:
        reg, how = _f(m.get("regular_income_monthly")), "is regular (salary or wages)"
    share = reg / tot if tot > 0 else 0.0
    add("income_stability", round(share * 100, 0), lin(share, 0.5, 0.9, 2.0, 7.0) if tot > 0 else 0.0, f"{share * 100:.0f}% of income {how}." if tot > 0 else "No income was found in the statements.")
    irregular = tot > 0 and share < p["min_recurring_share"]                                       # most of the income cannot be shown to recur (self-employed, commission, casual, gifts, one-offs)
    if tot > 0 and share < 0.7:
        flags.append(dict(severity="warning", text=f"Only {share * 100:.0f}% of the income can be shown to recur: assess on the recurring part"))
    # 5 employment
    em = profile.get("employment_months")
    add("employment", em, 0.0 if em in (None, "") else (3.0 if _f(em) >= 24 else 2.0 if _f(em) >= 12 else 1.0 if _f(em) >= 6 else 0.0), "Employment time was not entered." if em in (None, "") else f"{_f(em):g} months in the current employment.")
    # 6 surplus today
    sp = _f(m.get("umi")) / income if income > 0 else 0.0
    add("surplus_buffer", round(sp * 100, 0), lin(sp, 0.0, 0.20, 0.0, 5.0), f"Before the new loan the applicant keeps {sp * 100:.0f}% of income as a surplus.")
    # 7 conduct
    g = _f(m.get("gambling_ratio")) / 100                                    # the metrics engine reports this in PERCENT (5.0 means 5% of income)
    gp = 5.0 if g <= 0 else lin(g, 0.0, p["gambling_threshold"], 5.0, 0.0)
    dis = int(_f(extras.get("dishonours")))                                  # dishonoured payments and overdrawn events counted from the statements
    dp = 5.0 if dis == 0 else 3.0 if dis <= 2 else 0.0
    add("conduct", dict(gambling_pct=round(g * 100, 1), dishonours=dis), gp + dp, f"Gambling is {g * 100:.1f}% of income and there were {dis} dishonour or overdrawn event(s).")
    if g > p["gambling_threshold"]:
        flags.append(dict(severity="high", text=f"Gambling is {g * 100:.1f}% of income (guide limit {p['gambling_threshold'] * 100:.0f}%)"))
    if dis:
        flags.append(dict(severity="warning" if dis <= 2 else "high", text=f"{dis} dishonour or overdrawn event(s) in the statements"))
    # 8 loan size against income
    lti = amount / annual if annual > 0 else 99.0
    add("loan_size", round(lti, 2), lin(lti, 4.0, p["max_lti"], 10.0, 0.0), f"The loan is {lti:.1f} times annual income (guide limit {p['max_lti']:g}).")
    if lti > p["max_lti"]:
        flags.append(dict(severity="high", text=f"The loan is {lti:.1f} times income, above the {p['max_lti']:g} guide"))
    # 9 security
    lvr = amount / sec if sec > 0 else None
    if lvr is None:
        add("security", None, 5.0, "Unsecured: there is no collateral to fall back on, so this factor is neutral.")
    else:
        add("security", round(lvr * 100, 1), 10.0 if lvr <= 0.60 else lin(lvr, 0.60, 0.80, 10.0, 6.0) if lvr <= 0.80 else lin(lvr, 0.80, 0.95, 6.0, 0.0), f"The loan is {lvr * 100:.0f}% of the security's value (policy limit {p['lvr_cap'] * 100:.0f}%).")
        if lvr > p["lvr_cap"]:
            flags.append(dict(severity="high", text=f"Loan to value is {lvr * 100:.0f}%, above the {p['lvr_cap'] * 100:.0f}% policy limit"))
    base = round(sum(f["points"] for f in factors), 1)

    # ---- data-quality adjustments (shown, never hidden) ----------------------------------------------------------------------------------
    score = base
    if have_statements and cls < p["min_classification"]:
        score -= 5.0
        adjustments.append(dict(label="Under-categorised transactions", points=-5.0, detail="Fewer transactions were categorised than the policy needs, so the figures are less reliable."))
    if int(_f(extras.get("unusual_count"))) >= 3:
        flags.append(dict(severity="warning", text=f"{int(_f(extras.get('unusual_count')))} unusual transactions need explaining"))
    score = round(max(0.0, min(100.0, score)), 1)
    grade, band = grade_for(score, p["grades"])
    capped = False
    if (not have_statements or months < p["min_months"]) and grade in ("A", "B"):
        grade, band, capped = "C", "Moderate risk", True
        adjustments.append(dict(label="Fewer than the required months of statements", points=0.0, detail="The grade cannot be better than C until enough statements have been analysed."))
    if irregular and grade in ("A", "B"):
        grade, band, capped = "C", "Moderate risk", True
        adjustments.append(dict(label="Most of the income is irregular", points=0.0, detail=f"Less than {p['min_recurring_share'] * 100:.0f}% of the income can be shown to recur, so the grade cannot be better than C until the income is evidenced."))

    # ---- what the applicant can reasonably carry ---------------------------------------------------------------------------------------------
    pay_cap = max(0.0, _f(m.get("umi")) - hem_gap - p["min_umi"])
    by_service = pv_of_payment(pay_cap, rate + p["serviceability_buffer"], term) if term > 0 else 0.0
    caps = {"serviceability": by_service, "income multiple": p["max_lti"] * annual}
    if sec > 0:
        caps["security value"] = p["lvr_cap"] * sec
    binding = min(caps, key=caps.get)
    supportable = max(0.0, caps[binding])

    # ---- recommendation ----------------------------------------------------------------------------------------------------------------------
    reasons: List[str] = []
    conditions: List[str] = []
    hard_missing = (not have_statements) or amount <= 0 or term <= 0
    if hard_missing:
        outcome = "refer"
        reasons.append("Essential information is missing: " + "; ".join(x for x in missing[:3]) + ".")
    elif surplus_after < 0:
        outcome = "decline"
        reasons.append(f"The applicant cannot service this loan: after the repayment at the assessment rate they would be {money(abs(surplus_after))} a month short.")
        reasons.append(f"The most the numbers support is about {money(supportable // 1000 * 1000)}, limited by {binding}.")
    elif months < p["min_months"]:
        outcome = "refer"
        reasons.append(f"Only {months:g} month(s) of statements were analysed ({p['min_months']} are required).")
    elif grade in ("A", "B") and not any(f["severity"] == "high" for f in flags):
        outcome = "approve" if not missing else "approve_with_conditions"
        reasons.append(f"Grade {grade} ({band}) with {money(surplus_after)} a month left after the loan at the assessment rate.")
    elif grade == "C" or (grade in ("A", "B")):
        outcome = "approve_with_conditions" if margin >= 0.05 and not any(f["severity"] == "high" for f in flags) else "refer"
        reasons.append(f"Grade {grade} ({band})" + (" with high-severity risk flags." if any(f["severity"] == "high" for f in flags) else "."))
    elif grade == "D":
        outcome = "refer"
        reasons.append(f"Grade {grade} ({band}): refer to a credit manager.")
    else:
        outcome = "decline"
        reasons.append(f"Grade {grade} ({band}).")
    if amount > supportable + 1 and supportable > 0 and outcome in ("approve", "approve_with_conditions", "refer"):
        outcome = "approve_with_conditions" if outcome == "approve" else outcome                          # a smaller loan is the way forward in each of these cases
        conditions.append(f"Reduce the loan to about {money(supportable // 1000 * 1000)} (limited by {binding}).")
    if irregular and outcome == "approve":
        outcome = "approve_with_conditions"
    if outcome in ("approve_with_conditions", "refer"):
        if irregular:
            conditions.append("Obtain evidence that the irregular income will continue (two years of tax returns, or BAS and invoices)")
        conditions += [f"Obtain: {x}" for x in missing]
        conditions += [f"Explain: {f['text']}" for f in flags if f["severity"] == "high"]
    ranked = sorted(factors, key=lambda f: f["points"] / f["max"])
    key = dict(strengths=[dict(label=f["label"], detail=f["detail"]) for f in reversed(ranked[-3:]) if f["points"] / f["max"] >= 0.6],
               concerns=[dict(label=f["label"], detail=f["detail"]) for f in ranked[:3] if f["points"] / f["max"] < 0.6])
    return dict(score=score, base_score=base, grade=grade, band=band, grade_capped=capped, factors=factors, adjustments=adjustments, flags=flags, missing_info=missing, key_factors=key, cash_flow=cf,
                recommendation=dict(outcome=outcome, reasons=reasons, conditions=conditions, supportable_amount=round(supportable, 2), supportable_rounded=float(supportable // 1000 * 1000), limited_by=binding, income_evidence_needed=bool(irregular), requested=amount,
                                    shortfall_monthly=round(abs(surplus_after), 2) if surplus_after < 0 else 0.0), policy={k: p[k] for k in ("dti_limit", "serviceability_buffer", "min_umi", "max_lti", "lvr_cap", "min_months", "min_recurring_share")})
