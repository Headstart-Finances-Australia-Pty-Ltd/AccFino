"""
accfino_core.config
-------------------
Central settings for the platform foundation. Everything is read from
environment variables so production (Northflank) and local dev behave the same.
"""
import os


def _bool(name: str, default: bool = False) -> bool:
    v = os.environ.get(name)
    if v is None:
        return default
    return v.strip().lower() in ("1", "true", "yes", "on")


# JWT access tokens
JWT_ALGORITHM = "HS256"
ACCESS_TOKEN_MINUTES = int(os.environ.get("ACCESS_TOKEN_MINUTES", "480"))   # 8 hours
MFA_PENDING_MINUTES = 5

# Auth enforcement: "enforce" (default) or "report" (log only, emergency rollback switch)
AUTH_MODE = os.environ.get("AUTH_MODE", "enforce").strip().lower()

# MFA: when true every user must enrol before using the app (OSF requirement for go-live)
MFA_ENFORCED = _bool("MFA_ENFORCED", False)

# Login protection
LOGIN_MAX_FAILURES = int(os.environ.get("LOGIN_MAX_FAILURES", "10"))
LOGIN_LOCK_MINUTES = int(os.environ.get("LOGIN_LOCK_MINUTES", "15"))
LOGIN_IP_WINDOW_SECONDS = 900
LOGIN_IP_MAX_ATTEMPTS = int(os.environ.get("LOGIN_IP_MAX_ATTEMPTS", "30"))

# Password policy for new and changed passwords
PASSWORD_MIN_LENGTH = int(os.environ.get("PASSWORD_MIN_LENGTH", "8"))

# Dangerous dev-only endpoint
ALLOW_SHUTDOWN = _bool("ALLOW_SHUTDOWN", False)

# Admin bootstrap: only re-apply ADMIN_PASSWORD to an existing admin when explicitly asked
ADMIN_FORCE_RESET = _bool("ADMIN_FORCE_RESET", False)

# Interactive API docs (/docs, /openapi.json) are admin-only unless explicitly enabled
ENABLE_API_DOCS = _bool("ENABLE_API_DOCS", False)

# Client IP: number of trusted reverse proxies in front of the app that APPEND to X-Forwarded-For.
# Northflank alone = 1; Cloudflare in front of Northflank = 2; 0 = ignore the header (direct exposure).
# Only the address added by our own proxy is trusted - values a client puts in the header are ignored.
PROXY_HOPS = int(os.environ.get("PROXY_HOPS", "1"))

# How long (seconds) session-revocation / policy lookups are cached per worker
SESSION_CACHE_SECONDS = int(os.environ.get("SESSION_CACHE_SECONDS", "15"))
