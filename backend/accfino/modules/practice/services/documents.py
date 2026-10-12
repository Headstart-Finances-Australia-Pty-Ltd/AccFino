"""Documents: private storage, versions, content sniffing, safe names, short-lived single-use download tickets, retention / legal hold / deletion events."""
import datetime as dt
import hashlib
import os
import re
import secrets
import unicodedata
import uuid
from pathlib import Path

from accfino.modules.practice.models import practice as P
from accfino.modules.practice.services import core
from accfino.modules.practice.services.core import Access, Conflict, Forbidden, NotFound, PcError
from accfino.shared.paths import data_root

CATEGORIES = ("general", "tax_return", "financial_statements", "bank_statement", "invoice_receipt", "payroll", "correspondence", "engagement_letter", "identification", "workpaper_evidence", "other")
# extension -> (content type, sniffer)
TYPES = {
    "pdf": "application/pdf", "png": "image/png", "jpg": "image/jpeg", "jpeg": "image/jpeg", "csv": "text/csv", "txt": "text/plain",
    "xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
}
INLINE_OK = {"application/pdf", "image/png", "image/jpeg", "text/plain", "text/csv"}


def safe_filename(name: str) -> str:
    """Display/download name only. The stored object is named by a random key, never by this."""
    name = unicodedata.normalize("NFKC", str(name or "")).replace("\\", "/").split("/")[-1]
    name = re.sub(r"[\x00-\x1f\x7f\"<>|:*?;,]", "", name).strip(" .")
    name = re.sub(r"\s+", " ", name)
    if not name:
        raise PcError("The file needs a name")
    stem, dot, ext = name.rpartition(".")
    if not dot or not stem:
        raise PcError("The file name needs an extension, e.g. report.pdf")
    return (stem[:150] + "." + ext.lower())[:160]


def sniff(filename: str, data: bytes) -> str:
    """Decide the content type from the BYTES and require it to agree with the extension. The client-declared type is never trusted."""
    ext = filename.rsplit(".", 1)[-1].lower()
    if ext not in TYPES:
        raise PcError(f"File type .{ext} is not allowed. Allowed: {', '.join(sorted(TYPES))}")
    if not data:
        raise PcError("The file is empty")
    head = data[:8]
    ok = {
        "pdf": data.startswith(b"%PDF-"), "png": head.startswith(b"\x89PNG\r\n\x1a\n"), "jpg": head.startswith(b"\xff\xd8\xff"), "jpeg": head.startswith(b"\xff\xd8\xff"),
        "xlsx": head.startswith(b"PK\x03\x04") and b"xl/" in data[:4_000_000], "docx": head.startswith(b"PK\x03\x04") and b"word/" in data[:4_000_000],
    }.get(ext)
    if ext in ("csv", "txt"):
        sample = data[:65536]
        try:
            sample.decode("utf-8")
        except UnicodeDecodeError:
            try:
                sample.decode("cp1252")
            except UnicodeDecodeError:
                ok = False
            else:
                ok = b"\x00" not in sample
        else:
            ok = b"\x00" not in sample
    if not ok:
        raise PcError(f"The file content does not look like a real .{ext} file")
    return TYPES[ext]


def _root() -> Path:
    r = data_root() / "modules" / "practice" / "documents"
    r.mkdir(parents=True, exist_ok=True)
    return r


def _path(storage_key: str) -> Path:
    p = (_root() / storage_key).resolve()
    if _root().resolve() not in p.parents:
        raise PcError("Invalid storage key")
    return p


def _used_bytes(db, practice_id) -> int:
    from sqlalchemy import func
    return int(db.query(func.coalesce(func.sum(P.PcDocVersion.size), 0)).filter(P.PcDocVersion.practice_id == practice_id, P.PcDocVersion.purged_at.is_(None)).scalar() or 0)


def ddict(d: P.PcDocument, v: P.PcDocVersion = None) -> dict:
    out = dict(id=d.id, client_id=d.client_id, entity_id=d.entity_id, engagement_id=d.engagement_id, job_id=d.job_id, fy=d.fy, category=d.category, title=d.title, source=d.source, status=d.status,
               shared_with_portal=d.shared_with_portal, current_version=d.current_version, legal_hold=d.legal_hold, retain_until=core.plain(d.retain_until), created_at=core.plain(d.created_at))
    if v is not None:
        out.update(file_name=v.original_name, content_type=v.content_type, size=v.size, sha256=v.sha256, uploaded_at=core.plain(v.uploaded_at))
    return out


