# Demo data and seeding

> **DEMO / TEST DATA.** Every demo organisation is named `... (DEMO)` and every demo employee has `is_demo = true`. The loader and the reset only ever touch organisations whose name ends in `(DEMO)`. Never run it against a production organisation.

## Commands
```bash
cd AccFino/backend
export PYTHONPATH=. ACCFINO_DATA_ROOT=../../AccFino_Data     # and DATABASE_URL, JWT_SECRET
python -m accfino.modules.payroll.demo_seed --status           # what exists
python -m accfino.modules.payroll.demo_seed --load             # create the demo data; does nothing if it already exists (idempotent)
python -m accfino.modules.payroll.demo_seed --reset            # remove the demo organisations, their users and ALL their data incl. the ledger
python -m accfino.modules.payroll.demo_seed --reload           # reset then load: a clean, repeatable environment (about 10 seconds)
    add --yes                      skip the "type YES" safety prompt (needed in scripts)
    add --sqlite /tmp/demo.db      build an offline SQLite database instead of using DATABASE_URL (no PostgreSQL needed)
```
- **Reset** uses the platform's own force-delete: one transaction, the ledger's immutability triggers lifted inside it and restored before commit. It leaves **zero** rows behind (tested, including on PostgreSQL).
- **Idempotent**: loading twice changes nothing (tested). To rebuild use `--reload`.
- **From a clean database** (for example before running the manual tests): `python -m accfino.core.init_db`, then `--reload --yes`.
- Password for all demo logins: `DEMO_PASSWORD` (default `Demo-Payroll-1!`).
- The history is produced by the **real services** (create > calculate > approve > finalise > payslips > ledger journal), not inserted rows, so it reconciles everywhere. A seed bug that creates an invalid payroll fails loudly rather than being swallowed.
- It is limited to **FY2026-27**: statutory rules are only loaded for that year.

## What is created
| | Harbour & Co | Outback Supplies |
|---|---|---|
| Employees | 17 | 8 |
| Pay runs | 22 (6 fortnightly, 12 weekly, 3 monthly finalised; 1 open fortnight in *Review*) | 20 (6 fortnightly incl. a **reversal and corrected re-run**, 12 weekly) |
| Calendars | fortnightly, weekly (casuals), monthly (executives) | fortnightly, weekly |
| Super funds | AustralianSuper (default), Aware, HostPlus, an SMSF | the same |
| Logins | owner, payroll admin, payroll manager, accountant, bookkeeper, **Olivia (employee + line manager)** | the same five staff roles |

Scenarios covered (names and values are in the [testing guide](10-manual-testing-guide.md)): full-time salaried, part-time, casual with overtime and Saturday penalty, new starter (prorated), leave taken (annual, unpaid), bonus (Method A), allowance, multiple deductions, salary sacrifice (fixed and %), HELP, foreign resident, no tax-free threshold, different/split super funds, an SMSF, two bank accounts, a high earner, a leaver paid unused leave, a pay-run reversal and correction, zero earnings, and **invalid/incomplete setups** left in the open period: no bank account, no TFN, no super fund, casual with no hours.

Also created: timesheets in every state (processed, approved, submitted), leave requests (pending, approved, rejected), completed and reconciled payments for five runs with one awaiting payment, paid and overdue super contributions, STP pay events (some mock-submitted), opening leave balances.

## Verified by tests (`demo_seed_test.py`)
Volume and labelling; **every report reconciles for both companies**; every finalised run is internally consistent (run = employees = payslips = lines; journal balanced and equal to the ledger; integrity hash intact; payments equal net pay); Olivia's PAYG hand-worked from the ATO formula; Hannah's bonus hand-worked from Schedule 5; every scenario above exists and behaves; the open period has exactly the planned errors; load is idempotent; reset is complete; the data rebuilds from nothing.
