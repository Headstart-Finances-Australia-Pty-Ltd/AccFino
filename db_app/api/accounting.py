"""
Accounting API Router — /accounting/*

Sale endpoints  (document_type in: quote, invoice)
  GET/POST   /accounting/sale/documents
  GET/PATCH/DELETE /accounting/sale/documents/{id}
  POST       /accounting/sale/documents/{id}/convert   (quote → invoice)

Purchase endpoints (document_type in: bill, receipt)
  GET/POST   /accounting/purchase/documents
  GET/PATCH/DELETE /accounting/purchase/documents/{id}
  POST       /accounting/purchase/extract              (OCR extract PDF/image)

Shared
  GET/POST   /accounting/suppliers
  GET/PATCH/DELETE /accounting/suppliers/{id}
  GET        /accounting/stats/{user_id}

All endpoints are user-scoped — every query filters by user_id.
"""

from datetime import datetime
from typing import List, Optional
import io, logging

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from pydantic import BaseModel
from sqlalchemy.orm import Session

from db_app.database import get_db
from db_app.models.accounting import (
    AccountingDocument, AccountingLineItem, AccountingSupplier, AccountingCustomer,
)

logger = logging.getLogger("accfino")
router = APIRouter()

# ── Helpers ───────────────────────────────────────────────────────────────────

SALE_TYPES     = {"quote", "invoice"}
PURCHASE_TYPES = {"bill", "receipt"}
ALL_TYPES      = SALE_TYPES | PURCHASE_TYPES


def _doc_to_dict(doc: AccountingDocument) -> dict:
    return {
        "id":               doc.id,
        "user_id":          doc.user_id,
        "document_type":    doc.document_type,
        "document_number":  doc.document_number,
        "status":           doc.status,
        "document_date":    doc.document_date.isoformat() if doc.document_date else None,
        "due_date":         doc.due_date.isoformat()      if doc.due_date      else None,
        "paid_date":        doc.paid_date.isoformat()     if doc.paid_date     else None,
        "party_name":       doc.party_name,
        "party_email":      doc.party_email,
        "party_phone":      doc.party_phone,
        "party_address":    doc.party_address,
        "party_abn":        doc.party_abn,
        "business_name":    doc.business_name,
        "business_id":      doc.business_id,
        "subtotal":         doc.subtotal,
        "tax_percent":      doc.tax_percent,
        "tax_amount":       doc.tax_amount,
        "discount_amount":  doc.discount_amount,
        "total_amount":     doc.total_amount,
        "currency":         doc.currency,
        "gl_account":       doc.gl_account,
        "gst_category":     doc.gst_category,
        "reconciled":       doc.reconciled,
        "reconcile_txn_id": doc.reconcile_txn_id,
        "notes":            doc.notes,
        "payment_terms":    doc.payment_terms,
        "source_file":      doc.source_file,
        "extracted_data":   doc.extracted_data,
        "created_at":       doc.created_at.isoformat() if doc.created_at else None,
        "updated_at":       doc.updated_at.isoformat() if doc.updated_at else None,
        "line_items": [
            {
                "id":           li.id,
                "sort_order":   li.sort_order,
                "description":  li.description,
                "quantity":     li.quantity,
                "unit_price":   li.unit_price,
                "line_total":   li.line_total,
                "gl_account":   li.gl_account,
                "gst_category": li.gst_category,
            }
            for li in (doc.line_items or [])
        ],
    }


def _generate_number(doc_type: str, db: Session) -> str:
    prefix_map = {"quote": "QTE", "invoice": "INV", "bill": "BILL", "receipt": "RCPT"}
    prefix = prefix_map.get(doc_type, "DOC")
    year   = datetime.utcnow().year
    count  = db.query(AccountingDocument).filter(
        AccountingDocument.document_type == doc_type
    ).count()
    return f"{prefix}-{year}-{count + 1:04d}"


