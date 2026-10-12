import os
from pathlib import Path
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

_DATABASE_URL = os.environ.get("DATABASE_URL", "")

if not _DATABASE_URL:
    raise RuntimeError(
        "[accfino] DATABASE_URL environment variable is not set.\n"
        "Set it to your PostgreSQL connection string, e.g.:\n"
        "  postgresql+psycopg2://user:password@host:5432/dbname\n"
        "For local development set DATABASE_URL in the .env file next to app.cmd."
    )

def normalise_database_url(url: str):
    """Return (sqlalchemy_url, connect_args) for the psycopg2 driver AccFino uses.

    Accepts the forms people copy from Neon, Northflank, Heroku or async apps:
      postgres://...  postgresql://...  postgresql+asyncpg://...  postgresql+psycopg://...
      and SSL written as ?sslmode=require (libpq) or ?ssl=require / ssl=true (asyncpg).
    """
    import re
    url = (url or "").strip().strip('"').strip("'")
    # any driver suffix (asyncpg, psycopg, pg8000...) or none -> psycopg2
    url = re.sub(r"^(postgres|postgresql)(\+[a-z0-9_]+)?://", "postgresql+psycopg2://", url, count=1, flags=re.I)
    params = {}
    if "?" in url:
        base, query = url.split("?", 1)
        for part in query.split("&"):
            if "=" in part:
                k, v = part.split("=", 1)
                params[k.lower()] = v
        url = base
    ssl_required = (params.pop("sslmode", "").lower() in ("require", "verify-ca", "verify-full")
                    or params.pop("ssl", "").lower() in ("require", "true", "1")
                    or "neon.tech" in url)
    # keep libpq options psycopg2 understands (e.g. channel_binding); drop asyncpg-only ones
    keep = {k: v for k, v in params.items() if k in ("channel_binding", "connect_timeout", "application_name",
                                                      "options", "target_session_attrs")}
    if keep:
        url += "?" + "&".join(f"{k}={v}" for k, v in keep.items())
    return url, ({"sslmode": "require"} if ssl_required else {})


_DATABASE_URL, _connect_args = normalise_database_url(_DATABASE_URL)

def _env_int(name: str, default: int) -> int:
    try:
        return max(1, int(os.environ.get(name, default)))
    except ValueError:
        return default


engine = create_engine(
    _DATABASE_URL,
    pool_size=_env_int("DB_POOL_SIZE", 4),          # per process. Neon free tier allows 20 connections in total: two workers x (4 + 4) = 16
    max_overflow=_env_int("DB_MAX_OVERFLOW", 4),    # extra connections on a burst (the admin pages fire ~15 requests at once)
    pool_timeout=_env_int("DB_POOL_TIMEOUT", 30),   # seconds to wait for a free connection before giving up
    pool_recycle=300,   # Recycle connections every 5 min (Neon idles fast)
    pool_pre_ping=True, # Check connection before using
    connect_args=_connect_args,
)
print(f"[accfino] database: PostgreSQL")

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
