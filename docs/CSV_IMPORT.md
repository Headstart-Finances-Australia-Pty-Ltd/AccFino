# CSV import and mock data — how to load it and review performance

This pack adds **Import CSV** buttons to every list in *Books and Accounting*, and ships a complete, consistent set of mock-data CSV files
(`mockdata/csv/`) for a fictional Sydney IT-services and hardware-reselling company (GST-registered, June year end).

Everything you import goes through the same code as typing it in by hand, so each invoice, bill, receipt, claim, stock movement and asset
**posts to the general ledger** and shows up in the reports.

---

## 1. What changed in the app

| Where (Books and Accounting →) | New button | Importer |
|---|---|---|
| Ledger → Journals | *Import* (already existed) | journals (check first, all-or-nothing) |
| Sales → Customers | **Import CSV** | `customers` |
| Sales → Invoices / Quotes / Credit Notes | **Import CSV** | `invoices` / `quotes` / `credit_notes` |
| Sales → **Receipts** (new tab) | **Import CSV** | `receipts` (money received, allocated to invoices) |
| Purchases → Suppliers | **Import CSV** | `suppliers` |
| Purchases → Bills / Purchase Orders / Supplier Credits | **Import CSV** | `bills` / `purchase_orders` / `supplier_credits` |
| Purchases → **Payments** (new tab) | **Import CSV** | `supplier_payments` |
| Expenses | **Import CSV** | `expense_claims` |
| Inventory | **Import items**, **Import movements** | `inventory_items`, `stock_movements` |
| Fixed Assets | **Import CSV** | `fixed_assets` |
| Banking (existing) | Import statement | bank statement lines |

Every import window works the same way: **Download template → choose file → Check file → Import.**
*Check file* runs the complete import inside a transaction and rolls it back, so what it tells you is exactly what the real run will do.
If any record has a problem **nothing is saved** and every problem is listed with its row number. "Show columns" lists every column and what it means.

### ⚠ Important: Sales and Purchases now open the ledger-connected screens
In the pack you sent, the **Sales** and **Purchases** tabs were still the *original* screens, which save to the old `accounting_documents`
table. No report reads that table (Profit & Loss, Balance Sheet, Aged Receivables, GST/BAS all read the ledger), so anything loaded there
could never be reviewed. The ledger-connected screens (`SalesPurchasesPage`, already in the code and covered by your tests) were simply not mounted.

I mounted them as the default. The original screens are **not removed**: tick *"Show legacy records"* at the top of the Sales or Purchases tab
(this keeps the OCR *Upload & Extract* and the old purchase-order list reachable). To undo the change, revert the two lines in
`frontend/src/pages/accounting/AccountingPage.jsx` that render `LedgerOrLegacy`.

*Receipts* in the ledger model are customer payments. A purchase "receipt" (proof of payment) is a **bill plus a supplier payment**, which is why Purchases has a *Payments* tab.

### Switching bulk import on or off (Admin Console)
**Admin → Modules Management → Platform features → "Bulk data import (CSV upload)"** is a checkbox (active by default). It saves the moment you click it.
When **unticked (inactive)**: every Import button is hidden for all users (customers, suppliers, quotes, invoices, credit notes, receipts, purchase orders, bills, supplier payments,
claims, inventory, assets, journals, chart of accounts and bank statement), and the server refuses the uploads (*"Bulk data import has been switched off by your platform administrator"*),
so it cannot be bypassed by calling the API. Data already imported is untouched. The change is written to the audit log.
(The legacy pre-ledger *Show legacy records* screens have their own older CSV buttons, which this switch does not control.)

---

## 2. Install the update

1. Unzip `AccFino_CSV_Import_Update.zip` **over** your `AccFino` folder (it only adds/replaces the files listed in `CHANGED_FILES.txt`).
2. Restart: `app.cmd` (Windows) or `docker compose up --build`. The frontend must be rebuilt (Docker does this; locally `cd frontend && npm run build`).
3. No database migration is needed.

---

## 3. Prepare a clean test organisation

Use a **new organisation** so the mock data never mixes with real records (the importers only create new records, so re-loading into the
same organisation is refused with "already exists"; to start over, create another organisation).

1. Sign in (Owner or Admin role — approving claims and posting journals need it) and create/switch to a new organisation.
   It is seeded with the Australian chart of accounts and GST codes automatically. Leave *GST registered: yes*, year end **June**, and **no lock date**.
2. **Banking → add a bank account**: code **`090`**, name *Business Cheque Account*, type *Bank*.
   (If you use a different code, regenerate the files: `python mockdata/generate_mock_data.py --bank-code 091`.)

---

## 4. Load the data — in this order

Order matters: later files refer to earlier ones (invoices need customers, receipts need invoices, assets need their cost in the ledger).
Files are numbered in the order to load them.