def _calc_totals(items: list, tax_percent: float, discount: float) -> dict:
    subtotal = sum(i["quantity"] * i["unit_price"] for i in items)
    tax      = round(subtotal * tax_percent / 100, 2)
    total    = round(subtotal + tax - discount, 2)
    return {"subtotal": round(subtotal, 2), "tax_amount": tax, "total_amount": total}


# ── Pydantic schemas ──────────────────────────────────────────────────────────

class LineItemIn(BaseModel):
    description:  str
    quantity:     float = 1.0
    unit_price:   float = 0.0
    gl_account:   Optional[str] = None
    gst_category: Optional[str] = None
    sort_order:   int   = 0


class DocumentIn(BaseModel):
    user_id:        int
    document_type:  str          # quote | invoice | bill | receipt
    document_number: Optional[str] = None
    status:         Optional[str] = None
    document_date:  Optional[datetime] = None
    due_date:       Optional[datetime] = None
    party_name:     Optional[str] = None
    party_email:    Optional[str] = None
    party_phone:    Optional[str] = None
    party_address:  Optional[str] = None
    party_abn:      Optional[str] = None
    business_name:  Optional[str] = None
    business_id:    Optional[int] = None
    tax_percent:    float = 10.0
    discount_amount: float = 0.0
    currency:       str   = "AUD"
    gl_account:     Optional[str] = None
    gst_category:   Optional[str] = None
    notes:          Optional[str] = None
    payment_terms:  Optional[str] = None
    line_items:     List[LineItemIn] = []


class DocumentPatch(BaseModel):
    status:         Optional[str] = None
    document_date:  Optional[datetime] = None
    due_date:       Optional[datetime] = None
    paid_date:      Optional[datetime] = None
    party_name:     Optional[str] = None
    party_email:    Optional[str] = None
    party_phone:    Optional[str] = None
    party_address:  Optional[str] = None
    party_abn:      Optional[str] = None
    business_name:  Optional[str] = None
    business_id:    Optional[int] = None
    tax_percent:    Optional[float] = None
    discount_amount: Optional[float] = None
    gl_account:     Optional[str] = None
    gst_category:   Optional[str] = None
    notes:          Optional[str] = None
    payment_terms:  Optional[str] = None
    reconciled:     Optional[bool] = None
    reconcile_txn_id: Optional[int] = None
    line_items:     Optional[List[LineItemIn]] = None


class SupplierIn(BaseModel):
    user_id:      int
    name:         str
    email:        Optional[str] = None
    phone:        Optional[str] = None
    address:      Optional[str] = None
    abn:          Optional[str] = None
    website:      Optional[str] = None
    gl_account:   Optional[str] = None
    gst_category: Optional[str] = None


class CustomerIn(BaseModel):
    user_id:      int
    name:         str
    email:        Optional[str] = None
    phone:        Optional[str] = None
    address:      Optional[str] = None
    city:         Optional[str] = None
    state:        Optional[str] = None
    postcode:     Optional[str] = None
    abn:          Optional[str] = None
    website:      Optional[str] = None
    contact_name: Optional[str] = None
    notes:        Optional[str] = None
    gl_account:   Optional[str] = None
    gst_category: Optional[str] = None


# ── Document CRUD (shared Sale + Purchase) ────────────────────────────────────

