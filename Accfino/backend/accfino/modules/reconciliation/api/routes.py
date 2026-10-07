"""
Reconciliation HTTP API: statement processing, classification (ML/LLM/RDR), sessions, knowledge base, chart-of-accounts upload, GST, account balances, dashboard stats.
Moved verbatim from main_app/react_api.py (URLs unchanged).
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
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional
try:
    from main_app.react_api_helpers import _apply_currency_conversion, _detect_loan_payments, _persist_transactions_to_db
except ImportError:
    try:
        from react_api_helpers import (
            _apply_currency_conversion,
            _detect_loan_payments,
            _persist_transactions_to_db,
        )
    except ImportError:
        pass   # helpers not deployed yet — currency/loan features silently disabled
try:
    from accfino.modules.reconciliation.pipeline.currency_service import SUPPORTED_CURRENCIES
except Exception:
    SUPPORTED_CURRENCIES = ["AUD","USD","EUR","GBP","INR","JPY","CNY","CAD","NZD","SGD","HKD","CHF"]
import pandas as pd
from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile, Body
from fastapi.responses import Response, StreamingResponse
from pydantic import BaseModel
from accfino.modules.reconciliation.pipeline.bank_normalizer import normalize_transactions, BANK_PRESETS
from accfino.modules.reconciliation.pipeline import classifier as rec_classifier
from accfino.modules.reconciliation.pipeline.gst_calculator import calculate_gst, calculate_gst_value, GST_CATEGORY_OPTIONS
from accfino.modules.reconciliation.pipeline.exporter import export_excel_bytes
from accfino.modules.reconciliation.pipeline.session_manager import session_manager
try:
    from accfino.modules.cashflow.public import auto_detect_columns, preprocess, validate_date_span, monthly_features, train_leaderboard, predict_next_month, LEADERBOARD_CSV, NEXT_MONTH_CSV, LEADERBOARD_PLOT, NEXT_MONTH_PLOT
except Exception:
    auto_detect_columns = preprocess = validate_date_span = monthly_features = None
    train_leaderboard = predict_next_month = None
    LEADERBOARD_CSV = NEXT_MONTH_CSV = LEAD = None
try:
    from accfino.modules.reconciliation.classification.ml.train_model import train_from_df, DEFAULT_MODEL_DIR
    _TRAINER_AVAILABLE = True
except Exception:
    _TRAINER_AVAILABLE = False
    DEFAULT_MODEL_DIR = _paths.ml_models_dir()
    def train_from_df(*a, **kw): raise ImportError("Trainer not available")
from accfino.modules.reconciliation.classification.engine import classify as _engine_classify, warm as _engine_warm, DEFAULT_COA_PATH as _DEFAULT_COA_PATH
from accfino.modules.reconciliation.classification.llm.classify_category import CATEGORY_ENUM
from accfino.modules.reconciliation.pipeline.gst_calculator import GST_CATEGORY_OPTIONS
from fastapi import Depends as _Depends
from fastapi import Depends as _Depends
from sqlalchemy.orm import Session as _Session
from accfino.shared.db.database import get_db as _rdr_get_db
from accfino.modules.reconciliation.models.rdr_rule import RDRRule
from accfino.shared.db.database import SessionLocal as _SL
from accfino.core.identity.user import User as _User

_apply_currency_conversion  = None

_detect_loan_payments       = None

_persist_transactions_to_db = None

def _load_coa_names(path=None) -> tuple:
    """Return (sorted *Name list, {name: type} dict). Postgres
    (chart_of_accounts table) is authoritative; falls back to reading
    ChartOfAccounts.csv directly if the DB isn't reachable yet (e.g. this
    runs at import time, before the startup migration thread has
    necessarily created the table on a brand-new database)."""
    if path is None:
        try:
            from accfino.shared.db.database import SessionLocal
            from accfino.modules.reconciliation.models.reference import ChartOfAccount
            db = SessionLocal()
            try:
                rows = db.query(ChartOfAccount).order_by(ChartOfAccount.name).all()
                if rows:
                    names = [r.name for r in rows]
                    name_to_type = {r.name: (r.type or "") for r in rows}
                    return sorted(names), name_to_type
            finally:
                db.close()
        except Exception:
            pass  # DB not ready yet -- fall through to CSV

    import csv
    from accfino.modules.reconciliation.classification.engine import DEFAULT_COA_PATH
    names, name_to_type = [], {}
    try:
        with open(path or DEFAULT_COA_PATH, newline="", encoding="utf-8-sig") as f:
            for row in csv.DictReader(f):
                name = (row.get("*Name") or "").strip()
                atype = (row.get("*Type") or "").strip()
                if name:
                    names.append(name)
                    name_to_type[name] = atype
    except Exception:
        pass
    return sorted(names), name_to_type

_COA_NAMES, _COA_NAME_TO_TYPE = _load_coa_names()

_ACTIVE_COA_PATH = None   # tracks which COA file is in use; None = DEFAULT

def _refresh_coa_from_db():
    global _COA_NAMES, _COA_NAME_TO_TYPE, _ACTIVE_COA_PATH
    from accfino.modules.reconciliation.services.db_sync import sync_coa_csv_from_db as _sync
    from accfino.modules.reconciliation.classification.engine import evict as _ev, warm as _wm
    _sync()
    _ev()
    _wm(coa_path=_DEFAULT_COA_PATH)
    _ACTIVE_COA_PATH = None
    _COA_NAMES, _COA_NAME_TO_TYPE = _load_coa_names()

try:
    from accfino.modules.accounting.public import register_coa_refresh_hook as _reg_coa_hook
    _reg_coa_hook(_refresh_coa_from_db)
except Exception as _e:
    logger.warning(f"Ledger->classifier bridge not registered: {_e}")

def extract_who_bank(desc: str) -> str:
    """Fallback WHO resolver when CompanyResolver is unavailable."""
    import re as _re
    text = str(desc or "").lower().strip()
    if not text:
        return ""

    # ATO / tax office
    if any(k in text for k in ("australian taxation office", "tax office", "ato ", " ato", "bpay to tax")):
        return "Australian Taxation Office"
    # Macquarie
    if "macquarie" in text:
        return "Macquarie Bank"
    # Interactive Brokers / IBKR
    if "interactive brokers" in text or "ibkr" in text:
        return "Interactive Brokers"
    # Uber
    if "uber eats" in text:
        return "Uber Eats"
    if "uber" in text:
        return "Uber Australia"
    # Microsoft
    if "microsoft" in text:
        return "Microsoft"
    # Google
    if "google ads" in text:
        return "Google Ads"
    if "google" in text:
        return "Google"
    # Xero
    if "xero payroll" in text:
        return "Xero Payroll"
    if "xero" in text:
        return "Xero"
    # Wise
    if "wise australia" in text or "wise" in text:
        return "Wise"
    # Banks
    if "commonwealth bank" in text or "commbank" in text:
        return "Commonwealth Bank of Australia"
    if "westpac" in text:
        return "Westpac"
    if "anz" in text:
        return "ANZ"
    # Invoice payment: "Fast Transfer From PAYEE CREDIT TO ACCOUNT INV-xxxx"
    m = _re.search(
        r'(?:fast transfer from|transfer from|payment from)\s+([a-z][a-z0-9 &\-]{2,35}?)'
        r'\s+(?:credit to account|inv-|invoice|payment)',
        text
    )
    if m:
        candidate = m.group(1).strip().title()
        if candidate and len(candidate) > 2:
            return candidate
    # Generic: "From/To PAYEE" before receipt/BSB/number
    m = _re.search(
        r'^(?:from|to)\s+([a-z][a-z0-9 &\-]{2,40}?)(?:\s+(?:receipt|bsb|a\/c|crn|pty|ltd|inc|\d)|\s*$)',
        text
    )
    if m:
        candidate = m.group(1).strip().title()
        if candidate and len(candidate) > 2:
            return candidate
    return ""

@router.post("/debug/parse-csv", include_in_schema=False)
async def debug_parse_csv(
    file: UploadFile = File(...),
    bank_name: str = Form(...),
):
    """Debug endpoint: parse a CSV and return the first 5 rows as JSON.
    Use this to verify column detection is working correctly on Northflank.
    POST to /api/debug/parse-csv with file + bank_name form fields.
    """
    import io as _io
    try:
        df_raw = pd.read_csv(_io.BytesIO(await file.read()))
        result = normalize_transactions(df_raw, bank_name, "DEBUG")
        return {
            "raw_columns":    df_raw.columns.tolist(),
            "parsed_columns": result.columns.tolist(),
            "row_count":      len(result),
            "sample":         result.head(5).to_dict(orient="records"),
        }
    except Exception as e:
        return {"error": str(e)}

@router.get("/profile/home-company")
def get_home_company(username: str):
    """Return the registered home company for a user."""
    from accfino.shared.db.database import SessionLocal as _SL
    from accfino.core.identity.user import User as _User
    db2 = _SL()
    try:
        u = db2.query(_User).filter(_User.username == norm_username(username)).first()
        return {"home_company": u.home_company if u else ""}
    finally:
        db2.close()

@router.post("/profile/home-company")
def set_home_company(username: str = Body(...), home_company: str = Body(...)):
    """Set the registered home company for a user."""
    from accfino.shared.db.database import SessionLocal as _SL
    from accfino.core.identity.user import User as _User
    db2 = _SL()
    try:
        u = db2.query(_User).filter(_User.username == norm_username(username)).first()
        if not u:
            raise HTTPException(404, "User not found")
        u.home_company = home_company.strip()
        db2.commit()
        return {"home_company": u.home_company, "ok": True}
    finally:
        db2.close()

@router.post("/company/capture-who")
def capture_who_edit(
    who:         str  = Body(...),
    description: str  = Body(default=""),
    username:    str  = Body(default=""),
):
    """
    Called when a user manually sets/corrects the Who field in the output table.

    Behaviour:
      1. If a company with this name already exists (approved) - add the description
         as a new alias so future transactions auto-resolve.
      2. If the company does NOT exist - create it as pending (approved=False)
         so admin can review before it affects all future reconciliations.
      3. In both cases, derive alias keywords from the description text and
         attach them to the company record.

    Frontend flow:
      User edits Who - commitEdits/saveDB - also calls POST /api/company/capture-who
      Admin sees pending companies in the Company DB admin page - approves them
      On next reconciliation, CompanyResolver picks up the new aliases automatically
    """
    from accfino.shared.db.database import SessionLocal as _SL
    from accfino.modules.reconciliation.models.company import Company, CompanyAlias
    from accfino.modules.reconciliation.pipeline.company_resolver import _home_aliases

    who   = (who or "").strip()
    desc  = (description or "").strip()

    if not who:
        return {"ok": False, "reason": "empty who"}

    db = _SL()
    try:
        # -- Look for existing approved company with this name ---------------
        existing = (
            db.query(Company)
            .filter(Company.name.ilike(f"%{who}%"), Company.approved == True)
            .first()
        )

        # -- Build alias set from who name + description keywords ------------
        new_aliases: set = set()

        # Aliases from the who name itself
        new_aliases.update(_home_aliases(who, []))

        # Extract alias keywords from description
        if desc:
            # Key words from the description that identify this company
            desc_lower = desc.lower()
            # Remove known noise tokens
            import re as _re
            _noise = _re.compile(
                r"\b(?:transfer|to|from|fast|direct|credit|debit|payment|"
                r"commbank|app|savings|salary|wages?|payroll|pty|ltd|au|"
                r"bsb|a/c|receipt|number|value|date|card|xx\d+)\b",
                _re.IGNORECASE,
            )
            clean_desc = _noise.sub(" ", desc_lower).strip()
            # Extract 3+ char tokens
            tokens = [t for t in _re.split(r"[\s\-/]+", clean_desc)
                      if len(t) >= 3 and t.isalpha()]
            for token in tokens[:6]:  # limit to avoid noise
                new_aliases.add(token.lower())

        if existing:
            # -- Add new aliases to existing company -------------------------
            existing_set = {a.alias for a in existing.aliases}
            added = 0
            for alias in new_aliases:
                if alias and alias not in existing_set:
                    try:
                        db.add(CompanyAlias(
                            company_id=existing.id,
                            alias=alias.lower().strip(),
                            priority=1,  # user-confirmed - higher priority
                        ))
                        db.flush()
                        added += 1
                    except Exception:
                        db.rollback()
            db.commit()
            return {
                "ok": True,
                "action": "aliases_added",
                "company": existing.name,
                "aliases_added": added,
            }

        else:
            # -- Create new pending company ----------------------------------
            company = Company(
                name=who,
                short_name=who[:80],
                category="Unknown",
                country="AU",
                approved=False,   # pending admin approval
            )
            db.add(company)
            db.flush()

            seen = set()
            for alias in new_aliases:
                alias = (alias or "").lower().strip()
                if alias and alias not in seen and len(alias) >= 2:
                    seen.add(alias)
                    try:
                        db.add(CompanyAlias(
                            company_id=company.id,
                            alias=alias,
                            priority=1,
                        ))
                        db.flush()
                    except Exception:
                        db.rollback()

            db.commit()
            return {
                "ok": True,
                "action": "company_created_pending",
                "company": who,
                "aliases_added": len(seen),
                "message": f"'{who}' added as pending - visit Company DB to approve",
            }

    except Exception as e:
        db.rollback()
        return {"ok": False, "reason": str(e)}
    finally:
        db.close()

def _row_match_key(row: dict) -> tuple:
    """
    Build a stable composite key identifying the same underlying bank
    transaction across re-classification runs. Used to carry forward a
    user's manual edits (GL Account, GST, Who, Classification, etc.) from
    an old session's saved output onto the freshly re-classified rows when
    re-running on top of that session with extra files added.
    """
    def _num(v):
        try:
            f = float(v)
            return round(f, 2)
        except (TypeError, ValueError):
            return 0.0
    return (
        str(row.get("Date", "")).strip(),
        str(row.get("Bank", "")).strip().lower(),
        str(row.get("Account", "")).strip().lower(),
        str(row.get("Description", "")).strip().lower(),
        _num(row.get("Debit", 0)),
        _num(row.get("Credit", 0)),
    )

_CARRY_FORWARD_COLS = ["GL Account", "GL Type", "GST Category", "GST", "Who", "Classification"]

def _apply_prior_session_edits(classified: pd.DataFrame, prior_results: Optional[pd.DataFrame]) -> pd.DataFrame:
    """
    Overlay manually-edited fields from a prior session's saved output onto
    the freshly re-classified DataFrame, matched by transaction content
    (date/bank/account/description/amounts) rather than row position - row
    order can differ once new files are merged in.

    Rows that don't match anything in the prior session (i.e. transactions
    from newly added files) are left exactly as the fresh classifier output.
    """
    if prior_results is None or prior_results.empty:
        return classified

    prior = prior_results.copy()
    # prior_results.pkl is stored with Title Case columns (same as `classified`)
    if "Date" not in prior.columns:
        return classified

    edit_lookup: dict = {}
    for rec in prior.to_dict(orient="records"):
        key = _row_match_key(rec)
        # If the same content key appears more than once in the prior
        # session (e.g. two identical-looking transactions), keep the
        # first - safer than guessing which manual edit belongs to which.
        if key not in edit_lookup:
            edit_lookup[key] = {c: rec.get(c) for c in _CARRY_FORWARD_COLS if c in rec}

    if not edit_lookup:
        return classified

    out = classified.copy()
    matched = 0
    for idx, row in out.iterrows():
        key = _row_match_key(row.to_dict())
        prev = edit_lookup.get(key)
        if not prev:
            continue
        for col, val in prev.items():
            if col in out.columns and val is not None and str(val).strip() != "":
                out.at[idx, col] = val
        matched += 1

    logger.info(f"[process-with-session] Carried forward manual edits for {matched}/{len(out)} rows from prior session")
    return out

_OB_FILE_PREFIX = "openbanking_"

def _merge_open_banking_frames(combined: "pd.DataFrame") -> "pd.DataFrame":
    """Merge Open Banking rows into the uploaded-CSV rows of the same account.

    A pulled period usually overlaps the uploaded statement, so a plain concat would
    count those transactions twice. For every (bank, account) that has an Open
    Banking file we keep, per (date, description, debit, credit), the *largest number
    of times it appears in any one source file* - overlap collapses, but two genuine
    identical transactions on one day inside a single statement both survive. The
    uploaded CSV is listed first, so its row (and its bank balance) wins.
    Accounts without an Open Banking file are left exactly as they were.
    """
    if "_src" not in combined.columns:
        return combined
    try:
        cols = {c.lower(): c for c in combined.columns}
        need = [cols.get(k) for k in ("bank", "account", "date", "description", "debit", "credit")]
        if not all(need):
            return combined.drop(columns=["_src"])
        bank_c, acc_c, date_c, desc_c, deb_c, cred_c = need
        is_ob = combined["_src"].astype(str).str.startswith(_OB_FILE_PREFIX)
        ob_accounts = set(zip(combined.loc[is_ob, bank_c], combined.loc[is_ob, acc_c]))
        if not ob_accounts:
            return combined.drop(columns=["_src"])
        df = combined.copy()
        in_ob = pd.Series([(b, a) in ob_accounts for b, a in zip(df[bank_c], df[acc_c])], index=df.index)
        key = pd.DataFrame({
            "_b": df[bank_c].astype(str), "_a": df[acc_c].astype(str), "_s": df["_src"].astype(str),
            "_d": df[date_c].astype(str),
            "_t": df[desc_c].astype(str).str.strip().str.lower(),
            "_db": pd.to_numeric(df[deb_c], errors="coerce").fillna(0).round(2),
            "_cr": pd.to_numeric(df[cred_c], errors="coerce").fillna(0).round(2),
        })
        key["_n"] = key.groupby(["_b", "_a", "_s", "_d", "_t", "_db", "_cr"]).cumcount()
        dup = key.duplicated(subset=["_b", "_a", "_d", "_t", "_db", "_cr", "_n"], keep="first")
        merged = df[~(in_ob & dup)].drop(columns=["_src"]).reset_index(drop=True)
        logger.info(f"[open-banking] merge removed {int((in_ob & dup).sum())} overlapping row(s)")
        return merged
    except Exception as e:  # never break a reconciliation run over the merge
        logger.warning(f"[open-banking] merge skipped: {e}")
        return combined.drop(columns=["_src"], errors="ignore")

@router.post("/reconcile/process-with-session")
async def reconcile_process_with_session(
    files: Optional[List[UploadFile]] = File(default=None),
    bank_names:      Optional[List[str]] = Form(default=None),
    account_numbers: Optional[List[str]] = Form(default=None),
    account_names:   Optional[List[str]] = Form(default=None),
    session_id: str  = Form(...),
    username:   str  = Form(...),
):
    """
    Re-run reconciliation using:
      - All CSV files saved from a previous session
      - Plus any NEW files uploaded in this request

    Creates a NEW session with all combined data.
    """
    import json as _json
    import traceback as _traceback

    try:
        return await _reconcile_process_with_session_impl(
            files, bank_names, account_numbers, account_names, session_id, username, _json)
    except HTTPException:
        raise
    except Exception as e:
        # Any unexpected error here is logged with a full traceback and
        # returned as a clean HTTP 500 instead of propagating up - this
        # keeps the uvicorn worker alive even if something unforeseen goes
        # wrong (e.g. a transient file lock or DB hiccup on Windows).
        logger.error(f"[process-with-session] Unhandled error: {e}\n{_traceback.format_exc()}")
        raise HTTPException(500, f"Failed to re-process session: {e}")

async def _reconcile_process_with_session_impl(
    files, bank_names, account_numbers, account_names, session_id, username, _json,
):
    # -- Load saved files from previous session --------------------------------
    prev_sid = session_id
    prev_data = session_manager.load_session_data(norm_username(username), prev_sid)
    if prev_data is None:
        raise HTTPException(
            404,
            f"Session '{prev_sid}' was not found - it may have been deleted, "
            f"or the session folder is temporarily inaccessible. Try running "
            f"a fresh reconciliation instead of re-using this session.",
        )
    saved_files = prev_data.get("files_data", {})          # filename - bytes
    prev_accounts = prev_data.get("accounts", [])           # accounts_meta from prev session

    normed = []
    _acc_files: dict = {}
    _all_saved: dict = {}

    # Process previously saved files
    for acc in prev_accounts:
        bank    = acc.get("bank_name", "Unknown")
        account = acc.get("account_number", "Unknown")
        acc_name = acc.get("account_name", "")
        for fname in (acc.get("files") or []):
            raw = saved_files.get(fname)
            if not raw:
                # Try to find by filename without path
                raw = next((v for k, v in saved_files.items()
                            if k.endswith(fname) or fname.endswith(k)), None)
            if not raw:
                logger.warning(f"Saved file {fname} not found in session {prev_sid}")
                continue
            _acc_files.setdefault((bank, account), []).append((fname, acc_name))
            _all_saved[fname] = raw
            try:
                df = pd.read_csv(io.BytesIO(raw))
                normalized = normalize_transactions(df, bank, account)
                if acc_name:
                    normalized["account_name"] = acc_name
                normalized["_src"] = fname
                normed.append(normalized)
            except Exception as e:
                logger.warning(f"Failed to process saved file {fname}: {e}")

    # Process newly uploaded files
    for i, upload in enumerate(files or []):
        bank    = (bank_names or [])[i]      if bank_names    and i < len(bank_names)      else "Unknown"
        account = (account_numbers or [])[i] if account_numbers and i < len(account_numbers) else "Unknown"
        acc_name = (account_names or [])[i]  if account_names and i < len(account_names)   else ""
        fname   = upload.filename or f"new_file_{i}.csv"
        _acc_files.setdefault((bank, account), []).append((fname, acc_name))
        try:
            raw = await upload.read()
            _all_saved[fname] = raw
            df = pd.read_csv(io.BytesIO(raw))
            normalized = normalize_transactions(df, bank, account)
            if acc_name:
                normalized["account_name"] = acc_name
            normalized["_src"] = fname
            normed.append(normalized)
        except Exception as e:
            logger.warning(f"Failed to process new file {fname}: {e}")

    if not normed:
        raise HTTPException(400, "No valid files found - check session files and new uploads")

    # -- Classify --------------------------------------------------------------
    combined = _merge_open_banking_frames(pd.concat(normed, ignore_index=True))
    combined.columns = combined.columns.str.strip().str.lower()
    if "account_name" not in combined.columns:
        combined["account_name"] = ""

    _home_company = ""
    try:
        from accfino.shared.db.database import SessionLocal as _SL
        from accfino.core.identity.user import User as _User
        _db2 = _SL()
        _uname = norm_username(username)
        _usr = _db2.query(_User).filter(_User.username == _uname).first()
        if _usr and _usr.home_company:
            _home_company = _usr.home_company
        _db2.close()
    except Exception:
        pass

    classified = rec_classifier.classify_transactions(
        combined, show_progress=False, home_company=_home_company)
    classified = _norm_cols(classified)
    if "Account Name" not in classified.columns:
        classified["Account Name"] = combined.get("account_name", "").values[:len(classified)]
    for col, default in [("GL Account",""),("GL Type",""),("GST Category",""),
                         ("GST",0.0),("Who",""),("PairID","")]:
        if col not in classified.columns:
            classified[col] = default
    classified = _run_classify_gl(classified, username=username)

    # -- Carry forward manual edits made in the prior session ------------------
    # Without this, every re-run from a previous session (e.g. adding new
    # bank files on top of an already-reviewed session) would silently
    # discard every manual GL/GST/Who/Classification correction the user
    # made, since classification always runs fresh on the raw input files.
    prior_results_df = prev_data.get("results") if isinstance(prev_data, dict) else None
    classified = _apply_prior_session_edits(classified, prior_results_df)

    monthly = _build_monthly_summary(classified)

    # -- Create new session ----------------------------------------------------
    uname = norm_username(username)
    sid   = session_manager.create_session(uname)
    session_manager.save_output_data(uname, sid, classified, {}, set(), 1)

    accounts_meta = [
        {
            "bank_name":      bank,
            "account_number": account,
            "account_name":   tuples[0][1] if tuples else "",
            "files":          [t[0] for t in tuples],
        }
        for (bank, account), tuples in _acc_files.items()
    ]
    try:
        session_manager.save_input_meta_and_files(uname, sid, accounts_meta, _all_saved)
    except Exception as _e:
        logger.warning(f"Failed to save session input for {sid}: {_e}")

    return {
        "session_id":     sid,
        "transactions":   _to_frontend(classified),
        "monthly_summary": monthly,
        "count":          len(classified),
        "accounts_meta":  accounts_meta,
    }

_cf_cache: dict = {}

def normalize_gst_category(value) -> str:
    text = "" if pd.isna(value) else str(value).strip()
    if not text: return ""
    for option in GST_CATEGORY_OPTIONS:
        if option.lower() == text.lower(): return option
    return text  # pass through unknown values rather than blanking them

def normalize_gl_account(value) -> str:
    """Validate against COA *Name values - not *Type/CATEGORY_ENUM."""
    text = "" if pd.isna(value) else str(value).strip()
    if not text: return ""
    tl = text.lower()
    for name in _COA_NAMES:
        if name.lower() == tl: return name
    return ""

def _clean(df: pd.DataFrame) -> list:
    out = []
    for row in df.to_dict(orient="records"):
        c = {}
        for k, v in row.items():
            if isinstance(v, float) and pd.isna(v):          c[k] = None
            elif hasattr(v, "item"):                          c[k] = v.item()
            elif isinstance(v, (datetime, pd.Timestamp)):     c[k] = str(v)
            else:                                             c[k] = v
        out.append(c)
    return out

def _norm_cols(df: pd.DataFrame) -> pd.DataFrame:
    """Rename classifier output columns to Title Case matching original Streamlit app."""
    return df.rename(columns={
        "date":         "Date",
        "bank":         "Bank",
        "account_name": "Account Name",
        "account":      "Account",
        "description":  "Description",
        "debit":        "Debit",
        "credit":       "Credit",
        "classification": "Classification",
        "pairid":       "PairID",
        "GL Account":   "GL Account",   # already correct
        "GL Type":      "GL Type",
        "GST":          "GST",
        "GST Category": "GST Category",
        "Who":          "Who",
        "Month":        "Month",
        "Year":         "Year",
        # snake_case variants
        "gl_account":   "GL Account",
        "gl_type":      "GL Type",
        "gst":          "GST",
        "gst_category": "GST Category",
        "who":          "Who",
        "month":        "Month",
        "year":         "Year",
        "balance":      "Balance",    # bank-supplied running balance from CSV
    })

def _to_frontend(df: pd.DataFrame) -> list:
    """Convert df to frontend-friendly records using lowercase keys."""
    df2 = df.copy()
    df2 = df2.rename(columns={
        "Date": "date", "Bank": "bank", "Account Name": "account_name",
        "Account": "account", "Description": "description",
        "Debit": "debit", "Credit": "credit",
        "Balance": "balance",
        "Classification": "classification", "PairID": "pairid",
        "GL Account": "gl_account", "GL Type": "gl_type", "GST": "gst",
        "GST Category": "gst_category", "Who": "who",
        "Month": "month", "Year": "year",
    })
    # Ensure new columns always present with safe defaults
    for col, default in [
        ("balance",                None),
        ("currency",               "AUD"),
        ("exchange_rate",          1.0),
        ("amount_original_debit",  None),
        ("amount_original_credit", None),
        ("is_loan_payment",        False),
        ("loan_principal",         None),
        ("loan_interest",          None),
        ("loan_interest_rate",     None),
        ("loan_principal_gl",      None),
        ("loan_interest_gl",       None),
    ]:
        if col not in df2.columns:
            df2[col] = default
    return _clean(df2)

def _build_monthly_summary(df: pd.DataFrame, username: str = "",
                            account_balances: dict | None = None) -> list:
    """
    Build monthly summary with opening balance, closing balance, and net movement.

    account_balances: dict keyed (bank, account, year, month) -> float
      Injected from the DB AccountBalance table so the summary always shows
      the correct opening balance even when viewing a partial month.
    """
    if "Date" not in df.columns or df["Date"].isna().all():
        return []

    df = df.copy()
    df["Date_dt"] = pd.to_datetime(df["Date"], errors="coerce", dayfirst=True)
    df["Month"]   = df["Date_dt"].dt.month
    df["Year"]    = df["Date_dt"].dt.year
    df["Date"]    = df["Date_dt"].dt.strftime("%d/%m/%Y")

    if "GST" not in df.columns:
        df["GST"] = 0.0

    # ── Derive opening/closing balance from bank_balance column ─────────────
    # bank_balance is the running balance after each transaction from the CSV.
    # Opening balance of month M  = bank_balance of the row BEFORE the first
    #   transaction of month M   = bank_balance of last row in month M-1.
    # Closing balance of month M  = bank_balance of last row in month M.
    _has_bank_bal = "Balance" in df.columns and df["Balance"].notna().any()

    # Build per-(bank,account,year,month) opening/closing from CSV balance column
    _csv_balances: dict[tuple, dict] = {}
    if _has_bank_bal:
        _has_ba = "Bank" in df.columns and "Account" in df.columns
        df["_row_order"] = range(len(df))
        for keys, grp in df.groupby(
            ["Bank", "Account", "Year", "Month"] if _has_ba else ["Year", "Month"]
        ):
            if _has_ba: bank, acct, year, month = keys
            else: bank, acct = "", ""; year, month = keys
            # Sort oldest-first: date asc, row_order desc (higher idx = older in newest-first CSVs)
            grp_all = grp.sort_values(["Date_dt", "_row_order"], ascending=[True, False])
            if grp_all.empty: continue
            # Forward-simulate closing from last known balance (handles trailing balance-less rows)
            last_pos = grp_all["Balance"].last_valid_index()
            if last_pos is None: continue
            sim = float(grp_all.loc[last_pos, "Balance"])
            iloc_pos = grp_all.index.get_loc(last_pos)
            for _ri in grp_all.index[iloc_pos + 1:]:
                sim += float(grp_all.loc[_ri, "Credit"] or 0) - float(grp_all.loc[_ri, "Debit"] or 0)
            closing = round(float(sim), 4)
            # Opening = closing - net of ALL rows (not just balance-having rows)
            net_all = float(
                (grp_all["Credit"].fillna(0).sum() if "Credit" in grp_all.columns else 0)
                - (grp_all["Debit"].fillna(0).sum()  if "Debit"  in grp_all.columns else 0)
            )
            opening = round(float(closing - net_all), 4)
            key = (bank, acct, int(year), int(month)) if _has_ba else (int(year), int(month))
            _csv_balances[key] = {"opening": opening, "closing": closing}
        df.drop(columns=["_row_order"], inplace=True, errors="ignore")

    def _get_opening(bank, acct, year, month):
        """Opening balance: DB record > CSV-derived > None"""
        db_key = (bank, acct, int(year), int(month))
        if account_balances and db_key in account_balances:
            return account_balances[db_key], "db"
        csv_key = (bank, acct, int(year), int(month)) if "Bank" in df.columns else (int(year), int(month))
        if csv_key in _csv_balances:
            return _csv_balances[csv_key]["opening"], "csv"
        return None, None

    def _get_closing(bank, acct, year, month):
        """Closing balance: DB next-month opening > CSV-derived > None"""
        # Try CSV first
        csv_key = (bank, acct, int(year), int(month)) if "Bank" in df.columns else (int(year), int(month))
        if csv_key in _csv_balances:
            return _csv_balances[csv_key]["closing"], "csv"
        return None, None

    def _make_row(label, src, row_type="month"):
        return {
            "Year/Month":               label,
            "_row_type":                row_type,
            "🟢Internal Transfers":     sum(r["🟢Internal Transfers"] for r in src),
            "🔵Incoming Count":         sum(r["🔵Incoming Count"]     for r in src),
            "🟡Outgoing Count":         sum(r["🟡Outgoing Count"]     for r in src),
            "Total 🔵Incoming Income":  round(sum(r["Total 🔵Incoming Income"]  for r in src), 2),
            "Total 🟡Outgoing Expense": round(sum(r["Total 🟡Outgoing Expense"] for r in src), 2),
            "Total 🔵Incoming GST":     round(sum(r["Total 🔵Incoming GST"]     for r in src), 2),
            "Total 🟡Outgoing GST":     round(sum(r["Total 🟡Outgoing GST"]     for r in src), 2),
            "opening_balance":          None,
            "closing_balance":          None,
            "balance_source":           None,
        }

    months_by_year = {}
    group_cols = ["Bank", "Account", "Year", "Month"] if ("Bank" in df.columns and "Account" in df.columns) else ["Year", "Month"]
    for group_keys, group in df.groupby(group_cols):
        if len(group_cols) == 4:
            bank, acct, year, month = group_keys
        else:
            bank, acct = "", ""
            year, month = group_keys

        _cls = group["Classification"].fillna("") if "Classification" in group.columns else pd.Series([""] * len(group))
        internal_count = _cls.str.contains("Internal", na=False).sum()
        incoming_count = _cls.str.contains("Incoming", na=False).sum()
        outgoing_count = _cls.str.contains("Outgoing", na=False).sum()
        _in_m  = _cls.str.contains("Incoming", na=False)
        _out_m = _cls.str.contains("Outgoing", na=False)
        total_income  = group.loc[_in_m,  "Credit"].sum() if "Credit" in group.columns else 0
        total_expense = group.loc[_out_m, "Debit"].sum()  if "Debit"  in group.columns else 0
        gst_in        = group.loc[_in_m,  "GST"].sum()    if "GST"    in group.columns else 0
        gst_out       = group.loc[_out_m, "GST"].sum()    if "GST"    in group.columns else 0

        opening, ob_src = _get_opening(bank, acct, year, month)
        closing, cb_src = _get_closing(bank, acct, year, month)

        # Derive missing balance using ALL transactions (internal transfers affect balance!)
        _all_cr  = group["Credit"].fillna(0).sum() if "Credit" in group.columns else 0
        _all_db  = group["Debit"].fillna(0).sum()  if "Debit"  in group.columns else 0
        _net_all = float(_all_cr) - float(_all_db)
        if opening is None and closing is not None:
            opening = round(float(closing) - _net_all, 4); ob_src = "derived"
        elif closing is None and opening is not None:
            closing = round(float(opening) + _net_all, 4); cb_src = "derived"

        ym_label = f"{int(year)}/{int(month):02d}"
        _acct_name = ""
        if "Account Name" in group.columns:
            _first = group["Account Name"].dropna()
            _acct_name = str(_first.iloc[0]) if not _first.empty else ""
        row = {
            "Year/Month":               ym_label,
            "_row_type":                "month",
            "_bank":                    bank,
            "_account":                 acct,
            "_account_name":            _acct_name,
            "🟢Internal Transfers":     int(internal_count),
            "🔵Incoming Count":         int(incoming_count),
            "🟡Outgoing Count":         int(outgoing_count),
            "Total 🔵Incoming Income":  round(float(total_income),  2),
            "Total 🟡Outgoing Expense": round(float(total_expense), 2),
            "Total 🔵Incoming GST":     round(float(gst_in),  2),
            "Total 🟡Outgoing GST":     round(float(gst_out), 2),
            "opening_balance":          opening,
            "closing_balance":          closing,
            "balance_source":           ob_src or cb_src,
        }
        months_by_year.setdefault(int(year), []).append(row)

    # ── Propagate closing→next-month opening ────────────────────────────────
    # Sort all months chronologically and fill gaps
    all_months_flat = []
    for year in sorted(months_by_year):
        all_months_flat.extend(sorted(months_by_year[year], key=lambda r: int(r["Year/Month"].split("/")[1])))

    for i in range(len(all_months_flat) - 1):
        cur  = all_months_flat[i]
        nxt  = all_months_flat[i + 1]
        if cur["closing_balance"] is not None and nxt["opening_balance"] is None:
            nxt["opening_balance"] = cur["closing_balance"]
            nxt["balance_source"]  = "derived"
        if nxt["opening_balance"] is not None and cur["closing_balance"] is None:
            cur["closing_balance"] = nxt["opening_balance"]  # closing[M] == opening[M+1]
            cur["balance_source"]  = "derived"

    result, all_rows = [], []
    for year in sorted(months_by_year):
        yr_rows = months_by_year[year]
        result.extend(yr_rows)
        all_rows.extend(yr_rows)
        if len(months_by_year) > 1:
            totals_row = _make_row(f"{year} Total", yr_rows, "year_total")
            result.append(totals_row)

    if all_rows:
        result.append(_make_row("Grand Total", all_rows, "grand_total"))

    return result

class AccountBalanceIn(BaseModel):
    user_id: int
    bank:    str
    account: str
    year:    int
    month:   int
    balance: float
    is_manual: bool = True

class AccountBalanceOut(BaseModel):
    id:        int
    bank:      str
    account:   str
    year:      int
    month:     int
    balance:   float
    is_manual: bool
    source:    str

@router.get("/account-balances/{user_id}")
def get_account_balances(user_id: int):
    """Return all stored opening balances for a user as a dict keyed 'bank|account|year|month'."""
    try:
        from accfino.shared.db.database import SessionLocal as _SL
        from accfino.modules.reconciliation.models.account_balance import AccountBalance as _AB
        db = _SL()
        try:
            rows = db.query(_AB).filter(_AB.user_id == user_id).all()
            return {
                f"{r.bank}|{r.account}|{r.year}|{r.month}": {
                    "id": r.id, "bank": r.bank, "account": r.account,
                    "year": r.year, "month": r.month,
                    "balance": r.balance, "is_manual": r.is_manual, "source": r.source,
                }
                for r in rows
            }
        finally:
            db.close()
    except Exception as e:
        raise HTTPException(500, f"Error: {e}")

@router.post("/account-balances")
def upsert_account_balance(body: AccountBalanceIn):
    """Create or update an opening balance record."""
    try:
        from accfino.shared.db.database import SessionLocal as _SL
        from accfino.modules.reconciliation.models.account_balance import AccountBalance as _AB
        from accfino.core.identity.user import User as _U
        db = _SL()
        try:
            if not db.query(_U).filter(_U.id == body.user_id).first():
                raise HTTPException(404, "User not found")
            existing = db.query(_AB).filter(
                _AB.user_id == body.user_id,
                _AB.bank    == body.bank,
                _AB.account == body.account,
                _AB.year    == body.year,
                _AB.month   == body.month,
            ).first()
            if existing:
                existing.balance   = body.balance
                existing.is_manual = body.is_manual
                existing.source    = "manual" if body.is_manual else "csv"
            else:
                db.add(_AB(
                    user_id   = body.user_id,
                    bank      = body.bank,
                    account   = body.account,
                    year      = body.year,
                    month     = body.month,
                    balance   = body.balance,
                    is_manual = body.is_manual,
                    source    = "manual" if body.is_manual else "csv",
                ))
            db.commit()
            return {"ok": True}
        finally:
            db.close()
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(500, f"Error: {e}")

@router.post("/account-balances/bulk")
def bulk_upsert_account_balances(body: dict):
    """
    Bulk-upsert opening balances derived from CSV bank_balance column.
    Called after processing when we have reliable CSV balance data.
    body: { user_id, entries: [{bank, account, year, month, balance, source}] }
    """
    try:
        from accfino.shared.db.database import SessionLocal as _SL
        from accfino.modules.reconciliation.models.account_balance import AccountBalance as _AB
        db = _SL()
        try:
            uid     = body.get("user_id")
            entries = body.get("entries", [])
            saved   = 0
            for e in entries:
                existing = db.query(_AB).filter(
                    _AB.user_id == uid,
                    _AB.bank    == e["bank"],
                    _AB.account == e["account"],
                    _AB.year    == e["year"],
                    _AB.month   == e["month"],
                ).first()
                is_manual = e.get("source") == "manual"
                if existing:
                    # Never overwrite a manual entry with a CSV-derived one
                    if existing.is_manual and not is_manual:
                        continue
                    existing.balance   = e["balance"]
                    existing.is_manual = is_manual
                    existing.source    = e.get("source", "csv")
                else:
                    db.add(_AB(
                        user_id=uid, bank=e["bank"], account=e["account"],
                        year=e["year"], month=e["month"],
                        balance=e["balance"], is_manual=is_manual,
                        source=e.get("source", "csv"),
                    ))
                saved += 1
            db.commit()
            return {"ok": True, "saved": saved}
        finally:
            db.close()
    except Exception as e:
        raise HTTPException(500, f"Error: {e}")

@router.get("/banks")
def get_banks(): return sorted(BANK_PRESETS.keys())

@router.get("/gst/categories")
def get_gst_cats(): return GST_CATEGORY_OPTIONS

@router.get("/gl/accounts")
def get_gl_accounts(): return _COA_NAMES + [""]

@router.post("/gl/accounts/upload")
async def upload_gl_accounts(file: UploadFile = File(...)):
    """Save uploaded ChartOfAccounts.csv to disk and rebuild classifier index.
    Uses temp-file + replace to avoid locking errors on Windows."""
    # Retired: the organisation's ledger chart of accounts is the single source of truth.
    # Overwriting the classifier list from a CSV would silently diverge from the ledger.
    raise HTTPException(410, "The chart of accounts is now managed in Settings -> Chart of Accounts "
                             "(Import CSV is available there).")
    import shutil, tempfile
    from accfino.modules.reconciliation.classification.engine import rebuild as _engine_rebuild, evict as _engine_evict, warm as _engine_warm_path
    content = await file.read()

    coa_path = _DEFAULT_COA_PATH          # target path
    tmp_path  = coa_path.parent / ("ChartOfAccounts.tmp")
    alt_path  = coa_path.parent / "ChartOfAccounts_updated.csv"

    # Step 1: write to temp file
    try:
        tmp_path.write_bytes(content)
    except Exception as e:
        raise HTTPException(500, f"COA write failed: {e}")

    # Step 2: atomic replace - may fail on Windows if file is open in Excel
    saved_path = coa_path
    try:
        if coa_path.exists():
            coa_path.unlink()
        shutil.move(str(tmp_path), str(coa_path))
    except PermissionError:
        # File locked - save to alternate and use that for this session
        shutil.move(str(tmp_path), str(alt_path))
        saved_path = alt_path
        logger.warning("ChartOfAccounts.csv locked - saved to ChartOfAccounts_updated.csv")
    finally:
        if tmp_path.exists():
            try: tmp_path.unlink()
            except: pass

    # Step 3: push into Postgres (authoritative store) then re-sync the
    # canonical CSV from it, so the file the engine reads always matches
    # the DB exactly. Skipped in the rare Windows-file-locked fallback
    # case (saved_path != coa_path) -- that degraded path is left exactly
    # as before, since regenerating the canonical file there would
    # overwrite a different, currently-inaccessible file.
    if saved_path == coa_path:
        try:
            import csv as _csv_mod
            from accfino.shared.db.database import SessionLocal as _SL_coa
            from accfino.modules.reconciliation.models.reference import ChartOfAccount as _COA
            from accfino.modules.reconciliation.services.db_sync import sync_coa_csv_from_db as _sync_coa

            db = _SL_coa()
            try:
                db.query(_COA).delete()
                with open(saved_path, newline="", encoding="utf-8-sig") as f:
                    for row in _csv_mod.DictReader(f):
                        name = (row.get("*Name") or row.get("Name") or "").strip()
                        atype = (row.get("*Type") or row.get("Type") or "").strip()
                        if name:
                            db.add(_COA(name=name, type=atype))
                db.commit()
            finally:
                db.close()
            _sync_coa()  # regenerate the canonical CSV from the DB, now the source of truth
        except Exception as _e:
            logger.warning(f"COA Postgres sync skipped: {_e}")

    # Step 4: rebuild engine index from saved file
    _engine_evict()
    _engine_warm_path(coa_path=saved_path)

    # Step 5: reload name/type map
    global _COA_NAMES, _COA_NAME_TO_TYPE, _ACTIVE_COA_PATH
    _COA_NAMES, _COA_NAME_TO_TYPE = _load_coa_names(saved_path)
    _ACTIVE_COA_PATH = saved_path

    msg = f"COA saved and index rebuilt ({len(_COA_NAMES)} accounts)"
    if saved_path != coa_path:
        msg += " - NOTE: original file was locked (close Excel). Saved as ChartOfAccounts_updated.csv. Restart app to make permanent."
    return {"ok": True, "message": msg}

@router.get("/gl/accounts/all")
def get_gl_accounts_all():
    """Return full COA rows with all columns for the GL Accounts modal and coaMap."""
    import csv
    from accfino.modules.reconciliation.classification.engine import DEFAULT_COA_PATH
    rows = []
    try:
        _read_path = _ACTIVE_COA_PATH or DEFAULT_COA_PATH
        with open(_read_path, newline="", encoding="utf-8-sig") as f:
            for r in csv.DictReader(f):
                name = (r.get("*Name") or r.get("Name") or "").strip()
                if name:
                    rows.append({
                        # Keys the modal uses for its table columns
                        "Code":        (r.get("*Code")        or r.get("Code")        or "").strip(),
                        "Name":        name,
                        "Type":        (r.get("*Type")        or r.get("Type")        or "").strip(),
                        "TaxCode":     (r.get("*Tax Code")    or r.get("Tax Code")    or "").strip(),
                        "Description": (r.get("Description")  or "").strip(),
                        "Dashboard":   (r.get("Dashboard")    or "").strip(),
                        # Also snake_case for coaMap usage
                        "name":        name,
                        "type":        (r.get("*Type")        or r.get("Type")        or "").strip(),
                        "tax_code":    (r.get("*Tax Code")    or r.get("Tax Code")    or "").strip(),
                    })
    except Exception as e:
        logger.warning(f"COA read failed: {e}")
    return rows

@router.get("/gst/calculate")
def calc_gst(debit: float=0, credit: float=0, category: str="Unknown"):
    return {"gst": calculate_gst_value(debit, credit, category)}

_DATA_DIR = _paths.data_root() / "modules" / "reconciliation" / "sessions"      # legacy per-user session folders (sessions now live in the database)

def norm_username(username: str) -> str:
    """Return the folder name that matches this username.

    Handles the case where old sessions were saved under the full username
    string (e.g. 'p' from 'p@ex.com') or under a different casing.
    Falls back to stripping the email domain for new sessions.
    """
    raw = (username or "default_user").strip()
    if not raw:
        return "default_user"

    # 1. Exact match - folder already exists under this exact string
    if (_DATA_DIR / raw).is_dir():
        return raw

    # 2. Email - strip domain and check
    if "@" in raw:
        local = raw.split("@")[0].strip()
        if local and (_DATA_DIR / local).is_dir():
            return local
        # 3. No existing folder yet - use local part for new sessions
        return local or "default_user"

    return raw

class SaveSessReq(BaseModel):
    session_id: str; username: str; transactions: list
    pending_changes: dict = {}; page_number: int = 1

_KB_PATH = _paths.reference_file("knowledge_base.json")

_KB_RETURN_PREFIXES:    tuple = ("return ", "refund", "reversal", "credit adj", "chargeback",
                                  "credit note", "reimburs", "rebate", "cashback", "correction",
                                  "reversal of", "reversed ", "cancelled ", "cancellation",
                                  "fee waived", "fee reversal", "duplicate charge")

_KB_INTERNAL_KEYWORDS: list  = ["internal transfer", "funds transfer", "fund transfer",
                                  "own account transfer", "inter account", "account transfer",
                                  "interbank transfer", "tfr", "trf"]

def _reload_kb_prefixes():
    """Call once at startup and after KB edits to refresh the cached prefix lists."""
    global _KB_RETURN_PREFIXES, _KB_INTERNAL_KEYWORDS
    try:
        _kb = json.loads(_KB_PATH.read_text(encoding="utf-8"))
        _KB_RETURN_PREFIXES    = tuple(_kb.get("return_prefixes",   list(_KB_RETURN_PREFIXES)))
        _KB_INTERNAL_KEYWORDS  = _kb.get("internal_keywords", _KB_INTERNAL_KEYWORDS)
    except Exception:
        pass   # keep existing defaults

_reload_kb_prefixes()

def _load_kb():
    try:
        return json.loads(_KB_PATH.read_text(encoding="utf-8"))
    except Exception:
        return {}

def _save_kb(kb: dict):
    _KB_PATH.write_text(json.dumps(kb, indent=2, ensure_ascii=False), encoding="utf-8")
    _reload_kb_prefixes()   # keep module-level prefix cache in sync

@router.get("/kb")
def kb_get():
    """Return full knowledge base."""
    return _load_kb()

@router.put("/kb/vendor/{vendor_key}")
def kb_vendor_upsert(vendor_key: str, body: dict):
    """Add or update a vendor entry."""
    kb = _load_kb()
    kb.setdefault("vendor_map", {})[vendor_key.lower()] = body
    _save_kb(kb)
    return {"ok": True, "vendor": vendor_key, "entry": body}

@router.delete("/kb/vendor/{vendor_key}")
def kb_vendor_delete(vendor_key: str):
    """Remove a vendor entry."""
    kb = _load_kb()
    kb.get("vendor_map", {}).pop(vendor_key.lower(), None)
    _save_kb(kb)
    return {"ok": True}

@router.put("/kb/keyword/{keyword}")
def kb_keyword_upsert(keyword: str, body: dict):
    """Add or update a keyword entry."""
    kb = _load_kb()
    kb.setdefault("keyword_map", {})[keyword.lower()] = body
    _save_kb(kb)
    return {"ok": True, "keyword": keyword, "entry": body}

@router.delete("/kb/keyword/{keyword}")
def kb_keyword_delete(keyword: str):
    """Remove a keyword entry."""
    kb = _load_kb()
    kb.get("keyword_map", {}).pop(keyword.lower(), None)
    _save_kb(kb)
    return {"ok": True}

@router.put("/kb/meta")
def kb_meta_update(body: dict):
    """Update internal_keywords or return_prefixes lists."""
    kb = _load_kb()
    if "internal_keywords" in body:
        kb["internal_keywords"] = body["internal_keywords"]
    if "return_prefixes" in body:
        kb["return_prefixes"] = body["return_prefixes"]
    _save_kb(kb)
    return {"ok": True}

@router.get("/sessions")
def list_sessions(username: str):
    username = norm_username(username)
    ss = session_manager.get_all_sessions(username)
    for s in ss:
        if "datetime" in s and hasattr(s["datetime"], "isoformat"):
            s["datetime"] = s["datetime"].isoformat()
        # accounts_meta/file counts now come straight from the DB row and
        # its session_files relationship -- always in sync by construction,
        # so there's no repair/backfill step needed anymore (the old
        # version re-derived this from accounts.json + a directory scan
        # specifically to work around cases where the two could drift).
        try:
            summary = session_manager.get_session_summary(username, s["session_id"])
            s["accounts_meta"] = summary["accounts_meta"]
            s["account_count"] = summary["account_count"]
            s["file_count"] = summary["file_count"]
        except Exception:
            s["accounts_meta"] = []; s["account_count"] = 0; s["file_count"] = 0
    return ss

@router.delete("/sessions/{username}/{sid}")
def del_session(username: str, sid: str):
    return {"ok": session_manager.delete_session(norm_username(username), sid)}

@router.get("/sessions/{username}/{sid}")
def get_session(username: str, sid: str):
    username = norm_username(username)
    d = session_manager.load_session_data(username, sid)
    if not d: raise HTTPException(404, "Session not found")

    txns = []
    monthly = []
    if d.get("results") is not None and not d["results"].empty:
        df = _norm_cols(d["results"].copy())
        # Ensure all required columns exist
        for col, default in [("GL Account",""),("GL Type",""),("GST Category",""),("GST",0.0),("Who",""),("PairID","")]:
            if col not in df.columns: df[col] = default

        # ── Fix stale Internal classifications from old sessions ──────────────
        # Old sessions may have saved transactions as Internal that were not
        # actually transfers to/from the user's own company.
        # Re-evaluate: if a row is marked Internal but has no PairID (not a
        # pair-matched transfer) and is not to/from home company — restore it
        # to Incoming/Outgoing based on debit/credit direction.
        if "Classification" in df.columns and "Debit" in df.columns and "Credit" in df.columns:
            _home_co_check = ""
            try:
                from accfino.shared.db.database import SessionLocal as _SL_r
                from accfino.core.identity.user import User as _UUser_r
                _db_r = _SL_r()
                _ur = _db_r.query(_UUser_r).filter(
                    _UUser_r.username == norm_username(username)
                ).first()
                if _ur and _ur.home_company:
                    _home_co_check = _ur.home_company.strip().lower()
                _db_r.close()
            except Exception:
                pass

            for _ri in df.index:
                _cl = str(df.at[_ri, "Classification"])
                if "Internal" not in _cl:
                    continue
                _pid = str(df.at[_ri, "PairID"] if "PairID" in df.columns else "")
                # Keep Internal if it has a pair ID (genuine matched transfer)
                if _pid and _pid not in ("", "nan", "None"):
                    continue
                # Keep Internal if description/who contains home company name
                _desc_r = str(df.at[_ri, "Description"] if "Description" in df.columns else "").lower()
                _who_r  = str(df.at[_ri, "Who"] if "Who" in df.columns else "").lower()
                if _home_co_check and (
                    _home_co_check in _desc_r or
                    _home_co_check in _who_r or
                    (_home_co_check.split()[0] if _home_co_check.split() else "") in _desc_r
                ):
                    continue
                # Not a genuine internal — restore based on direction
                _deb = float(df.at[_ri, "Debit"]  or 0)
                _crd = float(df.at[_ri, "Credit"] or 0)
                if _deb > 0:
                    df.at[_ri, "Classification"] = "🟡Outgoing"
                elif _crd > 0:
                    df.at[_ri, "Classification"] = "🔵Incoming"

        # Clear GL/GST for remaining genuine Internal rows
        if "Classification" in df.columns:
            _int_mask = df["Classification"].str.contains("Internal", na=False)
            df.loc[_int_mask, ["GL Account","GL Type","GST Category"]] = ""
            df.loc[_int_mask, "GST"] = 0.0

        # Load saved account balances for this user
        _ses_ab: dict = {}
        try:
            from accfino.shared.db.database import SessionLocal as _SL_ab
            from accfino.core.identity.user import User as _U_ab
            from accfino.modules.reconciliation.models.account_balance import AccountBalance as _AB_ses
            _db_ab = _SL_ab()
            try:
                _u_ab = _db_ab.query(_U_ab).filter(_U_ab.username == norm_username(d.get("username",""))).first()
                if not _u_ab:
                    # Try from session username field
                    _u_ab = _db_ab.query(_U_ab).filter(_U_ab.username == norm_username(username if 'username' in dir() else "")).first()
                if _u_ab:
                    for _ab in _db_ab.query(_AB_ses).filter(_AB_ses.user_id == _u_ab.id).all():
                        _ses_ab[(_ab.bank, _ab.account, _ab.year, _ab.month)] = _ab.balance
            finally:
                _db_ab.close()
        except Exception:
            pass

        monthly = _build_monthly_summary(df, account_balances=_ses_ab if _ses_ab else None)
        txns = _to_frontend(df)
    # accounts from load_session_data is the accounts.json list
    accounts_meta = d.get("accounts") or []
    return {
        "session_id": sid,
        "transactions": txns,
        "monthly_summary": monthly,
        "accounts_meta": accounts_meta,   # [{bank_name, account_number, files:[str]}]
        "account_count": len(accounts_meta),
        "file_count": sum(len(a.get("files",[])) for a in accounts_meta),
        "page_number": d.get("page_number", 1),
        "pending_changes": {str(k): v for k, v in d.get("pending_changes", {}).items()},
    }

@router.post("/sessions/save")
def save_session(body: SaveSessReq):
    username = norm_username(body.username)
    df = pd.DataFrame(body.transactions) if body.transactions else pd.DataFrame()
    if not df.empty:
        df = _norm_cols(df)
    session_manager.save_output_data(username, body.session_id, df,
        {int(k): v for k, v in body.pending_changes.items()},
        set(), body.page_number)
    return {"ok": True}

@router.post("/reconcile/process")
async def reconcile_process(
    files: List[UploadFile]=File(...),
    bank_names: List[str]=Form(...),
    account_numbers: List[str]=Form(...),
    account_names:   Optional[List[str]]=Form(default=None),
    username: str=Form(...),
    currency: str=Form(default="AUD"),
):
  import time as _time
  _t0 = _time.time()
  def _step(n): logger.info(f"[process] STEP {n} (+{_time.time()-_t0:.1f}s)")
  try:
    _step("start")
    normed = []
    _parse_errors = []
    _acc_files: dict = {}   # (bank, account) -> [filename, ...]
    _saved_files: dict = {} # filename -> raw bytes (for session restore)
    for i, upload in enumerate(files):
        bank         = bank_names[i]      if i < len(bank_names)      else "Unknown"
        account      = account_numbers[i] if i < len(account_numbers) else "Unknown"
        account_name = (account_names or [])[i] if account_names and i < len(account_names) else ""
        fname        = upload.filename or f"file_{i}.csv"
        _acc_files.setdefault((bank, account), []).append((fname, account_name))
        try:
            raw = await upload.read()
            _saved_files[fname] = raw          # save raw bytes for session restore
            df = pd.read_csv(io.BytesIO(raw))
            normalized = normalize_transactions(df, bank, account)
            if account_name:
                normalized["account_name"] = account_name
            if normalized is not None and not normalized.empty:
                normalized["_src"] = fname
                normed.append(normalized)
            else:
                _parse_errors.append(f"{fname}: normalised to 0 rows (check bank selection)")
        except Exception as e:
            msg = f"{fname}: {type(e).__name__}: {e}"
            logger.warning(f"Skip {upload.filename}: {e}")
            _parse_errors.append(msg)
    if not normed:
        detail = "No valid CSVs parsed."
        if _parse_errors:
            detail += " Errors: " + " | ".join(_parse_errors[:3])
        raise HTTPException(400, detail)

    combined = _merge_open_banking_frames(pd.concat(normed, ignore_index=True))
    combined.columns = combined.columns.str.strip().str.lower()

    # ── Currency conversion (convert all amounts to AUD) ─────────────────────
    _currency = (currency or "AUD").upper().strip()
    if _apply_currency_conversion and _currency != "AUD":
        combined = _apply_currency_conversion(combined, _currency)

    # Safety: ensure account_name column always exists (may be missing if
    # bank_normalizer didn't produce it for some files)
    if "account_name" not in combined.columns:
        combined["account_name"] = ""

    # Log column presence for Northflank debugging
    logger.info(f"Combined columns: {combined.columns.tolist()}")
    logger.info(f"Sample description (first row): {combined['description'].iloc[0] if 'description' in combined.columns and len(combined) else 'N/A'}")

    # Fetch user's home company from DB for internal transfer detection
    _home_company = ""
    try:
        from accfino.shared.db.database import SessionLocal as _SL
        from accfino.core.identity.user import User as _User
        _db2 = _SL()
        _uname = norm_username(username)
        _usr = _db2.query(_User).filter(_User.username == _uname).first()
        if _usr and _usr.home_company:
            _home_company = _usr.home_company
        _db2.close()
    except Exception:
        pass
    try:
        classified = rec_classifier.classify_transactions(
            combined, show_progress=False,
            home_company=_home_company,
        )
    except Exception as _ce:
        logger.error(f"classify_transactions failed: {_ce}", exc_info=True)
        # Return raw combined as fallback so user gets data even without GL
        classified = combined.copy()
    classified = _norm_cols(classified)

    # Safety: ensure Account Name survives _norm_cols
    if "Account Name" not in classified.columns:
        classified["Account Name"] = combined.get("account_name", "").values[:len(classified)]

    # Ensure all columns match original schema
    for col, default in [("GL Account",""),("GL Type",""),("GST Category",""),("GST",0.0),("Who",""),("PairID","")]:
        if col not in classified.columns: classified[col] = default

    # Auto-classify GL (wrapped — never crash the endpoint)
    try:
        classified = _run_classify_gl(classified, username=username)
    except Exception as _ge:
        logger.error(f"_run_classify_gl failed: {_ge}", exc_info=True)

    # Loan payment detection (wrapped)
    try:
        if _detect_loan_payments:
            classified = _detect_loan_payments(classified)
    except Exception as _le:
        logger.warning(f"Loan detection skipped: {_le}")

    # Persist to DB in background thread — never blocks the HTTP response
    if _persist_transactions_to_db:
        _txns_snap  = _to_frontend(classified)
        _uname_snap = norm_username(username)
        _cur_snap   = _currency
        import threading as _thr
        def _bg_persist():
            try: _persist_transactions_to_db(_uname_snap, _txns_snap, _cur_snap)
            except Exception as _pe: logger.warning(f"DB persist bg error: {_pe}")
        _thr.Thread(target=_bg_persist, daemon=True, name="db-persist").start()
        _step("db-persist-started-in-background")

    # ── Extract opening/closing balances from CSV and save to DB ─────────────
    _norm_user = norm_username(username)
    _ab_entries = []
    _db_account_balances: dict = {}
    try:
        _bal_df = classified.copy()
        _bd = _bal_df.get("Date", _bal_df.get("date",""))
        _bal_df["_dt"] = pd.to_datetime(_bd, errors="coerce", dayfirst=True)
        _bal_df["_ro"] = range(len(_bal_df))
        _grp_cols = ["Bank","Account"] if "Bank" in _bal_df.columns and "Account" in _bal_df.columns else []
        if "Balance" in _bal_df.columns and _bal_df["Balance"].notna().any():
            for keys, grp in _bal_df.groupby(_grp_cols + [_bal_df["_dt"].dt.year.rename("_y"), _bal_df["_dt"].dt.month.rename("_m")]):
                if _grp_cols: _bank, _acct, _yr, _mo = keys[0], keys[1], keys[2], keys[3]
                else: _bank, _acct = "", ""; _yr, _mo = keys[0], keys[1]
                grp_all = grp.sort_values(["_dt","_ro"], ascending=[True,False])
                last_pos = grp_all["Balance"].last_valid_index()
                if last_pos is None: continue
                sim = float(grp_all.loc[last_pos,"Balance"])
                ip = grp_all.index.get_loc(last_pos)
                for _ri in grp_all.index[ip+1:]:
                    sim += float(grp_all.loc[_ri,"Credit"] or 0) - float(grp_all.loc[_ri,"Debit"] or 0)
                _closing = round(float(sim), 4)
                _net_all = float(
                    (grp_all["Credit"].fillna(0).sum() if "Credit" in grp_all.columns else 0)
                    - (grp_all["Debit"].fillna(0).sum() if "Debit" in grp_all.columns else 0)
                )
                _opening = round(float(_closing - _net_all), 4)
                _next_mo = int(_mo)+1; _next_yr = int(_yr)
                if _next_mo > 12: _next_mo = 1; _next_yr += 1
                _ab_entries.append({"bank":_bank,"account":_acct,"year":int(_yr),"month":int(_mo),
                                     "balance":float(_opening),"source":"csv"})
                _ab_entries.append({"bank":_bank,"account":_acct,"year":_next_yr,"month":_next_mo,
                                     "balance":float(_closing),"source":"derived"})
    except Exception as _be:
        logger.warning(f"Balance extraction failed: {_be}", exc_info=True)

    try:
        from accfino.shared.db.database import SessionLocal as _SLDB
        from accfino.core.identity.user import User as _UDBB
        from accfino.modules.reconciliation.models.account_balance import AccountBalance as _ABDB
        _dbb = _SLDB()
        try:
            _u = _dbb.query(_UDBB).filter(_UDBB.username == _norm_user).first()
            if _u:
                _uid = _u.id
                for _ab in _dbb.query(_ABDB).filter(_ABDB.user_id == _uid).all():
                    _db_account_balances[(_ab.bank,_ab.account,_ab.year,_ab.month)] = _ab.balance
                for _e in _ab_entries:
                    _ex = _dbb.query(_ABDB).filter(_ABDB.user_id==_uid,_ABDB.bank==_e["bank"],
                        _ABDB.account==_e["account"],_ABDB.year==_e["year"],_ABDB.month==_e["month"]).first()
                    if _ex:
                        if not _ex.is_manual: _ex.balance=float(_e["balance"]); _ex.source=_e["source"]
                    else:
                        _dbb.add(_ABDB(user_id=_uid,bank=_e["bank"],account=_e["account"],
                            year=_e["year"],month=_e["month"],balance=float(_e["balance"]),
                            is_manual=False,source=_e["source"]))
                _dbb.commit()
        finally: _dbb.close()
    except Exception as _dbe:
        logger.warning(f"AccountBalance DB save failed: {_dbe}")

    monthly = _build_monthly_summary(classified, account_balances=_db_account_balances)

    username = norm_username(username)
    sid = session_manager.create_session(username)
    session_manager.save_output_data(username, sid, classified, {}, set(), 1)

    # Save accounts.json so sessions panel can show bank/file counts
    # and so session restore can repopulate the Input panel
    import json as _json
    accounts_meta = [
        {
            "bank_name":    bank,
            "account_number": account,
            "account_name": tuples[0][1] if tuples else "",
            "files":        [t[0] for t in tuples],
        }
        for (bank, account), tuples in _acc_files.items()
    ]

    try:
        session_manager.save_input_meta_and_files(username, sid, accounts_meta, _saved_files)
    except Exception as _e:
        logger.warning(f"Failed to save session input for {sid}: {_e}")

    return {
        "session_id": sid,
        "transactions": _to_frontend(classified),
        "monthly_summary": monthly,
        "count": len(classified),
        "accounts_meta": accounts_meta,
    }
  except HTTPException:
      raise
  except Exception as _top_err:
      logger.error(f"/reconcile/process unhandled error: {_top_err}", exc_info=True)
      raise HTTPException(status_code=500, detail=f"Processing failed: {_top_err}")

def _run_classify_gl(df: pd.DataFrame, username: str = "") -> pd.DataFrame:
    """
    Classify GL account, GST category and GST amount for every row.
    Delegates to backend.classifier.engine - single call per transaction,
    all three fields resolved from COA in one TF-IDF pass.

    Refund/return matching: when a row is detected as a refund/return, the
    function first looks up the most recent matching debit row in the SAME
    DataFrame (same WHO or overlapping description tokens) and re-uses its
    GL Account and GST Category — so a Microsoft refund gets "Subscriptions",
    not "Other Revenue".
    """
    if "Description" not in df.columns:
        return df

    if "GL Account"   not in df.columns: df["GL Account"]   = ""
    if "GL Type"      not in df.columns: df["GL Type"]      = ""
    if "GST Category" not in df.columns: df["GST Category"] = ""
    if "GST"          not in df.columns: df["GST"]          = 0.0
    if "Who"          not in df.columns: df["Who"]          = ""

    # Build CompanyResolver for this request - uses company DB + home company
    _who_resolver = None
    _home_co = ""  # Always defined at function scope - pulled from logged-in user profile
    try:
        from accfino.shared.db.database import SessionLocal as _SL_who
        from accfino.core.identity.user import User as _UWho
        _who_db = _SL_who()
        try:
            _uw = _who_db.query(_UWho).filter(
                _UWho.username == norm_username(username)
            ).first()
            if _uw and _uw.home_company:
                _home_co = _uw.home_company
        except Exception:
            pass
        from accfino.modules.reconciliation.pipeline.company_resolver import CompanyResolver
        _who_resolver = CompanyResolver(db=_who_db, home_company=_home_co)
    except Exception:
        pass

    def _resolve_who(desc_text):
        """Resolve Who field. Returns (who_str, is_internal)."""
        if _who_resolver:
            try:
                who, is_int = _who_resolver.resolve(desc_text)
                if who and who not in ("", "Other/Unknown"):
                    return who, bool(is_int)
            except Exception:
                pass
        who_fb = extract_who_bank(desc_text)
        return who_fb, False

    def _to_float(v):
        parsed = pd.to_numeric(v, errors="coerce")
        return float(parsed) if pd.notnull(parsed) else 0.0

    _engine_warm(coa_path=_ACTIVE_COA_PATH)

    # Use module-level cached KB prefixes (loaded once at startup, never re-read per call)
    _return_prefixes   = _KB_RETURN_PREFIXES
    _internal_keywords = _KB_INTERNAL_KEYWORDS

    def _is_refund_desc(desc_lower: str) -> bool:
        return any(desc_lower.startswith(p) for p in _return_prefixes)

    # ── PRE-PASS 1: Resolve WHO for all rows + detect home-company internals ──
    _all_who: list[str] = []
    _all_internal: list[bool] = []
    for idx in df.index:
        desc = str(df.at[idx, "Description"]) if pd.notnull(df.at[idx, "Description"]) else ""
        who, is_int = _resolve_who(desc)
        _all_who.append(who)
        # Also check desc text for internal keywords (belt-and-suspenders)
        desc_lower = desc.lower()
        if not is_int:
            is_int = any(kw in desc_lower for kw in _internal_keywords)
        _all_internal.append(is_int)

    df["Who"] = _all_who

    # Mark Classification = Internal for home-company rows NOW so the main loop
    # can fast-skip them and blank their GL/GST
    if "Classification" not in df.columns:
        df["Classification"] = ""
    for idx, is_int in zip(df.index, _all_internal):
        if is_int:
            df.at[idx, "Classification"] = "🟢Internal"

    # ── PRE-PASS 2: Build vendor→GL lookup from debit (outgoing) rows ─────────
    # Maps vendor_key (lower WHO, or significant desc tokens) → (gl_account, gst_category, gl_type)
    # Uses the last-seen debit row for each key so more recent payments win.
    _vendor_gl: dict[str, tuple[str, str, str]] = {}

    def _vendor_keys_for(who: str, desc: str) -> list[str]:
        """Keys under which to index / look up a vendor GL mapping."""
        keys = []
        who_lower = (who or "").strip().lower()
        if who_lower and who_lower not in ("", "other/unknown"):
            keys.append(who_lower)
        # Also key on significant description tokens (3+ char words, not stop-words)
        import re as _re_vk
        _stop = {"the", "and", "for", "from", "to", "of", "a", "an", "in", "on",
                 "at", "by", "payment", "paid", "pay", "pty", "ltd", "aust",
                 "australia", "australian", "bpay", "ref", "transfer", "credit",
                 "debit", "return", "refund", "reversal", "chargeback"}
        tokens = [t for t in _re_vk.split(r"[^a-z0-9]+", desc.lower())
                  if len(t) >= 3 and t not in _stop]
        # Use up to 2 most significant tokens (longest)
        for tok in sorted(tokens, key=len, reverse=True)[:2]:
            keys.append(tok)
        return keys

    # Index debit rows (money out = original purchase)
    for idx in df.index:
        desc   = str(df.at[idx, "Description"]) if pd.notnull(df.at[idx, "Description"]) else ""
        debit  = _to_float(df.at[idx, "Debit"]  if "Debit"  in df.columns else 0)
        credit = _to_float(df.at[idx, "Credit"] if "Credit" in df.columns else 0)
        who    = str(df.at[idx, "Who"]).strip()

        if debit <= 0 or credit > 0:
            continue  # only index outgoing rows

        gl  = str(df.at[idx, "GL Account"]).strip()   # may be blank at this point
        gst = str(df.at[idx, "GST Category"]).strip()
        glt = str(df.at[idx, "GL Type"]).strip()

        # Only pre-index rows that already have a GL (carried-forward from prior session)
        # Blank GL rows will be filled in the classify loop below, then indexed for refunds
        if not gl:
            continue

        for vk in _vendor_keys_for(who, desc):
            _vendor_gl[vk] = (gl, gst, glt)

    # ── MAIN CLASSIFY LOOP ─────────────────────────────────────────────────────
    for idx in df.index:
        desc = str(df.at[idx, "Description"]) if pd.notnull(df.at[idx, "Description"]) else ""
        cl   = str(df.at[idx, "Classification"]) if "Classification" in df.columns and pd.notnull(df.at[idx, "Classification"]) else ""

        # Internal rows — ALWAYS zero out GL/GST (even if rec_classifier set something)
        _desc_lower_int = desc.lower()
        _is_text_internal = any(kw in _desc_lower_int for kw in _internal_keywords)
        if "Internal" in cl or _is_text_internal:
            df.at[idx, "GL Account"]   = ""
            df.at[idx, "GL Type"]      = ""
            df.at[idx, "GST Category"] = ""
            df.at[idx, "GST"]          = 0.0
            # WHO already written in pre-pass
            continue
        if not desc.strip():
            continue

        debit  = _to_float(df.at[idx, "Debit"]  if "Debit"  in df.columns else 0)
        credit = _to_float(df.at[idx, "Credit"] if "Credit" in df.columns else 0)
        who    = str(df.at[idx, "Who"]).strip()  # already set in pre-pass

        existing_gl  = normalize_gl_account(df.at[idx, "GL Account"])
        existing_gst = normalize_gst_category(df.at[idx, "GST Category"])

        # Fast path: row already fully classified — just index it for refund lookup
        if existing_gl and existing_gst and existing_gst not in ("", "Unknown"):
            if debit > 0 and credit == 0:
                for vk in _vendor_keys_for(who, desc):
                    if vk not in _vendor_gl:
                        _vendor_gl[vk] = (existing_gl, existing_gst,
                                          str(df.at[idx, "GL Type"]).strip() if "GL Type" in df.columns else "")
            continue

        # ── Refund/return: look up original GL from same-vendor debit rows ──────
        _desc_lower = desc.lower()
        _row_is_refund = credit > 0 and debit == 0 and _is_refund_desc(_desc_lower)

        if _row_is_refund and not existing_gl:
            _ref_gl = _ref_gst = _ref_glt = ""
            for vk in _vendor_keys_for(who, desc):
                if vk in _vendor_gl:
                    _ref_gl, _ref_gst, _ref_glt = _vendor_gl[vk]
                    break

            if _ref_gl:
                # Use the original GL account — refund reverses the same expense
                df.at[idx, "GL Account"]   = _ref_gl
                df.at[idx, "GL Type"]      = _ref_glt
                df.at[idx, "GST Category"] = _ref_gst
                from accfino.modules.reconciliation.pipeline.gst_calculator import calculate_gst_value
                df.at[idx, "GST"] = calculate_gst_value(debit, credit, _ref_gst)
                # Also update the DB lookup so future refunds from the same vendor chain
                for vk in _vendor_keys_for(who, desc):
                    _vendor_gl[vk] = (_ref_gl, _ref_gst, _ref_glt)
                continue  # skip engine classify for this row

        # ── Normal classify: RDR → KB → TF-IDF ───────────────────────────────
        _who_val = who
        _desc_with_who = f"{desc}|who:{_who_val.lower()}" if _who_val else desc
        try:
            result = _engine_classify(_desc_with_who, debit, credit)
        except Exception as _row_err:
            logger.warning(f"classify row [{idx}] '{desc[:60]}': {_row_err}")
            continue

        # Write GL Account if: RDR/TF-IDF found something AND field is empty
        if result.matched and not existing_gl:
            df.at[idx, "GL Account"] = result.gl_account
            df.at[idx, "GL Type"]    = result.gl_type or _COA_NAME_TO_TYPE.get(result.gl_account, "")

        if existing_gst in ("", "Unknown"):
            df.at[idx, "GST Category"] = result.gst_category
            try:
                from accfino.modules.reconciliation.pipeline.gst_calculator import calculate_gst_value
                df.at[idx, "GST"] = calculate_gst_value(debit, credit, result.gst_category)
            except Exception:
                df.at[idx, "GST"] = 0.0

        # ── Index this debit row for future refund lookups (after GL is set) ───
        if debit > 0 and credit == 0:
            _gl_now = str(df.at[idx, "GL Account"]).strip()
            if _gl_now:
                _gst_now = str(df.at[idx, "GST Category"]).strip()
                _glt_now = str(df.at[idx, "GL Type"]).strip()
                for vk in _vendor_keys_for(who, desc):
                    _vendor_gl[vk] = (_gl_now, _gst_now, _glt_now)

    return df

class ClassifyReq(BaseModel):
    session_id: str; username: str

@router.post("/reconcile/classify")
def reconcile_classify(body: ClassifyReq):
    """Classify empty GL/GST cells only - preserves manual edits."""
    username = norm_username(body.username)
    d = session_manager.load_session_data(username, body.session_id)
    if not d or d.get("results") is None:
        raise HTTPException(404, "Session not found")

    df = _norm_cols(d["results"].copy())
    df = _run_classify_gl(df, username=body.username)
    monthly = _build_monthly_summary(df)
    session_manager.save_output_data(username, body.session_id, df, {}, set(), 1)
    return {"transactions": _to_frontend(df), "monthly_summary": monthly}

@router.post("/reconcile/reclassify")
def reconcile_reclassify(body: ClassifyReq):
    """Force full reclassification of ALL rows using the current COA.
    Clears GL Account, GL Type and GST Category before running the engine
    so updated COA changes are applied to every row."""
    username = norm_username(body.username)
    d = session_manager.load_session_data(username, body.session_id)
    if not d or d.get("results") is None:
        raise HTTPException(404, "Session not found")

    df = _norm_cols(d["results"].copy())

    # Wipe classification columns so _run_classify_gl re-runs on everything
    for col in ["GL Account", "GL Type", "GST Category", "GST"]:
        if col in df.columns:
            df[col] = "" if col != "GST" else 0.0

    df = _run_classify_gl(df, username=body.username)
    monthly = _build_monthly_summary(df)
    session_manager.save_output_data(username, body.session_id, df, {}, set(), 1)
    return {"transactions": _to_frontend(df), "monthly_summary": monthly}

class ExportReq(BaseModel):
    transactions: list

@router.post("/reconcile/export")
def reconcile_export(body: ExportReq):
    df = pd.DataFrame(body.transactions)
    # Rename lowercase keys to Title Case for exporter
    df = _norm_cols(df)
    monthly_rows = _build_monthly_summary(df)
    monthly = pd.DataFrame(monthly_rows) if monthly_rows else None
    excel = export_excel_bytes(df, monthly)
    return StreamingResponse(excel,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": "attachment; filename=accfino_reconciliation.xlsx"})

@router.get("/db/stats/{user_id}")
def db_stats(user_id: int):
    try:
        from accfino.shared.db.database import SessionLocal as _SL
        from accfino.modules.reconciliation.models.transaction import Transaction as _Tx
        from accfino.core.identity.user import User as _U
        import sqlalchemy as _sa
        db = _SL()
        try:
            user = db.query(_U).filter(_U.id == user_id).first()
            if not user: raise HTTPException(404, "User not found")
            base_q = db.query(_Tx).filter(_Tx.user_id == user_id)
            total  = base_q.count()
            if total == 0: return None
            gl_set  = base_q.filter(_Tx.gl_account.isnot(None),  _Tx.gl_account  != "").count()
            gst_set = base_q.filter(_Tx.gst_category.isnot(None),_Tx.gst_category!= "").count()
            who_set = base_q.filter(_Tx.who.isnot(None),          _Tx.who         != "").count()
            bal_set = base_q.filter(_Tx.bank_balance.isnot(None)).count()
            loans   = base_q.filter(_Tx.is_loan_payment == True).count()
            loan_split = base_q.filter(_Tx.loan_principal.isnot(None)).count()
            currencies = [r[0] for r in db.query(_Tx.currency).filter(_Tx.user_id==user_id).distinct().all() if r[0]]
            last = db.query(_sa.func.max(_Tx.date)).filter(_Tx.user_id==user_id).scalar()
            # Return shape matching frontend expectation: dbStats.columns.gl_account etc
            return {
                "total": total,
                "columns": {
                    "gl_account":    gl_set,
                    "gst_category":  gst_set,
                    "who":           who_set,
                    "bank_balance":  bal_set,
                    "is_loan_payment": loans,
                    "loan_split":    loan_split,
                },
                "currencies":  currencies,
                "last_saved":  str(last) if last else None,
            }
        finally: db.close()
    except HTTPException: raise
    except Exception as e:
        logger.error(f"/db/stats error: {e}", exc_info=True)
        raise HTTPException(500, str(e))

@router.delete("/db/transactions/{user_id}")
def db_clear_user_transactions(user_id: int):
    """Delete ALL transactions for this user only. Other users unaffected."""
    try:
        from accfino.shared.db.database import SessionLocal as _SL
        from accfino.modules.reconciliation.models.transaction import Transaction as _Tx
        from accfino.core.identity.user import User as _U
        db = _SL()
        try:
            user = db.query(_U).filter(_U.id == user_id).first()
            if not user: raise HTTPException(404, "User not found")
            tx_count = db.query(_Tx).filter(_Tx.user_id == user_id).count()
            db.query(_Tx).filter(_Tx.user_id == user_id).delete(synchronize_session=False)
            ab_count = 0
            try:
                from accfino.modules.reconciliation.models.account_balance import AccountBalance as _AB
                ab_count = db.query(_AB).filter(_AB.user_id == user_id).count()
                db.query(_AB).filter(_AB.user_id == user_id).delete(synchronize_session=False)
            except Exception: pass
            db.commit()
            logger.info(f"DB cleared for user {user_id} ({user.username}): {tx_count} tx, {ab_count} balances deleted")
            return {"ok": True, "transactions_deleted": tx_count, "balances_deleted": ab_count, "user": user.username}
        finally: db.close()
    except HTTPException: raise
    except Exception as e:
        logger.error(f"/db/transactions delete error: {e}", exc_info=True)
        raise HTTPException(500, str(e))

@router.get("/cashflow/from-db/{user_id}")
def cashflow_from_db(user_id: int):
    """Build a transaction dataset from the user's saved DB transactions."""
    try:
        from accfino.shared.db.database import SessionLocal as _SL
        from accfino.modules.reconciliation.models.transaction import Transaction as _Tx
        _db = _SL()
        try:
            txns = _db.query(_Tx).filter(_Tx.user_id == user_id).order_by(_Tx.date).all()
            if not txns:
                return {"rows":[],"columns":[],"detected":{},"row_count":0,
                        "message":"No transactions in database"}
            rows = [{"date":str(t.date)[:10] if t.date else "","debit":float(t.debit or 0),
                     "credit":float(t.credit or 0),"balance":float(t.bank_balance or 0),
                     "description":t.description or ""} for t in txns]
            detected = {"date":"date","debit":"debit","credit":"credit","balance":"balance","desc":"description"}
            return {"rows":rows,"columns":list(rows[0].keys()),"detected":detected,
                    "row_count":len(rows),"message":f"{len(rows)} transactions loaded from database"}
        finally: _db.close()
    except Exception as e:
        logger.error(f"/cashflow/from-db: {e}", exc_info=True)
        raise HTTPException(500, str(e))