def _store(db, a: Access, doc: P.PcDocument, version: int, filename: str, data: bytes, user_id, portal=False) -> P.PcDocVersion:
    fn = safe_filename(filename)
    mx = int(a.settings.get("max_file_mb", 10)) * 1024 * 1024
    if len(data) > mx:
        raise PcError(f"The file is larger than the {a.settings.get('max_file_mb', 10)} MB limit")
    if _used_bytes(db, a.practice_id) + len(data) > int(a.settings.get("storage_limit_mb", 500)) * 1024 * 1024:
        raise Conflict("The practice storage limit has been reached", "storage_full")
    ctype = sniff(fn, data)
    key = f"{a.practice_id}/{doc.id}/{version}-{uuid.uuid4().hex}"
    p = _path(key)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(data)
    v = P.PcDocVersion(practice_id=a.practice_id, document_id=doc.id, version=version, original_name=fn, content_type=ctype, size=len(data), sha256=hashlib.sha256(data).hexdigest(),
                       storage_key=key, uploaded_by=user_id, uploaded_by_portal=portal)
    db.add(v)
    db.flush()
    return v


def upload(db, ctx, a: Access, client_id: int, filename: str, data: bytes, *, title=None, category="general", entity_id=None, fy=None, engagement_id=None, job_id=None, shared_with_portal=False,
           source="staff", portal_user_id=None) -> dict:
    if portal_user_id is None:
        a.require("docs")
        c = a.client(client_id, allow_archived=False)
    else:
        c = db.query(P.PcClient).filter_by(practice_id=a.practice_id, id=client_id).first()
        if c is None:
            raise NotFound("Client")
    if category not in CATEGORIES:
        raise PcError(f"category must be one of {', '.join(CATEGORIES)}")
    if entity_id and not db.query(P.PcClientEntity.id).filter_by(client_id=c.id, entity_id=entity_id).first():
        raise PcError("That entity is not linked to this client")
    ret = core.today().replace(year=core.today().year + int(a.settings.get("retention_years", 7)))
    d = P.PcDocument(practice_id=a.practice_id, client_id=c.id, entity_id=entity_id, engagement_id=engagement_id, job_id=job_id, fy=fy, category=category,
                     title=core.text(title or safe_filename(filename), "Title", required=True), source=source, shared_with_portal=bool(shared_with_portal), created_by=portal_user_id or ctx.user_id, retain_until=ret)
    db.add(d)
    db.flush()
    try:
        v = _store(db, a, d, 1, filename, data, portal_user_id or ctx.user_id, portal=portal_user_id is not None)
    except PcError:
        db.expunge(d)
        raise
    core.audit(db, ctx, a.practice_id, "document.uploaded", "document", d.id, client_id=c.id, version=1, size=v.size, sha256=v.sha256, source=source)
    return ddict(d, v)


def doc_row(db, a: Access, doc_id: int, *, include_deleted=False) -> P.PcDocument:
    d = db.query(P.PcDocument).filter_by(practice_id=a.practice_id, id=doc_id).first()
    if d is None or (d.status == "deleted" and not include_deleted):
        raise NotFound("Document")
    a.client(d.client_id)                          # scope: 404 when the client is outside the member's scope
    return d


def _ver(db, d, version=None) -> P.PcDocVersion:
    v = db.query(P.PcDocVersion).filter_by(document_id=d.id, version=version or d.current_version).first()
    if v is None or v.purged_at:
        raise NotFound("Document version")
    return v


def new_version(db, ctx, a: Access, doc_id: int, filename: str, data: bytes, reason: str = "") -> dict:
    a.require("docs")
    d = doc_row(db, a, doc_id)
    if d.status != "active":
        raise Conflict("Restore the document before adding a version")
    nv = d.current_version + 1
    v = _store(db, a, d, nv, filename, data, ctx.user_id)
    d.current_version = nv
    db.flush()
    core.audit(db, ctx, a.practice_id, "document.version_added", "document", d.id, version=nv, sha256=v.sha256, reason=reason[:200])
    return ddict(d, v)


