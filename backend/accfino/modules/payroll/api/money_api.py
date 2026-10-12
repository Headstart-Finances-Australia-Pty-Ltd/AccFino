"""Payslips, payments, super, STP, reports and audit."""
from datetime import date
from typing import Optional

from fastapi import APIRouter, Body, Depends, Query
from fastapi.responses import HTMLResponse, PlainTextResponse
from sqlalchemy.orm import Session

from accfino.core.security.context import OrgContext, current_org
from accfino.modules.payroll.access import Access
from accfino.modules.payroll.api.deps import access, parse_date
from accfino.modules.payroll.models.payroll import PayAudit
from accfino.modules.payroll.services import payments as P, payslips as S, reports as RP, stp as STP, superfunds as SF, audit as AU
from accfino.modules.payroll.services.errors import NotFound
from accfino.shared.db.database import get_db

router = APIRouter()
Ctx, Db, Acc = Depends(current_org), Depends(get_db), Depends(access)


# ---- payslips ------------------------------------------------------------------------------------------------------------------------
@router.get("/payslips")
def payslips(employee_id: int = 0, run_id: int = 0, mine: bool = False, ctx: OrgContext = Ctx, db: Session = Db, a: Access = Acc):
    return S.list_payslips(db, ctx, a, employee_id=employee_id, run_id=run_id, mine=mine)


@router.get("/payslips/{pid}")
def payslip(pid: int, ctx: OrgContext = Ctx, db: Session = Db, a: Access = Acc):
    return S.ser(S.get_payslip(db, ctx, a, pid), full=True)


@router.get("/payslips/{pid}/html", response_class=HTMLResponse)
def payslip_html(pid: int, ctx: OrgContext = Ctx, db: Session = Db, a: Access = Acc):
    return HTMLResponse(S.render_html(S.get_payslip(db, ctx, a, pid)))


# ---- payments ------------------------------------------------------------------------------------------------------------------------
@router.get("/payments")
def payments(run_id: int = 0, ctx: OrgContext = Ctx, db: Session = Db, a: Access = Acc):
    return P.list_payments(db, ctx, a, run_id)


@router.post("/runs/{run_id}/payments")
def payment_prepare(run_id: int, body: dict = Body(default={}), ctx: OrgContext = Ctx, db: Session = Db, a: Access = Acc):
    p = P.prepare(db, ctx, a, run_id, parse_date(body.get("payment_date"), "payment_date"), body.get("method", "mock"))
    db.commit()
    return P.detail(db, ctx, a, p.id)


@router.get("/payments/{pid}")
def payment(pid: int, ctx: OrgContext = Ctx, db: Session = Db, a: Access = Acc):
    return P.detail(db, ctx, a, pid)


@router.get("/payments/{pid}/aba", response_class=PlainTextResponse)
def payment_aba(pid: int, ctx: OrgContext = Ctx, db: Session = Db, a: Access = Acc):
    text = P.aba_file(db, ctx, a, pid)
    db.commit()                                                # the download is audited
    return PlainTextResponse(text, headers={"Content-Disposition": f'attachment; filename="payroll-{pid}.aba"'})


@router.post("/payments/{pid}/complete")
def payment_complete(pid: int, ctx: OrgContext = Ctx, db: Session = Db, a: Access = Acc):
    P.complete(db, ctx, a, pid)
    db.commit()
    return P.detail(db, ctx, a, pid)


@router.post("/payments/{pid}/cancel")
def payment_cancel(pid: int, body: dict = Body(...), ctx: OrgContext = Ctx, db: Session = Db, a: Access = Acc):
    P.cancel(db, ctx, a, pid, body.get("reason", ""))
    db.commit()
    return P.detail(db, ctx, a, pid)


@router.post("/payments/{pid}/reconcile")
def payment_reconcile(pid: int, body: dict = Body(default={}), ctx: OrgContext = Ctx, db: Session = Db, a: Access = Acc):
    n = P.reconcile(db, ctx, a, pid, body.get("item_ids"))
    db.commit()
    return {"reconciled": n, **P.detail(db, ctx, a, pid)}


@router.post("/payments/{pid}/items/{item_id}/status")
def payment_item(pid: int, item_id: int, body: dict = Body(...), ctx: OrgContext = Ctx, db: Session = Db, a: Access = Acc):
    P.set_item_status(db, ctx, a, pid, item_id, body.get("status", ""), body.get("reason", ""))
    db.commit()
    return P.detail(db, ctx, a, pid)


# ---- super ---------------------------------------------------------------------------------------------------------------------------
@router.get("/super")
def super_list(status: str = "", fund_id: int = 0, date_from: Optional[str] = None, date_to: Optional[str] = None, ctx: OrgContext = Ctx, db: Session = Db, a: Access = Acc):
    return SF.listing(db, ctx, a, status=status, fund_id=fund_id, date_from=parse_date(date_from, "date_from"), date_to=parse_date(date_to, "date_to"))


