"""Foundation of the lending services: errors, what each role may do, platform audit, and small helpers. LendError IS an HTTPException (FastAPI answers {"detail": message})."""
import datetime as _dt
import re
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from typing import Any, Optional, Set

from fastapi import HTTPException

import accfino.modules.accounting.public as acct
from accfino.core.security import audit as platform_audit

CAPS = ("view", "edit", "upload", "assess", "approve", "override", "settle", "collect", "configure", "delete")
ALL = set(CAPS)
# owner / admin: everything. accountant: everything but delete. bookkeeper: view, edit, upload, assess and record collection activity (NOT approve, override, settle or configure). read-only: view. payroll / employee: none.
ROLE_CAPS = {"owner": set(ALL), "admin": set(ALL), "accountant": ALL - {"delete"}, "bookkeeper": {"view", "edit", "upload", "assess", "collect"}, "readonly": {"view"}}
ZERO, CENT = Decimal("0"), Decimal("0.01")


class LendError(HTTPException):
    def __init__(self, message: str, status: int = 422, code: str = "invalid"):
        super().__init__(status_code=status, detail=message)
        self.message, self.status, self.code = message, status, code

    def __str__(self):
        return self.message


class NotFound(LendError):
    def __init__(self, what="Record"):
        super().__init__(f"{what} not found", 404, "not_found")


class Forbidden(LendError):
    def __init__(self, message="Your role does not allow that in Smart Lending"):
        super().__init__(message, 403, "forbidden")


class Conflict(LendError):
    def __init__(self, message, code="conflict"):
        super().__init__(message, 409, code)


class Access:
    def __init__(self, db, ctx):
        self.db, self.ctx = db, ctx
        self.caps: Set[str] = set(ALL) if getattr(ctx, "is_admin", False) else set(ROLE_CAPS.get(ctx.role, set()))

    @property
    def has_any_access(self) -> bool:
        return bool(self.caps)

    def can(self, cap: str) -> bool:
        return cap in self.caps

    def require(self, cap: str):
        if cap not in self.caps:
            raise Forbidden(f"Your role '{self.ctx.role}' does not allow this action ({cap.replace('_', ' ')})")

    def summary(self) -> dict:
        return dict(role=self.ctx.role, capabilities=sorted(self.caps))


def plain(v: Any):
    """JSON-safe copy: Decimal -> str, date -> ISO, nested containers walked."""
    if isinstance(v, Decimal):
        return str(v)
    if isinstance(v, (_dt.date, _dt.datetime)):
        return v.isoformat()
    if isinstance(v, dict):
        return {str(k): plain(x) for k, x in v.items()}
    if isinstance(v, (list, tuple, set)):
        return [plain(x) for x in v]
    return v


def audit(db, ctx, action: str, entity: str, entity_id=None, **detail):
    """One row in the platform audit log, in the SAME transaction as the change (so a rolled-back change leaves no trace)."""
    platform_audit.write(f"lending.{action}", user_id=ctx.user_id, username=getattr(ctx, "username", None), org_id=ctx.org.id, entity=entity, entity_id=entity_id, detail=plain(detail) or None, db=db)


def parse_date(v, name: str, required: bool = True):
    if v in (None, ""):
        if required:
            raise LendError(f"{name} is required")
        return None
    if isinstance(v, _dt.datetime):
        return v.date()
    if isinstance(v, _dt.date):
        return v
    try:
        return _dt.date.fromisoformat(str(v)[:10])
    except ValueError:
        raise LendError(f"{name} must be a date written like 2026-09-30")


def num(v, name: str, *, required=False, allow_negative=False, maximum: Optional[Decimal] = None) -> Optional[Decimal]:
    if v in (None, ""):
        if required:
            raise LendError(f"{name} is required")
        return None
    try:
        d = Decimal(str(v).strip())
    except (InvalidOperation, ValueError):
        raise LendError(f"{name} must be a number")
    if not d.is_finite():
        raise LendError(f"{name} must be a number")
    if d < 0 and not allow_negative:
        raise LendError(f"{name} cannot be negative")
    if maximum is not None and d > maximum:
        raise LendError(f"{name} is larger than allowed ({maximum})")
    return d


def q2(v) -> Decimal:
    return Decimal(str(v)).quantize(CENT, ROUND_HALF_UP)


def choice(v, allowed, name: str, required=True, default=None):
    if v in (None, ""):
        if default is not None:
            return default
        if required:
            raise LendError(f"{name} is required")
        return None
    v = str(v).strip().lower().replace(" ", "_")
    if v not in allowed:
        raise LendError(f"{name} must be one of {', '.join(allowed)} (got '{v}')")
    return v


_TFN = re.compile(r"(?<!\d)\d{3}[ -]?\d{3}[ -]?\d{3}(?!\d)")


def no_tfn(text, name: str):
    """A Tax File Number must never be stored. (An ABN has 11 digits and is not caught.)"""
    if text and _TFN.search(str(text)):
        raise LendError(f"{name} looks like it contains a Tax File Number. Do not enter a TFN: it is never needed here and is never stored.")


def contact_or_404(db, ctx, contact_id: int) -> dict:
    c = acct.contact(db, ctx.org.id, int(contact_id)) if str(contact_id).isdigit() or isinstance(contact_id, int) else None
    if c is None:
        raise NotFound("Applicant")
    return c


def label(v) -> str:
    return str(v or "").replace("_", " ").capitalize()
