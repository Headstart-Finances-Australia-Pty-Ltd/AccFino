"""Fringe benefits tax: benefit register (valued by the FBT engine), employer FBT return summary with RFBA, and the return workflow (user-recorded lodgement)."""
import hashlib
import json
from datetime import date, datetime
from typing import Optional

import accfino.modules.payroll.public as payroll
from accfino.modules.taxation.engine import fbt as E, rules as R
from accfino.modules.taxation.engine.money import ZERO, D, q2
from accfino.modules.taxation.models import tax as T
from accfino.modules.taxation.services import core, obligations as O, profile as P
from accfino.modules.taxation.services.core import Conflict, NotFound, TaxError

NUM_KEYS = ("base_value", "days_available", "average_balance", "interest_paid", "days", "actual_cost", "otherwise_deductible", "employee_contribution", "market_value", "taxable_percent")


def check_year(label: str):
    try:
        R.fbt_bounds(label)
    except R.RulesError as e:
        raise TaxError(str(e))
    return label


def b_dict(b: T.TaxFbtBenefit) -> dict:
    return dict(id=b.id, fbt_year=b.fbt_year, employee=b.employee, employee_id=b.employee_id, benefit_type=b.benefit_type, description=b.description, type1=b.type1, inputs=b.inputs or {},
                taxable_value=str(b.taxable_value), method=b.method, notes=b.notes or {})


def _guard(db, ctx, year):
    r = db.query(T.TaxFbtReturn).filter(T.TaxFbtReturn.org_id == ctx.org.id, T.TaxFbtReturn.fbt_year == year, T.TaxFbtReturn.status.in_(("approved", "lodged", "paid"))).first()
    if r:
        raise Conflict(f"The {year} FBT return is {r.status}: return it to draft before changing benefits.", "locked")


def save_benefit(db, ctx, a: core.Access, year: str, body: dict, bid: Optional[int] = None) -> T.TaxFbtBenefit:
    a.require("prepare")
    check_year(year)
    _guard(db, ctx, year)
    p = P.get(db, ctx)
    t = body.get("benefit_type")
    if t not in T.FBT_TYPES:
        raise TaxError(f"benefit_type must be one of {', '.join(T.FBT_TYPES)}")
    inputs = {k: v for k, v in (body.get("inputs") or {}).items() if k in NUM_KEYS + ("exempt_reason", "minor_benefit")}
    for k in NUM_KEYS:
        if k in inputs and inputs[k] not in (None, ""):
            inputs[k] = str(core.money_in(inputs[k], k, required=True))
    rs = core.rules_for_fbt_year(db, ctx, year)
    try:
        val = E.taxable_value(rs, dict(inputs, type=t))
    except ValueError as e:
        raise TaxError(str(e))
    emp, emp_id = (body.get("employee") or "").strip(), body.get("employee_id")
    if emp_id:
        names = {x["id"]: x["name"] for x in payroll.employee_names(db, ctx.org.id)}
        if emp_id not in names:
            raise TaxError("employee_id is not an active employee of this organisation")
        emp = emp or names[emp_id]
    if not emp:
        raise TaxError("An employee (or associate) name is required")
    if bid:
        b = db.query(T.TaxFbtBenefit).filter_by(org_id=ctx.org.id, id=bid, fbt_year=year).first()
        if b is None:
            raise NotFound("FBT benefit")
    else:
        b = T.TaxFbtBenefit(org_id=ctx.org.id, fbt_year=year, created_by=ctx.user_id)
    before = b_dict(b) if bid else None
    b.employee, b.employee_id, b.benefit_type, b.description = emp[:200], emp_id, t, (body.get("description") or "")[:300] or None
    b.type1, b.inputs = bool(body.get("type1", True)), inputs
    b.taxable_value, b.method, b.notes = D(val["taxable_value"]), val["method"], dict(notes=val["notes"], review=val["review"])
    if not bid:
        db.add(b)
    db.flush()
    core.record(db, ctx, "fbt.benefit.save", "tax_fbt_benefit", b.id, f"FBT benefit {t} for {emp} valued at {b.taxable_value} ({year})", before, b_dict(b))
    return b


