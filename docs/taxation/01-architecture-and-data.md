# 01 – Architecture and data

## Principle: the ledger stays the source of truth
Taxation stores only what the ledger cannot: the tax profile, due dates, user adjustments and overrides, workpapers and evidence, snapshots of what was reviewed, approved and lodged, and the audit trail. GST, PAYG, profit, fixed assets and documents are **read** from Accounting and Payroll through their `public` facades (architecture rule R3; the boundary checker reports 0 couplings).

| Need | Taken from | Facade function |
|---|---|---|
| GST labels G1, G10, G11, 1A, 1B and GST-account reconciliation | Accounting ledger | `gst_summary` |
| Wages W1, PAYG withheld W2 | Payroll journals in the ledger | `payg_summary` |
| Cross-check of PAYG to pay runs | Payroll | `withholding_for_period` |
| Profit for the income year | Ledger | `profit_and_loss` |
| Assets and book depreciation | Fixed Assets | `fixed_assets_for_tax` |
| Suspense and loan balances | Ledger | `system_account_balance`, `account_balance` |
| Linking evidence to Documents | Accounting attachments | `attachment_info` |
| Employee names for FBT | Payroll | `employee_names` |

## Layers
`engine/` pure Decimal functions, no database, no rates (income tax, BAS labels, FBT, Division 7A, CGT, depreciation, calendar, rules loader) → `services/` rules, workflows, permissions, audit → `api/` thin HTTP at `/tax` → `frontend/src/modules/taxation`.

## Tables (prefix `tax_`, every row has `org_id`)
`tax_profiles`, `tax_rule_overrides`, `tax_registrations`, `tax_obligations`, `tax_bas_statements`, `tax_adjustments`, `tax_returns`, `tax_cgt_events`, `tax_capital_losses`, `tax_fbt_benefits`, `tax_fbt_returns`, `tax_div7a_loans`, `tax_div7a_payments`, `tax_workpapers`, `tax_evidence`, `tax_scenarios`, `tax_audit`. Money is `NUMERIC(18,2)`. Check constraints enforce status and type values, non-negative amounts and date order. Created by the platform's normal startup (`registry.import_all_models()` then `create_all`); verified on PostgreSQL 16.

## How every figure is tagged
Each working step and BAS label carries one of: **source** (read from ledger/payroll), **calculated**, **user-entered**, **assumption**, **estimate**, or **review** (needs a professional). The UI shows the tag beside the number; workpapers and exports keep it.

## Calculation snapshots and stale protection
Calculating a BAS, return or FBT return stores the working and a fingerprint of its inputs. Approval recomputes the fingerprint; if the ledger, payroll, adjustments, CGT events, instalments or rates changed since, approval is refused with "recalculate". Documents that are approved, lodged or paid cannot have their inputs changed (adjustments, CGT events and FBT benefits for that year are locked).

## Integration points
- **BAS to return:** PAYG instalments (label 5A) on lodged or paid statements become the return's credits.
- **CGT to return:** the net capital gain for the year is added; losses carried forward are reported.
- **Assets to return:** depreciation review generates add-back and deduction adjustments (replaced, not duplicated, on regeneration).
- **Payroll to BAS and FBT:** W1/W2 from payroll journals, with a mismatch error if pay runs and ledger disagree; employees picked on FBT benefits.
- **Calendar to documents:** creating a BAS or return links its obligation; lodgement and payment are recorded on the document and mirrored to the calendar.
