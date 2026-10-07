"""
csv_import - bulk CSV loading for Payroll & Workforce.

Every importer goes through the SAME service layer the screens use (config, employees, leave, timesheets, pay runs), so each record is validated,
permission-checked, masked (TFN / bank numbers), audited and - for finalised pay runs - posted to the ledger exactly as if it had been keyed by hand.

Rules that apply to every entity
  * CHECK FIRST.  dry_run=True runs the whole import for real inside a transaction and then rolls it back, so the answer you get is exactly what
                  the real run would do (including records that depend on earlier records in the same file).
  * ALL-OR-NOTHING.  If any record has a problem nothing is saved: a half-loaded file is harder to fix than an empty one.
  * MASTER DATA IS UPSERTED (calendars, departments, locations, super funds, leave types, pay items, employees): a row whose code / name / number
                  already exists updates it. Re-loading a corrected file therefore works.  TRANSACTIONS ARE NEW-ONLY (timesheets, leave requests,
                  opening leave balances, recurring items, pay-run inputs): re-loading them fails cleanly ("already exists") instead of duplicating.
  * Columns are matched by name, in any order, case-insensitively; common aliases are accepted; unknown columns are ignored with a warning.
  * Dates: YYYY-MM-DD or DD/MM/YYYY.  Amounts: 1234.50, $1,234.50 or (1,234.50).  Yes/no: yes, no, true, false, 1, 0.
  * Sensitive values (TFN, bank account numbers) are sealed on the way in and NEVER echoed back: results show only masked forms.
  * No e-mail is sent by an import (in-app approval notifications are still created).

Load order (each file refers to earlier ones) is the `order` of each entity below.
"""
import csv
import io
import re
from datetime import date, datetime, timedelta
from decimal import Decimal, InvalidOperation
from typing import Callable, Dict, List, Optional

from sqlalchemy import func
from sqlalchemy.exc import SQLAlchemyError

import accfino.modules.accounting.public as accounting
from accfino.modules.payroll.models.payroll import (PayCalendar, PayDepartment, PayEmployee, PayItem, PayLeaveRequest, PayLeaveTxn, PayLeaveType, PayLocation, PayRun,
                                                    PayRunEmployee, PayRunInput, PaySuperFund)
from accfino.modules.payroll.services import audit, config as C, employees as E, leave as L, payruns as R, timesheets as T
from accfino.modules.payroll.services.errors import PayrollError
from accfino.modules.payroll.services.setup import get_settings

MAX_BYTES = 5_000_000
MAX_ROWS = 5000
MAX_ITEMS_RETURNED = 1000
Z = Decimal("0.00")


# ------------------------------------------------------------------------------------------------------------- parsing --
def _decode(raw):
    if isinstance(raw, str):
        return raw.lstrip("\ufeff")
    try:
        return raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        return raw.decode("cp1252", errors="replace")          # Excel on Windows "CSV (Comma delimited)"


def _norm_header(h):
    return re.sub(r"[^a-z0-9]+", "_", (h or "").strip().lower()).strip("_")


def _grid(text):
    first = next((ln for ln in text.splitlines() if ln.strip()), "")
    delim = max((",", ";", "\t"), key=lambda d: first.count(d))          # Excel in some regions writes ; instead of ,
    return [r for r in csv.reader(io.StringIO(text), delimiter=delim) if any((c or "").strip() for c in r)]


_DATE_FORMATS = ("%Y-%m-%d", "%d/%m/%Y", "%d/%m/%y", "%d-%m-%Y", "%d %b %Y", "%d-%b-%Y", "%d %B %Y", "%Y/%m/%d")


def _date(s, what="date") -> Optional[date]:
    s = (s or "").strip()
    if not s:
        return None
    for f in _DATE_FORMATS:
        try:
            return datetime.strptime(s, f).date()
        except ValueError:
            pass
    raise PayrollError(f"'{s}' is not a valid {what} (use DD/MM/YYYY or YYYY-MM-DD)")


def _dec(s, what="amount", default=None) -> Optional[Decimal]:
    s = (s or "").strip() if isinstance(s, str) else s
    if s in (None, ""):
        return default
    if isinstance(s, Decimal):
        return s
    t = str(s).replace("$", "").replace(",", "").replace(" ", "")
    neg = t.startswith("(") and t.endswith(")")
    t = t.strip("()")
    try:
        v = Decimal(t)
    except InvalidOperation:
        raise PayrollError(f"'{s}' is not a valid {what}")
    if not v.is_finite():
        raise PayrollError(f"'{s}' is not a valid {what}")
    return -v if neg else v


def _bool(s, default=None, what="value"):
    t = (s or "").strip().lower()
    if not t:
        return default
    if t in ("y", "yes", "true", "1", "active"):
        return True
    if t in ("n", "no", "false", "0", "inactive"):
        return False
    raise PayrollError(f"'{s}' is not yes/no for {what}")


def _choice(s, allowed, what):
    t = (s or "").strip().lower().replace(" ", "_").replace("-", "_")
    if t not in allowed:
        raise PayrollError(f"{what} '{s}' must be one of: {', '.join(allowed)}")
    return t


def _sort_date(s):
    try:
        return _date(s) or date.max
    except PayrollError:
        return date.max


def _monday(d: date) -> date:
    return d - timedelta(days=d.weekday())


def _put(body: dict, f: dict, *names):
    """Copy the non-blank text fields `names` from the record into the service body (blank cells never overwrite)."""
    for n in names:
        if f.get(n, "") != "":
            body[n] = f[n]


# ---------------------------------------------------------------------------------------------------------------- specs --
class Col:
    def __init__(self, name, help, required=False, example="", aliases=()):
        self.name, self.help, self.required, self.example, self.aliases = name, help, required, example, tuple(aliases)


class Spec:
    def __init__(self, key, title, order, group, cap, description, columns, handler, *, group_fn: Optional[Callable] = None, header_cols=(), notes=(),
                 sort_key: Optional[Callable] = None, pre_sort: Optional[Callable] = None, max_records: Optional[int] = None, sample=(), upsert=False):
        self.key, self.title, self.order, self.group, self.cap, self.description = key, title, order, group, cap, description
        self.columns, self.handler, self.group_fn, self.header_cols = columns, handler, group_fn, tuple(header_cols)
        self.notes, self.sort_key, self.pre_sort, self.max_records, self.sample, self.upsert = list(notes), sort_key, pre_sort, max_records, list(sample), upsert

    def alias_map(self):
        out = {}
        for c in self.columns:
            for a in (c.name,) + c.aliases:
                n = _norm_header(a)
                out.setdefault(n, c.name)
                out.setdefault(n.replace("_", ""), c.name)            # "FirstName" == first_name
        return out

    def info(self):
        return dict(entity=self.key, title=self.title, order=self.order, group=self.group, capability=self.cap, description=self.description, notes=self.notes,
                    mode="upsert" if self.upsert else "new_only", columns=[dict(name=c.name, required=c.required, help=c.help, example=c.example) for c in self.columns])


class Rec:
    """One record to create: the rows that make it up (lines of one timesheet, bank accounts of one employee, ...)."""

    def __init__(self, key, row):
        self.key, self.row, self.rows, self.fields, self.conflicts = key, row, [], {}, []

    def rows_with(self, *cols):
        for n, r in self.rows:
            if any(r.get(c) for c in cols):
                yield n, r


def _records(spec: Spec, grid, result) -> List[Rec]:
    head = [_norm_header(h) for h in grid[0]]
    amap = spec.alias_map()
    idx, unknown = {}, []
    for i, h in enumerate(head):
        canon = amap.get(h) or amap.get(h.replace("_", ""))
        if canon is None:
            if h:
                unknown.append(grid[0][i].strip())
        elif canon in idx:
            result["warnings"].append(f"Column '{grid[0][i].strip()}' repeats '{canon}' and was ignored")
        else:
            idx[canon] = i
    missing = [c.name for c in spec.columns if c.required and c.name not in idx]
    if missing:
        raise PayrollError(f"The file is missing required column(s): {', '.join(missing)}. Columns found: {', '.join(h.strip() for h in grid[0] if h.strip())}")
    if unknown:
        result["warnings"].append("Ignored column(s) not used by this import: " + ", ".join(unknown))
    body = grid[1:]
    if len(body) > MAX_ROWS:
        raise PayrollError(f"Too many rows ({len(body)}); the limit is {MAX_ROWS} per file. Split the file and import it in parts")
    rows = [(n, {c: (r[i].strip() if i < len(r) and r[i] is not None else "") for c, i in idx.items()}) for n, r in enumerate(body, start=2)]
    recs, by_key = [], {}
    for n, r in rows:
        k = spec.group_fn(r) if spec.group_fn else None
        if k is None:
            cur = Rec("", n)
            recs.append(cur)
        else:
            cur = by_key.get(k)
            if cur is None:
                cur = by_key[k] = Rec(str(k), n)
                recs.append(cur)
        cur.rows.append((n, r))
    for rec in recs:                                   # header fields: first non-blank value; disagreements are reported, not guessed
        for c in [col.name for col in spec.columns]:
            vals = [(n, r.get(c, "")) for n, r in rec.rows if r.get(c, "")]
            if vals:
                rec.fields[c] = vals[0][1]
                if c in spec.header_cols:
                    bad = next((n for n, v in vals if v != vals[0][1]), None)
                    if bad is not None:
                        rec.conflicts.append(f"rows {vals[0][0]} and {bad} give different values for '{c}'")
    if spec.max_records and len(recs) > spec.max_records:
        raise PayrollError(f"This file may contain only {spec.max_records} data row(s); it has {len(recs)}")
    return recs


