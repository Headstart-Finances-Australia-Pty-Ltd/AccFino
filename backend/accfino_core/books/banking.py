"""
Banking & Reconciliation v2 (A4).

  * import      statement lines (JSON or CSV), idempotent: re-importing a file never duplicates a line
  * match       PRECISION FIRST. A line is only matched to an invoice/bill/recorded payment when the description carries the
                document's number (or the supplier's reference) AND the amount fits, or when the customer/supplier name is in the
                description and exactly one open document has exactly that amount. An amount on its own NEVER matches.
  * code        per-ORGANISATION bank rules, then what this organisation has taught the classifier. Nothing is shared between
                organisations (the legacy classifier tables are global; this replaces them for the ledger).
  * reconcile   match to a document (records the payment), match to a payment already recorded, create a spend/receive-money
                transaction (with GST and splits), transfer between accounts, exclude, un-reconcile.
  * report      bank reconciliation: statement balance vs ledger balance, with the items that explain any difference.
"""
import csv
import hashlib
import io
import re
from datetime import date, datetime, timedelta
from decimal import Decimal, InvalidOperation

from sqlalchemy import func

from accfino_core import models as m
from accfino_core.books import docs as D
from accfino_core.books import models as b
from accfino_core.books.common import BooksError, CONTROL_KEYS, as_date, bank_account, get_account, get_tax, money, system_acct
from accfino_core.ledger import fx as FX
from accfino_core.ledger import service as L

NOISE = {"card", "purchase", "eftpos", "visa", "mastercard", "debit", "credit", "payment", "pay", "transfer", "to", "from", "pty", "ltd", "the",
         "and", "of", "au", "aus", "australia", "aud", "direct", "deposit", "withdrawal", "ref", "reference", "internet", "banking", "bpay",
         "osko", "npp", "value", "date", "receipt", "tap", "contactless", "eft", "fee", "cash"}
DOC_TOKEN = re.compile(r"[A-Za-z]{1,8}[-_ ]?\d{2,}")


def tokens(desc: str):
    return [w for w in re.findall(r"[a-z]+", (desc or "").lower()) if w not in NOISE and len(w) > 2]


def merchant_key(desc: str) -> str:
    """The first meaningful word: 'Officeworks 2231 Sydney' and 'OFFICEWORKS MELB' are one merchant."""
    t = tokens(desc)
    return t[0][:120] if t else ""


def norm_ref(s: str) -> str:
    return re.sub(r"[^A-Z0-9]", "", (s or "").upper())


def desc_tokens(desc: str) -> set:
    return {norm_ref(t) for t in DOC_TOKEN.findall(desc or "")} | {norm_ref(t) for t in re.findall(r"\b\d{5,}\b", desc or "")}


def signed(row) -> Decimal:
    if row.get("amount") not in (None, ""):
        return money(row["amount"])
    return money(row.get("credit") or 0) - money(row.get("debit") or 0)


# ---------------------------------------------------------------------------------------------- import --
def _fp(org_id, bank_id, d, amt, desc, n):
    return hashlib.sha256(f"{org_id}|{bank_id}|{d}|{amt}|{desc.lower()}|{n}".encode()).hexdigest()


def matched_journal_ids(db, org, bank_id):
    ids = {j for (j,) in db.query(b.BankLine.journal_id).filter(b.BankLine.org_id == org.id, b.BankLine.bank_account_id == bank_id,
                                                                b.BankLine.journal_id.isnot(None))}
    ids |= {j for (j,) in db.query(b.Payment.journal_id).filter(b.Payment.org_id == org.id, b.Payment.bank_account_id == bank_id,
                                                                b.Payment.bank_line_id.isnot(None), b.Payment.journal_id.isnot(None))}
    return ids


def import_lines(db, org, user_id, bank, rows, *, adopt_existing=True):
    seen, created, dups, skipped, new = {}, 0, 0, 0, []
    for r in rows:
        d = as_date(r.get("date"), "line date")
        desc = ((r.get("description") or "").strip() or "(no description)")[:500]
        amt = signed(r)
        if amt == 0:
            skipped += 1
            continue
        key = (d, amt, desc.lower())
        seen[key] = seen.get(key, 0) + 1
        fp = _fp(org.id, bank.id, d, amt, desc, seen[key])
        if db.query(b.BankLine.id).filter_by(org_id=org.id, fingerprint=fp).first():
            dups += 1
            continue
        bal = money(r["balance"]) if r.get("balance") not in (None, "") else None
        line = b.BankLine(org_id=org.id, bank_account_id=bank.id, line_date=d, description=desc, amount=amt, balance=bal, fingerprint=fp)
        db.add(line)
        new.append(line)
        created += 1
    db.flush()
    adopted = 0
    if adopt_existing and new:                   # lines already in the ledger (e.g. from the Phase 0 bank sync) are linked, not re-posted
        used = matched_journal_ids(db, org, bank.id)
        # journals of recorded payments are reconciled through the payment path (match_payment), never adopted as anonymous ledger items
        used |= {j for (j,) in db.query(b.Payment.journal_id).filter(b.Payment.org_id == org.id, b.Payment.bank_account_id == bank.id, b.Payment.journal_id.isnot(None))}
        avail = db.query(m.JournalLine, m.Journal).join(m.Journal, m.Journal.id == m.JournalLine.journal_id) \
            .filter(m.JournalLine.org_id == org.id, m.JournalLine.account_id == bank.id, m.Journal.status == "posted",
                    m.Journal.reversal_of_id.is_(None)).all()
        pool = [(jl.debit - jl.credit, j.journal_date, j.id) for jl, j in avail if j.id not in used]
        for line in new:
            for i, (amt, jd, jid) in enumerate(pool):
                if amt == line.amount and jd == line.line_date:
                    line.status, line.matched_kind, line.journal_id, line.reconciled_at = "reconciled", "ledger", jid, datetime.utcnow()
                    line.note = "Already in the ledger (adopted, not re-posted)"
                    pool.pop(i)
                    adopted += 1
                    break
    db.flush()
    return dict(created=created, duplicates=dups, skipped=skipped, adopted_from_ledger=adopted, line_ids=[l.id for l in new])


