"""Payslips: a frozen snapshot is generated from the finalised pay-run data (never recomputed), so a payslip always matches the pay run, payment and journal."""
import html as _html
from datetime import datetime
from decimal import Decimal
from typing import Optional

from accfino.modules.payroll.models.payroll import (PayEmployee, PayEmployeeBank, PayEmployeeSuper, PayLeaveType, PayPayslip, PayRun, PayRunEmployee, PayRunLine,
                                                    PaySuperFund)
from accfino.modules.payroll.services import audit, leave as leave_svc, protect
from accfino.modules.payroll.services.alloc import allocate_net
from accfino.modules.payroll.services.employees import display_name, full_name
from accfino.modules.payroll.services.errors import Forbidden, NotFound, PayrollError
from accfino.modules.payroll.services.setup import get_settings

Z = Decimal(0)
EARN = {"earnings", "overtime", "penalty", "allowance", "bonus", "commission", "back_pay", "leave", "leave_loading", "termination_leave", "etp", "salary_adjustment", "unpaid_leave"}
DEDUCT = {"deduction_pretax", "deduction_posttax", "salary_sacrifice_super", "employee_super_after_tax"}


def _s(v) -> str:
    return str(v if v is not None else 0)


def build_snapshot(db, ctx, run: PayRun, re_: PayRunEmployee, no: str) -> dict:
    org, e, st = ctx.org, db.get(PayEmployee, re_.employee_id), get_settings(db, ctx.org)
    lines = db.query(PayRunLine).filter_by(run_employee_id=re_.id).order_by(PayRunLine.line_no).all()
    earn = [{"name": l.name, "hours": _s(l.hours) if l.hours is not None else None, "rate": _s(l.rate) if l.rate is not None else None, "amount": _s(l.amount), "kind": l.kind}
            for l in lines if l.kind in EARN]
    ded = [{"name": l.name, "amount": _s(l.amount), "kind": l.kind} for l in lines if l.kind in DEDUCT]
    reimb = [{"name": l.name, "amount": _s(l.amount)} for l in lines if l.kind == "reimbursement"]
    funds = []
    memberships = {m.fund_id: m for m in db.query(PayEmployeeSuper).filter_by(employee_id=e.id, is_active=True)}
    from accfino.modules.payroll.models.payroll import PaySuperContribution
    for c in db.query(PaySuperContribution).filter_by(run_employee_id=re_.id).order_by(PaySuperContribution.id):
        f = db.get(PaySuperFund, c.fund_id)
        mem = memberships.get(c.fund_id)
        funds.append({"fund": f.name if f else "", "member_number": (("•••" + mem.member_number[-3:]) if mem and mem.member_number else None), "component": c.component,
                      "amount": _s(c.amount), "due_date": c.due_date.isoformat()})
    bank = []
    if re_.net > 0:
        banks = db.query(PayEmployeeBank).filter_by(employee_id=e.id, is_active=True).all()
        for b, a in allocate_net(banks, re_.net):
            bank.append({"account_name": b.account_name, "bsb": b.bsb, "account": protect.mask_account(b.account_last4), "amount": _s(a)})
    leave = []
    bal = leave_svc.balances(db, org.id, e.id)
    for lt in db.query(PayLeaveType).filter_by(org_id=org.id, is_active=True).order_by(PayLeaveType.code):
        accr = sum((Decimal(a["hours"]) for a in (re_.accruals or []) if a["leave_type_id"] == lt.id), Z)
        taken = sum((l.hours or Z for l in lines if l.leave_type_id == lt.id and l.kind in ("leave", "unpaid_leave")), Z)
        if lt.accrual_method != "none" or taken:
            leave.append({"name": lt.name, "accrued": _s(accr), "taken": _s(taken), "balance": _s(bal.get(lt.id, Z).quantize(Decimal("0.01")))})
    cfg = st.payslip_config or {}
    return {"payslip_no": no, "employer": {"name": st.employer_name or org.name, "abn": st.abn or org.abn}, "run": {"run_no": run.run_no, "type": run.run_type},
            "employee": {"id": e.id, "number": e.employee_number, "name": full_name(e), "position": e.position, "employment_type": e.employment_type,
                         "pay_basis": e.pay_basis, "annual_salary": _s(e.annual_salary) if e.pay_basis == "salary" else None,
                         "hourly_rate": _s(e.hourly_rate) if e.pay_basis == "hourly" else None},
            "period_start": run.period_start.isoformat(), "period_end": run.period_end.isoformat(), "pay_date": run.pay_date.isoformat(), "frequency": run.frequency,
            "earnings": earn, "deductions": ded, "reimbursements": reimb,
            "totals": {"gross": _s(re_.gross), "sacrifice_super": _s(re_.sacrifice_super), "pretax_deductions": _s(re_.pretax_deductions), "taxable": _s(re_.taxable),
                       "payg": _s(re_.payg), "study_loan": _s(re_.study_loan), "posttax_deductions": _s(re_.posttax_deductions), "reimbursements": _s(re_.reimbursements),
                       "net": _s(re_.net), "super_guarantee": _s(re_.super_guarantee), "super_total": _s(re_.super_total)},
            "hours": {"ordinary": _s(re_.ordinary_hours), "overtime": _s(re_.overtime_hours), "leave": _s(re_.leave_hours)},
            "super": funds, "payment": bank, "ytd": re_.ytd if cfg.get("show_ytd", True) else None, "leave": leave if cfg.get("show_leave", True) else [],
            "footer": cfg.get("footer", ""), "tax_scale": re_.tax_scale}