# ---------------------------------------------------------------------------------------------------------------- lookups --
def _ci(col, value):
    return func.lower(col) == (value or "").strip().lower()


def _employee(db, org, number, *, must=True) -> Optional[PayEmployee]:
    number = (number or "").strip()
    if not number:
        raise PayrollError("employee_number is required")
    e = db.query(PayEmployee).filter(PayEmployee.org_id == org.id, _ci(PayEmployee.employee_number, number)).first()
    if e is None and must:
        raise PayrollError(f"Employee '{number}' does not exist. Import your employees first")
    return e


def _by_code(db, org, model, code, what, *, must=True):
    code = (code or "").strip()
    if not code:
        return None
    r = db.query(model).filter(model.org_id == org.id, _ci(model.code, code)).first()
    if r is None and must:
        raise PayrollError(f"{what} '{code}' does not exist. Import it first (or fix the code)")
    return r


def _calendar(db, org, name, *, must=True) -> Optional[PayCalendar]:
    name = (name or "").strip()
    if not name:
        return None
    c = db.query(PayCalendar).filter(PayCalendar.org_id == org.id, _ci(PayCalendar.name, name)).first()
    if c is None and must:
        raise PayrollError(f"Pay calendar '{name}' does not exist. Import your pay calendars first")
    return c


def _fund(db, org, name) -> PaySuperFund:
    f = db.query(PaySuperFund).filter(PaySuperFund.org_id == org.id, _ci(PaySuperFund.name, name)).first()
    if f is None:
        raise PayrollError(f"Super fund '{name}' does not exist. Import your super funds first")
    return f


def _item(db, org, code) -> PayItem:
    return _by_code(db, org, PayItem, code, "Pay item")


def _leave_type(db, org, code) -> PayLeaveType:
    return _by_code(db, org, PayLeaveType, code, "Leave type")


def _info(label, detail="", amount=None, action="create", warnings=()):
    return dict(label=label, detail=detail, amount=amount, action=action, warnings=list(warnings))


# ------------------------------------------------------------------------------------------------------- 01 settings --
def _h_settings(db, org, ctx, a, rec):
    f = rec.fields
    body = {}
    _put(body, f, "employer_name", "abn", "default_frequency", "standard_hours_per_week", "employee_prefix", "run_prefix")
    if "default_frequency" in body:
        body["default_frequency"] = _choice(body["default_frequency"], ("weekly", "fortnightly", "monthly"), "default_frequency")
    if any(f.get(k, "") != "" for k in ("show_ytd", "show_leave", "payslip_footer")):
        cur = get_settings(db, org).payslip_config or {}
        body["payslip_config"] = {"show_ytd": _bool(f.get("show_ytd"), cur.get("show_ytd", True), "show_ytd"), "show_leave": _bool(f.get("show_leave"), cur.get("show_leave", True), "show_leave"),
                                  "footer": f.get("payslip_footer", cur.get("footer", ""))}
    if f.get("stp_bms_id", "") != "":
        body["stp_config"] = {"bms_id": f["stp_bms_id"], "branch_code": (get_settings(db, org).stp_config or {}).get("branch_code", "")}
    if f.get("require_separate_approver", "") != "":
        body["controls"] = {"require_separate_approver": _bool(f["require_separate_approver"], False, "require_separate_approver")}
    pay = {}
    for src, dst in (("payment_bsb", "bsb"), ("payment_account", "account"), ("payment_account_name", "account_name"), ("payment_apca_user_id", "apca_user_id"),
                     ("payment_bank_abbrev", "bank_abbrev"), ("payment_description", "description")):
        if f.get(src, "") != "":
            pay[dst] = f[src]
    if pay:
        body["payment_config"] = pay
    if f.get("payment_bank_account", ""):
        code = f["payment_bank_account"].strip()
        acct = next((x for x in accounting.ledger_accounts(db, org.id) if x["code"] == code), None)
        if acct is None:
            raise PayrollError(f"Ledger account '{code}' (the bank account wages are paid from) does not exist. Add it first in Books & Accounting > Banking, or leave payment_bank_account blank")
        body["accounting_map"] = {"payment_bank": acct["id"]}
    if not body:
        raise PayrollError("Nothing to import: every column is blank")
    out = C.save_settings(db, ctx, a, body)
    warn = []
    if not (out.get("payment_config") or {}).get("account_masked"):
        warn.append("No company bank account yet: the bank file (ABA) cannot be produced until Settings > Payments is complete")
    return _info(out["employer_name"] or "Payroll settings", f"ABN {out.get('abn') or '-'} · {out['default_frequency']} · prefixes {out['employee_prefix']}/{out['run_prefix']}"
                 + (f" · bank account {out['payment_config']['account_masked']}" if (out.get("payment_config") or {}).get("account_masked") else ""), action="update", warnings=warn)


# ----------------------------------------------------------------------------------------------- 02-06 simple config --
def _h_calendar(db, org, ctx, a, rec):
    f = rec.fields
    name = f.get("name", "")
    if not name:
        raise PayrollError("name is required")
    cur = _calendar(db, org, name, must=False)
    body = {"name": name, "frequency": _choice(f.get("frequency", ""), ("weekly", "fortnightly", "monthly"), "frequency"), "anchor_start": _date(f.get("anchor_start"), "anchor_start")}
    if body["anchor_start"] is None:
        raise PayrollError("anchor_start is required (the first day of any pay period, e.g. a Monday)")
    if f.get("pay_offset_days", "") != "":
        body["pay_offset_days"] = int(_dec(f["pay_offset_days"], "pay_offset_days"))
    for k in ("is_default", "is_active"):
        v = _bool(f.get(k), None, k)
        if v is not None:
            body[k] = v
    c = C.save_calendar(db, ctx, a, body, cur.id if cur else None)
    return _info(c.name, f"{c.frequency} · starts {c.anchor_start.isoformat()} · pay {c.pay_offset_days} day(s) after period end" + (" · default" if c.is_default else ""),
                 action="update" if cur else "create")


def _h_simple(model, saver, what, extra=()):
    def h(db, org, ctx, a, rec):
        f = rec.fields
        code = f.get("code", "")
        if not code or not f.get("name", ""):
            raise PayrollError(f"{what} needs a code and a name")
        cur = _by_code(db, org, model, code, what, must=False)
        body = {"code": code, "name": f["name"]}
        for k in extra:
            if f.get(k, "") != "":
                body[k] = f[k]
        act = _bool(f.get("active"), None, "active")
        if act is not None:
            body["is_active"] = act
        r = saver(db, ctx, a, body, cur.id if cur else None)
        return _info(f"{r.code} {r.name}", (f"state {r.state}" if getattr(r, "state", None) else ""), action="update" if cur else "create")
    return h


def _h_fund(db, org, ctx, a, rec):
    f = rec.fields
    name = f.get("name", "")
    if not name:
        raise PayrollError("name is required")
    cur = db.query(PaySuperFund).filter(PaySuperFund.org_id == org.id, _ci(PaySuperFund.name, name)).first()
    body = {"name": name}
    if f.get("fund_type", "") != "":
        body["fund_type"] = _choice(f["fund_type"], ("apra", "smsf"), "fund_type")
    _put(body, f, "usi", "abn", "esa", "smsf_bsb", "smsf_account", "smsf_account_name")
    for src, dst in (("default", "is_default"), ("active", "is_active")):
        v = _bool(f.get(src), None, src)
        if v is not None:
            body[dst] = v
    fund = C.save_fund(db, ctx, a, body, cur.id if cur else None)
    return _info(fund.name, f"{fund.fund_type.upper()}" + (f" · USI {fund.usi}" if fund.usi else "") + (" · employer default" if fund.is_default else ""), action="update" if cur else "create")


