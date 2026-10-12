"""Property register: purchase and cost base, rental income and expenses, valuations, loan, yields, capital works and a CGT estimate."""
import re
from collections import defaultdict
from datetime import date
from decimal import Decimal
from typing import Optional

from accfino.modules.investments.engine import property as PR
from accfino.modules.investments.engine.money import ZERO, D, add_months, q2
from accfino.modules.investments.models import inv as M
from accfino.modules.investments.services import core, data, documents_ref, valuations
from accfino.modules.investments.services.core import Access, Conflict, InvError, NotFound

STATES = ("NSW", "VIC", "QLD", "SA", "WA", "TAS", "NT", "ACT")


def p_dict(p: M.InvProperty) -> dict:
    return dict(id=p.id, name=p.name, address=p.address, suburb=p.suburb, state=p.state, postcode=p.postcode, property_type=p.property_type, use=p.use, ownership_pct=str(p.ownership_pct), contract_date=core.plain(p.contract_date),
                settlement_date=core.plain(p.settlement_date), purchase_price=str(p.purchase_price), stamp_duty=str(p.stamp_duty), legal_costs=str(p.legal_costs), other_acq_costs=str(p.other_acq_costs),
                depreciating_assets_value=str(p.depreciating_assets_value), construction_cost=str(p.construction_cost), construction_date=core.plain(p.construction_date), capital_works_rate=str(p.capital_works_rate),
                main_residence_from=core.plain(p.main_residence_from), main_residence_until=core.plain(p.main_residence_until), first_income_date=core.plain(p.first_income_date), value_when_first_income=None if p.value_when_first_income is None else str(p.value_when_first_income),
                sale_contract_date=core.plain(p.sale_contract_date), sale_price=None if p.sale_price is None else str(p.sale_price), selling_costs=str(p.selling_costs), loan_liability_id=p.loan_liability_id, notes=p.notes, active=p.active)


def get(db, ctx, pid) -> M.InvProperty:
    p = db.query(M.InvProperty).filter_by(org_id=ctx.org.id, id=pid).first()
    if p is None:
        raise NotFound("Property")
    return p


def save(db, ctx, a: Access, body: dict, pid: Optional[int] = None) -> M.InvProperty:
    a.require("edit")
    name = (body.get("name") or "").strip()
    if not name:
        raise InvError("name is required")
    ptype, use = body.get("property_type") or "house", body.get("use") or "investment"
    if ptype not in M.PROPERTY_TYPES:
        raise InvError(f"property_type must be one of {', '.join(M.PROPERTY_TYPES)}")
    if use not in M.PROPERTY_USES:
        raise InvError(f"use must be one of {', '.join(M.PROPERTY_USES)}")
    st = (body.get("state") or "").upper() or None
    if st and st not in STATES:
        raise InvError(f"state must be one of {', '.join(STATES)}")
    pc = (body.get("postcode") or "").strip() or None
    if pc and not re.fullmatch(r"\d{4}", pc):
        raise InvError("postcode must be 4 digits")
    own = core.num(body.get("ownership_pct", 100), "ownership_pct", required=True)
    if not (0 < own <= 100):
        raise InvError("ownership_pct must be more than 0 and at most 100")
    f = {k: core.num(body.get(k), k) or ZERO for k in ("purchase_price", "stamp_duty", "legal_costs", "other_acq_costs", "depreciating_assets_value", "construction_cost", "selling_costs")}
    if f["depreciating_assets_value"] > f["purchase_price"]:
        raise InvError("depreciating_assets_value cannot be more than the purchase price")
    rate = core.num(body.get("capital_works_rate", 0.025), "capital_works_rate", places=8)
    if rate not in (D("0.025"), D("0.04")):
        raise InvError("capital_works_rate is 0.025 (2.5%) or 0.04 (4%)")
    dt = {k: core.parse_date(body.get(k), k) for k in ("contract_date", "settlement_date", "construction_date", "main_residence_from", "main_residence_until", "first_income_date", "sale_contract_date")}
    if dt["contract_date"] and dt["settlement_date"] and dt["settlement_date"] < dt["contract_date"]:
        raise InvError("settlement_date cannot be before contract_date")
    if dt["main_residence_from"] and dt["main_residence_until"] and dt["main_residence_until"] < dt["main_residence_from"]:
        raise InvError("main_residence_until cannot be before main_residence_from")
    sale = core.num(body.get("sale_price"), "sale_price")
    if dt["sale_contract_date"]:
        if not sale or sale <= 0:
            raise InvError("sale_price is required with a sale date")
        if dt["contract_date"] and dt["sale_contract_date"] < dt["contract_date"]:
            raise InvError("sale_contract_date cannot be before the purchase contract_date")
        if dt["sale_contract_date"] > date.today():
            raise InvError("The sale contract date cannot be in the future: leave it empty and use the CGT estimator for a planned sale")
    liab = body.get("loan_liability_id") or None
    if liab and not db.query(M.InvLiability).filter_by(org_id=ctx.org.id, id=int(liab)).first():
        raise InvError("loan_liability_id is not one of your liabilities")
    p = get(db, ctx, pid) if pid else M.InvProperty(org_id=ctx.org.id)
    dup = db.query(M.InvProperty).filter(M.InvProperty.org_id == ctx.org.id, M.InvProperty.name == name, M.InvProperty.id != (p.id or 0)).first()
    if dup:
        raise Conflict(f"A property named '{name}' already exists")
    before = p_dict(p) if pid else None
    p.name, p.address, p.suburb, p.state, p.postcode, p.property_type, p.use, p.ownership_pct = name[:120], (body.get("address") or None), (body.get("suburb") or None), st, pc, ptype, use, own
    for k, v in {**f, **dt}.items():
        setattr(p, k, v)
    p.capital_works_rate, p.sale_price, p.loan_liability_id = rate, sale, int(liab) if liab else None
    p.value_when_first_income = core.num(body.get("value_when_first_income"), "value_when_first_income")
    p.notes = (body.get("notes") or None)
    if "active" in body:
        p.active = bool(body["active"])
    if not pid:
        db.add(p)
    db.flush()
    core.record(db, ctx, "property.save", "inv_property", p.id, f"Property '{p.name}' ({p.use})", before, p_dict(p))
    return p


