"""Taxation & Compliance HTTP API (mounted at /tax). The API layer only validates, authorises and calls services; business rules live in services/ and engine/."""
from datetime import date
from typing import Optional

from fastapi import APIRouter, Body, Depends, File, Form, HTTPException, Query, UploadFile
from fastapi.responses import Response
from sqlalchemy.orm import Session

from accfino.core.security.context import OrgContext, current_org
from accfino.modules.taxation.api.deps import access
from accfino.modules.taxation.engine import bas as bas_engine
from accfino.modules.taxation.models import tax as T
from accfino.modules.taxation.services import (assets, bas, cgt, core, div7a, fbt, obligations, overview, planning, profile, returns, workpapers)
from accfino.modules.taxation.services.core import Access
from accfino.shared.db.database import get_db

router = APIRouter()
Ctx, Db, Acc = Depends(current_org), Depends(get_db), Depends(access)


def _d(v, name):
    return core.parse_date(v, name)


# ---- overview ----------------------------------------------------------------------------------------------------------------------
@router.get("/me")
def me(a: Access = Acc):
    return a.summary()


@router.get("/dashboard")
def dashboard(ctx: OrgContext = Ctx, db: Session = Db, a: Access = Acc):
    return overview.dashboard(db, ctx)


@router.get("/health")
def health(ctx: OrgContext = Ctx, db: Session = Db, a: Access = Acc):
    return overview.health(db, ctx)


@router.get("/reference")
def reference(fy: str = "", ctx: OrgContext = Ctx, db: Session = Db, a: Access = Acc):
    start = date.today() if not fy else core.rules_for_fy(db, ctx, fy).effective_from
    return dict(adjustments=returns.COMMON_ADJUSTMENTS, bas_labels=bas.label_names(db, ctx, start), entity_types=list(T.ENTITY_TYPES), bas_frequencies=list(T.BAS_FREQUENCIES),
                registration_kinds=list(T.REGISTRATION_KINDS), obligation_statuses=list(T.OBLIGATION_STATUSES), obligation_kinds=list(T.OBLIGATION_KINDS), fbt_types=list(T.FBT_TYPES),
                cgt_classes=list(T.CGT_CLASSES), workpaper_areas=list(T.WORKPAPER_AREAS), evidence_kinds=list(T.EVIDENCE_KINDS), states=list(profile.STATES))


# ---- profile, rules, registrations ----------------------------------------------------------------------------------------------
@router.get("/profile")
def get_profile(ctx: OrgContext = Ctx, db: Session = Db, a: Access = Acc):
    p = profile.get(db, ctx)
    db.commit()
    return profile.to_dict(p)


@router.put("/profile")
def put_profile(body: dict = Body(...), ctx: OrgContext = Ctx, db: Session = Db, a: Access = Acc):
    p = profile.save(db, ctx, a, body)
    db.commit()
    return profile.to_dict(p)


@router.get("/rules")
def rules(fy: str, ctx: OrgContext = Ctx, db: Session = Db, a: Access = Acc):
    return profile.effective_rules(db, ctx, fy)


@router.put("/rules/override")
def set_override(body: dict = Body(...), ctx: OrgContext = Ctx, db: Session = Db, a: Access = Acc):
    out = profile.set_override(db, ctx, a, body.get("fy", ""), body.get("path", ""), body.get("value"), body.get("reason", ""))
    db.commit()
    return out


@router.delete("/rules/override")
def clear_override(fy: str, path: str, ctx: OrgContext = Ctx, db: Session = Db, a: Access = Acc):
    profile.clear_override(db, ctx, a, fy, path)
    db.commit()
    return {"ok": True}


@router.get("/registrations")
def regs(ctx: OrgContext = Ctx, db: Session = Db, a: Access = Acc):
    return obligations.registrations(db, ctx)


@router.post("/registrations")
def reg_add(body: dict = Body(...), ctx: OrgContext = Ctx, db: Session = Db, a: Access = Acc):
    r = obligations.save_registration(db, ctx, a, body)
    db.commit()
    return obligations.reg_dict(r)


@router.put("/registrations/{rid}")
def reg_upd(rid: int, body: dict = Body(...), ctx: OrgContext = Ctx, db: Session = Db, a: Access = Acc):
    r = obligations.save_registration(db, ctx, a, body, rid)
    db.commit()
    return obligations.reg_dict(r)