DATE_FORMATS = ("%d/%m/%Y", "%d/%m/%y", "%Y-%m-%d", "%d-%m-%Y", "%d %b %Y", "%d-%b-%Y", "%d %B %Y")


def _pdate(s):
    s = (s or "").strip()
    for f in DATE_FORMATS:
        try:
            return datetime.strptime(s, f).date()
        except ValueError:
            pass
    return None


def _pamount(s):
    s = (s or "").strip().replace("$", "").replace(",", "").replace(" ", "")
    if not s:
        return None
    neg = s.startswith("(") and s.endswith(")") or s.upper().endswith("DR") or s.startswith("-")
    s = re.sub(r"[()\-]|CR$|DR$|cr$|dr$", "", s)
    try:
        v = Decimal(s)
    except InvalidOperation:
        return None
    return -v if neg else v


def parse_csv(raw: bytes):
    """Bank CSV -> rows. Handles a header row (date/description/amount or debit+credit/balance) or the header-less
    'date, amount, description, balance' layout some banks export. Returns (rows, warnings)."""
    text = raw.decode("utf-8-sig", errors="replace")
    grid = [r for r in csv.reader(io.StringIO(text)) if any(c.strip() for c in r)]
    if not grid:
        raise BooksError("The file is empty")
    warnings, rows = [], []
    first = grid[0]
    headerless = _pdate(first[0]) is not None
    if headerless:
        cols = dict(date=0, amount=1, description=2, balance=3 if len(first) > 3 else None)
        data = grid
    else:
        head = [h.strip().lower() for h in first]
        def find(*keys):
            for i, h in enumerate(head):
                if any(k in h for k in keys):
                    return i
            return None
        cols = dict(date=find("date"), description=find("description", "details", "narrative", "memo", "particulars", "transaction", "payee"),
                    amount=find("amount"), debit=find("debit", "withdrawal", "paid out", "money out"),
                    credit=find("credit", "deposit", "paid in", "money in"), balance=find("balance"))
        if cols["date"] is None or cols["description"] is None or (cols["amount"] is None and cols["debit"] is None and cols["credit"] is None):
            raise BooksError("Could not find the columns. Expected a header row with Date, Description and Amount (or Debit/Credit)")
        data = grid[1:]
    for n, r in enumerate(data, start=1 if headerless else 2):
        try:
            d = _pdate(r[cols["date"]])
            if d is None:
                warnings.append(f"row {n}: unreadable date '{r[cols['date']]}' - skipped")
                continue
            amt = _pamount(r[cols["amount"]]) if cols.get("amount") is not None else (
                (_pamount(r[cols["credit"]]) or 0 if cols.get("credit") is not None else 0) - abs(_pamount(r[cols["debit"]]) or 0 if cols.get("debit") is not None else 0))
            if amt is None:
                warnings.append(f"row {n}: unreadable amount - skipped")
                continue
            bal = _pamount(r[cols["balance"]]) if cols.get("balance") is not None and cols["balance"] < len(r) else None
            rows.append(dict(date=d.isoformat(), description=r[cols["description"]], amount=str(amt), balance=str(bal) if bal is not None else None))
        except IndexError:
            warnings.append(f"row {n}: too few columns - skipped")
    return rows, warnings


# ---------------------------------------------------------------------------------------------- matching --
def _open_docs(db, org, money_in):
    return db.query(b.Doc).filter(b.Doc.org_id == org.id, b.Doc.doc_type == ("invoice" if money_in else "bill"), b.Doc.status == "approved").all()


def _open_payments(db, org, money_in, bank_id):
    kinds = ("receive", "refund_in") if money_in else ("pay", "refund_out")
    q = db.query(b.Payment).filter(b.Payment.org_id == org.id, b.Payment.kind.in_(kinds), b.Payment.status == "posted", b.Payment.bank_line_id.is_(None))
    if bank_id:
        q = q.filter(b.Payment.bank_account_id == bank_id)
    return q.all()


def _refs(doc):
    return {r for r in (norm_ref(doc.number), norm_ref(doc.reference)) if len(r) >= 4}


