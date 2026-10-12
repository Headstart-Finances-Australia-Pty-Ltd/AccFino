"""/ledger journal workflow: preview, drafts + approval, AI/rule suggestions, repeating journals, CSV import, settings, health, history, sources.
Paths are deliberately distinct from /ledger/journals/{id} so nothing here can be shadowed by (or shadow) the core journal routes."""
import csv
import io
from datetime import date
from datetime import date as Date
from decimal import Decimal

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import Response
from pydantic import BaseModel, ConfigDict
from sqlalchemy.orm import Session

from accfino.core import models as m
from accfino.modules.accounting.models import ledger as lm
from accfino.modules.accounting.books.common import BooksError, require_bulk_import
from accfino.modules.accounting.ledger import ai_assist as AA
from accfino.modules.accounting.ledger import fx as FX
from accfino.modules.accounting.ledger import fx_feed
from accfino.modules.accounting.ledger import journal_tools as JT
from accfino.modules.accounting.ledger.journal_models import JournalDraft, RepeatingJournal
from accfino.core.security import audit
from accfino.core.security.context import OrgContext, current_org
from accfino.core.security.login import client_ip
from accfino.shared.db.database import get_db

router = APIRouter()


class LineIn(BaseModel):
    model_config = ConfigDict(extra="ignore")
    account_id: int | None = None
    account: str | None = None
    description: str | None = None
    debit: Decimal | None = None
    credit: Decimal | None = None
    tax_code_id: int | None = None
    tax_amount: Decimal | None = None
    tracking_option_ids: list[int] | None = None
    contact_name: str | None = None
    allocations: list[dict] | None = None


class DraftIn(BaseModel):
    model_config = ConfigDict(extra="ignore")
    date: Date | None = None
    narration: str | None = None
    reference: str | None = None
    amounts_are: str | None = None
    auto_reverse_date: Date | None = None
    currency: str | None = None
    exchange_rate: Decimal | None = None
    lines: list[LineIn] | None = None
    # ai_bank adjustments
    account_id: int | None = None
    tax_code_id: int | None = None
    contact_name: str | None = None


class RejectIn(BaseModel):
    reason: str


class ApproveIn(BaseModel):
    post_date: Date | None = None


class BulkIn(BaseModel):
    min_confidence: Decimal = Decimal("0.95")
    ids: list[int] | None = None


class RepeatIn(BaseModel):
    model_config = ConfigDict(extra="ignore")
    name: str
    frequency: str = "monthly"
    next_date: Date
    end_date: Date | None = None
    mode: str = "draft"
    narration: str | None = None
    reference: str | None = None
    amounts_are: str = "no_tax"
    reverse_after_days: int | None = None
    is_active: bool = True
    currency: str | None = None
    auto_run: bool = False
    lines: list[LineIn]


class RunIn(BaseModel):
    as_at: Date | None = None


class ImportIn(BaseModel):
    csv: str
    mode: str = "draft"
    amounts_are: str = "no_tax"
    dry_run: bool = True


class SettingsIn(BaseModel):
    require_journal_approval: bool | None = None
    llm_suggestions: bool | None = None
    llm_assist: bool | None = None
    fx_feed_enabled: bool | None = None
    fx_feed_currencies: list[str] | None = None


class AccountCurrencyIn(BaseModel):
    currency: str | None = None


class RevalueIn(BaseModel):
    as_at: Date
    reverse: bool = True


class FeedRunIn(BaseModel):
    backfill: bool = False
    currencies: list[str] | None = None


class TextIn(BaseModel):
    text: str
    date: Date | None = None


class ExplainIn(BaseModel):
    date_from: Date
    date_to: Date
    compare_from: Date
    compare_to: Date


class FxIn(BaseModel):
    currency: str
    date: Date
    rate: Decimal
    source: str | None = None


def _lines(body):
    return [l.model_dump(exclude_none=True) for l in (body or [])]


def _data(b: DraftIn):
    d = b.model_dump(exclude_unset=True)
    if b.lines is not None:
        d["lines"] = _lines(b.lines)
    return d


def _audit(ctx, request, event, entity, eid, **detail):
    audit.write(f"ledger.{event}", user_id=ctx.user_id, username=ctx.username, org_id=ctx.org.id, entity=entity, entity_id=eid, ip=client_ip(request), detail=detail or None)


