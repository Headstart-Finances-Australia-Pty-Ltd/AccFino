"""Optional request timing: set ACCFINO_PROFILE=1 and every request slower than ACCFINO_SLOW_MS (default 800) is logged with its SQL statement count and the
time spent waiting on the database. Off by default (no listeners are installed). Nothing about the request body, headers or query values is logged.

Why it exists: with a remote database (Neon etc.) the cost of a page is roughly  statements x network round trip, so the statement count is the number to watch."""
import contextvars
import logging
import os
import time

from sqlalchemy import event
from sqlalchemy.engine import Engine
from starlette.middleware.base import BaseHTTPMiddleware

log = logging.getLogger("accfino.perf")
_cur = contextvars.ContextVar("accfino_perf", default=None)
_installed = False


def enabled() -> bool:
    return os.environ.get("ACCFINO_PROFILE", "").strip().lower() in ("1", "true", "yes", "on")


def _install_listeners():
    global _installed
    if _installed:
        return
    _installed = True

    @event.listens_for(Engine, "before_cursor_execute")
    def _before(conn, cursor, statement, parameters, context, executemany):
        s = _cur.get()
        if s is not None:
            s["n"] += 1
            context._perf_t0 = time.perf_counter()

    @event.listens_for(Engine, "after_cursor_execute")
    def _after(conn, cursor, statement, parameters, context, executemany):
        s = _cur.get()
        t0 = getattr(context, "_perf_t0", None)
        if s is not None and t0 is not None:
            s["db"] += time.perf_counter() - t0


class PerfMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request, call_next):
        stats = {"n": 0, "db": 0.0}
        tok = _cur.set(stats)
        t0 = time.perf_counter()
        try:
            resp = await call_next(request)
        finally:
            _cur.reset(tok)
        ms = (time.perf_counter() - t0) * 1000
        if ms >= float(os.environ.get("ACCFINO_SLOW_MS", "800")):
            log.warning("[slow] %s %s -> %s  %.0f ms  (%d SQL statements, %.0f ms in the database)", request.method, request.url.path, resp.status_code, ms, stats["n"], stats["db"] * 1000)
        return resp


def install(app):
    if enabled():
        _install_listeners()
        app.add_middleware(PerfMiddleware)
        logging.getLogger("accfino.perf").setLevel(logging.WARNING)
        print("[accfino] request profiling ON (slow requests are logged with SQL statement counts)")
