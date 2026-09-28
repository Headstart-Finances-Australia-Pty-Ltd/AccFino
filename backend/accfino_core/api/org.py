"""/org: organisations, settings, lock date and members."""
import re
from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy.orm import Session

from accfino_core import models as m
from accfino_core.migrate import seed_org_ledger
from accfino_core.security import audit
from accfino_core.security.context import OrgContext, current_auth, current_org
from accfino_core.security.login import client_ip, org_summaries
from db_app.database import get_db
from db_app.models.user import User

router = APIRouter()

ENTITY_TYPES = ("company", "trust", "partnership", "sole_trader", "smsf", "other")
_ABN_WEIGHTS = (10, 1, 3, 5, 7, 9, 11, 13, 15, 17, 19)


def valid_abn(abn: str) -> bool:
    digits = re.sub(r"\s", "", abn or "")
    if not re.fullmatch(r"\d{11}", digits):
        return False
    nums = [int(c) for c in digits]
    nums[0] -= 1
    return sum(w * n for w, n in zip(_ABN_WEIGHTS, nums)) % 89 == 0


def org_dict(o, role=None):
    return {"id": o.id, "name": o.name, "legal_name": o.legal_name, "abn": o.abn,
            "entity_type": o.entity_type, "base_currency": o.base_currency,
            "gst_registered": o.gst_registered, "gst_basis": o.gst_basis,
            "fy_end_month": o.fy_end_month, "lock_date": o.lock_date.isoformat() if o.lock_date else None,
            "role": role}


class OrgCreate(BaseModel):
    name: str
    legal_name: str | None = None
    abn: str | None = None
    entity_type: str | None = None


class OrgPatch(BaseModel):
    name: str | None = None
    legal_name: str | None = None
    abn: str | None = None
    entity_type: str | None = None
    gst_registered: bool | None = None
    gst_basis: str | None = None
    fy_end_month: int | None = None


class LockIn(BaseModel):
    lock_date: date | None


class MemberIn(BaseModel):
    email: str
    role: str = "readonly"


class RoleIn(BaseModel):
    role: str


def _validate(p):
    if p.abn not in (None, "") and not valid_abn(p.abn):
        raise HTTPException(422, "ABN is not valid (checksum failed)")
    if getattr(p, "entity_type", None) and p.entity_type not in ENTITY_TYPES:
        raise HTTPException(422, f"entity_type must be one of {', '.join(ENTITY_TYPES)}")
    if getattr(p, "gst_basis", None) and p.gst_basis not in ("accrual", "cash"):
        raise HTTPException(422, "gst_basis must be accrual or cash")
    if getattr(p, "fy_end_month", None) is not None and not 1 <= p.fy_end_month <= 12:
        raise HTTPException(422, "fy_end_month must be 1-12")


@router.get("/mine")
def my_orgs(request: Request, db: Session = Depends(get_db)):
    return org_summaries(db, current_auth(request)["user_id"])


@router.post("")
def create_org(body: OrgCreate, request: Request, db: Session = Depends(get_db)):
    auth = current_auth(request)
    _validate(body)
    if not body.name.strip():
        raise HTTPException(422, "Name is required")
    o = m.Organisation(name=body.name.strip()[:255], legal_name=body.legal_name, entity_type=body.entity_type,
                       abn=re.sub(r"\s", "", body.abn) if body.abn else None)
    db.add(o)
    db.flush()
    db.add(m.OrgMembership(org_id=o.id, user_id=auth["user_id"], role="owner", is_default=False))
    seed_org_ledger(db, o)
    db.commit()
    audit.write("org.created", user_id=auth["user_id"], username=auth["username"], org_id=o.id,
                entity="organisation", entity_id=o.id, ip=client_ip(request))
    return org_dict(o, "owner")


@router.get("/current")
def get_current(ctx: OrgContext = Depends(current_org)):
    return org_dict(ctx.org, ctx.role)


@router.patch("/current")
def patch_current(body: OrgPatch, request: Request, ctx: OrgContext = Depends(current_org),
                  db: Session = Depends(get_db)):
    ctx.require("settings")
    _validate(body)
    changes = body.model_dump(exclude_unset=True)
    if "abn" in changes and changes["abn"]:
        changes["abn"] = re.sub(r"\s", "", changes["abn"])
    before = org_dict(ctx.org)
    for k, v in changes.items():
        setattr(ctx.org, k, v)
    db.commit()
    audit.write("org.updated", user_id=ctx.user_id, username=ctx.username, org_id=ctx.org.id,
                entity="organisation", entity_id=ctx.org.id, ip=client_ip(request),
                detail={"before": before, "changes": {k: str(v) for k, v in changes.items()}})
    return org_dict(ctx.org, ctx.role)


