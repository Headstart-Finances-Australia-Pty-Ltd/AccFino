"""Practice workspace: profile, settings, members, teams, assignments."""
import re

from accfino.core import models as m
from accfino.core.identity.user import User
from accfino.modules.practice.models import practice as P
from accfino.modules.practice.services import core
from accfino.modules.practice.services.core import Access, Conflict, Forbidden, NotFound, PcError

EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def create(db, ctx, name: str, **profile) -> dict:
    """Create the practice workspace for the organisation. Only the Organisation Admin may; the creator becomes the first practice admin."""
    if not ctx.is_org_admin:
        raise Forbidden("Only the Organisation Admin can create the practice workspace")
    if db.query(P.PcPractice.id).filter_by(org_id=ctx.org.id).first():
        raise Conflict("This organisation already has a practice workspace")
    p = P.PcPractice(org_id=ctx.org.id, name=core.text(name, "Practice name", required=True), fy_end_month=ctx.org.fy_end_month or 6)
    db.add(p)
    db.flush()
    db.add(P.PcMember(practice_id=p.id, user_id=ctx.user_id, role="admin"))
    db.flush()
    a = Access(db, ctx)
    if profile:
        update_profile(db, ctx, a, profile)
    core.audit(db, ctx, p.id, "practice.created", "practice", p.id, name=p.name)
    return profile_get(a)


def profile_get(a: Access) -> dict:
    p = a.practice
    return dict(id=p.id, name=p.name, trading_name=p.trading_name, abn=p.abn, email=p.email, phone=p.phone, address=p.address, brand_colour=p.brand_colour, fy_end_month=p.fy_end_month,
                settings=a.settings, role=a.role, capabilities=sorted(a.caps))


def update_profile(db, ctx, a: Access, body: dict) -> dict:
    a.require("settings")
    p = a.practice
    for k, mx in (("name", 200), ("trading_name", 200), ("abn", 20), ("email", 200), ("phone", 40), ("address", 500)):
        if k in body:
            setattr(p, k, core.text(body[k], k, required=(k == "name"), max_len=mx))
    if p.email and not EMAIL.match(p.email):
        raise PcError("Email address is not valid")
    if p.abn:
        from accfino.modules.practice.engine import ids
        if not ids.valid_abn(p.abn):
            raise PcError("ABN is not well-formed")
    if body.get("brand_colour") is not None:
        c = (body["brand_colour"] or "").strip()
        if c and not re.fullmatch(r"#[0-9a-fA-F]{6}", c):
            raise PcError("Brand colour must look like #1F3A5F")
        p.brand_colour = c or None
    if "fy_end_month" in body:
        mth = int(body["fy_end_month"])
        if not 1 <= mth <= 12:
            raise PcError("Financial year end month must be 1 to 12")
        p.fy_end_month = mth
    db.flush()
    core.audit(db, ctx, p.id, "practice.profile_updated", "practice", p.id, fields=sorted(k for k in body))
    return profile_get(Access(db, ctx))


SETTING_RULES = dict(retention_years=(1, 50), storage_limit_mb=(1, 1_000_000), max_file_mb=(1, 100), dashboard_soon_days=(1, 90), portal_invite_hours=(1, 24 * 30), download_ticket_seconds=(10, 3600))


