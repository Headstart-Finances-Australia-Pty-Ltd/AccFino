"""Workpapers: templates, lifecycle (draft -> in_preparation -> ready_for_review -> review_in_progress -> changes_required / finalised), comments and queries,
evidence, references to authoritative AccFino records (with drift detection), hash-stamped finalisation and controlled reopen. Preparer and reviewer must differ."""
import hashlib
import json

from accfino.core import models as m
import accfino.modules.accounting.public as accounting
from accfino.modules.practice.models import practice as P
from accfino.modules.practice.services import core, documents as D
from accfino.modules.practice.services.core import Access, Conflict, Forbidden, NotFound, PcError

LINE_KINDS = ("source", "calculated", "user_entered", "assumption", "estimate", "review")
EDITABLE = ("draft", "in_preparation", "changes_required")
REF_KINDS = ("trial_balance", "profit_loss", "balance_sheet", "bank_reconciliation")
TRANSITIONS = {  # action -> (from states, to state)
    "start": (("draft",), "in_preparation"), "submit": (("in_preparation",), "ready_for_review"), "start_review": (("ready_for_review",), "review_in_progress"),
    "request_changes": (("review_in_progress",), "changes_required"), "finalise": (("review_in_progress",), "finalised"), "reopen": (("finalised",), "in_preparation"),
    "withdraw": (("ready_for_review",), "in_preparation"),
}


def _canon(wp_title, period_from, period_to, content) -> str:
    return hashlib.sha256(json.dumps(dict(t=wp_title, f=str(period_from), to=str(period_to), c=content or {}), sort_keys=True, separators=(",", ":"), default=str).encode()).hexdigest()


def clean_content(c) -> dict:
    lines = []
    for ln in (c or {}).get("lines", []) or []:
        k = ln.get("kind", "user_entered")
        if k not in LINE_KINDS:
            raise PcError(f"line kind must be one of {', '.join(LINE_KINDS)}")
        amt = ln.get("amount")
        if amt in (None, ""):
            amt = None
        else:
            from decimal import Decimal, InvalidOperation
            try:
                amt = str(Decimal(str(amt)).quantize(Decimal("0.01")))
            except InvalidOperation:
                raise PcError("Line amounts must be numbers")
        lines.append(dict(label=str(ln.get("label", ""))[:200], amount=amt, kind=k, note=str(ln.get("note", ""))[:500]))
    return dict(lines=lines, conclusion=str((c or {}).get("conclusion", ""))[:4000])


def wdict(w: P.PcWorkpaper, full=False) -> dict:
    d = dict(id=w.id, client_id=w.client_id, entity_id=w.entity_id, engagement_id=w.engagement_id, title=w.title, category=w.category, status=w.status, period_from=core.plain(w.period_from),
             period_to=core.plain(w.period_to), prepared_by=w.prepared_by, reviewer_id=w.reviewer_id, reviewed_by=w.reviewed_by, finalised_by=w.finalised_by,
             finalised_at=core.plain(w.finalised_at), version=w.version, content_hash=w.content_hash, reopen_count=w.reopen_count, updated_at=core.plain(w.updated_at))
    if full:
        d["content"] = w.content or {}
    return d


def row(db, a: Access, wid: int) -> P.PcWorkpaper:
    w = db.query(P.PcWorkpaper).filter_by(practice_id=a.practice_id, id=wid).first()
    if w is None:
        raise NotFound("Workpaper")
    a.client(w.client_id)
    return w


# ------------------------------------------------------------------ templates
def create_template(db, ctx, a: Access, name, category, lines) -> dict:
    a.require("settings")
    name = core.text(name, "Template name", required=True, max_len=120)
    if db.query(P.PcWpTemplate.id).filter_by(practice_id=a.practice_id, name=name).first():
        raise Conflict("A template with that name exists")
    t = P.PcWpTemplate(practice_id=a.practice_id, name=name, category=core.text(category, "Category", required=True, max_len=40), lines=clean_content(dict(lines=lines))["lines"])
    db.add(t)
    db.flush()
    core.audit(db, ctx, a.practice_id, "wp_template.created", "wp_template", t.id, name=name)
    return dict(id=t.id, name=t.name, category=t.category, lines=t.lines)


