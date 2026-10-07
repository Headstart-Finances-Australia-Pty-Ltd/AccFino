"""Tax workpapers and supporting evidence. A workpaper documents one area for one year (lines tagged calculated / source / user-entered / assumption / estimate, plus a
conclusion) and moves draft -> prepared -> reviewed -> approved with a different reviewer. Evidence is a file, a link to an existing Accounting document, a ledger
reference, a URL or a note; files are hashed (sha256) and size/type limited. Approved workpapers are frozen."""
import hashlib
from datetime import datetime
from typing import Optional

import accfino.modules.accounting.public as accounting
from accfino.modules.taxation.models import tax as T
from accfino.modules.taxation.services import bas as B, core, fbt as F, profile as P, returns as RT
from accfino.modules.taxation.services.core import Conflict, NotFound, TaxError

MAX_FILE = 5 * 1024 * 1024
ALLOWED_TYPES = ("application/pdf", "image/png", "image/jpeg", "text/csv", "text/plain", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                 "application/vnd.openxmlformats-officedocument.wordprocessingml.document")
LINE_KINDS = ("source", "calculated", "user_entered", "assumption", "estimate", "review")
LINK_TYPES = ("bas_statement", "tax_return", "fbt_return", "cgt_event", "fbt_benefit", "div7a_loan", "adjustment")


def w_dict(w: T.TaxWorkpaper, full=True, evidence_count=None) -> dict:
    d = dict(id=w.id, fy=w.fy, area=w.area, title=w.title, reference=w.reference, status=w.status, linked_type=w.linked_type, linked_id=w.linked_id, prepared_by=w.prepared_by,
             reviewed_by=w.reviewed_by, reviewed_at=core.plain(w.reviewed_at), updated_at=core.plain(w.updated_at), evidence_count=evidence_count)
    if full:
        d.update(content=w.content or {}, review_note=w.review_note)
    return d


def _clean_content(c: dict) -> dict:
    lines = []
    for ln in (c or {}).get("lines", []):
        k = ln.get("kind", "user_entered")
        if k not in LINE_KINDS:
            raise TaxError(f"line kind must be one of {', '.join(LINE_KINDS)}")
        amt = ln.get("amount")
        lines.append(dict(label=str(ln.get("label", ""))[:200], amount=None if amt in (None, "") else str(core.money_in(amt, "amount", allow_negative=True)), kind=k, source=str(ln.get("source", ""))[:200], note=str(ln.get("note", ""))[:500]))
    return dict(lines=lines, conclusion=str((c or {}).get("conclusion", ""))[:4000])


def get(db, ctx, wid) -> T.TaxWorkpaper:
    w = db.query(T.TaxWorkpaper).filter_by(org_id=ctx.org.id, id=wid).first()
    if w is None:
        raise NotFound("Workpaper")
    return w


def listing(db, ctx, fy="", area="", status=""):
    q = db.query(T.TaxWorkpaper).filter_by(org_id=ctx.org.id)
    for col, v in ((T.TaxWorkpaper.fy, fy), (T.TaxWorkpaper.area, area), (T.TaxWorkpaper.status, status)):
        if v:
            q = q.filter(col == v)
    counts = dict(db.query(T.TaxEvidence.workpaper_id, __import__("sqlalchemy").func.count(T.TaxEvidence.id)).filter(T.TaxEvidence.org_id == ctx.org.id).group_by(T.TaxEvidence.workpaper_id).all())
    return [w_dict(w, False, counts.get(w.id, 0)) for w in q.order_by(T.TaxWorkpaper.fy.desc(), T.TaxWorkpaper.area, T.TaxWorkpaper.id)]


def save(db, ctx, a: core.Access, body: dict, wid: Optional[int] = None) -> T.TaxWorkpaper:
    a.require("prepare")
    area = body.get("area")
    if area not in T.WORKPAPER_AREAS:
        raise TaxError(f"area must be one of {', '.join(T.WORKPAPER_AREAS)}")
    fy = body.get("fy") or ""
    if not fy.startswith("FBT"):
        core.check_fy(ctx, fy)
    title = (body.get("title") or "").strip()
    if not title:
        raise TaxError("title is required")
    lt = body.get("linked_type")
    if lt and lt not in LINK_TYPES:
        raise TaxError(f"linked_type must be one of {', '.join(LINK_TYPES)}")
    if wid:
        w = get(db, ctx, wid)
        if w.status in ("reviewed", "approved"):
            raise Conflict("A reviewed or approved workpaper is frozen: reopen it first.", "locked")
    else:
        w = T.TaxWorkpaper(org_id=ctx.org.id, created_by=ctx.user_id, status="draft")
    before = w_dict(w) if wid else None
    w.fy, w.area, w.title, w.reference = fy, area, title[:200], (body.get("reference") or "")[:30] or None
    w.linked_type, w.linked_id = lt, body.get("linked_id") if lt else None
    if "content" in body or not wid:
        w.content = _clean_content(body.get("content") or {})
    if wid and w.status == "prepared":
        w.status = "draft"
    if not wid:
        db.add(w)
    db.flush()
    core.record(db, ctx, "workpaper.save", "tax_workpaper", w.id, f"Workpaper '{title[:80]}' {'updated' if wid else 'created'}", before, w_dict(w))
    return w


