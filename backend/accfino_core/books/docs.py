"""
Document engine for Sales & Receivables (A2) and Purchases & Payables (A3).

One engine, two sides, so invoices and bills follow identical rules:

  invoice          Dr Accounts Receivable (gross)   Cr Revenue (net, per line)     Cr GST (tax)
  credit_note      Cr Accounts Receivable (gross)   Dr Revenue (net, per line)     Dr GST (tax)
  bill             Cr Accounts Payable   (gross)    Dr Expense/COGS (net, per line) Dr GST (tax)
  supplier_credit  Dr Accounts Payable   (gross)    Cr Expense (net, per line)     Cr GST (tax)
  quote / purchase_order  no ledger effect

  payment received Dr Bank  Cr Accounts Receivable        payment made   Dr Accounts Payable  Cr Bank
  refund to customer Dr AR  Cr Bank                        refund from supplier Dr Bank Cr AP

GST is calculated PER LINE (tax code rate, rounded half-up to the cent) and the line carries the tax code and tax amount so
the BAS report reads straight from the ledger. What is still owing on a document is always derived from `allocations`.
"""
from datetime import date, datetime, timedelta
from decimal import Decimal, InvalidOperation

from sqlalchemy import func

from accfino_core import models as m
from accfino_core.books import models as b
from accfino_core.books.common import (CONTROL_KEYS, BooksError, as_date, bank_account, default_account, find_contact, get_account,
                                       get_settings, get_tax, money, next_number, system_acct)
from accfino_core.ledger import service as L

SALES = ("quote", "invoice", "credit_note")
POSTING = ("invoice", "credit_note", "bill", "supplier_credit")
CREDIT_DOCS = ("credit_note", "supplier_credit")
# per side: (quote/order type, main document type, credit document type, payment kind, refund kind, contact role)
SIDES = {"sales": ("quote", "invoice", "credit_note", "receive", "refund_out", "customer"),
         "purchases": ("purchase_order", "bill", "supplier_credit", "pay", "refund_in", "supplier")}
PAYMENT_TARGET = {"receive": "invoice", "pay": "bill", "refund_out": "credit_note", "refund_in": "supplier_credit"}


def side_of(doc_type):
    return "sales" if doc_type in SALES else "purchases"


def dec(x, what="amount") -> Decimal:
    try:
        d = x if isinstance(x, Decimal) else Decimal(str(x))
    except (InvalidOperation, ValueError):
        raise BooksError(f"Invalid {what}: {x!r}")
    if not d.is_finite():
        raise BooksError(f"Invalid {what}: {x!r}")
    return d


# ---------------------------------------------------------------------------- line maths --
def calc_line(qty, price, disc_pct, rate, amounts_are):
    """-> (net, tax, gross), each rounded half-up to the cent. Tax is per line."""
    base = qty * price * (Decimal(1) - disc_pct / Decimal(100))
    if amounts_are == "inclusive":
        gross = money(base)
        tax = money(gross * rate / (Decimal(1) + rate)) if rate else Decimal("0.00")
        return gross - tax, tax, gross
    net = money(base)
    tax = money(net * rate) if (rate and amounts_are != "no_tax") else Decimal("0.00")
    return net, tax, net + tax


