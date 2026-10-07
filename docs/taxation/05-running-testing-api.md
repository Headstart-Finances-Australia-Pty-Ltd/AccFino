# 05 – Running, testing, API

## Tests
```
cd AccFino/backend
PYTHONPATH=. python -m pytest ../../AccFino_Testing/tests/modules/taxation -q        # 115+ tests, SQLite, offline
cd ../frontend && npx vitest run src/modules/taxation                                 # 37 tests
```
| File | Covers |
|---|---|
| `tax_foundation_test.py` | profile validation, rule overrides, calendar generation and roll-forward, roles, audit-chain tamper detection, tenant isolation |
| `tax_bas_test.py` | label oracle against posted journals, reconciliation blocks, workflow, separation of duties, stale-ledger refusal, overrides, IAS, calendar linking |
| `tax_returns_cgt_test.py` | company/individual/trust returns, adjustments, instalments from lodged BAS, CGT discount/loss order, 12-month boundary, import idempotency, depreciation review |
| `tax_fbt_div7a_test.py` | FBT valuation and return, exemptions, missing benchmark refusal, Division 7A schedule against an independent formula |
| `tax_workpapers_overview_test.py` | workpapers, evidence integrity/limits, planning, reconciliation, readiness, health, exports, demo seed |
| `tax_payroll_integration_test.py` | BAS and reconciliations against books posted by the real payroll module (21 finalised pay runs): W1/W2 equal payroll's own totals; a disagreeing manual journal is caught |
| `tax_payroll_tax_test.py` | payroll tax monitor: statuses and boundary, flat-rate indication only for NSW, unloaded states never guessed, due dates against the published NSW 2026-27 table, real payroll wages |
| `tax_lodgement_test.py` | declaration gate, agent policy, 8-digit agent number, stale/superseded/revoked sign-offs, hand-off pack contents, simulation never marks lodged, fake accredited gateway (accepted / no receipt / rejected / garbage / not ready), audit trail, tenancy |
| `tax_api_test.py` | HTTP status codes per role, validation, multipart evidence, exports, router mounted with plan gate |

Mutation check performed: breaking the CGT 12-month rule and the company base-rate test each fails a test.

## Real-browser journeys (PostgreSQL 16, the real built UI)
`AccFino_Testing/e2e/tax/run_tax_e2e.sh` creates a throwaway database, seeds an organisation, starts the real app, and drives headless Chromium through 95 checks (including a phone-width layout pass): sign-in through the login page, BAS, adjustments and the review gate, CGT, return, FBT, Division 7A, planning, workpapers with real file upload and download, reconciliation, Excel/CSV downloads, the state payroll tax monitor, lodgement readiness, the rates screen and the audit-chain check. See that folder's README.
It found three defects that no unit test could, all fixed with regression tests: BAS labels shown in the wrong order (PostgreSQL JSONB does not keep key order), estimates silently not flagged for review, and individual-only inputs shown on a company return.

## API (prefix `/tax`, org-aware, requires a role with access)
`/me /dashboard /health /reference /profile /rules (+/override) /registrations /obligations (+/generate) /bas /returns /adjustments /assets/review /cgt/{events,import,losses,compute} /fbt/{benefits,summary,returns,employees} /div7a/loans /workpapers /evidence /planning/{estimate,scenarios} /payroll-tax/watch /lodgement/{state,providers,submit,pack} /signoffs (+/{id}/revoke) /cgt/import-trades /reconcile /readiness /reports/{summary,export,xlsx} /audit (+/verify)`.
Workflow actions: `POST /bas|returns/{id}/{calculate,prepare,approve,return,lodged,paid,void}`; returns add `inputs`, `assessment`, `amend`. Errors are `{"detail": message}` with 403 (role/separation), 404 (not found or other tenant), 409 (state conflict, stale, locked), 422 (validation).