def delete(db, ctx, a: Access, pid: int):
    a.require("delete")
    p = get(db, ctx, pid)
    if db.query(M.InvPropertyEntry.id).filter_by(org_id=ctx.org.id, property_id=pid).first():
        raise Conflict("A property with income, expense or capital entries cannot be deleted: mark it inactive instead")
    core.record(db, ctx, "property.delete", "inv_property", p.id, f"Property '{p.name}' deleted", p_dict(p), None)
    db.query(M.InvValuation).filter_by(org_id=ctx.org.id, owner_type="property", owner_id=pid).delete()
    db.delete(p)
    db.flush()


# ---------------------------------------------------------------------------------------------------------------------- entries
def e_dict(e: M.InvPropertyEntry) -> dict:
    return dict(id=e.id, property_id=e.property_id, entry_date=e.entry_date.isoformat(), kind=e.kind, category=e.category, amount=str(e.amount), description=e.description, reference=e.reference, source=e.source, voided=e.voided,
                fy=core.fy_of(e.entry_date), linked_journal_id=e.linked_journal_id)


def save_entry(db, ctx, a: Access, pid: int, body: dict, eid: Optional[int] = None, source="manual", source_key=None) -> M.InvPropertyEntry:
    a.require("edit")
    p = get(db, ctx, pid)
    kind = body.get("kind")
    if kind not in M.ENTRY_KINDS:
        raise InvError(f"kind must be one of {', '.join(M.ENTRY_KINDS)}")
    d = core.parse_date(body.get("entry_date"), "entry_date")
    if d is None or d > date.today():
        raise InvError("entry_date is required and cannot be in the future")
    if d.year < 1985:
        raise InvError("entry_date is before 1985")
    amt = core.num(body.get("amount"), "amount", required=True)
    if amt <= 0:
        raise InvError("amount must be greater than zero")
    cat = body.get("category") or None
    if kind == "expense":
        if cat not in M.EXPENSE_CATEGORIES:
            raise InvError(f"category must be one of {', '.join(M.EXPENSE_CATEGORIES)} for an expense")
    else:
        cat = None
    if p.sale_contract_date and d > p.sale_contract_date and kind in ("rent_income", "expense", "loan_interest") and d > add_months(p.sale_contract_date, 12):
        raise InvError("This is more than a year after the sale: check the date")
    e = db.query(M.InvPropertyEntry).filter_by(org_id=ctx.org.id, id=eid, property_id=pid).first() if eid else M.InvPropertyEntry(org_id=ctx.org.id, property_id=pid, created_by=ctx.user_id, source=source, source_key=source_key)
    if eid and e is None:
        raise NotFound("Entry")
    if eid and (e.voided or e.linked_journal_id):
        raise Conflict("A voided entry, or one posted to the ledger, cannot be edited")
    before = e_dict(e) if eid else None
    e.entry_date, e.kind, e.category, e.amount, e.description, e.reference = d, kind, cat, amt, (body.get("description") or None), (body.get("reference") or None)
    if not eid:
        db.add(e)
    db.flush()
    core.record(db, ctx, "property.entry.save", "inv_property", pid, f"{kind} {amt} on {d} ({p.name})", before, e_dict(e))
    return e