def suggest_match(db, org, line, bank_id=None, _cache=None):
    """line = dict(date, description, amount(signed)). -> suggestion dict or None. See module docstring for the rules."""
    amt = line["amount"]
    if amt == 0:
        return None
    if bank_id is not None:
        acc = db.get(m.LedgerAccount, bank_id)
        if acc is not None and acc.foreign_currency:
            return None                # invoices and bills are in the base currency: a foreign-currency statement line is never auto-matched to one
    money_in = amt > 0
    absamt = abs(amt)
    dt = as_date(line["date"])
    toks = desc_tokens(line["description"])
    dtoks = set(tokens(line["description"]))
    cache = _cache if _cache is not None else {}
    docs = cache.setdefault(("docs", money_in), _open_docs(db, org, money_in))
    pays = cache.setdefault(("pays", money_in, bank_id), _open_payments(db, org, money_in, bank_id))
    hits = []
    for doc in docs:
        if not (_refs(doc) & toks) or dt < doc.issue_date:
            continue
        if absamt == doc.amount_due:
            hits.append((Decimal("0.99"), "invoice" if money_in else "bill", doc, None, "document number in the description and the exact amount"))
        elif absamt < doc.amount_due:
            hits.append((Decimal("0.90"), "invoice" if money_in else "bill", doc, None, "document number in the description; part-payment"))
    for p in pays:
        if p.amount != absamt:
            continue
        docs_of = [db.get(b.Doc, a.doc_id) for a in p.allocations if a.doc_id]
        pool = set(toks)
        if any(_refs(d) & pool for d in docs_of if d) or (p.reference and norm_ref(p.reference) and norm_ref(p.reference) in {norm_ref(t) for t in DOC_TOKEN.findall(line["description"])}):
            d0 = docs_of[0] if docs_of else None
            hits.append((Decimal("0.99"), "payment", d0, p, "matches a payment already recorded against " + (d0.number if d0 else "this contact")))
    if not hits:                                   # contact name + exact amount, only when unambiguous
        by_contact = {}
        for doc in docs:
            nm = {w for w in tokens(doc.contact.name)}
            if nm and (len(nm) >= 2 or max(len(w) for w in nm) >= 6) and nm <= dtoks and doc.amount_due == absamt and dt >= doc.issue_date:
                by_contact.setdefault(doc.contact_id, []).append(doc)
        ok = [v[0] for v in by_contact.values() if len(v) == 1]
        if len(ok) == 1:
            hits.append((Decimal("0.90"), "invoice" if money_in else "bill", ok[0], None, "customer/supplier name in the description and the exact amount"))
    if not hits:
        return None
    hits.sort(key=lambda h: h[0], reverse=True)
    top = [h for h in hits if h[0] == hits[0][0]]
    # A deposit that equals a payment ALREADY RECORDED is that payment: matching it to the (part-paid) invoice again would record the money twice.
    paid = [h for h in top if h[1] == "payment"]
    if paid:
        top = sorted(paid, key=lambda h: h[3].id)
    if len({h[2].id if h[2] else None for h in top}) > 1 or (not paid and len({(h[1], h[2].id if h[2] else None) for h in top}) > 1):
        return None                                # ambiguous between different documents: refuse to guess
    conf, kind, doc, pay, why = top[0]
    return dict(kind=kind, doc_id=doc.id if doc else None, payment_id=pay.id if pay else None, reference=doc.number if doc else None,
                contact=(doc.contact.name if doc else pay.contact.name), confidence=str(conf), reason=why, amount=str(absamt))


# ---------------------------------------------------------------------------------------------- classifier --
def classify(db, org, description, amount):
    """Per-organisation coding: rules first (priority order), then what this organisation has taught."""
    amt = money(amount)
    direction = "in" if amt > 0 else "out"
    for r in db.query(b.BankRule).filter_by(org_id=org.id, is_active=True).order_by(b.BankRule.priority, b.BankRule.id):
        if r.direction not in ("any", direction):
            continue
        if r.min_amount is not None and abs(amt) < r.min_amount or r.max_amount is not None and abs(amt) > r.max_amount:
            continue
        text = (description or "")
        ok = (r.pattern.lower() in text.lower() if r.match_type == "contains" else text.lower().startswith(r.pattern.lower())
              if r.match_type == "startswith" else bool(_safe_re(r.pattern, text)))
        if ok:
            return _coding(db, r.account_id, r.tax_code_id, r.contact_name, r.description, f"rule:{r.id}", r.name)
    key = merchant_key(description)
    if key:
        mem = db.query(b.ClassifierMemory).filter_by(org_id=org.id, key=key).one_or_none()
        if mem:
            return _coding(db, mem.account_id, mem.tax_code_id, mem.contact_name, None, "learned", f"learned from {mem.hits} earlier coding(s)")
    return None


def _safe_re(pat, text):
    try:
        return re.search(pat, text, re.I) if len(pat) <= 200 else None
    except re.error:
        return None


def _coding(db, account_id, tax_id, contact, desc, source, why):
    a = db.get(m.LedgerAccount, account_id)
    t = db.get(m.TaxCode, tax_id) if tax_id else None
    return dict(account_id=account_id, account_code=a.code if a else None, account_name=a.name if a else None, tax_code_id=tax_id,
                tax_code=t.code if t else None, contact_name=contact, description=desc, source=source, why=why)