def _draft(db, ctx, did) -> JournalDraft:
    d = db.query(JournalDraft).filter_by(org_id=ctx.org.id, id=did).one_or_none()
    if d is None:
        raise BooksError("Journal draft not found", 404)
    return d


@router.post("/journal-preview")
def journal_preview(body: DraftIn, ctx: OrgContext = Depends(current_org), db: Session = Depends(get_db)):
    ctx.require("read")
    return JT.preview(db, ctx.org, _data(body))


@router.get("/journal-sources")
def journal_sources(ctx: OrgContext = Depends(current_org), db: Session = Depends(get_db)):
    ctx.require("read")
    return {"items": JT.journal_sources(db, ctx.org)}


@router.get("/journal-settings")
def get_settings(ctx: OrgContext = Depends(current_org), db: Session = Depends(get_db)):
    ctx.require("read")
    return JT.get_settings(db, ctx.org)


@router.put("/journal-settings")
def put_settings(body: SettingsIn, request: Request, ctx: OrgContext = Depends(current_org), db: Session = Depends(get_db)):
    ctx.require("settings")
    res = JT.save_settings(db, ctx.org, body.model_dump(exclude_none=True))
    db.commit()
    _audit(ctx, request, "journal.settings", "organisation", ctx.org.id, **res)
    return res


@router.get("/ledger-health")
def health(ctx: OrgContext = Depends(current_org), db: Session = Depends(get_db)):
    ctx.require("read")
    return JT.ledger_health(db, ctx.org)


@router.get("/journals/{journal_id}/history")
def history(journal_id: int, ctx: OrgContext = Depends(current_org), db: Session = Depends(get_db)):
    ctx.require("read")
    return JT.journal_history(db, ctx.org, journal_id)


# -------------------------------------------------------------------------------------------------- drafts
@router.get("/journal-drafts")
def list_drafts(status: str | None = None, kind: str | None = None, ctx: OrgContext = Depends(current_org), db: Session = Depends(get_db)):
    ctx.require("read")
    return JT.list_drafts(db, ctx.org, status=status, kind=kind)


@router.post("/journal-drafts", status_code=201)
def create_draft(body: DraftIn, request: Request, submit: bool = False, ctx: OrgContext = Depends(current_org), db: Session = Depends(get_db)):
    ctx.require("post")
    d = JT.create_draft(db, ctx.org, ctx, _data(body))
    if submit:
        JT.submit_draft(db, ctx.org, ctx, d)
    db.commit()
    _audit(ctx, request, "journal_draft.created", "journal_draft", d.id, submitted=submit)
    return JT.draft_dict(db, d, JT._names(db, ctx.org))


@router.get("/journal-drafts/{draft_id}")
def get_draft(draft_id: int, ctx: OrgContext = Depends(current_org), db: Session = Depends(get_db)):
    ctx.require("read")
    return JT.draft_dict(db, _draft(db, ctx, draft_id), JT._names(db, ctx.org))


@router.put("/journal-drafts/{draft_id}")
def update_draft(draft_id: int, body: DraftIn, request: Request, ctx: OrgContext = Depends(current_org), db: Session = Depends(get_db)):
    ctx.require("post")
    d = JT.update_draft(db, ctx.org, ctx, _draft(db, ctx, draft_id), _data(body))
    db.commit()
    _audit(ctx, request, "journal_draft.updated", "journal_draft", d.id)
    return JT.draft_dict(db, d, JT._names(db, ctx.org))


@router.delete("/journal-drafts/{draft_id}")
def delete_draft(draft_id: int, request: Request, ctx: OrgContext = Depends(current_org), db: Session = Depends(get_db)):
    ctx.require("post")
    d = _draft(db, ctx, draft_id)
    JT.delete_draft(db, ctx, d)
    db.commit()
    _audit(ctx, request, "journal_draft.deleted", "journal_draft", draft_id)
    return {"deleted": True}