| # | File | Go to | Records | What it demonstrates |
|---|---|---|---|---|
| 1 | `01_customers.csv` | Sales → Customers → Import CSV | 12 | valid ABNs, terms, credit limits |
| 2 | `02_suppliers.csv` | Purchases → Suppliers → Import CSV | 14 | landlord, telco, contractors, insurer… |
| 3 | `03_journals.csv` | Ledger → Journals → **Import**, *Import as: Posted journals* | 104 | opening balances, pay runs (PAYG + super), loan, prepayment releases, prior-year depreciation, BAS / PAYG / super payments, bank fees, interest, dividend, director's loan, tax provision |
| 4 | `04_inventory_items.csv` | Inventory → Import items | 6 | stock items with opening stock |
| 5 | `05_quotes.csv` | Sales → Quotes → Import CSV | 16 | draft / sent / accepted / declined |
| 6 | `06_invoices.csv` | Sales → Invoices → Import CSV (*Approved*) | 180 | services + products, retainers, GST-free lines, tax-inclusive invoices, 2 drafts |
| 7 | `07_credit_notes.csv` | Sales → Credit Notes → Import CSV | 4 | 3 applied to invoices, 1 left for you to allocate |
| 8 | `08_receipts.csv` | Sales → Receipts → Import CSV | 149 | full, part, late, multi-invoice and over-payments |
| 9 | `09_purchase_orders.csv` | Purchases → Purchase Orders → Import CSV | 12 | approved and draft POs |
| 10 | `10_bills.csv` | Purchases → Bills → Import CSV (*Approved*) | 119 | recurring rent/telco/software, quarterly items, prepaid insurance, 2 asset purchases |
| 11 | `11_supplier_credits.csv` | Purchases → Supplier Credits → Import CSV | 2 | one applied, one left to allocate |
| 12 | `12_supplier_payments.csv` | Purchases → Payments → Import CSV | 113 | on time, late, part-paid, unpaid (overdue) |
| 13 | `13_fixed_assets.csv` | Fixed Assets → Import CSV | 7 | straight-line and diminishing value, a disposal |
| 14 | `14_expense_claims.csv` | Expenses → Import CSV | 10 | every status, mileage, GST-free item |
| 15 | `15_stock_movements.csv` | Inventory → Import movements | 84 | reorders, sales at average cost, stocktake adjustments |
| 16 | `16_bank_statement_090.csv` | Banking → import statement for account 090 | 356 | adoption, matching, unreconciled lines |

Tips
* At each step press **Check file** first. The summary shows the total value, and warnings (for example *"New customer … will be created"*).
* For invoices and bills leave *Import as: Approved (posts to the ledger)*; choosing *Drafts for review* loads them unposted.
* File 13 (assets) and files 4 / 15 (stock) show a warning if the ledger does not yet agree with the register; loading in the numbered order avoids it (the two asset purchases arrive through the bills in file 10).

