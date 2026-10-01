"""/banking: accounts, statement import, matching, reconcile actions, rules, per-organisation classifier, reconciliation report.
   /org/current/coa-rules: this organisation's chart + coding rules (replaces editing the global tables)."""
from datetime import date
from datetime import date as Date  # a field called 'date' would shadow the type inside a model
from decimal import Decimal

from fastapi import APIRouter, Depends, File, Form, Query, Request, UploadFile
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import or_
from sqlalchemy.orm import Session

from accfino_core import models as m
from accfino_core.books import banking as K
from accfino_core.books import models as b
from accfino_core.books.common import BooksError, bank_account, get_account, get_tax, money, require_bulk_import
from accfino_core.security import audit
from accfino_core.security.context import OrgContext, current_org
from accfino_core.security.login import client_ip
from db_app.database import get_db

router = APIRouter()
coa_rules_router = APIRouter()


class LineIn(BaseModel):
    model_config = ConfigDict(extra="ignore")
    date: Date
    description: str
    amount: Decimal | None = None
    debit: Decimal | None = None
    credit: Decimal | None = None
    balance: Decimal | None = None


class ImportIn(BaseModel):
    bank_account: str | int
    lines: list[LineIn]
    adopt_existing: bool = True


class SuggestIn(BaseModel):
    model_config = ConfigDict(extra="ignore")
    lines: list[LineIn]
    bank_account: str | int | None = None


class MatchIn(BaseModel):
    kind: str
    doc_id: int | None = None
    payment_id: int | None = None


class SplitIn(BaseModel):
    account: str | int
    tax_code: str | None = None
    amount: Decimal
    description: str | None = None


class CreateIn(BaseModel):
    account: str | int | None = None
    tax_code: str | None = None
    contact: str | None = None
    description: str | None = None
    splits: list[SplitIn] | None = None
    learn: bool = True
    rate: Decimal | None = None          # foreign-currency accounts: the rate you were given (otherwise your stored rate for the line's date is used)


class TransferIn(BaseModel):
    to_account: str | int
    pair_line_id: int | None = None
    other_amount: Decimal | None = None  # a currency conversion: the amount that arrived (or left) on the other account, in ITS currency
    rate: Decimal | None = None


class UnrecIn(BaseModel):
    reverse: bool = True


class RuleIn(BaseModel):
    model_config = ConfigDict(extra="ignore")
    name: str
    pattern: str
    account: str | int
    priority: int = 100
    direction: str = "any"
    match_type: str = "contains"
    min_amount: Decimal | None = None
    max_amount: Decimal | None = None
    tax_code: str | None = None
    contact_name: str | None = None
    description: str | None = None
    is_active: bool = True


class FeedbackIn(BaseModel):
    description: str
    account: str | int
    tax_code: str | None = None
    contact: str | None = None


class ClassifyIn(BaseModel):
    description: str
    amount: Decimal = Decimal(-1)


class AutoIn(BaseModel):
    bank_account: str | int | None = None
    min_confidence: Decimal = Decimal("0.99")
    dry_run: bool = False


class BankAccountIn(BaseModel):
    code: str
    name: str
    bank_name: str | None = None
    bank_account_ref: str | None = None
    type: str = "bank"


def _audit(ctx, request, event, entity, entity_id, **detail):
    audit.write(f"banking.{event}", user_id=ctx.user_id, username=ctx.username, org_id=ctx.org.id, entity=entity, entity_id=entity_id,
                ip=client_ip(request), detail=detail or None)


def _line(db, ctx, line_id, lock=True):
    q = db.query(b.BankLine).filter_by(org_id=ctx.org.id, id=line_id)
    l = (q.with_for_update() if lock else q).one_or_none()
    if l is None:
        raise BooksError("Bank line not found", 404)
    return l


def _rule_fields(db, ctx, body: RuleIn):
    if body.direction not in ("in", "out", "any") or body.match_type not in ("contains", "startswith", "regex"):
        raise BooksError("direction must be in/out/any and match_type contains/startswith/regex")
    if not body.pattern.strip():
        raise BooksError("A rule needs a pattern")
    if body.match_type == "regex":
        import re
        try:
            re.compile(body.pattern)
        except re.error as e:
            raise BooksError(f"Invalid regular expression: {e}")
    acc = get_account(db, ctx.org, body.account, what="Rule account")
    tax = get_tax(db, ctx.org, body.tax_code) if body.tax_code else None
    return dict(name=body.name.strip()[:120], priority=body.priority, direction=body.direction, match_type=body.match_type,
                pattern=body.pattern.strip()[:200], min_amount=body.min_amount, max_amount=body.max_amount, account_id=acc.id,
                tax_code_id=tax.id if tax else None, contact_name=body.contact_name, description=body.description, is_active=body.is_active)


