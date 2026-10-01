"""Organisation-first signup and invitation management.

PUBLIC (no sign-in)                                   - every one rate limited, and none reveals anything beyond name + town
  GET  /tenant/current                       which organisation does this web address belong to (name only)
  POST /signup/organisation/validate         check organisation details, propose the web address (nothing saved)
  POST /signup/organisation                  create organisation + its first user as OWNER, atomically
  GET  /signup/organisations/search?q=       find an organisation to join (>= 3 letters, 5 results, name + town only)
  GET  /signup/organisations/lookup?slug=    exact web-address lookup (also finds organisations hidden from search)
  POST /signup/verify-code                   organisation + access code -> short-lived signup token (code NOT consumed)
  POST /signup/join                          signup token + user details -> user created in THAT organisation with the code's role

ORGANISATION ADMIN ONLY (the single owner; every call re-checks it on the server - other members get 403)
  GET/POST /org/current/invites, DELETE /org/current/invites/{id}     licence usage, create (shown once), revoke
  GET/PATCH /org/current/tenant                                       organisation profile, web address, discoverability

Every account needs a valid email address AND phone number: enforced here (API), in the User model and by a PostgreSQL trigger.

Rule: no organisation context + no valid access code = no signup. Selecting an existing organisation proves nothing.
"""
import re
from datetime import datetime, timedelta
from typing import Optional

import bcrypt
import jwt
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy import func
from sqlalchemy.orm import Session

from accfino_core import models as m
from accfino_core import notifications as N
from accfino_core import org_admin as OA
from accfino_core.api.org import valid_abn
from accfino_core.security import audit, tokens
from accfino_core.security import contact as C
from accfino_core.security import contact_verify as V
from accfino_core.security.context import OrgContext, current_org
from accfino_core.security.login import client_ip
from accfino_core.tenancy import service as T
from accfino_core.tenancy.models import OrgInvite, OrgProfile
from db_app.database import get_db

tenant_router = APIRouter()
signup_router = APIRouter()
invites_router = APIRouter()
admin_tenant_router = APIRouter()

_EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]{2,}$")
_SIGNUP_TOKEN_MINUTES = 15


# ------------------------------------------------------------------------------------------------ models --
class OrgDetails(BaseModel):
    name: str
    abn: Optional[str] = None
    acn: Optional[str] = None
    other_id: Optional[str] = None
    entity_type: Optional[str] = None
    address: Optional[str] = None
    city: Optional[str] = None
    state: Optional[str] = None
    postcode: Optional[str] = None
    phone: Optional[str] = None
    contact_email: Optional[str] = None
    industry: Optional[str] = None
    slug: Optional[str] = None


class UserDetails(BaseModel):
    # email and phone are validated by accfino_core.security.contact (not by pydantic) so the messages are the exact, friendly ones - and a request that
    # leaves them out is rejected with the same message as one that sends garbage.
    first_name: Optional[str] = None
    last_name: Optional[str] = None
    email: Optional[str] = None
    phone: Optional[str] = None
    password: Optional[str] = None
    email_token: Optional[str] = None      # proof that the email address was verified (contact_verify) - required when verification is on
    phone_token: Optional[str] = None      # proof that the phone number was verified (required where an SMS can reach it)


class NewOrgIn(BaseModel):
    org: OrgDetails
    user: UserDetails


class CodeIn(BaseModel):
    slug: str
    code: str


class JoinIn(BaseModel):
    signup_token: str
    user: UserDetails


# ------------------------------------------------------------------------------------------------ validation --
def valid_acn(acn: str) -> bool:
    d = re.sub(r"\s", "", acn or "")
    if not re.fullmatch(r"\d{9}", d):
        return False
    s = sum(int(c) * w for c, w in zip(d[:8], range(8, 0, -1)))
    return (10 - s % 10) % 10 == int(d[8])


