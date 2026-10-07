# Payroll: manual testing guide

For a tester who has never used the Payroll module. Work top to bottom; tick each box as you go. **Every expected figure below was verified** two ways: by the automated test-suite, and by hand from the ATO's published formulas (the working is shown where it helps). If a screen disagrees with a figure here, that is a defect worth reporting.

> The demo data is fictional and is labelled **(DEMO)**. Never run these steps against a real organisation.
>
> Prefer to load the data yourself through the **Import CSV** buttons? See [13 Manual testing with the CSV data](13-manual-testing-with-csv-data.md) (a different company, 21 employees, 18 files).

---

## 0. Set-up

### 0.1 Start the application and load the demo data
```bash
cd AccFino/backend
export PYTHONPATH=. ACCFINO_DATA_ROOT=../../AccFino_Data      # plus DATABASE_URL, JWT_SECRET, ADMIN_PASSWORD (see docs/payroll/08-running-locally-and-tests.md)
python -m accfino.core.init_db                                  # creates/upgrades the schema (safe to repeat)
python -m accfino.modules.payroll.demo_seed --reload --yes      # clean demo data, about 10 seconds
python -m uvicorn accfino.app:app --port 8001 &                 # backend
cd ../frontend && npm install && npm run dev                    # http://localhost:3000
```
- [ ] The seed prints two organisations: **Harbour & Co Pty Ltd (DEMO)** and **Outback Supplies Pty Ltd (DEMO)**.
- [ ] `python -m accfino.modules.payroll.demo_seed --status` shows 17 + 8 employees, 22 + 20 pay runs.

To start again at any time: `--reload` (reset, then load). `--reset` removes the demo organisations, their users and all their data, including the ledger. It only touches organisations whose name ends in `(DEMO)`.

### 0.2 Logins
Password for every demo login: **`Demo-Payroll-1!`** (or the value of `DEMO_PASSWORD` when you loaded the data).

| Sign in as | Email | What they are |
|---|---|---|
| Organisation Administrator | `demo.owner@harbour.accfino.test` | `owner` |
| Payroll Administrator | `demo.padmin@harbour.accfino.test` | `payroll_admin` |
| Payroll Manager | `demo.pmanager@harbour.accfino.test` | `payroll` |
| Accountant | `demo.accountant@harbour.accfino.test` | `accountant` |
| Bookkeeper (no payroll access) | `demo.bookkeeper@harbour.accfino.test` | `bookkeeper` |
| Employee **and** line manager | `demo.olivia@harbour.accfino.test` | `employee`, linked to Olivia Chen (E0001), who manages Liam, Priya, Daniel and Zara |

The Outback company has the same five staff logins (`@outback.accfino.test`) and no linked employees; use it to prove one company cannot see another.

### 0.3 The demo "today"
The data is built around **Monday 5 October 2026**. Your computer's clock may differ, so:
- Use the **"Show periods around"** date in *New pay run* and set it to `2026-10-05`.
- Dashboard alerts and "overdue" super use the real clock. If it is later than 5 Oct 2026 you will see more overdue items than quoted here. That is expected.

### 0.4 The people (Harbour & Co)
| No. | Name | Situation |
|---|---|---|
| E0001 | Olivia Chen | $128,000, HELP debt, $300/pay salary sacrifice, Aware Super. Employee login. Manager. |
| E0002 | Liam Nguyen | $96,000, tool allowance, union fees + workplace giving |
| E0003 | Priya Raman | part-time, $57,000, 22.8 h/week |
| E0004 | Marcus Reid | casual $34.50/h, weekly pay, overtime |
| E0005 | Sofia Rossi | casual $33/h, weekly pay, Saturday penalty weeks |
| E0006 | Daniel Park | **new starter** (started Tue 8 Sep 2026) |
| E0007 | Hannah Wells | $145,000, **monthly**, $12,000 bonus in September, HostPlus |
| E0008 | Tom Baxter | **unpaid leave** week (17-21 Aug) and **annual leave** week (14-18 Sep) |
| E0009 | Grace Lim | part-time hourly, **two bank accounts** ($200 fixed + remainder), standard hours |
| E0010 | Ethan Brooks | **foreign resident**, self-managed super fund (SMSF) |
| E0011 | Zara Khan | does **not** claim the tax-free threshold (second job), loan deduction |
| E0012 | Noah Fisher | **terminated** 21 Aug 2026, unused leave paid out |
| E0013 | Richard Stone | $180,000 monthly, super split across **two funds**, extra employer super |
| E0014 | Isla Moore | **EDGE: no bank account** |
| E0015 | Jack Hill | **EDGE: no TFN** |
| E0016 | Kira Stone | **EDGE: no super fund** |
| E0017 | Leo Zero | **EDGE: casual with no hours** |

