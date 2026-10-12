"""/inventory: stock items, movements (buy/sell/adjustment/opening), valuation and control reports."""
from datetime import date
from datetime import date as Date
from decimal import Decimal

from fastapi import APIRouter, Depends, Query, Request
from pydantic import BaseModel, ConfigDict
from sqlalchemy.orm import Session

from accfino.modules.accounting.books.common import BooksError
from accfino.modules.accounting.inventory import models as inv
from accfino.modules.accounting.inventory import service as S
from accfino.core.security import audit
from accfino.core.security.context import OrgContext, current_org
from accfino.core.security.login import client_ip
from accfino.shared.db.database import get_db

router = APIRouter()


class ItemIn(BaseModel):
    model_config = ConfigDict(extra="ignore")
    sku: str
    name: str
    description: str | None = None
    inventory_account: str | int | None = None
    cogs_account: str | int | None = None
    sales_account: str | int | None = None
    purchase_tax_code: str | None = None
    sales_tax_code: str | None = None
    sale_price: Decimal | None = None


class ItemPatch(BaseModel):
    model_config = ConfigDict(extra="ignore")
    name: str | None = None
    description: str | None = None
    sale_price: Decimal | None = None
    is_active: bool | None = None


class MovementIn(BaseModel):
    model_config = ConfigDict(extra="ignore")
    kind: str
    date: Date | None = None
    quantity: Decimal | None = None
    unit_cost: Decimal | None = None
    counted_quantity: Decimal | None = None
    account: str | int | None = None
    credit_account: str | int | None = None
    debit_account: str | int | None = None
    reference: str | None = None
    note: str | None = None


def _audit(ctx, request, event, item, **detail):
    audit.write(f"inventory.{event}", user_id=ctx.user_id, username=ctx.username, org_id=ctx.org.id, entity="stock_item", entity_id=item.id,
                ip=client_ip(request), detail={"sku": item.sku, **detail})


def _get(db, ctx, item_id, lock=False):
    q = db.query(inv.StockItem).filter_by(org_id=ctx.org.id, id=item_id)
    x = (q.with_for_update() if lock else q).one_or_none()
    if x is None:
        raise BooksError("Stock item not found", 404)
    return x


@router.get("/items")
def list_items(q: str = "", include_inactive: bool = False, ctx: OrgContext = Depends(current_org), db: Session = Depends(get_db)):
    ctx.require("read")
    qq = db.query(inv.StockItem).filter_by(org_id=ctx.org.id)
    if not include_inactive:
        qq = qq.filter(inv.StockItem.is_active.is_(True))
    if q:
        qq = qq.filter((inv.StockItem.sku.ilike(f"%{q}%")) | (inv.StockItem.name.ilike(f"%{q}%")))
    return {"items": [S.item_dict(x) for x in qq.order_by(inv.StockItem.sku)]}


@router.post("/items", status_code=201)
def create_item(body: ItemIn, request: Request, ctx: OrgContext = Depends(current_org), db: Session = Depends(get_db)):
    ctx.require("post")
    x = S.create_item(db, ctx.org, body.model_dump())
    db.commit()
    _audit(ctx, request, "item_created", x)
    return S.item_dict(x)


@router.get("/items/{item_id}")
def get_item(item_id: int, ctx: OrgContext = Depends(current_org), db: Session = Depends(get_db)):
    ctx.require("read")
    return S.item_dict(_get(db, ctx, item_id))


@router.put("/items/{item_id}")
def update_item(item_id: int, body: ItemPatch, request: Request, ctx: OrgContext = Depends(current_org), db: Session = Depends(get_db)):
    ctx.require("post")
    x = _get(db, ctx, item_id, lock=True)
    S.update_item(db, x, body.model_dump(exclude_unset=True))
    db.commit()
    _audit(ctx, request, "item_updated", x)
    return S.item_dict(x)


@router.delete("/items/{item_id}")
def delete_item(item_id: int, request: Request, ctx: OrgContext = Depends(current_org), db: Session = Depends(get_db)):
    ctx.require("post")
    x = _get(db, ctx, item_id, lock=True)
    S.delete_item(db, x)
    db.commit()
    _audit(ctx, request, "item_deleted", x)
    return {"deleted": True}


@router.get("/items/{item_id}/movements")
def item_movements(item_id: int, ctx: OrgContext = Depends(current_org), db: Session = Depends(get_db)):
    ctx.require("read")
    _get(db, ctx, item_id)
    return {"items": S.movements_report(db, ctx.org, item_id=item_id)}


@router.post("/items/{item_id}/movements", status_code=201)
def add_movement(item_id: int, body: MovementIn, request: Request, ctx: OrgContext = Depends(current_org), db: Session = Depends(get_db)):
    ctx.require("post")
    x = _get(db, ctx, item_id, lock=True)
    mv = S.record_movement(db, ctx.org, ctx.user_id, x, body.model_dump())
    db.commit()
    _audit(ctx, request, "movement", x, kind=mv.kind, quantity=str(mv.quantity), amount=str(mv.amount), journal_id=mv.journal_id)
    return {**S.movement_dict(mv), "item": S.item_dict(x)}


# alias matching the roadmap's own spec test: POST /inventory/movements {item, ...}
class MovementWithItemIn(MovementIn):
    item: str


@router.post("/movements", status_code=201)
def add_movement_by_sku(body: MovementWithItemIn, request: Request, ctx: OrgContext = Depends(current_org), db: Session = Depends(get_db)):
    ctx.require("post")
    x = db.query(inv.StockItem).filter_by(org_id=ctx.org.id, sku=body.item).with_for_update().one_or_none()
    if x is None:
        raise BooksError(f"No stock item with SKU '{body.item}'", 404)
    mv = S.record_movement(db, ctx.org, ctx.user_id, x, body.model_dump())
    db.commit()
    _audit(ctx, request, "movement", x, kind=mv.kind, quantity=str(mv.quantity), amount=str(mv.amount), journal_id=mv.journal_id)
    return {**S.movement_dict(mv), "item": S.item_dict(x)}


@router.get("/movements")
def list_movements(item_id: int | None = None, date_from: date | None = Query(None, alias="from"), date_to: date | None = Query(None, alias="to"),
                   ctx: OrgContext = Depends(current_org), db: Session = Depends(get_db)):
    ctx.require("read")
    return {"items": S.movements_report(db, ctx.org, item_id=item_id, date_from=date_from, date_to=date_to)}


@router.get("/valuation")
def valuation(ctx: OrgContext = Depends(current_org), db: Session = Depends(get_db)):
    ctx.require("read")
    return S.valuation_report(db, ctx.org)


@router.get("/control")
def control(as_at: date | None = None, ctx: OrgContext = Depends(current_org), db: Session = Depends(get_db)):
    ctx.require("read")
    return S.control(db, ctx.org, as_at or date.today())