@router.get("/dashboard/stats")
def dashboard_stats(username: str):
    """
    Stats from the LATEST session only.
    Returns all-zero totals if no sessions exist.
    """
    username = norm_username(username)
    ZERO = {
        "total_in":0.0,"total_out":0.0,"total_gst":0.0,
        "internal":0,"incoming":0,"outgoing":0,
        "txn_count":0,"net":0.0,"session_count":0,
    }

    sessions = session_manager.get_all_sessions(username)
    if not sessions:
        return ZERO

    # Sort by datetime descending - pick the most recent session with results
    def _sess_dt(s):
        try: return str(s.get("datetime") or s.get("session_id") or "")
        except: return ""

    sorted_sessions = sorted(sessions, key=_sess_dt, reverse=True)
    latest = next((s for s in sorted_sessions if s.get("has_results")), None)
    if not latest:
        return {**ZERO, "session_count": len(sessions)}

    totals = {**ZERO, "session_count": len(sessions)}
    try:
        d  = session_manager.load_session_data(username, latest["session_id"])
        df = d.get("results")
        if df is None or df.empty:
            return totals
        df = _norm_cols(df)
        for _, row in df.iterrows():
            cl  = str(row.get("Classification") or row.get("classification") or "")
            db  = float(row.get("Debit",0)  or row.get("debit",0)  or 0)
            cr  = float(row.get("Credit",0) or row.get("credit",0) or 0)
            gst = float(row.get("GST",0)    or row.get("gst",0)    or 0)
            if "Incoming" in cl:
                totals["total_in"]  += cr
                totals["total_gst"] += gst
                totals["incoming"]  += 1
            elif "Outgoing" in cl:
                totals["total_out"] += db
                totals["total_gst"] += gst
                totals["outgoing"]  += 1
            elif "Internal" in cl:
                totals["internal"]  += 1
            totals["txn_count"] += 1
        totals["net"] = totals["total_in"] - totals["total_out"]
    except Exception:
        pass
    return totals

