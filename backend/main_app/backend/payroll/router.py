"""
Payroll module for AccFino — integrated into the main react_api.py FastAPI app.
All payroll data is stored in AccFino's existing PostgreSQL database using the
same SQLAlchemy engine. Routes are mounted at /payroll/*.

Covers: Employees · Timesheets · Payroll Runs · Payslips · STP/Compliance · Reports
"""
import uuid, logging
from datetime import datetime
from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import Column, String, Float, Boolean, DateTime, Text, Integer, JSON
from sqlalchemy.orm import Session

from db_app.database import SessionLocal, engine
from db_app.models.base import Base
from main_app.backend.payroll.tax_engine import PayrollInput, calculate_payroll

logger = logging.getLogger("accfino")
router = APIRouter()

# ── DB Models (created via migration, not here directly) ──────────────────────

class PayrollEmployeeDB(Base):
    __tablename__ = "payroll_employees"
    id                  = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id             = Column(Integer, nullable=True)   # links to accfino users.id
    employee_number     = Column(String, unique=True, nullable=False)
    first_name          = Column(String, nullable=False)
    last_name           = Column(String, nullable=False)
    email               = Column(String, nullable=False)
    phone               = Column(String)
    tfn                 = Column(String)
    employment_type     = Column(String, nullable=False)   # full_time, part_time, casual, contract
    pay_frequency       = Column(String, default="fortnightly")
    annual_salary       = Column(Float, nullable=False)
    hourly_rate         = Column(Float)
    super_fund_name     = Column(String, default="AustralianSuper")
    super_fund_usi      = Column(String)
    super_member_number = Column(String)
    bank_bsb            = Column(String)
    bank_account_number = Column(String)
    bank_account_name   = Column(String)
    start_date          = Column(String, nullable=False)
    end_date            = Column(String)
    is_active           = Column(Boolean, default=True)
    tax_free_threshold  = Column(Boolean, default=True)
    residency_status    = Column(String, default="resident")
    address_line1       = Column(String)
    address_suburb      = Column(String)
    address_state       = Column(String)
    address_postcode    = Column(String)
    created_at          = Column(DateTime, default=datetime.utcnow)
    updated_at          = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class PayrollTimesheetDB(Base):
    __tablename__ = "payroll_timesheets"
    id                       = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    employee_id              = Column(String, nullable=False)
    period_start             = Column(String, nullable=False)
    period_end               = Column(String, nullable=False)
    ordinary_hours           = Column(Float, default=0)
    overtime_hours_1_5x      = Column(Float, default=0)
    overtime_hours_2x        = Column(Float, default=0)
    public_holiday_hours     = Column(Float, default=0)
    annual_leave_hours       = Column(Float, default=0)
    sick_leave_hours         = Column(Float, default=0)
    long_service_leave_hours = Column(Float, default=0)
    unpaid_leave_hours       = Column(Float, default=0)
    notes                    = Column(String)
    status                   = Column(String, default="draft")
    submitted_at             = Column(DateTime)
    approved_at              = Column(DateTime)
    approved_by              = Column(String)
    created_at               = Column(DateTime, default=datetime.utcnow)
    updated_at               = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class PayrollRunDB(Base):
    __tablename__ = "payroll_runs"
    id             = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id        = Column(Integer, nullable=True)
    run_name       = Column(String, nullable=False)
    pay_frequency  = Column(String)
    period_start   = Column(String, nullable=False)
    period_end     = Column(String, nullable=False)
    pay_date       = Column(String)
    status         = Column(String, default="pending")
    total_gross    = Column(Float, default=0)
    total_tax      = Column(Float, default=0)
    total_net      = Column(Float, default=0)
    total_super    = Column(Float, default=0)
    employee_count = Column(Float, default=0)
    notes          = Column(Text)
    created_by     = Column(String)
    created_at     = Column(DateTime, default=datetime.utcnow)
    completed_at   = Column(DateTime)