def build_lines(db, org, contact, doc_type, amounts_are, lines_in):
    if not lines_in:
        raise BooksError("At least one line is required")
    side = side_of(doc_type)
    out = []
    for i, li in enumerate(lines_in, start=1):
        desc = (li.get("description") or "").strip()
        if not desc:
            raise BooksError(f"Line {i}: description is required")
        qty, price = dec(li.get("qty", 1), f"line {i} quantity"), dec(li.get("unit_price", 0), f"line {i} unit price")
        disc = dec(li.get("discount_pct") or 0, f"line {i} discount")
        if disc < 0 or disc > 100:
            raise BooksError(f"Line {i}: discount must be between 0 and 100")
        if qty == 0:
            raise BooksError(f"Line {i}: quantity cannot be zero")
        if li.get("account") not in (None, ""):
            acc = get_account(db, org, li["account"], what=f"Line {i} account")
        elif contact.default_account_id and (a := db.get(m.LedgerAccount, contact.default_account_id)) and a.is_active:
            acc = a
        else:
            acc = default_account(db, org, side)
        if acc.system_key in CONTROL_KEYS or acc.account_type in ("bank", "credit_card"):
            raise BooksError(f"Line {i}: {acc.code} {acc.name} is a control/bank account and cannot be used on a {doc_type.replace('_', ' ')}")
        tax = None
        if amounts_are != "no_tax":
            if li.get("tax_code") not in (None, ""):
                tax = get_tax(db, org, li["tax_code"])
            elif contact.default_tax_code_id:
                tax = db.get(m.TaxCode, contact.default_tax_code_id)
            elif acc.default_tax_code_id:
                tax = db.get(m.TaxCode, acc.default_tax_code_id)
            if tax is not None:
                ok = ("sales", "both") if side == "sales" else ("purchases", "both")
                if tax.applies_to not in ok:
                    raise BooksError(f"Line {i}: tax code {tax.code} ({tax.name}) cannot be used on {side}")
        rate = Decimal(tax.rate) if tax is not None else Decimal(0)
        if not org.gst_registered:
            rate, tax = Decimal(0), None
        net, taxamt, gross = calc_line(qty, price, disc, rate, amounts_are)
        out.append(dict(line_no=i, description=desc[:500], qty=qty, unit_price=price, discount_pct=disc, account_id=acc.id,
                        tax_code_id=tax.id if tax is not None else None, net=net, tax=taxamt, gross=gross,
                        tracking_option_ids=li.get("tracking_option_ids") or None))
    return out


def _apply_lines(doc, lines):
    doc.lines[:] = []
    for l in lines:
        doc.lines.append(b.DocLine(org_id=doc.org_id, **l))
    doc.subtotal = sum((l["net"] for l in lines), Decimal("0.00"))
    doc.tax_total = sum((l["tax"] for l in lines), Decimal("0.00"))
    doc.total = doc.subtotal + doc.tax_total


# ---------------------------------------------------------------------------- lifecycle --
def create_doc(db, org, user_id, doc_type, data: dict, *, approve=True):
    role = SIDES[side_of(doc_type)][5]
    contact = find_contact(db, org, contact_id=data.get("contact_id"), name=data.get(role) or data.get("contact"), role=role, create=True)
    amounts_are = data.get("amounts_are") or "exclusive"
    if amounts_are not in ("exclusive", "inclusive", "no_tax"):
        raise BooksError("amounts_are must be exclusive, inclusive or no_tax")
    issue = as_date(data.get("issue_date") or date.today(), "issue date")
    terms = contact.terms_days if contact.terms_days is not None else (14 if role == "customer" else 30)
    if doc_type == "quote":
        terms = 30
    due = as_date(data["due_date"], "due date") if data.get("due_date") else issue + timedelta(days=terms)
    if due < issue:
        raise BooksError("Due date cannot be before the issue date")
    number = (data.get("number") or "").strip() or next_number(db, org, doc_type)
    if db.query(b.Doc.id).filter_by(org_id=org.id, doc_type=doc_type, number=number).first():
        raise BooksError(f"{doc_type.replace('_', ' ').title()} number {number} already exists", 409)
    ref = (data.get("reference") or "").strip() or None
    if doc_type in ("bill", "supplier_credit") and ref:
        dup = db.query(b.Doc).filter(b.Doc.org_id == org.id, b.Doc.contact_id == contact.id, b.Doc.reference == ref,
                                     b.Doc.doc_type.in_(("bill", "supplier_credit")), b.Doc.status != "voided").first()
        if dup:
            raise BooksError(f"{contact.name} already has {dup.number} with supplier reference '{ref}' (possible duplicate bill)", 409)
    doc = b.Doc(org_id=org.id, doc_type=doc_type, number=number, contact_id=contact.id, status="draft", issue_date=issue, due_date=due,
                reference=ref, amounts_are=amounts_are, notes=data.get("notes"), terms=data.get("terms"),
                source=data.get("source") or "manual", parent_id=data.get("parent_id"), created_by=user_id)
    _apply_lines(doc, build_lines(db, org, contact, doc_type, amounts_are, data.get("lines") or []))
    db.add(doc)
    db.flush()
    if approve and doc_type != "quote":
        approve_doc(db, org, doc, user_id)
    return doc


