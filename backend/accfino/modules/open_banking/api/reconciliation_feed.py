"""
Open Banking endpoints used by the reconciliation screen: Basiq status/users/accounts, saved accounts, period pull, fetch-and-normalise.
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


from datetime import datetime
import pandas as pd
from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile, Body
try:
    from accfino.modules.open_banking.basiq import auth as ob_auth, user as ob_user, job_service as ob_job
    OB_AVAILABLE = True
except Exception:
    OB_AVAILABLE = False
from fastapi.requests  import Request as _Request
from accfino.shared.db.database import SessionLocal as _SL

@router.get("/openbanking/status")
def ob_status():
    from accfino.modules.open_banking.basiq_setup import basiq_config as _bc
    return {"available": OB_AVAILABLE, "configured": bool(_bc()["api_key"])}

@router.post("/openbanking/create-user")
def ob_create_user(body: dict=Body(...)):
    if not OB_AVAILABLE: raise HTTPException(503, "Open Banking not available")
    try:
        token = ob_auth.get_access_token()
        return ob_user.create_basiq_user_object(
            token, body.get("email",""), body.get("mobile",""),
            body.get("first_name",""), body.get("last_name",""))
    except Exception as e: raise HTTPException(500, str(e))

@router.get("/openbanking/accounts/{user_id}")
def ob_accounts(user_id: str):
    if not OB_AVAILABLE: raise HTTPException(503, "Open Banking not available")
    try:
        token = ob_auth.get_access_token()
        return ob_job.get_accounts(token, user_id)
    except Exception as e: raise HTTPException(500, str(e))

@router.get("/openbanking/transactions/{user_id}")
def ob_transactions(user_id: str):
    if not OB_AVAILABLE: raise HTTPException(503, "Open Banking not available")
    try:
        token = ob_auth.get_access_token()
        return ob_job.get_transactions(token, user_id)
    except Exception as e: raise HTTPException(500, str(e))

@router.post("/openbanking/fetch-and-normalise")
def ob_fetch_normalise(body: dict = Body(...)):
    """
    Fetch transactions from Open Banking, save as normalised CSV,
    and return rows ready to feed into /reconcile/process.
    Mirrors the original open_banking_connector.py logic.
    """
    if not OB_AVAILABLE:
        raise HTTPException(503, "Open Banking module not available")
    try:
        from accfino.modules.open_banking.basiq import csv_exporter as ob_csv_exp
        user_id    = body.get("user_id", "")
        account_id = body.get("account_id", "")
        token      = ob_auth.get_access_token()
        txns_raw   = ob_job.get_transactions(token, user_id)
        txns_list  = txns_raw.get("data", []) if isinstance(txns_raw, dict) else txns_raw

        # Normalise to bank_normalizer canonical format
        rows = []
        for t in txns_list:
            amount = float(t.get("amount", 0) or 0)
            rows.append({
                "date":        t.get("postDate") or t.get("valueDate", ""),
                "description": t.get("description") or t.get("narration", ""),
                "debit":       abs(amount) if amount < 0 else 0.0,
                "credit":      amount      if amount > 0 else 0.0,
                "balance":     float(t.get("runningBalance", 0) or 0),
                "bank":        body.get("bank_name", "OpenBanking"),
                "account":     account_id or t.get("accountId", ""),
            })

        # Also save to CSV
        csv_path = str(_paths.module_dir("open_banking", "exports") / f"ob_{user_id}_{account_id}.csv")
        pd.DataFrame(rows).to_csv(csv_path, index=False)

        return {"rows": rows, "count": len(rows), "csv_saved": csv_path}
    except Exception as e:
        raise HTTPException(500, str(e))

def _ob_saved_accounts(org_id: int = None) -> list:
    out = []
    for a in (integration_cfg("basiq_accounts") or {}).get("accounts", []):
        if a.get("account_id") and a.get("user_id"):
            out.append({
                "key": f"basiq:{a['account_id']}", "provider": "basiq",
                "user_id": a["user_id"], "account_id": a["account_id"],
                "bank": a.get("bank", ""), "name": a.get("name", ""), "number": a.get("number", ""),
            })
    if org_id:                                    # the signed-in organisation's own OpenFeed (CDR) accounts - only if its plan includes live bank feeds
        from accfino.modules.open_banking import openfeed as _OF
        from accfino.core.subscription import service as _S
        _db = _SL()
        try:
            if not _S.is_allowed(_S.entitlements(_db, org_id), ("open-banking",)):
                return out
            for a in _OF.org_accounts(_db, org_id):
                out.append({"key": f"openfeed:{a['id']}", "provider": "openfeed", "user_id": "", "account_id": a["id"],
                            "bank": a.get("provider", ""), "name": a.get("name", "Account"), "number": a.get("masked", "")})
        finally:
            _db.close()
    return out

def _ob_org_id(request) -> int:
    """The organisation a reconciliation request belongs to (None when it can't be resolved, e.g. a platform admin with no organisation)."""
    try:
        from accfino.core.security.context import current_org as _co
        _db = _SL()
        try:
            return _co(request, _db).org.id
        finally:
            _db.close()
    except Exception:
        return None

@router.get("/openbanking/reconcile-accounts")
def ob_reconcile_accounts(request: _Request):
    return {"accounts": _ob_saved_accounts(_ob_org_id(request))}

@router.get("/openbanking/saved-accounts")
def ob_saved_accounts_get():
    return {"accounts": (integration_cfg("basiq_accounts") or {}).get("accounts", [])}

@router.post("/openbanking/saved-accounts")
def ob_saved_accounts_save(body: dict = Body(...)):
    keep = []
    for a in body.get("accounts", []):
        if not (a.get("account_id") and a.get("user_id")):
            continue
        keep.append({k: str(a.get(k, "") or "") for k in ("user_id", "account_id", "bank", "name", "number")})
    save_integration("basiq_accounts", {"accounts": keep})
    return {"ok": True, "count": len(keep)}

def _ob_parse_day(v: str, label: str):
    try:
        return datetime.strptime(str(v)[:10], "%Y-%m-%d").date()
    except Exception:
        raise HTTPException(400, f"{label} must be a date (YYYY-MM-DD)")

@router.post("/openbanking/pull")
def ob_pull(request: _Request, body: dict = Body(...)):
    """Pull one saved account for a period, normalised to the reconciliation CSV layout."""
    _org = _ob_org_id(request)
    acc = next((a for a in _ob_saved_accounts(_org) if a["key"] == body.get("account_key")), None)
    if not acc:
        raise HTTPException(400, "That account isn't set up in Settings > Open Banking")
    d_from = _ob_parse_day(body.get("from_date"), "From date")
    d_to   = _ob_parse_day(body.get("to_date"), "To date")
    if d_from > d_to:
        raise HTTPException(400, "From date must be on or before To date")
    if acc["provider"] == "openfeed":
        from accfino.modules.open_banking import openfeed as _OF
        _db = _SL()
        try:
            rows = _OF.pull_rows(_db, _org, acc["account_id"], d_from, d_to)
            _db.commit()
        except _OF.OpenFeedError as e:
            _db.commit()
            raise HTTPException(e.status, e.message)
        finally:
            _db.close()
        return {"rows": rows, "count": len(rows), "bank": acc["bank"] or "OpenFeed", "account": acc["number"] or acc["account_id"],
                "account_name": acc["name"], "from_date": d_from.isoformat(), "to_date": d_to.isoformat()}
    if acc["provider"] != "basiq":
        raise HTTPException(501, "Unknown bank-feed provider")
    if not OB_AVAILABLE:
        raise HTTPException(503, "Open Banking module not available")
    try:
        txns = ob_job.get_transactions(acc["account_id"], d_from.isoformat(), d_to.isoformat())
    except Exception as e:
        raise HTTPException(502, f"Basiq request failed: {e}")
    bank = acc["bank"] or "OpenBanking"
    number = acc["number"] or acc["account_id"]
    rows = []
    for t in txns:
        raw_day = str(t.get("postDate") or t.get("transactionDate") or t.get("valueDate") or "")[:10]
        try:
            day = datetime.strptime(raw_day, "%Y-%m-%d").date()
        except Exception:
            continue
        if not (d_from <= day <= d_to):      # belt and braces: enforce the period even if the API ignores the filter
            continue
        try:    amount = float(t.get("amount", 0) or 0)
        except Exception: amount = 0.0
        if str(t.get("direction", "")).lower() == "debit" and amount > 0:
            amount = -amount                  # Basiq can report direction separately from the sign
        try:    bal = float(t.get("balance", "") or 0)
        except Exception: bal = ""
        rows.append({
            "date": day.strftime("%d/%m/%Y"),
            "description": (t.get("description") or t.get("narration") or "").strip(),
            "debit":  abs(amount) if amount < 0 else 0.0,
            "credit": amount if amount > 0 else 0.0,
            "balance": bal, "bank": bank, "account": number,
        })
    rows.sort(key=lambda r: datetime.strptime(r["date"], "%d/%m/%Y"))
    return {"rows": rows, "count": len(rows), "bank": bank, "account": number,
            "account_name": acc["name"], "from_date": d_from.isoformat(), "to_date": d_to.isoformat()}

