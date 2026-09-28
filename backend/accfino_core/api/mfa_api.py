"""/auth/mfa: authentication-method management and the sign-in verification steps.

Management (signed in):     GET  /methods
                            POST /sms/enrol {phone} -> code   POST /sms/confirm {code}   POST /sms/disable {password}
                            POST /email/enrol -> code         POST /email/confirm {code} POST /email/disable {password}
                            POST /passkeys/register/options   POST /passkeys/register/verify {challenge_id, credential, name}
                            POST /passkeys/{id}/remove {password}
                            POST /recovery-codes/regenerate {password}
Sign-in (public):           POST /challenge/send {mfa_token, channel}
                            POST /passkeys/auth/options {mfa_token?}   (no token = passwordless passkey sign-in)
                            POST /passkeys/auth/verify {challenge_id, credential, mfa_token?}
"""
import bcrypt
import jwt
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy.orm import Session

from accfino_core import models as m
from accfino_core.migrate import ensure_user_security
from accfino_core.security import audit, mfa, tokens
from accfino_core.security import mfa_service as S
from accfino_core.security.context import current_auth
from accfino_core.security.login import client_ip, record_success, throttle_ip, token_fields
from db_app.database import get_db
from db_app.models.user import User

router = APIRouter()


class PhoneIn(BaseModel):
    phone: str


class CodeIn(BaseModel):
    code: str


class PasswordIn(BaseModel):
    password: str


class RegisterIn(BaseModel):
    challenge_id: str
    credential: dict
    name: str | None = None


class SendIn(BaseModel):
    mfa_token: str
    channel: str


class AuthOptionsIn(BaseModel):
    mfa_token: str | None = None


class AuthVerifyIn(BaseModel):
    challenge_id: str
    credential: dict
    mfa_token: str | None = None


def _me(request, db):
    auth = current_auth(request)
    u = db.get(User, auth["user_id"])
    if u is None:
        raise HTTPException(404, "User not found")
    return u, ensure_user_security(db, u.id)


def _check_password(u, pw):
    if not bcrypt.checkpw((pw or "").encode(), u.password.encode()):
        raise HTTPException(401, "Password is incorrect")


def _enabled(db, request, u, sec, method):
    """Common tail after enabling a method: recovery codes on first method, audit, fresh token."""
    codes = S.ensure_recovery_codes(sec)
    db.commit()
    audit.write("auth.mfa_method_added", user_id=u.id, username=u.username, ip=client_ip(request),
                detail={"method": method})
    return {"ok": True, "recovery_codes": codes, **token_fields(db, u, mfa_verified=True, request=request)}


def _removed(db, request, u, sec, method):
    if not S.has_mfa(db, sec):
        sec.mfa_recovery_hashes = None
    db.commit()
    audit.write("auth.mfa_method_removed", user_id=u.id, username=u.username, ip=client_ip(request),
                detail={"method": method})
    return {"ok": True, **token_fields(db, u, mfa_verified=S.has_mfa(db, sec), request=request)}


# ----------------------------------------------------------------- overview --
@router.get("/methods")
def methods(request: Request, db: Session = Depends(get_db)):
    u, sec = _me(request, db)
    db.commit()
    return {
        "enabled_methods": S.available_methods(db, sec),
        "totp": bool(sec.mfa_enabled),
        "sms": {"enabled": bool(sec.sms_mfa_enabled), "phone": S.mask_phone(sec.phone_e164)},
        "email": {"enabled": bool(sec.email_mfa_enabled), "address": S.mask_email(u.email)},
        "passkeys": [{"id": c.id, "name": c.name, "synced": c.backed_up,
                      "created_at": c.created_at.isoformat() + "Z",
                      "last_used_at": c.last_used_at.isoformat() + "Z" if c.last_used_at else None}
                     for c in S.passkeys(db, u.id)],
        "recovery_codes_remaining": len(sec.mfa_recovery_hashes or []),
    }


# ---------------------------------------------------------------------- SMS --
@router.post("/sms/enrol")
def sms_enrol(body: PhoneIn, request: Request, db: Session = Depends(get_db)):
    u, sec = _me(request, db)
    phone = S.normalise_phone(body.phone)
    sec.phone_e164 = phone if not sec.sms_mfa_enabled else sec.phone_e164
    db.commit()
    S.send_code(db, u.id, "enrol_sms", "sms", phone)
    return {"ok": True, "sent_to": S.mask_phone(phone)}


@router.post("/sms/confirm")
def sms_confirm(body: CodeIn, request: Request, db: Session = Depends(get_db)):
    u, sec = _me(request, db)
    ch = S.check_code(db, u.id, ["enrol_sms"], body.code)
    sec.phone_e164, sec.sms_mfa_enabled = ch.destination, True
    return _enabled(db, request, u, sec, "sms")


@router.post("/sms/disable")
def sms_disable(body: PasswordIn, request: Request, db: Session = Depends(get_db)):
    u, sec = _me(request, db)
    _check_password(u, body.password)
    sec.sms_mfa_enabled, sec.phone_e164 = False, None
    return _removed(db, request, u, sec, "sms")


