"""/auth extensions: current user, logout, MFA enrolment and MFA login step."""
from datetime import datetime

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


@router.get("/me")
def me(request: Request, db: Session = Depends(get_db)):
    auth = current_auth(request)
    u = _user(db, auth["user_id"])
    sec = ensure_user_security(db, u.id)
    db.commit()
    return {"id": u.id, "username": u.username, "name": u.full_name or u.username, "email": u.email,
            "roles": [r.name for r in u.roles], "is_admin": auth["is_admin"],
            "mfa_enabled": S.has_mfa(db, sec), "mfa_methods": S.available_methods(db, sec),
            "last_login_at": sec.last_login_at,
            "organisations": org_summaries(db, u.id), "current_org_id": auth.get("org_id")}


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
