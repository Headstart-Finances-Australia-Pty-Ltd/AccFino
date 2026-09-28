"""/admin/security-status: platform security posture for administrators."""
import os

import bcrypt
from fastapi import APIRouter, Depends
from sqlalchemy import func
from sqlalchemy.orm import Session

from accfino_core import config
from accfino_core import models as m
from db_app.database import get_db
from db_app.models.user import User

router = APIRouter()
LEGACY_DEFAULT_ADMIN_PASSWORD = "Accfino@1"


@router.get("/security-status")
def security_status(db: Session = Depends(get_db)):
    admin = db.query(User).filter(User.username == "admin").first()
    default_pw = False
    if admin:
        try:
            default_pw = bcrypt.checkpw(LEGACY_DEFAULT_ADMIN_PASSWORD.encode(), admin.password.encode())
        except Exception:
            pass
    users = db.query(func.count(User.id)).scalar() or 0
    from sqlalchemy import or_, select, union
    q = union(select(m.UserSecurity.user_id).where(or_(m.UserSecurity.mfa_enabled.is_(True),
                                                       m.UserSecurity.sms_mfa_enabled.is_(True),
                                                       m.UserSecurity.email_mfa_enabled.is_(True))),
              select(m.WebAuthnCredential.user_id))
    mfa_users = db.execute(select(func.count()).select_from(q.subquery())).scalar() or 0
    from accfino_core.security.messaging import email_provider, sms_provider
    checks = [
        {"check": "Admin password changed from published default", "ok": not default_pw, "when": "now",
         "fix": "Log in as admin and change the password now; the default is visible in the source code."},
        {"check": "JWT_SECRET set in environment", "when": "now", "ok": bool(os.environ.get("JWT_SECRET")),
         "fix": "Set a long random JWT_SECRET in Northflank secrets (a DB-stored secret is used meanwhile)."},
        {"check": "Auth enforcement active", "when": "now", "ok": config.AUTH_MODE == "enforce",
         "fix": "Set AUTH_MODE=enforce (report mode only logs violations)."},
        {"check": "MFA enforced for all users", "when": "go-live", "ok": config.MFA_ENFORCED,
         "fix": "Set MFA_ENFORCED=true once users have enrolled (required for ATO DSP certification)."},
        {"check": "Shutdown endpoint disabled", "when": "now", "ok": not config.ALLOW_SHUTDOWN,
         "fix": "Unset ALLOW_SHUTDOWN in production."},
        {"check": "API docs not public", "when": "now", "ok": not config.ENABLE_API_DOCS, "fix": "Unset ENABLE_API_DOCS."},
        {"check": "SMS codes sent by a real provider", "when": "go-live", "ok": sms_provider() != "console",
         "fix": "Set SMS_PROVIDER=messagemedia or twilio with its credentials (console only logs codes)."},
        {"check": "Email codes sent by SMTP", "when": "go-live", "ok": email_provider() == "smtp",
         "fix": "Set SMTP_HOST, SMTP_USER, SMTP_PASSWORD, FROM_EMAIL."},
        {"check": "Passkey domain pinned", "when": "go-live", "ok": bool(os.environ.get("WEBAUTHN_RP_ID")),
         "fix": "Set WEBAUTHN_RP_ID (e.g. accfino.com.au) and WEBAUTHN_ORIGINS (https://app.accfino.com.au)."},
    ]
    return {"users": users, "mfa_enabled_users": mfa_users, "checks": checks,
            "all_ok": all(c["ok"] for c in checks),
            "now_ok": all(c["ok"] for c in checks if c.get("when") == "now")}
