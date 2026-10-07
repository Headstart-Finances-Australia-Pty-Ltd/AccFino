"""Employee payroll profile: personal, employment, tax, super, bank and recurring pay items. Validated, scoped, masked and audited."""
import re
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from typing import Optional

from sqlalchemy import func, or_

from accfino.modules.payroll.models.payroll import (EMPLOYMENT_TYPES, FREQUENCIES, PayCalendar, PayDepartment, PayEmployee, PayEmployeeBank,
                                                    PayEmployeeItem, PayEmployeeSuper, PayEmployeeTax, PayItem, PayLocation, PaySuperFund)
from accfino.modules.payroll.services import audit, protect
from accfino.modules.payroll.services.errors import Conflict, Forbidden, NotFound, PayrollError
from accfino.modules.payroll.services.setup import get_settings, next_number

STATES = ("ACT", "NSW", "NT", "QLD", "SA", "TAS", "VIC", "WA")
PERSONAL = ["first_name", "middle_name", "last_name", "preferred_name", "date_of_birth", "email", "phone", "address_line1", "address_line2", "suburb", "state", "postcode"]
EMPLOYMENT = ["employee_number", "start_date", "end_date", "status", "employment_type", "position", "department_id", "location_id", "manager_id", "calendar_id",
              "pay_frequency", "pay_basis", "annual_salary", "hourly_rate", "hours_per_week", "work_pattern", "pay_standard_hours", "termination_reason"]
PAY_KEYS = ["pay_basis", "annual_salary", "hourly_rate", "hours_per_week", "pay_frequency", "employment_type"]
TAX_KEYS = ["tfn_status", "residency", "claims_tft", "has_study_loan", "study_loan_type", "medicare_variation", "tax_offset_annual", "variation_pct",
            "extra_withholding", "declaration_date"]


def _dec(v, name, *, min_=None, max_=None, required=False) -> Optional[Decimal]:
    if v is None or v == "":
        if required:
            raise PayrollError(f"{name} is required")
        return None
    try:
        d = Decimal(str(v))
    except (InvalidOperation, ValueError):
        raise PayrollError(f"{name} must be a number")
    if not d.is_finite():
        raise PayrollError(f"{name} must be a number")
    if min_ is not None and d < min_:
        raise PayrollError(f"{name} must be at least {min_}")
    if max_ is not None and d > max_:
        raise PayrollError(f"{name} must be at most {max_}")
    return d


def _date(v, name, required=False) -> Optional[date]:
    if v in (None, ""):
        if required:
            raise PayrollError(f"{name} is required")
        return None
    if isinstance(v, date):
        return v
    try:
        return date.fromisoformat(str(v)[:10])
    except ValueError:
        raise PayrollError(f"{name} must be a date (YYYY-MM-DD)")


def get_employee(db, org_id: int, emp_id: int) -> PayEmployee:
    e = db.query(PayEmployee).filter(PayEmployee.org_id == org_id, PayEmployee.id == emp_id).first()
    if e is None:
        raise NotFound("Employee")
    return e


def full_name(e: PayEmployee) -> str:
    return " ".join(p for p in (e.first_name, e.middle_name, e.last_name) if p)


def display_name(e: PayEmployee) -> str:
    return f"{e.preferred_name or e.first_name} {e.last_name}"


def _can_see_pay(access, e) -> bool:
    return access.has("sensitive_view") or (access.employee is not None and access.employee.id == e.id)


