"""
Australian PAYG Tax Tables and Payroll Calculation Engine.
Based on ATO 2023-24 tax withholding tables.
Structured for easy updates each financial year.
"""
from dataclasses import dataclass
from typing import Optional
import math


# ── PAYG Weekly Earnings Brackets (ATO 2023-24) ──────────────────────────────
# Based on ATO NAT 3539 (Tax withheld calculator) 2023-24
# Scale 1: Residents WITH tax-free threshold
# Formula: tax = round(a × weekly_earnings − b)
# (weekly_earnings_up_to, coefficient_a, coefficient_b)
RESIDENT_TFT_WEEKLY = [
    (88,     0.1900,  0.19),
    (371,    0.2348, 3.80),
    (515,    0.2190, -2.10),
    (865,    0.3477, 63.97),
    (1282,   0.3450, 61.30),
    (1538,   0.3900, 119.10),
    (2307,   0.4150, 157.60),
    (3461,   0.4700, 284.25),
    (9999999, 0.5700, 630.10),
]

# Scale 2: Residents WITHOUT tax-free threshold
RESIDENT_NO_TFT_WEEKLY = [
    (359,    0.1900,  0.19),
    (721,    0.3477, 56.24),
    (865,    0.3450, 54.31),
    (1282,   0.3900, 93.22),
    (1538,   0.4150, 125.22),
    (2307,   0.4700, 209.91),
    (9999999, 0.5700, 550.08),
]

SUPER_GUARANTEE_RATE = 0.11  # 11% from 1 July 2023
MEDICARE_LEVY_RATE = 0.02    # 2% standard
MEDICARE_LEVY_THRESHOLD_ANNUAL = 26000  # below this, no Medicare


@dataclass
class PayrollInput:
    employee_id: str
    employee_number: str
    first_name: str
    last_name: str
    annual_salary: float
    employment_type: str
    pay_frequency: str  # weekly, fortnightly, monthly
    ordinary_hours: float
    overtime_hours_1_5x: float = 0.0
    overtime_hours_2x: float = 0.0
    public_holiday_hours: float = 0.0
    annual_leave_hours: float = 0.0
    sick_leave_hours: float = 0.0
    long_service_leave_hours: float = 0.0
    hourly_rate: Optional[float] = None
    tax_free_threshold: bool = True
    residency_status: str = "resident"
    super_fund_name: str = "AustralianSuper"
    super_member_number: Optional[str] = None
    ytd_gross: float = 0.0      # year-to-date gross (for annual checks)
    ytd_tax: float = 0.0
    ytd_super: float = 0.0
    period_start: str = ""
    period_end: str = ""


@dataclass
class PayrollResult:
    employee_id: str
    employee_number: str
    full_name: str
    period_start: str
    period_end: str
    pay_frequency: str

    # Hours
    ordinary_hours: float
    overtime_hours_1_5x: float
    overtime_hours_2x: float
    public_holiday_hours: float
    annual_leave_hours: float
    sick_leave_hours: float
    long_service_leave_hours: float

    # Earnings
    ordinary_pay: float
    overtime_pay_1_5x: float
    overtime_pay_2x: float
    public_holiday_pay: float
    annual_leave_pay: float
    sick_leave_pay: float
    long_service_leave_pay: float
    gross_earnings: float

    # Deductions
    payg_tax: float
    medicare_levy: float
    total_tax: float

    # Net
    net_pay: float

    # Super
    super_guarantee: float
    super_fund_name: str
    super_member_number: Optional[str]

    # YTD
    ytd_gross: float
    ytd_tax: float
    ytd_super: float

    # Rates
    hourly_rate: float
    annual_salary: float


def get_hourly_rate(annual_salary: float, employment_type: str) -> float:
    """Calculate hourly rate. Standard full-time = 38hrs/week."""
    standard_hours_per_year = 52 * 38
    return annual_salary / standard_hours_per_year


def get_periods_per_year(pay_frequency: str) -> int:
    return {"weekly": 52, "fortnightly": 26, "monthly": 12}.get(pay_frequency, 26)


def annualise_earnings(period_gross: float, pay_frequency: str) -> float:
    """Convert period earnings to annual for tax calculation."""
    return period_gross * get_periods_per_year(pay_frequency)


def calculate_payg_weekly(weekly_earnings: float, tax_free_threshold: bool,
                           residency_status: str = "resident") -> float:
    """
    Calculate PAYG withholding using ATO formula method.
    Tax = (a × weekly_earnings) - b
    """
    table = RESIDENT_TFT_WEEKLY if tax_free_threshold else RESIDENT_NO_TFT_WEEKLY

    # Non-residents pay more tax (no tax-free threshold, different scale)
    if residency_status == "non_resident":
        # Simplified non-resident: 32.5c from $0 to $120k, 37c above
        if weekly_earnings <= 2307:
            return max(0, weekly_earnings * 0.3250)
        else:
            return max(0, weekly_earnings * 0.3700)

    for ceiling, a, b in table:
        if weekly_earnings <= ceiling:
            raw = (a * weekly_earnings) - b
            return max(0, round(raw))

    # Fallback: top rate
    return max(0, round(weekly_earnings * 0.57 - 535.45))