SAMPLE_CSV = ("date,description,amount,category,gst_category\n"
    "15/09/2025,BUNNINGS,65.38,Expense,GST on Expenses\n"
    "22/09/2025,OFFICEWORKS,42.10,Expense,GST on Expenses\n"
    "16/08/2025,CLIENT PAYMENT ABC PTY,339.55,Revenue,GST on Income\n"
    "20/08/2025,CLIENT PAYMENT XYZ PTY,512.00,Revenue,GST on Income\n"
    "19/08/2025,AMAZON,97.98,Expense,GST on Expenses\n"
    "1/10/2025,SUPPLIER DIRECT COST,566.31,Direct Costs,GST on Expenses\n"
    "3/10/2025,SUPPLIER RAW MATERIALS,289.40,Direct Costs,GST on Expenses\n")

@router.get("/ml/status")
def ml_status():
    return {
        "category_model": (DEFAULT_MODEL_DIR / "category_classifier.pkl").exists(),
        "gst_model": (DEFAULT_MODEL_DIR / "gst_category_classifier.pkl").exists(),
    }

@router.get("/ml/sample-csv")
def ml_sample():
    return Response(content=SAMPLE_CSV, media_type="text/csv",
                    headers={"Content-Disposition": "attachment; filename=sample_training_data.csv"})

