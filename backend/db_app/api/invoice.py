from datetime import datetime
from typing import List

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import Session

from db_app.database import get_db
from db_app.models.invoice import BusinessDetail, Invoice
from db_app.services.invoice_service import (
    BusinessService,
    InvoiceService,
    generate_invoice_number,
    init_invoice_tables,
)

router = APIRouter()


# -- Phase 0 tenant isolation --------------------------------------------------
# Business records (and their invoices) now belong to the user who created them.
# Admins see everything; legacy rows without an owner are admin-only.
def _auth(request: Request) -> dict:
    return getattr(request.state, "auth", None) or {}


def _scope_businesses(q, request: Request):
    a = _auth(request)
    if a.get("is_admin"):
        return q
    return q.filter(BusinessDetail.owner_user_id == a.get("user_id", -1))


def _require_business(db, business_id: int, request: Request) -> BusinessDetail:
    b = _scope_businesses(db.query(BusinessDetail), request).filter(BusinessDetail.id == business_id).first()
    if not b:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Business not found")
    return b


def _require_invoice(db, invoice_id: int, request: Request) -> Invoice:
    inv = db.query(Invoice).filter(Invoice.id == invoice_id).first()
    if not inv:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Invoice not found")
    _require_business(db, inv.business_id, request)
    return inv


class BusinessCreateRequest(BaseModel):
    name: str
    email: str | None = None
    phone: str | None = None
    address: str | None = None
    city: str | None = None
    state: str | None = None
    postal_code: str | None = None
    country: str | None = None
    tax_id: str | None = None
    website: str | None = None
    logo_url: str | None = None


class BusinessUpdateRequest(BaseModel):
    name: str | None = None
    email: str | None = None
    phone: str | None = None
    address: str | None = None
    city: str | None = None
    state: str | None = None
    postal_code: str | None = None
    country: str | None = None
    tax_id: str | None = None
    website: str | None = None
    logo_url: str | None = None


class InvoiceItemRequest(BaseModel):
    description: str
    quantity: float
    unit_price: float


class InvoiceCreateRequest(BaseModel):
    invoice_number: str | None = None
    business_id: int
    customer_id: int | None = None
    invoice_date: datetime
    due_date: datetime | None = None
    items: List[InvoiceItemRequest] = []
    notes: str | None = None
    payment_terms: str | None = None
    tax_percent: float = 0.0
    bill_to_name: str | None = None
    bill_to_address: str | None = None
    bill_to_phone: str | None = None
    bill_to_email: str | None = None


class InvoiceStatusUpdateRequest(BaseModel):
    status: str


@router.on_event("startup")
def startup_init_invoice_tables():
    """Create invoice tables if missing. On a brand-new database another startup routine
    creates tables at the same moment; PostgreSQL then rejects one CREATE TABLE
    (duplicate pg_type). Retry instead of crashing the whole application."""
    import logging
    import time
    from sqlalchemy.exc import IntegrityError, ProgrammingError
    try:
        from db_app.init_db import ForeignDatabaseError, _check_database_is_accfino
        _check_database_is_accfino()
    except ForeignDatabaseError:
        logging.getLogger("accfino").error("invoice tables: database is not an AccFino database - not creating tables")
        return
    except Exception:
        pass
    for attempt in range(5):
        try:
            init_invoice_tables()
            return
        except (IntegrityError, ProgrammingError) as e:
            logging.getLogger("accfino").warning("invoice tables: concurrent create, retrying (%s)", type(e).__name__)
            time.sleep(1 + attempt)
    logging.getLogger("accfino").error("invoice tables: could not verify tables at startup; continuing")


@router.get("/next-number")
def get_next_invoice_number():
    return {"invoice_number": generate_invoice_number()}


@router.post("/business")
def create_business(request: BusinessCreateRequest, http_request: Request, db: Session = Depends(get_db)):
    business = BusinessService.create_business(**request.dict())
    row = db.query(BusinessDetail).filter(BusinessDetail.id == business["id"]).first()
    if row is not None:
        row.owner_user_id = _auth(http_request).get("user_id")
        db.commit()
    return {"id": business["id"], "name": business["name"]}


@router.get("/business")
def list_businesses(request: Request, db: Session = Depends(get_db)):
    businesses = _scope_businesses(db.query(BusinessDetail), request).order_by(BusinessDetail.name).all()
    return [
        {
            "id": business.id,
            "name": business.name,
            "email": business.email,
            "phone": business.phone,
            "address": business.address,
            "city": business.city,
            "state": business.state,
            "postal_code": business.postal_code,
            "country": business.country,
            "tax_id": business.tax_id,
            "website": business.website,
            "logo_url": business.logo_url,
            "created_at": business.created_at,
            "updated_at": business.updated_at,
        }
        for business in businesses
    ]


