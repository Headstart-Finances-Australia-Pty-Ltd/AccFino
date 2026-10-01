"""
Expenses (A5): claims -> submit -> approve -> reimburse.

  approve      Dr Expense (net, per item) + Dr GST     Cr 801 Unpaid Expense Claims (gross)     - the employee is owed the money
  reimburse    Dr 801 Unpaid Expense Claims            Cr Bank

Controls: only the claimant edits their own claim; an approver may not approve their own claim (an owner may, and it is audited);
receipts are required on submit for GST-bearing items over the ATO tax-invoice threshold; posted amounts can be un-approved
(reversed) until reimbursed. Mileage uses the organisation's configured cents-per-km rate - no rate is assumed.
"""
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import func

from accfino_core import models as m
from accfino_core.books import models as b
from accfino_core.books.common import BooksError, CONTROL_KEYS, as_date, bank_account, get_account, get_settings, get_tax, money, system_acct
from accfino_core.ledger import service as L

TAX_INVOICE_THRESHOLD = Decimal("82.50")          # ATO: a tax invoice is needed to claim GST on a purchase over $82.50 (GST inclusive)
APPROVER_ROLES = ("owner", "admin", "accountant")


def can_approve(ctx):
    return ctx.is_admin or ctx.role in APPROVER_ROLES


def _number(db, org):
    seq = db.query(b.DocSequence).filter_by(org_id=org.id, doc_type="expense_claim").with_for_update().one_or_none()
    if seq is None:
        seq = b.DocSequence(org_id=org.id, doc_type="expense_claim", prefix="EXP-", next_no=1)
        db.add(seq)
        db.flush()
    while True:
        n = f"{seq.prefix}{seq.next_no:04d}"
        seq.next_no += 1
        if not db.query(b.ExpenseClaim.id).filter_by(org_id=org.id, number=n).first():
            return n


def build_items(db, org, items_in):
    if not items_in:
        raise BooksError("A claim needs at least one item")
    out = []
    st = get_settings(db, org)
    for i, it in enumerate(items_in, start=1):
        kind = it.get("kind") or "receipt"
        desc = (it.get("description") or "").strip()
        if not desc:
            raise BooksError(f"Item {i}: description is required")
        acc = get_account(db, org, it.get("account"), what=f"Item {i} account")
        if acc.system_key in CONTROL_KEYS or acc.account_type in ("bank", "credit_card"):
            raise BooksError(f"Item {i}: {acc.code} {acc.name} cannot be used on an expense claim")
        km = rate = None
        tax = None
        if kind == "mileage":
            km = Decimal(str(it.get("km") or 0))
            rate = it.get("rate_per_km") if it.get("rate_per_km") not in (None, "") else st.get("mileage_rate_per_km")
            if km <= 0 or rate in (None, ""):
                raise BooksError(f"Item {i}: mileage needs km and a rate per km (set it on the item or in the organisation's books settings)")
            rate = Decimal(str(rate))
            gross = money(km * rate)
        elif kind == "receipt":
            gross = money(it.get("amount"))
            tcode = it.get("tax_code")
            tax = get_tax(db, org, tcode) if tcode not in (None, "") else (db.get(m.TaxCode, acc.default_tax_code_id) if acc.default_tax_code_id else None)
            if tax is not None and tax.applies_to not in ("purchases", "both"):
                raise BooksError(f"Item {i}: tax code {tax.code} cannot be used on an expense")
        else:
            raise BooksError(f"Item {i}: kind must be receipt or mileage")
        if gross <= 0:
            raise BooksError(f"Item {i}: the amount must be greater than zero")
        r = Decimal(tax.rate) if (tax is not None and org.gst_registered) else Decimal(0)
        taxamt = money(gross * r / (1 + r)) if r else Decimal("0.00")
        out.append(dict(item_date=as_date(it.get("date") or date.today(), f"item {i} date"), merchant=(it.get("merchant") or None), description=desc[:500],
                        account_id=acc.id, tax_code_id=tax.id if tax else None, kind=kind, km=km, rate_per_km=rate, gross=gross, tax=taxamt, net=gross - taxamt))
    return out


