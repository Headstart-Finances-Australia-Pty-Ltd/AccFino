"""/imports: bulk CSV loading for Books & Accounting.

  GET  /imports                     the list of imports with their columns, notes and options (drives the import window in the app)
  GET  /imports/{entity}/template   a ready-to-fill CSV template for that entity
  POST /imports/{entity}            multipart: file, dry_run (default true), mode (post|draft), amounts_are
                                    dry_run=true  -> validates by doing the whole import inside a transaction that is then rolled back
                                    dry_run=false -> imports, all-or-nothing (nothing is saved if any record has a problem)

Journals and bank statement lines keep their existing importers (/ledger/journal-import, /banking/lines/import-csv).
"""
from fastapi import APIRouter, Depends, File, Form, Request, UploadFile
from pydantic import BaseModel
from fastapi.responses import Response
from sqlalchemy.orm import Session

from accfino.modules.accounting.books import csv_import as CI
from accfino.modules.accounting.books.common import BooksError, bulk_import_enabled, require_bulk_import, set_bulk_import
from accfino.core.security import audit
from accfino.core.security.context import OrgContext, current_auth, current_org
from accfino.core.security.login import client_ip
from accfino.shared.db.database import get_db

router = APIRouter()
admin_router = APIRouter()        # mounted at /admin/bulk-import (administrators only - the /admin/ prefix is admin-guarded by the auth middleware)


@router.get("/status")
def status(ctx: OrgContext = Depends(current_org), db: Session = Depends(get_db)):
    """Is bulk import switched on platform-wide? (The app hides every import button when it is not.)"""
    from accfino.core.subscription import service as S
    return {"enabled": bulk_import_enabled(db) and S.is_allowed(S.entitlements(db, ctx.org.id), ("bulk-import",))}


@router.get("")
def list_imports(ctx: OrgContext = Depends(current_org), db: Session = Depends(get_db)):
    ctx.require("read")
    require_bulk_import(db, ctx)
    return {"items": CI.catalogue()}


@router.get("/{entity}/template")
def template(entity: str, ctx: OrgContext = Depends(current_org), db: Session = Depends(get_db)):
    ctx.require("read")
    require_bulk_import(db, ctx)
    if entity not in CI.SPECS:
        raise BooksError(f"Unknown import '{entity}'", 404)
    return Response(CI.template_csv(entity), media_type="text/csv", headers={"Content-Disposition": f'attachment; filename="{entity}-template.csv"'})


@router.post("/{entity}")
async def run(entity: str, request: Request, file: UploadFile = File(...), dry_run: bool = Form(True), mode: str | None = Form(None),
              amounts_are: str | None = Form(None), ctx: OrgContext = Depends(current_org), db: Session = Depends(get_db)):
    require_bulk_import(db, ctx)
    ctx.require("post")          # a check run executes the real posting code (then rolls it back), so it needs the same permission as the import
    raw = await file.read()
    opts = {k: v for k, v in (("mode", mode), ("amounts_are", amounts_are)) if v}
    if opts.get("mode") not in (None, "post", "draft"):
        raise BooksError("mode must be post or draft")
    try:
        res = CI.run_import(db, ctx.org, ctx, entity, raw, dry_run=dry_run, options=opts)
    except Exception:
        db.rollback()
        raise
    if not dry_run and not res.get("error"):
        db.commit()
        audit.write("books.import.csv", user_id=ctx.user_id, username=ctx.username, org_id=ctx.org.id, entity=entity, entity_id=None, ip=client_ip(request),
                    detail=dict(filename=(file.filename or "")[:200], records=res["count"], total=res["total"], options=opts))
    else:
        db.rollback()
    return res


class BulkImportIn(BaseModel):
    enabled: bool


@admin_router.get("")
def admin_get(db: Session = Depends(get_db)):
    return {"enabled": bulk_import_enabled(db)}


@admin_router.put("")
def admin_set(body: BulkImportIn, request: Request, auth: dict = Depends(current_auth), db: Session = Depends(get_db)):
    set_bulk_import(db, body.enabled)
    db.commit()
    audit.write("admin.bulk_import", user_id=auth["user_id"], username=auth["username"], entity="system", entity_id="bulk_import", ip=client_ip(request),
                detail={"enabled": body.enabled})
    return {"enabled": body.enabled}
