# AccFino architecture

AccFino is one product, one UI and one database, organised as a **modular monolith**: a Core, Shared services, and independent business modules.
No microservices. Behaviour, URLs, database tables and screens are unchanged by the restructure (verified, see "Verification").

## Layout

```
backend/accfino/
  app.py  routers.py                composition root - the only files that know every module
  core/                             platform (never imports a module)
    identity/  security/  tenancy/  subscription/  platform_admin/  web/  api/
    models.py  migrate.py  init_db.py  config.py  notifications.py  manifest.py
  shared/                           genuinely shared, business-free
    db/ (engine, Base, money types, known tables)   paths.py (ACCFINO_DATA_ROOT)   llm/ (Groq key pool)
    documents/ (invoice/receipt/bank-PDF extraction)   contracts/ (module registry)   utils/   integrations_store.py
  modules/<name>/                   each owns api/, services, models/, migrations/, manifest.py, public.py
    accounting       ledger, books (sales/purchases/banking), assets, inventory, invoices, legacy accounting documents, reports
    reconciliation   statement pipeline, classification (ML / LLM / RDR), sessions, company directory, GST, account balances
    cashflow         forecasting pipeline
    trading          equity CGT engine, stocks, crypto, property CGT, exporters
    lending          bank-statement serviceability / HEM
    payroll          employees, leave, timesheets, pay runs, PAYG/super engine, payslips, payments, STP structures, reports (see docs/payroll/)
    taxation         tax profile, BAS/IAS, income tax returns, CGT, FBT, Division 7A, compliance calendar, workpapers, audit (see docs/taxation/)
    billing          Square subscription billing, Stripe checkout, payment-gateway configuration
    open_banking     Basiq + OpenFeed (CDR) bank feeds and their platform set-up
frontend/src/
  core/        App shell, Layout, auth, settings, admin, hubs (compose module pages), shared UI/lib, module registry (config/modules.json)
  modules/<name>/{pages, components, lib, public.js}
```

## Dependency rules (enforced by `AccFino_Testing/architecture/check_boundaries.py`, run in CI by `AccFino_Testing/tests/architecture_test.py`)

| Rule | |
|---|---|
| R1 | `shared` imports neither `core` nor `modules` |
| R2 | `core` never imports a module. It learns about modules only through `shared.contracts.registry` (tables, schema hooks, org provisioning, start-up hooks) |
| R3 | a module never imports another module's internals - only `accfino.modules.<other>.public` |
| F1/F2 | the same for the frontend (`modules/<x>/public.js`); `core/App.jsx`, `core/moduleProviders.jsx`, `core/hubs/*` are composition and may import module pages |

Current cross-module links (all through `public`): Accounting → Reconciliation (`Transaction`, `RDRRule`); Reconciliation → Accounting (chart-of-accounts refresh hook),
Reconciliation → Cash Flow (forecast pipeline). Core's Setup/Admin pages embed module panels through the generated `public.js` facades.
The checker reports 0 couplings outside these rules. It fails on any new violation.

## Module registry

