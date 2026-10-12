"""/org: organisations, settings, lock date and members.

Everything that ADMINISTERS the organisation (details, lock date, users, roles, transfer, dashboard) needs the Organisation Admin - the organisation's
single 'owner' - and is checked on the server for every call (ctx.require_org_admin()). Other members can read the organisation's name and their own role.
"""
import re
from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy import func
from sqlalchemy.orm import Session

from accfino.core import models as m
from accfino.core import notifications as N
from accfino.core.identity import org_admin as OA
from accfino.shared.contracts import registry
from accfino.core.security import audit
from accfino.core.security.context import OrgContext, current_auth, current_org
from accfino.core.security.login import client_ip, org_summaries
from accfino.shared.db.database import get_db
from accfino.core.identity.user import User

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


class TransferIn(BaseModel):
    new_admin_user_id: int             # NB: not "user_id" - the auth guard requires any body field of that name to be the caller's own id
    password: str | None = None        # the current Organisation Admin re-enters their password to hand the organisation over


_ADMIN_ROLE_MSG = ("There is exactly one Organisation Admin per organisation and the role cannot be handed out like the others. "
                   "To change who it is, use 'Transfer admin'.")


def _check_assignable(role: str):
    if role in ("owner", "admin"):
        raise HTTPException(422, _ADMIN_ROLE_MSG)
    if role not in m.ASSIGNABLE_ROLES:
        raise HTTPException(422, f"role must be one of {', '.join(m.ASSIGNABLE_ROLES)}")


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
    OA.assign_first_admin(db, o, auth["user_id"], is_default=False)          # whoever creates an organisation is its Organisation Admin
    registry.provision_org(db, o)
    from accfino.core.subscription.service import start_subscription
    from accfino.core.tenancy.service import ensure_profile
    ensure_profile(db, o)                                         # its tenant address
    start_subscription(db, o.id)                                  # the platform's default plan (no effect while enforcement is off)
    db.commit()
    audit.write("org.created", user_id=auth["user_id"], username=auth["username"], org_id=o.id,
                entity="organisation", entity_id=o.id, ip=client_ip(request))
    from accfino.core.identity.user import User as _U
    N.org_created(db, o, db.get(_U, auth["user_id"]))
    return org_dict(o, "owner")


@router.get("/current")
def get_current(ctx: OrgContext = Depends(current_org), db: Session = Depends(get_db)):
    from accfino.core.tenancy import service as _T
    from accfino.core.tenancy.models import OrgProfile as _P
    c = OA.org_contact(db, ctx.org.id)
    out = org_dict(ctx.org, ctx.role)
    prof = db.get(_P, ctx.org.id)
    # The organisation's own web address (https://<name>.<TENANT_BASE_DOMAIN>) is for EVERY member: it is where they sign in. tenant_url is None until
    # TENANT_BASE_DOMAIN is configured for the installation (see docs/ORG_ADMIN.md).
    out.update(slug=prof.slug if prof else None, tenant_url=_T.tenant_url(prof.slug) if prof else None, tenant_urls_enabled=bool(_T.base_domain()))
    out.update(is_org_admin=ctx.is_org_admin, platform_admin=bool(ctx.is_admin), admin_name=c["name"])            # members see who to contact; email/phone are for the admin's own screens
    if ctx.is_org_admin:
        out.update(admin_email=c["email"], admin_phone=c["phone"], admin_user_id=c["user_id"])
    return out


@router.patch("/current")
def patch_current(body: OrgPatch, request: Request, ctx: OrgContext = Depends(current_org),
                  db: Session = Depends(get_db)):
    ctx.require_org_admin()
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
    N.settings_changed(db, ctx.org, ctx.username, "organisation details (" + ", ".join(sorted(changes)) + ")")
    return org_dict(ctx.org, ctx.role)


@router.post("/current/lock-date")
def set_lock_date(body: LockIn, request: Request, ctx: OrgContext = Depends(current_org),
                  db: Session = Depends(get_db)):
    ctx.require_org_admin()
    old = ctx.org.lock_date
    ctx.org.lock_date = body.lock_date
    db.commit()
    audit.write("org.lock_date_changed", user_id=ctx.user_id, username=ctx.username, org_id=ctx.org.id,
                entity="organisation", entity_id=ctx.org.id, ip=client_ip(request),
                detail={"from": old.isoformat() if old else None,
                        "to": body.lock_date.isoformat() if body.lock_date else None})
    N.settings_changed(db, ctx.org, ctx.username, f"the lock date ({old.isoformat() if old else 'none'} -> {body.lock_date.isoformat() if body.lock_date else 'none'})")
    return org_dict(ctx.org, ctx.role)


@router.get("/current/members")
def members(ctx: OrgContext = Depends(current_org), db: Session = Depends(get_db)):
    """User management list (includes contact details): Organisation Admin only."""
    ctx.require_org_admin()
    rows = db.query(m.OrgMembership, User).join(User, User.id == m.OrgMembership.user_id) \
        .filter(m.OrgMembership.org_id == ctx.org.id).order_by(User.username).all()
    return [{"user_id": u.id, "username": u.username, "name": u.full_name, "email": u.email, "phone": u.phone, "role": mem.role,
             "is_org_admin": mem.role == m.ADMIN_ROLE, "suspended": bool(mem.suspended_at)}
            for mem, u in rows]