@router.post("/ml/train")
async def ml_train(file: UploadFile=File(...)):
    try: df = pd.read_csv(io.BytesIO(await file.read()))
    except Exception as e: raise HTTPException(400, f"Cannot read CSV: {e}")
    text_col = "description" if "description" in df.columns else "transaction_description"
    errors = []
    if text_col not in df.columns: errors.append("Need 'description' or 'transaction_description'")
    for col in ["category", "gst_category"]:
        if col not in df.columns: errors.append(f"Missing: '{col}'")
    if errors: raise HTTPException(400, "\n".join(errors))
    try: result = train_from_df(df, model_dir=str(DEFAULT_MODEL_DIR))
    except ValueError as e: raise HTTPException(400, str(e))
    except Exception as e: raise HTTPException(500, f"Training failed: {e}")
    return {"ok": True, "rows_used": result.get("rows_used", len(df)),
            "category_accuracy": result.get("category_accuracy"),
            "gst_accuracy": result.get("gst_accuracy"),
            "warning": result.get("warning"),
            "message": "Models saved. Auto-classify will use them immediately."}

@router.get("/coa/accounts")
def coa_accounts(db: _Session = _Depends(_rdr_get_db)):
    """Return all GL account names + types from the chart_of_accounts table
    for RDR rule creation."""
    from accfino.modules.reconciliation.models.reference import ChartOfAccount
    try:
        rows = db.query(ChartOfAccount).order_by(ChartOfAccount.name).all()
        return [{"name": r.name, "type": r.type or ""} for r in rows]
    except Exception:
        return []

