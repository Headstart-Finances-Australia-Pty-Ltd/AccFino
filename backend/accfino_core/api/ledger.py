"""/ledger: chart of accounts, tax codes, tracking, journals, bank sync and reports."""
from datetime import date
from datetime import date as Date  # alias: some models have a field named 'date'
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, selectinload

from accfino_core import models as m
from accfino_core.coa.legacy_bridge import mirror_ledger_to_legacy
from accfino_core.ledger import service as L
from accfino_core.ledger.bank_sync import sync_bank_transactions
from accfino_core.security import audit
from accfino_core.security.context import OrgContext, current_org
from accfino_core.security.login import client_ip
from db_app.database import get_db

router = APIRouter()


def _ledger_error(e: Exception):
    raise HTTPException(422, str(e))


def _acc(a, balance=None):
    return {"id": a.id, "code": a.code, "name": a.name, "type": a.account_type, "class": a.account_class,
            "description": a.description, "default_tax_code_id": a.default_tax_code_id,
            "default_tax_code": a.default_tax_code.name if a.default_tax_code else None,
            "system_key": a.system_key, "is_system": bool(a.system_key), "is_active": a.is_active,
            "bank_name": a.bank_name, "bank_account_ref": a.bank_account_ref,
            "balance": str(balance) if balance is not None else None}


# ------------------------------------------------------------ accounts --
class AccountIn(BaseModel):
    code: str = Field(min_length=1, max_length=20)
    name: str = Field(min_length=1, max_length=200)
    type: str
    description: str | None = None
    default_tax_code_id: int | None = None


class AccountPatch(BaseModel):
    code: str | None = Field(default=None, min_length=1, max_length=20)
    name: str | None = Field(default=None, min_length=1, max_length=200)
    description: str | None = None
    default_tax_code_id: int | None = None
    is_active: bool | None = None


def _balances(db, org):
    sums = L._sums(db, org)
    return {aid: d - c for aid, (d, c) in sums.items()}


_mirrored_orgs: set[int] = set()     # one-time full sync per org per process


@router.get("/accounts")
def list_accounts(include_inactive: bool = False, ctx: OrgContext = Depends(current_org),
                  db: Session = Depends(get_db)):
    ctx.require("read")
    if ctx.org.id not in _mirrored_orgs:
        _mirrored_orgs.add(ctx.org.id)
        mirror_ledger_to_legacy(db, ctx.org.id)
    q = db.query(m.LedgerAccount).options(selectinload(m.LedgerAccount.default_tax_code)) \
        .filter(m.LedgerAccount.org_id == ctx.org.id)
    if not include_inactive:
        q = q.filter(m.LedgerAccount.is_active.is_(True))
    bal = _balances(db, ctx.org)
    out = []
    for a in q.order_by(m.LedgerAccount.code).all():
        b = bal.get(a.id, Decimal("0.00"))
        out.append(_acc(a, b if a.account_class in ("asset", "expense") else -b))
    return out


def _check_tax(db, org, tax_id):
    if tax_id and not db.query(m.TaxCode).filter_by(org_id=org.id, id=tax_id).first():
        raise HTTPException(422, "Tax code not found in this organisation")


@router.post("/accounts")
def create_account(body: AccountIn, request: Request, ctx: OrgContext = Depends(current_org),
                   db: Session = Depends(get_db)):
    ctx.require("settings")
    if body.type not in m.ACCOUNT_TYPES:
        raise HTTPException(422, f"type must be one of {', '.join(m.ACCOUNT_TYPES)}")
    _check_tax(db, ctx.org, body.default_tax_code_id)
    a = m.LedgerAccount(org_id=ctx.org.id, code=body.code.strip(), name=body.name.strip(),
                        account_type=body.type, account_class=m.ACCOUNT_TYPES[body.type],
                        description=body.description, default_tax_code_id=body.default_tax_code_id)
    db.add(a)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, "An account with that code or name already exists")
    audit.write("ledger.account.created", user_id=ctx.user_id, username=ctx.username, org_id=ctx.org.id,
                entity="ledger_account", entity_id=a.id, ip=client_ip(request),
                detail={"code": a.code, "name": a.name, "type": a.account_type})
    mirror_ledger_to_legacy(db, ctx.org.id)     # reconciliation dropdown / classifier see the new account
    return _acc(a)


