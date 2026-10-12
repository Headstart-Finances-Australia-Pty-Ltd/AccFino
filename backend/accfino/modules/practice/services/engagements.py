"""Engagements, jobs, tasks, dependencies, checklists, review points, deadlines (internal targets vs. statutory dates with source/verification/override), recurrence and reminders.
NO statutory (ATO) date is built in: a statutory rule is data the practice enters together with its source and the date it was last verified."""
import datetime as dt
import json

from sqlalchemy import func

from accfino.modules.practice.engine import deadlines as DL
from accfino.modules.practice.models import practice as P
from accfino.modules.practice.services import core
from accfino.modules.practice.services.core import Access, Conflict, Forbidden, NotFound, PcError

SERVICE_TYPES = ("bookkeeping", "financial_statements", "tax_return", "bas", "payroll", "advisory", "other")
ENG_FLOW = {"propose": (("draft",), "proposed"), "accept": (("draft", "proposed"), "accepted"), "start": (("accepted",), "active"), "complete": (("active",), "completed"),
            "terminate": (("accepted", "active"), "terminated"), "archive": (("completed", "terminated"), "archived")}
JOB_FLOW = {  # action -> (from, to)
    "start": (("not_started", "changes_required", "blocked", "awaiting_client"), "in_progress"), "await_client": (("in_progress",), "awaiting_client"), "block": (("not_started", "in_progress"), "blocked"),
    "submit_review": (("in_progress",), "ready_for_review"), "request_changes": (("ready_for_review",), "changes_required"), "complete": (("ready_for_review",), "completed"),
}


# ------------------------------------------------------------------ helpers
def edict(e: P.PcEngagement) -> dict:
    return dict(id=e.id, client_id=e.client_id, entity_id=e.entity_id, service_type=e.service_type, template_id=e.template_id, title=e.title, status=e.status, period_from=core.plain(e.period_from),
                period_to=core.plain(e.period_to), manager_id=e.manager_id, preparer_id=e.preparer_id, reviewer_id=e.reviewer_id, scope=e.scope, deliverables=e.deliverables, billing_basis=e.billing_basis,
                fixed_fee=core.plain(e.fixed_fee), accepted_at=core.plain(e.accepted_at), accepted_by=e.accepted_by, renewed_from_id=e.renewed_from_id, termination_reason=e.termination_reason)


def erow(db, a: Access, eid: int) -> P.PcEngagement:
    e = db.query(P.PcEngagement).filter_by(practice_id=a.practice_id, id=eid).first()
    if e is None:
        raise NotFound("Engagement")
    a.client(e.client_id)
    return e


def jrow(db, a: Access, jid: int) -> P.PcJob:
    j = db.query(P.PcJob).filter_by(practice_id=a.practice_id, id=jid).first()
    if j is None:
        raise NotFound("Job")
    a.client(j.client_id)
    return j


def trow(db, a: Access, tid: int):
    t = db.query(P.PcTask).filter_by(practice_id=a.practice_id, id=tid).first()
    if t is None:
        raise NotFound("Task")
    return t, jrow(db, a, t.job_id)


def _holidays(a: Access):
    return {core.parse_date(x, "holiday") for x in a.settings.get("holidays", [])}


# ------------------------------------------------------------------ deadline rules and deadlines
def create_rule(db, ctx, a: Access, name, kind, rule: dict, *, service_type=None, source=None, source_verified_at=None) -> dict:
    a.require("settings")
    if kind not in ("internal", "statutory"):
        raise PcError("kind must be internal or statutory")
    if kind == "statutory" and not (core.text(source, "Source", max_len=300) and source_verified_at):
        raise PcError("A statutory rule needs its source (e.g. the ATO page) and the date you last verified it")
    try:
        DL.from_rule(rule, dt.date(2026, 6, 30))
    except (KeyError, ValueError, TypeError):
        raise PcError("The rule is not valid. Use basis period_end (months, days, day_of_month) or fixed (month, day_of_month), and adjust none/next_business_day/prev_business_day")
    r = P.PcDeadlineRule(practice_id=a.practice_id, name=core.text(name, "Name", required=True, max_len=120), service_type=service_type, kind=kind, rule=rule, source=source,
                         source_verified_at=core.parse_date(source_verified_at, "Verified date"))
    if db.query(P.PcDeadlineRule.id).filter_by(practice_id=a.practice_id, name=r.name).first():
        raise Conflict("A rule with that name exists")
    db.add(r)
    db.flush()
    core.audit(db, ctx, a.practice_id, "deadline_rule.created", "deadline_rule", r.id, kind=kind, source=source)
    return dict(id=r.id, name=r.name, kind=kind, rule=rule, source=source, source_verified_at=core.plain(r.source_verified_at))


