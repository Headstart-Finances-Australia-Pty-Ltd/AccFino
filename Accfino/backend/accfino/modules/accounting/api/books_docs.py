"""/sales and /purchases (one factory -> identical behaviour), /contacts, /attachments and /org/current/books-settings."""
import csv
import html
import io
from datetime import date
from datetime import date as Date  # a field called 'date' would shadow the type inside a model
from decimal import Decimal

from fastapi import APIRouter, Depends, File, Query, Request, UploadFile
from fastapi.responses import HTMLResponse, Response
from pydantic import AliasChoices, BaseModel, ConfigDict, Field
from sqlalchemy import func, or_
from sqlalchemy.orm import Session, selectinload

from accfino.core import models as m
from accfino.modules.accounting.models import ledger as lm
from accfino.core.api.org import valid_abn
from accfino.modules.accounting.books import docs as D
from accfino.modules.accounting.books import models as b
from accfino.modules.accounting.books.common import BooksError, as_date, bank_accounts, bank_account, contact_dict, find_contact, get_account, get_settings, get_tax, money, require_bulk_import, save_settings
from accfino.core.security import audit
from accfino.core.security.context import OrgContext, current_org
from accfino.core.security.login import client_ip
from accfino.shared.db.database import get_db


# ---------------------------------------------------------------------------------------------- schemas --
class LineIn(BaseModel):
    model_config = ConfigDict(extra="ignore")
    description: str
    qty: Decimal = Decimal(1)
    unit_price: Decimal = Decimal(0)
    discount_pct: Decimal = Decimal(0)
    account: str | int | None = None
    tax_code: str | None = None
    tracking_option_ids: list[int] | None = None


class DocIn(BaseModel):
    model_config = ConfigDict(extra="ignore", populate_by_name=True)
    customer: str | None = None
    supplier: str | None = None
    contact: str | None = None
    contact_id: int | None = None
    number: str | None = None
    issue_date: date | None = Field(default=None, validation_alias=AliasChoices("issue_date", "issued"))
    due_date: date | None = Field(default=None, validation_alias=AliasChoices("due_date", "due"))
    reference: str | None = None
    amounts_are: str = "exclusive"
    lines: list[LineIn] = []
    notes: str | None = None
    terms: str | None = None
    status: str = "approved"                     # draft | approved (posts to the ledger immediately)


class DocPatch(DocIn):
    lines: list[LineIn] | None = None
    amounts_are: str | None = None


class AllocIn(BaseModel):
    doc_id: int
    amount: Decimal


class PaymentIn(BaseModel):
    model_config = ConfigDict(extra="ignore", populate_by_name=True)
    customer: str | None = None
    supplier: str | None = None
    contact: str | None = None
    contact_id: int | None = None
    date: Date = Field(default_factory=Date.today)
    amount: Decimal
    bank_account: str | int | None = None
    reference: str | None = None
    allocations: list[AllocIn] = []
    overpayment: bool = False


class DocPaymentIn(BaseModel):
    model_config = ConfigDict(extra="ignore")
    date: Date = Field(default_factory=Date.today)
    amount: Decimal | None = None
    bank_account: str | int | None = None
    reference: str | None = None


class AllocateIn(BaseModel):
    allocations: list[AllocIn]
    date: Date | None = None


class RefundIn(BaseModel):
    amount: Decimal | None = None
    date: Date = Field(default_factory=Date.today)
    bank_account: str | int | None = None
    reference: str | None = None


class ContactIn(BaseModel):
    model_config = ConfigDict(extra="ignore")
    name: str
    is_customer: bool | None = None
    is_supplier: bool | None = None
    email: str | None = None
    phone: str | None = None
    abn: str | None = None
    address: str | None = None
    terms_days: int | None = None
    default_account: str | int | None = None
    default_tax_code: str | None = None
    credit_limit: Decimal | None = None
    notes: str | None = None
    is_active: bool | None = None


class SettingsIn(BaseModel):
    model_config = ConfigDict(extra="ignore")
    default_sales_account: str | None = None
    default_purchase_account: str | None = None
    default_tax_sales: str | None = None
    default_tax_purchases: str | None = None
    invoice_terms_days: int | None = None
    bill_terms_days: int | None = None
    invoice_footer: str | None = None
    mileage_rate_per_km: Decimal | None = None


# ---------------------------------------------------------------------------------------------- helpers --
def _audit(ctx, request, event, entity, entity_id, **detail):
    audit.write(f"books.{event}", user_id=ctx.user_id, username=ctx.username, org_id=ctx.org.id, entity=entity, entity_id=entity_id,
                ip=client_ip(request), detail=detail or None)


