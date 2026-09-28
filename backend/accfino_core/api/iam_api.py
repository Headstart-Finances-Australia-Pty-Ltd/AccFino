"""IAM step 2 APIs (Microsoft Entra-style).

/auth/sessions                 your signed-in devices; end one or all others
/admin/users                   platform administrators: search, disable/enable, sign out, reset MFA,
                               unlock, require password change, view sign-ins and devices
/org/current/access-policy     organisation Conditional Access policy (owners/admins)
"""
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field
from sqlalchemy import func, or_
from sqlalchemy.orm import Session

from accfino_core import models as m
from accfino_core.migrate import ensure_user_security
from accfino_core.security import audit, iam, tokens
from accfino_core.security import mfa_service as S
from accfino_core.security.context import OrgContext, current_auth, current_org
from accfino_core.security.login import client_ip, org_summaries
from db_app.database import get_db
from db_app.models.user import User

sessions_router = APIRouter()
admin_router = APIRouter()
policy_router = APIRouter()


def _iso(d):
    return d.isoformat() + "Z" if d else None


def _device(ua: str) -> str:
    ua = ua or ""
    os_ = next((n for k, n in (("iPhone", "iPhone"), ("iPad", "iPad"), ("Android", "Android"), ("Windows", "Windows"),
                                ("Mac OS", "Mac"), ("Linux", "Linux")) if k in ua), "Unknown device")
    br = next((n for k, n in (("Edg/", "Edge"), ("OPR/", "Opera"), ("Chrome/", "Chrome"), ("Firefox/", "Firefox"),
                               ("Safari/", "Safari")) if k in ua), "")
    if not ua:
        return "Unknown device"
    if "python-httpx" in ua or "curl" in ua:
        return "API client"
    return f"{br} on {os_}".strip() if br else os_


def _session_row(s, current_sid=None):
    return {"id": s.id, "device": _device(s.user_agent), "ip": s.ip, "methods": s.auth_methods,
            "created_at": _iso(s.created_at), "last_seen_at": _iso(s.last_seen_at), "expires_at": _iso(s.expires_at),
            "active": not s.revoked_at and s.expires_at > datetime.utcnow(), "revoked_reason": s.revoked_reason,
            "current": s.id == current_sid}


# ================================================================ sessions ===
@sessions_router.get("")
def my_sessions(request: Request, db: Session = Depends(get_db)):
    auth = current_auth(request)
    rows = (db.query(m.UserSession).filter(m.UserSession.user_id == auth["user_id"], m.UserSession.revoked_at.is_(None),
                                           m.UserSession.expires_at > datetime.utcnow())
            .order_by(m.UserSession.last_seen_at.desc()).all())
    return [_session_row(s, auth.get("sid")) for s in rows]


@sessions_router.post("/{session_id}/revoke")
def revoke_one(session_id: str, request: Request, db: Session = Depends(get_db)):
    auth = current_auth(request)
    n = iam.revoke_sessions(db, auth["user_id"], sid=session_id, reason="signed_out_by_user")
    db.commit()
    if not n:
        raise HTTPException(404, "Session not found")
    audit.write("auth.session_revoked", user_id=auth["user_id"], username=auth["username"], ip=client_ip(request),
                entity="session", entity_id=session_id[:12])
    return {"ok": True}


@sessions_router.post("/revoke-others")
def revoke_others(request: Request, db: Session = Depends(get_db)):
    auth = current_auth(request)
    n = iam.revoke_sessions(db, auth["user_id"], except_sid=auth.get("sid"), reason="signed_out_by_user")
    db.commit()
    audit.write("auth.sessions_revoked_others", user_id=auth["user_id"], username=auth["username"],
                ip=client_ip(request), detail={"count": n})
    return {"ok": True, "ended": n}


# ============================================================ admin users ===
class ReasonIn(BaseModel):
    reason: str | None = Field(default=None, max_length=300)


class FlagIn(BaseModel):
    required: bool = True


def _admin_ids(db):
    from db_app.models.role import Role
    return {u.id for u in db.query(User).join(User.roles).filter(func.lower(Role.name) == "admin")}


def _target(db, user_id):
    u = db.get(User, user_id)
    if u is None:
        raise HTTPException(404, "User not found")
    return u, ensure_user_security(db, u.id)


def _revoke_all(db, u, sec, reason):
    sec.token_version += 1
    iam.revoke_sessions(db, u.id, reason=reason)
    db.commit()
    tokens.forget_token_version(u.id)
    iam.forget(("acct", u.id))


def _admin_audit(request, action, target, detail=None):
    a = current_auth(request)
    audit.write(f"admin.user.{action}", user_id=a["user_id"], username=a["username"], ip=client_ip(request),
                entity="user", entity_id=target.id, detail={"target": target.username, **(detail or {})})