def _clean_org(db: Session, o: OrgDetails) -> dict:
    errs = []
    name = (o.name or "").strip()
    if not 2 <= len(name) <= 200:
        errs.append("Organisation name is required (2-200 characters)")
    abn = re.sub(r"\s", "", o.abn or "")
    acn = re.sub(r"\s", "", o.acn or "")
    other = (o.other_id or "").strip()
    if not (abn or acn or other):
        errs.append("An organisation identifier is required: ABN, ACN or another registration number")
    if abn and not valid_abn(abn):
        errs.append("That ABN is not valid (11 digits, ATO checksum)")
    if acn and not valid_acn(acn):
        errs.append("That ACN is not valid (9 digits, ASIC checksum)")
    for field, label in (("address", "Address"), ("city", "City or suburb"), ("state", "State")):
        if not (getattr(o, field) or "").strip():
            errs.append(f"{label} is required")
    email = (o.contact_email or "").strip()
    if email and not C.is_valid_email(email):                 # optional: when left blank the Organisation Admin's own email is the organisation's contact
        errs.append("The organisation contact email is not valid")
    if errs:
        raise HTTPException(422, "; ".join(errs))
    if abn and db.query(m.Organisation.id).filter(m.Organisation.abn == abn).first():
        raise HTTPException(409, "An organisation with this ABN is already registered. To join it, ask its administrator for an access code and choose 'Join an existing organisation'.")
    if o.slug:
        slug = o.slug.strip().lower()
        if not T.valid_slug(slug):
            raise HTTPException(422, "The web address must be 3-40 lower-case letters, digits or single dashes, and not a reserved word")
        if db.query(OrgProfile.org_id).filter_by(slug=slug).first():
            raise HTTPException(409, "That web address is already taken. Choose another.")
    else:
        slug = T.unique_slug(db, name)
    return dict(name=name, abn=abn or None, acn=acn or None, other_id=other or None, entity_type=(o.entity_type or None), address=o.address.strip(), city=o.city.strip()[:100],
                state=o.state.strip()[:30], postcode=(o.postcode or "").strip()[:10] or None, phone=(o.phone or "").strip()[:40] or None, contact_email=email.lower()[:200] or None,
                industry=(o.industry or "").strip()[:100] or None, slug=slug)


def _clean_user(db: Session, u: UserDetails):
    """Validates the person's details on the SERVER: names, a valid email, a valid phone, a strong password. -> (first, last, email, phone_e164)."""
    from accfino_core.security.passwords import validate_new_password
    first, last = (u.first_name or "").strip(), (u.last_name or "").strip()
    if not first or not last:
        raise HTTPException(422, "First name and last name are required")
    try:
        email, phone = C.validate_contact(u.email, u.phone)          # both are mandatory; every problem is reported at once
    except C.ContactError as e:
        raise C.http_422(e)
    V.require_proofs(email, phone, u.email_token, u.phone_token)       # 422 'Please verify your email address / phone number.' without a valid proof for THESE values
    validate_new_password(u.password or "")
    from db_app.models import User
    if db.query(User.id).filter(func.lower(User.email) == email).first():
        raise HTTPException(409, "That email is already registered. Sign in instead, or ask your organisation administrator to add you.")
    return first[:100], last[:100], email, phone


def _create_user(db: Session, first: str, last: str, email: str, phone: str, password: str, details: Optional["UserDetails"] = None):
    """A normal AccFino user (same defaults as the legacy registration) - but with NO personal organisation: they belong only to the one they joined."""
    import json as _json
    from db_app.api.auth import ensure_users_full_name_column
    from db_app.models import Role, User
    from accfino_core.migrate import ensure_user_security
    ensure_users_full_name_column(db)
    base = re.sub(r"[^a-z0-9._-]", "", email.split("@")[0].lower())[:60] or "user"
    username, n = base, 1
    while db.query(User.id).filter(User.username == username).first():
        n += 1
        username = f"{base}{n}"
    role = db.query(Role).filter(Role.name == "user").first()
    if role is None:
        raise HTTPException(500, "The 'user' role is missing from the database")
    u = User(username=username, full_name=f"{first} {last}", email=email, password=bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode(), phone=phone, address="", home_company="")
    u.roles.append(role)
    db.add(u)
    db.flush()
    today = datetime.utcnow().date()
    # No per-user licence record: what a person may use comes from their ORGANISATION's plan (Admin > Subscriptions), not from a personal base plan.
    ensure_user_security(db, u.id)
    if details is not None:                                           # remember what was proven (the proofs were already required in _clean_user)
        V.record(db, u.id, email=V.token_ok(details.email_token, "email", email), phone=V.token_ok(details.phone_token, "phone", phone))
    return u


