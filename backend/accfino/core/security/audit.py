"""Append-only audit logging. Never raises into the caller."""
import logging
from datetime import datetime

log = logging.getLogger("accfino.audit")


def write(action: str, *, user_id=None, username=None, org_id=None, entity=None,
          entity_id=None, ip=None, method=None, path=None, status_code=None, detail=None, db=None):
    from accfino.core.models import AuditLog
    own = db is None
    if own:
        from accfino.shared.db.database import SessionLocal
        db = SessionLocal()
    try:
        db.add(AuditLog(occurred_at=datetime.utcnow(), action=action, user_id=user_id,
                        username=username, org_id=org_id, entity=entity,
                        entity_id=str(entity_id) if entity_id is not None else None,
                        ip=ip, method=method, path=(path or "")[:500], status_code=status_code,
                        detail=detail))
        if own:
            db.commit()
        else:
            db.flush()
    except Exception as e:  # audit must never break the request
        log.warning("audit write failed: %s", e)
        if own:
            db.rollback()
    finally:
        if own:
            db.close()