def teach(db, org, description, account_ref, tax_ref=None, contact_name=None):
    key = merchant_key(description)
    if not key:
        raise BooksError("The description has no recognisable merchant name to learn from")
    acc = get_account(db, org, account_ref)
    tax = get_tax(db, org, tax_ref) if tax_ref else None
    mem = db.query(b.ClassifierMemory).filter_by(org_id=org.id, key=key).one_or_none()
    if mem is None:
        mem = b.ClassifierMemory(org_id=org.id, key=key, account_id=acc.id, tax_code_id=tax.id if tax else None, contact_name=contact_name, hits=1)
        db.add(mem)
    else:
        same = mem.account_id == acc.id
        mem.account_id, mem.tax_code_id, mem.contact_name = acc.id, tax.id if tax else None, contact_name or mem.contact_name
        mem.hits = mem.hits + 1 if same else 1
    db.flush()
    return mem


# ---------------------------------------------------------------------------------------------- reconcile --
def _need_unreconciled(line):
    if line.status != "unreconciled":
        raise BooksError(f"This bank line is {line.status}", 409)


def _link(db, line, user_id, kind, *, payment=None, journal_id=None, contact_id=None):
    line.status, line.matched_kind, line.reconciled_at, line.reconciled_by = "reconciled", kind, datetime.utcnow(), user_id
    line.payment_id = payment.id if payment else None
    line.journal_id = journal_id if journal_id else (payment.journal_id if payment else None)
    line.contact_id = contact_id
    if payment:
        payment.bank_line_id = line.id
    db.flush()


def match_doc(db, org, user_id, line, doc_id):
    _need_unreconciled(line)
    _bank = db.get(m.LedgerAccount, line.bank_account_id)
    if _bank is not None and _bank.foreign_currency:
        raise BooksError(f"{_bank.code} {_bank.name} is held in {_bank.foreign_currency}, but invoices and bills are in {FX.base_currency(org)}. "
                         "Record this line with Spend/Receive money (it books the exchange rate and any realised gain or loss), or convert to the base-currency account first", 422)
    doc = db.query(b.Doc).filter_by(org_id=org.id, id=doc_id).with_for_update().one_or_none()
    if doc is None:
        raise BooksError("Document not found", 404)
    money_in = line.amount > 0
    if doc.doc_type != ("invoice" if money_in else "bill"):
        raise BooksError("Money in matches an invoice; money out matches a bill")
    bank = db.get(m.LedgerAccount, line.bank_account_id)
    pay = D.record_payment(db, org, user_id, kind="receive" if money_in else "pay", contact=doc.contact, pay_date=line.line_date,
                           amount=abs(line.amount), bank_ref=bank.id, reference=line.description[:200],
                           allocations=[dict(doc_id=doc.id, amount=abs(line.amount))])
    _link(db, line, user_id, "payment", payment=pay, contact_id=doc.contact_id)
    return pay


def match_payment(db, org, user_id, line, payment_id):
    _need_unreconciled(line)
    pay = db.query(b.Payment).filter_by(org_id=org.id, id=payment_id).with_for_update().one_or_none()
    if pay is None or pay.status != "posted":
        raise BooksError("Payment not found or reversed", 404)
    if pay.bank_line_id:
        raise BooksError("That payment is already reconciled to another line", 409)
    if pay.bank_account_id != line.bank_account_id:
        raise BooksError("The payment was recorded against a different bank account")
    if pay.amount != abs(line.amount) or (line.amount > 0) != (pay.kind in ("receive", "refund_in")):
        raise BooksError("The amount or direction of the payment does not match the bank line")
    _link(db, line, user_id, "payment", payment=pay, contact_id=pay.contact_id)
    return pay


