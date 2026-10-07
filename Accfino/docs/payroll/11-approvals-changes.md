# Approvals, notifications and My Pay (change note)

| Gap | What changed |
|---|---|
| No notifications | New `pay_notifications` table, `services/notify.py`, `/payroll/notifications*`. Bell in the Payroll header; email copy (best effort). |
| Approvers had to hunt for pending items | `GET /payroll/approvals/pending` and a red count badge on the **Time & Leave** tab (managers and payroll staff). |
| Approve / Reject shown to the wrong people | Rows carry `can_decide` (and timesheets `can_edit`) from the server; the buttons follow them. |
| Duplicate tabs for employees | Ordinary employees see **My Pay** only. My Pay now lists only the person's own items (`?mine=true`), even for a manager or payroll administrator. |
| Employee with no manager | Their requests go to the payroll team, who are notified. `/me` returns `approver` and My Pay tells the employee who approves. |
| "Preview" on Payroll tiles | All Payroll & Workforce modules were `status: beta` in `core/config/modules.json`; now `live`. |
| My Pay tile | Removed `home: false`, so My Pay has a Home tile. Opening it without a linked employee record shows an explanation. |

Tests added: `AccFino_Testing/tests/modules/payroll/approvals_test.py`; frontend cases in `payroll.test.jsx` and `modules.test.js`.