@router.post("/journal-drafts/{draft_id}/submit")
def submit_draft(draft_id: int, request: Request, ctx: OrgContext = Depends(current_org), db: Session = Depends(get_db)):
    ctx.require("post")
    d = JT.submit_draft(db, ctx.org, ctx, _draft(db, ctx, draft_id))
    db.commit()
    _audit(ctx, request, "journal_draft.submitted", "journal_draft", d.id)
    return JT.draft_dict(db, d, JT._names(db, ctx.org))


@router.post("/journal-drafts/{draft_id}/approve")
def approve_draft(draft_id: int, body: ApproveIn, request: Request, ctx: OrgContext = Depends(current_org), db: Session = Depends(get_db)):
    ctx.require("post")
    d = JT.approve_draft(db, ctx.org, ctx, _draft(db, ctx, draft_id), post_date=body.post_date)
    db.commit()
    _audit(ctx, request, "journal_draft.approved", "journal_draft", d.id, journal_id=d.posted_journal_id)
    if d.posted_journal_id:
        _audit(ctx, request, "journal.posted", "journal", d.posted_journal_id, from_draft=d.id, kind=d.kind)
    return JT.draft_dict(db, d, JT._names(db, ctx.org))


@router.post("/journal-drafts/{draft_id}/reject")
def reject_draft(draft_id: int, body: RejectIn, request: Request, ctx: OrgContext = Depends(current_org), db: Session = Depends(get_db)):
    ctx.require("post")
    d = JT.reject_draft(db, ctx, _draft(db, ctx, draft_id), body.reason)
    db.commit()
    _audit(ctx, request, "journal_draft.rejected", "journal_draft", d.id, reason=body.reason)
    return JT.draft_dict(db, d, JT._names(db, ctx.org))


@router.post("/journal-drafts/bulk-approve")
def bulk_approve(body: BulkIn, request: Request, ctx: OrgContext = Depends(current_org), db: Session = Depends(get_db)):
    ctx.require("post")
    res = JT.bulk_approve(db, ctx.org, ctx, min_confidence=body.min_confidence, ids=body.ids)
    _audit(ctx, request, "journal_draft.bulk_approved", "journal_draft", None, approved=res["approved"], min_confidence=str(body.min_confidence))
    return res


@router.post("/journal-suggestions/generate")
def generate_suggestions(request: Request, ctx: OrgContext = Depends(current_org), db: Session = Depends(get_db)):
    ctx.require("post")
    res = JT.suggest_bank_journals(db, ctx.org, ctx)
    db.commit()
    _audit(ctx, request, "journal_suggestions.generated", "organisation", ctx.org.id, **res)
    return res


# -------------------------------------------------------------------------------------------------- repeating
@router.get("/repeating-journals")
def list_repeating(ctx: OrgContext = Depends(current_org), db: Session = Depends(get_db)):
    ctx.require("read")
    rows = db.query(RepeatingJournal).filter_by(org_id=ctx.org.id).order_by(RepeatingJournal.next_date, RepeatingJournal.id).all()
    accs = JT._names(db, ctx.org)
    out = []
    for r in rows:
        d = JT.repeating_dict(r, next_preview=ctx.org)
        for l in d["lines"]:
            a = accs.get(l["account_id"])
            l["account_code"], l["account_name"] = (a.code, a.name) if a else (None, None)
        out.append(d)
    return {"items": out}


@router.post("/repeating-journals", status_code=201)
def create_repeating(body: RepeatIn, request: Request, ctx: OrgContext = Depends(current_org), db: Session = Depends(get_db)):
    ctx.require("post")
    data = body.model_dump()
    data["lines"] = _lines(body.lines)
    r = JT.save_repeating(db, ctx.org, ctx, data)
    db.commit()
    _audit(ctx, request, "repeating.created", "repeating_journal", r.id, name=r.name)
    return JT.repeating_dict(r, next_preview=ctx.org)


@router.put("/repeating-journals/{rid}")
def update_repeating(rid: int, body: RepeatIn, request: Request, ctx: OrgContext = Depends(current_org), db: Session = Depends(get_db)):
    ctx.require("post")
    r = db.query(RepeatingJournal).filter_by(org_id=ctx.org.id, id=rid).one_or_none()
    if r is None:
        raise BooksError("Repeating journal not found", 404)
    data = body.model_dump()
    data["lines"] = _lines(body.lines)
    r = JT.save_repeating(db, ctx.org, ctx, data, r)
    db.commit()
    _audit(ctx, request, "repeating.updated", "repeating_journal", r.id)
    return JT.repeating_dict(r, next_preview=ctx.org)


