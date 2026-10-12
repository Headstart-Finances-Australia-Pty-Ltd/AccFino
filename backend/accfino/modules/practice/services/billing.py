"""Billing: rates, time (draft -> submitted -> approved/rejected -> billed / written_off), invoices generated from approved time and issued through the existing Accounting
receivables ledger (no second ledger), idempotent issuance, voiding, credit notes, write-offs and the billing dashboard. Amounts are exact decimals (half-up cents)."""
import datetime as dt
from decimal import Decimal, InvalidOperation

from sqlalchemy import func
from sqlalchemy.exc import IntegrityError

import accfino.modules.accounting.public as accounting
from accfino.core import models as m
from accfino.modules.practice.engine import billing as B
from accfino.modules.practice.models import practice as P
from accfino.modules.practice.services import core
from accfino.modules.practice.services.core import Access, Conflict, Forbidden, NotFound, PcError

MAX_MIN = 24 * 60


def _money(v, name, *, positive=True) -> Decimal:
    try:
        d = Decimal(str(v)).quantize(Decimal("0.01"))
    except (InvalidOperation, TypeError):
        raise PcError(f"{name} must be a number")
    if positive and d <= 0:
        raise PcError(f"{name} must be greater than zero")
    return d


def _books_error(e):
    return PcError(str(e), getattr(e, "status", 422))


# ------------------------------------------------------------------ rates
def set_rate(db, ctx, a: Access, hourly_rate, *, user_id=None, client_id=None, service_type=None, effective_from=None, effective_to=None) -> dict:
    a.require("billing_admin")
    rate = _money(hourly_rate, "Hourly rate")
    if rate > 5000:
        raise PcError("Hourly rate looks too high (limit 5,000)")
    if user_id:
        a.require_member_user(user_id, "Staff member")
    if client_id:
        a.client(client_id, billing=True)
    ef, et = core.parse_date(effective_from, "Effective from", core.today()), core.parse_date(effective_to, "Effective to")
    if et and et < ef:
        raise PcError("Effective to cannot be before effective from")
    r = P.PcRate(practice_id=a.practice_id, user_id=user_id, client_id=client_id, service_type=service_type, hourly_rate=rate, effective_from=ef, effective_to=et, created_by=ctx.user_id)
    db.add(r)
    db.flush()
    core.audit(db, ctx, a.practice_id, "rate.set", "rate", r.id, user=user_id, client=client_id, service=service_type, rate=rate, effective_from=ef)
    return rdict(r)


def rdict(r):
    return dict(id=r.id, staff_id=r.user_id, client_id=r.client_id, service_type=r.service_type, hourly_rate=core.plain(r.hourly_rate), effective_from=core.plain(r.effective_from), effective_to=core.plain(r.effective_to))


def rates(db, a: Access) -> list:
    a.require("billing")
    return [rdict(r) for r in db.query(P.PcRate).filter_by(practice_id=a.practice_id).order_by(P.PcRate.effective_from.desc(), P.PcRate.id.desc())]


def _rate_pool(db, a: Access):
    return [dict(id=r.id, user_id=r.user_id, client_id=r.client_id, service_type=r.service_type, hourly_rate=r.hourly_rate, effective_from=r.effective_from, effective_to=r.effective_to)
            for r in db.query(P.PcRate).filter_by(practice_id=a.practice_id)]


# ------------------------------------------------------------------ time
def tdict(t: P.PcTimeEntry) -> dict:
    return dict(id=t.id, staff_id=t.user_id, client_id=t.client_id, entity_id=t.entity_id, engagement_id=t.engagement_id, job_id=t.job_id, task_id=t.task_id, work_date=core.plain(t.work_date),
                minutes=t.minutes, hours=str(B.hours(t.minutes)), description=t.description, billable=t.billable, status=t.status, rate_applied=core.plain(t.rate_applied), rate_source=t.rate_source,
                amount=core.plain(t.amount), rejection_reason=t.rejection_reason, approved_by=t.approved_by)


def _trow(db, a: Access, tid, *, billing=False) -> P.PcTimeEntry:
    t = db.query(P.PcTimeEntry).filter_by(practice_id=a.practice_id, id=tid).first()
    if t is None:
        raise NotFound("Time entry")
    if t.user_id != a.ctx.user_id:
        a.client(t.client_id, billing=billing or a.role == "billing")          # others' time is visible only through the client scope
    return t


