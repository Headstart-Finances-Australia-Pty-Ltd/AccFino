"""Shared helpers for the Phase 1 modules: errors, account/tax/contact resolution, numbering, per-organisation settings."""
import json
import re
from datetime import date, datetime

from sqlalchemy import func

from accfino.core import models as m
from accfino.modules.accounting.models import ledger as lm
from accfino.modules.accounting.books import models as b
from accfino.modules.accounting.ledger.service import LedgerError, money  # noqa: F401  (re-exported)

CONTROL_KEYS = {"ar_control", "ap_control", "gst"}
PREFIXES = {"quote": "QU-", "invoice": "INV-", "credit_note": "CN-", "purchase_order": "PO-", "bill": "BILL-", "supplier_credit": "SC-"}


class BooksError(Exception):
    """A business-rule violation. Mapped to an HTTP error by the handler installed in accfino_core.install()."""

    def __init__(self, message: str, status: int = 422):
        super().__init__(message)
        self.status = status


def as_date(v, field="date") -> date:
    if isinstance(v, datetime):
        return v.date()
    if isinstance(v, date):
        return v
    try:
        return date.fromisoformat(str(v)[:10])
    except Exception:
        raise BooksError(f"Invalid {field}: {v!r}")


# ------------------------------------------------------------------ accounts / tax --
def get_account(db, org, ref, *, what="Account"):
    """Find an active account of this organisation by id, code or (exact, case-insensitive) name."""
    if ref is None or ref == "":
        raise BooksError(f"{what} is required")
    q = db.query(lm.LedgerAccount).filter(lm.LedgerAccount.org_id == org.id)
    acc = None
    s = str(ref).strip()
    if isinstance(ref, int):                      # an integer is an id (never a code), so id 77 cannot collide with code "77"
        acc = q.filter(lm.LedgerAccount.id == ref).first()
    elif s.isdigit():
        acc = q.filter(lm.LedgerAccount.code == s).first() or q.filter(lm.LedgerAccount.id == int(s)).first()
    if acc is None:
        acc = q.filter(func.lower(lm.LedgerAccount.code) == s.lower()).first() or q.filter(func.lower(lm.LedgerAccount.name) == s.lower()).first()
    if acc is None:
        raise BooksError(f"{what} '{ref}' was not found in this organisation")
    if not acc.is_active:
        raise BooksError(f"{what} {acc.code} {acc.name} is inactive")
    return acc


def system_acct(db, org, key):
    acc = db.query(lm.LedgerAccount).filter_by(org_id=org.id, system_key=key).first()
    if acc is None:
        raise BooksError(f"The organisation has no '{key}' system account; run the ledger top-up", 500)
    return acc


def get_tax(db, org, ref):
    if ref is None or ref == "":
        return None
    q = db.query(lm.TaxCode).filter(lm.TaxCode.org_id == org.id, lm.TaxCode.is_active.is_(True))
    s = str(ref).strip()
    t = (q.filter(lm.TaxCode.id == int(s)).first() if s.isdigit() else None) \
        or q.filter(func.lower(lm.TaxCode.code) == s.lower()).first() or q.filter(func.lower(lm.TaxCode.name) == s.lower()).first()
    if t is None:
        raise BooksError(f"Tax code '{ref}' was not found in this organisation")
    return t


def bank_account(db, org, ref):
    acc = get_account(db, org, ref, what="Bank account")
    if acc.account_type not in ("bank", "credit_card"):
        raise BooksError(f"{acc.code} {acc.name} is not a bank or credit-card account")
    return acc


def bank_accounts(db, org):
    return db.query(lm.LedgerAccount).filter(lm.LedgerAccount.org_id == org.id, lm.LedgerAccount.account_type.in_(("bank", "credit_card")),
                                            lm.LedgerAccount.is_active.is_(True)).order_by(lm.LedgerAccount.code).all()


# ------------------------------------------------------------------ settings --
DEFAULT_SETTINGS = {"default_sales_account": "201", "default_purchase_account": "499", "default_tax_sales": "OUTPUT",
                    "default_tax_purchases": "INPUT", "invoice_terms_days": 14, "bill_terms_days": 30,
                    "invoice_footer": "", "mileage_rate_per_km": None}


def get_settings(db, org) -> dict:
    row = db.get(m.SystemSetting, f"books.settings:{org.id}")
    out = dict(DEFAULT_SETTINGS)
    if row and row.value:
        try:
            out.update(json.loads(row.value))
        except Exception:
            pass
    return out


