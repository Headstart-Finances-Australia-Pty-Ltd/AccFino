# Australian statutory rules

All statutory parameters live in `payroll_statutory_rules.json` (shipped in `deploy/data-seed/reference/`, copied to `ACCFINO_DATA_ROOT/reference/` on first use and **never overwritten**, so edits survive upgrades). The file is re-read when it changes: no restart needed. Each rule set has `effective_from`/`effective_to`; the engine uses the one covering the pay date.

## Adding a new financial year
1. Copy the `2026-27` object in `rule_sets`, change `id`, `label`, `effective_from`, `effective_to`.
2. Replace the PAYG coefficients with the ATO's *Schedule 1* tables (weekly), the study-loan coefficients (*Schedule 8*), super guarantee rate and maximum contribution base, ETP cap and redundancy limits.
3. Re-run `unit_payg_test.py` with the ATO's sample data for the new year (update the expected values from the ATO's *Withholding amounts sample data* page).
4. Set each section's `verified` / `verified_on`. The UI (Settings > Statutory rules, PAYG tab) shows these labels.

## What is in the 2026-27 rule set, and how far it is verified
| Section | Content | Status |
|---|---|---|
| `payg` | Schedule 1 coefficients, Scales 1, 2, 3, 5, 6 (+ Scale 4 flat rates), tax-offset percentages | **primary**: ATO page "Coefficients to use in formulas for withholding from weekly payments", published 17 June 2026 (instrument LI 2026/18) |
| `study_loan` | Schedule 8 marginal-repayment component tables (HELP, VSL, SSL, SFSS, AASL) | **primary**: ATO Schedule 8, applies from 1 July 2026, worked examples tested |
| `additional_payments` | Method A, 47% cap | **primary-prior-year**: steps as published for 2025-26; confirm unchanged for 2026-27 |
| `super` | SG 12%; Payday Super (received by the fund within 7 business days of payday); qualifying-earnings base; maximum contribution base $270,830 (annual) | **primary** (ATO) |
| `etp` | ETP cap $270,000; 32% / 17% (age 60+) / 47% above cap; genuine redundancy $13,598 + $6,801 per completed year | **secondary**: cross-checked from secondary sources only; verify with the ATO before relying on it |
| `termination_leave` | flat 32% for balances accrued before 18 Aug 1993 | **unverified**: not checked against Schedule 7 text |

## Behaviours worth knowing
- **Rounding**: ATO rule, .50 rounds up, applied directly to the dollar (not via cents). Scale 4 ignores cents on earnings and on the result.
- **Super is on qualifying earnings** (Payday Super), calculated before salary sacrifice. Overtime is not included.
- **Super due date** = payday + 7 business days (weekends skipped; **public holidays are not**, so the date can be a day early).
- **Medicare levy**: built into the scales; Scale 5 (full exemption) and 6 (half) supported. Family-income adjustments (levy variation declarations) are not.
- **Variations**: an ATO-approved withholding variation percentage replaces the schedule tax for regular earnings.
- **No rule, no pay**: a pay date with no covering rule set is rejected ("No statutory payroll rules cover ...") rather than guessed.
- **Not modelled**: Schedule 15 (working holiday makers), Schedule 7 detail beyond the flat/Method A split, fringe benefits tax calculation (a "reportable fringe benefit" flag exists on pay items for reporting only), the whole-of-income ETP cap (the ATO applies it at assessment).
