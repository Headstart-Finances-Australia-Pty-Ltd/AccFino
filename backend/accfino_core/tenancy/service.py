"""
Multi-tenant organisations: tenant URLs, access/invitation codes, licence seats and signup throttling.

Security model (the rules the rest of the code relies on)
  * An organisation's NAME, ID or URL name is public information. It is never the credential.
  * Joining an existing organisation needs a valid ACCESS CODE issued by that organisation. Codes are random (40 bits), single-use unless an
    owner/admin configures otherwise, expire, can be revoked, are bound to ONE organisation and one role, and are stored only as an HMAC hash.
    The plain code is shown once, to the administrator who generated it.
  * Brute force is limited by recording failed attempts per IP+organisation, per organisation and per IP (database backed, so it holds across workers).
  * Every failure gives the caller the same generic message; the real reason goes to the audit log.
  * Licence seats: active members + codes still waiting to be used can never exceed the organisation's licensed users.
  * Tenant isolation is decided by `tenant_decision` (pure, unit-tested) and enforced in the auth middleware and in `current_org`.
"""
import hashlib
import hmac
import os
import re
import secrets
from datetime import datetime, timedelta
from typing import Optional

from fastapi import HTTPException
from sqlalchemy import func
from sqlalchemy.orm import Session

from accfino_core import models as m
from accfino_core.security import audit
from accfino_core.tenancy.models import OrgInvite, OrgProfile, SignupAttempt

# ------------------------------------------------------------------------------------------------ tenant URLs --
RESERVED_SLUGS = {"www", "app", "api", "admin", "mail", "email", "smtp", "ftp", "static", "assets", "cdn", "help", "support", "status", "docs", "blog", "login", "signup",
                  "register", "auth", "billing", "portal", "dashboard", "demo", "test", "staging", "dev", "root", "accfino", "ns1", "ns2", "autodiscover", "webmail"}
_SLUG_RE = re.compile(r"^[a-z0-9](?:[a-z0-9-]{1,38}[a-z0-9])$")


def valid_slug(s: str) -> bool:
    return bool(s) and bool(_SLUG_RE.match(s)) and "--" not in s and s not in RESERVED_SLUGS


_COMPANY_WORDS = {"pty", "ltd", "limited", "inc", "llc", "co", "company", "proprietary"}


def slugify(name: str) -> str:
    parts = [p for p in re.sub(r"[^a-z0-9]+", "-", (name or "").lower()).split("-") if p]
    while len(parts) > 1 and parts[-1] in _COMPANY_WORDS:          # "Acme Pty Ltd" -> "acme"
        parts.pop()
    s = "-".join(parts)[:38].strip("-") or "org"
    if len(s) < 3:
        s = (s + "-org")[:38]
    return s


def unique_slug(db: Session, base: str) -> str:
    base = slugify(base)
    cand, n = base, 1
    while not valid_slug(cand) or db.query(OrgProfile.org_id).filter_by(slug=cand).first():
        n += 1
        cand = f"{base[:36 - len(str(n))]}-{n}"
    return cand


def base_domain() -> str:
    return os.environ.get("TENANT_BASE_DOMAIN", "").strip().lower().lstrip(".")


def tenant_url(slug: str) -> Optional[str]:
    """https://<slug>.<TENANT_BASE_DOMAIN> - None when tenant URLs are not configured (single-host / local development)."""
    base = base_domain()
    if not base or not slug:
        return None
    return f"{os.environ.get('TENANT_SCHEME', 'https')}://{slug}.{base}"


def tenant_from_host(host: Optional[str]) -> Optional[str]:
    """The tenant name in a Host header, or None (apex domain, localhost, unknown domain, tenant URLs not configured)."""
    base = base_domain().split(":")[0]
    if not base or not host:
        return None
    h = host.split(",")[0].strip().lower().split(":")[0]
    if not h.endswith("." + base):
        return None
    label = h[: -(len(base) + 1)]
    if "." in label or not valid_slug(label):
        return None
    return label


def request_tenant(headers) -> Optional[str]:
    return tenant_from_host(headers.get("x-forwarded-host") or headers.get("host"))


def org_id_for_slug(db: Session, slug: str) -> Optional[int]:
    p = db.query(OrgProfile).filter_by(slug=slug).first()
    return p.org_id if p else None


def ensure_profile(db: Session, org: "m.Organisation", **fields) -> OrgProfile:
    p = db.get(OrgProfile, org.id)
    if p is None:
        p = OrgProfile(org_id=org.id, slug=unique_slug(db, fields.pop("slug", None) or org.name))
        db.add(p)
    for k, v in fields.items():
        if hasattr(p, k) and v is not None:
            setattr(p, k, v)
    db.flush()
    return p


def backfill_profiles(db: Session) -> int:
    """Give every organisation created before tenant URLs existed a URL name."""
    n = 0
    for o in db.query(m.Organisation).outerjoin(OrgProfile, OrgProfile.org_id == m.Organisation.id).filter(OrgProfile.org_id.is_(None)):
        ensure_profile(db, o)
        n += 1
    db.flush()
    return n


