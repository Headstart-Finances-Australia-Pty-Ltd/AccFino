"""Payroll configuration: pay calendars and periods, pay items, leave types, super funds, departments, locations and organisation settings."""
import calendar as _cal
import re
from datetime import date, timedelta
from decimal import Decimal
from typing import Optional

import accfino.modules.accounting.public as accounting
from accfino.modules.payroll.models.payroll import (FREQUENCIES, ITEM_KINDS, PayCalendar, PayDepartment, PayEmployee, PayEmployeeItem, PayItem, PayLeaveType,
                                                    PayLocation, PayRun, PayRunLine, PaySuperFund)
from accfino.modules.payroll.services import audit, protect
from accfino.modules.payroll.services.employees import _date, _dec
from accfino.modules.payroll.services.errors import Conflict, NotFound, PayrollError
from accfino.modules.payroll.services.setup import get_settings


# ---- calendars & periods --------------------------------------------------------------------------------------------------------------
def _month_bounds(d: date):
    return date(d.year, d.month, 1), date(d.year, d.month, _cal.monthrange(d.year, d.month)[1])


def period_containing(cal: PayCalendar, d: date) -> dict:
    if cal.frequency == "monthly":
        s, e = _month_bounds(d)
    else:
        n = 7 if cal.frequency == "weekly" else 14
        k = (d - cal.anchor_start).days // n
        s = cal.anchor_start + timedelta(days=k * n)
        e = s + timedelta(days=n - 1)
    return {"period_start": s, "period_end": e, "pay_date": e + timedelta(days=cal.pay_offset_days)}


def next_period(cal: PayCalendar, p: dict) -> dict:
    return period_containing(cal, p["period_end"] + timedelta(days=1))


def prev_period(cal: PayCalendar, p: dict) -> dict:
    return period_containing(cal, p["period_start"] - timedelta(days=1))


def periods_around(cal: PayCalendar, today: date, before: int = 3, after: int = 6) -> list:
    cur = period_containing(cal, today)
    back, p = [], cur
    for _ in range(before):
        p = prev_period(cal, p)
        back.append(p)
    out = list(reversed(back)) + [cur]
    p = cur
    for _ in range(after):
        p = next_period(cal, p)
        out.append(p)
    return out


def valid_period(cal: PayCalendar, start: date, end: date) -> dict:
    p = period_containing(cal, start)
    if p["period_start"] != start or p["period_end"] != end:
        raise PayrollError(f"{start.isoformat()} to {end.isoformat()} is not a pay period of calendar '{cal.name}' "
                           f"({cal.frequency}; the period containing {start.isoformat()} is {p['period_start'].isoformat()} to {p['period_end'].isoformat()})")
    return p


def ser_calendar(c: PayCalendar) -> dict:
    return {"id": c.id, "name": c.name, "frequency": c.frequency, "anchor_start": c.anchor_start.isoformat(), "pay_offset_days": c.pay_offset_days,
            "is_default": c.is_default, "is_active": c.is_active}


def save_calendar(db, ctx, access, body: dict, cal_id: Optional[int] = None) -> PayCalendar:
    access.require("config_manage")
    name = str(body.get("name") or "").strip()
    if not name:
        raise PayrollError("Calendar name is required")
    freq = body.get("frequency")
    if freq not in FREQUENCIES:
        raise PayrollError(f"Frequency must be one of {', '.join(FREQUENCIES)}")
    anchor = _date(body.get("anchor_start"), "First period start", required=True)
    off = int(_dec(body.get("pay_offset_days", 5), "Days from period end to pay date", min_=Decimal(0), max_=Decimal(31)))
    c = db.query(PayCalendar).filter_by(id=cal_id, org_id=ctx.org.id).first() if cal_id else None
    if cal_id and c is None:
        raise NotFound("Pay calendar")
    if db.query(PayCalendar.id).filter(PayCalendar.org_id == ctx.org.id, PayCalendar.name == name, PayCalendar.id != (cal_id or 0)).first():
        raise Conflict(f"A calendar named '{name}' already exists")
    if c is not None and (c.frequency != freq or c.anchor_start != anchor) and db.query(PayRun.id).filter(PayRun.calendar_id == c.id, PayRun.status != "voided").first():
        raise Conflict("This calendar has pay runs: its frequency and start date can no longer change. Create a new calendar instead.")
    new = c is None
    c = c or PayCalendar(org_id=ctx.org.id)
    c.name, c.frequency, c.anchor_start, c.pay_offset_days = name, freq, anchor, off
    c.is_active = bool(body.get("is_active", True))
    db.add(c)
    if body.get("is_default") or not db.query(PayCalendar.id).filter(PayCalendar.org_id == ctx.org.id, PayCalendar.is_default.is_(True), PayCalendar.id != (c.id or 0)).first():
        db.query(PayCalendar).filter(PayCalendar.org_id == ctx.org.id).update({PayCalendar.is_default: False})
        c.is_default = True
    db.flush()
    audit.record(db, ctx, "config.calendar_" + ("create" if new else "update"), "calendar", c.id, c.name, f"{freq} calendar saved", after=ser_calendar(c))
    return c


