"""/books/legacy (organisation) and /admin/books (platform administrator): A1 report, A7 backfill/reconciliation/read-only switch."""
from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel
from sqlalchemy.orm import Session

from accfino.core import models as m
from accfino.modules.accounting.books import docs as D
from accfino.modules.accounting.books import legacy as G
from accfino.modules.accounting.books import money_migration
from accfino.modules.accounting.books.common import BooksError
from accfino.core.security import audit
from accfino.core.security.context import OrgContext, current_auth, current_org
from accfino.core.security.login import client_ip
from accfino.shared.db.database import get_db

org_router = APIRouter()
admin_router = APIRouter()


class BackfillIn(BaseModel):
    dry_run: bool = True
    include_transactions: bool = True


class ReadonlyIn(BaseModel):
    enabled: bool


def _audit(ctx, request, event, **detail):
    audit.write(f"books.{event}", user_id=ctx.user_id, username=ctx.username, org_id=ctx.org.id, entity="organisation", entity_id=ctx.org.id,
                ip=client_ip(request), detail=detail or None)


@org_router.get("/reconciliation")
def reconciliation(ctx: OrgContext = Depends(current_org), db: Session = Depends(get_db)):
    ctx.require("read")
    return G.reconciliation(db, ctx.org)


@org_router.post("/backfill")
def backfill(body: BackfillIn, request: Request, ctx: OrgContext = Depends(current_org), db: Session = Depends(get_db)):
    """Preview (dry_run=true, the default) or perform the one-off import of this organisation's legacy records."""
    ctx.require("settings")
    res = G.backfill(db, ctx.org, ctx.user_id, dry_run=body.dry_run, include_transactions=body.include_transactions)
    if not body.dry_run:
        db.commit()
        _audit(ctx, request, "legacy.backfilled", documents=res["documents"], contacts=res["contacts"], transactions=res["transactions"])
    else:
        db.rollback()
    return res


@org_router.get("/records")
def records(ctx: OrgContext = Depends(current_org), db: Session = Depends(get_db)):
    ctx.require("read")
    return {"items": G.list_records(db, ctx.org)}


@org_router.post("/records/{doc_id}/promote", status_code=201)
def promote(doc_id: int, request: Request, ctx: OrgContext = Depends(current_org), db: Session = Depends(get_db)):
    ctx.require("post")
    d = G.promote(db, ctx.org, ctx.user_id, doc_id)
    db.commit()
    _audit(ctx, request, "legacy.promoted", from_record=doc_id, to=d.number)
    return D.doc_dict(db, d)


@admin_router.get("/money-columns")
def money_report(db: Session = Depends(get_db)):
    """A1: were the legacy floating-point columns converted, and what were the before/after totals?"""
    return money_migration.report(db)


@admin_router.post("/money-columns/apply")
def money_apply(db: Session = Depends(get_db)):
    res = money_migration.run(db.get_bind())
    return {"converted": [r for r in res if "error" not in r], "errors": [r for r in res if "error" in r], **money_migration.report(db)}


@admin_router.get("/legacy/status")
def legacy_status(db: Session = Depends(get_db)):
    return {"readonly": G.is_readonly(db)}


@admin_router.post("/legacy/readonly")
def legacy_readonly(body: ReadonlyIn, request: Request, auth: dict = Depends(current_auth), db: Session = Depends(get_db)):
    """Retire the legacy write endpoints platform-wide (reads keep working). Reversible."""
    G.set_readonly(db, body.enabled)
    db.commit()
    audit.write("books.legacy.readonly", user_id=auth["user_id"], username=auth["username"], entity="system", entity_id="legacy", ip=client_ip(request),
                detail={"enabled": body.enabled})
    return {"readonly": body.enabled}


@admin_router.get("/legacy/reconciliation-all")
def reconciliation_all(db: Session = Depends(get_db)):
    """Every organisation that has legacy data, with its reconciliation verdict."""
    out = []
    for org in db.query(m.Organisation).filter(m.Organisation.legacy_user_id.isnot(None)).order_by(m.Organisation.id):
        r = G.reconciliation(db, org)
        out.append(dict(org_id=org.id, name=org.name, reconciled=r.get("reconciled"), documents=r.get("documents"), transactions=r.get("transactions")))
    return {"organisations": out, "all_reconciled": all(o["reconciled"] for o in out) if out else True}