@router.delete("/registrations/{rid}")
def reg_del(rid: int, ctx: OrgContext = Ctx, db: Session = Db, a: Access = Acc):
    obligations.delete_registration(db, ctx, a, rid)
    db.commit()
    return {"ok": True}


# ---- calendar ----------------------------------------------------------------------------------------------------------------------
@router.get("/obligations")
def ob_list(fy: str = "", status: str = "", kind: str = "", ctx: OrgContext = Ctx, db: Session = Db, a: Access = Acc):
    return obligations.listing(db, ctx, fy, status, kind)


@router.post("/obligations/generate")
def ob_generate(body: dict = Body(...), ctx: OrgContext = Ctx, db: Session = Db, a: Access = Acc):
    out = obligations.generate(db, ctx, a, body.get("fy", ""))
    db.commit()
    return out


@router.post("/obligations")
def ob_add(body: dict = Body(...), ctx: OrgContext = Ctx, db: Session = Db, a: Access = Acc):
    o = obligations.add_custom(db, ctx, a, body)
    db.commit()
    return obligations.to_dict(o)


@router.put("/obligations/{oid}")
def ob_upd(oid: int, body: dict = Body(...), ctx: OrgContext = Ctx, db: Session = Db, a: Access = Acc):
    o = obligations.update(db, ctx, a, oid, body)
    db.commit()
    return obligations.to_dict(o)


@router.delete("/obligations/{oid}")
def ob_del(oid: int, ctx: OrgContext = Ctx, db: Session = Db, a: Access = Acc):
    obligations.delete_custom(db, ctx, a, oid)
    db.commit()
    return {"ok": True}


@router.get("/payroll-tax/watch")
def payroll_tax_watch(fy: str, ctx: OrgContext = Ctx, db: Session = Db, a: Access = Acc):
    from accfino.modules.taxation.services import payroll_tax
    return payroll_tax.watch(db, ctx, fy)


# ---- sign-off & lodgement ----------------------------------------------------------------------------------------------------------------
@router.get("/lodgement/state")
def lodgement_state(doc_type: str, doc_id: int, ctx: OrgContext = Ctx, db: Session = Db, a: Access = Acc):
    from accfino.modules.taxation.services import lodgement
    return lodgement.state(db, ctx, doc_type, doc_id)


@router.get("/lodgement/providers")
def lodgement_providers(a: Access = Acc):
    from accfino.modules.taxation.services import lodgement
    return lodgement.providers()


@router.post("/signoffs")
def signoff_add(body: dict = Body(...), ctx: OrgContext = Ctx, db: Session = Db, a: Access = Acc):
    from accfino.modules.taxation.services import lodgement
    s = lodgement.sign(db, ctx, a, body.get("doc_type", ""), body.get("doc_id") or 0, body.get("capacity", ""), body.get("typed_name", ""), bool(body.get("confirmed")), body.get("agent_number", ""), body.get("note", ""))
    db.commit()
    return lodgement.so_dict(s)


@router.post("/signoffs/{sid}/revoke")
def signoff_revoke(sid: int, body: dict = Body(...), ctx: OrgContext = Ctx, db: Session = Db, a: Access = Acc):
    from accfino.modules.taxation.services import lodgement
    s = lodgement.revoke(db, ctx, a, sid, body.get("reason", ""))
    db.commit()
    return lodgement.so_dict(s)


@router.post("/lodgement/submit")
def lodgement_submit(body: dict = Body(...), ctx: OrgContext = Ctx, db: Session = Db, a: Access = Acc):
    from accfino.modules.taxation.services import lodgement
    out = lodgement.submit(db, ctx, a, body.get("doc_type", ""), body.get("doc_id") or 0, body.get("provider", ""))
    db.commit()
    return out


@router.get("/lodgement/pack")
def lodgement_pack(doc_type: str, doc_id: int, ctx: OrgContext = Ctx, db: Session = Db, a: Access = Acc):
    from accfino.modules.taxation.services import lodgement
    a.require("prepare")
    name, data = lodgement.build_pack(db, ctx, doc_type, doc_id)
    core.record(db, ctx, "lodgement.pack_downloaded", doc_type, doc_id, f"Hand-off pack downloaded ({len(data)} bytes)", None, None)
    db.commit()
    return Response(data, media_type="application/zip", headers={"Content-Disposition": f'attachment; filename="{name}"', "X-Content-Type-Options": "nosniff"})