Each module has `manifest.py` calling `registry.register(ModuleSpec(...))` to declare: model modules, tables to create, raw-SQL tables, schema hooks (pre / PostgreSQL / post),
per-organisation provisioning (Accounting seeds the chart of accounts + GST codes), plan-rename hooks, immutable-record tables (force delete),
start-up hooks (Billing's renewal loop) and background raw-SQL migrations. Core's own models are registered by `core/manifest.py`.

## Data and documents (mandatory separation)

All persistent business data and documents live in **`ACCFINO_DATA_ROOT`**, outside the application package. Only `accfino/shared/paths.py` knows where.

```
reference/   chart of accounts, knowledge base, RDR rules, pricing, companies, lending rules       (editable at runtime)
config/      integrations.json (may hold credentials)                                              legal/   website legal PDFs
shared/ml_models/  shared/llm_cache/        modules/<module>/...   (trading/{inputs,output,cost_base}, cashflow/outputs, open_banking/exports, ...)
```

* Not set -> `<folder next to AccFino>/AccFino_Data`. Docker/Northflank: mount a volume at `/data`, `ACCFINO_DATA_ROOT=/data` (the image sets it).
* `deploy/data-seed/` holds read-only first-run defaults; `paths.bootstrap_data_root()` copies a file there into the data root only if missing - never overwrites.
* Test datasets: `ACCFINO_TEST_DATA_ROOT` (default `../AccFino_Testing/testdata`).
* Reconciliation session files/uploads, accounting attachments and the ledger are stored in PostgreSQL, as before.

## Adding a module
1. `accfino/modules/<name>/` with `api`, `models`, `manifest.py`, `public.py`; add the name to `registry.MODULE_NAMES`.
2. Register its router in `accfino/app.py` (or `routers.py` for plan-gated ones). 3. Frontend: `modules/<name>/` + `public.js`; add routes in `core/App.jsx`.
4. Run `python AccFino_Testing/architecture/check_boundaries.py`.

## Verification (record of the restructure)
Route table before/after: 565 routes, identical methods and paths, no overlapping route reordered, identical middleware order.
Backend tests (SQLite, offline): same results as the original package apart from the new architecture tests. Frontend: `vite build` OK, vitest same results as the original.
Not verifiable offline: PostgreSQL-only SQL (ledger immutability triggers, `ALTER TABLE ... IF NOT EXISTS`, advisory locks). Run `AccFino_Testing/tests/core/force_delete_pg_test.py` and the ledger tests once against PostgreSQL.

## Migration notes (existing deployments)
* Start command: `python -m uvicorn accfino.app:app` (was `main_app.react_api:app`); DB init: `python -m accfino.core.init_db` (was `db_app.init_db`); `PYTHONPATH=backend`.
* Copy the old data into the new data root before first start: `main_app/data/{ChartOfAccounts.csv,knowledge_base.json,rdr_rules.json,pricing.json,lending_classifications.json}` -> `reference/`,
  `integrations.json` -> `config/`, `legal_documents/` -> `legal/`, `db_app/companies.json` -> `reference/`, `trading/data/local_cost_base_db.json` -> `modules/trading/cost_base/`,
  `cash_flow/outputs/` -> `modules/cashflow/outputs/`, `main_app/classifier_model/*.pkl` -> `shared/ml_models/`, `ollama_cache.json` -> `shared/llm_cache/`.
  (`AccFino_Data/` in this delivery already contains the files that shipped in the package.)
* Database schema, table names, URLs and the browser UI are unchanged. The reference-data tables are re-synced from the data root files exactly as before.
* Dropped as dead code (not imported or mounted anywhere): `react_api_helpers.py`, `db_app/api/invoice_api.py`, `main_app/data/api_call.py`; seven unreferenced pages, a duplicate `SetupPage.jsx`, the superseded `llm/_legacy` classifier versions and the one-off session backfill tool were removed (recoverable from the original package).


---

# Platform design notes

## Module registry (frontend) - one list drives navigation, Home and the landing page
`frontend/src/core/config/modules.json` lists every module: domain, route, tab, icons, plan (licence) key,
status (`live`, `beta`/preview, `planned`/soon), whether it appears in the side panel, and its descriptions.

| Surface | Built from the registry |
|---|---|
| Side panel | Domains in order; live and "Soon" entries (`nav: true`); plan locks |
| In-app Home | Every domain and module with Live / Preview / Soon status |
| Public landing page | Live and preview modules only (served as `/modules.json`) |

Domains (stable - new modules are added inside them, not new top-level areas): Books and Accounting - Payroll & Workforce - Taxation & Compliance - Assets, Investments & Wealth - Smart Lending, Credit & Treasury - Planning & Intelligence - Practice & Client Services. Account/platform concerns (Security, Open Banking, Integrations, API & Webhooks) live in **Settings**; AccFino-team tools (ML, licences, data, pricing, modules, users) in **Admin**. Which domains/modules are switched on is an admin setting (`/module-visibility`) applied to the side panel, hub tabs, Overview and the landing page. Delivery sequence and gates: `docs/ROADMAP.md`.
Tax logic (e.g. CGT) belongs to Tax & Compliance; assets provide the source transactions.

**Release rule:** every change that adds a page or changes what a module can do must update `modules.json`
and the release notes; landing-page wording is reviewed against the registry. The `test_registry_sync.py`
tests (AccFino_Testing) fail if a page is missing from the registry, a side-panel link or tab doesn't exist,
the landing page isn't registry-driven, or the landing page makes a claim (lodgement, STP, "ATO compliant",
AU hosting) before the matching module is live.

## Layering rules (all new work)
1. **API layer** (`accfino/core/api`, `accfino/modules/*/api`) - validation, permissions, HTTP only. No business rules.
2. **Services / pipelines** (`accfino_core/ledger`, `security`, …) - business rules; the only code that writes financial data.
3. **Models** (`accfino/core/models.py`, `accfino/modules/accounting/models/ledger.py`) - organisation-scoped tables; money as NUMERIC.
4. **Frontend** talks to the backend only through `frontend/src/lib/*Api.js`.

## LangChain pipelines (per docs/design/AccfinoAgent.docx)
The design brief asks for backend processing to be expressed as LangChain pipelines/agents invoked by API
endpoints. Migration plan - one pipeline at a time, each behind the existing regression tests:

| Pipeline | Current code | LangChain form | Phase |
|---|---|---|---|
| Bank statement → normalised transactions | `accfino/modules/reconciliation/pipeline` | `RunnableSequence`: parse → normalise → dedupe | 1 |
| Transaction classification (ML → LLM → RDR rules) | `accfino/modules/reconciliation/classification`, `llm_classifier` | `RunnableBranch` with LLM via `langchain-groq` / `langchain-ollama` | 1 |
| Reconciliation → ledger posting | `accfino/modules/accounting/ledger/bank_sync.py` | `RunnableSequence`: load → build lines → validate → post | 1 |
| Invoice / receipt extraction | `accfino/shared/documents/invoice_extractor.py` | document loader → structured-output chain | 1 |
| BAS preparation & review | new | chain over ledger queries + LLM anomaly review | 2 |
| Month-end close assistant | new | tool-calling agent over ledger/report tools | 5 |

Deterministic accounting rules (posting, GST maths, validation) stay plain Python inside the pipeline
steps; LangChain orchestrates the steps and the LLM calls. No LLM ever writes to the ledger directly.
