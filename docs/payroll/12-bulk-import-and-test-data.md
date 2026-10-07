# Bulk CSV import and the payroll test data set

Payroll can load its data from CSV files: every list in *Payroll & Workforce* has an **Import CSV** button, and **Settings > Bulk import** lists all of them in load order.
A ready-made, internally consistent test data set ships in `AccFino_Testing/testdata/payroll/`. To *test* with it, follow [13 Manual testing with the CSV data](13-manual-testing-with-csv-data.md).

> **TEST DATA.** Every name, TFN, bank account and amount in the shipped files is invented. TFNs pass the ATO check digit but belong to nobody. Load them into a **new, empty organisation**, never a real one.

---

## 1. How an import works

Every import window works the same way: **Download template > choose file > Check file > Import.**

| Step | What happens |
|---|---|
| **Check file** | Runs the *whole* import for real inside a database transaction, then rolls it back. What it reports is exactly what Import will do, including records that depend on earlier records in the same file. Nothing is saved. |
| **Import** | Enabled only after a clean check. Runs again and saves. **All-or-nothing**: if any record has a problem nothing is saved, and every problem is listed with its row number (problems first). |

Each record goes through **the same service code as the screens**, so it is validated, permission-checked, masked and audited exactly as if typed in. Finalised pay runs post their journal to the general ledger.

Rules for every file
* Columns are matched **by name**, any order, case-insensitive; aliases work (`Surname`, `Given Name`, `Employee No`, `Commencement Date`, `Job Title`...). Unknown columns are ignored with a warning; missing *required* columns are refused.
* Dates `YYYY-MM-DD` or `DD/MM/YYYY`. Amounts `1234.50`, `$1,234.50` or `(1,234.50)`. Yes/no: `yes`, `no`, `true`, `false`, `1`, `0`.
* Comma, semicolon or tab separated; UTF-8 (with or without BOM) or Windows-1252 (Excel "CSV"). Limits: 5 MB and 5,000 rows per file.
* **Master data is upserted** (settings, calendars, departments, locations, super funds, leave types, pay items, employees, tax, super, bank): a row whose code / name / number exists *updates* it, and **blank cells keep the current value**. So a corrected file can simply be loaded again.
* **Transactions are new-only** (recurring items, opening leave balances, timesheets, leave requests, pay-run inputs): loading the same rows twice is refused ("already exists / overlaps"), never duplicated. Pay runs that already exist are moved forward, not recreated.
* **Sensitive values** (TFN, bank account numbers, the company account number) are sealed on the way in and **never echoed back**: results show only `*** *** 782` and `•••• 2222`. They never appear in the audit trail.
* An import **never sends e-mail** (in-app approval notifications are still created).
* Every real import writes an `import.csv` entry to the payroll **Audit** log (who, when, which file, how many records).

## 2. Where the buttons are

| Screen | Button offers | Needs |
|---|---|---|
| Employees | Employees, Employee tax (TFN, opening YTD), Super fund memberships, Bank accounts, Recurring pay items, Opening leave balances (a drop-down chooses) | `employees_manage` (Payroll Administrator, Payroll Manager, Organisation Admin) |
| Time & Leave > Timesheets | Timesheets | `timesheets_manage` |
| Time & Leave > Leave | Leave requests | `leave_manage` |
| Payrun > Pay Runs | Pay runs, Pay run inputs | `run_create` |
| Payrun > Pay Items | Pay items | `items_manage` (administrators only) |
| Settings > Pay calendars / Leave policies / Super funds / Departments & locations | the matching import | `config_manage` (administrators only) |
| Settings > **Bulk import** | every import, in load order, each with Import and Template | `config_manage` |

Not shown inside **My Pay** (employee self-service), and hidden everywhere when bulk import is switched off.

**Switching it off or on.** Admin Console > Modules Management > Platform features > *Bulk data import (CSV upload)* (the same switch as the Books & Accounting imports). Off: every Import button disappears and the server refuses uploads (403). The organisation's plan must also include *Bulk data import (CSV)*; an expired, read-only subscription refuses imports.

## 3. The 17 imports

Load order = the `#`. Later imports refer to earlier ones.