# ---- BAS / IAS -----------------------------------------------------------------------------------------------------------------------
bas_r = APIRouter(prefix="/bas")


@bas_r.get("")
def bas_list(fy: str = "", status: str = "", ctx: OrgContext = Ctx, db: Session = Db, a: Access = Acc):
    return bas.listing(db, ctx, fy, status)


@bas_r.post("")
def bas_create(body: dict = Body(...), ctx: OrgContext = Ctx, db: Session = Db, a: Access = Acc):
    s = bas.create(db, ctx, a, body)
    db.commit()
    return bas.to_dict(s)


@bas_r.get("/{sid}")
def bas_get(sid: int, ctx: OrgContext = Ctx, db: Session = Db, a: Access = Acc):
    d = bas.to_dict(bas.get(db, ctx, sid))
    d["label_names"] = bas.label_names(db, ctx, bas.get(db, ctx, sid).period_start)
    return d


def _bas_action(name, fn, takes_body=False):
    if takes_body:
        @bas_r.post(f"/{{sid}}/{name}", name=f"bas_{name}")
        def ep(sid: int, body: dict = Body(default={}), ctx: OrgContext = Ctx, db: Session = Db, a: Access = Acc):
            s = fn(db, ctx, a, sid, body)
            db.commit()
            return bas.to_dict(s)
    else:
        @bas_r.post(f"/{{sid}}/{name}", name=f"bas_{name}")
        def ep(sid: int, ctx: OrgContext = Ctx, db: Session = Db, a: Access = Acc):
            s = fn(db, ctx, a, sid)
            db.commit()
            return bas.to_dict(s)


_bas_action("calculate", bas.calculate)
_bas_action("prepare", bas.mark_prepared)
_bas_action("lodged", bas.record_lodged, True)
_bas_action("paid", bas.record_paid, True)


@bas_r.post("/{sid}/approve")
def bas_approve(sid: int, body: dict = Body(default={}), ctx: OrgContext = Ctx, db: Session = Db, a: Access = Acc):
    s = bas.approve(db, ctx, a, sid, body.get("note", ""))
    db.commit()
    return bas.to_dict(s)


@bas_r.post("/{sid}/return")
def bas_return(sid: int, body: dict = Body(default={}), ctx: OrgContext = Ctx, db: Session = Db, a: Access = Acc):
    s = bas.return_to_draft(db, ctx, a, sid, body.get("note", ""))
    db.commit()
    return bas.to_dict(s)


@bas_r.post("/{sid}/void")
def bas_void(sid: int, body: dict = Body(...), ctx: OrgContext = Ctx, db: Session = Db, a: Access = Acc):
    s = bas.void(db, ctx, a, sid, body.get("reason", ""))
    db.commit()
    return bas.to_dict(s)


@bas_r.put("/{sid}/override")
def bas_override(sid: int, body: dict = Body(...), ctx: OrgContext = Ctx, db: Session = Db, a: Access = Acc):
    s = bas.override(db, ctx, a, sid, body.get("label", ""), body.get("value"), body.get("reason", ""))
    db.commit()
    return bas.to_dict(s)


@bas_r.delete("/{sid}/override/{label}")
def bas_override_del(sid: int, label: str, ctx: OrgContext = Ctx, db: Session = Db, a: Access = Acc):
    s = bas.remove_override(db, ctx, a, sid, label)
    db.commit()
    return bas.to_dict(s)


router.include_router(bas_r)


# ---- income tax returns & adjustments ------------------------------------------------------------------------------------------------
ret_r = APIRouter(prefix="/returns")


@ret_r.get("")
def ret_list(fy: str = "", ctx: OrgContext = Ctx, db: Session = Db, a: Access = Acc):
    return returns.listing(db, ctx, fy)


@ret_r.post("")
def ret_create(body: dict = Body(...), ctx: OrgContext = Ctx, db: Session = Db, a: Access = Acc):
    r = returns.create(db, ctx, a, body.get("fy", ""), body.get("inputs"))
    db.commit()
    return returns.to_dict(r)


@ret_r.get("/{rid}")
def ret_get(rid: int, ctx: OrgContext = Ctx, db: Session = Db, a: Access = Acc):
    return returns.to_dict(returns.get(db, ctx, rid))


@ret_r.put("/{rid}/inputs")
def ret_inputs(rid: int, body: dict = Body(...), ctx: OrgContext = Ctx, db: Session = Db, a: Access = Acc):
    r = returns.set_inputs(db, ctx, a, rid, body)
    db.commit()
    return returns.to_dict(r)


