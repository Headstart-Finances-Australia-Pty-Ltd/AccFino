"""Supporting records: stored with a SHA-256 and verified on every download. Allow-listed types, 5 MB."""
import hashlib

from accfino.modules.investments.models import inv as M
from accfino.modules.investments.services import core
from accfino.modules.investments.services.core import Access, Conflict, InvError, NotFound

ALLOWED = {"application/pdf": ".pdf", "image/png": ".png", "image/jpeg": ".jpg", "text/csv": ".csv", "text/plain": ".txt", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": ".xlsx"}
MAX = 5 * 1024 * 1024
_OWNERS = {"account": M.InvAccount, "security": M.InvSecurity, "transaction": M.InvTransaction, "property": M.InvProperty, "liability": M.InvLiability, "other_asset": M.InvOtherAsset}


def d_dict(x: M.InvDocument) -> dict:
    return dict(id=x.id, owner_type=x.owner_type, owner_id=x.owner_id, title=x.title, file_name=x.file_name, content_type=x.content_type, size=x.size, sha256=x.sha256, uploaded_at=core.plain(x.uploaded_at))


def upload(db, ctx, a: Access, owner_type: str, owner_id: int, title: str, file_name: str, content_type: str, data: bytes) -> M.InvDocument:
    a.require("edit")
    if owner_type not in _OWNERS:
        raise InvError(f"owner_type must be one of {', '.join(_OWNERS)}")
    if not db.query(_OWNERS[owner_type]).filter_by(org_id=ctx.org.id, id=owner_id).first():
        raise NotFound(owner_type.replace("_", " ").title())
    ct = (content_type or "").split(";")[0].strip().lower()
    if ct not in ALLOWED:
        raise InvError("Unsupported file type: use PDF, PNG, JPEG, CSV, TXT or XLSX")
    if not data:
        raise InvError("The file is empty")
    if len(data) > MAX:
        raise InvError("The file is larger than 5 MB")
    if not (title or file_name):
        raise InvError("title is required")
    x = M.InvDocument(org_id=ctx.org.id, owner_type=owner_type, owner_id=owner_id, title=(title or file_name)[:200], file_name=(file_name or "")[:200], content_type=ct, size=len(data), sha256=hashlib.sha256(data).hexdigest(), data=data, uploaded_by=ctx.user_id)
    db.add(x)
    db.flush()
    core.record(db, ctx, "document.upload", f"inv_{owner_type}", owner_id, f"Document '{x.title}' ({x.size} bytes, sha256 {x.sha256[:12]})", None, dict(id=x.id))
    return x


def listing(db, ctx, owner_type: str, owner_id: int):
    return [d_dict(x) for x in db.query(M.InvDocument).filter_by(org_id=ctx.org.id, owner_type=owner_type, owner_id=owner_id).order_by(M.InvDocument.id.desc())]


def download(db, ctx, doc_id: int) -> M.InvDocument:
    x = db.query(M.InvDocument).filter_by(org_id=ctx.org.id, id=doc_id).first()
    if x is None:
        raise NotFound("Document")
    if hashlib.sha256(x.data or b"").hexdigest() != x.sha256:
        raise Conflict("This document no longer matches its recorded SHA-256 and will not be served", "integrity")
    return x


def delete(db, ctx, a: Access, doc_id: int):
    a.require("delete")
    x = db.query(M.InvDocument).filter_by(org_id=ctx.org.id, id=doc_id).first()
    if x is None:
        raise NotFound("Document")
    core.record(db, ctx, "document.delete", f"inv_{x.owner_type}", x.owner_id, f"Document '{x.title}' deleted", d_dict(x), None)
    db.delete(x)
    db.flush()


# ---------------------------------------------------------------------------------------------------------------------- bulk upload with a manifest
# A CSV cannot carry files, so a bulk upload is the files themselves plus ONE manifest CSV that says what each file belongs to:
#   file_name,owner_type,owner,title      (owner = security CODE, account / property / liability / other asset NAME, or transaction REFERENCE)
EXT = {".pdf": "application/pdf", ".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".csv": "text/csv", ".txt": "text/plain", ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"}
MAX_FILES, MAX_TOTAL = 50, 30 * 1024 * 1024
MANIFEST_TEMPLATE = "file_name,owner_type,owner,title\nBHP_contract_note_CN-001.pdf,security,BHP,Contract note CN-001\nManly_contract_of_sale.pdf,property,\"14 Wattle Rd, Manly\",Contract of sale\n"


def _owner(db, ctx, owner_type: str, owner: str):
    q = lambda model, **kw: db.query(model).filter_by(org_id=ctx.org.id, **kw).all()
    if owner_type == "security":
        rows = q(M.InvSecurity, code=owner.strip().upper())
    elif owner_type == "transaction":
        rows = [t for t in q(M.InvTransaction, reference=owner.strip()) if not t.voided]
    else:
        model = {"account": M.InvAccount, "property": M.InvProperty, "liability": M.InvLiability, "other_asset": M.InvOtherAsset}[owner_type]
        rows = q(model, name=owner.strip())
    if not rows:
        raise InvError(f"No {owner_type.replace('_', ' ')} matches '{owner}'")
    if len(rows) > 1:
        raise InvError(f"'{owner}' matches more than one {owner_type.replace('_', ' ')}: use a more specific value")
    return rows[0].id


def _bulk_plan(db, ctx, manifest: bytes, files: dict) -> dict:
    from accfino.modules.investments.services import imports as I
    if len(files) > MAX_FILES:
        raise InvError(f"At most {MAX_FILES} files can be uploaded at once")
    if sum(len(b) for b in files.values()) > MAX_TOTAL:
        raise InvError("The files add up to more than 30 MB: upload them in smaller batches")
    headers, body = I._grid(manifest)
    missing = [c for c in ("file_name", "owner_type", "owner") if c not in headers]
    out = dict(total=len(body), ok=0, duplicates=0, errors=0, rows=[], unused_files=[], file_sha256=hashlib.sha256(manifest).hexdigest(), plan=[])
    if missing:
        out["file_error"] = "Required manifest column(s) missing: " + ", ".join(missing) + ". Download the manifest template for the exact layout."
        return out
    idx = {h: i for i, h in enumerate(headers)}
    seen, used = {}, set()
    cell = lambda r, k: (r[idx[k]].strip() if k in idx and idx[k] < len(r) else "")
    for n, r in enumerate(body, start=2):
        fn, ot, ow, title = cell(r, "file_name"), cell(r, "owner_type").lower().replace(" ", "_"), cell(r, "owner"), cell(r, "title")
        row = dict(line=n, status="ok", messages=[], data=dict(file_name=fn, owner_type=ot, owner=ow, title=title))
        err = None
        try:
            if fn in files:
                used.add(fn)                                                            # referenced by the manifest, whether or not the row turns out to be valid
            if not fn or not ow:
                raise InvError("file_name and owner are required")
            if ot not in _OWNERS:
                raise InvError(f"owner_type must be one of {', '.join(_OWNERS)} (got '{cell(r, 'owner_type')}')")
            ext = "." + fn.rsplit(".", 1)[-1].lower() if "." in fn else ""
            if ext not in EXT:
                raise InvError(f"'{fn}' is not an allowed file type (PDF, PNG, JPEG, CSV, TXT or XLSX)")
            if fn not in files:
                raise InvError(f"The file '{fn}' was not uploaded with the manifest")
            data = files[fn]
            if not data:
                raise InvError(f"'{fn}' is empty")
            if len(data) > MAX:
                raise InvError(f"'{fn}' is larger than 5 MB")
            oid = _owner(db, ctx, ot, ow)
            sha = hashlib.sha256(data).hexdigest()
            key = (ot, oid, sha)
            if key in seen:
                row["status"] = "duplicate"
                row["messages"].append(dict(level="info", text=f"Same file for the same {ot.replace('_', ' ')} as line {seen[key]}: skipped"))
            elif db.query(M.InvDocument.id).filter_by(org_id=ctx.org.id, owner_type=ot, owner_id=oid, sha256=sha).first():
                row["status"] = "duplicate"
                seen[key] = n
                row["messages"].append(dict(level="info", text="This exact file is already attached to that record: skipped"))
            else:
                seen[key] = n
                out["plan"].append(dict(line=n, owner_type=ot, owner_id=oid, title=title or fn, file_name=fn, content_type=EXT[ext], data=data))
        except InvError as e:
            err = e.message
        if err:
            row["status"], row["messages"] = "error", [dict(level="error", text=err)]
        out["rows"].append(row)
    out["unused_files"] = sorted(set(files) - used)
    for r in out["rows"]:
        out["ok"] += r["status"] == "ok"
        out["duplicates"] += r["status"] == "duplicate"
        out["errors"] += r["status"] == "error"
    return out


def bulk_preview(db, ctx, a: Access, manifest: bytes, files: dict) -> dict:
    """Nothing is stored. Same checks as the commit."""
    a.require("edit")
    p = _bulk_plan(db, ctx, manifest, files)
    p.pop("plan", None)
    p["can_commit"] = p["ok"] > 0 and not p.get("file_error")
    return p


def bulk_commit(db, ctx, a: Access, manifest: bytes, files: dict, mode: str = "valid_only") -> dict:
    a.require("edit")
    if mode not in ("valid_only", "all_or_nothing"):
        raise InvError("mode must be valid_only or all_or_nothing")
    p = _bulk_plan(db, ctx, manifest, files)
    if p.get("file_error"):
        raise InvError(p["file_error"])
    if mode == "all_or_nothing" and p["errors"]:
        raise Conflict(f"{p['errors']} row(s) have errors: nothing was uploaded (mode: all or nothing). Fix the manifest or upload the valid rows only.", "has_errors")
    done, failed = 0, []
    for item in p["plan"]:
        sp = db.begin_nested()
        try:
            upload(db, ctx, a, item["owner_type"], item["owner_id"], item["title"], item["file_name"], item["content_type"], item["data"])
            sp.commit()
            done += 1
        except Exception as e:
            sp.rollback()
            failed.append(dict(line=item["line"], error=getattr(e, "message", None) or str(e)))
    core.record(db, ctx, "import.documents", "inv_import", "documents", f"Bulk documents: {done} uploaded, {p['duplicates']} duplicate(s) skipped, {p['errors']} rejected, {len(failed)} failed (manifest sha256 {p['file_sha256'][:12]})", None,
                dict(mode=mode, uploaded=done, duplicates=p["duplicates"], rejected=p["errors"], failed=len(failed), sha256=p["file_sha256"]))
    return dict(mode=mode, uploaded=done, skipped_duplicates=p["duplicates"], rejected=p["errors"], failed=failed, total=p["total"], unused_files=p["unused_files"], file_sha256=p["file_sha256"], rows=p["rows"])
