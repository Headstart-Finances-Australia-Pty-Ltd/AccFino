# Payroll API reference

_Generated from the router by `generate_reference.py`. All routes are mounted under `/payroll` (the SPA proxy adds `/api`). Every call needs a bearer token and the `X-Org-Id` header; every call is re-authorised on the server._

Conventions: errors are `{"detail": "message"}` with 401 (not signed in), 403 (role cannot do this), 404 (missing, or not in your organisation / not yours), 409 (invalid state, duplicate or already done), 422 (validation). **No field is ever called `user_id` or `username`**: the platform's AuthGuard treats those names as "the caller", so the employee<->login link is `login_user_id`.

**99 endpoints.**

| Method | Path | Notes |
|---|---|---|
| GET | `/payroll/approvals/pending` | pending |
| GET | `/payroll/audit` | audit_list |
| GET | `/payroll/calendars` | calendars |
| POST | `/payroll/calendars` | calendar_create |
| PUT | `/payroll/calendars/{cid}` | calendar_update |
| GET | `/payroll/calendars/{cid}/periods` | calendar_periods |
| GET | `/payroll/dashboard` | get_dashboard |
| GET | `/payroll/departments` | list_departments |
| POST | `/payroll/departments` | create_departments |
| PUT | `/payroll/departments/{rid}` | update_departments |
| GET | `/payroll/employees` | list_ |
| POST | `/payroll/employees` | create |
| GET | `/payroll/employees/login-users` | login_users |
| GET | `/payroll/employees/{emp_id}` | get |
| PUT | `/payroll/employees/{emp_id}` | update |
| PUT | `/payroll/employees/{emp_id}/bank` | bank |
| POST | `/payroll/employees/{emp_id}/items` | item_add |
| DELETE | `/payroll/employees/{emp_id}/items/{assign_id}` | item_remove |
| GET | `/payroll/employees/{emp_id}/leave` | leave_balances |
| POST | `/payroll/employees/{emp_id}/leave/adjust` | leave_adjust |
| GET | `/payroll/employees/{emp_id}/leave/history` | leave_history |
| PUT | `/payroll/employees/{emp_id}/super` | super_ |
| PUT | `/payroll/employees/{emp_id}/tax` | tax |
| POST | `/payroll/employees/{emp_id}/tax/reveal-tfn` | reveal |
| POST | `/payroll/employees/{emp_id}/terminate` | terminate |
| GET | `/payroll/employees/{emp_id}/termination-suggestion` | term_suggestion |
| GET | `/payroll/leave-types` | list_leave-types |
| POST | `/payroll/leave-types` | create_leave-types |
| PUT | `/payroll/leave-types/{rid}` | update_leave-types |
| GET | `/payroll/leave/my-balances` | my_balances |
| GET | `/payroll/leave/requests` | requests (`?mine=true` = only the caller's own; each row carries `can_decide`) |
| POST | `/payroll/leave/requests` | create |
| POST | `/payroll/leave/requests/{rid}/approve` | approve |
| POST | `/payroll/leave/requests/{rid}/cancel` | cancel |
| POST | `/payroll/leave/requests/{rid}/reject` | reject |
| GET | `/payroll/ledger-accounts` | ledger_accounts |
| GET | `/payroll/locations` | list_locations |
| POST | `/payroll/locations` | create_locations |
| PUT | `/payroll/locations/{rid}` | update_locations |
| GET | `/payroll/me` | me |
| GET | `/payroll/notifications` | notifications |
| POST | `/payroll/notifications/read-all` | read_all |
| POST | `/payroll/notifications/{notification_id}/read` | read_one |
| GET | `/payroll/pay-items` | list_pay-items |
| POST | `/payroll/pay-items` | create_pay-items |
| DELETE | `/payroll/pay-items/{item_id}` | item_delete |
| PUT | `/payroll/pay-items/{rid}` | update_pay-items |
| GET | `/payroll/payments` | payments |
| GET | `/payroll/payments/{pid}` | payment |
| GET | `/payroll/payments/{pid}/aba` | payment_aba |
| POST | `/payroll/payments/{pid}/cancel` | payment_cancel |
| POST | `/payroll/payments/{pid}/complete` | payment_complete |
| POST | `/payroll/payments/{pid}/items/{item_id}/status` | payment_item |
| POST | `/payroll/payments/{pid}/reconcile` | payment_reconcile |
| GET | `/payroll/payslips` | payslips |
| GET | `/payroll/payslips/{pid}` | payslip |
| GET | `/payroll/payslips/{pid}/html` | payslip_html |
| GET | `/payroll/reports` | report_list |
| GET | `/payroll/reports/{key}` | report |
| GET | `/payroll/rules` | The statutory rule sets in force (rates are DATA in the rules file, not code). |
| GET | `/payroll/runs` | listing |
| POST | `/payroll/runs` | create |
| GET | `/payroll/runs/{run_id}` | get |
| POST | `/payroll/runs/{run_id}/approve` | run_approve |
| POST | `/payroll/runs/{run_id}/calculate` | run_calculate |
| POST | `/payroll/runs/{run_id}/employees/{employee_id}/exclude` | exclude |
| POST | `/payroll/runs/{run_id}/employees/{employee_id}/include` | include |
| POST | `/payroll/runs/{run_id}/finalise` | run_finalise |
| POST | `/payroll/runs/{run_id}/inputs` | add_input |
| DELETE | `/payroll/runs/{run_id}/inputs/{input_id}` | remove_input |
| GET | `/payroll/runs/{run_id}/integrity` | integrity |
| GET | `/payroll/runs/{run_id}/journal` | journal |
| POST | `/payroll/runs/{run_id}/payments` | payment_prepare |
| POST | `/payroll/runs/{run_id}/reverse` | reverse |
| POST | `/payroll/runs/{run_id}/stp` | stp_prepare |
| POST | `/payroll/runs/{run_id}/unapprove` | run_unapprove |
| POST | `/payroll/runs/{run_id}/void` | void |
| GET | `/payroll/settings` | get_settings_ |
| PUT | `/payroll/settings` | put_settings |
| GET | `/payroll/stp` | stp_list |
| GET | `/payroll/stp/finalisation` | stp_final |
| POST | `/payroll/stp/finalise` | stp_do_final |
| GET | `/payroll/stp/payment-summary` | stp_summary |
| GET | `/payroll/stp/{event_id}` | stp_get |
| POST | `/payroll/stp/{event_id}/mock-submit` | stp_mock |
| GET | `/payroll/super` | super_list |
| GET | `/payroll/super-funds` | list_super-funds |
| POST | `/payroll/super-funds` | create_super-funds |
| PUT | `/payroll/super-funds/{rid}` | update_super-funds |
| POST | `/payroll/super/mark-paid` | super_paid |
| GET | `/payroll/timesheets` | listing (`?mine=true` = only the caller's own; each row carries `can_decide` / `can_edit`) |
| POST | `/payroll/timesheets` | create |
| DELETE | `/payroll/timesheets/{ts_id}` | delete |
| GET | `/payroll/timesheets/{ts_id}` | get |
| PUT | `/payroll/timesheets/{ts_id}` | update |
| POST | `/payroll/timesheets/{ts_id}/approve` | approve |
| POST | `/payroll/timesheets/{ts_id}/reject` | reject |
| POST | `/payroll/timesheets/{ts_id}/reopen` | reopen |
| POST | `/payroll/timesheets/{ts_id}/submit` | submit |
