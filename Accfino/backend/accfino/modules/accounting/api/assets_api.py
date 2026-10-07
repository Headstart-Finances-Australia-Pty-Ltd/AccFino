"""/assets: fixed asset register, depreciation runs, disposal, register report and control check."""
from datetime import date
from decimal import Decimal

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session

from accfino.modules.accounting.assets import models as a
from accfino.modules.accounting.assets import service as S
from accfino.modules.accounting.books.common import BooksError
from accfino.core.security import audit
from accfino.core.security.context import OrgContext, current_org
from accfino.core.security.login import client_ip
from accfino.shared.db.database import get_db

router = APIRouter()


class AssetIn(BaseModel):
    model_config = ConfigDict(extra="ignore")
    number: str | None = None
    name: str
    category: str | None = None
    asset_account: str | int
    depreciation_account: str | int
    expense_account: str | int | None = None
    purchase_date: date
    cost: Decimal
    residual_value: Decimal = Decimal("0.00")
    method: str = "straight_line"
    effective_life_months: int | None = None
    dv_rate_pct: Decimal | None = None
    opening_accumulated_depreciation: Decimal = Decimal("0.00")
    notes: str | None = None


class AssetPatch(BaseModel):
    model_config = ConfigDict(extra="ignore")
    name: str | None = None
    category: str | None = None
    notes: str | None = None
    purchase_date: date | None = None
    cost: Decimal | None = None
    residual_value: Decimal | None = None
    method: str | None = None
    effective_life_months: int | None = None
    dv_rate_pct: Decimal | None = None
    opening_accumulated_depreciation: Decimal | None = None


class RunIn(BaseModel):
    as_at: date
    asset_ids: list[int] | None = None


class DisposeIn(BaseModel):
    date: date
    proceeds: Decimal = Decimal("0.00")
    bank_account: str | int | None = None


def _audit(ctx, request, event, asset, **detail):
    audit.write(f"assets.{event}", user_id=ctx.user_id, username=ctx.username, org_id=ctx.org.id, entity="fixed_asset", entity_id=asset.id,
                ip=client_ip(request), detail={"number": asset.number, **detail})


def _get(db, ctx, asset_id, lock=False):
    q = db.query(a.FixedAsset).filter_by(org_id=ctx.org.id, id=asset_id)
    x = (q.with_for_update() if lock else q).one_or_none()
    if x is None:
        raise BooksError("Asset not found", 404)
    return x


@router.get("/register")
def register_report(as_at: date | None = None, ctx: OrgContext = Depends(current_org), db: Session = Depends(get_db)):
    ctx.require("read")
    return S.register_report(db, ctx.org, as_at or date.today())


@router.get("/control")
def control(as_at: date | None = None, ctx: OrgContext = Depends(current_org), db: Session = Depends(get_db)):
    ctx.require("read")
    return S.control(db, ctx.org, as_at or date.today())


@router.get("")
def list_assets(status: str | None = None, ctx: OrgContext = Depends(current_org), db: Session = Depends(get_db)):
    ctx.require("read")
    q = db.query(a.FixedAsset).filter_by(org_id=ctx.org.id)
    if status:
        q = q.filter(a.FixedAsset.status == status)
    return {"items": [S.asset_dict(x) for x in q.order_by(a.FixedAsset.number)]}


@router.post("", status_code=201)
def create(body: AssetIn, request: Request, ctx: OrgContext = Depends(current_org), db: Session = Depends(get_db)):
    ctx.require("post")
    x = S.register(db, ctx.org, ctx.user_id, body.model_dump())
    db.commit()
    _audit(ctx, request, "registered", x, cost=str(x.cost))
    return S.asset_dict(x)


@router.get("/{asset_id}")
def get_one(asset_id: int, ctx: OrgContext = Depends(current_org), db: Session = Depends(get_db)):
    ctx.require("read")
    return S.asset_dict(_get(db, ctx, asset_id))


@router.put("/{asset_id}")
def update(asset_id: int, body: AssetPatch, request: Request, ctx: OrgContext = Depends(current_org), db: Session = Depends(get_db)):
    ctx.require("post")
    x = _get(db, ctx, asset_id, lock=True)
    S.update(db, ctx.org, x, body.model_dump(exclude_unset=True))
    db.commit()
    _audit(ctx, request, "updated", x)
    return S.asset_dict(x)


@router.delete("/{asset_id}")
def delete(asset_id: int, request: Request, ctx: OrgContext = Depends(current_org), db: Session = Depends(get_db)):
    ctx.require("post")
    x = _get(db, ctx, asset_id, lock=True)
    S.delete(db, x)
    db.commit()
    _audit(ctx, request, "deleted", x)
    return {"deleted": True}


@router.post("/depreciation/run")
def run(body: RunIn, request: Request, ctx: OrgContext = Depends(current_org), db: Session = Depends(get_db)):
    ctx.require("post")
    res = S.run_depreciation(db, ctx.org, ctx.user_id, as_at=body.as_at, asset_ids=body.asset_ids)
    db.commit()
    audit.write("assets.depreciation_run", user_id=ctx.user_id, username=ctx.username, org_id=ctx.org.id, entity="organisation", entity_id=ctx.org.id,
                ip=client_ip(request), detail={"as_at": body.as_at.isoformat(), "posted": len(res["posted"]), "skipped": len(res["skipped"])})
    return res


@router.post("/{asset_id}/dispose")
def dispose(asset_id: int, body: DisposeIn, request: Request, ctx: OrgContext = Depends(current_org), db: Session = Depends(get_db)):
    ctx.require("post")
    x = _get(db, ctx, asset_id, lock=True)
    res = S.dispose(db, ctx.org, ctx.user_id, x, disposal_date=body.date, proceeds=body.proceeds, bank_ref=body.bank_account)
    db.commit()
    _audit(ctx, request, "disposed", x, **res)
    return {**S.asset_dict(x), "disposal": res}
