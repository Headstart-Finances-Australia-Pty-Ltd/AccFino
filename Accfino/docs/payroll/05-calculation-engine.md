# Calculation engine

`engine/calc.py: calculate_employee(rules, employee, period, line_inputs, ytd, accrual_defs, leave_balances) -> PayResult`. Pure and deterministic: the same inputs always give the same result, byte for byte (`test_determinism`).

## Steps
1. **Validate** the employee set-up (basis, rate/salary, hours, proration).
2. **Base pay.** Salary: `annual / pay periods per year x proration`. Hourly: from timesheet lines.
3. **Lines.** Each caller-supplied line is priced by its pay item: `hours x rate` (rate = item rate, or the employee's base hourly rate x multiplier), `fixed`, `percent_of_base` or `percent_of_gross`.
   - *Leave*: pays hours at the base hourly rate; for a salaried employee a matching negative **salary adjustment** takes the same hours back out of the salary, so leave never double-pays. A 17.5% (configurable) **leave loading** line is added.
   - *Unpaid leave* (salaried): a negative line (hours x base hourly rate). Hourly staff are simply not paid for hours not worked.
4. **Totals.** Gross = all earnings. Taxable = taxable earnings - salary sacrifice - pre-tax deductions.
5. **PAYG** (`engine/payg.py`, ATO Schedule 1): scale chosen from TFN / residency / tax-free threshold / Medicare variation; weekly equivalent `x = floor($ per week) + 0.99` (fortnightly /2, monthly x3/13, with the 33-cent rule); `y = a*x - b`; rounded to the dollar with .50 rounding up; converted back to the pay period; tax offsets, an approved variation % and extra withholding applied. **Study loan** (Schedule 8) is a separate component. **Bonuses/commissions/back pay** use Schedule 5 **Method A** (apportion over the periods in the year, difference of withholdings x periods, capped at 47% of the payment, PAYG + loan combined). No TFN uses Scale 4 (no study-loan component). Unused leave on termination and ETPs follow their own treatments (see 06).
6. **Superannuation** (`engine/superannuation.py`): `SG = 12% x qualifying earnings`, limited by the **annual** maximum contribution base applied to **year-to-date** qualifying earnings. Qualifying earnings = items flagged OTE, *before* salary sacrifice; overtime and most allowances are not OTE. Salary sacrifice, extra employer contributions and employee after-tax contributions are tracked as separate components.
7. **Net** = gross - sacrifice - pre-tax deductions - PAYG - study loan - post-tax deductions - employee after-tax super + reimbursements.
8. **Employer cost** = gross + SG + extra employer super + reimbursements.
9. **YTD** (after this pay) and **leave accruals** (per ordinary hour or fixed per year, by employment type, capped by a maximum balance).
10. **Issues**: errors (block approval) and warnings, e.g. negative net, no super fund, no TFN, zero earnings.

## Worked example: bonus (verified by hand and by test)
Hannah, monthly, scale 2: regular $12,083.33, bonus $12,000.
- Regular: weekly equivalent `floor(12,083.33 x 3 / 13) + .99 = 2,788.99`; `0.39 x 2,788.99 - 363.4627 = 724.3` -> $724; x 13/3 = **$3,137**.
- With 12,000 / 12 = 1,000 added: 13,083.33 -> 3,019.99 -> $814 -> **$3,527**.
- (3,527 - 3,137) x 12 = **$4,680**; cap 47% x 12,000 = $5,640 not reached. Total PAYG **$7,817** (`test_bonus_withholding_matches_a_hand_worked_schedule_5_method_a`).

## How it is tested
- `unit_payg_test.py`: **85 cases from the ATO's own sample data** (Schedule 1, 2026-27): Scales 1, 2, 3, 5, 6 at weekly, fortnightly and monthly frequencies; the Schedule 8 worked examples; weekly-equivalent rules; offsets; Method A; ETP and redundancy limits. Expected values are copied from the ATO pages, not computed by the code under test.
- `unit_calc_test.py`: 19 scenarios with hand-worked expectations (salary, sacrifice, overtime, leave + loading, unpaid leave, bonus, HELP, no TFN, foreign resident, super cap, proration, YTD, termination, accruals, validation, determinism).
