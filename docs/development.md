# Developing and testing by business domain

AccFino is one deployable app, but every business domain is a **vertical slice** that one team can build, test and release-check on its own:

```
backend/accfino/modules/<domain>/      API, services, models, migrations, manifest.py, public.py, README.md
frontend/src/modules/<domain>/         pages, components, lib (API client), public.js, __tests__/
AccFino_Testing/tests/modules/<domain>/   backend tests          AccFino_Testing/testdata/<domain>/   its test data
```

Domains: accounting, reconciliation, cashflow, trading, lending, payroll, taxation, billing, open_banking. `core` (identity, security, tenancy, subscription, admin) is the platform they all stand on.

## 1. Ownership
* One **owning team per domain** (suggested `CODEOWNERS`: `/backend/accfino/modules/accounting/ @team-books`, the same for `/frontend/src/modules/accounting/` and `/AccFino_Testing/tests/modules/accounting/`; Core and Shared get the platform team).
* Changes inside a domain need only that team's review. Changes to `core/`, `shared/`, `*/public.py`, `*/public.js`, `manifest.py` need the platform team **and** every consuming domain.
* Each domain README states purpose, owned tables, HTTP prefixes and what it may use. Keep it true (the contract test checks it exists).

## 2. The contract between domains
* A domain exposes to others only `public.py` / `public.js`, plus data through the shared database tables it declares. Everything else is private (enforced by the boundary check).
* Prefer **events and registry hooks** over calls: Core and Shared never call a domain; a domain contributes via `manifest.py` (tables, schema hooks, per-organisation provisioning, start-up hooks).
* Changing a public function: add the new one, migrate callers, then remove the old (two PRs). Never change a signature in place.
* Cross-domain data sharing today: Accounting reads reconciliation's `Transaction`/`RDRRule` through `reconciliation.public`; if that grows, replace it with a small interface in `shared/contracts`.

## 3. Daily workflow (one domain)
```
python AccFino_Testing/run_tests.py accounting        # backend + frontend + boundary check for that domain only (seconds to ~2 min)
python AccFino_Testing/run_tests.py all               # before merging anything in core / shared / a public facade
cd AccFino/frontend && npm run dev                    # UI at :3000, proxies /api to :8001
cd AccFino/backend  && python -m uvicorn accfino.app:app --reload --port 8001
```
Run a single file with `python -m pytest ../../AccFino_Testing/tests/modules/accounting/ledger_api_test.py` from `AccFino/backend` (`PYTHONPATH=.`).

## 4. Test pyramid, per domain
| Layer | What it proves | Where | Speed |
|---|---|---|---|
| **Unit** | pure logic: parsers, classifiers, tax/CGT/payroll maths, rounding, FX | `tests/modules/<domain>/unit_*` | ms |
| **Service** | business rules against a real schema (SQLite harness `make_db`/`make_org`) | `tests/modules/<domain>/*_test.py` | s |
| **API** | HTTP contract, permissions, plan gates, tenant isolation (FastAPI `TestClient`) | same folder | s |
| **Module contract** | manifest, README, public facade, URL mounted, tables registered | `tests/modules/test_module_contracts.py` (all domains) | s |
| **Architecture** | dependency rules, no business data in the package | `tests/architecture/` | s |
| **UI component** | pages render, forms validate, API calls shaped right (vitest + Testing Library, API mocked) | `frontend/src/modules/<domain>/__tests__/` | s |
| **E2E journey** | a few critical paths in a real browser against a running stack | `AccFino_Testing/e2e/` | min |
| **PostgreSQL** | triggers, advisory locks, `ALTER TABLE` paths that SQLite cannot run | `tests/core/force_delete_pg_test.py` + ledger tests with `DATABASE_URL` | min (nightly) |

Rule of thumb: put each test at the **lowest** layer that can catch the bug. Money and tax logic belongs in unit tests with oracle values; E2E stays at five or six journeys.

## 5. Test data per domain
* **Golden datasets** in `AccFino_Testing/testdata/<domain>/` (accounting ships `csv/` + `generate_mock_data.py`; frontend report fixture in `testdata/frontend/`). Deterministic: generated from a fixed "today" so expected values never drift.
* **Oracles**: expected results computed independently of the code under test (a spreadsheet or a few lines of arithmetic written separately), stored beside the data. Review a changed oracle like a changed requirement.
* Never use real client data. Tests run with a throwaway `ACCFINO_DATA_ROOT` (the root `conftest.py` creates one).

## 6. What each domain needs next (current gaps)
Reconciliation, Cash Flow, Trading and Lending have no dedicated suites yet (they are covered only by the contract tests). **Payroll now has a full suite** (unit, integration, API, PostgreSQL and UI: see docs/payroll/08). Highest value first:
| Domain | First tests to write |
|---|---|
| Trading | FIFO lot matching and CGT discount golden file (buy/sell/split cases) - tax-sensitive, pure logic |
| Reconciliation | statement normaliser fixtures per bank format; classifier regression set (description -> GL + GST); duplicate detection |
| Lending | HEM group mapping, DTI/serviceability maths, statement gap detection |
| Cash Flow | column auto-detection, date-span validation, a deterministic forecast on a fixed dataset |

## 7. Continuous integration (path-aware)
* **Every PR**: boundary check + `run_tests.py` for the domains whose folders changed (backend, frontend and test folders share the domain name, so a path filter is trivial), plus the module contract tests.
* **Changes to `core/`, `shared/`, a `public.*` or `manifest.py`**: run `all`.
* **Nightly**: `all` + the PostgreSQL job (disposable PostgreSQL service) + E2E journeys.
* Merge gate: architecture test green. A listed-but-fixed or new boundary violation fails the build.

## 8. Releasing a domain without a big-bang
Modules deploy together (modular monolith) but **ship independently** through switches that already exist: plan gating (`feature_gate`), Admin > Modules visibility, and the registry `status` (`live` / `beta` / `planned`). Build behind `beta`, hide from non-pilot organisations, promote to `live` when its tests and README are complete.

## 9. Pull-request checklist
- [ ] Only this domain's folders changed (or the platform team is on the review).
- [ ] Tests added at the lowest sensible layer; `run_tests.py <domain>` green.
- [ ] No data path built from `__file__`/literals (use `accfino.shared.paths`); no real data in tests.
- [ ] New table/migration registered in `manifest.py`; README updated if endpoints, tables or dependencies changed.
- [ ] Public facade changed? Two-step deprecation, consumers updated.

## 10. Add a new domain in an hour
`modules/<name>/{api,models,manifest.py,README.md}` -> add to `registry.MODULE_NAMES` -> mount in `accfino/app.py` -> `frontend/src/modules/<name>/` + route in `core/App.jsx` -> a line in `test_module_contracts.py` (module list + expected route) -> `run_tests.py <name>`.
