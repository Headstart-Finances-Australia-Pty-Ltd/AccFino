"""Report endpoints: /sales/reports, /purchases/reports, /ledger/reports (GST, cash flow, GL summary, journals, cash, PAYG, budget, management pack...)."""
import csv
import io
from datetime import date

from decimal import Decimal

from fastapi import APIRouter, Depends, Query
from fastapi.responses import Response
from pydantic import BaseModel, ConfigDict
from sqlalchemy.orm import Session

from accfino_core.books import models as b
from accfino_core.books import reports as R
from accfino_core.books import reports_extra as X
from accfino_core.ledger import journal_tools as JT
from accfino_core.books.common import BooksError
from accfino_core.security.context import OrgContext, current_org
from db_app.database import get_db

sales_reports = APIRouter()
purchases_reports = APIRouter()
ledger_reports = APIRouter()


def _csv(rows, headers, name):
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(headers)
    for r in rows:
        w.writerow(r)
    return Response(buf.getvalue(), media_type="text/csv", headers={"Content-Disposition": f'attachment; filename="{name}"'})


def _aged(side, as_at, fmt, ctx, db):
    ctx.require("read")
    res = R.aged(db, ctx.org, side, as_at or date.today())
    if fmt == "csv":
        return _csv([[r["contact"], *[r[k] for k in R.BUCKETS], r["total"]] for r in res["contacts"]] + [["TOTAL", *[res["buckets"][k] for k in R.BUCKETS], res["total"]]],
                    ["Contact", *R.BUCKETS, "Total"], f"aged-{side}-{res['as_at']}.csv")
    return res


def _statement(side, contact_id, as_at, ctx, db):
    ctx.require("read")
    c = db.query(b.Contact).filter_by(org_id=ctx.org.id, id=contact_id).one_or_none()
    if c is None:
        raise BooksError("Contact not found", 404)
    return R.statement(db, ctx.org, c, as_at or date.today())


@sales_reports.get("/aged-receivables")
def aged_receivables(as_at: date | None = None, format: str = "json", ctx: OrgContext = Depends(current_org), db: Session = Depends(get_db)):
    return _aged("sales", as_at, format, ctx, db)


@sales_reports.get("/statement/{contact_id}")
def sales_statement(contact_id: int, as_at: date | None = None, ctx: OrgContext = Depends(current_org), db: Session = Depends(get_db)):
    return _statement("sales", contact_id, as_at, ctx, db)


@sales_reports.get("/by-customer")
def by_customer(date_from: date = Query(..., alias="from"), date_to: date = Query(..., alias="to"), ctx: OrgContext = Depends(current_org), db: Session = Depends(get_db)):
    ctx.require("read")
    return R.by_contact(db, ctx.org, "sales", date_from, date_to)


@sales_reports.get("/summary")
def sales_summary(ctx: OrgContext = Depends(current_org), db: Session = Depends(get_db)):
    ctx.require("read")
    return R.dashboard(db, ctx.org, "sales")


@purchases_reports.get("/aged-payables")
def aged_payables(as_at: date | None = None, format: str = "json", ctx: OrgContext = Depends(current_org), db: Session = Depends(get_db)):
    return _aged("purchases", as_at, format, ctx, db)


@purchases_reports.get("/statement/{contact_id}")
def purchases_statement(contact_id: int, as_at: date | None = None, ctx: OrgContext = Depends(current_org), db: Session = Depends(get_db)):
    return _statement("purchases", contact_id, as_at, ctx, db)


@purchases_reports.get("/by-supplier")
def by_supplier(date_from: date = Query(..., alias="from"), date_to: date = Query(..., alias="to"), ctx: OrgContext = Depends(current_org), db: Session = Depends(get_db)):
    ctx.require("read")
    return R.by_contact(db, ctx.org, "purchases", date_from, date_to)


@purchases_reports.get("/summary")
def purchases_summary(ctx: OrgContext = Depends(current_org), db: Session = Depends(get_db)):
    ctx.require("read")
    return R.dashboard(db, ctx.org, "purchases")