def rule_dict(db, r):
    a = db.get(m.LedgerAccount, r.account_id)
    t = db.get(m.TaxCode, r.tax_code_id) if r.tax_code_id else None
    return dict(id=r.id, name=r.name, priority=r.priority, direction=r.direction, match_type=r.match_type, pattern=r.pattern,
                min_amount=str(r.min_amount) if r.min_amount is not None else None, max_amount=str(r.max_amount) if r.max_amount is not None else None,
                account_id=r.account_id, account=f"{a.code} {a.name}" if a else None, tax_code=t.code if t else None,
                contact_name=r.contact_name, description=r.description, is_active=r.is_active)


# ------------------------------------------------------------------------------------------- accounts / lines --
@router.get("/accounts")
def accounts(ctx: OrgContext = Depends(current_org), db: Session = Depends(get_db)):
    ctx.require("read")
    return {"items": K.account_summary(db, ctx.org)}


@router.post("/accounts", status_code=201)
def create_bank_account(body: BankAccountIn, request: Request, ctx: OrgContext = Depends(current_org), db: Session = Depends(get_db)):
    ctx.require("settings")
    if body.type not in ("bank", "credit_card"):
        raise BooksError("type must be bank or credit_card")
    dup = db.query(m.LedgerAccount.id).filter(m.LedgerAccount.org_id == ctx.org.id,
                                              or_(m.LedgerAccount.code == body.code.strip(), m.LedgerAccount.name == body.name.strip())).first()
    if dup:
        raise BooksError("An account with that code or name already exists", 409)
    a = m.LedgerAccount(org_id=ctx.org.id, code=body.code.strip(), name=body.name.strip(), account_type=body.type, account_class=m.ACCOUNT_TYPES[body.type],
                        bank_name=body.bank_name, bank_account_ref=body.bank_account_ref, system_key=None)
    db.add(a)
    db.commit()
    _audit(ctx, request, "account.created", "ledger_account", a.id, code=a.code)
    return next(x for x in K.account_summary(db, ctx.org) if x["id"] == a.id)


@router.post("/lines/import", status_code=201)
def import_json(body: ImportIn, request: Request, ctx: OrgContext = Depends(current_org), db: Session = Depends(get_db)):
    ctx.require("post")
    bank = bank_account(db, ctx.org, body.bank_account)
    res = K.import_lines(db, ctx.org, ctx.user_id, bank, [l.model_dump() for l in body.lines], adopt_existing=body.adopt_existing)
    db.commit()
    _audit(ctx, request, "lines.imported", "ledger_account", bank.id, **{k: v for k, v in res.items() if k != "line_ids"})
    return res


@router.post("/lines/import-csv", status_code=201)
async def import_csv(request: Request, bank_account_ref: str = Form(..., alias="bank_account"), file: UploadFile = File(...),
                     adopt_existing: bool = Form(True), ctx: OrgContext = Depends(current_org), db: Session = Depends(get_db)):
    ctx.require("post")
    require_bulk_import(db, ctx)
    raw = await file.read()
    if len(raw) > 5_000_000:
        raise BooksError("File too large (5 MB max)", 413)
    bank = bank_account(db, ctx.org, bank_account_ref)
    rows, warnings = K.parse_csv(raw)
    res = K.import_lines(db, ctx.org, ctx.user_id, bank, rows, adopt_existing=adopt_existing)
    db.commit()
    _audit(ctx, request, "lines.imported", "ledger_account", bank.id, filename=file.filename, **{k: v for k, v in res.items() if k != "line_ids"})
    return {**res, "warnings": warnings, "rows_read": len(rows)}


