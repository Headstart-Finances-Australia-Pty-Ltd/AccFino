"""Subscription billing through Square.

  AccFino administrator (/admin/billing/*, admin-guarded):
    GET  /admin/billing/square           status of the platform's Square account (never the token)
    PUT  /admin/billing/square           {application_id, location_id, access_token?, environment, clear?}   blank token keeps the saved one
    POST /admin/billing/square/test      ask Square for the location with the saved settings
    GET  /admin/billing/overview         every organisation's card / next charge / last result + recent charges
    POST /admin/billing/run              run the renewal pass now

  Organisation (/org/current/billing/*; Organisation Admin manages, members can see):
    GET    /org/current/billing          card, plan, next charge, history, and what the browser needs to show Square's card form
    POST   /org/current/billing/card     {source_id}  save / replace the card
    DELETE /org/current/billing/card     remove the card (turns automatic renewal off)
    POST   /org/current/billing/subscribe  {billing_period}  turn automatic renewal on and pay the first period now
    POST   /org/current/billing/auto-renew {enabled}
"""
from fastapi import APIRouter, Body, Depends, HTTPException, Request
from sqlalchemy.orm import Session

from accfino.modules.billing import service as B
from accfino.core.subscription.models import OrgSubscription
from accfino.core.security import audit
from accfino.core.security.context import OrgContext, current_auth, current_org
from accfino.core.security.login import client_ip
from accfino.shared.db.database import SessionLocal, get_db

admin_router = APIRouter()
org_router = APIRouter()


def _admin(request: Request) -> dict:
    auth = current_auth(request)
    if not auth.get("is_admin"):
        raise HTTPException(403, "Administrators only")
    return auth


def _fail(e: B.BillingError):
    raise HTTPException(e.status, e.message)


# ----------------------------------------------------------------------------------------------------------------- platform --
@admin_router.get("/square")
def square_status(request: Request, db: Session = Depends(get_db)):
    _admin(request)
    return B.square_status(db)


@admin_router.put("/square")
def square_save(request: Request, body: dict = Body(...), db: Session = Depends(get_db)):
    auth = _admin(request)
    if B.SquareCfg(db).locked and (body.get("access_token") or body.get("clear")):
        raise HTTPException(409, "The Square token is set by the server environment (SQUARE_ACCESS_TOKEN) and can't be changed here.")
    try:
        B.save_square(db, access_token=body.get("access_token"), application_id=body.get("application_id"), location_id=body.get("location_id"),
                      environment=body.get("environment"), clear=bool(body.get("clear")))
    except B.BillingError as e:
        _fail(e)
    db.commit()
    audit.write("billing.square_saved", user_id=auth.get("user_id"), username=auth.get("username"), entity="square", ip=client_ip(request))
    return B.square_status(db)


@admin_router.post("/square/test")
def square_test(request: Request, db: Session = Depends(get_db)):
    _admin(request)
    return B.test_square(db)


@admin_router.get("/overview")
def overview(request: Request, db: Session = Depends(get_db)):
    _admin(request)
    return B.admin_overview(db)


@admin_router.post("/run")
def run_now(request: Request):
    _admin(request)
    from accfino.modules.billing import runner
    return runner.run_once()


# --------------------------------------------------------------------------------------------------------------- organisation --
@org_router.get("")
def my_billing(ctx: OrgContext = Depends(current_org), db: Session = Depends(get_db)):
    out = B.org_view(db, ctx.org.id)
    out["can_manage"] = ctx.is_org_admin
    return out


@org_router.post("/card")
def save_card(request: Request, body: dict = Body(...), ctx: OrgContext = Depends(current_org), db: Session = Depends(get_db)):
    ctx.require_org_admin()
    try:
        b = B.save_card(db, ctx.org, ctx.user_id, str(body.get("source_id", "")))
        retried = None
        sub = db.get(OrgSubscription, ctx.org.id)
        if sub is not None and sub.status == "past_due" and b.auto_renew:              # a new card fixes a failed renewal straight away
            retried = B.charge_now(db, ctx.org.id)
        db.commit()
    except B.BillingError as e:
        db.rollback()
        _fail(e)
    audit.write("billing.card_saved", user_id=ctx.user_id, username=ctx.username, org_id=ctx.org.id, entity="square_card", ip=client_ip(request))
    return {"ok": True, "retried": retried, **B.org_view(db, ctx.org.id)}


@org_router.delete("/card")
def delete_card(request: Request, ctx: OrgContext = Depends(current_org), db: Session = Depends(get_db)):
    ctx.require_org_admin()
    B.remove_card(db, ctx.org.id)
    db.commit()
    audit.write("billing.card_removed", user_id=ctx.user_id, username=ctx.username, org_id=ctx.org.id, entity="square_card", ip=client_ip(request))
    return {"ok": True}


@org_router.post("/subscribe")
def subscribe(request: Request, body: dict = Body(...), ctx: OrgContext = Depends(current_org), db: Session = Depends(get_db)):
    ctx.require_org_admin()
    try:
        res = B.subscribe(db, ctx.org.id, str(body.get("billing_period", "")), ctx.user_id)
        db.commit()
    except B.BillingError as e:
        db.rollback()
        _fail(e)
    audit.write("billing.subscribed", user_id=ctx.user_id, username=ctx.username, org_id=ctx.org.id, entity="subscription", detail=str(res.get("status")), ip=client_ip(request))
    if res.get("status") == "failed":
        raise HTTPException(402, "The payment was declined: " + str(res.get("error")) + " Please try another card.")
    return {"charge": res, **B.org_view(db, ctx.org.id)}                       # "charge" = what just happened; the rest is the refreshed billing view


@org_router.post("/auto-renew")
def auto_renew(body: dict = Body(...), ctx: OrgContext = Depends(current_org), db: Session = Depends(get_db)):
    ctx.require_org_admin()
    b = B.get_billing(db, ctx.org.id)
    if bool(body.get("enabled")) and not b.card_id:
        raise HTTPException(409, "Add a card first.")
    b.auto_renew, b.updated_by = bool(body.get("enabled")), ctx.user_id
    if b.auto_renew:
        b.failure_count, b.next_attempt_on = 0, None
    db.commit()
    return B.org_view(db, ctx.org.id)
