"""BAS / IAS preparation. The ledger (GST report + payroll journals) is the only source of figures; this service arranges them on the activity-statement labels,
cross-checks them (GST account reconciliation, payroll module vs ledger, suspense, lock date), lets a reviewer override a label with a reason, and runs the
workflow draft -> prepared -> approved -> lodged -> paid. AccFino does NOT transmit to the ATO: 'lodged' records that the user lodged through ATO Online services
or their tax agent, with the receipt reference. Approval is refused if the ledger changed after the figures were calculated."""
import hashlib
import json
from datetime import date, datetime
from decimal import Decimal
from typing import Optional

import accfino.modules.accounting.public as accounting
import accfino.modules.payroll.public as payroll
from accfino.modules.taxation.engine import bas as E
from accfino.modules.taxation.engine.money import D, q2
from accfino.modules.taxation.models import tax as T
from accfino.modules.taxation.services import core, obligations as O, profile as P
from accfino.modules.taxation.services.core import Conflict, NotFound, TaxError

EDITABLE = ("draft", "prepared")


def get(db, ctx, sid: int) -> T.TaxBasStatement:
    s = db.query(T.TaxBasStatement).filter_by(org_id=ctx.org.id, id=sid).first()
    if s is None:
        raise NotFound("Activity statement")
    return s


def to_dict(s: T.TaxBasStatement, full: bool = True) -> dict:
    d = dict(id=s.id, kind=s.kind, fy=s.fy, period_start=s.period_start.isoformat(), period_end=s.period_end.isoformat(), frequency=s.frequency, basis=s.basis, status=s.status,
             amount_payable=core.plain(s.amount_payable), due_date=core.plain(s.due_date), prepared_at=core.plain(s.prepared_at), approved_at=core.plain(s.approved_at), approved_by=s.approved_by,
             prepared_by=s.prepared_by, lodged_on=core.plain(s.lodged_on), lodgement_method=s.lodgement_method, lodgement_reference=s.lodgement_reference, paid_on=core.plain(s.paid_on),
             version=s.version, obligation_id=s.obligation_id, void_reason=s.void_reason, has_errors=any(f["severity"] == "error" for f in (s.findings or [])), calculated=bool(s.labels))
    if full:
        d.update(labels=s.labels or {}, overrides=s.overrides or {}, final=s.final or {}, label_order=E.ordered_labels(s.final or {}), findings=s.findings or [], snapshot=s.snapshot or {}, approval_note=s.approval_note,
                 label_names=None, lodgement_figures=E.lodgement_figures(s.final) if s.final else {})
    return d


def listing(db, ctx, fy: str = "", status: str = ""):
    q = db.query(T.TaxBasStatement).filter(T.TaxBasStatement.org_id == ctx.org.id)
    if fy:
        q = q.filter(T.TaxBasStatement.fy == fy)
    if status:
        q = q.filter(T.TaxBasStatement.status == status)
    return [to_dict(s, full=False) for s in q.order_by(T.TaxBasStatement.period_start.desc(), T.TaxBasStatement.id.desc())]


def create(db, ctx, a: core.Access, body: dict) -> T.TaxBasStatement:
    a.require("prepare")
    start, end = core.parse_date(body.get("period_start"), "period_start"), core.parse_date(body.get("period_end"), "period_end")
    if not start or not end or end < start:
        raise TaxError("period_start and period_end are required and the end cannot be before the start")
    if (end - start).days > 366:
        raise TaxError("An activity statement period cannot exceed 12 months")
    p = P.get(db, ctx)
    kind = body.get("kind") or ("bas" if p.gst_registered else "ias")
    if kind not in ("bas", "ias"):
        raise TaxError("kind must be bas or ias")
    if kind == "bas" and not p.gst_registered:
        raise TaxError("The organisation is not registered for GST in its tax profile: prepare an IAS, or update the profile.")
    for o in db.query(T.TaxBasStatement).filter(T.TaxBasStatement.org_id == ctx.org.id, T.TaxBasStatement.status != "void"):
        if o.period_start <= end and start <= o.period_end:
            raise Conflict(f"This period overlaps the {o.kind.upper()} for {o.period_start} to {o.period_end} (status {o.status}). Void it first if it was prepared in error.", "overlap")
    fy = core.check_fy(ctx, body.get("fy") or __import__("accfino.modules.taxation.engine.rules", fromlist=["x"]).fy_of(start, ctx.org.fy_end_month or 6))
    s = T.TaxBasStatement(org_id=ctx.org.id, kind=kind, fy=fy, period_start=start, period_end=end, frequency=p.bas_frequency, basis=p.gst_basis, status="draft", created_by=ctx.user_id)
    db.add(s)
    db.flush()
    ob = O.link_obligation(db, ctx, ("bas", "ias"), start, end, "bas_statement", s.id)
    if ob:
        s.obligation_id = ob
        s.due_date = db.get(T.TaxObligation, ob).due_date
    db.flush()
    core.record(db, ctx, "bas.create", "tax_bas_statement", s.id, f"{kind.upper()} {start} to {end} created", None, to_dict(s, False))
    return s