@router.delete("/repeating-journals/{rid}")
def delete_repeating(rid: int, request: Request, ctx: OrgContext = Depends(current_org), db: Session = Depends(get_db)):
    ctx.require("post")
    r = db.query(RepeatingJournal).filter_by(org_id=ctx.org.id, id=rid).one_or_none()
    if r is None:
        raise BooksError("Repeating journal not found", 404)
    db.delete(r)          # journals already created from it are unaffected
    db.commit()
    _audit(ctx, request, "repeating.deleted", "repeating_journal", rid)
    return {"deleted": True}


@router.post("/repeating-journals/run")
def run_repeating(body: RunIn, request: Request, template_id: int | None = None, ctx: OrgContext = Depends(current_org), db: Session = Depends(get_db)):
    ctx.require("post")
    res = JT.run_repeating(db, ctx.org, ctx, as_at=body.as_at, template_id=template_id)
    _audit(ctx, request, "repeating.run", "organisation", ctx.org.id, drafts=res["drafts"], posted=res["posted"], errors=len(res["errors"]))
    return res


# -------------------------------------------------------------------------------------------------- import
@router.post("/journal-import")
def import_journals(body: ImportIn, request: Request, ctx: OrgContext = Depends(current_org), db: Session = Depends(get_db)):
    ctx.require("post")
    require_bulk_import(db, ctx)
    res = JT.import_journals(db, ctx.org, ctx, body.csv, mode=body.mode, amounts_are=body.amounts_are, dry_run=body.dry_run)
    if not body.dry_run and not res.get("error"):
        db.commit()
        _audit(ctx, request, "journal.imported", "organisation", ctx.org.id, mode=body.mode, saved=res["saved"], posted=res["posted"])
    else:
        db.rollback()
    return res


@router.get("/journal-import/template")
def import_template(ctx: OrgContext = Depends(current_org)):
    ctx.require("read")
    rows = [["Date", "Narration", "Reference", "Account", "Description", "Debit", "Credit", "Tax Code", "Contact", "Tracking", "Currency", "Rate"],
            ["30/06/2026", "Accrue June audit fee", "AUD-2026", "412", "Audit fee accrual", "3200.00", "", "", "Baker & Co", "Admin", "", ""],
            ["", "", "", "805", "Accrued expenses", "", "3200.00", "", "", "", "", ""],
            ["30/06/2026", "Prepaid insurance release", "", "433", "Insurance", "575.00", "", "", "", "", "", ""],
            ["", "", "", "620", "Prepayments", "", "575.00", "", "", "", "", ""],
            ["30/06/2026", "US software licence (leave Rate blank to use your stored rate)", "USD-01", "485", "Licence", "1800.00", "", "", "Cloudware Inc", "", "USD", "0.66"],
            ["", "", "", "805", "Accrued", "", "1800.00", "", "", "", "", ""]]
    buf = io.StringIO()
    csv.writer(buf).writerows(rows)
    return Response(buf.getvalue(), media_type="text/csv", headers={"Content-Disposition": 'attachment; filename="journal-import-template.csv"'})


# -------------------------------------------------------------------------------------------------- exchange rates
@router.get("/fx-rates")
def list_fx_rates(currency: str | None = None, ctx: OrgContext = Depends(current_org), db: Session = Depends(get_db)):
    ctx.require("read")
    from accfino.modules.accounting.ledger.journal_models import FxRate
    q = db.query(FxRate).filter(FxRate.org_id == ctx.org.id)
    if currency:
        q = q.filter(FxRate.currency == currency.upper())
    return {"base": JT.base_currency(ctx.org), "items": [JT.fx_dict(r) for r in q.order_by(FxRate.currency, FxRate.rate_date.desc()).limit(500)]}


@router.put("/fx-rates")
def put_fx_rate(body: FxIn, request: Request, ctx: OrgContext = Depends(current_org), db: Session = Depends(get_db)):
    ctx.require("post")
    r = JT.set_fx_rate(db, ctx.org, ctx, body.currency, body.date, body.rate, body.source)
    db.commit()
    _audit(ctx, request, "fx_rate.set", "fx_rate", r.id, currency=r.currency, date=str(r.rate_date), rate=str(r.rate))
    return JT.fx_dict(r)


