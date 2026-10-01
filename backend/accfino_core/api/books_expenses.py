"""/expenses: claims, approval, reimbursement."""
from datetime import date
from datetime import date as Date  # a field called 'date' would shadow the type inside a model
from decimal import Decimal

from fastapi import APIRouter, Depends, Query, Request
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import func
from sqlalchemy.orm import Session, selectinload

from accfino_core.books import expenses as X
from accfino_core.books import models as b
from accfino_core.books.common import BooksError
from accfino_core.security import audit
from accfino_core.security.context import OrgContext, current_org
from accfino_core.security.login import client_ip
from db_app.database import get_db

router = APIRouter()


class ItemIn(BaseModel):
    model_config = ConfigDict(extra="ignore")
    date: Date | None = None
    merchant: str | None = None
    description: str
    account: str | int
    amount: Decimal | None = None
    tax_code: str | None = None
    kind: str = "receipt"
    km: Decimal | None = None
    rate_per_km: Decimal | None = None


class ClaimIn(BaseModel):
    title: str | None = None
    items: list[ItemIn] | None = None


class ApproveIn(BaseModel):
    post_date: Date | None = None


class RejectIn(BaseModel):
    reason: str


class ReimburseIn(BaseModel):
    date: Date = Field(default_factory=Date.today)
    bank_account: str | int
    reference: str | None = None


def _audit(ctx, request, event, claim, **detail):
    audit.write(f"expenses.{event}", user_id=ctx.user_id, username=ctx.username, org_id=ctx.org.id, entity="expense_claim", entity_id=claim.id,
                ip=client_ip(request), detail={"number": claim.number, **detail})


def _get(db, ctx, cid, lock=False):
    q = db.query(b.ExpenseClaim).options(selectinload(b.ExpenseClaim.items)).filter_by(org_id=ctx.org.id, id=cid)
    c = (q.with_for_update() if lock else q).one_or_none()
    if c is None:
        raise BooksError("Expense claim not found", 404)
    if c.claimant_user_id != ctx.user_id and not (X.can_approve(ctx) or ctx.can("audit")):
        raise BooksError("You can only see your own expense claims", 403)
    return c


@router.get("/claims")
def list_claims(status: str | None = None, mine: bool = False, limit: int = Query(100, le=500), offset: int = 0,
                ctx: OrgContext = Depends(current_org), db: Session = Depends(get_db)):
    ctx.require("read")
    q = db.query(b.ExpenseClaim).options(selectinload(b.ExpenseClaim.items)).filter_by(org_id=ctx.org.id)
    if mine or not (X.can_approve(ctx) or ctx.can("audit")):
        q = q.filter(b.ExpenseClaim.claimant_user_id == ctx.user_id)
    if status:
        q = q.filter(b.ExpenseClaim.status == status)
    total = q.count()
    return {"total": total, "items": [X.claim_dict(db, c, detail=False) for c in q.order_by(b.ExpenseClaim.id.desc()).limit(limit).offset(offset)]}


@router.post("/claims", status_code=201)
def create(body: ClaimIn, request: Request, ctx: OrgContext = Depends(current_org), db: Session = Depends(get_db)):
    ctx.require("post")
    c = X.create_claim(db, ctx.org, ctx, body.model_dump())
    db.commit()
    _audit(ctx, request, "claim.created", c, total=str(c.total))
    return X.claim_dict(db, c)


@router.get("/claims/{claim_id}")
def get_claim(claim_id: int, ctx: OrgContext = Depends(current_org), db: Session = Depends(get_db)):
    ctx.require("read")
    return X.claim_dict(db, _get(db, ctx, claim_id))


@router.put("/claims/{claim_id}")
def update(claim_id: int, body: ClaimIn, request: Request, ctx: OrgContext = Depends(current_org), db: Session = Depends(get_db)):
    ctx.require("post")
    c = _get(db, ctx, claim_id, lock=True)
    X.update_claim(db, ctx.org, ctx, c, body.model_dump(exclude_unset=True))
    db.commit()
    _audit(ctx, request, "claim.updated", c)
    return X.claim_dict(db, c)


@router.delete("/claims/{claim_id}")
def delete(claim_id: int, request: Request, ctx: OrgContext = Depends(current_org), db: Session = Depends(get_db)):
    ctx.require("post")
    c = _get(db, ctx, claim_id, lock=True)
    X.delete_claim(db, ctx, c)
    db.commit()
    _audit(ctx, request, "claim.deleted", c)
    return {"deleted": True}


@router.post("/claims/{claim_id}/submit")
def submit(claim_id: int, request: Request, ctx: OrgContext = Depends(current_org), db: Session = Depends(get_db)):
    ctx.require("post")
    c = _get(db, ctx, claim_id, lock=True)
    X.submit(db, ctx.org, ctx, c)
    db.commit()
    _audit(ctx, request, "claim.submitted", c, total=str(c.total))
    return X.claim_dict(db, c)


@router.post("/claims/{claim_id}/approve")
def approve(claim_id: int, request: Request, body: ApproveIn = ApproveIn(), ctx: OrgContext = Depends(current_org), db: Session = Depends(get_db)):
    ctx.require("post")
    c = _get(db, ctx, claim_id, lock=True)
    _, self_approved = X.approve(db, ctx.org, ctx, c, body.post_date)
    db.commit()
    _audit(ctx, request, "claim.approved", c, total=str(c.total), journal_id=c.approval_journal_id, self_approved=self_approved)
    return X.claim_dict(db, c)


@router.post("/claims/{claim_id}/reject")
def reject(claim_id: int, body: RejectIn, request: Request, ctx: OrgContext = Depends(current_org), db: Session = Depends(get_db)):
    ctx.require("post")
    c = _get(db, ctx, claim_id, lock=True)
    X.reject(db, ctx, c, body.reason)
    db.commit()
    _audit(ctx, request, "claim.rejected", c, reason=body.reason)
    return X.claim_dict(db, c)


@router.post("/claims/{claim_id}/unapprove")
def unapprove(claim_id: int, request: Request, ctx: OrgContext = Depends(current_org), db: Session = Depends(get_db)):
    ctx.require("post")
    c = _get(db, ctx, claim_id, lock=True)
    X.unapprove(db, ctx.org, ctx, c)
    db.commit()
    _audit(ctx, request, "claim.unapproved", c)
    return X.claim_dict(db, c)


@router.post("/claims/{claim_id}/reimburse")
def reimburse(claim_id: int, body: ReimburseIn, request: Request, ctx: OrgContext = Depends(current_org), db: Session = Depends(get_db)):
    ctx.require("post")
    c = _get(db, ctx, claim_id, lock=True)
    X.reimburse(db, ctx.org, ctx, c, body.date, body.bank_account, body.reference)
    db.commit()
    _audit(ctx, request, "claim.reimbursed", c, total=str(c.total), journal_id=c.payment_journal_id)
    return X.claim_dict(db, c)


@router.get("/summary")
def summary(ctx: OrgContext = Depends(current_org), db: Session = Depends(get_db)):
    ctx.require("read")
    q = db.query(b.ExpenseClaim.status, func.count(b.ExpenseClaim.id), func.coalesce(func.sum(b.ExpenseClaim.total), 0)).filter_by(org_id=ctx.org.id)
    if not (X.can_approve(ctx) or ctx.can("audit")):
        q = q.filter(b.ExpenseClaim.claimant_user_id == ctx.user_id)
    return {"by_status": {s: dict(count=n, total=str(t)) for s, n, t in q.group_by(b.ExpenseClaim.status)}}