def rules(db, a: Access) -> list:
    a.require("view")
    return [dict(id=r.id, name=r.name, kind=r.kind, rule=r.rule, service_type=r.service_type, source=r.source, source_verified_at=core.plain(r.source_verified_at)) for r in
            db.query(P.PcDeadlineRule).filter_by(practice_id=a.practice_id, active=True).order_by(P.PcDeadlineRule.name)]


def ddict(d: P.PcDeadline, today=None) -> dict:
    out = dict(id=d.id, client_id=d.client_id, engagement_id=d.engagement_id, job_id=d.job_id, title=d.title, kind=d.kind, due_date=core.plain(d.due_date), calculated_date=core.plain(d.calculated_date),
               source=d.source, verified=d.verified, verified_at=core.plain(d.verified_at), override_reason=d.override_reason, status=d.status,
               label="Statutory date" + ("" if d.verified else " (unverified)") if d.kind == "statutory" else "Internal target")
    if today:
        out["state"] = DL.classify(d.due_date, today, d.status == "completed")
    return out


def add_deadline(db, ctx, a: Access, engagement_id: int, rule_id: int, *, period_end=None, title=None, job_id=None) -> dict:
    a.require("engagements")
    e = erow(db, a, engagement_id)
    r = db.query(P.PcDeadlineRule).filter_by(practice_id=a.practice_id, id=rule_id, active=True).first()
    if r is None:
        raise NotFound("Deadline rule")
    pe = core.parse_date(period_end, "Period end", e.period_to)
    if pe is None:
        raise PcError("Set the engagement period (or give a period end) to calculate a deadline")
    key = f"dl:{e.id}:{r.id}:{pe.isoformat()}"
    if db.query(P.PcRunLog.id).filter_by(practice_id=a.practice_id, kind="deadline", key=key).first():
        raise Conflict("That deadline already exists for this engagement and period")
    due = DL.from_rule(r.rule, pe, _holidays(a))
    d = P.PcDeadline(practice_id=a.practice_id, client_id=e.client_id, engagement_id=e.id, job_id=job_id, title=core.text(title or r.name, "Title", required=True), kind=r.kind, due_date=due,
                     calculated_date=due, rule_id=r.id, source=r.source, verified=False)
    db.add(d)
    db.flush()
    db.add(P.PcRunLog(practice_id=a.practice_id, kind="deadline", key=key, ref_id=d.id))
    db.flush()
    core.audit(db, ctx, a.practice_id, "deadline.created", "deadline", d.id, kind=d.kind, due=due, rule=r.name)
    return ddict(d, core.today())


def _drow(db, a: Access, did: int) -> P.PcDeadline:
    d = db.query(P.PcDeadline).filter_by(practice_id=a.practice_id, id=did).first()
    if d is None:
        raise NotFound("Deadline")
    a.client(d.client_id)
    return d


def verify_deadline(db, ctx, a: Access, did: int, source: str) -> dict:
    """A person confirms a statutory date against its source. Required before the date is presented as verified."""
    if a.role not in ("admin", "partner", "manager"):
        raise Forbidden("Only a manager or partner can verify a statutory date")
    d = _drow(db, a, did)
    if d.kind != "statutory":
        raise Conflict("Only statutory deadlines are verified")
    if not core.text(source, "Source", required=True, max_len=300):
        raise PcError("Source is required")
    d.source, d.verified, d.verified_at, d.verified_by = source.strip(), True, core.now(), ctx.user_id
    db.flush()
    core.audit(db, ctx, a.practice_id, "deadline.verified", "deadline", d.id, source=source[:200])
    return ddict(d, core.today())


def override_deadline(db, ctx, a: Access, did: int, new_due, reason: str) -> dict:
    a.require("engagements")
    d = _drow(db, a, did)
    if d.status != "open":
        raise Conflict("Only open deadlines can be changed")
    if d.kind == "statutory" and a.role not in ("admin", "partner", "manager"):
        raise Forbidden("Only a manager or partner can override a statutory date")
    if not core.text(reason, "Reason", required=True, max_len=300):
        raise PcError("A reason is required")
    old = d.due_date
    d.due_date = core.parse_date(new_due, "New date")
    d.override_reason = reason.strip()
    if d.kind == "statutory":
        d.verified, d.verified_at = False, None          # a changed statutory date must be verified again
    db.flush()
    core.audit(db, ctx, a.practice_id, "deadline.overridden", "deadline", d.id, old=old, new=d.due_date, calculated=d.calculated_date, reason=reason[:200])
    return ddict(d, core.today())