def _apply(claim, items):
    claim.items[:] = []
    for it in items:
        claim.items.append(b.ExpenseItem(org_id=claim.org_id, **it))
    claim.total = sum((i["gross"] for i in items), Decimal("0.00"))
    claim.tax_total = sum((i["tax"] for i in items), Decimal("0.00"))


def create_claim(db, org, ctx, data):
    claim = b.ExpenseClaim(org_id=org.id, number=_number(db, org), claimant_user_id=ctx.user_id, claimant_name=ctx.username, title=(data.get("title") or "").strip()[:200] or "Expense claim",
                           status="draft")
    _apply(claim, build_items(db, org, data.get("items")))
    db.add(claim)
    db.flush()
    return claim


def _editable(ctx, claim):
    if claim.status not in ("draft", "rejected"):
        raise BooksError(f"A claim that is {claim.status} cannot be edited", 409)
    if claim.claimant_user_id != ctx.user_id and not can_approve(ctx):
        raise BooksError("Only the claimant (or an approver) can edit this claim", 403)


def update_claim(db, org, ctx, claim, data):
    _editable(ctx, claim)
    if data.get("title"):
        claim.title = data["title"].strip()[:200]
    if data.get("items") is not None:
        _apply(claim, build_items(db, org, data["items"]))
    if claim.status == "rejected":
        claim.status, claim.rejected_reason = "draft", None
    db.flush()
    return claim


def delete_claim(db, ctx, claim):
    _editable(ctx, claim)
    if claim.status != "draft":
        raise BooksError("Only draft claims can be deleted", 409)
    db.delete(claim)
    db.flush()


def submit(db, org, ctx, claim):
    _editable(ctx, claim)
    if claim.status == "rejected":
        claim.rejected_reason = None
    missing = []
    for it in claim.items:
        if it.kind == "receipt" and it.tax > 0 and it.gross > TAX_INVOICE_THRESHOLD:
            has = db.query(func.count(b.Attachment.id)).filter_by(org_id=org.id, owner_kind="expense_item", owner_id=it.id).scalar()
            if not has:
                missing.append(f"{it.description} ({it.gross})")
    if missing:
        raise BooksError("Attach the tax invoice / receipt before submitting (the ATO requires one to claim GST on purchases over "
                         f"${TAX_INVOICE_THRESHOLD}): " + "; ".join(missing))
    claim.status, claim.submitted_at = "submitted", datetime.utcnow()
    db.flush()
    return claim


def approve(db, org, ctx, claim, post_date=None):
    if not can_approve(ctx):
        raise BooksError(f"Your role '{ctx.role}' cannot approve expense claims", 403)
    if claim.status != "submitted":
        raise BooksError(f"Only submitted claims can be approved (this one is {claim.status})", 409)
    self_approved = claim.claimant_user_id == ctx.user_id
    if self_approved and ctx.role != "owner" and not ctx.is_admin:
        raise BooksError("You cannot approve your own claim; ask another approver (segregation of duties)", 403)
    d = as_date(post_date) if post_date else max(i.item_date for i in claim.items)
    payable, gst = system_acct(db, org, "expense_claims"), system_acct(db, org, "gst")
    lines, gst_by = [], {}
    for it in claim.items:
        lines.append({"account_id": it.account_id, "debit": it.net, "tax_code_id": it.tax_code_id, "tax_amount": it.tax,
                      "description": f"{it.merchant + ' - ' if it.merchant else ''}{it.description}"[:500], "contact_name": claim.claimant_name})
        if it.tax:
            gst_by[it.tax_code_id] = gst_by.get(it.tax_code_id, Decimal(0)) + it.tax
    for tid, amt in gst_by.items():
        lines.append({"account_id": gst.id, "debit": amt, "tax_code_id": tid, "description": f"GST - {claim.number}", "contact_name": claim.claimant_name})
    lines.insert(0, {"account_id": payable.id, "credit": claim.total, "description": f"{claim.number} {claim.title}"[:500], "contact_name": claim.claimant_name})
    try:
        j = L.post_journal(db, org, journal_date=d, lines=lines, narration=f"Expense claim {claim.number} - {claim.claimant_name}",
                           source_type="expense_claim", source_ref=f"claim:{claim.id}", created_by=ctx.user_id)
    except L.LedgerError as e:
        raise BooksError(str(e), 422)
    claim.status, claim.approved_by, claim.approved_at, claim.approval_journal_id = "approved", ctx.user_id, datetime.utcnow(), j.id
    db.flush()
    return claim, self_approved