### 0.5 Automated tests (run these first)
```bash
python AccFino_Testing/run_tests.py payroll          # payroll backend + frontend + boundary check
python AccFino_Testing/run_tests.py all              # everything: must match the baseline in the completion report
```
- [ ] `payroll` reports no failures.

---

## Scenario 1. Payroll setup
Sign in as **Payroll Administrator** (`demo.padmin@harbour.accfino.test`). Open **Payroll & Workforce**.

- [ ] Tabs shown include Dashboard, Employees, Timesheets, Leave, Pay Runs, Payslips, Payments, Super, PAYG, STP, Reports, Audit, Pay Items, Settings.
- [ ] **Settings > Organisation & payslips**: employer name `Harbour & Co Pty Ltd (DEMO)`, ABN `51 824 753 556`. Change the ABN to `11 111 111 111` and save: **refused** ("ABN is not valid"). Restore it.
- [ ] **Settings > Pay calendars**: three calendars (Fortnightly, Weekly casuals, Monthly executives). Open Fortnightly: periods are listed, pay date is 5 days after period end.
- [ ] Create a calendar with **no name**: the Save button is disabled. Create a duplicate name: refused.
- [ ] **Pay Items > Earnings**: Base salary and Ordinary hours are marked *system*. Try to remove Base salary: not offered / refused. Create `KMALLOW` ("Km allowance", Allowance, fixed $12) and save; it appears. Try the same code again: refused.
- [ ] **Settings > Leave policies**: Annual leave accrues 152 h/yr (38-hour week), loading 17.5%; Personal 76 h/yr; Long service has a minimum of 7 years of service.
- [ ] **Settings > Super funds**: AustralianSuper is the employer default; an SMSF exists.
- [ ] **Settings > Accounting**: seven ledger accounts are mapped (wages 477, super expense 478, reimbursements 479, wages payable 804, PAYG 825, super payable 826, deductions 806) plus the bank account 090.
- [ ] **Settings > Statutory rules**: rule set **2026-27**, super guarantee **12%**, maximum contribution base **$270,830**, super due **7 business days** after payday. The sources are labelled; ETP and termination-leave are marked *secondary* / *unverified*.
- [ ] **Settings > Payments**: company account number shows masked (`•••• 5678`), never in full.

## Scenario 2. Employee creation
As **Payroll Manager** (`demo.pmanager@harbour.accfino.test`), **Employees > New employee**.

- [ ] Click **Create employee** with everything blank: errors listed ("First name is required", "Annual salary must be greater than zero"), nothing saved.
- [ ] Enter First `Test`, Last `Starter`; **Employment & pay**: Full time, Salary **78000**, Fortnightly, Fortnightly calendar, start date `2026-09-01`. Create.
- [ ] The tabs Tax, Super, Bank, Recurring items, Leave unlock. A red notice says **No bank account** and **No super fund**, and a warning says **No TFN**.
- [ ] **Tax**: enter TFN `123456789`: *"not a valid TFN"*, Save disabled. Enter `123456782`: accepted; the screen then shows `*** *** 782`, never the full number.
- [ ] **Bank**: BSB `12` is rejected. Add `Test Starter`, BSB `062-000`, account `11112222`. Saved; shown as `•••• 2222`.
- [ ] **Super**: add AustralianSuper, member number `T1`, 100%. Change to 60%: refused (must total 100%).
- [ ] Reopen the employee: no readiness issues remain.
- [ ] A Payroll Manager has **no** *Reveal TFN* button (only Payroll Administrators and the Organisation Administrator do).