@router.get("/lines")
def list_lines(account_id: int | None = None, status: str | None = None, q: str | None = None, suggest: bool = False,
               date_from: date | None = Query(None, alias="from"), date_to: date | None = Query(None, alias="to"),
               limit: int = Query(100, le=500), offset: int = 0, ctx: OrgContext = Depends(current_org), db: Session = Depends(get_db)):
    ctx.require("read")
    qq = db.query(b.BankLine).filter(b.BankLine.org_id == ctx.org.id)
    if account_id:
        qq = qq.filter(b.BankLine.bank_account_id == account_id)
    if status:
        qq = qq.filter(b.BankLine.status == status)
    if q:
        qq = qq.filter(b.BankLine.description.ilike(f"%{q}%"))
    if date_from:
        qq = qq.filter(b.BankLine.line_date >= date_from)
    if date_to:
        qq = qq.filter(b.BankLine.line_date <= date_to)
    total = qq.count()
    rows = qq.order_by(b.BankLine.line_date.desc(), b.BankLine.id.desc()).limit(limit).offset(offset).all()
    items, cache = [], {}
    for l in rows:
        d = K.line_dict(l)
        if suggest and l.status == "unreconciled":
            d["suggestion"] = K.suggest_match(db, ctx.org, dict(date=l.line_date, description=l.description, amount=l.amount), l.bank_account_id, cache)
            d["coding"] = K.classify(db, ctx.org, l.description, l.amount)
        items.append(d)
    return {"total": total, "items": items}


@router.post("/reconcile/suggest")
def suggest(body: SuggestIn, ctx: OrgContext = Depends(current_org), db: Session = Depends(get_db)):
    """Order-preserving: suggestions[i] / classifications[i] belong to lines[i]; null = no confident match."""
    ctx.require("read")
    bank_id = bank_account(db, ctx.org, body.bank_account).id if body.bank_account not in (None, "") else None
    cache, sugg, cls = {}, [], []
    for l in body.lines:
        amt = K.signed(l.model_dump())
        sugg.append(K.suggest_match(db, ctx.org, dict(date=l.date, description=l.description, amount=amt), bank_id, cache) if amt != 0 else None)
        cls.append(K.classify(db, ctx.org, l.description, amt) if amt != 0 else None)
    return {"suggestions": sugg, "classifications": cls}


@router.post("/lines/{line_id}/match")
def match(line_id: int, body: MatchIn, request: Request, ctx: OrgContext = Depends(current_org), db: Session = Depends(get_db)):
    ctx.require("post")
    line = _line(db, ctx, line_id)
    if body.kind in ("invoice", "bill") and body.doc_id:
        pay = K.match_doc(db, ctx.org, ctx.user_id, line, body.doc_id)
    elif body.kind == "payment" and body.payment_id:
        pay = K.match_payment(db, ctx.org, ctx.user_id, line, body.payment_id)
    else:
        raise BooksError("Give kind=invoice|bill with doc_id, or kind=payment with payment_id")
    db.commit()
    _audit(ctx, request, "line.matched", "bank_line", line.id, kind=body.kind, payment_id=pay.id, amount=str(line.amount))
    return K.line_dict(line)


@router.post("/lines/{line_id}/create")
def create_txn(line_id: int, body: CreateIn, request: Request, ctx: OrgContext = Depends(current_org), db: Session = Depends(get_db)):
    ctx.require("post")
    line = _line(db, ctx, line_id)
    if not body.account and not body.splits:
        c = K.classify(db, ctx.org, line.description, line.amount)
        if not c:
            raise BooksError("Give an account (or splits): no rule or learned coding applies to this line")
        body.account, body.tax_code = c["account_id"], body.tax_code or c["tax_code"]
        body.contact = body.contact or c["contact_name"]
    j = K.create_from_line(db, ctx.org, ctx.user_id, line, account=body.account, tax_code=body.tax_code, contact=body.contact, description=body.description,
                           splits=[s.model_dump() for s in body.splits] if body.splits else None, learn=body.learn, rate=body.rate)
    db.commit()
    _audit(ctx, request, "line.coded", "bank_line", line.id, journal_id=j.id, amount=str(line.amount))
    rl = getattr(j, "fx_realised", None)
    return {**K.line_dict(line), "journal_id": j.id, "currency": j.currency, "exchange_rate": str(j.exchange_rate) if j.exchange_rate is not None else None,
            "realised_fx": str(-rl) if rl else None}          # + = gain, - = loss


