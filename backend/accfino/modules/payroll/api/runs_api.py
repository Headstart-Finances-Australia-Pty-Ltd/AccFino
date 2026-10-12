from typing import Optional

from fastapi import APIRouter, Body, Depends
from sqlalchemy.orm import Session

from accfino.core.security.context import OrgContext, current_org
from accfino.modules.payroll.access import Access
from accfino.modules.payroll.api.deps import access, parse_date
from accfino.modules.payroll.services import journals, payruns as R
from accfino.shared.db.database import get_db

router = APIRouter(prefix="/runs")
Ctx, Db, Acc = Depends(current_org), Depends(get_db), Depends(access)


def _detail(db, ctx, a, run_id):
    return R.run_detail(db, ctx, a, run_id)


@router.get("")
def listing(status: str = "", ctx: OrgContext = Ctx, db: Session = Db, a: Access = Acc):
    return R.list_runs(db, ctx, a, status=status)


@router.post("")
def create(body: dict = Body(...), ctx: OrgContext = Ctx, db: Session = Db, a: Access = Acc):
    r = R.create_run(db, ctx, a, body)
    db.commit()
    return _detail(db, ctx, a, r.id)


@router.get("/{run_id}")
def get(run_id: int, ctx: OrgContext = Ctx, db: Session = Db, a: Access = Acc):
    return _detail(db, ctx, a, run_id)


def _action(name, fn):
    @router.post(f"/{{run_id}}/{name}", name=f"run_{name}")
    def endpoint(run_id: int, ctx: OrgContext = Ctx, db: Session = Db, a: Access = Acc):
        fn(db, ctx, a, run_id)
        db.commit()
        return _detail(db, ctx, a, run_id)


_action("calculate", R.calculate)
_action("approve", R.approve)
_action("unapprove", R.return_to_review)
_action("finalise", R.finalise)


@router.post("/{run_id}/void")
def void(run_id: int, body: dict = Body(...), ctx: OrgContext = Ctx, db: Session = Db, a: Access = Acc):
    R.void(db, ctx, a, run_id, body.get("reason", ""))
    db.commit()
    return _detail(db, ctx, a, run_id)


@router.post("/{run_id}/reverse")
def reverse(run_id: int, body: dict = Body(...), ctx: OrgContext = Ctx, db: Session = Db, a: Access = Acc):
    rev = R.reverse(db, ctx, a, run_id, body.get("reason", ""), parse_date(body.get("reversal_date"), "reversal_date"))
    db.commit()
    return _detail(db, ctx, a, rev.id)


@router.post("/{run_id}/employees/{employee_id}/include")
def include(run_id: int, employee_id: int, ctx: OrgContext = Ctx, db: Session = Db, a: Access = Acc):
    R.set_included(db, ctx, a, run_id, employee_id, True)
    db.commit()
    return _detail(db, ctx, a, run_id)


@router.post("/{run_id}/employees/{employee_id}/exclude")
def exclude(run_id: int, employee_id: int, body: dict = Body(...), ctx: OrgContext = Ctx, db: Session = Db, a: Access = Acc):
    R.set_included(db, ctx, a, run_id, employee_id, False, body.get("reason", ""))
    db.commit()
    return _detail(db, ctx, a, run_id)


@router.post("/{run_id}/inputs")
def add_input(run_id: int, body: dict = Body(...), ctx: OrgContext = Ctx, db: Session = Db, a: Access = Acc):
    R.add_input(db, ctx, a, run_id, body)
    db.commit()
    return _detail(db, ctx, a, run_id)


@router.delete("/{run_id}/inputs/{input_id}")
def remove_input(run_id: int, input_id: int, ctx: OrgContext = Ctx, db: Session = Db, a: Access = Acc):
    R.remove_input(db, ctx, a, run_id, input_id)
    db.commit()
    return _detail(db, ctx, a, run_id)


@router.get("/{run_id}/journal")
def journal(run_id: int, ctx: OrgContext = Ctx, db: Session = Db, a: Access = Acc):
    a.require("journal_view")
    return journals.get_journal(db, ctx, run_id)


@router.get("/{run_id}/integrity")
def integrity(run_id: int, ctx: OrgContext = Ctx, db: Session = Db, a: Access = Acc):
    return R.verify_integrity(db, ctx, a, run_id)
