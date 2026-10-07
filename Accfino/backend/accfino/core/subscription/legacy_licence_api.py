"""
Legacy per-user licence endpoints (/licence/*).
"""
import os
import sys
from pathlib import Path
from fastapi import APIRouter
from accfino.shared import paths as _paths

router = APIRouter()

import logging
logger = logging.getLogger("accfino")


from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile, Body
from accfino.core.subscription.licence import LicenceRecord
from fastapi.requests  import Request as _Request
from accfino.shared.db.database import SessionLocal as _SL
from accfino.core.identity.user import User as _User

def _get_db_session():
    db = _SL()
    try:
        yield db
    finally:
        db.close()

ALL_MODULES = [
    "dashboard", "accounting", "reconciliation", "trading",
    "cash-flow", "invoice", "admin", "file-manager", "licence", "payroll", "lending"
]

@router.get("/licence/list")
def licence_list():
    """All users with their licence data including module permissions."""
    import json as _json
    db = _SL()
    try:
        # Ensure modules column exists (migration for existing DBs)
        try:
            import sqlite3 as _s3
            from accfino.shared.db.database import _DB_FILE as _dbf
            _dbf_str = str(_dbf)
            cx = _s3.connect(_dbf_str)
            cols = [r[1] for r in cx.execute("PRAGMA table_info(licence_records)").fetchall()]
            if "modules" not in cols:
                cx.execute("ALTER TABLE licence_records ADD COLUMN modules VARCHAR(1000) DEFAULT ''")
                cx.commit()
            cx.close()
        except Exception as _me:
            print(f"[licence] migration warning: {_me}")

        # Only people who belong to an organisation, plus the platform administrator. A login whose organisation was deleted is a leftover: it is
        # listed (and can be removed) under Organisations & Users > "Users not in any organisation", not here.
        from accfino.core import models as _cm
        members = {r[0] for r in db.query(_cm.OrgMembership.user_id).all()}
        users = [u for u in db.query(_User).all() if u.id in members or any(r.name == "admin" for r in u.roles)]
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

@router.get("/licence/my-modules")
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

@router.post("/licence/save")
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

@router.delete("/licence/user/{user_id}")
def licence_delete_user(user_id: int, request: _Request):
    """Delete a user and everything that belongs to them (licence, roles, sessions, memberships, transactions ...).
    Works on PostgreSQL (the old version only knew SQLite, so deleting always failed). The platform administrator and the signed-in
    account are protected."""
    from accfino.core.platform_admin import force_delete as _FD
    actor = getattr(request.state, "auth", None) or {}
    db = _SL()
    try:
        info = _FD.delete_user(db, user_id, actor_id=actor.get("user_id"), force=False)
        db.commit()
        return {"ok": True, **info}
    except HTTPException:
        db.rollback()
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(500, f"Delete failed: {e}")
    finally:
        db.close()

@router.patch("/licence/user/{user_id}")
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
    except ValueError as e:
        db.rollback()
        from accfino.core.security.contact import ContactError, http_422
        if isinstance(e, ContactError):                # email and phone are mandatory and must be valid for every account (User model guard)
            raise http_422(e)
        raise HTTPException(500, str(e))
    except Exception as e:
        db.rollback()
        raise HTTPException(500, str(e))
    finally:
        db.close()