def _get_doc(db, ctx, doc_id, doc_type, lock=False):
    q = db.query(b.Doc).options(selectinload(b.Doc.lines)).filter(b.Doc.org_id == ctx.org.id, b.Doc.id == doc_id, b.Doc.doc_type == doc_type)
    if lock:
        q = q.with_for_update()
    doc = q.one_or_none()
    if doc is None:
        raise BooksError("Document not found", 404)
    return doc


def _pick_bank(db, ctx, ref):
    if ref not in (None, ""):
        return ref
    banks = bank_accounts(db, ctx.org)
    if len(banks) == 1:
        return banks[0].id
    raise BooksError("Choose the bank account (this organisation has " + ("none" if not banks else "several") + ")")


def _contact_for_payment(db, ctx, body, role):
    return find_contact(db, ctx.org, contact_id=body.contact_id, name=body.customer or body.supplier or body.contact, role=role)


def _paginate(q, limit, offset):
    total = q.count()
    return total, q.limit(limit).offset(offset).all()


def _tax_invoice_html(db, org, doc):
    e = html.escape
    title = {"invoice": "Tax Invoice", "credit_note": "Adjustment Note (Credit Note)", "quote": "Quote", "bill": "Bill",
             "supplier_credit": "Supplier Credit", "purchase_order": "Purchase Order"}[doc.doc_type]
    c = doc.contact
    rows = "".join(f"<tr><td>{e(l.description)}</td><td class=r>{l.qty:g}</td><td class=r>{l.unit_price:,.2f}</td>"
                   f"<td>{e(l.tax_code.name) if l.tax_code else ''}</td><td class=r>{l.net:,.2f}</td></tr>" for l in doc.lines)
    st = get_settings(db, org)
    return f"""<!doctype html><html><head><meta charset=utf-8><title>{e(title)} {e(doc.number)}</title><style>
body{{font-family:Arial,Helvetica,sans-serif;color:#222;margin:32px;font-size:13px}}h1{{margin:0;font-size:26px}}table{{width:100%;border-collapse:collapse;margin-top:16px}}
th,td{{padding:6px 8px;border-bottom:1px solid #ddd;text-align:left}}th{{background:#f4f4f4}}.r{{text-align:right}}.tot td{{border:0}}.big{{font-size:16px;font-weight:bold}}
.muted{{color:#666}}@media print{{body{{margin:0}}}}</style></head><body>
<h1>{e(title)}</h1><p class=muted>{e(org.legal_name or org.name)}{(' &middot; ABN ' + e(org.abn)) if org.abn else ''}</p>
<table style="margin-top:8px"><tr><td><b>{e(c.name)}</b><br>{e(c.address or '')}{('<br>ABN ' + e(c.abn)) if c.abn else ''}</td>
<td class=r>Number: <b>{e(doc.number)}</b><br>Date: {doc.issue_date:%d %b %Y}<br>{'Due' if doc.doc_type in ('invoice','bill') else 'Expires'}: {doc.due_date:%d %b %Y}
{('<br>Reference: ' + e(doc.reference)) if doc.reference else ''}</td></tr></table>
<table><tr><th>Description</th><th class=r>Qty</th><th class=r>Unit price</th><th>Tax</th><th class=r>Amount (ex GST)</th></tr>{rows}</table>
<table class=tot style="width:45%;margin-left:auto"><tr><td>Subtotal</td><td class=r>{doc.subtotal:,.2f}</td></tr><tr><td>Total GST</td><td class=r>{doc.tax_total:,.2f}</td></tr>
<tr class=big><td>Total AUD</td><td class=r>{doc.total:,.2f}</td></tr><tr><td>Amount paid / credited</td><td class=r>{(doc.amount_paid + doc.amount_credited):,.2f}</td></tr>
<tr class=big><td>Amount due</td><td class=r>{doc.amount_due:,.2f}</td></tr></table>
<p class=muted>{e(doc.terms or '')}</p><p class=muted>{e(st.get('invoice_footer') or '')}</p></body></html>"""