def templates(db, a: Access) -> list:
    a.require("view")
    return [dict(id=t.id, name=t.name, category=t.category, lines=t.lines or []) for t in db.query(P.PcWpTemplate).filter_by(practice_id=a.practice_id, active=True).order_by(P.PcWpTemplate.name)]


# ------------------------------------------------------------------ lifecycle
def _snapshot(db, w: P.PcWorkpaper, user_id, reason=""):
    h = _canon(w.title, w.period_from, w.period_to, w.content)
    w.content_hash = h
    db.add(P.PcWpVersion(practice_id=w.practice_id, workpaper_id=w.id, version=w.version, content=w.content, content_hash=h, status=w.status, changed_by=user_id, reason=reason[:300]))
    db.flush()


def create(db, ctx, a: Access, client_id: int, title: str, *, category="general", template_id=None, entity_id=None, engagement_id=None, period_from=None, period_to=None, reviewer_id=None) -> dict:
    a.require("wp_prepare")
    c = a.client(client_id, allow_archived=False)
    content = dict(lines=[], conclusion="")
    if template_id:
        t = db.query(P.PcWpTemplate).filter_by(practice_id=a.practice_id, id=template_id, active=True).first()
        if t is None:
            raise NotFound("Template")
        content = dict(lines=[dict(label=l["label"], amount=None, kind=l.get("kind", "user_entered"), note="") for l in t.lines or []], conclusion="")
        category = t.category
    if entity_id and not db.query(P.PcClientEntity.id).filter_by(client_id=c.id, entity_id=entity_id).first():
        raise PcError("That entity is not linked to this client")
    a.require_member_user(reviewer_id, "Reviewer")
    pf, pt = core.parse_date(period_from, "Period from"), core.parse_date(period_to, "Period to")
    if pf and pt and pt < pf:
        raise PcError("Period to cannot be before period from")
    w = P.PcWorkpaper(practice_id=a.practice_id, client_id=c.id, entity_id=entity_id, engagement_id=engagement_id, template_id=template_id, title=core.text(title, "Title", required=True), category=category,
                      period_from=pf, period_to=pt, reviewer_id=reviewer_id or c.reviewer_id, created_by=ctx.user_id, content=content)
    db.add(w)
    db.flush()
    _snapshot(db, w, ctx.user_id, "created")
    core.audit(db, ctx, a.practice_id, "workpaper.created", "workpaper", w.id, client_id=c.id)
    return wdict(w, True)


def get(db, a: Access, wid: int) -> dict:
    w = row(db, a, wid)
    d = wdict(w, True)
    d["comments"] = comments(db, a, wid)
    d["documents"] = [dict(document_id=x.document_id) for x in db.query(P.PcWpDoc).filter_by(workpaper_id=w.id)]
    d["refs"] = [dict(id=r.id, kind=r.kind, params=r.params, seen_hash=r.seen_hash, seen_at=core.plain(r.seen_at), note=r.note) for r in db.query(P.PcWpRef).filter_by(workpaper_id=w.id)]
    d["integrity"] = integrity(w)
    return d


def listing(db, a: Access, *, client_id=None, status=None, mine=False, page_no=1, size=25) -> dict:
    a.require("view")
    q = db.query(P.PcWorkpaper).filter(P.PcWorkpaper.practice_id == a.practice_id, P.PcWorkpaper.client_id.in_(a.client_ids()))
    if client_id:
        q = q.filter(P.PcWorkpaper.client_id == client_id)
    if status:
        if status not in P.WP_STATUSES:
            raise PcError("Unknown status")
        q = q.filter(P.PcWorkpaper.status == status)
    if mine:
        q = q.filter((P.PcWorkpaper.prepared_by == a.ctx.user_id) | (P.PcWorkpaper.reviewer_id == a.ctx.user_id))
    meta, q = core.page(q.order_by(P.PcWorkpaper.updated_at.desc(), P.PcWorkpaper.id.desc()), page_no, size)
    return dict(**meta, items=[wdict(w) for w in q])


