# Demo data for testing Books & Accounting

    cd backend
    python -m accfino_core.seed_demo --user demo@accfino.com --verify      # needs DATABASE_URL (PostgreSQL), as for the app
    python -m accfino_core.seed_demo --user you@company.com --org-name "Test Co" --today 2026-09-30

Creates a NEW organisation each run (never touches existing ones) and, if the user does not exist, the login `demo@accfino.com` / `Demo@12345`.
Sign in, switch to the new organisation, and open Books and Accounting -> Reports.

Contents: 11 customers, 11 suppliers, ~150 invoices, ~145 bills, credit notes / supplier credit, quotes, purchase orders, drafts, a voided invoice,
part-paid / late / unpaid / over-paid documents (every ageing bucket), 3 bank accounts with ~550 statement lines (reconciled, unreconciled, excluded,
transfers), monthly pay runs with PAYG and super, BAS payments, loan, dividend, 5 fixed assets with depreciation and a disposal, 4 stock items,
7 expense claims (every status), prepayments / accruals / provisions, tracking categories, and two years of budgets.
Deliberate oddities (duplicates, stale lines, a suspense item, a large outlier) give Cash Validation something to find.

`--verify` checks: trial balance, balance sheet, AR/AP vs control, GST vs ledger, cash flow and cash summary vs bank movement, GL/journal balance,
inventory and fixed-asset registers vs ledger, PAYG, bank reconciliation, plus the management/budget/validation/claims reports.
`--sqlite FILE` builds the schema in SQLite and seeds it with no PostgreSQL (for checking the seeder itself; the app itself needs PostgreSQL).

## Ledger workflow demo data
The seeder also creates: 3 bank rules and ~19 AI/rule suggestions from unreconciled bank lines (15 "match to invoice/payment", 4 coded by rule), drafts in each state (draft, awaiting approval from a bookkeeper, rejected with a reason),
3 repeating journals (one overdue so "Run due now" does something), and a GST-exclusive accrual with a reference, tracking and an auto-reversing journal dated the next day. `--verify` now runs 22 checks.

The seeder also stores two USD rates and posts a USD 1,800 journal (AUD in the ledger, USD kept), posts a GST-exclusive $1,200 expense split 50/30/20 across Sydney / Melbourne / Brisbane, and marks the insurance-release template "run automatically".

The seeder now also creates a USD operating account (USD 12,000 opening deposit, a USD 3,500 client receipt, a GST-coded USD 900 purchase) at your stored USD rates and revalues it at the demo date (auto-reversing). Use `--no-foreign-demo` to leave it out.