def serialize(db, e: PayEmployee, access, detail: bool = False) -> dict:
    own = access.employee is not None and access.employee.id == e.id
    staff = access.is_payroll_staff
    out = {"id": e.id, "employee_number": e.employee_number, "first_name": e.first_name, "last_name": e.last_name, "preferred_name": e.preferred_name,
           "name": display_name(e), "status": e.status, "employment_type": e.employment_type, "position": e.position, "department_id": e.department_id,
           "location_id": e.location_id, "manager_id": e.manager_id, "start_date": e.start_date.isoformat(), "end_date": e.end_date.isoformat() if e.end_date else None,
           "pay_frequency": e.pay_frequency, "pay_basis": e.pay_basis, "email": e.email if (staff or own) else None, "has_login": e.user_id is not None}
    if _can_see_pay(access, e):
        out.update(annual_salary=str(e.annual_salary) if e.annual_salary is not None else None,
                   hourly_rate=str(e.hourly_rate) if e.hourly_rate is not None else None, hours_per_week=str(e.hours_per_week))
    if detail and (staff or own):
        out.update({k: (getattr(e, k).isoformat() if isinstance(getattr(e, k), date) else getattr(e, k)) for k in PERSONAL if k not in out},
                   middle_name=e.middle_name, work_pattern=e.work_pattern, calendar_id=e.calendar_id, termination_reason=e.termination_reason,
                   pay_standard_hours=e.pay_standard_hours, login_user_id=e.user_id if staff else None, is_demo=e.is_demo)
        out["date_of_birth"] = e.date_of_birth.isoformat() if e.date_of_birth else None
        if _can_see_pay(access, e):
            out["super"] = super_view(db, e)
            out["items"] = items_view(db, e)
        if access.has("employees_manage") or own:               # tax declaration and bank details: payroll staff who maintain them, and the employee. NOT accountants.
            out["tax"] = tax_view(db, e)
            out["bank"] = bank_view(db, e, access)
        out["readiness"] = readiness(db, e)
    return out


def tax_view(db, e) -> dict:
    t = db.get(PayEmployeeTax, e.id)
    if t is None:
        return {"tfn_status": "not_provided", "tfn_masked": None, "residency": "resident", "claims_tft": True, "has_study_loan": False, "medicare_variation": "none",
                "tax_offset_annual": "0.00", "extra_withholding": "0.00"}
    return {"tfn_status": t.tfn_status, "tfn_masked": protect.mask_tfn(t.tfn_last3), "residency": t.residency, "claims_tft": t.claims_tft,
            "has_study_loan": t.has_study_loan, "study_loan_type": t.study_loan_type, "medicare_variation": t.medicare_variation,
            "tax_offset_annual": str(t.tax_offset_annual or 0), "variation_pct": str(t.variation_pct) if t.variation_pct is not None else None,
            "extra_withholding": str(t.extra_withholding or 0), "declaration_date": t.declaration_date.isoformat() if t.declaration_date else None,
            "ytd_opening": t.ytd_opening}


def super_view(db, e) -> list:
    rows = (db.query(PayEmployeeSuper, PaySuperFund).join(PaySuperFund, PaySuperFund.id == PayEmployeeSuper.fund_id)
            .filter(PayEmployeeSuper.employee_id == e.id, PayEmployeeSuper.is_active.is_(True)).all())
    return [{"id": s.id, "fund_id": f.id, "fund_name": f.name, "fund_type": f.fund_type, "usi": f.usi, "member_number": s.member_number,
             "allocation_pct": str(s.allocation_pct), "is_default_fund": s.is_default_fund,
             "choice_form_date": s.choice_form_date.isoformat() if s.choice_form_date else None} for s, f in rows]


def bank_view(db, e, access=None) -> list:
    rows = db.query(PayEmployeeBank).filter(PayEmployeeBank.employee_id == e.id, PayEmployeeBank.is_active.is_(True)).order_by(PayEmployeeBank.priority).all()
    return [{"id": b.id, "account_name": b.account_name, "bsb": b.bsb, "account_masked": protect.mask_account(b.account_last4), "allocation_type": b.allocation_type,
             "allocation_value": str(b.allocation_value), "priority": b.priority, "reference": b.reference} for b in rows]


def items_view(db, e) -> list:
    rows = (db.query(PayEmployeeItem, PayItem).join(PayItem, PayItem.id == PayEmployeeItem.pay_item_id)
            .filter(PayEmployeeItem.employee_id == e.id, PayEmployeeItem.is_active.is_(True)).all())
    return [{"id": r.id, "pay_item_id": i.id, "code": i.code, "name": i.name, "kind": i.kind, "amount": str(r.amount) if r.amount is not None else None,
             "rate": str(r.rate) if r.rate is not None else None, "hours": str(r.hours) if r.hours is not None else None,
             "effective_from": r.effective_from.isoformat() if r.effective_from else None, "effective_to": r.effective_to.isoformat() if r.effective_to else None,
             "note": r.note} for r, i in rows]