def update_draft(db, org, doc, data: dict):
    if doc.status != "draft":
        raise BooksError(f"Only draft documents can be edited (this one is {doc.status}); void it or issue a credit note", 409)
    role = SIDES[side_of(doc.doc_type)][5]
    if data.get("contact_id") or data.get(role) or data.get("contact"):
        c = find_contact(db, org, contact_id=data.get("contact_id"), name=data.get(role) or data.get("contact"), role=role, create=True)
        doc.contact_id = c.id
    contact = db.get(b.Contact, doc.contact_id)
    if data.get("amounts_are"):
        doc.amounts_are = data["amounts_are"]
    if data.get("issue_date"):
        doc.issue_date = as_date(data["issue_date"])
    if data.get("due_date"):
        doc.due_date = as_date(data["due_date"])
    if doc.due_date and doc.due_date < doc.issue_date:
        raise BooksError("Due date cannot be before the issue date")
    for f in ("reference", "notes", "terms"):
        if f in data:
            setattr(doc, f, (data[f] or None))
    if data.get("number") and data["number"] != doc.number:
        if db.query(b.Doc.id).filter_by(org_id=org.id, doc_type=doc.doc_type, number=data["number"]).first():
            raise BooksError(f"Number {data['number']} already exists", 409)
        doc.number = data["number"]
    if data.get("lines") is not None:
        _apply_lines(doc, build_lines(db, org, contact, doc.doc_type, doc.amounts_are, data["lines"]))
    db.flush()
    return doc


def delete_draft(db, doc):
    if doc.status != "draft":
        raise BooksError("Only draft documents can be deleted; void an approved document instead", 409)
    db.delete(doc)
    db.flush()


def _journal_lines(db, org, doc):
    ar, ap, gst = system_acct(db, org, "ar_control"), system_acct(db, org, "ap_control"), system_acct(db, org, "gst")
    control = ar if doc.doc_type in SALES else ap
    control_debit = doc.doc_type in ("invoice", "supplier_credit")            # control account side
    name = doc.contact.name
    lines = []
    def contra(amount):   # a positive amount on the contra side of the control account; negative flips it
        return ("credit" if control_debit else "debit") if amount >= 0 else ("debit" if control_debit else "credit")
    contra_groups = {}
    for l in doc.lines:
        if l.net == 0 and l.tax == 0:
            continue
        key = (l.account_id, l.tax_code_id, tuple(l.tracking_option_ids or ()))
        g = contra_groups.setdefault(key, dict(net=Decimal(0), tax=Decimal(0), desc=l.description))
        g["net"] += l.net
        g["tax"] += l.tax
    gst_by_code, total = {}, Decimal(0)
    for (acc_id, tax_id, track), g in contra_groups.items():
        if g["net"] != 0:
            lines.append({"account_id": acc_id, contra(g["net"]): abs(g["net"]), "tax_code_id": tax_id, "tax_amount": abs(g["tax"]),
                          "description": g["desc"], "tracking_option_ids": list(track) or None, "contact_name": name})
        total += g["net"]
        if g["tax"] != 0:
            gst_by_code[tax_id] = gst_by_code.get(tax_id, Decimal(0)) + g["tax"]
            total += g["tax"]
    for tax_id, amt in gst_by_code.items():
        lines.append({"account_id": gst.id, contra(amt): abs(amt), "tax_code_id": tax_id, "description": f"GST - {doc.number}", "contact_name": name})
    if total <= 0:
        raise BooksError(f"The {doc.doc_type.replace('_', ' ')} total must be greater than zero")
    lines.insert(0, {"account_id": control.id, ("debit" if control_debit else "credit"): total, "description": f"{doc.number} {name}",
                     "contact_name": name})
    return lines, total