class PayslipDB(Base):
    __tablename__ = "payslips"
    id                       = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    payroll_run_id           = Column(String, nullable=False)
    employee_id              = Column(String, nullable=False)
    employee_number          = Column(String)
    full_name                = Column(String)
    period_start             = Column(String)
    period_end               = Column(String)
    pay_date                 = Column(String)
    pay_frequency            = Column(String)
    ordinary_hours           = Column(Float, default=0)
    overtime_hours_1_5x      = Column(Float, default=0)
    overtime_hours_2x        = Column(Float, default=0)
    annual_leave_hours       = Column(Float, default=0)
    sick_leave_hours         = Column(Float, default=0)
    ordinary_pay             = Column(Float, default=0)
    overtime_pay_1_5x        = Column(Float, default=0)
    overtime_pay_2x          = Column(Float, default=0)
    annual_leave_pay         = Column(Float, default=0)
    sick_leave_pay           = Column(Float, default=0)
    gross_earnings           = Column(Float, default=0)
    payg_tax                 = Column(Float, default=0)
    medicare_levy            = Column(Float, default=0)
    total_tax                = Column(Float, default=0)
    net_pay                  = Column(Float, default=0)
    super_guarantee          = Column(Float, default=0)
    super_fund_name          = Column(String)
    super_member_number      = Column(String)
    ytd_gross                = Column(Float, default=0)
    ytd_tax                  = Column(Float, default=0)
    ytd_super                = Column(Float, default=0)
    hourly_rate              = Column(Float)
    annual_salary            = Column(Float)
    created_at               = Column(DateTime, default=datetime.utcnow)


class STPSubmissionDB(Base):
    __tablename__ = "stp_submissions"
    id               = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    payroll_run_id   = Column(String)
    abn              = Column(String)
    submission_date  = Column(String)
    period_start     = Column(String)
    period_end       = Column(String)
    employee_count   = Column(Float, default=0)
    total_gross      = Column(Float, default=0)
    total_tax        = Column(Float, default=0)
    total_super      = Column(Float, default=0)
    payload_json     = Column(Text)
    status           = Column(String, default="draft")
    ato_reference    = Column(String)
    submitted_by     = Column(String)
    submitted_at     = Column(DateTime)
    created_at       = Column(DateTime, default=datetime.utcnow)


# ── DB Session helper ─────────────────────────────────────────────────────────

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


# ── Pydantic schemas ──────────────────────────────────────────────────────────

class EmployeeCreate(BaseModel):
    user_id: Optional[int] = None
    employee_number: str
    first_name: str
    last_name: str
    email: str
    phone: Optional[str] = None
    tfn: Optional[str] = None
    employment_type: str = "full_time"
    pay_frequency: str = "fortnightly"
    annual_salary: float
    hourly_rate: Optional[float] = None
    super_fund_name: Optional[str] = "AustralianSuper"
    super_fund_usi: Optional[str] = None
    super_member_number: Optional[str] = None
    bank_bsb: Optional[str] = None
    bank_account_number: Optional[str] = None
    bank_account_name: Optional[str] = None
    start_date: str
    tax_free_threshold: bool = True
    residency_status: str = "resident"
    address_line1: Optional[str] = None
    address_suburb: Optional[str] = None
    address_state: Optional[str] = None
    address_postcode: Optional[str] = None


class TimesheetCreate(BaseModel):
    employee_id: str
    period_start: str
    period_end: str
    ordinary_hours: float = 0
    overtime_hours_1_5x: float = 0
    overtime_hours_2x: float = 0
    public_holiday_hours: float = 0
    annual_leave_hours: float = 0
    sick_leave_hours: float = 0
    long_service_leave_hours: float = 0
    unpaid_leave_hours: float = 0
    notes: Optional[str] = None


class PayrollRunCreate(BaseModel):
    user_id: Optional[int] = None
    run_name: str
    pay_frequency: str = "fortnightly"
    period_start: str
    period_end: str
    pay_date: Optional[str] = None
    notes: Optional[str] = None


class STPCreate(BaseModel):
    payroll_run_id: str
    abn: str


# ── Helper ────────────────────────────────────────────────────────────────────

def _emp_dict(e: PayrollEmployeeDB) -> dict:
    return {k: getattr(e, k) for k in [
        "id","user_id","employee_number","first_name","last_name","email","phone",
        "employment_type","pay_frequency","annual_salary","hourly_rate",
        "super_fund_name","super_member_number","bank_bsb","bank_account_number",
        "bank_account_name","start_date","end_date","is_active","tax_free_threshold",
        "residency_status","address_line1","address_suburb","address_state","address_postcode",
    ]}


