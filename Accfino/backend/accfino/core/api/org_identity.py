"""/org/current/identity - Identity management for an ORGANISATION's owners and admins.

Organisation admins manage people in their own organisation:
  * any member:   view status (MFA on/off, last sign-in), suspend / restore access to THIS organisation
                  (role changes and removal stay on /org/current/members)
  * HOME members  (whose home organisation is this one): additionally sign out everywhere, reset MFA,
                  require a password change, view devices and sign-in history.

Actions that affect a person's whole AccFino account are limited to home members so that an admin of
some other organisation can't add a stranger by email and then weaken that stranger's account.
Platform-wide user management stays with AccFino super admins (/admin/users).
"""
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from accfino.core import models as m
from accfino.core import notifications as N
from accfino.core.migrate import ensure_user_security
from accfino.core.security import audit, iam, tokens
from accfino.core.security import mfa_service as S
from accfino.core.security.context import OrgContext, current_org
from accfino.core.security.login import client_ip, is_admin
from accfino.shared.db.database import get_db
from accfino.core.identity.user import User

router = APIRouter()
# NB: path parameter is member_user_id, not user_id - the auth guard requires any user_id in a URL
# to be the caller's own id (anti-IDOR), which is correct for every other route.


class ReasonIn(BaseModel):
    reason: str | None = Field(default=None, max_length=300)


class FlagIn(BaseModel):
    required: bool = True


def _iso(d):
    return d.isoformat() + "Z" if d else None


def _membership(db, ctx, member_user_id):
    row = db.query(m.OrgMembership, User).join(User, User.id == m.OrgMembership.user_id) \
        .filter(m.OrgMembership.org_id == ctx.org.id, m.OrgMembership.user_id == member_user_id).first()
    if row is None:
        raise HTTPException(404, "Not a member of this organisation")
    return row


def _guard(ctx, mem, u, *, home_only=False):
    if u.id == ctx.user_id:
        raise HTTPException(409, "Use your own Security page for your account")
    if is_admin(u):
        raise HTTPException(403, "AccFino platform administrators can't be managed from an organisation")
    if mem.role == "owner" and ctx.role != "owner" and not ctx.is_admin:
        raise HTTPException(403, "Only an owner can manage another owner")
    if home_only and not mem.is_default:
        raise HTTPException(403, "This person's home organisation is a different one, so only their own "
                                 "administrator can do this. You can suspend or remove their access here.")


def _audit(ctx, request, action, u, detail=None):
    audit.write(f"org.identity.{action}", user_id=ctx.user_id, username=ctx.username, org_id=ctx.org.id,
                ip=client_ip(request), entity="user", entity_id=u.id, detail={"target": u.username, **(detail or {})})


@router.get("/members")
def members(ctx: OrgContext = Depends(current_org), db: Session = Depends(get_db)):
    ctx.require_org_admin()
    now = datetime.utcnow()
    out = []
    rows = db.query(m.OrgMembership, User).join(User, User.id == m.OrgMembership.user_id) \
        .filter(m.OrgMembership.org_id == ctx.org.id).order_by(User.username).all()
    for mem, u in rows:
        sec = ensure_user_security(db, u.id)
        active = db.query(m.UserSession).filter(m.UserSession.user_id == u.id, m.UserSession.revoked_at.is_(None),
                                                 m.UserSession.expires_at > now).count() if mem.is_default else None
        out.append({"user_id": u.id, "name": u.full_name or u.username, "email": u.email, "phone": u.phone, "role": mem.role,
                    "is_org_admin": mem.role == m.ADMIN_ROLE,
                    "home_member": bool(mem.is_default), "is_you": u.id == ctx.user_id,
                    "platform_admin": is_admin(u),
                    "suspended": bool(mem.suspended_at), "suspended_reason": mem.suspended_reason,
                    "mfa_methods": S.available_methods(db, sec),
                    "last_login_at": _iso(sec.last_login_at), "active_sessions": active,
                    "must_change_password": bool(sec.must_change_password)})
    db.commit()
    return out


@router.get("/members/{member_user_id}")
def member_detail(member_user_id: int, ctx: OrgContext = Depends(current_org), db: Session = Depends(get_db)):
    ctx.require_org_admin()
    mem, u = _membership(db, ctx, member_user_id)
    sec = ensure_user_security(db, u.id)
    db.commit()
    out = {"user_id": u.id, "name": u.full_name or u.username, "email": u.email, "role": mem.role,
           "home_member": bool(mem.is_default), "suspended_at": _iso(mem.suspended_at),
           "suspended_reason": mem.suspended_reason, "mfa_methods": S.available_methods(db, sec),
           "last_login_at": _iso(sec.last_login_at), "must_change_password": bool(sec.must_change_password),
           "sessions": None, "sign_ins": None}
    if mem.is_default:   # devices and sign-in history only for home members (privacy)
        from accfino.core.api.iam_api import _session_row
        out["sessions"] = [_session_row(s) for s in db.query(m.UserSession).filter(m.UserSession.user_id == u.id)
                           .order_by(m.UserSession.created_at.desc()).limit(15)]
        out["sign_ins"] = [{"at": _iso(a.occurred_at), "action": a.action, "ip": a.ip} for a in
                           db.query(m.AuditLog).filter(m.AuditLog.user_id == u.id, m.AuditLog.action.like("auth.%"))
                           .order_by(m.AuditLog.id.desc()).limit(20)]
    return out


