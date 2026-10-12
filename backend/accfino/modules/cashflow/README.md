# Cash Flow  (`accfino.modules.cashflow`)

Cash-flow forecasting: detects the columns of uploaded transactions, trains a model leaderboard and predicts next month. Outputs go to the data root.

| | |
|---|---|
| Backend | `backend/accfino/modules/cashflow/` |
| Frontend | `frontend/src/modules/cashflow/` |
| Tests | `python AccFino_Testing/run_tests.py cashflow`  ->  contract tests only so far (`tests/modules/test_module_contracts.py`) - add a suite in `AccFino_Testing/tests/modules/cashflow/`; no UI tests yet |
| Owns tables | none |
| Data files | `ACCFINO_DATA_ROOT/modules/cashflow/...` (only through `accfino.shared.paths`) |
| Uses (public facades) | none |
| Uses (shared services) | `contracts`, `paths` |
| Public API for other modules | `public.py` (backend), `public.js` (frontend, if present) |
| Extra docs | - |

## HTTP API (URL prefixes, route count)
| Prefix | Routes |
|---|---|
| `/cashflow/detect` | 1 |
| `/cashflow/predict` | 1 |
| `/cashflow/run` | 1 |

## Rules for working here
1. Stay inside this folder. To use another domain, import only `accfino.modules.<other>.public` (the boundary check fails otherwise).
2. New table: model in `models/`, listed in `manifest.py`. New schema/data migration: a function registered in `manifest.py`.
3. Files and documents go to the data root via `accfino.shared.paths` - never next to the code.
4. Add or update the tests for what you change, then run `python AccFino_Testing/run_tests.py cashflow`.