for _name, _fn in (("calculate", returns.calculate), ("prepare", returns.mark_prepared)):
    def _mk(fn=_fn, name=_name):
        @ret_r.post(f"/{{rid}}/{name}", name=f"ret_{name}")
        def ep(rid: int, ctx: OrgContext = Ctx, db: Session = Db, a: Access = Acc):
            r = fn(db, ctx, a, rid)
            db.commit()
            return returns.to_dict(r)
    _mk()


@ret_r.post("/{rid}/approve")
def ret_approve(rid: int, body: dict = Body(default={}), ctx: OrgContext = Ctx, db: Session = Db, a: Access = Acc):
    r = returns.approve(db, ctx, a, rid, body.get("note", ""))
    db.commit()
    return returns.to_dict(r)


@ret_r.post("/{rid}/return")
def ret_back(rid: int, body: dict = Body(default={}), ctx: OrgContext = Ctx, db: Session = Db, a: Access = Acc):
    r = returns.return_to_draft(db, ctx, a, rid, body.get("note", ""))
    db.commit()
    return returns.to_dict(r)


@ret_r.post("/{rid}/lodged")
def ret_lodged(rid: int, body: dict = Body(...), ctx: OrgContext = Ctx, db: Session = Db, a: Access = Acc):
    r = returns.record_lodged(db, ctx, a, rid, body)
    db.commit()
    return returns.to_dict(r)


@ret_r.post("/{rid}/assessment")
def ret_assess(rid: int, body: dict = Body(...), ctx: OrgContext = Ctx, db: Session = Db, a: Access = Acc):
    r = returns.record_assessment(db, ctx, a, rid, body.get("amount"), body.get("assessed_on"))
    db.commit()
    return returns.to_dict(r)


@ret_r.post("/{rid}/paid")
def ret_paid(rid: int, body: dict = Body(default={}), ctx: OrgContext = Ctx, db: Session = Db, a: Access = Acc):
    r = returns.record_paid(db, ctx, a, rid, body.get("paid_on"))
    db.commit()
    return returns.to_dict(r)


@ret_r.post("/{rid}/void")
def ret_void(rid: int, body: dict = Body(...), ctx: OrgContext = Ctx, db: Session = Db, a: Access = Acc):
    r = returns.void(db, ctx, a, rid, body.get("reason", ""))
    db.commit()
    return returns.to_dict(r)


@ret_r.post("/{rid}/amend")
def ret_amend(rid: int, body: dict = Body(...), ctx: OrgContext = Ctx, db: Session = Db, a: Access = Acc):
    r = returns.amend(db, ctx, a, rid, body.get("reason", ""))
    db.commit()
    return returns.to_dict(r)


router.include_router(ret_r)


@router.get("/adjustments")
def adj_list(fy: str, ctx: OrgContext = Ctx, db: Session = Db, a: Access = Acc):
    return returns.adjustments(db, ctx, core.check_fy(ctx, fy))


@router.post("/adjustments")
def adj_add(fy: str, body: dict = Body(...), ctx: OrgContext = Ctx, db: Session = Db, a: Access = Acc):
    x = returns.save_adjustment(db, ctx, a, fy, body)
    db.commit()
    return returns.adj_dict(x)


@router.put("/adjustments/{aid}")
def adj_upd(aid: int, fy: str, body: dict = Body(...), ctx: OrgContext = Ctx, db: Session = Db, a: Access = Acc):
    x = returns.save_adjustment(db, ctx, a, fy, body, aid)
    db.commit()
    return returns.adj_dict(x)


@router.delete("/adjustments/{aid}")
def adj_del(aid: int, fy: str, ctx: OrgContext = Ctx, db: Session = Db, a: Access = Acc):
    returns.delete_adjustment(db, ctx, a, fy, aid)
    db.commit()
    return {"ok": True}


@router.post("/adjustments/{aid}/review")
def adj_review(aid: int, body: dict = Body(default={}), ctx: OrgContext = Ctx, db: Session = Db, a: Access = Acc):
    x = returns.review_adjustment(db, ctx, a, aid, body.get("note", ""))
    db.commit()
    return returns.adj_dict(x)


@router.post("/adjustments/generate-depreciation")
def adj_dep(body: dict = Body(...), ctx: OrgContext = Ctx, db: Session = Db, a: Access = Acc):
    out = assets.generate_adjustments(db, ctx, a, body.get("fy", ""))
    db.commit()
    return out