def _create_foreign(db, org, user_id, line, bank, *, account, tax_code, contact, description, splits, learn, rate):
    """Spend/receive money on a foreign-held account. The statement amount is in the account's currency. Money IN is booked at spot; money OUT leaves the
    account at its average cost, and the difference to the spot value of what was bought is a realised gain/loss. GST is calculated on the DOLLAR amount."""
    ccy = bank.foreign_currency
    money_in = line.amount > 0
    gross_f = abs(line.amount)
    parts = splits or [dict(account=account, tax_code=tax_code, amount=gross_f, description=description)]
    if sum((money(p.get("amount")) for p in parts), Decimal("0.00")) != gross_f:
        raise BooksError(f"The split amounts must add up to the bank line ({gross_f} {ccy})")
    sp = FX.spot(db, org, ccy, line.line_date, rate)
    gst_acc = system_acct(db, org, "gst")
    others, gst_by, name = [], {}, contact or None
    sign = -1 if money_in else 1                 # the coding side is the opposite of the bank side
    for i, p in enumerate(parts, start=1):
        acc = get_account(db, org, p.get("account"), what=f"Split {i} account")
        if acc.system_key in CONTROL_KEYS or acc.account_type in ("bank", "credit_card"):
            raise BooksError(f"Split {i}: {acc.code} {acc.name} cannot be used here (use Transfer for bank-to-bank movements)")
        if acc.foreign_currency:
            raise BooksError(f"Split {i}: {acc.code} {acc.name} is itself a foreign-currency account; use Transfer")
        tax = get_tax(db, org, p.get("tax_code")) if p.get("tax_code") not in (None, "") else (db.get(m.TaxCode, acc.default_tax_code_id) if acc.default_tax_code_id else None)
        if tax is not None and tax.applies_to not in (("sales", "both") if money_in else ("purchases", "both")):
            raise BooksError(f"Split {i}: tax code {tax.code} cannot be used for money {'in' if money_in else 'out'}")
        g_f = money(p["amount"])
        g_b = FX.q2(g_f * sp)                                                # the consideration in dollars
        r = Decimal(tax.rate) if (tax is not None and org.gst_registered) else Decimal(0)
        t_b = money(g_b * r / (1 + r)) if r else Decimal("0.00")             # GST in dollars (what the BAS needs)
        t_f = money(g_f * r / (1 + r)) if r else Decimal("0.00")
        others.append(dict(account_id=acc.id, signed=sign * (g_b - t_b), orig=sign * (g_f - t_f), tax_code_id=tax.id if tax else None, tax_amount=t_b,
                           description=(p.get("description") or description or line.description)[:500], contact_name=name))
        if t_b:
            cur = gst_by.setdefault(tax.id, [Decimal(0), Decimal(0)])
            cur[0] += t_b
            cur[1] += t_f
    for tid, (tb, tf) in gst_by.items():
        others.append(dict(account_id=gst_acc.id, signed=sign * tb, orig=sign * tf, tax_code_id=tid, description=f"GST - {line.description}"[:500], contact_name=name))
    delta_f = gross_f if money_in else -gross_f
    signed_bank = FX.carry(db, org, bank, delta_f, sp, line.line_date)
    lines, realised = FX.build_fx_journal(db, org, [dict(account_id=bank.id, signed=signed_bank, orig=delta_f, description=line.description[:500], contact_name=name)],
                                          other_lines=others, currency=ccy, rate=sp)
    try:
        j = L.post_journal(db, org, journal_date=line.line_date, lines=lines, narration=f"{'Receive' if money_in else 'Spend'} money ({ccy} {gross_f} @ {sp.normalize():f}): {line.description}"[:500],
                           source_type="bank_line", source_ref=f"bankline:{line.id}", created_by=user_id, currency=ccy, exchange_rate=sp)
    except L.LedgerError as e:
        raise BooksError(str(e), 422)
    cid = None
    if name:
        c = db.query(b.Contact).filter(b.Contact.org_id == org.id, func.lower(b.Contact.name) == name.lower()).first()
        cid = c.id if c else None
    _link(db, line, user_id, "receive" if money_in else "spend", journal_id=j.id, contact_id=cid)
    if learn and len(parts) == 1:
        try:
            teach(db, org, line.description, parts[0]["account"], parts[0].get("tax_code"), name)
        except BooksError:
            pass
    j.fx_realised = realised                                      # transient, for the API response only
    return j


def create_from_line(db, org, user_id, line, *, account=None, tax_code=None, contact=None, description=None, splits=None, learn=True, rate=None):
    """Spend money / receive money coded directly to the ledger. Bank amounts are GST-inclusive. On a foreign-held account the line is in that currency."""
    _need_unreconciled(line)
    bank = db.get(m.LedgerAccount, line.bank_account_id)
    if bank.foreign_currency:
        return _create_foreign(db, org, user_id, line, bank, account=account, tax_code=tax_code, contact=contact, description=description, splits=splits, learn=learn, rate=rate)
    money_in = line.amount > 0
    gross_total = abs(line.amount)
    parts = splits or [dict(account=account, tax_code=tax_code, amount=gross_total, description=description)]
    if sum((money(p.get("amount")) for p in parts), Decimal("0.00")) != gross_total:
        raise BooksError(f"The split amounts must add up to the bank line ({gross_total})")
    gst_acc = system_acct(db, org, "gst")
    lines, gst_by = [], {}
    name = contact or None
    for i, p in enumerate(parts, start=1):
        acc = get_account(db, org, p.get("account"), what=f"Split {i} account")
        if acc.system_key in CONTROL_KEYS or acc.account_type in ("bank", "credit_card"):
            raise BooksError(f"Split {i}: {acc.code} {acc.name} cannot be used here (use Transfer for bank-to-bank movements)")
        tax = get_tax(db, org, p.get("tax_code")) if p.get("tax_code") not in (None, "") else (db.get(m.TaxCode, acc.default_tax_code_id) if acc.default_tax_code_id else None)
        if tax is not None and tax.applies_to not in (("sales", "both") if money_in else ("purchases", "both")):
            raise BooksError(f"Split {i}: tax code {tax.code} cannot be used for money {'in' if money_in else 'out'}")
        gross = money(p["amount"])
        rate = Decimal(tax.rate) if (tax is not None and org.gst_registered) else Decimal(0)
        taxamt = money(gross * rate / (1 + rate)) if rate else Decimal("0.00")
        net = gross - taxamt
        lines.append({"account_id": acc.id, ("credit" if money_in else "debit"): net, "tax_code_id": tax.id if tax else None, "tax_amount": taxamt,
                      "description": (p.get("description") or description or line.description)[:500], "contact_name": name})
        if taxamt:
            gst_by[tax.id] = gst_by.get(tax.id, Decimal(0)) + taxamt
    for tid, amt in gst_by.items():
        lines.append({"account_id": gst_acc.id, ("credit" if money_in else "debit"): amt, "tax_code_id": tid, "description": f"GST - {line.description}"[:500],
                      "contact_name": name})
    lines.insert(0, {"account_id": bank.id, ("debit" if money_in else "credit"): gross_total, "description": line.description[:500], "contact_name": name})
    try:
        j = L.post_journal(db, org, journal_date=line.line_date, lines=lines, narration=f"{'Receive' if money_in else 'Spend'} money: {line.description}"[:500],
                           source_type="bank_line", source_ref=f"bankline:{line.id}", created_by=user_id)
    except L.LedgerError as e:
        raise BooksError(str(e), 422)
    cid = None
    if name:
        c = db.query(b.Contact).filter(b.Contact.org_id == org.id, func.lower(b.Contact.name) == name.lower()).first()
        cid = c.id if c else None
    _link(db, line, user_id, "receive" if money_in else "spend", journal_id=j.id, contact_id=cid)
    if learn and len(parts) == 1:
        try:
            teach(db, org, line.description, parts[0]["account"], parts[0].get("tax_code"), name)
        except BooksError:
            pass
    return j


