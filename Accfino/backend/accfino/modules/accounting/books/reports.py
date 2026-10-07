"""
A6 - financial reports derived ONLY from the ledger and the allocations (never from the legacy tables).

  aged(...)            aged receivables / payables by days overdue, per contact, with a CONTROL CHECK against the AR/AP ledger balance
  statement(...)       a customer/supplier statement with running balance
  gst_summary(...)     BAS-style GST report (G1..G15, 1A, 1B) on accrual or cash basis, reconciled to the GST ledger account
  cash_flow(...)       indirect cash-flow statement; the net movement must equal the change in bank balances
  by_contact(...)      sales by customer / spend by supplier
  dashboard(...)       what is owing, overdue, in draft
"""
from collections import defaultdict
from datetime import date, timedelta
from decimal import Decimal

from sqlalchemy import func

from accfino.core import models as m
from accfino.modules.accounting.models import ledger as lm
from accfino.modules.accounting.books import models as b
from accfino.modules.accounting.books.common import BooksError, money, system_acct

BUCKETS = ("current", "1-30", "31-60", "61-90", "90+")
Z = Decimal("0.00")


def bucket_of(as_at, due):
    late = (as_at - due).days
    return "current" if late <= 0 else "1-30" if late <= 30 else "31-60" if late <= 60 else "61-90" if late <= 90 else "90+"


def _settled_asat(db, org, as_at):
    """{doc_id: amount settled on or before as_at} from payment AND credit allocations (both sides of a credit application)."""
    out = defaultdict(lambda: Z)
    for a in db.query(b.Allocation).filter(b.Allocation.org_id == org.id, b.Allocation.alloc_date <= as_at):
        if a.doc_id:
            out[a.doc_id] += a.amount
        if a.credit_doc_id:
            out[a.credit_doc_id] += a.amount
    return out


def control_balance(db, org, key, as_at):
    acc = system_acct(db, org, key)
    r = db.query(func.coalesce(func.sum(lm.JournalLine.debit - lm.JournalLine.credit), 0)).join(lm.Journal, lm.Journal.id == lm.JournalLine.journal_id) \
        .filter(lm.JournalLine.org_id == org.id, lm.JournalLine.account_id == acc.id, lm.Journal.journal_date <= as_at).scalar()
    return money(r) if key == "ar_control" else -money(r)


def aged(db, org, side, as_at):
    main, credit = ("invoice", "credit_note") if side == "sales" else ("bill", "supplier_credit")
    pkind = "receive" if side == "sales" else "pay"
    settled = _settled_asat(db, org, as_at)
    docs = db.query(b.Doc).filter(b.Doc.org_id == org.id, b.Doc.doc_type.in_((main, credit)), b.Doc.status.in_(("approved", "paid")),
                                  b.Doc.issue_date <= as_at).all()
    contacts, total = {}, Z
    tot_b = {k: Z for k in BUCKETS}

    def row(c):
        return contacts.setdefault(c.id, dict(contact_id=c.id, contact=c.name, docs=[], **{k: Z for k in BUCKETS}, total=Z))

    def add(c, bucket, amount, item):
        nonlocal total
        r = row(c)
        r[bucket] += amount
        r["total"] += amount
        r["docs"].append(item)
        tot_b[bucket] += amount
        total += amount

    for d in docs:
        owing = d.total - settled.get(d.id, Z)
        if owing == 0:
            continue
        if d.doc_type == main:
            bk = bucket_of(as_at, d.due_date or d.issue_date)
            add(d.contact, bk, owing, dict(kind=main, number=d.number, reference=d.reference, date=d.issue_date.isoformat(),
                                           due=(d.due_date or d.issue_date).isoformat(), amount=str(owing), days_overdue=max((as_at - (d.due_date or d.issue_date)).days, 0)))
        else:                                                      # credit note / supplier credit still to apply: a negative
            add(d.contact, "current", -owing, dict(kind=credit, number=d.number, date=d.issue_date.isoformat(), amount=str(-owing)))
    for p in db.query(b.Payment).filter(b.Payment.org_id == org.id, b.Payment.kind == pkind, b.Payment.status == "posted", b.Payment.payment_date <= as_at):
        used = sum((a.amount for a in p.allocations if a.alloc_date <= as_at), Z)
        free = p.amount - used
        if free > 0:
            add(p.contact, "current", -free, dict(kind="unallocated payment", number=str(p.id), reference=p.reference, date=p.payment_date.isoformat(), amount=str(-free)))
    ledger = control_balance(db, org, "ar_control" if side == "sales" else "ap_control", as_at)
    rows = sorted(contacts.values(), key=lambda r: r["contact"].lower())
    for r in rows:
        for k in (*BUCKETS, "total"):
            r[k] = str(r[k])
    return dict(as_at=as_at.isoformat(), side=side, buckets={k: str(v) for k, v in tot_b.items()}, total=str(total), contacts=rows,
                control=dict(ledger_balance=str(ledger), subledger_total=str(total), difference=str(ledger - total), reconciled=(ledger == total),
                             note="A difference means something was posted to the control account outside invoices/bills/payments (e.g. a manual journal)."))


