"""Foundation of the Planning services: errors, role capabilities, audit, settings, hashing and date helpers.
PlanError IS an HTTPException, so FastAPI answers {"detail": message} with the right status wherever it is raised."""
import datetime as _dt
import decimal
import hashlib
import json
import os
from typing import Any, Set

from fastapi import HTTPException

from accfino.modules.planning.models import plan as P


class PlanError(HTTPException):
    def __init__(self, message: str, status: int = 422, code: str = "invalid"):
        super().__init__(status_code=status, detail=message)
        self.message, self.status, self.code = message, status, code

    def __str__(self):
        return self.message


class NotFound(PlanError):
    def __init__(self, what: str = "Record"):
        super().__init__(f"{what} not found", 404, "not_found")


class Forbidden(PlanError):
    def __init__(self, message: str = "Your role does not allow that in Planning & Intelligence"):
        super().__init__(message, 403, "forbidden")


class Conflict(PlanError):
    def __init__(self, message: str, code: str = "conflict"):
        super().__init__(message, 409, code)


# capabilities
#  owner / platform admin     everything
#  admin / accountant         view, edit, approve, review, config, ai
#  bookkeeper                 view, edit (draft budgets, scenarios, forecasts), ai; cannot approve, review alerts or configure
#  readonly                   view and ask the assistant (read-only)
#  payroll / payroll_admin / employee   no access (company-wide financials)
ALL = {"view", "edit", "approve", "review", "config", "ai"}
ROLE_CAPS = {"owner": set(ALL), "admin": set(ALL), "accountant": set(ALL), "bookkeeper": {"view", "edit", "ai"}, "readonly": {"view", "ai"}}


class Access:
    def __init__(self, db, ctx):
        self.db, self.ctx = db, ctx
        self.caps: Set[str] = set(ALL) if ctx.is_admin else set(ROLE_CAPS.get(ctx.role, set()))

    def has(self, cap: str) -> bool:
        return cap in self.caps

    def require(self, cap: str):
        if cap not in self.caps:
            raise Forbidden(f"Your role '{self.ctx.role}' does not allow this action in Planning & Intelligence ({cap})")

    @property
    def has_any_access(self) -> bool:
        return "view" in self.caps

    def summary(self) -> dict:
        return dict(role=self.ctx.role, capabilities=sorted(self.caps))


def plain(v: Any):
    """JSON-safe copy: dates -> ISO, Decimal -> string, tuples/sets -> lists."""
    if isinstance(v, (_dt.date, _dt.datetime)):
        return v.isoformat()
    if isinstance(v, decimal.Decimal):
        return str(v)
    if isinstance(v, dict):
        return {str(k): plain(x) for k, x in v.items()}
    if isinstance(v, (list, tuple, set)):
        return [plain(x) for x in v]
    return v


def digest(obj: Any) -> str:
    """Stable SHA-256 of any JSON-able structure: the same inputs always hash the same (used for reproducibility checks)."""
    return hashlib.sha256(json.dumps(plain(obj), sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def audit(db, ctx, action: str, entity: str, entity_id=None, **detail):
    """Append to the platform audit log IN THE SAME transaction as the change (flushed, committed or rolled back with it)."""
    from accfino.core.security import audit as _a
    _a.write(f"planning.{action}", user_id=ctx.user_id, username=ctx.username, org_id=ctx.org.id, entity=entity, entity_id=entity_id, detail=plain(detail), db=db)


def business_today() -> _dt.date:
    try:
        from zoneinfo import ZoneInfo
        return _dt.datetime.now(ZoneInfo(os.getenv("ACCFINO_TZ", "Australia/Sydney"))).date()
    except Exception:
        return _dt.date.today()


def parse_date(v, name: str, default=None):
    if v in (None, ""):
        return default
    if isinstance(v, _dt.date):
        return v
    try:
        return _dt.date.fromisoformat(str(v))
    except ValueError:
        raise PlanError(f"{name} must be a date (YYYY-MM-DD)")


def fy_start_for(org, d: _dt.date) -> _dt.date:
    """First day of the financial year containing d (fy_end_month from the organisation; June by default)."""
    end_m = org.fy_end_month or 6
    start_m = end_m % 12 + 1
    y = d.year if d.month >= start_m else d.year - 1
    if start_m == 1:
        y = d.year
    return _dt.date(y, start_m, 1)


def settings(db, ctx) -> "P.PlanSetting":
    row = db.get(P.PlanSetting, ctx.org.id)
    if row is None:
        row = P.PlanSetting(org_id=ctx.org.id, min_cash_threshold=0, horizon_weeks=13, overdue_collection_pct=80, overdue_collection_days=14, stale_days=7, recurring_weight_pct=100)
        db.add(row)
        db.flush()
    return row


def settings_dict(row) -> dict:
    return dict(min_cash_threshold=str(row.min_cash_threshold or 0), horizon_weeks=row.horizon_weeks, overdue_collection_pct=row.overdue_collection_pct,
                overdue_collection_days=row.overdue_collection_days, stale_days=row.stale_days, recurring_weight_pct=row.recurring_weight_pct if row.recurring_weight_pct is not None else 100, insight_cfg=row.insight_cfg or {}, risk_cfg=row.risk_cfg or {}, benchmarks=row.benchmarks or [])


def stamp(ctx, **extra) -> dict:
    """Standard provenance for every figure: organisation, currency, source system."""
    return dict(organisation=ctx.org.name, organisation_id=ctx.org.id, currency=getattr(ctx.org, "currency", None) or "AUD", **extra)