@router.patch("/accounts/{account_id}")
def update_account(account_id: int, body: AccountPatch, request: Request, ctx: OrgContext = Depends(current_org),
                   db: Session = Depends(get_db)):
    ctx.require("settings")
    a = db.query(m.LedgerAccount).filter_by(org_id=ctx.org.id, id=account_id).first()
    if a is None:
        raise HTTPException(404, "Account not found")
    changes = body.model_dump(exclude_unset=True)
    if a.system_key and ("is_active" in changes and changes["is_active"] is False):
        raise HTTPException(409, "System accounts cannot be deactivated")
    if changes.get("is_active") is False:
        bal = _balances(db, ctx.org).get(a.id, Decimal("0.00"))
        if bal != 0:
            raise HTTPException(409, f"Account has a balance of {bal}; it must be zero before deactivating")
    if "default_tax_code_id" in changes:
        _check_tax(db, ctx.org, changes["default_tax_code_id"])
    before = {"code": a.code, "name": a.name, "is_active": a.is_active}
    for k, v in changes.items():
        setattr(a, k, v.strip() if isinstance(v, str) and k in ("code", "name") else v)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, "An account with that code or name already exists")
    audit.write("ledger.account.updated", user_id=ctx.user_id, username=ctx.username, org_id=ctx.org.id,
                entity="ledger_account", entity_id=a.id, ip=client_ip(request),
                detail={"before": before, "changes": {k: str(v) for k, v in changes.items()}})
    if {"name", "is_active"} & changes.keys():
        if "name" in changes and before["name"] != a.name:      # rename: retire the old name from the legacy list
            try:
                from sqlalchemy import text as _t
                db.execute(_t("DELETE FROM chart_of_accounts WHERE name = :n"), {"n": before["name"]}); db.commit()
            except Exception:
                db.rollback()
        mirror_ledger_to_legacy(db, ctx.org.id)
    return _acc(a)


@router.get("/account-types")
def account_types():
    return [{"type": t, "class": c} for t, c in m.ACCOUNT_TYPES.items()]


# ----------------------------------------------------------- tax codes --
@router.get("/tax-codes")
def tax_codes(ctx: OrgContext = Depends(current_org), db: Session = Depends(get_db)):
    ctx.require("read")
    return [{"id": t.id, "code": t.code, "name": t.name, "rate": str(t.rate), "applies_to": t.applies_to,
             "bas_labels": t.bas_labels, "is_active": t.is_active}
            for t in db.query(m.TaxCode).filter_by(org_id=ctx.org.id).order_by(m.TaxCode.id)]


# ------------------------------------------------------------ tracking --
class NameIn(BaseModel):
    name: str = Field(min_length=1, max_length=100)


@router.get("/tracking-categories")
def tracking(ctx: OrgContext = Depends(current_org), db: Session = Depends(get_db)):
    ctx.require("read")
    cats = db.query(m.TrackingCategory).filter_by(org_id=ctx.org.id).order_by(m.TrackingCategory.name).all()
    return [{"id": c.id, "name": c.name, "is_active": c.is_active,
             "options": [{"id": o.id, "name": o.name, "is_active": o.is_active} for o in c.options]} for c in cats]


@router.post("/tracking-categories")
def add_category(body: NameIn, request: Request, ctx: OrgContext = Depends(current_org),
                 db: Session = Depends(get_db)):
    ctx.require("settings")
    if db.query(m.TrackingCategory).filter_by(org_id=ctx.org.id, is_active=True).count() >= 2:
        raise HTTPException(409, "Up to two active tracking categories are supported")
    c = m.TrackingCategory(org_id=ctx.org.id, name=body.name.strip())
    db.add(c)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, "A tracking category with that name exists")
    audit.write("ledger.tracking.created", user_id=ctx.user_id, username=ctx.username, org_id=ctx.org.id,
                entity="tracking_category", entity_id=c.id, ip=client_ip(request))
    return {"id": c.id, "name": c.name, "options": []}


@router.post("/tracking-categories/{category_id}/options")
def add_option(category_id: int, body: NameIn, request: Request, ctx: OrgContext = Depends(current_org),
               db: Session = Depends(get_db)):
    ctx.require("settings")
    c = db.query(m.TrackingCategory).filter_by(org_id=ctx.org.id, id=category_id).first()
    if c is None:
        raise HTTPException(404, "Tracking category not found")
    o = m.TrackingOption(category_id=c.id, name=body.name.strip())
    db.add(o)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, "That option already exists")
    return {"id": o.id, "name": o.name}


# ------------------------------------------------------------ journals --
class LineIn(BaseModel):
    account_id: int
    description: str | None = None
    debit: Decimal = Decimal("0")
    credit: Decimal = Decimal("0")
    tax_code_id: int | None = None
    tax_amount: Decimal = Decimal("0")
    tracking_option_ids: list[int] | None = None
    contact_name: str | None = None
    allocations: list[dict] | None = None              # split this line across several tracking options (jobs) by percent or amount


class JournalIn(BaseModel):
    date: Date
    narration: str = Field(min_length=1, max_length=500)
    lines: list[LineIn]
    reference: str | None = Field(default=None, max_length=100)
    amounts_are: str = "no_tax"                        # no_tax | inclusive | exclusive  (GST handling for lines that carry a tax code)
    auto_reverse_date: Date | None = None              # accruals: post the reversing journal on this date
    currency: str | None = None                        # foreign currency the amounts are ENTERED in (omit for the base currency)
    exchange_rate: Decimal | None = None               # base units per 1 foreign unit; omit to use the organisation's stored rate for the date


