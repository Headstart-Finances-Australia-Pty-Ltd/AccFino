"""Foundation of the Taxation services: business-rule errors, role capabilities, the tamper-evident audit trail, JSON helpers and rule resolution.
TaxError IS an HTTPException, so FastAPI answers {"detail": message} with the right status wherever it is raised."""
import datetime as _dt
import decimal
import hashlib
import json
from typing import Any, Optional, Set

from fastapi import HTTPException

from accfino.modules.taxation.engine import rules as R
from accfino.modules.taxation.models import tax as T


class TaxError(HTTPException):
    def __init__(self, message: str, status: int = 422, code: str = "invalid"):
        super().__init__(status_code=status, detail=message)
        self.message, self.status, self.code = message, status, code

    def __str__(self):
        return self.message


class NotFound(TaxError):
    def __init__(self, what: str = "Record"):
        super().__init__(f"{what} not found", 404, "not_found")


class Forbidden(TaxError):
    def __init__(self, message: str = "Your role does not allow that in Taxation & Compliance"):
        super().__init__(message, 403, "forbidden")


class Conflict(TaxError):
    def __init__(self, message: str, code: str = "conflict"):
        super().__init__(message, 409, code)


# ---------------------------------------------------------------------------------------------------------------------- capabilities
#  owner (Organisation Admin) / platform admin   everything
#  accountant / admin(legacy)                    prepare, approve, record lodgement, configure, audit
#  bookkeeper                                    view and prepare (draft/prepared) and attach evidence; cannot approve, record lodgement or configure
#  readonly                                      view only
#  payroll / payroll_admin / employee            no access to tax data
ALL = {"view", "prepare", "evidence", "approve", "lodge", "config", "audit_view", "delete"}
ROLE_CAPS = {
    "owner": set(ALL),
    "admin": ALL - {"delete"},
    "accountant": ALL - {"delete"},
    "bookkeeper": {"view", "prepare", "evidence"},
    "readonly": {"view"},
}


class Access:
    def __init__(self, db, ctx):
        self.db, self.ctx = db, ctx
        self.caps: Set[str] = set(ALL) if ctx.is_admin else set(ROLE_CAPS.get(ctx.role, set()))

    def has(self, cap: str) -> bool:
        return cap in self.caps

    def require(self, cap: str):
        if cap not in self.caps:
            raise Forbidden(f"Your role '{self.ctx.role}' does not allow this tax action ({cap.replace('_', ' ')})")

    @property
    def has_any_access(self) -> bool:
        return "view" in self.caps

    def summary(self) -> dict:
        return dict(role=self.ctx.role, capabilities=sorted(self.caps))


def check_separation(db, ctx, prepared_by: Optional[int], what: str, profile: "T.TaxProfile", audit_action: str, entity_type: str, entity_id) -> bool:
    """Approver must differ from the preparer unless the organisation has enabled self-approval (single-person businesses). Returns True if self-approval was used."""
    if prepared_by is not None and prepared_by == ctx.user_id:
        if not (profile and profile.allow_self_approval):
            raise Forbidden(f"Separation of duties: the person who prepared this {what} cannot approve it. Another authorised user must approve, or the Organisation Admin can enable self-approval for a one-person business (Tax > Rates & Settings, audited).")
        return True
    return False


# ---------------------------------------------------------------------------------------------------------------------- JSON / audit
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


def _digest(prev: str, row: dict) -> str:
    return hashlib.sha256((prev + json.dumps(row, sort_keys=True, default=str)).encode()).hexdigest()


def record(db, ctx, action: str, entity_type: str, entity_id=None, summary: str = "", before: Optional[dict] = None, after: Optional[dict] = None) -> "T.TaxAudit":
    """Append one audit event to the organisation's hash chain."""
    last = db.query(T.TaxAudit).filter(T.TaxAudit.org_id == ctx.org.id).order_by(T.TaxAudit.seq.desc()).first()
    seq = (last.seq if last else 0) + 1
    prev = last.hash if last else ""
    at = _dt.datetime.utcnow().replace(microsecond=0)
    body = dict(org=ctx.org.id, seq=seq, at=at.isoformat(), user=ctx.user_id, action=action, entity=entity_type, entity_id=None if entity_id is None else str(entity_id),
                summary=(summary or "")[:500], before=plain(before), after=plain(after))
    row = T.TaxAudit(org_id=ctx.org.id, seq=seq, at=at, user_id=ctx.user_id, username=ctx.username, action=action, entity_type=entity_type,
                     entity_id=body["entity_id"], summary=body["summary"], before=body["before"], after=body["after"], prev_hash=prev, hash=_digest(prev, body))
    db.add(row)
    db.flush()
    return row


def verify_audit(db, org_id: int) -> dict:
    """Recompute the chain. {ok, events, broken_at}: broken_at is the first sequence whose content or link no longer matches."""
    prev, n = "", 0
    for r in db.query(T.TaxAudit).filter(T.TaxAudit.org_id == org_id).order_by(T.TaxAudit.seq):
        n += 1
        body = dict(org=org_id, seq=r.seq, at=r.at.replace(microsecond=0).isoformat(), user=r.user_id, action=r.action, entity=r.entity_type, entity_id=r.entity_id,
                    summary=r.summary or "", before=r.before, after=r.after)
        if r.prev_hash != prev or r.hash != _digest(prev, body) or r.seq != n:
            return dict(ok=False, events=n, broken_at=r.seq)
        prev = r.hash
    return dict(ok=True, events=n, broken_at=None)