@router.get("/assets/review")
def assets_review(fy: str, ctx: OrgContext = Ctx, db: Session = Db, a: Access = Acc):
    return assets.review(db, ctx, fy)


# ---- CGT ---------------------------------------------------------------------------------------------------------------------------------
@router.get("/cgt/events")
def cgt_events(fy: str = "", ctx: OrgContext = Ctx, db: Session = Db, a: Access = Acc):
    return cgt.events(db, ctx, fy)


@router.post("/cgt/events")
def cgt_add(body: dict = Body(...), ctx: OrgContext = Ctx, db: Session = Db, a: Access = Acc):
    e = cgt.save_event(db, ctx, a, body)
    db.commit()
    return cgt.ev_dict(e)


@router.put("/cgt/events/{eid}")
def cgt_upd(eid: int, body: dict = Body(...), ctx: OrgContext = Ctx, db: Session = Db, a: Access = Acc):
    e = cgt.save_event(db, ctx, a, body, eid)
    db.commit()
    return cgt.ev_dict(e)


@router.delete("/cgt/events/{eid}")
def cgt_del(eid: int, ctx: OrgContext = Ctx, db: Session = Db, a: Access = Acc):
    cgt.delete_event(db, ctx, a, eid)
    db.commit()
    return {"ok": True}


@router.post("/cgt/events/{eid}/exclude")
def cgt_excl(eid: int, body: dict = Body(...), ctx: OrgContext = Ctx, db: Session = Db, a: Access = Acc):
    e = cgt.set_excluded(db, ctx, a, eid, bool(body.get("excluded", True)))
    db.commit()
    return cgt.ev_dict(e)


@router.post("/cgt/import")
def cgt_import(body: dict = Body(...), ctx: OrgContext = Ctx, db: Session = Db, a: Access = Acc):
    if "text" in body:
        out = cgt.import_csv(db, ctx, a, body["text"], asset_class=body.get("asset_class", "shares"), dry_run=bool(body.get("dry_run")))
    else:
        out = cgt.import_rows(db, ctx, a, body.get("rows") or [], asset_class=body.get("asset_class", "shares"), dry_run=bool(body.get("dry_run")))
    db.commit()
    return out


@router.post("/cgt/import-trades")
def cgt_import_trades(body: dict = Body(...), ctx: OrgContext = Ctx, db: Session = Db, a: Access = Acc):
    out = cgt.import_trades(db, ctx, a, body.get("trades") or [], body.get("method", "fifo"), bool(body.get("dry_run")))
    db.commit()
    return out


@router.get("/cgt/losses")
def cgt_losses(ctx: OrgContext = Ctx, db: Session = Db, a: Access = Acc):
    return cgt.losses(db, ctx)


@router.post("/cgt/losses")
def cgt_loss_add(body: dict = Body(...), ctx: OrgContext = Ctx, db: Session = Db, a: Access = Acc):
    l = cgt.add_loss(db, ctx, a, body.get("fy_incurred", ""), body.get("amount"), body.get("note", ""))
    db.commit()
    return dict(id=l.id)


@router.delete("/cgt/losses/{lid}")
def cgt_loss_del(lid: int, ctx: OrgContext = Ctx, db: Session = Db, a: Access = Acc):
    cgt.delete_loss(db, ctx, a, lid)
    db.commit()
    return {"ok": True}


@router.get("/cgt/compute")
def cgt_compute(fy: str, holder: str = "", ctx: OrgContext = Ctx, db: Session = Db, a: Access = Acc):
    return cgt.compute(db, ctx, fy, holder or None)


# ---- FBT -----------------------------------------------------------------------------------------------------------------------------------
fbt_r = APIRouter(prefix="/fbt")


@fbt_r.get("/employees")
def fbt_emps(ctx: OrgContext = Ctx, db: Session = Db, a: Access = Acc):
    import accfino.modules.payroll.public as payroll
    return payroll.employee_names(db, ctx.org.id)


@fbt_r.get("/benefits")
def fbt_benefits(year: str, ctx: OrgContext = Ctx, db: Session = Db, a: Access = Acc):
    return fbt.benefits(db, ctx, fbt.check_year(year))


