"""
Smart Lending — Australian Responsible Lending Metrics
Computes all statistics used by Australian banks and lenders per:
- National Consumer Credit Protection Act 2009 (NCCP)
- ASIC RG 209 Responsible Lending
- APRA Prudential Standards (APS 220, APG 223)
- HEM (Household Expenditure Measure) — Melbourne Institute
- UMI (Uncommitted Monthly Income / Net Surplus)
- DSR (Debt Service Ratio)
- NDI (Net Disposable Income)
- LVR / LTI indicators
"""
from typing import Dict, List, Optional
from dataclasses import dataclass, field

# ── HEM 2024 Benchmarks (Melbourne Institute, quarterly) ──────────────────────
# Values are monthly AUD for an individual (single adult, no children)
# Source: RMIT / Melbourne Institute HEM December 2023 Release
HEM_BENCHMARKS = {
    "single_no_children": {
        "food_groceries":           800,
        "clothing_personal":        120,
        "recreation_entertainment": 150,
        "transport":                350,
        "health_medical":           90,
        "utilities":                180,   # electricity, gas, water
        "subscriptions":            60,
        "personal_care":            50,
    },
    "couple_no_children": {
        "food_groceries":           1200,
        "clothing_personal":        200,
        "recreation_entertainment": 250,
        "transport":                500,
        "health_medical":           150,
        "utilities":                250,
        "subscriptions":            80,
        "personal_care":            80,
    },
    "couple_1_child": {
        "food_groceries":           1500,
        "clothing_personal":        280,
        "recreation_entertainment": 320,
        "transport":                560,
        "health_medical":           200,
        "utilities":                300,
        "subscriptions":            100,
        "personal_care":            100,
        "childcare_education":      600,
    },
    "couple_2_children": {
        "food_groceries":           1700,
        "clothing_personal":        350,
        "recreation_entertainment": 400,
        "transport":                620,
        "health_medical":           250,
        "utilities":                340,
        "subscriptions":            120,
        "personal_care":            120,
        "childcare_education":      1100,
    },
}

# ── Regulatory thresholds ─────────────────────────────────────────────────────
DTI_LIMIT               = 0.43     # ASIC guidance: 43% debt-to-income limit
HOUSEHOLD_EXPENSE_LIMIT = 0.30     # 30% of income on household expenses
DISCRETIONARY_WARNING   = 0.20     # Flag if >20% of income on discretionary
SERVICEABILITY_BUFFER   = 0.03     # APRA 3% interest rate buffer on new loans
MIN_UMI_MONTHLY         = 200      # Minimum Uncommitted Monthly Income ($)
MAX_LTI                 = 6.0      # Max loan-to-income ratio (APRA guidance)
GAMBLING_THRESHOLD      = 0.05     # Flag if >5% of income on gambling


@dataclass
class LendingMetrics:
    """All computed lending statistics."""
    # Income
    total_income_monthly:       float = 0.0
    regular_income_monthly:     float = 0.0
    irregular_income_monthly:   float = 0.0
    government_payments_monthly:float = 0.0

    # Expenses — mandatory
    housing_monthly:            float = 0.0   # rent or mortgage
    food_monthly:               float = 0.0
    utilities_monthly:          float = 0.0
    transport_monthly:          float = 0.0
    health_monthly:             float = 0.0
    insurance_monthly:          float = 0.0
    childcare_education_monthly:float = 0.0
    loans_monthly:              float = 0.0   # existing loan repayments
    credit_card_monthly:        float = 0.0

    # Expenses — discretionary
    recreation_monthly:         float = 0.0
    clothing_monthly:           float = 0.0
    travel_monthly:             float = 0.0
    gambling_monthly:           float = 0.0
    subscriptions_monthly:      float = 0.0
    other_discretionary_monthly:float = 0.0

    # Computed totals
    total_mandatory_monthly:    float = 0.0
    total_discretionary_monthly:float = 0.0
    total_expenses_monthly:     float = 0.0

    # Lending statistics
    ndi:                        float = 0.0   # Net Disposable Income
    umi:                        float = 0.0   # Uncommitted Monthly Income
    dsr:                        float = 0.0   # Debt Service Ratio (%)
    household_expense_ratio:    float = 0.0   # Household Expenses / Income (%)
    discretionary_ratio:        float = 0.0   # Discretionary / Income (%)
    gambling_ratio:             float = 0.0   # Gambling / Income (%)

    # Proposed loan assessment
    proposed_repayment_monthly: float = 0.0
    assessment_rate:            float = 0.0   # Interest rate + 3% buffer
    serviced_umi:               float = 0.0   # UMI after proposed repayment
    max_borrowing_capacity:     float = 0.0   # Estimated maximum loan
    lti:                        float = 0.0   # Loan-to-Income ratio

    # HEM comparison
    hem_benchmark_monthly:      float = 0.0
    actual_vs_hem:              float = 0.0   # % above/below HEM

    # Risk flags
    flags:                      list = field(default_factory=list)
    risk_score:                 int  = 0      # 0-100: higher = more risk
    risk_category:              str  = "Low"  # Low / Medium / High / Very High

    # Statement metadata
    months_analysed:            int  = 3
    classification_rate:        float = 0.0  # % of transactions classified
    total_transactions:         int  = 0