def void_entry(db, ctx, a: Access, pid: int, eid: int, reason: str):
    a.require("edit")
    e = db.query(M.InvPropertyEntry).filter_by(org_id=ctx.org.id, id=eid, property_id=pid).first()
    if e is None:
        raise NotFound("Entry")
    if not reason or len(reason.strip()) < 5:
        raise InvError("A reason (at least 5 characters) is required")
    e.voided = True
    core.record(db, ctx, "property.entry.void", "inv_property", pid, f"Entry {e.kind} {e.amount} on {e.entry_date} voided: {reason.strip()[:120]}", None, None)
    return e


def entries(db, ctx, pid: int, kind="", fy="", category="", include_voided=False):
    q = db.query(M.InvPropertyEntry).filter_by(org_id=ctx.org.id, property_id=pid)
    if kind:
        q = q.filter(M.InvPropertyEntry.kind == kind)
    if category:
        q = q.filter(M.InvPropertyEntry.category == category)
    if fy:
        lo, hi = core.fy_bounds(fy)
        q = q.filter(M.InvPropertyEntry.entry_date.between(lo, hi))
    if not include_voided:
        q = q.filter(M.InvPropertyEntry.voided.is_(False))
    return [e_dict(e) for e in q.order_by(M.InvPropertyEntry.entry_date.desc(), M.InvPropertyEntry.id.desc())]


def liability_balance(db, ctx, liab_id: Optional[int], as_at: date):
    if not liab_id:
        return None
    v = valuations.latest(db, ctx, "liability", liab_id, as_at)
    return v.value if v else None


def current_value(db, ctx, p: M.InvProperty, as_at: date):
    """(value of the WHOLE property, basis). The latest valuation; otherwise the purchase price, flagged."""
    v = valuations.latest(db, ctx, "property", p.id, as_at)
    if v:
        return v.value, f"valuation {v.as_at}" + (f" ({v.basis})" if v.basis else "")
    return (p.purchase_price, "purchase price (no valuation recorded)") if p.purchase_price else (ZERO, "no value recorded")


def _sums(rows):
    t = defaultdict(lambda: ZERO)
    for e in rows:
        t[e.kind] += e.amount
        if e.kind == "expense":
            t["cat:" + (e.category or "other")] += e.amount
    return t