def _inputs(db, ctx, s: T.TaxBasStatement, p: T.TaxProfile):
    org = ctx.org
    gst = accounting.gst_summary(db, org, s.period_start, s.period_end, p.gst_basis) if s.kind == "bas" else None
    ledger_payg = accounting.payg_summary(db, org, s.period_start, s.period_end)
    run = payroll.withholding_for_period(db, org.id, s.period_start, s.period_end)
    return gst, ledger_payg, run


def calculate(db, ctx, a: core.Access, sid: int) -> T.TaxBasStatement:
    a.require("prepare")
    s = get(db, ctx, sid)
    if s.status not in EDITABLE:
        raise Conflict(f"A statement that is {s.status} cannot be recalculated.", "locked")
    p = P.get(db, ctx)
    rs = core.rules_for_date(db, ctx, s.period_start)
    gst, lp, run = _inputs(db, ctx, s, p)
    payg = None
    if p.payg_withholding or lp.get("has_payroll") or run["runs"]:
        payg = dict(W1=lp["bas"]["W1"], W2=lp["bas"]["W2"], has_payroll=True)
    instalment_income = None
    if gst is not None:
        instalment_income = max(D(gst["fields"].get("G1")) - D(gst["fields"].get("1A")), Decimal(0))
    labels = E.build_labels(rs, kind=s.kind, gst=gst, payg=payg, profile=dict(payg_instalment_method=p.payg_instalment_method, payg_instalment_amount=p.payg_instalment_amount,
                            payg_instalment_rate=p.payg_instalment_rate, fbt_registered=p.fbt_registered, fbt_instalment_amount=p.fbt_instalment_amount), instalment_income=instalment_income)
    # keep any overrides the reviewer already made, re-derive totals
    final = E.apply_overrides(labels, s.overrides or {})
    findings = _findings(db, ctx, s, p, rs, gst, lp, run, final)
    snap = dict(gst_basis=p.gst_basis, rule_set=rs.id, ledger_gst_check=(gst or {}).get("ledger_check"), ledger_payg_check=lp.get("check"), payroll_runs=run, calculated_at=datetime.utcnow().isoformat(timespec="seconds"))
    s.labels, s.final, s.findings, s.snapshot = core.plain(labels), core.plain(final), findings, core.plain(snap)
    s.amount_payable = D(final["9"]["value"])
    s.calc_hash = _hash(db, ctx, s, p)
    if s.status == "prepared":
        s.status = "draft"                                           # figures changed under a reviewer: must be prepared again
    s.version += 1
    db.flush()
    core.record(db, ctx, "bas.calculate", "tax_bas_statement", s.id, f"{s.kind.upper()} {s.period_start} to {s.period_end} calculated; label 9 = {s.amount_payable}", None,
                dict(label_9=str(s.amount_payable), findings=len(findings), hash=s.calc_hash[:12]))
    return s


def _hash(db, ctx, s, p) -> str:
    """Fingerprint of the ledger inputs for the period. If it differs at approval time the ledger changed after calculation."""
    gst, lp, run = _inputs(db, ctx, s, p)
    body = dict(gst=(gst or {}).get("fields"), by_code=(gst or {}).get("by_tax_code"), w1=lp["bas"]["W1"], w2=lp["bas"]["W2"], run=run, ov=s.overrides or {},
                inst=[str(p.payg_instalment_method), str(p.payg_instalment_amount), str(p.payg_instalment_rate), str(p.fbt_instalment_amount)])
    return hashlib.sha256(json.dumps(body, sort_keys=True, default=str).encode()).hexdigest()


