"""Compliance dashboard, tax reconciliation, data-health validation, lodgement readiness and report exports. Read-only over everything else."""
import csv
import io
from datetime import date
from typing import Optional

import accfino.modules.accounting.public as accounting
import accfino.modules.payroll.public as payroll
from accfino.modules.taxation.engine import rules as R
from accfino.modules.taxation.engine.money import ZERO, D, q2
from accfino.modules.taxation.models import tax as T
from accfino.modules.taxation.services import assets as AS, bas as B, cgt as CGT, core, div7a as DV, fbt as F, obligations as O, profile as P, returns as RT, workpapers as W

LODGEMENT_NOTE = ("AccFino prepares, checks and records. It does not transmit activity statements, returns or FBT returns to the ATO (that needs ATO Digital Service Provider onboarding, "
                  "which is not in place). Lodge through ATO Online services for business, myTax, or your registered tax agent, then record the receipt reference here.")


def health(db, ctx) -> dict:
    """Setup / data-quality checks that make every other figure trustworthy. severity: error | warn | info"""
    p = P.get(db, ctx)
    org = ctx.org
    out = []
    add = lambda key, sev, msg, fix="": out.append(dict(key=key, severity=sev, message=msg, fix=fix))
    if not p.abn:
        add("abn", "warn", "No ABN in the tax profile.", "Tax > Rates & Settings > Profile")
    elif not _abn_ok(p.abn):
        add("abn_invalid", "error", "The ABN fails the ATO check-digit test.", "Correct the ABN")
    if p.gst_registered != bool(org.gst_registered):
        add("gst_mismatch", "warn", "The tax profile and the organisation record disagree about GST registration.", "Make them consistent")
    if p.gst_basis != org.gst_basis:
        add("basis_mismatch", "warn", f"GST basis differs: tax profile {p.gst_basis}, organisation {org.gst_basis}. The BAS uses the tax profile.", "Make them consistent")
    if p.aggregated_turnover is None:
        add("turnover", "warn", "Aggregated turnover is not entered: small business concessions and company rate cannot be tested.", "Enter turnover in the profile")
    if payroll.has_employees(db, org.id) and not p.payg_withholding:
        add("payg_flag", "warn", "The organisation has active employees but PAYG withholding is not ticked in the tax profile.", "Tick PAYG withholding and register with the ATO")
    if p.payg_instalment_method == "none":
        add("instalments", "info", "No PAYG instalment method is set. If the ATO has notified instalments, enter the amount or rate.", "Profile")
    susp = accounting.system_account_balance(db, org, "suspense", date.today())
    if susp not in (None, "0.00") and D(susp) != 0:
        add("suspense", "warn", f"The Suspense account holds {susp}: unclassified transactions distort GST and profit.", "Banking & Reconciliation")
    if org.lock_date is None:
        add("lock_date", "info", "No books lock date is set. Locking each period after lodgement protects lodged figures.", "Accounting > Settings")
    if p.has_tax_agent and not p.tax_agent_number:
        add("agent_number", "info", "A tax agent is recorded without a registration number.", "Profile")
    if p.entity_type == "company" and db.query(T.TaxDiv7aLoan.id).filter_by(org_id=org.id, status="active").first() is None:
        add("div7a_check", "info", "No Division 7A loans recorded. If shareholders or associates have borrowed from the company or been paid unpaid present entitlements, record them.", "Division 7A")
    try:
        from accfino.modules.taxation.services import payroll_tax as PT
        w = PT.watch(db, ctx, R.fy_of(date.today(), org.fy_end_month or 6))
        if w["status"] in ("above", "approaching") and not w["registered"]:
            add("payroll_tax", "warn", f"Payroll tax: {w['message']} No payroll tax registration is recorded.", "Calendar > Registrations")
    except core.TaxError:
        pass
    rs = core.rules_for_date(db, ctx, date.today())
    if rs.provisional:
        add("rules_provisional", "warn", f"The rule set for {rs.id} is PROVISIONAL: values were carried forward before they were published.", "Rates & Settings")
    summ = {}
    for r in rs.flat():
        summ[r["verification"]] = summ.get(r["verification"], 0) + 1
    unver = summ.get("knowledge_unverified", 0) + summ.get("not_loaded", 0)
    if unver:
        add("rules_unverified", "warn", f"{unver} statutory rule value(s) in {rs.id} are unverified or not loaded. Review Tax > Rates & Settings before relying on calculations.", "Rates & Settings")
    reg_kinds = {r["kind"] for r in O.registrations(db, ctx) if r["active"]}
    for need, cond, label in (("gst", p.gst_registered, "GST"), ("payg_withholding", p.payg_withholding, "PAYG withholding"), ("fbt", p.fbt_registered, "FBT")):
        if cond and need not in reg_kinds:
            add(f"reg_{need}", "info", f"{label} is ticked in the profile but no {label} registration is recorded.", "Registrations")
    return dict(items=out, rule_verification=summ, ok=not any(i["severity"] == "error" for i in out))