@router.post("/current/lock-date")
def set_lock_date(body: LockIn, request: Request, ctx: OrgContext = Depends(current_org),
                  db: Session = Depends(get_db)):
    ctx.require("settings")
    old = ctx.org.lock_date
    ctx.org.lock_date = body.lock_date
    db.commit()
    audit.write("org.lock_date_changed", user_id=ctx.user_id, username=ctx.username, org_id=ctx.org.id,
                entity="organisation", entity_id=ctx.org.id, ip=client_ip(request),
                detail={"from": old.isoformat() if old else None,
                        "to": body.lock_date.isoformat() if body.lock_date else None})
    return org_dict(ctx.org, ctx.role)


@router.get("/current/members")
def members(ctx: OrgContext = Depends(current_org), db: Session = Depends(get_db)):
    rows = db.query(m.OrgMembership, User).join(User, User.id == m.OrgMembership.user_id) \
        .filter(m.OrgMembership.org_id == ctx.org.id).order_by(User.username).all()
    return [{"user_id": u.id, "username": u.username, "name": u.full_name, "email": u.email, "role": mem.role}
            for mem, u in rows]


@router.post("/current/members")
def add_member(body: MemberIn, request: Request, ctx: OrgContext = Depends(current_org),
               db: Session = Depends(get_db)):
    ctx.require("members")
    if body.role not in m.ORG_ROLES:
        raise HTTPException(422, f"role must be one of {', '.join(m.ORG_ROLES)}")
    if body.role == "owner" and ctx.role != "owner" and not ctx.is_admin:
        raise HTTPException(403, "Only an owner can add another owner")
    u = db.query(User).filter(User.email == body.email.strip()).first()
    if u is None:
        raise HTTPException(404, "No AccFino user with that email. Ask them to register first.")
    if db.query(m.OrgMembership).filter_by(org_id=ctx.org.id, user_id=u.id).first():
        raise HTTPException(409, "That user is already a member")
    db.add(m.OrgMembership(org_id=ctx.org.id, user_id=u.id, role=body.role, is_default=False))
    db.commit()
    audit.write("org.member_added", user_id=ctx.user_id, username=ctx.username, org_id=ctx.org.id,
                entity="user", entity_id=u.id, ip=client_ip(request), detail={"role": body.role})
    return {"ok": True}


def _owners(db, org_id):
    return db.query(m.OrgMembership).filter_by(org_id=org_id, role="owner").count()


@router.patch("/current/members/{member_user_id}")
def change_role(member_user_id: int, body: RoleIn, request: Request, ctx: OrgContext = Depends(current_org),
                db: Session = Depends(get_db)):
    ctx.require("members")
    if body.role not in m.ORG_ROLES:
        raise HTTPException(422, f"role must be one of {', '.join(m.ORG_ROLES)}")
    mem = db.query(m.OrgMembership).filter_by(org_id=ctx.org.id, user_id=member_user_id).first()
    if mem is None:
        raise HTTPException(404, "Member not found")
    if (mem.role == "owner" or body.role == "owner") and ctx.role != "owner" and not ctx.is_admin:
        raise HTTPException(403, "Only an owner can change owner roles")
    if mem.role == "owner" and body.role != "owner" and _owners(db, ctx.org.id) <= 1:
        raise HTTPException(409, "An organisation must keep at least one owner")
    old = mem.role
    mem.role = body.role
    db.commit()
    audit.write("org.member_role_changed", user_id=ctx.user_id, username=ctx.username, org_id=ctx.org.id,
                entity="user", entity_id=member_user_id, ip=client_ip(request), detail={"from": old, "to": body.role})
    return {"ok": True}


@router.delete("/current/members/{member_user_id}")
def remove_member(member_user_id: int, request: Request, ctx: OrgContext = Depends(current_org),
                  db: Session = Depends(get_db)):
    ctx.require("members")
    mem = db.query(m.OrgMembership).filter_by(org_id=ctx.org.id, user_id=member_user_id).first()
    if mem is None:
        raise HTTPException(404, "Member not found")
    if mem.role == "owner" and _owners(db, ctx.org.id) <= 1:
        raise HTTPException(409, "An organisation must keep at least one owner")
    if mem.is_default:
        raise HTTPException(409, "This is the member's personal default organisation and cannot be removed")
    db.delete(mem)
    db.commit()
    audit.write("org.member_removed", user_id=ctx.user_id, username=ctx.username, org_id=ctx.org.id,
                entity="user", entity_id=member_user_id, ip=client_ip(request))
    return {"ok": True}