def complete_deadline(db, ctx, a: Access, did: int) -> dict:
    a.require("engagements")
    d = _drow(db, a, did)
    if d.status != "open":
        raise Conflict("Already " + d.status)
    d.status, d.completed_at = "completed", core.now()
    db.flush()
    core.audit(db, ctx, a.practice_id, "deadline.completed", "deadline", d.id)
    return ddict(d, core.today())


def deadlines(db, a: Access, *, client_id=None, kind=None, state=None, status=None, page_no=1, size=50) -> dict:
    a.require("view")
    q = db.query(P.PcDeadline).filter(P.PcDeadline.practice_id == a.practice_id, P.PcDeadline.client_id.in_(a.client_ids()))
    if client_id:
        q = q.filter(P.PcDeadline.client_id == client_id)
    if kind:
        q = q.filter(P.PcDeadline.kind == kind)
    if status:
        q = q.filter(P.PcDeadline.status == status)
    today, soon = core.today(), int(a.settings.get("dashboard_soon_days", 14))
    if state == "overdue":
        q = q.filter(P.PcDeadline.status == "open", P.PcDeadline.due_date < today)
    elif state == "due_soon":
        q = q.filter(P.PcDeadline.status == "open", P.PcDeadline.due_date >= today, P.PcDeadline.due_date <= today + dt.timedelta(days=soon))
    elif state == "upcoming":
        q = q.filter(P.PcDeadline.status == "open", P.PcDeadline.due_date > today + dt.timedelta(days=soon))
    meta, q = core.page(q.order_by(P.PcDeadline.due_date, P.PcDeadline.id), page_no, size)
    return dict(**meta, items=[ddict(d, today) for d in q])


# ------------------------------------------------------------------ templates
def create_template(db, ctx, a: Access, name, service_type, jobs, deadline_rule_id=None) -> dict:
    a.require("settings")
    if service_type not in SERVICE_TYPES:
        raise PcError(f"service_type must be one of {', '.join(SERVICE_TYPES)}")
    _validate_template(jobs)
    name = core.text(name, "Name", required=True, max_len=120)
    if db.query(P.PcEngTemplate.id).filter_by(practice_id=a.practice_id, name=name).first():
        raise Conflict("A template with that name exists")
    t = P.PcEngTemplate(practice_id=a.practice_id, name=name, service_type=service_type, jobs=jobs, deadline_rule_id=deadline_rule_id)
    db.add(t)
    db.flush()
    core.audit(db, ctx, a.practice_id, "eng_template.created", "eng_template", t.id, name=name)
    return dict(id=t.id, name=name, service_type=service_type, jobs=jobs)


def _validate_template(jobs):
    if not jobs or not isinstance(jobs, list):
        raise PcError("A template needs at least one job")
    jk = set()
    for j in jobs:
        if not j.get("key") or not j.get("title") or j["key"] in jk:
            raise PcError("Every job needs a unique key and a title")
        jk.add(j["key"])
        tk = {t.get("key") for t in j.get("tasks", [])}
        if len(tk) != len(j.get("tasks", [])) or None in tk:
            raise PcError(f"Job {j['key']}: tasks need unique keys")
        for t in j.get("tasks", []):
            for n in t.get("needs", []):
                if n not in tk:
                    raise PcError(f"Task {t['key']} depends on unknown task {n}")
        _no_cycle(j.get("tasks", []))


def _no_cycle(tasks):
    deps = {t["key"]: list(t.get("needs", [])) for t in tasks}
    state = {}
    def visit(k):
        if state.get(k) == 1:
            raise PcError("Task dependencies contain a cycle")
        if state.get(k) == 2:
            return
        state[k] = 1
        for n in deps[k]:
            visit(n)
        state[k] = 2
    for k in deps:
        visit(k)


def templates(db, a: Access) -> list:
    a.require("view")
    return [dict(id=t.id, name=t.name, service_type=t.service_type, jobs=t.jobs) for t in db.query(P.PcEngTemplate).filter_by(practice_id=a.practice_id, active=True).order_by(P.PcEngTemplate.name)]