| # | Import (`entity`) | Records | Re-load | Needs |
|---|---|---|---|---|
| 01 | `settings` Organisation, payslip and payment settings | one row | updates | `config_manage` |
| 02 | `calendars` Pay calendars | one per calendar | updates | `config_manage` |
| 03 | `departments` | one per department | updates | `config_manage` |
| 04 | `locations` | one per location | updates | `config_manage` |
| 05 | `super_funds` | one per fund (APRA or SMSF) | updates | `config_manage` |
| 06 | `leave_types` Leave policies | one per type | updates | `config_manage` |
| 07 | `pay_items` Earnings, deductions, super | one per item | updates | `items_manage` |
| 08 | `employees` Personal and employment | one per employee (managers in the same file are loaded first) | updates | `employees_manage` |
| 09 | `employee_tax` TFN, residency, study loan, opening YTD | one per employee | updates | `employees_manage` |
| 10 | `employee_super` Fund memberships | rows grouped per employee; allocations total 100% | replaces | `employees_manage` |
| 11 | `employee_bank` Bank accounts | rows grouped per employee; exactly one `remainder` | replaces | `employees_manage` |
| 12 | `employee_items` Recurring allowances / deductions / salary sacrifice | one per assignment | new only | `employees_manage` |
| 13 | `leave_balances` Opening balances | one per employee and leave type | new only | `leave_manage` |
| 14 | `timesheets` | rows (day-lines) grouped into one timesheet per employee and week; status draft / submitted / approved / rejected | new only | `timesheets_manage` |
| 15 | `leave_requests` | one per request; status pending / approved / rejected | new only | `leave_manage` |
| 16 | `pay_runs` Create, calculate, approve, finalise | one per run; status draft / calculated / approved / finalised; oldest first | moves forward | `run_create` |
| 17 | `pay_run_inputs` Bonuses, reimbursements, back pay, termination payments | one per input; run found by number or by calendar + period start | new only | `run_create` |

`pay_runs` with `status = finalised` creates, calculates, approves and **finalises** in one step (payslips, leave ledger, super contributions, ledger journal). A run with employee errors (no bank account, no super fund) **cannot** be approved or finalised: the file is refused and the errors are named.

Column-by-column help is in the app (**Show columns**), and `GET /payroll/imports` returns it. Templates: `GET /payroll/imports/{entity}/template`.

## 4. The data set

`AccFino_Testing/testdata/payroll/`

| Folder | Contents |
|---|---|
| `csv/` | **18 valid files**, numbered in load order (`16` = history, `17` = open runs). 320 data rows in total. |
| `csv_invalid/` | **17 broken files**, one per importer. Every row in each file fails, for a stated reason. Load after the valid set. |
| `csv_special/` | `departments_partial.csv` (all-or-nothing), `employees_update.csv` (update by re-load), `employees_excel_style.csv` (semicolons, BOM, `DD/MM/YYYY`, other header names, non-ASCII), `fix_B0014_bank.csv` and `fix_B0016_super.csv` (repair the two blocked employees), `link_logins.csv` (link two employees to logins) |
| `generate_payroll_data.py` | writes all of the above; deterministic; standard library only |

```
python AccFino_Testing/testdata/payroll/generate_payroll_data.py            # rewrites the three folders
python AccFino_Testing/testdata/payroll/generate_payroll_data.py --out /tmp/pay
```
A test (`test_shipped_files_match_the_generator`) fails if anyone edits a CSV by hand without regenerating.

**The company.** *Bluegum Logistics Pty Ltd*, Sydney, FY2026-27. 21 employees on three calendars, with the demo "today" of **Monday 5 October 2026**:

| Calendar | Frequency | Who |
|---|---|---|
| Fortnightly (Mon start) | fortnightly, pay 5 days after period end | 15 salaried and part-time staff |
| Weekly casuals | weekly | B0004, B0005, B0017 |
| Monthly executives | monthly, pay on the last day | B0007, B0013 |

**History** (file 16): 21 finalised runs, 29 June to 20 September (6 fortnightly, 12 weekly, 3 monthly), with ledger journals. **Open** (file 17): five draft runs to process: fortnight 21 Sep (PR-0022), weeks 21 Sep (PR-0023) and 28 Sep (PR-0024), month October (PR-0025) and fortnight 5 Oct (PR-0026), with inputs (file 18).

**The people**

