"""
A7 - retire `accounting_documents` / `transactions` as sources of truth.

  backfill(org)        legacy customers/suppliers -> contacts; legacy documents -> READ-ONLY archived records (status 'archived': never
                       posted, so nothing is double counted against the bank sync); legacy transactions -> bank lines, ADOPTING the
                       journals the Phase 0 bank sync already posted instead of posting them again. Idempotent (legacy_links).
  reconciliation(org)  legacy vs new, to the cent: documents by type, contacts, and the bank sync's posted total vs the ledger.
  promote(doc)         turn an archived open invoice/bill into a normal DRAFT so it can be reviewed and posted deliberately.
  legacy_write_guard   FastAPI dependency: when switched on, the old write endpoints refuse with a pointer to the new ones.
"""
from collections import defaultdict
from decimal import Decimal

from fastapi import HTTPException, Request
from sqlalchemy import func, text

from accfino.core import models as m
from accfino.modules.accounting.models import ledger as lm
from accfino.modules.accounting.books import banking as K
from accfino.modules.accounting.books import docs as D
from accfino.modules.accounting.books import models as b
from accfino.modules.accounting.books.common import BooksError, money
from accfino.modules.accounting.ledger.bank_sync import SOURCE, _Resolver

Z = Decimal("0.00")
SETTING = "books.legacy_readonly"
TYPE_MAP = {"invoice": "invoice", "quote": "quote", "bill": "bill", "receipt": "bill"}


def _d(x):
    return money(Decimal(str(x))) if x is not None else Z


# ---------------------------------------------------------------------------------------------- guard --
def is_readonly(db) -> bool:
    row = db.get(m.SystemSetting, SETTING)
    return bool(row and row.value == "on")


def set_readonly(db, enabled: bool):
    row = db.get(m.SystemSetting, SETTING)
    if row is None:
        db.add(m.SystemSetting(key=SETTING, value="on" if enabled else "off"))
    else:
        row.value = "on" if enabled else "off"
    db.flush()


async def legacy_write_guard(request: Request):
    """Dependency for the legacy routers: writes are refused once the organisation has moved to the Phase 1 modules."""
    if request.method in ("POST", "PUT", "PATCH", "DELETE"):
        from accfino.shared.db.database import SessionLocal
        db = SessionLocal()
        try:
            if is_readonly(db):
                raise HTTPException(409, "The legacy document and transaction tables are read-only. Use /sales, /purchases, /banking and /expenses instead.")
        finally:
            db.close()


# ---------------------------------------------------------------------------------------------- backfill --
def _contact(db, org, name, role, email=None, phone=None, abn=None, address=None):
    name = (name or "").strip()
    if not name:
        return None
    c = db.query(b.Contact).filter(b.Contact.org_id == org.id, func.lower(b.Contact.name) == name.lower()).first()
    if c is None:
        c = b.Contact(org_id=org.id, name=name[:255], is_customer=(role == "customer"), is_supplier=(role == "supplier"), email=email, phone=phone,
                      abn="".join(ch for ch in (abn or "") if ch.isdigit()) or None, address=address, terms_days=14 if role == "customer" else 30)
        db.add(c)
        db.flush()
    elif role == "customer" and not c.is_customer:
        c.is_customer = True
    elif role == "supplier" and not c.is_supplier:
        c.is_supplier = True
    return c


def _linked(db, org, table, legacy_id):
    return db.query(b.LegacyLink).filter_by(org_id=org.id, legacy_table=table, legacy_id=legacy_id).first()


