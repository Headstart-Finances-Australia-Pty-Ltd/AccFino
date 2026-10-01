"""
Accfino React API - Full REST backend replacing ALL Streamlit modules.
Preserves ALL original logic from render_output_ui.py and render_input_ui.py
Run: python -m uvicorn main_app.react_api:app --host 127.0.0.1 --port 8001 --reload
"""
import base64, io, json, logging, os, sys, uuid
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

# Currency + loan helpers (new files — gracefully absent if not yet deployed)
_apply_currency_conversion  = None
_detect_loan_payments       = None
_persist_transactions_to_db = None
try:
    from main_app.react_api_helpers import (
        _apply_currency_conversion,
        _detect_loan_payments,
        _persist_transactions_to_db,
    )
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
    from backend.reconciliation.currency_service import SUPPORTED_CURRENCIES
except Exception:
    SUPPORTED_CURRENCIES = ["AUD","USD","EUR","GBP","INR","JPY","CNY","CAD","NZD","SGD","HKD","CHF"]

import pandas as pd
from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile, Body
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response, StreamingResponse
from pydantic import BaseModel

ROOT         = Path(__file__).parent   # main_app/
PROJECT_ROOT = ROOT.parent             # HSLedger/
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(PROJECT_ROOT))
os.chdir(PROJECT_ROOT)

logger = logging.getLogger("accfino")

from db_app.api import auth as db_auth
from db_app.api import transactions as db_transactions
from db_app.api import invoice as db_invoice
from db_app.api import password_reset as db_password_reset
from db_app.api import payments as db_payments
from db_app.api import groq_pool as db_groq_pool
from db_app.api import db_browser as db_db_browser
from db_app.api import reports as db_reports
from db_app.models.licence import LicenceRecord
from db_app.models.password_reset_token import PasswordResetToken

from backend.reconciliation.bank_normalizer import normalize_transactions, BANK_PRESETS
from backend.reconciliation import classifier as rec_classifier
from backend.reconciliation.gst_calculator import (
    calculate_gst, calculate_gst_value, GST_CATEGORY_OPTIONS,
)
from backend.reconciliation.exporter import export_excel_bytes
from backend.reconciliation.session_manager import session_manager

from backend.trading.data_parser import parse_trading_file
from backend.trading.report_presentation import generate_report_df
from backend.trading.trading_exporter import export_report_trading

try:
    from backend.cash_flow.pipeline import (
        auto_detect_columns, preprocess, validate_date_span,
        monthly_features, train_leaderboard, predict_next_month,
        LEADERBOARD_CSV, NEXT_MONTH_CSV, LEADERBOARD_PLOT, NEXT_MONTH_PLOT,
    )
except Exception:
    auto_detect_columns = preprocess = validate_date_span = monthly_features = None
    train_leaderboard = predict_next_month = None
    LEADERBOARD_CSV = NEXT_MONTH_CSV = LEAD = None

try:
    from backend.transaction_classifier.train_model import train_from_df, DEFAULT_MODEL_DIR
    _TRAINER_AVAILABLE = True
except Exception:
    _TRAINER_AVAILABLE = False
    DEFAULT_MODEL_DIR = Path("main_app/data/models")
    def train_from_df(*a, **kw): raise ImportError("Trainer not available")
from backend.classifier.engine import classify as _engine_classify, warm as _engine_warm, DEFAULT_COA_PATH as _DEFAULT_COA_PATH

# -- COA name/type lookup - built once at startup ------------------------------
def _load_coa_names(path=None) -> tuple:
    """Return (sorted *Name list, {name: type} dict). Postgres
    (chart_of_accounts table) is authoritative; falls back to reading
    ChartOfAccounts.csv directly if the DB isn't reachable yet (e.g. this
    runs at import time, before the startup migration thread has
    necessarily created the table on a brand-new database)."""
    if path is None:
        try:
            from db_app.database import SessionLocal
            from db_app.models.app_data import ChartOfAccount
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
    from backend.classifier.engine import DEFAULT_COA_PATH
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

# Import the EXACT enums used in the original output UI
from backend.llm_classifier.classify_category import (
    CATEGORY_ENUM,
)
# extract_who_bank: fallback WHO resolver when CompanyResolver is unavailable.
# Parses common vendor/payee names directly from the bank description text.
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
from backend.reconciliation.gst_calculator import GST_CATEGORY_OPTIONS

try:
    from backend.invoice_extractor.core import (
        process_files as ie_process_files, get_dependency_status,
    )
    IE_AVAILABLE = True
except Exception:
    IE_AVAILABLE = False

try:
    from backend.open_banking import (
        auth as ob_auth, user as ob_user,
        job_service as ob_job,
    )
    OB_AVAILABLE = True
except Exception:
    OB_AVAILABLE = False

app = FastAPI(title="Accfino API", version="2.0")

# Startup readiness flag - set to True after all heavy modules are loaded.
# The /ready endpoint returns 503 until this is True so Northflank's
# load balancer doesn't route traffic before the app is initialised.
_app_ready = False

# Register company API router - graceful degradation if model files are missing
try:
    from db_app.api.company import router as _company_router
    app.include_router(_company_router, prefix="/company", tags=["company"])
    print("[accfino] Company DB router registered OK")
except Exception as _company_err:
    print(f"[accfino] WARNING: Company DB router not loaded: {_company_err}")
    print("[accfino] Company features disabled ? ensure db_app/models/company.py exists")
# CORS - extend via CORS_ORIGINS env var (comma-separated) for custom domains.
# E.g. in Northflank env vars: CORS_ORIGINS=https://myapp.northflank.app
import os as _os
_extra_origins = [o.strip() for o in _os.environ.get("CORS_ORIGINS","").split(",") if o.strip()]
_CORS_ORIGINS = [
    "http://localhost:3000","http://127.0.0.1:3000",
    "http://localhost:5173","http://127.0.0.1:5173",
    "https://www.accfino.com","https://accfino.com",
] + _extra_origins

app.add_middleware(CORSMiddleware,
    allow_origins=_CORS_ORIGINS,
    allow_origin_regex=r"https://.*\.northflank\.app",  # all Northflank preview URLs
    allow_credentials=True, allow_methods=["*"], allow_headers=["*"])

from fastapi.responses import JSONResponse
from fastapi.requests  import Request as _Request

@app.exception_handler(Exception)
async def global_exception_handler(request: _Request, exc: Exception):
    """Catch any unhandled exception and return JSON instead of crashing."""
    import traceback, logging
    logging.getLogger("accfino").error(f"Unhandled: {exc}\n{traceback.format_exc()}")
    return JSONResponse(
        status_code=500,
        content={"detail": f"Server error: {type(exc).__name__}: {str(exc)[:500]}"}
    )

# -- Health check endpoint (used by Northflank / Docker HEALTHCHECK) -----------
@app.post("/debug/parse-csv", include_in_schema=False)
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


@app.get("/profile/home-company")
def get_home_company(username: str):
    """Return the registered home company for a user."""
    from db_app.database import SessionLocal as _SL
    from db_app.models.user import User as _User
    db2 = _SL()
    try:
        u = db2.query(_User).filter(_User.username == norm_username(username)).first()
        return {"home_company": u.home_company if u else ""}
    finally:
        db2.close()


@app.post("/profile/home-company")
def set_home_company(username: str = Body(...), home_company: str = Body(...)):
    """Set the registered home company for a user."""
    from db_app.database import SessionLocal as _SL
    from db_app.models.user import User as _User
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


@app.post("/company/capture-who")
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
    from db_app.database import SessionLocal as _SL
    from db_app.models.company import Company, CompanyAlias
    from backend.reconciliation.company_resolver import _home_aliases

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


@app.on_event("startup")
async def _on_startup():
    """
    Mark app as ready immediately so health checks pass.
    Run DB housekeeping in a background thread so slow Neon cold-starts
    don't block uvicorn from finishing startup.
    """
    global _app_ready
    _app_ready = True

    import threading as _threading

    def _bg_init():
        try:
            from db_app.database import engine as _db_engine
            from db_app.models.licence import LicenceRecord as _LR
            from db_app.models.password_reset_token import PasswordResetToken as _PRT
            _LR.__table__.create(bind=_db_engine, checkfirst=True)
            _PRT.__table__.create(bind=_db_engine, checkfirst=True)
        except Exception as _e:
            logger.warning(f"startup: table create skipped: {_e}")
        try:
            from db_app.init_db import migrate_db as _mdb
            _mdb()
        except Exception as _e:
            logger.warning(f"startup: migrate_db skipped: {_e}")
        try:
            from db_app.migrations.add_currency_loan_columns import run as _mc
            from db_app.database import engine as _db_engine
            _mc(_db_engine)
        except Exception as _e:
            logger.warning(f"startup: currency/loan migration skipped: {_e}")
        try:
            from db_app.migrations.create_account_balances import run as _mab
            from db_app.database import engine as _db_engine
            _mab(_db_engine)
        except Exception as _e:
            logger.warning(f"startup: account_balances migration skipped: {_e}")
        try:
            from db_app.migrations.create_accounting_tables import run as _mac
            from db_app.database import engine as _db_engine
            _mac(_db_engine)
        except Exception as _e:
            logger.warning(f"startup: accounting migration skipped: {_e}")
        try:
            from db_app.migrations.create_payroll_tables import run as _mpr
            from db_app.database import engine as _db_engine
            _mpr(_db_engine)
        except Exception as _e:
            logger.warning(f"startup: payroll migration skipped: {_e}")
        try:
            from db_app.migrations.restructure_rdr_rules import run as _mrdr
            from db_app.database import engine as _db_engine
            _mrdr(_db_engine)
        except Exception as _e:
            logger.warning(f"startup: rdr_rules migration skipped: {_e}")
        try:
            from db_app.migrations.create_groq_key_pool import run as _mgkp
            from db_app.database import engine as _db_engine
            _mgkp(_db_engine)
        except Exception as _e:
            logger.warning(f"startup: groq_key_pool migration skipped: {_e}")
        try:
            from db_app.migrations.create_reconciliation_sessions import run as _mrs
            from db_app.database import engine as _db_engine
            _mrs(_db_engine)
        except Exception as _e:
            logger.warning(f"startup: reconciliation_sessions migration skipped: {_e}")
        try:
            from db_app.migrations.create_coa_kb_pricing_lending import run as _mckpl
            from db_app.database import engine as _db_engine
            _mckpl(_db_engine)
        except Exception as _e:
            logger.warning(f"startup: coa/kb/pricing/lending migration skipped: {_e}")
        try:
            from db_app.migrations.restructure_pricing_plans import run as _mpp
            from db_app.database import engine as _db_engine
            _mpp(_db_engine)
        except Exception as _e:
            logger.warning(f"startup: pricing_plans restructure migration skipped: {_e}")
        try:
            from db_app.migrations.create_classifier_cache import run as _mcc
            from db_app.database import engine as _db_engine
            _mcc(_db_engine)
        except Exception as _e:
            logger.warning(f"startup: classifier_cache migration skipped: {_e}")
        logger.info("startup: background DB init complete")

    _threading.Thread(target=_bg_init, daemon=True, name="startup-db-init").start()