def generate_for_run(db, ctx, run: PayRun) -> int:
    n = 0
    for re_ in db.query(PayRunEmployee).filter_by(run_id=run.id, status="included").order_by(PayRunEmployee.employee_number):
        if db.query(PayPayslip.id).filter_by(run_employee_id=re_.id).first():
            raise PayrollError(f"A payslip already exists for {re_.employee_name} in {run.run_no}")
        no = f"{run.run_no}-{re_.employee_number}"
        snap = build_snapshot(db, ctx, run, re_, no)
        db.add(PayPayslip(org_id=ctx.org.id, run_id=run.id, run_employee_id=re_.id, employee_id=re_.employee_id, payslip_no=no, pay_date=run.pay_date, snapshot=snap,
                          generated_by=ctx.user_id))
        n += 1
    db.flush()
    audit.record(db, ctx, "payslip.generate", "pay_run", run.id, run.run_no, f"{n} payslips generated")
    return n


def _allowed(access, employee_id: int) -> bool:
    return access.has("sensitive_view") or (access.employee is not None and access.employee.id == employee_id)


def ser(p: PayPayslip, full: bool = False) -> dict:
    t = p.snapshot["totals"]
    out = {"id": p.id, "payslip_no": p.payslip_no, "run_id": p.run_id, "employee_id": p.employee_id, "employee": p.snapshot["employee"]["name"],
           "employee_number": p.snapshot["employee"]["number"], "pay_date": p.pay_date.isoformat(), "period_start": p.snapshot["period_start"],
           "period_end": p.snapshot["period_end"], "gross": t["gross"], "payg": t["payg"], "net": t["net"], "super": t["super_total"]}
    if full:
        out["snapshot"] = p.snapshot
    return out


def list_payslips(db, ctx, access, *, employee_id: int = 0, run_id: int = 0, mine: bool = False, limit: int = 200) -> list:
    q = db.query(PayPayslip).filter(PayPayslip.org_id == ctx.org.id)
    if mine or not access.has("sensitive_view"):
        if access.employee is None:
            raise Forbidden("You have no payslips: your login is not linked to an employee record")
        q = q.filter(PayPayslip.employee_id == access.employee.id)
    elif employee_id:
        q = q.filter(PayPayslip.employee_id == employee_id)
    if run_id:
        q = q.filter(PayPayslip.run_id == run_id)
    return [ser(p) for p in q.order_by(PayPayslip.pay_date.desc(), PayPayslip.id.desc()).limit(limit)]


