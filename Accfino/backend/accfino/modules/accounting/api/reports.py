"""
db_app/api/reports.py
-----------------------------------------------------------------------------
Real financial reports computed from actual user data -- replaces the
hardcoded demo numbers that used to live in
frontend/src/modules/accounting/pages/FinancialReports.jsx (PL, BS, AR, AP
constants with invented company names like "Acme Corporation").

Data sources:
  - transactions table (gl_account, debit, credit) -- posted/reconciled txns
  - chart_of_accounts table (name -> type: Revenue, Direct Costs, Expense,
    Fixed Asset, Inventory, Equity, GST)
  - account_balances table -- real per-account bank balances
  - invoices table -- real customer invoices with due_date/status for aging

Honesty note: this Chart of Accounts doesn't distinguish "Bank" or
"Current Liability" as their own types (see chart_of_accounts.type values),
so the Balance Sheet below is built only from sections that map onto real,
existing COA types -- it does not invent categories the data can't support.
There is also no bills/purchases model in this app at all, so Aged Payables
has no real data source; that endpoint returns an explicit "not available"
response rather than fabricating supplier data.
"""
from datetime import datetime, timezone
from fastapi import APIRouter, HTTPException
from sqlalchemy import text

from accfino.shared.db.database import SessionLocal

router = APIRouter()


def _sum_by_account(db, user_id: int, coa_type: str):
    """Net movement (credit - debit) per GL account, for accounts of a
    given chart_of_accounts.type, for one user's posted transactions."""
    rows = db.execute(text("""
        SELECT t.gl_account AS account, SUM(t.credit - t.debit) AS amount
        FROM transactions t
        JOIN chart_of_accounts c ON c.name = t.gl_account
        WHERE t.user_id = :uid AND c.type = :ctype AND t.gl_account IS NOT NULL
        GROUP BY t.gl_account
        HAVING SUM(t.credit - t.debit) != 0
        ORDER BY t.gl_account
    """), {"uid": user_id, "ctype": coa_type}).fetchall()
    return [{"account": r.account, "amount": round(float(r.amount), 2)} for r in rows]


@router.get("/profit-loss/{user_id}")
def profit_loss(user_id: int):
    """Real P&L from posted transactions, grouped by COA type.
    Income = Revenue-type accounts, Cost of Sales = Direct Costs, Expenses = Expense.
    No 'Other Income' section -- this COA has no type for that, so it's
    left out rather than invented."""
    db = SessionLocal()
    try:
        income = _sum_by_account(db, user_id, "Revenue")
        cost_of_sales = _sum_by_account(db, user_id, "Direct Costs")
        expenses = _sum_by_account(db, user_id, "Expense")
        has_data = bool(income or cost_of_sales or expenses)
        return {
            "income": income,
            "cost_of_sales": cost_of_sales,
            "expenses": expenses,
            "has_data": has_data,
        }
    finally:
        db.close()


@router.get("/balance-sheet/{user_id}")
def balance_sheet(user_id: int):
    """Real Balance Sheet, built only from sections this COA can actually
    support: Bank (from account_balances -- real per-account balances),
    Inventory (real COA type, shown as the Current Assets section),
    Fixed Assets (real COA type), Equity (real COA type). There is no
    'Current Liability' or 'Accounts Payable' type in this COA, so those
    sections are omitted rather than shown with invented numbers."""
    db = SessionLocal()
    try:
        bank_rows = db.execute(text("""
            SELECT bank, account, balance, year, month
            FROM account_balances
            WHERE user_id = :uid
            ORDER BY bank, account, year DESC, month DESC
        """), {"uid": user_id}).fetchall()
        latest_bank = {}
        for r in bank_rows:
            key = (r.bank, r.account)
            if key not in latest_bank:  # first row per key = most recent, due to ORDER BY above
                latest_bank[key] = r.balance
        bank = [{"account": f"{b} - {a}", "amount": round(float(v), 2)} for (b, a), v in latest_bank.items()]

        current_assets = _sum_by_account(db, user_id, "Inventory")
        fixed_assets = _sum_by_account(db, user_id, "Fixed Asset")
        equity = _sum_by_account(db, user_id, "Equity")

        has_data = bool(bank or current_assets or fixed_assets or equity)
        return {
            "bank": bank,
            "current_assets": current_assets,
            "fixed_assets": fixed_assets,
            "equity": equity,
            "has_data": has_data,
            "note": "Current Liabilities are not shown -- this Chart of Accounts has no Accounts Payable / Current Liability account type yet.",
        }
    finally:
        db.close()


@router.get("/aged-receivables/{user_id}")
def aged_receivables(user_id: int):
    """Aged receivables from this user's own unpaid sales invoices, bucketed by
    days overdue vs each invoice's due_date.

    Phase 0 security fix: this previously read the legacy global `invoices`
    table with no owner filter and returned every tenant's unpaid invoices. It
    now reads the user-scoped `accounting_documents` table (document_type =
    'invoice'), which is where the Sales module stores invoices."""
    db = SessionLocal()
    try:
        rows = db.execute(text("""
            SELECT COALESCE(NULLIF(party_name, ''), 'Unknown customer') AS customer,
                   due_date, total_amount
            FROM accounting_documents
            WHERE user_id = :uid
              AND document_type = 'invoice'
              AND COALESCE(status, 'draft') NOT IN ('paid', 'void', 'draft')
        """), {"uid": user_id}).fetchall()

        now = datetime.now(timezone.utc)
        buckets: dict = {}
        for r in rows:
            due = r.due_date
            if due and due.tzinfo is None:
                due = due.replace(tzinfo=timezone.utc)
            days_over = (now - due).days if due else 0
            b = buckets.setdefault(r.customer, {"customer": r.customer, "cur": 0, "d30": 0, "d60": 0, "d90": 0, "total": 0})
            amt = float(r.total_amount or 0)
            if days_over <= 0:
                b["cur"] += amt
            elif days_over <= 30:
                b["d30"] += amt
            elif days_over <= 60:
                b["d60"] += amt
            else:
                b["d90"] += amt
            b["total"] += amt

        result = [{k: (round(v, 2) if isinstance(v, float) else v) for k, v in row.items()} for row in buckets.values()]
        return {"rows": result, "has_data": bool(result)}
    except Exception as e:
        return {"rows": [], "has_data": False, "error": str(e)}
    finally:
        db.close()
