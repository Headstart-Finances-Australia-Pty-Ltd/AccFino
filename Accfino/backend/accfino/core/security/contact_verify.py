"""
accfino_core.security.contact_verify
------------------------------------
Proof that a person controls the email address and the phone number they give.

  1. send(channel, destination)   a 6-digit code goes to the address (email) or number (SMS)
  2. verify(channel, destination, code)  -> a signed PROOF TOKEN (30 minutes) bound to that exact destination
  3. the proof token is sent with the sign-up / join / profile request, and the server checks it again - so skipping the screen or
     replaying a token for a different address achieves nothing

Policy (CONTACT_VERIFICATION):  email (default) | both | off
  both   email must be verified; phone must be verified where a text message can reach it (SMS_ALLOWED_COUNTRY_CODES, default 61 and 64 = Australia / NZ).
         Numbers in other countries are format-validated and stored but can't be verified by SMS, so they are not blocked (they stay "unverified").
  email  only the email is verified.
  off    nothing is verified (format validation still applies).

Codes: 6 digits, HMAC-hashed at rest (bound to the destination), 5-minute expiry, 5 wrong attempts, 30-second resend cooldown,
6 sends per destination per hour and 20 per IP per hour. The same message is returned whether or not an address is already registered.
Delivery uses accfino_core.security.messaging (SMTP / SMS provider; the development outbox when none is configured).
"""
import os
import re
import secrets
from datetime import datetime, timedelta
from typing import Optional

import jwt
from fastapi import HTTPException

from accfino.core import models as m
from accfino.core.security import contact as C
from accfino.core.security import messaging, tokens

CODE_TTL = timedelta(minutes=5)
PROOF_MINUTES = 30
MAX_ATTEMPTS = 5
COOLDOWN = timedelta(seconds=30)
MAX_PER_DEST_HOUR = 6
MAX_PER_IP_HOUR = 20
KIND = {"email": "verify_email", "phone": "verify_phone"}
EMAIL_NEEDED = "Please verify your email address."
PHONE_NEEDED = "Please verify your phone number."


# ------------------------------------------------------------------------------------------------ policy --
def mode() -> str:
    # Default: only the EMAIL address is verified (organisation sign-up asks for email verification only).
    # Set CONTACT_VERIFICATION=both to verify the phone number by SMS as well.
    v = os.environ.get("CONTACT_VERIFICATION", "email").strip().lower()
    return v if v in ("both", "email", "off") else "email"


def sms_countries() -> list:
    return [c.strip() for c in os.environ.get("SMS_ALLOWED_COUNTRY_CODES", "61,64").split(",") if c.strip()]


def sms_deliverable(e164: str) -> bool:
    return any((e164 or "").startswith("+" + c) for c in sms_countries())


def required(channel: str, destination: Optional[str]) -> bool:
    """Must this email / (normalised) phone be verified before an account can use it?
    The platform administrator's own email (admin@accfino.com) is never verified."""
    if channel == "email" and C.is_platform_admin_email(destination):
        return False
    if channel == "email":
        return mode() in ("both", "email")
    return mode() == "both" and sms_deliverable(destination or "")


def config() -> dict:
    return {"mode": mode(), "email_required": mode() in ("both", "email"), "phone_required": mode() == "both", "sms_country_codes": sms_countries()}


# ------------------------------------------------------------------------------------------------ helpers --
def _norm(channel: str, raw: str) -> str:
    try:
        return C.normalise_email(raw) if channel == "email" else C.normalise_phone(raw)
    except C.ContactError as e:
        raise C.http_422(e)


def _hash(kind: str, destination: str, code: str) -> str:
    from accfino.core.security import mfa_service
    return mfa_service._hash(f"{kind}|{destination}|{code}")


def _check_channel(channel: str):
    if channel not in KIND:
        raise HTTPException(422, "channel must be 'email' or 'phone'")


def _throttle(db, ip: str, kind: str, destination: str):
    from accfino.core.tenancy.models import SignupAttempt
    now = datetime.utcnow()
    q = db.query(m.MfaChallenge).filter(m.MfaChallenge.kind == kind, m.MfaChallenge.destination == destination)
    last = q.order_by(m.MfaChallenge.created_at.desc()).first()
    if last and now - last.created_at < COOLDOWN:
        wait = int((COOLDOWN - (now - last.created_at)).total_seconds()) + 1
        raise HTTPException(429, f"Please wait {wait} seconds before requesting another code.")
    if q.filter(m.MfaChallenge.created_at > now - timedelta(hours=1)).count() >= MAX_PER_DEST_HOUR:
        raise HTTPException(429, "Too many codes requested for this address. Try again in an hour.")
    ip_count = db.query(SignupAttempt.id).filter(SignupAttempt.kind == "verify", SignupAttempt.ip == ip, SignupAttempt.created_at > now - timedelta(hours=1)).count()
    if ip_count >= MAX_PER_IP_HOUR:
        raise HTTPException(429, "Too many verification requests. Try again later.")