@router.post("/documents")
def create_document(body: DocumentIn, db: Session = Depends(get_db)):
    if body.document_type not in ALL_TYPES:
        raise HTTPException(400, f"document_type must be one of {sorted(ALL_TYPES)}")

    num  = body.document_number or _generate_number(body.document_type, db)
    items = [li.dict() for li in body.line_items]
    tots = _calc_totals(items, body.tax_percent, body.discount_amount)

    default_status = {
        "quote":   "draft",
        "invoice": "draft",
        "bill":    "pending",
        "receipt": "unmatched",
    }

    doc = AccountingDocument(
        user_id         = body.user_id,
        document_type   = body.document_type,
        document_number = num,
        status          = body.status or default_status[body.document_type],
        document_date   = body.document_date,
        due_date        = body.due_date,
        party_name      = body.party_name,
        party_email     = body.party_email,
        party_phone     = body.party_phone,
        party_address   = body.party_address,
        party_abn       = body.party_abn,
        business_name   = body.business_name,
        business_id     = body.business_id,
        tax_percent     = body.tax_percent,
        discount_amount = body.discount_amount,
        currency        = body.currency,
        gl_account      = body.gl_account,
        gst_category    = body.gst_category,
        notes           = body.notes,
        payment_terms   = body.payment_terms,
        **tots,
    )
    db.add(doc)
    db.flush()

    for i, li in enumerate(items):
        db.add(AccountingLineItem(
            document_id  = doc.id,
            sort_order   = li.get("sort_order", i),
            description  = li["description"],
            quantity     = li["quantity"],
            unit_price   = li["unit_price"],
            line_total   = round(li["quantity"] * li["unit_price"], 2),
            gl_account   = li.get("gl_account"),
            gst_category = li.get("gst_category"),
        ))

    db.commit()
    db.refresh(doc)
    return _doc_to_dict(doc)


@router.get("/documents")
def list_documents(
    user_id:       int,
    document_type: Optional[str] = None,
    status:        Optional[str] = None,
    db: Session = Depends(get_db),
):
    q = db.query(AccountingDocument).filter(AccountingDocument.user_id == user_id)
    if document_type:
        q = q.filter(AccountingDocument.document_type == document_type)
    if status:
        q = q.filter(AccountingDocument.status == status)
    docs = q.order_by(AccountingDocument.created_at.desc()).all()
    return [_doc_to_dict(d) for d in docs]


@router.get("/documents/{doc_id}")
def get_document(doc_id: int, user_id: int, db: Session = Depends(get_db)):
    doc = db.query(AccountingDocument).filter(
        AccountingDocument.id == doc_id,
        AccountingDocument.user_id == user_id,
    ).first()
    if not doc:
        raise HTTPException(404, "Document not found")
    return _doc_to_dict(doc)


@router.patch("/documents/{doc_id}")
def patch_document(doc_id: int, user_id: int, body: DocumentPatch, db: Session = Depends(get_db)):
    doc = db.query(AccountingDocument).filter(
        AccountingDocument.id == doc_id,
        AccountingDocument.user_id == user_id,
    ).first()
    if not doc:
        raise HTTPException(404, "Document not found")

    for field, val in body.dict(exclude_unset=True, exclude={"line_items"}).items():
        setattr(doc, field, val)

    # Recalculate totals if line items updated
    if body.line_items is not None:
        db.query(AccountingLineItem).filter(AccountingLineItem.document_id == doc_id).delete()
        items = [li.dict() for li in body.line_items]
        for i, li in enumerate(items):
            db.add(AccountingLineItem(
                document_id  = doc_id,
                sort_order   = li.get("sort_order", i),
                description  = li["description"],
                quantity     = li["quantity"],
                unit_price   = li["unit_price"],
                line_total   = round(li["quantity"] * li["unit_price"], 2),
                gl_account   = li.get("gl_account"),
                gst_category = li.get("gst_category"),
            ))
        tots = _calc_totals(items, doc.tax_percent, doc.discount_amount or 0)
        for k, v in tots.items():
            setattr(doc, k, v)

    doc.updated_at = datetime.utcnow()
    db.commit()
    db.refresh(doc)
    return _doc_to_dict(doc)


@router.delete("/documents/{doc_id}")
def delete_document(doc_id: int, user_id: int, db: Session = Depends(get_db)):
    doc = db.query(AccountingDocument).filter(
        AccountingDocument.id == doc_id,
        AccountingDocument.user_id == user_id,
    ).first()
    if not doc:
        raise HTTPException(404, "Document not found")
    db.delete(doc)
    db.commit()
    return {"ok": True}


