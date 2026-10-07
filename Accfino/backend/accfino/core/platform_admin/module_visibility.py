"""
Admin > Modules: which domains/modules are switched on (/module-visibility).
"""
import os
import sys
from pathlib import Path
from fastapi import APIRouter
from accfino.shared import paths as _paths

router = APIRouter()

import logging
logger = logging.getLogger("accfino")


import base64, io, json, logging, os, sys, uuid
from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile, Body

_MODULE_VISIBILITY_FILE = _paths.config_file("module_visibility.json")     # legacy location, imported once into the database

_MV_SERVICE = "module_visibility"        # platform_settings rows: key "domain:<id>" / "module:<id>" = "off" (absent = visible)

def _load_module_visibility() -> dict:
    """{ domains: {id: False}, modules: {id: False} } - only switched-OFF items are stored, missing means visible.
    Stored in platform_settings (shared by every instance/worker, reset with the database). A visibility file left by
    the previous version is imported once, then renamed."""
    out = {"domains": {}, "modules": {}}
    try:
        from accfino.shared.db.database import SessionLocal
        from accfino.core.platform_setting import PlatformSetting
        db = SessionLocal()
        try:
            rows = db.query(PlatformSetting).filter(PlatformSetting.service == _MV_SERVICE).all()
            if not rows and _MODULE_VISIBILITY_FILE.exists():
                try:
                    legacy = json.loads(_MODULE_VISIBILITY_FILE.read_text(encoding="utf-8"))
                    _save_module_visibility(legacy)
                    _MODULE_VISIBILITY_FILE.rename(_MODULE_VISIBILITY_FILE.with_suffix(".json.migrated"))
                    return _load_module_visibility()
                except Exception:
                    pass
            for r in rows:
                kind, _, ident = r.key_name.partition(":")
                if r.key_value == "off" and kind in ("domain", "module") and ident:
                    out["domains" if kind == "domain" else "modules"][ident] = False
        finally:
            db.close()
    except Exception as e:                     # fail open: a settings problem must never blank the product
        logger.warning(f"module visibility: could not read platform_settings ({e})")
    return out

def _save_module_visibility(data: dict):
    from accfino.shared.db.database import SessionLocal
    from accfino.core.platform_setting import PlatformSetting
    off = [("domain:" + str(k)) for k, v in (data.get("domains") or {}).items() if v is False or v == "off"] + \
          [("module:" + str(k)) for k, v in (data.get("modules") or {}).items() if v is False or v == "off"]
    db = SessionLocal()
    try:
        db.query(PlatformSetting).filter(PlatformSetting.service == _MV_SERVICE).delete()
        for key in off:
            db.add(PlatformSetting(service=_MV_SERVICE, key_name=key[:100], key_value="off"))
        db.commit()
    except Exception:
        db.rollback(); raise
    finally:
        db.close()

@router.get("/module-visibility")
def module_visibility_get():
    """Public - every logged-in surface (side panel, Home, marketing page) reads
    this to decide what to show. Missing entries default to visible."""
    return _load_module_visibility()

@router.post("/module-visibility")
def module_visibility_save(body: dict = Body(...)):
    """Admin - replace the full visibility map."""
    _save_module_visibility(body)
    return {"ok": True}