def _h_leave_type(db, org, ctx, a, rec):
    f = rec.fields
    code = f.get("code", "")
    if not code or not f.get("name", ""):
        raise PayrollError("A leave type needs a code and a name")
    cur = _by_code(db, org, PayLeaveType, code, "Leave type", must=False)
    body = {"code": code, "name": f["name"]}
    _put(body, f, "category", "accrual_method", "accrual_annual_hours", "loading_pct", "max_balance", "min_service_years")
    if "accrual_method" in body:
        body["accrual_method"] = _choice(body["accrual_method"], ("none", "per_ordinary_hour", "fixed_per_year"), "accrual_method")
    if f.get("applies_to", "") != "":
        body["applies_to"] = [t.strip().lower().replace(" ", "_").replace("-", "_") for t in re.split(r"[|;,]", f["applies_to"]) if t.strip()]
    for src, dst in (("paid", "is_paid"), ("accrue_on_paid_leave", "accrue_on_paid_leave"), ("allow_negative", "allow_negative"), ("active", "is_active")):
        v = _bool(f.get(src), None, src)
        if v is not None:
            body[dst] = v
    lt = C.save_leave_type(db, ctx, a, body, cur.id if cur else None)
    return _info(f"{lt.code} {lt.name}", f"{lt.accrual_method.replace('_', ' ')}" + (f" · {lt.accrual_annual_hours} h/yr" if lt.accrual_annual_hours else "") + (f" · loading {lt.loading_pct}%" if lt.loading_pct else ""),
                 action="update" if cur else "create")


# ------------------------------------------------------------------------------------------------------ 07 pay items --
def _h_pay_item(db, org, ctx, a, rec):
    f = rec.fields
    code = f.get("code", "")
    if not code:
        raise PayrollError("code is required")
    cur = _by_code(db, org, PayItem, code, "Pay item", must=False)
    if cur is None and (not f.get("name") or not f.get("kind")):
        raise PayrollError("A new pay item needs a name and a kind")
    body = {"code": code}
    _put(body, f, "name", "kind", "description", "calc_method", "multiplier", "rate", "default_amount", "percent", "payg_treatment", "super_treatment")
    for k in ("kind", "calc_method", "payg_treatment", "super_treatment"):
        if k in body:
            body[k] = body[k].strip().lower().replace(" ", "_").replace("-", "_")
    for src, dst in (("taxable", "taxable"), ("reportable_fringe", "reportable_fringe"), ("active", "is_active")):
        v = _bool(f.get(src), None, src)
        if v is not None:
            body[dst] = v
    if f.get("leave_type", "") != "":
        body["leave_type_id"] = _leave_type(db, org, f["leave_type"]).id
    if f.get("expense_account", "") != "":
        acct = next((x for x in accounting.ledger_accounts(db, org.id) if x["code"] == f["expense_account"].strip()), None)
        if acct is None:
            raise PayrollError(f"Ledger account '{f['expense_account']}' is not in this organisation's chart of accounts")
        body["expense_account_id"] = acct["id"]
    it = C.save_item(db, ctx, a, body, cur.id if cur else None)
    return _info(f"{it.code} {it.name}", f"{it.kind.replace('_', ' ')} · {it.calc_method.replace('_', ' ')}" + (" · system item" if it.is_system else ""), action="update" if cur else "create")


# ------------------------------------------------------------------------------------------------------- 08 employees --
def _work_pattern(s):
    out = {}
    for part in re.split(r"[|;]", s):
        if not part.strip():
            continue
        if "=" not in part:
            raise PayrollError(f"work_pattern '{s}' must look like mon=7.6|tue=7.6|wed=0")
        k, v = part.split("=", 1)
        out[k.strip().lower()[:3]] = str(_dec(v, f"work_pattern {k.strip()}"))
    return {d: out.get(d, "0") for d in ("mon", "tue", "wed", "thu", "fri", "sat", "sun")} if out else out        # days not listed are days off


def _login_user(db, org, email):
    from accfino.core import models as m
    from accfino.core.identity.user import User
    row = (db.query(User.id).join(m.OrgMembership, m.OrgMembership.user_id == User.id)
           .filter(m.OrgMembership.org_id == org.id, _ci(User.email, email)).first())
    if row is None:
        raise PayrollError(f"No login with the email '{email}' is a member of this organisation (invite the user first, then import again)")
    return row[0]


def _h_employee(db, org, ctx, a, rec):
    f = rec.fields
    number = f.get("employee_number", "")
    cur = _employee(db, org, number, must=False)
    body = {}
    _put(body, f, "first_name", "middle_name", "last_name", "preferred_name", "email", "phone", "address_line1", "address_line2", "suburb", "state", "postcode",
         "position", "termination_reason")
    for k in ("date_of_birth", "start_date", "end_date"):
        if f.get(k, ""):
            body[k] = _date(f[k], k)
    if f.get("employment_type", ""):
        body["employment_type"] = _choice(f["employment_type"], ("full_time", "part_time", "casual", "contractor"), "employment_type")
    for k in ("annual_salary", "hourly_rate", "hours_per_week"):
        if f.get(k, ""):
            body[k] = _dec(f[k], k)
    if f.get("pay_basis", ""):
        body["pay_basis"] = _choice(f["pay_basis"], ("salary", "hourly"), "pay_basis")
    elif cur is None:
        casual = body.get("employment_type") == "casual"
        body["pay_basis"] = "hourly" if (casual or (body.get("hourly_rate") and not body.get("annual_salary"))) else "salary"
    v = _bool(f.get("pay_standard_hours"), None, "pay_standard_hours")
    if v is not None:
        body["pay_standard_hours"] = v
    if f.get("work_pattern", ""):
        body["work_pattern"] = _work_pattern(f["work_pattern"])
    if f.get("department", ""):
        body["department_id"] = _by_code(db, org, PayDepartment, f["department"], "Department").id
    if f.get("location", ""):
        body["location_id"] = _by_code(db, org, PayLocation, f["location"], "Location").id
    if f.get("calendar", ""):
        cal = _calendar(db, org, f["calendar"])
        body["calendar_id"] = cal.id
        if not f.get("pay_frequency"):
            body["pay_frequency"] = cal.frequency
    if f.get("pay_frequency", ""):
        body["pay_frequency"] = _choice(f["pay_frequency"], ("weekly", "fortnightly", "monthly"), "pay_frequency")
    if f.get("manager", ""):
        body["manager_id"] = _employee(db, org, f["manager"]).id
    if f.get("login_email", ""):
        body["login_user_id"] = _login_user(db, org, f["login_email"])
    status = _choice(f["status"], ("active", "inactive", "terminated"), "status") if f.get("status") else None
    warn = []
    if status == "terminated":
        if not body.get("end_date") and not (cur and cur.end_date):
            raise PayrollError("A terminated employee needs an end_date")
    elif status:
        body["status"] = status
    term_end, term_reason = body.get("end_date"), body.get("termination_reason", "")
    if status == "terminated":
        body.pop("end_date", None)
        body.pop("termination_reason", None)
    if cur is None:
        for k, nice in (("first_name", "first_name"), ("last_name", "last_name"), ("start_date", "start_date")):
            if k not in body:
                raise PayrollError(f"{nice} is required for a new employee")
        body["employee_number"] = number
        e = E.create_employee(db, ctx, a, body)
        _advance_employee_counter(db, org, e.employee_number)
        action = "create"
    else:
        e = E.update_employee(db, ctx, a, cur.id, body)
        action = "update"
    if status == "terminated" and e.status != "terminated":
        E.terminate_employee(db, ctx, a, e.id, term_end or e.end_date, term_reason)
    db.flush()
    for r in E.readiness(db, e):
        if r["severity"] == "error" and r["code"] in ("no_salary", "no_rate"):
            warn.append(r["message"])
    pay = f"${e.annual_salary:,.2f} pa" if e.pay_basis == "salary" and e.annual_salary else (f"${e.hourly_rate:,.2f}/h" if e.hourly_rate else "no rate")
    return _info(f"{e.employee_number} {E.full_name(e)}", f"{e.employment_type.replace('_', ' ')} · {pay} · {e.pay_frequency}" + (f" · {e.status}" if e.status != "active" else ""),
                 action=action, warnings=warn)


