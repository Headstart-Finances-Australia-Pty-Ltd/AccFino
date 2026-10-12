"""
Small JSON store for runtime integration settings (ACCFINO_DATA_ROOT/config/integrations.json).
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

_INTEGRATIONS_FILE = _paths.config_file("integrations.json")

def load_integrations() -> dict:
    try:
        if _INTEGRATIONS_FILE.exists():
            return json.loads(_INTEGRATIONS_FILE.read_text(encoding="utf-8"))
    except Exception:
        pass
    return {}

def save_integration(name: str, cfg: dict):
    _INTEGRATIONS_FILE.parent.mkdir(parents=True, exist_ok=True)
    data = load_integrations()
    data[name] = cfg
    _INTEGRATIONS_FILE.write_text(json.dumps(data, indent=2), encoding="utf-8")

def integration_cfg(name: str) -> dict:
    return load_integrations().get(name, {})

