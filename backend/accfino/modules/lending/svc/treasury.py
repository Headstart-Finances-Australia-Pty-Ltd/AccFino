"""Treasury and liquidity: cash position, funding facilities and a 30 / 60 / 90 day projection that never blends Actual, Committed and Forecast.

ACTUAL    cash held today: the ledger's bank account balances
COMMITTED contractual: facility repayments, instalments on the organisation's OWN borrowing (loans linked to ledger accounts), unpaid bills (at their due date, or today if overdue), invoices not yet due (at their due date)
FORECAST  what someone expects but nobody is bound to: entered here
Overdue invoices are listed apart (money owed to us that has not arrived is not something to plan on), and loans the agent only tracks for a client are NOT the organisation's cash."""
from datetime import date, timedelta
from decimal import Decimal
from typing import Dict, List, Optional

import accfino.modules.accounting.public as acct
from accfino.modules.lending import lend_models as M
from accfino.modules.lending.engine import amort as A, liquidity as LQ
from accfino.modules.lending.svc import loans as LN, settings
from accfino.modules.lending.svc.core import Access, Conflict, LendError, NotFound, audit, choice, no_tfn, num, parse_date, q2

ZERO = Decimal("0")
EXPIRY_WARNING_DAYS = 60


def _balances(db, ctx, as_at: date) -> Dict[int, Decimal]:
    return {b["id"]: Decimal(str(b["balance"])) for b in acct.balances_by_account(db, ctx.org, as_at)}


def facility_dict(f: M.LendFacility, bal: Dict[int, Decimal], as_at: date) -> Dict:
    drawn = abs(bal.get(f.ledger_account_id, ZERO)) if f.ledger_account_id else Decimal(f.drawn_amount or 0)
    avail = Decimal(f.limit_amount) - drawn
    days = (f.expiry_date - as_at).days if f.expiry_date else None
    return dict(id=f.id, name=f.name, lender=f.lender, facility_type=f.facility_type, limit=f.limit_amount, drawn=q2(drawn), available=q2(max(ZERO, avail)), over_limit=avail < 0, utilisation_pct=round(float(drawn / f.limit_amount * 100), 1) if f.limit_amount else None,
                drawn_from_ledger=bool(f.ledger_account_id), ledger_account_id=f.ledger_account_id, interest_rate=f.interest_rate, expiry_date=f.expiry_date, days_to_expiry=days, expiry_warning=days is not None and days <= EXPIRY_WARNING_DAYS,
                repayment_amount=f.repayment_amount, repayment_frequency=f.repayment_frequency, next_repayment_date=f.next_repayment_date, status=f.status, notes=f.notes)


def list_facilities(db, ctx, a: Access, as_at: Optional[date] = None) -> Dict:
    a.require("view")
    as_at = as_at or date.today()
    bal = _balances(db, ctx, as_at)
    rows = [facility_dict(f, bal, as_at) for f in db.query(M.LendFacility).filter_by(org_id=ctx.org.id).order_by(M.LendFacility.id)]
    act = [r for r in rows if r["status"] == "active"]
    return dict(rows=rows, totals=dict(limit=q2(sum((r["limit"] for r in act), ZERO)), drawn=q2(sum((r["drawn"] for r in act), ZERO)), available=q2(sum((r["available"] for r in act), ZERO)), facilities=len(act),
                                      expiring=len([r for r in act if r["expiry_warning"]])))