@router.post("/documents/{doc_id}/convert")
def convert_quote_to_invoice(doc_id: int, user_id: int, db: Session = Depends(get_db)):
    """Convert an accepted Quote into a new Invoice. Original quote remains unchanged."""
    doc = db.query(AccountingDocument).filter(
        AccountingDocument.id == doc_id,
        AccountingDocument.user_id == user_id,
        AccountingDocument.document_type == "quote",
    ).first()
    if not doc:
        raise HTTPException(404, "Quote not found")

    inv_num = _generate_number("invoice", db)
    inv = AccountingDocument(
        user_id         = doc.user_id,
        document_type   = "invoice",
        document_number = inv_num,
        status          = "draft",
        document_date   = datetime.utcnow(),
        due_date        = doc.due_date,
        party_name      = doc.party_name,
        party_email     = doc.party_email,
        party_phone     = doc.party_phone,
        party_address   = doc.party_address,
        party_abn       = doc.party_abn,
        business_name   = doc.business_name,
        business_id     = doc.business_id,
        subtotal        = doc.subtotal,
        tax_percent     = doc.tax_percent,
        tax_amount      = doc.tax_amount,
        discount_amount = doc.discount_amount,
        total_amount    = doc.total_amount,
        currency        = doc.currency,
        gl_account      = doc.gl_account,
        gst_category    = doc.gst_category,
        notes           = doc.notes,
        payment_terms   = doc.payment_terms,
    )
    db.add(inv)
    db.flush()

    for li in doc.line_items:
        db.add(AccountingLineItem(
            document_id  = inv.id,
            sort_order   = li.sort_order,
            description  = li.description,
            quantity     = li.quantity,
            unit_price   = li.unit_price,
            line_total   = li.line_total,
            gl_account   = li.gl_account,
            gst_category = li.gst_category,
        ))

    # Mark original quote as converted
    doc.status = "converted"
    db.commit()
    db.refresh(inv)
    return _doc_to_dict(inv)


# ── Purchase: OCR extraction endpoint ────────────────────────────────────────