def _advance_employee_counter(db, org, number):
    """After loading explicit numbers (B0001..B0020) the next employee created by hand must not collide with them."""
    s = get_settings(db, org)
    m = re.fullmatch(re.escape(s.employee_prefix) + r"(\d+)", number or "", re.I)
    if m and int(m.group(1)) >= s.next_employee_no:
        s.next_employee_no = int(m.group(1)) + 1


def _employee_depth():
    """pre_sort for employees: managers listed in the same file are loaded before the people who report to them."""
    def order(recs):
        mgr = {}
        for rc in recs:
            mgr[(rc.fields.get("employee_number") or "").lower()] = (rc.fields.get("manager") or "").lower()

        def depth(num, seen=()):
            m = mgr.get(num, "")
            return 0 if (not m or m not in mgr or m in seen or num in seen) else 1 + depth(m, seen + (num,))
        recs.sort(key=lambda rc: depth((rc.fields.get("employee_number") or "").lower()))
        return recs
    return order


# ----------------------------------------------------------------------------- 09-13 employee tax / super / bank / items --
_YTD = ("gross", "taxable", "tax", "study_loan", "super_total", "super_guarantee", "qualifying_earnings", "salary_sacrifice", "net")


def _h_tax(db, org, ctx, a, rec):
    f = rec.fields
    e = _employee(db, org, f.get("employee_number"))
    body = {}
    if f.get("tfn", ""):
        body["tfn"] = f["tfn"]
    if f.get("tfn_status", ""):
        body["tfn_status"] = _choice(f["tfn_status"], ("provided", "pending", "exempt", "not_provided"), "tfn_status")
    if f.get("residency", ""):
        body["residency"] = _choice(f["residency"], ("resident", "foreign_resident"), "residency")
    for k in ("claims_tft", "has_study_loan"):
        v = _bool(f.get(k), None, k)
        if v is not None:
            body[k] = v
    if f.get("study_loan_type", ""):
        body["study_loan_type"] = f["study_loan_type"]
    if f.get("medicare_variation", ""):
        body["medicare_variation"] = _choice(f["medicare_variation"], ("none", "half", "full"), "medicare_variation")
    for k in ("tax_offset_annual", "extra_withholding", "variation_pct"):
        if f.get(k, "") != "":
            body[k] = _dec(f[k], k)
    if f.get("declaration_date", ""):
        body["declaration_date"] = _date(f["declaration_date"], "declaration_date")
    ytd = {k: f[f"ytd_{k}"] for k in _YTD if f.get(f"ytd_{k}", "") != ""}
    if ytd or f.get("ytd_fy", ""):
        if not f.get("ytd_fy"):
            raise PayrollError("Opening year-to-date figures need ytd_fy (the financial year, e.g. 2026-27)")
        body["ytd_opening"] = {"fy": f["ytd_fy"], **{k: _dec(v, f"ytd_{k}") for k, v in ytd.items()}}
    if not body:
        raise PayrollError("Nothing to import: every tax column is blank")
    t = E.set_tax(db, ctx, a, e.id, body)
    warn = []
    if t["tfn_status"] != "provided":
        warn.append(f"{E.display_name(e)} has no TFN on file: tax is withheld at the no-TFN rate")
    return _info(f"{e.employee_number} {E.full_name(e)}", f"TFN {t['tfn_masked'] or t['tfn_status'].replace('_', ' ')} · {t['residency'].replace('_', ' ')}"
                 + ("" if t["claims_tft"] else " · no tax-free threshold") + (f" · {t.get('study_loan_type') or 'study loan'}" if t["has_study_loan"] else "")
                 + (f" · opening YTD {t['ytd_opening']['fy']}" if t.get("ytd_opening") else ""), action="update", warnings=warn)


def _h_super(db, org, ctx, a, rec):
    e = _employee(db, org, rec.fields.get("employee_number"))
    memberships = []
    for n, r in rec.rows:
        fund = _fund(db, org, r.get("fund"))
        memberships.append(dict(fund_id=fund.id, member_number=r.get("member_number") or None, allocation_pct=_dec(r.get("allocation_pct"), "allocation_pct", Decimal(100)),
                                is_default_fund=bool(_bool(r.get("is_default_fund"), False, "is_default_fund")), choice_form_date=_date(r.get("choice_form_date"), "choice_form_date")))
    out = E.set_super(db, ctx, a, e.id, memberships)
    return _info(f"{e.employee_number} {E.full_name(e)}", " + ".join(f"{s['fund_name']} {s['allocation_pct']}%" for s in out), action="update")


def _h_bank(db, org, ctx, a, rec):
    e = _employee(db, org, rec.fields.get("employee_number"))
    accounts = []
    for n, r in rec.rows:
        accounts.append(dict(account_name=r.get("account_name") or None, bsb=r.get("bsb"), account_number=r.get("account_number"),
                             allocation_type=_choice(r.get("allocation_type") or "remainder", ("fixed", "percent", "remainder"), "allocation_type"),
                             allocation_value=_dec(r.get("allocation_value"), "allocation_value", Decimal(0)), reference=r.get("reference") or None))
    out = E.set_bank(db, ctx, a, e.id, accounts)
    return _info(f"{e.employee_number} {E.full_name(e)}", " + ".join(f"{b['bsb']} {b['account_masked']}" + ("" if b["allocation_type"] == "remainder" else f" ({b['allocation_type']} {b['allocation_value']})") for b in out), action="update")


def _h_emp_item(db, org, ctx, a, rec):
    f = rec.fields
    e = _employee(db, org, f.get("employee_number"))
    it = _item(db, org, f.get("pay_item"))
    body = dict(pay_item_id=it.id, amount=_dec(f.get("amount"), "amount"), rate=_dec(f.get("rate"), "rate"), hours=_dec(f.get("hours"), "hours"),
                effective_from=_date(f.get("effective_from"), "effective_from"), effective_to=_date(f.get("effective_to"), "effective_to"), note=f.get("note") or None)
    for x in E.items_view(db, e):
        if x["pay_item_id"] == it.id and x["effective_from"] == (body["effective_from"].isoformat() if body["effective_from"] else None) and \
                (Decimal(x["amount"]) if x["amount"] is not None else None) == body["amount"] and (Decimal(x["rate"]) if x["rate"] is not None else None) == body["rate"]:
            raise PayrollError(f"{it.code} is already assigned to {E.display_name(e)} with these details (recurring items are loaded once)")
    out = E.assign_item(db, ctx, a, e.id, body)
    shown = out["amount"] if out["amount"] is not None else (out["rate"] or (str(it.default_amount) if it.default_amount is not None else "default"))
    return _info(f"{e.employee_number} {E.full_name(e)}", f"{it.code} {it.name}: {shown}", amount=out["amount"])


def _h_leave_balance(db, org, ctx, a, rec):
    f = rec.fields
    e = _employee(db, org, f.get("employee_number"))
    lt = _leave_type(db, org, f.get("leave_type"))
    kind = _choice(f.get("type") or "opening", ("opening", "adjustment"), "type")
    hours = _dec(f.get("hours"), "hours")
    if hours is None:
        raise PayrollError("hours is required")
    if kind == "opening" and db.query(PayLeaveTxn.id).filter_by(org_id=org.id, employee_id=e.id, leave_type_id=lt.id, txn_type="opening").first():
        raise PayrollError(f"{E.display_name(e)} already has an opening {lt.name} balance (use type=adjustment to change a balance)")
    L.adjust(db, ctx, a, e.id, lt.id, hours, f.get("note") or ("Opening balance (CSV import)" if kind == "opening" else "Adjustment (CSV import)"), kind, _date(f.get("as_at"), "as_at"))
    bal = L.balances(db, org.id, e.id).get(lt.id, Z)
    return _info(f"{e.employee_number} {E.full_name(e)}", f"{lt.name}: {hours:+} h ({kind}) -> balance {bal.quantize(Decimal('0.01'))} h")


# --------------------------------------------------------------------------------------------- 14-15 time and leave --
def _ts_key(r):
    d = None
    try:
        d = _date(r.get("work_date"))
    except PayrollError:
        pass
    emp = (r.get("employee_number") or "").lower()
    return (emp, _monday(d)) if emp and d else None