@router.get("/rdr/rules")
def rdr_list(db: _Session = _Depends(_rdr_get_db)):
    rules = db.query(RDRRule).order_by(RDRRule.priority.desc()).all()
    return [r.to_dict() for r in rules]

@router.post("/rdr/rules")
def rdr_create(rule: dict = Body(...), db: _Session = _Depends(_rdr_get_db)):
    rule_id = rule.get("id") or f"rule_{int(datetime.now().timestamp()*1000)}"
    entry = RDRRule(
        id=rule_id,
        name=rule.get("name"),
        priority=int(rule.get("priority", 100) or 100),
        then=rule.get("then"),
        then_gst_category=rule.get("then_gst_category"),
    )
    entry.set_condition(rule.get("if", {}))
    db.add(entry)
    db.commit()
    db.refresh(entry)
    return entry.to_dict()

@router.put("/rdr/rules/{rule_id}")
def rdr_update(rule_id: str, rule: dict = Body(...), db: _Session = _Depends(_rdr_get_db)):
    entry = db.get(RDRRule, rule_id)
    if not entry:
        raise HTTPException(404, "Rule not found")
    if "name" in rule: entry.name = rule["name"]
    if "priority" in rule: entry.priority = int(rule["priority"] or 100)
    if "if" in rule: entry.set_condition(rule["if"])
    if "then" in rule: entry.then = rule["then"]
    if "then_gst_category" in rule: entry.then_gst_category = rule["then_gst_category"]
    db.commit()
    db.refresh(entry)
    return entry.to_dict()

@router.delete("/rdr/rules/{rule_id}")
def rdr_delete(rule_id: str, db: _Session = _Depends(_rdr_get_db)):
    entry = db.get(RDRRule, rule_id)
    if entry:
        db.delete(entry)
        db.commit()
    return {"ok": True}

@router.post("/rdr/test")
def rdr_test(body: dict = Body(...), db: _Session = _Depends(_rdr_get_db)):
    import re
    desc   = str(body.get("description", ""))
    debit  = float(body.get("debit", 0) or 0)
    credit = float(body.get("credit", 0) or 0)
    d      = desc.lower()
    rules = db.query(RDRRule).order_by(RDRRule.priority.desc()).all()
    for rule in rules:
        if rule.debit_gt is not None and not debit > rule.debit_gt: continue
        if rule.credit_gt is not None and not credit > rule.credit_gt: continue
        if rule.debit_only and not (debit > 0 and credit == 0): continue
        if rule.credit_only and not (credit > 0 and debit == 0): continue
        if rule.contains_any and not any(str(k).lower() in d for k in rule.contains_any): continue
        if rule.regex_any and not any(re.search(rx, d) for rx in rule.regex_any): continue
        return {"matched": True, "rule": rule.to_dict()}
    return {"matched": False, "rule": None}

