"""
accfino_core.org_admin
----------------------
The Organisation Admin ("Account Owner"): the ONE person who administers an organisation and is its primary contact.

  * the user who creates an organisation becomes its Organisation Admin automatically (`assign_first_admin`)
  * identified in the database two ways that are kept in step: organisations.admin_user_id and the single role='owner' membership
    (a unique index makes a second owner impossible, even by direct SQL)
  * the admin's email and phone ARE the organisation's primary contact details (`org_contact`) - every organisation-level
    communication (accfino_core.notifications) goes there, never to an ordinary member
  * the role moves only by `transfer_admin` (never through an invitation, "add member" or a role change)
"""
from datetime import datetime
from typing import Optional

from fastapi import HTTPException
from sqlalchemy.orm import Session

from accfino.core import models as m
from accfino.core.security import audit
from accfino.core.security import contact as C

DEMOTED_ROLE = "accountant"          # what a former admin becomes: full day-to-day access, no organisation administration


# ------------------------------------------------------------------------------------------------ lookup --
def admin_membership(db: Session, org_id: int) -> Optional["m.OrgMembership"]:
    return db.query(m.OrgMembership).filter_by(org_id=org_id, role=m.ADMIN_ROLE).first()


def admin_user(db: Session, org_id: int):
    """The Organisation Admin's user row (None only for a damaged organisation that has no owner)."""
    from accfino.core.identity.user import User
    mem = admin_membership(db, org_id)
    return db.get(User, mem.user_id) if mem else None


def org_contact(db: Session, org_id: int) -> dict:
    """The organisation's PRIMARY contact = its Organisation Admin: name, email, phone (E.164 and display form)."""
    u = admin_user(db, org_id)
    if u is None:
        return {"user_id": None, "name": None, "email": None, "phone": None, "phone_display": None}
    return {"user_id": u.id, "name": u.full_name or u.username, "email": u.email, "phone": u.phone, "phone_display": C.format_phone(u.phone)}


# ------------------------------------------------------------------------------------------------ designation --
def assign_first_admin(db: Session, org: "m.Organisation", user_id: int, *, is_default: bool = False) -> "m.OrgMembership":
    """Make `user_id` the Organisation Admin of a brand-new organisation (the person who created it)."""
    mem = db.query(m.OrgMembership).filter_by(org_id=org.id, user_id=user_id).first()
    if mem is None:
        mem = m.OrgMembership(org_id=org.id, user_id=user_id, role=m.ADMIN_ROLE, is_default=is_default)
        db.add(mem)
    else:
        mem.role = m.ADMIN_ROLE
    org.admin_user_id = user_id
    db.flush()
    return mem


def sync_org_admins(db: Session) -> dict:
    """Idempotent repair, run at every start: every organisation ends up with exactly ONE owner (the Organisation Admin) and a matching
    organisations.admin_user_id. Organisations that grew several owners keep one (the creator when known, else the earliest) and the others
    become accountants - they keep their access to the books, and lose organisation administration. Every change is audited."""
    out = {"demoted": 0, "promoted": 0, "synced": 0}
    for org in db.query(m.Organisation).order_by(m.Organisation.id).all():
        owners = db.query(m.OrgMembership).filter_by(org_id=org.id, role=m.ADMIN_ROLE).order_by(m.OrgMembership.id).all()
        if len(owners) > 1:
            keep = next((o for o in owners if o.user_id == org.legacy_user_id), None) or next((o for o in owners if o.user_id == org.admin_user_id), None) or owners[0]
            for o in owners:
                if o is not keep:
                    o.role = DEMOTED_ROLE
                    out["demoted"] += 1
                    audit.write("org.admin_normalised", org_id=org.id, entity="user", entity_id=o.user_id, db=db,
                                detail={"action": "demoted_extra_owner", "kept_admin_user_id": keep.user_id, "new_role": DEMOTED_ROLE})
            db.flush()
            owners = [keep]
        if not owners:
            cand = (db.query(m.OrgMembership).filter(m.OrgMembership.org_id == org.id, m.OrgMembership.role == "admin", m.OrgMembership.suspended_at.is_(None))
                    .order_by(m.OrgMembership.id).first())
            if cand is not None:
                cand.role = m.ADMIN_ROLE
                out["promoted"] += 1
                audit.write("org.admin_normalised", org_id=org.id, entity="user", entity_id=cand.user_id, db=db, detail={"action": "promoted_to_admin_no_owner"})
                db.flush()
                owners = [cand]
        want = owners[0].user_id if owners else None
        if org.admin_user_id != want:
            org.admin_user_id = want
            out["synced"] += 1
    db.flush()
    return out


def transfer_admin(db: Session, org: "m.Organisation", from_user_id: int, to_user_id: int) -> None:
    """Hand the organisation over to another ACTIVE member whose profile is complete. The previous admin becomes an Accountant."""
    from accfino.core.identity.user import User
    if from_user_id == to_user_id:
        raise HTTPException(409, "That person is already the Organisation Admin")
    new = db.query(m.OrgMembership).filter_by(org_id=org.id, user_id=to_user_id).first()
    if new is None:
        raise HTTPException(404, "That person is not a member of this organisation")
    if new.suspended_at:
        raise HTTPException(409, "Restore this member's access before making them the Organisation Admin")
    u = db.get(User, to_user_id)
    if u is None or C.missing_contact(u.email, u.phone):
        raise HTTPException(409, "The new Organisation Admin must have a valid email address and phone number on their profile first")
    old = admin_membership(db, org.id)
    if old is not None:
        old.role = DEMOTED_ROLE
        db.flush()                                  # the unique index allows one owner: free the seat BEFORE taking it
    new.role = m.ADMIN_ROLE
    org.admin_user_id = to_user_id
    db.flush()


# ------------------------------------------------------------------------------------------------ dashboard --
def invite_counts(db: Session, org_id: int) -> dict:
    from accfino.core.tenancy import service as T
    from accfino.core.tenancy.models import OrgInvite
    counts = {"unused": 0, "partly_used": 0, "used": 0, "expired": 0, "revoked": 0}
    now = datetime.utcnow()
    for i in db.query(OrgInvite).filter_by(org_id=org_id):
        counts[T.invite_status(i, now)] += 1
    return counts


def overview(db: Session, org: "m.Organisation") -> dict:
    """The Organisation Admin dashboard: organisation, primary contact, licence usage and access-code counts."""
    from accfino.core.tenancy import service as T
    c = org_contact(db, org.id)
    st = T.seat_status(db, org.id)
    codes = invite_counts(db, org.id)
    return {
        "organisation": {"id": org.id, "name": org.name, "admin_name": c["name"], "admin_email": c["email"], "admin_phone": c["phone"], "admin_phone_display": c["phone_display"],
                         "admin_user_id": c["user_id"]},
        "users": {"licensed_users": st["licensed"], "active_users": st["active"], "available_slots": st["available"], "pending_invitations": st["pending"]},
        "access_codes": {"active": codes["unused"] + codes["partly_used"], "used": codes["used"], "expired": codes["expired"], "revoked": codes["revoked"]},
    }
