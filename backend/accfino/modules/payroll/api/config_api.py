from typing import Optional

from fastapi import APIRouter, Body, Depends, Query
from sqlalchemy.orm import Session

from accfino.core.security.context import OrgContext, current_org
import accfino.modules.accounting.public as accounting
from accfino.modules.payroll.access import Access
from accfino.modules.payroll.api.deps import access, parse_date
from accfino.modules.payroll.engine.rules import RulesError, rulebook
from accfino.modules.payroll.models.payroll import PayCalendar, PayDepartment, PayItem, PayLeaveType, PayLocation, PaySuperFund
from accfino.modules.payroll.services import config as C
from accfino.modules.payroll.services import dashboard
from accfino.modules.payroll.services.errors import PayrollError
from accfino.shared.db.database import get_db

router = APIRouter()
q = lambda db, ctx, model, order: db.query(model).filter(model.org_id == ctx.org.id).order_by(*order)


@router.get("/me")
def me(a: Access = Depends(access)):
    return a.summary()


@router.get("/dashboard")
def get_dashboard(ctx: OrgContext = Depends(current_org), db: Session = Depends(get_db), a: Access = Depends(access), today: Optional[str] = None):
    return dashboard.build(db, ctx, a, parse_date(today, "today"))


@router.get("/rules")
def rules(a: Access = Depends(access)):
    """The statutory rule sets in force (rates are DATA in the rules file, not code)."""
    a.require("view")
    try:
        return {"rule_sets": [r.summary() for r in rulebook().sets]}
    except RulesError as e:
        raise PayrollError(str(e), 500)


@router.get("/settings")
def get_settings_(ctx: OrgContext = Depends(current_org), db: Session = Depends(get_db), a: Access = Depends(access)):
    a.require("view")
    out = C.ser_settings(db, ctx)
    db.commit()
    return out


@router.put("/settings")
def put_settings(body: dict = Body(...), ctx: OrgContext = Depends(current_org), db: Session = Depends(get_db), a: Access = Depends(access)):
    out = C.save_settings(db, ctx, a, body)
    db.commit()
    return out


@router.get("/ledger-accounts")
def ledger_accounts(ctx: OrgContext = Depends(current_org), db: Session = Depends(get_db), a: Access = Depends(access)):
    a.require("config_manage")
    return accounting.ledger_accounts(db, ctx.org.id)


@router.get("/calendars")
def calendars(ctx: OrgContext = Depends(current_org), db: Session = Depends(get_db), a: Access = Depends(access)):
    a.require("view")
    return [C.ser_calendar(c) for c in q(db, ctx, PayCalendar, [PayCalendar.name])]


@router.post("/calendars")
def calendar_create(body: dict = Body(...), ctx: OrgContext = Depends(current_org), db: Session = Depends(get_db), a: Access = Depends(access)):
    c = C.save_calendar(db, ctx, a, body)
    db.commit()
    return C.ser_calendar(c)


@router.put("/calendars/{cid}")
def calendar_update(cid: int, body: dict = Body(...), ctx: OrgContext = Depends(current_org), db: Session = Depends(get_db), a: Access = Depends(access)):
    c = C.save_calendar(db, ctx, a, body, cid)
    db.commit()
    return C.ser_calendar(c)


@router.get("/calendars/{cid}/periods")
def calendar_periods(cid: int, around: Optional[str] = None, before: int = Query(3, ge=0, le=26), after: int = Query(6, ge=0, le=26),
                     ctx: OrgContext = Depends(current_org), db: Session = Depends(get_db), a: Access = Depends(access)):
    a.require("view")
    from datetime import date
    c = db.query(PayCalendar).filter_by(id=cid, org_id=ctx.org.id).first()
    if c is None:
        raise PayrollError("Pay calendar not found", 404)
    ps = C.periods_around(c, parse_date(around, "around") or date.today(), before, after)
    return [{"period_start": p["period_start"].isoformat(), "period_end": p["period_end"].isoformat(), "pay_date": p["pay_date"].isoformat()} for p in ps]


def _lst(name, model, ser, order, save, perm="view"):
    @router.get(f"/{name}", name=f"list_{name}")
    def lst(ctx: OrgContext = Depends(current_org), db: Session = Depends(get_db), a: Access = Depends(access)):
        a.require(perm)
        return [ser(r) for r in q(db, ctx, model, order)]

    @router.post(f"/{name}", name=f"create_{name}")
    def create(body: dict = Body(...), ctx: OrgContext = Depends(current_org), db: Session = Depends(get_db), a: Access = Depends(access)):
        r = save(db, ctx, a, body)
        db.commit()
        return ser(r)

    @router.put(f"/{name}/{{rid}}", name=f"update_{name}")
    def update(rid: int, body: dict = Body(...), ctx: OrgContext = Depends(current_org), db: Session = Depends(get_db), a: Access = Depends(access)):
        r = save(db, ctx, a, body, rid)
        db.commit()
        return ser(r)


_simple = lambda r: {"id": r.id, "code": r.code, "name": r.name, "is_active": r.is_active, **({"state": r.state} if hasattr(r, "state") else {})}
_lst("departments", PayDepartment, _simple, [PayDepartment.code], C.save_department)
_lst("locations", PayLocation, _simple, [PayLocation.code], C.save_location)
_lst("super-funds", PaySuperFund, C.ser_fund, [PaySuperFund.name], C.save_fund)
_lst("pay-items", PayItem, C.ser_item, [PayItem.sort, PayItem.code], C.save_item)
_lst("leave-types", PayLeaveType, C.ser_leave_type, [PayLeaveType.code], C.save_leave_type)


@router.delete("/pay-items/{item_id}")
def item_delete(item_id: int, ctx: OrgContext = Depends(current_org), db: Session = Depends(get_db), a: Access = Depends(access)):
    r = C.delete_item(db, ctx, a, item_id)
    db.commit()
    return {"result": r}
