# Open Banking  (`accfino.modules.open_banking`)

Live bank feeds: Basiq and OpenFeed (CDR) connections, consent flow, account selection and period pulls, plus the administrator's provider set-up.

| | |
|---|---|
| Backend | `backend/accfino/modules/open_banking/` |
| Frontend | `frontend/src/modules/open_banking/` |
| Tests | `python AccFino_Testing/run_tests.py open_banking`  ->  `AccFino_Testing/tests/modules/open_banking/`; `frontend/src/modules/open_banking/__tests__/` |
| Owns tables | `openfeed_connections`, `openfeed_flows` |
| Data files | `ACCFINO_DATA_ROOT/modules/open_banking/...` (only through `accfino.shared.paths`) |
| Uses (public facades) | none |
| Uses (shared services) | `contracts`, `db`, `integrations_store`, `paths`, `utils` |
| Public API for other modules | none yet - add `public.py` only when another module genuinely needs something |
| Extra docs | [SETUP.md](SETUP.md) - provider set-up |

## HTTP API (URL prefixes, route count)
| Prefix | Routes |
|---|---|
| `/admin/open-banking` | 3 |
| `/open-banking/openfeed` | 3 |
| `/openbanking/accounts` | 1 |
| `/openbanking/create-user` | 1 |
| `/openbanking/fetch-and-normalise` | 1 |
| `/openbanking/pull` | 1 |
| `/openbanking/reconcile-accounts` | 1 |
| `/openbanking/saved-accounts` | 2 |
| `/openbanking/status` | 1 |
| `/openbanking/transactions` | 1 |
| `/openfeed/config` | 1 |
| `/openfeed/keys` | 1 |
| `/openfeed/public-key` | 1 |
| `/openfeed/status` | 1 |
| `/openfeed/test` | 1 |
| `/org/current` | 6 |

## Rules for working here
1. Stay inside this folder. To use another domain, import only `accfino.modules.<other>.public` (the boundary check fails otherwise).
2. New table: model in `models/`, listed in `manifest.py`. New schema/data migration: a function registered in `manifest.py`.
3. Files and documents go to the data root via `accfino.shared.paths` - never next to the code.
4. Add or update the tests for what you change, then run `python AccFino_Testing/run_tests.py open_banking`.