def compute_metrics(
    classified_transactions: List[Dict],
    proposed_loan_amount:    float = 0,
    proposed_interest_rate:  float = 0.065,  # 6.5% default
    proposed_term_years:     int   = 30,
    household_type:          str   = "single_no_children",
    analysis_months:         int   = 3,
) -> LendingMetrics:
    """
    Compute all lending metrics from classified transactions.
    """
    m = LendingMetrics()
    m.months_analysed = analysis_months

    if not classified_transactions:
        return m

    # ── Aggregate by HEM group (using Saar categories and M/D flags) ─────────
    group_totals: Dict[str, float] = {}
    income_total   = 0.0
    regular_income = 0.0   # M income (salary/wages)
    oneoff_income  = 0.0   # D income (one-off)
    classified     = 0

    for txn in classified_transactions:
        grp      = txn.get("hem_group", "other")
        cat      = txn.get("category", "Others")
        exp_type = txn.get("exp_type", "D")    # M or D — from Saar classifier
        amt      = abs(float(txn.get("amount") or 0))
        is_income= txn.get("is_income", False)

        if cat and cat not in ("Others", "Other"):
            classified += 1

        if is_income:
            income_total += amt
            if exp_type == "M":
                regular_income += amt
            else:
                oneoff_income += amt
        else:
            group_totals[grp] = group_totals.get(grp, 0) + amt

    m.total_transactions   = len(classified_transactions)
    m.classification_rate  = classified / max(len(classified_transactions), 1)

    # Monthly averages
    div = max(analysis_months, 1)

    m.total_income_monthly       = income_total / div
    m.regular_income_monthly     = regular_income / div
    m.irregular_income_monthly   = oneoff_income / div
    m.housing_monthly            = group_totals.get("housing", 0) / div
    m.food_monthly               = group_totals.get("food_groceries", 0) / div
    m.utilities_monthly          = group_totals.get("utilities", 0) / div
    m.transport_monthly          = group_totals.get("transport", 0) / div
    m.health_monthly             = group_totals.get("health_medical", 0) / div
    m.insurance_monthly          = group_totals.get("insurance", 0) / div
    m.childcare_education_monthly= group_totals.get("childcare_education", 0) / div
    m.loans_monthly              = group_totals.get("loans_debt", 0) / div
    m.credit_card_monthly        = group_totals.get("credit_card", 0) / div
    m.recreation_monthly         = group_totals.get("recreation_entertainment", 0) / div
    m.clothing_monthly           = group_totals.get("clothing_personal", 0) / div
    m.travel_monthly             = group_totals.get("travel", 0) / div
    m.gambling_monthly           = group_totals.get("gambling", 0) / div
    m.subscriptions_monthly      = group_totals.get("subscriptions", 0) / div
    m.other_discretionary_monthly= (group_totals.get("other", 0) +
                                    group_totals.get("services", 0) +
                                    group_totals.get("goods_household", 0)) / div

    # ── Totals ────────────────────────────────────────────────────────────────
    m.total_mandatory_monthly = (
        m.housing_monthly + m.food_monthly + m.utilities_monthly +
        m.transport_monthly + m.health_monthly + m.insurance_monthly +
        m.childcare_education_monthly + m.loans_monthly + m.credit_card_monthly
    )
    m.total_discretionary_monthly = (
        m.recreation_monthly + m.clothing_monthly + m.travel_monthly +
        m.gambling_monthly + m.subscriptions_monthly + m.other_discretionary_monthly
    )
    m.total_expenses_monthly = m.total_mandatory_monthly + m.total_discretionary_monthly

    income = m.total_income_monthly
    if income <= 0:
        # Estimate income from net balance if not found
        income = m.total_expenses_monthly * 1.2

    # ── Key lending ratios ────────────────────────────────────────────────────
    m.ndi = income - m.total_expenses_monthly
    m.umi = m.ndi  # Base UMI before proposed loan

    m.dsr = (m.loans_monthly / income * 100) if income > 0 else 0
    m.household_expense_ratio = (m.total_mandatory_monthly / income * 100) if income > 0 else 0
    m.discretionary_ratio = (m.total_discretionary_monthly / income * 100) if income > 0 else 0
    m.gambling_ratio = (m.gambling_monthly / income * 100) if income > 0 else 0

    # ── HEM benchmark comparison ──────────────────────────────────────────────
    hem = HEM_BENCHMARKS.get(household_type, HEM_BENCHMARKS["single_no_children"])
    m.hem_benchmark_monthly = sum(hem.values())
    m.actual_vs_hem = ((m.total_expenses_monthly - m.hem_benchmark_monthly) /
                       m.hem_benchmark_monthly * 100) if m.hem_benchmark_monthly > 0 else 0

    # ── Proposed loan assessment ──────────────────────────────────────────────
    if proposed_loan_amount > 0 and income > 0:
        m.assessment_rate = proposed_interest_rate + SERVICEABILITY_BUFFER
        # Monthly repayment using annuity formula at assessment rate
        r = m.assessment_rate / 12
        n = proposed_term_years * 12
        if r > 0:
            m.proposed_repayment_monthly = proposed_loan_amount * r * (1+r)**n / ((1+r)**n - 1)
        else:
            m.proposed_repayment_monthly = proposed_loan_amount / n
        m.serviced_umi = m.umi - m.proposed_repayment_monthly
        m.lti = proposed_loan_amount / (income * 12)

    # ── Maximum borrowing capacity ────────────────────────────────────────────
    # Using assessment rate, max monthly repayment = UMI - MIN_UMI
    max_repayment = max(0, m.umi - MIN_UMI_MONTHLY)
    if max_repayment > 0:
        r = (proposed_interest_rate + SERVICEABILITY_BUFFER) / 12
        n = proposed_term_years * 12
        if r > 0:
            m.max_borrowing_capacity = max_repayment * ((1+r)**n - 1) / (r * (1+r)**n)
        else:
            m.max_borrowing_capacity = max_repayment * n

    # ── Risk flags (ASIC RG 209 / APRA) ──────────────────────────────────────
    flags = []

    if m.dsr > DTI_LIMIT * 100:
        flags.append(f"⚠️ Debt Service Ratio {m.dsr:.1f}% exceeds ASIC 43% limit")

    if m.household_expense_ratio > HOUSEHOLD_EXPENSE_LIMIT * 100:
        flags.append(f"⚠️ Household expenses {m.household_expense_ratio:.1f}% of income (>30% threshold)")

    if m.gambling_ratio > GAMBLING_THRESHOLD * 100:
        flags.append(f"🚨 Gambling spend {m.gambling_ratio:.1f}% of income — responsible lending flag")

    if m.umi < MIN_UMI_MONTHLY:
        flags.append(f"⚠️ UMI ${m.umi:.0f}/mo below minimum threshold (${MIN_UMI_MONTHLY})")

    if m.lti > MAX_LTI:
        flags.append(f"⚠️ Loan-to-Income ratio {m.lti:.1f}x exceeds APRA guideline of {MAX_LTI}x")

    if m.serviced_umi < 0:
        flags.append("🚨 UMI goes negative after proposed repayment — serviceability fails")

    if m.actual_vs_hem > 30:
        flags.append(f"ℹ️ Expenses {m.actual_vs_hem:.0f}% above HEM benchmark — review lifestyle costs")

    if m.loans_monthly > 0 and m.total_income_monthly > 0:
        existing_dsr = m.loans_monthly / m.total_income_monthly * 100
        if existing_dsr > 25:
            flags.append(f"⚠️ Existing debt repayments consume {existing_dsr:.1f}% of income")

    m.flags = flags

    # ── Risk score (0-100) ────────────────────────────────────────────────────
    score = 0
    if m.dsr > 43:          score += 25
    elif m.dsr > 30:        score += 15
    elif m.dsr > 20:        score += 8

    if m.gambling_ratio > 5:    score += 20
    elif m.gambling_ratio > 2:  score += 10

    if m.umi < 0:           score += 30
    elif m.umi < 200:       score += 20
    elif m.umi < 500:       score += 10

    if m.household_expense_ratio > 50:  score += 15
    elif m.household_expense_ratio > 35: score += 8

    if m.lti > 6:           score += 15
    elif m.lti > 4:         score += 8

    if m.actual_vs_hem > 50:    score += 10
    elif m.actual_vs_hem > 20:  score += 5

    m.risk_score = min(100, score)

    if m.risk_score < 25:      m.risk_category = "Low"
    elif m.risk_score < 50:    m.risk_category = "Medium"
    elif m.risk_score < 75:    m.risk_category = "High"
    else:                       m.risk_category = "Very High"

    return m