### After loading
1. **Fixed Assets → Run depreciation to today.** Posts Jul–Sep 2026 for 6 assets (the mock data already contains last financial year's depreciation in the journals).
2. **Banking → Reconciliation → Auto-reconcile** on account 090. It clears **262** lines and leaves exactly **6** statement-only lines (Woolworths, Adobe, Stripe payout, BP, Australia Post, cafe) for you to code — that is the deliberate "to-do" list.
3. **Reports → Budget Variance → generate a budget** from last year if you want to see budget vs actual (the files do not include budgets).
4. Expense claims: open a **draft** claim (CLM-009, CLM-010), attach a receipt, submit it; approve the **submitted** ones (CLM-006, CLM-007); reimburse the **approved** ones (CLM-004, CLM-005). Drafts with GST receipts over $82.50 are deliberate — the ATO rule requires the tax invoice to be attached before submitting.
5. Sales → Quotes: open an *accepted* quote → **Convert to Invoice**. Purchases → Purchase Orders: **Convert to Bill**.
6. Sales → Credit Notes: open the unapplied credit note → **Allocate**. Same for the unapplied supplier credit.

---

## 5. Review performance — where to look and what you should see

Open **Books and Accounting → Reports**. Figures below are for the shipped files, "as at 30 Sep 2026", after *Run depreciation*.
(If you regenerate with a different `--today`, the figures change but the checks stay the same.)

| Question | Report | What to expect |
|---|---|---|
| Was last year profitable? | **Profit & Loss** 1 Jul 2025 – 30 Jun 2026 | Income **$563,387**, gross profit **$445,880**, expenses **$356,815**, net profit **$74,651** |
| How is this year going? | **Profit & Loss** 1 Jul – 30 Sep 2026 | Income **$166,555**, net profit **$47,053** |
| Trend and KPIs at a glance | **Executive Summary**, **Management Report** | cash, profit, balance sheet and ageing in one view |
| Financial position | **Balance Sheet** 30 Sep 2026 | total assets ≈ **$320,810**, liabilities ≈ **$79,486**, net assets ≈ **$241,324** |
| Who owes us, and how late? | **Aged Receivables** | total **$127,056** across current, 1–30, 31–60 and 90+ (Coastal Builders $44.2k and Blue Mountains Tourism $30.3k are the big slow payers) |
| Who do we owe? | **Aged Payables** | total **$21,551**; Codeforge, Spark Digital and Paper & Pixel have deliberately overdue bills, and CloudSoft shows an unapplied credit |
| Who are the best customers / biggest suppliers? | **Sales by Customer**, **Purchases by Supplier** | |
| What do we owe the ATO? | **GST / BAS** 1 Jul – 30 Sep 2026 | 1A **$16,655.53**, 1B **$8,919.10**, net payable **$7,736.43** |
| Stock position | **Inventory Item Details**; Inventory page | stock value **$22,084.62**, matches the ledger |
| Assets | Fixed Assets page; **Sub-ledger Control Check** | cost **$115,750**, accumulated depreciation **$28,555**, book value **$87,195**; register agrees with the ledger |
| Expenses | **Expense Claims** | draft 2 ($878.00), submitted 2 ($137.60), approved 2 ($233.75), paid 3 ($593.80), rejected 1 ($44.00) |
| Cash | **Cash Summary**, **Cash Flow Statement**, **Bank Reconciliation** | statement explains the ledger (difference $0.00) |
| Is the data sound? | **Trial Balance**, **Sub-ledger Control Check**, **Cash Validation** | debits = credits; AR and AP agree with their control accounts |
| Every posting | **General Ledger (detailed)**, **Journal Report** | filter by account, party, source |

Things worth investigating as a reviewer: slow-paying customers (collections), the gross margin on product vs service revenue, the loss on the plotter
disposal (−$640), the PAYG and super still owing at 30 Sep, and the unapplied credits.

> **Note — the Accounting Dashboard tab** reads the legacy statistics table, so it will not reflect this data. Use Reports.

### Known behaviour to be aware of
* **GST/BAS "ledger check" shows a difference** for the current year (−$7,943.50 in the shipped data: it equals the quarterly BAS payments dated in the period). The check only
  excludes BAS payments created through the BAS workflow; ones entered as manual journals (which is what a CSV journal is) look like "GST posted without a tax code".
  Every other control passes. This is pre-existing behaviour of that check, not a data problem.
* Claimant names in expense claims are stored as text; the claims belong to the user who imported them (they appear under *My claims only*).
* The register never posts an asset's cost (by design) — that is why the opening-balance journal and the two asset bills are in the pack.

---

## 6. If a check fails — common messages

| Message | Fix |
|---|---|
| *missing required column(s)* | use **Download template**; headers are matched by name, in any order (aliases such as `Quantity`, `Unit Amount`, `Due` work) |
| *Customer 'X' does not exist* (receipts) | load customers and invoices first |
| *Over-allocation: … exceeds what is still owing* | the invoice/bill is already paid or credited; receipts/payments cannot exceed the balance |
| *Bank account … not found* / *bank_account is required* | add the bank account (code 090) in Banking, or set `bank_account` in the file |
| *… already exists* | that number/SKU was already loaded (imports only create new records; contacts are updated) |
| *possible duplicate bill* | the same supplier + reference was already entered (duplicate protection) |
| *on or before the lock date* | remove/adjust the organisation's lock date, or change the dates |
| *Attach the tax invoice / receipt before submitting* | import the claim as `draft`, attach the receipt in the app, then submit |
| *cannot approve your own claim* | only an Owner/Admin may approve a claim imported under their own user |
| *Only N units … on hand* | stock movements are applied in date order; a sell cannot exceed stock |
| *not a valid ABN* | ABNs must pass the ATO checksum |

---

## 7. Generating fresh or different mock data

```
python mockdata/generate_mock_data.py                        # 1 Jul 2025 → 30 Sep 2026 into mockdata/csv/
python mockdata/generate_mock_data.py --today 2026-12-31     # any "as at" date (starts 1 July of the previous financial year)
python mockdata/generate_mock_data.py --bank-code 091        # a different operating bank account code
```
No database or packages are needed. The same inputs always produce the same files.

## 8. Tests

```
cd backend && PYTHONPATH=. python -m pytest ../AccFino_Testing_additions/csv_import_test.py -q     # 18 tests, offline (SQLite)
PYTHONPATH=. python ../AccFino_Testing_additions/csv_import_harness.py                              # loads all files and prints the app's own control checks
cd frontend && npx vitest run                                                                        # 172 tests including the import window, every button and the admin switch
```
The backend tests load the full mock data set into a fresh organisation and run the application's own reconciliation checks (trial balance, balance sheet,
AR/AP, cash flow, inventory, fixed assets, PAYG, bank). The importer itself is `backend/accfino_core/books/csv_import.py`; the endpoints are `GET /imports`,
`GET /imports/{entity}/template` and `POST /imports/{entity}` (`dry_run=true|false`).

## 9. Security note
The zip you sent contains a real `.env` file with API keys (Groq, Anthropic) and the JWT/session secrets. It was not used or copied into anything in this pack.
Treat those keys as exposed if the zip has been shared, rotate them, and keep `.env` out of archives (it is already in `.gitignore`).