def _transfer_foreign(db, org, user_id, line, bank, other, pair_line_id, other_amount, rate):
    """A transfer where at least one account is foreign-held. Currency conversions (AUD<->USD) use the amounts the bank actually moved, so the implied rate is
    exact and any realised gain/loss on the foreign side is booked; two DIFFERENT foreign currencies must go through the base-currency account."""
    out = line.amount < 0
    a_out, a_in = (bank, other) if out else (other, bank)
    c_out, c_in = a_out.foreign_currency, a_in.foreign_currency
    if c_out and c_in and c_out != c_in:
        raise BooksError(f"{c_out} to {c_in} cannot be transferred directly. Convert to {FX.base_currency(org)} first (one transfer each way) so each conversion has a real rate")
    this_amt = abs(line.amount)
    pair = None
    if pair_line_id:
        pair = db.query(b.BankLine).filter(b.BankLine.org_id == org.id, b.BankLine.bank_account_id == other.id, b.BankLine.status == "unreconciled",
                                           b.BankLine.id == pair_line_id).first()
        if pair is None:
            raise BooksError("The paired line was not found (it must be an unreconciled line of the other account)")
        if (pair.amount > 0) == (line.amount > 0):
            raise BooksError("The paired line must move money the opposite way")
    other_amt = abs(pair.amount) if pair else (money(other_amount) if other_amount not in (None, "") else None)
    if other_amt is None and c_out == c_in:
        other_amt = this_amt                                             # same currency both sides: the same number
    if other_amt is None or other_amt <= 0:
        raise BooksError(f"{bank.code} is in {bank.foreign_currency or FX.base_currency(org)} and {other.code} is in {other.foreign_currency or FX.base_currency(org)}: "
                         "choose the paired statement line, or enter the amount that arrived, so the exchange rate is the real one")
    out_amt, in_amt = (this_amt, other_amt) if out else (other_amt, this_amt)
    ccy = c_out or c_in
    if c_out and not c_in:                      # foreign -> base: the base amount received is what it is; the foreign side leaves at cost
        rate_used = FX.q2(in_amt) / FX.q2(out_amt)
        signed_out = FX.carry(db, org, a_out, -out_amt, rate_used, line.line_date)
        signed_in = FX.q2(in_amt)
        legs_f = [dict(account_id=a_out.id, signed=signed_out, orig=-FX.q2(out_amt), description=line.description[:500])]
        legs_o = [dict(account_id=a_in.id, signed=signed_in, orig=None, description=line.description[:500])]
    elif c_in and not c_out:                    # base -> foreign: the base amount paid is what it is
        rate_used = FX.q2(out_amt) / FX.q2(in_amt)
        signed_in = FX.carry(db, org, a_in, FX.q2(in_amt), rate_used, line.line_date)
        legs_f = [dict(account_id=a_in.id, signed=signed_in, orig=FX.q2(in_amt), description=line.description[:500])]
        legs_o = [dict(account_id=a_out.id, signed=-FX.q2(out_amt), orig=None, description=line.description[:500])]
    else:                                       # same foreign currency both sides: move at the source's cost, no gain
        sp = FX.spot(db, org, ccy, line.line_date, rate)
        signed_out = FX.carry(db, org, a_out, -FX.q2(out_amt), sp, line.line_date)
        rate_used = abs(signed_out) / FX.q2(out_amt)
        signed_in = FX.carry(db, org, a_in, FX.q2(in_amt), rate_used, line.line_date)
        legs_f = [dict(account_id=a_out.id, signed=signed_out, orig=-FX.q2(out_amt), description=line.description[:500]),
                  dict(account_id=a_in.id, signed=signed_in, orig=FX.q2(in_amt), description=line.description[:500])]
        legs_o = []
    rate_used = rate_used.quantize(Decimal("0.00000001"))
    lines, realised = FX.build_fx_journal(db, org, legs_f, other_lines=legs_o, currency=ccy, rate=rate_used)
    try:
        j = L.post_journal(db, org, journal_date=line.line_date, lines=lines, narration=f"Transfer {bank.code} {'to' if out else 'from'} {other.code} ({ccy} @ {rate_used.normalize():f})",
                           source_type="bank_line", source_ref=f"bankline:{line.id}", created_by=user_id, currency=ccy, exchange_rate=rate_used)
    except L.LedgerError as e:
        raise BooksError(str(e), 422)
    _link(db, line, user_id, "transfer", journal_id=j.id)
    if pair:
        _link(db, pair, user_id, "transfer", journal_id=j.id)
    j.fx_realised = realised
    return j, pair


