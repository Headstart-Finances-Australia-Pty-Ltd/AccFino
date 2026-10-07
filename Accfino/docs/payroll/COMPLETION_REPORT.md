# Payroll Phase 2: completion report

**Status: built, integrated and tested; not yet exercised in a browser.** The manual testing guide ([10](10-manual-testing-guide.md)) is the on-screen acceptance procedure and has not been executed by a human. See "Honest status" below.

## 1. What was implemented
The full payroll lifecycle inside AccFino, on the existing architecture, auth, tenancy and UI:

| Area | Delivered |
|---|---|
| Dashboard | KPIs, next/last run, pending actions, alerts, compliance reminders, trend chart, attention list: all computed from data |
| Employees | profile, employment, tax (TFN sealed + masked), super (multi-fund), bank (multi-account, sealed, masked), recurring items, leave, termination |
| Configuration | organisation/payslip/payment/STP settings, pay calendars and periods, pay items (earnings, deductions, reimbursements, super), leave policies, super funds, departments, locations, ledger account mapping, statutory rules view |
| Leave | accruals, balances (ledger), requests, approve / reject / cancel, history, adjustments, payout suggestion, leave paid through payroll with loading |
| Timesheets | weekly sheets, validation, draft / submitted / approved / rejected / processed, manager approval |
| Pay runs | create (period validated against the calendar), manual inputs (bonus, back pay, reimbursement, termination), calculate, review, approve, finalise, void, **reverse**; stale-calculation and duplicate protection; integrity hash |
| Calculation engine | pure, deterministic: PAYG scales 1/2/3/4/5/6, study loans, Method A bonuses, super on qualifying earnings with the annual cap, salary sacrifice, leave + loading, unpaid leave, proration, ETP, termination leave, accruals, YTD |
| Australian rules | rates as data (`payroll_statutory_rules.json`), effective-dated, with per-section verification status |
| Payslips | frozen snapshot from finalised data; print / download HTML (no PDF library exists in the app) |
| Payments | per-account allocation, ABA bank file, mock completion (no bank contacted), return / reconcile, optional ledger journal |
| Accounting | one balanced journal per run through the ledger's own posting; employee-level traceability; reversal journal |
| Super | per-fund, per-component contributions with Payday Super due dates, paid / overdue tracking |
| STP | pay events, update events, finalisation, payment-summary data; **mock submission only, never lodged** |
| Reports | 18 reports, filters, CSV export, print, and a reconciliation control on each where a second source exists |
| Audit | user, time, action, record, before/after (secrets scrubbed) |
| Security | role matrix on the platform's roles, employee self-service, derived line managers, masking, tenant isolation, separation of duties |
| Demo data | 2 companies, 25 employees, 42 pay runs, all scenarios; load / reset / reload commands |
| Docs and tests | `docs/payroll/` (11 pages incl. the manual guide), automated tests at every layer |

## 2. Files and modules
**84 added, 19 modified, 2 removed** (counted against the supplied `AccFino.zip`; build output and caches excluded).
- **Backend** `modules/payroll/`: `engine/` (7 files), `models/` (1 table module, 29 tables), `services/` (19 files), `api/` (8 files), `access.py`, `demo_seed.py`, `manifest.py`, `README.md`.
- **Frontend** `modules/payroll/`: 14 tab pages + shell, 4 components, API client, validators, formatters, `public.js`, tests.
- **Data**: `deploy/data-seed/reference/payroll_statutory_rules.json`.
- **Docs**: `docs/payroll/` (12 files incl. the generator). **Tests**: 8 payroll test files + a shared harness.
- **Size**: about 6,600 lines of backend, 2,060 of frontend, 1,620 of tests.
- **Modified (platform):** `core/models.py`, `core/security/context.py`, `core/api/org_directory_api.py`, `core/migrate.py`, `core/subscription/service.py`, `modules/accounting/public.py` (additive facade); `frontend/src/core/config/modules.json`; four core role-label UI files and two core tests whose pinned role lists legitimately grew; `docs/architecture.md`, `docs/development.md`; the legacy migration (broad `except` narrowed); `modules/payroll/{README.md,manifest.py}`, `pages/PayrollPage.jsx` (rewritten).
- **Removed**: the legacy `payroll/api.py` (unauthenticated-by-organisation, user-scoped) and `payroll/tax_engine.py` (2023-24 coefficients). Their five tables are kept, unused.

## 3. Database changes
29 new organisation-scoped `pay_*` tables with check, unique and foreign-key constraints and a partial unique index guarding duplicate live pay runs (see [02](02-database-model.md)). TFN and bank account numbers are Fernet-sealed columns. `ck_org_member_role` widened for `payroll_admin` and `employee` (idempotent; verified on PostgreSQL against the old constraint). No existing table is altered or dropped. Created by the platform's existing `init_db` / `migrate` path via the module manifest.

## 4. API changes
95 endpoints under `/payroll` (see [03](03-api-reference.md)), replacing the legacy ~20. All authenticated and organisation-scoped; permission-checked per capability (see [04](04-roles-and-permissions.md)). Errors are `{"detail": ...}` with 401/403/404/409/422.