def _ts_dict(t: PayrollTimesheetDB) -> dict:
    return {k: getattr(t, k) for k in [
        "id","employee_id","period_start","period_end","ordinary_hours",
        "overtime_hours_1_5x","overtime_hours_2x","public_holiday_hours",
        "annual_leave_hours","sick_leave_hours","long_service_leave_hours",
        "unpaid_leave_hours","notes","status",
    ]}


def _run_dict(r: PayrollRunDB) -> dict:
    return {k: getattr(r, k) for k in [
        "id","user_id","run_name","pay_frequency","period_start","period_end",
        "pay_date","status","total_gross","total_tax","total_net","total_super",
        "employee_count","notes",
        "created_at",
    ] if hasattr(r, k)}


def _ps_dict(p: PayslipDB) -> dict:
    return {k: getattr(p, k) for k in [
        "id","payroll_run_id","employee_id","employee_number","full_name",
        "period_start","period_end","pay_date","pay_frequency",
        "ordinary_hours","overtime_hours_1_5x","overtime_hours_2x",
        "annual_leave_hours","sick_leave_hours",
        "ordinary_pay","overtime_pay_1_5x","overtime_pay_2x",
        "annual_leave_pay","sick_leave_pay","gross_earnings",
        "payg_tax","medicare_levy","total_tax","net_pay",
        "super_guarantee","super_fund_name","super_member_number",
        "ytd_gross","ytd_tax","ytd_super","hourly_rate","annual_salary",
    ]}


# ── Employee endpoints ────────────────────────────────────────────────────────

@router.get("/employees")
def list_employees(user_id: Optional[int] = None, db: Session = Depends(get_db)):
    q = db.query(PayrollEmployeeDB)
    if user_id:
        q = q.filter(PayrollEmployeeDB.user_id == user_id)
    return [_emp_dict(e) for e in q.filter(PayrollEmployeeDB.is_active == True).order_by(PayrollEmployeeDB.last_name).all()]


@router.post("/employees")
def create_employee(body: EmployeeCreate, db: Session = Depends(get_db)):
    # Auto-generate employee number if not unique
    if db.query(PayrollEmployeeDB).filter(PayrollEmployeeDB.employee_number == body.employee_number).first():
        raise HTTPException(400, f"Employee number {body.employee_number} already exists")
    emp = PayrollEmployeeDB(**body.dict())
    db.add(emp); db.commit(); db.refresh(emp)
    return _emp_dict(emp)


@router.get("/employees/{emp_id}")
def get_employee(emp_id: str, db: Session = Depends(get_db)):
    e = db.query(PayrollEmployeeDB).filter(PayrollEmployeeDB.id == emp_id).first()
    if not e: raise HTTPException(404, "Employee not found")
    return _emp_dict(e)


@router.patch("/employees/{emp_id}")
def patch_employee(emp_id: str, body: dict, db: Session = Depends(get_db)):
    e = db.query(PayrollEmployeeDB).filter(PayrollEmployeeDB.id == emp_id).first()
    if not e: raise HTTPException(404, "Employee not found")
    for k, v in body.items():
        if hasattr(e, k): setattr(e, k, v)
    e.updated_at = datetime.utcnow()
    db.commit(); db.refresh(e)
    return _emp_dict(e)


@router.delete("/employees/{emp_id}")
def deactivate_employee(emp_id: str, db: Session = Depends(get_db)):
    e = db.query(PayrollEmployeeDB).filter(PayrollEmployeeDB.id == emp_id).first()
    if not e: raise HTTPException(404, "Employee not found")
    e.is_active = False; e.end_date = datetime.utcnow().strftime("%Y-%m-%d")
    db.commit()
    return {"ok": True}


# ── Timesheet endpoints ───────────────────────────────────────────────────────

@router.get("/timesheets")
def list_timesheets(employee_id: Optional[str] = None, db: Session = Depends(get_db)):
    q = db.query(PayrollTimesheetDB)
    if employee_id:
        q = q.filter(PayrollTimesheetDB.employee_id == employee_id)
    return [_ts_dict(t) for t in q.order_by(PayrollTimesheetDB.period_start.desc()).all()]


