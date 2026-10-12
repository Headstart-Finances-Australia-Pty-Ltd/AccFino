"""Foundation of the Practice services: errors, practice membership and capabilities, client scope, audit, helpers.
PcError IS an HTTPException so FastAPI answers {"detail": message} with the right status wherever it is raised.
SECURITY MODEL: a request is authorised in the BACKEND by (1) the signed-in user being an active PcMember of the practice that owns the organisation in the request,
(2) the member's role granting the capability, and (3) for client data, the client being inside the member's SCOPE. Frontend state is never consulted."""
import datetime as _dt
import decimal
import json
import os
from typing import Any, Iterable, Optional, Set

from fastapi import HTTPException

from accfino.modules.practice.models import practice as P


class PcError(HTTPException):
    def __init__(self, message: str, status: int = 422, code: str = "invalid"):
        super().__init__(status_code=status, detail=message)
        self.message, self.status, self.code = message, status, code

    def __str__(self):
        return self.message


class NotFound(PcError):
    def __init__(self, what: str = "Record"):
        super().__init__(f"{what} not found", 404, "not_found")


class Forbidden(PcError):
    def __init__(self, message: str = "Your practice role does not allow that"):
        super().__init__(message, 403, "forbidden")


class Conflict(PcError):
    def __init__(self, message: str, code: str = "conflict"):
        super().__init__(message, 409, code)


# capability sets by practice role
CAPS = {
    "admin":    {"view", "clients_edit", "clients_archive", "members", "settings", "docs", "docs_delete", "wp_prepare", "wp_review", "wp_reopen", "engagements", "time", "time_approve",
                 "billing", "billing_admin", "writeoff", "portal", "tax_ids", "import", "audit_view"},
    "partner":  {"view", "clients_edit", "clients_archive", "docs", "docs_delete", "wp_prepare", "wp_review", "wp_reopen", "engagements", "time", "time_approve", "billing", "billing_admin",
                 "writeoff", "portal", "tax_ids", "import", "audit_view"},
    "manager":  {"view", "clients_edit", "docs", "wp_prepare", "wp_review", "engagements", "time", "time_approve", "billing", "portal", "tax_ids", "import"},
    "preparer": {"view", "docs", "wp_prepare", "engagements", "time", "portal"},
    "reviewer": {"view", "docs", "wp_prepare", "wp_review", "engagements", "time", "portal"},
    "billing":  {"view", "time", "time_approve", "billing", "billing_admin"},
    "readonly": {"view"},
}
ALL_CLIENTS_ROLES = {"admin", "partner", "billing"}            # see every client (billing only for billing purposes; see client_scope)


def plain(v: Any):
    if isinstance(v, decimal.Decimal):
        return str(v)
    if isinstance(v, (_dt.datetime, _dt.date)):
        return v.isoformat()
    if isinstance(v, dict):
        return {str(k): plain(x) for k, x in v.items()}
    if isinstance(v, (list, tuple, set)):
        return [plain(x) for x in v]
    return v


def audit(db, ctx, practice_id: int, action: str, entity: str, entity_id=None, outcome: str = "ok", **detail):
    """Append to the platform audit log in the SAME transaction. Never put secrets (tokens, tax identifiers, file contents) in `detail`."""
    from accfino.core.security import audit as _a
    detail["practice_id"] = practice_id
    detail["outcome"] = outcome
    _a.write(f"practice.{action}", user_id=getattr(ctx, "user_id", None), username=getattr(ctx, "username", None), org_id=ctx.org.id if getattr(ctx, "org", None) else None,
             entity=entity, entity_id=entity_id, detail=json.dumps(plain(detail), default=str)[:3000], db=db)


def today() -> _dt.date:
    try:
        from zoneinfo import ZoneInfo
        return _dt.datetime.now(ZoneInfo(os.getenv("ACCFINO_TZ", "Australia/Sydney"))).date()
    except Exception:
        return _dt.date.today()


def now() -> _dt.datetime:
    return _dt.datetime.utcnow()


def parse_date(v, name: str, default=None):
    if v in (None, ""):
        return default
    if isinstance(v, _dt.date):
        return v
    try:
        return _dt.date.fromisoformat(str(v))
    except ValueError:
        raise PcError(f"{name} must be a date (YYYY-MM-DD)")


def text(v, name: str, *, required=False, max_len=200) -> Optional[str]:
    s = (v or "").strip() if isinstance(v, str) or v is None else str(v).strip()
    if required and not s:
        raise PcError(f"{name} is required")
    if len(s) > max_len:
        raise PcError(f"{name} must be at most {max_len} characters")
    return s or None