def statement(db, org, contact, as_at):
    sales = contact.is_customer
    main, credit = ("invoice", "credit_note") if sales else ("bill", "supplier_credit")
    ev = []
    for d in db.query(b.Doc).filter(b.Doc.org_id == org.id, b.Doc.contact_id == contact.id, b.Doc.doc_type.in_((main, credit)),
                                    b.Doc.status.in_(("approved", "paid")), b.Doc.issue_date <= as_at):
        inc = d.doc_type == main
        ev.append((d.issue_date, 0, d.number, f"{'Invoice' if sales else 'Bill'} {d.number}" if inc else f"{'Credit note' if sales else 'Supplier credit'} {d.number}",
                   d.total if inc else Z, Z if inc else d.total))
    for p in db.query(b.Payment).filter(b.Payment.org_id == org.id, b.Payment.contact_id == contact.id, b.Payment.status == "posted", b.Payment.payment_date <= as_at):
        toward_ar = p.kind in ("receive", "pay")
        ev.append((p.payment_date, 1, str(p.id), f"Payment {p.reference or p.id}" if toward_ar else f"Refund {p.reference or p.id}",
                   Z if toward_ar else p.amount, p.amount if toward_ar else Z))
    for a in db.query(b.Allocation).filter(b.Allocation.org_id == org.id, b.Allocation.credit_doc_id.isnot(None), b.Allocation.alloc_date <= as_at):
        c1, tgt = db.get(b.Doc, a.credit_doc_id), db.get(b.Doc, a.doc_id) if a.doc_id else None
        if c1 and c1.contact_id == contact.id and tgt:
            pass                                                   # credit application moves value between two documents: net zero on the account
    ev.sort(key=lambda e: (e[0], e[1], e[2]))
    bal, rows = Z, []
    for d, _, ref, text, dr, cr in ev:
        bal += dr - cr
        rows.append(dict(date=d.isoformat(), reference=ref, description=text, charges=str(dr), credits=str(cr), balance=str(bal)))
    return dict(contact=dict(id=contact.id, name=contact.name, abn=contact.abn), as_at=as_at.isoformat(), rows=rows, closing_balance=str(bal))


# ------------------------------------------------------------------------------------------------ GST / BAS --
DOC_SOURCES = ("doc_invoice", "doc_credit_note", "doc_bill", "doc_supplier_credit")
SETTLEMENT_SOURCES = ("bas_payment",)
BAS_ORDER = ("G1", "G2", "G3", "G4", "G10", "G11", "G13", "G14", "G15", "G18", "1A", "1B")