def _minimal(p: OrgProfile, o: "m.Organisation") -> dict:
    return {"slug": p.slug, "name": o.name, "location": T.location(p)}


def _sign_token(org_id: int, invite_id: int) -> str:
    now = datetime.utcnow()
    return jwt.encode({"typ": "signup", "org": org_id, "inv": invite_id, "iat": now, "exp": now + timedelta(minutes=_SIGNUP_TOKEN_MINUTES)}, tokens._secret(), algorithm="HS256")


def _read_token(tok: str) -> dict:
    try:
        d = jwt.decode(tok or "", tokens._secret(), algorithms=["HS256"])
    except jwt.PyJWTError:
        raise HTTPException(400, "Your verification has expired. Please enter the organisation access code again.")
    if d.get("typ") != "signup":
        raise HTTPException(400, "Invalid signup token")
    return d


def _result(slug):
    url = T.tenant_url(slug)
    return {"tenant_url": url, "login_url": (url + "/login") if url else None, "slug": slug}


# ------------------------------------------------------------------------------------------------ public: tenant --
@tenant_router.get("/current")
def tenant_current(request: Request, db: Session = Depends(get_db)):
    slug = T.request_tenant(request.headers)
    base = {"tenant": slug, "found": False, "name": None, "tenant_urls_enabled": bool(T.base_domain())}
    if slug:
        oid = T.org_id_for_slug(db, slug)
        o = db.get(m.Organisation, oid) if oid else None
        if o and o.is_active:
            base.update(found=True, name=o.name)
    return base


# ------------------------------------------------------------------------------------------------ public: verify email / phone --
class SendIn(BaseModel):
    channel: str
    destination: str


class VerifyIn(BaseModel):
    channel: str
    destination: str
    code: str


@signup_router.get("/contact/config")
def contact_config():
    return V.config()


@signup_router.post("/contact/send")
def contact_send(body: SendIn, request: Request, db: Session = Depends(get_db)):
    """Send a verification code to an email address or phone number (before an account exists). Rate limited per address and per IP."""
    return V.send(db, body.channel, body.destination, client_ip(request))


@signup_router.post("/contact/verify")
def contact_verify(body: VerifyIn, request: Request, db: Session = Depends(get_db)):
    """Check the code -> a short-lived proof token to send with the sign-up request."""
    T.throttle(db, client_ip(request), "lookup")
    T.record_attempt(db, client_ip(request), "lookup", success=True)
    db.commit()
    return V.verify(db, body.channel, body.destination, body.code)


# ------------------------------------------------------------------------------------------------ public: new organisation --
@signup_router.post("/organisation/validate")
def validate_org(body: OrgDetails, request: Request, db: Session = Depends(get_db)):
    ip = client_ip(request)
    T.throttle(db, ip, "lookup")
    T.record_attempt(db, ip, "lookup", success=True)
    db.commit()
    c = _clean_org(db, body)
    return {"ok": True, "slug": c["slug"], "tenant_url": T.tenant_url(c["slug"])}


@signup_router.post("/organisation")
def create_organisation(body: NewOrgIn, request: Request, db: Session = Depends(get_db)):
    ip = client_ip(request)
    T.throttle(db, ip, "create")
    c = _clean_org(db, body.org)
    first, last, email, phone = _clean_user(db, body.user)
    from accfino_core.migrate import seed_org_ledger
    from accfino_core.subscription.service import start_subscription
    org = m.Organisation(name=c["name"], legal_name=c["name"], abn=c["abn"], entity_type=c["entity_type"])
    db.add(org)
    db.flush()
    user = _create_user(db, first, last, email, phone, body.user.password, body.user)
    # The Organisation Admin's email and phone ARE the organisation's primary contact: they fill the contact fields the form left blank.
    contact_fields = {k: c[k] for k in ("slug", "acn", "other_id", "address", "city", "state", "postcode", "industry")}
    contact_fields.update(phone=c["phone"] or user.phone, contact_email=c["contact_email"] or user.email)
    T.ensure_profile(db, org, **contact_fields)
    OA.assign_first_admin(db, org, user.id, is_default=True)                                  # the creator is THE Organisation Admin / Account Owner
    seed_org_ledger(db, org)
    start_subscription(db, org.id)                                                            # the platform's default plan: licensed users, modules
    T.record_attempt(db, ip, "create", org_id=org.id, success=True)
    db.commit()
    audit.write("signup.organisation_created", user_id=user.id, username=user.username, org_id=org.id, ip=ip, entity="organisation", entity_id=org.id, detail={"slug": c["slug"]})
    audit.write("auth.registered", user_id=user.id, username=user.username, org_id=org.id, ip=ip)
    N.org_created(db, org, user, c["slug"])                                                   # organisation-level: to the Organisation Admin's email
    return {"ok": True, "organisation": {"name": org.name, **_result(c["slug"])}, **_result(c["slug"])}