def log_time(db, ctx, a: Access, client_id: int, work_date, minutes, description, *, billable=True, engagement_id=None, job_id=None, task_id=None, entity_id=None, for_staff_id=None) -> dict:
    a.require("time")
    owner = ctx.user_id
    if for_staff_id and for_staff_id != ctx.user_id:         # recording time FOR someone else (e.g. loading a timesheet) is a billing-administration action and is audited as such
        a.require("billing_admin")
        a.require_member_user(for_staff_id, "Staff member")
        owner = for_staff_id
    c = a.client(client_id, allow_archived=False)
    wd = core.parse_date(work_date, "Work date")
    if wd is None or wd > core.today():
        raise PcError("The work date cannot be in the future")
    try:
        mins = int(minutes)
    except (TypeError, ValueError):
        raise PcError("Minutes must be a whole number")
    if not 1 <= mins <= MAX_MIN:
        raise PcError("Minutes must be between 1 and 1440")
    if engagement_id:
        e = db.query(P.PcEngagement).filter_by(practice_id=a.practice_id, id=engagement_id, client_id=c.id).first()
        if e is None:
            raise PcError("That engagement does not belong to this client")
        if e.status in ("terminated", "archived"):
            raise Conflict("The engagement is closed")
    if job_id and not db.query(P.PcJob.id).filter_by(practice_id=a.practice_id, id=job_id, client_id=c.id).first():
        raise PcError("That job does not belong to this client")
    t = P.PcTimeEntry(practice_id=a.practice_id, user_id=owner, client_id=c.id, entity_id=entity_id, engagement_id=engagement_id, job_id=job_id, task_id=task_id, work_date=wd, minutes=mins,
                      description=core.text(description, "Description", required=True, max_len=500), billable=bool(billable))
    db.add(t)
    db.flush()
    core.audit(db, ctx, a.practice_id, "time.logged", "time_entry", t.id, client_id=c.id, minutes=mins, on_behalf_of=owner if owner != ctx.user_id else None)
    return tdict(t)


def update_time(db, ctx, a: Access, tid: int, body: dict) -> dict:
    a.require("time")
    t = _trow(db, a, tid)
    if t.user_id != ctx.user_id:
        raise Forbidden("You can only change your own time")
    if t.status not in ("draft", "rejected"):
        raise Conflict(f"A {t.status.replace('_', ' ')} time entry cannot be edited. Ask for a correction instead.")
    if "minutes" in body:
        mins = int(body["minutes"])
        if not 1 <= mins <= MAX_MIN:
            raise PcError("Minutes must be between 1 and 1440")
        t.minutes = mins
    if "description" in body:
        t.description = core.text(body["description"], "Description", required=True, max_len=500)
    if "work_date" in body:
        wd = core.parse_date(body["work_date"], "Work date")
        if wd > core.today():
            raise PcError("The work date cannot be in the future")
        t.work_date = wd
    if "billable" in body:
        t.billable = bool(body["billable"])
    if t.status == "rejected":
        t.status, t.rejection_reason = "draft", None
    db.flush()
    core.audit(db, ctx, a.practice_id, "time.edited", "time_entry", t.id)
    return tdict(t)


def delete_time(db, ctx, a: Access, tid: int) -> dict:
    a.require("time")
    t = _trow(db, a, tid)
    if t.user_id != ctx.user_id:
        raise Forbidden("You can only delete your own time")
    if t.status != "draft":
        raise Conflict("Only draft time can be deleted")
    db.delete(t)
    db.flush()
    core.audit(db, ctx, a.practice_id, "time.deleted", "time_entry", tid)
    return dict(deleted=tid)


def submit_time(db, ctx, a: Access, ids) -> dict:
    a.require("time")
    done, skipped = [], []
    for tid in dict.fromkeys(ids or []):
        try:
            t = _trow(db, a, tid)
            if t.user_id != ctx.user_id:
                raise Forbidden("Not your time")
            if t.status != "draft":
                raise Conflict(f"Already {t.status}")
            t.status, t.submitted_at = "submitted", core.now()
            done.append(t.id)
        except PcError as e:
            skipped.append(dict(id=tid, reason=e.message))
    db.flush()
    core.audit(db, ctx, a.practice_id, "time.submitted", "time_entry", None, ids=done)
    return dict(updated=done, skipped=skipped)


