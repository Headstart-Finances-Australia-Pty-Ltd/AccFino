"""Login hardening used by db_app.api.auth: lockout, IP throttling, MFA step, token issue."""
import threading
import time
from collections import deque
from datetime import datetime, timedelta

from fastapi import HTTPException

from accfino.core import config
from accfino.core import models as m
from accfino.core.migrate import ensure_personal_org, ensure_user_security
from accfino.core.security import audit, tokens

_ip_hits: dict = {}
_ip_lock = threading.Lock()


def client_ip(request) -> str:
    """Trusted client address (see iam.client_ip_from / PROXY_HOPS). The old version used the
    FIRST X-Forwarded-For entry, which any client can set - defeating throttling and IP rules."""
    if request is None:
        return ""
    from accfino.core.security.iam import client_ip_from
    return client_ip_from(request.headers, request.client.host if request.client else "")


def throttle_ip(ip: str):
    """Sliding-window limit on login attempts per IP (per worker)."""
    now = time.time()
    with _ip_lock:
        q = _ip_hits.setdefault(ip, deque())
        while q and now - q[0] > config.LOGIN_IP_WINDOW_SECONDS:
            q.popleft()
        if len(q) >= config.LOGIN_IP_MAX_ATTEMPTS:
            raise HTTPException(429, "Too many login attempts from this address. Try again later.")
        q.append(now)


def check_locked(db, user):
    sec = ensure_user_security(db, user.id)
    if sec.locked_until and sec.locked_until > datetime.utcnow():
        mins = int((sec.locked_until - datetime.utcnow()).total_seconds() // 60) + 1
        raise HTTPException(423, f"Account temporarily locked after repeated failed logins. Try again in {mins} minute(s).")
    return sec


def check_disabled(db, user):
    """Call only AFTER the password/passkey is verified, so disabled status isn't revealed to guessers."""
    sec = ensure_user_security(db, user.id)
    if sec.disabled_at:
        audit.write("auth.login_blocked_disabled", user_id=user.id, username=user.username)
        raise HTTPException(403, "This account has been disabled by an administrator. Contact your AccFino administrator.")
    return sec


def record_failure(db, user, ip):
    sec = ensure_user_security(db, user.id)
    sec.failed_logins = (sec.failed_logins or 0) + 1
    locked = False
    if sec.failed_logins >= config.LOGIN_MAX_FAILURES:
        sec.locked_until = datetime.utcnow() + timedelta(minutes=config.LOGIN_LOCK_MINUTES)
        sec.failed_logins = 0
        locked = True
    db.commit()
    audit.write("auth.login_failed", user_id=user.id, username=user.username, ip=ip,
                detail={"locked": locked})


def is_admin(user) -> bool:
    return any((r.name or "").strip().lower() == "admin" for r in user.roles)


def org_summaries(db, user_id):
    rows = db.query(m.OrgMembership, m.Organisation).join(m.Organisation, m.Organisation.id == m.OrgMembership.org_id) \
        .filter(m.OrgMembership.user_id == user_id, m.Organisation.is_active.is_(True)).all()
    return [{"id": o.id, "name": o.name, "role": mem.role, "is_default": mem.is_default,
             "suspended": bool(mem.suspended_at)} for mem, o in rows]


def token_fields(db, user, *, mfa_verified: bool, org_id=None, request=None, amr=None) -> dict:
    """Issue an access token and return the extra fields added to the login response."""
    sec = ensure_user_security(db, user.id)
    org = ensure_personal_org(db, user)
    orgs = org_summaries(db, user.id)
    use_org = org_id or next((o["id"] for o in orgs if o["is_default"]), org.id)
    from accfino.core.security.mfa_service import has_mfa
    # Device session: a new sign-in (amr given) opens one; a token refresh after a security change
    # (MFA enrolment, password change) keeps the caller's current session and methods.
    from accfino.core.security import iam
    cur = getattr(getattr(request, "state", None), "auth", None) if request is not None else None
    if amr is None and cur and cur.get("sid"):
        sid, amr = cur["sid"], cur.get("amr") or ["pwd"]
        iam.extend_session(db, sid)
    else:
        amr = amr or ["pwd"]
        s = iam.create_session(db, user.id, ip=client_ip(request),
                               user_agent=request.headers.get("user-agent") if request is not None else None, amr=amr)
        sid = s.id
    token, exp = tokens.issue_access_token(user, sec.token_version, is_admin(user), org_id=use_org,
                                           mfa=bool(mfa_verified and has_mfa(db, sec)), sid=sid, amr=amr)
    from accfino.core.security.mfa_service import available_methods
    methods = available_methods(db, sec)
    return {"token": token, "token_expires_at": exp.isoformat(), "org_id": use_org,
            "organisations": orgs, "mfa_enabled": bool(methods), "mfa_methods": methods,
            "mfa_required_to_enrol": bool(config.MFA_ENFORCED and not methods),
            "password_change_required": bool(sec.must_change_password), "session_id": sid}


def record_success(db, user, ip, *, method="password"):
    sec = ensure_user_security(db, user.id)
    sec.failed_logins = 0
    sec.locked_until = None
    sec.last_login_at = datetime.utcnow()
    db.commit()
    audit.write("auth.login", user_id=user.id, username=user.username, ip=ip, detail={"method": method})