# ---------------------------------------------------------------------------------------------- factory --
def make_router(side: str) -> APIRouter:
    QUOTE, MAIN, CREDIT, PAY, REFUND, ROLE = D.SIDES[side]
    seg = dict(sales=dict(quote="quotes", main="invoices", credit="credit-notes", contacts="customers"),
               purchases=dict(quote="orders", main="bills", credit="credits", contacts="suppliers"))[side]
    r = APIRouter()

    def contact_row(db, c):
        due = db.query(func.coalesce(func.sum(b.Doc.total - b.Doc.amount_paid - b.Doc.amount_credited), 0)).filter(
            b.Doc.org_id == c.org_id, b.Doc.contact_id == c.id, b.Doc.doc_type == MAIN, b.Doc.status == "approved").scalar()
        return {**contact_dict(c), "owing": str(money(due))}

    # ---- contacts (customers / suppliers) ---------------------------------------------------------
    @r.get(f"/{seg['contacts']}")
    def list_contacts(q: str = "", include_archived: bool = False, ctx: OrgContext = Depends(current_org), db: Session = Depends(get_db)):
        ctx.require("read")
        flt = b.Contact.is_customer if side == "sales" else b.Contact.is_supplier
        qq = db.query(b.Contact).filter(b.Contact.org_id == ctx.org.id, flt)
        if not include_archived:
            qq = qq.filter(b.Contact.is_active.is_(True))
        if q:
            qq = qq.filter(b.Contact.name.ilike(f"%{q}%"))
        return {"items": [contact_row(db, c) for c in qq.order_by(func.lower(b.Contact.name)).limit(500)]}

    @r.post(f"/{seg['contacts']}", status_code=201)
    def create_contact(body: ContactIn, request: Request, ctx: OrgContext = Depends(current_org), db: Session = Depends(get_db)):
        ctx.require("post")
        c = upsert_contact(db, ctx, body, None, ROLE)
        db.commit()
        _audit(ctx, request, "contact.created", "contact", c.id, name=c.name)
        return contact_row(db, c)

    @r.get(f"/{seg['contacts']}/{{contact_id}}")
    def get_contact(contact_id: int, ctx: OrgContext = Depends(current_org), db: Session = Depends(get_db)):
        ctx.require("read")
        return contact_row(db, find_contact(db, ctx.org, contact_id=contact_id, role=None))

    @r.patch(f"/{seg['contacts']}/{{contact_id}}")
    def patch_contact(contact_id: int, body: ContactIn, request: Request, ctx: OrgContext = Depends(current_org), db: Session = Depends(get_db)):
        ctx.require("post")
        c = db.query(b.Contact).filter_by(org_id=ctx.org.id, id=contact_id).one_or_none()
        if c is None:
            raise BooksError("Contact not found", 404)
        upsert_contact(db, ctx, body, c, ROLE)
        db.commit()
        _audit(ctx, request, "contact.updated", "contact", c.id)
        return contact_row(db, c)

    # ---- documents ---------------------------------------------------------------------------------
    def register(segment, doc_type):
        @r.get(f"/{segment}", name=f"list_{segment}")
        def list_docs(status: str | None = None, contact_id: int | None = None, q: str | None = None,
                      date_from: date | None = Query(None, alias="from"), date_to: date | None = Query(None, alias="to"),
                      overdue: bool = False, limit: int = Query(100, le=500), offset: int = 0,
                      ctx: OrgContext = Depends(current_org), db: Session = Depends(get_db)):
            ctx.require("read")
            qq = db.query(b.Doc).options(selectinload(b.Doc.contact)).filter(b.Doc.org_id == ctx.org.id, b.Doc.doc_type == doc_type)
            if status:
                qq = qq.filter(b.Doc.status == status)
            if contact_id:
                qq = qq.filter(b.Doc.contact_id == contact_id)
            if q:
                qq = qq.join(b.Contact, b.Contact.id == b.Doc.contact_id).filter(
                    or_(b.Doc.number.ilike(f"%{q}%"), b.Doc.reference.ilike(f"%{q}%"), b.Contact.name.ilike(f"%{q}%")))
            if date_from:
                qq = qq.filter(b.Doc.issue_date >= date_from)
            if date_to:
                qq = qq.filter(b.Doc.issue_date <= date_to)
            if overdue:
                qq = qq.filter(b.Doc.status == "approved", b.Doc.due_date < date.today())
            total, rows = _paginate(qq.order_by(b.Doc.issue_date.desc(), b.Doc.id.desc()), limit, offset)
            due = sum((d.amount_due for d in rows if d.status == "approved"), Decimal("0.00"))
            return {"total": total, "items": [D.doc_dict(db, d, detail=False) for d in rows], "amount_due_on_page": str(due)}

        @r.post(f"/{segment}", status_code=201, name=f"create_{segment}")
        def create(body: DocIn, request: Request, ctx: OrgContext = Depends(current_org), db: Session = Depends(get_db)):
            ctx.require("post")
            data = body.model_dump()
            if body.status not in ("draft", "approved"):
                raise BooksError("status must be draft or approved")
            doc = D.create_doc(db, ctx.org, ctx.user_id, doc_type, data, approve=(body.status == "approved"))
            db.commit()
            _audit(ctx, request, f"{doc_type}.created", "doc", doc.id, number=doc.number, total=str(doc.total), status=doc.status)
            db.refresh(doc)
            return D.doc_dict(db, doc)

        @r.get(f"/{segment}/{{doc_id}}", name=f"get_{segment}")
        def get_(doc_id: int, ctx: OrgContext = Depends(current_org), db: Session = Depends(get_db)):
            ctx.require("read")
            return D.doc_dict(db, _get_doc(db, ctx, doc_id, doc_type))

        @r.put(f"/{segment}/{{doc_id}}", name=f"update_{segment}")
        def update(doc_id: int, body: DocPatch, request: Request, ctx: OrgContext = Depends(current_org), db: Session = Depends(get_db)):
            ctx.require("post")
            doc = _get_doc(db, ctx, doc_id, doc_type, lock=True)
            D.update_draft(db, ctx.org, doc, body.model_dump(exclude_unset=True))
            db.commit()
            _audit(ctx, request, f"{doc_type}.updated", "doc", doc.id)
            db.refresh(doc)
            return D.doc_dict(db, doc)

        @r.delete(f"/{segment}/{{doc_id}}", name=f"delete_{segment}")
        def delete(doc_id: int, request: Request, ctx: OrgContext = Depends(current_org), db: Session = Depends(get_db)):
            ctx.require("post")
            doc = _get_doc(db, ctx, doc_id, doc_type, lock=True)
            num = doc.number
            D.delete_draft(db, doc)
            db.commit()
            _audit(ctx, request, f"{doc_type}.deleted", "doc", doc_id, number=num)
            return {"deleted": True}

        @r.post(f"/{segment}/{{doc_id}}/approve", name=f"approve_{segment}")
        def approve(doc_id: int, request: Request, ctx: OrgContext = Depends(current_org), db: Session = Depends(get_db)):
            ctx.require("post")
            doc = _get_doc(db, ctx, doc_id, doc_type, lock=True)
            D.approve_doc(db, ctx.org, doc, ctx.user_id)
            db.commit()
            _audit(ctx, request, f"{doc_type}.approved", "doc", doc.id, number=doc.number, total=str(doc.total), journal_id=doc.journal_id)
            db.refresh(doc)
            return D.doc_dict(db, doc)

        @r.post(f"/{segment}/{{doc_id}}/void", name=f"void_{segment}")
        def void(doc_id: int, request: Request, ctx: OrgContext = Depends(current_org), db: Session = Depends(get_db)):
            ctx.require("post")
            doc = _get_doc(db, ctx, doc_id, doc_type, lock=True)
            D.void_doc(db, ctx.org, doc, ctx.user_id)
            db.commit()
            _audit(ctx, request, f"{doc_type}.voided", "doc", doc.id, number=doc.number)
            db.refresh(doc)
            return D.doc_dict(db, doc)

        @r.post(f"/{segment}/{{doc_id}}/send", name=f"send_{segment}")
        def send(doc_id: int, request: Request, ctx: OrgContext = Depends(current_org), db: Session = Depends(get_db)):
            ctx.require("post")
            doc = _get_doc(db, ctx, doc_id, doc_type, lock=True)
            D.mark_sent(db, doc)
            db.commit()
            _audit(ctx, request, f"{doc_type}.sent", "doc", doc.id)
            db.refresh(doc)
            return D.doc_dict(db, doc)

        @r.get(f"/{segment}/{{doc_id}}/print", response_class=HTMLResponse, name=f"print_{segment}")
        def print_(doc_id: int, ctx: OrgContext = Depends(current_org), db: Session = Depends(get_db)):
            ctx.require("read")
            return HTMLResponse(_tax_invoice_html(db, ctx.org, _get_doc(db, ctx, doc_id, doc_type)))

    register(seg["quote"], QUOTE)
    register(seg["main"], MAIN)
    register(seg["credit"], CREDIT)

    @r.post(f"/{seg['quote']}/{{doc_id}}/accept")
    def accept(doc_id: int, ctx: OrgContext = Depends(current_org), db: Session = Depends(get_db)):
        ctx.require("post")
        doc = _get_doc(db, ctx, doc_id, QUOTE, lock=True)
        if QUOTE != "quote":
            raise BooksError("Only quotes can be accepted")
        D.quote_decision(db, doc, "accepted")
        db.commit()
        return D.doc_dict(db, doc)

    @r.post(f"/{seg['quote']}/{{doc_id}}/decline")
    def decline(doc_id: int, ctx: OrgContext = Depends(current_org), db: Session = Depends(get_db)):
        ctx.require("post")
        doc = _get_doc(db, ctx, doc_id, QUOTE, lock=True)
        if QUOTE != "quote":
            raise BooksError("Only quotes can be declined")
        D.quote_decision(db, doc, "declined")
        db.commit()
        return D.doc_dict(db, doc)

    @r.post(f"/{seg['quote']}/{{doc_id}}/convert", status_code=201)
    def convert(doc_id: int, request: Request, approve: bool = True, ctx: OrgContext = Depends(current_org), db: Session = Depends(get_db)):
        ctx.require("post")
        doc = _get_doc(db, ctx, doc_id, QUOTE, lock=True)
        new = D.convert(db, ctx.org, doc, ctx.user_id, approve=approve)
        db.commit()
        _audit(ctx, request, f"{QUOTE}.converted", "doc", doc.id, to=new.number)
        db.refresh(new)
        return D.doc_dict(db, new)

    # ---- payments against one document ------------------------------------------------------------
    @r.post(f"/{seg['main']}/{{doc_id}}/payments", status_code=201)
    def pay_one(doc_id: int, body: DocPaymentIn, request: Request, ctx: OrgContext = Depends(current_org), db: Session = Depends(get_db)):
        ctx.require("post")
        doc = _get_doc(db, ctx, doc_id, MAIN, lock=True)
        amount = money(body.amount) if body.amount is not None else doc.amount_due
        p = D.record_payment(db, ctx.org, ctx.user_id, kind=PAY, contact=doc.contact, pay_date=body.date, amount=amount,
                             bank_ref=_pick_bank(db, ctx, body.bank_account), reference=body.reference or f"{doc.number}",
                             allocations=[dict(doc_id=doc.id, amount=amount)])
        db.commit()
        _audit(ctx, request, "payment.recorded", "payment", p.id, kind=PAY, amount=str(amount), doc=doc.number, journal_id=p.journal_id)
        db.refresh(doc)
        return {"payment": D.payment_dict(db, p), "document": D.doc_dict(db, doc)}

    # ---- credit documents: apply / refund ---------------------------------------------------------
    @r.post(f"/{seg['credit']}/{{doc_id}}/allocate")
    def allocate(doc_id: int, body: AllocateIn, request: Request, ctx: OrgContext = Depends(current_org), db: Session = Depends(get_db)):
        ctx.require("post")
        credit = _get_doc(db, ctx, doc_id, CREDIT, lock=True)
        D.allocate_credit(db, ctx.org, credit, [a.model_dump() for a in body.allocations], body.date)
        db.commit()
        _audit(ctx, request, f"{CREDIT}.applied", "doc", credit.id, allocations=[str(a.amount) for a in body.allocations])
        db.refresh(credit)
        return D.doc_dict(db, credit)

    @r.post(f"/{seg['credit']}/{{doc_id}}/refund", status_code=201)
    def refund(doc_id: int, body: RefundIn, request: Request, ctx: OrgContext = Depends(current_org), db: Session = Depends(get_db)):
        ctx.require("post")
        credit = _get_doc(db, ctx, doc_id, CREDIT, lock=True)
        amount = money(body.amount) if body.amount is not None else credit.amount_due
        p = D.record_payment(db, ctx.org, ctx.user_id, kind=REFUND, contact=credit.contact, pay_date=body.date, amount=amount,
                             bank_ref=_pick_bank(db, ctx, body.bank_account), reference=body.reference or f"Refund {credit.number}",
                             allocations=[dict(doc_id=credit.id, amount=amount)])
        db.commit()
        _audit(ctx, request, "payment.refunded", "payment", p.id, kind=REFUND, amount=str(amount), credit=credit.number)
        db.refresh(credit)
        return {"payment": D.payment_dict(db, p), "document": D.doc_dict(db, credit)}

    # ---- payments (multi-document, overpayments) ---------------------------------------------------
    @r.get("/payments")
    def list_payments(contact_id: int | None = None, limit: int = Query(100, le=500), offset: int = 0,
                      ctx: OrgContext = Depends(current_org), db: Session = Depends(get_db)):
        ctx.require("read")
        kinds = (PAY, REFUND)
        qq = db.query(b.Payment).options(selectinload(b.Payment.contact), selectinload(b.Payment.allocations)) \
            .filter(b.Payment.org_id == ctx.org.id, b.Payment.kind.in_(kinds))
        if contact_id:
            qq = qq.filter(b.Payment.contact_id == contact_id)
        total, rows = _paginate(qq.order_by(b.Payment.payment_date.desc(), b.Payment.id.desc()), limit, offset)
        return {"total": total, "items": [D.payment_dict(db, p) for p in rows]}

    @r.post("/payments", status_code=201)
    def create_payment(body: PaymentIn, request: Request, ctx: OrgContext = Depends(current_org), db: Session = Depends(get_db)):
        ctx.require("post")
        contact = _contact_for_payment(db, ctx, body, ROLE)
        p = D.record_payment(db, ctx.org, ctx.user_id, kind=PAY, contact=contact, pay_date=body.date, amount=body.amount,
                             bank_ref=_pick_bank(db, ctx, body.bank_account), reference=body.reference,
                             allocations=[a.model_dump() for a in body.allocations], overpayment=body.overpayment)
        db.commit()
        _audit(ctx, request, "payment.recorded", "payment", p.id, kind=PAY, amount=str(p.amount), journal_id=p.journal_id)
        return D.payment_dict(db, p)

    def _get_payment(db, ctx, pid):
        p = db.query(b.Payment).options(selectinload(b.Payment.allocations), selectinload(b.Payment.contact)) \
            .filter(b.Payment.org_id == ctx.org.id, b.Payment.id == pid, b.Payment.kind.in_((PAY, REFUND))).with_for_update().one_or_none()
        if p is None:
            raise BooksError("Payment not found", 404)
        return p

    @r.get("/payments/{payment_id}")
    def get_payment(payment_id: int, ctx: OrgContext = Depends(current_org), db: Session = Depends(get_db)):
        ctx.require("read")
        return D.payment_dict(db, _get_payment(db, ctx, payment_id))

    @r.post("/payments/{payment_id}/allocate")
    def alloc_payment(payment_id: int, body: AllocateIn, request: Request, ctx: OrgContext = Depends(current_org), db: Session = Depends(get_db)):
        ctx.require("post")
        p = _get_payment(db, ctx, payment_id)
        D.allocate_payment(db, ctx.org, p, [a.model_dump() for a in body.allocations])
        db.commit()
        _audit(ctx, request, "payment.allocated", "payment", p.id)
        return D.payment_dict(db, p)

    @r.delete("/payments/{payment_id}")
    def reverse_payment(payment_id: int, request: Request, ctx: OrgContext = Depends(current_org), db: Session = Depends(get_db)):
        ctx.require("post")
        p = _get_payment(db, ctx, payment_id)
        D.reverse_payment(db, ctx.org, p, ctx.user_id)
        db.commit()
        _audit(ctx, request, "payment.reversed", "payment", p.id)
        return D.payment_dict(db, p)

    return r