# ------------------------------------------------------------------------------------------------ public: join an organisation --
@signup_router.get("/organisations/search")
def search_orgs(q: str, request: Request, db: Session = Depends(get_db)):
    ip = client_ip(request)
    T.throttle(db, ip, "lookup")
    T.record_attempt(db, ip, "lookup", success=True)
    db.commit()
    term = (q or "").strip().lower()
    if len(term) < 3:
        raise HTTPException(422, "Type at least 3 letters of the organisation's name")
    like = "%" + term.replace("\\", "\\\\").replace("%", r"\%").replace("_", r"\_") + "%"
    rows = (db.query(OrgProfile, m.Organisation).join(m.Organisation, m.Organisation.id == OrgProfile.org_id)
            .filter(OrgProfile.discoverable.is_(True), m.Organisation.is_active.is_(True), func.lower(m.Organisation.name).like(like, escape="\\"))
            .order_by(m.Organisation.name).limit(5).all())
    return {"items": [_minimal(p, o) for p, o in rows]}


@signup_router.get("/organisations/lookup")
def lookup_org(slug: str, request: Request, db: Session = Depends(get_db)):
    ip = client_ip(request)
    T.throttle(db, ip, "lookup")
    T.record_attempt(db, ip, "lookup", success=True)
    db.commit()
    s = (slug or "").strip().lower()
    oid = T.org_id_for_slug(db, s) if T.valid_slug(s) else None
    o = db.get(m.Organisation, oid) if oid else None
    if not o or not o.is_active:
        raise HTTPException(404, "No organisation found at that web address")
    return _minimal(db.get(OrgProfile, oid), o)


@signup_router.post("/verify-code")
def verify_code(body: CodeIn, request: Request, db: Session = Depends(get_db)):
    ip = client_ip(request)
    try:
        org, inv = T.verify_code(db, ip, body.slug, body.code)
    except T.CodeRejected as e:
        db.commit()                                  # keep the failed-attempt record that the throttle counts
        if e.reason == "seat_limit":
            _oid = T.org_id_for_slug(db, (body.slug or "").strip().lower())
            if _oid:
                N.licence_rejected(db, _oid)
        raise HTTPException(e.status, e.message)
    except HTTPException as e:
        db.commit()
        if e.status_code == 429:                     # code guessing locked this organisation out: the Organisation Admin is told
            _oid = T.org_id_for_slug(db, (body.slug or "").strip().lower())
            if _oid:
                N.security_alert(db, _oid, "Access code guessing", "Repeated wrong access codes were entered for your organisation, so sign-ups are temporarily locked. "
                                 "If this was not a colleague mistyping, revoke your unused access codes and generate new ones.")
        raise
    p = db.get(OrgProfile, org.id)
    return {"ok": True, "signup_token": _sign_token(org.id, inv.id), "role": inv.role, "organisation": _minimal(p, org), "expires_in_minutes": _SIGNUP_TOKEN_MINUTES}