| No. | Name | What they test |
|---|---|---|
| B0001 | Amelia Hart | $128,000, HELP, $300 salary sacrifice, Aware Super; manages B0002, B0003, B0006, B0011 |
| B0002 | Noah Walker | $96,000; tool allowance (default $50), union fees ($20), workplace giving ($10) |
| B0003 | Priya Menon | part-time $57,000, 22.8 h/week; **5% salary sacrifice**; study leave balance |
| B0004 | Jack Turner | casual $34.50/h, weekly; overtime on some weeks |
| B0005 | Sienna Rossi | casual $33.00/h, weekly; Saturday penalty weeks |
| B0006 | Daniel Kerr | **new starter** 8 Sep 2026 (part first pay) |
| B0007 | Hannah Webb | $145,000 **monthly**, HostPlus; $12,000 bonus in October |
| B0008 | Tom Briggs | **unpaid leave** week (17-21 Aug) and **annual leave** week (14-18 Sep) |
| B0009 | Grace Lin | part-time hourly $38, **two bank accounts** ($200 fixed + remainder), paid standard hours |
| B0010 | Ethan Brooks | **foreign resident**, self-managed super fund |
| B0011 | Zara Khan | **no tax-free threshold**, $50 loan repayment |
| B0012 | Noel Fisher | **terminated** 2 Oct 2026; unused annual leave paid out |
| B0013 | Richard Stone | $180,000 monthly, super **split across two funds**, extra employer super |
| B0014 | Isla Moore | **EDGE: no bank account** (blocks approval) |
| B0015 | Jack Hill | **EDGE: no TFN** (taxed at the no-TFN rate) |
| B0016 | Kira Stone | **EDGE: no super fund** (blocks approval) |
| B0017 | Leo Zero | **EDGE: casual with no hours** |
| B0018 | Mia Tran | TFN provided; **half Medicare levy variation** (scale 6); $50 extra withholding |
| B0019 | Oscar Dean | transferred in mid-year: **opening YTD**; 4-day working week (no Friday) |
| B0020 | Paula Quinn | **inactive** (long-term leave): in no pay run |
| B0021 | Ryan Cole | **TFN "pending"** (see finding 1 in the testing guide) |

## 5. Tests that protect this

| Test file | Covers |
|---|---|
| `AccFino_Testing/tests/modules/payroll/payroll_csv_import_test.py` (53 tests) | the generator is deterministic and the shipped files match it; the whole set loads; counts and details; dry run saves nothing; all-or-nothing; Excel-style, Windows-1252 and BOM files; upsert and blank-cell behaviour; re-loading the set is safe; TFN/bank numbers sealed and never echoed or audited; every report reconciles; every history run is internally consistent (run = employees = payslips = lines; journal balanced; integrity hash intact); every figure quoted in the testing guide; **every row of every broken file is refused and nothing is saved**; the API: catalogue, template, role permissions, switch off, tenant isolation |
| `AccFino_Testing/tests/_support/payroll_csv_harness.py` | loads the set through the real importers; `python payroll_csv_harness.py` prints what each file does |
| `AccFino/frontend/src/modules/payroll/__tests__/csvImport.test.jsx` (19 tests) | the window (check, then import), problems shown by row, stale-check protection, entity picker, templates, the switch, the import centre, button placement and visibility by role, the multipart request |

```
cd AccFino/backend && PYTHONPATH=. python -m pytest ../../AccFino_Testing/tests/modules/payroll/payroll_csv_import_test.py -q
cd AccFino/frontend && npx vitest run src/modules/payroll/__tests__/csvImport.test.jsx
```

## 6. Files added and changed

Added: `backend/accfino/modules/payroll/services/csv_import.py`, `backend/accfino/modules/payroll/api/imports_api.py`, `frontend/src/modules/payroll/components/CsvImport.jsx`, `AccFino_Testing/testdata/payroll/` (generator, three folders, README), `AccFino_Testing/tests/_support/payroll_csv_harness.py`, `AccFino_Testing/tests/modules/payroll/payroll_csv_import_test.py`, `frontend/src/modules/payroll/__tests__/csvImport.test.jsx`, docs 12 and 13.

Changed (small): `api/__init__.py` (mounts the router), `lib/payrollApi.js` (four functions), and the Import buttons in `EmployeesTab`, `TimesheetsTab`, `LeaveTab`, `PayRunsTab`, `PayItemsTab`, `SettingsTab`. No database migration. No existing behaviour changed.

The importer is deliberately a **self-contained copy** of accounting's pattern, not a reuse of it: the architecture rules forbid one module importing another's internals (`check_boundaries.py` reports 0 couplings).
