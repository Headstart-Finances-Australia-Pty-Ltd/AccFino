from typing import Optional

from fastapi import APIRouter, Body, Depends
from sqlalchemy.orm import Session

from accfino.core.security.context import OrgContext, current_org
from accfino.modules.payroll.access import Access
from accfino.modules.payroll.api.deps import access, parse_date
from accfino.modules.payroll.models.payroll import PayEmployee
from accfino.modules.payroll.services import notify, timesheets as T
from accfino.shared.db.database import get_db

router = APIRouter(prefix="/timesheets")
Ctx, Db, Acc = Depends(current_org), Depends(get_db), Depends(access)
_one = lambda db, ts: T.ser(db, ts, db.get(PayEmployee, ts.employee_id))


@router.get("")
def listing(status: str = "", employee_id: int = 0, date_from: Optional[str] = None, date_to: Optional[str] = None, mine: bool = False, ctx: OrgContext = Ctx, db: Session = Db, a: Access = Acc):
    return T.listing(db, ctx, a, status=status, employee_id=employee_id, date_from=parse_date(date_from, "date_from"), date_to=parse_date(date_to, "date_to"), mine=mine)


@router.post("")
def create(body: dict = Body(...), ctx: OrgContext = Ctx, db: Session = Db, a: Access = Acc):
    ts = T.save(db, ctx, a, body)
    db.commit()
    return _one(db, ts)


@router.get("/{ts_id}")
def get(ts_id: int, ctx: OrgContext = Ctx, db: Session = Db, a: Access = Acc):
    return T.get(db, ctx, a, ts_id)


@router.put("/{ts_id}")
def update(ts_id: int, body: dict = Body(...), ctx: OrgContext = Ctx, db: Session = Db, a: Access = Acc):
    ts = T.save(db, ctx, a, body, ts_id)
    db.commit()
    return _one(db, ts)


@router.delete("/{ts_id}")
def delete(ts_id: int, ctx: OrgContext = Ctx, db: Session = Db, a: Access = Acc):
    T.delete(db, ctx, a, ts_id)
    db.commit()
    return {"ok": True}


@router.post("/{ts_id}/submit")
def submit(ts_id: int, ctx: OrgContext = Ctx, db: Session = Db, a: Access = Acc):
    ts = T.submit(db, ctx, a, ts_id)
    db.commit()
    notify.deliver(db)
    return _one(db, ts)


@router.post("/{ts_id}/approve")
def approve(ts_id: int, ctx: OrgContext = Ctx, db: Session = Db, a: Access = Acc):
    ts = T.decide(db, ctx, a, ts_id, True)
    db.commit()
    notify.deliver(db)
    return _one(db, ts)


@router.post("/{ts_id}/reject")
def reject(ts_id: int, body: dict = Body(default={}), ctx: OrgContext = Ctx, db: Session = Db, a: Access = Acc):
    ts = T.decide(db, ctx, a, ts_id, False, body.get("reason", ""))
    db.commit()
    notify.deliver(db)
    return _one(db, ts)


@router.post("/{ts_id}/reopen")
def reopen(ts_id: int, ctx: OrgContext = Ctx, db: Session = Db, a: Access = Acc):
    ts = T.reopen(db, ctx, a, ts_id)
    db.commit()
    return _one(db, ts)