# ------------------------------------------------------------------ engagements
def create(db, ctx, a: Access, client_id: int, title: str, service_type: str, *, template_id=None, period_from=None, period_to=None, entity_id=None, billing_basis="hourly", fixed_fee=None,
           scope=None, deliverables=None, manager_id=None, preparer_id=None, reviewer_id=None, renewed_from_id=None) -> dict:
    a.require("engagements")
    c = a.client(client_id, allow_archived=False)
    if c.status != "active":
        raise Conflict("Engagements can only be created for active clients")
    if service_type not in SERVICE_TYPES:
        raise PcError(f"service_type must be one of {', '.join(SERVICE_TYPES)}")
    if billing_basis not in ("hourly", "fixed"):
        raise PcError("billing_basis must be hourly or fixed")
    fee = None
    if billing_basis == "fixed":
        from decimal import Decimal, InvalidOperation
        try:
            fee = Decimal(str(fixed_fee)).quantize(Decimal("0.01"))
        except (InvalidOperation, TypeError):
            raise PcError("A fixed-fee engagement needs a fixed fee")
        if fee <= 0:
            raise PcError("The fixed fee must be greater than zero")
    pf, pt = core.parse_date(period_from, "Period from"), core.parse_date(period_to, "Period to")
    if pf and pt and pt < pf:
        raise PcError("Period to cannot be before period from")
    if entity_id and not db.query(P.PcClientEntity.id).filter_by(client_id=c.id, entity_id=entity_id).first():
        raise PcError("That entity is not linked to this client")
    mgr, prep, rev = manager_id or c.manager_id, preparer_id or c.preparer_id, reviewer_id or c.reviewer_id
    for x, lab in ((mgr, "Manager"), (prep, "Preparer"), (rev, "Reviewer")):
        a.require_member_user(x, lab)
    if prep and prep == rev:
        raise PcError("The preparer and the reviewer must be different people")
    tpl = None
    if template_id:
        tpl = db.query(P.PcEngTemplate).filter_by(practice_id=a.practice_id, id=template_id, active=True).first()
        if tpl is None:
            raise NotFound("Engagement template")
    e = P.PcEngagement(practice_id=a.practice_id, client_id=c.id, entity_id=entity_id, service_type=service_type, template_id=template_id, title=core.text(title, "Title", required=True), period_from=pf,
                       period_to=pt, manager_id=mgr, preparer_id=prep, reviewer_id=rev, scope=core.text(scope, "Scope", max_len=4000), deliverables=core.text(deliverables, "Deliverables", max_len=4000),
                       billing_basis=billing_basis, fixed_fee=fee, renewed_from_id=renewed_from_id, created_by=ctx.user_id)
    db.add(e)
    db.flush()
    if tpl:
        _instantiate(db, a, e, tpl)
    core.audit(db, ctx, a.practice_id, "engagement.created", "engagement", e.id, client_id=c.id, template=template_id)
    return edict(e)


def _instantiate(db, a: Access, e: P.PcEngagement, tpl: P.PcEngTemplate):
    base = e.period_to or core.today()
    for jd in tpl.jobs:
        due = DL.roll_forward(base + dt.timedelta(days=int(jd.get("due_offset_days", 0))), _holidays(a)) if jd.get("due_offset_days") is not None else None
        j = P.PcJob(practice_id=a.practice_id, engagement_id=e.id, client_id=e.client_id, tkey=jd["key"], title=jd["title"], owner_id=e.preparer_id, reviewer_id=e.reviewer_id, due_date=due)
        db.add(j)
        db.flush()
        tmap = {}
        for td in jd.get("tasks", []):
            t = P.PcTask(practice_id=a.practice_id, job_id=j.id, tkey=td["key"], title=td["title"], owner_id=e.preparer_id, mandatory=bool(td.get("mandatory", True)),
                         due_date=(base + dt.timedelta(days=int(td["due_offset_days"]))) if td.get("due_offset_days") is not None else None)
            db.add(t)
            db.flush()
            tmap[td["key"]] = t
            for item in td.get("checklist", []):
                db.add(P.PcChecklistItem(practice_id=a.practice_id, task_id=t.id, text=str(item)[:300]))
        for td in jd.get("tasks", []):
            for n in td.get("needs", []):
                db.add(P.PcTaskDep(task_id=tmap[td["key"]].id, needs_task_id=tmap[n].id))
    db.flush()