def save_content(db, ctx, a: Access, wid: int, *, content=None, title=None, expected_version=None) -> dict:
    a.require("wp_prepare")
    w = row(db, a, wid)
    if w.status not in EDITABLE:
        raise Conflict(f"A workpaper that is {w.status.replace('_', ' ')} cannot be edited")
    if expected_version is not None and int(expected_version) != w.version:
        raise Conflict("This workpaper was changed by someone else. Reload and try again.", "stale_version")
    if title is not None:
        w.title = core.text(title, "Title", required=True)
    if content is not None:
        w.content = clean_content(content)
    if w.status == "changes_required":
        w.status = "in_preparation"
    if w.status == "draft":
        w.status = "in_preparation"
    w.prepared_by = w.prepared_by or ctx.user_id
    w.version += 1
    _snapshot(db, w, ctx.user_id, "edited")
    core.audit(db, ctx, a.practice_id, "workpaper.edited", "workpaper", w.id, version=w.version)
    return wdict(w, True)


def transition(db, ctx, a: Access, wid: int, action: str, reason: str = "") -> dict:
    if action not in TRANSITIONS:
        raise PcError(f"action must be one of {', '.join(TRANSITIONS)}")
    frm, to = TRANSITIONS[action]
    w = row(db, a, wid)
    if w.status not in frm:
        raise Conflict(f"Cannot {action.replace('_', ' ')} a workpaper that is {w.status.replace('_', ' ')}", "invalid_transition")
    uid = ctx.user_id
    if action in ("start", "submit", "withdraw"):
        a.require("wp_prepare")
    if action == "start":
        w.prepared_by = w.prepared_by or uid
    if action == "submit":
        if not (w.content or {}).get("lines") and not (w.content or {}).get("conclusion"):
            raise PcError("Add workpaper lines or a conclusion before submitting for review")
        if not w.reviewer_id:
            raise PcError("Choose a reviewer before submitting")
        if w.reviewer_id == (w.prepared_by or uid):
            raise PcError("The reviewer must be a different person from the preparer")
        w.prepared_by = w.prepared_by or uid
        w.prepared_at = core.now()
    if action in ("start_review", "request_changes", "finalise"):
        a.require("wp_review")
        if uid == w.prepared_by:
            raise Forbidden("You prepared this workpaper, so you cannot review it (segregation of duties)")
    if action == "start_review":
        w.reviewer_id, w.review_started_at = uid, core.now()
    if action == "request_changes":
        if not core.text(reason, "Reason", required=True, max_len=1000):
            raise PcError("Explain what must change")
        db.add(P.PcWpComment(practice_id=a.practice_id, workpaper_id=w.id, kind="comment", body=reason.strip(), mandatory=True, author_id=uid))
    if action == "finalise":
        if w.reviewer_id != uid:
            raise Forbidden("Only the reviewer who started the review can finalise")
        open_m = db.query(P.PcWpComment.id).filter_by(workpaper_id=w.id, mandatory=True, status="open").count()
        if open_m:
            raise Conflict(f"{open_m} mandatory review point(s) are still open", "open_review_points")
        w.reviewed_by, w.reviewed_at, w.finalised_by, w.finalised_at = uid, core.now(), uid, core.now()
    if action == "reopen":
        a.require("wp_reopen")
        if not core.text(reason, "Reason", required=True, max_len=500):
            raise PcError("A reason is required to reopen a finalised workpaper")
        w.reopen_count += 1
        w.finalised_by = w.finalised_at = w.reviewed_by = w.reviewed_at = None
    w.status = to
    w.version += 1
    _snapshot(db, w, uid, reason or action)
    core.audit(db, ctx, a.practice_id, f"workpaper.{action}", "workpaper", w.id, to=to, version=w.version, reason=(reason or "")[:300])
    return wdict(w, True)