def _h_timesheet(db, org, ctx, a, rec):
    f = rec.fields
    e = _employee(db, org, f.get("employee_number"))
    lines, week = [], None
    for n, r in rec.rows:
        if not r.get("work_date"):
            raise PayrollError(f"row {n}: work_date is required")
        d = _date(r["work_date"], "work_date")
        week = _monday(d)
        it = _item(db, org, r.get("pay_item"))
        ln = dict(work_date=d, pay_item_id=it.id, hours=_dec(r.get("hours"), f"row {n}: hours"), break_minutes=r.get("break_minutes") or 0,
                  start_time=r.get("start_time") or None, end_time=r.get("end_time") or None, notes=r.get("line_notes") or None)
        if r.get("leave_type"):
            ln["leave_type_id"] = _leave_type(db, org, r["leave_type"]).id
        lines.append(ln)
    status = _choice(f.get("status") or "draft", ("draft", "submitted", "approved", "rejected"), "status")
    ts = T.save(db, ctx, a, dict(employee_id=e.id, week_start=week, lines=lines, notes=f.get("notes") or None))
    if status in ("submitted", "approved", "rejected"):
        T.submit(db, ctx, a, ts.id)
    if status == "approved":
        T.decide(db, ctx, a, ts.id, True)
    if status == "rejected":
        T.decide(db, ctx, a, ts.id, False, f.get("reject_reason") or "Rejected (CSV import)")
    tot = T.ser(db, ts, e, lines=False)["totals"]
    return _info(f"{e.employee_number} {E.full_name(e)} · week of {week.isoformat()}", f"{len(lines)} line(s) · {tot['total']} h (ordinary {tot['ordinary']}, overtime {tot['overtime']}, leave {tot['leave']}) · {ts.status}")


def _h_leave_request(db, org, ctx, a, rec):
    f = rec.fields
    e = _employee(db, org, f.get("employee_number"))
    lt = _leave_type(db, org, f.get("leave_type"))
    status = _choice(f.get("status") or "pending", ("pending", "approved", "rejected"), "status")
    sd, ed = _date(f.get("start_date"), "start_date"), _date(f.get("end_date"), "end_date")
    if sd and ed and db.query(PayLeaveRequest.id).filter(PayLeaveRequest.org_id == org.id, PayLeaveRequest.employee_id == e.id, PayLeaveRequest.leave_type_id == lt.id,
                                                         PayLeaveRequest.start_date == sd, PayLeaveRequest.end_date == ed, PayLeaveRequest.status != "cancelled").first():
        raise PayrollError(f"{E.display_name(e)} already has a {lt.name} request for {sd.isoformat()} to {ed.isoformat()} (leave requests are loaded once)")
    r = L.request_leave(db, ctx, a, dict(employee_id=e.id, leave_type_id=lt.id, start_date=_date(f.get("start_date"), "start_date"), end_date=_date(f.get("end_date"), "end_date"),
                                         hours=_dec(f.get("hours"), "hours"), reason=f.get("reason") or None))
    if status == "approved":
        L.decide(db, ctx, a, r.id, True, f.get("decision_note") or "")
    elif status == "rejected":
        L.decide(db, ctx, a, r.id, False, f.get("decision_note") or "Not approved (CSV import)")
    return _info(f"{e.employee_number} {E.full_name(e)}", f"{lt.name} {r.start_date.isoformat()} to {r.end_date.isoformat()} · {r.hours} h · {r.status}")


# ----------------------------------------------------------------------------------------------- 16-18 pay run flow --
_RUN_STEP = {"draft": 0, "calculated": 1, "review": 1, "approved": 2, "finalised": 3}
_RUN_NOW = {"draft": 0, "review": 1, "approved": 2, "finalised": 3, "paid": 3}


def _find_run(db, org, cal, start) -> Optional[PayRun]:
    return (db.query(PayRun).filter(PayRun.org_id == org.id, PayRun.calendar_id == cal.id, PayRun.period_start == start, PayRun.run_type == "regular",
                                    PayRun.status != "voided", PayRun.reversed_by_run_id.is_(None)).first())


def _h_pay_run(db, org, ctx, a, rec):
    f = rec.fields
    cal = _calendar(db, org, f.get("calendar"))
    start = _date(f.get("period_start"), "period_start")
    if start is None:
        raise PayrollError("period_start is required")
    p = C.period_containing(cal, start)
    end = _date(f.get("period_end"), "period_end") or p["period_end"]
    target = _choice(f.get("status") or "draft", tuple(_RUN_STEP), "status")
    want = _RUN_STEP[target]
    run = _find_run(db, org, cal, start)
    existed = run is not None
    if run is None:
        body = dict(calendar_id=cal.id, period_start=start, period_end=end, run_type=_choice(f.get("run_type") or "regular", ("regular", "off_cycle", "termination"), "run_type"),
                    notes=f.get("notes") or None)
        if f.get("pay_date"):
            body["pay_date"] = _date(f["pay_date"], "pay_date")
        if f.get("name"):
            body["name"] = f["name"]
        if f.get("employees"):
            body["employee_ids"] = [_employee(db, org, n).id for n in re.split(r"[|;]", f["employees"]) if n.strip()]
        run = R.create_run(db, ctx, a, body)
    cur = _RUN_NOW[run.status]
    warn = []
    if existed and cur > want:
        raise PayrollError(f"{run.run_no} is already {run.status}; it cannot go back to {target}")
    if existed and cur == want:
        warn.append(f"{run.run_no} is already {run.status}: nothing to do")
    if want >= 1 and cur <= 1 and not (existed and cur == 1 and want == 1):
        R.calculate(db, ctx, a, run.id)                      # (re)calculate: picks up inputs, timesheets and leave added since the last calculation
    if want >= 2 and cur < 2:
        if run.error_count:
            bad = [(x.employee_name, (x.errors or [{}])[0].get("message", "")) for x in db.query(PayRunEmployee).filter_by(run_id=run.id) if x.errors]
            raise PayrollError(f"{run.run_no} cannot be {target}: {run.error_count} employee(s) have errors - " + "; ".join(f"{n}: {m}" for n, m in bad[:4]) + (" ..." if len(bad) > 4 else ""))
        R.approve(db, ctx, a, run.id)
    if want >= 3 and cur < 3:
        R.finalise(db, ctx, a, run.id)
    db.flush()
    if run.error_count and want < 2:
        warn.append(f"{run.error_count} employee(s) have errors: fix them (or exclude them) before approving")
    if run.warning_count:
        warn.append(f"{run.warning_count} employee(s) have warnings")
    return _info(f"{run.run_no} · {cal.name} {run.period_start.isoformat()} to {run.period_end.isoformat()}",
                 f"{run.status} · {run.employee_count} employee(s) · gross ${run.total_gross:,.2f} · net ${run.total_net:,.2f} · pay date {run.pay_date.isoformat()}",
                 amount=str(run.total_net) if run.status != "draft" else None, action="update" if existed else "create", warnings=warn)


def _h_run_input(db, org, ctx, a, rec):
    f = rec.fields
    if f.get("run"):
        run = db.query(PayRun).filter(PayRun.org_id == org.id, _ci(PayRun.run_no, f["run"]), PayRun.status != "voided").first()
        if run is None:
            raise PayrollError(f"Pay run '{f['run']}' does not exist")
    else:
        cal = _calendar(db, org, f.get("calendar"))
        start = _date(f.get("period_start"), "period_start")
        run = _find_run(db, org, cal, start) if (cal and start) else None
        if run is None:
            raise PayrollError("Say which pay run: give `run` (e.g. PR-0007) or `calendar` and `period_start` of a run that has been created (load the pay_runs file with status draft first)")
    e = _employee(db, org, f.get("employee_number"))
    it = _item(db, org, f.get("pay_item"))
    body = dict(employee_id=e.id, pay_item_id=it.id, hours=_dec(f.get("hours"), "hours"), rate=_dec(f.get("rate"), "rate"), amount=_dec(f.get("amount"), "amount"),
                periods=int(_dec(f["periods"], "periods")) if f.get("periods") else None, leave_pre1993=bool(_bool(f.get("leave_pre1993"), False, "leave_pre1993")),
                genuine_redundancy=bool(_bool(f.get("genuine_redundancy"), False, "genuine_redundancy")), note=f.get("note") or None)
    for x in db.query(PayRunInput).filter_by(run_id=run.id, employee_id=e.id, pay_item_id=it.id):
        if (x.amount, x.hours, x.note) == (body["amount"], body["hours"], body["note"]):
            raise PayrollError(f"{it.code} for {E.display_name(e)} is already on {run.run_no} with these details")
    R.add_input(db, ctx, a, run.id, body)
    shown = f"${body['amount']:,.2f}" if body["amount"] is not None else (f"{body['hours']} h" if body["hours"] else "default amount")
    return _info(f"{run.run_no} · {e.employee_number} {E.full_name(e)}", f"{it.code} {it.name}: {shown}" + (f" · {body['note']}" if body["note"] else ""), amount=str(body["amount"]) if body["amount"] is not None else None)


# -------------------------------------------------------------------------------------------------------- registry --
SPECS: Dict[str, Spec] = {}