def get_settings(practice: "P.PcPractice") -> dict:
    d = dict(retention_years=7, storage_limit_mb=500, max_file_mb=10, holidays=[], dedupe={}, billing=dict(payment_terms_days=14, tax_rate="0.10", revenue_account="200", default_service="advisory"),
             dashboard_soon_days=14, portal_invite_hours=72, download_ticket_seconds=120)
    for k, v in (practice.settings or {}).items():
        d[k] = {**d[k], **v} if isinstance(v, dict) and isinstance(d.get(k), dict) else v
    return d


class Access:
    """The authorisation object created for EVERY staff request. Raises 403 when the user is not an active member of the practice for the request's organisation."""

    def __init__(self, db, ctx, *, require_member=True):
        self.db, self.ctx = db, ctx
        self.practice = db.query(P.PcPractice).filter_by(org_id=ctx.org.id).first()
        self.member = None
        if self.practice is not None:
            self.member = db.query(P.PcMember).filter_by(practice_id=self.practice.id, user_id=ctx.user_id, status="active").first()
        if require_member and (self.practice is None or self.member is None):
            raise Forbidden("You are not a member of this practice" if self.practice else "This organisation has no practice workspace")
        self.role = self.member.role if self.member else None
        self.caps: Set[str] = set(CAPS.get(self.role, set()))
        self.practice_id = self.practice.id if self.practice else None
        self.settings = get_settings(self.practice) if self.practice else {}

    # ---- capabilities
    def can(self, cap: str) -> bool:
        return cap in self.caps

    def require(self, cap: str):
        if cap not in self.caps:
            raise Forbidden(f"Your practice role '{self.role}' does not allow '{cap.replace('_', ' ')}'")

    def summary(self) -> dict:
        return dict(practice_id=self.practice_id, practice=self.practice.name if self.practice else None, role=self.role, capabilities=sorted(self.caps), staff_id=self.ctx.user_id)

    # ---- client scope: THE isolation rule for staff. Admin/partner see all; others see clients they are assigned to or via a team.
    def team_ids(self) -> Set[int]:
        return {t for (t,) in self.db.query(P.PcTeamMember.team_id).join(P.PcTeam, P.PcTeam.id == P.PcTeamMember.team_id)
                .filter(P.PcTeam.practice_id == self.practice_id, P.PcTeamMember.user_id == self.ctx.user_id)}

    def scoped_clients(self, q=None, *, billing=False):
        """Query of PcClient the member may see. billing=True lets the billing role see all clients (for invoicing only)."""
        from sqlalchemy import or_
        C = P.PcClient
        q = q if q is not None else self.db.query(C)
        q = q.filter(C.practice_id == self.practice_id)
        if self.role in ("admin", "partner") or (billing and self.role == "billing"):
            return q
        uid, teams = self.ctx.user_id, self.team_ids()
        conds = [C.manager_id == uid, C.preparer_id == uid, C.reviewer_id == uid]
        if teams:
            conds.append(C.team_id.in_(teams))
        return q.filter(or_(*conds))

    def client(self, client_id, *, billing=False, allow_archived=True) -> "P.PcClient":
        """Fetch one client inside the member's scope. Out-of-scope and other-practice ids both answer 404 (never reveal existence)."""
        c = self.scoped_clients(billing=billing).filter(P.PcClient.id == client_id).first() if client_id else None
        if c is None:
            raise NotFound("Client")
        if not allow_archived and c.status == "archived":
            raise Conflict("This client is archived. Reactivate it first.")
        return c

    def client_ids(self, *, billing=False) -> list:
        return [i for (i,) in self.scoped_clients(self.db.query(P.PcClient.id), billing=billing)]

    def member_of(self, user_id) -> bool:
        return bool(user_id) and self.db.query(P.PcMember.id).filter_by(practice_id=self.practice_id, user_id=user_id, status="active").first() is not None

    def require_member_user(self, user_id, what="User"):
        if user_id is not None and not self.member_of(user_id):
            raise PcError(f"{what} must be an active member of this practice")


def page(q, page_no: int = 1, size: int = 25, *, max_size: int = 200):
    size = max(1, min(int(size or 25), max_size))
    page_no = max(1, int(page_no or 1))
    total = q.count()
    return dict(total=total, page=page_no, size=size, pages=(total + size - 1) // size), q.offset((page_no - 1) * size).limit(size)


class SystemCtx:
    """Actor for scheduled/background work: never a person, always audited, always bound to ONE practice's organisation."""
    def __init__(self, org, label="system"):
        self.org, self.user_id, self.username, self.is_admin, self.role = org, None, label, False, "system"