# -------------------------------------------------------------------- email --
@router.post("/email/enrol")
def email_enrol(request: Request, db: Session = Depends(get_db)):
    u, sec = _me(request, db)
    if not u.email:
        raise HTTPException(400, "Your account has no email address")
    S.send_code(db, u.id, "enrol_email", "email", u.email)
    return {"ok": True, "sent_to": S.mask_email(u.email)}


@router.post("/email/confirm")
def email_confirm(body: CodeIn, request: Request, db: Session = Depends(get_db)):
    u, sec = _me(request, db)
    S.check_code(db, u.id, ["enrol_email"], body.code)
    sec.email_mfa_enabled = True
    return _enabled(db, request, u, sec, "email")


@router.post("/email/disable")
def email_disable(body: PasswordIn, request: Request, db: Session = Depends(get_db)):
    u, sec = _me(request, db)
    _check_password(u, body.password)
    sec.email_mfa_enabled = False
    return _removed(db, request, u, sec, "email")


# ----------------------------------------------------------------- passkeys --
@router.post("/passkeys/register/options")
def passkey_register_options(request: Request, db: Session = Depends(get_db)):
    u, _ = _me(request, db)
    return S.registration_options(db, request, u)


@router.post("/passkeys/register/verify")
def passkey_register_verify(body: RegisterIn, request: Request, db: Session = Depends(get_db)):
    u, sec = _me(request, db)
    cred = S.finish_registration(db, request, u, body.challenge_id, body.credential, body.name)
    out = _enabled(db, request, u, sec, "passkey")
    out["passkey"] = {"id": cred.id, "name": cred.name}
    return out


@router.post("/passkeys/{passkey_id}/remove")
def passkey_remove(passkey_id: int, body: PasswordIn, request: Request, db: Session = Depends(get_db)):
    u, sec = _me(request, db)
    _check_password(u, body.password)
    cred = db.query(m.WebAuthnCredential).filter_by(id=passkey_id, user_id=u.id).first()
    if cred is None:
        raise HTTPException(404, "Passkey not found")
    db.delete(cred)
    db.flush()
    return _removed(db, request, u, sec, "passkey")


@router.post("/recovery-codes/regenerate")
def regenerate_codes(body: PasswordIn, request: Request, db: Session = Depends(get_db)):
    u, sec = _me(request, db)
    _check_password(u, body.password)
    if not S.has_mfa(db, sec):
        raise HTTPException(400, "Turn on a verification method first")
    codes, hashes = mfa.new_recovery_codes()
    sec.mfa_recovery_hashes = hashes
    db.commit()
    audit.write("auth.recovery_codes_regenerated", user_id=u.id, username=u.username, ip=client_ip(request))
    return {"ok": True, "recovery_codes": codes}


# ------------------------------------------------------------ sign-in steps --
def _pending_user(db, mfa_token):
    try:
        data = tokens.decode(mfa_token, "mfa")
    except jwt.PyJWTError:
        raise HTTPException(401, "Your sign-in step expired. Please enter your password again.")
    u = db.get(User, int(data["sub"]))
    if u is None:
        raise HTTPException(401, "Account not found")
    return u, ensure_user_security(db, u.id)


def _full_login(db, request, u, method):
    from accfino_core.security.login import check_disabled
    check_disabled(db, u)
    record_success(db, u, client_ip(request), method=method)
    from db_app.api.auth import build_user_response
    resp = build_user_response(u).model_dump()
    resp.update(token_fields(db, u, mfa_verified=True, request=request,
                             amr=["passkey"] if method == "passkey" else ["pwd", "passkey"]))
    db.commit()
    return resp


@router.post("/challenge/send")
def challenge_send(body: SendIn, request: Request, db: Session = Depends(get_db)):
    throttle_ip(client_ip(request))
    u, sec = _pending_user(db, body.mfa_token)
    if body.channel == "sms" and sec.sms_mfa_enabled and sec.phone_e164:
        S.send_code(db, u.id, "login_sms", "sms", sec.phone_e164)
        return {"ok": True, "sent_to": S.mask_phone(sec.phone_e164)}
    if body.channel == "email" and sec.email_mfa_enabled and u.email:
        S.send_code(db, u.id, "login_email", "email", u.email)
        return {"ok": True, "sent_to": S.mask_email(u.email)}
    raise HTTPException(400, "That verification method isn't set up for this account")


@router.post("/passkeys/auth/options")
def passkey_auth_options(body: AuthOptionsIn, request: Request, db: Session = Depends(get_db)):
    throttle_ip(client_ip(request))
    uid = _pending_user(db, body.mfa_token)[0].id if body.mfa_token else None
    return S.authentication_options(db, request, uid)


@router.post("/passkeys/auth/verify")
def passkey_auth_verify(body: AuthVerifyIn, request: Request, db: Session = Depends(get_db)):
    ip = client_ip(request)
    throttle_ip(ip)
    expected = _pending_user(db, body.mfa_token)[0].id if body.mfa_token else None
    try:
        cred = S.finish_authentication(db, request, body.challenge_id, body.credential, expected)
    except HTTPException:
        audit.write("auth.passkey_failed", user_id=expected, ip=ip)
        raise
    u = db.get(User, cred.user_id)
    from accfino_core.security.login import check_locked
    check_locked(db, u)
    return _full_login(db, request, u, "passkey" if body.mfa_token is None else "password+passkey")