def gst_summary(db, org, date_from, date_to, basis=None):
    basis = basis or org.gst_basis or "accrual"
    if basis not in ("accrual", "cash"):
        raise BooksError("basis must be accrual or cash")
    gst_acc = system_acct(db, org, "gst")
    tcs = {t.id: t for t in db.query(lm.TaxCode).filter_by(org_id=org.id)}
    fields, by_code, detail = defaultdict(lambda: Z), defaultdict(lambda: dict(base=Z, tax=Z)), []

    def apply(tc, base, tax):
        labels = tc.bas_labels or {}
        for lb in labels.get("base", []):
            fields[lb] += base
        if labels.get("tax"):
            fields[labels["tax"]] += tax
        by_code[tc.code]["base"] += base
        by_code[tc.code]["tax"] += tax

    q = db.query(lm.JournalLine, lm.Journal).join(lm.Journal, lm.Journal.id == lm.JournalLine.journal_id) \
        .filter(lm.JournalLine.org_id == org.id, lm.JournalLine.tax_code_id.isnot(None), lm.JournalLine.account_id != gst_acc.id)
    if basis == "accrual":
        q = q.filter(lm.Journal.journal_date.between(date_from, date_to))
    else:
        q = q.filter(lm.Journal.journal_date.between(date_from, date_to), ~lm.Journal.source_type.in_(DOC_SOURCES))
    for jl, j in q:
        tc = tcs.get(jl.tax_code_id)
        if tc is None or not tc.bas_labels:
            continue
        sales_side = tc.applies_to == "sales"
        sign = (jl.credit - jl.debit) if sales_side else (jl.debit - jl.credit)
        tax = jl.tax_amount if sign >= 0 else -jl.tax_amount
        apply(tc, sign + tax, tax)
    if basis == "cash":                                             # documents count when settled, pro-rata to what was settled in the period
        for d in db.query(b.Doc).filter(b.Doc.org_id == org.id, b.Doc.doc_type.in_(("invoice", "credit_note", "bill", "supplier_credit")),
                                        b.Doc.status.in_(("approved", "paid"))):
            paid = Z
            for a in db.query(b.Allocation).filter(b.Allocation.org_id == org.id, b.Allocation.alloc_date.between(date_from, date_to),
                                                   (b.Allocation.doc_id == d.id) | (b.Allocation.credit_doc_id == d.id)):
                paid += a.amount
            if paid == 0 or d.total == 0:
                continue
            ratio = paid / d.total
            neg = d.doc_type in ("credit_note", "supplier_credit")
            for l in d.lines:
                tc = tcs.get(l.tax_code_id) if l.tax_code_id else None
                if tc is None or not tc.bas_labels:
                    continue
                s = Decimal(-1) if neg else Decimal(1)
                apply(tc, s * l.gross * ratio, s * l.tax * ratio)
    out = {k: str(money(fields[k])) for k in BAS_ORDER if k in fields or k in ("G1", "G10", "G11", "1A", "1B")}
    a1, b1 = money(fields["1A"]), money(fields["1B"])
    movement = db.query(func.coalesce(func.sum(lm.JournalLine.credit - lm.JournalLine.debit), 0)).join(lm.Journal, lm.Journal.id == lm.JournalLine.journal_id) \
        .filter(lm.JournalLine.org_id == org.id, lm.JournalLine.account_id == gst_acc.id, lm.Journal.journal_date.between(date_from, date_to),
                ~lm.Journal.source_type.in_(SETTLEMENT_SOURCES)).scalar()   # paying / receiving the BAS settles the GST account; it is not a GST posting
    res = dict(basis=basis, date_from=date_from.isoformat(), date_to=date_to.isoformat(), fields=out,
               gst_on_sales_1A=str(a1), gst_on_purchases_1B=str(b1), net_gst_payable=str(a1 - b1),
               by_tax_code={k: dict(base=str(money(v["base"])), tax=str(money(v["tax"]))) for k, v in sorted(by_code.items())})
    if basis == "accrual":
        led = money(movement)
        res["ledger_check"] = dict(gst_account_movement=str(led), difference=str(led - (a1 - b1)), reconciled=(led == a1 - b1),
                                   note="The GST account (820) should move by exactly 1A less 1B (BAS payments/refunds are excluded); a difference means GST was posted without a tax code (e.g. a manual journal).")
    else:
        res["ledger_check"] = dict(note="Cash basis recognises GST on documents when they are settled; the GST account balance is on an accrual basis, so no direct reconciliation is shown.")
    return res


# ------------------------------------------------------------------------------------------------ cash flow --
def _balances(db, org, upto):
    rows = db.query(lm.JournalLine.account_id, func.coalesce(func.sum(lm.JournalLine.debit - lm.JournalLine.credit), 0)) \
        .join(lm.Journal, lm.Journal.id == lm.JournalLine.journal_id).filter(lm.JournalLine.org_id == org.id, lm.Journal.journal_date <= upto) \
        .group_by(lm.JournalLine.account_id).all()
    return {a: money(v) for a, v in rows}


