# Payroll & Workforce  (`accfino.modules.payroll`)

Employees (profile, tax, super, bank, recurring items), pay calendars, pay items, leave (accruals, requests, approvals), timesheets, **pay runs** (calculate > review > approve > finalise > reverse), the **PAYG / super / study-loan calculation engine**, payslips, payments (bank file, mock completion), super contribution tracking, STP structures (not lodged), 18 reports, an audit trail and a ledger journal per pay run. **Full documentation: [`docs/payroll/`](../../../../docs/payroll/README.md)**; manual test procedure: [`docs/payroll/10-manual-testing-guide.md`](../../../../docs/payroll/10-manual-testing-guide.md).

| | |
|---|---|
| Backend | `backend/accfino/modules/payroll/` (`engine/` pure calculation, `services/` rules, `api/` HTTP, `models/`, `access.py`, `demo_seed.py`) |
| Frontend | `frontend/src/modules/payroll/` |
| Tests | `python AccFino_Testing/run_tests.py payroll` -> `AccFino_Testing/tests/modules/payroll/`; `frontend/src/modules/payroll/__tests__/`; PostgreSQL-only: `payroll_pg_test.py` (needs `PAYROLL_PG_URL`) |
| Owns tables | `pay_audit`, `pay_calendars`, `pay_departments`, `pay_employee_bank`, `pay_employee_items`, `pay_employee_super`, `pay_employee_tax`, `pay_employees`, `pay_items`, `pay_journal_lines`, `pay_journals`, `pay_leave_requests`, `pay_leave_txns`, `pay_leave_types`, `pay_locations`, `pay_notifications`, `pay_payment_items`, `pay_payments`, `pay_payslips`, `pay_run_employees`, `pay_run_inputs`, `pay_run_lines`, `pay_runs`, `pay_settings`, `pay_stp_events`, `pay_stp_final`, `pay_super_contribs`, `pay_super_funds`, `pay_timesheet_lines`, `pay_timesheets`. Legacy tables `payroll_employees`, `payroll_runs`, `payroll_timesheets`, `payslips`, `stp_submissions` are kept, unused |
| Statutory data | `deploy/data-seed/reference/payroll_statutory_rules.json` -> `ACCFINO_DATA_ROOT/reference/` (rates are data, not code) |
| Uses (public facades) | `accounting` (`post_journal`, `reverse_journal`, `ledger_accounts`, `ensure_ledger_account`, `journal_summary`, `seed_org_ledger_accounts`) |
| Uses (shared services) | `contracts`, `db`, `paths` (and `core`: org context, field sealing, force-delete for demo reset) |
| Public API for other modules | none |
| Extra docs | [docs/payroll/](../../../../docs/payroll/README.md) |

## HTTP API (URL prefixes, route count)
| Prefix | Routes |
|---|---|
| `/payroll/audit` | 1 |
| `/payroll/calendars` | 4 |
| `/payroll/dashboard` | 1 |
| `/payroll/departments` | 3 |
| `/payroll/employees` | 16 |
| `/payroll/leave` | 6 |
| `/payroll/leave-types` | 3 |
| `/payroll/ledger-accounts` | 1 |
| `/payroll/locations` | 3 |
| `/payroll/me` | 1 |
| `/payroll/pay-items` | 4 |
| `/payroll/payments` | 7 |
| `/payroll/payslips` | 3 |
| `/payroll/reports` | 2 |
| `/payroll/rules` | 1 |
| `/payroll/runs` | 17 |
| `/payroll/settings` | 2 |
| `/payroll/stp` | 6 |
| `/payroll/super` | 2 |
| `/payroll/super-funds` | 3 |
| `/payroll/timesheets` | 9 |

## Rules for working here
1. Stay inside this folder. To use another domain, import only `accfino.modules.<other>.public` (the boundary check fails otherwise); import it as `import accfino.modules.accounting.public as accounting`.
2. **No rate or threshold in code.** Statutory values belong in `payroll_statutory_rules.json` (see docs/payroll/06).
3. **Never use `user_id` / `username` as an API field**: the platform AuthGuard treats them as "the caller". The employee<->login link is `login_user_id`.
4. Finalised pay data is immutable: correct it with `payruns.reverse`, never an edit. API handlers only call services and commit; business rules live in `services/` and `engine/`.
5. Sensitive values (TFN, bank accounts) are sealed with `services/protect.py` and returned masked only; never log them.
6. New table: model in `models/payroll.py` and `PAYROLL_TABLES`. Add or update tests for what you change, then run `python AccFino_Testing/run_tests.py payroll`. Regenerate the reference docs (`docs/payroll/generate_reference.py`).