@router.post("/timesheets")
def create_timesheet(body: TimesheetCreate, db: Session = Depends(get_db)):
    ts = PayrollTimesheetDB(**body.dict())
    db.add(ts); db.commit(); db.refresh(ts)
    return _ts_dict(ts)


@router.patch("/timesheets/{ts_id}")
def patch_timesheet(ts_id: str, body: dict, db: Session = Depends(get_db)):
    ts = db.query(PayrollTimesheetDB).filter(PayrollTimesheetDB.id == ts_id).first()
    if not ts: raise HTTPException(404, "Timesheet not found")
    for k, v in body.items():
        if hasattr(ts, k): setattr(ts, k, v)
    if body.get("status") == "submitted":
        ts.submitted_at = datetime.utcnow()
    elif body.get("status") == "approved":
        ts.approved_at = datetime.utcnow()
    ts.updated_at = datetime.utcnow()
    db.commit(); db.refresh(ts)
    return _ts_dict(ts)


# ── Payroll run endpoints ─────────────────────────────────────────────────────

@router.get("/payroll-runs")
def list_runs(user_id: Optional[int] = None, db: Session = Depends(get_db)):
    q = db.query(PayrollRunDB)
    if user_id:
        q = q.filter(PayrollRunDB.user_id == user_id)
    return [_run_dict(r) for r in q.order_by(PayrollRunDB.created_at.desc()).all()]


@router.post("/payroll-runs")
def create_run(body: PayrollRunCreate, db: Session = Depends(get_db)):
    run = PayrollRunDB(**body.dict())
    db.add(run); db.commit(); db.refresh(run)
    return _run_dict(run)


@router.get("/payroll-runs/{run_id}")
def get_run(run_id: str, db: Session = Depends(get_db)):
    run = db.query(PayrollRunDB).filter(PayrollRunDB.id == run_id).first()
    if not run: raise HTTPException(404, "Run not found")
    payslips = db.query(PayslipDB).filter(PayslipDB.payroll_run_id == run_id).all()
    return {"run": _run_dict(run), "payslips": [_ps_dict(p) for p in payslips]}