def approve_doc(db, org, doc, user_id):
    """draft -> approved. Ledger-posting types post their journal; quotes/POs simply become active."""
    if doc.status != "draft":
        raise BooksError(f"Only draft documents can be approved (this one is {doc.status})", 409)
    if not doc.lines:
        raise BooksError("The document has no lines")
    if doc.doc_type in POSTING:
        lines, total = _journal_lines(db, org, doc)
        if total != doc.total:
            raise BooksError(f"Internal total mismatch ({total} vs {doc.total})", 500)
        try:
            j = L.post_journal(db, org, journal_date=doc.issue_date, lines=lines,
                               narration=f"{doc.doc_type.replace('_', ' ').title()} {doc.number} - {doc.contact.name}",
                               source_type=f"doc_{doc.doc_type}", source_ref=f"doc:{doc.id}", created_by=user_id)
        except L.LedgerError as e:
            raise BooksError(str(e), 422)
        doc.journal_id = j.id
        doc.status = "approved"
    elif doc.doc_type == "quote":
        raise BooksError("A quote is sent to the customer, not approved (use send / accept / decline)", 409)
    else:                                                                  # purchase order: active, no ledger effect
        doc.status = "approved"
    doc.approved_at, doc.approved_by = datetime.utcnow(), user_id
    db.flush()
    return doc


def mark_sent(db, doc):
    if doc.status == "draft" and doc.doc_type == "quote":
        doc.status = "sent"
    if doc.status in ("draft", "voided"):
        raise BooksError("Approve the document before sending it", 409)
    doc.sent_at = datetime.utcnow()
    db.flush()
    return doc


def quote_decision(db, doc, decision):
    if doc.doc_type != "quote":
        raise BooksError("Only quotes can be accepted or declined")
    if doc.status not in ("draft", "sent", "accepted", "declined"):
        raise BooksError(f"A quote that is {doc.status} cannot be {decision}", 409)
    doc.status = decision
    db.flush()
    return doc


def void_doc(db, org, doc, user_id):
    if doc.status == "voided" or doc.status == "cancelled":
        raise BooksError("Already voided", 409)
    if doc.doc_type not in POSTING:                                      # quote / purchase order
        if doc.status in ("invoiced", "billed"):
            raise BooksError(f"This {doc.doc_type.replace('_', ' ')} has been converted; void the resulting document first", 409)
        doc.status = "declined" if doc.doc_type == "quote" else "cancelled"
        db.flush()
        return doc
    if doc.status == "draft":
        raise BooksError("A draft has no ledger effect: delete it instead", 409)
    if (doc.amount_paid or 0) > 0 or (doc.amount_credited or 0) > 0:
        raise BooksError("This document has payments or credits applied. Reverse/remove them first, then void it", 409)
    try:
        L.reverse_journal(db, org, doc.journal_id, reversal_date=doc.issue_date, narration=f"Void {doc.number}", created_by=user_id)
    except L.LedgerError as e:
        raise BooksError(str(e), 422)
    doc.status, doc.voided_at = "voided", datetime.utcnow()
    if doc.parent_id:                                                    # reopen the quote / PO it came from
        parent = db.get(b.Doc, doc.parent_id)
        if parent and parent.status in ("invoiced", "billed"):
            parent.status = "accepted" if parent.doc_type == "quote" else "approved"
    db.flush()
    return doc


def convert(db, org, doc, user_id, *, approve=True):
    """quote -> invoice, purchase order -> bill (copies the lines, links parent, marks the source converted)."""
    if doc.doc_type == "quote":
        to, done = "invoice", "invoiced"
        if doc.status in ("declined", "invoiced"):
            raise BooksError(f"A quote that is {doc.status} cannot be converted", 409)
    elif doc.doc_type == "purchase_order":
        to, done = "bill", "billed"
        if doc.status != "approved":
            raise BooksError("Approve the purchase order before converting it to a bill", 409)
    else:
        raise BooksError("Only quotes and purchase orders can be converted")
    contact = doc.contact
    terms = contact.terms_days if contact.terms_days is not None else 14
    issue = date.today()
    new = b.Doc(org_id=org.id, doc_type=to, number=next_number(db, org, to), contact_id=doc.contact_id, status="draft", issue_date=issue,
                due_date=issue + timedelta(days=terms), reference=doc.reference if to == "invoice" else None, amounts_are=doc.amounts_are,
                notes=doc.notes, terms=doc.terms, parent_id=doc.id, created_by=user_id, source="manual")
    for l in doc.lines:
        new.lines.append(b.DocLine(org_id=org.id, line_no=l.line_no, description=l.description, qty=l.qty, unit_price=l.unit_price,
                                   discount_pct=l.discount_pct, account_id=l.account_id, tax_code_id=l.tax_code_id, net=l.net, tax=l.tax,
                                   gross=l.gross, tracking_option_ids=l.tracking_option_ids))
    new.subtotal, new.tax_total, new.total = doc.subtotal, doc.tax_total, doc.total
    db.add(new)
    db.flush()
    doc.status = done
    if approve:
        approve_doc(db, org, new, user_id)
    return new