@signup_router.post("/join")
def join(body: JoinIn, request: Request, db: Session = Depends(get_db)):
    ip = client_ip(request)
    tok = _read_token(body.signup_token)
    first, last, email, phone = _clean_user(db, body.user)
    inv = db.query(OrgInvite).filter_by(id=tok["inv"], org_id=tok["org"]).with_for_update().first()
    reason = None
    if inv is None:
        reason = "unknown_code"
    else:
        reason = {"revoked": "revoked", "used": "already_used", "expired": "expired"}.get(T.invite_status(inv))
    if reason:                                        # revoked / used / expired between 'verify' and 'create account'
        audit.write("signup.code_failed", org_id=tok["org"], ip=ip, entity="organisation", entity_id=tok["org"], detail={"reason": reason, "stage": "join"})
        raise HTTPException(400, "That access code is no longer valid. Ask your organisation administrator for a new one.")
    st = T.seat_status(db, inv.org_id)
    if st["licensed"] is not None and st["active"] >= st["licensed"]:
        audit.write("signup.rejected_seat_limit", org_id=inv.org_id, ip=ip, entity="organisation", entity_id=inv.org_id, detail={"licensed": st["licensed"], "active": st["active"]})
        N.licence_rejected(db, inv.org_id)
        raise HTTPException(403, T.SEAT_MESSAGE)
    user = _create_user(db, first, last, email, phone, body.user.password, body.user)
    db.add(m.OrgMembership(org_id=inv.org_id, user_id=user.id, role=inv.role, is_default=True))
    inv.used_count = (inv.used_count or 0) + 1
    inv.last_used_by, inv.last_used_at = user.id, datetime.utcnow()
    T.record_attempt(db, ip, "code", org_id=inv.org_id, success=True, reason="joined")
    p = db.get(OrgProfile, inv.org_id)
    org_id, role, inv_id, slug = inv.org_id, inv.role, inv.id, p.slug
    db.commit()
    audit.write("signup.invite_redeemed", user_id=user.id, username=user.username, org_id=org_id, ip=ip, entity="invite", entity_id=inv_id, detail={"role": role})
    audit.write("auth.registered", user_id=user.id, username=user.username, org_id=org_id, ip=ip)
    org = db.get(m.Organisation, org_id)
    N.user_joined(db, org, user, role)                                                        # organisation-level: the Organisation Admin is told
    N.licence_usage(db, org, T.seat_status(db, org_id))                                       # ...and warned when the licence is nearly or completely full
    return {"ok": True, "organisation": {"name": org.name, **_result(slug)}, **_result(slug)}


# ------------------------------------------------------------------------------------------------ organisation administrators --
class InviteIn(BaseModel):
    role: str = "bookkeeper"                 # an Organisation User role; the Organisation Admin role cannot be issued by a code
    count: int = 1
    expires_in_days: int = 7
    max_uses: int = 1
    label: Optional[str] = None


def _invite_dict(i: OrgInvite, now=None) -> dict:
    return {"id": i.id, "code_hint": i.code_hint, "role": i.role, "label": i.label, "status": T.invite_status(i, now), "uses": i.used_count or 0, "max_uses": i.max_uses,
            "created_at": i.created_at.isoformat() if i.created_at else None, "expires_at": i.expires_at.isoformat(), "created_by": i.created_by,
            "last_used_at": i.last_used_at.isoformat() if i.last_used_at else None, "revoked_at": i.revoked_at.isoformat() if i.revoked_at else None}


def _summary(db: Session, org_id: int) -> dict:
    st = T.seat_status(db, org_id)
    counts = {"unused": 0, "partly_used": 0, "used": 0, "expired": 0, "revoked": 0}
    now = datetime.utcnow()
    for i in db.query(OrgInvite).filter_by(org_id=org_id):
        counts[T.invite_status(i, now)] += 1
    return {"licensed_users": st["licensed"], "active_users": st["active"], "pending_invitations": st["pending"], "available_slots": st["available"], "codes": counts}


@invites_router.get("")
def list_invites(ctx: OrgContext = Depends(current_org), db: Session = Depends(get_db)):
    ctx.require_org_admin()
    rows = db.query(OrgInvite).filter_by(org_id=ctx.org.id).order_by(OrgInvite.id.desc()).limit(500).all()
    db.commit()
    return {"summary": _summary(db, ctx.org.id), "overview": OA.overview(db, ctx.org), "items": [_invite_dict(i) for i in rows]}


