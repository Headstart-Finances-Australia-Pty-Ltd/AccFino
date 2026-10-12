# Taxation & Compliance  (`accfino.modules.taxation`)

Tax profile and registrations, compliance calendar, **BAS / IAS** preparation from the ledger, **income tax returns** (individual, sole trader, company, partnership, trust, SMSF) with
book-to-tax adjustments, **CGT** (register, import from Trading, capital losses), small-business **depreciation / instant asset write-off** review, **FBT**, **Division 7A**, workpapers
and evidence, planning estimates and scenarios, reconciliation, lodgement readiness, reports/exports and a tamper-evident audit trail. Full documentation: [`docs/taxation/`](../../../../docs/taxation/README.md).

| | |
|---|---|
| Backend | `engine/` pure Decimal calculation (no DB, no rates), `services/` rules + workflows, `api/` HTTP, `models/tax.py` |
| Frontend | `frontend/src/modules/taxation/` |
| Tests | `python AccFino_Testing/run_tests.py taxation` -> `AccFino_Testing/tests/modules/taxation/` and `frontend/src/modules/taxation/__tests__/` |
| Owns tables | `tax_profiles`, `tax_rule_overrides`, `tax_registrations`, `tax_obligations`, `tax_bas_statements`, `tax_adjustments`, `tax_returns`, `tax_cgt_events`, `tax_capital_losses`, `tax_fbt_benefits`, `tax_fbt_returns`, `tax_div7a_loans`, `tax_div7a_payments`, `tax_workpapers`, `tax_evidence`, `tax_scenarios`, `tax_audit` |
| Statutory data | `deploy/data-seed/reference/tax_statutory_rules.json` -> `ACCFINO_DATA_ROOT/reference/` (rates are data, each group carries provenance; organisations may override a value with a reason) |
| Uses (public facades) | `accounting` (`gst_summary`, `payg_summary`, `profit_and_loss`, `fixed_assets_for_tax`, `account_balance`, `system_account_balance`, `attachment_info`), `payroll` (`withholding_for_period`, `has_employees`, `employee_names`) |
| Uses (shared services) | `contracts`, `db`, `paths` (and `core`: org context, plan gate) |
| Public API for other modules | none |

## What it does NOT do
AccFino does **not** transmit anything to the ATO. Statuses `lodged` and `paid` are records made by a user, with the ATO receipt reference. Lodge through ATO Online services, myTax or a tax agent.
A TFN is never stored. Items the engines cannot assess are returned as `review` findings and listed on every document.

## HTTP API (prefix `/tax`)
profile, rules (+ override), registrations, obligations (+ generate), bas (+ calculate/prepare/approve/return/lodged/paid/void/override), returns (+ inputs/calculate/prepare/approve/return/lodged/assessment/paid/void/amend),
adjustments (+ review, generate-depreciation), assets/review, payroll-tax/watch, cgt (events, import, losses, compute), fbt (benefits, summary, returns), div7a (loans, payments, schedule), workpapers (+ generate, advance), evidence,
planning (estimate, scenarios), reconcile, readiness, reports (summary, export, xlsx), audit (+ verify), dashboard, health, reference.
