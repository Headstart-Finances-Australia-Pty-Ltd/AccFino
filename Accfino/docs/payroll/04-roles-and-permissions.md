# Payroll roles and permissions

_Generated from `accfino/modules/payroll/access.py` by `generate_reference.py`._

Payroll uses the platform's organisation roles - there is no second login or role store. Two roles were added to Core for Phase 2: `payroll_admin` and `employee` (no ledger access at all).

| Capability | Organisation Administrator | Payroll Administrator | Payroll Manager | Accountant | Legacy 'admin' |
|---|---|---|---|---|---|
| access manage | ✓ |  |  |  |  |
| audit view | ✓ | ✓ |  | ✓ | ✓ |
| config manage | ✓ | ✓ |  |  |  |
| employees manage | ✓ | ✓ | ✓ |  |  |
| employees view | ✓ | ✓ | ✓ | ✓ | ✓ |
| items manage | ✓ | ✓ |  |  |  |
| journal view | ✓ | ✓ | ✓ | ✓ | ✓ |
| leave approve | ✓ | ✓ | ✓ |  |  |
| leave manage | ✓ | ✓ | ✓ |  |  |
| payments manage | ✓ | ✓ | ✓ |  |  |
| reports view | ✓ | ✓ | ✓ | ✓ | ✓ |
| run approve | ✓ | ✓ | ✓ |  |  |
| run create | ✓ | ✓ | ✓ |  |  |
| run finalise | ✓ | ✓ | ✓ |  |  |
| run reverse | ✓ | ✓ |  |  |  |
| sensitive view | ✓ | ✓ | ✓ | ✓ | ✓ |
| stp manage | ✓ | ✓ | ✓ |  |  |
| tfn reveal | ✓ | ✓ |  |  |  |
| timesheets approve | ✓ | ✓ | ✓ |  |  |
| timesheets manage | ✓ | ✓ | ✓ |  |  |
| view | ✓ | ✓ | ✓ | ✓ | ✓ |

**Employee / Manager are not roles you assign for payroll:**

- **Employee**: anyone whose login is linked to an employee record (`login_user_id`). They can see only their own payslips, leave, timesheets and details. The platform role `employee` gives such a person *no* access to the books.
- **Manager**: derived. A user whose linked employee has direct reports can approve those reports' timesheets and leave and see their names and leave. No salary, tax or bank access.
- **Nobody approves their own timesheet or leave**, including payroll administrators.
- `bookkeeper` and `readonly` have no payroll access unless they are also linked to an employee (then: self-service only).

What each sees of sensitive data:

| Data | Org Admin / Payroll Admin | Payroll Manager | Accountant | Manager | Employee |
|---|---|---|---|---|---|
| Salary / pay rate | yes | yes | yes | no | own |
| Tax details (masked TFN) | yes | yes | yes | no | own |
| Full TFN | Payroll Admin / Org Admin only (audited each time) | no | no | no | no |
| Bank details (account masked) | yes | yes | no | no | own |
| Full bank account number | never returned by any API | never | never | never | never |
| Audit trail | yes | no | yes | no | no |

## Approvals: who is asked, who is told

- **Who approves**: the employee's *manager* (set on the employee record) when that manager has a login. An employee with no manager, or whose manager has no login, is approved by the **payroll team** (Organisation Admin, Payroll Administrator, Payroll Manager). Set a manager on every employee to keep requests with the right person.
- **Notifications**: submitting a timesheet or requesting leave notifies the approver(s); approving or rejecting notifies the employee (with the reason). Each notification appears in the bell at the top of the Payroll screen and is also emailed. The person who performs an action is never notified of it, and nobody is asked to approve their own request.
- **Email** is best effort: a mail failure never blocks or undoes the payroll action. Emails go through the platform mail settings (without SMTP they are written to the outbox log). Set `PAYROLL_EMAIL_NOTIFICATIONS=0` to turn emails off (the bell stays). Set `APP_BASE_URL` to add a link to the email.
- **Pending badge**: the *Time & Leave* tab shows how many submitted timesheets and pending leave requests the signed-in person may decide (their direct reports', or everyone's for payroll staff; never their own). `GET /payroll/approvals/pending`.
- **Buttons follow permission**: Approve / Reject appear only on rows the server says you may decide (`can_decide`); Edit / Submit / Delete only on your own drafts (`can_edit`). The server still refuses anything else.
- **Employees**: an ordinary employee uses *My Pay* only (payslips, leave, timesheets, all strictly their own via `?mine=true`). *Time & Leave* is for managers and payroll staff. *My Pay* tells the employee who will approve their requests.