@ledger_reports.get("/gst-summary")
def gst_summary(date_from: date = Query(..., alias="from"), date_to: date = Query(..., alias="to"), basis: str | None = None, format: str = "json",
                ctx: OrgContext = Depends(current_org), db: Session = Depends(get_db)):
    ctx.require("read")
    res = R.gst_summary(db, ctx.org, date_from, date_to, basis)
    if format == "csv":
        return _csv([[k, v] for k, v in res["fields"].items()] + [["Net GST payable", res["net_gst_payable"]]], ["BAS label", "Amount"], f"gst-{res['date_from']}-{res['date_to']}.csv")
    return res


@ledger_reports.get("/cash-flow")
def cash_flow(date_from: date = Query(..., alias="from"), date_to: date = Query(..., alias="to"), ctx: OrgContext = Depends(current_org), db: Session = Depends(get_db)):
    ctx.require("read")
    return R.cash_flow(db, ctx.org, date_from, date_to)


@ledger_reports.get("/subledger-control")
def subledger_control(as_at: date | None = None, ctx: OrgContext = Depends(current_org), db: Session = Depends(get_db)):
    """Do the invoice/bill sub-ledgers agree with the AR / AP control accounts? (the check every accountant runs before a BAS)"""
    ctx.require("read")
    at = as_at or date.today()
    return dict(as_at=at.isoformat(), receivables=R.aged(db, ctx.org, "sales", at)["control"], payables=R.aged(db, ctx.org, "purchases", at)["control"])


# ------------------------------------------------------------------------------------------------ remaining reports --
class BudgetLineIn(BaseModel):
    model_config = ConfigDict(extra="ignore")
    account: str | int
    period: str
    amount: Decimal


class BudgetIn(BaseModel):
    model_config = ConfigDict(extra="ignore")
    scenario: str = "Budget"
    lines: list[BudgetLineIn]


class BudgetGenerateIn(BaseModel):
    model_config = ConfigDict(extra="ignore")
    scenario: str = "Budget"
    fy_start: date
    uplift_pct: Decimal = Decimal(0)


@ledger_reports.get("/gl-summary")
def gl_summary(date_from: date = Query(..., alias="from"), date_to: date = Query(..., alias="to"), ctx: OrgContext = Depends(current_org), db: Session = Depends(get_db)):
    ctx.require("read")
    return X.gl_summary(db, ctx.org, date_from, date_to)


@ledger_reports.get("/journal-report")
def journal_report(date_from: date = Query(..., alias="from"), date_to: date = Query(..., alias="to"), source_type: str | None = None, account_id: int | None = None,
                   include_reversed: bool = True, limit: int = 500, ctx: OrgContext = Depends(current_org), db: Session = Depends(get_db)):
    ctx.require("read")
    return X.journal_report(db, ctx.org, date_from, date_to, source_type=source_type, account_id=account_id, include_reversed=include_reversed, limit=limit)


@ledger_reports.get("/cash-summary")
def cash_summary(date_from: date = Query(..., alias="from"), date_to: date = Query(..., alias="to"), ctx: OrgContext = Depends(current_org), db: Session = Depends(get_db)):
    ctx.require("read")
    return X.cash_summary(db, ctx.org, date_from, date_to)


@ledger_reports.get("/account-summary")
def account_summary(date_from: date = Query(..., alias="from"), date_to: date = Query(..., alias="to"), ctx: OrgContext = Depends(current_org), db: Session = Depends(get_db)):
    ctx.require("read")
    return X.account_summary(db, ctx.org, date_from, date_to)


@ledger_reports.get("/cash-validation")
def cash_validation(date_from: date = Query(..., alias="from"), date_to: date = Query(..., alias="to"), ctx: OrgContext = Depends(current_org), db: Session = Depends(get_db)):
    ctx.require("read")
    return X.cash_validation(db, ctx.org, date_from, date_to)


@ledger_reports.get("/expense-claims")
def expense_claims(date_from: date = Query(..., alias="from"), date_to: date = Query(..., alias="to"), ctx: OrgContext = Depends(current_org), db: Session = Depends(get_db)):
    ctx.require("read")
    return X.expense_claims_report(db, ctx.org, date_from, date_to)


@ledger_reports.get("/payg-summary")
def payg_summary(date_from: date = Query(..., alias="from"), date_to: date = Query(..., alias="to"), ctx: OrgContext = Depends(current_org), db: Session = Depends(get_db)):
    ctx.require("read")
    return X.payg_summary(db, ctx.org, date_from, date_to)