# ---- pay items ------------------------------------------------------------------------------------------------------------------------
def ser_item(i: PayItem) -> dict:
    f = lambda v: None if v is None else str(v)
    return {"id": i.id, "code": i.code, "name": i.name, "kind": i.kind, "description": i.description, "calc_method": i.calc_method, "rate": f(i.rate),
            "multiplier": f(i.multiplier), "default_amount": f(i.default_amount), "percent": f(i.percent), "taxable": i.taxable, "payg_treatment": i.payg_treatment,
            "super_treatment": i.super_treatment, "reportable_fringe": i.reportable_fringe, "expense_account_id": i.expense_account_id, "leave_type_id": i.leave_type_id,
            "is_system": i.is_system, "is_default": i.is_default, "is_active": i.is_active, "sort": i.sort}


CALC = ("fixed", "hours_x_rate", "percent_of_base", "percent_of_gross")
PAYG_T = ("regular", "additional", "none", "termination_leave", "etp")
EARNING_LIKE = {"earnings", "overtime", "penalty", "allowance", "bonus", "commission", "back_pay", "leave", "leave_loading", "termination_leave", "etp", "salary_adjustment", "unpaid_leave"}


def save_item(db, ctx, access, body: dict, item_id: Optional[int] = None) -> PayItem:
    access.require("items_manage")
    it = db.query(PayItem).filter_by(id=item_id, org_id=ctx.org.id).first() if item_id else None
    if item_id and it is None:
        raise NotFound("Pay item")
    code = str(body.get("code", it.code if it else "")).strip().upper()
    if not re.fullmatch(r"[A-Z0-9_]{1,20}", code):
        raise PayrollError("Code must be 1-20 letters, digits or underscores")
    name = str(body.get("name", it.name if it else "")).strip()
    if not name:
        raise PayrollError("Name is required")
    kind = body.get("kind", it.kind if it else None)
    if kind not in ITEM_KINDS:
        raise PayrollError(f"Type must be one of: {', '.join(ITEM_KINDS)}")
    if it is not None and it.is_system and (code != it.code or kind != it.kind or body.get("is_active") is False):
        raise PayrollError(f"'{it.name}' is a system pay item: its code and type cannot change and it cannot be deactivated")
    calc = body.get("calc_method", it.calc_method if it else "fixed")
    if calc not in CALC:
        raise PayrollError(f"Calculation method must be one of: {', '.join(CALC)}")
    payg = body.get("payg_treatment", it.payg_treatment if it else "regular")
    if payg not in PAYG_T:
        raise PayrollError(f"Tax treatment must be one of: {', '.join(PAYG_T)}")
    sup = body.get("super_treatment", it.super_treatment if it else "none")
    if sup not in ("ote", "none"):
        raise PayrollError("Super treatment must be ote or none")
    if kind not in EARNING_LIKE:
        if body.get("super_treatment") == "ote" or body.get("payg_treatment") in ("additional", "termination_leave", "etp"):
            raise PayrollError(f"A {kind.replace('_', ' ')} item carries no PAYG method or ordinary time earnings treatment of its own")
        payg, sup = "none", "none"                                           # deductions / reimbursements / super items carry no PAYG or OTE of their own
    taxable = bool(body.get("taxable", it.taxable if it else True)) if kind in EARNING_LIKE else False
    if payg in ("additional", "termination_leave", "etp") and not taxable:
        raise PayrollError("A non-taxable item cannot use a withholding method")
    if kind == "etp" and payg != "etp" or kind == "termination_leave" and payg != "termination_leave":
        raise PayrollError(f"A {kind.replace('_', ' ')} item must use the matching tax treatment")
    if sup == "ote" and kind in ("etp", "termination_leave", "reimbursement"):
        raise PayrollError("Termination payments and reimbursements are never ordinary time earnings")
    mult = _dec(body.get("multiplier", it.multiplier if it else 1), "Multiplier", min_=Decimal("0.01"), max_=Decimal(10))
    rate = _dec(body.get("rate", it.rate if it else None), "Rate", min_=Decimal(0), max_=Decimal(100000))
    amount = _dec(body.get("default_amount", it.default_amount if it else None), "Default amount", min_=Decimal(0), max_=Decimal(100000000))
    pct = _dec(body.get("percent", it.percent if it else None), "Percent", min_=Decimal(0), max_=Decimal(100))
    acct = body.get("expense_account_id", it.expense_account_id if it else None)
    if acct and acct not in {a["id"] for a in accounting.ledger_accounts(db, ctx.org.id)}:
        raise PayrollError("Ledger account not found in this organisation's chart of accounts")
    if db.query(PayItem.id).filter(PayItem.org_id == ctx.org.id, PayItem.code == code, PayItem.id != (item_id or 0)).first():
        raise Conflict(f"A pay item with code {code} already exists")
    new = it is None
    it = it or PayItem(org_id=ctx.org.id)
    it.code, it.name, it.kind, it.calc_method, it.payg_treatment, it.super_treatment, it.taxable = code, name, kind, calc, payg, sup, taxable
    it.description = (body.get("description", it.description) or None)
    it.multiplier, it.rate, it.default_amount, it.percent, it.expense_account_id = mult, rate, amount, pct, acct
    it.reportable_fringe = bool(body.get("reportable_fringe", it.reportable_fringe))
    it.is_active = bool(body.get("is_active", True if new else it.is_active))
    it.is_default = bool(body.get("is_default", it.is_default or False))
    it.sort = int(body.get("sort", it.sort if it.sort is not None else 100))
    lt = body.get("leave_type_id", it.leave_type_id)
    if lt and not db.query(PayLeaveType.id).filter_by(id=lt, org_id=ctx.org.id).first():
        raise PayrollError("Leave type not found")
    it.leave_type_id = lt or None
    db.add(it)
    db.flush()
    audit.record(db, ctx, "config.item_" + ("create" if new else "update"), "pay_item", it.id, f"{it.code} {it.name}", "Pay item saved", after=ser_item(it))
    return it