def save_settings(db, org, patch: dict) -> dict:
    cur = get_settings(db, org)
    for k, v in patch.items():
        if k in DEFAULT_SETTINGS:
            cur[k] = v
    key = f"books.settings:{org.id}"
    row = db.get(m.SystemSetting, key)
    if row is None:
        db.add(m.SystemSetting(key=key, value=json.dumps(cur)))
    else:
        row.value = json.dumps(cur)
    db.flush()
    return cur


def default_account(db, org, side):
    """The account a line uses when none is given: contact default -> organisation setting -> first suitable account."""
    st = get_settings(db, org)
    want = st["default_sales_account"] if side == "sales" else st["default_purchase_account"]
    try:
        return get_account(db, org, want)
    except BooksError:
        classes = ("revenue",) if side == "sales" else ("expense",)
        acc = db.query(lm.LedgerAccount).filter(lm.LedgerAccount.org_id == org.id, lm.LedgerAccount.account_class.in_(classes),
                                               lm.LedgerAccount.is_active.is_(True)).order_by(lm.LedgerAccount.code).first()
        if acc is None:
            raise BooksError("No default account is set up for this organisation")
        return acc


# ------------------------------------------------------------------ contacts --
def contact_dict(c):
    return dict(id=c.id, name=c.name, is_customer=c.is_customer, is_supplier=c.is_supplier, email=c.email, phone=c.phone, abn=c.abn,
                address=c.address, terms_days=c.terms_days, default_account_id=c.default_account_id,
                default_tax_code_id=c.default_tax_code_id, credit_limit=str(c.credit_limit) if c.credit_limit is not None else None,
                notes=c.notes, is_active=c.is_active)


def find_contact(db, org, *, contact_id=None, name=None, role, create=False):
    """Resolve a contact by id or name; optionally create it (used when an invoice is keyed with a new customer name)."""
    q = db.query(b.Contact).filter(b.Contact.org_id == org.id)
    c = None
    if contact_id:
        c = q.filter(b.Contact.id == int(contact_id)).first()
        if c is None:
            raise BooksError("Contact not found", 404)
    elif name and str(name).strip():
        c = q.filter(func.lower(b.Contact.name) == str(name).strip().lower()).first()
        if c is None:
            if not create:
                raise BooksError(f"Contact '{name}' not found", 404)
            c = b.Contact(org_id=org.id, name=str(name).strip()[:255], is_customer=(role == "customer"), is_supplier=(role == "supplier"),
                          terms_days=14 if role == "customer" else 30)
            db.add(c)
            db.flush()
    else:
        raise BooksError("A customer/supplier is required" if role else "A contact is required")
    if not c.is_active:
        raise BooksError(f"Contact {c.name} is archived")
    if role == "customer" and not c.is_customer:
        c.is_customer = True
    if role == "supplier" and not c.is_supplier:
        c.is_supplier = True
    return c


# ------------------------------------------------------------------ numbering --
def next_number(db, org, doc_type: str) -> str:
    seq = db.query(b.DocSequence).filter_by(org_id=org.id, doc_type=doc_type).with_for_update().one_or_none()
    if seq is None:
        seq = b.DocSequence(org_id=org.id, doc_type=doc_type, prefix=PREFIXES[doc_type], next_no=1)
        db.add(seq)
        db.flush()
    while True:
        number = f"{seq.prefix}{seq.next_no:04d}"
        seq.next_no += 1
        if not db.query(b.Doc.id).filter_by(org_id=org.id, doc_type=doc_type, number=number).first():
            return number


def ledger_error(e: Exception):
    raise BooksError(str(e), 422)


# ------------------------------------------------------------------ platform switch: bulk data import --
BULK_IMPORT_KEY = "platform.bulk_import"


def bulk_import_enabled(db) -> bool:
    """Admin Console > Modules Management > 'Bulk data import'. On unless an administrator switched it off."""
    row = db.get(m.SystemSetting, BULK_IMPORT_KEY)
    return not (row and (row.value or "").strip().lower() == "off")


def set_bulk_import(db, enabled: bool):
    row = db.get(m.SystemSetting, BULK_IMPORT_KEY)
    if row is None:
        db.add(m.SystemSetting(key=BULK_IMPORT_KEY, value="on" if enabled else "off"))
    else:
        row.value = "on" if enabled else "off"
    db.flush()


def require_bulk_import(db, ctx=None):
    """Platform switch first; then, when a ctx is given, the organisation's plan / add-on must include 'bulk-import' (and not be read-only)."""
    if not bulk_import_enabled(db):
        raise BooksError("Bulk data import has been switched off by your platform administrator (Admin > Modules Management).", 403)
    if ctx is not None:
        from accfino.core.subscription import service as S          # lazy: subscription imports models, not books
        S.check(db, ctx, ("bulk-import",), "POST")