@app.post("/auth/reset-admin", include_in_schema=False)
def reset_admin_password(secret: str = Body(...)):
    """
    Emergency endpoint - resets admin password to a new value.
    Requires the ADMIN_RESET_SECRET env var to be set and passed as 'secret'.
    Use when locked out of Northflank deployment.

    POST /api/auth/reset-admin
    Body: {"secret": "<ADMIN_RESET_SECRET env var>", "new_password": "newpass"}
    """
    import os as _os
    from db_app.database import SessionLocal as _SL
    from db_app.models.user import User as _User
    import bcrypt as _bcrypt

    expected = _os.environ.get("ADMIN_RESET_SECRET", "")
    if not expected or secret != expected:
        raise HTTPException(403, "Invalid secret")
    return {"error": "Use new_password field"}


@app.post("/auth/reset-admin-full", include_in_schema=False)
async def reset_admin_full(request: Request):
    """Full admin reset - body: {secret, new_password}"""
    import os as _os
    from db_app.database import SessionLocal as _SL
    from db_app.models.user import User as _User
    import bcrypt as _bcrypt

    body = await request.json()
    secret = body.get("secret", "")
    new_pw = body.get("new_password", "")
    expected = _os.environ.get("ADMIN_RESET_SECRET", "")

    if not expected:
        raise HTTPException(503, "ADMIN_RESET_SECRET not set in environment")
    if secret != expected:
        raise HTTPException(403, "Invalid secret")
    if not new_pw or len(new_pw) < 1:
        raise HTTPException(400, "new_password required")

    db = _SL()
    try:
        admin = db.query(_User).filter(
            (_User.username == "admin") | (_User.email == "admin@accfino.com")
        ).first()
        if not admin:
            raise HTTPException(404, "Admin user not found")
        hashed = _bcrypt.hashpw(new_pw.encode(), _bcrypt.gensalt()).decode()
        admin.password = hashed
        db.commit()
        return {"ok": True, "message": f"Admin password reset successfully"}
    finally:
        db.close()


@app.get("/ready", include_in_schema=False)
def readiness_probe():
    """
    Northflank / Kubernetes readiness probe.
    Returns 200 once the app is fully initialised, 503 during startup.
    Configure Northflank to use this as the health check path.
    """
    if _app_ready:
        from fastapi.responses import JSONResponse
        return JSONResponse({"status": "ready"}, status_code=200)
    from fastapi.responses import JSONResponse
    return JSONResponse({"status": "starting"}, status_code=503)


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


# Fields a user can manually edit in the Output panel — these are the only
# fields carried forward from a prior session's saved results onto matching
# rows in a freshly re-classified re-run. Everything else (e.g. PairID for
# brand-new internal-transfer matches involving newly added files) is left
# to be recomputed fresh by the classifier so new pairings still work.
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


@app.post("/reconcile/process-with-session")
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
            normed.append(normalized)
        except Exception as e:
            logger.warning(f"Failed to process new file {fname}: {e}")

    if not normed:
        raise HTTPException(400, "No valid files found - check session files and new uploads")

    # -- Classify --------------------------------------------------------------
    combined = pd.concat(normed, ignore_index=True)
    combined.columns = combined.columns.str.strip().str.lower()
    if "account_name" not in combined.columns:
        combined["account_name"] = ""

    _home_company = ""
    try:
        from db_app.database import SessionLocal as _SL
        from db_app.models.user import User as _User
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


@app.post("/shutdown", include_in_schema=False)
async def shutdown():
    """Graceful shutdown - closes DB connections then exits."""
    import threading, os, signal
    def _stop():
        import time; time.sleep(0.5)
        os.kill(os.getpid(), signal.SIGTERM)
    threading.Thread(target=_stop, daemon=True).start()
    return {"ok": True}


@app.get("/health", include_in_schema=False)
def health_check():
    """Simple liveness probe - returns 200 if the API process is running."""
    return {"status": "ok", "service": "accfino-api"}



app.include_router(db_auth.router,           prefix="/auth",        tags=["auth"])
app.include_router(db_transactions.router,   prefix="/transactions", tags=["transactions"])
app.include_router(db_invoice.router,        prefix="/invoice",      tags=["invoice"])
app.include_router(db_password_reset.router, prefix="/auth",         tags=["auth"])
app.include_router(db_payments.router,       prefix="/payments",     tags=["payments"])
app.include_router(db_groq_pool.router,      prefix="/groq-pool",    tags=["groq-pool"])
app.include_router(db_db_browser.router,     prefix="/db-browser",   tags=["db-browser"])
app.include_router(db_reports.router,        prefix="/reports",      tags=["reports"])

# ── Accounting module ──────────────────────────────────────────────────────────
try:
    from db_app.api.accounting import router as _accounting_router
    app.include_router(_accounting_router, prefix="/accounting", tags=["accounting"])
    print("[accfino] Accounting router registered OK")
except Exception as _acc_err:
    print(f"[accfino] WARNING: Accounting router not loaded: {_acc_err}")

# ── Payroll module ─────────────────────────────────────────────────────────────
try:
    from main_app.backend.payroll.router import router as _payroll_router
    app.include_router(_payroll_router, prefix="/payroll", tags=["payroll"])
    print("[accfino] Payroll router registered OK")
except Exception as _pr_err:
    try:
        from backend.payroll.router import router as _payroll_router
        app.include_router(_payroll_router, prefix="/payroll", tags=["payroll"])
    except Exception as _pr_err2:
        print(f"[accfino] WARNING: Payroll router not loaded: {_pr_err2}")

# ── Smart Lending module ───────────────────────────────────────────────────────
try:
    from main_app.backend.lending.router import router as _lending_router
    app.include_router(_lending_router, tags=["lending"])
    print("[accfino] Smart Lending router registered OK")
except Exception as _lr_err:
    try:
        from backend.lending.router import router as _lending_router
        app.include_router(_lending_router, tags=["lending"])
        print("[accfino] Smart Lending router registered OK (fallback)")
    except Exception as _lr_err2:
        print(f"[accfino] WARNING: Smart Lending router not loaded: {_lr_err2}")

_cf_cache: dict = {}


# -- GST normalization --------------------------------------------------------
# GST category values come directly from COA *Tax Code column via the engine.
# No alias mapping - values are passed through unchanged if they match COA.
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


# -- Helpers -------------------------------------------------------------------
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


# ── Account Balance API endpoints ────────────────────────────────────────────

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

@app.get("/account-balances/{user_id}")
def get_account_balances(user_id: int):
    """Return all stored opening balances for a user as a dict keyed 'bank|account|year|month'."""
    try:
        from db_app.database import SessionLocal as _SL
        from db_app.models.account_balance import AccountBalance as _AB
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


@app.post("/account-balances")
def upsert_account_balance(body: AccountBalanceIn):
    """Create or update an opening balance record."""
    try:
        from db_app.database import SessionLocal as _SL
        from db_app.models.account_balance import AccountBalance as _AB
        from db_app.models.user import User as _U
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


@app.post("/account-balances/bulk")
def bulk_upsert_account_balances(body: dict):
    """
    Bulk-upsert opening balances derived from CSV bank_balance column.
    Called after processing when we have reliable CSV balance data.
    body: { user_id, entries: [{bank, account, year, month, balance, source}] }
    """
    try:
        from db_app.database import SessionLocal as _SL
        from db_app.models.account_balance import AccountBalance as _AB
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


# ------------------------------------------------------------------------------
# BANKS / GST
# ------------------------------------------------------------------------------
@app.get("/banks")
def get_banks(): return sorted(BANK_PRESETS.keys())

@app.get("/gst/categories")
def get_gst_cats(): return GST_CATEGORY_OPTIONS

@app.get("/gl/accounts")
def get_gl_accounts(): return _COA_NAMES + [""]

@app.post("/gl/accounts/upload")
async def upload_gl_accounts(file: UploadFile = File(...)):
    """Save uploaded ChartOfAccounts.csv to disk and rebuild classifier index.
    Uses temp-file + replace to avoid locking errors on Windows."""
    import shutil, tempfile
    from backend.classifier.engine import rebuild as _engine_rebuild, evict as _engine_evict, warm as _engine_warm_path
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
            from db_app.database import SessionLocal as _SL_coa
            from db_app.models.app_data import ChartOfAccount as _COA
            from backend.utils.db_sync import sync_coa_csv_from_db as _sync_coa

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

@app.get("/gl/accounts/all")
def get_gl_accounts_all():
    """Return full COA rows with all columns for the GL Accounts modal and coaMap."""
    import csv
    from backend.classifier.engine import DEFAULT_COA_PATH
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

@app.get("/gst/calculate")
def calc_gst(debit: float=0, credit: float=0, category: str="Unknown"):
    return {"gst": calculate_gst_value(debit, credit, category)}


# ------------------------------------------------------------------------------
# USERNAME NORMALISATION
# The session folder is always the username string used at creation time.
# norm_username() must return exactly that string for both create and lookup.
#
# Strategy (in order):
#   1. Use username exactly as given if a matching folder already exists
#   2. If it looks like an email (has @), try the local part (before @)
#      and check if that folder exists
#   3. Fall back to the local part anyway (new sessions use local part)
# ------------------------------------------------------------------------------
_DATA_DIR = Path(__file__).parent / "data"

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


# ------------------------------------------------------------------------------
# SESSIONS
# ------------------------------------------------------------------------------
class SaveSessReq(BaseModel):
    session_id: str; username: str; transactions: list
    pending_changes: dict = {}; page_number: int = 1

# ── Knowledge Base endpoints ──────────────────────────────────────────────────
_KB_PATH = ROOT / "data" / "knowledge_base.json"

# Module-level cached prefixes so _run_classify_gl never reads disk per call
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

# Load at startup
_reload_kb_prefixes()

def _load_kb():
    try:
        return json.loads(_KB_PATH.read_text(encoding="utf-8"))
    except Exception:
        return {}

def _save_kb(kb: dict):
    _KB_PATH.write_text(json.dumps(kb, indent=2, ensure_ascii=False), encoding="utf-8")
    _reload_kb_prefixes()   # keep module-level prefix cache in sync

@app.get("/kb")
def kb_get():
    """Return full knowledge base."""
    return _load_kb()

@app.put("/kb/vendor/{vendor_key}")
def kb_vendor_upsert(vendor_key: str, body: dict):
    """Add or update a vendor entry."""
    kb = _load_kb()
    kb.setdefault("vendor_map", {})[vendor_key.lower()] = body
    _save_kb(kb)
    return {"ok": True, "vendor": vendor_key, "entry": body}

