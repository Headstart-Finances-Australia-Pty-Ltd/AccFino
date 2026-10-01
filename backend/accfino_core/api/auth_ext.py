"""/auth extensions: current user, logout, MFA enrolment and MFA login step."""
from datetime import datetime

import bcrypt
import jwt
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy import func
from sqlalchemy.orm import Session

from accfino_core import models as m
from accfino_core.migrate import ensure_user_security
from accfino_core import notifications as N
from accfino_core.security import audit, mfa, tokens
from accfino_core.security import contact as C
from accfino_core.security import contact_verify as V
from accfino_core.security import mfa_service as S
from accfino_core.security.context import current_auth
from accfino_core.security.login import (client_ip, org_summaries, record_success, throttle_ip,
                                         token_fields)
from db_app.database import get_db
from db_app.models.user import User

router = APIRouter()


class CodeIn(BaseModel):
    code: str


class DisableIn(BaseModel):
    password: str
    code: str | None = None
    recovery_code: str | None = None


class MfaLoginIn(BaseModel):
    mfa_token: str
    code: str | None = None
    method: str | None = None          # totp (default) | sms | email
    recovery_code: str | None = None


def _user(db, uid):
    u = db.get(User, uid)
    if u is None:
        raise HTTPException(404, "User not found")
    return u


def _me_dict(db, u, auth, sec):
    orgs = org_summaries(db, u.id)
    cur = next((o for o in orgs if o["id"] == auth.get("org_id")), None)
    missing = C.missing_contact(u.email, u.phone)
    return {"id": u.id, "username": u.username, "name": u.full_name or u.username, "email": u.email,
            "phone": u.phone, "phone_display": C.format_phone(u.phone),
            "email_verified": bool(sec.email_verified_at), "phone_verified": bool(sec.phone_verified_at),
            "verification": {**V.config(), "email_needed": V.required("email", u.email) and not sec.email_verified_at,
                             "phone_needed": V.required("phone", u.phone) and not sec.phone_verified_at and not C.is_platform_admin_email(u.email)},
            "profile_complete": not missing, "missing_contact": missing,      # an account without a valid email AND phone is asked to complete its profile
            "roles": [r.name for r in u.roles], "is_admin": auth["is_admin"],
            "is_org_admin": bool(auth["is_admin"] or (cur and cur["role"] == "owner")),
            "mfa_enabled": S.has_mfa(db, sec), "mfa_methods": S.available_methods(db, sec),
            "last_login_at": sec.last_login_at,
            "organisations": orgs, "current_org_id": auth.get("org_id")}


@router.get("/me")
def me(request: Request, db: Session = Depends(get_db)):
    auth = current_auth(request)
    u = _user(db, auth["user_id"])
    sec = ensure_user_security(db, u.id)
    db.commit()
    return _me_dict(db, u, auth, sec)


class ProfileIn(BaseModel):
    full_name: str | None = None
    email: str | None = None
    phone: str | None = None
    email_token: str | None = None           # proof from /auth/me/contact/verify for the NEW (or current) email
    phone_token: str | None = None
    current_password: str | None = None      # needed to CHANGE an email / phone that is already set (a stolen session must not be able to take over the account)


class ContactSendIn(BaseModel):
    channel: str
    destination: str


class ContactVerifyIn(BaseModel):
    channel: str
    destination: str
    code: str


@router.post("/me/contact/send")
def my_contact_send(body: ContactSendIn, request: Request, db: Session = Depends(get_db)):
    """Signed-in: send a code to a new (or the current) email / phone. Same rules and limits as at sign-up."""
    current_auth(request)
    return V.send(db, body.channel, body.destination, client_ip(request))


@router.post("/me/contact/verify")
def my_contact_verify(body: ContactVerifyIn, request: Request, db: Session = Depends(get_db)):
    current_auth(request)
    return V.verify(db, body.channel, body.destination, body.code)