@router.delete("/fx-rates/{rate_id}")
def delete_fx_rate(rate_id: int, request: Request, ctx: OrgContext = Depends(current_org), db: Session = Depends(get_db)):
    ctx.require("post")
    from accfino.modules.accounting.ledger.journal_models import FxRate
    r = db.query(FxRate).filter_by(org_id=ctx.org.id, id=rate_id).one_or_none()
    if r is None:
        raise BooksError("Exchange rate not found", 404)
    db.delete(r)          # journals already posted keep the rate they were posted at
    db.commit()
    _audit(ctx, request, "fx_rate.deleted", "fx_rate", rate_id)
    return {"deleted": True}


@router.get("/fx-rate")
def lookup_fx_rate(currency: str, on: Date = Query(None, alias="date"), ctx: OrgContext = Depends(current_org), db: Session = Depends(get_db)):
    """The organisation's own rate on/before a date (or null) - never a guessed one."""
    ctx.require("read")
    cur = currency.strip().upper()
    when = on or date.today()
    from accfino.modules.accounting.ledger.journal_models import FxRate
    r = db.query(FxRate).filter(FxRate.org_id == ctx.org.id, FxRate.currency == cur, FxRate.rate_date <= when).order_by(FxRate.rate_date.desc()).first()
    return {"currency": cur, "base": JT.base_currency(ctx.org), "rate": str(r.rate) if r else None, "rate_date": r.rate_date.isoformat() if r else None, "source": r.source if r else None}


# -------------------------------------------------------------------------------------------------- scheduler
@router.get("/scheduler-status")
def scheduler_status(ctx: OrgContext = Depends(current_org), db: Session = Depends(get_db)):
    ctx.require("read")
    import os

    from accfino.modules.accounting.ledger import scheduler
    n = db.query(RepeatingJournal).filter_by(org_id=ctx.org.id, is_active=True, auto_run=True).count()
    hb = scheduler.heartbeat(db)
    return {"enabled": os.getenv("ACCFINO_SCHEDULER", "1") not in ("0", "false", "False", "no"), "interval_seconds": max(30, int(os.getenv("ACCFINO_SCHEDULER_SECONDS", "900"))),
            "timezone": os.getenv("ACCFINO_TZ", "Australia/Sydney"), "auto_templates": n, "last_sweep": hb}


# -------------------------------------------------------------------------------------------------- foreign-held accounts
@router.get("/fx/accounts")
def fx_accounts(ctx: OrgContext = Depends(current_org), db: Session = Depends(get_db)):
    """Accounts that could be held in a foreign currency, with their current setting and foreign balance."""
    ctx.require("read")
    out = []
    for a in db.query(lm.LedgerAccount).filter(lm.LedgerAccount.org_id == ctx.org.id, lm.LedgerAccount.is_active.is_(True), lm.LedgerAccount.account_type.in_(FX.MONETARY_TYPES),
                                              lm.LedgerAccount.system_key.is_(None)).order_by(lm.LedgerAccount.code):
        has = db.query(lm.JournalLine.id).filter_by(org_id=ctx.org.id, account_id=a.id).first() is not None
        row = dict(id=a.id, code=a.code, name=a.name, type=a.account_type, currency=a.foreign_currency, has_postings=has, foreign_balance=None, base_value=None)
        if a.foreign_currency:
            f, c = FX.position(db, ctx.org, a)
            row.update(foreign_balance=str(f), base_value=str(c))
        out.append(row)
    return {"base": FX.base_currency(ctx.org), "items": out}


@router.put("/fx/accounts/{account_id}")
def set_fx_account(account_id: int, body: AccountCurrencyIn, request: Request, ctx: OrgContext = Depends(current_org), db: Session = Depends(get_db)):
    ctx.require("settings")
    a = FX.set_account_currency(db, ctx.org, account_id, body.currency)
    if a.foreign_currency:
        FX.ensure_fx_accounts(db, ctx.org)
    db.commit()
    _audit(ctx, request, "fx.account_currency", "ledger_account", a.id, currency=a.foreign_currency)
    return {"id": a.id, "code": a.code, "name": a.name, "currency": a.foreign_currency}


