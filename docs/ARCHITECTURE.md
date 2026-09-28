# AccFino architecture

```
AccFino/
├── backend/                     Python 3.11 · FastAPI · SQLAlchemy · PostgreSQL
│   ├── accfino_core/            Platform core (Phase 0+): new code lives here
│   │   ├── api/                 HTTP routers (auth ext, MFA, org, ledger, audit, admin)
│   │   ├── security/            tokens, auth guard middleware, MFA, passkeys, messaging, audit
│   │   ├── ledger/              double-entry posting service, reports, bank sync
│   │   ├── coa/                 Australian chart of accounts + GST tax codes
│   │   ├── models.py            organisations, IAM, ledger tables
│   │   ├── migrate.py           idempotent migration + PostgreSQL integrity triggers
│   │   └── config.py            environment settings
│   ├── db_app/                  legacy data layer & routers (users, transactions, accounting docs, payroll…)
│   ├── main_app/                legacy application: react_api.py (FastAPI app), ML/LLM classifiers, pipelines
│   └── requirements.txt
├── frontend/                    React 18 · Vite
│   └── src/{pages,components,hooks,lib,styles}
├── deploy/entrypoint.sh         container start (init DB → uvicorn)
├── scripts/windows/             start.cmd / stop.cmd for local Windows development (reads .env)
├── docs/                        architecture, security, IAM roadmap, per-phase release notes
├── Dockerfile · docker-compose.yml · northflank.yml · .env.example
```

Tests, test data and test-case documents are deliberately **outside** this package, in the
separate `AccFino_Testing/` folder, so the deployable package contains only application code.

## Module registry - one list drives navigation, Home and the landing page
`frontend/src/config/modules.json` lists every module: domain, route, tab, icons, plan (licence) key,
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
1. **API layer** (`accfino_core/api`) - validation, permissions, HTTP only. No business rules.
2. **Services / pipelines** (`accfino_core/ledger`, `security`, …) - business rules; the only code that writes financial data.
3. **Models** (`accfino_core/models.py`) - organisation-scoped tables; money as NUMERIC.
4. **Frontend** talks to the backend only through `frontend/src/lib/*Api.js`.

## LangChain pipelines (per docs/design/AccfinoAgent.docx)
The design brief asks for backend processing to be expressed as LangChain pipelines/agents invoked by API
endpoints. Migration plan - one pipeline at a time, each behind the existing regression tests:

| Pipeline | Current code | LangChain form | Phase |
|---|---|---|---|
| Bank statement → normalised transactions | `main_app/backend/reconciliation` | `RunnableSequence`: parse → normalise → dedupe | 1 |
| Transaction classification (ML → LLM → RDR rules) | `main_app/backend/classifier`, `llm_classifier` | `RunnableBranch` with LLM via `langchain-groq` / `langchain-ollama` | 1 |
| Reconciliation → ledger posting | `accfino_core/ledger/bank_sync.py` | `RunnableSequence`: load → build lines → validate → post | 1 |
| Invoice / receipt extraction | `main_app/backend/invoice_extractor` | document loader → structured-output chain | 1 |
| BAS preparation & review | new | chain over ledger queries + LLM anomaly review | 2 |
| Month-end close assistant | new | tool-calling agent over ledger/report tools | 5 |

Deterministic accounting rules (posting, GST maths, validation) stay plain Python inside the pipeline
steps; LangChain orchestrates the steps and the LLM calls. No LLM ever writes to the ledger directly.
