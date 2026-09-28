"""
main_app/backend/utils/groq_pool.py
-----------------------------------------------------------------------------
Shared Groq key pool with adaptive, self-healing routing.

Instead of a single hardcoded GROQ_API_KEY, this spreads load across a
POOL of keys (db_app.models.GroqKeyPool) and automatically routes around
whichever ones are currently rate-limited or erroring -- recovering them
automatically once they cool down. Adding capacity is a one-row insert
via the admin API/UI, not a code change.

Health tracking is DB-backed (not in-process memory) so it stays correct
across multiple app instances/replicas.

Usage from any classifier script:

    from main_app.backend.utils.groq_pool import resolve_groq_key, record_key_outcome

    db = SessionLocal()
    resolved = resolve_groq_key(db)
    if not resolved["groq_key"]:
        raise RuntimeError("No Groq key available in the pool.")
    try:
        ... call Groq using resolved["groq_key"] / resolved["model"] ...
        record_key_outcome(db, resolved["pool_id"], success=True)
    except Exception:
        record_key_outcome(db, resolved["pool_id"], success=False)
        raise
"""
from datetime import datetime, timedelta
from typing import Optional
from sqlalchemy import or_
from sqlalchemy.orm import Session

from db_app.models.groq_key_pool import GroqKeyPool

# Cooldown grows with consecutive failures (30s, 60s, 120s, 240s...
# capped at 10 minutes) -- a key that's genuinely being rate-limited gets
# a real break instead of being retried every request, but nothing is
# ever a PERMANENT ban; it's automatically retried once the cooldown
# lapses, and a single success immediately clears it back to full health.
BASE_COOLDOWN_SECONDS = 30
MAX_COOLDOWN_SECONDS = 600


def _mask(key_value: str) -> str:
    """Last 4 characters only -- safe to log or display, never the real key."""
    if not key_value:
        return ""
    tail = key_value[-4:] if len(key_value) >= 4 else key_value
    return f"...{tail}"


def resolve_groq_key(db: Session) -> dict:
    """Resolves which Groq key (and optional per-key model override) to
    use for the next request.

    Returns:
    {"groq_key": str | None, "model": str | None, "pool_id": int | None,
     "key_preview": str}

    Picks the least-recently-used currently-healthy key in the pool
    (is_active=True, and cooldown_until is null or already in the past).
    Returns groq_key=None if the pool is empty or every key is currently
    cooling down -- callers should treat that as "no Groq available right
    now" (e.g. fall back to a keyword-only classifier, or raise).
    """
    now = datetime.utcnow()
    entry = (
        db.query(GroqKeyPool)
        .filter(
            GroqKeyPool.is_active.is_(True),
            or_(GroqKeyPool.cooldown_until.is_(None), GroqKeyPool.cooldown_until < now),
        )
        .order_by(GroqKeyPool.last_used_at.asc().nullsfirst())
        .first()
    )
    if not entry:
        return {"groq_key": None, "model": None, "pool_id": None, "key_preview": ""}

    entry.last_used_at = now
    db.commit()
    return {
        "groq_key": entry.key_value,
        "model": entry.model or None,
        "pool_id": entry.id,
        "key_preview": _mask(entry.key_value),
    }


def record_key_outcome(db: Session, pool_id: Optional[int], success: bool) -> None:
    """Updates a pool key's health after an attempt that used it.

    On success: clears any cooldown and resets the error streak
    immediately -- a key that's working again is trusted again right
    away, no gradual "probation" period.

    On failure: applies an exponentially increasing cooldown so a key
    that's genuinely struggling gets skipped for a while rather than
    retried on every single request.
    """
    if pool_id is None:
        return
    entry = db.get(GroqKeyPool, pool_id)
    if not entry:
        return
    if success:
        entry.consecutive_errors = 0
        entry.cooldown_until = None
    else:
        entry.consecutive_errors += 1
        cooldown = min(BASE_COOLDOWN_SECONDS * (2 ** (entry.consecutive_errors - 1)), MAX_COOLDOWN_SECONDS)
        entry.cooldown_until = datetime.utcnow() + timedelta(seconds=cooldown)
    db.commit()


def count_available_keys(db: Session) -> int:
    """How many keys are currently active and not cooling down -- used to
    decide whether it's worth retrying with a different key at all."""
    now = datetime.utcnow()
    return (
        db.query(GroqKeyPool)
        .filter(
            GroqKeyPool.is_active.is_(True),
            or_(GroqKeyPool.cooldown_until.is_(None), GroqKeyPool.cooldown_until < now),
        )
        .count()
    )