@router.post("/purchase/extract")
async def extract_purchase_document(
    files:    List[UploadFile] = File(...),
    user_id:  int  = Form(...),
    doc_type: str  = Form("bill"),   # "bill" or "receipt"
    save:     bool = Form(True),     # auto-save extracted docs to DB
    db: Session = Depends(get_db),
):
    """
    Extract bill or receipt data from PDF/image files using the existing
    invoice_extractor backend. Returns extracted documents (and saves them
    to accounting_documents if save=True).
    """
    if doc_type not in {"bill", "receipt"}:
        raise HTTPException(400, "doc_type must be 'bill' or 'receipt'")

    # Reuse existing extraction engine
    try:
        from main_app.backend.invoice_extractor.core import (
            process_files as ie_process_files,
        )
        IE_AVAILABLE = True
    except ImportError:
        try:
            from backend.invoice_extractor.core import process_files as ie_process_files
            IE_AVAILABLE = True
        except ImportError:
            IE_AVAILABLE = False

    if not IE_AVAILABLE:
        raise HTTPException(503, "Invoice extractor not available — check server dependencies")

    import tempfile, os as _os
    from pathlib import Path

    tmp_files = []
    saved_docs = []

    try:
        for upload in files:
            raw = await upload.read()
            suffix = Path(upload.filename or "file").suffix or ".pdf"
            with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
                tmp.write(raw)
                tmp_files.append((tmp.name, upload.filename or tmp.name))

        _, invoice_results, _ = ie_process_files([Path(p) for p, _ in tmp_files])

        extracted_docs = []
        for result, src_path in invoice_results:
            fname = next((n for p, n in tmp_files if p == src_path), src_path)
            data  = result if isinstance(result, dict) else {}

            # Map extracted fields to our schema
            party_name = (
                data.get("vendor")     or
                data.get("supplier")   or
                data.get("from")       or
                data.get("company")    or ""
            )
            total = float(data.get("total") or data.get("amount") or 0)
            tax   = float(data.get("gst")   or data.get("tax")    or 0)
            sub   = round(total - tax, 2) if total else 0.0

            items = data.get("items") or []
            if not items and total:
                items = [{"description": data.get("description", "Extracted item"),
                          "quantity": 1.0, "unit_price": sub}]

            doc_data = {
                "user_id":       user_id,
                "document_type": doc_type,
                "status":        "pending" if doc_type == "bill" else "unmatched",
                "document_date": _parse_date(data.get("date") or data.get("invoice_date")),
                "party_name":    party_name,
                "party_abn":     data.get("abn") or data.get("tax_id"),
                "subtotal":      sub,
                "tax_amount":    tax,
                "tax_percent":   10.0,
                "total_amount":  total,
                "source_file":   fname,
                "extracted_data": data,
                "notes":         data.get("notes") or data.get("payment_terms"),
            }

            extracted_docs.append({**doc_data, "line_items": items})

            if save:
                num = _generate_number(doc_type, db)
                doc = AccountingDocument(
                    document_number = num,
                    source_text     = str(data),
                    **{k: v for k, v in doc_data.items()
                       if k not in ("line_items",)},
                )
                db.add(doc)
                db.flush()
                for i, li in enumerate(items):
                    qty = float(li.get("quantity", 1))
                    up  = float(li.get("unit_price", li.get("amount", 0)))
                    db.add(AccountingLineItem(
                        document_id = doc.id,
                        sort_order  = i,
                        description = str(li.get("description", "Item")),
                        quantity    = qty,
                        unit_price  = up,
                        line_total  = round(qty * up, 2),
                    ))
                db.commit()
                db.refresh(doc)
                saved_docs.append(_doc_to_dict(doc))

        if not save:
            return {"extracted": extracted_docs, "saved": []}
        return {"extracted": extracted_docs, "saved": saved_docs}

    except Exception as e:
        logger.error(f"/accounting/purchase/extract error: {e}", exc_info=True)
        raise HTTPException(500, str(e))
    finally:
        for p, _ in tmp_files:
            try: _os.unlink(p)
            except: pass


def _parse_date(val) -> Optional[datetime]:
    if not val:
        return None
    if isinstance(val, datetime):
        return val
    for fmt in ("%d/%m/%Y", "%Y-%m-%d", "%d-%m-%Y", "%m/%d/%Y", "%d %b %Y", "%d %B %Y"):
        try:
            return datetime.strptime(str(val).strip(), fmt)
        except ValueError:
            continue
    return None


# ── Supplier CRUD ─────────────────────────────────────────────────────────────

@router.post("/suppliers")
def create_supplier(body: SupplierIn, db: Session = Depends(get_db)):
    sup = AccountingSupplier(**body.dict())
    db.add(sup); db.commit(); db.refresh(sup)
    return _sup_to_dict(sup)


@router.get("/suppliers")
def list_suppliers(user_id: int, db: Session = Depends(get_db)):
    rows = db.query(AccountingSupplier).filter(
        AccountingSupplier.user_id == user_id,
        AccountingSupplier.is_active == True,
    ).order_by(AccountingSupplier.name).all()
    return [_sup_to_dict(s) for s in rows]


@router.patch("/suppliers/{sup_id}")
def patch_supplier(sup_id: int, user_id: int, body: dict, db: Session = Depends(get_db)):
    sup = db.query(AccountingSupplier).filter(
        AccountingSupplier.id == sup_id,
        AccountingSupplier.user_id == user_id,
    ).first()
    if not sup: raise HTTPException(404, "Supplier not found")
    for k, v in body.items():
        if hasattr(sup, k): setattr(sup, k, v)
    sup.updated_at = datetime.utcnow()
    db.commit(); db.refresh(sup)
    return _sup_to_dict(sup)