def _reg(s: Spec):
    SPECS[s.key] = s
    return s


_EMP = Col("employee_number", "The employee's number, as created by the Employees import (e.g. B0001)", True, "B0001", ("employee_no", "emp_no", "employee_id", "staff_no"))
_ACTIVE = Col("active", "yes / no (default yes)", False, "yes", ("is_active",))

_reg(Spec("settings", "Organisation, payslip & payment settings", 1, "Settings", "config_manage",
          "One row of organisation-level payroll settings: employer name and ABN, number prefixes, payslip options and the company bank account used for the bank file. Leave a cell blank to keep the current value.",
          [Col("employer_name", "Employer name printed on payslips", False, "Bluegum Logistics Pty Ltd"), Col("abn", "11-digit ABN with a valid check digit", False, "51 824 753 556"),
           Col("default_frequency", "weekly, fortnightly or monthly", False, "fortnightly"), Col("standard_hours_per_week", "Full-time hours per week", False, "38"),
           Col("employee_prefix", "Prefix for new employee numbers (1-6 letters/digits)", False, "B"), Col("run_prefix", "Prefix for pay run numbers", False, "PR"),
           Col("show_ytd", "Show year-to-date on payslips (yes/no)", False, "yes"), Col("show_leave", "Show leave balances on payslips (yes/no)", False, "yes"),
           Col("payslip_footer", "Footer text on payslips", False, "TEST DATA - not a real payslip"), Col("stp_bms_id", "STP software / BMS id (recorded in STP payloads)", False, "ACCFINO-TEST"),
           Col("require_separate_approver", "The creator of a pay run cannot approve it (yes/no)", False, "no"),
           Col("payment_bsb", "Company bank BSB for the bank file", False, "062-000"), Col("payment_account", "Company bank account number (stored encrypted, never shown)", False, "12345678"),
           Col("payment_account_name", "Company account name", False, "Bluegum Logistics"), Col("payment_apca_user_id", "APCA user id (6 digits)", False, "301500"),
           Col("payment_bank_abbrev", "Bank abbreviation (3 letters)", False, "CBA"), Col("payment_description", "Bank file description", False, "PAYROLL"),
           Col("payment_bank_account", "Ledger code of the bank account wages are paid from, e.g. 090 (must exist: Books & Accounting > Banking). Needed for the payment to reach the ledger", False, "090")],
          _h_settings, max_records=1, upsert=True, notes=["The company account number is stored encrypted and is never shown again.", "payment_bank_account must already exist in the chart of accounts (add bank account 090 in Books & Accounting > Banking first)."]))
_reg(Spec("calendars", "Pay calendars", 2, "Settings", "config_manage", "Weekly, fortnightly and monthly pay calendars. Matched on name: an existing calendar is updated (its frequency and start date cannot change once it has pay runs).",
          [Col("name", "Calendar name (unique)", True, "Fortnightly (Mon start)"), Col("frequency", "weekly, fortnightly or monthly", True, "fortnightly"),
           Col("anchor_start", "First day of any pay period (use a Monday for weekly/fortnightly, the 1st for monthly)", True, "2026-06-29"),
           Col("pay_offset_days", "Days from period end to pay date (0-31, default 5)", False, "5"), Col("is_default", "Make this the default calendar (yes/no)", False, "yes"), _ACTIVE],
          _h_calendar, upsert=True, sample=[["Fortnightly (Mon start)", "fortnightly", "2026-06-29", "5", "yes", "yes"]]))
_reg(Spec("departments", "Departments", 3, "Settings", "config_manage", "Departments used for employee grouping and cost reports. Matched on code.",
          [Col("code", "Short code, letters/digits, up to 20", True, "OPS"), Col("name", "Department name", True, "Operations"), _ACTIVE], _h_simple(PayDepartment, C.save_department, "Department"),
          upsert=True, sample=[["OPS", "Operations", "yes"]]))
_reg(Spec("locations", "Locations", 4, "Settings", "config_manage", "Work locations. Matched on code.",
          [Col("code", "Short code", True, "SYD"), Col("name", "Location name", True, "Sydney HQ"), Col("state", "State (NSW, VIC, QLD, SA, WA, TAS, NT, ACT)", False, "NSW"), _ACTIVE],
          _h_simple(PayLocation, C.save_location, "Location", extra=("state",)), upsert=True, sample=[["SYD", "Sydney HQ", "NSW", "yes"]]))
_reg(Spec("super_funds", "Super funds", 5, "Settings", "config_manage", "Superannuation funds (APRA-regulated or self-managed). Matched on name. A self-managed fund needs its BSB and account.",
          [Col("name", "Fund name (unique)", True, "AustralianSuper"), Col("fund_type", "apra (default) or smsf", False, "apra"), Col("usi", "Unique Superannuation Identifier", False, "STA0100AU"),
           Col("abn", "Fund ABN (valid check digit)", False, "65 714 394 898"), Col("esa", "Electronic service address", False, ""),
           Col("smsf_bsb", "SMSF bank BSB (SMSF only)", False, "063-000"), Col("smsf_account", "SMSF bank account (SMSF only, stored encrypted)", False, "55667788"),
           Col("smsf_account_name", "SMSF bank account name", False, ""), Col("default", "Employer default fund (yes/no)", False, "yes"), _ACTIVE],
          _h_fund, upsert=True, sample=[["AustralianSuper", "apra", "STA0100AU", "", "", "", "", "", "yes", "yes"]]))
_reg(Spec("leave_types", "Leave types (policies)", 6, "Settings", "config_manage", "Leave policies and accrual rules. Matched on code. Standard types AL, PL, CL, LSL, PAR and LWP already exist: a row with one of those codes updates it.",
          [Col("code", "Short code (letters, digits, underscore)", True, "AL"), Col("name", "Leave type name", True, "Annual leave"),
           Col("category", "annual, personal, long_service, compassionate, parental, unpaid or other", False, "annual"), Col("paid", "Paid leave (yes/no)", False, "yes"),
           Col("accrual_method", "none, per_ordinary_hour or fixed_per_year", False, "per_ordinary_hour"), Col("accrual_annual_hours", "Hours accrued per year for a standard week", False, "152"),
           Col("accrue_on_paid_leave", "Keep accruing while on paid leave (yes/no)", False, "yes"), Col("applies_to", "Employment types, separated by |: full_time|part_time|casual|contractor (blank = everyone)", False, "full_time|part_time"),
           Col("loading_pct", "Leave loading % (annual leave 17.5)", False, "17.5"), Col("max_balance", "Maximum balance in hours (blank = none)", False, ""),
           Col("min_service_years", "Years of service before it can be taken (long service 7)", False, "0"), Col("allow_negative", "Allow a negative balance (yes/no)", False, "no"), _ACTIVE],
          _h_leave_type, upsert=True, sample=[["AL", "Annual leave", "annual", "yes", "per_ordinary_hour", "152", "yes", "full_time|part_time", "17.5", "", "0", "no", "yes"]]))
_reg(Spec("pay_items", "Pay items (earnings, deductions, super)", 7, "Settings", "items_manage", "Earnings, allowances, deductions, salary sacrifice and reimbursement items. Matched on code. System items (BASE, ORD, UNPAID, LEAVELOAD, SALADJ) keep their code and type.",
          [Col("code", "Code, letters/digits/underscore, up to 20 (upper-cased)", True, "TOOL"), Col("name", "Name shown on payslips", False, "Tool allowance"),
           Col("kind", "earnings, overtime, penalty, allowance, bonus, commission, back_pay, leave, leave_loading, termination_leave, etp, salary_adjustment, unpaid_leave, deduction_pretax, salary_sacrifice_super, deduction_posttax, employee_super_after_tax, employer_super_additional, reimbursement", False, "allowance"),
           Col("calc_method", "fixed, hours_x_rate, percent_of_base or percent_of_gross", False, "fixed"), Col("multiplier", "Multiple of the base rate for hours_x_rate (1.5 = time and a half)", False, "1"),
           Col("rate", "Fixed $/hour (optional)", False, ""), Col("default_amount", "Default amount per pay for fixed items", False, "50"), Col("percent", "Default percent for percent items", False, ""),
           Col("taxable", "Subject to PAYG (yes/no; earnings only)", False, "yes"), Col("payg_treatment", "regular, additional (bonus method), none, termination_leave or etp", False, "regular"),
           Col("super_treatment", "ote (super payable) or none", False, "none"), Col("reportable_fringe", "Reportable fringe benefit (yes/no)", False, "no"),
           Col("leave_type", "Leave type code this pay item draws on (leave items)", False, ""), Col("expense_account", "Ledger account code (e.g. 477); blank = default", False, ""),
           Col("description", "Free text", False, ""), _ACTIVE],
          _h_pay_item, upsert=True, sample=[["TOOL", "Tool allowance", "allowance", "fixed", "1", "", "50", "", "yes", "regular", "none", "no", "", "", "", "yes"]]))
