"""Income tax returns (individual / sole trader / company / partnership / trust / SMSF). Taxable income starts from the LEDGER profit for the income year, then applies
book-to-tax adjustments (manual, generated depreciation), other income entered by the user, the net capital gain from the CGT register, and PAYG instalments taken from
lodged BAS/IAS (label 5A). Every number is tagged calculated / source / user-entered / assumption / estimate. Workflow as BAS: draft -> prepared -> approved ->
lodged (user-recorded) -> paid, with amendments creating a new version. AccFino never transmits a return to the ATO."""
import hashlib
import json
from datetime import date, datetime
from decimal import Decimal
from typing import Optional

import accfino.modules.accounting.public as accounting
from accfino.modules.taxation.engine import income_tax as E, rules as R
from accfino.modules.taxation.engine.money import ZERO, D, q2
from accfino.modules.taxation.models import tax as T
from accfino.modules.taxation.services import cgt as CGT, core, obligations as O, profile as P
from accfino.modules.taxation.services.core import Conflict, NotFound, TaxError

EDITABLE = ("draft", "prepared")
INPUT_KEYS = ("other_income", "labour_income", "work_expenses_itemised", "deductions_other", "franking_credits", "tax_withheld", "help_repayment", "medicare_surcharge", "other_offsets",
              "losses_brought_forward", "net_capital_gain_override", "allocations", "claim_standard_deduction", "passive_income_ratio")
COMMON_ADJUSTMENTS = [
    dict(code="ENTERTAINMENT", direction="add", label="Non-deductible entertainment (meals, recreation)"),
    dict(code="PRIVATE_USE", direction="add", label="Private use of business expenses (car, phone, home)"),
    dict(code="FINES", direction="add", label="Fines and penalties (non-deductible)"),
    dict(code="BOOK_DEPRECIATION", direction="add", label="Book depreciation added back"),
    dict(code="TAX_DEPRECIATION", direction="deduct", label="Tax depreciation / instant asset write-off"),
    dict(code="PROVISIONS", direction="add", label="Provisions and accruals not yet deductible"),
    dict(code="BAD_DEBTS", direction="deduct", label="Bad debts written off (confirm conditions)"),
    dict(code="DONATIONS", direction="deduct", label="Gifts and donations to deductible gift recipients"),
    dict(code="SUPER_PAID", direction="deduct", label="Employer superannuation paid within the year / due date"),
    dict(code="PREPAID", direction="deduct", label="Prepaid expenses deductible (small business concession)"),
    dict(code="NON_ASSESSABLE", direction="deduct", label="Non-assessable income included in the accounts"),
    dict(code="OTHER", direction="add", label="Other adjustment (explain in a workpaper)"),
]


def get(db, ctx, rid: int) -> T.TaxReturn:
    r = db.query(T.TaxReturn).filter_by(org_id=ctx.org.id, id=rid).first()
    if r is None:
        raise NotFound("Income tax return")
    return r


def to_dict(r: T.TaxReturn, full: bool = True) -> dict:
    d = dict(id=r.id, fy=r.fy, entity_type=r.entity_type, version=r.version, status=r.status, taxable_income=core.plain(r.taxable_income), tax_payable=core.plain(r.tax_payable),
             due_date=core.plain(r.due_date), prepared_at=core.plain(r.prepared_at), prepared_by=r.prepared_by, approved_at=core.plain(r.approved_at), approved_by=r.approved_by,
             lodged_on=core.plain(r.lodged_on), lodgement_method=r.lodgement_method, lodgement_reference=r.lodgement_reference, assessed_amount=core.plain(r.assessed_amount),
             assessed_on=core.plain(r.assessed_on), paid_on=core.plain(r.paid_on), obligation_id=r.obligation_id, void_reason=r.void_reason, calculated=bool(r.computation),
             has_errors=any(f["severity"] == "error" for f in (r.findings or [])))
    if full:
        d.update(inputs=r.inputs or {}, accounting=r.accounting or {}, computation=r.computation or {}, findings=r.findings or [], approval_note=r.approval_note)
    return d


