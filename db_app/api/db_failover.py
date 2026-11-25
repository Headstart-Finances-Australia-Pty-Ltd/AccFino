"""Database failover status and manual copies.

AccFino has no server-side login sessions, so these controls are protected by a
secret instead: set DB_ADMIN_TOKEN in the environment and send it as the
`X-DB-Admin-Token` header. With no DB_ADMIN_TOKEN set, every route here answers 503.
"""
import hmac
import os
import threading

from fastapi import APIRouter, Header, HTTPException

from db_app import dbsync
from db_app.database import failover

router = APIRouter()


def _check(token: str | None):
    expected = os.environ.get("DB_ADMIN_TOKEN", "")
    if not expected:
        raise HTTPException(503, "Set DB_ADMIN_TOKEN in the server environment to use these controls.")
    if not token or not hmac.compare_digest(token, expected):
        raise HTTPException(403, "Invalid token.")


@router.get("/status")
def status(x_db_admin_token: str | None = Header(default=None)):
    _check(x_db_admin_token)
    return {"failover": failover.status(), "busy": dbsync.is_busy(), "last": dbsync.last}


@router.post("/sync", status_code=202)
def sync(source: int, target: int, x_db_admin_token: str | None = Header(default=None)):
    """Merge database `source` into `target` (0 = DATABASE_URL, 1 = first standby ...) in the background."""
    _check(x_db_admin_token)
    n = failover.count
    if not (0 <= source < n and 0 <= target < n) or source == target:
        raise HTTPException(400, f"Pick two different database numbers between 0 and {n - 1}.")
    if dbsync.is_busy():
        raise HTTPException(409, "A database copy is already running.")
    threading.Thread(target=dbsync.merge_now, args=(source, target), daemon=True, name="db-manual-sync").start()
    return {"message": f"Copying database {source} into {target} in the background."}


@router.post("/switch")
def switch(to: int, x_db_admin_token: str | None = Header(default=None)):
    """Make a database the active one (e.g. move back to the main one after a manual copy)."""
    _check(x_db_admin_token)
    if not (0 <= to < failover.count):
        raise HTTPException(400, f"Pick a database number between 0 and {failover.count - 1}.")
    failover.set_active(to, "admin")
    return {"failover": failover.status()}