@router.get("/current/directory")
def directory(ctx: OrgContext = Depends(current_org), db: Session = Depends(get_db)):
    """What any member may see of their colleagues: names and roles only - no email addresses or phone numbers."""
    rows = db.query(m.OrgMembership, User).join(User, User.id == m.OrgMembership.user_id) \
        .filter(m.OrgMembership.org_id == ctx.org.id, m.OrgMembership.suspended_at.is_(None)).order_by(User.full_name).all()
    return [{"user_id": u.id, "name": u.full_name or u.username, "role": mem.role} for mem, u in rows]


@router.get("/current/admin/overview")
def admin_overview(ctx: OrgContext = Depends(current_org), db: Session = Depends(get_db)):
    """The Organisation Admin dashboard: organisation, primary contact, licence usage, access-code counts."""
    ctx.require_org_admin()
    out = OA.overview(db, ctx.org)
    db.commit()
    return out


@router.post("/current/members")
def add_member(body: MemberIn, request: Request, ctx: OrgContext = Depends(current_org),
               db: Session = Depends(get_db)):
    ctx.require_org_admin()
    _check_assignable(body.role)
    u = db.query(User).filter(func.lower(User.email) == body.email.strip().lower()).first()
    if u is None:
        raise HTTPException(404, "No AccFino user with that email. Ask them to register first.")
    if db.query(m.OrgMembership).filter_by(org_id=ctx.org.id, user_id=u.id).first():
        raise HTTPException(409, "That user is already a member")
    from accfino.core.subscription.service import check_seat
    check_seat(db, ctx)                                           # plan seat limit
    db.add(m.OrgMembership(org_id=ctx.org.id, user_id=u.id, role=body.role, is_default=False))
    db.commit()
    audit.write("org.member_added", user_id=ctx.user_id, username=ctx.username, org_id=ctx.org.id,
                entity="user", entity_id=u.id, ip=client_ip(request), detail={"role": body.role})
    N.member_changed(db, ctx.org, ctx.username, u, "added", f"Role: {body.role}.")
    return {"ok": True}


def _owners(db, org_id):
    return db.query(m.OrgMembership).filter_by(org_id=org_id, role="owner").count()


@router.patch("/current/members/{member_user_id}")
def change_role(member_user_id: int, body: RoleIn, request: Request, ctx: OrgContext = Depends(current_org),
                db: Session = Depends(get_db)):
    ctx.require_org_admin()
    _check_assignable(body.role)
    mem = db.query(m.OrgMembership).filter_by(org_id=ctx.org.id, user_id=member_user_id).first()
    if mem is None:
        raise HTTPException(404, "Member not found")
    if mem.role == m.ADMIN_ROLE:
        raise HTTPException(409, "The Organisation Admin's role cannot be changed here. Use 'Transfer admin' to hand the organisation to someone else.")
    old = mem.role
    mem.role = body.role
    db.commit()
    audit.write("org.member_role_changed", user_id=ctx.user_id, username=ctx.username, org_id=ctx.org.id,
                entity="user", entity_id=member_user_id, ip=client_ip(request), detail={"from": old, "to": body.role})
    N.member_changed(db, ctx.org, ctx.username, db.get(User, member_user_id), "role_changed", f"{old} -> {body.role}.")
    return {"ok": True}


@router.delete("/current/members/{member_user_id}")
def remove_member(member_user_id: int, request: Request, ctx: OrgContext = Depends(current_org),
                  db: Session = Depends(get_db)):
    ctx.require_org_admin()
    mem = db.query(m.OrgMembership).filter_by(org_id=ctx.org.id, user_id=member_user_id).first()
    if mem is None:
        raise HTTPException(404, "Member not found")
    if mem.role == m.ADMIN_ROLE:
        raise HTTPException(409, "The Organisation Admin cannot be removed. Transfer the organisation to someone else first.")
    if mem.is_default:
        raise HTTPException(409, "This is the member's personal default organisation and cannot be removed")
    removed = db.get(User, member_user_id)
    db.delete(mem)
    db.commit()
    audit.write("org.member_removed", user_id=ctx.user_id, username=ctx.username, org_id=ctx.org.id,
                entity="user", entity_id=member_user_id, ip=client_ip(request))
    if removed is not None:
        N.member_changed(db, ctx.org, ctx.username, removed, "removed")
    return {"ok": True}


@router.post("/current/transfer-admin")
def transfer_admin(body: TransferIn, request: Request, ctx: OrgContext = Depends(current_org), db: Session = Depends(get_db)):
    """Hand the organisation to another active member. The previous Organisation Admin becomes an Accountant. Needs the current admin's password."""
    ctx.require_org_admin()
    if ctx.role == m.ADMIN_ROLE:                                            # AccFino support staff acting on someone else's organisation don't have that password
        import bcrypt
        me = db.get(User, ctx.user_id)
        if not body.password or not bcrypt.checkpw(body.password.encode(), me.password.encode()):
            raise HTTPException(401, "Your password is incorrect")
    old_admin = OA.admin_user(db, ctx.org.id)
    OA.transfer_admin(db, ctx.org, old_admin.id if old_admin else 0, body.new_admin_user_id)
    db.commit()
    from accfino.core.security import iam
    for uid in {body.new_admin_user_id, old_admin.id if old_admin else 0}:
        iam.forget(("role", uid, ctx.org.id))
    audit.write("org.admin_transferred", user_id=ctx.user_id, username=ctx.username, org_id=ctx.org.id, entity="user", entity_id=body.new_admin_user_id,
                ip=client_ip(request), detail={"from_user_id": old_admin.id if old_admin else None, "to_user_id": body.new_admin_user_id})
    new_admin = db.get(User, body.new_admin_user_id)
    if old_admin is not None:
        N.admin_transferred(db, ctx.org, old_admin, new_admin)
    return {"ok": True}