def backfill(db, org, user_id, *, dry_run=True, include_transactions=True):
    uid = org.legacy_user_id
    if not uid:
        raise BooksError("This organisation has no linked legacy data", 404)
    res = dict(dry_run=dry_run, contacts=dict(customers=0, suppliers=0), documents=dict(imported=0, already=0, skipped=0), transactions=None, warnings=[])
    nested = db.begin_nested()
    try:
        for tbl, role in (("accounting_customers", "customer"), ("accounting_suppliers", "supplier")):
            for r in db.execute(text(f"select id, name, email, phone, address, abn from {tbl} where user_id = :u order by id"), dict(u=uid)).fetchall():
                if _linked(db, org, tbl, r.id):
                    continue
                c = _contact(db, org, r.name, role, r.email, r.phone, r.abn, r.address)
                if c:
                    db.add(b.LegacyLink(org_id=org.id, legacy_table=tbl, legacy_id=r.id, new_kind="contact", new_id=c.id))
                    res["contacts"]["customers" if role == "customer" else "suppliers"] += 1
        taxes = {t.name.lower(): t for t in db.query(lm.TaxCode).filter_by(org_id=org.id)}
        accs = {a.name.lower(): a for a in db.query(lm.LedgerAccount).filter_by(org_id=org.id)}
        for r in db.execute(text("""select id, document_type, document_number, status, document_date, due_date, party_name, party_email, party_phone, party_address,
                                    party_abn, subtotal, tax_amount, discount_amount, total_amount, notes, created_at
                                    from accounting_documents where user_id = :u order by id"""), dict(u=uid)).fetchall():
            if _linked(db, org, "accounting_documents", r.id):
                res["documents"]["already"] += 1
                continue
            dtype = TYPE_MAP.get(r.document_type)
            if dtype is None or not (r.party_name or "").strip():
                res["documents"]["skipped"] += 1
                res["warnings"].append(f"legacy document #{r.id} ({r.document_type}) has no usable type/party - skipped")
                continue
            role = "customer" if dtype in ("invoice", "quote") else "supplier"
            c = _contact(db, org, r.party_name, role, r.party_email, r.party_phone, r.party_abn, r.party_address)
            issue = (r.document_date or r.created_at).date()
            number = (r.document_number or f"LEG-{r.id}").strip()
            if db.query(b.Doc.id).filter_by(org_id=org.id, doc_type=dtype, number=number).first():
                number = f"{number}-L{r.id}"
            sub, tax, total = _d(r.subtotal), _d(r.tax_amount), _d(r.total_amount)
            if total != sub + tax - _d(r.discount_amount):
                res["warnings"].append(f"legacy document #{r.id}: total {total} != subtotal {sub} + tax {tax} - discount (kept as recorded)")
            doc = b.Doc(org_id=org.id, doc_type=dtype, number=number[:60], contact_id=c.id, status="archived", issue_date=issue,
                        due_date=r.due_date.date() if r.due_date else None, amounts_are="exclusive", subtotal=sub, tax_total=tax, total=total,
                        notes=f"Imported from legacy record #{r.id} (legacy status: {r.status}). {r.notes or ''}".strip()[:2000], source="legacy", created_by=user_id)
            items = db.execute(text("select description, quantity, unit_price, line_total, gl_account, gst_category from accounting_line_items where document_id = :d order by sort_order, id"),
                               dict(d=r.id)).fetchall()
            base = sum((_d(i.line_total) for i in items), Z)
            left_tax = tax
            for n, i in enumerate(items, start=1):
                net = _d(i.line_total)
                lt = (left_tax if n == len(items) else money(tax * net / base)) if base else Z
                left_tax -= lt
                tc = taxes.get((i.gst_category or "").strip().lower())
                ac = accs.get((i.gl_account or "").strip().lower())
                doc.lines.append(b.DocLine(org_id=org.id, line_no=n, description=(i.description or "(no description)")[:500], qty=Decimal(str(i.quantity or 1)),
                                           unit_price=Decimal(str(i.unit_price or 0)), account_id=ac.id if ac else None, tax_code_id=tc.id if tc else None,
                                           net=net, tax=lt, gross=net + lt))
            db.add(doc)
            db.flush()
            db.add(b.LegacyLink(org_id=org.id, legacy_table="accounting_documents", legacy_id=r.id, new_kind="doc", new_id=doc.id))
            res["documents"]["imported"] += 1
        if include_transactions:
            res["transactions"] = import_legacy_transactions(db, org, user_id)
        if dry_run:
            nested.rollback()
        else:
            nested.commit()
    except Exception:
        nested.rollback()
        raise
    return res


def import_legacy_transactions(db, org, user_id):
    uid = org.legacy_user_id
    rows = db.execute(text("select id, date, bank, account, description, debit, credit from transactions where user_id = :u order by date, id"), dict(u=uid)).fetchall()
    groups = defaultdict(list)
    for r in rows:
        amt = _d(r.credit) - _d(r.debit)
        if amt != 0:
            groups[(r.bank, r.account)].append(dict(date=r.date.date().isoformat(), description=r.description, amount=str(amt)))
    resolver, out = _Resolver(db, org), dict(accounts=0, created=0, duplicates=0, adopted_from_ledger=0)
    for (bank, acct), lines in groups.items():
        acc = resolver.bank(bank, acct)
        r = K.import_lines(db, org, user_id, acc, lines, adopt_existing=True)
        out["accounts"] += 1
        for k in ("created", "duplicates", "adopted_from_ledger"):
            out[k] += r[k]
    return out