@ledger_reports.get("/management-report")
def management_report(date_from: date = Query(..., alias="from"), date_to: date = Query(..., alias="to"), ctx: OrgContext = Depends(current_org), db: Session = Depends(get_db)):
    ctx.require("read")
    return X.management_report(db, ctx.org, date_from, date_to)


@ledger_reports.get("/inventory-items")
def inventory_items(date_from: date = Query(..., alias="from"), date_to: date = Query(..., alias="to"), ctx: OrgContext = Depends(current_org), db: Session = Depends(get_db)):
    ctx.require("read")
    return X.inventory_item_details(db, ctx.org, date_from, date_to)


@ledger_reports.get("/budget-variance")
def budget_variance(date_from: date = Query(..., alias="from"), date_to: date = Query(..., alias="to"), scenario: str = "Budget", by_month: bool = False,
                    ctx: OrgContext = Depends(current_org), db: Session = Depends(get_db)):
    ctx.require("read")
    return X.budget_variance(db, ctx.org, date_from, date_to, scenario, by_month)


@ledger_reports.get("/budget")
def get_budget(scenario: str = "Budget", fy_start: date | None = None, ctx: OrgContext = Depends(current_org), db: Session = Depends(get_db)):
    ctx.require("read")
    return X.get_budget(db, ctx.org, scenario, fy_start)


@ledger_reports.put("/budget")
def save_budget(body: BudgetIn, ctx: OrgContext = Depends(current_org), db: Session = Depends(get_db)):
    ctx.require("post")
    res = X.save_budget(db, ctx.org, body.scenario, [l.model_dump() for l in body.lines])
    db.commit()
    return res


@ledger_reports.post("/budget/generate")
def generate_budget(body: BudgetGenerateIn, ctx: OrgContext = Depends(current_org), db: Session = Depends(get_db)):
    """Create a 12-month budget from last year's actuals (optionally lifted by uplift_pct) - a starting point the user then edits."""
    ctx.require("post")
    res = X.generate_budget(db, ctx.org, body.scenario, body.fy_start, body.uplift_pct)
    db.commit()
    return res


@ledger_reports.get("/profit-loss-by-tracking")
def profit_loss_by_tracking(date_from: date = Query(..., alias="from"), date_to: date = Query(..., alias="to"), category_id: int = Query(...),
                            ctx: OrgContext = Depends(current_org), db: Session = Depends(get_db)):
    """Profit & loss with a column per tracking option (job / department / region) of one category; the columns add up to the ordinary Profit & Loss."""
    ctx.require("read")
    return JT.profit_loss_by_tracking(db, ctx.org, date_from, date_to, category_id)


@ledger_reports.get("/general-ledger-detail")
def general_ledger_detail(date_from: date = Query(..., alias="from"), date_to: date = Query(..., alias="to"), account_ids: list[int] | None = Query(None),
                          contact: str | None = None, tracking_option_ids: list[int] | None = Query(None), source_type: str | None = None, group_by: str = "account",
                          consolidate: bool = False, q: str | None = None, min_amount: Decimal | None = None, max_amount: Decimal | None = None,
                          include_reversed: bool = True, format: str = "json", ctx: OrgContext = Depends(current_org), db: Session = Depends(get_db)):
    """The full ledger: every posting line, filterable by account(s), party, tracking option, source and text; grouped by account / voucher / party / dimension / source / month."""
    ctx.require("read")
    res = JT.general_ledger_detail(db, ctx.org, date_from, date_to, account_ids=account_ids, contact=contact, tracking_option_ids=tracking_option_ids, source_type=source_type,
                                   group_by=group_by, consolidate=consolidate, q=q, min_amount=min_amount, max_amount=max_amount, include_reversed=include_reversed)
    if format == "csv":
        rows = [[g["label"], r["date"], r["journal_no"], r["account"], r["description"], r["reference"] or "", r["contact"] or "", r["source_type"], "; ".join(r["tracking"]), r["debit"], r["credit"], r["balance"]]
                for g in res["groups"] for r in g["rows"]]
        return _csv(rows, ["Group", "Date", "Journal", "Account", "Description", "Reference", "Party", "Source", "Tracking", "Debit", "Credit", "Balance"], f"general-ledger-{res['date_from']}-{res['date_to']}.csv")
    return res