@fbt_r.post("/benefits")
def fbt_add(year: str, body: dict = Body(...), ctx: OrgContext = Ctx, db: Session = Db, a: Access = Acc):
    b = fbt.save_benefit(db, ctx, a, year, body)
    db.commit()
    return fbt.b_dict(b)


@fbt_r.put("/benefits/{bid}")
def fbt_upd(bid: int, year: str, body: dict = Body(...), ctx: OrgContext = Ctx, db: Session = Db, a: Access = Acc):
    b = fbt.save_benefit(db, ctx, a, year, body, bid)
    db.commit()
    return fbt.b_dict(b)


@fbt_r.delete("/benefits/{bid}")
def fbt_del(bid: int, year: str, ctx: OrgContext = Ctx, db: Session = Db, a: Access = Acc):
    fbt.delete_benefit(db, ctx, a, year, bid)
    db.commit()
    return {"ok": True}


@fbt_r.get("/summary")
def fbt_summary(year: str, ctx: OrgContext = Ctx, db: Session = Db, a: Access = Acc):
    return fbt.summary(db, ctx, year)


@fbt_r.get("/returns")
def fbt_returns(ctx: OrgContext = Ctx, db: Session = Db, a: Access = Acc):
    return fbt.returns(db, ctx)


@fbt_r.get("/returns/{rid}")
def fbt_return(rid: int, ctx: OrgContext = Ctx, db: Session = Db, a: Access = Acc):
    return fbt.r_dict(fbt.get_return(db, ctx, rid))


@fbt_r.post("/returns/calculate")
def fbt_calc(body: dict = Body(...), ctx: OrgContext = Ctx, db: Session = Db, a: Access = Acc):
    r = fbt.calculate(db, ctx, a, body.get("year", ""))
    db.commit()
    return fbt.r_dict(r)


@fbt_r.post("/returns/{rid}/prepare")
def fbt_prep(rid: int, ctx: OrgContext = Ctx, db: Session = Db, a: Access = Acc):
    r = fbt.mark_prepared(db, ctx, a, rid)
    db.commit()
    return fbt.r_dict(r)


@fbt_r.post("/returns/{rid}/approve")
def fbt_appr(rid: int, body: dict = Body(default={}), ctx: OrgContext = Ctx, db: Session = Db, a: Access = Acc):
    r = fbt.approve(db, ctx, a, rid, body.get("note", ""))
    db.commit()
    return fbt.r_dict(r)


@fbt_r.post("/returns/{rid}/return")
def fbt_back(rid: int, body: dict = Body(default={}), ctx: OrgContext = Ctx, db: Session = Db, a: Access = Acc):
    r = fbt.return_to_draft(db, ctx, a, rid, body.get("note", ""))
    db.commit()
    return fbt.r_dict(r)


@fbt_r.post("/returns/{rid}/lodged")
def fbt_lodged(rid: int, body: dict = Body(...), ctx: OrgContext = Ctx, db: Session = Db, a: Access = Acc):
    r = fbt.record_lodged(db, ctx, a, rid, body)
    db.commit()
    return fbt.r_dict(r)


@fbt_r.post("/returns/{rid}/paid")
def fbt_paid(rid: int, body: dict = Body(default={}), ctx: OrgContext = Ctx, db: Session = Db, a: Access = Acc):
    r = fbt.record_paid(db, ctx, a, rid, body.get("paid_on"))
    db.commit()
    return fbt.r_dict(r)


router.include_router(fbt_r)


# ---- Division 7A -----------------------------------------------------------------------------------------------------------------------------
d7 = APIRouter(prefix="/div7a")


@d7.get("/loans")
def d7_loans(ctx: OrgContext = Ctx, db: Session = Db, a: Access = Acc):
    return div7a.loans(db, ctx)


@d7.post("/loans")
def d7_add(body: dict = Body(...), ctx: OrgContext = Ctx, db: Session = Db, a: Access = Acc):
    l = div7a.save_loan(db, ctx, a, body)
    db.commit()
    return div7a.l_dict(l)


@d7.put("/loans/{lid}")
def d7_upd(lid: int, body: dict = Body(...), ctx: OrgContext = Ctx, db: Session = Db, a: Access = Acc):
    l = div7a.save_loan(db, ctx, a, body, lid)
    db.commit()
    return div7a.l_dict(l)


@d7.delete("/loans/{lid}")
def d7_del(lid: int, ctx: OrgContext = Ctx, db: Session = Db, a: Access = Acc):
    div7a.delete_loan(db, ctx, a, lid)
    db.commit()
    return {"ok": True}