def cash_flow(db, org, date_from, date_to):
    opening_day = date_from - timedelta(days=1)
    b0, b1 = _balances(db, org, opening_day), _balances(db, org, date_to)
    accs = {a.id: a for a in db.query(lm.LedgerAccount).filter_by(org_id=org.id)}
    move = {i: b1.get(i, Z) - b0.get(i, Z) for i in accs}                    # movement in (debit - credit)
    profit = Z
    for i, a in accs.items():
        if a.account_class == "revenue":
            profit += -move[i]
        elif a.account_class == "expense":
            profit -= move[i]
    op_adj, inv, fin = [], [], []
    dep = sum((move[i] for i, a in accs.items() if a.account_class == "expense" and "depreciation" in a.name.lower()), Z)
    if dep:
        op_adj.append(dict(label="Add back depreciation (non-cash)", amount=str(dep)))
    # Disposals: accumulated depreciation is released (debited) when an asset is sold, which the depreciation add-back does not see, and
    # the gain/loss on disposal is a non-cash item inside profit. Without these two lines a period containing a disposal never reconciles.
    accum_ids = [i for i, a in accs.items() if a.account_type in ("fixed_asset", "non_current_asset") and a.name.lower().startswith("less accumulated")]
    released = sum((move[i] for i in accum_ids), Z) + dep
    disposal_acc = next((a for a in accs.values() if a.system_key == "asset_disposal"), None)
    gl = move[disposal_acc.id] if disposal_acc else Z                          # debit - credit: a loss is positive, a gain negative
    if gl:
        op_adj.append(dict(label="Add back loss / (deduct gain) on disposal of assets", account=disposal_acc.code, amount=str(gl)))
    for a in sorted(accs.values(), key=lambda x: x.code):
        mv = move[a.id]
        if mv == 0:
            continue
        t = a.account_type
        if t in ("current_asset", "inventory"):
            op_adj.append(dict(label=f"(Increase)/decrease in {a.name}", account=a.code, amount=str(-mv)))
        elif t in ("current_liability", "credit_card"):
            op_adj.append(dict(label=f"Increase/(decrease) in {a.name}", account=a.code, amount=str(-mv)))
        elif t in ("fixed_asset", "non_current_asset"):
            if a.name.lower().startswith("less accumulated"):
                continue                                                         # captured by the depreciation add-back
            inv.append(dict(label=f"Purchase/(sale) of {a.name}", account=a.code, amount=str(-mv)))
        elif t == "non_current_liability":
            fin.append(dict(label=f"Proceeds/(repayment) of {a.name}", account=a.code, amount=str(-mv)))
        elif t == "equity":
            fin.append(dict(label=f"Movement in {a.name}", account=a.code, amount=str(-mv)))
    if released:
        inv.append(dict(label="Accumulated depreciation released on asset disposals", amount=str(-released)))
    if gl:
        inv.append(dict(label="(Loss)/gain on disposal of assets (proceeds vs book value)", account=disposal_acc.code, amount=str(-gl)))
    op_total = profit + sum((Decimal(x["amount"]) for x in op_adj), Z)
    inv_total, fin_total = sum((Decimal(x["amount"]) for x in inv), Z), sum((Decimal(x["amount"]) for x in fin), Z)
    net = op_total + inv_total + fin_total
    bank_ids = [i for i, a in accs.items() if a.account_type == "bank"]
    open_cash, close_cash = sum((b0.get(i, Z) for i in bank_ids), Z), sum((b1.get(i, Z) for i in bank_ids), Z)
    return dict(date_from=date_from.isoformat(), date_to=date_to.isoformat(),
                operating=dict(net_profit=str(profit), adjustments=op_adj, total=str(op_total)), investing=dict(items=inv, total=str(inv_total)),
                financing=dict(items=fin, total=str(fin_total)), net_change_in_cash=str(net), opening_cash=str(open_cash), closing_cash=str(close_cash),
                reconciled=(open_cash + net == close_cash), difference=str(close_cash - open_cash - net),
                note="Cash = bank accounts. A difference means a movement is in an account type this statement does not classify.")


# ------------------------------------------------------------------------------------------------ summaries --
def by_contact(db, org, side, date_from, date_to):
    main, credit = ("invoice", "credit_note") if side == "sales" else ("bill", "supplier_credit")
    agg = {}
    for d in db.query(b.Doc).filter(b.Doc.org_id == org.id, b.Doc.doc_type.in_((main, credit)), b.Doc.status.in_(("approved", "paid")),
                                    b.Doc.issue_date.between(date_from, date_to)):
        s = 1 if d.doc_type == main else -1
        r = agg.setdefault(d.contact_id, dict(contact_id=d.contact_id, contact=d.contact.name, net=Z, gst=Z, gross=Z, documents=0))
        r["net"] += s * d.subtotal
        r["gst"] += s * d.tax_total
        r["gross"] += s * d.total
        r["documents"] += 1
    rows = sorted(agg.values(), key=lambda r: r["gross"], reverse=True)
    tot = dict(net=sum((r["net"] for r in rows), Z), gst=sum((r["gst"] for r in rows), Z), gross=sum((r["gross"] for r in rows), Z))
    for r in rows:
        for k in ("net", "gst", "gross"):
            r[k] = str(r[k])
    return dict(date_from=date_from.isoformat(), date_to=date_to.isoformat(), rows=rows, totals={k: str(v) for k, v in tot.items()})


def dashboard(db, org, side):
    main = "invoice" if side == "sales" else "bill"
    today = date.today()
    open_docs = db.query(b.Doc).filter(b.Doc.org_id == org.id, b.Doc.doc_type == main, b.Doc.status == "approved").all()
    owing = sum((d.amount_due for d in open_docs), Z)
    overdue = [d for d in open_docs if d.due_date and d.due_date < today]
    drafts = db.query(func.count(b.Doc.id)).filter_by(org_id=org.id, doc_type=main, status="draft").scalar()
    since = today - timedelta(days=30)
    paid30 = db.query(func.coalesce(func.sum(b.Payment.amount), 0)).filter(b.Payment.org_id == org.id, b.Payment.kind == ("receive" if side == "sales" else "pay"),
                                                                           b.Payment.status == "posted", b.Payment.payment_date >= since).scalar()
    return dict(owing=str(owing), owing_count=len(open_docs), overdue=str(sum((d.amount_due for d in overdue), Z)), overdue_count=len(overdue), drafts=drafts,
                paid_last_30_days=str(money(paid30)))
