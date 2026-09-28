"""
accfino_core.security.mfa_service
---------------------------------
Multi-factor authentication methods (Microsoft Entra-style "authentication methods"):

  passkey  - WebAuthn / FIDO2: Face ID, Touch ID, Windows Hello (face, fingerprint, PIN),
             Android biometrics, or a hardware security key. Phishing-resistant. User
             verification is REQUIRED, so the device checks the face/fingerprint/PIN locally;
             AccFino only ever stores the public key (no biometric data - Privacy Act friendly).
  totp     - authenticator-app passcode (Microsoft/Google Authenticator, 1Password, Authy)
  sms      - 6-digit code texted to a verified mobile number
  email    - 6-digit code emailed to the account address
  recovery - single-use backup codes

Codes: 6 digits, HMAC-hashed at rest, 5-minute expiry, 5 attempts, 30s resend cooldown,
6 sends per user per hour.
"""
import hashlib
import hmac
import json
import os
import re
import secrets
from datetime import datetime, timedelta
from urllib.parse import urlparse

from fastapi import HTTPException
from webauthn import (generate_authentication_options, generate_registration_options, options_to_json,
                      verify_authentication_response, verify_registration_response)
from webauthn.helpers import base64url_to_bytes, bytes_to_base64url
from webauthn.helpers.structs import (AuthenticatorSelectionCriteria, PublicKeyCredentialDescriptor,
                                      ResidentKeyRequirement, UserVerificationRequirement)

from accfino_core import models as m
from accfino_core.security import mfa, tokens
from accfino_core.security.messaging import DeliveryError, send_email, send_sms

CODE_TTL = timedelta(minutes=5)
CEREMONY_TTL = timedelta(minutes=5)
MAX_ATTEMPTS = 5
RESEND_COOLDOWN = timedelta(seconds=30)
MAX_SENDS_PER_HOUR = 6
RP_NAME = "AccFino"


# ---------------------------------------------------------------- helpers --
def _hash(code: str) -> str:
    return hmac.new(tokens._secret().encode(), code.encode(), hashlib.sha256).hexdigest()


def mask_phone(p):
    return f"•••• {p[-3:]}" if p else None


def mask_email(e):
    if not e or "@" not in e:
        return None
    name, dom = e.split("@", 1)
    return f"{name[:2]}{'•' * max(1, len(name) - 2)}@{dom}"


def normalise_phone(raw: str) -> str:
    """Australian-first E.164 normalisation. 0412 345 678 -> +61412345678."""
    p = re.sub(r"[\s\-()]", "", raw or "")
    if p.startswith("00"):
        p = "+" + p[2:]
    if re.fullmatch(r"04\d{8}", p):
        p = "+61" + p[1:]
    if not re.fullmatch(r"\+[1-9]\d{7,14}", p):
        raise HTTPException(422, "Enter a mobile number like 0412 345 678 or +61412345678")
    allowed = [c.strip() for c in os.environ.get("SMS_ALLOWED_COUNTRY_CODES", "61,64").split(",") if c.strip()]
    if not any(p.startswith("+" + c) for c in allowed):
        raise HTTPException(422, "SMS codes are only available for Australian and New Zealand mobile numbers")
    return p


def passkeys(db, user_id):
    return db.query(m.WebAuthnCredential).filter_by(user_id=user_id).order_by(m.WebAuthnCredential.id).all()


def available_methods(db, sec) -> list:
    out = []
    if db.query(m.WebAuthnCredential).filter_by(user_id=sec.user_id).first():
        out.append("passkey")
    if sec.mfa_enabled and sec.mfa_secret:
        out.append("totp")
    if sec.sms_mfa_enabled and sec.phone_e164:
        out.append("sms")
    if sec.email_mfa_enabled:
        out.append("email")
    return out


def has_mfa(db, sec) -> bool:
    return bool(available_methods(db, sec))


def ensure_recovery_codes(sec):
    """Issue recovery codes the first time any method is enabled. Returns new codes or None."""
    if sec.mfa_recovery_hashes:
        return None
    codes, hashes = mfa.new_recovery_codes()
    sec.mfa_recovery_hashes = hashes
    return codes


