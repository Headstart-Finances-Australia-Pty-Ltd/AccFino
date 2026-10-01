"""/audit: the audit trail is visible to the AccFino platform administrator ONLY (/audit and /audit/all); every user sees just their own sign-in history (/audit/mine)."""
from datetime import date, datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy.orm import Session

from accfino_core import models as m
from accfino_core.security.context import OrgContext, current_auth, current_org
from db_app.database import get_db

router = APIRouter()


def _row(a):
    return {"id": a.id, "at": a.occurred_at.isoformat() + "Z", "user_id": a.user_id, "username": a.username,
            "org_id": a.org_id, "action": a.action, "entity": a.entity, "entity_id": a.entity_id, "ip": a.ip,
            "method": a.method, "path": a.path, "status": a.status_code, "detail": a.detail}


def _filter(q, date_from, date_to, action):
    if date_from:
        q = q.filter(m.AuditLog.occurred_at >= datetime.combine(date_from, datetime.min.time()))
    if date_to:
        q = q.filter(m.AuditLog.occurred_at < datetime.combine(date_to + timedelta(days=1), datetime.min.time()))
    if action:
        q = q.filter(m.AuditLog.action.like(f"{action}%"))
    return q


@router.get("")
def org_audit(date_from: date | None = Query(None, alias="from"), date_to: date | None = Query(None, alias="to"),
              action: str | None = None, limit: int = Query(200, le=1000), offset: int = 0,
              request: Request = None, ctx: OrgContext = Depends(current_org), db: Session = Depends(get_db)):
    if not (request is not None and current_auth(request).get("is_admin")):
        raise HTTPException(403, "The audit log is available to the AccFino administrator only")
    ctx.require("audit")
    q = _filter(db.query(m.AuditLog).filter(m.AuditLog.org_id == ctx.org.id), date_from, date_to, action)
    return {"total": q.count(), "items": [_row(a) for a in q.order_by(m.AuditLog.id.desc()).offset(offset).limit(limit)]}


@router.get("/mine")
def my_audit(request: Request, limit: int = Query(100, le=500), db: Session = Depends(get_db)):
    """A user's own sign-in and security history."""
    auth = current_auth(request)
    q = db.query(m.AuditLog).filter(m.AuditLog.user_id == auth["user_id"], m.AuditLog.action.like("auth.%"))
    return [_row(a) for a in q.order_by(m.AuditLog.id.desc()).limit(limit)]


@router.get("/all")
def all_audit(date_from: date | None = Query(None, alias="from"), date_to: date | None = Query(None, alias="to"),
              action: str | None = None, limit: int = Query(200, le=1000), offset: int = 0,
              db: Session = Depends(get_db)):
    """Platform-wide (admin only - enforced by the auth guard)."""
    q = _filter(db.query(m.AuditLog), date_from, date_to, action)
    return {"total": q.count(), "items": [_row(a) for a in q.order_by(m.AuditLog.id.desc()).offset(offset).limit(limit)]}