@router.post("/lines/{line_id}/transfer")
def transfer(line_id: int, body: TransferIn, request: Request, ctx: OrgContext = Depends(current_org), db: Session = Depends(get_db)):
    ctx.require("post")
    line = _line(db, ctx, line_id)
    j, pair = K.transfer(db, ctx.org, ctx.user_id, line, body.to_account, body.pair_line_id, body.other_amount, body.rate)
    db.commit()
    _audit(ctx, request, "line.transferred", "bank_line", line.id, journal_id=j.id, paired_line=pair.id if pair else None)
    rl = getattr(j, "fx_realised", None)
    return {**K.line_dict(line), "journal_id": j.id, "paired_line_id": pair.id if pair else None, "currency": j.currency,
            "exchange_rate": str(j.exchange_rate) if j.exchange_rate is not None else None, "realised_fx": str(-rl) if rl else None}


@router.post("/lines/{line_id}/exclude")
def exclude(line_id: int, request: Request, ctx: OrgContext = Depends(current_org), db: Session = Depends(get_db)):
    ctx.require("post")
    line = _line(db, ctx, line_id)
    K.exclude(db, line)
    db.commit()
    _audit(ctx, request, "line.excluded", "bank_line", line.id)
    return K.line_dict(line)


@router.post("/lines/{line_id}/unreconcile")
def unreconcile(line_id: int, body: UnrecIn, request: Request, ctx: OrgContext = Depends(current_org), db: Session = Depends(get_db)):
    ctx.require("post")
    line = _line(db, ctx, line_id)
    K.unreconcile(db, ctx.org, ctx.user_id, line, reverse=body.reverse)
    db.commit()
    _audit(ctx, request, "line.unreconciled", "bank_line", line.id, reverse=body.reverse)
    return K.line_dict(line)


@router.post("/reconcile/auto")
def auto(body: AutoIn, request: Request, ctx: OrgContext = Depends(current_org), db: Session = Depends(get_db)):
    """Reconciles every line whose match is certain (default: document number + exact amount). Everything else is left for a person."""
    ctx.require("post")
    bank_id = bank_account(db, ctx.org, body.bank_account).id if body.bank_account not in (None, "") else None
    res = K.auto_reconcile(db, ctx.org, ctx.user_id, bank_id=bank_id, min_confidence=body.min_confidence, dry_run=body.dry_run)
    if not body.dry_run:
        db.commit()
        _audit(ctx, request, "auto_reconciled", "organisation", ctx.org.id, matched=len(res["matched"]), left=res["left_for_review"])
    return res


@router.get("/reconciliation/{account_id}")
def reconciliation(account_id: int, as_at: date | None = None, statement_balance: Decimal | None = None,
                   ctx: OrgContext = Depends(current_org), db: Session = Depends(get_db)):
    ctx.require("read")
    bank = bank_account(db, ctx.org, account_id)
    return K.reconciliation_report(db, ctx.org, bank, as_at or date.today(), statement_balance)


# ------------------------------------------------------------------------------------------- rules + learning --
@router.get("/rules")
def list_rules(ctx: OrgContext = Depends(current_org), db: Session = Depends(get_db)):
    ctx.require("read")
    return {"items": [rule_dict(db, r) for r in db.query(b.BankRule).filter_by(org_id=ctx.org.id).order_by(b.BankRule.priority, b.BankRule.id)]}


@router.post("/rules", status_code=201)
def add_rule(body: RuleIn, request: Request, ctx: OrgContext = Depends(current_org), db: Session = Depends(get_db)):
    ctx.require("post")
    r = b.BankRule(org_id=ctx.org.id, **_rule_fields(db, ctx, body))
    db.add(r)
    db.commit()
    _audit(ctx, request, "rule.created", "bank_rule", r.id, name=r.name)
    return rule_dict(db, r)


@router.put("/rules/{rule_id}")
def edit_rule(rule_id: int, body: RuleIn, request: Request, ctx: OrgContext = Depends(current_org), db: Session = Depends(get_db)):
    ctx.require("post")
    r = db.query(b.BankRule).filter_by(org_id=ctx.org.id, id=rule_id).one_or_none()
    if r is None:
        raise BooksError("Rule not found", 404)
    for k, v in _rule_fields(db, ctx, body).items():
        setattr(r, k, v)
    db.commit()
    _audit(ctx, request, "rule.updated", "bank_rule", r.id)
    return rule_dict(db, r)


