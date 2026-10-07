"""Compliance calendar: generates the obligations the tax profile implies (idempotently), tracks their status and flags overdue / due-soon items.
Registrations (ABN, GST, PAYG, FBT, state taxes) live here too, with a check of what the organisation's own data says it should be registered for."""
from datetime import date, datetime, timedelta
from typing import List, Optional

from accfino.modules.taxation.engine import calendar as C, rules as R
from accfino.modules.taxation.models import tax as T
from accfino.modules.taxation.services import core, profile as P
from accfino.modules.taxation.services.core import NotFound, TaxError

DUE_SOON_DAYS = 14
OPEN = ("upcoming", "in_progress", "prepared")


def profile_flags(db, ctx, p: T.TaxProfile) -> dict:
    has_loans = db.query(T.TaxDiv7aLoan.id).filter_by(org_id=ctx.org.id, status="active").first() is not None
    pt = db.query(T.TaxRegistration.id).filter(T.TaxRegistration.org_id == ctx.org.id, T.TaxRegistration.kind == "payroll_tax", T.TaxRegistration.cancelled_on.is_(None)).first() is not None
    return dict(payroll_tax_registered=pt, state=p.state, entity_type=p.entity_type, bas_frequency=p.bas_frequency, gst_registered=p.gst_registered, fbt_registered=p.fbt_registered, tpar_required=p.tpar_required,
                uses_agent_program=p.uses_agent_program, has_div7a_loans=has_loans and p.entity_type == "company")


def generate(db, ctx, a: core.Access, fy: str, today: Optional[date] = None) -> dict:
    """Create missing obligations for the income year; existing rows (matched by source_key) keep their status and any dates the user changed."""
    a.require("prepare")
    core.check_fy(ctx, fy)
    p = P.get(db, ctx)
    rs = core.rules_for_fy(db, ctx, fy)
    hol = C.holidays_from(rs, p.extra_holidays or [])
    items = C.generate(rs, fy, profile_flags(db, ctx, p), hol, ctx.org.fy_end_month or 6)
    if p.asic_review_date and p.entity_type == "company":
        start, end = R.fy_bounds(fy, ctx.org.fy_end_month or 6)
        m, d = (int(x) for x in p.asic_review_date.split("-"))
        for y in (start.year, end.year):
            try:
                due = date(y, m, d)
            except ValueError:
                continue
            if start <= due <= end:
                items.append(dict(kind="asic_review", title=f"ASIC annual review date {due.strftime('%d %b %Y')}", fy=fy, period_start=None, period_end=None,
                                  due_date=C.next_business_day(due, hol), original_due_date=due, agent_due_date=None, source_key=f"asic_review:{due.isoformat()}",
                                  note="Company review date. ASIC fees and the solvency resolution timing are outside AccFino: check ASIC Connect.", authority="ASIC"))
    created = 0
    for it in items:
        row = db.query(T.TaxObligation).filter_by(org_id=ctx.org.id, source_key=it["source_key"]).first()
        if row is not None:
            continue
        db.add(T.TaxObligation(org_id=ctx.org.id, kind=it["kind"], title=it["title"], authority=it.get("authority", "ATO"), fy=fy, period_start=it["period_start"], period_end=it["period_end"],
                               due_date=it["due_date"], original_due_date=it["original_due_date"], agent_due_date=it.get("agent_due_date"), source_key=it["source_key"],
                               note=it.get("note"), auto_generated=True, status="upcoming"))
        created += 1
    db.flush()
    if created:
        core.record(db, ctx, "calendar.generate", "tax_obligation", None, f"Generated {created} obligations for {fy}", None, dict(fy=fy, created=created))
    return dict(fy=fy, created=created, total=len(items), rule_set=rs.id,
                caveat="Due dates roll to the next business day using weekends and the national holidays in the rules; add your state's public holidays in the tax profile. Confirm dates on ato.gov.au.")


