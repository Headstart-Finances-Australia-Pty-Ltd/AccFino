# Lending  (`accfino.modules.lending`)

Smart Lending: analyses bank statements for serviceability. Classifies spending (HEM groups), computes metrics (DTI, buffers), detects statement gaps and de-duplicates uploads.

| | |
|---|---|
| Backend | `backend/accfino/modules/lending/` |
| Frontend | `frontend/src/modules/lending/` |
| Tests | `python AccFino_Testing/run_tests.py lending`  ->  contract tests only so far (`tests/modules/test_module_contracts.py`) - add a suite in `AccFino_Testing/tests/modules/lending/`; no UI tests yet |
| Owns tables | `lending_classifications` |
| Data files | `ACCFINO_DATA_ROOT/modules/lending/...` (only through `accfino.shared.paths`) |
| Uses (public facades) | none |
| Uses (shared services) | `contracts`, `db`, `documents`, `paths` |
| Public API for other modules | none yet - add `public.py` only when another module genuinely needs something |
| Extra docs | - |

## HTTP API (URL prefixes, route count)
| Prefix | Routes |
|---|---|
| `/lending/analyse` | 1 |
| `/lending/categories` | 1 |
| `/lending/classify` | 1 |
| `/lending/regulatory` | 1 |
| `/lending/upload` | 1 |
| `/lending/upload-multi` | 1 |

## Rules for working here
1. Stay inside this folder. To use another domain, import only `accfino.modules.<other>.public` (the boundary check fails otherwise).
2. New table: model in `models/`, listed in `manifest.py`. New schema/data migration: a function registered in `manifest.py`.
3. Files and documents go to the data root via `accfino.shared.paths` - never next to the code.
4. Add or update the tests for what you change, then run `python AccFino_Testing/run_tests.py lending`.