@app.delete("/kb/vendor/{vendor_key}")
def kb_vendor_delete(vendor_key: str):
    """Remove a vendor entry."""
    kb = _load_kb()
    kb.get("vendor_map", {}).pop(vendor_key.lower(), None)
    _save_kb(kb)
    return {"ok": True}

@app.put("/kb/keyword/{keyword}")
def kb_keyword_upsert(keyword: str, body: dict):
    """Add or update a keyword entry."""
    kb = _load_kb()
    kb.setdefault("keyword_map", {})[keyword.lower()] = body
    _save_kb(kb)
    return {"ok": True, "keyword": keyword, "entry": body}

@app.delete("/kb/keyword/{keyword}")
def kb_keyword_delete(keyword: str):
    """Remove a keyword entry."""
    kb = _load_kb()
    kb.get("keyword_map", {}).pop(keyword.lower(), None)
    _save_kb(kb)
    return {"ok": True}

@app.put("/kb/meta")
def kb_meta_update(body: dict):
    """Update internal_keywords or return_prefixes lists."""
    kb = _load_kb()
    if "internal_keywords" in body:
        kb["internal_keywords"] = body["internal_keywords"]
    if "return_prefixes" in body:
        kb["return_prefixes"] = body["return_prefixes"]
    _save_kb(kb)
    return {"ok": True}

@app.get("/sessions")
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

@app.delete("/sessions/{username}/{sid}")
def del_session(username: str, sid: str):
    return {"ok": session_manager.delete_session(norm_username(username), sid)}

@app.get("/sessions/{username}/{sid}")
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
                from db_app.database import SessionLocal as _SL_r
                from db_app.models.user import User as _UUser_r
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
            from db_app.database import SessionLocal as _SL_ab
            from db_app.models.user import User as _U_ab
            from db_app.models.account_balance import AccountBalance as _AB_ses
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

@app.post("/sessions/save")
def save_session(body: SaveSessReq):
    username = norm_username(body.username)
    df = pd.DataFrame(body.transactions) if body.transactions else pd.DataFrame()
    if not df.empty:
        df = _norm_cols(df)
    session_manager.save_output_data(username, body.session_id, df,
        {int(k): v for k, v in body.pending_changes.items()},
        set(), body.page_number)
    return {"ok": True}


# ------------------------------------------------------------------------------
# RECONCILIATION
# ------------------------------------------------------------------------------
@app.post("/reconcile/process")
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

    combined = pd.concat(normed, ignore_index=True)
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
        from db_app.database import SessionLocal as _SL
        from db_app.models.user import User as _User
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
        from db_app.database import SessionLocal as _SLDB
        from db_app.models.user import User as _UDBB
        from db_app.models.account_balance import AccountBalance as _ABDB
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
        from db_app.database import SessionLocal as _SL_who
        from db_app.models.user import User as _UWho
        _who_db = _SL_who()
        try:
            _uw = _who_db.query(_UWho).filter(
                _UWho.username == norm_username(username)
            ).first()
            if _uw and _uw.home_company:
                _home_co = _uw.home_company
        except Exception:
            pass
        from backend.reconciliation.company_resolver import CompanyResolver
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
                from backend.reconciliation.gst_calculator import calculate_gst_value
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
                from backend.reconciliation.gst_calculator import calculate_gst_value
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

@app.post("/reconcile/classify")
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


@app.post("/reconcile/reclassify")
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

@app.post("/reconcile/export")
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



# ── DB Stats endpoint ────────────────────────────────────────────────────────
@app.get("/db/stats/{user_id}")
def db_stats(user_id: int):
    try:
        from db_app.database import SessionLocal as _SL
        from db_app.models.transaction import Transaction as _Tx
        from db_app.models.user import User as _U
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


# ── Clear user DB transactions ────────────────────────────────────────────────
@app.delete("/db/transactions/{user_id}")
def db_clear_user_transactions(user_id: int):
    """Delete ALL transactions for this user only. Other users unaffected."""
    try:
        from db_app.database import SessionLocal as _SL
        from db_app.models.transaction import Transaction as _Tx
        from db_app.models.user import User as _U
        db = _SL()
        try:
            user = db.query(_U).filter(_U.id == user_id).first()
            if not user: raise HTTPException(404, "User not found")
            tx_count = db.query(_Tx).filter(_Tx.user_id == user_id).count()
            db.query(_Tx).filter(_Tx.user_id == user_id).delete(synchronize_session=False)
            ab_count = 0
            try:
                from db_app.models.account_balance import AccountBalance as _AB
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


# ── Cash Flow from DB ─────────────────────────────────────────────────────────
@app.get("/cashflow/from-db/{user_id}")
def cashflow_from_db(user_id: int):
    """Build a transaction dataset from the user's saved DB transactions."""
    try:
        from db_app.database import SessionLocal as _SL
        from db_app.models.transaction import Transaction as _Tx
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


# ------------------------------------------------------------------------------
# DASHBOARD STATS  - aggregates from ALL session pickles (no Save-to-DB needed)
# ------------------------------------------------------------------------------
@app.get("/dashboard/stats")
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

# ------------------------------------------------------------------------------
# TRADING
# ------------------------------------------------------------------------------
@app.post("/trading/analyze")
async def trading_analyze(file: UploadFile=File(...)):
    import tempfile, os as _os
    raw = await file.read()
    suffix = ".json" if (file.filename or "").lower().endswith(".json") else ".csv"
    with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
        tmp.write(raw); tmp_path = tmp.name
    try:
        trades_df = parse_trading_file(open(tmp_path, "rb"))
        _os.unlink(tmp_path)
    except Exception as e:
        raise HTTPException(400, f"Parse failed: {e}")
    if trades_df is None or trades_df.empty:
        raise HTTPException(400, "No valid trading records found")
    try:
        per_symbol_df, totals_df, tax_df = generate_report_df(trades_df)
    except Exception as e:
        raise HTTPException(500, f"Report failed: {e}")

    def sdf(df):
        if df is None or df.empty: return []
        d = df.copy()
        for c in d.columns:
            d[c] = d[c].apply(lambda x: None if (isinstance(x, float) and pd.isna(x)) else
                              (str(x) if hasattr(x, "isoformat") else x))
        return d.to_dict(orient="records")

    return {"trades": sdf(trades_df), "tax": sdf(tax_df),
            "per_symbol": sdf(per_symbol_df), "count": len(trades_df)}