def transition(db, ctx, a: Access, eid: int, action: str, *, reason=None, accepted_by=None) -> dict:
    if action not in ENG_FLOW:
        raise PcError(f"action must be one of {', '.join(ENG_FLOW)}")
    a.require("engagements")
    e = erow(db, a, eid)
    frm, to = ENG_FLOW[action]
    if e.status not in frm:
        raise Conflict(f"Cannot {action} an engagement that is {e.status}", "invalid_transition")
    if action == "accept":
        e.accepted_by = core.text(accepted_by, "Accepted by (who at the client accepted)", required=True)
        e.accepted_at = core.now()
    if action == "start":
        if not e.period_from or not e.period_to:
            raise PcError("Set the engagement period before starting")
        c = db.get(P.PcClient, e.client_id)
        if c.status != "active":
            raise Conflict("The client is not active")
    if action == "complete":
        open_jobs = db.query(P.PcJob.id).filter(P.PcJob.engagement_id == e.id, P.PcJob.status != "completed").count()
        if open_jobs:
            raise Conflict(f"{open_jobs} job(s) are not completed", "open_jobs")
    if action == "terminate":
        if not core.text(reason, "Reason", required=True, max_len=500):
            raise PcError("A reason is required")
        e.terminated_at, e.termination_reason = core.now(), reason.strip()
        for d in db.query(P.PcDeadline).filter_by(engagement_id=e.id, status="open"):
            d.status = "cancelled"
    if action == "archive":
        pass
    e.status = to
    db.flush()
    core.audit(db, ctx, a.practice_id, f"engagement.{action}", "engagement", e.id, to=to, reason=(reason or "")[:300])
    return edict(e)


def renew(db, ctx, a: Access, eid: int) -> dict:
    """Next-period copy of a completed/active engagement. Idempotent: an engagement can be renewed once."""
    a.require("engagements")
    e = erow(db, a, eid)
    if e.status not in ("active", "completed"):
        raise Conflict("Only active or completed engagements can be renewed")
    existing = db.query(P.PcEngagement).filter_by(practice_id=a.practice_id, renewed_from_id=e.id).first()
    if existing:
        raise Conflict(f"Already renewed as engagement {existing.id}", "already_renewed")
    if not (e.period_from and e.period_to):
        raise PcError("The engagement has no period to roll forward")
    span = (e.period_to - e.period_from).days + 1
    months = 12 if span > 300 else 3 if span > 80 else 1
    nf, nt = e.period_to + dt.timedelta(days=1), DL.next_period_end(e.period_to, {12: "annual", 3: "quarterly", 1: "monthly"}[months])
    out = create(db, ctx, a, e.client_id, e.title, e.service_type, template_id=e.template_id, period_from=nf, period_to=nt, entity_id=e.entity_id, billing_basis=e.billing_basis,
                 fixed_fee=e.fixed_fee, scope=e.scope, deliverables=e.deliverables, manager_id=e.manager_id, preparer_id=e.preparer_id, reviewer_id=e.reviewer_id, renewed_from_id=e.id)
    core.audit(db, ctx, a.practice_id, "engagement.renewed", "engagement", e.id, new=out["id"])
    return out


def listing(db, a: Access, *, client_id=None, status=None, service_type=None, page_no=1, size=25) -> dict:
    a.require("view")
    q = db.query(P.PcEngagement).filter(P.PcEngagement.practice_id == a.practice_id, P.PcEngagement.client_id.in_(a.client_ids()))
    if client_id:
        q = q.filter(P.PcEngagement.client_id == client_id)
    if status:
        q = q.filter(P.PcEngagement.status == status)
    if service_type:
        q = q.filter(P.PcEngagement.service_type == service_type)
    meta, q = core.page(q.order_by(P.PcEngagement.id.desc()), page_no, size)
    return dict(**meta, items=[edict(e) for e in q])


def get(db, a: Access, eid: int) -> dict:
    e = erow(db, a, eid)
    d = edict(e)
    d["jobs"] = [jdict(db, j) for j in db.query(P.PcJob).filter_by(engagement_id=e.id).order_by(P.PcJob.id)]
    d["deadlines"] = [ddict(x, core.today()) for x in db.query(P.PcDeadline).filter_by(engagement_id=e.id).order_by(P.PcDeadline.due_date)]
    return d


# ------------------------------------------------------------------ jobs, tasks
def jdict(db, j: P.PcJob) -> dict:
    tasks = db.query(P.PcTask).filter_by(job_id=j.id).order_by(P.PcTask.id).all()
    deps = {}
    for dd in db.query(P.PcTaskDep).filter(P.PcTaskDep.task_id.in_([t.id for t in tasks] or [0])):
        deps.setdefault(dd.task_id, []).append(dd.needs_task_id)
    return dict(id=j.id, engagement_id=j.engagement_id, client_id=j.client_id, key=j.tkey, title=j.title, status=j.status, owner_id=j.owner_id, reviewer_id=j.reviewer_id, due_date=core.plain(j.due_date),
                blocker=j.blocker, completed_at=core.plain(j.completed_at),
                tasks=[dict(id=t.id, key=t.tkey, title=t.title, status=t.status, owner_id=t.owner_id, mandatory=t.mandatory, due_date=core.plain(t.due_date), needs=deps.get(t.id, []), blocker=t.blocker,
                            checklist=[dict(id=c.id, text=c.text, done=c.done) for c in db.query(P.PcChecklistItem).filter_by(task_id=t.id).order_by(P.PcChecklistItem.id)]) for t in tasks])