def integrity(w: P.PcWorkpaper) -> dict:
    now_hash = _canon(w.title, w.period_from, w.period_to, w.content)
    return dict(stored=w.content_hash, computed=now_hash, intact=now_hash == w.content_hash)


# ------------------------------------------------------------------ comments, queries
def comments(db, a: Access, wid: int) -> list:
    w = row(db, a, wid)
    return [dict(id=c.id, parent_id=c.parent_id, kind=c.kind, body=c.body, mandatory=c.mandatory, status=c.status, author_id=c.author_id, created_at=core.plain(c.created_at), resolved_by=c.resolved_by)
            for c in db.query(P.PcWpComment).filter_by(workpaper_id=w.id).order_by(P.PcWpComment.id)]


def add_comment(db, ctx, a: Access, wid: int, body: str, *, kind="comment", mandatory=False, parent_id=None) -> dict:
    a.require("wp_prepare")
    w = row(db, a, wid)
    if w.status == "finalised":
        raise Conflict("Reopen the workpaper before adding review points")
    if kind not in ("comment", "query", "response"):
        raise PcError("kind must be comment, query or response")
    if mandatory and not a.can("wp_review"):
        raise Forbidden("Only a reviewer can raise a mandatory review point")
    if parent_id and not db.query(P.PcWpComment.id).filter_by(id=parent_id, workpaper_id=w.id).first():
        raise NotFound("Parent comment")
    c = P.PcWpComment(practice_id=a.practice_id, workpaper_id=w.id, kind=kind, body=core.text(body, "Comment", required=True, max_len=2000), mandatory=bool(mandatory), parent_id=parent_id, author_id=ctx.user_id)
    db.add(c)
    db.flush()
    core.audit(db, ctx, a.practice_id, "workpaper.commented", "workpaper", w.id, comment_id=c.id, kind=kind, mandatory=bool(mandatory))
    return dict(id=c.id, kind=c.kind, status=c.status, mandatory=c.mandatory)


def resolve_comment(db, ctx, a: Access, wid: int, comment_id: int) -> dict:
    a.require("wp_prepare")
    w = row(db, a, wid)
    if w.status == "finalised":
        raise Conflict("The workpaper is finalised")
    c = db.query(P.PcWpComment).filter_by(id=comment_id, workpaper_id=w.id).first()
    if c is None:
        raise NotFound("Comment")
    if c.status == "resolved":
        raise Conflict("Already resolved")
    if c.mandatory and w.status == "review_in_progress" and ctx.user_id != w.reviewer_id:
        raise Forbidden("Only the reviewer can clear a mandatory review point during review")
    c.status, c.resolved_by, c.resolved_at = "resolved", ctx.user_id, core.now()
    db.flush()
    core.audit(db, ctx, a.practice_id, "workpaper.comment_resolved", "workpaper", w.id, comment_id=c.id)
    return dict(id=c.id, status=c.status)


# ------------------------------------------------------------------ evidence
def attach_document(db, ctx, a: Access, wid: int, document_id: int) -> dict:
    a.require("wp_prepare")
    w = row(db, a, wid)
    if w.status not in EDITABLE:
        raise Conflict("Evidence can only be changed while the workpaper is editable")
    d = D.doc_row(db, a, document_id)
    if d.client_id != w.client_id:
        raise PcError("The document belongs to a different client")
    if db.query(P.PcWpDoc).filter_by(workpaper_id=w.id, document_id=d.id).first():
        raise Conflict("Already attached")
    db.add(P.PcWpDoc(workpaper_id=w.id, document_id=d.id, practice_id=a.practice_id))
    db.flush()
    core.audit(db, ctx, a.practice_id, "workpaper.evidence_attached", "workpaper", w.id, document_id=d.id)
    return dict(workpaper_id=w.id, document_id=d.id)