@router.get("/business/{business_id}")
def get_business(business_id: int, request: Request, db: Session = Depends(get_db)):
    business = _require_business(db, business_id, request)

    return {
        "id": business.id,
        "name": business.name,
        "email": business.email,
        "phone": business.phone,
        "address": business.address,
        "city": business.city,
        "state": business.state,
        "postal_code": business.postal_code,
        "country": business.country,
        "tax_id": business.tax_id,
        "website": business.website,
        "logo_url": business.logo_url,
        "created_at": business.created_at,
        "updated_at": business.updated_at,
    }


@router.patch("/business/{business_id}")
def update_business(business_id: int, request: BusinessUpdateRequest, http_request: Request,
                    db: Session = Depends(get_db)):
    _require_business(db, business_id, http_request)
    payload = request.dict(exclude_unset=True)
    if not payload:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="No fields provided")

    updated = BusinessService.update_business(business_id, **payload)
    if not updated:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Business not found")

    return updated


@router.delete("/business/{business_id}")
def delete_business(business_id: int, request: Request, db: Session = Depends(get_db)):
    _require_business(db, business_id, request)
    try:
        result = BusinessService.delete_business(business_id)
        if not result.get("deleted"):
            reason = result.get("reason")
            if reason == "not_found":
                raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Business not found")
            if reason == "has_invoices":
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail="Cannot delete business with existing invoices.",
                )
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Unable to delete business")
        return {"deleted": True}
    except SQLAlchemyError as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Business delete failed: {exc.__class__.__name__}",
        ) from exc


@router.post("")
def create_invoice(request: InvoiceCreateRequest, http_request: Request, db: Session = Depends(get_db)):
    _require_business(db, request.business_id, http_request)
    invoice_number = request.invoice_number or generate_invoice_number()
    try:
        invoice = InvoiceService.create_invoice(
            invoice_number=invoice_number,
            business_id=request.business_id,
            customer_id=request.customer_id,
            invoice_date=request.invoice_date,
            due_date=request.due_date,
            items=[item.dict() for item in request.items],
            notes=request.notes,
            payment_terms=request.payment_terms,
            tax_percent=request.tax_percent,
            bill_to_name=request.bill_to_name,
            bill_to_address=request.bill_to_address,
            bill_to_phone=request.bill_to_phone,
            bill_to_email=request.bill_to_email,
        )
        return invoice
    except IntegrityError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Invoice save failed due to a duplicate or invalid record.",
        ) from exc
    except SQLAlchemyError as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Invoice save failed: {exc.__class__.__name__}",
        ) from exc


@router.get("")
def list_invoices(request: Request, db: Session = Depends(get_db)):
    business_map = {
        business.id: business.name
        for business in _scope_businesses(db.query(BusinessDetail), request).all()
    }
    invoices = (db.query(Invoice).filter(Invoice.business_id.in_(list(business_map) or [-1]))
                .order_by(Invoice.created_at.desc()).all())

    return [
        {
            "id": invoice.id,
            "invoice_number": invoice.invoice_number,
            "business_id": invoice.business_id,
            "business_name": business_map.get(invoice.business_id, "N/A"),
            "status": invoice.status,
            "invoice_date": invoice.invoice_date,
            "due_date": invoice.due_date,
            "subtotal": invoice.subtotal,
            "tax_amount": invoice.tax_amount,
            "discount_amount": invoice.discount_amount,
            "total_amount": invoice.total_amount,
            "bill_to_name": invoice.bill_to_name,
            "bill_to_email": invoice.bill_to_email,
            "bill_to_phone": invoice.bill_to_phone,
            "bill_to_address": invoice.bill_to_address,
            "notes": invoice.notes,
            "items": [
                {
                    "description": item.description,
                    "quantity": item.quantity,
                    "unit_price": item.unit_price,
                    "line_total": item.line_total,
                }
                for item in invoice.items
            ],
        }
        for invoice in invoices
    ]


@router.patch("/{invoice_id}/status")
def update_invoice_status(invoice_id: int, request: InvoiceStatusUpdateRequest, http_request: Request,
                          db: Session = Depends(get_db)):
    _require_invoice(db, invoice_id, http_request)
    try:
        updated = InvoiceService.update_invoice_status(invoice_id, request.status)
        if not updated:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Invoice not found")
        # Avoid detached-instance attribute access after session close.
        return {"id": invoice_id, "status": request.status}
    except SQLAlchemyError as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Invoice status update failed: {exc.__class__.__name__}",
        ) from exc


@router.delete("/{invoice_id}")
def delete_invoice(invoice_id: int, request: Request, db: Session = Depends(get_db)):
    _require_invoice(db, invoice_id, request)
    deleted = InvoiceService.delete_invoice(invoice_id)
    if not deleted:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Invoice not found")
    return {"deleted": True}