def listing(db, ctx, fy: str = ""):
    q = db.query(T.TaxReturn).filter(T.TaxReturn.org_id == ctx.org.id)
    if fy:
        q = q.filter(T.TaxReturn.fy == fy)
    return [to_dict(r, False) for r in q.order_by(T.TaxReturn.fy.desc(), T.TaxReturn.version.desc())]


def create(db, ctx, a: core.Access, fy: str, inputs: Optional[dict] = None) -> T.TaxReturn:
    a.require("prepare")
    core.check_fy(ctx, fy)
    p = P.get(db, ctx)
    live = db.query(T.TaxReturn).filter(T.TaxReturn.org_id == ctx.org.id, T.TaxReturn.fy == fy, T.TaxReturn.entity_type == p.entity_type, T.TaxReturn.status != "void").first()
    if live:
        raise Conflict(f"A {fy} return already exists (version {live.version}, {live.status}). Open it, or void it first. To correct a lodged return use Amend.", "exists")
    ver = (db.query(T.TaxReturn).filter_by(org_id=ctx.org.id, fy=fy, entity_type=p.entity_type).count()) + 1
    r = T.TaxReturn(org_id=ctx.org.id, fy=fy, entity_type=p.entity_type, version=ver, status="draft", inputs=_clean_inputs(inputs or {}), created_by=ctx.user_id)
    db.add(r)
    db.flush()
    ob = db.query(T.TaxObligation).filter_by(org_id=ctx.org.id, kind="income_tax_return", fy=fy).first()
    if ob:
        ob.linked_type, ob.linked_id, r.obligation_id, r.due_date = "tax_return", r.id, ob.id, ob.due_date
        if ob.status == "upcoming":
            ob.status = "in_progress"
    core.record(db, ctx, "return.create", "tax_return", r.id, f"Income tax return {fy} ({p.entity_type}) created", None, dict(version=ver))
    return r


def _clean_inputs(i: dict) -> dict:
    bad = set(i) - set(INPUT_KEYS)
    if bad:
        raise TaxError(f"Unknown input(s): {', '.join(sorted(bad))}")
    out = {}
    for k, v in i.items():
        if k == "allocations":
            if not isinstance(v, list):
                raise TaxError("allocations must be a list")
            out[k] = [dict(name=str(x.get("name", ""))[:120], percent=str(core.money_in(x.get("percent"), "percent", required=True))) for x in v]
        elif k == "claim_standard_deduction":
            out[k] = bool(v)
        else:
            m = core.money_in(v, k, allow_negative=(k == "other_income"))
            out[k] = None if m is None else str(m)
    return out


def set_inputs(db, ctx, a: core.Access, rid: int, inputs: dict) -> T.TaxReturn:
    a.require("prepare")
    r = get(db, ctx, rid)
    if r.status not in EDITABLE:
        raise Conflict(f"A return that is {r.status} cannot be changed.", "locked")
    new = _clean_inputs(inputs)
    before = dict(r.inputs or {})
    r.inputs = {**before, **new}
    if r.status == "prepared":
        r.status = "draft"
    db.flush()
    core.record(db, ctx, "return.inputs", "tax_return", r.id, "Return inputs changed: " + ", ".join(sorted(new)), before, r.inputs)
    return r


# ---- adjustments -----------------------------------------------------------------------------------------------------------------
def adj_dict(x: T.TaxAdjustment) -> dict:
    return dict(id=x.id, fy=x.fy, code=x.code, description=x.description, direction=x.direction, amount=str(x.amount), category=x.category, source=x.source, requires_review=x.requires_review,
                review_note=x.review_note, reviewed=x.reviewed_at is not None, reviewed_by=x.reviewed_by, workpaper_id=x.workpaper_id)


def adjustments(db, ctx, fy: str):
    return [adj_dict(x) for x in db.query(T.TaxAdjustment).filter_by(org_id=ctx.org.id, fy=fy).order_by(T.TaxAdjustment.id)]


def _guard(db, ctx, fy):
    r = db.query(T.TaxReturn).filter(T.TaxReturn.org_id == ctx.org.id, T.TaxReturn.fy == fy, T.TaxReturn.status.in_(("approved", "lodged", "paid"))).first()
    if r:
        raise Conflict(f"The {fy} return is {r.status}: return it to draft or amend it before changing adjustments.", "locked")