def to_dict(o: T.TaxObligation, today: Optional[date] = None) -> dict:
    today = today or date.today()
    effective_due = o.due_date
    state = o.status
    if o.status in OPEN:
        if effective_due < today:
            state = "overdue"
        elif effective_due <= today + timedelta(days=DUE_SOON_DAYS):
            state = "due_soon"
    return dict(id=o.id, kind=o.kind, title=o.title, authority=o.authority, fy=o.fy, period_start=core.plain(o.period_start), period_end=core.plain(o.period_end),
                due_date=o.due_date.isoformat(), original_due_date=core.plain(o.original_due_date), agent_due_date=core.plain(o.agent_due_date), status=o.status, display_status=state,
                days_to_due=(o.due_date - today).days, lodged_on=core.plain(o.lodged_on), paid_on=core.plain(o.paid_on), reference=o.reference, amount=core.plain(o.amount),
                linked_type=o.linked_type, linked_id=o.linked_id, auto_generated=o.auto_generated, note=o.note)


def listing(db, ctx, fy: str = "", status: str = "", kind: str = "", today: Optional[date] = None) -> List[dict]:
    q = db.query(T.TaxObligation).filter(T.TaxObligation.org_id == ctx.org.id)
    if fy:
        q = q.filter(T.TaxObligation.fy == fy)
    if status:
        q = q.filter(T.TaxObligation.status == status)
    if kind:
        q = q.filter(T.TaxObligation.kind == kind)
    rows = [to_dict(o, today) for o in q.order_by(T.TaxObligation.due_date, T.TaxObligation.id)]
    return rows


def get(db, ctx, oid: int) -> T.TaxObligation:
    o = db.query(T.TaxObligation).filter_by(org_id=ctx.org.id, id=oid).first()
    if o is None:
        raise NotFound("Obligation")
    return o


def add_custom(db, ctx, a: core.Access, body: dict) -> T.TaxObligation:
    a.require("prepare")
    title = (body.get("title") or "").strip()
    due = core.parse_date(body.get("due_date"), "due_date")
    if not title or due is None:
        raise TaxError("title and due_date are required")
    kind = body.get("kind") or "custom"
    if kind not in T.OBLIGATION_KINDS:
        raise TaxError(f"kind must be one of {', '.join(T.OBLIGATION_KINDS)}")
    o = T.TaxObligation(org_id=ctx.org.id, kind=kind, title=title[:200], authority=(body.get("authority") or "")[:60] or None, fy=body.get("fy") or R.fy_of(due, ctx.org.fy_end_month or 6),
                        period_start=core.parse_date(body.get("period_start"), "period_start"), period_end=core.parse_date(body.get("period_end"), "period_end"), due_date=due,
                        original_due_date=due, auto_generated=False, status="upcoming", note=(body.get("note") or "")[:500] or None)
    db.add(o)
    db.flush()
    core.record(db, ctx, "obligation.create", "tax_obligation", o.id, f"Custom obligation '{o.title}' due {due.isoformat()}", None, to_dict(o))
    return o


def update(db, ctx, a: core.Access, oid: int, body: dict) -> T.TaxObligation:
    a.require("prepare")
    o = get(db, ctx, oid)
    before = to_dict(o)
    if "status" in body:
        st = body["status"]
        if st not in T.OBLIGATION_STATUSES:
            raise TaxError(f"status must be one of {', '.join(T.OBLIGATION_STATUSES)}")
        if st in ("lodged", "paid", "completed", "not_required"):
            a.require("lodge")
        if o.linked_type and st in ("lodged", "paid"):
            raise TaxError("This obligation is linked to a prepared document: record lodgement or payment on that document so the two stay in step.", 409, "linked")
        o.status = st
        if st == "lodged":
            o.lodged_on = core.parse_date(body.get("lodged_on"), "lodged_on") or date.today()
        if st == "paid":
            o.paid_on = core.parse_date(body.get("paid_on"), "paid_on") or date.today()
    for k in ("reference", "note"):
        if k in body:
            setattr(o, k, (body[k] or "")[:500] or None)
    if "due_date" in body or "agent_due_date" in body:
        if "due_date" in body:
            nd = core.parse_date(body["due_date"], "due_date")
            if nd is None:
                raise TaxError("due_date cannot be empty")
            o.due_date = nd
        if "agent_due_date" in body:
            o.agent_due_date = core.parse_date(body["agent_due_date"], "agent_due_date")
    db.flush()
    core.record(db, ctx, "obligation.update", "tax_obligation", o.id, f"Obligation '{o.title}' updated", before, to_dict(o))
    return o