def mask(channel: str, destination: str) -> str:
    if channel == "email":
        name, dom = destination.split("@", 1)
        return f"{name[:2]}{'•' * max(1, len(name) - 2)}@{dom}"
    return f"•••• {destination[-3:]}"


# ------------------------------------------------------------------------------------------------ send / verify --
def send(db, channel: str, raw_destination: str, ip: str) -> dict:
    _check_channel(channel)
    dest = _norm(channel, raw_destination)
    if not required(channel, dest):
        return {"ok": True, "required": False, "reason": "not_required" if channel == "email" or mode() != "both" else "sms_unavailable", "destination": dest}
    kind = KIND[channel]
    _throttle(db, ip, kind, dest)
    from accfino.core.tenancy.models import SignupAttempt
    db.add(SignupAttempt(ip=(ip or "?")[:64], kind="verify", success=True))
    code = f"{secrets.randbelow(1_000_000):06d}"
    ch = m.MfaChallenge(id=secrets.token_urlsafe(24), user_id=None, kind=kind, code_hash=_hash(kind, dest, code), destination=dest, expires_at=datetime.utcnow() + CODE_TTL)
    db.add(ch)
    db.commit()
    text_ = f"Your AccFino verification code is {code}. It expires in 5 minutes. Never share this code."
    try:
        if channel == "phone":
            messaging.send_sms(dest, text_)
        else:
            messaging.send_email(dest, "Your AccFino verification code", text_)
    except messaging.DeliveryError:
        raise HTTPException(502, "We couldn't send the code just now. Please check the address and try again.")
    return {"ok": True, "required": True, "sent_to": mask(channel, dest), "expires_in_minutes": int(CODE_TTL.total_seconds() // 60)}


def verify(db, channel: str, raw_destination: str, code: str) -> dict:
    _check_channel(channel)
    dest = _norm(channel, raw_destination)
    kind = KIND[channel]
    ch = (db.query(m.MfaChallenge).filter(m.MfaChallenge.kind == kind, m.MfaChallenge.destination == dest, m.MfaChallenge.consumed_at.is_(None))
          .order_by(m.MfaChallenge.created_at.desc()).first())
    if ch is None or ch.expires_at < datetime.utcnow():
        raise HTTPException(400, "That code has expired. Request a new one.")
    if ch.attempts >= MAX_ATTEMPTS:
        raise HTTPException(429, "Too many incorrect attempts. Request a new code.")
    import hmac
    if not hmac.compare_digest(ch.code_hash or "", _hash(kind, dest, re.sub(r"\s", "", code or ""))):
        ch.attempts += 1
        db.commit()
        raise HTTPException(401, "That code is not correct.")
    ch.consumed_at = datetime.utcnow()
    db.commit()
    now = datetime.utcnow()
    token = jwt.encode({"typ": "contact", "ch": channel, "dst": dest, "iat": now, "exp": now + timedelta(minutes=PROOF_MINUTES)}, tokens._secret(), algorithm="HS256")
    return {"ok": True, "token": token, "verified": dest}


def token_ok(token: Optional[str], channel: str, destination: str) -> bool:
    """Is `token` a valid proof that THIS destination was verified?"""
    if not token:
        return False
    try:
        d = jwt.decode(token, tokens._secret(), algorithms=["HS256"])
    except jwt.PyJWTError:
        return False
    return d.get("typ") == "contact" and d.get("ch") == channel and d.get("dst") == destination


# ------------------------------------------------------------------------------------------------ at account creation --
def require_proofs(email: str, phone: str, email_token: Optional[str], phone_token: Optional[str]) -> dict:
    """Server-side gate for sign-up / join / profile changes. `email` / `phone` are the NORMALISED values. Raises 422 when a required proof is missing or
    belongs to a different address. -> {"email": bool, "phone": bool}: which of the two were verified (to be recorded)."""
    out = {"email": False, "phone": False}
    out["email"] = token_ok(email_token, "email", email)
    out["phone"] = token_ok(phone_token, "phone", phone)
    if required("email", email) and not out["email"]:
        raise HTTPException(422, EMAIL_NEEDED)
    if required("phone", phone) and not out["phone"]:
        raise HTTPException(422, PHONE_NEEDED)
    return out


def record(db, user_id: int, *, email: Optional[bool] = None, phone: Optional[bool] = None) -> None:
    """Set (True) or clear (False) the verified marks. None leaves it alone."""
    from accfino.core.migrate import ensure_user_security
    sec = ensure_user_security(db, user_id)
    now = datetime.utcnow()
    if email is not None:
        sec.email_verified_at = now if email else None
    if phone is not None:
        sec.phone_verified_at = now if phone else None
