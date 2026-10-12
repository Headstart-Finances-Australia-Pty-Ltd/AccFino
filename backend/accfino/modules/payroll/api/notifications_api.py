"""Approval notifications (the bell) and the pending-approvals count (the badge on Time & Leave). Everything here is scoped to the signed-in caller."""
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from accfino.core.security.context import OrgContext, current_org
from accfino.modules.payroll.access import Access
from accfino.modules.payroll.api.deps import access
from accfino.modules.payroll.services import notify
from accfino.shared.db.database import get_db

router = APIRouter()
Ctx, Db, Acc = Depends(current_org), Depends(get_db), Depends(access)


@router.get("/approvals/pending")
def pending(ctx: OrgContext = Ctx, db: Session = Db, a: Access = Acc):
    """{timesheets, leave, total} waiting for the caller to decide (their direct reports', or everyone's for payroll staff; never their own)."""
    return notify.pending_approvals(db, ctx, a)


@router.get("/notifications")
def notifications(ctx: OrgContext = Ctx, db: Session = Db, a: Access = Acc):
    return notify.list_mine(db, ctx)


@router.post("/notifications/read-all")
def read_all(ctx: OrgContext = Ctx, db: Session = Db, a: Access = Acc):
    n = notify.mark_read(db, ctx)
    db.commit()
    return {"marked": n}


@router.post("/notifications/{notification_id}/read")
def read_one(notification_id: int, ctx: OrgContext = Ctx, db: Session = Db, a: Access = Acc):
    n = notify.mark_read(db, ctx, notification_id)
    db.commit()
    return {"marked": n}