sales_router = make_router("sales")
purchases_router = make_router("purchases")


# ---------------------------------------------------------------------------------------------- contacts --
def upsert_contact(db, ctx, body: ContactIn, c, role):
    org = ctx.org
    name = (body.name or "").strip()
    if not name:
        raise BooksError("Name is required")
    if body.abn:
        digits = "".join(ch for ch in body.abn if ch.isdigit())
        if not valid_abn(digits):
            raise BooksError(f"'{body.abn}' is not a valid ABN (checksum failed)")
        body.abn = digits
    dup = db.query(b.Contact).filter(b.Contact.org_id == org.id, func.lower(b.Contact.name) == name.lower(), b.Contact.id != (c.id if c else 0)).first()
    if dup:
        raise BooksError(f"A contact named '{dup.name}' already exists", 409)
    if c is None:
        c = b.Contact(org_id=org.id, name=name, is_customer=(role == "customer"), is_supplier=(role == "supplier"),
                      terms_days=14 if role == "customer" else 30)
        db.add(c)
    c.name = name[:255]
    for f in ("email", "phone", "abn", "address", "notes", "credit_limit", "terms_days", "is_active", "is_customer", "is_supplier"):
        v = getattr(body, f)
        if v is not None:
            setattr(c, f, v)
    if body.default_account not in (None, ""):
        c.default_account_id = get_account(db, org, body.default_account, what="Default account").id
    if body.default_tax_code not in (None, ""):
        c.default_tax_code_id = get_tax(db, org, body.default_tax_code).id
    if not (c.is_customer or c.is_supplier):
        raise BooksError("A contact must be a customer, a supplier or both")
    db.flush()
    return c