def delete_benefit(db, ctx, a: core.Access, year: str, bid: int):
    a.require("prepare")
    _guard(db, ctx, year)
    b = db.query(T.TaxFbtBenefit).filter_by(org_id=ctx.org.id, id=bid, fbt_year=year).first()
    if b is None:
        raise NotFound("FBT benefit")
    core.record(db, ctx, "fbt.benefit.delete", "tax_fbt_benefit", b.id, "FBT benefit deleted", b_dict(b), None)
    db.delete(b)


def benefits(db, ctx, year: str):
    return [b_dict(b) for b in db.query(T.TaxFbtBenefit).filter_by(org_id=ctx.org.id, fbt_year=year).order_by(T.TaxFbtBenefit.employee, T.TaxFbtBenefit.id)]


def summary(db, ctx, year: str) -> dict:
    check_year(year)
    rs = core.rules_for_fbt_year(db, ctx, year)
    rows = [dict(employee=b.employee, type1=b.type1, taxable_value=b.taxable_value) for b in db.query(T.TaxFbtBenefit).filter_by(org_id=ctx.org.id, fbt_year=year)]
    res = E.year_summary(rs, rows)
    res.update(fbt_year=year, benefit_count=len(rows), rule_set=rs.id)
    res["findings"] = []
    p = P.get(db, ctx)
    if rs.provisional:
        res["findings"].append(dict(key="provisional_rules", severity="warn", message=f"Rule set {rs.id} is PROVISIONAL: the FBT benchmark rate and thresholds for this year are not loaded or confirmed."))
    if rows and not p.fbt_registered:
        res["findings"].append(dict(key="not_registered", severity="warn", message="Benefits are recorded but the tax profile says the organisation is not registered for FBT. Register with the ATO before lodging a return."))
    for b in db.query(T.TaxFbtBenefit).filter_by(org_id=ctx.org.id, fbt_year=year):
        for rv in (b.notes or {}).get("review", []):
            res["findings"].append(dict(key=f"benefit_{b.id}", severity="review", message=f"{b.employee} ({b.benefit_type}): {rv}"))
    return res


def _hash(s: dict) -> str:
    return hashlib.sha256(json.dumps(s, sort_keys=True, default=str).encode()).hexdigest()


def r_dict(r: T.TaxFbtReturn, full=True) -> dict:
    d = dict(id=r.id, fbt_year=r.fbt_year, status=r.status, fbt_payable=core.plain(r.fbt_payable), due_date=core.plain(r.due_date), prepared_by=r.prepared_by, approved_by=r.approved_by,
             lodged_on=core.plain(r.lodged_on), lodgement_reference=r.lodgement_reference, lodgement_method=r.lodgement_method, paid_on=core.plain(r.paid_on))
    if full:
        d["summary"] = r.summary or {}
    return d


def returns(db, ctx):
    return [r_dict(r, False) for r in db.query(T.TaxFbtReturn).filter_by(org_id=ctx.org.id).order_by(T.TaxFbtReturn.fbt_year.desc())]


def get_return(db, ctx, rid):
    r = db.query(T.TaxFbtReturn).filter_by(org_id=ctx.org.id, id=rid).first()
    if r is None:
        raise NotFound("FBT return")
    return r


def calculate(db, ctx, a: core.Access, year: str) -> T.TaxFbtReturn:
    a.require("prepare")
    check_year(year)
    r = db.query(T.TaxFbtReturn).filter_by(org_id=ctx.org.id, fbt_year=year).first()
    if r is not None and r.status not in ("draft", "prepared", "void"):
        raise Conflict(f"The {year} FBT return is {r.status} and cannot be recalculated.", "locked")
    s = summary(db, ctx, year)
    if r is None:
        r = T.TaxFbtReturn(org_id=ctx.org.id, fbt_year=year, status="draft", created_by=ctx.user_id)
        db.add(r)
    if r.status == "void":
        r.status, r.void_reason = "draft", None
    r.summary, r.fbt_payable, r.calc_hash = core.plain(s), D(s["fbt_payable"]), _hash(dict(s, findings=None))
    if r.status == "prepared":
        r.status = "draft"
    ob = db.query(T.TaxObligation).filter_by(org_id=ctx.org.id, kind="fbt_return", source_key=f"fbt_return:{year}").first()
    if ob:
        r.obligation_id, r.due_date, ob.linked_type, ob.linked_id = ob.id, ob.due_date, "fbt_return", r.id
    db.flush()
    core.record(db, ctx, "fbt.calculate", "tax_fbt_return", r.id, f"FBT return {year}: FBT payable {r.fbt_payable}", None, dict(payable=str(r.fbt_payable)))
    return r