@router.patch("/me/profile")
def update_profile(body: ProfileIn, request: Request, db: Session = Depends(get_db)):
    """My Account: the signed-in user edits THEIR OWN name, email and phone. Email and phone can never be blanked or set to something invalid."""
    auth = current_auth(request)
    u = _user(db, auth["user_id"])
    changes = body.model_dump(exclude_unset=True)
    changes.pop("current_password", None)
    changes.pop("email_token", None); changes.pop("phone_token", None)
    if not changes and not (body.email_token or body.phone_token):
        raise HTTPException(422, "Nothing to change")
    old_email, old_phone = u.email, u.phone
    errors, new_email, new_phone = {}, None, None
    if "email" in changes:
        try:
            new_email = C.normalise_email(changes["email"])
        except C.ContactError as e:
            errors.update(e.errors)
    if "phone" in changes:
        try:
            new_phone = C.normalise_phone(changes["phone"])
        except C.ContactError as e:
            errors.update(e.errors)
    if errors:
        raise C.http_422(C.ContactError(errors))
    name = None
    if "full_name" in changes:
        name = (changes["full_name"] or "").strip()
        if not name:
            raise HTTPException(422, "Name cannot be empty")
    email_changing = new_email is not None and new_email != (old_email or "").lower()
    old_phone_norm = C.normalise_phone(old_phone) if C.is_valid_phone(old_phone) else None
    phone_changing = new_phone is not None and new_phone != old_phone_norm
    # Replacing a contact detail that is already valid needs the current password; filling in a MISSING one (profile completion) does not.
    if (email_changing and C.is_valid_email(old_email)) or (phone_changing and C.is_valid_phone(old_phone)):
        if not body.current_password or not bcrypt.checkpw(body.current_password.encode(), u.password.encode()):
            raise HTTPException(401, "Enter your current password to change your email address or phone number")
    sec0 = ensure_user_security(db, u.id)
    eff_email = new_email if email_changing else (u.email or "")
    eff_phone = new_phone if phone_changing else (C.normalise_phone(u.phone) if C.is_valid_phone(u.phone) else (u.phone or ""))
    email_proof = V.token_ok(body.email_token, "email", eff_email)
    phone_proof = V.token_ok(body.phone_token, "phone", eff_phone)
    # A NEW or CHANGED address / number must be verified (when verification applies); an unchanged one only needs verifying if the person chooses to.
    if email_changing and V.required("email", eff_email) and not email_proof:
        raise HTTPException(422, V.EMAIL_NEEDED)
    if phone_changing and V.required("phone", eff_phone) and not phone_proof:
        raise HTTPException(422, V.PHONE_NEEDED)
    if email_changing and db.query(User.id).filter(func.lower(User.email) == new_email, User.id != u.id).first():
        raise HTTPException(409, "That email address is already used by another account")
    if name is not None:
        u.full_name = name[:200]
    if email_changing:
        u.email = new_email
    if phone_changing:
        u.phone = new_phone
    db.flush()
    changed = [k for k, flag in (("full_name", name is not None), ("email", email_changing), ("phone", phone_changing)) if flag]
    if not changed and (email_proof or phone_proof):
        changed = [k for k, flag in (("email_verified", email_proof), ("phone_verified", phone_proof)) if flag]
    if email_changing:                                 # keep an organisation's contact email in step when it was this admin's own address
        from accfino_core.tenancy.models import OrgProfile
        for org in db.query(m.Organisation).filter(m.Organisation.admin_user_id == u.id):
            prof = db.get(OrgProfile, org.id)
            if prof is not None and (prof.contact_email or "").lower() == (old_email or "").lower():
                prof.contact_email = new_email
    sec = ensure_user_security(db, u.id)
    if email_changing:
        V.record(db, u.id, email=email_proof)                    # a changed address starts unverified unless it was just proven
    elif email_proof:
        V.record(db, u.id, email=True)                           # verifying the current address
    if phone_changing:
        V.record(db, u.id, phone=phone_proof)
    elif phone_proof:
        V.record(db, u.id, phone=True)
    db.commit()
    from accfino_core.security import iam
    iam.forget(("contact", u.id))
    audit.write("auth.profile_updated", user_id=u.id, username=u.username, ip=client_ip(request), detail={"fields": changed})
    if email_changing and C.is_valid_email(old_email):          # individual security notice, to the OLD address as well as the new one
        N.notify_user(db, u, "Your AccFino email address was changed", f"The email address on your account was changed to {new_email}. If this was not you, contact your Organisation Admin straight away.",
                      kind="email_changed", to=old_email)
    if email_changing or phone_changing:
        for org in db.query(m.Organisation).filter(m.Organisation.admin_user_id == u.id):        # the Organisation Admin's contact details ARE the organisation's
            N.notify_org_admin(db, org.id, "admin_contact_changed", "Organisation primary contact details changed",
                               "The Organisation Admin's email address or phone number - the organisation's primary contact details - was changed.")
    return _me_dict(db, u, auth, sec)


@router.post("/logout")
def logout(request: Request):
    auth = current_auth(request)
    if auth.get("sid"):                      # end THIS device's session only
        from accfino_core.security import iam
        from db_app.database import SessionLocal
        db = SessionLocal()
        try:
            iam.revoke_sessions(db, auth["user_id"], sid=auth["sid"], reason="signed_out")
            db.commit()
        finally:
            db.close()
    audit.write("auth.logout", user_id=auth["user_id"], username=auth["username"], ip=client_ip(request))
    return {"ok": True}


@router.post("/logout-all")
def logout_all(request: Request, db: Session = Depends(get_db)):
    """Revoke every token for this user (all devices)."""
    auth = current_auth(request)
    sec = ensure_user_security(db, auth["user_id"])
    sec.token_version += 1
    from accfino_core.security import iam
    iam.revoke_sessions(db, auth["user_id"], reason="signed_out_everywhere")
    db.commit()
    tokens.forget_token_version(auth["user_id"])
    audit.write("auth.logout_all", user_id=auth["user_id"], username=auth["username"], ip=client_ip(request))
    return {"ok": True}