def readiness(db, e: PayEmployee) -> list:
    """Set-up problems that would stop or weaken a pay run for this employee: [{code, severity, message}]."""
    out = []
    t = db.get(PayEmployeeTax, e.id)
    if t is None or t.tfn_status == "not_provided" or (t.tfn_status == "provided" and not t.tfn_enc):
        out.append({"code": "no_tfn", "severity": "warning", "message": "No TFN: tax will be withheld at the highest (no-TFN) rate"})
    elif t.tfn_status == "pending":
        out.append({"code": "tfn_pending", "severity": "warning", "message": "TFN declared as pending: confirm within 28 days"})
    if not db.query(PayEmployeeBank).filter_by(employee_id=e.id, is_active=True).first():
        out.append({"code": "no_bank", "severity": "error", "message": "No bank account: net pay cannot be paid"})
    if not db.query(PayEmployeeSuper).filter_by(employee_id=e.id, is_active=True).first():
        out.append({"code": "no_super", "severity": "error", "message": "No super fund: superannuation cannot be paid"})
    if e.pay_basis == "salary" and not (e.annual_salary and e.annual_salary > 0):
        out.append({"code": "no_salary", "severity": "error", "message": "No annual salary"})
    if e.pay_basis == "hourly" and not (e.hourly_rate and e.hourly_rate > 0):
        out.append({"code": "no_rate", "severity": "error", "message": "No hourly rate"})
    if not e.calendar_id:
        out.append({"code": "no_calendar", "severity": "warning", "message": "No pay calendar assigned"})
    return out


# ---- list ---------------------------------------------------------------------------------------------------------------------------
def list_employees(db, ctx, access, *, q: str = "", status: str = "", department_id: int = 0, employment_type: str = "", manager_id: int = 0,
                   sort: str = "name", page: int = 1, limit: int = 50) -> dict:
    sc = access.scope("employees_view")
    if sc is not None and not sc:
        raise Forbidden("You have no access to employee records")
    qs = db.query(PayEmployee).filter(PayEmployee.org_id == ctx.org.id)
    if sc is not None:
        qs = qs.filter(PayEmployee.id.in_(sc))
    if q:
        like = f"%{q.strip().lower()}%"
        qs = qs.filter(or_(func.lower(PayEmployee.first_name).like(like), func.lower(PayEmployee.last_name).like(like),
                           func.lower(PayEmployee.employee_number).like(like), func.lower(func.coalesce(PayEmployee.position, "")).like(like)))
    if status:
        qs = qs.filter(PayEmployee.status == status)
    if department_id:
        qs = qs.filter(PayEmployee.department_id == department_id)
    if employment_type:
        qs = qs.filter(PayEmployee.employment_type == employment_type)
    if manager_id:
        qs = qs.filter(PayEmployee.manager_id == manager_id)
    total = qs.count()
    order = {"number": PayEmployee.employee_number, "start": PayEmployee.start_date.desc(), "status": PayEmployee.status}.get(sort)
    qs = qs.order_by(*( [order] if order is not None else [PayEmployee.last_name, PayEmployee.first_name]))
    page, limit = max(1, int(page)), max(1, min(int(limit), 200))
    rows = qs.offset((page - 1) * limit).limit(limit).all()
    return {"items": [serialize(db, e, access) for e in rows], "total": total, "page": page, "limit": limit}


# ---- create / update ----------------------------------------------------------------------------------------------------------------
def _check_refs(db, org_id, d: dict, emp_id: Optional[int] = None):
    for key, model, label in (("department_id", PayDepartment, "Department"), ("location_id", PayLocation, "Location"), ("calendar_id", PayCalendar, "Pay calendar")):
        if d.get(key) and not db.query(model).filter_by(id=d[key], org_id=org_id).first():
            raise PayrollError(f"{label} not found in this organisation")
    mid = d.get("manager_id")
    if mid:
        if emp_id and mid == emp_id:
            raise PayrollError("An employee cannot be their own manager")
        seen, cur = {emp_id}, db.query(PayEmployee).filter_by(id=mid, org_id=org_id).first()
        if cur is None:
            raise PayrollError("Manager not found in this organisation")
        while cur is not None and cur.manager_id:                       # no reporting loops
            if cur.manager_id in seen:
                raise PayrollError("That manager would create a reporting loop")
            seen.add(cur.id)
            cur = db.get(PayEmployee, cur.manager_id)