@app.post("/trading/export")
async def trading_export(file: UploadFile=File(...)):
    import tempfile, os as _os
    raw = await file.read()
    suffix = ".json" if (file.filename or "").lower().endswith(".json") else ".csv"
    with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
        tmp.write(raw); tmp_path = tmp.name
    trades_df = parse_trading_file(open(tmp_path, "rb")); _os.unlink(tmp_path)
    per_symbol_df, totals_df, tax_df = generate_report_df(trades_df)
    xlsx = export_report_trading(trades_df, per_symbol_df, tax_df, None)
    return Response(content=xlsx,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": "attachment; filename=trading_report.xlsx"})


# ------------------------------------------------------------------------------
# CASH FLOW
# ------------------------------------------------------------------------------
@app.post("/cashflow/detect")
async def cf_detect(file: UploadFile=File(...)):
    df = pd.read_csv(io.BytesIO(await file.read()))
    detected = auto_detect_columns(df)
    cols = [c for c in df.columns if not c.startswith("_")]
    rows = df.to_dict(orient="records")
    return {"detected": detected, "columns": cols, "row_count": len(df),
            "sample": df.head(5).to_dict(orient="records"), "rows": rows}

class CfRunReq(BaseModel):
    rows: list; col_map: dict

@app.post("/cashflow/run")
def cf_run(body: CfRunReq):
    if not body.rows: raise HTTPException(400, "No data")
    df_raw  = pd.DataFrame(body.rows)
    col_map = {k: (v if v != "(none)" else None) for k, v in body.col_map.items()}
    missing = [r for r in ("date", "debit", "credit") if not col_map.get(r)]
    if missing: raise HTTPException(400, f"Unmapped: {missing}")
    try:
        df_proc, _t, _o = preprocess(df_raw, col_map)
        months_span, d_min, d_max = validate_date_span(df_proc)
        monthly = monthly_features(df_proc)
        lb, trained_models, feature_cols, data = train_leaderboard(monthly)
    except Exception as e:
        raise HTTPException(500, str(e))
    run_id = str(uuid.uuid4())
    _cf_cache[run_id] = dict(trained_models=trained_models, feature_cols=feature_cols,
                              monthly=monthly, data=data)
    lb_img = base64.b64encode(LEADERBOARD_PLOT.read_bytes()).decode() if LEADERBOARD_PLOT.exists() else ""
    return {"run_id": run_id, "months_span": months_span,
            "date_min": str(d_min), "date_max": str(d_max),
            "model_names": lb["model"].tolist(),
            "leaderboard": lb.to_dict(orient="records"),
            "leaderboard_plot_b64": lb_img}

@app.post("/cashflow/predict/{run_id}")
def cf_predict(run_id: str, model_name: str=Body(..., embed=True)):
    cache = _cf_cache.get(run_id)
    if not cache: raise HTTPException(404, "Run expired - please re-run pipeline")
    try:
        pred = predict_next_month(model_name, cache["trained_models"],
                                  cache["feature_cols"], cache["monthly"], cache["data"])
    except Exception as e:
        raise HTTPException(500, str(e))
    plot_b64 = base64.b64encode(NEXT_MONTH_PLOT.read_bytes()).decode() if NEXT_MONTH_PLOT.exists() else ""
    csv_data = NEXT_MONTH_CSV.read_text() if NEXT_MONTH_CSV.exists() else ""
    return {**pred, "forecast_plot_b64": plot_b64, "forecast_csv": csv_data}


# ------------------------------------------------------------------------------
# ML CLASSIFIER
# ------------------------------------------------------------------------------
SAMPLE_CSV = ("date,description,amount,category,gst_category\n"
    "15/09/2025,BUNNINGS,65.38,Expense,GST on Expenses\n"
    "22/09/2025,OFFICEWORKS,42.10,Expense,GST on Expenses\n"
    "16/08/2025,CLIENT PAYMENT ABC PTY,339.55,Revenue,GST on Income\n"
    "20/08/2025,CLIENT PAYMENT XYZ PTY,512.00,Revenue,GST on Income\n"
    "19/08/2025,AMAZON,97.98,Expense,GST on Expenses\n"
    "1/10/2025,SUPPLIER DIRECT COST,566.31,Direct Costs,GST on Expenses\n"
    "3/10/2025,SUPPLIER RAW MATERIALS,289.40,Direct Costs,GST on Expenses\n")

@app.get("/ml/status")
def ml_status():
    return {
        "category_model": (DEFAULT_MODEL_DIR / "category_classifier.pkl").exists(),
        "gst_model": (DEFAULT_MODEL_DIR / "gst_category_classifier.pkl").exists(),
    }

@app.get("/ml/sample-csv")
def ml_sample():
    return Response(content=SAMPLE_CSV, media_type="text/csv",
                    headers={"Content-Disposition": "attachment; filename=sample_training_data.csv"})

@app.post("/ml/train")
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


# ------------------------------------------------------------------------------
# RDR RULES  (Postgres-backed -- see db_app/models/rdr_rule.py)
# ------------------------------------------------------------------------------
from fastapi import Depends as _Depends
from sqlalchemy.orm import Session as _Session
from db_app.database import get_db as _rdr_get_db
from db_app.models.rdr_rule import RDRRule

@app.get("/coa/accounts")
def coa_accounts(db: _Session = _Depends(_rdr_get_db)):
    """Return all GL account names + types from the chart_of_accounts table
    for RDR rule creation."""
    from db_app.models.app_data import ChartOfAccount
    try:
        rows = db.query(ChartOfAccount).order_by(ChartOfAccount.name).all()
        return [{"name": r.name, "type": r.type or ""} for r in rows]
    except Exception:
        return []

@app.get("/rdr/rules")
def rdr_list(db: _Session = _Depends(_rdr_get_db)):
    rules = db.query(RDRRule).order_by(RDRRule.priority.desc()).all()
    return [r.to_dict() for r in rules]

@app.post("/rdr/rules")
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

@app.put("/rdr/rules/{rule_id}")
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

@app.delete("/rdr/rules/{rule_id}")
def rdr_delete(rule_id: str, db: _Session = _Depends(_rdr_get_db)):
    entry = db.get(RDRRule, rule_id)
    if entry:
        db.delete(entry)
        db.commit()
    return {"ok": True}

@app.post("/rdr/test")
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


# ------------------------------------------------------------------------------
# INVOICE EXTRACTOR
# ------------------------------------------------------------------------------
@app.get("/invoice-extractor/status")
def ie_status():
    if not IE_AVAILABLE: return {"available": False, "reason": "Module not installed"}
    try: return {"available": True, **get_dependency_status()}
    except Exception as e: return {"available": False, "reason": str(e)}

@app.post("/invoice-extractor/process")
async def ie_process(
    files: List[UploadFile]=File(...),
    tesseract_cmd: str=Form(""), poppler_bin: str=Form(""),
):
    if not IE_AVAILABLE: raise HTTPException(503, "Invoice extractor not available")
    import tempfile, os as _os
    tmp_files = []
    try:
        for upload in files:
            raw = await upload.read()
            suffix = Path(upload.filename or "file").suffix or ".pdf"
            with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
                tmp.write(raw); tmp_files.append(tmp.name)
        kwargs = {}
        if tesseract_cmd: kwargs["tesseract_cmd"] = tesseract_cmd
        if poppler_bin:   kwargs["poppler_bin"]   = poppler_bin
        bank_results, invoice_results, excel_bytes = ie_process_files(
            [Path(p) for p in tmp_files], **kwargs)
        all_txns = []
        for result, src in bank_results:
            meta = result["meta"]
            for txn in result["transactions"]:
                all_txns.append({**txn, "bank": meta.get("bank", ""),
                    "account_type": meta.get("account_type", ""), "source_file": src})
        all_inv = [{"source_file": src, **res} for res, src in invoice_results]
        excel_b64 = base64.b64encode(excel_bytes).decode() if excel_bytes else ""
        return {"bank_transactions": all_txns, "invoices": all_inv, "excel_b64": excel_b64}
    finally:
        for p in tmp_files:
            try: _os.unlink(p)
            except: pass


# ------------------------------------------------------------------------------
# OPEN BANKING
# ------------------------------------------------------------------------------
@app.get("/openbanking/status")
def ob_status():
    configured = bool(os.getenv("BASIQ_API_KEY"))
    return {"available": OB_AVAILABLE, "configured": configured}

@app.post("/openbanking/create-user")
def ob_create_user(body: dict=Body(...)):
    if not OB_AVAILABLE: raise HTTPException(503, "Open Banking not available")
    try:
        token = ob_auth.get_access_token()
        return ob_user.create_basiq_user_object(
            token, body.get("email",""), body.get("mobile",""),
            body.get("first_name",""), body.get("last_name",""))
    except Exception as e: raise HTTPException(500, str(e))

@app.get("/openbanking/accounts/{user_id}")
def ob_accounts(user_id: str):
    if not OB_AVAILABLE: raise HTTPException(503, "Open Banking not available")
    try:
        token = ob_auth.get_access_token()
        return ob_job.get_accounts(token, user_id)
    except Exception as e: raise HTTPException(500, str(e))

@app.get("/openbanking/transactions/{user_id}")
def ob_transactions(user_id: str):
    if not OB_AVAILABLE: raise HTTPException(503, "Open Banking not available")
    try:
        token = ob_auth.get_access_token()
        return ob_job.get_transactions(token, user_id)
    except Exception as e: raise HTTPException(500, str(e))


# ------------------------------------------------------------------------------
# STOCK / EQUITY TRADING  (integrated in backend/trading/)
# ------------------------------------------------------------------------------
import tempfile as _tempfile, uuid as _uuid

# The equity module lives at main_app/backend/trading/
# equity_pipeline.py adds that directory to sys.path so shared/equity/output imports resolve.
_EQUITY_DIR        = ROOT / "backend" / "trading"
_trading_module_ok = False
_trading_import_err = ""

try:
    # Pre-insert equity module dir so its internal imports resolve
    _eq_dir_str = str(_EQUITY_DIR)
    if _eq_dir_str not in sys.path:
        sys.path.insert(0, _eq_dir_str)
    from backend.trading.equity_pipeline import run_trading_pipeline, TradingPipelineResult
    from backend.trading.equity.equity_engine import disposals_to_df, income_to_df, summary_to_df
    from backend.trading.output.excel_exporter import export_to_excel
    from backend.trading.shared.local_cost_base_db import ensure_local_db, get_resolution_log
    _trading_module_ok = True
except Exception as _te:
    _trading_import_err = str(_te)


def _stocks_clean(df) -> list:
    if df is None or df.empty: return []
    d = df.copy()
    for c in d.columns:
        d[c] = d[c].apply(lambda x: None if (isinstance(x, float) and pd.isna(x)) else
                          (str(x) if hasattr(x, "strftime") or hasattr(x, "isoformat") else x))
    return d.to_dict(orient="records")


@app.get("/stocks/status")
def stocks_status():
    return {
        "available":   _trading_module_ok,
        "module_root": str(_EQUITY_DIR),
        "error":       _trading_import_err if not _trading_module_ok else None,
    }


@app.post("/stocks/analyze")
async def stocks_analyze(
    files:          List[UploadFile] = File(...),
    financial_year: str              = Form("2024-25"),
):
    """
    Accept one or more broker Excel/CSV files.
    Runs the full HSLedger equity CGT pipeline (FIFO, ATO rules).
    Returns disposals, income, summary, and missing-buy flags.
    """
    if not _trading_module_ok:
        raise HTTPException(503, f"Stock trading module not available: {_trading_import_err}")

    # Write uploads to a temp directory
    tmp_dir = _tempfile.mkdtemp(prefix="accfino_stocks_")
    try:
        for upload in files:
            raw  = await upload.read()
            dest = os.path.join(tmp_dir, upload.filename or f"file_{_uuid.uuid4()}.xlsx")
            with open(dest, "wb") as f:
                f.write(raw)

        local_db = str(_EQUITY_DIR / "data" / "local_cost_base_db.json")
        ensure_local_db(local_db)

        result: TradingPipelineResult = run_trading_pipeline(
            source        = tmp_dir,
            local_db_path = local_db,
            target_fy     = financial_year,
            interactive_missing = False,
        )

        disposals_df = disposals_to_df(result.disposals)
        income_df    = income_to_df(result.income)
        summary_df   = summary_to_df({financial_year: result.summary})

        # Missing buys
        missing = []
        for flag in (result.missing_buys or []):
            missing.append({
                "code":           flag.code,
                "qty_unmatched":  flag.qty_unmatched,
                "disposal_date":  str(flag.disposal_date),
                "broker":         flag.broker,
                "reference":      flag.reference,
                "proceeds_per_unit": flag.proceeds_per_unit,
            })

        return {
            "financial_year":  financial_year,
            "disposals":       _stocks_clean(disposals_df),
            "income":          _stocks_clean(income_df),
            "summary":         _stocks_clean(summary_df),
            "missing_buys":    missing,
            "total_disposals": len(result.disposals),
            "load_report":     result.load_report.__dict__ if result.load_report else {},
        }
    except Exception as e:
        raise HTTPException(500, f"Pipeline failed: {e}")
    finally:
        import shutil as _shutil
        _shutil.rmtree(tmp_dir, ignore_errors=True)


@app.post("/stocks/export")
async def stocks_export(
    files:          List[UploadFile] = File(...),
    financial_year: str              = Form("2024-25"),
):
    """Run the full pipeline and return a formatted Excel report."""
    if not _trading_module_ok:
        raise HTTPException(503, "Stock trading module not available")

    tmp_dir    = _tempfile.mkdtemp(prefix="accfino_stocks_")
    output_xlsx = os.path.join(tmp_dir, "report.xlsx")
    try:
        for upload in files:
            raw  = await upload.read()
            dest = os.path.join(tmp_dir, upload.filename or f"file_{_uuid.uuid4()}.xlsx")
            with open(dest, "wb") as f:
                f.write(raw)

        local_db = str(_EQUITY_DIR / "data" / "local_cost_base_db.json")
        ensure_local_db(local_db)

        result = run_trading_pipeline(
            source        = tmp_dir,
            output_path   = output_xlsx,
            local_db_path = local_db,
            target_fy     = financial_year,
        )

        if not os.path.exists(output_xlsx):
            # Build it manually via exporter
            export_to_excel(result, output_path=output_xlsx, target_fy=financial_year)

        with open(output_xlsx, "rb") as f:
            content = f.read()

        return Response(
            content    = content,
            media_type = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            headers    = {"Content-Disposition": f"attachment; filename=HSLedger_CGT_{financial_year}.xlsx"},
        )
    except Exception as e:
        raise HTTPException(500, f"Export failed: {e}")
    finally:
        import shutil as _shutil
        _shutil.rmtree(tmp_dir, ignore_errors=True)


# ------------------------------------------------------------------------------
# OPEN BANKING - CSV (normalised, ready for reconciliation)
# ------------------------------------------------------------------------------
@app.post("/openbanking/fetch-and-normalise")
def ob_fetch_normalise(body: dict = Body(...)):
    """
    Fetch transactions from Open Banking, save as normalised CSV,
    and return rows ready to feed into /reconcile/process.
    Mirrors the original open_banking_connector.py logic.
    """
    if not OB_AVAILABLE:
        raise HTTPException(503, "Open Banking module not available")
    try:
        from backend.open_banking import csv_exporter as ob_csv_exp
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
        csv_path = str(ROOT / "data" / f"ob_{user_id}_{account_id}.csv")
        pd.DataFrame(rows).to_csv(csv_path, index=False)

        return {"rows": rows, "count": len(rows), "csv_saved": csv_path}
    except Exception as e:
        raise HTTPException(500, str(e))


# ------------------------------------------------------------------------------
# FILE MANAGER - browse main_app/data, read/write files & SQLite tables
# ------------------------------------------------------------------------------
import csv        as _csv
import math       as _math
import pickle     as _pickle
import sqlite3    as _sqlite3
from urllib.parse import unquote as _unquote
import pandas     as _pd_fm

# _DATA_ROOT is resolved once at import time - absolute, immune to cwd changes
_DATA_ROOT = Path(__file__).parent.joinpath("data").resolve()


def _node_type(p: Path) -> str:
    if p.is_dir():                              return "folder"
    if p.suffix.lower() in (".db", ".sqlite"): return "database"
    return "file"


def _safe_val(v) -> str:
    """Convert any Python value to a clean, JSON-safe string."""
    try:
        if v is None:
            return ""
        if isinstance(v, float) and (_math.isnan(v) or _math.isinf(v)):
            return ""
        s = str(v)
        # Strip null bytes and non-printable control chars (keep newlines as space)
        s = "".join(c if c >= " " or c in "\t" else " " for c in s)
        return s[:500]
    except Exception:
        return ""


def _safe_rows(raw: list, cols: list) -> list:
    """Return list of {col: safe_str} dicts - every value is JSON-safe."""
    str_cols = [str(c) for c in cols]
    result   = []
    for row in raw:
        if isinstance(row, dict):
            result.append({c: _safe_val(row.get(orig)) for c, orig in zip(str_cols, cols)})
        else:
            result.append({c: _safe_val(getattr(row, str(orig), "")) for c, orig in zip(str_cols, cols)})
    return result


def _resolve_path(raw: str) -> Path:
    """
    Decode a URL-encoded relative path, normalise separators,
    resolve to an absolute path inside _DATA_ROOT.
    Raises HTTPException 403 if path escapes DATA_ROOT.
    Raises HTTPException 404 if path does not exist.
    """
    # 1. URL-decode (%20 - space, %2F - /, etc.)
    decoded = _unquote(raw or "")
    # 2. Normalise: forward slashes only, no leading slash
    clean   = decoded.replace("\\", "/").replace("\\\\", "/").strip("/")
    if not clean:
        raise HTTPException(400, "Empty path")
    # 3. Resolve to absolute
    target  = (_DATA_ROOT / clean).resolve()
    # 4. Security: must stay inside DATA_ROOT
    try:
        target.relative_to(_DATA_ROOT)
    except ValueError:
        raise HTTPException(403, f"Access denied: {clean}")
    return target


# -- Tree ----------------------------------------------------------------------

@app.get("/filemanager/tree")
def fm_tree():
    """Return full recursive tree of DATA_ROOT for the file manager, plus a
    synthetic 'Postgres Database' node exposing every real app table
    (chart_of_accounts, pricing_plans, rdr_rules, groq_key_pool, etc.) --
    same browsing/editing UI as any other file/table in this page, just
    backed by the actual application database instead of a stray .db file."""
    def _walk(base: Path, rel: str) -> list:
        items = []
        try:
            for child in sorted(base.iterdir()):
                rel_path = f"{rel}/{child.name}" if rel else child.name
                node = {
                    "name": child.name,
                    "path": rel_path,          # forward-slash relative path
                    "type": _node_type(child),
                }
                if child.is_dir():
                    node["children"] = _walk(child, rel_path)
                elif child.suffix.lower() in (".db", ".sqlite"):
                    try:
                        cx = _sqlite3.connect(str(child))
                        node["tables"] = [
                            r[0] for r in cx.execute(
                                "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
                            ).fetchall()
                        ]
                        cx.close()
                    except Exception:
                        node["tables"] = []
                items.append(node)
        except PermissionError:
            pass
        return items

    tree = []
    try:
        from sqlalchemy import inspect as _sa_inspect
        from db_app.database import engine as _pg_engine
        from db_app.known_tables import get_accfino_table_names
        accfino_tables = get_accfino_table_names()
        pg_tables = sorted(t for t in _sa_inspect(_pg_engine).get_table_names() if t in accfino_tables)
        tree.append({
            "name": "Postgres Database",
            "path": "__postgres_db__",
            "type": "database",
            "tables": pg_tables,
        })
    except Exception as _e:
        logger.warning(f"filemanager: could not list Postgres tables: {_e}")

    if _DATA_ROOT.exists():
        tree.extend(_walk(_DATA_ROOT, ""))
    else:
        return {"tree": tree, "data_root": str(_DATA_ROOT), "error": "DATA_ROOT does not exist"}

    return {"tree": tree, "data_root": str(_DATA_ROOT)}


# -- Read ----------------------------------------------------------------------

@app.get("/filemanager/read/{file_path:path}")
def fm_read(file_path: str, table: str = ""):
    """
    Read a file, SQLite table, or Postgres table and return {columns, rows, source}.
    file_path is a URL-encoded, forward-slash relative path from DATA_ROOT,
    EXCEPT for the sentinel "__postgres_db__" which reads from the real
    application database instead of a file on disk.
    All returned values are plain JSON-safe strings.
    """
    if file_path == "__postgres_db__":
        if not table:
            raise HTTPException(400, "table is required to read from the Postgres database")
        from db_app.known_tables import get_accfino_table_names
        if table not in get_accfino_table_names():
            raise HTTPException(404, f"Table {table!r} does not exist")
        from sqlalchemy import text as _sa_text, inspect as _sa_inspect
        from db_app.database import SessionLocal as _PgSession, engine as _pg_engine
        insp = _sa_inspect(_pg_engine)
        if not insp.has_table(table):
            raise HTTPException(404, f"Table {table!r} does not exist in Postgres")
        db = _PgSession()
        try:
            result = db.execute(_sa_text(f'SELECT * FROM "{table}" LIMIT 1000'))
            cols = list(result.keys())
            raw  = [dict(zip(cols, row)) for row in result.fetchall()]
            return {"columns": cols, "rows": _safe_rows(raw, cols),
                    "source": f"postgres - {len(raw)} rows"}
        except Exception as e:
            raise HTTPException(500, f"Postgres read error: {e}")
        finally:
            db.close()

    target = _resolve_path(file_path)

    if not target.exists():
        raise HTTPException(404, f"File not found: {file_path!r} - {target}")

    ext = target.suffix.lower()

    # -- SQLite table ----------------------------------------------------------
    if table and ext in (".db", ".sqlite"):
        try:
            cx   = _sqlite3.connect(str(target))
            cols = [r[1] for r in cx.execute(f"PRAGMA table_info('{table}')").fetchall()]
            if not cols:
                cx.close()
                raise HTTPException(404, f"Table {table!r} not found in {target.name}")
            raw  = [dict(zip(cols, row)) for row in
                    cx.execute(f'SELECT * FROM "{table}" LIMIT 1000').fetchall()]
            cx.close()
            return {"columns": cols, "rows": _safe_rows(raw, cols),
                    "source": f"sqlite - {len(raw)} rows"}
        except HTTPException:
            raise
        except Exception as e:
            raise HTTPException(500, f"SQLite error: {e}")

    # -- CSV - parse into columns/rows for tabular editing -------------------
    if ext == ".csv":
        try:
            import csv as _csv_r, io as _io
            raw_bytes = target.read_bytes()
            if raw_bytes.startswith(b"\xef\xbb\xbf"):
                raw_bytes = raw_bytes[3:]
            text = raw_bytes.decode("utf-8", errors="replace")
            text = text.replace("\r\n", "\n").replace("\r", "\n")
            reader = _csv_r.DictReader(_io.StringIO(text))
            items  = [dict(row) for row in reader]
            cols   = list(reader.fieldnames or (items[0].keys() if items else []))
            rows   = [{c: _safe_val(r.get(c, "")) for c in cols} for r in items[:2000]]
            return {
                "columns": cols,
                "rows":    rows,
                "source":  f"csv - {len(rows)} rows",
            }
        except Exception as e:
            raise HTTPException(500, f"CSV read error: {e}")

    # -- JSON - always tabular -------------------------------------------------
    if ext in (".json", ".jsonl"):
        try:
            import json as _j
            raw_bytes = target.read_bytes()
            if raw_bytes.startswith(b"\xef\xbb\xbf"):
                raw_bytes = raw_bytes[3:]
            text = raw_bytes.decode("utf-8", errors="replace")
            if ext == ".jsonl":
                items = [_j.loads(ln) for ln in text.splitlines() if ln.strip()]
            else:
                items = _j.loads(text)
            if isinstance(items, list) and items and isinstance(items[0], dict):
                # Collect all keys across all rows (some rows may have extra keys)
                all_keys = list(dict.fromkeys(k for row in items[:500] for k in row))
                cols = [str(c) for c in all_keys]
                return {"columns": cols, "rows": _safe_rows(items[:500], all_keys),
                        "source": f"json - {len(items)} rows"}
            elif isinstance(items, dict):
                # If values are dicts (e.g. pricing.json), expand into tabular rows
                first_val = next(iter(items.values()), None)
                if isinstance(first_val, dict):
                    all_keys = list(dict.fromkeys(
                        k for v in items.values() if isinstance(v, dict) for k in v
                    ))
                    cols = ["_key"] + all_keys
                    rows = []
                    for k, v in list(items.items())[:500]:
                        if isinstance(v, dict):
                            row = {"_key": _safe_val(k)}
                            row.update({c: _safe_val(v.get(c, "")) for c in all_keys})
                        else:
                            row = {"_key": _safe_val(k), **{c: "" for c in all_keys}}
                        rows.append(row)
                    return {"columns": cols, "rows": rows,
                            "source": f"json - {len(rows)} entries"}
                else:
                    rows = [{"key": _safe_val(k), "value": _safe_val(v)}
                            for k, v in list(items.items())[:500]]
                    return {"columns": ["key", "value"], "rows": rows,
                            "source": f"json - {len(rows)} entries"}
            elif isinstance(items, list):
                rows = [{"#": str(i+1), "value": _safe_val(v)}
                        for i, v in enumerate(items[:500])]
                return {"columns": ["#", "value"], "rows": rows,
                        "source": f"json - {len(items)} items"}
            else:
                return {"columns": ["value"], "rows": [{"value": _safe_val(items)}],
                        "source": "json"}
        except Exception as e:
            raise HTTPException(500, f"JSON read error: {e}")

    # -- Pickle ----------------------------------------------------------------
    if ext in (".pkl", ".pickle"):
        try:
            obj = _pd_fm.read_pickle(str(target))
            if isinstance(obj, _pd_fm.DataFrame):
                df   = obj.head(500)
                cols = [str(c) for c in df.columns]
                rows = []
                for _, row in df.iterrows():
                    rows.append({c: _safe_val(v) for c, v in zip(cols, row)})
                return {"columns": cols, "rows": rows,
                        "source": f"pickle - DataFrame {len(df)}r - {len(cols)}c"}
            elif isinstance(obj, dict):
                rows = [{"key": _safe_val(k), "value": _safe_val(v)}
                        for k, v in list(obj.items())[:500]]
                return {"columns": ["key", "value"], "rows": rows, "source": "pickle - dict"}
            elif isinstance(obj, list):
                if obj and isinstance(obj[0], dict):
                    cols = [str(k) for k in obj[0].keys()]
                    return {"columns": cols, "rows": _safe_rows(obj[:500], cols), "source": "pickle - list"}
                rows = [{"#": str(i), "value": _safe_val(v)} for i, v in enumerate(obj[:500])]
                return {"columns": ["#", "value"], "rows": rows, "source": "pickle - list"}
            else:
                return {"columns": ["type", "repr"],
                        "rows": [{"type": type(obj).__name__, "repr": _safe_val(obj)[:2000]}],
                        "source": "pickle"}
        except Exception as e:
            return {"columns": ["error"], "rows": [{"error": f"Cannot read pickle: {e}"}],
                    "source": "pickle - error"}

    # -- PDF -------------------------------------------------------------------
    # Run PDF extraction in a separate subprocess so any crash cannot
    # kill the uvicorn worker process.
    if ext == ".pdf":
        import subprocess, sys, json as _json_pdf
        script = f"""
import sys, json, traceback
try:
    import pdfplumber
    rows = []
    n_pages = 0
    with pdfplumber.open({str(target)!r}) as pdf:
        n_pages = len(pdf.pages)
        for pnum, page in enumerate(pdf.pages[:50], start=1):
            try:
                txt = page.extract_text() or ""
            except Exception:
                txt = ""
            for line in txt.splitlines():
                line = line.strip()
                if line:
                    rows.append({{"page": str(pnum), "text": line[:400]}})
    if not rows:
        rows = [{{"page": "-", "text": "(No extractable text - may be scanned PDF)"}}]
    print(json.dumps({{"ok": True, "rows": rows[:500], "n_pages": n_pages}}))
except Exception as e:
    print(json.dumps({{"ok": False, "error": str(e)[:300]}}))
"""
        try:
            result = subprocess.run(
                [sys.executable, "-c", script],
                capture_output=True, text=True, timeout=30
            )
            out = result.stdout.strip()
            if out:
                data = _json_pdf.loads(out)
                if data.get("ok"):
                    return {
                        "columns": ["page", "text"],
                        "rows":    data["rows"],
                        "source":  f"pdf - {data['n_pages']} page(s) - {target.stat().st_size // 1024} KB",
                        "display": "raw",
                    }
                else:
                    return {
                        "columns": ["error"],
                        "rows":    [{"error": data.get("error", "Unknown PDF error")}],
                        "source":  "pdf - error",
                    }
        except subprocess.TimeoutExpired:
            return {"columns": ["error"], "rows": [{"error": "PDF processing timed out (30s)"}], "source": "pdf"}
        except Exception as e:
            pass

        # Fallback: just show file info
        size_kb = target.stat().st_size // 1024
        return {
            "columns": ["property", "value"],
            "rows": [
                {"property": "filename", "value": target.name},
                {"property": "size",     "value": f"{size_kb} KB"},
                {"property": "note",     "value": "PDF text extraction unavailable"},
            ],
            "source": "pdf - info only",
        }

    # -- Plain text fallback ---------------------------------------------------
    try:
        raw_bytes = target.read_bytes()
        if raw_bytes.startswith(b"\xef\xbb\xbf"):
            raw_bytes = raw_bytes[3:]
        text  = raw_bytes.decode("utf-8", errors="replace")
        text  = text.replace("\r\n", "\n").replace("\r", "\n")
        lines = text.splitlines()[:1000]
        rows  = [{"#": str(i + 1), "line": _safe_val(ln)} for i, ln in enumerate(lines)]
        return {"columns": ["#", "line"], "rows": rows,
                "source": f"text - {len(rows)} lines"}
    except Exception as e:
        raise HTTPException(500, f"Cannot read file: {e}")


# -- Save ----------------------------------------------------------------------

@app.post("/filemanager/save")
def fm_save(body: dict = Body(...)):
    """Save edited rows back to a CSV file, SQLite table, or Postgres table."""
    path   = body.get("path",   "")
    table  = body.get("table",  "")
    rows   = body.get("rows",   [])
    source = body.get("source", "")

    if path == "__postgres_db__":
        if not table:
            raise HTTPException(400, "table is required to save to the Postgres database")
        from db_app.known_tables import get_accfino_table_names
        if table not in get_accfino_table_names():
            raise HTTPException(404, f"Table {table!r} does not exist")
        # Deliberately NOT a delete-all-then-reinsert like the SQLite path
        # below -- a Postgres table can hold far more rows than the 1000-row
        # page currently loaded in the browser, so wholesale replace here
        # would silently destroy every row outside the current view.
        # Instead: upsert each row by its real primary key; use the
        # per-row Delete button (fm_delete_row) to remove rows.
        from sqlalchemy import text as _sa_text, inspect as _sa_inspect
        from db_app.database import SessionLocal as _PgSession, engine as _pg_engine
        insp = _sa_inspect(_pg_engine)
        if not insp.has_table(table):
            raise HTTPException(404, f"Table {table!r} does not exist in Postgres")
        pk = insp.get_pk_constraint(table).get("constrained_columns") or []
        if not pk:
            raise HTTPException(400, f"Table {table!r} has no primary key -- cannot save generically")
        pk_col = pk[0]

        db = _PgSession()
        try:
            saved = 0
            for row in rows:
                if pk_col not in row or row[pk_col] in (None, ""):
                    continue  # skip incomplete rows rather than guessing a PK
                cols = [c for c in row.keys() if c != pk_col]
                if not cols:
                    continue
                set_clause = ", ".join(f'"{c}" = :{c}' for c in cols)
                params = {c: row[c] for c in cols}
                params["_pk"] = row[pk_col]
                result = db.execute(_sa_text(f'UPDATE "{table}" SET {set_clause} WHERE "{pk_col}" = :_pk'), params)
                if result.rowcount == 0:
                    # Row doesn't exist yet -- insert it (covers rows added via "Add Row")
                    all_cols = [pk_col] + cols
                    col_list = ", ".join(f'"{c}"' for c in all_cols)
                    val_list = ", ".join(f':{c}' for c in all_cols)
                    insert_params = {c: row.get(c) for c in all_cols}
                    db.execute(_sa_text(f'INSERT INTO "{table}" ({col_list}) VALUES ({val_list})'), insert_params)
                saved += 1
            db.commit()
            return {"ok": True, "saved": saved}
        except Exception as e:
            db.rollback()
            raise HTTPException(500, f"Postgres save error: {e}")
        finally:
            db.close()

    target = _resolve_path(path)

    if "sqlite" in source and table:
        try:
            cx   = _sqlite3.connect(str(target))
            cols = [r[1] for r in cx.execute(f"PRAGMA table_info('{table}')").fetchall()]
            cx.execute(f'DELETE FROM "{table}"')
            for row in rows:
                vals = [row.get(c) for c in cols]
                cx.execute(
                    f'INSERT INTO "{table}" ({",".join(cols)}) VALUES ({",".join(["?"]*len(cols))})',
                    vals
                )
            cx.commit(); cx.close()
            return {"ok": True, "saved": len(rows)}
        except Exception as e:
            raise HTTPException(500, f"SQLite save error: {e}")

    if "csv" in source or target.suffix.lower() == ".csv":
        if not rows:
            return {"ok": True, "saved": 0}
        cols = list(rows[0].keys())
        with open(target, "w", newline="", encoding="utf-8") as f:
            w = _csv.DictWriter(f, fieldnames=cols, extrasaction="ignore")
            w.writeheader(); w.writerows(rows)
        return {"ok": True, "saved": len(rows)}

    if target.suffix.lower() in (".json", ".jsonl"):
        import json as _js
        if not rows:
            return {"ok": True, "saved": 0}
        if target.suffix.lower() == ".jsonl":
            with open(target, "w", encoding="utf-8") as f:
                for row in rows:
                    f.write(_js.dumps(row) + "\n")
        else:
            with open(target, "w", encoding="utf-8") as f:
                _js.dump(rows, f, indent=2, ensure_ascii=False)
        return {"ok": True, "saved": len(rows)}

    raise HTTPException(400, f"Save not supported for: {source or target.suffix}")


# -- Delete row ----------------------------------------------------------------

@app.delete("/filemanager/delete-row")
def fm_delete_row(body: dict = Body(...)):
    """Delete a single row from a SQLite table, or a Postgres table, by primary key."""
    path   = body.get("path",   "")
    table  = body.get("table",  "")
    row_id = body.get("row_id")
    pk_col = body.get("pk_col", "id")

    if not table:
        raise HTTPException(400, "table is required for row delete")

    if path == "__postgres_db__":
        from db_app.known_tables import get_accfino_table_names
        if table not in get_accfino_table_names():
            raise HTTPException(404, f"Table {table!r} does not exist")
        from sqlalchemy import text as _sa_text, inspect as _sa_inspect
        from db_app.database import SessionLocal as _PgSession, engine as _pg_engine
        insp = _sa_inspect(_pg_engine)
        if not insp.has_table(table):
            raise HTTPException(404, f"Table {table!r} does not exist in Postgres")
        # Trust the real PK column from the DB over whatever the frontend
        # guessed (it defaults to "id" or the first column when it can't tell).
        pk = insp.get_pk_constraint(table).get("constrained_columns") or []
        real_pk_col = pk[0] if pk else pk_col
        db = _PgSession()
        try:
            result = db.execute(_sa_text(f'DELETE FROM "{table}" WHERE "{real_pk_col}" = :id'), {"id": row_id})
            db.commit()
            if result.rowcount == 0:
                raise HTTPException(404, "Row not found")
            return {"ok": True}
        except HTTPException:
            raise
        except Exception as e:
            db.rollback()
            raise HTTPException(500, f"Postgres delete error: {e}")
        finally:
            db.close()

    target = _resolve_path(path)
    try:
        cx = _sqlite3.connect(str(target))
        cx.execute(f'DELETE FROM "{table}" WHERE "{pk_col}" = ?', (row_id,))
        cx.commit(); cx.close()
        return {"ok": True}
    except Exception as e:
        raise HTTPException(500, f"Delete error: {e}")


# ------------------------------------------------------------------------------
# LICENCE MANAGEMENT
# ------------------------------------------------------------------------------
from db_app.database import SessionLocal as _SL
from db_app.models.user import User as _User


def _get_db_session():
    db = _SL()
    try:
        yield db
    finally:
        db.close()


# All module keys available for licence assignment
ALL_MODULES = [
    "dashboard", "accounting", "reconciliation", "trading",
    "cash-flow", "invoice", "admin", "file-manager", "licence", "payroll", "lending"
]

@app.get("/licence/list")
def licence_list():
    """All users with their licence data including module permissions."""
    import json as _json
    db = _SL()
    try:
        # Ensure modules column exists (migration for existing DBs)
        try:
            import sqlite3 as _s3
            from db_app.database import _DB_FILE as _dbf
            _dbf_str = str(_dbf)
            cx = _s3.connect(_dbf_str)
            cols = [r[1] for r in cx.execute("PRAGMA table_info(licence_records)").fetchall()]
            if "modules" not in cols:
                cx.execute("ALTER TABLE licence_records ADD COLUMN modules VARCHAR(1000) DEFAULT ''")
                cx.commit()
            cx.close()
        except Exception as _me:
            print(f"[licence] migration warning: {_me}")

        users = db.query(_User).all()
        result = []
        for u in users:
            lic = db.query(LicenceRecord).filter(LicenceRecord.user_id == u.id).first()
            # Parse modules - empty = base plan (dashboard + reconciliation)
            BASE_MODULES = ["dashboard", "reconciliation"]
            raw_mods = (lic.modules if lic and lic.modules else "")
            try:
                mods = _json.loads(raw_mods) if raw_mods and raw_mods.strip().startswith('[') else BASE_MODULES[:]
            except Exception:
                mods = BASE_MODULES[:]
            # Remove admin-only modules from user view
            mods = [m for m in mods if m not in ('admin', 'file-manager', 'licence')]
            result.append({
                "user_id":      u.id,
                "username":     u.username,
                "full_name":    u.full_name or "",
                "email":        u.email,
                "roles":        [r.name for r in u.roles],
                "licence_id":   lic.id           if lic else None,
                "licence_type": lic.licence_type if lic else "demo",
                "payment_mode": lic.payment_mode if lic else "",
                "start_date":   lic.start_date   if lic else "",
                "end_date":     lic.end_date     if lic else "",
                "notes":        lic.notes        if lic else "",
                "modules":      mods,
                "phone":        getattr(u, "phone", "") or "",
                "home_company": getattr(u, "home_company", "") or "",
            })
        return result
    finally:
        db.close()


@app.get("/licence/my-modules")
def my_modules(user_id: int):
    """Return list of module keys the user is allowed to access."""
    import json as _json
    BASE_MODULES = ["dashboard", "reconciliation"]
    db = _SL()
    try:
        user = db.query(_User).filter(_User.id == user_id).first()
        if not user:
            return {"modules": BASE_MODULES}
        # Admins always get all modules
        if any(r.name == "admin" for r in user.roles):
            return {"modules": ALL_MODULES}
        lic = db.query(LicenceRecord).filter(LicenceRecord.user_id == user_id).first()
        if not lic or not lic.modules:
            return {"modules": BASE_MODULES}
        try:
            mods = _json.loads(lic.modules)
            if not mods:
                return {"modules": BASE_MODULES}
            # Remove admin-only modules
            mods = [m for m in mods if m not in ('admin', 'file-manager', 'licence')]
            return {"modules": mods}
        except Exception:
            return {"modules": BASE_MODULES}
    finally:
        db.close()


@app.post("/licence/save")
def licence_save(body: dict = Body(...)):
    """Create or update a licence record for a user including module permissions."""
    import json as _json
    db = _SL()
    try:
        user_id = body.get("user_id")
        if not user_id:
            raise HTTPException(400, "user_id required")
        lic = db.query(LicenceRecord).filter(LicenceRecord.user_id == user_id).first()
        if not lic:
            lic = LicenceRecord(user_id=user_id)
            db.add(lic)
        lic.licence_type = body.get("licence_type", "demo")
        lic.payment_mode = body.get("payment_mode", "")
        lic.start_date   = body.get("start_date",   "")
        lic.end_date     = body.get("end_date",     "")
        lic.notes        = body.get("notes",        "")
        mods = body.get("modules", ALL_MODULES)
        lic.modules      = _json.dumps(mods)
        db.commit()
        return {"ok": True}
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(500, str(e))
    finally:
        db.close()


@app.delete("/licence/user/{user_id}")
def licence_delete_user(user_id: int):
    """Delete a user and their licence record.
    SQLite does not enforce FK cascades unless PRAGMA foreign_keys=ON,
    so we manually delete related rows first.
    """
    import sqlite3 as _s3
    from db_app.database import _DB_FILE as _dbf
    try:
        cx = _s3.connect(str(_dbf))
        cx.execute("PRAGMA foreign_keys = ON")
        # Check user exists
        row = cx.execute("SELECT id FROM users WHERE id=?", (user_id,)).fetchone()
        if not row:
            cx.close()
            raise HTTPException(404, "User not found")
        # Delete related rows in correct order
        cx.execute("DELETE FROM user_roles WHERE user_id=?",        (user_id,))
        cx.execute("DELETE FROM licence_records WHERE user_id=?",   (user_id,))
        cx.execute("DELETE FROM password_reset_tokens WHERE user_id=?", (user_id,))
        cx.execute("DELETE FROM transactions WHERE user_id=?",      (user_id,))
        cx.execute("DELETE FROM users WHERE id=?",                   (user_id,))
        cx.commit()
        cx.close()
        return {"ok": True}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(500, f"Delete failed: {e}")


@app.patch("/licence/user/{user_id}")
def licence_update_user(user_id: int, body: dict = Body(...)):
    """Update user details (username, email, full_name)."""
    db = _SL()
    try:
        user = db.query(_User).filter(_User.id == user_id).first()
        if not user:
            raise HTTPException(404, "User not found")
        if "username"     in body: user.username     = body["username"]
        if "email"        in body: user.email        = body["email"]
        if "full_name"    in body: user.full_name    = body["full_name"]
        if "phone"        in body: user.phone        = body.get("phone", "") or ""
        if "home_company" in body: user.home_company = body.get("home_company", "") or ""
        db.commit()
        return {"ok": True}
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(500, str(e))
    finally:
        db.close()

# ------------------------------------------------------------------------------
# PRICING MANAGEMENT - Postgres-backed (pricing_plans table, see
# db_app/models/app_data.py PricingPlan). Falls back to payments.py's PLANS
# (which itself falls back further to pricing.json then hardcoded defaults)
# only if the DB is unreachable -- matches the pattern used everywhere else.
# ------------------------------------------------------------------------------
def _load_pricing() -> dict:
    """Load pricing -- Postgres is authoritative."""
    try:
        from db_app.database import SessionLocal
        from db_app.models.app_data import PricingPlan
        db = SessionLocal()
        try:
            rows = db.query(PricingPlan).order_by(PricingPlan.sort_order).all()
            if rows:
                return {r.slug: r.to_dict() for r in rows}
        finally:
            db.close()
    except Exception:
        pass
    # Fallback to payments.py PLANS (JSON file / hardcoded, in that order)
    try:
        from db_app.api.payments import PLANS
        return PLANS
    except Exception:
        return {}

def _save_pricing(data: dict):
    """Admin - replace the full pricing config. Upserts every plan slug
    in `data` into the pricing_plans table's real columns; slugs no
    longer present in `data` are left alone (matches the old file's
    "whole document" replace semantics closely enough without deleting
    plans an admin didn't intend to touch in an unrelated partial
    payload)."""
    from db_app.database import SessionLocal
    from db_app.models.app_data import PricingPlan
    db = SessionLocal()
    try:
        for i, (slug, plan) in enumerate(data.items()):
            row = db.get(PricingPlan, slug)
            if not row:
                row = PricingPlan(slug=slug, sort_order=i)
                db.add(row)
            row.name = plan.get("name")
            row.description = plan.get("description")
            row.price_monthly = plan.get("price_monthly", 0)
            row.price_yearly = plan.get("price_yearly", 0)
            row.badge = plan.get("badge")
            row.highlight = bool(plan.get("highlight", False))
            row.category = plan.get("category")
            row.features = plan.get("features", [])
            row.modules = plan.get("modules", [])
            row.price_effective_from = plan.get("price_effective_from")
        db.commit()
    finally:
        db.close()

@app.get("/payments/plans")
def payments_get_plans():
    """Alias of /pricing/plans - kept for backward compatibility."""
    return _load_pricing()


@app.get("/pricing/plans")
def pricing_get():
    """Public - return all plan definitions."""
    return _load_pricing()

@app.post("/pricing/plans")
def pricing_save(body: dict = Body(...)):
    """Admin - save full pricing config."""
    _save_pricing(body)
    return {"ok": True}

@app.patch("/pricing/plans/{plan_id}")
def pricing_update_plan(plan_id: str, body: dict = Body(...)):
    """Admin - update a single plan's pricing fields (partial update --
    only fields present in body are changed)."""
    from db_app.database import SessionLocal
    from db_app.models.app_data import PricingPlan
    db = SessionLocal()
    try:
        row = db.get(PricingPlan, plan_id)
        if not row:
            raise HTTPException(404, f"Plan {plan_id!r} not found")
        for field in ("name", "description", "price_monthly", "price_yearly", "badge",
                      "highlight", "category", "features", "modules", "price_effective_from"):
            if field in body:
                setattr(row, field, body[field])
        db.commit()
        return {"ok": True, "plan": row.to_dict()}
    finally:
        db.close()

# -- Strip /api prefix middleware ----------------------------------------------
# In production the React frontend calls /api/banks, /api/sessions etc.
# This middleware strips the /api prefix before FastAPI processes the request.
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request as _SReq

class StripApiPrefix(BaseHTTPMiddleware):
    async def dispatch(self, request: _SReq, call_next):
        scope = request.scope
        path  = scope.get("path", "")
        if path.startswith("/api/"):
            new_path = path[4:]                    # "/api/banks" - "/banks"
            scope["path"] = new_path
            qs = scope.get("query_string", b"")
            scope["raw_path"] = (
                new_path + ("?" + qs.decode() if qs else "")
            ).encode()
        elif path == "/api":
            scope["path"]     = "/"
            scope["raw_path"] = b"/"
        # All other paths pass through unchanged
        return await call_next(request)

app.add_middleware(StripApiPrefix)

# -- Serve React SPA + Marketing Site -----------------------------------------
# Registered LAST so all /api/* routes take priority.
#
# URL routing:
#   /                        - index-marketing.html  (public marketing site)
#   /login, /reset-password  - index.html            (React SPA - public)
#   /upgrade                 - index.html            (React SPA - public)
#   /dashboard, /reconciliation, /trading, etc.
#                            - index.html            (React SPA - auth guarded)
#   /assets/*                - StaticFiles           (JS / CSS / images)
# -----------------------------------------------------------------------------
from fastapi.staticfiles import StaticFiles
from fastapi.responses   import FileResponse as _FileResponse

_ROOT       = Path(__file__).parent.parent          # project root
_DIST       = _ROOT / "frontend" / "dist"
_PUBLIC     = _ROOT / "frontend" / "public"   # Vite public folder (dev mode)

# Marketing page: prefer built dist/, fall back to source public/ (local dev)
_MARKETING  = _DIST / "index-marketing.html" if (_DIST / "index-marketing.html").exists()               else _PUBLIC / "index-marketing.html"
_APP_INDEX  = _DIST / "index.html"


def _serve_marketing():
    """Return the marketing homepage with pricing always injected from pricing.json.

    Three-layer sync so homepage, login and upgrade always match pricing.json:
      Layer 1 - server injects window.__ACCFINO_PRICING__ into <head> (instant, no flash)
      Layer 2 - client JS uses window.__ACCFINO_PRICING__ before any fetch completes
      Layer 3 - client fetches /api/pricing/plans and re-renders (updates after load)

    Additionally regenerates the BUNDLES variable inside the marketing script so
    bundle vs module card layout stays correct when pricing.json changes.
    """
    if not _MARKETING.exists():
        return {"error": "Marketing page not found. Check frontend/public/index-marketing.html"}
    import json as _json_mkt, re as _re_mkt
    from fastapi.responses import HTMLResponse as _HTMLResponse
    html = _MARKETING.read_text(encoding="utf-8")
    try:
        pricing = _load_pricing()

        # -- Layer 1: inject window.__ACCFINO_PRICING__ into <head> ----------
        pricing_json = _json_mkt.dumps(pricing, ensure_ascii=False)
        inject = f'''<script>
// Pricing injected server-side from pricing.json - single source of truth
window.__ACCFINO_PRICING__ = {pricing_json};
</script>'''
        html = html.replace("</head>", inject + "\n</head>", 1)

        # -- Layer 2: keep DEFAULTS fallback in sync with pricing.json --------
        # Replace the hardcoded DEFAULTS object so the page renders correctly
        # even if window.__ACCFINO_PRICING__ is not set (e.g. cached HTML).
        defaults_js = _json_mkt.dumps(pricing, ensure_ascii=False, separators=(',', ':'))
        html = _re_mkt.sub(
            r'var DEFAULTS=window\.__ACCFINO_PRICING__\|\|\{.*?\};',
            f'var DEFAULTS=window.__ACCFINO_PRICING__||{defaults_js};',
            html, count=1, flags=_re_mkt.DOTALL
        )

        # -- Layer 3: regenerate BUNDLES array from pricing.json ---------------
        # A plan is a "bundle" if it includes 2+ non-base modules.
        _base_mods = {"dashboard", "reconciliation"}
        bundle_keys = _json_mkt.dumps([
            k for k, p in pricing.items()
            if sum(1 for m in p.get("modules", []) if m not in _base_mods) >= 2
        ])
        html = _re_mkt.sub(r'BUNDLES=\[.*?\]', f'BUNDLES={bundle_keys}', html)

    except Exception:
        pass  # Fall back gracefully - client-side fetch still works
    return _HTMLResponse(content=html, status_code=200)


def _serve_app() -> _FileResponse:
    """Return the React SPA shell (only available after npm run build)."""
    if _APP_INDEX.exists():
        return _FileResponse(str(_APP_INDEX))
    return {"error": "React app not built. Run: cd frontend && npm run build"}


# -- Marketing page - served at /index-marketing.html -------------------------
# "/" is intentionally NOT mapped here - React Router owns it.
# In dev mode Vite serves index.html at "/" via SPA fallback.
# In prod mode FastAPI serves index.html at "/" via spa_routes below.
@app.get("/index-marketing.html", include_in_schema=False)
def marketing_html():
    return _serve_marketing()

# -- Brand logo - served at /accfino-logo.png ----------------------------------
@app.get("/accfino-logo.png", include_in_schema=False)
def brand_logo():
    for base in (_DIST, _PUBLIC):
        f = base / "accfino-logo.png"
        if f.is_file():
            return _FileResponse(str(f), media_type="image/png", headers={"Cache-Control": "public, max-age=86400"})
    raise HTTPException(404, "Not found")

# -- Static assets (only available in production after npm run build) ----------
if _DIST.exists() and (_DIST / "assets").exists():
    app.mount("/assets", StaticFiles(directory=str(_DIST / "assets")), name="assets")


# -- Legal document routes -----------------------------------------------------
_LEGAL_DIR = _ROOT / "main_app" / "data" / "legal_documents"

LEGAL_DOCS = {
    "terms-of-service":         "terms_of_service.pdf",
    "privacy-policy":           "privacy_policy.pdf",
    "acceptable-use-policy":    "acceptable_use_policy.pdf",
    "subscription-refund-policy": "subscription_refund_policy.pdf",
    "cookie-policy":            "cookie_policy.pdf",
    "disclaimer":               "disclaimer.pdf",
}

@app.get("/legal/{doc_name}", include_in_schema=False)
def serve_legal_doc(doc_name: str):
    from fastapi.responses import FileResponse as _FR
    filename = LEGAL_DOCS.get(doc_name)
    if not filename:
        raise HTTPException(404, "Document not found")
    path = _LEGAL_DIR / filename
    if not path.exists():
        raise HTTPException(404, "Document file not found")
    return _FR(str(path), media_type="application/pdf",
               headers={"Content-Disposition": f"inline; filename={filename}"})

@app.get("/legal", include_in_schema=False)
def legal_index():
    from fastapi.responses import JSONResponse
    return JSONResponse({"documents": list(LEGAL_DOCS.keys())})

# -- sitemap.xml / robots.txt ---------------------------------------------------
# Must be defined BEFORE the "/{spa_path:path}" catch-all below, otherwise
# the SPA fallback intercepts these requests and serves index.html — which
# is exactly why Google Search Console reported "Sitemap appears to be an
# HTML page" instead of reading real XML.
_SITE_ORIGIN = "https://accfino.com"

# Public, indexable pages. "/" is the marketing landing page (highest
# priority); the product module pages (dashboard, reconciliation, trading,
# cash-flow, invoice) are also public-facing feature pages and indexable.
# Internal admin-only tools (/admin, /file-manager, /licence,
# /pricing-admin) and pure auth-flow pages (/reset-password) are excluded
# — see robots.txt below.
# Format: (path, priority, changefreq)
_SITEMAP_PATHS = [
    ("/",               "1.0", "daily"),
    ("/login",          "0.6", "monthly"),
    ("/upgrade",        "0.8", "monthly"),
    ("/dashboard",      "0.9", "weekly"),
    ("/reconciliation", "0.9", "weekly"),
    ("/trading",        "0.9", "weekly"),
    ("/cash-flow",      "0.9", "weekly"),
    ("/invoice",        "0.9", "weekly"),
]


def _legal_doc_lastmod(filename: str) -> str:
    """ISO date the legal PDF was last modified on disk, for sitemap <lastmod>."""
    import datetime as _dt
    path = _LEGAL_DIR / filename
    if path.exists():
        return _dt.datetime.utcfromtimestamp(path.stat().st_mtime).strftime("%Y-%m-%d")
    return _dt.datetime.utcnow().strftime("%Y-%m-%d")


@app.get("/sitemap.xml", include_in_schema=False)
def sitemap_xml():
    from fastapi.responses import Response as _XmlResponse

    entries = [
        {"loc": path, "priority": priority, "changefreq": freq, "lastmod": None}
        for path, priority, freq in _SITEMAP_PATHS
    ]
    # Legal documents — low priority, rarely change, but genuinely indexable
    # public pages (each /legal/{doc} route serves a real PDF).
    for slug, filename in LEGAL_DOCS.items():
        entries.append({
            "loc": f"/legal/{slug}",
            "priority": "0.2",
            "changefreq": "yearly",
            "lastmod": _legal_doc_lastmod(filename),
        })

    url_blocks = []
    for e in entries:
        lastmod_tag = f"\n    <lastmod>{e['lastmod']}</lastmod>" if e["lastmod"] else ""
        url_blocks.append(
            f"  <url>\n"
            f"    <loc>{_SITE_ORIGIN}{e['loc']}</loc>{lastmod_tag}\n"
            f"    <changefreq>{e['changefreq']}</changefreq>\n"
            f"    <priority>{e['priority']}</priority>\n"
            f"  </url>"
        )

    xml = (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'
        + "\n".join(url_blocks) +
        "\n</urlset>"
    )
    return _XmlResponse(content=xml, media_type="application/xml")


@app.get("/robots.txt", include_in_schema=False)
def robots_txt():
    from fastapi.responses import PlainTextResponse as _TxtResponse
    body = (
        "User-agent: *\n"
        "Allow: /\n"
        "Allow: /login\n"
        "Allow: /upgrade\n"
        "Allow: /legal\n"
        "Allow: /dashboard\n"
        "Allow: /reconciliation\n"
        "Allow: /trading\n"
        "Allow: /cash-flow\n"
        "Allow: /invoice\n"
        "Disallow: /admin\n"
        "Disallow: /file-manager\n"
        "Disallow: /licence\n"
        "Disallow: /pricing-admin\n"
        "Disallow: /reset-password\n"
        f"\nSitemap: {_SITE_ORIGIN}/sitemap.xml\n"
    )
    return _TxtResponse(content=body)


# -- Root "/" - marketing home page (top of page) -----------------------------
@app.get("/", include_in_schema=False)
def root():
    return _serve_marketing()

# -- SPA routes (only available in production; in dev Vite handles these) ------
if _DIST.exists() and _APP_INDEX.exists():

    # Public SPA routes (no auth required)
    @app.get("/login",          include_in_schema=False)
    @app.get("/reset-password", include_in_schema=False)
    @app.get("/upgrade",        include_in_schema=False)
    def public_spa_routes():
        return _serve_app()

    # Authenticated SPA routes
    @app.get("/dashboard",      include_in_schema=False)
    @app.get("/reconciliation", include_in_schema=False)
    @app.get("/trading",        include_in_schema=False)
    @app.get("/cash-flow",      include_in_schema=False)
    @app.get("/invoice",        include_in_schema=False)
    @app.get("/admin",          include_in_schema=False)
    @app.get("/file-manager",   include_in_schema=False)
    @app.get("/licence",        include_in_schema=False)
    @app.get("/pricing-admin",  include_in_schema=False)
    def auth_spa_routes():
        return _serve_app()

    # Catch-all for deep SPA paths
    @app.get("/{spa_path:path}", include_in_schema=False)
    def spa_fallback(spa_path: str = ""):
        return _serve_app()