@router.post("/mfa/setup")
def mfa_setup(request: Request, db: Session = Depends(get_db)):
    auth = current_auth(request)
    u = _user(db, auth["user_id"])
    sec = ensure_user_security(db, u.id)
    if sec.mfa_enabled:
        raise HTTPException(400, "MFA is already enabled")
    sec.mfa_secret = mfa.new_secret()
    db.commit()
    uri = mfa.provisioning_uri(sec.mfa_secret, u.email or u.username)
    return {"secret": sec.mfa_secret, "otpauth_uri": uri, "qr_png": mfa.qr_data_uri(uri)}


@router.post("/mfa/enable")
def mfa_enable(body: CodeIn, request: Request, db: Session = Depends(get_db)):
    auth = current_auth(request)
    u = _user(db, auth["user_id"])
    sec = ensure_user_security(db, u.id)
    if sec.mfa_enabled:
        raise HTTPException(400, "MFA is already enabled")
    if not sec.mfa_secret or not mfa.verify_code(sec.mfa_secret, body.code):
        raise HTTPException(400, "That code is not valid. Check the time on your phone and try again.")
    sec.mfa_enabled = True
    codes = S.ensure_recovery_codes(sec)       # only on the first verification method
    db.commit()
    audit.write("auth.mfa_enabled", user_id=u.id, username=u.username, ip=client_ip(request))
    return {"ok": True, "recovery_codes": codes, **token_fields(db, u, mfa_verified=True, request=request)}


@router.post("/mfa/disable")
def mfa_disable(body: DisableIn, request: Request, db: Session = Depends(get_db)):
    auth = current_auth(request)
    u = _user(db, auth["user_id"])
    sec = ensure_user_security(db, u.id)
    if not sec.mfa_enabled:
        raise HTTPException(400, "MFA is not enabled")
    if not bcrypt.checkpw(body.password.encode(), u.password.encode()):
        raise HTTPException(401, "Password is incorrect")
    ok = (body.code and mfa.verify_code(sec.mfa_secret, body.code)) or \
         (body.recovery_code and mfa.use_recovery_code(sec.mfa_recovery_hashes, body.recovery_code) is not None)
    if not ok:
        raise HTTPException(400, "A valid authenticator or recovery code is required")
    sec.mfa_enabled, sec.mfa_secret = False, None
    if not S.has_mfa(db, sec):                  # keep recovery codes while other methods remain
        sec.mfa_recovery_hashes = None
    sec.token_version += 1
    db.commit()
    tokens.forget_token_version(u.id)
    audit.write("auth.mfa_disabled", user_id=u.id, username=u.username, ip=client_ip(request))
    return {"ok": True, **token_fields(db, u, mfa_verified=S.has_mfa(db, sec), request=request)}


@router.post("/mfa/login")
def mfa_login(body: MfaLoginIn, request: Request, db: Session = Depends(get_db)):
    ip = client_ip(request)
    throttle_ip(ip)
    try:
        data = tokens.decode(body.mfa_token, "mfa")
    except jwt.PyJWTError:
        raise HTTPException(401, "Your sign-in step expired. Please enter your password again.")
    u = _user(db, int(data["sub"]))
    sec = ensure_user_security(db, u.id)
    method = body.method or "totp"
    if body.code and method in ("sms", "email"):
        enabled = sec.sms_mfa_enabled if method == "sms" else sec.email_mfa_enabled
        if not enabled:
            raise HTTPException(400, "That verification method isn't set up for this account")
        try:
            S.check_code(db, u.id, [f"login_{method}"], body.code)
        except HTTPException:
            audit.write("auth.mfa_failed", user_id=u.id, username=u.username, ip=ip, detail={"method": method})
            raise
    elif body.code and method == "totp" and sec.mfa_enabled and mfa.verify_code(sec.mfa_secret, body.code):
        pass
    elif body.recovery_code:
        remaining = mfa.use_recovery_code(sec.mfa_recovery_hashes, body.recovery_code)
        if remaining is None:
            audit.write("auth.mfa_failed", user_id=u.id, username=u.username, ip=ip)
            raise HTTPException(401, "Invalid recovery code")
        sec.mfa_recovery_hashes = remaining
        method = "recovery_code"
        db.commit()
    else:
        audit.write("auth.mfa_failed", user_id=u.id, username=u.username, ip=ip)
        raise HTTPException(401, "Invalid authentication code")
    from accfino_core.security.login import check_disabled
    check_disabled(db, u)
    record_success(db, u, ip, method=f"password+{method}")
    from db_app.api.auth import build_user_response
    resp = build_user_response(u).model_dump()
    resp.update(token_fields(db, u, mfa_verified=True, request=request,
                             amr=["pwd", "recovery" if method == "recovery_code" else method]))
    db.commit()
    return resp
