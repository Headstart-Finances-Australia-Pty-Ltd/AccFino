# Reconciliation  (`accfino.modules.reconciliation`)

Bank-statement pipeline: parse and normalise statements (CSV, PDF, Open Banking pulls), classify every transaction to a GL account and GST category (ML, then LLM, then RDR rules), review and correct, keep session history, export to Excel. Also owns the company/vendor directory and the dashboard statistics.

| | |
|---|---|
| Backend | `backend/accfino/modules/reconciliation/` |
| Frontend | `frontend/src/modules/reconciliation/` |
| Tests | `python AccFino_Testing/run_tests.py reconciliation`  ->  contract tests only so far (`tests/modules/test_module_contracts.py`) - add a suite in `AccFino_Testing/tests/modules/reconciliation/`; `frontend/src/modules/reconciliation/__tests__/` |
| Owns tables | `chart_of_accounts`, `classifier_cache`, `companies`, `company_aliases`, `knowledge_base`, `rdr_rules`, `reconciliation_sessions`, `session_files`, `transactions`, `account_balances` |
| Data files | `ACCFINO_DATA_ROOT/modules/reconciliation/...` (only through `accfino.shared.paths`) |
| Uses (public facades) | `accounting`, `cashflow` |
| Uses (shared services) | `contracts`, `db`, `llm`, `paths`, `utils` |
| Public API for other modules | `public.py` (backend), `public.js` (frontend, if present) |
| Extra docs | - |

## HTTP API (URL prefixes, route count)
| Prefix | Routes |
|---|---|
| `/account-balances` | 1 |
| `/account-balances/bulk` | 1 |
| `/account-balances/{id}` | 1 |
| `/banks` | 1 |
| `/cashflow/from-db` | 1 |
| `/coa/accounts` | 1 |
| `/company` | 1 |
| `/company/approve` | 1 |
| `/company/capture-who` | 1 |
| `/company/categories` | 1 |
| `/company/list` | 1 |
| `/company/search` | 1 |
| `/company/{id}` | 4 |
| `/dashboard/stats` | 1 |
| `/db/stats` | 1 |
| `/db/transactions` | 1 |
| `/debug/parse-csv` | 1 |
| `/gl/accounts` | 3 |
| `/gst/calculate` | 1 |
| `/gst/categories` | 1 |
| `/kb` | 1 |
| `/kb/keyword` | 2 |
| `/kb/meta` | 1 |
| `/kb/vendor` | 2 |
| `/ml/sample-csv` | 1 |
| `/ml/status` | 1 |
| `/ml/train` | 1 |
| `/profile/home-company` | 2 |
| `/rdr/rules` | 4 |
| `/rdr/test` | 1 |
| `/reconcile/classify` | 1 |
| `/reconcile/export` | 1 |
| `/reconcile/process` | 1 |
| `/reconcile/process-with-session` | 1 |
| `/reconcile/reclassify` | 1 |
| `/sessions` | 1 |
| `/sessions/save` | 1 |
| `/sessions/{id}` | 2 |
| `/transactions` | 1 |
| `/transactions/save` | 1 |
| `/transactions/user` | 1 |
| `/transactions/{id}` | 2 |

## Rules for working here
1. Stay inside this folder. To use another domain, import only `accfino.modules.<other>.public` (the boundary check fails otherwise).
2. New table: model in `models/`, listed in `manifest.py`. New schema/data migration: a function registered in `manifest.py`.
3. Files and documents go to the data root via `accfino.shared.paths` - never next to the code.
4. Add or update the tests for what you change, then run `python AccFino_Testing/run_tests.py reconciliation`.