@router.post("/payroll-runs/{run_id}/process")
def process_run(run_id: str, db: Session = Depends(get_db)):
    """
    Process a payroll run: for each active employee, find their approved timesheet
    for the run period, run the tax engine, and create payslips.
    """
    run = db.query(PayrollRunDB).filter(PayrollRunDB.id == run_id).first()
    if not run: raise HTTPException(404, "Run not found")
    if run.status == "completed":
        raise HTTPException(400, "Run already completed")

    run.status = "processing"; db.commit()

    try:
        # Get all active employees
        employees = db.query(PayrollEmployeeDB).filter(
            PayrollEmployeeDB.is_active == True,
            PayrollEmployeeDB.user_id == run.user_id if run.user_id else True,
        ).all()

        if not employees:
            run.status = "failed"; run.notes = "No active employees found"; db.commit()
            raise HTTPException(400, "No active employees")

        total_gross = total_tax = total_net = total_super = 0
        payslip_count = 0

        for emp in employees:
            # Find approved timesheet for this period
            ts = db.query(PayrollTimesheetDB).filter(
                PayrollTimesheetDB.employee_id == emp.id,
                PayrollTimesheetDB.period_start == run.period_start,
                PayrollTimesheetDB.status.in_(["approved", "submitted"]),
            ).first()

            if not ts:
                # Use standard hours based on pay frequency if no timesheet
                hrs = {"weekly": 38, "fortnightly": 76, "monthly": 165}.get(emp.pay_frequency, 76)
                ordinary_hours = hrs
                ts_data = {}
            else:
                ordinary_hours = ts.ordinary_hours
                ts_data = _ts_dict(ts)

            # Get YTD from previous payslips this financial year
            fy_start = f"{datetime.utcnow().year}-07-01" if datetime.utcnow().month >= 7 else f"{datetime.utcnow().year-1}-07-01"
            prev = db.query(PayslipDB).filter(
                PayslipDB.employee_id == emp.id,
                PayslipDB.period_start >= fy_start,
            ).all()
            ytd_gross = sum(p.gross_earnings for p in prev)
            ytd_tax   = sum(p.total_tax for p in prev)
            ytd_super  = sum(p.super_guarantee for p in prev)

            inp = PayrollInput(
                employee_id=emp.id,
                employee_number=emp.employee_number,
                first_name=emp.first_name,
                last_name=emp.last_name,
                annual_salary=emp.annual_salary,
                employment_type=emp.employment_type,
                pay_frequency=emp.pay_frequency,
                ordinary_hours=ordinary_hours,
                overtime_hours_1_5x=float(ts_data.get("overtime_hours_1_5x", 0)),
                overtime_hours_2x=float(ts_data.get("overtime_hours_2x", 0)),
                annual_leave_hours=float(ts_data.get("annual_leave_hours", 0)),
                sick_leave_hours=float(ts_data.get("sick_leave_hours", 0)),
                hourly_rate=emp.hourly_rate,
                tax_free_threshold=emp.tax_free_threshold,
                residency_status=emp.residency_status,
                super_fund_name=emp.super_fund_name or "AustralianSuper",
                super_member_number=emp.super_member_number,
                ytd_gross=ytd_gross, ytd_tax=ytd_tax, ytd_super=ytd_super,
                period_start=run.period_start, period_end=run.period_end,
            )

            result = calculate_payroll(inp)

            ps = PayslipDB(
                payroll_run_id=run_id,
                employee_id=emp.id,
                employee_number=emp.employee_number,
                full_name=result.full_name,
                period_start=run.period_start,
                period_end=run.period_end,
                pay_date=run.pay_date,
                pay_frequency=emp.pay_frequency,
                ordinary_hours=result.ordinary_hours,
                overtime_hours_1_5x=result.overtime_hours_1_5x,
                overtime_hours_2x=result.overtime_hours_2x,
                annual_leave_hours=result.annual_leave_hours,
                sick_leave_hours=result.sick_leave_hours,
                ordinary_pay=result.ordinary_pay,
                overtime_pay_1_5x=result.overtime_pay_1_5x,
                overtime_pay_2x=result.overtime_pay_2x,
                annual_leave_pay=result.annual_leave_pay,
                sick_leave_pay=result.sick_leave_pay,
                gross_earnings=result.gross_earnings,
                payg_tax=result.payg_tax,
                medicare_levy=result.medicare_levy,
                total_tax=result.total_tax,
                net_pay=result.net_pay,
                super_guarantee=result.super_guarantee,
                super_fund_name=result.super_fund_name,
                super_member_number=result.super_member_number,
                ytd_gross=result.ytd_gross,
                ytd_tax=result.ytd_tax,
                ytd_super=result.ytd_super,
                hourly_rate=result.hourly_rate,
                annual_salary=emp.annual_salary,
            )
            db.add(ps)
            total_gross += result.gross_earnings
            total_tax   += result.total_tax
            total_net   += result.net_pay
            total_super  += result.super_guarantee
            payslip_count += 1

        run.status         = "completed"
        run.total_gross    = round(total_gross, 2)
        run.total_tax      = round(total_tax, 2)
        run.total_net      = round(total_net, 2)
        run.total_super    = round(total_super, 2)
        run.employee_count = payslip_count
        run.completed_at   = datetime.utcnow()
        db.commit()

        return {
            "ok": True,
            "run_id": run_id,
            "employee_count": payslip_count,
            "total_gross": round(total_gross, 2),
            "total_tax":   round(total_tax, 2),
            "total_net":   round(total_net, 2),
            "total_super": round(total_super, 2),
        }

    except HTTPException:
        raise
    except Exception as e:
        run.status = "failed"; run.notes = str(e); db.commit()
        logger.error(f"Payroll run {run_id} failed: {e}", exc_info=True)
        raise HTTPException(500, f"Payroll processing failed: {e}")


# ── Payslip endpoints ─────────────────────────────────────────────────────────

@router.get("/payslips")
def list_payslips(employee_id: Optional[str] = None, payroll_run_id: Optional[str] = None,
                  db: Session = Depends(get_db)):
    q = db.query(PayslipDB)
    if employee_id:     q = q.filter(PayslipDB.employee_id == employee_id)
    if payroll_run_id:  q = q.filter(PayslipDB.payroll_run_id == payroll_run_id)
    return [_ps_dict(p) for p in q.order_by(PayslipDB.created_at.desc()).all()]


