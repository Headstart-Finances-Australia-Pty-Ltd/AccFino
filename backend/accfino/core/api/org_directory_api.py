"""GET /admin/org-directory - every organisation with its contact details, licence and users (platform administrators only).

  organisations[]   org_id, name, is_active, admin{user_id, name, email, phone}, licence{plan_id, plan_name, status, seats, active_users, pending_codes, period_end},
                    user_count, users[] {user_id, username, full_name, email, phone, role, suspended, protected}
  unassigned_users  users who belong to no organisation (legacy accounts)
  platform_admins   the AccFino administrator account(s): shown for reference, NEVER deletable (protected = true)

The /admin/ prefix is admin-guarded by the auth middleware and every call re-checks it.
"""
from fastapi import APIRouter, Body, Depends, HTTPException, Request, Response
from sqlalchemy.orm import Session

from accfino.core.platform_admin import force_delete as FD
from accfino.core import models as m
from accfino.core.identity import org_admin as OA
from accfino.core.security import contact as C
from accfino.core.security.context import current_auth
from accfino.core.subscription import service as S
from accfino.core.subscription.models import OrgSubscription, Plan
from accfino.core.tenancy import service as T
from accfino.shared.db.database import get_db
from accfino.core.identity.user import User

router = APIRouter()

ROLE_LABEL = {"owner": "Organisation Admin", "admin": "Admin (legacy)", "accountant": "Accountant", "bookkeeper": "Bookkeeper", "payroll": "Payroll Manager", "payroll_admin": "Payroll Administrator", "employee": "Employee", "readonly": "Read only"}


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


# ------------------------------------------------------------------------------------------------------------------------ plan by user --
def _domains_of(modules) -> list:
    have = set(modules)
    return [name for did, name, ms in S.DOMAINS if have & set(ms)]


def user_plan_rows(db: Session) -> dict:
    """Every user with the plan of the organisation they belong to (the organisation plans are the only licence now): plan, billing, paid-until, users used / allowed,
    add-ons and the business domains the plan shows. The AccFino administrator shows the top plan."""
    from accfino.shared.contracts import registry
    users = {u.id: u for u in db.query(User).order_by(User.id).all()}
    members = {}
    for mem in db.query(m.OrgMembership).order_by(m.OrgMembership.org_id, m.OrgMembership.id).all():
        members.setdefault(mem.user_id, []).append(mem)
    orgs = {o.id: o for o in db.query(m.Organisation).all()}
    ents, cache = {}, {}

    def org_block(org_id):
        if org_id in cache:
            return cache[org_id]
        ent = S.entitlements(db, org_id)
        sub, bill = db.get(OrgSubscription, org_id), registry.org_billing(db, org_id)
        seats = T.seat_status(db, org_id)
        cache[org_id] = {"org_id": org_id, "org_name": orgs[org_id].name if org_id in orgs else f"#{org_id}", "plan_id": ent["plan_id"], "plan_name": ent["plan_name"], "grandfathered": ent["grandfathered"],
                         "status": ent["status"], "billing_period": ent["billing_period"], "period_end": ent["period_end"], "trial_ends": ent["trial_ends"],
                         "seats_used": seats["active"], "seats_pending": seats["pending"], "seats_allowed": seats["licensed"],
                         "addons": [a["name"] for a in ent["addons"]], "domains": _domains_of(ent["modules"]),
                         "card": f"{bill.card_brand or 'Card'} ···· {bill.card_last4}" if bill and bill.card_id else None, "auto_renew": bool(bill and bill.auto_renew)}
        return cache[org_id]

    rows = []
    for uid, u in users.items():
        is_admin = FD.is_protected_user(u)
        base = {"user_id": uid, "username": u.username, "full_name": u.full_name or "", "email": u.email or "", "phone": u.phone or "", "phone_display": C.format_phone(u.phone) if u.phone else "",
                "platform_admin": is_admin}
        mems = members.get(uid, [])
        if not mems:
            rows.append({**base, "org": None, "role": None, "role_label": "No organisation"})
            continue
        for mem in mems:
            rows.append({**base, "org": org_block(mem.org_id), "role": mem.role, "role_label": ROLE_LABEL.get(mem.role, mem.role), "suspended": mem.suspended_at is not None})
    active = db.query(Plan).filter_by(is_active=True).order_by(Plan.sort_order, Plan.id).all()
    top = max(active, key=lambda p: p.price_monthly, default=None)
    return {"rows": rows, "plans": [{"id": p.id, "name": p.name, "price_monthly": float(p.price_monthly)} for p in active], "top_plan": top.name if top is not None else None}


@router.get("/user-plans")
def user_plans(request: Request, response: Response = None, db: Session = Depends(get_db)):
    auth = current_auth(request)
    if not auth.get("is_admin"):
        raise HTTPException(403, "Administrators only")
    if response is not None:
        response.headers["Cache-Control"] = "no-store"
    return user_plan_rows(db)


@router.put("/org/{org_id}/plan")
def set_org_plan(org_id: int, request: Request, body: dict = Body(...), db: Session = Depends(get_db)):
    """Change ONLY the plan of an organisation (add-ons, billing period, status and dates are left as they are)."""
    auth = current_auth(request)
    if not auth.get("is_admin"):
        raise HTTPException(403, "Administrators only")
    if db.get(m.Organisation, org_id) is None:
        raise HTTPException(404, "Organisation not found")
    plan = db.get(Plan, str(body.get("plan_id", "")))
    if plan is None or not plan.is_active:
        raise HTTPException(404, "Unknown plan")
    sub = db.get(OrgSubscription, org_id)
    before = sub.plan_id if sub else None
    if sub is None:
        sub = OrgSubscription(org_id=org_id, plan_id=plan.id, status="active")
        db.add(sub)
    sub.plan_id, sub.updated_by = plan.id, auth.get("user_id")
    db.commit()
    from accfino.core.security import audit
    audit.write("admin.subscription_plan_changed", user_id=auth.get("user_id"), username=auth.get("username"), org_id=org_id, entity="subscription", entity_id=org_id,
                detail=dict(before=before, after=plan.id))
    if before != plan.id:
        try:
            from accfino.core import notifications as N
            N.subscription_changed(db, org_id, sub.status, plan.name, "Your plan was changed by your platform administrator.")
        except Exception:
            pass
    return {"org_id": org_id, "plan_id": plan.id, "plan_name": plan.name}


@router.get("/address-check")
def address_check(request: Request):
    """Platform administrator: is everything in place for organisation web addresses (setting, wildcard DNS, wildcard certificate, routing)?"""
    from accfino.core.tenancy import address_check as AC
    auth = current_auth(request)
    if not auth.get("is_admin"):
        raise HTTPException(403, "Administrators only")
    return AC.check()
