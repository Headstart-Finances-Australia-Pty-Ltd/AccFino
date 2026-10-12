# Billing & Payments  (`accfino.modules.billing`)

Subscription billing: Square card-on-file and automatic renewals, Stripe checkout and webhooks, platform payment-gateway configuration and billing history.

| | |
|---|---|
| Backend | `backend/accfino/modules/billing/` |
| Frontend | `frontend/src/modules/billing/` |
| Tests | `python AccFino_Testing/run_tests.py billing`  ->  `AccFino_Testing/tests/modules/billing/`; `frontend/src/modules/billing/__tests__/` |
| Owns tables | `billing_charges`, `org_billing` |
| Data files | `ACCFINO_DATA_ROOT/modules/billing/...` (only through `accfino.shared.paths`) |
| Uses (public facades) | none |
| Uses (shared services) | `contracts`, `db`, `integrations_store`, `paths` |
| Public API for other modules | none yet - add `public.py` only when another module genuinely needs something |
| Extra docs | [SETUP.md](SETUP.md) - provider set-up |

## HTTP API (URL prefixes, route count)
| Prefix | Routes |
|---|---|
| `/admin/billing` | 5 |
| `/bank-account/config` | 1 |
| `/bank-account/status` | 1 |
| `/org/current` | 5 |
| `/payments/activate-after-payment` | 1 |
| `/payments/admin` | 1 |
| `/payments/create-checkout` | 1 |
| `/payments/my-plan` | 1 |
| `/payments/plans` | 1 |
| `/payments/webhook` | 1 |
| `/square/config` | 1 |
| `/square/status` | 1 |
| `/stripe/config` | 1 |
| `/stripe/status` | 1 |

## Rules for working here
1. Stay inside this folder. To use another domain, import only `accfino.modules.<other>.public` (the boundary check fails otherwise).
2. New table: model in `models/`, listed in `manifest.py`. New schema/data migration: a function registered in `manifest.py`.
3. Files and documents go to the data root via `accfino.shared.paths` - never next to the code.
4. Add or update the tests for what you change, then run `python AccFino_Testing/run_tests.py billing`.