# ---------------------------------------------------------------------------- settlement --
def recompute(db, doc):
    """Derive amount_paid / amount_credited and the paid|approved status from the allocations (the single source of truth)."""
    paid = db.query(func.coalesce(func.sum(b.Allocation.amount), 0)).join(b.Payment, b.Payment.id == b.Allocation.payment_id) \
        .filter(b.Allocation.doc_id == doc.id, b.Payment.status == "posted").scalar()
    credited = db.query(func.coalesce(func.sum(b.Allocation.amount), 0)).filter(b.Allocation.credit_doc_id.isnot(None), b.Allocation.doc_id == doc.id).scalar()
    applied = db.query(func.coalesce(func.sum(b.Allocation.amount), 0)).filter(b.Allocation.credit_doc_id == doc.id).scalar()
    doc.amount_paid = money(paid)
    doc.amount_credited = money(credited) + money(applied)
    if doc.status in ("approved", "paid"):
        doc.status = "paid" if doc.total - doc.amount_paid - doc.amount_credited == 0 else "approved"
    db.flush()


def _lock_docs(db, org, ids):
    docs = {d.id: d for d in db.query(b.Doc).filter(b.Doc.org_id == org.id, b.Doc.id.in_(list(ids))).order_by(b.Doc.id).with_for_update()}
    missing = set(ids) - set(docs)
    if missing:
        raise BooksError(f"Document(s) not found: {sorted(missing)}", 404)
    return docs


def _check_targets(docs, allocs, contact_id, want_type, on_date):
    seen = {}
    for a in allocs:
        d = docs[a["doc_id"]]
        seen[d.id] = seen.get(d.id, Decimal(0)) + a["amount"]
    for did, amt in seen.items():
        d = docs[did]
        if d.doc_type != want_type:
            raise BooksError(f"{d.number} is a {d.doc_type.replace('_', ' ')}; this operation settles {want_type.replace('_', ' ')}s")
        if d.contact_id != contact_id:
            raise BooksError(f"{d.number} belongs to a different customer/supplier than the payment")
        if d.status not in ("approved",):
            raise BooksError(f"{d.number} is {d.status}; only approved, unpaid documents can be settled", 409)
        if on_date < d.issue_date:
            raise BooksError(f"The date {on_date} is before {d.number} was issued ({d.issue_date})")
        if amt > d.amount_due:
            raise BooksError(f"Over-allocation: {amt} exceeds the {d.amount_due} still owing on {d.number}", 422)


def _norm_allocs(allocations):
    out = []
    for a in allocations or []:
        amt = money(a.get("amount"))
        if amt <= 0:
            raise BooksError("Each allocation amount must be greater than zero")
        out.append(dict(doc_id=int(a["doc_id"]), amount=amt))
    return out


def unallocated(db, payment):
    used = db.query(func.coalesce(func.sum(b.Allocation.amount), 0)).filter(b.Allocation.payment_id == payment.id).scalar()
    return payment.amount - money(used)