def transfer(db, org, user_id, line, to_ref, pair_line_id=None, other_amount=None, rate=None):
    _need_unreconciled(line)
    other = bank_account(db, org, to_ref)
    bank = db.get(m.LedgerAccount, line.bank_account_id)
    if other.id == bank.id:
        raise BooksError("Choose a different account for the transfer")
    if bank.foreign_currency or other.foreign_currency:
        return _transfer_foreign(db, org, user_id, line, bank, other, pair_line_id, other_amount, rate)
    amt = abs(line.amount)
    out = line.amount < 0
    pair = None
    q = db.query(b.BankLine).filter(b.BankLine.org_id == org.id, b.BankLine.bank_account_id == other.id, b.BankLine.status == "unreconciled",
                                    b.BankLine.amount == -line.amount)
    if pair_line_id:
        pair = q.filter(b.BankLine.id == pair_line_id).first()
        if pair is None:
            raise BooksError("The paired line was not found (it must be an unreconciled line of the other account with the opposite amount)")
    else:
        pair = q.filter(b.BankLine.line_date.between(line.line_date - timedelta(days=3), line.line_date + timedelta(days=3))).order_by(b.BankLine.id).first()
    lines = [{"account_id": (other.id if out else bank.id), "debit": amt, "description": line.description[:500]},
             {"account_id": (bank.id if out else other.id), "credit": amt, "description": line.description[:500]}]
    try:
        j = L.post_journal(db, org, journal_date=line.line_date, lines=lines, narration=f"Transfer {bank.code} {'to' if out else 'from'} {other.code}",
                           source_type="bank_line", source_ref=f"bankline:{line.id}", created_by=user_id)
    except L.LedgerError as e:
        raise BooksError(str(e), 422)
    _link(db, line, user_id, "transfer", journal_id=j.id)
    if pair:
        _link(db, pair, user_id, "transfer", journal_id=j.id)
    return j, pair


def exclude(db, line):
    _need_unreconciled(line)
    line.status = "excluded"
    db.flush()


def unreconcile(db, org, user_id, line, *, reverse=True):
    if line.status == "excluded":
        line.status = "unreconciled"
        db.flush()
        return line
    if line.status != "reconciled":
        raise BooksError("This bank line is not reconciled", 409)
    kind, jid = line.matched_kind, line.journal_id
    if kind == "payment":
        pay = db.get(b.Payment, line.payment_id)
        if pay:
            pay.bank_line_id = None
            db.flush()
            if reverse and pay.status == "posted":
                D.reverse_payment(db, org, pay, user_id)
    elif kind in ("spend", "receive", "transfer") and jid:
        if reverse:
            try:
                L.reverse_journal(db, org, jid, reversal_date=line.line_date, narration=f"Un-reconcile: {line.description}"[:500], created_by=user_id)
            except L.LedgerError as e:
                raise BooksError(str(e), 422)
        for other in db.query(b.BankLine).filter(b.BankLine.org_id == org.id, b.BankLine.journal_id == jid, b.BankLine.id != line.id):
            other.status, other.matched_kind, other.journal_id, other.reconciled_at = "unreconciled", None, None, None
    line.status, line.matched_kind, line.payment_id, line.journal_id, line.contact_id, line.reconciled_at = "unreconciled", None, None, None, None, None
    db.flush()
    return line


def apply_suggestion(db, org, user_id, line, s):
    if s["kind"] == "payment":
        return match_payment(db, org, user_id, line, s["payment_id"])
    return match_doc(db, org, user_id, line, s["doc_id"])


def auto_reconcile(db, org, user_id, *, bank_id=None, min_confidence=Decimal("0.99"), dry_run=False):
    q = db.query(b.BankLine).filter_by(org_id=org.id, status="unreconciled").order_by(b.BankLine.line_date, b.BankLine.id)
    if bank_id:
        q = q.filter(b.BankLine.bank_account_id == bank_id)
    done, skipped = [], 0
    for line in q.all():
        s = suggest_match(db, org, dict(date=line.line_date, description=line.description, amount=line.amount), line.bank_account_id)
        if s and Decimal(s["confidence"]) >= min_confidence:
            done.append(dict(line_id=line.id, **s))
            if not dry_run:
                try:
                    with db.begin_nested():
                        apply_suggestion(db, org, user_id, line, s)
                except BooksError as e:
                    done[-1]["error"] = str(e)
        else:
            skipped += 1
    return dict(matched=[d for d in done if "error" not in d], failed=[d for d in done if "error" in d], left_for_review=skipped, dry_run=dry_run)


# ---------------------------------------------------------------------------------------------- report --
def line_dict(l):
    return dict(id=l.id, bank_account_id=l.bank_account_id, date=l.line_date.isoformat(), description=l.description, amount=str(l.amount),
                balance=str(l.balance) if l.balance is not None else None, status=l.status, matched_kind=l.matched_kind, payment_id=l.payment_id,
                journal_id=l.journal_id, note=l.note)