def _abn_ok(abn: str) -> bool:
    d = [int(c) for c in abn if c.isdigit()]
    if len(d) != 11:
        return False
    d[0] -= 1
    w = (10, 1, 3, 5, 7, 9, 11, 13, 15, 17, 19)
    return sum(a * b for a, b in zip(d, w)) % 89 == 0


def dashboard(db, ctx, today: Optional[date] = None) -> dict:
    today = today or date.today()
    p = P.get(db, ctx)
    fo = ctx.org.fy_end_month or 6
    fy = R.fy_of(today, fo)
    cal = O.summary(db, ctx, today)
    stmts = B.listing(db, ctx, fy)
    ret = [r for r in RT.listing(db, ctx, fy) if r["status"] != "void"]
    h = health(db, ctx)
    return dict(fy=fy, today=today.isoformat(), entity_type=p.entity_type, calendar=cal, bas=dict(count=len(stmts), by_status=_count(stmts), latest=stmts[:3]), returns=ret[:1],
                fbt=[r for r in F.returns(db, ctx)][:2], div7a=dict(active_loans=len([l for l in DV.loans(db, ctx) if l["status"] == "active"])), health=h,
                open_adjustments_for_review=db.query(T.TaxAdjustment).filter_by(org_id=ctx.org.id, fy=fy, requires_review=True, reviewed_at=None).count(),
                workpapers=_count(W.listing(db, ctx, fy)), recent_activity=audit(db, ctx, limit=8), lodgement_note=LODGEMENT_NOTE,
                alerts=_alerts(cal, h))


def _count(rows):
    out = {}
    for r in rows:
        out[r["status"]] = out.get(r["status"], 0) + 1
    return out


def _alerts(cal, h):
    out = [dict(level="error", text=f"Overdue: {o['title']} (due {o['due_date']})") for o in cal["overdue"]]
    out += [dict(level="warn", text=f"Due in {o['days_to_due']} days: {o['title']} ({o['due_date']})") for o in cal["due_soon"]]
    out += [dict(level=i["severity"], text=i["message"]) for i in h["items"] if i["severity"] in ("error", "warn")][:5]
    return out


def audit(db, ctx, limit=100, entity_type="", before_seq=None):
    q = db.query(T.TaxAudit).filter_by(org_id=ctx.org.id)
    if entity_type:
        q = q.filter(T.TaxAudit.entity_type == entity_type)
    if before_seq:
        q = q.filter(T.TaxAudit.seq < before_seq)
    return [dict(seq=r.seq, at=r.at.isoformat(), user=r.username, action=r.action, entity_type=r.entity_type, entity_id=r.entity_id, summary=r.summary) for r in q.order_by(T.TaxAudit.seq.desc()).limit(min(limit, 500))]


