"""
accfino_core.security.iam
-------------------------
Identity & access management primitives (Microsoft Entra-style):

  * client_ip()      - trustworthy client address behind reverse proxies (PROXY_HOPS)
  * device sessions  - one row per signed-in browser/device; revocable individually
  * account state    - disabled accounts, forced password change
  * Conditional Access - per-organisation policy: require MFA, allowed MFA methods,
                         IP allow-list, sign-in frequency; states off / report / on

Lookups on the request path are cached per worker for SESSION_CACHE_SECONDS.
"""
import ipaddress
import secrets
import time
from datetime import datetime, timedelta

from accfino_core import config

_cache: dict = {}


def _cached(key, loader, ttl=None):
    ttl = config.SESSION_CACHE_SECONDS if ttl is None else ttl
    hit = _cache.get(key)
    now = time.time()
    if hit and now - hit[1] < ttl:
        return hit[0]
    val = loader()
    _cache[key] = (val, now)
    return val


def forget(*keys):
    for k in keys:
        _cache.pop(k, None)


# ------------------------------------------------------------------- client IP --
def client_ip_from(headers, peer: str) -> str:
    """X-Forwarded-For is 'client, proxy1, proxy2' and each trusted proxy APPENDS the address it
    received the request from. With PROXY_HOPS trusted proxies, the real client is the entry
    PROXY_HOPS from the right. Anything a client writes into the header is to the left and ignored."""
    hops = config.PROXY_HOPS
    xff = [p.strip() for p in (headers.get("x-forwarded-for") or "").split(",") if p.strip()]
    if hops > 0 and xff:
        return xff[max(0, len(xff) - hops)]
    return peer or ""


def ip_allowed(ip: str, cidrs) -> bool:
    if not cidrs:
        return True
    try:
        addr = ipaddress.ip_address(ip)
    except ValueError:
        return False
    for c in cidrs:
        try:
            if addr in ipaddress.ip_network(c, strict=False):
                return True
        except ValueError:
            continue
    return False


def validate_cidrs(cidrs):
    out = []
    for c in cidrs or []:
        c = str(c).strip()
        if not c:
            continue
        try:
            out.append(str(ipaddress.ip_network(c, strict=False)))
        except ValueError:
            raise ValueError(f"'{c}' is not a valid IP address or range (e.g. 203.0.113.10 or 203.0.113.0/24)")
    return out


# --------------------------------------------------------------------- sessions --
def create_session(db, user_id, *, ip=None, user_agent=None, amr=None):
    from accfino_core import models as m
    s = m.UserSession(id=secrets.token_urlsafe(24), user_id=user_id, ip=(ip or "")[:64],
                      user_agent=(user_agent or "")[:400], auth_methods=amr or ["pwd"],
                      expires_at=datetime.utcnow() + timedelta(minutes=config.ACCESS_TOKEN_MINUTES))
    db.add(s)
    db.flush()
    return s


def extend_session(db, sid):
    from accfino_core import models as m
    s = db.get(m.UserSession, sid)
    if s and not s.revoked_at:
        s.expires_at = datetime.utcnow() + timedelta(minutes=config.ACCESS_TOKEN_MINUTES)
    return s


def session_info(sid):
    """(revoked_or_missing: bool, created_at: datetime|None) - cached."""
    def load():
        from db_app.database import SessionLocal
        from accfino_core import models as m
        db = SessionLocal()
        try:
            s = db.get(m.UserSession, sid)
            if s is None:
                return (True, None)
            return (bool(s.revoked_at) or s.expires_at < datetime.utcnow(), s.created_at)
        finally:
            db.close()
    return _cached(("sess", sid), load)


def revoke_sessions(db, user_id, *, sid=None, except_sid=None, reason="revoked"):
    from accfino_core import models as m
    q = db.query(m.UserSession).filter(m.UserSession.user_id == user_id, m.UserSession.revoked_at.is_(None))
    if sid:
        q = q.filter(m.UserSession.id == sid)
    if except_sid:
        q = q.filter(m.UserSession.id != except_sid)
    n = 0
    for s in q.all():
        s.revoked_at, s.revoked_reason = datetime.utcnow(), reason
        forget(("sess", s.id))
        n += 1
    return n


_last_touch: dict = {}


def touch_session(sid):
    """Update last_seen_at at most every 5 minutes per session."""
    now = time.time()
    if now - _last_touch.get(sid, 0) < 300:
        return
    _last_touch[sid] = now
    from db_app.database import SessionLocal
    from accfino_core import models as m
    db = SessionLocal()
    try:
        s = db.get(m.UserSession, sid)
        if s and not s.revoked_at:
            s.last_seen_at = datetime.utcnow()
            db.commit()
    except Exception:
        db.rollback()
    finally:
        db.close()


# ---------------------------------------------------------------- account state --
def account_state(user_id):
    """{'disabled': bool, 'must_change_password': bool} - cached."""
    def load():
        from db_app.database import SessionLocal
        from accfino_core import models as m
        db = SessionLocal()
        try:
            sec = db.get(m.UserSecurity, user_id)
            return {"disabled": bool(sec and sec.disabled_at),
                    "must_change_password": bool(sec and sec.must_change_password)}
        finally:
            db.close()
    return _cached(("acct", user_id), load)


# ---------------------------------------------------------- conditional access --
MFA_METHODS = ("passkey", "totp", "sms", "email", "recovery")


def org_policy(org_id):
    def load():
        from db_app.database import SessionLocal
        from accfino_core import models as m
        db = SessionLocal()
        try:
            p = db.get(m.AccessPolicy, org_id)
            if p is None or p.state == "off":
                return None
            return {"state": p.state, "applies_to": p.applies_to, "require_mfa": p.require_mfa,
                    "allowed": p.allowed_mfa_methods or None, "ips": p.ip_allowlist or None,
                    "max_hours": p.max_session_hours}
        finally:
            db.close()
    return _cached(("pol", org_id), load)


def member_role(user_id, org_id):
    def load():
        from db_app.database import SessionLocal
        from accfino_core import models as m
        db = SessionLocal()
        try:
            mem = db.query(m.OrgMembership).filter_by(user_id=user_id, org_id=org_id).first()
            return mem.role if mem and not mem.suspended_at else None
        finally:
            db.close()
    return _cached(("role", user_id, org_id), load)


def evaluate(policy, *, role, ip, mfa_verified, amr, session_started):
    """Return None if access is allowed, else (code, message)."""
    if not policy:
        return None
    if policy["applies_to"] == "admins" and role not in ("owner", "admin"):
        return None
    if policy["ips"] and not ip_allowed(ip, policy["ips"]):
        return ("ca_ip_blocked", f"Your organisation only allows access from approved networks (your address: {ip}).")
    if policy["max_hours"] and session_started and \
            datetime.utcnow() - session_started > timedelta(hours=policy["max_hours"]):
        return ("ca_reauth_required", "Your organisation requires you to sign in again.")
    if policy["require_mfa"] and not mfa_verified:
        return ("ca_mfa_required", "Your organisation requires two-step verification. Set it up under Security, then sign in again.")
    if policy["allowed"] and mfa_verified:
        used = [a for a in (amr or []) if a in MFA_METHODS]
        if used and not any(a in policy["allowed"] for a in used):
            names = ", ".join(policy["allowed"])
            return ("ca_method_not_allowed", f"Your organisation only accepts these verification methods: {names}. Sign in again using one of them.")
    return None