def approve_time(db, ctx, a: Access, ids) -> dict:
    """Snapshots the applicable rate and amount at approval. The approver can never approve their own time."""
    a.require("time_approve")
    pool = _rate_pool(db, a)
    done, skipped = [], []
    for tid in dict.fromkeys(ids or []):
        try:
            t = _trow(db, a, tid, billing=True)
            if t.user_id == ctx.user_id:
                raise Forbidden("You cannot approve your own time")
            if t.status != "submitted":
                raise Conflict(f"Only submitted time can be approved (this is {t.status})")
            if t.billable:
                svc = db.query(P.PcEngagement.service_type).filter_by(id=t.engagement_id).scalar() if t.engagement_id else None
                r = B.pick_rate(pool, user_id=t.user_id, client_id=t.client_id, service_type=svc, on_date=t.work_date)
                if r is None:
                    raise PcError("No hourly rate applies to this time. Set a rate first.")
                t.rate_applied, t.amount = r["hourly_rate"], B.time_amount(t.minutes, r["hourly_rate"])
                t.rate_source = "-".join(k for k in ("client" if r["client_id"] else "", "user" if r["user_id"] else "", "service" if r["service_type"] else "") if k) or "default"
            else:
                t.rate_applied, t.amount, t.rate_source = None, Decimal("0.00"), "non_billable"
            t.status, t.approved_by, t.approved_at = "approved", ctx.user_id, core.now()
            done.append(t.id)
        except PcError as e:
            skipped.append(dict(id=tid, reason=e.message))
    db.flush()
    core.audit(db, ctx, a.practice_id, "time.approved", "time_entry", None, ids=done)
    return dict(updated=done, skipped=skipped)


def reject_time(db, ctx, a: Access, ids, reason: str) -> dict:
    a.require("time_approve")
    if not core.text(reason, "Reason", required=True, max_len=300):
        raise PcError("A reason is required")
    done, skipped = [], []
    for tid in dict.fromkeys(ids or []):
        try:
            t = _trow(db, a, tid, billing=True)
            if t.user_id == ctx.user_id:
                raise Forbidden("You cannot review your own time")
            if t.status != "submitted":
                raise Conflict(f"Only submitted time can be rejected (this is {t.status})")
            t.status, t.rejection_reason = "rejected", reason.strip()
            done.append(t.id)
        except PcError as e:
            skipped.append(dict(id=tid, reason=e.message))
    db.flush()
    core.audit(db, ctx, a.practice_id, "time.rejected", "time_entry", None, ids=done, reason=reason[:200])
    return dict(updated=done, skipped=skipped)


def list_time(db, a: Access, *, mine=False, client_id=None, status=None, user_id=None, date_from=None, date_to=None, page_no=1, size=50) -> dict:
    a.require("time")
    q = db.query(P.PcTimeEntry).filter(P.PcTimeEntry.practice_id == a.practice_id)
    if mine or not a.can("time_approve"):
        q = q.filter(P.PcTimeEntry.user_id == a.ctx.user_id)
    else:
        q = q.filter((P.PcTimeEntry.user_id == a.ctx.user_id) | P.PcTimeEntry.client_id.in_(a.client_ids(billing=True)))
    for col, v in ((P.PcTimeEntry.client_id, client_id), (P.PcTimeEntry.status, status), (P.PcTimeEntry.user_id, user_id)):
        if v:
            q = q.filter(col == v)
    if date_from:
        q = q.filter(P.PcTimeEntry.work_date >= core.parse_date(date_from, "From"))
    if date_to:
        q = q.filter(P.PcTimeEntry.work_date <= core.parse_date(date_to, "To"))
    meta, q = core.page(q.order_by(P.PcTimeEntry.work_date.desc(), P.PcTimeEntry.id.desc()), page_no, size)
    return dict(**meta, items=[tdict(t) for t in q])