# ---- reconciliation ------------------------------------------------------------------------------------------------------------------
def reconcile(db, ctx, period_start: date, period_end: date) -> dict:
    """Independent cross-checks of the tax figures to their sources. Each row: what, figure A, figure B, difference, status, explanation."""
    p = P.get(db, ctx)
    org = ctx.org
    rows = []

    def row(key, label, a, b, why, tol="0.01"):
        diff = q2(D(a) - D(b))
        rows.append(dict(key=key, label=label, a=str(q2(a)), b=str(q2(b)), difference=str(diff), status="ok" if abs(diff) <= D(tol) else "difference", explanation=why))
    gst = accounting.gst_summary(db, org, period_start, period_end, p.gst_basis) if p.gst_registered else None
    pl = accounting.profit_and_loss(db, org, period_start, period_end)
    if gst:
        lc = gst.get("ledger_check", {})
        if lc.get("gst_account_movement") is not None:
            row("gst_account", "GST account movement vs 1A - 1B", lc["gst_account_movement"], D(gst["gst_on_sales_1A"]) - D(gst["gst_on_purchases_1B"]),
                "A difference means GST was posted without a tax code (for example a manual journal).")
        g1, a1 = D(gst["fields"].get("G1")), D(gst["fields"].get("1A"))
        row("sales_vs_g1", "Ledger revenue (ex GST) vs G1 less 1A", pl["revenue_total"], g1 - a1,
            "Differences are normal when sales include GST-free, input-taxed, or excluded revenue (interest, grants) or are on a different basis; each must be explainable.", tol="1.00")
    ledger = accounting.payg_summary(db, org, period_start, period_end)
    run = payroll.withholding_for_period(db, org.id, period_start, period_end)
    if ledger.get("has_payroll") or run["runs"]:
        row("payg_vs_payroll", "PAYG withheld: ledger (W2) vs finalised pay runs", ledger["bas"]["W2"], run["withheld_total"], "Both should agree. A difference means a pay run was not posted, or journals were posted manually.")
        row("wages_vs_payroll", "Wages: ledger (W1) vs finalised pay runs gross", ledger["bas"]["W1"], run["gross"], "W1 includes wages expense only; a manual wages journal or unposted run causes a difference.", tol="1.00")
        row("payg_liability", "PAYG liability reconciliation (withheld less remitted vs ledger movement)", ledger["check"]["payg_expected"], ledger["check"]["payg_ledger_movement"], "The PAYG payable account movement should equal withheld less remitted.")
    stmts = db.query(T.TaxBasStatement).filter(T.TaxBasStatement.org_id == ctx.org.id, T.TaxBasStatement.status.in_(("lodged", "paid", "approved")), T.TaxBasStatement.period_start >= period_start,
                                               T.TaxBasStatement.period_end <= period_end).all()
    if gst and stmts:
        lodged_1a = sum((D((s.final or {}).get("1A", {}).get("value")) for s in stmts), ZERO)
        row("lodged_1a", "1A on approved/lodged statements vs ledger GST on sales for the same period", lodged_1a, gst["gst_on_sales_1A"],
            "If the ledger changed after lodgement, an amended BAS may be needed.")
    return dict(period_start=period_start.isoformat(), period_end=period_end.isoformat(), rows=rows, all_ok=all(r["status"] == "ok" for r in rows) if rows else True,
                note="Cross-checks only compare AccFino's own sources. They do not prove the figures are correct for tax purposes.")