def save_adjustment(db, ctx, a: core.Access, fy: str, body: dict, aid: Optional[int] = None) -> T.TaxAdjustment:
    a.require("prepare")
    core.check_fy(ctx, fy)
    _guard(db, ctx, fy)
    direction = body.get("direction")
    if direction not in ("add", "deduct"):
        raise TaxError("direction must be add or deduct")
    amt = core.money_in(body.get("amount"), "amount", required=True)
    desc = (body.get("description") or "").strip()
    if not desc:
        raise TaxError("description is required")
    cat = body.get("category") or "user_entered"
    if cat not in T.ADJ_CATEGORIES:
        raise TaxError(f"category must be one of {', '.join(T.ADJ_CATEGORIES)}")
    if aid:
        x = db.query(T.TaxAdjustment).filter_by(org_id=ctx.org.id, id=aid, fy=fy).first()
        if x is None:
            raise NotFound("Adjustment")
        if x.source != "manual":
            raise TaxError("Generated adjustments are replaced by regenerating them; edit a manual adjustment or add another.", 409, "generated")
    else:
        x = T.TaxAdjustment(org_id=ctx.org.id, fy=fy, source="manual", created_by=ctx.user_id)
    before = adj_dict(x) if aid else None
    x.code, x.description, x.direction, x.amount, x.category = (body.get("code") or "OTHER")[:40], desc[:300], direction, amt, cat
    x.requires_review = bool(body.get("requires_review")) or cat in ("estimate", "assumption")          # invariant: estimates and assumptions are ALWAYS reviewed, whatever the client sent
    x.review_note = (body.get("review_note") or "")[:500] or None
    x.reviewed_by = x.reviewed_at = None
    x.workpaper_id = body.get("workpaper_id") or None
    if not aid:
        db.add(x)
    db.flush()
    core.record(db, ctx, "adjustment.save", "tax_adjustment", x.id, f"Adjustment '{desc[:80]}' {direction} {amt}", before, adj_dict(x))
    return x


def delete_adjustment(db, ctx, a: core.Access, fy: str, aid: int):
    a.require("prepare")
    _guard(db, ctx, fy)
    x = db.query(T.TaxAdjustment).filter_by(org_id=ctx.org.id, id=aid, fy=fy).first()
    if x is None:
        raise NotFound("Adjustment")
    core.record(db, ctx, "adjustment.delete", "tax_adjustment", x.id, f"Adjustment '{x.description[:80]}' deleted", adj_dict(x), None)
    db.delete(x)


def review_adjustment(db, ctx, a: core.Access, aid: int, note: str = "") -> T.TaxAdjustment:
    a.require("approve")
    x = db.query(T.TaxAdjustment).filter_by(org_id=ctx.org.id, id=aid).first()
    if x is None:
        raise NotFound("Adjustment")
    x.reviewed_by, x.reviewed_at = ctx.user_id, datetime.utcnow()
    if note:
        x.review_note = note[:500]
    core.record(db, ctx, "adjustment.review", "tax_adjustment", x.id, f"Adjustment '{x.description[:80]}' reviewed", None, None)
    return x


# ---- calculation -----------------------------------------------------------------------------------------------------------------
def _sources(db, ctx, r: T.TaxReturn, p: T.TaxProfile) -> dict:
    start, end = R.fy_bounds(r.fy, ctx.org.fy_end_month or 6)
    pl = accounting.profit_and_loss(db, ctx.org, start, end)
    adds = sum((x.amount for x in db.query(T.TaxAdjustment).filter_by(org_id=ctx.org.id, fy=r.fy, direction="add")), ZERO)
    deds = sum((x.amount for x in db.query(T.TaxAdjustment).filter_by(org_id=ctx.org.id, fy=r.fy, direction="deduct")), ZERO)
    inst = ZERO
    stmts = []
    for s in db.query(T.TaxBasStatement).filter(T.TaxBasStatement.org_id == ctx.org.id, T.TaxBasStatement.fy == r.fy, T.TaxBasStatement.status.in_(("lodged", "paid"))):
        v = D(((s.final or {}).get("5A") or {}).get("value"))
        inst += v
        stmts.append(dict(id=s.id, period=f"{s.period_start} to {s.period_end}", instalment=str(v)))
    pending = db.query(T.TaxBasStatement).filter(T.TaxBasStatement.org_id == ctx.org.id, T.TaxBasStatement.fy == r.fy, T.TaxBasStatement.status.in_(("draft", "prepared", "approved"))).count()
    ncg = CGT.compute(db, ctx, r.fy)
    return dict(pl=pl, adds=adds, deds=deds, instalments=inst, statements=stmts, pending_statements=pending, ncg=ncg)