@router.delete("/suppliers/{sup_id}")
def delete_supplier(sup_id: int, user_id: int, db: Session = Depends(get_db)):
    sup = db.query(AccountingSupplier).filter(
        AccountingSupplier.id == sup_id,
        AccountingSupplier.user_id == user_id,
    ).first()
    if not sup: raise HTTPException(404, "Supplier not found")
    sup.is_active = False
    db.commit()
    return {"ok": True}


def _sup_to_dict(s: AccountingSupplier) -> dict:
    return {
        "id": s.id, "user_id": s.user_id, "name": s.name,
        "email": s.email, "phone": s.phone, "address": s.address,
        "abn": s.abn, "website": s.website,
        "gl_account": s.gl_account, "gst_category": s.gst_category,
        "is_active": s.is_active,
        "created_at": s.created_at.isoformat() if s.created_at else None,
    }


# ── Customer CRUD ─────────────────────────────────────────────────────────────

@router.post("/customers")
def create_customer(body: CustomerIn, db: Session = Depends(get_db)):
    cust = AccountingCustomer(**body.dict())
    db.add(cust); db.commit(); db.refresh(cust)
    return _cust_to_dict(cust)


@router.get("/customers")
def list_customers(user_id: int, db: Session = Depends(get_db)):
    rows = db.query(AccountingCustomer).filter(
        AccountingCustomer.user_id == user_id,
        AccountingCustomer.is_active == True,
    ).order_by(AccountingCustomer.name).all()
    return [_cust_to_dict(c) for c in rows]


@router.patch("/customers/{cust_id}")
def patch_customer(cust_id: int, user_id: int, body: dict, db: Session = Depends(get_db)):
    cust = db.query(AccountingCustomer).filter(
        AccountingCustomer.id == cust_id,
        AccountingCustomer.user_id == user_id,
    ).first()
    if not cust: raise HTTPException(404, "Customer not found")
    for k, v in body.items():
        if hasattr(cust, k): setattr(cust, k, v)
    cust.updated_at = datetime.utcnow()
    db.commit(); db.refresh(cust)
    return _cust_to_dict(cust)


@router.delete("/customers/{cust_id}")
def delete_customer(cust_id: int, user_id: int, db: Session = Depends(get_db)):
    cust = db.query(AccountingCustomer).filter(
        AccountingCustomer.id == cust_id,
        AccountingCustomer.user_id == user_id,
    ).first()
    if not cust: raise HTTPException(404, "Customer not found")
    cust.is_active = False
    db.commit()
    return {"ok": True}


@router.post("/customers/csv-import")
async def import_customers_csv(
    file:    UploadFile = File(...),
    user_id: int        = Form(...),
    db: Session = Depends(get_db),
):
    """
    Bulk-import customers from CSV.
    Expected columns (any order, case-insensitive):
      name*, email, phone, address, city, state, postcode, abn,
      website, contact_name, notes, gl_account, gst_category
    Rows where name matches an existing active customer are updated (upsert).
    """
    import csv, io
    raw = await file.read()
    try:
        text_data = raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        text_data = raw.decode("latin-1")

    reader = csv.DictReader(io.StringIO(text_data))
    # Normalise header keys
    def norm(k): return k.strip().lower().replace(" ","_").replace("-","_")

    created = updated = skipped = 0
    for row in reader:
        data = {norm(k): (v.strip() if v else None) for k, v in row.items()}
        name = data.get("name") or data.get("customer_name") or data.get("company")
        if not name:
            skipped += 1
            continue
        # Upsert: find existing by name + user_id
        existing = db.query(AccountingCustomer).filter(
            AccountingCustomer.user_id == user_id,
            AccountingCustomer.name == name,
        ).first()
        fields = ["email","phone","address","city","state","postcode","abn",
                  "website","contact_name","notes","gl_account","gst_category"]
        if existing:
            for f in fields:
                if data.get(f): setattr(existing, f, data[f])
            existing.is_active   = True
            existing.updated_at  = datetime.utcnow()
            updated += 1
        else:
            cust = AccountingCustomer(user_id=user_id, name=name,
                **{f: data.get(f) for f in fields})
            db.add(cust)
            created += 1
    db.commit()
    return {"created": created, "updated": updated, "skipped": skipped,
            "total": created + updated}


