"""Payroll -> general ledger. One balanced journal per finalised pay run, posted through the ledger's own post_journal (no second accounting engine).
The ledger line per account is the sum of employee-level lines kept in pay_journal_lines, so every ledger amount traces:
Company -> Pay Run -> Employee -> Payroll transaction (txn_ref)."""
from collections import defaultdict
from decimal import Decimal
from typing import Optional

import accfino.modules.accounting.public as accounting
from accfino.modules.payroll.models.payroll import PayItem, PayJournal, PayJournalLine, PayRun, PayRunEmployee, PayRunLine
from accfino.modules.payroll.services.errors import Conflict, NotFound, PayrollError
from accfino.modules.payroll.services.payslips import EARN
from accfino.modules.payroll.services.setup import get_settings

Z = Decimal(0)
REQUIRED = ("wages_expense", "super_expense", "reimbursement_expense", "wages_payable", "payg_payable", "super_payable", "deductions_payable")


def _map(db, ctx) -> dict:
    m = dict(get_settings(db, ctx.org).accounting_map or {})
    missing = [k for k in REQUIRED if not m.get(k)]
    if missing:
        raise PayrollError(f"Payroll accounting is not set up (missing: {', '.join(missing)}). Choose the ledger accounts in Payroll > Settings > Accounting.")
    valid = {a["id"] for a in accounting.ledger_accounts(db, ctx.org.id)}
    bad = [k for k in REQUIRED if m[k] not in valid]
    if bad:
        raise PayrollError(f"These payroll ledger accounts are missing or inactive: {', '.join(bad)}. Fix them in Payroll > Settings > Accounting.")
    return m


def employee_entries(db, ctx, run: PayRun, m: dict) -> list:
    """Employee-level journal entries (dicts) for the run. Debits and credits balance per employee."""
    items = {i.id: i for i in db.query(PayItem).filter_by(org_id=ctx.org.id)}
    out = []
    for re_ in db.query(PayRunEmployee).filter_by(run_id=run.id, status="included").order_by(PayRunEmployee.employee_number):
        base = dict(employee_id=re_.employee_id, run_employee_id=re_.id)
        who = f"{re_.employee_number} {re_.employee_name}"
        for l in db.query(PayRunLine).filter_by(run_employee_id=re_.id).order_by(PayRunLine.line_no):
            it = items.get(l.pay_item_id)
            acct = (it.expense_account_id if it and it.expense_account_id else None)
            if l.kind in EARN:
                a = acct or m["wages_expense"]
                out.append(dict(base, component="wages", account_id=a, pay_item_id=l.pay_item_id, txn_ref=l.txn_ref, debit=l.amount if l.amount > 0 else Z, credit=-l.amount if l.amount < 0 else Z, description=f"{l.name} - {who}"))
            elif l.kind == "reimbursement":
                out.append(dict(base, component="reimbursements", account_id=acct or m["reimbursement_expense"], pay_item_id=l.pay_item_id, txn_ref=l.txn_ref, debit=l.amount, credit=Z, description=f"{l.name} - {who}"))
            elif l.kind == "employer_super_additional":
                out.append(dict(base, component="super_expense", account_id=acct or m["super_expense"], pay_item_id=l.pay_item_id, txn_ref=l.txn_ref, debit=l.amount, credit=Z, description=f"{l.name} - {who}"))
                out.append(dict(base, component="super_payable", account_id=m["super_payable"], pay_item_id=l.pay_item_id, txn_ref=l.txn_ref, debit=Z, credit=l.amount, description=f"{l.name} - {who}"))
            elif l.kind in ("salary_sacrifice_super", "employee_super_after_tax"):
                out.append(dict(base, component="super_payable", account_id=m["super_payable"], pay_item_id=l.pay_item_id, txn_ref=l.txn_ref, debit=Z, credit=l.amount, description=f"{l.name} - {who}"))
            elif l.kind in ("deduction_pretax", "deduction_posttax"):
                out.append(dict(base, component="deductions", account_id=acct or m["deductions_payable"], pay_item_id=l.pay_item_id, txn_ref=l.txn_ref, debit=Z, credit=l.amount, description=f"{l.name} - {who}"))
        if re_.super_guarantee:
            out.append(dict(base, component="super_expense", account_id=m["super_expense"], txn_ref=f"{run.run_no}-{re_.employee_number}-SG", debit=re_.super_guarantee, credit=Z, description=f"Super guarantee - {who}"))
            out.append(dict(base, component="super_payable", account_id=m["super_payable"], txn_ref=f"{run.run_no}-{re_.employee_number}-SG", debit=Z, credit=re_.super_guarantee, description=f"Super guarantee - {who}"))
        if re_.payg + re_.study_loan:
            out.append(dict(base, component="payg", account_id=m["payg_payable"], txn_ref=f"{run.run_no}-{re_.employee_number}-TAX", debit=Z, credit=re_.payg + re_.study_loan, description=f"PAYG withheld - {who}"))
        if re_.net:
            out.append(dict(base, component="net_pay", account_id=m["wages_payable"], txn_ref=f"{run.run_no}-{re_.employee_number}-NET", debit=Z, credit=re_.net, description=f"Net pay - {who}"))
    return out


