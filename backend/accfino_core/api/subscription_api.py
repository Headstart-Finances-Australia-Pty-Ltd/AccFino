"""Subscriptions per organisation.

  GET  /org/current/subscription            any member: plan, modules, locked modules, seats, plus the plan/add-on catalogue for comparison
  POST /org/current/subscription/request    Organisation Admin only: ask for a plan change or an add-on (recorded in the audit log for the platform admin)

  Platform administrators only (/admin/ is admin-guarded by the auth middleware, and re-checked here):
  GET  /admin/subscriptions                 settings + plans + add-ons + every organisation's subscription
  PUT  /admin/subscriptions/settings        {enforced, default_plan}
  PUT/DELETE /admin/subscriptions/plans/{id}, /addons/{id}
  PUT  /admin/subscriptions/orgs/{org_id}   assign plan / add-ons / status / dates
"""
import json
import re
from datetime import date
from decimal import Decimal, InvalidOperation
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy.orm import Session

from accfino_core import models as m
from accfino_core import notifications as N
from accfino_core.security import audit
from accfino_core.security.context import OrgContext, current_auth, current_org
from accfino_core.security.login import client_ip
from accfino_core.subscription import service as S
from accfino_core.subscription import align as AL
from accfino_core.subscription.models import Addon, OrgSubscription, Plan
from db_app.database import get_db

org_router = APIRouter()
admin_router = APIRouter()
_SLUG = re.compile(r"^[a-z0-9][a-z0-9-]{1,38}$")
_STATUSES = ("trial", "active", "past_due", "cancelled", "expired")


def _plan_dict(p):
    return dict(id=p.id, name=p.name, description=p.description or "", price_monthly=str(p.price_monthly), price_yearly=str(p.price_yearly), seat_limit=p.seat_limit,
                modules=S._loads(p.modules), is_active=p.is_active, sort_order=p.sort_order)


def _addon_dict(a):
    return dict(id=a.id, name=a.name, description=a.description or "", price_monthly=str(a.price_monthly), modules=S._loads(a.modules), extra_seats=a.extra_seats or 0,
                is_active=a.is_active, sort_order=a.sort_order)


# ------------------------------------------------------------------------------------------ the organisation's own view
@org_router.get("")
def my_subscription(ctx: OrgContext = Depends(current_org), db: Session = Depends(get_db)):
    ent = S.entitlements(db, ctx.org.id)
    db.commit()                                         # ensure_catalogue may have created the starting plans
    return {**ent, "can_manage": ctx.is_org_admin,
            "plans": [_plan_dict(p) for p in db.query(Plan).filter_by(is_active=True).order_by(Plan.sort_order)],
            "addon_catalogue": [_addon_dict(a) for a in db.query(Addon).filter_by(is_active=True).order_by(Addon.sort_order)]}


class RequestIn(BaseModel):
    plan_id: Optional[str] = None
    addon_ids: List[str] = []
    message: Optional[str] = None


@org_router.post("/request")
def request_change(body: RequestIn, request: Request, ctx: OrgContext = Depends(current_org), db: Session = Depends(get_db)):
    ctx.require_org_admin()                             # licence / subscription settings: the Organisation Admin only
    if body.plan_id and db.get(Plan, body.plan_id) is None:
        raise HTTPException(404, "Unknown plan")
    for a in body.addon_ids:
        if db.get(Addon, a) is None:
            raise HTTPException(404, f"Unknown add-on '{a}'")
    audit.write("subscription.change_requested", user_id=ctx.user_id, username=ctx.username, org_id=ctx.org.id, entity="subscription", entity_id=ctx.org.id, ip=client_ip(request),
                detail=dict(plan_id=body.plan_id, addon_ids=body.addon_ids, message=(body.message or "")[:500]))
    N.notify_org_admin(db, ctx.org.id, "subscription_requested", "Your plan change request was recorded",
                       f"A plan change was requested for {ctx.org.name} (plan: {body.plan_id or 'unchanged'}; add-ons: {', '.join(body.addon_ids) or 'none'}). "
                       "Your platform administrator will confirm it; you will be told when it is applied.")
    return {"ok": True, "message": "Your request has been recorded. Your platform administrator will confirm the change; it takes effect immediately once applied."}


# ------------------------------------------------------------------------------------------ platform administrator
def _admin(request: Request):
    auth = current_auth(request)
    if not auth.get("is_admin"):
        raise HTTPException(403, "Administrators only")
    return auth


def _modules(raw):
    mods = list(dict.fromkeys(raw or []))
    bad = [x for x in mods if x != "*" and x not in S.CATALOGUE_IDS and not (isinstance(x, str) and x.startswith("domain:") and x[7:] in S.DOMAIN_IDS)]
    if bad:
        raise HTTPException(422, f"Unknown module(s): {', '.join(bad)}. Use a module id, domain:<id> ({', '.join(S.DOMAIN_IDS)}) or *")
    return mods