def _validate(d: dict, existing: Optional[PayEmployee] = None) -> dict:
    g = lambda k: d[k] if k in d else (getattr(existing, k) if existing is not None else None)
    out = dict(d)
    for k in ("first_name", "last_name"):
        if k in d or existing is None:
            if not str(g(k) or "").strip():
                raise PayrollError(f"{'First' if k == 'first_name' else 'Last'} name is required")
            out[k] = str(g(k)).strip()
    if "email" in d and d["email"]:
        if not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", str(d["email"]).strip()):
            raise PayrollError("Email address is not valid")
        out["email"] = str(d["email"]).strip().lower()
    if "postcode" in d and d["postcode"] and not re.fullmatch(r"\d{4}", str(d["postcode"])):
        raise PayrollError("Postcode must be 4 digits")
    if "state" in d and d["state"] and str(d["state"]).upper() not in STATES:
        raise PayrollError(f"State must be one of {', '.join(STATES)}")
    if d.get("state"):
        out["state"] = str(d["state"]).upper()
    for k in ("date_of_birth", "start_date", "end_date"):
        if k in d or (existing is None and k == "start_date"):
            out[k] = _date(d.get(k), k.replace("_", " ").capitalize(), required=(k == "start_date"))
    dob, start, end = out.get("date_of_birth", g("date_of_birth")), out.get("start_date", g("start_date")), out.get("end_date", g("end_date"))
    if dob and dob >= date.today():
        raise PayrollError("Date of birth must be in the past")
    if dob and start and (start.year - dob.year) < 14:
        raise PayrollError("Employee must be at least 14 years old at their start date")
    if end and start and end < start:
        raise PayrollError("End date cannot be before the start date")
    et = g("employment_type") or "full_time"
    if et not in EMPLOYMENT_TYPES:
        raise PayrollError(f"Employment type must be one of {', '.join(EMPLOYMENT_TYPES)}")
    if (g("pay_frequency") or "fortnightly") not in FREQUENCIES:
        raise PayrollError(f"Pay frequency must be one of {', '.join(FREQUENCIES)}")
    basis = g("pay_basis") or "salary"
    if basis not in ("salary", "hourly"):
        raise PayrollError("Pay basis must be salary or hourly")
    for k, lo, hi in (("annual_salary", Decimal("0.01"), Decimal("10000000")), ("hourly_rate", Decimal("0.01"), Decimal("5000"))):
        if k in d:
            out[k] = _dec(d[k], k.replace("_", " ").capitalize(), min_=lo, max_=hi)
    if basis == "salary" and not (out.get("annual_salary") if "annual_salary" in out else g("annual_salary")):
        raise PayrollError("Annual salary is required for a salaried employee")
    if basis == "hourly" and not (out.get("hourly_rate") if "hourly_rate" in out else g("hourly_rate")):
        raise PayrollError("Hourly rate is required for an hourly employee")
    if "hours_per_week" in d:
        out["hours_per_week"] = _dec(d["hours_per_week"], "Ordinary hours per week", min_=Decimal("0.1"), max_=Decimal("100"), required=True)
    if et == "casual" and basis == "salary":
        raise PayrollError("Casual employees are paid by the hour: choose hourly pay")
    wp = d.get("work_pattern")
    if wp:
        days = {"mon", "tue", "wed", "thu", "fri", "sat", "sun"}
        if not isinstance(wp, dict) or set(wp) - days:
            raise PayrollError("Work pattern must list hours for mon..sun")
        for k, v in wp.items():
            _dec(v, f"Work pattern {k}", min_=Decimal(0), max_=Decimal(24))
    return out


