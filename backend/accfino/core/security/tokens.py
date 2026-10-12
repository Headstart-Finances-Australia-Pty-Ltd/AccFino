"""JWT access tokens. The signing secret comes from JWT_SECRET, or a random
secret generated once and stored in system_settings (shared by all workers)."""
import os
import time
import uuid
from datetime import datetime, timedelta, timezone

import jwt

from accfino.core import config

_secret_cache = {"value": None}
# token_version cache: user_id -> (version, fetched_at)
_tv_cache: dict = {}
_TV_TTL = 15


def _secret() -> str:
    if _secret_cache["value"]:
        return _secret_cache["value"]
    env = os.environ.get("JWT_SECRET", "").strip()
    if env:
        _secret_cache["value"] = env
        return env
    from accfino.shared.db.database import SessionLocal
    from accfino.core.migrate import get_or_create_setting
    import secrets
    db = SessionLocal()
    try:
        _secret_cache["value"] = get_or_create_setting(db, "jwt_secret", lambda: secrets.token_urlsafe(48))
    finally:
        db.close()
    return _secret_cache["value"]


def issue_access_token(user, token_version: int, is_admin: bool, org_id=None, mfa=False, sid=None, amr=None):
    now = datetime.now(timezone.utc)
    exp = now + timedelta(minutes=config.ACCESS_TOKEN_MINUTES)
    payload = {
        "sub": str(user.id), "usr": user.username, "eml": user.email,
        "adm": bool(is_admin), "tv": int(token_version), "org": org_id, "mfa": bool(mfa),
        "sid": sid, "amr": amr or ["pwd"],
        "typ": "access", "iat": int(now.timestamp()), "exp": int(exp.timestamp()),
        "jti": uuid.uuid4().hex,
    }
    return jwt.encode(payload, _secret(), algorithm=config.JWT_ALGORITHM), exp


def issue_mfa_token(user_id: int):
    now = datetime.now(timezone.utc)
    payload = {"sub": str(user_id), "typ": "mfa", "iat": int(now.timestamp()),
               "exp": int((now + timedelta(minutes=config.MFA_PENDING_MINUTES)).timestamp()),
               "jti": uuid.uuid4().hex}
    return jwt.encode(payload, _secret(), algorithm=config.JWT_ALGORITHM)


def decode(token: str, expected_type: str = "access") -> dict:
    """Raises jwt.PyJWTError on any problem."""
    data = jwt.decode(token, _secret(), algorithms=[config.JWT_ALGORITHM],
                      options={"require": ["exp", "sub", "typ"]})
    if data.get("typ") != expected_type:
        raise jwt.InvalidTokenError("wrong token type")
    return data


def current_token_version(user_id: int) -> int:
    """Token version from DB with a short cache; bumping it revokes all tokens."""
    hit = _tv_cache.get(user_id)
    if hit and time.time() - hit[1] < _TV_TTL:
        return hit[0]
    from accfino.shared.db.database import SessionLocal
    from accfino.core.models import UserSecurity
    db = SessionLocal()
    try:
        sec = db.get(UserSecurity, user_id)
        v = sec.token_version if sec else 1
    finally:
        db.close()
    _tv_cache[user_id] = (v, time.time())
    return v


def forget_token_version(user_id: int):
    _tv_cache.pop(user_id, None)
