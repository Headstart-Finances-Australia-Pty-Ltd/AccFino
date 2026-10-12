"""Public surface of the Payroll module: the ONLY import path other modules may use (read-only)."""
from decimal import Decimal


def withholding_for_period(db, org_id: int, date_from, date_to) -> dict:
    """Finalised pay-run totals by pay date: {runs, gross, taxable, payg, study_loan, withheld_total, super} (strings, cents)."""
    from sqlalchemy import func
    from accfino.modules.payroll.models.payroll import PayRun, PayRunEmployee
    q = db.query(func.count(func.distinct(PayRun.id)), func.coalesce(func.sum(PayRunEmployee.gross), 0), func.coalesce(func.sum(PayRunEmployee.taxable), 0),
                 func.coalesce(func.sum(PayRunEmployee.payg), 0), func.coalesce(func.sum(PayRunEmployee.study_loan), 0), func.coalesce(func.sum(PayRunEmployee.super_total), 0)) \
        .join(PayRun, PayRun.id == PayRunEmployee.run_id) \
        .filter(PayRun.org_id == org_id, PayRun.status.in_(("finalised", "paid")), PayRunEmployee.status == "included", PayRun.pay_date.between(date_from, date_to))
    runs, gross, taxable, payg, sl, sup = q.one()
    m = lambda v: str(Decimal(str(v)).quantize(Decimal("0.01")))
    return dict(runs=int(runs or 0), gross=m(gross), taxable=m(taxable), payg=m(payg), study_loan=m(sl), withheld_total=m(Decimal(str(payg)) + Decimal(str(sl))), super=m(sup))


def has_employees(db, org_id: int) -> bool:
    from accfino.modules.payroll.models.payroll import PayEmployee
    return db.query(PayEmployee.id).filter(PayEmployee.org_id == org_id, PayEmployee.status == "active").first() is not None


def employee_names(db, org_id: int):
    """[{id, name}] of active employees (for picking the employee on an FBT benefit)."""
    from accfino.modules.payroll.models.payroll import PayEmployee
    return [dict(id=e.id, name=f"{e.first_name} {e.last_name}".strip()) for e in
            db.query(PayEmployee).filter(PayEmployee.org_id == org_id, PayEmployee.status == "active").order_by(PayEmployee.last_name, PayEmployee.first_name)]