def create_employee(db, ctx, access, body: dict) -> PayEmployee:
    access.require("employees_manage")
    d = _validate(body)
    s = get_settings(db, ctx.org)
    d.setdefault("pay_frequency", s.default_frequency)
    d.setdefault("hours_per_week", s.standard_hours_per_week)
    num = (body.get("employee_number") or "").strip() or next_number(db, ctx.org, "employee")
    if db.query(PayEmployee.id).filter_by(org_id=ctx.org.id, employee_number=num).first():
        raise Conflict(f"Employee number {num} already exists")
    _check_refs(db, ctx.org.id, d)
    cols = {k: d[k] for k in PERSONAL + EMPLOYMENT if k in d and k != "employee_number"}
    cols.setdefault("status", "active")
    if body.get("login_user_id"):                      # NB: never called user_id in the API - the platform AuthGuard treats user_id as "the caller"
        cols["user_id"] = _link_user(db, ctx, body["login_user_id"], None)
    e = PayEmployee(org_id=ctx.org.id, employee_number=num, **cols)
    db.add(e)
    db.flush()
    db.add(PayEmployeeTax(employee_id=e.id, org_id=ctx.org.id))
    db.flush()
    audit.record(db, ctx, "employee.create", "employee", e.id, f"{e.employee_number} {display_name(e)}", "Employee created",
                 after={k: getattr(e, k) for k in ("employee_number", "employment_type", "pay_basis", "start_date")})
    return e


def _link_user(db, ctx, user_id, emp_id):
    from accfino.core import models as m
    if not db.query(m.OrgMembership).filter_by(org_id=ctx.org.id, user_id=int(user_id)).first():
        raise PayrollError("That user is not a member of this organisation")
    other = db.query(PayEmployee).filter(PayEmployee.org_id == ctx.org.id, PayEmployee.user_id == int(user_id))
    if emp_id:
        other = other.filter(PayEmployee.id != emp_id)
    if other.first():
        raise Conflict("That user is already linked to another employee")
    return int(user_id)


def update_employee(db, ctx, access, emp_id: int, body: dict) -> PayEmployee:
    access.require("employees_manage")
    e = get_employee(db, ctx.org.id, emp_id)
    if e.status == "terminated" and body.get("status") not in (None, "terminated"):
        pass                                                              # re-hire is allowed explicitly
    d = _validate(body, e)
    _check_refs(db, ctx.org.id, d, e.id)
    if "employee_number" in d and d["employee_number"] != e.employee_number:
        if db.query(PayEmployee.id).filter(PayEmployee.org_id == ctx.org.id, PayEmployee.employee_number == d["employee_number"]).first():
            raise Conflict(f"Employee number {d['employee_number']} already exists")
    old = {k: getattr(e, k) for k in PERSONAL + EMPLOYMENT + ["user_id"]}
    for k in PERSONAL + EMPLOYMENT:
        if k in d:
            setattr(e, k, d[k])
    if "login_user_id" in body:
        e.user_id = _link_user(db, ctx, body["login_user_id"], e.id) if body["login_user_id"] else None
    if e.status == "terminated" and not e.end_date:
        raise PayrollError("A terminated employee needs an end date")
    new = {k: getattr(e, k) for k in PERSONAL + EMPLOYMENT + ["user_id"]}
    b, a = audit.diff(old, new, PERSONAL + EMPLOYMENT + ["user_id"])
    if b:
        pay_change = any(k in b for k in PAY_KEYS)
        action = "employee.pay_change" if pay_change else ("employee.status_change" if "status" in b else "employee.update")
        audit.record(db, ctx, action, "employee", e.id, f"{e.employee_number} {display_name(e)}",
                     "Pay rate / basis changed" if pay_change else f"Updated {', '.join(sorted(b))}", before=b, after=a)
    db.flush()
    return e


def terminate_employee(db, ctx, access, emp_id: int, end_date, reason: str = "") -> PayEmployee:
    access.require("employees_manage")
    e = get_employee(db, ctx.org.id, emp_id)
    end = _date(end_date, "End date", required=True)
    if end < e.start_date:
        raise PayrollError("End date cannot be before the start date")
    if e.status == "terminated":
        raise Conflict("Employee is already terminated")
    before = {"status": e.status, "end_date": e.end_date}
    e.status, e.end_date, e.termination_reason = "terminated", end, (reason or "")[:200]
    audit.record(db, ctx, "employee.terminate", "employee", e.id, f"{e.employee_number} {display_name(e)}", f"Terminated effective {end.isoformat()}",
                 before=before, after={"status": "terminated", "end_date": end, "reason": e.termination_reason})
    return e