# -------------------------------------------------------------------------------------------------- revaluation and reports
@router.get("/fx/revaluation")
def fx_revaluation_preview(as_at: Date = Query(...), ctx: OrgContext = Depends(current_org), db: Session = Depends(get_db)):
    ctx.require("read")
    return FX.revaluation_preview(db, ctx.org, as_at)


@router.post("/fx/revalue")
def fx_revalue(body: RevalueIn, request: Request, ctx: OrgContext = Depends(current_org), db: Session = Depends(get_db)):
    """Post the unrealised gain/loss journals (approvers only - it changes the books)."""
    if not JT.can_approve(ctx):
        raise BooksError("Only an approver can post a revaluation", 403)
    res = FX.revalue(db, ctx.org, ctx.user_id, body.as_at, reverse=body.reverse)
    db.commit()
    _audit(ctx, request, "fx.revalued", "organisation", ctx.org.id, as_at=str(body.as_at), journals=[p["journal_no"] for p in res["posted"]], reverse=body.reverse)
    return res


@router.get("/reports/fx-gains-losses")
def fx_gains_losses(date_from: Date = Query(..., alias="from"), date_to: Date = Query(..., alias="to"), ctx: OrgContext = Depends(current_org), db: Session = Depends(get_db)):
    ctx.require("read")
    return FX.gains_losses_report(db, ctx.org, date_from, date_to)


# -------------------------------------------------------------------------------------------------- automatic rate feed
@router.get("/fx-feed")
def fx_feed_status(ctx: OrgContext = Depends(current_org), db: Session = Depends(get_db)):
    ctx.require("read")
    return fx_feed.status(db, ctx.org)


@router.post("/fx-feed/run")
def fx_feed_run(body: FeedRunIn, request: Request, ctx: OrgContext = Depends(current_org), db: Session = Depends(get_db)):
    ctx.require("post")
    only = [c.strip().upper() for c in body.currencies] if body.currencies else None
    res = fx_feed.fetch_for_org(db, ctx.org, backfill=body.backfill, only_currencies=only)
    fx_feed.record(db, ctx.org, dict(ok=True, business_date=date.today().isoformat(), manual=True, **res))
    db.commit()
    _audit(ctx, request, "fx.feed_run", "organisation", ctx.org.id, stored=res["stored"], backfill=body.backfill, currencies=res["currencies"])
    return res


# -------------------------------------------------------------------------------------------------- AI assistant
@router.post("/ai/journal-from-text")
def ai_journal(body: TextIn, request: Request, ctx: OrgContext = Depends(current_org), db: Session = Depends(get_db)):
    ctx.require("post")
    res = AA.journal_from_text(db, ctx.org, body.text, body.date or date.today())
    _audit(ctx, request, "ai.journal_from_text", "organisation", ctx.org.id, balanced=res["balanced"], lines=len(res["proposal"]["lines"]))
    return res


@router.post("/ai/review-draft/{draft_id}")
def ai_review(draft_id: int, request: Request, ctx: OrgContext = Depends(current_org), db: Session = Depends(get_db)):
    if not JT.can_approve(ctx):
        raise BooksError("Only an approver can request an AI review", 403)
    d = db.query(JournalDraft).filter_by(org_id=ctx.org.id, id=draft_id).one_or_none()
    if d is None:
        raise BooksError("Draft not found", 404)
    res = AA.review_draft(db, ctx.org, d)
    _audit(ctx, request, "ai.review_draft", "journal_draft", d.id, verdict=res["verdict"])
    return res


@router.post("/ai/explain-profit-loss")
def ai_explain(body: ExplainIn, request: Request, ctx: OrgContext = Depends(current_org), db: Session = Depends(get_db)):
    ctx.require("read")
    res = AA.explain_profit_loss(db, ctx.org, body.date_from, body.date_to, body.compare_from, body.compare_to)
    _audit(ctx, request, "ai.explain_profit_loss", "organisation", ctx.org.id, withheld=bool(res.get("note") and not res.get("commentary")))
    return res