def _findings(db, ctx, s, p, rs, gst, lp, run, final) -> list:
    out = []
    add = lambda key, sev, msg, **kw: out.append(dict(key=key, severity=sev, message=msg, **kw))
    if gst is not None:
        lc = gst.get("ledger_check", {})
        if p.gst_basis == "accrual" and lc.get("reconciled") is False:
            add("gst_not_reconciled", "error", f"The GST account moved by {lc['gst_account_movement']} but labels 1A less 1B total {q2(D(gst['gst_on_sales_1A']) - D(gst['gst_on_purchases_1B']))} "
                f"(difference {lc['difference']}). GST was posted without a tax code (for example a manual journal). Fix the journal or explain the difference in a workpaper.", area="ledger")
        elif p.gst_basis == "cash":
            add("cash_basis", "info", "Cash basis: GST is recognised when documents are settled, so the GST account balance cannot be reconciled directly to the labels.")
    susp = accounting.system_account_balance(db, ctx.org, "suspense", s.period_end)
    if susp not in (None, "0.00") and D(susp) != 0:
        add("suspense_balance", "warn", f"The Suspense account holds {susp} at {s.period_end}. Unclassified transactions may carry GST that is not yet on the BAS.", area="banking")
    pm, lw = D(run["withheld_total"]), D(lp["bas"]["W2"])
    if lp.get("has_payroll") or run["runs"]:
        if pm != lw:
            add("payg_mismatch", "error", f"PAYG withheld per finalised pay runs ({pm}) differs from PAYG posted to the ledger ({lw}). Check payroll journals for the period before lodging W2.", area="payroll")
        if not lp.get("check", {}).get("reconciled", True) and False:
            pass
    if rs.provisional:
        add("provisional_rules", "warn", f"Rule set {rs.id} is PROVISIONAL (figures carried forward before publication). GST labels come from your ledger, but PAYG instalment and due-date settings may change.", area="rules")
    org = ctx.org
    if org.lock_date is None or org.lock_date < s.period_end:
        add("period_not_locked", "info", "The books are not locked to the end of this period. Consider setting the lock date after approval so figures cannot change.", area="ledger")
    for f in E.sanity_checks(final, rs):
        out.append(dict(f, area="validation"))
    if s.kind == "bas" and p.payg_withholding and "W1" not in final:
        add("payg_registered_no_wages", "warn", "The profile says PAYG withholding is registered but no wages were found in the period.", area="payroll")
    if (p.payg_instalment_method or "none") in ("amount", "rate") and "5A" in final and D(final["5A"]["value"]) == 0:
        add("instalment_missing", "warn", "A PAYG instalment method is selected but the instalment amount is nil. Enter the ATO-notified amount or rate in the tax profile.", area="profile")
    if s.kind == "bas" and p.gst_registered and gst and D(gst["fields"].get("G1")) == 0 and D(gst["fields"].get("G11")) == 0 and D(gst["fields"].get("G10")) == 0:
        add("nil_return", "info", "No GST transactions in the period: this is a nil BAS. Lodge it anyway if the ATO requires a statement.")
    if D(final["9"]["value"]) < 0:
        add("refund", "info", "This statement is in refund: the ATO may hold it for review.")
    return out


