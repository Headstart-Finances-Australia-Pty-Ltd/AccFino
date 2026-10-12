"""
Payment-gateway configuration endpoints: Square, Stripe, bank account.
"""
import os
import sys
from pathlib import Path
from fastapi import APIRouter
from accfino.shared import paths as _paths

router = APIRouter()
from accfino.shared.integrations_store import integration_cfg, save_integration

import logging
logger = logging.getLogger("accfino")


import os
import base64, io, json, logging, os, sys, uuid
from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile, Body

@router.get("/square/status")
def square_status():
    cfg = integration_cfg("square")
    configured = bool(cfg.get("access_token")) or bool(os.getenv("SQUARE_ACCESS_TOKEN"))
    return {"available": True, "configured": configured,
            "environment": cfg.get("environment", os.getenv("SQUARE_ENVIRONMENT", "sandbox")),
            "application_id": cfg.get("application_id", os.getenv("SQUARE_APPLICATION_ID", ""))}

@router.post("/square/config")
def square_config_save(body: dict = Body(...)):
    cfg = {
        "application_id": body.get("application_id", ""),
        "access_token":   body.get("access_token", ""),
        "location_id":    body.get("location_id", ""),
        "environment":    body.get("environment", "sandbox"),
    }
    save_integration("square", cfg)
    return {"ok": True}

@router.get("/stripe/status")
def stripe_status():
    cfg = integration_cfg("stripe")
    configured = bool(cfg.get("secret_key")) or bool(os.getenv("STRIPE_SECRET_KEY"))
    return {"available": True, "configured": configured,
            "environment": cfg.get("environment", os.getenv("STRIPE_ENVIRONMENT", "sandbox")),
            "publishable_key": cfg.get("publishable_key", os.getenv("STRIPE_PUBLISHABLE_KEY", ""))}

@router.post("/stripe/config")
def stripe_config_save(body: dict = Body(...)):
    cfg = {
        "publishable_key": body.get("publishable_key", ""),
        "secret_key":      body.get("secret_key", ""),
        "webhook_secret":  body.get("webhook_secret", ""),
        "environment":     body.get("environment", "sandbox"),
    }
    save_integration("stripe", cfg)
    return {"ok": True}

@router.get("/bank-account/status")
def bank_account_status():
    cfg = integration_cfg("bank_account")
    configured = bool(cfg.get("bsb")) and bool(cfg.get("account_number"))
    return {"available": True, "configured": configured,
            "account_name": cfg.get("account_name", ""),
            "bank_name": cfg.get("bank_name", ""),
            "account_number_last4": cfg.get("account_number", "")[-4:] if cfg.get("account_number") else ""}

@router.post("/bank-account/config")
def bank_account_config_save(body: dict = Body(...)):
    cfg = {
        "account_name":   body.get("account_name", ""),
        "bank_name":      body.get("bank_name", ""),
        "bsb":            body.get("bsb", ""),
        "account_number": body.get("account_number", ""),
    }
    save_integration("bank_account", cfg)
    return {"ok": True}