# ------------------------------------------------------------- one-time codes --
def _rate_limit(db, user_id, kinds):
    now = datetime.utcnow()
    q = db.query(m.MfaChallenge).filter(m.MfaChallenge.user_id == user_id, m.MfaChallenge.kind.in_(kinds))
    last = q.order_by(m.MfaChallenge.created_at.desc()).first()
    if last and now - last.created_at < RESEND_COOLDOWN:
        wait = int((RESEND_COOLDOWN - (now - last.created_at)).total_seconds()) + 1
        raise HTTPException(429, f"Please wait {wait} seconds before requesting another code")
    if q.filter(m.MfaChallenge.created_at > now - timedelta(hours=1)).count() >= MAX_SENDS_PER_HOUR:
        raise HTTPException(429, "Too many codes requested. Try again in an hour or use another method.")


def send_code(db, user_id, kind, channel, destination) -> str:
    """Create a challenge and deliver a 6-digit code. Returns the challenge id."""
    _rate_limit(db, user_id, [kind])
    code = f"{secrets.randbelow(1_000_000):06d}"
    ch = m.MfaChallenge(id=secrets.token_urlsafe(24), user_id=user_id, kind=kind, code_hash=_hash(code),
                        destination=destination, expires_at=datetime.utcnow() + CODE_TTL)
    db.add(ch)
    db.commit()
    text_ = f"Your AccFino verification code is {code}. It expires in 5 minutes. Never share this code."
    try:
        if channel == "sms":
            send_sms(destination, text_)
        else:
            send_email(destination, "Your AccFino verification code", text_)
    except DeliveryError as e:
        raise HTTPException(502, f"Couldn't send the code: {e}")
    return ch.id


def check_code(db, user_id, kinds, code) -> "m.MfaChallenge":
    """Verify the most recent unconsumed code of the given kinds. Raises 400/401 on failure."""
    ch = (db.query(m.MfaChallenge)
          .filter(m.MfaChallenge.user_id == user_id, m.MfaChallenge.kind.in_(kinds),
                  m.MfaChallenge.consumed_at.is_(None))
          .order_by(m.MfaChallenge.created_at.desc()).first())
    if ch is None or ch.expires_at < datetime.utcnow():
        raise HTTPException(400, "The code has expired. Request a new one.")
    if ch.attempts >= MAX_ATTEMPTS:
        raise HTTPException(429, "Too many incorrect attempts. Request a new code.")
    code = re.sub(r"\s", "", code or "")
    if not hmac.compare_digest(ch.code_hash or "", _hash(code)):
        ch.attempts += 1
        db.commit()
        raise HTTPException(401, "Incorrect code")
    ch.consumed_at = datetime.utcnow()
    db.commit()
    return ch


# ------------------------------------------------------------------ passkeys --
def rp_and_origins(request):
    """RP ID and allowed origins. Defaults follow the browser's Origin header so the same
    build works on localhost, staging and production; pin them with WEBAUTHN_RP_ID /
    WEBAUTHN_ORIGINS in production."""
    origin = request.headers.get("origin") or ""
    env_rp = os.environ.get("WEBAUTHN_RP_ID", "").strip()
    rp_id = env_rp or urlparse(origin).hostname or request.url.hostname
    env_origins = [o.strip() for o in os.environ.get("WEBAUTHN_ORIGINS", "").split(",") if o.strip()]
    if env_origins:
        origins = env_origins
    else:
        host = urlparse(origin).hostname or ""
        origins = [origin] if origin and (host == rp_id or host.endswith("." + rp_id)) else []
    if not origins:
        raise HTTPException(400, "Passkeys need to be used from the AccFino web app (missing browser origin)")
    return rp_id, origins


def _save_ceremony(db, user_id, kind, challenge: bytes) -> str:
    ch = m.MfaChallenge(id=secrets.token_urlsafe(24), user_id=user_id, kind=kind,
                        challenge=bytes_to_base64url(challenge), expires_at=datetime.utcnow() + CEREMONY_TTL)
    db.add(ch)
    db.commit()
    return ch.id


def _take_ceremony(db, challenge_id, kind) -> "m.MfaChallenge":
    ch = db.get(m.MfaChallenge, challenge_id or "")
    if ch is None or ch.kind != kind or ch.consumed_at or ch.expires_at < datetime.utcnow():
        raise HTTPException(400, "This passkey request expired. Please try again.")
    ch.consumed_at = datetime.utcnow()
    db.commit()
    return ch