# ---------------------------------------------------------------------------------------------------------------------- rules
def overrides_for(db, org_id: int, rule_set_id: str) -> dict:
    return {o.path: o.value for o in db.query(T.TaxRuleOverride).filter_by(org_id=org_id, rule_set_id=rule_set_id)}


def rules_for_fy(db, ctx, fy: str) -> "R.TaxRuleSet":
    try:
        rs = R.rulebook().for_fy(fy, ctx.org.fy_end_month or 6)
        ov = overrides_for(db, ctx.org.id, rs.id)
        return rs.with_overrides(ov) if ov else rs
    except R.RulesError as e:
        raise TaxError(str(e), 422, "no_rules")


def rules_for_date(db, ctx, d: _dt.date) -> "R.TaxRuleSet":
    try:
        rs = R.rulebook().for_date(d)
        ov = overrides_for(db, ctx.org.id, rs.id)
        return rs.with_overrides(ov) if ov else rs
    except R.RulesError as e:
        raise TaxError(str(e), 422, "no_rules")


def rules_for_fbt_year(db, ctx, label: str) -> "R.TaxRuleSet":
    try:
        rs = R.rulebook().for_fbt_year(label)
        ov = overrides_for(db, ctx.org.id, rs.id)
        return rs.with_overrides(ov) if ov else rs
    except R.RulesError as e:
        raise TaxError(str(e), 422, "no_rules")


def parse_date(v, name: str):
    if v in (None, ""):
        return None
    if isinstance(v, _dt.date):
        return v
    try:
        return _dt.date.fromisoformat(str(v))
    except ValueError:
        raise TaxError(f"{name} must be a date (YYYY-MM-DD)")


def check_fy(ctx, fy: str) -> str:
    try:
        R.fy_bounds(fy, ctx.org.fy_end_month or 6)
    except R.RulesError as e:
        raise TaxError(str(e))
    return fy


def money_in(v, name: str, *, allow_negative: bool = False, required: bool = False):
    from accfino.modules.taxation.engine.money import D, q2
    if v in (None, ""):
        if required:
            raise TaxError(f"{name} is required")
        return None
    try:
        x = D(v)
    except ValueError:
        raise TaxError(f"{name} must be a number")
    if x < 0 and not allow_negative:
        raise TaxError(f"{name} cannot be negative")
    return q2(x)


def locked(org, d: _dt.date) -> bool:
    return bool(org.lock_date and d <= org.lock_date)


# ---------------------------------------------------------------------------------------------------------------------- sign-off / declaration gate
def supersede_signoffs(db, ctx, doc_type: str, doc_id: int, reason: str):
    """Called whenever a document leaves the 'approved' state (returned to draft, voided, amended): its declarations no longer describe what will be lodged."""
    n = 0
    for so in db.query(T.TaxSignoff).filter_by(org_id=ctx.org.id, doc_type=doc_type, doc_id=doc_id, status="valid"):
        so.status, so.ended_at, so.ended_by, so.end_reason = "superseded", _dt.datetime.utcnow(), ctx.user_id, reason[:300]
        n += 1
    if n:
        record(db, ctx, "signoff.superseded", doc_type, doc_id, f"{n} sign-off(s) superseded: {reason[:150]}", None, None)
    return n


def declaration_status(db, ctx, doc_type: str, doc_id: int, calc_hash: Optional[str]) -> dict:
    """Does the document carry the declaration the organisation's policy requires, for exactly the figures that exist now?"""
    p = db.get(T.TaxProfile, ctx.org.id)
    policy = (p.lodgement_policy if p else None) or "self_declaration"
    valid = [so for so in db.query(T.TaxSignoff).filter_by(org_id=ctx.org.id, doc_type=doc_type, doc_id=doc_id, status="valid").order_by(T.TaxSignoff.id) if so.doc_hash == calc_hash]
    agent = [so for so in valid if so.capacity in ("tax_agent", "bas_agent")]
    ok = bool(agent) if policy == "agent_signoff_required" else bool(valid)
    need = ("Policy: a registered tax agent or BAS agent must sign off this document before lodgement can be recorded."
            if policy == "agent_signoff_required" else "A declaration is required before lodgement can be recorded: the taxpayer / authorised person, or a registered agent, signs off the document.")
    return dict(policy=policy, ok=ok, requirement=need, valid=[so.id for so in valid], agent_signed=bool(agent))


def check_declaration(db, ctx, doc_type: str, doc_id: int, calc_hash: Optional[str]):
    st = declaration_status(db, ctx, doc_type, doc_id, calc_hash)
    if not st["ok"]:
        raise Conflict(st["requirement"] + " Use the Sign-off & lodgement panel on the document.", "declaration_required")
    return st