def list_docs(db, a: Access, *, client_id=None, entity_id=None, category=None, status="active", q="", fy=None, page_no=1, size=25) -> dict:
    a.require("view")
    qq = db.query(P.PcDocument).filter(P.PcDocument.practice_id == a.practice_id, P.PcDocument.client_id.in_(a.client_ids()))
    if client_id:
        qq = qq.filter(P.PcDocument.client_id == client_id)
    if entity_id:
        qq = qq.filter(P.PcDocument.entity_id == entity_id)
    if category:
        qq = qq.filter(P.PcDocument.category == category)
    if fy:
        qq = qq.filter(P.PcDocument.fy == int(fy))
    qq = qq.filter(P.PcDocument.status == status) if status != "all" else qq.filter(P.PcDocument.status != "deleted")
    if q:
        qq = qq.filter(P.PcDocument.title.ilike(f"%{q.strip()[:100]}%"))
    meta, qq = core.page(qq.order_by(P.PcDocument.id.desc()), page_no, size)
    items = []
    for d in qq:
        items.append(ddict(d, _ver_or_none(db, d)))
    return dict(**meta, items=items)


def _ver_or_none(db, d):
    return db.query(P.PcDocVersion).filter_by(document_id=d.id, version=d.current_version).first()


def get(db, a: Access, doc_id: int) -> dict:
    d = doc_row(db, a, doc_id)
    vs = db.query(P.PcDocVersion).filter_by(document_id=d.id).order_by(P.PcDocVersion.version).all()
    out = ddict(d, _ver_or_none(db, d))
    out["versions"] = [dict(version=v.version, file_name=v.original_name, size=v.size, sha256=v.sha256, uploaded_at=core.plain(v.uploaded_at), purged=bool(v.purged_at)) for v in vs]
    return out


def update(db, ctx, a: Access, doc_id: int, body: dict) -> dict:
    """Rename, classify, move (to another client / entity the member can reach), share with the portal."""
    a.require("docs")
    d = doc_row(db, a, doc_id)
    if d.status != "active":
        raise Conflict("Restore the document before changing it")
    ch = {}
    if "title" in body:
        d.title = core.text(body["title"], "Title", required=True); ch["title"] = True
    if "category" in body:
        if body["category"] not in CATEGORIES:
            raise PcError(f"category must be one of {', '.join(CATEGORIES)}")
        d.category = body["category"]; ch["category"] = d.category
    if "fy" in body:
        d.fy = int(body["fy"]) if body["fy"] else None
    if "client_id" in body and body["client_id"] != d.client_id:
        dest = a.client(body["client_id"], allow_archived=False)
        if d.shared_with_portal:
            d.shared_with_portal = False              # moving a document never silently exposes it to another client's portal
        d.client_id, d.entity_id, d.engagement_id, d.job_id = dest.id, None, None, None
        ch["moved_to_client"] = dest.id
    if "entity_id" in body:
        if body["entity_id"] and not db.query(P.PcClientEntity.id).filter_by(client_id=d.client_id, entity_id=body["entity_id"]).first():
            raise PcError("That entity is not linked to this client")
        d.entity_id = body["entity_id"] or None; ch["entity_id"] = d.entity_id
    if "shared_with_portal" in body:
        d.shared_with_portal = bool(body["shared_with_portal"]); ch["shared_with_portal"] = d.shared_with_portal
    db.flush()
    core.audit(db, ctx, a.practice_id, "document.updated", "document", d.id, **ch)
    return ddict(d, _ver_or_none(db, d))


def set_status(db, ctx, a: Access, doc_id: int, action: str) -> dict:
    a.require("docs")
    d = doc_row(db, a, doc_id)
    if action == "archive":
        if d.status != "active":
            raise Conflict("Only active documents can be archived")
        d.status, d.shared_with_portal = "archived", False
    elif action == "restore":
        if d.status != "archived":
            raise Conflict("Only archived documents can be restored")
        d.status = "active"
    else:
        raise PcError("action must be archive or restore")
    db.flush()
    core.audit(db, ctx, a.practice_id, f"document.{action}d", "document", d.id)
    return ddict(d, _ver_or_none(db, d))


def set_hold(db, ctx, a: Access, doc_id: int, hold: bool, reason: str = "") -> dict:
    a.require("docs_delete")
    d = doc_row(db, a, doc_id)
    d.legal_hold = bool(hold)
    db.flush()
    core.audit(db, ctx, a.practice_id, "document.legal_hold_set" if hold else "document.legal_hold_released", "document", d.id, reason=reason[:200])
    return ddict(d, _ver_or_none(db, d))