def delete_item(db, ctx, access, item_id: int) -> str:
    access.require("items_manage")
    it = db.query(PayItem).filter_by(id=item_id, org_id=ctx.org.id).first()
    if it is None:
        raise NotFound("Pay item")
    if it.is_system:
        raise PayrollError("System pay items cannot be deleted")
    used = (db.query(PayRunLine.id).filter(PayRunLine.pay_item_id == it.id).first() or db.query(PayEmployeeItem.id).filter_by(pay_item_id=it.id).first())
    if used:
        it.is_active = False
        audit.record(db, ctx, "config.item_deactivate", "pay_item", it.id, it.code, "Pay item deactivated (it has history)")
        return "deactivated"
    audit.record(db, ctx, "config.item_delete", "pay_item", it.id, it.code, "Pay item deleted", before=ser_item(it))
    db.delete(it)
    return "deleted"


# ---- leave types ----------------------------------------------------------------------------------------------------------------------
def ser_leave_type(l: PayLeaveType) -> dict:
    return {"id": l.id, "code": l.code, "name": l.name, "category": l.category, "is_paid": l.is_paid, "accrual_method": l.accrual_method,
            "accrual_annual_hours": str(l.accrual_annual_hours), "accrue_on_paid_leave": l.accrue_on_paid_leave, "applies_to": l.applies_to,
            "loading_pct": str(l.loading_pct), "max_balance": str(l.max_balance) if l.max_balance is not None else None,
            "min_service_years": str(l.min_service_years), "allow_negative": l.allow_negative, "is_active": l.is_active}