def get_payslip(db, ctx, access, payslip_id: int) -> PayPayslip:
    p = db.query(PayPayslip).filter_by(id=payslip_id, org_id=ctx.org.id).first()
    if p is None or not _allowed(access, p.employee_id):
        raise NotFound("Payslip")                                       # same answer for "missing" and "not yours": never confirm another person's payslip exists
    return p


def render_html(p: PayPayslip) -> str:
    s = p.snapshot
    e = lambda v: _html.escape(str(v if v is not None else ""))
    money = lambda v: f"${Decimal(str(v or 0)):,.2f}"
    row = lambda *c: "<tr>" + "".join(f"<td{' class=r' if i else ''}>{e(x)}</td>" for i, x in enumerate(c)) + "</tr>"
    earn = "".join(row(x["name"] + (f" ({x['hours']} h)" if x.get("hours") else ""), money(x["amount"])) for x in s["earnings"])
    ded = "".join(row(x["name"], money(x["amount"])) for x in s["deductions"])
    t = s["totals"]
    ytd = s.get("ytd") or {}
    sup = "".join(row(f"{x['fund']} ({x['component'].replace('_', ' ')})", money(x["amount"])) for x in s["super"])
    pay = "".join(row(f"{x['account_name']} {x['bsb']} {x['account']}", money(x["amount"])) for x in s["payment"])
    lv = "".join(row(x["name"], f"{x['balance']} h") for x in s["leave"])
    return f"""<!doctype html><html><head><meta charset="utf-8"><title>Payslip {e(s['payslip_no'])}</title><style>
body{{font-family:Arial,Helvetica,sans-serif;color:#111;max-width:760px;margin:24px auto;padding:0 16px}}h1{{font-size:20px;margin:0}}h2{{font-size:13px;text-transform:uppercase;letter-spacing:.05em;
border-bottom:2px solid #0f766e;padding-bottom:3px;margin:18px 0 6px}}table{{width:100%;border-collapse:collapse;font-size:13px}}td{{padding:4px 6px;border-bottom:1px solid #e5e7eb}}td.r{{text-align:right}}
.head{{display:flex;justify-content:space-between}}.net{{font-size:16px;font-weight:700}}.small{{color:#555;font-size:12px}}@media print{{body{{margin:0}}}}</style></head><body>
<div class="head"><div><h1>Payslip</h1><div class="small">{e(s['employer']['name'])}{' · ABN ' + e(s['employer']['abn']) if s['employer'].get('abn') else ''}</div></div>
<div class="small" style="text-align:right">Payslip {e(s['payslip_no'])}<br>Pay date {e(s['pay_date'])}</div></div>
<div class="small" style="margin-top:8px"><b>{e(s['employee']['name'])}</b> · {e(s['employee']['number'])}{' · ' + e(s['employee']['position']) if s['employee'].get('position') else ''}<br>
Pay period {e(s['period_start'])} to {e(s['period_end'])} ({e(s['frequency'])})</div>
<h2>Earnings</h2><table>{earn}{row('Gross earnings', money(t['gross']))}</table>
<h2>Tax and deductions</h2><table>{row('PAYG withholding', money(t['payg']))}{row('Study and training loan', money(t['study_loan'])) if Decimal(str(t['study_loan'])) else ''}{ded}</table>
{('<h2>Reimbursements</h2><table>' + ''.join(row(x['name'], money(x['amount'])) for x in s['reimbursements']) + '</table>') if s['reimbursements'] else ''}
<h2>Net pay</h2><table>{row('Net pay', money(t['net']))}{pay}</table>
<h2>Superannuation (paid by employer)</h2><table>{sup or row('None this pay', '')}</table>
{('<h2>Year to date</h2><table>' + row('Gross', money(ytd.get('gross'))) + row('Tax withheld', money(ytd.get('tax'))) + row('Super', money(ytd.get('super_total'))) + '</table>') if ytd else ''}
{('<h2>Leave balances</h2><table>' + lv + '</table>') if lv else ''}
<p class="small" style="margin-top:18px">{e(s.get('footer'))}</p></body></html>"""