@invites_router.post("")
def create_invites(body: InviteIn, request: Request, ctx: OrgContext = Depends(current_org), db: Session = Depends(get_db)):
    ctx.require_org_admin()
    made = T.create_invites(db, ctx.org, ctx.user_id, role=body.role, count=body.count, days=body.expires_in_days, max_uses=body.max_uses, label=body.label)
    db.commit()
    audit.write("invite.created", user_id=ctx.user_id, username=ctx.username, org_id=ctx.org.id, ip=client_ip(request), entity="invite", entity_id=made[0][0].id,
                detail={"count": len(made), "role": body.role, "days": body.expires_in_days, "max_uses": body.max_uses})
    if ctx.user_id != OA.org_contact(db, ctx.org.id)["user_id"]:                         # created by platform support, not by the admin: tell the admin
        N.notify_org_admin(db, ctx.org.id, "invites_created", "Access codes were generated", f"{ctx.username} generated {len(made)} access code(s) for {ctx.org.name}.")
    return {"codes": [{**_invite_dict(i), "code": code} for i, code in made], "note": "Copy these now. For security the full codes are not stored and cannot be shown again.",
            "summary": _summary(db, ctx.org.id), "tenant_url": T.tenant_url(db.get(OrgProfile, ctx.org.id).slug)}


@invites_router.delete("/{invite_id}")
def revoke_invite(invite_id: int, request: Request, ctx: OrgContext = Depends(current_org), db: Session = Depends(get_db)):
    ctx.require_org_admin()
    i = db.query(OrgInvite).filter_by(id=invite_id, org_id=ctx.org.id).first()       # another organisation's code is simply "not found"
    if i is None:
        raise HTTPException(404, "Access code not found")
    if i.revoked_at is None:
        i.revoked_at, i.revoked_by = datetime.utcnow(), ctx.user_id
        db.commit()
        audit.write("invite.revoked", user_id=ctx.user_id, username=ctx.username, org_id=ctx.org.id, ip=client_ip(request), entity="invite", entity_id=i.id, detail={"hint": i.code_hint})
    return {"ok": True, "summary": _summary(db, ctx.org.id)}


class TenantPatch(BaseModel):
    address: Optional[str] = None
    city: Optional[str] = None
    state: Optional[str] = None
    postcode: Optional[str] = None
    phone: Optional[str] = None
    contact_email: Optional[str] = None
    industry: Optional[str] = None
    discoverable: Optional[bool] = None


def _tenant_dict(db, ctx):
    p = T.ensure_profile(db, ctx.org)
    return {"slug": p.slug, "tenant_url": T.tenant_url(p.slug), "tenant_urls_enabled": bool(T.base_domain()), "address": p.address, "city": p.city, "state": p.state, "postcode": p.postcode,
            "phone": p.phone, "contact_email": p.contact_email, "industry": p.industry, "acn": p.acn, "other_id": p.other_id, "discoverable": p.discoverable,
            "primary_contact": OA.org_contact(db, ctx.org.id),          # the Organisation Admin: the organisation's primary email and phone (read-only here)
            "licence": _summary(db, ctx.org.id)}


@admin_tenant_router.get("")
def get_tenant(ctx: OrgContext = Depends(current_org), db: Session = Depends(get_db)):
    ctx.require_org_admin()
    out = _tenant_dict(db, ctx)
    db.commit()
    return out


@admin_tenant_router.patch("")
def patch_tenant(body: TenantPatch, request: Request, ctx: OrgContext = Depends(current_org), db: Session = Depends(get_db)):
    ctx.require_org_admin()
    ch = body.model_dump(exclude_unset=True)
    if "contact_email" in ch and ch["contact_email"]:
        try:
            ch["contact_email"] = C.normalise_email(ch["contact_email"])
        except C.ContactError as e:
            raise C.http_422(e)
    T.ensure_profile(db, ctx.org, **ch)
    db.commit()
    audit.write("org.profile_updated", user_id=ctx.user_id, username=ctx.username, org_id=ctx.org.id, ip=client_ip(request), entity="organisation", entity_id=ctx.org.id, detail=ch)
    N.settings_changed(db, ctx.org, ctx.username, "organisation contact details / profile (" + ", ".join(sorted(ch)) + ")")
    return _tenant_dict(db, ctx)