@admin_router.get("")
def list_users(q: str | None = None, status: str | None = Query(None, pattern="^(active|disabled|locked|no_mfa)$"),
               limit: int = Query(50, le=200), offset: int = 0, db: Session = Depends(get_db)):
    query = db.query(User, m.UserSecurity).outerjoin(m.UserSecurity, m.UserSecurity.user_id == User.id)
    if q:
        like = f"%{q.strip()}%"
        query = query.filter(or_(User.username.ilike(like), User.email.ilike(like), User.full_name.ilike(like)))
    now = datetime.utcnow()
    if status == "active":
        query = query.filter(m.UserSecurity.disabled_at.is_(None))
    elif status == "disabled":
        query = query.filter(m.UserSecurity.disabled_at.isnot(None))
    elif status == "locked":
        query = query.filter(m.UserSecurity.locked_until > now)
    total = query.count()
    rows = query.order_by(User.username).offset(offset).limit(limit).all()
    admins = _admin_ids(db)
    items = []
    for u, sec in rows:
        methods = S.available_methods(db, sec) if sec else []
        if status == "no_mfa" and methods:
            continue
        items.append({"id": u.id, "username": u.username, "name": u.full_name, "email": u.email,
                      "is_admin": u.id in admins, "mfa_methods": methods,
                      "disabled": bool(sec and sec.disabled_at),
                      "locked": bool(sec and sec.locked_until and sec.locked_until > now),
                      "must_change_password": bool(sec and sec.must_change_password),
                      "last_login_at": _iso(sec.last_login_at) if sec else None,
                      "created_at": _iso(u.created_at) if getattr(u, "created_at", None) else None})
    return {"total": total, "items": items}


@admin_router.get("/{user_id}")
def user_detail(user_id: int, db: Session = Depends(get_db)):
    u, sec = _target(db, user_id)
    db.commit()
    sessions = (db.query(m.UserSession).filter(m.UserSession.user_id == u.id)
                .order_by(m.UserSession.created_at.desc()).limit(20).all())
    signins = (db.query(m.AuditLog).filter(m.AuditLog.user_id == u.id, m.AuditLog.action.like("auth.%"))
               .order_by(m.AuditLog.id.desc()).limit(25).all())
    return {
        "id": u.id, "username": u.username, "name": u.full_name, "email": u.email,
        "roles": [r.name for r in u.roles],
        "disabled_at": _iso(sec.disabled_at), "disabled_reason": sec.disabled_reason,
        "locked_until": _iso(sec.locked_until) if sec.locked_until and sec.locked_until > datetime.utcnow() else None,
        "must_change_password": sec.must_change_password, "last_login_at": _iso(sec.last_login_at),
        "mfa_methods": S.available_methods(db, sec), "passkeys": len(S.passkeys(db, u.id)),
        "recovery_codes_remaining": len(sec.mfa_recovery_hashes or []),
        "organisations": org_summaries(db, u.id),
        "sessions": [_session_row(s) for s in sessions],
        "sign_ins": [{"at": _iso(a.occurred_at), "action": a.action, "ip": a.ip, "detail": a.detail} for a in signins],
    }


@admin_router.post("/{user_id}/disable")
def disable_user(user_id: int, body: ReasonIn, request: Request, db: Session = Depends(get_db)):
    if user_id == current_auth(request)["user_id"]:
        raise HTTPException(409, "You can't disable your own account")
    u, sec = _target(db, user_id)
    if u.id in _admin_ids(db) and len(_admin_ids(db)) <= 1:
        raise HTTPException(409, "This is the only administrator account")
    sec.disabled_at, sec.disabled_reason = datetime.utcnow(), (body.reason or "").strip() or None
    _revoke_all(db, u, sec, "account_disabled")
    _admin_audit(request, "disabled", u, {"reason": sec.disabled_reason})
    return {"ok": True}


@admin_router.post("/{user_id}/enable")
def enable_user(user_id: int, request: Request, db: Session = Depends(get_db)):
    u, sec = _target(db, user_id)
    sec.disabled_at = sec.disabled_reason = None
    db.commit()
    iam.forget(("acct", u.id))
    _admin_audit(request, "enabled", u)
    return {"ok": True}


@admin_router.post("/{user_id}/sign-out")
def sign_out_user(user_id: int, request: Request, db: Session = Depends(get_db)):
    u, sec = _target(db, user_id)
    _revoke_all(db, u, sec, "signed_out_by_admin")
    _admin_audit(request, "signed_out", u)
    return {"ok": True}


@admin_router.post("/{user_id}/reset-mfa")
def reset_mfa(user_id: int, request: Request, db: Session = Depends(get_db)):
    """For a user who lost their phone: removes every method and recovery code; they re-enrol after signing in."""
    u, sec = _target(db, user_id)
    before = S.available_methods(db, sec)
    sec.mfa_enabled, sec.mfa_secret = False, None
    sec.sms_mfa_enabled, sec.phone_e164, sec.email_mfa_enabled = False, None, False
    sec.mfa_recovery_hashes = None
    db.query(m.WebAuthnCredential).filter_by(user_id=u.id).delete()
    _revoke_all(db, u, sec, "mfa_reset_by_admin")
    _admin_audit(request, "mfa_reset", u, {"removed": before})
    return {"ok": True, "removed": before}