# ---- lodgement readiness -------------------------------------------------------------------------------------------------------------
def readiness(db, ctx, kind: str, doc_id: int) -> dict:
    checks = []
    add = lambda key, ok, label, detail="": checks.append(dict(key=key, ok=bool(ok), label=label, detail=detail))
    p = P.get(db, ctx)
    ev = lambda lt: len(W.evidence_for(db, ctx, linked_type=lt, linked_id=doc_id))
    wps = lambda lt: [w for w in W.listing(db, ctx) if w["linked_type"] == lt and w["linked_id"] == doc_id]
    if kind == "bas_statement":
        s = B.get(db, ctx, doc_id)
        add("abn", bool(p.abn) and _abn_ok(p.abn), "Valid ABN in the tax profile")
        add("calculated", bool(s.labels), "Figures calculated from the ledger")
        add("no_errors", not any(f["severity"] == "error" for f in (s.findings or [])), "No blocking errors")
        add("overrides_documented", all(any(w["status"] in ("prepared", "reviewed", "approved") for w in wps("bas_statement")) for _ in (s.overrides or {}) ) if s.overrides else True,
            "Every override is explained in a workpaper" if s.overrides else "No overrides used")
        add("evidence", ev("bas_statement") > 0 or bool(wps("bas_statement")), "Working or evidence attached", "Generate a workpaper from the statement")
        add("approved", s.status in ("approved", "lodged", "paid"), "Approved by a second person" if not p.allow_self_approval else "Approved (self-approval enabled)")
        ds = core.declaration_status(db, ctx, "bas_statement", doc_id, s.calc_hash)
        add("declaration", ds["ok"] or s.status in ("lodged", "paid"), "Registered agent sign-off recorded (required by your policy)" if ds["policy"] == "agent_signoff_required" else "Declaration / sign-off recorded", ds["requirement"])
        add("period_locked", ctx.org.lock_date is not None and ctx.org.lock_date >= s.period_end, "Books locked to the end of the period", "Lock after approval so lodged figures cannot change")
        status, lodged = s.status, s.status in ("lodged", "paid")
    elif kind == "tax_return":
        r = RT.get(db, ctx, doc_id)
        add("calculated", bool(r.computation), "Return calculated from the ledger")
        add("no_errors", not any(f["severity"] == "error" for f in (r.findings or [])), "No blocking errors")
        add("adjustments", db.query(T.TaxAdjustment).filter_by(org_id=ctx.org.id, fy=r.fy, requires_review=True, reviewed_at=None).count() == 0, "All adjustments requiring review have been reviewed")
        add("evidence", bool(wps("tax_return")) or ev("tax_return") > 0, "Workpaper or evidence attached")
        add("agent_review", bool([f for f in (r.findings or []) if f["severity"] == "review"]) is False or p.has_tax_agent, "Review items cleared or a tax agent is engaged",
            "Items marked review need professional sign-off")
        add("approved", r.status in ("approved", "lodged", "paid"), "Approved")
        ds = core.declaration_status(db, ctx, "tax_return", doc_id, r.calc_hash)
        add("declaration", ds["ok"] or r.status in ("lodged", "paid"), "Registered agent sign-off recorded (required by your policy)" if ds["policy"] == "agent_signoff_required" else "Declaration / sign-off recorded", ds["requirement"])
        add("period_locked", ctx.org.lock_date is not None and ctx.org.lock_date >= R.fy_bounds(r.fy, ctx.org.fy_end_month or 6)[1], "Books locked to year end")
        status, lodged = r.status, r.status in ("lodged", "paid")
    elif kind == "fbt_return":
        r = F.get_return(db, ctx, doc_id)
        add("registered", p.fbt_registered, "Registered for FBT in the tax profile")
        add("benefits", (r.summary or {}).get("benefit_count", 0) > 0 or D(r.fbt_payable) == 0, "Benefits recorded")
        add("approved", r.status in ("approved", "lodged", "paid"), "Approved")
        ds = core.declaration_status(db, ctx, "fbt_return", doc_id, r.calc_hash)
        add("declaration", ds["ok"] or r.status in ("lodged", "paid"), "Registered agent sign-off recorded (required by your policy)" if ds["policy"] == "agent_signoff_required" else "Declaration / sign-off recorded", ds["requirement"])
        add("agent_review", p.has_tax_agent, "A tax agent is engaged to review the FBT return", "FBT valuation rules have many conditions that AccFino does not assess")
        status, lodged = r.status, r.status in ("lodged", "paid")
    else:
        raise core.TaxError("kind must be bas_statement, tax_return or fbt_return")
    return dict(kind=kind, id=doc_id, status=status, checks=checks, ready=all(c["ok"] for c in checks if c["key"] not in ("period_locked", "agent_review", "evidence")) and not lodged,
                already_lodged=lodged, how_to_lodge=LODGEMENT_NOTE)


# ---- reports -------------------------------------------------------------------------------------------------------------------------
def summary_pack(db, ctx, fy: str) -> dict:
    core.check_fy(ctx, fy)
    start, end = R.fy_bounds(fy, ctx.org.fy_end_month or 6)
    rets = [r for r in RT.listing(db, ctx, fy) if r["status"] != "void"]
    return dict(fy=fy, organisation=ctx.org.name, abn=ctx.org.abn, generated_on=date.today().isoformat(), profile=P.to_dict(P.get(db, ctx)),
                activity_statements=[B.to_dict(B.get(db, ctx, s["id"]), True) for s in B.listing(db, ctx, fy) if s["status"] != "void"],
                returns=[RT.to_dict(RT.get(db, ctx, r["id"])) for r in rets], adjustments=RT.adjustments(db, ctx, fy), cgt=CGT.compute(db, ctx, fy), cgt_events=CGT.events(db, ctx, fy),
                assets=AS.review(db, ctx, fy), obligations=O.listing(db, ctx, fy), reconciliation=reconcile(db, ctx, start, end), rule_set=core.rules_for_fy(db, ctx, fy).summary(),
                disclaimer="Prepared by AccFino for review. Not tax advice. Items marked review need a registered tax agent.")