def generate(db, ctx, a: core.Access, kind: str, doc_id, fy: str = "") -> T.TaxWorkpaper:
    """Create a workpaper pre-filled from a prepared document, so the working that produced each figure is on file."""
    a.require("prepare")
    lines, title, area, wfy, lt = [], "", "general", fy, kind
    if kind == "bas_statement":
        s = B.get(db, ctx, doc_id)
        title, area, wfy = f"{s.kind.upper()} {s.period_start} to {s.period_end}", "bas", s.fy
        from accfino.modules.taxation.engine.bas import ordered_labels
        for lb in ordered_labels(s.final or {}):
            v = s.final[lb]
            lines.append(dict(label=f"Label {lb}", amount=v["value"], kind=v["kind"], source=v.get("source", ""), note=v.get("note", "")))
        for f in s.findings or []:
            lines.append(dict(label=f"Finding ({f['severity']})", amount=None, kind="review", source=f.get("area", ""), note=f["message"]))
    elif kind == "tax_return":
        r = RT.get(db, ctx, doc_id)
        title, area, wfy = f"Income tax return {r.fy} v{r.version}", "income_tax", r.fy
        for st in (r.computation or {}).get("steps", []):
            lines.append(dict(label=st["label"], amount=st["amount"], kind=st["kind"], source="engine", note=st.get("note", "")))
        for f in r.findings or []:
            lines.append(dict(label=f"Finding ({f['severity']})", amount=None, kind="review", source=f.get("area", ""), note=f["message"]))
    elif kind == "fbt_return":
        r = F.get_return(db, ctx, doc_id)
        title, area, wfy = f"FBT return {r.fbt_year}", "fbt", r.fbt_year
        sm = r.summary or {}
        for k in ("type1_taxable", "type2_taxable", "type1_grossed_up", "type2_grossed_up", "aggregate_fringe_benefits_amount", "fbt_payable"):
            lines.append(dict(label=k.replace("_", " ").capitalize(), amount=sm.get(k), kind="calculated", source="FBT engine", note=""))
    else:
        raise TaxError("kind must be bas_statement, tax_return or fbt_return")
    w = T.TaxWorkpaper(org_id=ctx.org.id, fy=wfy, area=area, title=title, status="draft", linked_type=lt, linked_id=doc_id, created_by=ctx.user_id,
                       content=_clean_content(dict(lines=lines, conclusion="")))
    db.add(w)
    db.flush()
    w.reference = f"WP-{w.id:04d}"
    core.record(db, ctx, "workpaper.generate", "tax_workpaper", w.id, f"Workpaper generated from {kind} {doc_id}", None, None)
    return w


def advance(db, ctx, a: core.Access, wid: int, to: str, note: str = "") -> T.TaxWorkpaper:
    w = get(db, ctx, wid)
    order = {"draft": 0, "prepared": 1, "reviewed": 2, "approved": 3}
    if to not in order:
        raise TaxError("to must be draft, prepared, reviewed or approved")
    if to == "prepared":
        a.require("prepare")
        if w.status != "draft":
            raise Conflict(f"Only a draft can be marked prepared (status is {w.status}).")
        if not (w.content or {}).get("lines") and not (w.content or {}).get("conclusion"):
            raise TaxError("A workpaper needs at least one line or a conclusion")
        w.status, w.prepared_by, w.prepared_at = "prepared", ctx.user_id, datetime.utcnow()
    elif to in ("reviewed", "approved"):
        a.require("approve")
        need = "prepared" if to == "reviewed" else "reviewed"
        if w.status != need:
            raise Conflict(f"A workpaper must be {need} before it can be {to} (status is {w.status}).")
        if to == "reviewed":
            core.check_separation(db, ctx, w.prepared_by, "workpaper", P.get(db, ctx), "workpaper.review", "tax_workpaper", w.id)
            w.reviewed_by, w.reviewed_at, w.review_note = ctx.user_id, datetime.utcnow(), (note or "")[:500] or None
        w.status = to
    else:                                                                              # reopen
        a.require("approve" if w.status in ("reviewed", "approved") else "prepare")
        w.status, w.reviewed_by, w.reviewed_at = "draft", None, None
    core.record(db, ctx, f"workpaper.{to}", "tax_workpaper", w.id, f"Workpaper '{w.title[:80]}' -> {to}. {note[:150]}", None, None)
    return w


def delete(db, ctx, a: core.Access, wid: int):
    a.require("prepare")
    w = get(db, ctx, wid)
    if w.status in ("reviewed", "approved"):
        raise Conflict("A reviewed or approved workpaper cannot be deleted.", "locked")
    core.record(db, ctx, "workpaper.delete", "tax_workpaper", w.id, f"Workpaper '{w.title[:80]}' deleted", w_dict(w), None)
    db.delete(w)