# ---- tax ----------------------------------------------------------------------------------------------------------------------------
def set_tax(db, ctx, access, emp_id: int, body: dict) -> dict:
    access.require("employees_manage")
    e = get_employee(db, ctx.org.id, emp_id)
    t = db.get(PayEmployeeTax, e.id) or PayEmployeeTax(employee_id=e.id, org_id=ctx.org.id)
    db.add(t)
    before = tax_view(db, e)
    if body.get("tfn"):
        t.tfn_enc, t.tfn_last3 = protect.seal_tfn(body["tfn"])
        t.tfn_status = "provided"
    status = body.get("tfn_status")
    if status:
        if status not in ("provided", "pending", "exempt", "not_provided"):
            raise PayrollError("TFN status is not valid")
        if status == "provided" and not t.tfn_enc:
            raise PayrollError("Enter the TFN to mark it as provided")
        t.tfn_status = status
        if status == "not_provided":
            t.tfn_enc = t.tfn_last3 = None
    if "residency" in body:
        if body["residency"] not in ("resident", "foreign_resident"):
            raise PayrollError("Residency must be resident or foreign_resident")
        t.residency = body["residency"]
    for k in ("claims_tft", "has_study_loan"):
        if k in body:
            setattr(t, k, bool(body[k]))
    if "medicare_variation" in body:
        if body["medicare_variation"] not in ("none", "half", "full"):
            raise PayrollError("Medicare variation must be none, half or full")
        t.medicare_variation = body["medicare_variation"]
    if "study_loan_type" in body:
        t.study_loan_type = body["study_loan_type"] or None
    if t.has_study_loan is False:
        t.study_loan_type = None
    if "tax_offset_annual" in body:
        t.tax_offset_annual = _dec(body["tax_offset_annual"], "Tax offset", min_=Decimal(0), max_=Decimal(1000000)) or Decimal(0)
    if "extra_withholding" in body:
        t.extra_withholding = _dec(body["extra_withholding"], "Extra withholding", min_=Decimal(0), max_=Decimal(1000000)) or Decimal(0)
    if "variation_pct" in body:
        t.variation_pct = _dec(body["variation_pct"], "Withholding variation %", min_=Decimal(0), max_=Decimal(100))
    if "declaration_date" in body:
        t.declaration_date = _date(body["declaration_date"], "Declaration date")
    if "ytd_opening" in body:
        t.ytd_opening = _clean_opening(body["ytd_opening"])
    if t.residency == "foreign_resident" and t.claims_tft:
        t.claims_tft = False                                              # foreign residents cannot claim the tax-free threshold
    db.flush()
    after = tax_view(db, e)
    b, a = audit.diff(before, after, list(after))
    if b:
        audit.record(db, ctx, "employee.tax_change", "employee", e.id, f"{e.employee_number} {display_name(e)}", "Tax details changed", before=b, after=a)
    return after


def _clean_opening(v) -> Optional[dict]:
    if not v:
        return None
    out = {"fy": str(v.get("fy") or "")}
    if not re.fullmatch(r"\d{4}-\d{2}", out["fy"]):
        raise PayrollError("Opening balances need a financial year such as 2026-27")
    for k in ("gross", "taxable", "tax", "study_loan", "super_total", "super_guarantee", "qualifying_earnings", "salary_sacrifice", "net"):
        out[k] = str(_dec(v.get(k), f"Opening {k}", min_=Decimal(0)) or Decimal(0))
    return out


def reveal_tfn(db, ctx, access, emp_id: int) -> str:
    access.require("tfn_reveal")
    e = get_employee(db, ctx.org.id, emp_id)
    t = db.get(PayEmployeeTax, e.id)
    tfn = protect.reveal(t.tfn_enc) if t else None
    if not tfn:
        raise NotFound("TFN")
    audit.record(db, ctx, "employee.tfn_viewed", "employee", e.id, f"{e.employee_number} {display_name(e)}", "TFN revealed")
    return f"{tfn[:3]} {tfn[3:6]} {tfn[6:]}"