def save_leave_type(db, ctx, access, body: dict, lt_id: Optional[int] = None) -> PayLeaveType:
    access.require("config_manage")
    l = db.query(PayLeaveType).filter_by(id=lt_id, org_id=ctx.org.id).first() if lt_id else None
    if lt_id and l is None:
        raise NotFound("Leave type")
    code = str(body.get("code", l.code if l else "")).strip().upper()
    if not re.fullmatch(r"[A-Z0-9_]{1,20}", code):
        raise PayrollError("Code must be 1-20 letters, digits or underscores")
    name = str(body.get("name", l.name if l else "")).strip()
    if not name:
        raise PayrollError("Name is required")
    method = body.get("accrual_method", l.accrual_method if l else "none")
    if method not in ("none", "per_ordinary_hour", "fixed_per_year"):
        raise PayrollError("Accrual method must be none, per_ordinary_hour or fixed_per_year")
    hours = _dec(body.get("accrual_annual_hours", l.accrual_annual_hours if l else 0), "Annual accrual hours", min_=Decimal(0), max_=Decimal(2000))
    if method != "none" and not hours:
        raise PayrollError("Enter the annual accrual hours (for a standard 38-hour week)")
    applies = body.get("applies_to", l.applies_to if l else None)
    if applies is not None and (not isinstance(applies, list) or set(applies) - {"full_time", "part_time", "casual", "contractor"}):
        raise PayrollError("Applies-to must be a list of employment types")
    if db.query(PayLeaveType.id).filter(PayLeaveType.org_id == ctx.org.id, PayLeaveType.code == code, PayLeaveType.id != (lt_id or 0)).first():
        raise Conflict(f"A leave type with code {code} already exists")
    new = l is None
    l = l or PayLeaveType(org_id=ctx.org.id)
    l.code, l.name, l.accrual_method, l.accrual_annual_hours, l.applies_to = code, name, method, hours or Decimal(0), applies or None
    l.category = body.get("category", l.category or "other")
    l.is_paid = bool(body.get("is_paid", True if new else l.is_paid))
    l.accrue_on_paid_leave = bool(body.get("accrue_on_paid_leave", True if new else l.accrue_on_paid_leave))
    l.loading_pct = _dec(body.get("loading_pct", l.loading_pct or 0), "Loading %", min_=Decimal(0), max_=Decimal(100)) or Decimal(0)
    l.max_balance = _dec(body.get("max_balance", l.max_balance), "Maximum balance", min_=Decimal(0))
    l.min_service_years = _dec(body.get("min_service_years", l.min_service_years or 0), "Minimum service years", min_=Decimal(0), max_=Decimal(50)) or Decimal(0)
    l.allow_negative = bool(body.get("allow_negative", False if new else l.allow_negative))
    l.is_active = bool(body.get("is_active", True if new else l.is_active))
    db.add(l)
    db.flush()
    audit.record(db, ctx, "config.leave_type_" + ("create" if new else "update"), "leave_type", l.id, l.code, "Leave type saved", after=ser_leave_type(l))
    return l


# ---- super funds / departments / locations --------------------------------------------------------------------------------------------
def ser_fund(f: PaySuperFund) -> dict:
    return {"id": f.id, "name": f.name, "fund_type": f.fund_type, "usi": f.usi, "abn": f.abn, "esa": f.esa, "is_default": f.is_default, "is_active": f.is_active,
            "smsf_bsb": f.smsf_bsb, "smsf_account_name": f.smsf_account_name}