def _hash(src: dict, inputs: dict, p: T.TaxProfile) -> str:
    body = dict(np=src["pl"]["net_profit"], rev=src["pl"]["revenue_total"], adds=str(src["adds"]), deds=str(src["deds"]), inst=str(src["instalments"]), ncg=src["ncg"]["net_capital_gain"],
                lc=src["ncg"]["losses_carried_forward"], inputs=inputs, turnover=str(p.aggregated_turnover), res=p.residency, pir=str(p.passive_income_ratio))
    return hashlib.sha256(json.dumps(body, sort_keys=True, default=str).encode()).hexdigest()


def calculate(db, ctx, a: core.Access, rid: int) -> T.TaxReturn:
    a.require("prepare")
    r = get(db, ctx, rid)
    if r.status not in EDITABLE:
        raise Conflict(f"A return that is {r.status} cannot be recalculated.", "locked")
    p = P.get(db, ctx)
    rs = core.rules_for_fy(db, ctx, r.fy)
    src = _sources(db, ctx, r, p)
    i = dict(r.inputs or {})
    net_profit, other = D(src["pl"]["net_profit"]), D(i.get("other_income"))
    ncg = D(i["net_capital_gain_override"]) if i.get("net_capital_gain_override") not in (None, "") else D(src["ncg"]["net_capital_gain"])
    eng_in = dict(assessable_income=net_profit + other + src["adds"], deductions_other=src["deds"] + D(i.get("deductions_other")), net_capital_gain=ncg, franking_credits=i.get("franking_credits"),
                  tax_withheld=i.get("tax_withheld"), instalments_paid=src["instalments"], help_repayment=i.get("help_repayment"), medicare_surcharge=i.get("medicare_surcharge"),
                  other_offsets=i.get("other_offsets"), losses_brought_forward=i.get("losses_brought_forward"), resident=(p.residency == "resident"), aggregated_turnover=p.aggregated_turnover,
                  labour_income=i.get("labour_income"), work_expenses_itemised=i.get("work_expenses_itemised"), business_net_income=max(net_profit, ZERO),
                  passive_income_ratio=i.get("passive_income_ratio") if i.get("passive_income_ratio") is not None else (p.passive_income_ratio or 0),
                  claim_standard_deduction=i.get("claim_standard_deduction", True), allocations=i.get("allocations") or [])
    try:
        comp = E.compute_return(rs, r.fy, r.entity_type, eng_in)
    except (ValueError, R.RulesError) as e:
        raise TaxError(str(e))
    # make the ledger starting point visible as the first working step
    comp["steps"].insert(0, E.step("ledger_profit", "Accounting net profit from the ledger (income year)", net_profit, "source", f"Revenue {src['pl']['revenue_total']} less expenses {src['pl']['expense_total']}"))
    if other:
        comp["steps"].insert(1, E.step("other_income", "Other income entered (salary, interest, dividends, rent)", other, "input"))
    if src["adds"] or src["deds"]:
        comp["steps"].insert(2, E.step("book_tax", "Book-to-tax adjustments: add " + str(q2(src["adds"])) + ", deduct " + str(q2(src["deds"])), src["adds"] - src["deds"], "calculated", "See the adjustments register"))
    taxable_raw = eng_in["assessable_income"] + eng_in["net_capital_gain"] + D(eng_in["franking_credits"]) - eng_in["deductions_other"]
    loss_generated = max(-taxable_raw, ZERO) if r.entity_type in ("individual", "sole_trader", "company", "smsf") else ZERO
    comp["tax_loss_generated"] = str(q2(loss_generated))
    findings = _findings(db, ctx, r, p, rs, src, comp, loss_generated)
    r.accounting = core.plain(dict(net_profit=src["pl"]["net_profit"], revenue_total=src["pl"]["revenue_total"], expense_total=src["pl"]["expense_total"], instalment_statements=src["statements"],
                                   adjustments_add=str(src["adds"]), adjustments_deduct=str(src["deds"]), net_capital_gain=src["ncg"]["net_capital_gain"], cgt=src["ncg"]))
    r.computation, r.findings = core.plain(comp), findings
    r.taxable_income, r.tax_payable = D(comp["taxable_income"]), D(comp["balance"])
    r.calc_hash = _hash(src, i, p)
    if r.status == "prepared":
        r.status = "draft"
    r.version = r.version
    db.flush()
    core.record(db, ctx, "return.calculate", "tax_return", r.id, f"Return {r.fy} calculated: taxable income {r.taxable_income}, balance {r.tax_payable}", None, dict(taxable=str(r.taxable_income), balance=str(r.tax_payable), hash=r.calc_hash[:12]))
    return r