def delete_custom(db, ctx, a: core.Access, oid: int):
    a.require("prepare")
    o = get(db, ctx, oid)
    if o.auto_generated:
        raise TaxError("Generated obligations cannot be deleted; mark them 'not required' instead (the audit trail keeps the reason).", 409, "generated")
    core.record(db, ctx, "obligation.delete", "tax_obligation", o.id, f"Custom obligation '{o.title}' deleted", to_dict(o), None)
    db.delete(o)


def link_status(db, ctx, obligation_id: Optional[int], status: str, **kw):
    """Called by the BAS / return / FBT workflows so the calendar mirrors the document."""
    if not obligation_id:
        return
    o = db.query(T.TaxObligation).filter_by(org_id=ctx.org.id, id=obligation_id).first()
    if o is None:
        return
    o.status = status
    for k, v in kw.items():
        setattr(o, k, v)


def link_obligation(db, ctx, kind_prefix: str, period_start: date, period_end: date, linked_type: str, linked_id: int) -> Optional[int]:
    o = (db.query(T.TaxObligation).filter(T.TaxObligation.org_id == ctx.org.id, T.TaxObligation.kind.in_((kind_prefix,) if isinstance(kind_prefix, str) else kind_prefix),
                                          T.TaxObligation.period_start == period_start, T.TaxObligation.period_end == period_end).first())
    if o is None:
        return None
    o.linked_type, o.linked_id = linked_type, linked_id
    if o.status == "upcoming":
        o.status = "in_progress"
    return o.id


def summary(db, ctx, today: Optional[date] = None) -> dict:
    rows = listing(db, ctx, today=today)
    open_rows = [r for r in rows if r["status"] in OPEN]
    return dict(overdue=[r for r in open_rows if r["display_status"] == "overdue"], due_soon=[r for r in open_rows if r["display_status"] == "due_soon"],
                next=[r for r in open_rows if r["display_status"] in ("upcoming", "in_progress", "prepared")][:5], open=len(open_rows), total=len(rows))


# ---- registrations --------------------------------------------------------------------------------------------------------
def reg_dict(r: T.TaxRegistration) -> dict:
    return dict(id=r.id, kind=r.kind, authority=r.authority, identifier=r.identifier, registered_on=core.plain(r.registered_on), cancelled_on=core.plain(r.cancelled_on), notes=r.notes, active=r.cancelled_on is None)


def registrations(db, ctx) -> List[dict]:
    return [reg_dict(r) for r in db.query(T.TaxRegistration).filter_by(org_id=ctx.org.id).order_by(T.TaxRegistration.kind, T.TaxRegistration.id)]


def save_registration(db, ctx, a: core.Access, body: dict, rid: Optional[int] = None) -> T.TaxRegistration:
    a.require("config")
    kind = body.get("kind")
    if kind not in T.REGISTRATION_KINDS:
        raise TaxError(f"kind must be one of {', '.join(T.REGISTRATION_KINDS)}")
    ident = (body.get("identifier") or "").strip()
    if "tfn" in ident.lower() or (ident.replace(" ", "").isdigit() and len(ident.replace(" ", "")) == 9 and kind != "abn" and kind != "other"):
        raise TaxError("Do not enter a Tax File Number in AccFino. Record the registration without it.")
    r = db.query(T.TaxRegistration).filter_by(org_id=ctx.org.id, id=rid).first() if rid else T.TaxRegistration(org_id=ctx.org.id, created_by=ctx.user_id)
    if rid and r is None:
        raise NotFound("Registration")
    before = reg_dict(r) if rid else None
    r.kind, r.authority, r.identifier = kind, (body.get("authority") or "ATO")[:60], ident[:60] or None
    r.registered_on, r.cancelled_on = core.parse_date(body.get("registered_on"), "registered_on"), core.parse_date(body.get("cancelled_on"), "cancelled_on")
    r.notes = (body.get("notes") or "")[:500] or None
    if not rid:
        db.add(r)
    db.flush()
    core.record(db, ctx, "registration.save", "tax_registration", r.id, f"Registration {kind} {'updated' if rid else 'added'}", before, reg_dict(r))
    return r


def delete_registration(db, ctx, a: core.Access, rid: int):
    a.require("config")
    r = db.query(T.TaxRegistration).filter_by(org_id=ctx.org.id, id=rid).first()
    if r is None:
        raise NotFound("Registration")
    core.record(db, ctx, "registration.delete", "tax_registration", r.id, f"Registration {r.kind} deleted", reg_dict(r), None)
    db.delete(r)