@admin_router.post("/{user_id}/unlock")
def unlock_user(user_id: int, request: Request, db: Session = Depends(get_db)):
    u, sec = _target(db, user_id)
    sec.failed_logins, sec.locked_until = 0, None
    db.commit()
    _admin_audit(request, "unlocked", u)
    return {"ok": True}


@admin_router.post("/{user_id}/require-password-change")
def require_password_change(user_id: int, body: FlagIn, request: Request, db: Session = Depends(get_db)):
    u, sec = _target(db, user_id)
    sec.must_change_password = bool(body.required)
    db.commit()
    iam.forget(("acct", u.id))
    _admin_audit(request, "password_change_required" if body.required else "password_change_cleared", u)
    return {"ok": True}


@admin_router.post("/{user_id}/sessions/{session_id}/revoke")
def admin_revoke_session(user_id: int, session_id: str, request: Request, db: Session = Depends(get_db)):
    u, _ = _target(db, user_id)
    n = iam.revoke_sessions(db, u.id, sid=session_id, reason="revoked_by_admin")
    db.commit()
    if not n:
        raise HTTPException(404, "Session not found or already ended")
    _admin_audit(request, "session_revoked", u, {"session": session_id[:12]})
    return {"ok": True}


# ======================================================= access policy ===
class PolicyIn(BaseModel):
    state: str = Field(pattern="^(off|report|on)$")
    applies_to: str = Field(default="all", pattern="^(all|admins)$")
    require_mfa: bool = False
    allowed_mfa_methods: list[str] | None = None
    ip_allowlist: list[str] | None = None
    max_session_hours: int | None = Field(default=None, ge=1, le=720)


def _policy_dict(p):
    if p is None:
        return {"state": "off", "applies_to": "all", "require_mfa": False, "allowed_mfa_methods": None,
                "ip_allowlist": None, "max_session_hours": None, "updated_at": None}
    return {"state": p.state, "applies_to": p.applies_to, "require_mfa": p.require_mfa,
            "allowed_mfa_methods": p.allowed_mfa_methods, "ip_allowlist": p.ip_allowlist,
            "max_session_hours": p.max_session_hours, "updated_at": _iso(p.updated_at)}


@policy_router.get("")
def get_policy(request: Request, ctx: OrgContext = Depends(current_org), db: Session = Depends(get_db)):
    ctx.require("settings")
    out = _policy_dict(db.get(m.AccessPolicy, ctx.org.id))
    out["your_ip"] = client_ip(request)
    return out


@policy_router.put("")
def put_policy(body: PolicyIn, request: Request, ctx: OrgContext = Depends(current_org), db: Session = Depends(get_db)):
    ctx.require("members")
    try:
        ips = iam.validate_cidrs(body.ip_allowlist)
    except ValueError as e:
        raise HTTPException(422, str(e))
    allowed = None
    if body.allowed_mfa_methods:
        bad = [x for x in body.allowed_mfa_methods if x not in iam.MFA_METHODS]
        if bad:
            raise HTTPException(422, f"Unknown verification method(s): {', '.join(bad)}")
        allowed = sorted(set(body.allowed_mfa_methods))
    new = {"state": body.state, "applies_to": body.applies_to, "require_mfa": body.require_mfa,
           "allowed": allowed, "ips": ips or None, "max_hours": body.max_session_hours}
    # Lock-out protection (as in Entra): refuse an enforced policy that would block the person saving it
    auth = current_auth(request)
    if body.state == "on" and not auth["is_admin"]:
        d = iam.evaluate(new, role=ctx.role, ip=client_ip(request), mfa_verified=auth["mfa"], amr=auth.get("amr"),
                         session_started=None)
        if d:
            raise HTTPException(409, f"This policy would block your own access: {d[1]} Adjust it, or use "
                                     "'Report only' first to see who would be affected.")
    p = db.get(m.AccessPolicy, ctx.org.id)
    before = _policy_dict(p)
    if p is None:
        p = m.AccessPolicy(org_id=ctx.org.id)
        db.add(p)
    p.state, p.applies_to, p.require_mfa = body.state, body.applies_to, body.require_mfa
    p.allowed_mfa_methods, p.ip_allowlist, p.max_session_hours = allowed, ips or None, body.max_session_hours
    p.updated_by = ctx.user_id
    db.commit()
    iam.forget(("pol", ctx.org.id))
    audit.write("org.access_policy_changed", user_id=ctx.user_id, username=ctx.username, org_id=ctx.org.id,
                ip=client_ip(request), detail={"before": before, "after": _policy_dict(p)})
    return _policy_dict(p)
