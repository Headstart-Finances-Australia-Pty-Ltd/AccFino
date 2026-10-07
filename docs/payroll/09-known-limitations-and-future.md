# Known limitations and future integration points

## Limitations (stated plainly)
**Compliance and statutory**
- **AccFino does not lodge with the ATO.** STP output is a payload prepared for review with a *mock* submission that only records a reference (`MOCK-NOT-LODGED-...`). Pay events, update events and finalisation data follow STP Phase 2 / Payday Super concepts (qualifying earnings, super liability) but are **not an ATO-certified file**. The UI and the registry say so.
- Statutory figures for **ETP, genuine redundancy and the flat rate on pre-1993 leave** are from secondary sources or unverified (see 06). PAYG, study loans and super parameters were verified against ATO pages.
- 2026-27 is the **only** rule set; the engine refuses to calculate other years. Add earlier years' rules to back-date.
- Medicare levy **family** adjustments, working holiday maker (Schedule 15) rates, FBT calculation, and the ETP whole-of-income cap are not modelled.
- **Super due dates ignore public holidays** (they can be a day early). There is no clearing-house integration: you record payment with your reference.
- Long service leave eligibility is a single "minimum years" setting, not a state-by-state rule set.
- Awards, enterprise agreements and automatic penalty/overtime rules are not modelled: penalties are pay items you enter.

**Payments and documents**
- **No bank connection.** The ABA (Cecil layout) file was written from the published layout, **not tested with a bank**: validate it with yours before use. "Mark as paid" records payment; nothing is sent.
- The application has **no PDF library**: payslips are print-ready HTML (browser *Save as PDF*).
- The payment-summary view provides the data; there is no formatted PDF.

**Product and quality**
- The UI was verified by unit tests, a production build and API tests, but **not by an automated browser (E2E) run**. Use the manual testing guide for the on-screen walk-through.
- **Approval notifications** are the in-app bell plus a plain-text email, sent after the action is saved (no push or SMS, no per-person preference, no reminder or escalation if an approver does nothing, no delegate/cover approver when a manager is away). The bell refreshes every minute rather than live.
- Employee "Manager" is derived from reporting lines (an employee with direct reports), so a manager must be an employee record.
- Reports return up to the data volume of a typical SME in one response (no server-side paging); the grids page on screen.
- One unexplained, non-reproducible `IllegalStateChangeError` occurred once in a multi-threaded PostgreSQL test (it did not recur in four repeat runs or 30 further concurrent attempts, which all behaved correctly). It is recorded rather than explained.

## Future integration points
- **ATO**: replace `stp.mock_submit` with a certified STP/ebMS client; the payload builders in `services/stp.py` are the seam.
- **Clearing house / SuperStream**: `PaySuperContribution` is the per-fund, per-component liability list to submit; `superfunds.mark_paid` is where a confirmation lands.
- **Bank**: `payments.prepare` already produces per-account items and an ABA file; a bank API would take those items and call `payments.complete` / `set_item_status` from a webhook.
- **Open Banking reconciliation**: payment items carry `reconciliation` status ready to be matched to bank-feed lines (Open Banking module, through a `public` facade).
- **Timesheets**: `pay_timesheets` / lines can be filled by an import or a mobile app; the approval flow is unchanged.
- **Statutory updates**: a new rule set in the JSON file (06); no code change.
- **Awards**: a rules layer that turns worked time into pay-item lines would plug into `runbuild.build`, ahead of the engine.