@d7.get("/loans/{lid}/payments")
def d7_pays(lid: int, ctx: OrgContext = Ctx, db: Session = Db, a: Access = Acc):
    return div7a.payments(db, ctx, lid)


@d7.post("/loans/{lid}/payments")
def d7_pay(lid: int, body: dict = Body(...), ctx: OrgContext = Ctx, db: Session = Db, a: Access = Acc):
    p = div7a.add_payment(db, ctx, a, lid, body)
    db.commit()
    return dict(id=p.id)


@d7.delete("/loans/{lid}/payments/{pid}")
def d7_pay_del(lid: int, pid: int, ctx: OrgContext = Ctx, db: Session = Db, a: Access = Acc):
    div7a.delete_payment(db, ctx, a, lid, pid)
    db.commit()
    return {"ok": True}


@d7.get("/loans/{lid}/schedule")
def d7_sched(lid: int, through_fy: str = "", ctx: OrgContext = Ctx, db: Session = Db, a: Access = Acc):
    return div7a.schedule(db, ctx, lid, through_fy or None)


router.include_router(d7)


# ---- workpapers & evidence ---------------------------------------------------------------------------------------------------------------------
wp = APIRouter(prefix="/workpapers")


@wp.get("")
def wp_list(fy: str = "", area: str = "", status: str = "", ctx: OrgContext = Ctx, db: Session = Db, a: Access = Acc):
    return workpapers.listing(db, ctx, fy, area, status)


@wp.post("")
def wp_add(body: dict = Body(...), ctx: OrgContext = Ctx, db: Session = Db, a: Access = Acc):
    w = workpapers.save(db, ctx, a, body)
    db.commit()
    return workpapers.w_dict(w)


@wp.post("/generate")
def wp_gen(body: dict = Body(...), ctx: OrgContext = Ctx, db: Session = Db, a: Access = Acc):
    w = workpapers.generate(db, ctx, a, body.get("kind", ""), body.get("doc_id"))
    db.commit()
    return workpapers.w_dict(w)


@wp.get("/{wid}")
def wp_get(wid: int, ctx: OrgContext = Ctx, db: Session = Db, a: Access = Acc):
    d = workpapers.w_dict(workpapers.get(db, ctx, wid))
    d["evidence"] = workpapers.evidence_for(db, ctx, workpaper_id=wid)
    return d


@wp.put("/{wid}")
def wp_upd(wid: int, body: dict = Body(...), ctx: OrgContext = Ctx, db: Session = Db, a: Access = Acc):
    w = workpapers.save(db, ctx, a, body, wid)
    db.commit()
    return workpapers.w_dict(w)


@wp.post("/{wid}/advance")
def wp_adv(wid: int, body: dict = Body(...), ctx: OrgContext = Ctx, db: Session = Db, a: Access = Acc):
    w = workpapers.advance(db, ctx, a, wid, body.get("to", ""), body.get("note", ""))
    db.commit()
    return workpapers.w_dict(w)


@wp.delete("/{wid}")
def wp_del(wid: int, ctx: OrgContext = Ctx, db: Session = Db, a: Access = Acc):
    workpapers.delete(db, ctx, a, wid)
    db.commit()
    return {"ok": True}


router.include_router(wp)


@router.get("/evidence")
def ev_list(workpaper_id: Optional[int] = None, linked_type: str = "", linked_id: Optional[int] = None, ctx: OrgContext = Ctx, db: Session = Db, a: Access = Acc):
    return workpapers.evidence_for(db, ctx, workpaper_id, linked_type, linked_id)


@router.post("/evidence")
async def ev_add(workpaper_id: Optional[int] = Form(None), linked_type: str = Form(""), linked_id: Optional[int] = Form(None), kind: str = Form(""), title: str = Form(""), note: str = Form(""),
                 url: str = Form(""), ledger_ref: str = Form(""), attachment_id: Optional[int] = Form(None), file: Optional[UploadFile] = File(None),
                 ctx: OrgContext = Ctx, db: Session = Db, a: Access = Acc):
    data = await file.read() if file is not None else None
    if data is not None and len(data) > workpapers.MAX_FILE + 1:
        raise HTTPException(422, "Evidence files are limited to 5 MB")
    e = workpapers.add_evidence(db, ctx, a, dict(workpaper_id=workpaper_id, linked_type=linked_type or None, linked_id=linked_id, kind=kind or None, title=title, note=note, url=url,
                                                  ledger_ref=ledger_ref, attachment_id=attachment_id), data, (file.filename if file else ""), (file.content_type if file else ""))
    db.commit()
    return workpapers.e_dict(e)