# ---- evidence ------------------------------------------------------------------------------------------------------------------------
def e_dict(e: T.TaxEvidence) -> dict:
    return dict(id=e.id, workpaper_id=e.workpaper_id, linked_type=e.linked_type, linked_id=e.linked_id, kind=e.kind, title=e.title, note=e.note, url=e.url, attachment_id=e.attachment_id,
                ledger_ref=e.ledger_ref, file_name=e.file_name, content_type=e.content_type, size=e.size, sha256=e.sha256, created_at=core.plain(e.created_at))


def add_evidence(db, ctx, a: core.Access, body: dict, file_bytes: Optional[bytes] = None, file_name: str = "", content_type: str = "") -> T.TaxEvidence:
    a.require("evidence")
    kind = body.get("kind") or ("file" if file_bytes else "note")
    if kind not in T.EVIDENCE_KINDS:
        raise TaxError(f"kind must be one of {', '.join(T.EVIDENCE_KINDS)}")
    title = (body.get("title") or file_name or "").strip()
    if not title:
        raise TaxError("title is required")
    wid, lt, lid = body.get("workpaper_id"), body.get("linked_type"), body.get("linked_id")
    if not wid and not (lt and lid):
        raise TaxError("Attach evidence to a workpaper or to a document (linked_type + linked_id)")
    if wid:
        w = get(db, ctx, wid)
        if w.status == "approved":
            raise Conflict("The workpaper is approved: reopen it to add evidence.", "locked")
    if lt and lt not in LINK_TYPES:
        raise TaxError(f"linked_type must be one of {', '.join(LINK_TYPES)}")
    e = T.TaxEvidence(org_id=ctx.org.id, workpaper_id=wid, linked_type=lt, linked_id=lid, kind=kind, title=title[:200], note=(body.get("note") or "")[:500] or None, uploaded_by=ctx.user_id)
    if kind == "file":
        if not file_bytes:
            raise TaxError("No file received")
        if len(file_bytes) > MAX_FILE:
            raise TaxError("Evidence files are limited to 5 MB")
        if content_type not in ALLOWED_TYPES:
            raise TaxError("Unsupported file type (PDF, PNG, JPEG, CSV, text, Excel or Word)")
        e.data, e.file_name, e.content_type, e.size, e.sha256 = file_bytes, (file_name or "file")[:255], content_type, len(file_bytes), hashlib.sha256(file_bytes).hexdigest()
    elif kind == "attachment":
        info = accounting.attachment_info(db, ctx.org.id, int(body.get("attachment_id") or 0))
        if info is None:
            raise TaxError("That document was not found in this organisation's Documents")
        e.attachment_id, e.file_name, e.content_type, e.size = info["id"], info["filename"], info["content_type"], info["size"]
    elif kind == "ledger_ref":
        if not (body.get("ledger_ref") or "").strip():
            raise TaxError("ledger_ref is required (for example journal:42)")
        e.ledger_ref = body["ledger_ref"].strip()[:120]
    elif kind == "url":
        u = (body.get("url") or "").strip()
        if not u.lower().startswith(("https://", "http://")):
            raise TaxError("url must start with https:// or http://")
        e.url = u[:500]
    db.add(e)
    db.flush()
    core.record(db, ctx, "evidence.add", "tax_evidence", e.id, f"Evidence '{title[:80]}' ({kind}) added", None, dict(kind=kind, sha256=e.sha256))
    return e


def evidence_for(db, ctx, workpaper_id=None, linked_type="", linked_id=None):
    q = db.query(T.TaxEvidence).filter_by(org_id=ctx.org.id)
    if workpaper_id:
        q = q.filter(T.TaxEvidence.workpaper_id == workpaper_id)
    if linked_type:
        q = q.filter(T.TaxEvidence.linked_type == linked_type, T.TaxEvidence.linked_id == linked_id)
    return [e_dict(e) for e in q.order_by(T.TaxEvidence.id)]


def evidence_file(db, ctx, eid):
    e = db.query(T.TaxEvidence).filter_by(org_id=ctx.org.id, id=eid).first()
    if e is None or e.kind != "file":
        raise NotFound("Evidence file")
    if hashlib.sha256(e.data).hexdigest() != e.sha256:
        raise TaxError("Stored file failed its integrity check", 500, "corrupt")
    return e


def delete_evidence(db, ctx, a: core.Access, eid: int):
    a.require("evidence")
    e = db.query(T.TaxEvidence).filter_by(org_id=ctx.org.id, id=eid).first()
    if e is None:
        raise NotFound("Evidence")
    if e.workpaper_id and get(db, ctx, e.workpaper_id).status in ("reviewed", "approved"):
        raise Conflict("The workpaper is reviewed or approved: reopen it to remove evidence.", "locked")
    core.record(db, ctx, "evidence.delete", "tax_evidence", e.id, f"Evidence '{e.title[:80]}' deleted", dict(kind=e.kind, sha256=e.sha256), None)
    db.delete(e)