def _findings(db, ctx, r, p, rs, src, comp, loss) -> list:
    out = []
    add = lambda key, sev, msg, area="return": out.append(dict(key=key, severity=sev, message=msg, area=area))
    for w in comp.get("warnings", []):
        add(w["key"], "review" if w["kind"] == "review" else "warn", w["note"] or w["label"], "engine")
    if src["pending_statements"]:
        add("bas_pending", "warn", f"{src['pending_statements']} activity statement(s) for {r.fy} are not lodged yet, so PAYG instalments may be incomplete.", "bas")
    if D(src["pl"]["revenue_total"]) == 0 and D(src["pl"]["expense_total"]) == 0 and r.entity_type != "individual":
        add("no_ledger_activity", "warn", "The ledger has no income or expenses in this income year. Is the year fully posted?", "ledger")
    if loss:
        add("tax_loss", "warn", f"A tax loss of {q2(loss)} arises. Record it in the loss register for future years; loss recoupment tests are not assessed.", "return")
    unrev = db.query(T.TaxAdjustment).filter_by(org_id=ctx.org.id, fy=r.fy, requires_review=True, reviewed_at=None).count()
    if unrev:
        add("adjustments_unreviewed", "warn", f"{unrev} adjustment(s) marked 'requires review' have not been reviewed. Approval is blocked until a reviewer signs them off.", "adjustments")
    org = ctx.org
    if org.lock_date is None or org.lock_date < R.fy_bounds(r.fy, org.fy_end_month or 6)[1]:
        add("year_not_locked", "info", "The books are not locked to the end of the income year. Lock the period after approval so the return can be reproduced.", "ledger")
    if p.entity_type in ("company", "smsf") and p.aggregated_turnover is None:
        add("turnover_missing", "warn", "Aggregated turnover is not in the tax profile: base-rate-entity status could not be tested.", "profile")
    if rs.provisional:
        add("provisional_rules", "warn", f"Rule set {rs.id} is PROVISIONAL: its figures were carried forward before the ATO published them, so every amount here is an estimate. Confirm with your tax agent.", "rules")
    if src["ncg"].get("post_reform_events"):
        ov = (r.inputs or {}).get("net_capital_gain_override")
        if ov in (None, ""):
            add("cgt_new_regime", "error", f"{src['ncg']['post_reform_events']} CGT event(s) fall on or after 1 July 2027, when indexation and the 30% minimum tax replace the 50% discount. AccFino does not calculate that regime: enter the net capital gain computed under it (yourself or through your tax agent) in the return inputs, or exclude the event.", "cgt")
        else:
            add("cgt_new_regime_entered", "review", f"The net capital gain ({ov}) for CGT events on or after 1 July 2027 was entered by you, not calculated by AccFino. It must be supported by a workpaper and reviewed by a tax agent.", "cgt")
    if src["ncg"]["events"] and src["ncg"]["review"]:
        add("cgt_review", "review", "CGT events need review: " + "; ".join(src["ncg"]["review"][:2]), "cgt")
    if comp.get("undistributed") not in (None, "0.00"):
        add("undistributed", "review", f"Undistributed trust income {comp['undistributed']}: tax is generally payable by the trustee at the top rate.", "return")
    add("professional_review", "info", "AccFino prepares figures for review. Items marked 'review' (loss tests, trust distributions, Medicare levy thresholds, concessions) need a registered tax agent before lodgement.", "return")
    return out