def save_fund(db, ctx, access, body: dict, fund_id: Optional[int] = None) -> PaySuperFund:
    access.require("config_manage")
    f = db.query(PaySuperFund).filter_by(id=fund_id, org_id=ctx.org.id).first() if fund_id else None
    if fund_id and f is None:
        raise NotFound("Super fund")
    name = str(body.get("name", f.name if f else "")).strip()
    if not name:
        raise PayrollError("Fund name is required")
    ftype = body.get("fund_type", f.fund_type if f else "apra")
    if ftype not in ("apra", "smsf"):
        raise PayrollError("Fund type must be apra or smsf")
    if db.query(PaySuperFund.id).filter(PaySuperFund.org_id == ctx.org.id, PaySuperFund.name == name, PaySuperFund.id != (fund_id or 0)).first():
        raise Conflict(f"A fund named '{name}' already exists")
    abn = re.sub(r"\D", "", str(body.get("abn", f.abn if f else "") or ""))
    if abn and not valid_abn(abn):
        raise PayrollError("Fund ABN is not valid")
    if ftype == "smsf" and not (body.get("smsf_bsb") or (f and f.smsf_bsb)):
        raise PayrollError("A self-managed fund needs its bank account (BSB and account) for contributions")
    new = f is None
    f = f or PaySuperFund(org_id=ctx.org.id)
    f.name, f.fund_type, f.abn = name, ftype, abn or None
    f.usi, f.esa = (body.get("usi", f.usi) or None), (body.get("esa", f.esa) or None)
    if body.get("smsf_bsb"):
        f.smsf_bsb = protect.norm_bsb(body["smsf_bsb"])
    if body.get("smsf_account"):
        f.smsf_account = protect.clean_digits(body["smsf_account"])
    f.smsf_account_name = body.get("smsf_account_name", f.smsf_account_name)
    f.is_active = bool(body.get("is_active", True if new else f.is_active))
    db.add(f)
    db.flush()
    if body.get("is_default"):
        db.query(PaySuperFund).filter(PaySuperFund.org_id == ctx.org.id).update({PaySuperFund.is_default: False})
        f.is_default = True
    audit.record(db, ctx, "config.fund_" + ("create" if new else "update"), "super_fund", f.id, f.name, "Super fund saved")
    return f


def valid_abn(abn: str) -> bool:
    d = re.sub(r"\D", "", abn or "")
    if len(d) != 11:
        return False
    nums = [int(c) for c in d]
    nums[0] -= 1
    return sum(n * w for n, w in zip(nums, (10, 1, 3, 5, 7, 9, 11, 13, 15, 17, 19))) % 89 == 0


def _simple(model, kind_label, db, ctx, access, body, rid=None, extra=()):
    access.require("config_manage")
    r = db.query(model).filter_by(id=rid, org_id=ctx.org.id).first() if rid else None
    if rid and r is None:
        raise NotFound(kind_label)
    code = str(body.get("code", r.code if r else "")).strip().upper()
    name = str(body.get("name", r.name if r else "")).strip()
    if not re.fullmatch(r"[A-Z0-9_-]{1,20}", code) or not name:
        raise PayrollError(f"{kind_label} needs a code (letters/digits, up to 20) and a name")
    if db.query(model.id).filter(model.org_id == ctx.org.id, model.code == code, model.id != (rid or 0)).first():
        raise Conflict(f"A {kind_label.lower()} with code {code} already exists")
    new = r is None
    r = r or model(org_id=ctx.org.id)
    r.code, r.name = code, name
    for k in extra:
        if k in body:
            setattr(r, k, body[k])
    r.is_active = bool(body.get("is_active", True if new else r.is_active))
    db.add(r)
    db.flush()
    audit.record(db, ctx, f"config.{kind_label.lower()}_{'create' if new else 'update'}", kind_label.lower(), r.id, f"{code} {name}", f"{kind_label} saved")
    return r


def save_department(db, ctx, access, body, rid=None):
    return _simple(PayDepartment, "Department", db, ctx, access, body, rid)


def save_location(db, ctx, access, body, rid=None):
    return _simple(PayLocation, "Location", db, ctx, access, body, rid, extra=("state",))


# ---- organisation settings ------------------------------------------------------------------------------------------------------------
MAP_KEYS = ("wages_expense", "super_expense", "reimbursement_expense", "wages_payable", "payg_payable", "super_payable", "deductions_payable", "payment_bank")   # payment_bank is optional