@router.post("/members/{member_user_id}/suspend")
def suspend(member_user_id: int, body: ReasonIn, request: Request, ctx: OrgContext = Depends(current_org),
            db: Session = Depends(get_db)):
    ctx.require_org_admin()
    mem, u = _membership(db, ctx, member_user_id)
    _guard(ctx, mem, u)
    if mem.role == "owner" and db.query(m.OrgMembership).filter_by(org_id=ctx.org.id, role="owner",
                                                                    suspended_at=None).count() <= 1:
        raise HTTPException(409, "An organisation must keep at least one active owner")
    mem.suspended_at, mem.suspended_reason = datetime.utcnow(), (body.reason or "").strip() or None
    db.commit()
    iam.forget(("role", u.id, ctx.org.id))
    _audit(ctx, request, "suspended", u, {"reason": mem.suspended_reason})
    N.member_changed(db, ctx.org, ctx.username, u, "suspended", mem.suspended_reason or "")
    return {"ok": True}


@router.post("/members/{member_user_id}/restore")
def restore(member_user_id: int, request: Request, ctx: OrgContext = Depends(current_org), db: Session = Depends(get_db)):
    ctx.require_org_admin()
    mem, u = _membership(db, ctx, member_user_id)
    _guard(ctx, mem, u)
    mem.suspended_at = mem.suspended_reason = None
    db.commit()
    iam.forget(("role", u.id, ctx.org.id))
    _audit(ctx, request, "restored", u)
    N.member_changed(db, ctx.org, ctx.username, u, "restored")
    return {"ok": True}


@router.post("/members/{member_user_id}/sign-out")
def sign_out(member_user_id: int, request: Request, ctx: OrgContext = Depends(current_org), db: Session = Depends(get_db)):
    ctx.require_org_admin()
    mem, u = _membership(db, ctx, member_user_id)
    _guard(ctx, mem, u, home_only=True)
    sec = ensure_user_security(db, u.id)
    sec.token_version += 1
    iam.revoke_sessions(db, u.id, reason="signed_out_by_org_admin")
    db.commit()
    tokens.forget_token_version(u.id)
    _audit(ctx, request, "signed_out", u)
    return {"ok": True}


@router.post("/members/{member_user_id}/reset-mfa")
def reset_mfa(member_user_id: int, request: Request, ctx: OrgContext = Depends(current_org), db: Session = Depends(get_db)):
    ctx.require_org_admin()
    mem, u = _membership(db, ctx, member_user_id)
    _guard(ctx, mem, u, home_only=True)
    sec = ensure_user_security(db, u.id)
    removed = S.available_methods(db, sec)
    sec.mfa_enabled, sec.mfa_secret = False, None
    sec.sms_mfa_enabled, sec.phone_e164, sec.email_mfa_enabled, sec.mfa_recovery_hashes = False, None, False, None
    db.query(m.WebAuthnCredential).filter_by(user_id=u.id).delete()
    sec.token_version += 1
    iam.revoke_sessions(db, u.id, reason="mfa_reset_by_org_admin")
    db.commit()
    tokens.forget_token_version(u.id)
    _audit(ctx, request, "mfa_reset", u, {"removed": removed})
    N.member_changed(db, ctx.org, ctx.username, u, "two_step_verification_reset", "Removed: " + (", ".join(removed) or "nothing") + ". They will set it up again after signing in.")
    return {"ok": True, "removed": removed}


@router.post("/members/{member_user_id}/require-password-change")
def require_pw(member_user_id: int, body: FlagIn, request: Request, ctx: OrgContext = Depends(current_org),
               db: Session = Depends(get_db)):
    ctx.require_org_admin()
    mem, u = _membership(db, ctx, member_user_id)
    _guard(ctx, mem, u, home_only=True)
    sec = ensure_user_security(db, u.id)
    sec.must_change_password = bool(body.required)
    db.commit()
    iam.forget(("acct", u.id))
    _audit(ctx, request, "password_change_required" if body.required else "password_change_cleared", u)
    return {"ok": True}
