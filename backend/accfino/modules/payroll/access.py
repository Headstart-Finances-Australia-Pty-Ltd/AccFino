"""
Payroll authorisation. Built on the platform's organisation roles (OrgContext) - there is no second login or role store.

  owner (Organisation Admin) / platform admin   everything
  payroll_admin (Payroll Administrator)         everything in payroll, including configuration, reversals and revealing TFN / bank numbers
  payroll (Payroll Manager)                     run payroll end to end (create, calculate, approve, finalise, pay), manage employees, approve
                                                time and leave; sees salary, tax and bank details MASKED; cannot configure, reverse or reveal
  accountant / admin(legacy)                    read-only: reports, journals, audit, salaries (no TFN / bank details)
  employee, or ANY user linked to an employee   self-service: own payslips, leave, timesheets, details
  Manager (derived)                             a user whose linked employee has direct reports: approve their reports' time and leave,
                                                see their team's names and leave. No salary, tax or bank access.
bookkeeper / readonly have no payroll access unless they are also linked to an employee record (self-service only).
"""
from typing import Optional, Set

from accfino.modules.payroll.models.payroll import PayEmployee
from accfino.modules.payroll.services.errors import Forbidden

ALL = {"view", "employees_view", "employees_manage", "sensitive_view", "tfn_reveal", "config_manage", "items_manage", "timesheets_manage",
       "timesheets_approve", "leave_manage", "leave_approve", "run_create", "run_approve", "run_finalise", "run_reverse", "payments_manage",
       "journal_view", "reports_view", "audit_view", "stp_manage", "access_manage"}
MANAGER_CAPS = ALL - {"config_manage", "items_manage", "run_reverse", "tfn_reveal", "access_manage", "audit_view"}   # pay items control tax/OTE treatment: admins only
ROLE_CAPS = {
    "owner": set(ALL), "admin": {"view", "employees_view", "sensitive_view", "reports_view", "journal_view", "audit_view"},
    "payroll_admin": set(ALL) - {"access_manage"}, "payroll": MANAGER_CAPS,
    "accountant": {"view", "employees_view", "sensitive_view", "reports_view", "journal_view", "audit_view"},
}


class Access:
    def __init__(self, db, ctx):
        self.db, self.ctx = db, ctx
        self.caps: Set[str] = set(ALL) if ctx.is_admin else set(ROLE_CAPS.get(ctx.role, set()))
        self.employee: Optional[PayEmployee] = (db.query(PayEmployee).filter(PayEmployee.org_id == ctx.org.id, PayEmployee.user_id == ctx.user_id).first())
        self._reports: Optional[Set[int]] = None

    # -- capabilities -------------------------------------------------------------------------------------------------------------
    def has(self, cap: str) -> bool:
        return cap in self.caps

    def require(self, cap: str):
        if cap not in self.caps:
            raise Forbidden(f"Your role does not allow this payroll action ({cap.replace('_', ' ')})")

    @property
    def is_payroll_staff(self) -> bool:
        return "employees_view" in self.caps

    @property
    def reports(self) -> Set[int]:
        """Employee ids that report (directly) to the signed-in user's employee record."""
        if self._reports is None:
            self._reports = set()
            if self.employee is not None:
                self._reports = {i for (i,) in self.db.query(PayEmployee.id).filter(PayEmployee.org_id == self.ctx.org.id,
                                                                                    PayEmployee.manager_id == self.employee.id)}
        return self._reports

    @property
    def is_manager(self) -> bool:
        return bool(self.reports)

    @property
    def has_any_access(self) -> bool:
        return bool(self.caps) or self.employee is not None

    def scope(self, cap: str) -> Optional[Set[int]]:
        """Employee ids the caller may act on for this capability. None = everyone; otherwise a set (self and/or direct reports)."""
        if cap in self.caps:
            return None
        s: Set[int] = set()
        if self.employee is not None:
            s.add(self.employee.id)
            if cap in ("timesheets_approve", "leave_approve", "employees_view"):
                s |= self.reports
        return s

    def can_act_on(self, cap: str, employee_id: int, *, include_self: bool = True) -> bool:
        """May the caller use `cap` on this employee? With include_self=False nobody - not even a payroll administrator - may act on their OWN record
        (separation of duties for approvals)."""
        if not include_self and self.employee is not None and employee_id == self.employee.id:
            return False
        sc = self.scope(cap)
        return sc is None or employee_id in sc

    def approver_label(self) -> Optional[str]:
        """Who decides this person's own timesheets and leave (None when the login is not linked to an employee)."""
        if self.employee is None:
            return None
        from accfino.modules.payroll.services import notify
        return notify.approver_label(self.db, self.employee)

    def summary(self) -> dict:
        return {"approver": self.approver_label(), "role": self.ctx.role, "capabilities": sorted(self.caps), "employee_id": self.employee.id if self.employee else None,
                "is_manager": self.is_manager, "is_payroll_staff": self.is_payroll_staff, "self_service": self.employee is not None}