def registration_options(db, request, user):
    rp_id, _ = rp_and_origins(request)
    existing = [PublicKeyCredentialDescriptor(id=base64url_to_bytes(c.credential_id)) for c in passkeys(db, user.id)]
    opts = generate_registration_options(
        rp_id=rp_id, rp_name=RP_NAME, user_id=str(user.id).encode(), user_name=user.email or user.username,
        user_display_name=user.full_name or user.username, exclude_credentials=existing,
        authenticator_selection=AuthenticatorSelectionCriteria(
            resident_key=ResidentKeyRequirement.PREFERRED, user_verification=UserVerificationRequirement.REQUIRED),
        timeout=120000)
    cid = _save_ceremony(db, user.id, "passkey_register", opts.challenge)
    return {"challenge_id": cid, "options": json.loads(options_to_json(opts))}


def finish_registration(db, request, user, challenge_id, credential: dict, name: str):
    ch = _take_ceremony(db, challenge_id, "passkey_register")
    if ch.user_id != user.id:
        raise HTTPException(403, "Passkey request belongs to another user")
    rp_id, origins = rp_and_origins(request)
    try:
        v = verify_registration_response(credential=credential, expected_challenge=base64url_to_bytes(ch.challenge),
                                         expected_rp_id=rp_id, expected_origin=origins,
                                         require_user_verification=True)
    except Exception as e:
        raise HTTPException(400, f"Passkey could not be verified: {e}")
    cred = m.WebAuthnCredential(
        user_id=user.id, credential_id=bytes_to_base64url(v.credential_id),
        public_key=bytes_to_base64url(v.credential_public_key), sign_count=v.sign_count,
        transports=(credential.get("response") or {}).get("transports"),
        name=(name or "Passkey").strip()[:100] or "Passkey", aaguid=str(v.aaguid),
        backed_up=bool(getattr(v, "credential_backed_up", False)))
    db.add(cred)
    db.commit()
    return cred


def authentication_options(db, request, user_id=None):
    """user_id given -> second factor after password; None -> passwordless (discoverable passkey)."""
    rp_id, _ = rp_and_origins(request)
    allow = []
    if user_id is not None:
        allow = [PublicKeyCredentialDescriptor(id=base64url_to_bytes(c.credential_id)) for c in passkeys(db, user_id)]
        if not allow:
            raise HTTPException(400, "No passkey is registered for this account")
    opts = generate_authentication_options(rp_id=rp_id, allow_credentials=allow,
                                           user_verification=UserVerificationRequirement.REQUIRED, timeout=120000)
    cid = _save_ceremony(db, user_id, "passkey_auth", opts.challenge)
    return {"challenge_id": cid, "options": json.loads(options_to_json(opts))}


def finish_authentication(db, request, challenge_id, credential: dict, expected_user_id=None):
    ch = _take_ceremony(db, challenge_id, "passkey_auth")
    if ch.user_id is not None and expected_user_id is not None and ch.user_id != expected_user_id:
        raise HTTPException(403, "Passkey request belongs to another user")
    cred = db.query(m.WebAuthnCredential).filter_by(credential_id=credential.get("id") or credential.get("rawId")).first()
    if cred is None:
        raise HTTPException(401, "This passkey isn't registered with AccFino")
    if (ch.user_id is not None and cred.user_id != ch.user_id) or \
            (expected_user_id is not None and cred.user_id != expected_user_id):
        raise HTTPException(401, "This passkey belongs to a different account")
    rp_id, origins = rp_and_origins(request)
    try:
        v = verify_authentication_response(
            credential=credential, expected_challenge=base64url_to_bytes(ch.challenge), expected_rp_id=rp_id,
            expected_origin=origins, credential_public_key=base64url_to_bytes(cred.public_key),
            credential_current_sign_count=cred.sign_count, require_user_verification=True)
    except Exception as e:
        raise HTTPException(401, f"Passkey sign-in failed: {e}")
    cred.sign_count = v.new_sign_count
    cred.last_used_at = datetime.utcnow()
    db.commit()
    return cred
