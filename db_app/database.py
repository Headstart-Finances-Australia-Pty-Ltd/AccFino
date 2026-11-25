import json
import logging
import os
import re
import threading
import time
from pathlib import Path

import psycopg2
import psycopg2.extensions
from sqlalchemy import create_engine, event, exc
from sqlalchemy.dialects.postgresql import psycopg2 as _pg_psycopg2
from sqlalchemy.engine import make_url
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import NullPool

log = logging.getLogger("accfino.db")

_DATABASE_URL = os.environ.get("DATABASE_URL", "")

if not _DATABASE_URL:
    raise RuntimeError(
        "[accfino] DATABASE_URL environment variable is not set.\n"
        "Set it to your PostgreSQL connection string, e.g.:\n"
        "  postgresql+psycopg2://user:password@host:5432/dbname\n"
        "For local development, install PostgreSQL and set DATABASE_URL in app.cmd."
    )


def _normalise(url: str) -> str:
    """postgres:// -> postgresql+psycopg2://, trailing whitespace stripped (Windows CMD can add spaces)."""
    url = url.strip()
    if url.startswith("postgres://"):
        url = url.replace("postgres://", "postgresql+psycopg2://", 1)
    elif url.startswith("postgresql://") and "+psycopg2" not in url:
        url = url.replace("postgresql://", "postgresql+psycopg2://", 1)
    return url


def _needs_ssl(url: str) -> bool:
    return "neon.tech" in url or "sslmode=require" in url


def _strip_sslmode(url: str) -> str:
    # sslmode is passed through connect args instead of the URL.
    return re.sub(r"[?&]sslmode=\S+", "", url).rstrip("?").strip()


# ─────────────────────────────────────────────────────────────────────────────
# Database failover (main database + optional standby databases)
#
#   DATABASE_URL            main database                      -> number 0
#   DATABASE_STANDBY_URLS   extra connection strings (comma or newline
#                           separated, e.g. a second Neon account) -> 1, 2, ...
#   DATABASE_ACTIVE_INDEX   which one to start on (default 0)
#
# New connections use the active database. When it can't be reached or is out
# of quota (Neon "compute time quota exceeded", too many connections, suspended
# project), the next one is tried and becomes the active one. Failover happens
# ONLY while a connection is being opened, never in the middle of a query, so a
# write is never silently repeated. Copying data between the databases lives
# in db_app/dbsync.py.
#
# With no DATABASE_STANDBY_URLS this behaves like the plain engine it used to be.
# ─────────────────────────────────────────────────────────────────────────────
_RAW_URLS = [_DATABASE_URL] + [
    u for u in re.split(r"[,\n]+", os.environ.get("DATABASE_STANDBY_URLS", "")) if u.strip()
]
URLS = [_normalise(u) for u in _RAW_URLS]
_SSL = [_needs_ssl(u) for u in URLS]
URLS = [_strip_sslmode(u) for u in URLS]
_DATABASE_URL = URLS[0]  # kept for modules that import it

_APP_NAME = os.environ.get("ACCFINO_APP_NAME", "accfino")
_MARKER = Path(os.environ.get("DB_ACTIVE_MARKER") or Path(__file__).resolve().parent / ".db-active.json")
_BAD_FOR_S = 600


def _host(i: int) -> str:
    try:
        return make_url(URLS[i]).host or "?"
    except Exception:
        return "?"