def _price(v, what):
    try:
        d = Decimal(str(v if v not in (None, "") else 0))
    except InvalidOperation:
        raise HTTPException(422, f"{what} is not a number")
    if d < 0 or d > Decimal("99999999"):
        raise HTTPException(422, f"{what} must be 0 or more")
    return d.quantize(Decimal("0.01"))


@admin_router.get("")
def admin_overview(request: Request, db: Session = Depends(get_db)):
    _admin(request)
    S.ensure_catalogue(db)
    db.commit()
    orgs = []
    for o in db.query(m.Organisation).order_by(m.Organisation.id):
        sub = db.get(OrgSubscription, o.id)
        orgs.append(dict(org_id=o.id, name=o.name, is_active=o.is_active, members=S.member_count(db, o.id), plan_id=sub.plan_id if sub else None,
                         addons=S._loads(sub.addons) if sub else [], status=sub.status if sub else None, billing_period=sub.billing_period if sub else None,
                         trial_ends=sub.trial_ends.isoformat() if sub and sub.trial_ends else None, period_end=sub.period_end.isoformat() if sub and sub.period_end else None,
                         notes=sub.notes if sub else None, effective_status=S.entitlements(db, o.id)["status"]))
    return {"settings": S.get_settings(db), "catalogue": [dict(id=i, name=n) for i, n in S.CATALOGUE], "features": [dict(id=i, name=n, description=d) for i, n, d in S.FEATURES], "domains": [dict(id=i, name=n, modules=ms) for i, n, ms in S.DOMAINS],
            "plans": [_plan_dict(p) for p in db.query(Plan).order_by(Plan.sort_order)], "addons": [_addon_dict(a) for a in db.query(Addon).order_by(Addon.sort_order)],
            "organisations": orgs}


class SettingsIn(BaseModel):
    enforced: Optional[bool] = None
    default_plan: Optional[str] = None


@admin_router.put("/settings")
def admin_settings(body: SettingsIn, request: Request, db: Session = Depends(get_db)):
    auth = _admin(request)
    if body.default_plan is not None and db.get(Plan, body.default_plan) is None:
        raise HTTPException(404, "Unknown plan")
    S.set_settings(db, body.enforced, body.default_plan)
    db.commit()
    audit.write("admin.subscription_settings", user_id=auth["user_id"], username=auth["username"], entity="system", entity_id="subscriptions", ip=client_ip(request),
                detail=body.model_dump(exclude_none=True))
    return S.get_settings(db)


class PlanIn(BaseModel):
    name: str
    description: Optional[str] = None
    price_monthly: Optional[str] = "0"
    price_yearly: Optional[str] = "0"
    seat_limit: Optional[int] = None
    modules: List[str] = []
    is_active: bool = True
    sort_order: int = 0


@admin_router.put("/plans/{plan_id}")
def admin_save_plan(plan_id: str, body: PlanIn, request: Request, db: Session = Depends(get_db)):
    auth = _admin(request)
    if not _SLUG.match(plan_id):
        raise HTTPException(422, "Plan id: lower-case letters, digits and dashes (2-39 characters)")
    if not body.name.strip():
        raise HTTPException(422, "Name is required")
    if body.seat_limit is not None and body.seat_limit < 1:
        raise HTTPException(422, "Seat limit must be 1 or more (leave blank for unlimited)")
    monthly, yearly, mods = _price(body.price_monthly, "Monthly price"), _price(body.price_yearly, "Yearly price"), _modules(body.modules)      # validate everything before touching the session
    p = db.get(Plan, plan_id)
    if p is None:
        p = Plan(id=plan_id)
        db.add(p)
    p.name, p.description, p.seat_limit, p.is_active, p.sort_order = body.name.strip()[:100], body.description, body.seat_limit, body.is_active, body.sort_order
    p.price_monthly, p.price_yearly, p.modules = monthly, yearly, json.dumps(mods)
    AL.sync_pricing_plans(db)                                   # the old plan table follows the plans
    db.commit()
    audit.write("admin.plan_saved", user_id=auth["user_id"], username=auth["username"], entity="plan", entity_id=plan_id, ip=client_ip(request), detail=_plan_dict(p))
    return _plan_dict(p)


@admin_router.delete("/plans/{plan_id}")
def admin_delete_plan(plan_id: str, request: Request, db: Session = Depends(get_db)):
    auth = _admin(request)
    p = db.get(Plan, plan_id)
    if p is None:
        raise HTTPException(404, "Plan not found")
    used = db.query(OrgSubscription).filter_by(plan_id=plan_id).count()
    if used:
        raise HTTPException(409, f"{used} organisation(s) are on this plan. Move them to another plan first (or untick Active to stop new sign-ups).")
    if S.get_settings(db)["default_plan"] == plan_id:
        raise HTTPException(409, "This is the default plan for new organisations. Choose another default first.")
    db.delete(p)
    AL.sync_pricing_plans(db)                                   # the old plan table follows the plans
    db.commit()
    audit.write("admin.plan_deleted", user_id=auth["user_id"], username=auth["username"], entity="plan", entity_id=plan_id, ip=client_ip(request))
    return {"ok": True}