def location(p: OrgProfile) -> str:
    return ", ".join(x for x in (p.city, p.state) if x)


# ------------------------------------------------------------------------------------------------ tenant isolation --
def tenant_decision(*, org_id_of_tenant: Optional[int], role_in_tenant: Optional[str], is_platform_admin: bool, org_header: Optional[str]):
    """Pure rule used by the middleware. -> None when allowed, else (http_status, code, message).

      * the host names an organisation that does not exist           -> 404
      * the caller is not an active member of that organisation      -> 403   (platform administrators may enter any tenant)
      * the caller sends a different organisation id than the host   -> 403   (changing X-Org-Id / ?org_id= can never move you to another tenant)
    """
    if org_id_of_tenant is None:
        return 404, "tenant_unknown", "This organisation address does not exist."
    if not is_platform_admin and not role_in_tenant:
        return 403, "tenant_forbidden", "You do not have access to this organisation."
    if org_header not in (None, "") and str(org_header).strip() != str(org_id_of_tenant):
        return 403, "tenant_mismatch", "That request names a different organisation than this address."
    return None


# ------------------------------------------------------------------------------------------------ licence seats --
def seat_status(db: Session, org_id: int) -> dict:
    """licensed (None = unlimited), active members, codes waiting to be used (each reserves its remaining uses), and what is left."""
    from accfino_core.subscription import service as S
    licensed = S.entitlements(db, org_id)["seats"]
    active = db.query(m.OrgMembership).filter_by(org_id=org_id).filter(m.OrgMembership.suspended_at.is_(None)).count()
    now = datetime.utcnow()
    pending = 0
    for i in db.query(OrgInvite).filter_by(org_id=org_id).filter(OrgInvite.revoked_at.is_(None), OrgInvite.expires_at > now):
        pending += max(0, (i.max_uses or 1) - (i.used_count or 0))
    return {"licensed": licensed, "active": active, "pending": pending, "available": None if licensed is None else max(0, licensed - active - pending)}


SEAT_MESSAGE = "This organisation has reached its licensed user limit. Please contact your organisation administrator."


# ------------------------------------------------------------------------------------------------ access codes --
_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"        # no 0/O/1/I: codes are read out and typed by people


def _secret_key() -> bytes:
    from accfino_core.security import tokens
    return ("tenancy.invite|" + tokens._secret()).encode()


def normalise_code(code: str) -> str:
    return re.sub(r"[^A-Z0-9]", "", (code or "").upper())


def hash_code(code: str) -> str:
    return hmac.new(_secret_key(), normalise_code(code).encode(), hashlib.sha256).hexdigest()


def new_code(slug: str) -> str:
    prefix = (re.sub(r"[^A-Z]", "", slug.upper()) + "ORG")[:3]
    body = "".join(secrets.choice(_ALPHABET) for _ in range(8))
    return f"{prefix}-{body[:4]}-{body[4:]}"


def create_invites(db: Session, org: "m.Organisation", created_by: int, *, role: str, count: int, days: int, max_uses: int, label: Optional[str]):
    """-> [(OrgInvite, plain code)]. The plain codes exist only in this return value."""
    if role in ("owner", "admin"):
        raise HTTPException(422, "An access code cannot create an Organisation Admin: each organisation has exactly one, who is changed with 'Transfer admin'. "
                                 f"Choose one of: {', '.join(m.ASSIGNABLE_ROLES)}")
    if role not in m.ASSIGNABLE_ROLES:
        raise HTTPException(422, f"role must be one of {', '.join(m.ASSIGNABLE_ROLES)}")
    if not 1 <= count <= 50:
        raise HTTPException(422, "Create between 1 and 50 codes at a time")
    if not 1 <= days <= 90:
        raise HTTPException(422, "Codes can last from 1 to 90 days")
    if not 1 <= max_uses <= 50:
        raise HTTPException(422, "A code can be used from 1 to 50 times")
    st = seat_status(db, org.id)
    need = count * max_uses
    if st["available"] is not None and need > st["available"]:
        raise HTTPException(409, f"Not enough licensed user slots: {st['available']} available (licensed {st['licensed']}, active {st['active']}, pending codes {st['pending']}), "
                                 f"{need} needed. Revoke unused codes or upgrade the plan.")
    slug = ensure_profile(db, org).slug
    out = []
    for _ in range(count):
        code = new_code(slug)
        inv = OrgInvite(org_id=org.id, code_hash=hash_code(code), code_hint=code[:8] + "-....", role=role, label=(label or "")[:100] or None, created_by=created_by,
                        expires_at=datetime.utcnow() + timedelta(days=days), max_uses=max_uses)
        db.add(inv)
        out.append((inv, code))
    db.flush()
    return out