def write_off(db, ctx, a: Access, tid: int, reason: str) -> dict:
    """Explicit workflow: an approved, unbilled entry is written off with a reason and an approver. The value is kept (PcWriteOff), the entry is never deleted."""
    a.require("writeoff")
    t = _trow(db, a, tid, billing=True)
    if t.status != "approved" or not t.billable or not t.amount or t.amount <= 0:
        raise Conflict("Only approved, billable, unbilled time with a value can be written off")
    if db.query(P.PcInvoiceLine.id).filter_by(time_entry_id=t.id).filter(P.PcInvoiceLine.active_time_key.isnot(None)).first():
        raise Conflict("This time is on a draft or issued invoice")
    if not core.text(reason, "Reason", required=True, max_len=300):
        raise PcError("A reason is required")
    db.add(P.PcWriteOff(practice_id=a.practice_id, time_entry_id=t.id, amount=t.amount, reason=reason.strip(), approved_by=ctx.user_id))
    t.status = "written_off"
    db.flush()
    core.audit(db, ctx, a.practice_id, "time.written_off", "time_entry", t.id, amount=t.amount, reason=reason[:200])
    return tdict(t)


# ------------------------------------------------------------------ invoices
def _tax_rate(a: Access, org) -> Decimal:
    if not org.gst_registered:
        return Decimal("0")
    return Decimal(str(a.settings.get("billing", {}).get("tax_rate", "0.10")))


def idict(db, inv: P.PcInvoice, org=None, detail=False) -> dict:
    d = dict(id=inv.id, client_id=inv.client_id, engagement_id=inv.engagement_id, status=inv.status, issue_date=core.plain(inv.issue_date), due_date=core.plain(inv.due_date), reference=inv.reference,
             net=core.plain(inv.net), tax=core.plain(inv.tax), total=core.plain(inv.total), accounting_doc_id=inv.accounting_doc_id, accounting_number=inv.accounting_number,
             idempotency_key=inv.idempotency_key, visible_to_client=inv.visible_to_client, void_reason=inv.void_reason, credit_doc_ids=inv.credit_doc_ids or [])
    if org is not None and inv.accounting_doc_id:
        s = accounting.sales_document(db, org.id, inv.accounting_doc_id)
        if s:
            d["payment"] = dict(status=s["status"], paid=str(s["amount_paid"]), credited=str(s["amount_credited"]), due=str(s["amount_due"]))
    if detail:
        d["lines"] = [dict(id=l.id, kind=l.kind, description=l.description, quantity=core.plain(l.quantity), unit_price=core.plain(l.unit_price), amount=core.plain(l.amount), tax_rate=core.plain(l.tax_rate),
                           time_entry_id=l.time_entry_id, reason=l.reason) for l in db.query(P.PcInvoiceLine).filter_by(invoice_id=inv.id).order_by(P.PcInvoiceLine.id)]
    return d


def irow(db, a: Access, iid: int, *, lock=False) -> P.PcInvoice:
    q = db.query(P.PcInvoice).filter_by(practice_id=a.practice_id, id=iid)
    inv = (q.with_for_update() if lock else q).first()
    if inv is None:
        raise NotFound("Invoice")
    a.client(inv.client_id, billing=True)
    return inv


def _recompute(db, inv: P.PcInvoice):
    lines = db.query(P.PcInvoiceLine).filter_by(invoice_id=inv.id).all()
    t = B.invoice_totals([dict(amount=l.amount, tax_rate=l.tax_rate) for l in lines])
    inv.net, inv.tax, inv.total = t["net"], t["tax"], t["total"]