def update_settings(db, ctx, a: Access, body: dict) -> dict:
    a.require("settings")
    cur = dict(a.practice.settings or {})
    for k, v in body.items():
        if k in SETTING_RULES:
            lo, hi = SETTING_RULES[k]
            try:
                iv = int(v)
            except (TypeError, ValueError):
                raise PcError(f"{k} must be a whole number")
            if not lo <= iv <= hi:
                raise PcError(f"{k} must be between {lo} and {hi}")
            cur[k] = iv
        elif k == "holidays":
            cur[k] = sorted({core.parse_date(x, "holiday").isoformat() for x in (v or [])})
        elif k == "dedupe":
            cur[k] = {kk: vv for kk, vv in (v or {}).items() if kk in ("name_threshold", "match_email", "match_phone", "match_identifier")}
        elif k == "billing":
            b = dict(cur.get("billing") or {})
            for kk in ("payment_terms_days", "tax_rate", "revenue_account", "default_service"):
                if kk in (v or {}):
                    b[kk] = v[kk]
            cur[k] = b
        else:
            raise PcError(f"Unknown setting '{k}'")
    a.practice.settings = cur
    db.flush()
    core.audit(db, ctx, a.practice_id, "practice.settings_updated", "practice", a.practice_id, keys=sorted(body))
    return core.get_settings(a.practice)


# ------------------------------------------------------------------------------------------------------------------------------ members and teams
def _mdict(mem, user):
    return dict(id=mem.id, staff_id=mem.user_id, name=getattr(user, "full_name", None) if user else None, email=getattr(user, "email", None) if user else None,
                role=mem.role, status=mem.status)


def members(db, a: Access) -> list:
    a.require("view")
    rows = db.query(P.PcMember, User).join(User, User.id == P.PcMember.user_id).filter(P.PcMember.practice_id == a.practice_id).order_by(P.PcMember.id).all()
    return [_mdict(mem, u) for mem, u in rows]


def _admins(db, a):
    return db.query(P.PcMember).filter_by(practice_id=a.practice_id, role="admin", status="active").count()


def add_member(db, ctx, a: Access, user_id: int, role: str) -> dict:
    a.require("members")
    if role not in P.PRACTICE_ROLES:
        raise PcError(f"role must be one of {', '.join(P.PRACTICE_ROLES)}")
    u = db.get(User, user_id)
    org_member = db.query(m.OrgMembership).filter_by(org_id=a.practice.org_id, user_id=user_id).first() if u else None
    if u is None or org_member is None:
        raise PcError("That user must first be added to the organisation (Settings > Users); practice membership builds on organisation membership")
    if org_member.role in ("employee", "payroll", "payroll_admin"):
        raise PcError("Payroll and employee-only users cannot be practice staff")
    if db.query(P.PcMember.id).filter_by(practice_id=a.practice_id, user_id=user_id).first():
        raise Conflict("That user is already a member of this practice")
    mem = P.PcMember(practice_id=a.practice_id, user_id=user_id, role=role)
    db.add(mem)
    db.flush()
    core.audit(db, ctx, a.practice_id, "member.added", "member", mem.id, target_user=user_id, role=role)
    return _mdict(mem, u)


def change_member(db, ctx, a: Access, member_id: int, *, role=None, status=None) -> dict:
    a.require("members")
    mem = db.query(P.PcMember).filter_by(practice_id=a.practice_id, id=member_id).first()
    if mem is None:
        raise NotFound("Member")
    before = (mem.role, mem.status)
    new_role, new_status = role or mem.role, status or mem.status
    if new_role not in P.PRACTICE_ROLES:
        raise PcError(f"role must be one of {', '.join(P.PRACTICE_ROLES)}")
    if new_status not in ("active", "suspended"):
        raise PcError("status must be active or suspended")
    if mem.role == "admin" and mem.status == "active" and (new_role != "admin" or new_status != "active") and _admins(db, a) <= 1:
        raise Conflict("The practice must keep at least one active administrator")
    mem.role, mem.status = new_role, new_status
    db.flush()
    core.audit(db, ctx, a.practice_id, "member.changed", "member", mem.id, target_user=mem.user_id, before=before, after=(mem.role, mem.status))
    return _mdict(mem, db.get(User, mem.user_id))