def post_run(db, ctx, run: PayRun) -> PayJournal:
    if db.query(PayJournal.id).filter_by(run_id=run.id).first():
        raise Conflict(f"A journal has already been posted for {run.run_no}", "already_posted")
    m = _map(db, ctx)
    entries = employee_entries(db, ctx, run, m)
    dr, cr = sum((e["debit"] for e in entries), Z), sum((e["credit"] for e in entries), Z)
    if dr != cr or dr == 0:
        raise PayrollError(f"Payroll journal for {run.run_no} does not balance (debits {dr}, credits {cr}); nothing was posted")
    by_acct = defaultdict(lambda: Z)
    for e in entries:
        by_acct[e["account_id"]] += e["debit"] - e["credit"]
    gl = [dict(account_id=a, debit=n if n > 0 else Z, credit=-n if n < 0 else Z, description=f"Payroll {run.run_no} {run.period_start.isoformat()} to {run.period_end.isoformat()}")
          for a, n in by_acct.items() if n != 0]
    try:
        j = accounting.post_journal(db, ctx.org, journal_date=run.pay_date, lines=gl, narration=f"Payroll {run.run_no}: {run.name or ''}"[:500], source_type="payroll",
                                    source_ref=f"payrun:{run.id}", created_by=ctx.user_id, reference=run.run_no)
    except accounting.LedgerError as e:
        raise PayrollError(f"The ledger refused the payroll journal: {e}")
    gl_dr, gl_cr = sum((l["debit"] for l in gl), Z), sum((l["credit"] for l in gl), Z)       # the LEDGER's totals (accounts are netted), so both records agree
    pj = PayJournal(org_id=ctx.org.id, run_id=run.id, ledger_journal_id=j.id, status="posted", total_debit=gl_dr, total_credit=gl_cr, posted_by=ctx.user_id)
    db.add(pj)
    db.flush()
    accts = {a["id"]: a for a in accounting.ledger_accounts(db, ctx.org.id, active_only=False)}
    for e in entries:
        a = accts.get(e["account_id"], {})
        db.add(PayJournalLine(org_id=ctx.org.id, pay_journal_id=pj.id, account_code=a.get("code"), account_name=a.get("name"), **e))
    db.flush()
    return pj


def reverse_run(db, ctx, orig: PayRun, rev: PayRun, reversal_date) -> PayJournal:
    pj = db.query(PayJournal).filter_by(run_id=orig.id).first()
    if pj is None:
        raise PayrollError(f"{orig.run_no} has no payroll journal to reverse")
    if pj.status == "reversed":
        raise Conflict("The payroll journal has already been reversed", "already_reversed")
    try:
        r = accounting.reverse_journal(db, ctx.org, pj.ledger_journal_id, reversal_date=reversal_date, narration=f"Reversal of payroll {orig.run_no} ({rev.run_no})", created_by=ctx.user_id)
    except accounting.LedgerError as e:
        raise PayrollError(f"The ledger refused to reverse the payroll journal: {e}")
    pj.status, pj.reversal_journal_id = "reversed", r.id
    rj = PayJournal(org_id=ctx.org.id, run_id=rev.id, ledger_journal_id=r.id, status="posted", total_debit=pj.total_credit, total_credit=pj.total_debit, posted_by=ctx.user_id)
    db.add(rj)
    db.flush()
    for l in db.query(PayJournalLine).filter_by(pay_journal_id=pj.id).all():
        db.add(PayJournalLine(org_id=ctx.org.id, pay_journal_id=rj.id, component=l.component, account_id=l.account_id, account_code=l.account_code, account_name=l.account_name,
                              employee_id=l.employee_id, run_employee_id=None, pay_item_id=l.pay_item_id, txn_ref=l.txn_ref, debit=l.credit, credit=l.debit,
                              description=f"Reversal: {l.description}"))
    db.flush()
    return rj


def get_journal(db, ctx, run_id: int) -> dict:
    run = db.query(PayRun).filter_by(id=run_id, org_id=ctx.org.id).first()
    if run is None:
        raise NotFound("Pay run")
    pj = db.query(PayJournal).filter_by(run_id=run.id).first()
    if pj is None:
        return {"run_id": run.id, "run_no": run.run_no, "posted": False, "message": "No journal yet: it is posted when the pay run is finalised"}
    lines = db.query(PayJournalLine).filter_by(pay_journal_id=pj.id).order_by(PayJournalLine.account_code, PayJournalLine.employee_id, PayJournalLine.id).all()
    net = defaultdict(lambda: [Z, "", ""])
    for l in lines:
        n = net[l.account_id]
        n[0] += l.debit - l.credit; n[1] = l.account_code; n[2] = l.account_name
    by_account = [{"account_id": a, "code": v[1], "name": v[2], "debit": str(v[0] if v[0] > 0 else Z), "credit": str(-v[0] if v[0] < 0 else Z)}
                  for a, v in sorted(net.items(), key=lambda kv: kv[1][1]) if v[0] != 0]
    ledger = accounting.journal_summary(db, ctx.org.id, pj.ledger_journal_id)
    return {"run_id": run.id, "run_no": run.run_no, "posted": True, "status": pj.status, "ledger_journal": ledger, "total_debit": str(pj.total_debit), "total_credit": str(pj.total_credit),
            "balanced": pj.total_debit == pj.total_credit,
            "by_account": by_account,
            "lines": [{"component": l.component, "account_code": l.account_code, "account_name": l.account_name, "employee_id": l.employee_id, "txn_ref": l.txn_ref,
                       "debit": str(l.debit), "credit": str(l.credit), "description": l.description} for l in lines]}