def generate(db, ctx, a: Access, client_id: int, *, time_entry_ids=None, engagement_id=None, fixed_fee_engagement_id=None, adjustments=None, idempotency_key=None, reference=None) -> dict:
    """Draft invoice from approved, unbilled, billable time (all of the client's, or the ids given) and/or an engagement's fixed fee. Replaying the same idempotency key returns the same invoice."""
    a.require("billing")
    org = ctx.org
    c = a.client(client_id, billing=True)
    if idempotency_key:
        ex = db.query(P.PcInvoice).filter_by(practice_id=a.practice_id, idempotency_key=idempotency_key).first()
        if ex is not None:
            if ex.client_id != c.id:
                raise Conflict("That idempotency key was used for a different client", "idempotency_conflict")
            return dict(idict(db, ex, org, True), replayed=True)
    rate = _tax_rate(a, org)
    q = db.query(P.PcTimeEntry).filter(P.PcTimeEntry.practice_id == a.practice_id, P.PcTimeEntry.client_id == c.id, P.PcTimeEntry.status == "approved", P.PcTimeEntry.billable.is_(True),
                                       P.PcTimeEntry.amount > 0)
    if time_entry_ids is not None:
        ids = list(dict.fromkeys(time_entry_ids))
        found = {t.id: t for t in q.filter(P.PcTimeEntry.id.in_(ids or [0]))}
        bad = [i for i in ids if i not in found]
        if bad:
            raise Conflict(f"Time entries {bad} are not approved, billable and unbilled for this client", "not_billable")
        entries = [found[i] for i in ids]
    else:
        entries = q.order_by(P.PcTimeEntry.work_date, P.PcTimeEntry.id).all()
        if engagement_id:
            entries = [t for t in entries if t.engagement_id == engagement_id]
    fixed = None
    if fixed_fee_engagement_id:
        fixed = db.query(P.PcEngagement).filter_by(practice_id=a.practice_id, id=fixed_fee_engagement_id, client_id=c.id).first()
        if fixed is None or fixed.billing_basis != "fixed" or not fixed.fixed_fee:
            raise PcError("That engagement is not a fixed-fee engagement for this client")
        if db.query(P.PcInvoiceLine.id).join(P.PcInvoice, P.PcInvoice.id == P.PcInvoiceLine.invoice_id).filter(P.PcInvoice.practice_id == a.practice_id, P.PcInvoice.status != "voided",
                                                                                                                P.PcInvoiceLine.kind == "fixed", P.PcInvoiceLine.reason == f"engagement:{fixed.id}").first():
            raise Conflict("The fixed fee for this engagement is already invoiced", "already_billed")
    # time on fixed-fee engagements is not billed by the hour
    fixed_eng = {e for (e,) in db.query(P.PcEngagement.id).filter_by(practice_id=a.practice_id, client_id=c.id, billing_basis="fixed")}
    if time_entry_ids is not None and any(t.engagement_id in fixed_eng for t in entries):
        raise Conflict("Time on a fixed-fee engagement is not billed by the hour", "fixed_fee_time")
    entries = [t for t in entries if t.engagement_id not in fixed_eng]
    if not entries and not fixed and not adjustments:
        raise Conflict("There is nothing to invoice for this client", "nothing_to_bill")
    inv = P.PcInvoice(practice_id=a.practice_id, client_id=c.id, engagement_id=engagement_id or (fixed.id if fixed else None), status="draft", reference=core.text(reference, "Reference", max_len=100),
                      idempotency_key=core.text(idempotency_key, "Idempotency key", max_len=80), created_by=ctx.user_id)
    db.add(inv)
    db.flush()
    try:
        with db.begin_nested():
            for t in entries:
                db.add(P.PcInvoiceLine(practice_id=a.practice_id, invoice_id=inv.id, kind="time", description=f"{t.work_date.isoformat()} {t.description}"[:500], quantity=B.hours(t.minutes),
                                       unit_price=t.rate_applied, tax_rate=rate, amount=t.amount, time_entry_id=t.id, active_time_key=t.id, created_by=ctx.user_id))
            if fixed:
                db.add(P.PcInvoiceLine(practice_id=a.practice_id, invoice_id=inv.id, kind="fixed", description=f"{fixed.title} (fixed fee)", quantity=1, unit_price=fixed.fixed_fee, tax_rate=rate,
                                       amount=fixed.fixed_fee, reason=f"engagement:{fixed.id}", created_by=ctx.user_id))
            db.flush()
    except IntegrityError:
        raise Conflict("Some of that time is already on another invoice", "already_billed")
    for adj in adjustments or []:
        _add_adjustment(db, ctx, a, inv, adj.get("description"), adj.get("amount"), adj.get("reason"), rate)
    _recompute(db, inv)
    db.flush()
    core.audit(db, ctx, a.practice_id, "invoice.drafted", "invoice", inv.id, client_id=c.id, entries=[t.id for t in entries], total=inv.total)
    return dict(idict(db, inv, org, True), replayed=False)


def _add_adjustment(db, ctx, a, inv, description, amount, reason, rate):
    amt = _money(amount, "Adjustment amount", positive=False)
    if amt == 0:
        raise PcError("Adjustment amount cannot be zero")
    if not core.text(reason, "Reason", required=True, max_len=300):
        raise PcError("An adjustment needs a reason")
    db.add(P.PcInvoiceLine(practice_id=a.practice_id, invoice_id=inv.id, kind="discount" if amt < 0 else "adjustment", description=core.text(description, "Description", required=True, max_len=500),
                           quantity=1, unit_price=amt, tax_rate=rate, amount=amt, reason=reason.strip(), created_by=ctx.user_id))