class ReverseIn(BaseModel):
    date: Date | None = None
    narration: str | None = None


@router.get("/journals")
def list_journals(date_from: date | None = Query(None, alias="from"), date_to: date | None = Query(None, alias="to"),
                  source_type: str | None = None, q: str | None = None, account_id: int | None = None, min_amount: Decimal | None = None,
                  max_amount: Decimal | None = None, status: str | None = None, limit: int = Query(100, le=500), offset: int = 0,
                  ctx: OrgContext = Depends(current_org), db: Session = Depends(get_db)):
    ctx.require("read")
    from sqlalchemy import func, or_
    qy = db.query(m.Journal).filter(m.Journal.org_id == ctx.org.id)
    if date_from:
        qy = qy.filter(m.Journal.journal_date >= date_from)
    if date_to:
        qy = qy.filter(m.Journal.journal_date <= date_to)
    if source_type:
        qy = qy.filter(m.Journal.source_type == source_type)
    if status == "reversed":
        qy = qy.filter(m.Journal.status == "reversed")
    elif status == "posted":
        qy = qy.filter(m.Journal.status == "posted", m.Journal.reversal_of_id.is_(None))
    elif status == "reversal":
        qy = qy.filter(m.Journal.reversal_of_id.isnot(None))
    if account_id:
        qy = qy.filter(m.Journal.id.in_(db.query(m.JournalLine.journal_id).filter(m.JournalLine.org_id == ctx.org.id, m.JournalLine.account_id == account_id)))
    if min_amount is not None:
        qy = qy.filter(m.Journal.total >= min_amount)
    if max_amount is not None:
        qy = qy.filter(m.Journal.total <= max_amount)
    if q and q.strip():
        like = f"%{q.strip().lower()}%"
        conds = [func.lower(func.coalesce(m.Journal.narration, "")).like(like), func.lower(func.coalesce(m.Journal.reference, "")).like(like)]
        if q.strip().isdigit():
            conds.append(m.Journal.journal_no == int(q.strip()))
        conds.append(m.Journal.id.in_(db.query(m.JournalLine.journal_id).filter(m.JournalLine.org_id == ctx.org.id,
                     or_(func.lower(func.coalesce(m.JournalLine.description, "")).like(like), func.lower(func.coalesce(m.JournalLine.contact_name, "")).like(like)))))
        qy = qy.filter(or_(*conds))
    total = qy.count()
    sum_total = qy.with_entities(func.coalesce(func.sum(m.Journal.total), 0)).scalar()
    rows = qy.order_by(m.Journal.journal_date.desc(), m.Journal.journal_no.desc()).offset(offset).limit(limit).all()
    return {"total": total, "sum_total": str(sum_total), "items": [{"id": j.id, "journal_no": j.journal_no, "date": j.journal_date.isoformat(),
                                       "narration": j.narration, "reference": j.reference, "currency": j.currency, "source_type": j.source_type, "status": j.status,
                                       "total": str(j.total), "reversal_of_id": j.reversal_of_id,
                                       "reversed_by_id": j.reversed_by_id} for j in rows]}


@router.get("/journals/{journal_id}")
def get_journal(journal_id: int, ctx: OrgContext = Depends(current_org), db: Session = Depends(get_db)):
    ctx.require("read")
    from accfino_core.books import models as bm
    from accfino_core.ledger import journal_tools as JT
    j = db.query(m.Journal).filter_by(org_id=ctx.org.id, id=journal_id).first()
    if j is None:
        raise HTTPException(404, "Journal not found")
    d = L.journal_to_dict(j)
    d["source"] = JT.describe_source(db, ctx.org, j)
    rev = None
    if j.reversed_by_id:
        r = db.get(m.Journal, j.reversed_by_id)
        rev = {"id": r.id, "journal_no": r.journal_no, "date": r.journal_date.isoformat(), "pending": r.journal_date > date.today() and j.status == "posted"} if r else None
    d["reversal"] = rev
    if j.reversal_of_id:
        o = db.get(m.Journal, j.reversal_of_id)
        d["reverses"] = {"id": o.id, "journal_no": o.journal_no} if o else None
    d["attachments"] = [{"id": a.id, "filename": a.filename, "size": a.size} for a in db.query(bm.Attachment).filter_by(org_id=ctx.org.id, owner_kind="journal", owner_id=j.id)]
    tr = {o.id: o.name for o in db.query(m.TrackingOption).join(m.TrackingCategory).filter(m.TrackingCategory.org_id == ctx.org.id)}
    for ln in d["lines"]:
        ln["tracking"] = [tr[i] for i in (ln.get("tracking_option_ids") or []) if i in tr]
    return d


