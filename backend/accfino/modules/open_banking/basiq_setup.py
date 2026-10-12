"""Platform-level Basiq set-up, done ONCE by the AccFino administrator in Admin Console > Open Banking (OpenFeed's own set-up lives in openfeed_cdr.py).

Clients never see or enter any of this: they only connect their own accounts from Settings > Open Banking.
Precedence (same as OpenFeed): a server environment variable wins; otherwise what the administrator saved; otherwise a sensible default.
The API key is stored encrypted and is never sent back to the browser. Read per request (small cache) so every worker picks up a change."""
import os
import time
from typing import Optional

import requests

from accfino.core import models as m
from accfino.core.security.secrets import seal, unseal

DEFAULT_BASE = "https://au-api.basiq.io"
DEFAULT_VERSION = "3.0"
_K_KEY, _K_BASE, _K_VER = "basiq.api_key", "basiq.base_url", "basiq.version"
_cache: dict = {"at": 0.0, "val": None}
_TTL = 10.0


def _rows(db) -> dict:
    out = {}
    for k in (_K_KEY, _K_BASE, _K_VER):
        r = db.get(m.SystemSetting, k)
        out[k] = (r.value or "").strip() if r else ""
    return out


def _load(db=None) -> dict:
    close = False
    if db is None:
        from accfino.shared.db.database import SessionLocal
        db, close = SessionLocal(), True
    try:
        return _rows(db)
    finally:
        if close:
            db.close()


def basiq_config(db=None) -> dict:
    """{base_url, api_key, version, source}. source = 'environment' | 'admin' | None (not configured)."""
    now = time.time()
    if db is None and _cache["val"] is not None and now - _cache["at"] < _TTL:
        return dict(_cache["val"])
    try:
        saved = _load(db)
    except Exception:                                    # database not reachable (e.g. very early start-up): fall back to the environment only
        saved = {_K_KEY: "", _K_BASE: "", _K_VER: ""}
    env_key = (os.getenv("BASIQ_API_KEY") or "").strip()
    admin_key = (unseal(saved[_K_KEY]) or "") if saved[_K_KEY] else ""
    val = {"api_key": env_key or admin_key,
           "base_url": (os.getenv("BASIQ_BASE_URL") or saved[_K_BASE] or DEFAULT_BASE).rstrip("/"),
           "version": os.getenv("BASIQ_VERSION") or saved[_K_VER] or DEFAULT_VERSION,
           "source": "environment" if env_key else ("admin" if admin_key else None)}
    if db is None:
        _cache.update(at=now, val=dict(val))
    return val


def forget_cache():
    _cache.update(at=0.0, val=None)


def basiq_status(db) -> dict:
    c = basiq_config(db)
    return {"configured": bool(c["api_key"]), "source": c["source"], "base_url": c["base_url"], "version": c["version"],
            "locked_by_environment": c["source"] == "environment"}


def _put(db, key: str, value: str):
    row = db.get(m.SystemSetting, key)
    if row is None:
        db.add(m.SystemSetting(key=key, value=value))
    else:
        row.value = value
    db.flush()


def save_basiq(db, api_key: Optional[str] = None, base_url: Optional[str] = None, version: Optional[str] = None, clear: bool = False):
    """A blank api_key keeps the saved one (so the screen never has to hold the secret); clear=True removes it."""
    if clear:
        _put(db, _K_KEY, "")
    elif api_key and api_key.strip():
        _put(db, _K_KEY, seal(api_key.strip()))
    if base_url is not None:
        b = base_url.strip().rstrip("/")
        if b and not b.startswith("https://"):
            raise ValueError("The Basiq address must start with https://")
        _put(db, _K_BASE, b)
    if version is not None:
        _put(db, _K_VER, version.strip())
    forget_cache()


def _http_post(url: str, headers: dict):
    return requests.post(url, headers=headers, timeout=15)


def test_basiq(db) -> dict:
    """Ask Basiq for a server token with the effective settings. Never raises; never echoes the key."""
    c = basiq_config(db)
    if not c["api_key"]:
        return {"ok": False, "message": "No Basiq API key is saved yet."}
    try:
        r = _http_post(c["base_url"] + "/token", {"accept": "application/json", "basiq-version": c["version"], "content-type": "application/x-www-form-urlencoded",
                                                  "Authorization": f"Basic {c['api_key']}"})
    except Exception:
        return {"ok": False, "message": "Could not reach Basiq. Check the address and your network."}
    if r.status_code == 200:
        return {"ok": True, "message": "Connected to Basiq."}
    if r.status_code in (400, 401, 403):
        return {"ok": False, "message": f"Basiq rejected the API key ({r.status_code}). Check the key and that it is a server application key."}
    return {"ok": False, "message": f"Basiq returned {r.status_code}. Try again shortly."}
