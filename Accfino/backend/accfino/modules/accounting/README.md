# Books & Accounting  (`accfino.modules.accounting`)

Double-entry general ledger, sales and purchases (invoices, bills, quotes, credit notes, payments), banking and matching of bank lines to documents, expenses, fixed assets, inventory, financial reports and GST/BAS, CSV import, and the AI journal assistant. The ledger is the only write path for financial data.

| | |
|---|---|
| Backend | `backend/accfino/modules/accounting/` |
| Frontend | `frontend/src/modules/accounting/` |
| Tests | `python AccFino_Testing/run_tests.py accounting`  ->  `AccFino_Testing/tests/modules/accounting/`; `frontend/src/modules/accounting/__tests__/` |
| Owns tables | `accounting_customers`, `accounting_documents`, `accounting_line_items`, `accounting_suppliers`, `allocations`, `asset_depreciation_runs`, `attachments`, `bank_lines`, `bank_rules`, `business_details`, `classifier_memory`, `contacts`, `customers`, `doc_lines`, `doc_sequences`, `docs`, `expense_claims`, `expense_items`, `fixed_assets`, `invoice_items`, `invoices`, `journal_lines`, `journals`, `ledger_accounts`, `ledger_fx_rates`, `ledger_journal_drafts`, `ledger_repeating_journals`, `ledger_source_links`, `legacy_links`, `org_budget_lines`, `payments`, `stock_items`, `stock_movements`, `tax_codes`, `tracking_categories`, `tracking_options`, `accounting_customers`, `accounting_documents`, `accounting_line_items`, `accounting_suppliers` |
| Data files | `ACCFINO_DATA_ROOT/modules/accounting/...` (only through `accfino.shared.paths`) |
| Uses (public facades) | `reconciliation` |
| Uses (shared services) | `contracts`, `db`, `documents`, `llm`, `paths` |
| Public API for other modules | `public.py` (backend), `public.js` (frontend, if present) |
| Extra docs | [docs/](docs/) - CSV_IMPORT.md, DEMO_DATA.md |

## HTTP API (URL prefixes, route count)
| Prefix | Routes |
|---|---|
| `/accounting/customers` | 5 |
| `/accounting/documents` | 6 |
| `/accounting/purchase` | 1 |
| `/accounting/stats` | 1 |
| `/accounting/suppliers` | 5 |
| `/admin/books` | 5 |
| `/admin/bulk-import` | 2 |
| `/assets` | 2 |
| `/assets/control` | 1 |
| `/assets/depreciation` | 1 |
| `/assets/register` | 1 |
| `/assets/{id}` | 4 |
| `/attachments` | 2 |
| `/attachments/{id}` | 2 |
| `/banking/accounts` | 2 |
| `/banking/classifier` | 4 |
| `/banking/lines` | 8 |
| `/banking/reconcile` | 2 |
| `/banking/reconciliation` | 1 |
| `/banking/rules` | 4 |
| `/books/legacy` | 4 |
| `/contacts` | 1 |
| `/contacts/import` | 1 |
| `/expenses/claims` | 10 |
| `/expenses/summary` | 1 |
| `/imports` | 1 |
| `/imports/status` | 1 |
| `/imports/{id}` | 2 |
| `/inventory/control` | 1 |
| `/inventory/items` | 7 |
| `/inventory/movements` | 2 |
| `/inventory/valuation` | 1 |
| `/invoice` | 2 |
| `/invoice-extractor/process` | 1 |
| `/invoice-extractor/status` | 1 |
| `/invoice/business` | 5 |
| `/invoice/next-number` | 1 |
| `/invoice/{id}` | 2 |
| `/ledger/account-types` | 1 |
| `/ledger/accounts` | 3 |
| `/ledger/ai` | 3 |
| `/ledger/fx` | 4 |
| `/ledger/fx-feed` | 2 |
| `/ledger/fx-rate` | 1 |
| `/ledger/fx-rates` | 3 |
| `/ledger/journal-drafts` | 9 |
| `/ledger/journal-import` | 2 |
| `/ledger/journal-preview` | 1 |
| `/ledger/journal-settings` | 2 |
| `/ledger/journal-sources` | 1 |
| `/ledger/journal-suggestions` | 1 |
| `/ledger/journals` | 5 |
| `/ledger/ledger-health` | 1 |
| `/ledger/repeating-journals` | 5 |
| `/ledger/reports` | 23 |
| `/ledger/scheduler-status` | 1 |
| `/ledger/sync` | 1 |
| `/ledger/tax-codes` | 1 |
| `/ledger/tracking-categories` | 3 |
| `/org/current` | 4 |
| `/purchases/bills` | 10 |
| `/purchases/credits` | 11 |
| `/purchases/orders` | 12 |
| `/purchases/payments` | 5 |
| `/purchases/reports` | 4 |
| `/purchases/suppliers` | 4 |
| `/reports/aged-receivables` | 1 |
| `/reports/balance-sheet` | 1 |
| `/reports/profit-loss` | 1 |
| `/sales/credit-notes` | 11 |
| `/sales/customers` | 4 |
| `/sales/invoices` | 10 |
| `/sales/payments` | 5 |
| `/sales/quotes` | 12 |
| `/sales/reports` | 4 |

## Rules for working here
1. Stay inside this folder. To use another domain, import only `accfino.modules.<other>.public` (the boundary check fails otherwise).
2. New table: model in `models/`, listed in `manifest.py`. New schema/data migration: a function registered in `manifest.py`.
3. Files and documents go to the data root via `accfino.shared.paths` - never next to the code.
4. Add or update the tests for what you change, then run `python AccFino_Testing/run_tests.py accounting`.