contacts_router = APIRouter()


@contacts_router.get("")
def all_contacts(q: str = "", role: str | None = None, include_archived: bool = False, ctx: OrgContext = Depends(current_org),
                 db: Session = Depends(get_db)):
    ctx.require("read")
    qq = db.query(b.Contact).filter(b.Contact.org_id == ctx.org.id)
    if role == "customer":
        qq = qq.filter(b.Contact.is_customer)
    elif role == "supplier":
        qq = qq.filter(b.Contact.is_supplier)
    if not include_archived:
        qq = qq.filter(b.Contact.is_active.is_(True))
    if q:
        qq = qq.filter(b.Contact.name.ilike(f"%{q}%"))
    return {"items": [contact_dict(c) for c in qq.order_by(func.lower(b.Contact.name)).limit(1000)]}


@contacts_router.post("/import")
async def import_contacts(request: Request, file: UploadFile = File(...), role: str = "customer", ctx: OrgContext = Depends(current_org),
                          db: Session = Depends(get_db)):
    """CSV columns (header row, any order): name, email, phone, abn, address, terms_days.  Existing names are updated, not duplicated."""
    ctx.require("post")
    require_bulk_import(db, ctx)
    if role not in ("customer", "supplier"):
        raise BooksError("role must be customer or supplier")
    raw = (await file.read()).decode("utf-8-sig", errors="replace")
    if len(raw) > 2_000_000:
        raise BooksError("File too large (2 MB max)", 413)
    rdr = csv.DictReader(io.StringIO(raw))
    if not rdr.fieldnames or "name" not in [f.strip().lower() for f in rdr.fieldnames]:
        raise BooksError("The CSV needs a header row with at least a 'name' column")
    created = updated = 0
    errors = []
    for n, row in enumerate(rdr, start=2):
        row = {(k or "").strip().lower(): (v or "").strip() for k, v in row.items()}
        if not row.get("name"):
            continue
        try:
            existing = db.query(b.Contact).filter(b.Contact.org_id == ctx.org.id, func.lower(b.Contact.name) == row["name"].lower()).first()
            body = ContactIn(name=row["name"], email=row.get("email") or None, phone=row.get("phone") or None, abn=row.get("abn") or None,
                             address=row.get("address") or None, terms_days=int(row["terms_days"]) if row.get("terms_days") else None)
            if existing and not (existing.is_customer if role == "customer" else existing.is_supplier):
                body.is_customer, body.is_supplier = (True, None) if role == "customer" else (None, True)
            with db.begin_nested():
                upsert_contact(db, ctx, body, existing, role)
            updated += 1 if existing else 0
            created += 0 if existing else 1
        except (BooksError, ValueError) as e:
            errors.append({"row": n, "name": row["name"], "error": str(e)})
    db.commit()
    _audit(ctx, request, "contact.imported", "contact", None, created=created, updated=updated, errors=len(errors))
    return {"created": created, "updated": updated, "errors": errors}