# ---------------------------------------------------------------------------------------------- reports --
def reconciliation(db, org):
    uid = org.legacy_user_id
    if not uid:
        return dict(linked=False, note="This organisation has no linked legacy data")
    legacy = {}
    for r in db.execute(text("""select document_type, count(*) n, coalesce(sum(subtotal),0) s, coalesce(sum(tax_amount),0) t, coalesce(sum(total_amount),0) g
                                from accounting_documents where user_id = :u group by document_type"""), dict(u=uid)).fetchall():
        legacy[TYPE_MAP.get(r.document_type, r.document_type)] = dict(count=legacy.get(TYPE_MAP.get(r.document_type, r.document_type), {}).get("count", 0) + r.n,
                                                                       total=legacy.get(TYPE_MAP.get(r.document_type, r.document_type), {}).get("total", Z) + _d(r.g))
    new = {}
    for dtype, n, total in db.query(b.Doc.doc_type, func.count(b.Doc.id), func.coalesce(func.sum(b.Doc.total), 0)).filter_by(org_id=org.id, source="legacy").group_by(b.Doc.doc_type):
        new[dtype] = dict(count=n, total=money(total))
    docs = {}
    for k in sorted(set(legacy) | set(new)):
        lg, nw = legacy.get(k, dict(count=0, total=Z)), new.get(k, dict(count=0, total=Z))
        docs[k] = dict(legacy_count=lg["count"], legacy_total=str(lg["total"]), imported_count=nw["count"], imported_total=str(nw["total"]),
                       difference=str(lg["total"] - nw["total"]), reconciled=(lg["count"] == nw["count"] and lg["total"] == nw["total"]))
    txn = db.execute(text("select count(*), coalesce(sum(credit - debit), 0) from transactions where user_id = :u"), dict(u=uid)).one()
    links = db.query(lm.LedgerSourceLink).filter_by(org_id=org.id, source_type=SOURCE).all()
    by_status = defaultdict(int)
    for l in links:
        by_status[l.status] += 1
    posted_ids = [int(l.source_id) for l in links if l.status == "posted"]
    expected = Z
    if posted_ids:
        expected = _d(db.execute(text("select coalesce(sum(credit - debit), 0) from transactions where id = any(:ids)"), dict(ids=posted_ids)).scalar())
    bank_ids = [a.id for a in db.query(lm.LedgerAccount).filter_by(org_id=org.id, account_type="bank")]
    ledger_net = Z
    if bank_ids:
        jl = lm.JournalLine
        ledger_net = money(db.query(func.coalesce(func.sum(jl.debit - jl.credit), 0)).join(lm.Journal, lm.Journal.id == jl.journal_id)
                           .filter(jl.org_id == org.id, jl.account_id.in_(bank_ids), lm.Journal.source_type == SOURCE).scalar())
    linked_contacts = db.query(func.count(b.LegacyLink.id)).filter(b.LegacyLink.org_id == org.id, b.LegacyLink.new_kind == "contact").scalar()
    legacy_contacts = db.execute(text("select (select count(*) from accounting_customers where user_id=:u) + (select count(*) from accounting_suppliers where user_id=:u)"), dict(u=uid)).scalar()
    all_ok = all(v["reconciled"] for v in docs.values()) and expected == ledger_net
    return dict(linked=True, documents=docs,
                contacts=dict(legacy=legacy_contacts, imported=linked_contacts, reconciled=(legacy_contacts == linked_contacts)),
                transactions=dict(legacy_count=txn[0], legacy_net=str(_d(txn[1])), sync_status=dict(by_status),
                                  sync_posted_net_expected=str(expected), ledger_bank_net_from_sync=str(ledger_net), difference=str(expected - ledger_net),
                                  reconciled=(expected == ledger_net), bank_lines=db.query(func.count(b.BankLine.id)).filter_by(org_id=org.id).scalar()),
                reconciled=all_ok,
                note="Imported documents are read-only history (status 'archived') and are NOT in the ledger. Promote any still-open item to a draft to post it deliberately.")


def list_records(db, org, limit=200):
    rows = db.query(b.Doc).filter_by(org_id=org.id, source="legacy").order_by(b.Doc.issue_date.desc(), b.Doc.id.desc()).limit(limit).all()
    return [D.doc_dict(db, d, detail=False) for d in rows]


def promote(db, org, user_id, doc_id):
    old = db.query(b.Doc).filter_by(org_id=org.id, id=doc_id, source="legacy", status="archived").one_or_none()
    if old is None:
        raise BooksError("Archived legacy record not found", 404)
    if db.query(b.Doc.id).filter_by(org_id=org.id, parent_id=old.id).first():
        raise BooksError("This legacy record has already been promoted", 409)
    role = "customer" if old.doc_type in ("invoice", "quote") else "supplier"
    from datetime import date
    data = dict(contact_id=old.contact_id, issue_date=date.today(), reference=old.reference, notes=f"Promoted from legacy {old.number}", parent_id=old.id,
                lines=[dict(description=l.description, qty=l.qty, unit_price=l.unit_price, account=l.account_id, tax_code=l.tax_code_id) for l in old.lines])
    return D.create_doc(db, org, user_id, old.doc_type, data, approve=False)
