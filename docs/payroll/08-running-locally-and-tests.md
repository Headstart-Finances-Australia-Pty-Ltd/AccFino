# Running payroll locally, and running the tests

## Run the application
```bash
cp .env.example .env           # set DATABASE_URL (PostgreSQL), JWT_SECRET (long random), ADMIN_PASSWORD, ACCFINO_DATA_ROOT
cd backend && pip install -r requirements.txt
export PYTHONPATH=. ACCFINO_DATA_ROOT=../../AccFino_Data
python -m accfino.core.init_db                       # creates the schema; on an existing database it upgrades it (adds the payroll tables, widens the role constraint)
python -m uvicorn accfino.app:app --host 127.0.0.1 --port 8001 --reload
cd ../frontend && npm install && npm run dev         # http://localhost:3000  (proxies /api to :8001)
python -m accfino.modules.payroll.demo_seed --reload --yes     # optional: demo data (see 07)
```
PostgreSQL is required (ledger triggers). No payroll-specific configuration is needed: on first use each organisation is provisioned automatically (payroll settings, system pay items, default leave types, payroll ledger accounts). Then in the app: **Payroll & Workforce > Settings** (employer, calendars, funds, accounting, payments).

To give someone self-service access: add them to the organisation with the **Employee** role, then on their employee record choose that person under **Login (self-service)**.

## Upgrading an existing installation
`python -m accfino.core.init_db` is idempotent. It creates the 29 `pay_*` tables, and widens `ck_org_member_role` so `payroll_admin` and `employee` are accepted (verified against a database holding the old constraint). The five legacy payroll tables are left in place and unused; nothing is dropped.

## Tests
| What | Command | Notes |
|---|---|---|
| Payroll (backend + frontend + boundary) | `python AccFino_Testing/run_tests.py payroll` | offline; SQLite for the backend |
| Everything | `python AccFino_Testing/run_tests.py all` | what CI runs |
| Payroll backend only | `cd AccFino/backend && PYTHONPATH=. python -m pytest ../../AccFino_Testing/tests/modules/payroll` | |
| Payroll frontend only | `cd AccFino/frontend && npx vitest run src/modules/payroll` | |
| **PostgreSQL-only guarantees** | `PAYROLL_PG_URL=postgresql://user:pw@host/db python -m pytest AccFino_Testing/tests/modules/payroll/payroll_pg_test.py` | needs a **disposable, initialised** database; skipped otherwise. Checks ledger immutability, duplicate-create and concurrent-finalise races, the balance trigger and force-delete reset |
| Architecture | `python AccFino_Testing/architecture/check_boundaries.py AccFino` | must report 0 couplings |

Backend payroll test files (`AccFino_Testing/tests/modules/payroll/`):
| File | Layer | Covers |
|---|---|---|
| `unit_payg_test.py` | unit | PAYG, study loan, Method A, ETP against the ATO sample data |
| `unit_calc_test.py` | unit | gross, overtime, leave, salary sacrifice, super cap, net, YTD, accruals, determinism |
| `payrun_flow_test.py` | integration | create > calculate > approve > finalise > payslips > journal > YTD > reversal > locks > leave |
| `integration_test.py` | integration | timesheet > payroll, leave > payroll, complex run, termination, edge cases, super, STP |
| `api_test.py` | API | success, validation, authentication, authorisation for every role, tenant isolation, duplicates, invalid states, reports, payments |
| `demo_seed_test.py` | integration | the demo dataset (see 07) |
| `payroll_pg_test.py` | PostgreSQL | see above |
Frontend: `src/modules/payroll/__tests__/payroll.test.jsx` (validators, role-based navigation, dashboard, employee form, pay-run workflow by status and role, reports, payslip).

## Troubleshooting
- *"No statutory payroll rules cover <date>"*: the pay date is outside the loaded rule sets (06).
- *Role not accepted on an existing PostgreSQL database*: run `python -m accfino.core.init_db`.
- *`user_id` rejected by the platform ("You can only access your own data")*: payroll APIs never use that name; if you add an endpoint, use another field name (the AuthGuard treats `user_id`/`username` as "the caller").