def add_adjustment(db, ctx, a: Access, iid: int, description, amount, reason) -> dict:
    a.require("billing_admin")
    inv = irow(db, a, iid, lock=True)
    if inv.status != "draft":
        raise Conflict("Adjustments can only be made on a draft invoice. Use a credit note after issue.")
    _add_adjustment(db, ctx, a, inv, description, amount, reason, _tax_rate(a, ctx.org))
    db.flush()
    _recompute(db, inv)
    if inv.total < 0:
        raise PcError("The invoice total cannot be negative")
    db.flush()
    core.audit(db, ctx, a.practice_id, "invoice.adjusted", "invoice", inv.id, amount=amount, reason=reason[:200])
    return idict(db, inv, ctx.org, True)


def _contact_for(db, a: Access, org, c: P.PcClient) -> int:
    if c.billing_contact_id:
        ex = accounting.contact(db, org.id, c.billing_contact_id)
        if ex:
            return ex["id"]
    name = f"{c.legal_name}"
    ct, _ = accounting.create_contact(db, org.id, name=name, email=c.email, phone=c.phone)
    c.billing_contact_id = ct["id"]
    db.flush()
    return ct["id"]


def issue(db, ctx, a: Access, iid: int, *, issue_date=None) -> dict:
    """Posts the invoice to the practice's receivables ledger through the Accounting facade. Replay-safe: an already issued invoice is returned, never re-posted."""
    a.require("billing_admin")
    inv = irow(db, a, iid, lock=True)
    if inv.status == "issued":
        return dict(idict(db, inv, ctx.org, True), replayed=True)
    if inv.status != "draft":
        raise Conflict(f"A {inv.status} invoice cannot be issued", "invalid_transition")
    lines_db = db.query(P.PcInvoiceLine).filter_by(invoice_id=inv.id).order_by(P.PcInvoiceLine.id).all()
    if not lines_db or inv.total <= 0:
        raise Conflict("The invoice has nothing to charge", "empty_invoice")
    for l in lines_db:                                       # the time must still be exactly what was approved
        if l.time_entry_id:
            t = db.get(P.PcTimeEntry, l.time_entry_id)
            if t.status != "approved" or t.amount != l.amount:
                raise Conflict("Time on this invoice changed after it was drafted", "stale")
    c = db.get(P.PcClient, inv.client_id)
    cfg = a.settings.get("billing", {})
    idate = core.parse_date(issue_date, "Issue date", core.today())
    due = idate + dt.timedelta(days=int(cfg.get("payment_terms_days", 14)))
    contact_id = _contact_for(db, a, ctx.org, c)
    acc_lines = [dict(description=l.description, qty=1, unit_price=str(l.amount), account=cfg.get("revenue_account", "200")) for l in lines_db]
    try:
        with db.begin_nested():
            doc = accounting.create_sales_invoice(db, ctx.org, ctx.user_id, contact_id=contact_id, issue_date=idate, due_date=due, reference=inv.reference or f"PC-{inv.id}", lines=acc_lines)
            if Decimal(doc["total"]) != inv.total or Decimal(doc["subtotal"]) != inv.net:
                raise Conflict(f"The Accounting tax settings give a total of {doc['total']} but the invoice says {inv.total}. Check the practice tax rate and the revenue account's tax code.", "total_mismatch")
    except Exception as e:                                   # BooksError and friends: nothing was posted (savepoint rolled back)
        if isinstance(e, PcError):
            raise
        if hasattr(e, "status"):
            raise _books_error(e)
        raise
    inv.accounting_doc_id, inv.accounting_number, inv.status = doc["id"], doc["number"], "issued"
    inv.issue_date, inv.due_date, inv.issued_by, inv.issued_at = idate, due, ctx.user_id, core.now()
    for l in lines_db:
        if l.time_entry_id:
            db.get(P.PcTimeEntry, l.time_entry_id).status = "billed"
    try:
        db.flush()
    except IntegrityError:
        raise Conflict("This invoice was issued by another request", "already_issued")
    core.audit(db, ctx, a.practice_id, "invoice.issued", "invoice", inv.id, accounting_doc=doc["id"], number=doc["number"], total=inv.total)
    return dict(idict(db, inv, ctx.org, True), replayed=False)


