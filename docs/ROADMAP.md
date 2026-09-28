# AccFino roadmap - revised 28 Sep 2026 (rev 2: after closing the Phase 0.5 exit gate)

Supersedes the phase notes scattered through `RELEASE_NOTES.md` and `ARCHITECTURE.md`. It is organised by the seven business
domains in the side panel, sequenced by dependency, and every phase ships with **mock data, an automated gate and a manual
verification script** (see `AccFino_Testing/`). Nothing here is a calendar promise - sizes are relative (S/M/L/XL).

## 1. Where we are (audited and re-tested, not assumed)

**Phase 0 is complete for its stated scope** - security, organisations, double-entry ledger, chart of accounts, audit - and the
Phase 0.5 exit gate is closed except for three tracked items, two of which only you can do (X1, X5). Evidence: 82 Phase 0 tests
(81 pass, 1 strict expected-failure that tracks X9) plus 19 front-end unit tests and the production build, run against a
fresh PostgreSQL 16 and the real server. Whole suite: **94 pass, 27 skipped (module not built), 3 expected-failures**.
"Complete" does **not** mean release-ready: see X1, X5 and X9 below.

| Area | Result |
|---|---|
| Security guard, admin-only tools, tenant isolation, roles | Verified (every non-public GET is 401 unauthenticated; admin routes 403 to ordinary users; `user_id` override blocked; org header can't be borrowed) |
| Login lockout, MFA (TOTP + single-use recovery codes), device sessions, admin disable/unlock | Verified. SMS, email-code and passkey paths **not** exercised |
| Double-entry ledger, reversal, lock date, rounding, DB triggers, immutable audit log | Verified, including direct-SQL attempts to corrupt posted data |
| Reports and bank sync | Verified against an independent oracle (net profit 4,950; GST payable 295; 23 posted / 2 suspense / 1 skipped) |
| Frontend | Builds; **route pages now load on demand** (entry 146 kB, largest chunk 400 kB, was one 1,337 kB file); 19 unit tests on navigation/visibility logic. Not browser-tested |
| Settings/visibility | Module visibility now stored in the database (shared by all instances) |
| Payroll | Super rate **fixed to 12%** (engine and UI); Payroll shown as *Preview*. PAYG tables are still ATO **2023-24** - Phase 2 |

Defects found and fixed during the audit: module-visibility writes open to every signed-in user; visibility read 401 on `/login`
(both `D1/D2`, regression-tested); and `D3` - **my own** `tabsForDomain`/`visibleGroups` mis-handled the route-less entries now in
your registry (hiding one could hide Accounting's Dashboard tab, and a domain with only route-less items could produce an
undefined link). Fixed with unit tests.

Known gaps still open: 13 user-reachable front-end calls that 404 (X9); legacy money columns are floating point (Phase 1 A1); the Setup page edits a global chart/rules/knowledge base
(Phase 1 A4); PAYG tables 2023-24 (Phase 2 B1).

## 2. Principles (unchanged, now enforced by tests)

1. **The ledger is the only write path for financial data.** Sub-ledgers (sales, purchases, payroll, assets…) post journals through `accfino_core/ledger`; nothing writes balances directly.
2. **Deterministic rules in plain Python; LLMs advise, never post.** GST maths, payroll, depreciation, CGT are code with oracle tests.
3. **Registry-driven honesty.** `modules.json` status (`planned` -> `beta` -> `live`) changes only when the phase gate is green; the landing-page claims test blocks "ATO compliant", "lodge", AU-hosting etc. until true.
4. **Every rule has a positive and a negative test**, and every phase has a mutation check (break the rule, see the test fail).
5. **No invented regulatory numbers.** Tax tables and rates come from ATO-published sources pinned in the repo and signed off by an accountant.

## 3. Phase overview

| Phase | Theme | Domains | Milestones | Size | Depends on | Status |
|---|---|---|---|---|---|---|
| **0** | Platform foundation | Platform | M1-M3 | - | - | **Complete (scope)** - 82 tests |
| **0.5** | Exit gate | Platform, Payroll | X0-X10 | S | 0 | **3 open**: X1, X5 (you), X9 |
| **1** | Books & Accounting engine | Books and Accounting | A1-A7 | XL | 0.5 | Not started |
| **2** | Payroll & Tax compliance | Payroll & Workforce, Taxation & Compliance | B1-B4, C1-C2 | XL | 1, ATO onboarding (external) | Not started (SG rate fixed early) |
| **3** | Assets, inventory & investments | Assets/Investments & Wealth, Books | D1-D6 | L | 1 | Not started |
| **4** | Lending, credit, treasury & entity tax | Smart Lending/Credit/Treasury, Taxation | E2-E5, F1-F3 | L | 1, 3 | Not started (E1 statement analysis live) |
| **5a** | Planning & intelligence | Planning & Intelligence | G1-G6 | L | 1 | Not started (cash-flow forecast live) |
| **5b** | Practice & client services | Practice & Client Services | H1-H6 | L | 1, IAM step 3 | Not started |
| **6** | Platform & ecosystem | Settings / Admin | P1-P5 | M-L | 0.5 | Partly present in Settings/Admin (API keys, webhooks pages exist) but **no acceptance evidence**: specs still skip |

Why this order: **compliance risk moved forward** (payroll rate, Payday Super) - a live under-payment risk, not a feature. Books
before everything else because every domain posts to it. Lodgement (BAS/STP) is gated by an *external* dependency (ATO Digital
Service Provider onboarding / software ID), so preparation ships first. Intelligence comes after the ledger holds enough clean,
per-organisation data. Practice needs external-accountant access (invitations/guests) - IAM step 3.

## 4. Phase 0.5 - Exit gate status

| ID | Item | Status | Evidence |
|---|---|---|---|
| X0 | Payroll honesty | **Done** (tables remain in Phase 2) | SG constant 12%; UI label "Super (12%)"; payroll modules `beta` (Preview); tests `test_super_guarantee_rate_is_12_percent`, `test_payroll_ui_shows_the_current_super_rate`, `test_payroll_modules_are_labelled_preview_until_phase_2`; strict xfail `test_payg_tables_are_for_the_current_year` (2023-24) |
| X1 | Tests in source control + CI | **Open - yours**: suite and CI template delivered | commit `AccFino_Testing/`, enable `ci/github-actions.yml` |
| X2 | Module visibility in the database | **Done** | `platform_settings` rows (`service='module_visibility'`); old file imported once; 2 tests |
| X3 | Start-up table-creation race | **Accepted, bounded** | retry <= 5 with back-off is by design; `test_first_boot_has_no_errors_or_tracebacks` fails on any error/traceback or > 2 retries. Proper fix: single migration runner in Phase 1 A1 |
| X4 | Docs sync | **Done** | release notes rev 6, architecture, audit, manual script |
| X5 | Rotate leaked Neon password | **Open - yours** | `test_no_credentials_in_the_package` proves the current tree is clean; git history cannot be checked here |
| X6 | Code-split + front-end tests | **Done** | 19 Vitest tests; build test fails if any chunk > 500 kB |
| X7 | Admin tidy-up | **Done (by you)** | Platform Users inside *Users & Licence*; retired paths redirect; `test_admin_hub_tabs_have_routes_and_retired_paths_redirect`. Company DB was **removed** (covered by Data Manager / Setup > Knowledgebase) rather than added as a *Company Data* tab - confirm intended |
| X8 | Legacy `/invoice/businesses` mismatch | **Generalised** | new front-end -> back-end contract test guards against any *new* unserved call |
| **X9** | **13 user-reachable calls 404** | **Open** | Contacts CSV import (customers, suppliers); Admin delete user; Setup company edit/delete; Invoice Generator (5 calls); Admin > API Keys "list models", "test database", "test S3". Tracked by strict xfail `test_no_user_reachable_frontend_call_is_unserved`; 5 more calls are dead code |
| **X10** | **Provider switches leaking into domain tiles** | **Done** | 13 registry entries (Basiq, OpenFeed, Square, Stripe, Groq key pool, ML training, Database, S3, System email, Calendly, Meeting link) are Settings/Admin **switches** (flagged `area` + `group`): the Settings/Admin screens read them and Modules Management lists them separately. They were leaking into the Overview and side-panel domain lists (tiles under Books and Accounting and Smart Lending). Now excluded there and from the public registry; 3 pytest + 4 Vitest tests, incl. "every switch is read by code". Ids unchanged. (`square-open-banking` is a mis-named id for the Settings > Payment Setup Square switch; renaming needs a saved-settings migration) |

**Recommendation:** do X9 before Phase 1 (small next to Phase 1). X10 was first described here as "platform capabilities misplaced in business
domains"; that was incomplete - they are deliberate Settings/Admin switches, and the actual defect (tiles on Overview) is fixed.

## 5. Phases

Each phase lists: goal, milestones, **mock data**, **automated gate**, **exit criteria**, **manual verification**, risks.
Contracts (endpoint names) are proposals encoded in the spec tests; adjust names when designing, keep the assertions.

### Phase 1 - Books & Accounting engine  (domain: Books and Accounting)
**Goal:** sales, purchases, banking and reports all flow through the ledger for every organisation; the legacy tables stop being a source of truth.

| M | Milestone | Notes |
|---|---|---|
| A1 | Legacy money columns -> `NUMERIC(18,2)` | Migration with before/after totals; flips `test_legacy_money_columns_are_numeric` |
| A2 | Sales & Receivables | customers, quotes, tax invoices, credit notes, payments/allocation; posts Dr AR (gross) Cr Revenue (net) Cr GST |
| A3 | Purchases & Payables | suppliers, POs, bills, bill payments, OCR extraction; Dr expense/COGS Dr GST Cr AP |
| A4 | Banking & Reconciliation v2 + **per-organisation classifier** | match feed lines to invoices/bills; the Setup page stops editing global data |
| A5 | Expenses | claims, receipts, reimbursements |
| A6 | Financial reports from the ledger only | P&L, balance sheet, aged receivables/payables, GST summary, cash-flow statement |
| A7 | Retire `transactions`/`accounting_documents` as sources of truth | one-off backfill + reconciliation report |

- **Mock data:** `mockdata/phase1.py` - 6 customers, 7 suppliers, 10 invoices (3 payment patterns), 7 bills, 20 bank lines (14 that must match, 6 that must not). Oracles: invoice journal, aged receivables buckets, bill journal.
- **Automated gate:** `tests/phase1/test_p1_books_specs.py` - oracle self-checks (run today); invoice journal = oracle; aged receivables = oracle (total and buckets); over-allocation rejected; 14/14 matches with 0 false positives; classifier teaching in org A leaves org B unchanged; legacy float columns gone.
- **Exit criteria:** all Phase 1 specs green; Phase 0 suite still green; on a real customer copy, sum of legacy vs ledger balances reconciles to the cent; matching precision >= 95% and zero false positives on a labelled set of >= 500 lines (the 20-line set here is the seed, not the bar).
- **Manual:** `MANUAL_TESTS.md` §Phase 1 (create invoice -> see journal -> receive payment -> aged report -> reconcile a bank line).
- **Risks:** data migration on live floats; classifier privacy (per-org learning must not leak).

### Phase 2 - Payroll & Tax compliance  (Payroll & Workforce; Taxation & Compliance)
**Goal:** correct payroll under current law, and BAS prepared from the ledger. Lodgement only after ATO onboarding.

| M | Milestone | Notes |
|---|---|---|
| B1 | Payroll engine: current-year tax tables (**SG rate already fixed to 12%** in X0; base moves to qualifying earnings under Payday Super), PAYG, payslips, ledger posting (Dr Wages, Cr PAYG payable 825, Cr Super payable 826, Cr Wages payable 804) | tables pinned from ATO; accountant sign-off |
| B2 | Leave & entitlements | accruals, balances, leave loading, payout on termination |
| B3 | STP Phase 2 + **Payday Super** | super due by payday + 7 business days; STP carries qualifying earnings and super liability |
| B4 | PAYG withholding remittance | feeds BAS/IAS |
| C1 | GST / BAS / IAS **preparation** | labels G1, G10, G11, 1A, 1B; review workflow; anomaly review (LLM advises only) |
| C2 | ATO lodgement | **external dependency**: Digital Service Provider onboarding / software ID; feature-flagged off until then |

- **Mock data:** `mockdata/phase2.py` - 8 employees (full-time, part-time, casual; weekly/fortnightly/monthly). Oracles cover gross, super at 12%, net = gross - PAYG. **PAYG oracle is deliberately empty** - `mockdata/golden/payg_2026_27.json` must be filled from ATO worked examples and signed off; the test skips (loudly) until then. BAS oracle for tenant A: G1 19,250; G10 8,800; G11 7,205; 1A 1,750; 1B 1,455; net payable 295 - it reconciles to the Phase 0 GST balance (checked today).
- **Automated gate:** `tests/phase2/test_p2_payroll_tax_specs.py`.
- **Exit criteria:** SG test green; every golden PAYG case exact; super `due` date correct across weekends/public holidays; BAS labels equal the ledger for two quarters of real anonymised data; **no landing-page claim of lodgement/STP until C2/B3 are live** (already enforced).
- **Manual:** `MANUAL_TESTS.md` §Phase 2 (run a pay run, compare payslip to the ATO calculator, view BAS, tick the review checklist).
- **Risks:** regulatory drift (re-verify tables each 1 July); ATO onboarding lead time; tax-agent/BAS-agent obligations if AccFino prepares on behalf of others - get advice before Phase 5b.

### Phase 3 - Assets, inventory & investments  (Assets, Investments & Wealth; Books)
| M | Milestone |
|---|---|
| D1 | Fixed assets: register, straight-line/diminishing value, monthly posting |
| D2 | Inventory & COGS (weighted average first; FIFO optional), stocktakes |
| D3 | Property register, rental income/expenses |
| D4 | CGT engine unified with the ledger (shares, crypto, property; discount rules by entity type) |
| D5 | Funds, bonds, investment portfolio, dividends, corporate actions |
| D6 | Wealth & net worth (from ledger + register) |

- **Mock data:** `mockdata/phase3.py` - roaster (8,000; 120 months; cumulative 200.00 after 3 months, no per-month rounding drift); stock (buy 100@4, 100@6, sell 150 -> COGS 750.00, 50 units / 250.00); shares (cost base 404.00, proceeds 590.00, gain 186.00, 93.00 after 50% discount for an individual; **186.00 for a company**).
- **Automated gate:** `tests/phase3/test_p3_assets_investments_specs.py`. **Exit:** oracles exact; asset register reconciles to ledger control accounts; existing Stock/Crypto/Property pages keep their results (regression fixtures captured before migration).
- **Risks:** migrating existing CGT pages without changing users' historical results.

### Phase 4 - Smart Lending, Credit, Treasury & entity tax
| M | Milestone |
|---|---|
| E1 | Statement analysis (**live** - keep regression fixtures) |
| E2 | Credit assessment & origination workflow |
| E3 | Loan management (amortisation, repayments, leases, hire purchase; principal/interest posting) |
| E4 | Collections (arrears buckets, hardship workflow) |
| E5 | Treasury & liquidity (cash position, facilities, 13-week view) |
| F1 | Income tax for entities (company base-rate 25% vs 30%; trusts, partnerships) |
| F2 | FBT & other taxes |
| F3 | Tax planning (projections; *advice boundary reviewed by a licensed adviser*) |

- **Mock data:** `mockdata/phase4.py` - $100,000 / 6% / 360 months -> payment 599.55, month-1 interest 500.00, closing balance 0.00; three arrears; company tax on 4,950 = 1,237.50.
- **Gate:** `tests/phase4/test_p4_lending_tax_specs.py`. **Exit:** schedule matches oracle to the cent for 5 rate/term combinations; credit decisions are explainable (inputs + rule fired stored) and reproducible.
- **Risks:** responsible-lending obligations if used for actual credit decisions; bias/fairness review of any scoring.

### Phase 5a - Planning & Intelligence
| M | Milestone |
|---|---|
| G1 | Budgeting & forecasting (budget vs actual from ledger) |
| G2 | Scenario planning (read-only sandbox; never writes) |
| G3 | Management reporting / board packs (not the statutory reports - see A6) |
| G4 | CFO insights (trends, benchmarks) |
| G5 | Risk & anomaly detection (duplicates, round sums, new-payee large transfers) |
| G6 | AI financial assistant (tool-calling over report tools; cannot post) |

- **Mock data:** `mockdata/phase5.py` - budget 6,000/month vs actual 8,000/7,500/2,000 (variance +2,000/+1,500/-4,000); scenario revenue -10% -> profit 3,200; 3 injected anomalies.
- **Gate:** `tests/phase5/test_p5_planning_practice_specs.py`. **Exit:** anomaly recall = 100% on injected cases and no high-severity flags on the clean data; every assistant number traceable to a report call; tenant B data never appears in tenant A answers; scenario runs leave the journal count unchanged.

### Phase 5b - Practice & Client Services
| M | Milestone |
|---|---|
| H1 | Practice management (multi-client dashboard) |
| H2 | Clients & entities register |
| H3 | Workpapers & documents (hash-stamped, versioned) |
| H4 | Engagements & workflows (deadlines) |
| H5 | Billing (time -> invoices) |
| H6 | Client portal |

- **Depends on** IAM step 3 (invitations, guest access, groups). **Mock data:** 3 client organisations, an accountant granted 2 of them; time entries 3.5h x 180 + 2h x 220 = 1,070.00.
- **Exit:** the accountant sees exactly the granted clients and revocation is immediate; workpaper hashes verify; billing equals oracle; access to each client is audit-logged.

### Phase 6 - Platform & ecosystem  (Settings / Admin - not business domains)
| M | Milestone |
|---|---|
| P1 | API keys (org-scoped, shown once, revocable) |
| P2 | Webhooks (HMAC-signed, retried with back-off) |
| P3 | Business integrations |
| P4 | IAM step 3: groups, custom roles, invitations/guests, Microsoft/Google sign-in (OIDC) |
| P5 | IAM steps 4-5: identity protection, SAML, SCIM, SIEM export, PIM, access reviews |

Can start earlier in parallel for P4 (Phase 5b depends on it). **Exit:** revoked key -> 401 immediately; webhook signatures verify; OIDC sign-in still enforces the organisation's MFA/IP policy.

## 6. Definition of done for every phase

1. `mockdata/phaseN.py` seeds a deterministic dataset **and** an independent oracle; `python -m mockdata.expected` regenerates `EXPECTED_RESULTS.md`.
2. Acceptance specs turn from *skipped* to *passing* - not deleted, not loosened.
3. At least one negative test per rule, one **mutation check** (break the rule, confirm the test fails), and no regression in earlier phases (full suite in CI).
4. `modules.json` status flipped, release notes written, landing-page claims test green.
5. `MANUAL_TESTS.md` section executed by a person other than the author; results recorded.
6. Regulatory inputs (tax tables, rates, thresholds) cite their ATO source and carry an accountant sign-off date.

## 7. External dependencies and things nobody at the keyboard can decide

- **ATO Digital Service Provider onboarding / software ID** (STP, BAS lodgement) - lead time unknown; blocks C2 and full B3.
- **Accountant sign-off** on PAYG tables and BAS logic; re-verify every 1 July.
- **Open Banking (CDR)**: accreditation or an accredited intermediary - decide before scaling bank feeds.
- **Data residency**: databases are currently in the USA; the landing page correctly makes no AU-hosting claim. Decide before any such claim.
- **Regulated activity**: tax-agent / BAS-agent services, credit assistance and financial advice each have licensing boundaries - get advice before shipping F3, E2 or Phase 5b features that act for others.

## 8. What this audit did not cover

No real browser session (UI behaviour, the login-redirect fix, passkeys with a real authenticator); SMS/email code delivery; Stripe and Open Banking integrations; load, concurrency beyond one worker, or backup/restore; the classifier's accuracy; the ML/OCR pipelines. The Phase 0 suite runs with the per-IP login throttle relaxed (its behaviour was observed - HTTP 429 - but is not asserted).
