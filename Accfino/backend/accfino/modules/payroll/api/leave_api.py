from fastapi import APIRouter, Body, Depends
from sqlalchemy.orm import Session

from accfino.core.security.context import OrgContext, current_org
from accfino.modules.payroll.access import Access
from accfino.modules.payroll.api.deps import access
from accfino.modules.payroll.models.payroll import PayEmployee, PayLeaveRequest, PayLeaveType
from accfino.modules.payroll.services import leave as L, notify
from accfino.modules.payroll.services.errors import NotFound
from accfino.shared.db.database import get_db

router = APIRouter(prefix="/leave")
Ctx, Db, Acc = Depends(current_org), Depends(get_db), Depends(access)


def _one(db, ctx, r):
    return L.ser_request(r, db.get(PayEmployee, r.employee_id), db.get(PayLeaveType, r.leave_type_id))


@router.get("/requests")
def requests(status: str = "", employee_id: int = 0, mine: bool = False, ctx: OrgContext = Ctx, db: Session = Db, a: Access = Acc):
    return L.list_requests(db, ctx, a, status=status, employee_id=employee_id, mine=mine)


@router.post("/requests")
def create(body: dict = Body(...), ctx: OrgContext = Ctx, db: Session = Db, a: Access = Acc):
    r = L.request_leave(db, ctx, a, body)
    db.commit()
    notify.deliver(db)
    return _one(db, ctx, r)


@router.post("/requests/{rid}/approve")
def approve(rid: int, body: dict = Body(default={}), ctx: OrgContext = Ctx, db: Session = Db, a: Access = Acc):
    r = L.decide(db, ctx, a, rid, True, body.get("note", ""))
    db.commit()
    notify.deliver(db)
    return _one(db, ctx, r)


@router.post("/requests/{rid}/reject")
def reject(rid: int, body: dict = Body(default={}), ctx: OrgContext = Ctx, db: Session = Db, a: Access = Acc):
    r = L.decide(db, ctx, a, rid, False, body.get("note", ""))
    db.commit()
    notify.deliver(db)
    return _one(db, ctx, r)


@router.post("/requests/{rid}/cancel")
def cancel(rid: int, ctx: OrgContext = Ctx, db: Session = Db, a: Access = Acc):
    r = L.cancel(db, ctx, a, rid)
    db.commit()
    return _one(db, ctx, r)


@router.get("/my-balances")
def my_balances(ctx: OrgContext = Ctx, db: Session = Db, a: Access = Acc):
    if a.employee is None:
        raise NotFound("Employee record for your login")
    return L.employee_balances(db, ctx, a, a.employee.id)