def save_facility(db, ctx, a: Access, body: dict, facility_id: Optional[int] = None) -> Dict:
    a.require("configure")
    for k in ("name", "lender", "notes"):
        no_tfn(body.get(k), k)
    name = (body.get("name") or "").strip()
    if not name:
        raise LendError("The facility needs a name")
    limit = q2(num(body.get("limit_amount"), "limit_amount", required=True))
    if limit <= 0:
        raise LendError("The facility limit must be greater than zero")
    drawn = q2(num(body.get("drawn_amount", 0) or 0, "drawn_amount"))
    rate = num(body.get("interest_rate"), "interest_rate")
    if rate is not None and rate > Decimal("0.5"):
        raise LendError("interest_rate is a fraction: 7.5% is 0.075")
    led = body.get("ledger_account_id")
    if led not in (None, ""):
        if int(led) not in {x["id"] for x in acct.ledger_accounts(db, ctx.org.id)}:
            raise LendError("That ledger account was not found in this organisation")
    rep = num(body.get("repayment_amount"), "repayment_amount")
    freq = choice(body.get("repayment_frequency"), M.FREQUENCIES, "repayment_frequency", required=False)
    nxt = parse_date(body.get("next_repayment_date"), "next_repayment_date", False)
    if rep and (not freq or not nxt):
        raise LendError("A repayment amount needs its frequency and the date of the next repayment")
    vals = dict(name=name[:200], lender=(body.get("lender") or None), facility_type=choice(body.get("facility_type"), M.FACILITY_TYPES, "facility_type", default="line_of_credit"), limit_amount=limit, drawn_amount=drawn,
                ledger_account_id=int(led) if led not in (None, "") else None, interest_rate=rate, expiry_date=parse_date(body.get("expiry_date"), "expiry_date", False), repayment_amount=q2(rep) if rep else None,
                repayment_frequency=freq, next_repayment_date=nxt, status=choice(body.get("status"), ("active", "closed"), "status", default="active"), notes=(body.get("notes") or None))
    if facility_id is None:
        f = M.LendFacility(org_id=ctx.org.id, created_by=ctx.user_id, **vals)
        db.add(f)
    else:
        f = db.query(M.LendFacility).filter_by(org_id=ctx.org.id, id=facility_id).first()
        if f is None:
            raise NotFound("Facility")
        for k, v in vals.items():
            setattr(f, k, v)
    db.flush()
    audit(db, ctx, "treasury.facility", "lend_facility", f.id, name=f.name, limit=f.limit_amount, status=f.status)
    return facility_dict(f, _balances(db, ctx, date.today()), date.today())


# ---------------------------------------------------------------------------------------------------------------------------------- forecast items
def item_dict(i: M.LendForecastItem) -> Dict:
    return dict(id=i.id, item_date=i.item_date, amount=i.amount, description=i.description, category=i.category, status=i.status, direction="in" if i.amount > 0 else "out")


def list_items(db, ctx, a: Access, date_from: Optional[date] = None, date_to: Optional[date] = None, status: str = "") -> List[Dict]:
    a.require("view")
    q = db.query(M.LendForecastItem).filter_by(org_id=ctx.org.id)
    if date_from:
        q = q.filter(M.LendForecastItem.item_date >= date_from)
    if date_to:
        q = q.filter(M.LendForecastItem.item_date <= date_to)
    if status:
        q = q.filter(M.LendForecastItem.status == status)
    return [item_dict(i) for i in q.order_by(M.LendForecastItem.item_date, M.LendForecastItem.id)]


def save_item(db, ctx, a: Access, body: dict, item_id: Optional[int] = None) -> Dict:
    a.require("edit")
    desc = (body.get("description") or "").strip()
    if not desc:
        raise LendError("Describe the expected money in or out")
    no_tfn(desc, "description")
    amt = q2(num(body.get("amount"), "amount", required=True, allow_negative=True))
    if amt == 0:
        raise LendError("The amount cannot be zero (money in is positive, money out is negative)")
    vals = dict(item_date=parse_date(body.get("item_date"), "item_date"), amount=amt, description=desc[:200], category=(body.get("category") or None), status=choice(body.get("status"), ("expected", "received", "cancelled"), "status", default="expected"))
    if item_id is None:
        i = M.LendForecastItem(org_id=ctx.org.id, created_by=ctx.user_id, **vals)
        db.add(i)
    else:
        i = db.query(M.LendForecastItem).filter_by(org_id=ctx.org.id, id=item_id).first()
        if i is None:
            raise NotFound("Forecast item")
        for k, v in vals.items():
            setattr(i, k, v)
    db.flush()
    audit(db, ctx, "treasury.forecast_item", "lend_forecast_item", i.id, date=i.item_date, amount=i.amount, status=i.status)
    return item_dict(i)


# ---------------------------------------------------------------------------------------------------------------------------------- the position
def _facility_repayments(f: M.LendFacility, start: date, end: date) -> List[Dict]:
    out = []
    if f.status != "active" or not f.repayment_amount or not f.next_repayment_date or not f.repayment_frequency:
        return out
    k = 1
    while True:
        d = A.due_date(f.next_repayment_date, f.repayment_frequency, k)
        if d > end:
            break
        if d >= start:
            out.append(dict(date=d, amount=-Decimal(f.repayment_amount), kind="committed", label=f"{f.name}: repayment", source="facility"))
        k += 1
        if k > 400:
            break
    return out