def job_transition(db, ctx, a: Access, jid: int, action: str, *, reason=None) -> dict:
    if action not in JOB_FLOW:
        raise PcError(f"action must be one of {', '.join(JOB_FLOW)}")
    a.require("engagements")
    j = jrow(db, a, jid)
    e = db.get(P.PcEngagement, j.engagement_id)
    if e.status != "active":
        raise Conflict("The engagement is not active")
    frm, to = JOB_FLOW[action]
    if j.status not in frm:
        raise Conflict(f"Cannot {action.replace('_', ' ')} a job that is {j.status.replace('_', ' ')}", "invalid_transition")
    uid = ctx.user_id
    if action in ("request_changes", "complete"):
        a.require("wp_review")
        if uid == j.owner_id:
            raise Forbidden("You own this job, so you cannot review it (segregation of duties)")
    if action == "request_changes":
        if not core.text(reason, "Reason", required=True, max_len=500):
            raise PcError("Say what must change")
        db.add(P.PcReviewPoint(practice_id=a.practice_id, job_id=j.id, finding=reason.strip(), mandatory=True, raised_by=uid))
    if action == "submit_review":
        open_t = db.query(P.PcTask.id).filter(P.PcTask.job_id == j.id, P.PcTask.mandatory.is_(True), P.PcTask.status != "completed").count()
        if open_t:
            raise Conflict(f"{open_t} mandatory task(s) are not completed", "open_tasks")
        if j.reviewer_id and j.reviewer_id == j.owner_id:
            raise PcError("The job's reviewer must differ from its owner")
    if action == "complete":
        n = db.query(P.PcReviewPoint.id).filter(P.PcReviewPoint.job_id == j.id, P.PcReviewPoint.mandatory.is_(True), P.PcReviewPoint.status != "resolved").count()
        if n:
            raise Conflict(f"{n} mandatory review point(s) are not resolved", "open_review_points")
        j.completed_at, j.completed_by = core.now(), uid
    if action in ("block", "await_client"):
        j.blocker = core.text(reason, "Reason", required=action == "block", max_len=300)
    else:
        j.blocker = None
    j.status = to
    db.flush()
    core.audit(db, ctx, a.practice_id, f"job.{action}", "job", j.id, to=to)
    return jdict(db, j)


def task_transition(db, ctx, a: Access, tid: int, action: str) -> dict:
    a.require("engagements")
    t, j = trow(db, a, tid)
    if db.get(P.PcEngagement, j.engagement_id).status != "active":
        raise Conflict("The engagement is not active")
    if j.status in ("completed", "ready_for_review"):
        raise Conflict("The job is locked for review or completed")
    if action == "start":
        if t.status != "not_started":
            raise Conflict(f"Cannot start a task that is {t.status}")
        blockers = [x.title for x in db.query(P.PcTask).join(P.PcTaskDep, P.PcTaskDep.needs_task_id == P.PcTask.id).filter(P.PcTaskDep.task_id == t.id, P.PcTask.status != "completed")]
        if blockers:
            raise Conflict("Waiting for: " + ", ".join(blockers), "dependency")
        t.status = "in_progress"
        if j.status in ("not_started", "changes_required"):
            j.status = "in_progress"
    elif action == "complete":
        if t.status not in ("not_started", "in_progress"):
            raise Conflict(f"Cannot complete a task that is {t.status}")
        blockers = [x.title for x in db.query(P.PcTask).join(P.PcTaskDep, P.PcTaskDep.needs_task_id == P.PcTask.id).filter(P.PcTaskDep.task_id == t.id, P.PcTask.status != "completed")]
        if blockers:
            raise Conflict("Waiting for: " + ", ".join(blockers), "dependency")
        undone = db.query(P.PcChecklistItem.id).filter_by(task_id=t.id, done=False).count()
        if undone:
            raise Conflict(f"{undone} checklist item(s) are not ticked", "checklist")
        t.status, t.completed_at, t.completed_by = "completed", core.now(), ctx.user_id
        if j.status in ("not_started", "changes_required"):
            j.status = "in_progress"
    elif action == "reopen":
        if t.status != "completed":
            raise Conflict("Only completed tasks can be reopened")
        later = db.query(P.PcTask).join(P.PcTaskDep, P.PcTaskDep.task_id == P.PcTask.id).filter(P.PcTaskDep.needs_task_id == t.id, P.PcTask.status == "completed").count()
        if later:
            raise Conflict("Tasks that depend on this one are already completed", "dependants_done")
        t.status, t.completed_at = "in_progress", None
    else:
        raise PcError("action must be start, complete or reopen")
    db.flush()
    core.audit(db, ctx, a.practice_id, f"task.{action}", "task", t.id)
    return dict(id=t.id, status=t.status)