def calculate_medicare_levy(annual_gross: float) -> float:
    """Calculate Medicare levy (2%). Phase-in applies below threshold."""
    if annual_gross <= MEDICARE_LEVY_THRESHOLD_ANNUAL:
        return 0.0
    # Simplified: full 2% above threshold (phase-in omitted for clarity)
    return annual_gross * MEDICARE_LEVY_RATE


def calculate_payroll(inp: PayrollInput) -> PayrollResult:
    """Main payroll calculation engine."""

    # ── 1. Determine hourly rate ──────────────────────────────────────────
    hourly_rate = inp.hourly_rate or get_hourly_rate(inp.annual_salary, inp.employment_type)

    # ── 2. Calculate earnings per component ──────────────────────────────
    ordinary_pay = inp.ordinary_hours * hourly_rate
    ot_1_5 = inp.overtime_hours_1_5x * hourly_rate * 1.5
    ot_2x = inp.overtime_hours_2x * hourly_rate * 2.0
    ph_pay = inp.public_holiday_hours * hourly_rate * 2.25  # typical AU award loading
    al_pay = inp.annual_leave_hours * hourly_rate           # leave at ordinary rate
    sl_pay = inp.sick_leave_hours * hourly_rate
    lsl_pay = inp.long_service_leave_hours * hourly_rate

    gross_earnings = ordinary_pay + ot_1_5 + ot_2x + ph_pay + al_pay + sl_pay + lsl_pay

    # ── 3. PAYG tax calculation ───────────────────────────────────────────
    # Convert period gross to weekly equivalent for ATO formula
    periods_per_year = get_periods_per_year(inp.pay_frequency)
    weekly_equivalent = (gross_earnings * periods_per_year) / 52

    weekly_tax = calculate_payg_weekly(weekly_equivalent, inp.tax_free_threshold, inp.residency_status)

    # Convert weekly tax back to period
    period_tax = (weekly_tax * 52) / periods_per_year

    # ── 4. Medicare levy ─────────────────────────────────────────────────
    annual_gross = gross_earnings * periods_per_year
    annual_medicare = calculate_medicare_levy(annual_gross)
    period_medicare = annual_medicare / periods_per_year

    total_tax = period_tax  # Medicare included in PAYG for simplicity at this level

    # ── 5. Net pay ───────────────────────────────────────────────────────
    net_pay = gross_earnings - total_tax

    # ── 6. Superannuation guarantee ──────────────────────────────────────
    # Super is on Ordinary Time Earnings (OTE) - excludes overtime
    ote = ordinary_pay + al_pay + sl_pay + lsl_pay + ph_pay
    super_guarantee = ote * SUPER_GUARANTEE_RATE

    # ── 7. YTD accumulators ──────────────────────────────────────────────
    ytd_gross = inp.ytd_gross + gross_earnings
    ytd_tax = inp.ytd_tax + total_tax
    ytd_super = inp.ytd_super + super_guarantee

    return PayrollResult(
        employee_id=inp.employee_id,
        employee_number=inp.employee_number,
        full_name=f"{inp.first_name} {inp.last_name}",
        period_start=inp.period_start,
        period_end=inp.period_end,
        pay_frequency=inp.pay_frequency,
        ordinary_hours=inp.ordinary_hours,
        overtime_hours_1_5x=inp.overtime_hours_1_5x,
        overtime_hours_2x=inp.overtime_hours_2x,
        public_holiday_hours=inp.public_holiday_hours,
        annual_leave_hours=inp.annual_leave_hours,
        sick_leave_hours=inp.sick_leave_hours,
        long_service_leave_hours=inp.long_service_leave_hours,
        ordinary_pay=round(ordinary_pay, 2),
        overtime_pay_1_5x=round(ot_1_5, 2),
        overtime_pay_2x=round(ot_2x, 2),
        public_holiday_pay=round(ph_pay, 2),
        annual_leave_pay=round(al_pay, 2),
        sick_leave_pay=round(sl_pay, 2),
        long_service_leave_pay=round(lsl_pay, 2),
        gross_earnings=round(gross_earnings, 2),
        payg_tax=round(period_tax, 2),
        medicare_levy=round(period_medicare, 2),
        total_tax=round(total_tax, 2),
        net_pay=round(net_pay, 2),
        super_guarantee=round(super_guarantee, 2),
        super_fund_name=inp.super_fund_name,
        super_member_number=inp.super_member_number,
        ytd_gross=round(ytd_gross, 2),
        ytd_tax=round(ytd_tax, 2),
        ytd_super=round(ytd_super, 2),
        hourly_rate=round(hourly_rate, 4),
        annual_salary=inp.annual_salary,
    )
