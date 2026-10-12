"""Foundation of the Investments services: errors, role capabilities, the tamper-evident audit chain and small helpers. InvError IS an HTTPException (FastAPI answers {"detail": message})."""
import datetime as _dt
import decimal
import hashlib
import json
from typing import Any, Optional, Set

from fastapi import HTTPException

from accfino.modules.investments.models import inv as M


class InvError(HTTPException):
    def __init__(self, message: str, status: int = 422, code: str = "invalid"):
        super().__init__(status_code=status, detail=message)
        self.message, self.status, self.code = message, status, code

    def __str__(self):
        return self.message


class NotFound(InvError):
    def __init__(self, what="Record"):
        super().__init__(f"{what} not found", 404, "not_found")


class Forbidden(InvError):
    def __init__(self, message="Your role does not allow that in Assets, Investments & Wealth"):
        super().__init__(message, 403, "forbidden")


class Conflict(InvError):
    def __init__(self, message, code="conflict"):
        super().__init__(message, 409, code)


# owner/admin: everything. accountant: everything but delete. bookkeeper: view, edit, import. readonly: view. payroll / employee roles: no access.
ALL = {"view", "edit", "import", "post", "config", "audit_view", "delete"}
ROLE_CAPS = {"owner": set(ALL), "admin": ALL - {"delete"}, "accountant": ALL - {"delete"}, "bookkeeper": {"view", "edit", "import"}, "readonly": {"view"}}


class Access:
    def __init__(self, db, ctx):
        self.db, self.ctx = db, ctx
        self.caps: Set[str] = set(ALL) if ctx.is_admin else set(ROLE_CAPS.get(ctx.role, set()))

    def has(self, cap):
        return cap in self.caps

    def require(self, cap):
        if cap not in self.caps:
            raise Forbidden(f"Your role '{self.ctx.role}' does not allow this action ({cap.replace('_', ' ')})")

    @property
    def has_any_access(self):
        return "view" in self.caps

    def summary(self):
        return dict(role=self.ctx.role, capabilities=sorted(self.caps))


def plain(v: Any):
    if isinstance(v, (_dt.date, _dt.datetime)):
        return v.isoformat()
    if isinstance(v, decimal.Decimal):
        return str(v)
    if isinstance(v, dict):
        return {str(k): plain(x) for k, x in v.items()}
    if isinstance(v, (list, tuple, set)):
        return [plain(x) for x in v]
    return v


def _digest(prev, row):
    return hashlib.sha256((prev + json.dumps(row, sort_keys=True, default=str)).encode()).hexdigest()


def record(db, ctx, action: str, entity_type: str, entity_id=None, summary: str = "", before: Optional[dict] = None, after: Optional[dict] = None):
    last = db.query(M.InvAudit).filter(M.InvAudit.org_id == ctx.org.id).order_by(M.InvAudit.seq.desc()).first()
    seq, prev = (last.seq if last else 0) + 1, (last.hash if last else "")
    at = _dt.datetime.utcnow().replace(microsecond=0)
    body = dict(org=ctx.org.id, seq=seq, at=at.isoformat(), user=ctx.user_id, action=action, entity=entity_type, entity_id=None if entity_id is None else str(entity_id), summary=(summary or "")[:500], before=plain(before), after=plain(after))
    row = M.InvAudit(org_id=ctx.org.id, seq=seq, at=at, user_id=ctx.user_id, username=ctx.username, action=action, entity_type=entity_type, entity_id=body["entity_id"], summary=body["summary"], before=body["before"], after=body["after"],
                     prev_hash=prev, hash=_digest(prev, body))
    db.add(row)
    db.flush()
    return row


def verify_audit(db, org_id: int) -> dict:
    prev, n = "", 0
    for r in db.query(M.InvAudit).filter(M.InvAudit.org_id == org_id).order_by(M.InvAudit.seq):
        n += 1
        body = dict(org=org_id, seq=r.seq, at=r.at.replace(microsecond=0).isoformat(), user=r.user_id, action=r.action, entity=r.entity_type, entity_id=r.entity_id, summary=r.summary or "", before=r.before, after=r.after)
        if r.prev_hash != prev or r.hash != _digest(prev, body) or r.seq != n:
            return dict(ok=False, events=n, broken_at=r.seq)
        prev = r.hash
    return dict(ok=True, events=n, broken_at=None)


def audit_rows(db, ctx, limit=100, entity_type="", entity_id=None, before_seq=None):
    q = db.query(M.InvAudit).filter_by(org_id=ctx.org.id)
    if entity_type:
        q = q.filter(M.InvAudit.entity_type == entity_type)
    if entity_id not in (None, ""):
        q = q.filter(M.InvAudit.entity_id == str(entity_id))
    if before_seq:
        q = q.filter(M.InvAudit.seq < before_seq)
    return [dict(seq=r.seq, at=r.at.isoformat(), user=r.username, action=r.action, entity_type=r.entity_type, entity_id=r.entity_id, summary=r.summary, hash=r.hash[:12]) for r in q.order_by(M.InvAudit.seq.desc()).limit(limit)]


def parse_date(v, name: str):
    if v in (None, ""):
        return None
    if isinstance(v, _dt.date):
        return v
    try:
        return _dt.date.fromisoformat(str(v))
    except ValueError:
        raise InvError(f"{name} must be a date (YYYY-MM-DD)")


def num(v, name: str, *, required=False, allow_negative=False, places: int = 2):
    from accfino.modules.investments.engine.money import D, q2, q8
    if v in (None, ""):
        if required:
            raise InvError(f"{name} is required")
        return None
    try:
        x = D(v)
    except Exception:
        raise InvError(f"{name} must be a number")
    if x < 0 and not allow_negative:
        raise InvError(f"{name} cannot be negative")
    return q2(x) if places == 2 else q8(x)


def fy_of(d: _dt.date) -> str:
    y = d.year if d.month >= 7 else d.year - 1
    return f"{y}-{str(y + 1)[2:]}"


def fy_bounds(fy: str):
    try:
        y = int(fy[:4])
        if fy != f"{y}-{str(y + 1)[2:]}":
            raise ValueError
    except (ValueError, TypeError):
        raise InvError(f"'{fy}' is not an income year such as 2026-27")
    return _dt.date(y, 7, 1), _dt.date(y + 1, 6, 30)