_reg(Spec("employees", "Employees (personal & employment)", 8, "Employees", "employees_manage",
          "Personal details, employment terms and pay rate. Matched on employee_number: an existing employee is updated (blank cells keep the current value). Managers listed in the same file are loaded first. Tax, super and bank details have their own imports.",
          [_EMP, Col("first_name", "First name (required for a new employee)", False, "Olivia", ("firstname", "given_name")), Col("middle_name", "Middle name", False, ""),
           Col("last_name", "Last name (required for a new employee)", False, "Chen", ("surname", "family_name", "lastname")), Col("preferred_name", "Preferred name", False, ""),
           Col("date_of_birth", "Date of birth", False, "1988-03-14", ("dob",)), Col("email", "Email address", False, "olivia.chen@example.com"), Col("phone", "Phone", False, "0400 000 000"),
           Col("address_line1", "Street address", False, "1 Demo Street"), Col("address_line2", "Address line 2", False, ""), Col("suburb", "Suburb", False, "Sydney"),
           Col("state", "State", False, "NSW"), Col("postcode", "4-digit postcode", False, "2000"),
           Col("start_date", "First day of employment (required for a new employee)", False, "2025-07-01", ("commencement_date", "hire_date")), Col("end_date", "Last day of employment, if known", False, ""),
           Col("status", "active (default), inactive or terminated (terminated needs end_date)", False, "active"), Col("termination_reason", "Reason for leaving", False, ""),
           Col("employment_type", "full_time (default), part_time, casual or contractor", False, "full_time", ("type",)), Col("position", "Job title", False, "Finance Manager", ("job_title",)),
           Col("department", "Department code", False, "FIN", ("department_code", "dept")), Col("location", "Location code", False, "SYD", ("location_code",)),
           Col("manager", "Employee number of the line manager", False, "B0001", ("manager_number", "reports_to")), Col("calendar", "Pay calendar name", False, "Fortnightly (Mon start)", ("pay_calendar",)),
           Col("pay_frequency", "weekly, fortnightly or monthly (default: the calendar's)", False, "fortnightly"), Col("pay_basis", "salary or hourly (default: hourly if only an hourly rate is given)", False, "salary"),
           Col("annual_salary", "Annual salary (salaried)", False, "128000", ("salary",)), Col("hourly_rate", "Hourly rate (hourly / casual)", False, "", ("rate",)),
           Col("hours_per_week", "Ordinary hours per week (default 38)", False, "38", ("weekly_hours",)), Col("pay_standard_hours", "Hourly employee paid standard hours each period without timesheets (yes/no)", False, "no"),
           Col("work_pattern", "Scheduled hours per day, e.g. mon=7.6|tue=7.6|wed=7.6|thu=7.6|fri=0 (days not listed are days off; default: hours_per_week over Mon-Fri)", False, ""),
           Col("login_email", "Email of an existing organisation login to link for self-service (My Pay)", False, "")],
          _h_employee, upsert=True, pre_sort=_employee_depth(), notes=["Do not put TFNs or bank details in this file - use the Tax and Bank imports."],
          group_fn=lambda r: None))
_reg(Spec("employee_tax", "Employee tax declarations (incl. TFN and opening YTD)", 9, "Employees", "employees_manage",
          "Tax file number, residency, tax-free threshold, study loan and withholding variations; optional opening year-to-date totals for people migrated part-way through the year. One row per employee.",
          [_EMP, Col("tfn", "9-digit TFN with a valid check digit (stored encrypted, never shown again)", False, "123 456 782"), Col("tfn_status", "provided, pending, exempt or not_provided", False, "provided"),
           Col("residency", "resident or foreign_resident", False, "resident"), Col("claims_tft", "Claims the tax-free threshold (yes/no)", False, "yes"),
           Col("has_study_loan", "Has a study / training support loan (yes/no)", False, "no"), Col("study_loan_type", "e.g. HELP", False, ""),
           Col("medicare_variation", "none, half or full", False, "none"), Col("tax_offset_annual", "Annual tax offset claimed", False, "0"), Col("extra_withholding", "Extra amount withheld each pay", False, "0"),
           Col("variation_pct", "Approved withholding variation %", False, ""), Col("declaration_date", "Date the declaration was signed", False, "2025-07-01"),
           Col("ytd_fy", "Opening YTD: financial year (e.g. 2026-27)", False, ""), Col("ytd_gross", "Opening YTD gross", False, ""), Col("ytd_taxable", "Opening YTD taxable", False, ""),
           Col("ytd_tax", "Opening YTD tax withheld", False, ""), Col("ytd_study_loan", "Opening YTD study loan repaid", False, ""), Col("ytd_super_guarantee", "Opening YTD super guarantee", False, ""),
           Col("ytd_super_total", "Opening YTD total super", False, ""), Col("ytd_qualifying_earnings", "Opening YTD ordinary time earnings", False, ""),
           Col("ytd_salary_sacrifice", "Opening YTD salary sacrifice", False, ""), Col("ytd_net", "Opening YTD net pay", False, "")],
          _h_tax, upsert=True, notes=["TFNs are sealed on the way in; the results show only the masked form (*** *** 782)."]))
_reg(Spec("employee_super", "Employee super fund memberships", 10, "Employees", "employees_manage",
          "Which fund(s) each employee's super goes to. One row per fund; all rows of an employee are loaded together and replace their current membership. Allocations must total 100%.",
          [_EMP, Col("fund", "Fund name, as in the Super funds import", True, "AustralianSuper"), Col("member_number", "Member number (required for an APRA fund unless it is the employer default)", False, "M000123"),
           Col("allocation_pct", "Share of the contribution (default 100)", False, "100"), Col("is_default_fund", "Employer default fund (yes/no)", False, "no"),
           Col("choice_form_date", "Date the standard choice form was received", False, "2025-07-01")],
          _h_super, group_fn=lambda r: (r.get("employee_number") or "").lower() or None, upsert=True))
_reg(Spec("employee_bank", "Employee bank accounts", 11, "Employees", "employees_manage",
          "Where each employee's net pay is paid. One row per account; all rows of an employee are loaded together and replace their current accounts. Exactly one account must be the remainder. Account numbers are stored encrypted and never shown again.",
          [_EMP, Col("account_name", "Account name", True, "Olivia Chen"), Col("bsb", "6-digit BSB", True, "062-000"), Col("account_number", "Account number, 5-9 digits (stored encrypted)", True, "10000037"),
           Col("allocation_type", "remainder (default), fixed or percent", False, "remainder"), Col("allocation_value", "Dollar amount (fixed) or percent; blank for remainder", False, ""),
           Col("reference", "Bank statement reference (up to 18 characters)", False, "")],
          _h_bank, group_fn=lambda r: (r.get("employee_number") or "").lower() or None, upsert=True))
_reg(Spec("employee_items", "Recurring pay items (allowances, deductions, salary sacrifice)", 12, "Employees", "employees_manage",
          "Pay items that apply to an employee in every pay run until removed (tool allowance, union fees, salary sacrifice, loan repayments ...). New records only: loading the same file twice is refused.",
          [_EMP, Col("pay_item", "Pay item code", True, "TOOL"), Col("amount", "Fixed amount per pay (blank = the item's default)", False, "50"), Col("rate", "Rate or percent (percent items)", False, ""),
           Col("hours", "Hours (hourly items)", False, ""), Col("effective_from", "Starts on", False, ""), Col("effective_to", "Ends on", False, ""), Col("note", "Note", False, "")],
          _h_emp_item, notes=["System and generated items (overtime, leave, termination payments) cannot be assigned as recurring items."]))
_reg(Spec("leave_balances", "Opening leave balances", 13, "Employees", "leave_manage",
          "Leave balances brought across from a previous system, as hours at a date. New records only: an employee can have one opening balance per leave type (use type=adjustment later).",
          [_EMP, Col("leave_type", "Leave type code", True, "AL"), Col("hours", "Balance in hours (negative only for an adjustment)", True, "120"),
           Col("as_at", "Balance date (default today). Use a date before the first pay run, e.g. the start of the year", False, "2026-07-01"),
           Col("type", "opening (default) or adjustment", False, "opening"), Col("note", "Reason / note", False, "Opening balance")],
          _h_leave_balance))
