# AccFino Payroll (Phase 2)

Payroll for Australian employers inside AccFino: **Employee > Payroll setup > Pay run > Earnings/deductions > Tax/super > Payslip > Payment > Reporting > Year-end**.

| Page | What it covers |
|---|---|
| [01 Architecture](01-architecture.md) | How payroll sits in the platform; layers; data flow; integrity rules |
| [02 Database model](02-database-model.md) | every table and constraint _(generated)_ |
| [03 API reference](03-api-reference.md) | every endpoint _(generated)_ |
| [04 Roles and permissions](04-roles-and-permissions.md) | who can do and see what _(generated)_ |
| [05 Calculation engine](05-calculation-engine.md) | the pure engine, step by step, with worked examples |
| [06 Australian rules](06-australian-rules.md) | the statutory rules file, what is verified and what is not |
| [07 Demo data](07-demo-data-and-seeding.md) | the dataset, load / reset / reload |
| [08 Running locally and tests](08-running-locally-and-tests.md) | set-up, running the app, running every kind of test |
| [09 Limitations and future](09-known-limitations-and-future.md) | what it does not do, and the integration points |
| [10 Manual testing guide](10-manual-testing-guide.md) | step-by-step, with checkboxes and verified figures |
| [12 Bulk import and test data](12-bulk-import-and-test-data.md) | the Import CSV buttons, the 17 importers, the 18-file test data set, how it is tested |
| [13 Manual testing with the CSV data](13-manual-testing-with-csv-data.md) | step-by-step, module by module, load-it-yourself, with verified figures |
| [Completion report](COMPLETION_REPORT.md) | what was built, changed and tested, with results |

Regenerate the three generated pages after changing models, routes or roles:
`cd AccFino/backend && PYTHONPATH=. DATABASE_URL=postgresql://x:y@localhost/none JWT_SECRET=<64 chars> python ../docs/payroll/generate_reference.py`