@router.post("/journals")
def create_journal(body: JournalIn, request: Request, ctx: OrgContext = Depends(current_org),
                   db: Session = Depends(get_db)):
    ctx.require("post")
    from accfino_core.ledger import journal_tools as JT
    if JT.get_settings(db, ctx.org)["require_journal_approval"] and not JT.can_approve(ctx):
        raise HTTPException(403, "This organisation requires manual journals to be approved: save it as a draft and submit it for approval")
    try:
        j, rj = JT.post_journal_full(db, ctx.org, ctx.user_id, journal_date=body.date, narration=body.narration, lines=[l.model_dump(exclude_none=True) for l in body.lines],
                                     reference=body.reference, amounts_are=body.amounts_are, auto_reverse_date=body.auto_reverse_date,
                                     currency=body.currency, exchange_rate=body.exchange_rate)
        db.commit()
    except L.LedgerError as e:
        db.rollback()
        _ledger_error(e)
    except Exception:
        db.rollback()
        raise
    audit.write("ledger.journal.posted", user_id=ctx.user_id, username=ctx.username, org_id=ctx.org.id,
                entity="journal", entity_id=j.id, ip=client_ip(request),
                detail={"journal_no": j.journal_no, "total": str(j.total), "reference": j.reference, "auto_reversal_journal_id": rj.id if rj else None})
    db.refresh(j)
    out = L.journal_to_dict(j)
    out["auto_reversal"] = {"id": rj.id, "journal_no": rj.journal_no, "date": rj.journal_date.isoformat()} if rj else None
    return out


@router.post("/journals/{journal_id}/reverse")
def reverse(journal_id: int, body: ReverseIn, request: Request, ctx: OrgContext = Depends(current_org),
            db: Session = Depends(get_db)):
    ctx.require("post")
    try:
        r = L.reverse_journal(db, ctx.org, journal_id, reversal_date=body.date, narration=body.narration,
                              created_by=ctx.user_id)
        db.commit()
    except L.LedgerError as e:
        db.rollback()
        _ledger_error(e)
    audit.write("ledger.journal.reversed", user_id=ctx.user_id, username=ctx.username, org_id=ctx.org.id,
                entity="journal", entity_id=journal_id, ip=client_ip(request),
                detail={"reversal_journal_id": r.id, "reversal_no": r.journal_no})
    db.refresh(r)
    return L.journal_to_dict(r)


# ---------------------------------------------------------------- sync --
@router.post("/sync/bank-transactions")
def sync_bank(request: Request, dry_run: bool = False, ctx: OrgContext = Depends(current_org),
              db: Session = Depends(get_db)):
    ctx.require("post")
    try:
        result = sync_bank_transactions(db, ctx.org, created_by=ctx.user_id, dry_run=dry_run)
        if dry_run:
            db.rollback()
        else:
            db.commit()
    except L.LedgerError as e:
        db.rollback()
        _ledger_error(e)
    if not dry_run:
        audit.write("ledger.sync.bank", user_id=ctx.user_id, username=ctx.username, org_id=ctx.org.id,
                    ip=client_ip(request), detail={k: v for k, v in result.items() if k != "suspense_items"})
    return result


# ------------------------------------------------------------- reports --
def _today():
    return date.today()


@router.get("/reports/trial-balance")
def rpt_tb(as_at: date | None = None, ctx: OrgContext = Depends(current_org), db: Session = Depends(get_db)):
    ctx.require("read")
    return L.trial_balance(db, ctx.org, as_at or _today())


@router.get("/reports/profit-loss")
def rpt_pl(date_from: date | None = Query(None, alias="from"), date_to: date | None = Query(None, alias="to"),
           ctx: OrgContext = Depends(current_org), db: Session = Depends(get_db)):
    ctx.require("read")
    to = date_to or _today()
    return L.profit_and_loss(db, ctx.org, date_from or L._fy_start(ctx.org, to), to)


@router.get("/reports/balance-sheet")
def rpt_bs(as_at: date | None = None, ctx: OrgContext = Depends(current_org), db: Session = Depends(get_db)):
    ctx.require("read")
    return L.balance_sheet(db, ctx.org, as_at or _today())


@router.get("/reports/general-ledger")
def rpt_gl(account_id: int, date_from: date | None = Query(None, alias="from"),
           date_to: date | None = Query(None, alias="to"), ctx: OrgContext = Depends(current_org),
           db: Session = Depends(get_db)):
    ctx.require("read")
    to = date_to or _today()
    try:
        return L.general_ledger(db, ctx.org, account_id, date_from or L._fy_start(ctx.org, to), to)
    except L.LedgerError as e:
        _ledger_error(e)
