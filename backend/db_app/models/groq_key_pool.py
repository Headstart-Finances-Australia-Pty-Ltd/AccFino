from sqlalchemy import Column, Integer, String, Text, Boolean, TIMESTAMP
from datetime import datetime
from .base import Base


class GroqKeyPool(Base):
    """A pool of Groq API keys, load-balanced automatically based on
    real-time health rather than a single fixed key.

    Why this exists: Groq's rate limits are per API key/account. With
    only one key, any heavy usage exhausts the rate limit for every
    classifier/agent in AccFino that depends on it. This spreads load
    across a POOL of keys and automatically routes around whichever ones
    are currently rate-limited or erroring, recovering them automatically
    once they cool down. Capacity grows by adding another key to the pool
    (one row, via the admin API/UI) - not a code change.

    Health tracking is DB-backed (not in-process memory) so it stays
    correct across multiple app instances/replicas - each one reads/writes
    the same cooldown state instead of independently re-discovering that
    a key is rate-limited.
    """
    __tablename__ = "groq_key_pool"

    id                 = Column(Integer, primary_key=True)
    key_value          = Column(Text, nullable=False, unique=True)
    model              = Column(String(200), nullable=True)  # per-key model override; falls back to GROQ_DEFAULT_MODEL if empty
    is_active          = Column(Boolean, default=True, nullable=False)  # admin can disable a key without deleting it
    consecutive_errors = Column(Integer, default=0, nullable=False)
    cooldown_until     = Column(TIMESTAMP, nullable=True)  # if set and in the future, this key is skipped until then
    last_used_at       = Column(TIMESTAMP, nullable=True)
    added_at           = Column(TIMESTAMP, default=datetime.utcnow)