*Expected pay for this employee (used in Scenario 5):* gross **$3,000.00**, PAYG **$598**, super **$360.00**, net **$2,402.00**. With no TFN instead: PAYG **$1,410** (47%), net **$1,590.00**.

## Scenario 3. Timesheets
As **Payroll Manager**, **Timesheets**.

- [ ] Three open sheets: Marcus 21 Sep (**approved**), Sofia 21 Sep (**submitted**), Marcus 28 Sep (**submitted**). Earlier weeks are **processed**.
- [ ] **New timesheet** for a casual. Add a line with **25 hours**: error "more than 24 hours". A date outside the week: error. Hours `0`: error. Save is disabled until fixed.
- [ ] Enter 5 days of 8 hours (week of 12 Oct), **Save & submit**. Status becomes *submitted*.
- [ ] **Reject** Marcus's 28 Sep sheet: a reason is **required**. After rejecting, the reason shows on the row.
- [ ] **Approve** Sofia's 21 Sep sheet. Status *approved*.
- [ ] Try to edit or delete a *processed* sheet: no Edit/Delete is offered.
- [ ] Sign in as **Olivia** (employee login). **Timesheets** is empty: her four reports are salaried, and she cannot see Marcus's or Sofia's sheets (they do not report to her).

## Scenario 4. Leave
- [ ] As Payroll Manager, **Leave**: pending requests for **Olivia** (annual leave 12-16 Oct) and **Priya** (personal leave 5-6 Oct, 9.12 h). Marcus's compassionate leave is **rejected** with a note.
- [ ] Olivia's balances (Employees > Olivia > Leave): annual leave about **155.08 h**.
- [ ] **Request leave** for a casual employee using *Annual leave*: refused (casuals do not accrue it). Request more hours than the balance: **"Insufficient ... balance"**. A weekend-only range: refused (no scheduled hours). Overlapping dates: refused.
- [ ] **Reject** Priya's request with no reason: refused. With a reason: *rejected*.
- [ ] **Approve** Olivia's request. (You are not Olivia, so you can; Olivia herself could not approve her own.)
- [ ] Sign in as Olivia: **My Pay** shows her balances. She **cannot** approve her own leave. She *can* approve Liam's, Priya's, Daniel's and Zara's.
- [ ] **Leave accrual**: look at Tom Baxter > Leave > History: an *accrual* entry per finalised pay run, and *taken* entries for his paid week.
- [ ] **Leave in payroll:** see Scenario 6 (Olivia's approved leave is paid in the next period).

## Scenario 4b. Approvals, notifications and My Pay
- [ ] As **Olivia** (employee and manager), open **Payroll**: the tab bar shows **My Pay** and **Time & Leave**. If Liam, Priya, Daniel or Zara have a submitted timesheet or pending leave, **Time & Leave** carries a red count and the bell shows unread items.
- [ ] Open the bell and click an item: it is marked read and opens Time & Leave on the right sub-tab. **Mark all read** clears the count.
- [ ] In **Time & Leave > Leave**, Olivia sees **Approve / Reject** on her reports' pending requests and **not** on her own request (she has no manager, so the payroll team decides it).
- [ ] As **Payroll Manager**, the badge counts everything submitted or pending except anything of your own. After Olivia approves or rejects a report's request, that employee's bell shows the decision and reason.
- [ ] As an ordinary employee (a login linked to an employee with no reports): only **My Pay** is shown, with no **Time & Leave** tab and no duplicate screens. My Pay says who approves your requests, lists only your own leave and timesheets, and offers no Approve / Reject.
- [ ] Open the **Home** page: Payroll & Workforce tiles show no "Preview" badge, and there is a **My Pay** tile. As someone with no linked employee record, the tile explains how to link a login.
- [ ] Email: with SMTP configured, the approver gets "Timesheet to approve" / "Leave to approve" and the employee gets the decision. Without SMTP they are written to the mail outbox log. A mail failure must never block the action.

## Scenario 5. Standard pay run
Sign in as **Payroll Manager**. **Pay Runs** shows PR-0001 to PR-0006 finalised/paid and **PR-0022** in *Review* (the open fortnight 21 Sep to 4 Oct, pay date 9 Oct).

Open **PR-0022**. The stepper shows Draft ✓ > **Review**.
- [ ] 11 employees. Totals: gross **$34,099.25**, PAYG **$8,060.00**, net **$25,367.25**, super **$4,385.91**. **2 employees have errors**.
- [ ] **Approve is disabled** ("Resolve errors first").
- [ ] Expand **Olivia Chen**: lines Base salary $4,923.08, Salary sacrifice $300.00. Gross **$4,923.08**, taxable **$4,623.08**, PAYG **$1,116.00**, study loan **$292.00**, net **$3,215.08**, super **$590.77** (12% of $4,923.08, calculated *before* sacrifice), scale 2. YTD figures are shown.
  *Hand check:* weekly equivalent = floor(4,623.08 / 2) + 0.99 = 2,311.99 → 0.32 × 2,311.99 − 181.7319 = 558.1 → $558 × 2 = **$1,116**. HELP: 0.15 × 2,311.99 − 200.5615 = 146.2 → $146 × 2 = **$292**.
- [ ] Expand **Isla Moore**: error *"No bank account: net pay cannot be paid"*. **Kira Stone**: error *"Superannuation is payable but the employee has no super fund"*. **Jack Hill**: only a *warning* (no TFN), scale **4**, PAYG **$1,084** (47% of $2,307).
- [ ] **Exclude** Isla with no reason: refused. Exclude with reason "no bank details yet". Do the same for Kira.
- [ ] **Recalculate**. Errors drop to 0 (Jack's warning remains). Approve is enabled.
- [ ] **Approve**. Status *Approved*. **Return to review** is offered. Approve again.
- [ ] **Finalise...**: a confirmation explains it will create payslips, update leave and super and post the journal, and that the run can then only be reversed. Confirm.
- [ ] Status **Finalised**, the banner says 🔒 *Finalised and locked*. There are **no** Calculate / Approve / Exclude buttons.
- [ ] Open the *Integrity* tab: **"Finalised results are unchanged since finalisation"**.
- [ ] Create **your own** run: New pay run, calendar *Fortnightly*, "Show periods around" `2026-10-05`, choose **21 Sep to 4 Oct**: refused with *"already exists"* (duplicate protection). Choose **5 Oct to 18 Oct** and create it: it opens in *Draft*, with every employee listed.
- [ ] The *Test Starter* employee from Scenario 2 is included in that new run (once calculated: gross $3,000.00, PAYG $598, super $360.00, net $2,402.00).
- [ ] **Cancel run...** requires a reason, then the run shows *Cancelled* and the period is free again.

## Scenario 6. Complex pay run
As Payroll Manager, create a run for **5 Oct to 18 Oct** (pay date 23 Oct) and calculate it.

**6a. Leave paid through payroll.** Approve Olivia's leave first (Scenario 4), then calculate.
- [ ] Olivia's lines: Base salary $4,923.08; **Annual leave 38 h $2,461.54**; **Salary adjustment for leave -$2,461.54** (the salary already paid those hours); **Annual leave loading $430.77** (17.5%); Salary sacrifice $300.
- [ ] Gross **$5,353.85**, PAYG **$1,254**, study loan **$358**, super **$642.46**, net **$3,441.85**.

**6b. Bonus, allowance, deductions, reimbursement, HELP, salary sacrifice.** Use your **Test Starter** employee: change their salary to **$104,000** and tick *Has a study loan* on the Tax tab. Then, in the open run, expand the employee and use **+ Add bonus / adjustment**:
- Bonus **3,000**; Reimbursement **85.50** ("Taxi"). Assign recurring items on the employee beforehand: Tool allowance (default $50), Salary sacrifice, **400**, Union fees (default $20).
- [ ] Gross **$7,050.00** (4,000 + 50 + 3,000). Salary sacrifice **$400**, taxable **$6,650.00**.
- [ ] PAYG **$1,742** and study loan **$614** (the bonus is taxed with ATO *Method A*; below the 47% cap of $1,410).
- [ ] Union fees **$20.00** and reimbursement **$85.50** (not taxed). Net pay **$4,359.50**.
- [ ] Super **$840.00** = 12% of $7,000 (salary + bonus; the tool allowance is **not** ordinary-time earnings). Super total including the $400 sacrifice: **$1,240.00**.
  *Hand check of the bonus:* regular taxable 3,650: tax $806, HELP $146. Add $3,000/26 = $115 → 3,765: tax $842, HELP $164. (842 − 806) × 26 = **936**, (164 − 146) × 26 = **468**. 806 + 936 = **1,742**; 146 + 468 = **614**.
- [ ] Remove the bonus input (Bonuses & adjustments tab): recalculation drops the bonus.

**6c. Bonus in history.** Open **Hannah Wells'** September monthly run (Pay Runs, the monthly run of 30 Sep): gross **$24,083.33**, PAYG **$7,817** (regular $3,137 + $4,680 on the bonus).

**6d. Unpaid leave and a starter.** Open **PR-0004** (pay date 28 Aug): Tom's gross **$1,576.93** (an unpaid week took $1,576.92 off his $3,153.85). Open **PR-0006** (25 Sep): Tom gross **$3,429.81** (includes $275.96 leave loading), Daniel Park gross **$3,046.15** (his first, part, pay: 9 of 10 working days).

## Scenario 7. Payroll approval
- [ ] Draft: only *Calculate* and *Cancel run*. Review: *Recalculate*, *Approve*, *Cancel run*. Approved: *Return to review*, *Finalise*.
- [ ] **Stale protection:** create a run, calculate it, then (in another tab) change an employee's salary. Back on the run, **Approve** is refused: *"Pay inputs changed since this run was calculated... Recalculate."*
- [ ] **Finalised cannot be edited:** with the API (or by trying the UI), every edit on a finalised run is refused with *"is finalised and cannot be changed. Use Reverse to correct it."*
- [ ] Finalise a run twice in two tabs: the second says *"already finalised: it was not processed again."* and only **one** payslip set and one journal exist.
- [ ] **Reverse...** (Payroll Administrator only; a Payroll Manager does not see it). A reason is required. After reversing, a **reversal run** appears (amounts negated), the original is marked *Reversed*, and the period is free for a corrected run. Open the reversal: *"reversal of another pay run. It cannot be changed."*
- [ ] **Separation of duties:** Settings > Organisation, tick *the person who created a pay run cannot approve it*. A run you created can no longer be approved by you.

## Scenario 8. Payslips
- [ ] As Payroll Administrator, **Payslips** lists them. Open Olivia's payslip for 17 Jul: employer + ABN, employee, period 29 Jun to 12 Jul, pay date 17 Jul. Gross **$4,923.08**, PAYG **$1,116.00**, study loan **$292.00**, salary sacrifice **$300.00**, net **$3,215.08**, super (Aware Super, member number masked) **$590.77**, YTD, leave balances.
- [ ] The bank account shows masked (`•••• nnnn`, last four digits only), never in full.
- [ ] **Print / save as PDF** opens a clean printable page; **Download** saves an `.html` file. (The app has no PDF library: use the browser's *Save as PDF*.)
- [ ] Sign in as **Olivia**: **My Pay** lists **only her** payslips. Another employee's payslip is not reachable.
- [ ] Payslip totals equal the run: Reports > Payroll Summary for PR-0001, *Net* equals the sum of the run's payslips.

## Scenario 9. Payments
Sign in as Payroll Manager. **Payments**.
- [ ] PR-0006 is under *Finalised pay runs awaiting payment* (net **$19,714.43**). PR-0001 to PR-0005 have **completed** batches.
- [ ] **Prepare payment**: confirm. A batch opens with one line per bank account; **Grace Lim has two lines** ($200 fixed plus the remainder). The total equals the run's net pay.
- [ ] Try to prepare it again: **refused** (a live batch already exists).
- [ ] **Download bank file (ABA)**: the first time (company details complete in the demo) a file downloads. Every line is 120 characters; the first record starts `0`, the last `7`, with one balancing debit.
- [ ] **Mark as paid...**: a confirmation states *no money is sent*. Items become *paid*; the run becomes **Paid**. Mark as paid again: refused.
- [ ] **Reconcile paid items**: reconciliation shows *reconciled*. Record one item as **Returned...** (reason required).
- [ ] Ledger: Books & Accounting > Ledger: a journal *"Payroll payment PR-0006-PAY"* (Dr Wages Payable, Cr Business Cheque Account).

## Scenario 10. Accounting integration
As Accountant (`demo.accountant@harbour.accfino.test`) or Administrator, open **PR-0001 > Ledger journal**.
- [ ] "Ledger journal #..." posted on **17 Jul 2026**, status *Posted*, "debits equal credits".
- [ ] Accounts: **477 Wages and Salaries** debit = the run's gross; **478 Superannuation** debit and **826 Superannuation Payable** credit = the run's super; **825 PAYG Withholdings Payable** credit = PAYG + study loan; **804 Wages Payable** credit = net pay; **806 Payroll Deductions Payable** for deductions.
- [ ] Expand *Employee-level lines*: each carries a transaction reference like `PR-0001-E0001-001`. Search one: it matches the line in the run.
- [ ] Books & Accounting > General Ledger: the same journal appears in the journal list with the same totals (reference `PR-0001`). The trial balance still balances.
- [ ] Open a **reversed** run: the journal shows *Reversed*, and the ledger has a reversing journal dated the reversal date.

## Scenario 11. Reports
Sign in as Accountant or Payroll Administrator. **Reports**, set From `2026-07-01`, To `2026-10-05`.
For **each of the 18 reports** (Payroll Summary, Register, Employee Payroll, Gross-to-Net, PAYG Withholding, Superannuation, Leave Balance, Leave Liability, Timesheet, Deduction, Earnings, Payroll Journal, Cost by Department / Employee / Pay Period, Year-to-Date, Termination, Audit):
- [ ] The report runs with no error, the table and totals show.
- [ ] Wherever a green **"✓ Reconciled"** line appears (most do), it says the total agrees with the payroll lines, payslips, journal or super contributions. **A red "DOES NOT RECONCILE" is a defect.**
- [ ] **Export CSV** downloads; open it: title, filters, headers, rows, totals.
- [ ] Filter by **Employee** (Olivia): only her rows. By **Department** (Finance): only Finance. By **Pay run**: only that run. A From date after the To date: refused.
- [ ] Specific checks: **Payroll Summary** total employees per run; **PAYG Withholding** total = credits to account 825; **Termination** lists Noah Fisher with unused leave **$3,713.80** (paid in PR-0004); **Gross-to-Net**: every row's check is $0.00; **Leave Liability** lists annual leave at current rates plus loading and a 12% super on-cost.
- [ ] **Year-to-date** for Olivia equals her latest payslip YTD.

## Scenario 12. Security
Use a private window per login. For each person try the listed actions.

| Sign in as | Must be able to | Must NOT be able to |
|---|---|---|
| Organisation Administrator | everything, incl. Reveal TFN, Reverse, Settings, Audit | |
| Payroll Administrator | everything in payroll incl. Reveal TFN (audited), Reverse, Settings, Pay Items | change Organisation settings / users |
| Payroll Manager | create, calculate, approve, finalise, pay, manage employees | see **Settings**, **Audit**, **Pay Items** tabs; **Reverse**; **Reveal TFN** |
| Accountant | read runs, reports, journals, audit, salaries | change anything; see **TFN status or bank details** on an employee; see Settings |
| Bookkeeper | use the books | open Payroll at all (403 / no tabs) |
| Olivia (employee + line manager) | **My Pay**; see her 4 reports' names, positions and leave; approve their leave and timesheets | see any **salary, tax or bank** detail (even her own team's); open Pay Runs, Payslips, Reports, Settings; see anyone else's payslip; approve her own leave |

- [ ] Reveal a TFN as Payroll Administrator, then check **Audit**: an `employee.tfn_viewed` entry with user and time.
- [ ] No full TFN or account number appears anywhere in the browser: inspect the network responses (F12) for an employee: only masked forms such as `*** *** nnn` and `•••• nnnn`.
- [ ] Sign in to **Outback** as its Payroll Administrator: **none** of Harbour's employees, runs or payslips are visible; a Harbour pay-run URL gives *not found*.
- [ ] Change an employee's salary, bank details and tax details; **Audit** shows who, when, and before/after (account numbers are never in the log).
- [ ] An employee cannot approve their own timesheet or leave: even a Payroll Administrator.

## Scenario 13. Edge cases
- [ ] **Missing bank details**: Isla Moore blocks approval with a clear message (Scenario 5).
- [ ] **Missing TFN**: Jack Hill is paid at the no-TFN rate (scale 4, $1,084 on $2,307.69) with a warning.
- [ ] **Missing super**: Kira Stone blocks approval.
- [ ] **Zero earnings**: run the weekly calendar for **21 Sep to 27 Sep** (pay 2 Oct). Calculate. **Leo Zero** (no hours) and **Sofia** (sheet not yet approved) show warnings *"Zero earnings"* and *"unapproved timesheets"*; **Marcus**: gross **$1,483.50**, PAYG **$293**, super **$165.60**, net **$1,190.50**. Approve Sofia's timesheet (Scenario 3) and recalculate: Sofia gross **$1,056.00**, PAYG $156, net $900.00, super $126.72. Run totals: gross **$2,539.50**, PAYG **$449**, net **$2,090.50**, super **$292.32**.
  *Hand check (Marcus):* 40 h × $34.50 = $1,380 + 2 h × $51.75 (1.5×) = $103.50 → $1,483.50. Overtime is **not** super-able: 12% × 1,380 = **$165.60**. Tax: floor(1,483) + 0.99 = 1,483.99 → 0.32 × 1,483.99 − 181.7319 = 293.1 → **$293**.
- [ ] **Negative / correction transactions**: reverse a finalised run (Scenario 7); the reversal shows negative amounts and nets the YTD to zero. **Outback > Fortnight 3** was reversed and re-run: Ruby Evans' YTD after her latest pay is **$15,076.92** (two pays at $64,000 plus four at the corrected $66,000), not double counted.
- [ ] **Terminated employee**: Noah Fisher shows *Terminated* (ended 21 Aug 2026), appears in no run after PR-0004, and his final pay (PR-0004, pay date 28 Aug) included **Unused leave payout $3,713.80**. Try to request leave for him: refused (leave is only for active employees).
- [ ] **Unpaid leave**: Tom's PR-0004 (Scenario 6d).
- [ ] **Duplicate payroll attempt**: Scenario 5 (create) and Scenario 7 (finalise twice).
- [ ] **Re-running a finalised pay run**: Calculate on PR-0001 is not offered; via the API it returns 409 *"is finalised and cannot be changed"*.
- [ ] **Invalid timesheet**: Scenario 3. **Invalid pay item**: Scenario 1 (duplicate code / bad code `BAD CODE` / no name). **Invalid employee configuration**: Scenario 2 (casual with a salary: *"Casual employees are paid by the hour"*; end date before start; invalid postcode `12`).
- [ ] **Termination payments**: add an employee, terminate them, then in a run add *Unused leave payout* and *Employment termination payment* (tick *Genuine redundancy*). The tax-free amount is **$13,598 + $6,801 per completed year of service**; the remainder is taxed at 32% / 17% (age 60+) up to $270,000, 47% above.
- [ ] **Super**: *Super* tab, status *Overdue* lists contributions past the 7-business-day due date (40 as at 5 Oct 2026 for Harbour). Select some, **Mark as paid** with a reference: they become *paid*. Marking them again is refused.
- [ ] **STP**: *STP* tab. A red banner says AccFino **does not lodge with the ATO**. Prepare an event from PR-0006, view the payload (no TFN in it), **Mock submit**: a reference starting `MOCK-NOT-LODGED` is recorded. Year-end finalisation is refused until the year has ended and every run is finalised.

---

## Recording results
| Scenario | Tester | Date | Pass / Fail | Defect notes |
|---|---|---|---|---|
| 1 Setup | | | | |
| 2 Employee | | | | |
| 3 Timesheets | | | | |
| 4 Leave | | | | |
| 5 Standard run | | | | |
| 6 Complex run | | | | |
| 7 Approval | | | | |
| 8 Payslips | | | | |
| 9 Payments | | | | |
| 10 Accounting | | | | |
| 11 Reports | | | | |
| 12 Security | | | | |
| 13 Edge cases | | | | |