def tick(db, ctx, a: Access, item_id: int, done: bool = True) -> dict:
    a.require("engagements")
    it = db.query(P.PcChecklistItem).filter_by(practice_id=a.practice_id, id=item_id).first()
    if it is None:
        raise NotFound("Checklist item")
    t, j = trow(db, a, it.task_id)
    if t.status == "completed":
        raise Conflict("Reopen the task first")
    it.done, it.done_by, it.done_at = bool(done), ctx.user_id if done else None, core.now() if done else None
    db.flush()
    return dict(id=it.id, done=it.done)


def assign_job(db, ctx, a: Access, jid: int, *, owner_id=None, reviewer_id=None) -> dict:
    a.require("engagements")
    j = jrow(db, a, jid)
    a.require_member_user(owner_id, "Owner")
    a.require_member_user(reviewer_id, "Reviewer")
    o, r = owner_id or j.owner_id, reviewer_id or j.reviewer_id
    if o and o == r:
        raise PcError("The job's owner and reviewer must be different people")
    j.owner_id, j.reviewer_id = o, r
    db.flush()
    core.audit(db, ctx, a.practice_id, "job.assigned", "job", j.id, owner=o, reviewer=r)
    return jdict(db, j)


# ------------------------------------------------------------------ review points
def raise_point(db, ctx, a: Access, jid: int, finding: str, mandatory=True) -> dict:
    a.require("wp_review")
    j = jrow(db, a, jid)
    if j.status not in ("ready_for_review", "changes_required"):
        raise Conflict("Review points are raised while the job is in review")
    if ctx.user_id == j.owner_id:
        raise Forbidden("You own this job, so you cannot review it")
    p = P.PcReviewPoint(practice_id=a.practice_id, job_id=j.id, finding=core.text(finding, "Finding", required=True, max_len=2000), mandatory=bool(mandatory), raised_by=ctx.user_id)
    db.add(p)
    db.flush()
    core.audit(db, ctx, a.practice_id, "review_point.raised", "job", j.id, point=p.id)
    return dict(id=p.id, status=p.status)


def respond_point(db, ctx, a: Access, pid: int, response: str) -> dict:
    a.require("engagements")
    p = db.query(P.PcReviewPoint).filter_by(practice_id=a.practice_id, id=pid).first()
    if p is None:
        raise NotFound("Review point")
    jrow(db, a, p.job_id)
    if p.status == "resolved":
        raise Conflict("Already resolved")
    p.response, p.status, p.responded_by = core.text(response, "Response", required=True, max_len=2000), "responded", ctx.user_id
    db.flush()
    return dict(id=p.id, status=p.status)


def resolve_point(db, ctx, a: Access, pid: int) -> dict:
    a.require("wp_review")
    p = db.query(P.PcReviewPoint).filter_by(practice_id=a.practice_id, id=pid).first()
    if p is None:
        raise NotFound("Review point")
    j = jrow(db, a, p.job_id)
    if ctx.user_id == j.owner_id:
        raise Forbidden("The job owner cannot resolve review points on their own work")
    if p.status == "resolved":
        raise Conflict("Already resolved")
    p.status, p.resolved_by, p.resolved_at = "resolved", ctx.user_id, core.now()
    db.flush()
    core.audit(db, ctx, a.practice_id, "review_point.resolved", "job", j.id, point=p.id)
    return dict(id=p.id, status=p.status)


def points(db, a: Access, jid: int) -> list:
    j = jrow(db, a, jid)
    return [dict(id=p.id, finding=p.finding, mandatory=p.mandatory, status=p.status, response=p.response, raised_by=p.raised_by) for p in db.query(P.PcReviewPoint).filter_by(job_id=j.id).order_by(P.PcReviewPoint.id)]


# ------------------------------------------------------------------ work lists
def my_work(db, a: Access, *, page_no=1, size=50) -> dict:
    a.require("view")
    q = db.query(P.PcJob).filter(P.PcJob.practice_id == a.practice_id, P.PcJob.client_id.in_(a.client_ids()), P.PcJob.status != "completed",
                                 (P.PcJob.owner_id == a.ctx.user_id) | (P.PcJob.reviewer_id == a.ctx.user_id))
    meta, q = core.page(q.order_by(P.PcJob.due_date.is_(None), P.PcJob.due_date), page_no, size)
    return dict(**meta, items=[jdict(db, j) for j in q])