def reconciliation_report(db, org, bank, as_at, statement_balance=None):
    foreign = bank.foreign_currency
    if foreign:
        ledger_bal, _cost = FX.position(db, org, bank, as_at)                    # the account's balance IN ITS OWN CURRENCY, compared with the statement
    else:
        ledger_bal = db.query(func.coalesce(func.sum(m.JournalLine.debit - m.JournalLine.credit), 0)).join(m.Journal, m.Journal.id == m.JournalLine.journal_id) \
            .filter(m.JournalLine.org_id == org.id, m.JournalLine.account_id == bank.id, m.Journal.journal_date <= as_at).scalar()
    ledger_bal = money(ledger_bal)
    used = matched_journal_ids(db, org, bank.id)
    rows = db.query(m.JournalLine, m.Journal).join(m.Journal, m.Journal.id == m.JournalLine.journal_id) \
        .filter(m.JournalLine.org_id == org.id, m.JournalLine.account_id == bank.id, m.Journal.journal_date <= as_at).order_by(m.Journal.journal_date, m.Journal.id).all()
    # a reversed journal and its reversal cancel each other; only genuinely open ledger items are reported
    reversed_ids = {j.id for _, j in rows if j.status == "reversed"} | {j.reversal_of_id for _, j in rows if j.reversal_of_id}
    unmatched = [dict(journal_id=j.id, journal_no=j.journal_no, date=j.journal_date.isoformat(), description=j.narration,
                      amount=str((jl.orig_debit or 0) - (jl.orig_credit or 0) if foreign else jl.debit - jl.credit))
                 for jl, j in rows if j.id not in used and j.id not in reversed_ids and not (foreign and j.source_type in L.FX_EXEMPT_SOURCES)]
    unmatched_net = sum((Decimal(u["amount"]) for u in unmatched), Decimal("0.00"))
    open_lines = db.query(b.BankLine).filter(b.BankLine.org_id == org.id, b.BankLine.bank_account_id == bank.id, b.BankLine.line_date <= as_at,
                                             b.BankLine.status.in_(("unreconciled", "excluded"))).order_by(b.BankLine.line_date).all()
    unrec = [l for l in open_lines if l.status == "unreconciled"]
    excl = [l for l in open_lines if l.status == "excluded"]
    unrec_net, excl_net = sum((l.amount for l in unrec), Decimal("0.00")), sum((l.amount for l in excl), Decimal("0.00"))
    if statement_balance is None:
        last = db.query(b.BankLine).filter(b.BankLine.org_id == org.id, b.BankLine.bank_account_id == bank.id, b.BankLine.line_date <= as_at,
                                           b.BankLine.balance.isnot(None)).order_by(b.BankLine.line_date.desc(), b.BankLine.id.desc()).first()
        statement_balance = last.balance if last else None
    else:
        statement_balance = money(statement_balance)
    out = dict(account=dict(id=bank.id, code=bank.code, name=bank.name, currency=foreign or FX.base_currency(org)), as_at=as_at.isoformat(), ledger_balance=str(ledger_bal),
               statement_balance=str(statement_balance) if statement_balance is not None else None,
               unreconciled_statement_lines=dict(count=len(unrec), net=str(unrec_net), lines=[line_dict(l) for l in unrec[:200]]),
               excluded_statement_lines=dict(count=len(excl), net=str(excl_net)),
               unmatched_ledger_items=dict(count=len(unmatched), net=str(unmatched_net), items=unmatched[:200]))
    if statement_balance is not None:
        matched_statement = statement_balance - unrec_net - excl_net
        matched_ledger = ledger_bal - unmatched_net
        out["difference"] = str(matched_statement - matched_ledger)
        out["reconciled"] = matched_statement == matched_ledger and not unrec and not unmatched
        out["explanation"] = ("statement balance less items not yet in the ledger, compared with ledger balance less items not yet on the statement")
    return out


def account_summary(db, org):
    out = []
    for a in db.query(m.LedgerAccount).filter(m.LedgerAccount.org_id == org.id, m.LedgerAccount.account_type.in_(("bank", "credit_card")),
                                              m.LedgerAccount.is_active.is_(True)).order_by(m.LedgerAccount.code):
        bal = db.query(func.coalesce(func.sum(m.JournalLine.debit - m.JournalLine.credit), 0)).filter(m.JournalLine.org_id == org.id, m.JournalLine.account_id == a.id).scalar()
        n = db.query(func.count(b.BankLine.id)).filter_by(org_id=org.id, bank_account_id=a.id, status="unreconciled").scalar()
        last = db.query(func.max(b.BankLine.line_date)).filter_by(org_id=org.id, bank_account_id=a.id).scalar()
        base_val = money(bal)
        if a.foreign_currency:
            bal, _c = FX.position(db, org, a, None)                              # show the foreign balance; the dollar value is alongside
        out.append(dict(id=a.id, code=a.code, name=a.name, type=a.account_type, bank_name=a.bank_name, bank_account_ref=a.bank_account_ref,
                        currency=a.foreign_currency or FX.base_currency(org), foreign=bool(a.foreign_currency), base_value=str(base_val),
                        ledger_balance=str(money(bal)), unreconciled=n, last_statement_date=last.isoformat() if last else None))
    return out
