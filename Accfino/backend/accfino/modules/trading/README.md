# Trading / Capital Gains  (`accfino.modules.trading`)

Capital-gains tax for shares and ETFs (FIFO lot matching, cost base history), crypto trading analysis, property CGT, tax-return data and the Excel CGT report.

| | |
|---|---|
| Backend | `backend/accfino/modules/trading/` |
| Frontend | `frontend/src/modules/trading/` |
| Tests | `python AccFino_Testing/run_tests.py trading`  ->  contract tests only so far (`tests/modules/test_module_contracts.py`) - add a suite in `AccFino_Testing/tests/modules/trading/`; no UI tests yet |
| Owns tables | `trading_cost_base` |
| Data files | `ACCFINO_DATA_ROOT/modules/trading/...` (only through `accfino.shared.paths`) |
| Uses (public facades) | none |
| Uses (shared services) | `contracts`, `db`, `paths` |
| Public API for other modules | none yet - add `public.py` only when another module genuinely needs something |
| Extra docs | - |

## HTTP API (URL prefixes, route count)
| Prefix | Routes |
|---|---|
| `/stocks/analyze` | 1 |
| `/stocks/export` | 1 |
| `/stocks/status` | 1 |
| `/trading/analyze` | 1 |
| `/trading/export` | 1 |

## Rules for working here
1. Stay inside this folder. To use another domain, import only `accfino.modules.<other>.public` (the boundary check fails otherwise).
2. New table: model in `models/`, listed in `manifest.py`. New schema/data migration: a function registered in `manifest.py`.
3. Files and documents go to the data root via `accfino.shared.paths` - never next to the code.
4. Add or update the tests for what you change, then run `python AccFino_Testing/run_tests.py trading`.