def ser_settings(db, ctx) -> dict:
    s = get_settings(db, ctx.org)
    pc = dict(s.payment_config or {})
    acct = pc.pop("account_enc", None)
    pc["account_masked"] = protect.mask_account(pc.get("account_last4")) if acct else None
    pc.pop("account_last4", None)
    return {"employer_name": s.employer_name or ctx.org.legal_name or ctx.org.name, "abn": s.abn or ctx.org.abn, "default_frequency": s.default_frequency,
            "standard_hours_per_week": str(s.standard_hours_per_week), "employee_prefix": s.employee_prefix, "run_prefix": s.run_prefix,
            "payslip_config": s.payslip_config or {}, "payment_config": pc, "accounting_map": s.accounting_map or {}, "stp_config": s.stp_config or {},
            "controls": s.controls or {}, "financial_year_end_month": ctx.org.fy_end_month}


def save_settings(db, ctx, access, body: dict) -> dict:
    access.require("config_manage")
    s = get_settings(db, ctx.org)
    before = ser_settings(db, ctx)
    if "employer_name" in body:
        if not str(body["employer_name"] or "").strip():
            raise PayrollError("Employer name is required")
        s.employer_name = str(body["employer_name"]).strip()
    if "abn" in body:
        if body["abn"] and not valid_abn(str(body["abn"])):
            raise PayrollError("ABN is not valid (11 digits with a correct check digit)")
        s.abn = body["abn"] or None
    if "default_frequency" in body:
        if body["default_frequency"] not in FREQUENCIES:
            raise PayrollError(f"Frequency must be one of {', '.join(FREQUENCIES)}")
        s.default_frequency = body["default_frequency"]
    if "standard_hours_per_week" in body:
        s.standard_hours_per_week = _dec(body["standard_hours_per_week"], "Standard hours per week", min_=Decimal("0.1"), max_=Decimal(100), required=True)
    for k, col in (("employee_prefix", "employee_prefix"), ("run_prefix", "run_prefix")):
        if k in body:
            v = str(body[k] or "").strip().upper()
            if not re.fullmatch(r"[A-Z0-9]{1,6}", v):
                raise PayrollError("Number prefixes are 1-6 letters or digits")
            setattr(s, col, v)
    if "payslip_config" in body:
        pcfg = body["payslip_config"] or {}
        s.payslip_config = {"show_ytd": bool(pcfg.get("show_ytd", True)), "show_leave": bool(pcfg.get("show_leave", True)), "footer": str(pcfg.get("footer", ""))[:300]}
    if "payment_config" in body:
        p = dict(s.payment_config or {})
        n = body["payment_config"] or {}
        if n.get("bsb"):
            p["bsb"] = protect.norm_bsb(n["bsb"])
        if n.get("account"):
            p["account_enc"], p["account_last4"] = protect.seal_account(n["account"])
        for k in ("account_name", "bank_abbrev", "apca_user_id", "description"):
            if k in n:
                p[k] = str(n[k] or "").strip()
        if p.get("apca_user_id") and not re.fullmatch(r"\d{6}", p["apca_user_id"]):
            raise PayrollError("APCA user ID must be 6 digits")
        if p.get("bank_abbrev") and not re.fullmatch(r"[A-Za-z]{3}", p["bank_abbrev"]):
            raise PayrollError("Bank abbreviation must be 3 letters (e.g. CBA)")
        s.payment_config = p
    if "accounting_map" in body:
        valid = {a["id"] for a in accounting.ledger_accounts(db, ctx.org.id)}
        m = dict(s.accounting_map or {})
        for k, v in (body["accounting_map"] or {}).items():
            if k not in MAP_KEYS:
                raise PayrollError(f"Unknown accounting setting '{k}'")
            if v not in valid:
                raise PayrollError(f"Account for '{k}' is not in this organisation's active chart of accounts")
            m[k] = v
        s.accounting_map = m
    if "stp_config" in body:
        s.stp_config = {k: str((body["stp_config"] or {}).get(k, ""))[:40] for k in ("bms_id", "branch_code")}
    if "controls" in body:
        s.controls = {"require_separate_approver": bool((body["controls"] or {}).get("require_separate_approver"))}
    db.flush()
    after = ser_settings(db, ctx)
    b, a = audit.diff(before, after, list(after))
    if b:
        audit.record(db, ctx, "config.settings_update", "settings", ctx.org.id, "Payroll settings", f"Changed {', '.join(sorted(b))}", before=b, after=a)
    return after