def void(db, ctx, a: Access, iid: int, reason: str) -> dict:
    a.require("billing_admin")
    inv = irow(db, a, iid, lock=True)
    if not core.text(reason, "Reason", required=True, max_len=300):
        raise PcError("A reason is required")
    if inv.status == "voided":
        raise Conflict("Already voided")
    if inv.status == "issued":
        try:
            with db.begin_nested():
                accounting.void_sales_invoice(db, ctx.org, ctx.user_id, inv.accounting_doc_id)
        except Exception as e:
            if hasattr(e, "status"):
                raise PcError(f"{e} Issue a credit note instead." if getattr(e, "status", 0) == 409 else str(e), 409)
            raise
        for l in db.query(P.PcInvoiceLine).filter_by(invoice_id=inv.id):
            if l.time_entry_id:
                t = db.get(P.PcTimeEntry, l.time_entry_id)
                if t.status == "billed":
                    t.status = "approved"
    inv.status, inv.voided_at, inv.void_reason = "voided", core.now(), reason.strip()
    db.query(P.PcInvoiceLine).filter_by(invoice_id=inv.id).update({"active_time_key": None})           # frees the time for a new invoice
    db.flush()
    core.audit(db, ctx, a.practice_id, "invoice.voided", "invoice", inv.id, reason=reason[:200])
    return idict(db, inv, ctx.org, True)


def credit_note(db, ctx, a: Access, iid: int, amount, reason: str) -> dict:
    """A credit note against an issued invoice for an amount EX TAX (a single adjustment line), posted through Accounting. The time stays billed: the invoice is corrected financially, not rewritten."""
    a.require("billing_admin")
    inv = irow(db, a, iid, lock=True)
    if inv.status != "issued":
        raise Conflict("Only issued invoices can be credited")
    amt = _money(amount, "Credit amount")
    if not core.text(reason, "Reason", required=True, max_len=300):
        raise PcError("A reason is required")
    s = accounting.sales_document(db, ctx.org.id, inv.accounting_doc_id)
    gross = amt + B.q2(amt * _tax_rate(a, ctx.org))
    if gross > s["amount_due"]:
        raise Conflict(f"The credit ({gross}) exceeds what is still owing on the invoice ({s['amount_due']})", "over_credit")
    cfg = a.settings.get("billing", {})
    try:
        with db.begin_nested():
            cn = accounting.credit_sales_invoice(db, ctx.org, ctx.user_id, inv.accounting_doc_id, lines=[dict(description=f"Credit: {reason.strip()}"[:500], qty=1, unit_price=str(amt),
                                                                                                             account=cfg.get("revenue_account", "200"))], issue_date=core.today(), reason=reason)
    except Exception as e:
        if hasattr(e, "status"):
            raise _books_error(e)
        raise
    inv.credit_doc_ids = list(inv.credit_doc_ids or []) + [cn["id"]]
    db.flush()
    core.audit(db, ctx, a.practice_id, "invoice.credited", "invoice", inv.id, credit_doc=cn["id"], amount=amt, reason=reason[:200])
    return dict(idict(db, inv, ctx.org, True), credit_note=dict(id=cn["id"], number=cn["number"], total=cn["total"]))


def invoices(db, a: Access, *, client_id=None, status=None, page_no=1, size=25) -> dict:
    a.require("billing")
    q = db.query(P.PcInvoice).filter(P.PcInvoice.practice_id == a.practice_id, P.PcInvoice.client_id.in_(a.client_ids(billing=True)))
    if client_id:
        q = q.filter(P.PcInvoice.client_id == client_id)
    if status:
        q = q.filter(P.PcInvoice.status == status)
    meta, q = core.page(q.order_by(P.PcInvoice.id.desc()), page_no, size)
    return dict(**meta, items=[idict(db, i, a.ctx.org) for i in q])


def get_invoice(db, a: Access, iid: int) -> dict:
    a.require("billing")
    return idict(db, irow(db, a, iid), a.ctx.org, True)


