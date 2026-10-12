"""
Emergency admin password reset endpoints (hidden from the API docs).
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
import os as _os
from accfino.shared.db.database import SessionLocal as _SL
from accfino.core.identity.user import User as _User

@router.post("/auth/reset-admin", include_in_schema=False)
def reset_admin_password(secret: str = Body(...)):
    """
    Emergency endpoint - resets admin password to a new value.
    Requires the ADMIN_RESET_SECRET env var to be set and passed as 'secret'.
    Use when locked out of Northflank deployment.

    POST /api/auth/reset-admin
    Body: {"secret": "<ADMIN_RESET_SECRET env var>", "new_password": "newpass"}
    """
    import os as _os
    from accfino.shared.db.database import SessionLocal as _SL
    from accfino.core.identity.user import User as _User
    import bcrypt as _bcrypt

    expected = _os.environ.get("ADMIN_RESET_SECRET", "")
    if not expected or secret != expected:
        raise HTTPException(403, "Invalid secret")
    return {"error": "Use new_password field"}

@router.post("/auth/reset-admin-full", include_in_schema=False)
async def reset_admin_full(request: Request):
    """Full admin reset - body: {secret, new_password}"""
    import os as _os
    from accfino.shared.db.database import SessionLocal as _SL
    from accfino.core.identity.user import User as _User
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