def metrics_to_dict(m: LendingMetrics) -> Dict:
    """Convert LendingMetrics dataclass to JSON-serialisable dict."""
    return {
        "income": {
            "total_monthly":         round(m.total_income_monthly, 2),
            "regular_monthly":       round(m.regular_income_monthly, 2),
        },
        "expenses": {
            "housing":               round(m.housing_monthly, 2),
            "food_groceries":        round(m.food_monthly, 2),
            "utilities":             round(m.utilities_monthly, 2),
            "transport":             round(m.transport_monthly, 2),
            "health_medical":        round(m.health_monthly, 2),
            "insurance":             round(m.insurance_monthly, 2),
            "childcare_education":   round(m.childcare_education_monthly, 2),
            "loans_debt":            round(m.loans_monthly, 2),
            "recreation":            round(m.recreation_monthly, 2),
            "clothing":              round(m.clothing_monthly, 2),
            "travel":                round(m.travel_monthly, 2),
            "gambling":              round(m.gambling_monthly, 2),
            "subscriptions":         round(m.subscriptions_monthly, 2),
            "other":                 round(m.other_discretionary_monthly, 2),
            "total_mandatory":       round(m.total_mandatory_monthly, 2),
            "total_discretionary":   round(m.total_discretionary_monthly, 2),
            "total":                 round(m.total_expenses_monthly, 2),
        },
        "lending_metrics": {
            "ndi":                   round(m.ndi, 2),
            "umi":                   round(m.umi, 2),
            "dsr":                   round(m.dsr, 2),
            "household_expense_ratio": round(m.household_expense_ratio, 2),
            "discretionary_ratio":   round(m.discretionary_ratio, 2),
            "gambling_ratio":        round(m.gambling_ratio, 2),
            "hem_benchmark":         round(m.hem_benchmark_monthly, 2),
            "actual_vs_hem_pct":     round(m.actual_vs_hem, 2),
        },
        "loan_assessment": {
            "proposed_repayment":    round(m.proposed_repayment_monthly, 2),
            "assessment_rate_pct":   round(m.assessment_rate * 100, 3),
            "serviced_umi":          round(m.serviced_umi, 2),
            "max_borrowing_capacity":round(m.max_borrowing_capacity, 2),
            "lti":                   round(m.lti, 3),
        },
        "risk": {
            "score":                 m.risk_score,
            "category":              m.risk_category,
            "flags":                 m.flags,
        },
        "metadata": {
            "months_analysed":       m.months_analysed,
            "classification_rate_pct": round(m.classification_rate * 100, 1),
            "total_transactions":    m.total_transactions,
        },
    }