# ---- workflow ----------------------------------------------------------------------------------------------------------------------
def mark_prepared(db, ctx, a: core.Access, rid: int) -> T.TaxReturn:
    a.require("prepare")
    r = get(db, ctx, rid)
    if r.status != "draft":
        raise Conflict(f"Only a draft can be marked prepared (status is {r.status}).")
    if not r.computation:
        raise TaxError("Calculate the return first")
    errs = [f for f in r.findings if f["severity"] == "error"]
    if errs:
        raise Conflict("Resolve the errors first: " + "; ".join(f["message"][:90] for f in errs[:3]), "has_errors")
    r.status, r.prepared_by, r.prepared_at = "prepared", ctx.user_id, datetime.utcnow()
    db.flush()
    core.record(db, ctx, "return.prepared", "tax_return", r.id, f"Return {r.fy} marked prepared", None, dict(balance=str(r.tax_payable)))
    O.link_status(db, ctx, r.obligation_id, "prepared")
    return r


def return_to_draft(db, ctx, a: core.Access, rid: int, note: str = "") -> T.TaxReturn:
    a.require("prepare")
    r = get(db, ctx, rid)
    if r.status not in ("prepared", "approved"):
        raise Conflict(f"Only a prepared or approved return can be returned to draft (status is {r.status}).")
    if r.status == "approved":
        a.require("approve")
    r.status, r.approved_by, r.approved_at = "draft", None, None
    core.supersede_signoffs(db, ctx, "tax_return", r.id, "document returned to draft")
    core.record(db, ctx, "return.returned", "tax_return", r.id, f"Return {r.fy} returned to draft. {note[:200]}", None, None)
    O.link_status(db, ctx, r.obligation_id, "in_progress")
    return r


def approve(db, ctx, a: core.Access, rid: int, note: str = "") -> T.TaxReturn:
    a.require("approve")
    r = get(db, ctx, rid)
    if r.status != "prepared":
        raise Conflict(f"Only a prepared return can be approved (status is {r.status}).")
    p = P.get(db, ctx)
    if _hash(_sources(db, ctx, r, p), r.inputs or {}, p) != r.calc_hash:
        raise Conflict("The ledger, adjustments, CGT events or instalments changed after this return was calculated. Return it to draft and recalculate.", "stale")
    unrev = db.query(T.TaxAdjustment).filter_by(org_id=ctx.org.id, fy=r.fy, requires_review=True, reviewed_at=None).count()
    if unrev:
        raise Conflict(f"{unrev} adjustment(s) still need review by an approver before the return can be approved.", "unreviewed")
    selfa = core.check_separation(db, ctx, r.prepared_by, "income tax return", p, "return.approve", "tax_return", r.id)
    r.status, r.approved_by, r.approved_at, r.approval_note = "approved", ctx.user_id, datetime.utcnow(), (note or "")[:500] or None
    core.record(db, ctx, "return.approved" + (".self" if selfa else ""), "tax_return", r.id, f"Return {r.fy} approved{' (SELF-APPROVAL)' if selfa else ''}", None, dict(balance=str(r.tax_payable)))
    return r


def record_lodged(db, ctx, a: core.Access, rid: int, body: dict) -> T.TaxReturn:
    a.require("lodge")
    r = get(db, ctx, rid)
    if r.status != "approved":
        raise Conflict("Only an approved return can be recorded as lodged.")
    core.check_declaration(db, ctx, "tax_return", r.id, r.calc_hash)
    ref = (body.get("reference") or "").strip()
    if not ref:
        raise TaxError("Enter the ATO receipt / reference number")
    method = body.get("method") or "ato_online_services"
    if method not in ("ato_online_services", "tax_agent", "gateway", "other"):
        raise TaxError("method must be ato_online_services, tax_agent, gateway or other")
    on = core.parse_date(body.get("lodged_on"), "lodged_on") or date.today()
    if on < R.fy_bounds(r.fy, ctx.org.fy_end_month or 6)[1]:
        raise TaxError("A return cannot be lodged before the income year ends")
    r.status, r.lodged_on, r.lodged_by, r.lodgement_method, r.lodgement_reference = "lodged", on, ctx.user_id, method, ref[:80]
    core.record(db, ctx, "return.lodged", "tax_return", r.id, f"Return {r.fy} recorded as lodged on {on} via {method}, ref {ref[:40]}", None, dict(balance=str(r.tax_payable)))
    O.link_status(db, ctx, r.obligation_id, "lodged", lodged_on=on, reference=ref[:80], amount=r.tax_payable)
    return r