def _own_loan_flows(db, ctx, start: date, end: date) -> List[Dict]:
    out = []
    for x in db.query(M.LendLoan).filter(M.LendLoan.org_id == ctx.org.id, M.LendLoan.status == "active", M.LendLoan.ledger_loan_account_id.isnot(None)):
        pos = LN.position(db, ctx, x, start)
        if pos["arrears_amount"] > 0:
            out.append(dict(date=start, amount=-pos["arrears_amount"], kind="committed", label=f"{x.number}: arrears now due", source="loan"))
        t = LN.terms_of(db, ctx, x)
        for r in A.contractual_schedule(t):
            if start <= r["due"] <= end and r["due"] >= start and not (r["due"] <= start and pos["arrears_amount"] > 0):
                out.append(dict(date=r["due"], amount=-r["payment"], kind="committed", label=f"{x.number}: loan instalment", source="loan"))
    return out


def position(db, ctx, a: Access, as_at: Optional[date] = None, horizon: int = 90) -> Dict:
    a.require("view")
    as_at = as_at or date.today()
    horizon = max(30, min(int(horizon), 365))
    end = as_at + timedelta(days=horizon)
    bal = _balances(db, ctx, as_at)
    banks = acct.bank_accounts(db, ctx.org.id)
    accounts = [dict(id=b["id"], code=b["code"], name=b["name"], balance=q2(bal.get(b["id"], ZERO))) for b in banks]
    cash = q2(sum((b["balance"] for b in accounts), ZERO))
    facs = db.query(M.LendFacility).filter_by(org_id=ctx.org.id).order_by(M.LendFacility.id).all()
    fdicts = [facility_dict(f, bal, as_at) for f in facs]
    flows: List[Dict] = []
    for f in facs:
        flows += _facility_repayments(f, as_at, end)
    flows += _own_loan_flows(db, ctx, as_at, end)
    overdue_recv = []
    for it in acct.open_items(db, ctx.org, as_at):
        if it["side"] == "payable":
            flows.append(dict(date=max(it["due"], as_at), amount=-it["amount"], kind="committed", label=f"Bill {it['number']} ({it['contact']})", source="bill"))
        elif it["due"] >= as_at:
            flows.append(dict(date=it["due"], amount=it["amount"], kind="committed", label=f"Invoice {it['number']} ({it['contact']})", source="invoice"))
        else:
            overdue_recv.append(dict(number=it["number"], contact=it["contact"], due=it["due"], amount=it["amount"], days_overdue=it["days_overdue"]))
    for i in db.query(M.LendForecastItem).filter(M.LendForecastItem.org_id == ctx.org.id, M.LendForecastItem.status == "expected", M.LendForecastItem.item_date >= as_at, M.LendForecastItem.item_date <= end):
        flows.append(dict(date=i.item_date, amount=i.amount, kind="forecast", label=i.description, source="forecast"))
    buf = Decimal(settings._row(db, ctx).min_cash_buffer or 0)
    live_f = [dict(limit=f["limit"], drawn=f["drawn"], status=f["status"]) for f in fdicts]
    proj = LQ.project(float(cash), [dict(i, amount=float(i["amount"])) for i in flows], as_at, horizon, float(buf), live_f)
    w = {x["days"]: x for x in proj["windows"]}
    return dict(as_at=as_at, horizon=horizon, cash=dict(total=cash, accounts=accounts), facilities=dict(rows=fdicts, limit=q2(sum((f["limit"] for f in fdicts if f["status"] == "active"), ZERO)), drawn=q2(sum((f["drawn"] for f in fdicts if f["status"] == "active"), ZERO)),
                                                                   available=q2(sum((f["available"] for f in fdicts if f["status"] == "active"), ZERO))), min_cash_buffer=buf, projection=proj, windows=proj["windows"],
                flows=sorted(proj["flows"], key=lambda i: (i["date"], i["kind"])), overdue_receivables=overdue_recv,
                funding=dict(required_committed=w[30]["shortfall_committed"]["funding_required"] if 30 in w else 0.0, status={k: v["status"] for k, v in w.items()}),
                explain="Actual is the cash in your bank accounts today. Committed flows are contractual (loan and facility repayments, unpaid bills, invoices not yet due). Forecast flows are expectations you entered. The two projected balances are kept apart: committed alone, and committed plus forecast.")