def share_invoice(db, ctx, a: Access, iid: int, visible: bool) -> dict:
    a.require("billing_admin")
    inv = irow(db, a, iid)
    if inv.status != "issued":
        raise Conflict("Only issued invoices can be shown to the client")
    inv.visible_to_client = bool(visible)
    db.flush()
    core.audit(db, ctx, a.practice_id, "invoice.shared" if visible else "invoice.unshared", "invoice", inv.id)
    return idict(db, inv, ctx.org)


# ------------------------------------------------------------------ dashboard
def dashboard(db, a: Access, *, date_from=None, date_to=None) -> dict:
    """Every figure is a SUM over records the member may see; nothing is cached. realisation = billed / (billed + written off) for the period."""
    a.require("billing")
    ids = a.client_ids(billing=True)
    today = core.today()
    df, dto = core.parse_date(date_from, "From", today.replace(day=1)), core.parse_date(date_to, "To", today)
    T = P.PcTimeEntry
    base = db.query(T).filter(T.practice_id == a.practice_id, T.client_id.in_(ids or [0]))
    def s(q, col):
        return Decimal(str(q.with_entities(func.coalesce(func.sum(col), 0)).scalar() or 0)).quantize(Decimal("0.01"))
    reserved = {i for (i,) in db.query(P.PcInvoiceLine.time_entry_id).join(P.PcInvoice, P.PcInvoice.id == P.PcInvoiceLine.invoice_id).filter(
        P.PcInvoice.practice_id == a.practice_id, P.PcInvoice.status == "draft", P.PcInvoiceLine.time_entry_id.isnot(None))}
    appr = base.filter(T.status == "approved", T.billable.is_(True), T.amount > 0).all()
    wip = sum((t.amount for t in appr if t.id not in reserved), Decimal("0.00"))
    drafted = sum((t.amount for t in appr if t.id in reserved), Decimal("0.00"))
    sub = base.filter(T.status == "submitted")
    I = P.PcInvoice
    issued = db.query(I).filter(I.practice_id == a.practice_id, I.client_id.in_(ids or [0]), I.status == "issued")
    billed_time = Decimal(str(db.query(func.coalesce(func.sum(P.PcInvoiceLine.amount), 0)).join(I, I.id == P.PcInvoiceLine.invoice_id).filter(
        I.practice_id == a.practice_id, I.client_id.in_(ids or [0]), I.status == "issued", I.issue_date >= df, I.issue_date <= dto, P.PcInvoiceLine.kind == "time").scalar() or 0)).quantize(Decimal("0.01"))
    wo = Decimal(str(db.query(func.coalesce(func.sum(P.PcWriteOff.amount), 0)).join(T, T.id == P.PcWriteOff.time_entry_id).filter(
        P.PcWriteOff.practice_id == a.practice_id, T.client_id.in_(ids or [0]), func.date(P.PcWriteOff.created_at) >= df, func.date(P.PcWriteOff.created_at) <= dto).scalar() or 0)).quantize(Decimal("0.01"))
    invoiced = Decimal(str(issued.with_entities(func.coalesce(func.sum(I.net), 0)).filter(I.issue_date >= df, I.issue_date <= dto).scalar() or 0)).quantize(Decimal("0.01"))
    ar_total = ar_overdue = Decimal("0.00")
    for inv in issued.all():
        st = accounting.sales_document(db, a.ctx.org.id, inv.accounting_doc_id)
        if st and st["status"] == "approved":
            ar_total += Decimal(st["amount_due"])
            if st["due_date"] and st["due_date"] < today:
                ar_overdue += Decimal(st["amount_due"])
    return dict(period=dict(from_=df.isoformat(), to=dto.isoformat()), wip=str(wip), drafted_unissued=str(drafted), submitted_awaiting_approval=dict(count=sub.count(), minutes=int(sub.with_entities(func.coalesce(func.sum(T.minutes), 0)).scalar() or 0)),
                invoiced_net=str(invoiced), billed_time=str(billed_time), written_off=str(wo), realisation_pct=(None if (billed_time + wo) == 0 else str(B.realisation(billed_time, billed_time + wo))),
                receivables=str(ar_total), receivables_overdue=str(ar_overdue),
                drill=dict(wip="/practice/billing?tab=time&status=approved", submitted="/practice/billing?tab=time&status=submitted", invoices="/practice/billing?tab=invoices&status=issued"))
