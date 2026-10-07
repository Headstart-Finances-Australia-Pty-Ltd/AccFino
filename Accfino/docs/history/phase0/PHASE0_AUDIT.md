# Phase 0 audit - 28 Sep 2026

Method: fresh PostgreSQL 16, real server (`uvicorn accfino.app:app`), real HTTP, plus direct SQL for the integrity triggers. Reproduce with `AccFino_Testing/` (see its README). Result: **69 Phase 0 checks pass** (whole suite: 81 pass, 27 skipped for unbuilt modules, 2 strict expected-failures).

## Verdict
Phase 0's core promises hold. Phase 0 is **not yet closed**: there was no reproducible test evidence, two defects (introduced after the Phase 0 sign-off, in the module-visibility feature) were found and fixed, and the items in `ROADMAP.md` §4 (Phase 0.5) remain.

## Defects found and fixed
| # | Defect | Evidence | Fix |
|---|---|---|---|
| D1 | **Any signed-in user could change platform-wide module visibility** (`POST /module-visibility`), hiding domains for everyone including the public landing page | Ordinary user got HTTP 200 and Accounting vanished from `/modules.json` | `middleware.py`: add `({"POST","PATCH","PUT","DELETE"}, "/module-visibility", "exact")` to `ADMIN_RULES` -> ordinary user gets 403 |
| D2 | `GET /module-visibility` required sign-in, but the SPA reads it on `/login`; the shared client turns any 401 into a redirect to `/login` (loop risk) | Signed-out GET returned 401 | `middleware.py`: `("GET", "/module-visibility")` in `PUBLIC_METHOD_ROUTES`; `api.js`: read through bare axios so it can never trigger the 401 redirect |

Regression tests: `test_regression_module_visibility_is_public_read_admin_write` and the admin-write parametrised test. Mutation check: re-introducing D1 fails exactly those two tests.

## Open findings (tracked in ROADMAP §4)
1. No automated tests or CI shipped; the "195 passed" claim could not be reproduced. (X1)
2. **Payroll uses `SUPER_GUARANTEE_RATE = 0.11`** (`accfino/modules/payroll/tax_engine.py`); ATO: 12% since 1 Jul 2025, Payday Super since 1 Jul 2026. Strict xfail test added. (X0)
3. Module visibility is stored in `main_app/data/module_visibility.json`, not the database: not shared across instances and not reset with the database. (X2)
4. Start-up log: `invoice tables: concurrent create, retrying (IntegrityError)` - two code paths create the same tables. (X3)
5. Legacy money columns are `double precision` (already documented). Strict xfail test added. (Phase 1 A1)
6. Frontend is a single 1.3 MB bundle; no frontend unit tests. (X6)
7. Release notes / architecture doc described superseded navigation. (X4, corrected in this pack)

## Not verified
Browser behaviour; SMS/email/passkey MFA; Stripe; Open Banking; multi-worker and load; backup/restore; classifier accuracy.

## Closure record - rev 2 (same day)
Exit gate worked through and re-tested: see `ROADMAP.md` section 4 for the item-by-item table. Additional defect found while doing it:

| # | Defect | Evidence | Fix |
|---|---|---|---|
| D3 | `tabsForDomain` mapped route-less registry entries onto the default "dashboard" tab (hiding e.g. `openfeed-open-banking` could hide Accounting's Dashboard); `visibleGroups` could return a domain with nothing routable, giving the side panel an undefined link | Vitest `never maps a route-less capability entry onto a hub tab` failed before the fix | `lib/modules.js`: ignore route-less entries in `tabsForDomain`; require one routable visible module in `visibleGroups`; `Layout.jsx` landing = first routable item |

Results: Phase 0 - 82 tests (81 pass, 1 strict xfail); front-end - 19 unit tests; whole suite 94 pass / 27 skipped / 3 xfail.
New findings: X9 (13 user-reachable front-end calls with no back-end route - open) and X10 (13 Settings/Admin provider switches shown as domain tiles on Overview - **fixed**: entries carry `area`/`group`, are now excluded from domain views and the public registry). Correction: X10 was first described as "platform capabilities misplaced in business domains"; they are deliberate switches read by the Settings/Admin screens.