@router.post("/suppliers/csv-import")
async def import_suppliers_csv(
    file:    UploadFile = File(...),
    user_id: int        = Form(...),
    db: Session = Depends(get_db),
):
    """Bulk-import suppliers from CSV (same column schema as customers)."""
    import csv, io
    raw = await file.read()
    try:
        text_data = raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        text_data = raw.decode("latin-1")

    reader = csv.DictReader(io.StringIO(text_data))
    def norm(k): return k.strip().lower().replace(" ","_").replace("-","_")

    created = updated = skipped = 0
    for row in reader:
        data = {norm(k): (v.strip() if v else None) for k, v in row.items()}
        name = data.get("name") or data.get("supplier_name") or data.get("company")
        if not name:
            skipped += 1
            continue
        existing = db.query(AccountingSupplier).filter(
            AccountingSupplier.user_id == user_id,
            AccountingSupplier.name == name,
        ).first()
        fields = ["email","phone","address","abn","website","gl_account","gst_category"]
        if existing:
            for f in fields:
                if data.get(f): setattr(existing, f, data[f])
            existing.is_active   = True
            existing.updated_at  = datetime.utcnow()
            updated += 1
        else:
            sup = AccountingSupplier(user_id=user_id, name=name,
                **{f: data.get(f) for f in fields})
            db.add(sup)
            created += 1
    db.commit()
    return {"created": created, "updated": updated, "skipped": skipped,
            "total": created + updated}


def _cust_to_dict(c: AccountingCustomer) -> dict:
    return {
        "id": c.id, "user_id": c.user_id, "name": c.name,
        "email": c.email, "phone": c.phone, "address": c.address,
        "city": c.city, "state": c.state, "postcode": c.postcode,
        "abn": c.abn, "website": c.website, "contact_name": c.contact_name,
        "notes": c.notes, "gl_account": c.gl_account, "gst_category": c.gst_category,
        "is_active": c.is_active,
        "created_at": c.created_at.isoformat() if c.created_at else None,
        "updated_at": c.updated_at.isoformat() if c.updated_at else None,
    }


# ── Stats ─────────────────────────────────────────────────────────────────────

@router.get("/stats/{user_id}")
def accounting_stats(user_id: int, db: Session = Depends(get_db)):
    from sqlalchemy import func

    def count_type(t):
        return db.query(AccountingDocument).filter(
            AccountingDocument.user_id == user_id,
            AccountingDocument.document_type == t,
        ).count()

    def sum_total(t, status_in=None):
        q = db.query(func.sum(AccountingDocument.total_amount)).filter(
            AccountingDocument.user_id == user_id,
            AccountingDocument.document_type == t,
        )
        if status_in:
            q = q.filter(AccountingDocument.status.in_(status_in))
        return float(q.scalar() or 0)

    return {
        "sale": {
            "quotes":         count_type("quote"),
            "invoices":       count_type("invoice"),
            "invoices_paid":  db.query(AccountingDocument).filter(
                AccountingDocument.user_id == user_id,
                AccountingDocument.document_type == "invoice",
                AccountingDocument.status == "paid",
            ).count(),
            "total_invoiced": sum_total("invoice"),
            "total_paid":     sum_total("invoice", ["paid"]),
        },
        "purchase": {
            "bills":          count_type("bill"),
            "receipts":       count_type("receipt"),
            "bills_pending":  db.query(AccountingDocument).filter(
                AccountingDocument.user_id == user_id,
                AccountingDocument.document_type == "bill",
                AccountingDocument.status == "pending",
            ).count(),
            "total_bills":    sum_total("bill"),
            "total_receipts": sum_total("receipt"),
        },
    }