def remove_member(db, ctx, a: Access, member_id: int) -> dict:
    a.require("members")
    mem = db.query(P.PcMember).filter_by(practice_id=a.practice_id, id=member_id).first()
    if mem is None:
        raise NotFound("Member")
    if mem.role == "admin" and mem.status == "active" and _admins(db, a) <= 1:
        raise Conflict("The practice must keep at least one active administrator")
    uid = mem.user_id
    # assignments are cleared so the person no longer appears as the responsible staff member; history stays in the audit log
    for col in ("manager_id", "preparer_id", "reviewer_id"):
        db.query(P.PcClient).filter(P.PcClient.practice_id == a.practice_id, getattr(P.PcClient, col) == uid).update({col: None})
    db.query(P.PcTeamMember).filter(P.PcTeamMember.user_id == uid, P.PcTeamMember.team_id.in_(db.query(P.PcTeam.id).filter_by(practice_id=a.practice_id))).delete(synchronize_session=False)
    db.delete(mem)
    db.flush()
    core.audit(db, ctx, a.practice_id, "member.removed", "member", member_id, target_user=uid)
    return dict(removed=member_id)


def teams(db, a: Access) -> list:
    a.require("view")
    out = []
    for t in db.query(P.PcTeam).filter_by(practice_id=a.practice_id).order_by(P.PcTeam.name):
        out.append(dict(id=t.id, name=t.name, members=[u for (u,) in db.query(P.PcTeamMember.user_id).filter_by(team_id=t.id)]))
    return out


def create_team(db, ctx, a: Access, name: str, user_ids=()) -> dict:
    a.require("members")
    name = core.text(name, "Team name", required=True, max_len=80)
    if db.query(P.PcTeam.id).filter_by(practice_id=a.practice_id, name=name).first():
        raise Conflict("A team with that name already exists")
    t = P.PcTeam(practice_id=a.practice_id, name=name)
    db.add(t)
    db.flush()
    set_team_members(db, ctx, a, t.id, user_ids, _audit=False)
    core.audit(db, ctx, a.practice_id, "team.created", "team", t.id, name=name)
    return dict(id=t.id, name=name, members=list(user_ids))


def set_team_members(db, ctx, a: Access, team_id: int, user_ids, _audit=True) -> dict:
    a.require("members")
    t = db.query(P.PcTeam).filter_by(practice_id=a.practice_id, id=team_id).first()
    if t is None:
        raise NotFound("Team")
    ids = sorted({int(x) for x in user_ids})
    for u in ids:
        a.require_member_user(u, "Team member")
    db.query(P.PcTeamMember).filter_by(team_id=t.id).delete()
    for u in ids:
        db.add(P.PcTeamMember(team_id=t.id, user_id=u))
    db.flush()
    if _audit:
        core.audit(db, ctx, a.practice_id, "team.members_set", "team", t.id, members=ids)
    return dict(id=t.id, name=t.name, members=ids)


def delete_team(db, ctx, a: Access, team_id: int) -> dict:
    a.require("members")
    t = db.query(P.PcTeam).filter_by(practice_id=a.practice_id, id=team_id).first()
    if t is None:
        raise NotFound("Team")
    db.query(P.PcClient).filter_by(practice_id=a.practice_id, team_id=t.id).update({"team_id": None})
    db.delete(t)
    db.flush()
    core.audit(db, ctx, a.practice_id, "team.deleted", "team", team_id)
    return dict(removed=team_id)


def audit_trail(db, a: Access, limit: int = 100, action_prefix: str = "") -> list:
    """The practice's own audit entries (those written with this practice_id), newest first. Read-only."""
    a.require("audit_view")
    import json
    rows = db.query(m.AuditLog).filter(m.AuditLog.org_id == a.practice.org_id, m.AuditLog.action.like("practice.%")).order_by(m.AuditLog.id.desc()).limit(min(int(limit), 500)).all()
    out = []
    for r in rows:
        if action_prefix and not r.action.startswith("practice." + action_prefix):
            continue
        out.append(dict(id=r.id, at=r.occurred_at.isoformat(), action=r.action, user=r.username, entity=r.entity, entity_id=r.entity_id, detail=r.detail))
    return out