def record_payment(db, org, user_id, *, kind, contact, pay_date, amount, bank_ref, reference=None, allocations=None, overpayment=False):
    amount = money(amount)
    if amount <= 0:
        raise BooksError("Payment amount must be greater than zero")
    bank = bank_account(db, org, bank_ref)
    allocs = _norm_allocs(allocations)
    total_alloc = sum((a["amount"] for a in allocs), Decimal("0.00"))
    if total_alloc > amount:
        raise BooksError(f"Allocations ({total_alloc}) exceed the payment amount ({amount})")
    if total_alloc < amount and not overpayment:
        raise BooksError(f"{amount - total_alloc} of the payment is not allocated to any document. Allocate it, or set overpayment=true "
                         f"to keep it as a credit on the account")
    if kind in ("refund_out", "refund_in") and total_alloc != amount:
        raise BooksError("A refund must be allocated in full to the credit note(s) it refunds")
    docs = _lock_docs(db, org, {a["doc_id"] for a in allocs}) if allocs else {}
    _check_targets(docs, allocs, contact.id, PAYMENT_TARGET[kind], pay_date)
    control = system_acct(db, org, "ar_control" if kind in ("receive", "refund_out") else "ap_control")
    name = contact.name
    money_in = kind in ("receive", "refund_in")
    lines = [{"account_id": bank.id, ("debit" if money_in else "credit"): amount, "description": reference or f"{kind} {name}", "contact_name": name},
             {"account_id": control.id, ("credit" if kind in ("receive", "refund_in") else "debit"): amount,
              "description": reference or f"{kind} {name}", "contact_name": name}]
    pay = b.Payment(org_id=org.id, kind=kind, contact_id=contact.id, payment_date=pay_date, amount=amount, bank_account_id=bank.id,
                    reference=reference, status="posted", created_by=user_id)
    db.add(pay)
    db.flush()
    try:
        j = L.post_journal(db, org, journal_date=pay_date, lines=lines, narration=f"{kind.replace('_', ' ').title()} - {name}"
                           + (f" ({reference})" if reference else ""), source_type="payment", source_ref=f"payment:{pay.id}", created_by=user_id)
    except L.LedgerError as e:
        raise BooksError(str(e), 422)
    pay.journal_id = j.id
    for a in allocs:
        db.add(b.Allocation(org_id=org.id, payment_id=pay.id, doc_id=a["doc_id"], amount=a["amount"], alloc_date=pay_date))
    db.flush()
    for d in docs.values():
        recompute(db, d)
    return pay


def allocate_payment(db, org, payment, allocations):
    """Apply the unallocated remainder of a payment (an overpayment / prepayment) to further documents."""
    if payment.status != "posted":
        raise BooksError("This payment has been reversed", 409)
    allocs = _norm_allocs(allocations)
    if not allocs:
        raise BooksError("No allocations supplied")
    total = sum((a["amount"] for a in allocs), Decimal("0.00"))
    free = unallocated(db, payment)
    if total > free:
        raise BooksError(f"Only {free} of this payment is unallocated (you tried to allocate {total})", 422)
    if payment.kind in ("refund_out", "refund_in"):
        raise BooksError("A refund is fully allocated when it is created")
    docs = _lock_docs(db, org, {a["doc_id"] for a in allocs})
    on = max(payment.payment_date, max(docs[a["doc_id"]].issue_date for a in allocs))
    _check_targets(docs, allocs, payment.contact_id, PAYMENT_TARGET[payment.kind], on)
    for a in allocs:
        db.add(b.Allocation(org_id=org.id, payment_id=payment.id, doc_id=a["doc_id"], amount=a["amount"], alloc_date=on))
    db.flush()
    for d in docs.values():
        recompute(db, d)
    return payment


def allocate_credit(db, org, credit, allocations, alloc_date=None):
    """Apply a credit note / supplier credit to invoices / bills of the same contact (no ledger entry: the credit already posted)."""
    if credit.doc_type not in CREDIT_DOCS:
        raise BooksError("Only credit notes and supplier credits can be applied")
    if credit.status != "approved":
        raise BooksError(f"{credit.number} is {credit.status}; only an approved credit with a balance can be applied", 409)
    allocs = _norm_allocs(allocations)
    if not allocs:
        raise BooksError("No allocations supplied")
    total = sum((a["amount"] for a in allocs), Decimal("0.00"))
    if total > credit.amount_due:
        raise BooksError(f"Over-allocation: {total} exceeds the {credit.amount_due} remaining on {credit.number}", 422)
    want = "invoice" if credit.doc_type == "credit_note" else "bill"
    docs = _lock_docs(db, org, {a["doc_id"] for a in allocs})
    on = as_date(alloc_date) if alloc_date else max([credit.issue_date] + [docs[a["doc_id"]].issue_date for a in allocs])
    _check_targets(docs, allocs, credit.contact_id, want, on)
    for a in allocs:
        db.add(b.Allocation(org_id=org.id, credit_doc_id=credit.id, doc_id=a["doc_id"], amount=a["amount"], alloc_date=on))
    db.flush()
    for d in list(docs.values()) + [credit]:
        recompute(db, d)
    return credit