## 5. Frontend changes
The 800-line single-file page is replaced by a role-aware module: tabs are shown from the user's capabilities (the server re-checks everything); shared grid with search, sort, pagination; loading, empty and error states; confirmation dialogs with required reasons for destructive actions; client-side validation (TFN check digit, BSB, hours, etc.) with the server as the authority.

## 6. Payroll calculation functionality
See [05](05-calculation-engine.md). Verified against the ATO's published Schedule 1 sample data (85 cases across five scales and three frequencies), the Schedule 8 worked examples, and hand-worked scenarios, including a Schedule 5 Method A bonus (Hannah: $7,817).

## 7. Demo data
See [07](07-demo-data-and-seeding.md). 2 organisations, 25 employees, 42 pay runs, 148 payslips, 48 ledger journals, produced by the real services; reset and reload are complete and repeatable (tested on SQLite and PostgreSQL).

## 8. Tests created and results
Baselines were recorded before any change. Final results:

| Suite | Baseline | Final | Notes |
|---|---|---|---|
| Backend (all, SQLite, offline) | 320 passed, 2 failed | **499 passed, 2 failed, 6 skipped** | the 2 failures are `contact_verify_test` and **pre-exist** my work (unrelated); 5 skips are the PostgreSQL payroll tests (need a database URL) |
| Frontend (all) | 363 passed, 1 failed | **391 passed, 1 failed** | the failure is the pre-existing `CsvImport` test; +28 payroll tests |
| Architecture boundary check | 0 couplings | **0 couplings** | |
| Payroll on real **PostgreSQL 16** | n/a | **5 passed** | ledger immutability, balance trigger, concurrent creates (1 winner of 4), concurrent finalise (1 winner of 4), force-delete reset |
| Extra concurrency stress (script, PostgreSQL) | n/a | **5 runs x 6 simultaneous finalisers: 5 winners, 25 clean rejections** | one journal and one payslip set per run every time |

Payroll backend tests by layer: unit (104: PAYG/ATO oracles + calculation scenarios), integration (pay-run lifecycle, timesheet/leave/termination flows, demo dataset), API (46: all roles, validation, isolation, invalid states, duplicates), PostgreSQL (5). Frontend: 28.

## 9. Defects found by testing and fixed
Builder issues silently dropped from runs; leave balance checked at the wrong date; payroll journal totals disagreeing with the ledger; a self-referencing `RESTRICT` foreign key that blocked deleting any organisation with a reversed run; payroll admins able to approve their own leave/timesheets; accountants seeing masked tax/bank sections; managers able to create pay items; state changes not visible within a session (`autoflush` is off in production); an orphan timesheet left by a rejected save; a duplicate-row crash creating employees; three broad `except` handlers; a hidden hard-coded super rate in a report; the New Pay Run dialog unable to select non-current periods.

## 10. Honest status and known limitations
Full list in [09](09-known-limitations-and-future.md). The ones that matter most:
1. **Not executed in a browser.** UI verified by unit tests, a production build and API tests. Nobody has walked the manual guide on screen.
2. **AccFino does not lodge with the ATO.** STP is payload preparation plus a mock submission, labelled as such everywhere.
3. **The ABA bank file layout is untested with a bank.**
4. **ETP / redundancy / pre-1993 leave figures** come from secondary sources or are unverified (labelled in the rules file and UI). PAYG, study loans and super parameters were verified against ATO pages.
5. Only **FY2026-27** rules exist; the engine refuses other dates.
6. Super due dates ignore **public holidays**. No PDF generation (print to PDF). No award interpretation. Medicare family adjustments, Schedule 15 and FBT calculation not modelled.
7. **One unexplained, non-reproducible** `IllegalStateChangeError` appeared once in the first multi-threaded PostgreSQL test run; it did not recur in four repeat runs or 30 further racing attempts.
8. The 2 failing backend tests and 1 failing frontend test are pre-existing and were not touched.

## 11. Definition of done (brief section 28)
| Item | Status |
|---|---|
| Navigation, dashboard, configuration, employee profiles, pay items, leave, timesheets, pay runs | built and tested |
| Calculation engine; PAYG, super, deductions, salary sacrifice, allowances, bonuses | built; verified against ATO data |
| Payslips, payments workflow, accounting integration, reports, audit | built and tested |
| Permissions; sensitive data protected | built and tested |
| Demo data; reset / reload | built and tested |
| Unit, integration, API, important frontend tests | exist and pass |
| Manual testing guide | written (not yet executed by a human) |
| Existing functionality still works | yes against the recorded baselines (only the pre-existing failures remain) |
| No critical build or runtime errors | production build succeeds; full suites pass as above |
| All major workflows tested end to end | **API / service / PostgreSQL level: yes. In a browser: no.** |
| No placeholder payroll functionality | none remains ("Coming Soon" tabs removed); STP lodgement is explicitly mock |