def reject(db, ctx, claim, reason):
    if not can_approve(ctx):
        raise BooksError(f"Your role '{ctx.role}' cannot reject expense claims", 403)
    if claim.status != "submitted":
        raise BooksError(f"Only submitted claims can be rejected (this one is {claim.status})", 409)
    if not (reason or "").strip():
        raise BooksError("Give the claimant a reason")
    claim.status, claim.rejected_reason = "rejected", reason.strip()[:300]
    db.flush()
    return claim


def unapprove(db, org, ctx, claim):
    if not can_approve(ctx):
        raise BooksError(f"Your role '{ctx.role}' cannot change approved claims", 403)
    if claim.status != "approved":
        raise BooksError("Only an approved, un-reimbursed claim can be un-approved (reimbursed claims: reverse the reimbursement first)", 409)
    try:
        L.reverse_journal(db, org, claim.approval_journal_id, narration=f"Un-approve {claim.number}", created_by=ctx.user_id)
    except L.LedgerError as e:
        raise BooksError(str(e), 422)
    claim.status, claim.approved_by, claim.approved_at, claim.approval_journal_id = "submitted", None, None, None
    db.flush()
    return claim


def reimburse(db, org, ctx, claim, pay_date, bank_ref, reference=None):
    if not can_approve(ctx):
        raise BooksError(f"Your role '{ctx.role}' cannot reimburse claims", 403)
    if claim.status != "approved":
        raise BooksError(f"Only approved claims can be reimbursed (this one is {claim.status})", 409)
    bank = bank_account(db, org, bank_ref)
    payable = system_acct(db, org, "expense_claims")
    lines = [{"account_id": payable.id, "debit": claim.total, "description": f"Reimburse {claim.number}", "contact_name": claim.claimant_name},
             {"account_id": bank.id, "credit": claim.total, "description": reference or f"Reimburse {claim.claimant_name} {claim.number}", "contact_name": claim.claimant_name}]
    try:
        j = L.post_journal(db, org, journal_date=as_date(pay_date), lines=lines, narration=f"Reimbursement {claim.number} - {claim.claimant_name}",
                           source_type="expense_payment", source_ref=f"claim:{claim.id}", created_by=ctx.user_id)
    except L.LedgerError as e:
        raise BooksError(str(e), 422)
    claim.status, claim.paid_at, claim.payment_journal_id = "paid", datetime.utcnow(), j.id
    db.flush()
    return claim


def claim_dict(db, c, detail=True):
    d = dict(id=c.id, number=c.number, title=c.title, claimant=c.claimant_name, claimant_user_id=c.claimant_user_id, status=c.status, total=str(c.total),
             tax_total=str(c.tax_total), submitted_at=c.submitted_at.isoformat() if c.submitted_at else None, rejected_reason=c.rejected_reason,
             approval_journal_id=c.approval_journal_id, payment_journal_id=c.payment_journal_id, item_count=len(c.items))
    if detail:
        d["items"] = [dict(id=i.id, date=i.item_date.isoformat(), merchant=i.merchant, description=i.description, kind=i.kind, account_id=i.account_id,
                           account_code=i.account.code if i.account else None, tax_code_id=i.tax_code_id, gross=str(i.gross), tax=str(i.tax), net=str(i.net),
                           km=str(i.km) if i.km is not None else None, rate_per_km=str(i.rate_per_km) if i.rate_per_km is not None else None,
                           receipts=db.query(func.count(b.Attachment.id)).filter_by(org_id=c.org_id, owner_kind="expense_item", owner_id=i.id).scalar())
                      for i in c.items]
    return d
