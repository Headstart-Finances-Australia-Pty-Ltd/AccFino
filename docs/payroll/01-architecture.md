# Architecture

Payroll is a vertical slice of the AccFino modular monolith and follows the platform rules (`docs/architecture.md`): it uses `core` and `shared`, imports the Accounting module **only** through `accounting.public`, and is enforced by `AccFino_Testing/architecture/check_boundaries.py` (0 violations).

```
backend/accfino/modules/payroll/
  engine/        PURE calculation: no database, no clock, no I/O   (money, rules, payg, superannuation, leave, calc)
  models/        SQLAlchemy tables (pay_*), all org-scoped
  services/      business rules and the only code that writes payroll data
                 employees, config, leave, timesheets, runbuild, payruns, payslips, payments, superfunds, journals, reports, stp, dashboard,
                 audit, protect (TFN/bank sealing + masking), alloc, setup (per-organisation provisioning), errors
  api/           HTTP only: validation, authorisation, call a service. No business rules.
  access.py      capability matrix built on the platform's organisation roles
  demo_seed.py   DEMO data loader (development/testing only)
  manifest.py    registers tables, org provisioning, legacy startup step
deploy/data-seed/reference/payroll_statutory_rules.json     statutory rates as DATA (copied to ACCFINO_DATA_ROOT/reference on first use)
frontend/src/modules/payroll/   pages/, components/, lib/ (API client, validators), __tests__/
```

## The three layers, kept apart
1. **Statutory rules** (`payroll_statutory_rules.json`): rates, thresholds and coefficient tables with effective dates and a per-section source/verification status. No rate exists in code. A new financial year is a new rule set; the engine picks the one covering the **pay date** and refuses to calculate if none does.
2. **Calculation engine** (`engine/`): given an employee, a period, line inputs and year-to-date totals it returns a complete deterministic result. Decimal arithmetic, ATO rounding, no side effects. Unit-tested against the ATO's own published sample data.
3. **Payroll processing** (`services/`): assembles inputs from the database (`runbuild`), runs the engine, stores results, and drives the pay-run lifecycle, leave, payments and the ledger journal.

## Data flow
```
Employee + tax + super + bank + recurring items ─┐
Approved timesheet lines ────────────────────────┤
Approved leave requests ─────────────────────────┼─> runbuild.build() ─> engine.calculate_employee() ─> pay_run_employees + pay_run_lines
Manual run inputs (bonus, back pay, termination) ┤                                                     (status: review)
Year-to-date (finalised runs + opening balances) ┘
                              approve  (refuses errors, stale inputs, and - if enabled - the run's creator)
                              finalise (ONE transaction): leave ledger + timesheets marked paid + super contributions
                                        + payslips (frozen snapshot) + ledger journal + sealed result hash
                              payments (batch, bank file, mock completion, optional bank journal) ; super tracking ; STP structures ; reports
```

## Integrity rules (and where they are enforced)
| Rule | Enforced by |
|---|---|
| Finalised data is never edited | every mutator rejects a run that is not draft/review (`run_locked`, 409); reports read only finalised data |
| Corrections are reversals, not edits | `payruns.reverse`: a new run with every amount negated, the ledger journal reversed, leave/timesheets released. The original is kept |
| No duplicate processing | service check **and** a partial unique index (`uq_pay_run_period`) on live regular runs; `SELECT ... FOR UPDATE` on finalise; proven under real concurrency on PostgreSQL |
| A stale calculation cannot be approved/finalised | each employee's inputs are fingerprinted at calculation and re-checked at approve and finalise |
| Totals agree across run, payslips, payments, journal | payslips are snapshots of the run; the payroll journal totals equal the ledger journal; every report carries a reconciliation control; tested for all demo runs |
| Tampering is detectable | `result_hash` over the finalised results; `/runs/{id}/integrity` |
| Sensitive data | TFN and bank account numbers are Fernet-sealed at rest and returned only masked; revealing a TFN is audited |
| Everything is audited | `pay_audit`: user, time, action, record, before/after (secrets scrubbed) |
| Tenancy | every query filters on `org_id`; another organisation's record answers 404 |

## Ledger posting
One balanced journal per finalised run through `accounting.public.post_journal` (the platform's only ledger write path). Accounts are mapped in Settings and default to the chart's payroll accounts (477, 478, 479, 804, 825, 826, 806). Lines are netted per account; the employee-level breakdown is kept in `pay_journal_lines` (each with a transaction reference such as `PR-0001-E0001-003`), so ledger amounts trace **Company > Pay run > Employee > Payroll transaction**. A reversal posts a reversing journal through the ledger's `reverse_journal`.

## Platform changes made for Phase 2 (outside the payroll folder)
- `core/models.py`, `core/security/context.py`, `core/api/org_directory_api.py`: new organisation roles `payroll_admin` and `employee` (`employee` has no ledger access).
- `core/migrate.py`: widens the PostgreSQL CHECK constraint `ck_org_member_role` on existing databases (idempotent; verified on PostgreSQL).
- `modules/accounting/public.py`: additive ledger facade (`post_journal`, `reverse_journal`, `ledger_accounts`, `ensure_ledger_account`, ...).
- `core/subscription/service.py` and `frontend/src/core/config/modules.json`: six new payroll tabs registered; leave/super/PAYG moved from "planned" to "beta"; STP wording corrected (it does not lodge).
- Four frontend files: role labels for the new roles.
- The legacy payroll API and tax engine were removed (their data tables remain, unused).