def reverse_payment(db, org, payment, user_id):
    if payment.status != "posted":
        raise BooksError("This payment is already reversed", 409)
    if payment.bank_line_id:
        raise BooksError("This payment is reconciled to a bank-statement line. Un-reconcile the line first", 409)
    doc_ids = {a.doc_id for a in payment.allocations if a.doc_id}
    docs = _lock_docs(db, org, doc_ids) if doc_ids else {}
    try:
        L.reverse_journal(db, org, payment.journal_id, reversal_date=payment.payment_date, narration=f"Reversal of payment {payment.id}",
                          created_by=user_id)
    except L.LedgerError as e:
        raise BooksError(str(e), 422)
    payment.status = "reversed"
    for a in list(payment.allocations):
        db.delete(a)
    db.flush()
    for d in docs.values():
        recompute(db, d)
    return payment


# ---------------------------------------------------------------------------- serialisation --
def line_dict(l):
    return dict(id=l.id, line_no=l.line_no, description=l.description, qty=str(l.qty), unit_price=str(l.unit_price),
                discount_pct=str(l.discount_pct), account_id=l.account_id, account_code=l.account.code if l.account else None,
                tax_code_id=l.tax_code_id, tax_code=l.tax_code.code if l.tax_code else None, net=str(l.net), tax=str(l.tax),
                gross=str(l.gross), tracking_option_ids=l.tracking_option_ids)


def doc_dict(db, doc, detail=True):
    d = dict(id=doc.id, doc_type=doc.doc_type, number=doc.number, contact_id=doc.contact_id, contact=doc.contact.name, status=doc.status,
             issue_date=doc.issue_date.isoformat(), due_date=doc.due_date.isoformat() if doc.due_date else None, reference=doc.reference,
             amounts_are=doc.amounts_are, currency=doc.currency, subtotal=str(doc.subtotal), tax_total=str(doc.tax_total),
             total=str(doc.total), amount_paid=str(doc.amount_paid), amount_credited=str(doc.amount_credited), amount_due=str(doc.amount_due),
             journal_id=doc.journal_id, parent_id=doc.parent_id, sent_at=doc.sent_at.isoformat() if doc.sent_at else None,
             source=doc.source)
    if detail:
        d["lines"] = [line_dict(l) for l in doc.lines]
        d["notes"], d["terms"] = doc.notes, doc.terms
        pays = db.query(b.Allocation, b.Payment).join(b.Payment, b.Payment.id == b.Allocation.payment_id) \
            .filter(b.Allocation.doc_id == doc.id).order_by(b.Allocation.id).all()
        d["payments"] = [dict(payment_id=p.id, date=a.alloc_date.isoformat(), amount=str(a.amount), kind=p.kind, status=p.status,
                              reference=p.reference) for a, p in pays]
        cr = db.query(b.Allocation).filter(b.Allocation.credit_doc_id.isnot(None),
                                           (b.Allocation.doc_id == doc.id) | (b.Allocation.credit_doc_id == doc.id)).order_by(b.Allocation.id).all()
        d["credits"] = [dict(credit_doc_id=a.credit_doc_id, doc_id=a.doc_id, date=a.alloc_date.isoformat(), amount=str(a.amount)) for a in cr]
        d["attachments"] = db.query(func.count(b.Attachment.id)).filter_by(org_id=doc.org_id, owner_kind="doc", owner_id=doc.id).scalar()
    return d


def payment_dict(db, p):
    return dict(id=p.id, kind=p.kind, contact_id=p.contact_id, contact=p.contact.name, date=p.payment_date.isoformat(), amount=str(p.amount),
                bank_account_id=p.bank_account_id, reference=p.reference, journal_id=p.journal_id, status=p.status,
                reconciled=bool(p.bank_line_id), unallocated=str(unallocated(db, p) if p.status == "posted" else Decimal("0.00")),
                allocations=[dict(doc_id=a.doc_id, amount=str(a.amount)) for a in p.allocations])