def delete(db, ctx, a: Access, doc_id: int, reason: str) -> dict:
    """Deletion is a recorded event. Blocked by legal hold and by the retention period; the row stays (status=deleted), the stored bytes are purged."""
    a.require("docs_delete")
    d = doc_row(db, a, doc_id)
    if not core.text(reason, "Reason", required=True, max_len=300):
        raise PcError("A reason is required")
    if d.legal_hold:
        raise Conflict("This document is under legal hold and cannot be deleted", "legal_hold")
    if d.retain_until and d.retain_until > core.today():
        raise Conflict(f"This document must be retained until {d.retain_until.isoformat()}", "retention")
    vs = db.query(P.PcDocVersion).filter_by(document_id=d.id).all()
    for v in vs:
        try:
            _path(v.storage_key).unlink(missing_ok=True)
        except OSError:
            pass
        v.purged_at = core.now()
    d.status, d.deleted_at, d.deleted_by, d.shared_with_portal = "deleted", core.now(), ctx.user_id, False
    for t in db.query(P.PcDownloadTicket).join(P.PcDocVersion, P.PcDocVersion.id == P.PcDownloadTicket.version_id).filter(P.PcDocVersion.document_id == d.id, P.PcDownloadTicket.used_at.is_(None)):
        t.revoked_at = core.now()
    db.flush()
    core.audit(db, ctx, a.practice_id, "document.deleted", "document", d.id, reason=reason[:200], versions=len(vs))
    return dict(id=d.id, status="deleted")


# --------------------------------------------------------------------------------------------------------------------- delivery
def _hash(tok: str) -> str:
    return hashlib.sha256(tok.encode()).hexdigest()


def issue_ticket(db, ctx, a: Access, doc_id: int, version=None) -> dict:
    """Staff: a one-time ticket valid for a few seconds. The response carries the ticket, never a path or storage key."""
    a.require("view")
    d = doc_row(db, a, doc_id)
    v = _ver(db, d, version)
    return _issue(db, ctx, a.practice_id, v, ctx.user_id, False, int(a.settings.get("download_ticket_seconds", 120)), d)


def _issue(db, ctx, practice_id, v, user_id, portal, seconds, d) -> dict:
    tok = secrets.token_urlsafe(32)
    db.add(P.PcDownloadTicket(practice_id=practice_id, token_hash=_hash(tok), version_id=v.id, user_id=user_id, portal=portal, expires_at=core.now() + dt.timedelta(seconds=seconds)))
    db.flush()
    core.audit(db, ctx, practice_id, "document.download_issued", "document", d.id, version=v.version, portal=portal)
    return dict(ticket=tok, expires_in=seconds, file_name=v.original_name)


def redeem(db, ctx, practice_id: int, ticket: str, user_id: int, *, portal: bool, allowed) -> dict:
    """Single use. Re-checks, NOW, that the ticket belongs to this user and that `allowed(document)` still holds (so revoked access / unshared documents stop working immediately)."""
    t = db.query(P.PcDownloadTicket).filter_by(token_hash=_hash(ticket or ""), practice_id=practice_id).first()
    if t is None or t.user_id != user_id or t.portal != portal:
        raise NotFound("Download")
    if t.used_at or t.revoked_at or t.expires_at < core.now():
        raise Conflict("This download link has expired or was already used", "ticket_spent")
    v = db.get(P.PcDocVersion, t.version_id)
    d = db.get(P.PcDocument, v.document_id) if v else None
    if d is None or d.status == "deleted" or v.purged_at or not allowed(d):
        raise NotFound("Download")
    p = _path(v.storage_key)
    if not p.is_file():
        raise NotFound("Stored file")
    t.used_at = core.now()
    db.flush()
    core.audit(db, ctx, practice_id, "document.downloaded", "document", d.id, version=v.version, portal=portal)
    return dict(path=str(p), file_name=v.original_name, content_type=v.content_type, sha256=v.sha256, inline=v.content_type in INLINE_OK)


def staff_download(db, ctx, a: Access, ticket: str) -> dict:
    a.require("view")
    def ok(d):
        try:
            a.client(d.client_id)
            return True
        except PcError:
            return False
    return redeem(db, ctx, a.practice_id, ticket, ctx.user_id, portal=False, allowed=ok)


def preview(db, ctx, a: Access, doc_id: int, max_lines=40) -> dict:
    """Text preview for csv/txt; other types are previewed through a ticket (inline for pdf/images)."""
    a.require("view")
    d = doc_row(db, a, doc_id)
    v = _ver(db, d)
    out = dict(content_type=v.content_type, file_name=v.original_name, size=v.size, inline_ok=v.content_type in INLINE_OK)
    if v.content_type in ("text/csv", "text/plain"):
        raw = _path(v.storage_key).read_bytes()[:20000]
        out["text"] = "\n".join(raw.decode("utf-8", "replace").splitlines()[:max_lines])
    core.audit(db, ctx, a.practice_id, "document.previewed", "document", d.id, version=v.version)
    return out
