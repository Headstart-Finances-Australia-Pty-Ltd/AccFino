"""Payroll HTTP API (mounted at /payroll). The API layer only validates, authorises and calls services; business rules live in services/ and engine/.
NOTE: no route or body here may use the names user_id / username - the platform AuthGuard treats them as 'the caller' (the employee<->login link is login_user_id)."""
from fastapi import APIRouter

from accfino.modules.payroll.api import config_api, employees_api, imports_api, leave_api, money_api, notifications_api, runs_api, timesheets_api

router = APIRouter()
for r in (config_api.router, employees_api.router, leave_api.router, timesheets_api.router, notifications_api.router, runs_api.router, money_api.router, imports_api.router):
    router.include_router(r)