def override(db, ctx, a: core.Access, sid: int, label: str, value, reason: str) -> T.TaxBasStatement:
    a.require("prepare")
    s = get(db, ctx, sid)
    if s.status not in EDITABLE:
        raise Conflict(f"A statement that is {s.status} cannot be changed.", "locked")
    if not s.labels:
        raise TaxError("Calculate the statement first")
    if label in ("8A", "8B", "9", "W5", "4"):
        raise TaxError(f"{label} is derived from other labels: override the labels it is made of")
    if not reason or len(reason.strip()) < 5:
        raise TaxError("A reason (at least 5 characters) is required for every override")
    try:
        v = core.money_in(value, "value", allow_negative=True, required=True)
    except TaxError:
        raise
    ov = dict(s.overrides or {})
    old = (s.final or {}).get(label, {}).get("value")
    ov[label] = dict(value=str(v), reason=reason.strip(), by=ctx.user_id, at=datetime.utcnow().isoformat(timespec="seconds"))
    s.overrides = ov
    rs = core.rules_for_date(db, ctx, s.period_start)
    final = E.apply_overrides(s.labels, ov)
    s.final = core.plain(final)
    s.amount_payable = D(final["9"]["value"])
    s.findings = [f for f in (s.findings or []) if f.get("area") != "validation"] + [dict(f, area="validation") for f in E.sanity_checks(final, rs)] + \
        [dict(key=f"override_{label}", severity="warn", message=f"Label {label} was overridden ({old} -> {v}): '{reason.strip()[:120]}'. Overrides need a workpaper.", area="override")]
    s.findings = [f for i, f in enumerate(s.findings) if not (f["key"].startswith("override_") and any(g["key"] == f["key"] for g in s.findings[i + 1:]))]
    s.calc_hash = _hash(db, ctx, s, P.get(db, ctx))
    if s.status == "prepared":
        s.status = "draft"
    s.version += 1
    db.flush()
    core.record(db, ctx, "bas.override", "tax_bas_statement", s.id, f"Label {label} overridden {old} -> {v}: {reason.strip()[:150]}", dict(value=old), dict(value=str(v)))
    return s


def remove_override(db, ctx, a: core.Access, sid: int, label: str) -> T.TaxBasStatement:
    a.require("prepare")
    s = get(db, ctx, sid)
    if s.status not in EDITABLE:
        raise Conflict(f"A statement that is {s.status} cannot be changed.", "locked")
    ov = dict(s.overrides or {})
    if label not in ov:
        raise NotFound("Override")
    del ov[label]
    s.overrides = ov
    db.flush()
    core.record(db, ctx, "bas.override_removed", "tax_bas_statement", s.id, f"Override of {label} removed", None, None)
    return calculate(db, ctx, a, sid)


def mark_prepared(db, ctx, a: core.Access, sid: int) -> T.TaxBasStatement:
    a.require("prepare")
    s = get(db, ctx, sid)
    if s.status != "draft":
        raise Conflict(f"Only a draft can be marked prepared (status is {s.status}).")
    if not s.labels:
        raise TaxError("Calculate the statement first")
    errs = [f for f in (s.findings or []) if f["severity"] == "error"]
    if errs:
        raise Conflict("Resolve the errors first: " + "; ".join(f["message"][:90] for f in errs[:3]), "has_errors")
    s.status, s.prepared_by, s.prepared_at = "prepared", ctx.user_id, datetime.utcnow()
    db.flush()
    core.record(db, ctx, "bas.prepared", "tax_bas_statement", s.id, f"{s.kind.upper()} {s.period_start} to {s.period_end} marked prepared", None, dict(label_9=str(s.amount_payable)))
    O.link_status(db, ctx, s.obligation_id, "prepared")
    return s


def return_to_draft(db, ctx, a: core.Access, sid: int, note: str = "") -> T.TaxBasStatement:
    a.require("prepare")
    s = get(db, ctx, sid)
    if s.status not in ("prepared", "approved"):
        raise Conflict(f"Only a prepared or approved statement can be returned to draft (status is {s.status}).")
    if s.status == "approved":
        a.require("approve")
    s.status, s.approved_by, s.approved_at = "draft", None, None
    core.supersede_signoffs(db, ctx, "bas_statement", s.id, "document returned to draft")
    db.flush()
    core.record(db, ctx, "bas.returned", "tax_bas_statement", s.id, f"Returned to draft. {note[:200]}", None, None)
    O.link_status(db, ctx, s.obligation_id, "in_progress")
    return s


