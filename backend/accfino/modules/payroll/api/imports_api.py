"""/payroll/imports: bulk CSV loading for Payroll & Workforce.

  GET  /payroll/imports/status            is bulk import switched on? (the app hides every Import button when it is not)
  GET  /payroll/imports                   the imports with their columns, notes and load order (drives the import window), each marked with what the caller may do
  GET  /payroll/imports/{entity}/template a ready-to-fill CSV template for that entity
  POST /payroll/imports/{entity}          multipart: file, dry_run (default true)
                                          dry_run=true  -> validates by doing the whole import inside a transaction that is then rolled back
                                          dry_run=false -> imports, all-or-nothing (nothing is saved if any record has a problem)

Same platform switch (Admin > Modules Management > Bulk data import) and the same plan feature ("bulk-import") as the Books & Accounting imports.
Each import needs the payroll capability of the screen it feeds (e.g. employees_manage for employees): a check run executes the real code, then rolls back,
so it needs the same permission as the import itself. Fields are named `file` and `dry_run` only (never user_id / username: see api/__init__.py).
"""
from fastapi import APIRouter, Depends, File, Form, Request, UploadFile
from fastapi.responses import Response
from sqlalchemy.orm import Session

from accfino.core import models as m
from accfino.core.security.context import OrgContext, current_org
from accfino.core.subscription import service as S
from accfino.modules.payroll.access import Access
from accfino.modules.payroll.api.deps import access
from accfino.modules.payroll.services import csv_import as CI
from accfino.modules.payroll.services.errors import Forbidden, PayrollError
from accfino.shared.db.database import get_db

router = APIRouter(prefix="/imports")
Ctx, Db, Acc = Depends(current_org), Depends(get_db), Depends(access)
BULK_IMPORT_KEY = "platform.bulk_import"          # the platform-wide switch shared with Books & Accounting


def _switched_on(db) -> bool:
    row = db.get(m.SystemSetting, BULK_IMPORT_KEY)
    return not (row and (row.value or "").strip().lower() == "off")


def _require_bulk(db, ctx):
    if not _switched_on(db):
        raise Forbidden("Bulk data import has been switched off by your platform administrator (Admin > Modules Management).")
    S.check(db, ctx, ("bulk-import",), "POST")         # the organisation's plan must include bulk import, and must not be read-only


def _spec(entity: str) -> CI.Spec:
    s = CI.SPECS.get(entity)
    if s is None:
        raise PayrollError(f"Unknown import '{entity}'", 404)
    return s


@router.get("/status")
def status(ctx: OrgContext = Ctx, db: Session = Db, a: Access = Acc):
    return {"enabled": _switched_on(db) and S.is_allowed(S.entitlements(db, ctx.org.id), ("bulk-import",))}


@router.get("")
def list_imports(ctx: OrgContext = Ctx, db: Session = Db, a: Access = Acc):
    _require_bulk(db, ctx)
    items = CI.catalogue()
    for i in items:
        i["allowed"] = a.has(i["capability"])
    return {"items": items}


@router.get("/{entity}/template")
def template(entity: str, ctx: OrgContext = Ctx, db: Session = Db, a: Access = Acc):
    _require_bulk(db, ctx)
    _spec(entity)
    return Response(CI.template_csv(entity), media_type="text/csv", headers={"Content-Disposition": f'attachment; filename="payroll-{entity}-template.csv"'})


@router.post("/{entity}")
async def run(entity: str, request: Request, file: UploadFile = File(...), dry_run: bool = Form(True), ctx: OrgContext = Ctx, db: Session = Db, a: Access = Acc):
    _require_bulk(db, ctx)
    spec = _spec(entity)
    a.require(spec.cap)
    raw = await file.read()
    try:
        res = CI.run_import(db, ctx.org, ctx, a, entity, raw, dry_run=dry_run, filename=file.filename or "")
    except Exception:
        db.rollback()
        raise
    if not dry_run and not res.get("error"):
        db.commit()
    else:
        db.rollback()
    return res