def mark_prepared(db, ctx, a: core.Access, rid: int):
    a.require("prepare")
    r = get_return(db, ctx, rid)
    if r.status != "draft":
        raise Conflict(f"Only a draft can be marked prepared (status is {r.status}).")
    r.status, r.prepared_by, r.prepared_at = "prepared", ctx.user_id, datetime.utcnow()
    core.record(db, ctx, "fbt.prepared", "tax_fbt_return", r.id, f"FBT return {r.fbt_year} prepared", None, None)
    O.link_status(db, ctx, r.obligation_id, "prepared")
    return r


def approve(db, ctx, a: core.Access, rid: int, note=""):
    a.require("approve")
    r = get_return(db, ctx, rid)
    if r.status != "prepared":
        raise Conflict(f"Only a prepared return can be approved (status is {r.status}).")
    if _hash(dict(summary(db, ctx, r.fbt_year), findings=None)) != r.calc_hash:
        raise Conflict("Benefits or FBT rates changed after the return was calculated. Return it to draft and recalculate.", "stale")
    selfa = core.check_separation(db, ctx, r.prepared_by, "FBT return", P.get(db, ctx), "fbt.approve", "tax_fbt_return", r.id)
    r.status, r.approved_by, r.approved_at, r.approval_note = "approved", ctx.user_id, datetime.utcnow(), (note or "")[:500] or None
    core.record(db, ctx, "fbt.approved" + (".self" if selfa else ""), "tax_fbt_return", r.id, f"FBT return {r.fbt_year} approved", None, dict(payable=str(r.fbt_payable)))
    return r


def return_to_draft(db, ctx, a: core.Access, rid: int, note=""):
    a.require("prepare")
    r = get_return(db, ctx, rid)
    if r.status not in ("prepared", "approved"):
        raise Conflict("Only a prepared or approved return can be returned to draft.")
    if r.status == "approved":
        a.require("approve")
    r.status, r.approved_by = "draft", None
    core.supersede_signoffs(db, ctx, "fbt_return", r.id, "document returned to draft")
    core.record(db, ctx, "fbt.returned", "tax_fbt_return", r.id, f"FBT return {r.fbt_year} returned to draft. {note[:200]}", None, None)
    return r


def record_lodged(db, ctx, a: core.Access, rid: int, body: dict):
    a.require("lodge")
    r = get_return(db, ctx, rid)
    if r.status != "approved":
        raise Conflict("Only an approved return can be recorded as lodged.")
    core.check_declaration(db, ctx, "fbt_return", r.id, r.calc_hash)
    ref = (body.get("reference") or "").strip()
    if not ref:
        raise TaxError("Enter the ATO receipt / reference number")
    on = core.parse_date(body.get("lodged_on"), "lodged_on") or date.today()
    if on < R.fbt_bounds(r.fbt_year)[1]:
        raise TaxError("An FBT return cannot be lodged before the FBT year ends (31 March)")
    r.status, r.lodged_on, r.lodged_by, r.lodgement_reference, r.lodgement_method = "lodged", on, ctx.user_id, ref[:80], body.get("method") or "ato_online_services"
    core.record(db, ctx, "fbt.lodged", "tax_fbt_return", r.id, f"FBT return {r.fbt_year} recorded as lodged on {on}, ref {ref[:40]}", None, None)
    O.link_status(db, ctx, r.obligation_id, "lodged", lodged_on=on, reference=ref[:80], amount=r.fbt_payable)
    return r


def record_paid(db, ctx, a: core.Access, rid: int, paid_on=None):
    a.require("lodge")
    r = get_return(db, ctx, rid)
    if r.status != "lodged":
        raise Conflict("Only a lodged return can be recorded as paid.")
    r.status, r.paid_on = "paid", core.parse_date(paid_on, "paid_on") or date.today()
    core.record(db, ctx, "fbt.paid", "tax_fbt_return", r.id, f"FBT {r.fbt_year} payment recorded", None, None)
    O.link_status(db, ctx, r.obligation_id, "paid", paid_on=r.paid_on)
    return r