# ---------------------------------------------------------------------------------------------- attachments --
attachments_router = APIRouter()
MAX_ATTACH = 5 * 1024 * 1024
ALLOWED_TYPES = ("application/pdf", "image/png", "image/jpeg", "image/gif", "image/webp", "text/plain", "text/csv")


def _owner_check(db, ctx, kind, oid):
    if kind == "doc":
        ok = db.query(b.Doc.id).filter_by(org_id=ctx.org.id, id=oid).first()
    elif kind == "expense_item":
        ok = db.query(b.ExpenseItem.id).filter_by(org_id=ctx.org.id, id=oid).first()
    elif kind == "bank_line":
        ok = db.query(b.BankLine.id).filter_by(org_id=ctx.org.id, id=oid).first()
    elif kind == "journal":
        ok = db.query(lm.Journal.id).filter_by(org_id=ctx.org.id, id=oid).first()
    elif kind == "journal_draft":
        from accfino.modules.accounting.ledger.journal_models import JournalDraft
        ok = db.query(JournalDraft.id).filter_by(org_id=ctx.org.id, id=oid).first()
    else:
        raise BooksError("owner_kind must be doc, expense_item, bank_line, journal or journal_draft")
    if not ok:
        raise BooksError("The record to attach to was not found", 404)


@attachments_router.post("", status_code=201)
async def upload(owner_kind: str, owner_id: int, request: Request, file: UploadFile = File(...), ctx: OrgContext = Depends(current_org),
                 db: Session = Depends(get_db)):
    ctx.require("post")
    _owner_check(db, ctx, owner_kind, owner_id)
    data = await file.read()
    if not data:
        raise BooksError("The file is empty")
    if len(data) > MAX_ATTACH:
        raise BooksError("Files are limited to 5 MB", 413)
    ctype = (file.content_type or "").lower()
    if ctype not in ALLOWED_TYPES:
        raise BooksError(f"File type '{ctype or 'unknown'}' is not allowed (PDF, images, text/CSV)", 415)
    a = b.Attachment(org_id=ctx.org.id, owner_kind=owner_kind, owner_id=owner_id, filename=(file.filename or "file")[:255],
                     content_type=ctype, size=len(data), data=data, uploaded_by=ctx.user_id)
    db.add(a)
    db.commit()
    _audit(ctx, request, "attachment.added", owner_kind, owner_id, filename=a.filename, size=a.size)
    return dict(id=a.id, filename=a.filename, size=a.size, content_type=a.content_type)