# ------------------------------------------------------------------ recurrence and reminders (idempotent)
def create_recurrence(db, ctx, a: Access, client_id: int, template_id: int, frequency: str, next_period_end) -> dict:
    a.require("engagements")
    c = a.client(client_id, allow_archived=False)
    if frequency not in ("monthly", "quarterly", "annual"):
        raise PcError("frequency must be monthly, quarterly or annual")
    t = db.query(P.PcEngTemplate).filter_by(practice_id=a.practice_id, id=template_id, active=True).first()
    if t is None:
        raise NotFound("Engagement template")
    r = P.PcRecurrence(practice_id=a.practice_id, client_id=c.id, template_id=t.id, frequency=frequency, next_period_end=core.parse_date(next_period_end, "Next period end"), manager_id=c.manager_id)
    db.add(r)
    db.flush()
    core.audit(db, ctx, a.practice_id, "recurrence.created", "recurrence", r.id, frequency=frequency)
    return dict(id=r.id, frequency=frequency, next_period_end=core.plain(r.next_period_end))


def run_recurrences(db, practice_id: int, as_of: dt.date) -> dict:
    """Create the engagement for every recurrence whose period has ended. Safe to run any number of times and concurrently: the (kind,key) run-log row is unique per period."""
    pr = db.get(P.PcPractice, practice_id)
    org = db.get(__import__("accfino.core.models", fromlist=["x"]).Organisation, pr.org_id)
    ctx = core.SystemCtx(org, "recurrence")
    created, skipped = [], 0
    for r in db.query(P.PcRecurrence).filter_by(practice_id=practice_id, active=True).order_by(P.PcRecurrence.id).all():
        guard = 0
        while r.next_period_end <= as_of and guard < 24:
            guard += 1
            pe = r.next_period_end
            key = f"rec:{r.id}:{pe.isoformat()}"
            c = db.get(P.PcClient, r.client_id)
            if db.query(P.PcRunLog.id).filter_by(practice_id=practice_id, kind="recurrence", key=key).first():
                skipped += 1
            elif c.status == "active":
                tpl = db.get(P.PcEngTemplate, r.template_id)
                months = dict(monthly=1, quarterly=3, annual=12)[r.frequency]
                pf = DL.add_months(pe.replace(day=1), -(months - 1))
                e = P.PcEngagement(practice_id=practice_id, client_id=c.id, service_type=tpl.service_type, template_id=tpl.id, title=f"{tpl.name} - period ending {pe.isoformat()}", period_from=pf, period_to=pe,
                                   manager_id=r.manager_id or c.manager_id, preparer_id=c.preparer_id, reviewer_id=c.reviewer_id, status="draft")
                db.add(e)
                db.flush()
                a_stub = type("A", (), dict(practice_id=practice_id, settings=core.get_settings(pr)))()
                _instantiate(db, a_stub, e, tpl)
                db.add(P.PcRunLog(practice_id=practice_id, kind="recurrence", key=key, ref_id=e.id))
                db.flush()
                created.append(e.id)
                core.audit(db, ctx, practice_id, "recurrence.created_engagement", "engagement", e.id, recurrence=r.id, period_end=pe)
            r.next_period_end = DL.next_period_end(pe, r.frequency)
    db.flush()
    return dict(created=created, skipped=skipped)


def run_reminders(db, practice_id: int, as_of: dt.date) -> dict:
    """One notification per (deadline, state, due date) to the engagement manager (and job owner for overdue jobs). Re-running creates nothing new."""
    pr = db.get(P.PcPractice, practice_id)
    soon = int(core.get_settings(pr).get("dashboard_soon_days", 14))
    made = 0
    for d in db.query(P.PcDeadline).filter(P.PcDeadline.practice_id == practice_id, P.PcDeadline.status == "open", P.PcDeadline.due_date <= as_of + dt.timedelta(days=soon)):
        state = DL.classify(d.due_date, as_of, False, soon)
        c = db.get(P.PcClient, d.client_id)
        to = c.manager_id
        if not to:
            continue
        key = f"dl:{d.id}:{state}:{d.due_date.isoformat()}"
        if db.query(P.PcNotification.id).filter_by(practice_id=practice_id, dedupe_key=key).first():
            continue
        db.add(P.PcNotification(practice_id=practice_id, user_id=to, audience="staff", client_id=c.id, subject=f"{'Overdue' if state == 'overdue' else 'Due soon'}: {d.title} ({c.legal_name})",
                                body=f"{d.kind.title()} date {d.due_date.isoformat()}", ref_kind="deadline", ref_id=d.id, dedupe_key=key, status="sent", sent_at=core.now()))
        made += 1
    db.flush()
    return dict(created=made)