# ── STP Compliance ────────────────────────────────────────────────────────────

@router.post("/stp/prepare")
def stp_prepare(body: STPCreate, submitted_by: Optional[str] = None, db: Session = Depends(get_db)):
    run = db.query(PayrollRunDB).filter(PayrollRunDB.id == body.payroll_run_id).first()
    if not run: raise HTTPException(404, "Payroll run not found")
    payslips = db.query(PayslipDB).filter(PayslipDB.payroll_run_id == body.payroll_run_id).all()

    # Build STP Phase 2 payload (simplified)
    payload = {
        "submissionType": "PAY_EVENT",
        "abn": body.abn,
        "softwareId": "AccFino-STP-001",
        "payrollPeriod": {"start": run.period_start, "end": run.period_end},
        "employees": [
            {
                "employeeId":  p.employee_id,
                "fullName":    p.full_name,
                "grossEarnings": p.gross_earnings,
                "paygTax":     p.payg_tax,
                "superGuarantee": p.super_guarantee,
                "ytdGross":    p.ytd_gross,
                "ytdTax":      p.ytd_tax,
                "ytdSuper":    p.ytd_super,
            }
            for p in payslips
        ],
        "totals": {
            "gross": run.total_gross, "tax": run.total_tax, "super": run.total_super,
        },
    }

    import json
    stp = STPSubmissionDB(
        payroll_run_id  = body.payroll_run_id,
        abn             = body.abn,
        submission_date = datetime.utcnow().strftime("%Y-%m-%d"),
        period_start    = run.period_start,
        period_end      = run.period_end,
        employee_count  = len(payslips),
        total_gross     = run.total_gross,
        total_tax       = run.total_tax,
        total_super     = run.total_super,
        payload_json    = json.dumps(payload),
        status          = "validated",
        submitted_by    = submitted_by or "system",
    )
    db.add(stp); db.commit(); db.refresh(stp)
    return {"id": stp.id, "status": "validated", "payload": payload}


@router.post("/stp/submit/{stp_id}")
def stp_submit(stp_id: str, db: Session = Depends(get_db)):
    stp = db.query(STPSubmissionDB).filter(STPSubmissionDB.id == stp_id).first()
    if not stp: raise HTTPException(404, "STP submission not found")
    # Simulate ATO submission
    stp.status        = "submitted"
    stp.submitted_at  = datetime.utcnow()
    stp.ato_reference = f"ATO-{datetime.utcnow().strftime('%Y%m%d')}-{str(uuid.uuid4())[:8].upper()}"
    db.commit()
    return {"ok": True, "ato_reference": stp.ato_reference, "status": "submitted"}


@router.get("/stp/submissions")
def list_stp(db: Session = Depends(get_db)):
    rows = db.query(STPSubmissionDB).order_by(STPSubmissionDB.created_at.desc()).all()
    return [{"id": s.id, "payroll_run_id": s.payroll_run_id, "abn": s.abn,
             "period_start": s.period_start, "period_end": s.period_end,
             "employee_count": s.employee_count, "total_gross": s.total_gross,
             "status": s.status, "ato_reference": s.ato_reference,
             "submitted_at": s.submitted_at} for s in rows]


# ── Stats ─────────────────────────────────────────────────────────────────────

@router.get("/stats")
def payroll_stats(user_id: Optional[int] = None, db: Session = Depends(get_db)):
    q = db.query(PayrollEmployeeDB)
    if user_id: q = q.filter(PayrollEmployeeDB.user_id == user_id)
    total_employees = q.filter(PayrollEmployeeDB.is_active == True).count()

    rq = db.query(PayrollRunDB)
    if user_id: rq = rq.filter(PayrollRunDB.user_id == user_id)
    runs = rq.order_by(PayrollRunDB.created_at.desc()).limit(12).all()
    total_payroll = sum(r.total_gross for r in runs)
    last_run = runs[0] if runs else None

    return {
        "total_employees": total_employees,
        "total_runs": len(runs),
        "total_payroll_ytd": round(total_payroll, 2),
        "last_run": _run_dict(last_run) if last_run else None,
    }