@attachments_router.get("")
def list_attachments(owner_kind: str, owner_id: int, ctx: OrgContext = Depends(current_org), db: Session = Depends(get_db)):
    ctx.require("read")
    rows = db.query(b.Attachment).filter_by(org_id=ctx.org.id, owner_kind=owner_kind, owner_id=owner_id).order_by(b.Attachment.id).all()
    return {"items": [dict(id=a.id, filename=a.filename, size=a.size, content_type=a.content_type, created_at=a.created_at.isoformat()) for a in rows]}


@attachments_router.get("/{attachment_id}/download")
def download(attachment_id: int, ctx: OrgContext = Depends(current_org), db: Session = Depends(get_db)):
    ctx.require("read")
    a = db.query(b.Attachment).filter_by(org_id=ctx.org.id, id=attachment_id).one_or_none()
    if a is None:
        raise BooksError("Attachment not found", 404)
    safe = "".join(ch for ch in a.filename if ch.isalnum() or ch in "._- ") or "file"
    return Response(a.data, media_type=a.content_type or "application/octet-stream",
                    headers={"Content-Disposition": f'attachment; filename="{safe}"', "X-Content-Type-Options": "nosniff"})


@attachments_router.delete("/{attachment_id}")
def delete_attachment(attachment_id: int, request: Request, ctx: OrgContext = Depends(current_org), db: Session = Depends(get_db)):
    ctx.require("post")
    a = db.query(b.Attachment).filter_by(org_id=ctx.org.id, id=attachment_id).one_or_none()
    if a is None:
        raise BooksError("Attachment not found", 404)
    db.delete(a)
    db.commit()
    _audit(ctx, request, "attachment.removed", a.owner_kind, a.owner_id, filename=a.filename)
    return {"deleted": True}