def record_assessment(db, ctx, a: core.Access, rid: int, amount, assessed_on=None) -> T.TaxReturn:
    a.require("lodge")
    r = get(db, ctx, rid)
    if r.status not in ("lodged", "paid"):
        raise Conflict("Record the notice of assessment after lodgement.")
    r.assessed_amount, r.assessed_on = core.money_in(amount, "amount", allow_negative=True, required=True), core.parse_date(assessed_on, "assessed_on") or date.today()
    diff = r.assessed_amount - (r.tax_payable or ZERO)
    core.record(db, ctx, "return.assessed", "tax_return", r.id, f"Notice of assessment recorded: {r.assessed_amount} (AccFino computed {r.tax_payable}; difference {diff})", None, dict(assessed=str(r.assessed_amount), difference=str(diff)))
    return r


def record_paid(db, ctx, a: core.Access, rid: int, paid_on=None) -> T.TaxReturn:
    a.require("lodge")
    r = get(db, ctx, rid)
    if r.status != "lodged":
        raise Conflict("Only a lodged return can be recorded as paid.")
    on = core.parse_date(paid_on, "paid_on") or date.today()
    if on < r.lodged_on:
        raise TaxError("Payment cannot be dated before lodgement")
    r.status, r.paid_on = "paid", on
    core.record(db, ctx, "return.paid", "tax_return", r.id, f"Return {r.fy} payment/refund recorded on {on}", None, None)
    O.link_status(db, ctx, r.obligation_id, "paid", paid_on=on)
    return r


def void(db, ctx, a: core.Access, rid: int, reason: str) -> T.TaxReturn:
    a.require("prepare")
    r = get(db, ctx, rid)
    if r.status in ("lodged", "paid"):
        raise Conflict("A lodged return cannot be voided: amend it instead.", "lodged")
    if not reason or len(reason.strip()) < 5:
        raise TaxError("A reason is required")
    if r.status == "approved":
        a.require("approve")
    r.status, r.void_reason = "void", reason.strip()[:300]
    core.supersede_signoffs(db, ctx, "tax_return", r.id, "document voided")
    if r.obligation_id:
        ob = db.get(T.TaxObligation, r.obligation_id)
        ob.linked_type = ob.linked_id = None
        ob.status = "upcoming"
        r.obligation_id = None
    core.record(db, ctx, "return.void", "tax_return", r.id, f"Return {r.fy} voided: {reason.strip()[:200]}", None, None)
    return r


def amend(db, ctx, a: core.Access, rid: int, reason: str) -> T.TaxReturn:
    """New version of a lodged return (the original stays as the lodged record). Opens as a draft with the same inputs."""
    a.require("prepare")
    old = get(db, ctx, rid)
    if old.status not in ("lodged", "paid"):
        raise Conflict("Only a lodged or paid return is amended; edit a draft directly.")
    if not reason or len(reason.strip()) < 5:
        raise TaxError("A reason for the amendment is required")
    if db.query(T.TaxReturn).filter(T.TaxReturn.org_id == ctx.org.id, T.TaxReturn.fy == old.fy, T.TaxReturn.entity_type == old.entity_type, T.TaxReturn.status.in_(("draft", "prepared", "approved"))).first():
        raise Conflict("An amendment is already open for this year.", "exists")
    n = db.query(T.TaxReturn).filter_by(org_id=ctx.org.id, fy=old.fy, entity_type=old.entity_type).count() + 1
    new = T.TaxReturn(org_id=ctx.org.id, fy=old.fy, entity_type=old.entity_type, version=n, status="draft", inputs=dict(old.inputs or {}), created_by=ctx.user_id)
    db.add(new)
    db.flush()
    core.record(db, ctx, "return.amend", "tax_return", new.id, f"Amendment (version {n}) of the {old.fy} return opened: {reason.strip()[:200]}", dict(from_version=old.version), dict(version=n))
    return new