_reg(Spec("timesheets", "Timesheets", 14, "Time & Leave", "timesheets_manage",
          "Weekly timesheets for hourly employees, one row per day-line. Rows are grouped into one timesheet per employee and week (Monday to Sunday). Each timesheet can be loaded as draft, submitted, approved or rejected. New records only.",
          [_EMP, Col("work_date", "Date worked", True, "2026-09-21"), Col("pay_item", "Hourly pay item code: ORD, OT15, OT20, SAT, SUN, PH or a leave item", True, "ORD"),
           Col("hours", "Hours (or give start_time and end_time)", False, "8"), Col("start_time", "24-hour HH:MM", False, "08:00"), Col("end_time", "24-hour HH:MM", False, "16:30"),
           Col("break_minutes", "Unpaid break in minutes", False, "30"), Col("leave_type", "Leave type code (leave lines only)", False, ""), Col("line_notes", "Note on this line", False, ""),
           Col("status", "draft (default), submitted, approved or rejected - same on every row of a timesheet", False, "approved"), Col("reject_reason", "Reason (rejected timesheets)", False, ""),
           Col("notes", "Note on the whole timesheet", False, "")],
          _h_timesheet, group_fn=_ts_key, header_cols=("status",), notes=["The employee must be hourly (salaried employees record leave, not timesheets).",
                                                                          "Approving is done by the person importing: they cannot approve a timesheet for their own employee record."]))
_reg(Spec("leave_requests", "Leave requests", 15, "Time & Leave", "leave_manage",
          "Leave requests, optionally already approved or rejected. Balance, overlap and scheduled-hours rules are checked exactly as in the app. Approved leave is paid in the next pay run that covers it. New records only.",
          [_EMP, Col("leave_type", "Leave type code", True, "AL"), Col("start_date", "First day of leave", True, "2026-10-12"), Col("end_date", "Last day of leave", True, "2026-10-16"),
           Col("hours", "Hours (blank = scheduled hours between the dates)", False, ""), Col("reason", "Reason", False, "Family holiday"),
           Col("status", "pending (default), approved or rejected", False, "pending"), Col("decision_note", "Note on the decision (required when rejected)", False, "")],
          _h_leave_request))
_reg(Spec("pay_runs", "Pay runs (create / calculate / approve / finalise)", 16, "Pay runs", "run_create",
          "Creates a pay run for a calendar period and optionally takes it forward through the real pay run steps. status: draft (create only), calculated, approved or finalised. If the run already exists it is moved forward. Runs are processed oldest first.",
          [Col("calendar", "Pay calendar name", True, "Fortnightly (Mon start)", ("pay_calendar",)), Col("period_start", "First day of the pay period (must be a real period of that calendar)", True, "2026-06-29"),
           Col("period_end", "Last day of the period (default: the calendar's)", False, ""), Col("pay_date", "Pay date (default: the calendar's)", False, ""), Col("name", "Run name", False, ""),
           Col("run_type", "regular (default), off_cycle or termination", False, "regular"), Col("status", "draft (default), calculated, approved or finalised", False, "finalised"),
           Col("employees", "Only these employee numbers, separated by | (default: everyone eligible)", False, ""), Col("notes", "Notes", False, "")],
          _h_pay_run, upsert=True, sort_key=lambda rc: (_sort_date(rc.fields.get("period_start")), rc.fields.get("calendar") or ""),
          notes=["A run with errors cannot be approved or finalised: the file is refused and the errors are listed.", "Finalising posts the run's journal to the general ledger."]))
_reg(Spec("pay_run_inputs", "Pay run inputs (bonuses, adjustments, termination payments)", 17, "Pay runs", "run_create",
          "One-off items for a pay run that has been created but not yet approved: bonuses, commissions, reimbursements, back pay, unused leave payout, ETPs. Identify the run by run number, or by calendar and period_start. New records only.",
          [Col("run", "Pay run number, e.g. PR-0007 (or give calendar + period_start)", False, "PR-0007"), Col("calendar", "Pay calendar name (if no run number)", False, ""),
           Col("period_start", "Period start (if no run number)", False, ""), _EMP, Col("pay_item", "Pay item code: BONUS, COMM, BACKPAY, REIMB, TLEAVE, ETP, TOOL ...", True, "BONUS"),
           Col("amount", "Amount (fixed items)", False, "3000"), Col("hours", "Hours (hourly items)", False, ""), Col("rate", "Rate", False, ""), Col("periods", "Pay periods a back-payment relates to", False, ""),
           Col("genuine_redundancy", "ETP is a genuine redundancy (yes/no)", False, "no"), Col("leave_pre1993", "Unused leave accrued before 17 Aug 1993 (yes/no)", False, "no"), Col("note", "Note", False, "Q3 bonus")],
          _h_run_input))

# ------------------------------------------------------------------------------------------------------------ public --
def catalogue() -> List[dict]:
    return [s.info() for s in sorted(SPECS.values(), key=lambda s: s.order)]


def template_csv(key: str) -> str:
    s = SPECS[key]
    buf = io.StringIO()
    w = csv.writer(buf, lineterminator="\r\n")
    w.writerow([c.name for c in s.columns])
    w.writerow([c.example for c in s.columns])
    return buf.getvalue()


def run_import(db, org, ctx, access, entity: str, raw, *, dry_run: bool = True, filename: str = "") -> dict:
    """Validate (and, unless dry_run, stage) an import. The CALLER commits when `error` is empty and dry_run is False, and rolls back otherwise.
    -> dict(entity, dry_run, count, valid, invalid, saved, items[], warnings[], error, total)"""
    spec = SPECS.get(entity)
    if spec is None:
        raise PayrollError(f"Unknown import '{entity}'. Available: {', '.join(SPECS)}", 404)
    if isinstance(raw, (bytes, bytearray)) and len(raw) > MAX_BYTES:
        raise PayrollError("File too large (5 MB max). Split it and import it in parts", 413)
    grid = _grid(_decode(raw))
    if not grid:
        raise PayrollError("The file is empty")
    if len(grid) == 1:
        raise PayrollError("The file has a header row but no data rows")
    result = dict(entity=entity, title=spec.title, dry_run=dry_run, count=0, valid=0, invalid=0, saved=0, items=[], warnings=[], error=None, total="0.00")
    recs = _records(spec, grid, result)
    if spec.sort_key:
        recs.sort(key=spec.sort_key)
    if spec.pre_sort:
        recs = spec.pre_sort(recs)
    result["count"] = len(recs)
    total = Z
    for rec in recs:
        item = dict(row=rec.row, key=rec.key, label=rec.key or f"row {rec.row}", detail="", amount=None, errors=[], warnings=[], action="create")
        try:
            if rec.conflicts:
                raise PayrollError("; ".join(rec.conflicts).capitalize())
            with db.begin_nested():
                info = spec.handler(db, org, ctx, access, rec)
            item.update(label=info["label"], detail=info["detail"], amount=str(info["amount"]) if info.get("amount") is not None else None, action=info.get("action", "create"),
                        warnings=list(info.get("warnings") or []))
            if info.get("amount") is not None:
                total += Decimal(str(info["amount"]))
        except (PayrollError, ValueError, InvalidOperation, KeyError) as e:
            item["errors"].append(str(e.args[0]) if isinstance(e, KeyError) else str(e))
        except SQLAlchemyError as e:
            item["errors"].append("The database rejected this record: " + str(getattr(e, "orig", e)).splitlines()[0][:200])
        result["items"].append(item)
    result["invalid"] = sum(1 for i in result["items"] if i["errors"])
    result["valid"] = result["count"] - result["invalid"]
    result["total"] = str(total)
    db.info.pop("pay_outbox", None)                     # an import never sends e-mail
    if result["invalid"]:
        result["error"] = f"{result['invalid']} of {result['count']} record(s) have problems; nothing was imported. Fix the file and try again."
        db.rollback()
    elif dry_run:
        db.rollback()
    else:
        audit.record(db, ctx, "import.csv", "import", None, spec.key, f"CSV import of {result['count']} {spec.title.lower()} record(s)" + (f" from {filename[:80]}" if filename else ""),
                     after=dict(entity=spec.key, records=result["count"], file=filename[:200]))
        db.flush()
        result["saved"] = result["count"]
    result["items_truncated"] = max(0, len(result["items"]) - MAX_ITEMS_RETURNED)
    bad = [i for i in result["items"] if i["errors"]]
    ok = [i for i in result["items"] if not i["errors"]]
    result["items"] = (bad + ok)[:MAX_ITEMS_RETURNED]          # problems first, so they are never cut off
    return result