@router.delete("/rules/{rule_id}")
def del_rule(rule_id: int, request: Request, ctx: OrgContext = Depends(current_org), db: Session = Depends(get_db)):
    ctx.require("post")
    r = db.query(b.BankRule).filter_by(org_id=ctx.org.id, id=rule_id).one_or_none()
    if r is None:
        raise BooksError("Rule not found", 404)
    db.delete(r)
    db.commit()
    _audit(ctx, request, "rule.deleted", "bank_rule", rule_id)
    return {"deleted": True}


@router.post("/classifier/feedback", status_code=201)
def feedback(body: FeedbackIn, request: Request, ctx: OrgContext = Depends(current_org), db: Session = Depends(get_db)):
    """Teach THIS organisation's classifier. Other organisations are never affected."""
    ctx.require("post")
    mem = K.teach(db, ctx.org, body.description, body.account, body.tax_code, body.contact)
    db.commit()
    _audit(ctx, request, "classifier.taught", "classifier_memory", mem.id, key=mem.key)
    return dict(key=mem.key, account_id=mem.account_id, hits=mem.hits, scope="organisation")


@router.post("/classifier/suggest")
def classifier_suggest(body: ClassifyIn, ctx: OrgContext = Depends(current_org), db: Session = Depends(get_db)):
    ctx.require("read")
    return {"coding": K.classify(db, ctx.org, body.description, body.amount), "merchant_key": K.merchant_key(body.description), "scope": "organisation"}


@router.get("/classifier/memory")
def memory(ctx: OrgContext = Depends(current_org), db: Session = Depends(get_db)):
    ctx.require("read")
    rows = db.query(b.ClassifierMemory).filter_by(org_id=ctx.org.id).order_by(b.ClassifierMemory.hits.desc(), b.ClassifierMemory.key).all()
    return {"items": [dict(id=r.id, key=r.key, account_id=r.account_id, tax_code_id=r.tax_code_id, contact_name=r.contact_name, hits=r.hits) for r in rows]}


@router.delete("/classifier/memory/{mem_id}")
def forget(mem_id: int, ctx: OrgContext = Depends(current_org), db: Session = Depends(get_db)):
    ctx.require("post")
    r = db.query(b.ClassifierMemory).filter_by(org_id=ctx.org.id, id=mem_id).one_or_none()
    if r is None:
        raise BooksError("Not found", 404)
    db.delete(r)
    db.commit()
    return {"deleted": True}


# ------------------------------------------------------------------------------------------- /org/current/coa-rules --
class CoaRulesIn(BaseModel):
    rules: list[RuleIn]


@coa_rules_router.get("")
def coa_rules(ctx: OrgContext = Depends(current_org), db: Session = Depends(get_db)):
    """This organisation's chart of accounts, tax codes, coding rules and learned coding - all scoped to the organisation."""
    ctx.require("read")
    accs = db.query(m.LedgerAccount).filter_by(org_id=ctx.org.id).order_by(m.LedgerAccount.code).all()
    taxes = db.query(m.TaxCode).filter_by(org_id=ctx.org.id, is_active=True).order_by(m.TaxCode.code).all()
    mem = db.query(b.ClassifierMemory).filter_by(org_id=ctx.org.id).count()
    return dict(scope="organisation", organisation_id=ctx.org.id,
                accounts=[dict(id=a.id, code=a.code, name=a.name, type=a.account_type, is_active=a.is_active, system_key=a.system_key) for a in accs],
                tax_codes=[dict(id=t.id, code=t.code, name=t.name, rate=str(t.rate), applies_to=t.applies_to) for t in taxes],
                rules=[rule_dict(db, r) for r in db.query(b.BankRule).filter_by(org_id=ctx.org.id).order_by(b.BankRule.priority, b.BankRule.id)],
                learned_count=mem)


@coa_rules_router.put("")
def replace_rules(body: CoaRulesIn, request: Request, ctx: OrgContext = Depends(current_org), db: Session = Depends(get_db)):
    """Replace THIS organisation's coding rules. An ordinary owner can never change another organisation's (or a global) rule."""
    ctx.require("post")
    fields = [_rule_fields(db, ctx, r) for r in body.rules]
    db.query(b.BankRule).filter_by(org_id=ctx.org.id).delete()
    for f in fields:
        db.add(b.BankRule(org_id=ctx.org.id, **f))
    db.commit()
    _audit(ctx, request, "rules.replaced", "organisation", ctx.org.id, count=len(fields))
    return coa_rules(ctx, db)
