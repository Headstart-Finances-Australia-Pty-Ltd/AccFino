"""Background renewal loop. Started once per web worker; a Postgres advisory lock makes sure only ONE worker runs a pass at a time (and charge rows are
idempotent anyway). Switch off with BILLING_AUTORUN=0; interval via BILLING_INTERVAL_MIN (default 30)."""
import logging
import os
import threading
import time

from sqlalchemy import text

log = logging.getLogger("accfino.billing")
LOCK_ID = 727001
_started = False


def run_once() -> dict:
    from accfino_core.billing import service as B
    from db_app.database import SessionLocal, engine
    db = SessionLocal()
    try:
        if not B.SquareCfg(db).ready:
            return {"skipped": "square not configured"}
    finally:
        db.close()
    pg = engine.dialect.name == "postgresql"
    conn = engine.connect() if pg else None
    try:
        if pg and not conn.execute(text("SELECT pg_try_advisory_lock(:k)"), {"k": LOCK_ID}).scalar():
            return {"skipped": "another worker is running billing"}
        return B.run_due(SessionLocal)
    finally:
        if conn is not None:
            try:
                conn.execute(text("SELECT pg_advisory_unlock(:k)"), {"k": LOCK_ID})
            finally:
                conn.close()


def _loop(minutes: int):
    time.sleep(60)                                           # let start-up and migrations finish first
    while True:
        try:
            res = run_once()
            if any(res.get(k) for k in ("paid", "failed", "errors")):
                log.info("billing pass: %s", res)
        except Exception:
            log.exception("billing pass crashed")
        time.sleep(minutes * 60)


def start_billing_loop():
    global _started
    if _started or os.environ.get("BILLING_AUTORUN", "1") == "0":
        return
    _started = True
    minutes = max(5, int(os.environ.get("BILLING_INTERVAL_MIN", "30") or 30))
    threading.Thread(target=_loop, args=(minutes,), daemon=True, name="accfino-billing").start()
