from typing import Optional

from fastapi import APIRouter, Body, Depends, Query
from sqlalchemy.orm import Session

from accfino.core.security.context import OrgContext, current_org
from accfino.modules.payroll.access import Access
from accfino.modules.payroll.api.deps import access
from accfino.modules.payroll.services import employees as E, leave as L
from accfino.modules.payroll.services.errors import Forbidden
from accfino.shared.db.database import get_db

router = APIRouter(prefix="/employees")
Ctx, Db, Acc = Depends(current_org), Depends(get_db), Depends(access)


def _own_or(a: Access, emp_id: int, cap: str):
    if not a.can_act_on(cap, emp_id):
        raise Forbidden("You can only see your own record")


@router.get("")
def list_(q: str = "", status: str = "", department_id: int = 0, employment_type: str = "", manager_id: int = 0, sort: str = "name", page: int = Query(1, ge=1),
          limit: int = Query(50, ge=1, le=200), ctx: OrgContext = Ctx, db: Session = Db, a: Access = Acc):
    return E.list_employees(db, ctx, a, q=q, status=status, department_id=department_id, employment_type=employment_type, manager_id=manager_id, sort=sort, page=page, limit=limit)


@router.get("/login-users")
def login_users(ctx: OrgContext = Ctx, db: Session = Db, a: Access = Acc):
    return E.org_users(db, ctx, a)


@router.post("")
def create(body: dict = Body(...), ctx: OrgContext = Ctx, db: Session = Db, a: Access = Acc):
    e = E.create_employee(db, ctx, a, body)
    db.commit()
    return E.serialize(db, e, a, detail=True)


@router.get("/{emp_id}")
def get(emp_id: int, ctx: OrgContext = Ctx, db: Session = Db, a: Access = Acc):
    _own_or(a, emp_id, "employees_view")
    return E.serialize(db, E.get_employee(db, ctx.org.id, emp_id), a, detail=True)


@router.put("/{emp_id}")
def update(emp_id: int, body: dict = Body(...), ctx: OrgContext = Ctx, db: Session = Db, a: Access = Acc):
    e = E.update_employee(db, ctx, a, emp_id, body)
    db.commit()
    return E.serialize(db, e, a, detail=True)


@router.post("/{emp_id}/terminate")
def terminate(emp_id: int, body: dict = Body(...), ctx: OrgContext = Ctx, db: Session = Db, a: Access = Acc):
    e = E.terminate_employee(db, ctx, a, emp_id, body.get("end_date"), body.get("reason", ""))
    db.commit()
    return E.serialize(db, e, a, detail=True)


@router.get("/{emp_id}/termination-suggestion")
def term_suggestion(emp_id: int, ctx: OrgContext = Ctx, db: Session = Db, a: Access = Acc):
    return L.payout_suggestion(db, ctx, a, emp_id)


@router.put("/{emp_id}/tax")
def tax(emp_id: int, body: dict = Body(...), ctx: OrgContext = Ctx, db: Session = Db, a: Access = Acc):
    out = E.set_tax(db, ctx, a, emp_id, body)
    db.commit()
    return out


@router.post("/{emp_id}/tax/reveal-tfn")
def reveal(emp_id: int, ctx: OrgContext = Ctx, db: Session = Db, a: Access = Acc):
    tfn = E.reveal_tfn(db, ctx, a, emp_id)
    db.commit()                                               # the audit entry must persist even though nothing else changed
    return {"tfn": tfn}


@router.put("/{emp_id}/super")
def super_(emp_id: int, body: dict = Body(...), ctx: OrgContext = Ctx, db: Session = Db, a: Access = Acc):
    out = E.set_super(db, ctx, a, emp_id, body.get("funds", []))
    db.commit()
    return out


@router.put("/{emp_id}/bank")
def bank(emp_id: int, body: dict = Body(...), ctx: OrgContext = Ctx, db: Session = Db, a: Access = Acc):
    out = E.set_bank(db, ctx, a, emp_id, body.get("accounts", []))
    db.commit()
    return out


@router.post("/{emp_id}/items")
def item_add(emp_id: int, body: dict = Body(...), ctx: OrgContext = Ctx, db: Session = Db, a: Access = Acc):
    out = E.assign_item(db, ctx, a, emp_id, body)
    db.commit()
    return out


@router.delete("/{emp_id}/items/{assign_id}")
def item_remove(emp_id: int, assign_id: int, ctx: OrgContext = Ctx, db: Session = Db, a: Access = Acc):
    E.remove_item(db, ctx, a, emp_id, assign_id)
    db.commit()
    return {"ok": True}


@router.get("/{emp_id}/leave")
def leave_balances(emp_id: int, ctx: OrgContext = Ctx, db: Session = Db, a: Access = Acc):
    return L.employee_balances(db, ctx, a, emp_id)


@router.get("/{emp_id}/leave/history")
def leave_history(emp_id: int, ctx: OrgContext = Ctx, db: Session = Db, a: Access = Acc):
    return L.history(db, ctx, a, emp_id)


@router.post("/{emp_id}/leave/adjust")
def leave_adjust(emp_id: int, body: dict = Body(...), ctx: OrgContext = Ctx, db: Session = Db, a: Access = Acc):
    L.adjust(db, ctx, a, emp_id, body.get("leave_type_id"), body.get("hours"), body.get("note", ""), body.get("type", "adjustment"))
    db.commit()
    return L.employee_balances(db, ctx, a, emp_id)
