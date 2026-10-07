# Payroll: manual testing with the CSV data set

For a tester who has never used the module. Work top to bottom and tick each box. You load the data **yourself, through the Import CSV buttons**, so loading is part of the test. How the importer works and what each file is: [12 Bulk import and test data](12-bulk-import-and-test-data.md). The older seed-based guide ([10](10-manual-testing-guide.md)) still applies to the DEMO organisations.

**Every figure below was produced by the real application code against exactly these files** (the automated test `csv_import_test.py` asserts them), and the ones marked *hand-checked* were also worked from the ATO formulas. If a screen disagrees, that is a defect worth reporting. The screens themselves (labels, buttons) are described from the code and its tests: if a label differs on your build, note it as a finding.

> **TEST DATA.** Invented names, TFNs and bank accounts. Use a **new, empty organisation**, never a real one.

---

## 0. Set-up

### 0.1 Start the application
Follow [08 Running locally](08-running-locally-and-tests.md): `init_db`, `uvicorn`, `npm run dev` (http://localhost:3000). You do **not** run `demo_seed` for this guide.

### 0.2 Create a clean organisation and a bank account
1. On the sign-in page choose **Sign up > Create a New Organisation**. Name it `Bluegum Test Org` (any name; the payroll employer name is set by file 01). You become the **Organisation Admin**.
2. Sign in. Open **Books & Accounting > Banking** and **add a bank account with code `090`** and name *Business Cheque Account* (type Bank). File 01 maps payroll payments to it.
3. Confirm the import is available: **Payroll & Workforce > Settings > Bulk import** shows a table of 17 imports. If the tab is missing or says *switched off*: Admin Console > Modules Management > Platform features > **Bulk data import (CSV upload)** must be ticked, and the organisation's plan must include *Bulk data import (CSV)*.

> To start over, create another organisation (imports only create or update; they do not delete). A test organisation whose name ends in `(DEMO)` can be wiped with `python -m accfino.modules.payroll.demo_seed --reset --yes`, but that has only been tested on the seeded demo organisations.

### 0.3 The demo "today"
The data is built around **Monday 5 October 2026**. In *New pay run* set **Show periods around** to `2026-10-05`. "Overdue" super and dashboard alerts use your computer's clock; the numbers quoted here are *as at 5 Oct 2026*, and later dates show more overdue items.

### 0.4 Files
Get them from `AccFino_Testing/testdata/payroll/`: `csv/` (18 valid), `csv_invalid/` (17 broken), `csv_special/` (6). Regenerate any time: `python AccFino_Testing/testdata/payroll/generate_payroll_data.py`.

---

## 1. Load the data (test the importer as you go)

For **every** file: *Import CSV (or Settings > Bulk import > Import) > Download template (optional) > choose file > **Check file** > read the result > **Import**.* Check first, every time.

- [ ] After **Check file**, the green banner says *Checked: all N record(s) are valid. Nothing has been saved yet - press Import.* and **Import is still disabled until then**.
- [ ] After **Import**, a toast says *N record(s) imported* and the window closes.

Load in this order. "Records" is what the banner must say.

| # | File | Where | Records | What to notice in the result table |
|---|---|---|---|---|
| 01 | `01_settings.csv` | Settings > Bulk import > *Organisation...settings* | 1 | `ABN 51 824 753 556 · fortnightly · prefixes B/PR · bank account •••• 5678` (never the full number) |
| 02 | `02_calendars.csv` | Settings > Pay calendars > Import CSV | 3 | Fortnightly shows *default* |
| 03 | `03_departments.csv` | Settings > Departments & locations > Departments > Import CSV | 5 | |
| 04 | `04_locations.csv` | same page > Locations > Import CSV | 3 | |
| 05 | `05_super_funds.csv` | Settings > Super funds > Import CSV | 4 | AustralianSuper *employer default*; one SMSF |
| 06 | `06_leave_types.csv` | Settings > Leave policies > Import CSV | 5 | AL, PL, LSL, CL show **update** (they already exist); STUDY is new |
| 07 | `07_pay_items.csv` | Payrun > Pay Items > Import CSV | 5 | KMALLOW, MEAL, SSPCT, STUDYPAY new; GIVING shows **update** (adds a default $10) |
| 08 | `08_employees.csv` | Employees > Import CSV > *Employees* | 21 | managers are listed *after* their reports in the file; all still load |
| 09 | `09_employee_tax.csv` | Employees > Import CSV > *Employee tax declarations* | 21 | TFNs appear only as `*** *** 201`; **2 warnings** (B0015, B0021: no TFN on file) |
| 10 | `10_employee_super.csv` | Employees > Import CSV > *Super fund memberships* | 20 | B0013 shows `AustralianSuper 50.00% + HostPlus 50.00%` |
| 11 | `11_employee_bank.csv` | Employees > Import CSV > *Bank accounts* | 20 | accounts shown as `•••• 0037` |
| 12 | `12_employee_items.csv` | Employees > Import CSV > *Recurring pay items* | 8 | |
| 13 | `13_leave_balances.csv` | Employees > Import CSV > *Opening leave balances* | 14 | e.g. `Annual leave: +120 h (opening) -> balance 120.00 h` |
| 14 | `14_timesheets.csv` | Time & Leave > Timesheets > Import CSV | **29** (from 150 rows) | one result row per timesheet, e.g. `B0004 Jack Turner · week of 2026-06-29 · 6 line(s) · 39 h` |
| 15 | `15_leave_requests.csv` | Time & Leave > Leave > Import CSV | 6 | |
| 16 | `16_pay_runs_history.csv` | Payrun > Pay Runs > Import CSV > *Pay runs* | 21 | PR-0001...PR-0021, all `finalised`; first row `PR-0001 · 8 employee(s) · gross $26,483.86 · net $19,736.24`; 6 runs warn (see below) |
| 17 | `17_pay_runs_open.csv` | same | 5 | all `draft`: PR-0022 (fortnight 21 Sep, 15 employees), PR-0023, PR-0024, PR-0025, PR-0026 |
| 18 | `18_pay_run_inputs.csv` | Payrun > Pay Runs > Import CSV > *Pay run inputs* | 6 | e.g. `PR-0022 · B0012 ... TLEAVE Unused leave payout: $4,512.63` |

*Expected warnings in 16:* "1 employee(s) have warnings" for PR-0001, 0005, 0008, 0012 and "2 employee(s)" for PR-0015 and PR-0019. These are Noel Fisher ("Employee has left": he carries a 2 Oct end date, so every earlier run notes it) and, from PR-0015, Ryan Cole (pending TFN). Not defects.

**After loading, tick:**
- [ ] **Payroll > Employees**: 21 employees (19 active, B0012 terminated, B0020 inactive).
- [ ] **Payrun > Pay Runs**: 26 runs: 21 *Finalised*, 5 *Draft*.
- [ ] **Time & Leave > Timesheets**: 29 timesheets: 24 *processed*, 1 *approved*, 2 *submitted*, 1 *draft*, 1 *rejected*.
- [ ] **Time & Leave > Leave**: 3 *pending*, 2 *approved* (both already paid in history), 1 *rejected*.
- [ ] **Payrun > Audit**: 18 `import.csv` entries (one per file).
- [ ] **Settings > Accounting**: seven ledger accounts mapped (477, 478, 479, 804, 825, 826, 806) **and the bank account 090** (set by file 01).

---

## 2. Module scripts

### Module A. Settings
Sign in as the Organisation Admin.
- [ ] **Organisation & payslips**: employer `Bluegum Logistics Pty Ltd`, ABN `51 824 753 556`, prefixes `B` / `PR`, footer *TEST DATA - not a real payslip.* Change the ABN to `11 111 111 111`: refused (*ABN is not valid*). Restore it.
- [ ] **Payments**: company account shows `•••• 5678` and never in full.
- [ ] **Pay calendars**: Fortnightly (Mon start) is default; Weekly casuals; Monthly executives (pay offset 0). Open Fortnightly: periods are listed and the pay date is 5 days after period end.
- [ ] **Departments & locations**: OPS, SAL, FIN, EXE and HR (HR is *inactive*); SYD, MEL, BNE.
- [ ] **Super funds**: AustralianSuper (employer default), Aware Super, HostPlus, *Smith Family SMSF* (Self-managed).
- [ ] **Leave policies**: Annual leave 152 h/yr, loading 17.5%; Personal 76 h/yr; Long service minimum 7 years; new **STUDY** (maximum 40 h, no accrual).
- [ ] **Pay items > Earnings / Allowances**: KMALLOW ($12) and MEAL ($15) exist; **Study leave** (STUDYPAY) is a leave item tied to STUDY. **Deductions**: SSPCT (percent of gross, 10); *Workplace giving* has default $10.
- [ ] **Statutory rules**: rule set 2026-27, super guarantee 12%.

### Module B. Employees
Sign in as the **Payroll Manager** (invite one: [ORG_ADMIN.md](../platform/ORG_ADMIN.md)) or the Admin.
- [ ] Open **Amelia Hart**: $128,000, Finance, manager of four people. **Tax**: `*** *** 201`, HELP. **Super**: Aware Super. **Bank**: `•••• 0037`. **Recurring items**: Salary sacrifice - super $300. **Leave**: annual **155.08 h**, personal **77.54 h** (120 + accruals from the history runs).
- [ ] **Readiness** (the notice at the top of the record):

| Employee | Notice |
|---|---|
| B0014 Isla Moore | red: **No bank account** |
| B0015 Jack Hill | amber: **No TFN** (taxed at the highest rate) |
| B0016 Kira Stone | red: **No super fund** |
| B0021 Ryan Cole | amber: **TFN declared as pending** |
| B0018, B0019, B0017 | none |

- [ ] **Grace Lin** (B0009): two bank accounts, savings (fixed $200) and everyday (remainder). **Ethan Brooks** (B0010): foreign resident, no tax-free threshold, SMSF. **Richard Stone** (B0013): two funds 50% / 50%. **Priya Menon** (B0003): recurring item *Salary sacrifice super (% of gross)* at 5%.
- [ ] **Oscar Dean** (B0019): work pattern Monday-Thursday (no Friday); the tax page shows opening year-to-date for 2026-27 (gross $18,000.00).
- [ ] **Noel Fisher** (B0012) shows *Terminated*, ended 2 Oct 2026. **Paula Quinn** (B0020) shows *Inactive*.
- [ ] Tom Briggs (B0008) **Leave > History** shows *accrual* entries per finalised run and *taken* entries for his paid weeks. His LWP balance is **-38 h** (unpaid leave allows negative).
- [ ] **Sensitive data**: open the browser's Network tab (F12), reload an employee: responses contain only masked values (`*** *** 201`, `•••• 0037`), never a full TFN or account number. As Payroll Manager there is no **Reveal TFN** button; as Payroll Administrator there is, and using it adds an `employee.tfn_viewed` entry to **Audit**.

### Module C. Time & Leave
As Payroll Manager.
**Timesheets**
- [ ] Open sheets: **Jack Turner 21 Sep: approved**; **Sienna Rossi 21 Sep: submitted**; **Jack Turner 28 Sep: submitted** (entered with start and finish times 07:00 to 15:30 less a 30 minute break = 8 h a day, 40 h); Sienna 28 Sep: **draft**; **Jack Turner 5 Oct: rejected**. Earlier weeks are *processed* and cannot be edited or deleted.
- [ ] Open the rejected sheet: the reason *Friday hours are missing: please complete and resubmit* is shown.
- [ ] **New timesheet** (a casual, week of 12 Oct): a line of **25** hours is refused ("more than 24 hours"); hours **0** refused; a date outside the week refused. Enter 5 days x 8 h, **Save & submit**: status *submitted*.
- [ ] **Reject** a submitted sheet with no reason: refused. **Approve** Sienna's 21 Sep sheet (needed for Module D).

**Leave**
- [ ] Pending: **Amelia** annual leave 12-16 Oct (38 h), **Priya** personal leave 5-6 Oct (9.12 h), **Priya** study leave 8 Oct (4.56 h). **Rejected**: Jack Turner compassionate leave, note *Please attach evidence and resubmit*.
- [ ] **Request leave** for **Jack Turner** using *Annual leave*: refused (*does not apply to casual employees*). For **Oscar Dean**, Friday 9 Oct only: refused (*no scheduled working hours*). For Amelia, 2 Nov to 26 Feb: *Insufficient Annual leave balance: 117.08 hours available*. Overlapping Amelia's 12-16 Oct: refused. For **Noel Fisher**: refused (*only for an active employee*).
- [ ] **Reject** Priya's request with no reason: refused. **Approve** all three pending requests (needed for Module D). You are not the employee, so you may; nobody can approve their own.

### Module D. Pay runs
As Payroll Manager. **Payrun > Pay Runs.** PR-0022 to PR-0026 are *Draft*.

**D1. The open fortnight (PR-0022, 21 Sep to 4 Oct, pay date 9 Oct).** Open it, **Calculate**.
- [ ] 15 employees. Totals: gross **$50,857.64**, PAYG **$12,702.00**, study loan **$292.00**, net **$37,434.52**, super **$5,988.23**. **2 employees have errors**, 2 warnings. **Approve is disabled.**
- [ ] **Isla Moore**: error *No bank account: net pay cannot be paid*. **Kira Stone**: *Superannuation is payable but the employee has no super fund recorded*.
- [ ] Per employee (expand the row):

| Employee | Gross | PAYG | Net | Note |
|---|---|---|---|---|
| Amelia Hart B0001 | 4,923.08 | 1,116.00 (+ study loan 292.00) | 3,215.08 | taxable 4,623.08; sacrifice 300.00 |
| Noah Walker B0002 | 3,742.31 | 834.00 | 2,963.81 | base 3,692.31 + tool allowance 50; union 20 + giving 10 deducted; taxi reimbursement 85.50 (untaxed) |
| Priya Menon B0003 | 2,692.31 | 454.00 | 2,103.69 | base 2,192.31 + **back pay 500**; sacrifice 134.62 (5% of gross) |
| Ethan Brooks B0010 | 2,692.31 | **808.00** | 1,884.31 | **scale 3**, 30% (*hand-checked*) |
| Zara Khan B0011 | 4,038.46 | 1,150.00 | 2,838.46 | **scale 1** (no tax-free threshold); $50 loan deducted |
| Noel Fisher B0012 | 7,974.17 | 2,200.00 | 5,774.17 | base 3,461.54 + **unused leave payout 4,512.63** |
| Jack Hill B0015 | 2,307.69 | **1,084.00** | 1,223.69 | **scale 4**, 47%; warning *No TFN* |
| Mia Tran B0018 | 2,846.15 | **570.00** | 2,276.15 | **scale 6** (half Medicare): 520 + $50 extra (*hand-checked*) |
| Oscar Dean B0019 | 3,000.00 | 598.00 | 2,402.00 | super 360.00 (*hand-checked; same as the older guide's $78,000 example*) |
| Ryan Cole B0021 | 2,538.46 | **1,192.00** | 1,346.46 | **scale 4**: see finding 1 |

- [ ] Amelia's super is $890.77 = **$590.77 (12% of $4,923.08, before sacrifice)** + $300 sacrifice. *Hand check*: x = floor(4,623.08 / 2) + 0.99 = 2,311.99; 0.32x - 181.7319 = 558.1, so $558 x 2 = **$1,116**; HELP 0.15x - 200.5615 = 146.2, so $146 x 2 = **$292**.
- [ ] **Fix by import** (a good test of the importer): load `csv_special/fix_B0014_bank.csv` (Employees > Import CSV > Bank accounts) and `fix_B0016_super.csv` (Super fund memberships). Open Isla: the notice is gone. **Recalculate**: errors drop to **0** and net stays $37,434.52 (their pay was calculated all along; only payment and super were blocked).
- [ ] **Approve**, then **Finalise...** (read the confirmation: payslips, leave, super, journal; only reversible). Status **Finalised**, banner *Finalised and locked*, no Calculate / Approve buttons. **Integrity** tab: *unchanged since finalisation*. 15 payslips exist.

**D2. Weekly casuals (PR-0023, 21-27 Sep) and the unapproved timesheet.** Calculate.
- [ ] 3 employees. Gross **$1,483.50**, PAYG **$293.00**, net **$1,190.50**, super **$165.60**, 2 warnings.
- [ ] **Jack Turner**: 40 h x $34.50 = $1,380.00 + 2 h overtime x $51.75 = $103.50. Overtime is **not** super-able: 12% x 1,380 = **$165.60**. *Hand check*: floor(1,483) + 0.99 = 1,483.99; 0.32x - 181.7319 = 293.1, so **$293**.
- [ ] **Sienna Rossi**: warnings *Zero earnings* and *1 timesheet(s) ... are not approved and are NOT included*. **Leo Zero**: *Zero earnings*.
- [ ] Approve Sienna's 21 Sep timesheet (Module C), **Recalculate**: Sienna gross **$1,056.00** (32 h), PAYG $156, net $900.00, super $126.72; run totals gross **$2,539.50**, PAYG **$449.00**, net **$2,090.50**, super **$292.32**.
- [ ] **PR-0024** (28 Sep week): all three have zero earnings (Jack's sheet is *submitted*, Sienna's *draft*): gross $0.00, 3 warnings.

**D3. Monthly executives with a bonus (PR-0025, October).** Calculate.
- [ ] 2 employees: gross **$39,083.33**, PAYG **$12,094.00**, net **$26,989.33**, super **$4,890.00**.
- [ ] **Hannah Webb**: base $12,083.33 + **bonus $12,000** = $24,083.33; PAYG **$7,817.00** (regular $3,137 + $4,680 on the bonus, ATO *Method A*); net $16,266.33.
- [ ] **Richard Stone**: super **$2,000.00** = 12% of $15,000 ($1,800) + $200 extra employer super.

**D4. Leave, bonus and commission (PR-0026, 5-18 Oct, pay date 23 Oct).** Approve the three pending leave requests first (Module C), then **Calculate**.
- [ ] **Amelia**: lines Base salary $4,923.08, **Annual leave 38 h $2,461.54**, **Salary adjustment for leave -$2,461.54**, **Annual leave loading $430.77** (17.5%), Salary sacrifice $300. Gross **$5,353.85**, taxable $5,053.85, PAYG **$1,254.00**, study loan **$358.00**, net **$3,441.85**, super guarantee **$642.46** (same as the older guide, Scenario 6a).
- [ ] **Priya**: personal leave 9.12 h **$438.46** and study leave 4.56 h **$219.23**, each with a matching salary adjustment; base $2,192.31; sacrifice $109.62 (5% of $2,192.31); gross $2,192.31, PAYG $302.00.
- [ ] **Noah Walker**: base + tool allowance + **bonus $3,000** = gross **$6,742.31**, PAYG **$1,822.00**, net **$4,890.31**. **Zara Khan**: **commission $1,500**, gross **$5,538.46**, PAYG $1,618.00.
- [ ] Run totals (Isla and Kira *not yet repaired* in this run): gross **$47,314.24**, PAYG **$11,944.00**, study loan **$358.00**, net **$34,522.62**, super **$6,079.54**, 2 errors.
- [ ] **Duplicate protection**: **New pay run**, calendar Fortnightly, *Show periods around* `2026-10-05`, choose 5 Oct to 18 Oct: refused (*already exists*).
- [ ] **Stale protection**: calculate, change an employee's salary in another tab, return and **Approve**: refused (*Pay inputs changed... Recalculate*).
- [ ] **Inputs load once**: load `18_pay_run_inputs.csv` a second time. The whole file is refused (all-or-nothing): every row says *is already on PR-00nn with these details*, and **nothing** is added or duplicated. Check the *Bonuses & adjustments* tab: unchanged.

**D5. History (finalised).**
- [ ] **PR-0001** (29 Jun to 12 Jul, pay 17 Jul): 8 employees, gross **$26,483.86**, PAYG **$5,966.00**, net **$19,736.24**, super **$3,581.69**.
- [ ] **PR-0012** (10-23 Aug): gross **$24,906.94**. **Tom Briggs** gross **$1,576.93** (an unpaid week took $1,576.92 off $3,153.85).
- [ ] **PR-0019** (7-20 Sep): 11 employees, gross **$35,190.58**; **Daniel Kerr** gross **$3,046.15**, PAYG $612.00 (first, part pay: 9 of 10 working days).
- [ ] **Paula Quinn** appears in no run. **Daniel Kerr** appears in no run before PR-0019.

### Module E. Payslips and payments
- [ ] **Payslips**: Amelia's payslip for pay date 17 Jul: gross $4,923.08, PAYG $1,116.00, study loan $292.00, sacrifice $300.00, net $3,215.08, super (Aware Super) $590.77, leave balances; bank shown `•••• 0037`.
- [ ] Amelia's payslip from PR-0022 shows **YTD gross $34,461.56**, tax $7,812.00. **Oscar Dean**'s PR-0022 payslip shows **YTD gross $21,000.00** (his opening $18,000 + this pay $3,000) and tax **$4,198.00**.
- [ ] **Payments > Finalised pay runs awaiting payment**: PR-0001...PR-0021 are listed (history has no payment batches), PR-0022 included. Open **PR-0022 > Prepare payment**: batch `PR-0022-PAY`, total **$37,434.52**, **16 lines** (15 employees; **Grace Lin has two**: `Grace Lin savings` 063-000 `•••• 0369` **$200.00**, `Grace Lin everyday` 062-000 `•••• 0333` **$1,714.00**).
- [ ] Prepare it again: refused (a live batch exists).
- [ ] **Download bank file (ABA)**: **19 lines of exactly 120 characters**: first starts `0`, last starts `7`, 17 detail lines (16 credits + 1 balancing debit).
- [ ] **Mark as paid...** (it states no money is sent): run becomes **Paid**. **Reconcile**: items *reconciled*. Mark as paid again: refused. Record one item as **Returned...**: a reason is required.
- [ ] **Books & Accounting > General Ledger**: a payment journal *Payroll payment PR-0022-PAY*: **Dr Wages Payable $37,434.52, Cr Business Cheque Account (090) $37,434.52**. (If the journal is missing, the bank account was not mapped: Module A, Settings > Accounting.)

### Module F. Super, PAYG and STP
- [ ] **Super** (as at 5 Oct 2026): after PR-0022 there are **121 contributions** totalling **$42,423.63**, all *pending*; **84 are overdue** totalling **$28,066.57** (history runs; due 7 business days after payday). PR-0022's are not due until 20 Oct. Select two overdue rows, **Mark as paid** with reference `CH-TEST1`: they become *paid*; marking again is refused; an empty reference is refused.
- [ ] B0013 Richard Stone: contributions are split between AustralianSuper and HostPlus, plus an *additional* component of $200. Ethan Brooks' go to the SMSF.
- [ ] **PAYG**: the rule table for 2026-27 is shown. PAYG withholding report total (Module G) = **$80,421.00** (tax $78,377.00 + study loan $2,044.00).
- [ ] **STP**: a red banner states AccFino **does not lodge with the ATO**. **Prepare** an event from PR-0022 (status *draft*), open the payload (**no TFN in it**), **Mock submit**: a reference starting `MOCK-NOT-LODGED` is recorded. Year-end finalisation is refused until the year ends.

### Module G. Accounting integration and reports
Sign in as the **Accountant** (or Admin).
- [ ] **PR-0022 > Ledger journal**: *Posted*, debits **$56,496.75** = credits. Accounts: **477 Wages and Salaries Dr $50,857.64**; **478 Superannuation Dr $5,553.61**; **479 Employee Reimbursements Dr $85.50**; **804 Wages Payable Cr $37,434.52**; **806 Payroll Deductions Payable Cr $80.00**; **825 PAYG Withholdings Payable Cr $12,994.00** (PAYG $12,702 + study loan $292); **826 Superannuation Payable Cr $5,988.23**. (478 + salary sacrifice $434.62 = 826.)
- [ ] **Employee-level lines** each carry a reference like `PR-0022-B0001-001`.
- [ ] General Ledger: the same journal with the same totals; the trial balance still balances.
- [ ] **Reports**, From `2026-07-01` To `2026-10-05`, all 18 reports (Payroll Summary, Register, Employee Payroll, Gross-to-Net, PAYG Withholding, Superannuation, Leave Balance, Leave Liability, Timesheet, Deduction, Earnings, Payroll Journal, Cost by Department / Employee / Pay Period, Year-to-Date, Termination, Audit): each runs, **every green "Reconciled" line is green** (red *DOES NOT RECONCILE* is a defect), and **Export CSV** works.
- [ ] Figures, **after PR-0022 is finalised** (before it, history only: gross $278,912.54, PAYG $65,675.00, net $208,547.82, super $36,435.40, 21 runs):

| Report | Expect |
|---|---|
| Payroll Summary | **22 runs**; gross **$329,770.18**, PAYG **$78,377.00**, study loan **$2,044.00**, deductions $560.00, sacrifice $2,892.34, reimbursements $85.50, net **$245,982.34**, super **$42,423.63** |
| PAYG Withholding | tax $78,377.00 + study loan $2,044.00 = **$80,421.00**; reconciles to the credits to account 825 |
| Superannuation | **$42,423.63**; reconciles to the contributions |
| Gross-to-Net | every row's check is $0.00 |
| Cost by Department | 4 departments; gross $329,770.18; cost **$369,386.97** |
| Termination | **Noel Fisher**, last pay 9 Oct, unused leave paid **$4,512.63**; see finding 2 |
| Year-to-Date, employee Amelia Hart | gross **$34,461.56** = her latest payslip YTD |

- [ ] Filters: *Employee* = Amelia: only her rows; *Department* = Finance: only Finance; *Pay run* = PR-0001: only that run; a From date after the To date: refused.

### Module H. Roles and security
Use a private window per login; invite users (ORG_ADMIN.md). 
- [ ] Capabilities as in [10, Scenario 12](10-manual-testing-guide.md): Administrator everything; Payroll Manager no Settings / Audit / Pay Items / Reverse / Reveal TFN; Accountant read-only without TFN or bank details; Bookkeeper no Payroll at all; Employee self-service only.
- [ ] **Link logins** (tests manager approval): as Admin invite two users with role **Employee** and these exact emails: `amelia.hart@bluegum.example` and `jack.turner@bluegum.example` (if your install verifies emails, use addresses you control and edit `csv_special/link_logins.csv`). Before inviting, **Check file** on `link_logins.csv` (Employees > Import CSV > Employees) is refused: *No login with the email ... is a member of this organisation*. After inviting, it imports 2 records.
- [ ] Sign in as **Amelia**: **My Pay** and **Time & Leave**. She sees her four reports (Noah, Priya, Daniel, Zara) and can approve *their* leave and timesheets, **not her own** (no manager: the payroll team decides it). She sees **no** salary, tax or bank detail, not even her team's. Sign in as **Jack Turner**: only **My Pay**, his own payslips, leave and timesheets.
- [ ] **Import permissions** (Employees > Import CSV exists for the Payroll Manager; Settings imports do not):

| Sign in as | Can import | Cannot |
|---|---|---|
| Organisation Admin / Payroll Administrator | everything | |
| Payroll Manager | employees, tax, super, bank, items, opening leave, timesheets, leave, pay runs, inputs | settings, calendars, departments, locations, funds, leave types, **pay items** (no button; a direct request is refused 403) |
| Accountant, Bookkeeper, Employee, Amelia | nothing | no Import button; the API answers 403 |

- [ ] A second organisation cannot see or use this one's data: in another organisation, importing `08_employees.csv` fails on *Department 'OPS' does not exist*.
- [ ] **Audit**: every import appears as `import.csv` with user, time and file name. The Audit trail contains no full TFN or account number.

---

## 3. Testing the importer itself

Sign in as the Admin. Everything here is *Check file* only unless stated.

### 3.1 Every broken file is refused
For each file in `csv_invalid/`, open the matching import and **Check file**:
- [ ] The banner is red: *N of N record(s) have problems; nothing was imported.* **Import stays disabled.**
- [ ] **Every** row is listed in red with its row number and a plain reason. The table lists problems first.

Spot-check these messages:

| File (row) | Message must say |
|---|---|
| `settings_invalid` (2) | ABN is not valid |
| `calendars_invalid` (2, 3, 4, 5) | frequency must be one of...; not a valid anchor_start; at most 31; name is required |
| `employees_invalid` (2) | hourly rate is required (a casual given a salary) |
| `employees_invalid` (3, 4, 11) | Postcode must be 4 digits; End date cannot be before the start date; at least 14 years old |
| `employee_tax_invalid` (2) | not a valid Tax File Number (check digit) |
| `employee_super_invalid` (2) | must add up to 100% (currently 90%) |
| `employee_bank_invalid` (2, 3, 4) | BSB must be 6 digits; account number 5 to 9 digits; exactly one account must receive the remainder |
| `timesheets_invalid` (2, 4, 6, 11) | more than 24 hours; rows 4 and 5 give different values for 'status'; salaried; a timesheet for that week already exists |
| `leave_requests_invalid` (2, 4, 5, 7) | does not apply to casual employees; no scheduled working hours; overlaps an existing pending request; Insufficient Annual leave balance |
| `pay_runs_invalid` (2, 4, 6) | is not a pay period of calendar...; cannot be finalised / approved: employees have errors (names Isla Moore and Kira Stone) |
| `pay_run_inputs_invalid` (6, 9) | pay run is finalised and cannot be changed; already on PR-0026 with these details |

### 3.2 All-or-nothing, update and format handling
- [ ] **All-or-nothing**: `csv_special/departments_partial.csv` (two good rows, one bad). *Check file*: red banner, 2 valid + 1 problem. Try Import: it is disabled. Confirm **LOG and IT do not exist** in Departments.
- [ ] **Update by re-load**: `employees_update.csv` changes only Priya Menon's position (*Senior Accounts Officer*) and phone. Result row shows **update**; after Import her salary, hours and manager are unchanged; Audit shows `employee.update`.
- [ ] **Excel-style file**: `employees_excel_style.csv` (semicolons, `06/10/2026`, `$64,000.00`, headers like *Given Name*, *Surname*): imports **B0022 Zoë Müller**, starting 6 Oct 2026, $64,000. The next employee you add by hand is **B0023** (the counter moved on).
- [ ] **Re-load a valid file**: load `08_employees.csv` again: all 21 show **update** and nothing is duplicated. Load `14_timesheets.csv` again: refused (every timesheet *already exists*). Load `15_leave_requests.csv` again: refused. Load `16_pay_runs_history.csv` again: accepted with *nothing to do* on every row.
- [ ] **Missing column**: delete the `employee_number` column from a copy of `11_employee_bank.csv`: refused (*missing required column(s): employee_number*). An empty file and a header-only file are refused with their own messages.
- [ ] **Unknown column** (add a column `colour`): the file is accepted with *Ignored column(s) not used by this import: colour*.
- [ ] **Template**: *Download template* for each import; open it: headers match *Show columns*, with one example row.

### 3.3 Switch it off
- [ ] Admin Console > Modules Management > untick **Bulk data import**. Reload Payroll: **every Import CSV button is gone**, and *Settings > Bulk import* says it is switched off. Tick it again: buttons return.

---

## 4. Edge cases (quick list)

- [ ] **Missing bank / TFN / super**: Isla, Jack Hill, Kira (D1).
- [ ] **TFN pending**: Ryan Cole (finding 1). **Foreign resident**, **no tax-free threshold**, **half Medicare + extra withholding**: Ethan, Zara, Mia (D1).
- [ ] **Zero earnings / unapproved timesheets**: Leo, Sienna, PR-0023/0024 (D2).
- [ ] **Part-time with a 4-day pattern, opening YTD**: Oscar (B; payslip YTD E).
- [ ] **New starter part pay**: Daniel in PR-0019 (D5). **Inactive employee excluded**: Paula (D5).
- [ ] **Terminated with leave payout**: Noel in PR-0022 (D1).
- [ ] **Unpaid and annual leave in history**: Tom (D5, B).
- [ ] **Salary sacrifice fixed and percentage**: Amelia ($300), Priya (5%).
- [ ] **Split bank account**: Grace (E). **Split super**: Richard (F). **SMSF**: Ethan.
- [ ] **Bonus (Method A)**: Hannah, Noah (D3, D4). **Commission, back pay, reimbursement**: Zara, Priya, Noah.
- [ ] **Reversal**: reverse a finalised run (Payrun > Pay Runs > open > **Reverse...**, Administrator only, reason required): a reversal run with negated amounts appears, the original shows *Reversed*, and Reports still reconcile. Then re-load `16_pay_runs_history.csv`: the reversed period can be re-created.

---

## 5. Findings from building this data set

These are behaviours of the existing application that the test data exposed. They are **not** changed by the import work; please log or triage them.

1. **A "pending" TFN is taxed at the no-TFN rate.** Ryan Cole (TFN status *pending*) is paid on Scale 4 (47%): PAYG **$1,192.00** on gross $2,538.46, with the same warning as someone with no TFN. The employee readiness notice says *"TFN declared as pending: confirm within 28 days"*, which suggests a grace period that the pay run does not apply. Decide which is intended.
2. **A termination leave payout does not reduce the leave balance.** After Noel Fisher's unused annual leave ($4,512.63, 99.08 h) is paid in PR-0022, the Termination report still shows **134.25 h** "leave still on balance" and the Leave Liability report still counts it. Check whether paying the leave out should debit the leave ledger. This is not listed in [09 Known limitations](09-known-limitations-and-future.md).
3. **"Employee has left" is shown on earlier runs too.** Because Noel's end date is 2 Oct, every earlier run (back to 29 Jun) carries the warning *Employee has left: check for unused leave payout*. Harmless here (it is only a warning), but it suggests the check ignores whether the period is before or after the leaving date.
4. **Two payroll frontend tests already fail** (before any import work): `payroll.test.jsx` > *role-based navigation* > *shows no badge when nothing waits* (fails only in sequence: mock state leaks) and *tells someone with no employee record why My Pay is empty* (fails alone).

---

## 6. Recording results

| Module | Tester | Date | Pass / Fail | Defect notes |
|---|---|---|---|---|
| 0 Set-up | | | | |
| 1 Loading the 18 files | | | | |
| A Settings | | | | |
| B Employees | | | | |
| C Time & Leave | | | | |
| D Pay runs | | | | |
| E Payslips and payments | | | | |
| F Super, PAYG, STP | | | | |
| G Accounting and reports | | | | |
| H Roles and security | | | | |
| 3 Importer behaviours | | | | |
| 4 Edge cases | | | | |