# ---- super --------------------------------------------------------------------------------------------------------------------------
def set_super(db, ctx, access, emp_id: int, memberships: list) -> list:
    access.require("employees_manage")
    e = get_employee(db, ctx.org.id, emp_id)
    if not isinstance(memberships, list):
        raise PayrollError("Super details must be a list of fund memberships")
    total = Decimal(0)
    clean = []
    for m in memberships:
        f = db.query(PaySuperFund).filter_by(id=m.get("fund_id"), org_id=ctx.org.id, is_active=True).first()
        if f is None:
            raise PayrollError("Super fund not found (or inactive)")
        pct = _dec(m.get("allocation_pct", 100), "Allocation %", min_=Decimal("0.01"), max_=Decimal(100))
        total += pct
        if not m.get("member_number") and not m.get("is_default_fund") and f.fund_type == "apra":
            raise PayrollError(f"Member number is required for {f.name}")
        clean.append((f, pct, m))
    if clean and total != 100:
        raise PayrollError(f"Fund allocations must add up to 100% (currently {total}%)")
    before = super_view(db, e)
    db.query(PayEmployeeSuper).filter_by(employee_id=e.id).delete()
    for f, pct, m in clean:
        db.add(PayEmployeeSuper(org_id=ctx.org.id, employee_id=e.id, fund_id=f.id, member_number=(m.get("member_number") or None), allocation_pct=pct,
                                is_default_fund=bool(m.get("is_default_fund")), choice_form_date=_date(m.get("choice_form_date"), "Choice form date")))
    db.flush()
    after = super_view(db, e)
    if before != after:
        audit.record(db, ctx, "employee.super_change", "employee", e.id, f"{e.employee_number} {display_name(e)}", "Super fund details changed",
                     before={"funds": before}, after={"funds": after})
    return after


# ---- bank ---------------------------------------------------------------------------------------------------------------------------
def set_bank(db, ctx, access, emp_id: int, accounts: list) -> list:
    access.require("employees_manage")
    e = get_employee(db, ctx.org.id, emp_id)
    if not isinstance(accounts, list):
        raise PayrollError("Bank details must be a list of accounts")
    existing = {b.id: b for b in db.query(PayEmployeeBank).filter_by(employee_id=e.id, is_active=True)}
    if len(accounts) > 5:
        raise PayrollError("At most 5 bank accounts per employee")
    rem = [a for a in accounts if a.get("allocation_type", "remainder") == "remainder"]
    if accounts and len(rem) != 1:
        raise PayrollError("Exactly one account must receive the remainder of net pay")
    pct = Decimal(0)
    clean = []
    for i, a in enumerate(accounts, start=1):
        name = str(a.get("account_name") or "").strip()
        if not name:
            raise PayrollError("Account name is required")
        bsb = protect.norm_bsb(a.get("bsb"))
        atype = a.get("allocation_type", "remainder")
        val = _dec(a.get("allocation_value", 0), "Allocation", min_=Decimal(0), max_=Decimal(10000000)) or Decimal(0)
        if atype not in ("fixed", "percent", "remainder"):
            raise PayrollError("Allocation type must be fixed, percent or remainder")
        if atype in ("fixed", "percent") and val <= 0:
            raise PayrollError("Fixed and percentage allocations must be greater than zero")
        if atype == "percent":
            pct += val
        keep = existing.get(a.get("id")) if a.get("id") else None
        if a.get("account_number"):
            enc, last4 = protect.seal_account(a["account_number"])
        elif keep is not None:
            enc, last4 = keep.account_enc, keep.account_last4          # unchanged account number is kept (never sent back to the browser)
        else:
            raise PayrollError(f"Account number is required for '{name}'")
        clean.append(dict(account_name=name, bsb=bsb, account_enc=enc, account_last4=last4, allocation_type=atype, allocation_value=val, priority=i,
                          reference=(a.get("reference") or "")[:18] or None))
    if pct > 100:
        raise PayrollError("Percentage allocations cannot exceed 100%")
    before = bank_view(db, e)
    for b in existing.values():
        b.is_active = False
    for c in clean:
        db.add(PayEmployeeBank(org_id=ctx.org.id, employee_id=e.id, **c))
    db.flush()
    after = bank_view(db, e)
    if [(x["bsb"], x["account_masked"], x["allocation_type"], x["allocation_value"]) for x in before] != [(x["bsb"], x["account_masked"], x["allocation_type"], x["allocation_value"]) for x in after]:
        audit.record(db, ctx, "employee.bank_change", "employee", e.id, f"{e.employee_number} {display_name(e)}", "Bank details changed",
                     before={"accounts": before}, after={"accounts": after})
    return after