@router.get("/evidence/{eid}/file")
def ev_file(eid: int, ctx: OrgContext = Ctx, db: Session = Db, a: Access = Acc):
    e = workpapers.evidence_file(db, ctx, eid)
    safe = "".join(c for c in (e.file_name or "evidence") if c.isalnum() or c in "._- ")[:100] or "evidence"
    return Response(e.data, media_type=e.content_type or "application/octet-stream", headers={"Content-Disposition": f'attachment; filename="{safe}"', "X-Content-Type-Options": "nosniff"})


@router.delete("/evidence/{eid}")
def ev_del(eid: int, ctx: OrgContext = Ctx, db: Session = Db, a: Access = Acc):
    workpapers.delete_evidence(db, ctx, a, eid)
    db.commit()
    return {"ok": True}


# ---- planning, reconciliation, readiness, reports, audit -------------------------------------------------------------------------------------------
@router.post("/planning/estimate")
def plan_estimate(body: dict = Body(...), ctx: OrgContext = Ctx, db: Session = Db, a: Access = Acc):
    return planning.estimate(db, ctx, body.get("fy", ""), _d(body.get("as_at"), "as_at"), body.get("levers"), body.get("projected_profit"), body.get("other_income") or "0")


@router.get("/planning/scenarios")
def plan_list(fy: str, ctx: OrgContext = Ctx, db: Session = Db, a: Access = Acc):
    return planning.scenarios(db, ctx, fy)


@router.post("/planning/scenarios")
def plan_save(body: dict = Body(...), ctx: OrgContext = Ctx, db: Session = Db, a: Access = Acc):
    s = planning.save_scenario(db, ctx, a, body.get("fy", ""), body.get("name", ""), body.get("levers") or [], body.get("projected_profit"))
    db.commit()
    return dict(id=s.id, result=s.result)


@router.delete("/planning/scenarios/{sid}")
def plan_del(sid: int, ctx: OrgContext = Ctx, db: Session = Db, a: Access = Acc):
    planning.delete_scenario(db, ctx, a, sid)
    db.commit()
    return {"ok": True}


@router.get("/reconcile")
def reconcile(date_from: str, date_to: str, ctx: OrgContext = Ctx, db: Session = Db, a: Access = Acc):
    f, t = _d(date_from, "date_from"), _d(date_to, "date_to")
    if not f or not t or t < f:
        raise HTTPException(422, "date_from and date_to are required and the end cannot be before the start")
    return overview.reconcile(db, ctx, f, t)


@router.get("/readiness")
def readiness(kind: str, doc_id: int, ctx: OrgContext = Ctx, db: Session = Db, a: Access = Acc):
    return overview.readiness(db, ctx, kind, doc_id)


@router.get("/reports/summary")
def report_summary(fy: str, ctx: OrgContext = Ctx, db: Session = Db, a: Access = Acc):
    return overview.summary_pack(db, ctx, fy)


@router.get("/reports/export")
def report_export(what: str, fy: str = "", doc_id: Optional[int] = None, ctx: OrgContext = Ctx, db: Session = Db, a: Access = Acc):
    name, text = overview.export_csv(db, ctx, what, fy, doc_id)
    return Response(text, media_type="text/csv; charset=utf-8", headers={"Content-Disposition": f'attachment; filename="{name}"'})


@router.get("/reports/xlsx")
def report_xlsx(fy: str, ctx: OrgContext = Ctx, db: Session = Db, a: Access = Acc):
    data = overview.export_xlsx(db, ctx, fy)
    return Response(data, media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", headers={"Content-Disposition": f'attachment; filename="tax_summary_{fy}.xlsx"'})


@router.get("/audit")
def audit(limit: int = Query(100, ge=1, le=500), entity_type: str = "", before_seq: Optional[int] = None, ctx: OrgContext = Ctx, db: Session = Db, a: Access = Acc):
    a.require("audit_view")
    return overview.audit(db, ctx, limit, entity_type, before_seq)


@router.get("/audit/verify")
def audit_verify(ctx: OrgContext = Ctx, db: Session = Db, a: Access = Acc):
    a.require("audit_view")
    return core.verify_audit(db, ctx.org.id)