def detach_document(db, ctx, a: Access, wid: int, document_id: int) -> dict:
    a.require("wp_prepare")
    w = row(db, a, wid)
    if w.status not in EDITABLE:
        raise Conflict("Evidence can only be changed while the workpaper is editable")
    n = db.query(P.PcWpDoc).filter_by(workpaper_id=w.id, document_id=document_id).delete()
    if not n:
        raise NotFound("Attachment")
    core.audit(db, ctx, a.practice_id, "workpaper.evidence_detached", "workpaper", w.id, document_id=document_id)
    return dict(removed=n)


# ------------------------------------------------------------------ references to authoritative records
def _linked_org(db, a: Access, w: P.PcWorkpaper):
    """The client's own AccFino books. The staff member must ALSO be a member of that organisation, so the practice never reads books it has not been given."""
    c = db.get(P.PcClient, w.client_id)
    if not c.linked_org_id:
        raise PcError("This client is not linked to an AccFino organisation, so there are no books to reference")
    mem = db.query(m.OrgMembership).filter_by(org_id=c.linked_org_id, user_id=a.ctx.user_id).first()
    if mem is None or getattr(mem, "suspended_at", None):
        raise Forbidden("You do not have access to this client's books")
    return db.get(m.Organisation, c.linked_org_id)


def _compute_ref(db, org, kind, params):
    from datetime import date
    d = lambda k: core.parse_date(params.get(k), k)
    if kind == "trial_balance":
        rows = [r for r in accounting.balances_by_account(db, org, d("as_at")) if r["balance"] != "0.00"]
        return dict(as_at=params["as_at"], accounts=sorted(rows, key=lambda r: r["code"]))
    if kind == "profit_loss":
        return accounting.profit_and_loss(db, org, d("date_from"), d("date_to"))
    if kind == "balance_sheet":
        return accounting.balance_sheet(db, org, d("as_at"))
    if kind == "bank_reconciliation":
        return dict(rows=accounting.bank_reconciliation_status(db, org, d("as_at")))
    raise PcError(f"kind must be one of {', '.join(REF_KINDS)}")


def _h(v) -> str:
    return hashlib.sha256(json.dumps(core.plain(v), sort_keys=True, default=str).encode()).hexdigest()


def add_ref(db, ctx, a: Access, wid: int, kind: str, params: dict, note: str = "") -> dict:
    a.require("wp_prepare")
    w = row(db, a, wid)
    if w.status not in EDITABLE:
        raise Conflict("References can only be changed while the workpaper is editable")
    if kind not in REF_KINDS:
        raise PcError(f"kind must be one of {', '.join(REF_KINDS)}")
    org = _linked_org(db, a, w)
    params = {k: str(v) for k, v in (params or {}).items() if k in ("as_at", "date_from", "date_to")}
    data = _compute_ref(db, org, kind, params)
    r = P.PcWpRef(practice_id=a.practice_id, workpaper_id=w.id, kind=kind, params=params, seen_hash=_h(data), seen_at=core.now(), note=core.text(note, "Note", max_len=300))
    db.add(r)
    db.flush()
    core.audit(db, ctx, a.practice_id, "workpaper.ref_added", "workpaper", w.id, kind=kind, params=params)
    return dict(id=r.id, kind=kind, params=params, seen_hash=r.seen_hash, data=core.plain(data))


def check_refs(db, ctx, a: Access, wid: int) -> list:
    """Re-read each referenced record and say whether it has changed since the preparer saw it."""
    w = row(db, a, wid)
    org = _linked_org(db, a, w)
    out = []
    for r in db.query(P.PcWpRef).filter_by(workpaper_id=w.id).order_by(P.PcWpRef.id):
        now_hash = _h(_compute_ref(db, org, r.kind, r.params or {}))
        out.append(dict(id=r.id, kind=r.kind, params=r.params, changed=now_hash != r.seen_hash, seen_at=core.plain(r.seen_at)))
    return out