# ---------------------------------------------------------------------------------------------- settings --
settings_router = APIRouter()


@settings_router.get("")
def read_settings(ctx: OrgContext = Depends(current_org), db: Session = Depends(get_db)):
    ctx.require("read")
    st = get_settings(db, ctx.org)
    return {**st, "bank_accounts": [dict(id=a.id, code=a.code, name=a.name, type=a.account_type) for a in bank_accounts(db, ctx.org)]}


@settings_router.put("")
def write_settings(body: SettingsIn, request: Request, ctx: OrgContext = Depends(current_org), db: Session = Depends(get_db)):
    ctx.require("settings")
    patch = {k: v for k, v in body.model_dump(exclude_unset=True).items() if v is not None}
    for k in ("default_sales_account", "default_purchase_account"):
        if k in patch:
            patch[k] = get_account(db, ctx.org, patch[k]).code
    for k in ("default_tax_sales", "default_tax_purchases"):
        if k in patch:
            patch[k] = get_tax(db, ctx.org, patch[k]).code
    if "mileage_rate_per_km" in patch:
        patch["mileage_rate_per_km"] = str(patch["mileage_rate_per_km"])
    st = save_settings(db, ctx.org, patch)
    db.commit()
    _audit(ctx, request, "settings.updated", "organisation", ctx.org.id, keys=sorted(patch))
    return st