def invite_status(i: OrgInvite, now=None) -> str:
    now = now or datetime.utcnow()
    if i.revoked_at:
        return "revoked"
    if (i.used_count or 0) >= (i.max_uses or 1):
        return "used"
    if i.expires_at <= now:
        return "expired"
    return "unused" if not i.used_count else "partly_used"


# ------------------------------------------------------------------------------------------------ throttling --
WINDOWS = {"code_ip_org": (5, 15), "code_org": (25, 60), "code_ip": (30, 60), "lookup_ip": (60, 10), "create_ip": (5, 60)}      # (max, minutes)


def _count(db, minutes, **flt):
    q = db.query(func.count(SignupAttempt.id)).filter(SignupAttempt.created_at > datetime.utcnow() - timedelta(minutes=minutes))
    for k, v in flt.items():
        q = q.filter(getattr(SignupAttempt, k) == v)
    return q.scalar() or 0


def _too_many(minutes):
    raise HTTPException(429, "Too many attempts. Please wait a while and try again.", headers={"Retry-After": str(minutes * 60)})


def throttle(db: Session, ip: str, kind: str, org_id: Optional[int] = None):
    """Raise 429 when this caller (or organisation) has made too many recent attempts of this kind."""
    if kind == "code":
        for rule, flt in (("code_ip_org", dict(ip=ip, org_id=org_id)), ("code_org", dict(org_id=org_id)), ("code_ip", dict(ip=ip))):
            limit, mins = WINDOWS[rule]
            if org_id is None and "org_id" in flt:
                continue
            if _count(db, mins, kind="code", success=False, **flt) >= limit:
                audit.write("signup.code_lockout", org_id=org_id, ip=ip, entity="organisation", entity_id=org_id, detail={"rule": rule})
                _too_many(mins)
    elif kind == "lookup":
        if _count(db, WINDOWS["lookup_ip"][1], kind="lookup", ip=ip) >= WINDOWS["lookup_ip"][0]:
            _too_many(WINDOWS["lookup_ip"][1])
    elif kind == "create":
        if _count(db, WINDOWS["create_ip"][1], kind="create", ip=ip) >= WINDOWS["create_ip"][0]:
            _too_many(WINDOWS["create_ip"][1])


def record_attempt(db: Session, ip: str, kind: str, *, org_id=None, success=False, reason=None):
    db.add(SignupAttempt(ip=(ip or "?")[:64], org_id=org_id, kind=kind, success=success, reason=reason))
    db.query(SignupAttempt).filter(SignupAttempt.created_at < datetime.utcnow() - timedelta(days=2)).delete(synchronize_session=False)
    db.flush()


# ------------------------------------------------------------------------------------------------ verifying a code --
class CodeRejected(Exception):
    def __init__(self, reason, status=400, message="That access code is not valid, or has expired. Check it with your organisation administrator."):
        self.reason, self.status, self.message = reason, status, message


def verify_code(db: Session, ip: str, slug: str, code: str):
    """-> (org, invite). Raises HTTPException(429) when throttled, or CodeRejected (after recording the failed attempt).
    Does NOT consume the code."""
    slug = (slug or "").strip().lower()
    org_id = org_id_for_slug(db, slug) if valid_slug(slug) else None
    throttle(db, ip, "code", org_id)
    reason = None
    inv = None
    if org_id is None:
        reason = "unknown_organisation"
    elif len(normalise_code(code)) < 8:
        reason = "malformed"
    else:
        inv = db.query(OrgInvite).filter_by(code_hash=hash_code(code)).first()
        if inv is None:
            reason = "unknown_code"
        elif inv.org_id != org_id:
            reason = "wrong_organisation"            # a real code, used against a different organisation
        else:
            reason = {"revoked": "revoked", "used": "already_used", "expired": "expired"}.get(invite_status(inv))
    if reason:
        record_attempt(db, ip, "code", org_id=org_id, success=False, reason=reason)
        audit.write("signup.code_failed", org_id=org_id, ip=ip, entity="organisation", entity_id=org_id, detail={"reason": reason, "slug": slug[:40]})
        raise CodeRejected(reason)
    st = seat_status(db, org_id)
    if st["licensed"] is not None and st["active"] >= st["licensed"]:           # this code's own slot is reserved in `pending`; no free seat is left for it
        audit.write("signup.rejected_seat_limit", org_id=org_id, ip=ip, entity="organisation", entity_id=org_id, detail={"licensed": st["licensed"], "active": st["active"]})
        raise CodeRejected("seat_limit", 403, SEAT_MESSAGE)
    return db.get(m.Organisation, org_id), inv


def legacy_signup_allowed(db: Session) -> bool:
    """The old open /auth/register (anyone, no organisation) is closed. It stays open only for the very first user of an empty system
    (bootstrap) or when ACCFINO_OPEN_SIGNUP=1 is set deliberately (emergency rollback)."""
    if os.environ.get("ACCFINO_OPEN_SIGNUP", "").strip() in ("1", "true", "yes"):
        return True
    from db_app.models import User
    return db.query(User).count() == 0