def _csv(rows, cols):
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(cols)
    for r in rows:
        w.writerow([_safe(r.get(c, "")) for c in cols])
    return buf.getvalue()


def _safe(v):
    s = "" if v is None else str(v)
    return "'" + s if s[:1] in ("=", "+", "-", "@") and not _isnum(s) else s          # CSV-injection guard for text cells


def _isnum(s):
    try:
        float(s)
        return True
    except ValueError:
        return False


def export_csv(db, ctx, what: str, fy: str = "", doc_id: Optional[int] = None) -> tuple:
    """-> (filename, csv text). what: bas | adjustments | cgt | obligations | audit"""
    if what == "bas":
        s = B.get(db, ctx, doc_id)
        fig = B.E.lodgement_figures(s.final or {})
        rows = [dict(label=k, value=s.final[k]["value"], kind=s.final[k]["kind"], source=s.final[k].get("source", ""), lodgement_dollars=fig.get(k, "")) for k in B.E.ordered_labels(s.final or {})]
        return f"{s.kind}_{s.period_start}_{s.period_end}.csv", _csv(rows, ("label", "value", "kind", "source", "lodgement_dollars"))
    if what == "adjustments":
        return f"adjustments_{fy}.csv", _csv(RT.adjustments(db, ctx, fy), ("code", "description", "direction", "amount", "category", "source", "requires_review", "reviewed"))
    if what == "cgt":
        return f"cgt_events_{fy}.csv", _csv(CGT.events(db, ctx, fy), ("asset_name", "asset_class", "acquire_date", "dispose_date", "proceeds", "acquisition_cost", "incidental_costs", "capital_improvements", "disposal_costs", "source", "excluded"))
    if what == "obligations":
        return f"obligations_{fy or 'all'}.csv", _csv(O.listing(db, ctx, fy), ("title", "kind", "due_date", "original_due_date", "status", "display_status", "lodged_on", "paid_on", "reference", "amount"))
    if what == "audit":
        return "tax_audit.csv", _csv(audit(db, ctx, limit=500), ("seq", "at", "user", "action", "entity_type", "entity_id", "summary"))
    raise core.TaxError("what must be bas, adjustments, cgt, obligations or audit")


def export_xlsx(db, ctx, fy: str) -> bytes:
    from openpyxl import Workbook
    pack = summary_pack(db, ctx, fy)
    wb = Workbook()
    ws = wb.active
    ws.title = "Summary"
    ws.append(["Organisation", pack["organisation"]]); ws.append(["ABN", pack["abn"]]); ws.append(["Income year", fy]); ws.append(["Generated", pack["generated_on"]]); ws.append([pack["disclaimer"]])
    for r in pack["returns"]:
        ws.append([]); ws.append([f"Return v{r['version']} ({r['status']})", "Taxable income", r["taxable_income"], "Balance", r["tax_payable"]])
    for title, rows, cols in (("Activity statements", [dict(period=f"{s['period_start']} to {s['period_end']}", kind=s["kind"], status=s["status"], label_9=s["amount_payable"]) for s in pack["activity_statements"]], ("period", "kind", "status", "label_9")),
                              ("Adjustments", pack["adjustments"], ("code", "description", "direction", "amount", "category", "reviewed")), ("CGT events", pack["cgt_events"], ("asset_name", "acquire_date", "dispose_date", "proceeds", "acquisition_cost")),
                              ("Obligations", pack["obligations"], ("title", "due_date", "status", "reference")), ("Reconciliation", pack["reconciliation"]["rows"], ("label", "a", "b", "difference", "status"))):
        sh = wb.create_sheet(title[:31])
        sh.append(list(cols))
        for r in rows:
            sh.append([_safe(r.get(c, "")) for c in cols])
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()
