"""GET /admin/org-directory - every organisation with its contact details, licence and users (platform administrators only).

  organisations[]   org_id, name, is_active, admin{user_id, name, email, phone}, licence{plan_id, plan_name, status, seats, active_users, pending_codes, period_end},
                    user_count, users[] {user_id, username, full_name, email, phone, role, suspended, protected}
  unassigned_users  users who belong to no organisation (legacy accounts)
  platform_admins   the AccFino administrator account(s): shown for reference, NEVER deletable (protected = true)

The /admin/ prefix is admin-guarded by the auth middleware and every call re-checks it.
"""
from fastapi import APIRouter, Depends, HTTPException, Request, Response
from sqlalchemy.orm import Session

from accfino_core import force_delete as FD
from accfino_core import models as m
from accfino_core import org_admin as OA
from accfino_core.security import contact as C
from accfino_core.security.context import current_auth
from accfino_core.subscription import service as S
from accfino_core.subscription.models import OrgSubscription
from accfino_core.tenancy import service as T
from db_app.database import get_db
from db_app.models.user import User

router = APIRouter()

ROLE_LABEL = {"owner": "Organisation Admin", "admin": "Admin (legacy)", "accountant": "Accountant", "bookkeeper": "Bookkeeper", "payroll": "Payroll", "readonly": "Read only"}


def _user_row(u: User, role: str = None, suspended: bool = False) -> dict:
    return {"user_id": u.id, "username": u.username, "full_name": u.full_name or "", "email": u.email or "", "phone": u.phone or "",
            "phone_display": C.format_phone(u.phone) if u.phone else "", "role": role, "role_label": ROLE_LABEL.get(role, role) if role else "",
            "suspended": bool(suspended), "protected": FD.is_protected_user(u)}


@router.get("")
def org_directory(request: Request, response: Response = None, db: Session = Depends(get_db)):
    if response is not None:
        response.headers["Cache-Control"] = "no-store"          # always the live list: a deleted row must never come back from a cache
    auth = current_auth(request)
    if not auth.get("is_admin"):
        raise HTTPException(403, "Administrators only")
    S.ensure_catalogue(db)
    db.commit()
    users = {u.id: u for u in db.query(User).all()}
    members = {}
    for mem in db.query(m.OrgMembership).order_by(m.OrgMembership.org_id, m.OrgMembership.id).all():
        members.setdefault(mem.org_id, []).append(mem)
    assigned = {mem.user_id for ms in members.values() for mem in ms}

    orgs = []
    for o in db.query(m.Organisation).order_by(m.Organisation.name, m.Organisation.id).all():
        ent = S.entitlements(db, o.id)
        seat = T.seat_status(db, o.id)
        sub = db.get(OrgSubscription, o.id)
        contact = OA.org_contact(db, o.id)
        rows = []
        for mem in sorted(members.get(o.id, []), key=lambda x: (x.role != m.ADMIN_ROLE, (users[x.user_id].full_name or users[x.user_id].username or "").lower() if x.user_id in users else "")):
            u = users.get(mem.user_id)
            if u is not None:
                rows.append(_user_row(u, mem.role, mem.suspended_at is not None))
        orgs.append({
            "org_id": o.id, "name": o.name, "is_active": o.is_active,
            "admin": {"user_id": contact["user_id"], "name": contact["name"] or "", "email": contact["email"] or "", "phone": contact["phone"] or "", "phone_display": contact["phone_display"] or ""},
            "licence": {"plan_id": ent["plan_id"], "plan_name": ent["plan_name"], "status": ent["status"], "grandfathered": ent["grandfathered"], "seats": seat["licensed"],
                        "active_users": seat["active"], "pending_codes": seat["pending"], "period_end": ent["period_end"], "trial_ends": ent["trial_ends"],
                        "billing_period": ent["billing_period"], "plan_status": sub.status if sub else None},
            "user_count": len(rows), "users": rows,
        })
    platform_admins = [_user_row(u) for u in users.values() if FD.is_protected_user(u)]
    unassigned = [_user_row(u) for u in users.values() if u.id not in assigned and not FD.is_protected_user(u)]
    unassigned.sort(key=lambda r: (r["full_name"] or r["username"]).lower())
    return {"organisations": orgs, "unassigned_users": unassigned, "platform_admins": platform_admins,
            "totals": {"organisations": len(orgs), "users": len(users)}}


@router.post("/prune-empty")
def prune_empty(request: Request, db: Session = Depends(get_db)):
    """Remove every organisation that has no users left (leftovers of deleted logins). Organisations holding posted journals are kept unless
    Force delete is switched on. Platform administrators only."""
    auth = current_auth(request)
    if not auth.get("is_admin"):
        raise HTTPException(403, "Administrators only")
    res = FD.prune_empty_orgs(db, None, force=FD.force_delete_enabled(db))
    db.commit()
    return res


@router.post("/prune-orphan-users")
def prune_orphan_users(request: Request, db: Session = Depends(get_db)):
    """Delete logins that belong to no organisation (leftovers of deleted organisations). The AccFino administrator and the caller are never
    removed. A login that still has linked records is kept unless Force delete is switched on. Platform administrators only."""
    auth = current_auth(request)
    if not auth.get("is_admin"):
        raise HTTPException(403, "Administrators only")
    force = FD.force_delete_enabled(db)
    member_ids = {r[0] for r in db.query(m.OrgMembership.user_id).all()}
    removed, skipped = [], []
    candidates = [u for u in db.query(User).order_by(User.id).all()
                  if u.id not in member_ids and not FD.is_protected_user(u) and u.id != auth.get("user_id")]
    for u in candidates:
        uid, uname, uemail = u.id, u.username, u.email            # read BEFORE deleting: the delete expires every loaded object
        try:
            with db.begin_nested():
                FD.delete_user(db, uid, actor_id=auth.get("user_id"), force=force)
            removed.append({"id": uid, "username": uname, "email": uemail})
        except HTTPException as e:
            skipped.append({"id": uid, "username": uname, "reason": str(e.detail)})
    db.commit()
    return {"removed": removed, "skipped": skipped}