class AddonIn(BaseModel):
    name: str
    description: Optional[str] = None
    price_monthly: Optional[str] = "0"
    modules: List[str] = []
    extra_seats: int = 0
    is_active: bool = True
    sort_order: int = 0


@admin_router.put("/addons/{addon_id}")
def admin_save_addon(addon_id: str, body: AddonIn, request: Request, db: Session = Depends(get_db)):
    auth = _admin(request)
    if not _SLUG.match(addon_id):
        raise HTTPException(422, "Add-on id: lower-case letters, digits and dashes (2-39 characters)")
    if not body.name.strip():
        raise HTTPException(422, "Name is required")
    if body.extra_seats < 0:
        raise HTTPException(422, "Extra seats cannot be negative")
    price, mods = _price(body.price_monthly, "Monthly price"), [x for x in _modules(body.modules) if x != "*"]
    a = db.get(Addon, addon_id)
    if a is None:
        a = Addon(id=addon_id)
        db.add(a)
    a.name, a.description, a.extra_seats, a.is_active, a.sort_order = body.name.strip()[:100], body.description, body.extra_seats, body.is_active, body.sort_order
    a.price_monthly, a.modules = price, json.dumps(mods)
    db.commit()
    audit.write("admin.addon_saved", user_id=auth["user_id"], username=auth["username"], entity="addon", entity_id=addon_id, ip=client_ip(request), detail=_addon_dict(a))
    return _addon_dict(a)


@admin_router.delete("/addons/{addon_id}")
def admin_delete_addon(addon_id: str, request: Request, db: Session = Depends(get_db)):
    auth = _admin(request)
    a = db.get(Addon, addon_id)
    if a is None:
        raise HTTPException(404, "Add-on not found")
    used = sum(1 for s in db.query(OrgSubscription) if addon_id in S._loads(s.addons))
    if used:
        raise HTTPException(409, f"{used} organisation(s) use this add-on. Remove it from them first (or untick Active).")
    db.delete(a)
    db.commit()
    audit.write("admin.addon_deleted", user_id=auth["user_id"], username=auth["username"], entity="addon", entity_id=addon_id, ip=client_ip(request))
    return {"ok": True}


class OrgSubIn(BaseModel):
    plan_id: str
    addons: List[str] = []
    status: str = "active"
    billing_period: str = "monthly"
    trial_ends: Optional[date] = None
    period_end: Optional[date] = None
    notes: Optional[str] = None


@admin_router.put("/orgs/{org_id}")
def admin_assign(org_id: int, body: OrgSubIn, request: Request, db: Session = Depends(get_db)):
    auth = _admin(request)
    if db.get(m.Organisation, org_id) is None:
        raise HTTPException(404, "Organisation not found")
    if db.get(Plan, body.plan_id) is None:
        raise HTTPException(404, "Unknown plan")
    for a in body.addons:
        if db.get(Addon, a) is None:
            raise HTTPException(404, f"Unknown add-on '{a}'")
    if body.status not in _STATUSES:
        raise HTTPException(422, f"status must be one of {', '.join(_STATUSES)}")
    if body.billing_period not in ("monthly", "yearly"):
        raise HTTPException(422, "billing_period must be monthly or yearly")
    sub = db.get(OrgSubscription, org_id)
    before = dict(plan_id=sub.plan_id, addons=S._loads(sub.addons), status=sub.status) if sub else None
    if sub is None:
        sub = OrgSubscription(org_id=org_id, plan_id=body.plan_id)
        db.add(sub)
    sub.plan_id, sub.addons, sub.status, sub.billing_period = body.plan_id, json.dumps(list(dict.fromkeys(body.addons))), body.status, body.billing_period
    sub.trial_ends, sub.period_end, sub.notes, sub.updated_by = body.trial_ends, body.period_end, body.notes, auth["user_id"]
    db.commit()
    audit.write("admin.subscription_assigned", user_id=auth["user_id"], username=auth["username"], org_id=org_id, entity="subscription", entity_id=org_id, ip=client_ip(request),
                detail=dict(before=before, after=dict(plan_id=sub.plan_id, addons=body.addons, status=sub.status)))
    changed = before is None or before["plan_id"] != sub.plan_id or before["status"] != sub.status or before["addons"] != list(dict.fromkeys(body.addons))
    if changed:                                          # licence / subscription communication goes to the Organisation Admin
        plan = db.get(Plan, sub.plan_id)
        N.subscription_changed(db, org_id, sub.status, plan.name if plan else sub.plan_id, "Your subscription was updated by your platform administrator.")
    return S.entitlements(db, org_id)