def detail(db, ctx, pid: int, as_at: Optional[date] = None, sale_price=None, sale_date=None) -> dict:
    as_at = as_at or date.today()
    p = get(db, ctx, pid)
    allrows = [e for e in db.query(M.InvPropertyEntry).filter_by(org_id=ctx.org.id, property_id=pid, voided=False) if e.entry_date <= as_at]
    last12 = [e for e in allrows if e.entry_date > add_months(as_at, -12)]
    value, basis = current_value(db, ctx, p, as_at)
    loan = liability_balance(db, ctx, p.loan_liability_id, as_at) or ZERO
    share = p.ownership_pct / D(100)
    s12 = _sums(last12)
    pur_total = (p.purchase_price - p.depreciating_assets_value) + p.stamp_duty + p.legal_costs + p.other_acq_costs
    start = p.settlement_date or p.contract_date
    years = ((as_at - start).days / 365.25) if start else None
    perf = PR.performance(value, loan, s12["rent_income"], s12["expense"], s12["loan_interest"], pur_total, years)
    sums_all = _sums(allrows)
    cb = PR.cost_base(p_dict_num(p), improvements=sums_all["capital_improvement"], capital_works_claimed=sums_all["capital_works_claimed"], include_selling_costs=True)
    sp = D(sale_price) if sale_price not in (None, "") else p.sale_price
    sd = core.parse_date(sale_date, "sale_date") or p.sale_contract_date
    est = None
    warnings = []
    holder = data.get_settings(db, ctx).holder
    if sp and sd:
        est = PR.cgt_estimate(p_dict_num(p, dates=True), cb, holder, sp, sd)
        est["planned"] = not (p.sale_contract_date and p.sale_price)
    by_fy = {}
    for e in allrows:
        f = by_fy.setdefault(core.fy_of(e.entry_date), defaultdict(lambda: ZERO))
        f[e.kind] += e.amount
        if e.kind == "expense":
            f["cat:" + (e.category or "other")] += e.amount
    sched = []
    for fy in sorted(by_fy, reverse=True):
        f = by_fy[fy]
        lo, hi = core.fy_bounds(fy)
        cw_est = PR.capital_works_deduction(p.construction_cost, p.capital_works_rate, p.construction_date, lo, hi) if p.use != "main_residence" else ZERO
        cw = f["capital_works_claimed"] or cw_est
        ded = f["expense"] + f["loan_interest"] + cw + f["depreciation_claimed"]
        sched.append(dict(fy=fy, rent=q2(f["rent_income"]), expenses=q2(f["expense"]), by_category={k[4:]: q2(v) for k, v in f.items() if k.startswith("cat:")}, loan_interest=q2(f["loan_interest"]), capital_works=q2(cw),
                          capital_works_estimated=not f["capital_works_claimed"] and cw_est > 0, depreciation=q2(f["depreciation_claimed"]), total_deductions=q2(ded), net_rental_result=q2(f["rent_income"] - ded),
                          your_share_net=q2((f["rent_income"] - ded) * share), negatively_geared=(f["rent_income"] - ded) < 0))
    if value == 0:
        warnings.append("No value is recorded for this property: add a valuation")
    elif "no valuation" in basis:
        warnings.append("Valued at the purchase price: add a current valuation (agent appraisal, bank valuation or your own estimate)")
    if p.loan_liability_id and not loan:
        warnings.append("The linked loan has no balance recorded")
    if p.use == "investment" and not p.first_income_date and any(e.kind == "rent_income" for e in allrows):
        warnings.append("Rent has been recorded but 'first rented' is empty: it starts the clock for the 6-year absence rule")
    if p.use == "main_residence" and any(e.kind == "rent_income" for e in allrows):
        warnings.append("A main residence that earns rent loses part of the CGT exemption: check the use and dates")
    return dict(property=p_dict(p), as_at=as_at.isoformat(), value=q2(value), value_basis=basis, your_share_value=q2(value * share), loan_balance=q2(loan), your_share_equity=q2((value - loan) * share), performance=perf, last_12_months=dict(rent=q2(s12["rent_income"]), expenses=q2(s12["expense"]),
                interest=q2(s12["loan_interest"])), cost_base=cb, cgt_estimate=est, schedule=sched, valuations=valuations.history(db, ctx, "property", pid), entries=entries(db, ctx, pid)[:200], documents=documents_ref.count(db, ctx, "property", pid), warnings=warnings, holder=holder)


def p_dict_num(p: M.InvProperty, dates=False) -> dict:
    d = dict(purchase_price=p.purchase_price, depreciating_assets_value=p.depreciating_assets_value, stamp_duty=p.stamp_duty, legal_costs=p.legal_costs, other_acq_costs=p.other_acq_costs, selling_costs=p.selling_costs, ownership_pct=p.ownership_pct)
    if dates:
        d.update(contract_date=p.contract_date, use=p.use, main_residence_from=p.main_residence_from, main_residence_until=p.main_residence_until, first_income_date=p.first_income_date)
    return d


def overview(db, ctx, as_at: Optional[date] = None) -> dict:
    as_at = as_at or date.today()
    rows = []
    for p in db.query(M.InvProperty).filter_by(org_id=ctx.org.id).order_by(M.InvProperty.name):
        if p.sale_contract_date and p.sale_contract_date <= as_at:
            status = "sold"
        else:
            status = "active" if p.active else "inactive"
        d = detail(db, ctx, p.id, as_at)
        rows.append(dict(id=p.id, name=p.name, address=", ".join(x for x in (p.address, p.suburb, p.state) if x), use=p.use, status=status, value=d["value"], your_share_value=d["your_share_value"], loan=d["loan_balance"], your_share_equity=d["your_share_equity"],
                         gross_yield=d["performance"]["gross_yield"], net_yield=d["performance"]["net_yield"], cash_flow=d["performance"]["cash_flow_after_interest"], lvr=d["performance"]["lvr"], warnings=len(d["warnings"])))
    live = [r for r in rows if r["status"] in ("active", "inactive")]
    return dict(rows=rows, total_value=q2(sum((r["your_share_value"] for r in live), ZERO)), total_loans=q2(sum((r["loan"] * 1 for r in live), ZERO)), total_equity=q2(sum((r["your_share_equity"] for r in live), ZERO)))