@router.post("/super/mark-paid")
def super_paid(body: dict = Body(...), ctx: OrgContext = Ctx, db: Session = Db, a: Access = Acc):
    n = SF.mark_paid(db, ctx, a, body.get("ids", []), body.get("reference", ""))
    db.commit()
    return {"marked_paid": n}


# ---- STP -----------------------------------------------------------------------------------------------------------------------------
@router.get("/stp")
def stp_list(ctx: OrgContext = Ctx, db: Session = Db, a: Access = Acc):
    return STP.list_events(db, ctx, a)


@router.get("/stp/finalisation")
def stp_final(fy: str, ctx: OrgContext = Ctx, db: Session = Db, a: Access = Acc):
    return STP.finalisation_status(db, ctx, a, fy)


@router.post("/stp/finalise")
def stp_do_final(body: dict = Body(...), ctx: OrgContext = Ctx, db: Session = Db, a: Access = Acc):
    out = STP.finalise_employees(db, ctx, a, body.get("fy", ""), body.get("employee_ids", []))
    db.commit()
    return {"finalised": out}


@router.get("/stp/payment-summary")
def stp_summary(employee_id: int, fy: str, ctx: OrgContext = Ctx, db: Session = Db, a: Access = Acc):
    return STP.payment_summary(db, ctx, a, employee_id, fy)


@router.get("/stp/{event_id}")
def stp_get(event_id: int, ctx: OrgContext = Ctx, db: Session = Db, a: Access = Acc):
    a.require("stp_manage")
    from accfino.modules.payroll.models.payroll import PayStpEvent
    ev = db.query(PayStpEvent).filter_by(id=event_id, org_id=ctx.org.id).first()
    if ev is None:
        raise NotFound("STP event")
    return STP.ser(ev, full=True)


@router.post("/runs/{run_id}/stp")
def stp_prepare(run_id: int, ctx: OrgContext = Ctx, db: Session = Db, a: Access = Acc):
    ev = STP.prepare_pay_event(db, ctx, a, run_id)
    db.commit()
    return STP.ser(ev, full=True)


@router.post("/stp/{event_id}/mock-submit")
def stp_mock(event_id: int, ctx: OrgContext = Ctx, db: Session = Db, a: Access = Acc):
    ev = STP.mock_submit(db, ctx, a, event_id)
    db.commit()
    return STP.ser(ev, full=True)


# ---- reports -------------------------------------------------------------------------------------------------------------------------
@router.get("/reports")
def report_list(a: Access = Acc):
    a.require("reports_view")
    return RP.catalogue()


@router.get("/reports/{key}")
def report(key: str, date_from: Optional[str] = None, date_to: Optional[str] = None, employee_id: int = 0, department_id: int = 0, run_id: int = 0,
           format: str = Query("json", pattern="^(json|csv)$"), ctx: OrgContext = Ctx, db: Session = Db, a: Access = Acc):
    rep = RP.run_report(db, ctx, a, key, RP.Filters(parse_date(date_from, "date_from"), parse_date(date_to, "date_to"), employee_id, department_id, run_id))
    if format == "csv":
        return PlainTextResponse(RP.to_csv(rep), media_type="text/csv", headers={"Content-Disposition": f'attachment; filename="payroll-{key}.csv"'})
    return rep


# ---- audit ---------------------------------------------------------------------------------------------------------------------------
@router.get("/audit")
def audit_list(entity_type: str = "", entity_id: str = "", action: str = "", date_from: Optional[str] = None, date_to: Optional[str] = None, limit: int = Query(200, ge=1, le=1000),
               ctx: OrgContext = Ctx, db: Session = Db, a: Access = Acc):
    a.require("audit_view")
    q = db.query(PayAudit).filter(PayAudit.org_id == ctx.org.id)
    if entity_type:
        q = q.filter(PayAudit.entity_type == entity_type)
    if entity_id:
        q = q.filter(PayAudit.entity_id == entity_id)
    if action:
        q = q.filter(PayAudit.action.like(f"{action}%"))
    if date_from:
        q = q.filter(PayAudit.occurred_at >= parse_date(date_from, "date_from"))
    if date_to:
        q = q.filter(PayAudit.occurred_at < date.fromordinal(parse_date(date_to, "date_to").toordinal() + 1))
    return [{"id": r.id, "occurred_at": r.occurred_at.isoformat(), "user": r.username, "action": r.action, "entity_type": r.entity_type, "entity_id": r.entity_id,
             "entity_label": r.entity_label, "summary": r.summary, "before": r.before, "after": r.after} for r in q.order_by(PayAudit.id.desc()).limit(limit)]