class Failover:
    def __init__(self, count: int):
        self.count = count
        self.bad_until: dict[int, float] = {}
        self.hooks = []          # callables (old, new) run in a background thread after an automatic failover
        self._marker_mtime = 0.0
        self._active = self._initial_active()

    @property
    def enabled(self) -> bool:
        return self.count > 1

    def _initial_active(self) -> int:
        env = os.environ.get("DATABASE_ACTIVE_INDEX", "").strip()
        if env.isdigit() and int(env) < self.count:
            n = int(env)
        else:
            n = 0
            try:  # remember where the last run ended up, so a restart doesn't jump back to older data
                m = int(json.loads(_MARKER.read_text()).get("active", 0))
                if 0 < m < self.count:
                    n = m
            except Exception:
                pass
        if self.enabled:
            self._write_marker(n)
        return n

    def _write_marker(self, n: int):
        try:
            _MARKER.write_text(json.dumps({"active": n, "at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}))
            self._marker_mtime = _MARKER.stat().st_mtime
        except Exception:
            pass

    @property
    def active(self) -> int:
        """The active database. The marker file is how the two server processes (main + auth) stay in step."""
        if self.enabled:
            try:
                mt = _MARKER.stat().st_mtime
                if mt != self._marker_mtime:
                    self._marker_mtime = mt
                    n = int(json.loads(_MARKER.read_text()).get("active", self._active))
                    if 0 <= n < self.count:
                        self._active = n
            except Exception:
                pass
        return self._active

    def set_active(self, i: int, reason: str = "manual"):
        if not (0 <= i < self.count) or i == self._active:
            return
        prev = self._active
        self._active = i
        self.bad_until.pop(i, None)
        self._write_marker(i)
        log.error("DATABASE SWITCH (%s): now using database %d (%s), was %d.", reason, i, _host(i), prev)

    def _failed_over(self, i: int):
        prev = self._active
        self._active = i
        self._write_marker(i)
        log.error(
            "DATABASE FAILOVER: now using database %d (%s). Set DATABASE_ACTIVE_INDEX=%d so a restart keeps it.",
            i, _host(i), i,
        )
        for h in list(self.hooks):
            threading.Thread(target=h, args=(prev, i), daemon=True, name="db-failover-hook").start()

    def status(self) -> dict:
        now = time.time()
        return {
            "active": self.active,
            "count": self.count,
            "hosts": [_host(i) for i in range(self.count)],
            "marked_unusable": [
                {"index": i, "retry_in_s": int(t - now)} for i, t in self.bad_until.items() if t > now
            ],
        }


failover = Failover(len(URLS))


class _Tagged(psycopg2.extensions.connection):
    """A connection that remembers which database it belongs to."""
    kidx = -1


def _connect_kwargs(i: int) -> dict:
    _args, kw = _pg_psycopg2.dialect().create_connect_args(make_url(URLS[i]))
    kw = dict(kw)
    if _SSL[i]:
        kw["sslmode"] = "require"
    kw.setdefault("connect_timeout", 20)
    kw.setdefault("application_name", _APP_NAME)  # shows up in pg_stat_activity / Neon's monitoring
    kw.setdefault("keepalives", 1)
    kw.setdefault("keepalives_idle", 60)
    return kw


def connect_index(i: int):
    """A raw psycopg2 connection to database number `i` (no failover). Used by the copy tool."""
    conn = psycopg2.connect(connection_factory=_Tagged, **_connect_kwargs(i))
    conn.kidx = i
    return conn


def _connect_active():
    n = len(URLS)
    start = failover.active
    last = None
    for step in range(n):
        i = (start + step) % n
        if step and failover.bad_until.get(i, 0) > time.time():
            continue
        try:
            conn = connect_index(i)
        except psycopg2.Error as e:
            last = e
            if n > 1:
                failover.bad_until[i] = time.time() + _BAD_FOR_S
                log.warning("Database %d (%s) not usable: %s", i, _host(i), str(e).strip()[:160])
            continue
        if i != failover.active:
            failover._failed_over(i)
        return conn
    raise last


engine = create_engine(
    URLS[0],
    creator=_connect_active,
    pool_size=2,        # Neon free tier: max 20 connections total
    max_overflow=3,     # Allow 3 extra on burst
    pool_timeout=60,    # Neon can be slow to connect first time
    pool_recycle=300,   # Recycle connections every 5 min (Neon idles fast)
    pool_pre_ping=True, # Check connection before using
)


@event.listens_for(engine, "checkout")
def _drop_other_database(dbapi_conn, _record, _proxy):
    """After a failover, pooled connections to the old database are thrown away instead of reused."""
    if getattr(dbapi_conn, "kidx", failover.active) != failover.active:
        raise exc.DisconnectionError("database switched")


def make_engine(i: int):
    """A throw-away engine pinned to database number `i` (no failover, no pooling) - for schema setup and copies."""
    return create_engine(URLS[i], creator=lambda: connect_index(i), poolclass=NullPool)


# Optional: DB_TRACE=1 logs every statement's first words with a timestamp, so a database that
# "wakes up by itself" can be traced back to the request or job that did it.
if os.environ.get("DB_TRACE") == "1":
    @event.listens_for(engine, "before_cursor_execute")
    def _trace(conn, cursor, statement, parameters, context, executemany):
        log.warning("[dbtrace] %s", " ".join(statement.split())[:110])

print(
    "[accfino] database: PostgreSQL"
    + (f" (failover on: {failover.count} databases, active #{failover.active})" if failover.enabled else "")
)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