# ---- recurring pay items ------------------------------------------------------------------------------------------------------------
NOT_ASSIGNABLE = {"leave", "leave_loading", "unpaid_leave", "salary_adjustment", "termination_leave", "etp", "overtime", "penalty"}


def assign_item(db, ctx, access, emp_id: int, body: dict) -> dict:
    access.require("employees_manage")
    e = get_employee(db, ctx.org.id, emp_id)
    item = db.query(PayItem).filter_by(id=body.get("pay_item_id"), org_id=ctx.org.id, is_active=True).first()
    if item is None:
        raise PayrollError("Pay item not found (or inactive)")
    if item.kind in NOT_ASSIGNABLE or item.is_system:
        raise PayrollError(f"'{item.name}' cannot be assigned as a recurring item (it is generated from hours, leave or termination details)")
    amount = _dec(body.get("amount"), "Amount", min_=Decimal(0))
    rate = _dec(body.get("rate"), "Rate / percent", min_=Decimal(0))
    if item.calc_method.startswith("percent") and rate is None and item.percent is None:
        raise PayrollError(f"{item.name}: enter a percentage")
    if item.calc_method == "fixed" and amount is None and item.default_amount is None:
        raise PayrollError(f"{item.name}: enter an amount")
    frm, to = _date(body.get("effective_from"), "Effective from"), _date(body.get("effective_to"), "Effective to")
    if frm and to and to < frm:
        raise PayrollError("Effective to cannot be before effective from")
    row = PayEmployeeItem(org_id=ctx.org.id, employee_id=e.id, pay_item_id=item.id, amount=amount, rate=rate, hours=_dec(body.get("hours"), "Hours", min_=Decimal(0)),
                          effective_from=frm, effective_to=to, note=(body.get("note") or "")[:200] or None)
    db.add(row)
    db.flush()
    audit.record(db, ctx, "employee.item_assign", "employee", e.id, f"{e.employee_number} {display_name(e)}", f"Assigned {item.code}",
                 after={"item": item.code, "amount": amount, "rate": rate})
    return next(i for i in items_view(db, e) if i["id"] == row.id)


def remove_item(db, ctx, access, emp_id: int, assign_id: int):
    access.require("employees_manage")
    e = get_employee(db, ctx.org.id, emp_id)
    r = db.query(PayEmployeeItem).filter_by(id=assign_id, employee_id=e.id, org_id=ctx.org.id, is_active=True).first()
    if r is None:
        raise NotFound("Assigned pay item")
    r.is_active = False
    item = db.get(PayItem, r.pay_item_id)
    audit.record(db, ctx, "employee.item_remove", "employee", e.id, f"{e.employee_number} {display_name(e)}", f"Removed {item.code if item else '?'}",
                 before={"item": item.code if item else None, "amount": r.amount})


def org_users(db, ctx, access) -> list:
    """Organisation members that can be linked to an employee record (for self-service), and whether each is already linked."""
    access.require("employees_manage")
    from accfino.core import models as m
    from accfino.core.identity.user import User
    linked = {e.user_id: e for e in db.query(PayEmployee).filter(PayEmployee.org_id == ctx.org.id, PayEmployee.user_id.isnot(None))}
    rows = db.query(m.OrgMembership, User).join(User, User.id == m.OrgMembership.user_id).filter(m.OrgMembership.org_id == ctx.org.id).all()
    return [{"id": u.id, "name": u.full_name or u.username, "email": u.email, "role": mem.role, "linked_employee_id": linked[u.id].id if u.id in linked else None} for mem, u in rows]