def approve(db, ctx, a: core.Access, sid: int, note: str = "") -> T.TaxBasStatement:
    a.require("approve")
    s = get(db, ctx, sid)
    if s.status != "prepared":
        raise Conflict(f"Only a prepared statement can be approved (status is {s.status}).")
    p = P.get(db, ctx)
    if _hash(db, ctx, s, p) != s.calc_hash:
        raise Conflict("The ledger or payroll changed after this statement was calculated. Return it to draft and recalculate before approving.", "stale")
    errs = [f for f in (s.findings or []) if f["severity"] == "error"]
    if errs:
        raise Conflict("Errors remain: " + "; ".join(f["message"][:90] for f in errs[:3]), "has_errors")
    selfa = core.check_separation(db, ctx, s.prepared_by, "activity statement", p, "bas.approve", "tax_bas_statement", s.id)
    s.status, s.approved_by, s.approved_at, s.approval_note = "approved", ctx.user_id, datetime.utcnow(), (note or "")[:500] or None
    db.flush()
    core.record(db, ctx, "bas.approved" + (".self" if selfa else ""), "tax_bas_statement", s.id, f"{s.kind.upper()} approved{' (SELF-APPROVAL)' if selfa else ''}; label 9 = {s.amount_payable}", None,
                dict(label_9=str(s.amount_payable), note=note[:200]))
    return s


def record_lodged(db, ctx, a: core.Access, sid: int, body: dict) -> T.TaxBasStatement:
    a.require("lodge")
    s = get(db, ctx, sid)
    if s.status != "approved":
        raise Conflict("Only an approved statement can be recorded as lodged.")
    core.check_declaration(db, ctx, "bas_statement", s.id, s.calc_hash)
    ref = (body.get("reference") or "").strip()
    if not ref:
        raise TaxError("Enter the ATO receipt / reference number you received when lodging")
    method = body.get("method") or "ato_online_services"
    if method not in ("ato_online_services", "tax_agent", "gateway", "other"):
        raise TaxError("method must be ato_online_services, tax_agent, gateway or other")
    on = core.parse_date(body.get("lodged_on"), "lodged_on") or date.today()
    if on < s.period_end:
        raise TaxError("A statement cannot be lodged before its period ends")
    s.status, s.lodged_on, s.lodged_by, s.lodgement_method, s.lodgement_reference = "lodged", on, ctx.user_id, method, ref[:80]
    db.flush()
    core.record(db, ctx, "bas.lodged", "tax_bas_statement", s.id, f"Recorded as lodged on {on} via {method}, ref {ref[:40]}", None, dict(label_9=str(s.amount_payable)))
    O.link_status(db, ctx, s.obligation_id, "lodged", lodged_on=on, reference=ref[:80], amount=s.amount_payable)
    return s


def record_paid(db, ctx, a: core.Access, sid: int, body: dict) -> T.TaxBasStatement:
    a.require("lodge")
    s = get(db, ctx, sid)
    if s.status != "lodged":
        raise Conflict("Only a lodged statement can be recorded as paid.")
    on = core.parse_date(body.get("paid_on"), "paid_on") or date.today()
    if on < s.lodged_on:
        raise TaxError("Payment cannot be dated before lodgement")
    s.status, s.paid_on = "paid", on
    db.flush()
    core.record(db, ctx, "bas.paid", "tax_bas_statement", s.id, f"Payment of label 9 ({s.amount_payable}) recorded on {on}. Post the bank payment in Accounting (BAS payment).", None, None)
    O.link_status(db, ctx, s.obligation_id, "paid", paid_on=on)
    return s


def void(db, ctx, a: core.Access, sid: int, reason: str) -> T.TaxBasStatement:
    a.require("prepare")
    s = get(db, ctx, sid)
    if s.status in ("lodged", "paid"):
        raise Conflict("A lodged statement cannot be voided here: lodge an amendment with the ATO and record it as a new statement.", "lodged")
    if not reason or len(reason.strip()) < 5:
        raise TaxError("A reason is required to void a statement")
    if s.status == "approved":
        a.require("approve")
    s.status, s.void_reason = "void", reason.strip()[:300]
    core.supersede_signoffs(db, ctx, "bas_statement", s.id, "document voided")
    db.flush()
    core.record(db, ctx, "bas.void", "tax_bas_statement", s.id, f"Voided: {reason.strip()[:200]}", None, None)
    O.link_status(db, ctx, s.obligation_id, "upcoming")
    if s.obligation_id:
        ob = db.get(T.TaxObligation, s.obligation_id)
        ob.linked_type = ob.linked_id = None
        s.obligation_id = None
    return s


def label_names(db, ctx, period_start: date) -> dict:
    rs = core.rules_for_date(db, ctx, period_start)
    return {k: v for k, v in (rs.get("bas_labels") or {}).items() if not k.startswith("_")}
