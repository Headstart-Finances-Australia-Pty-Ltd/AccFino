"""
csv_import - bulk CSV loading for Books & Accounting.

Every importer goes through the SAME service layer the screens use (documents, payments, expenses, inventory, fixed assets), so each
record is validated and posted to the ledger exactly as if it had been keyed by hand: GST per line, control accounts, lock date,
duplicate-bill protection, stock/asset sub-ledgers, segregation of duties on expense claims.

Rules that apply to every entity
  * CHECK FIRST.  dry_run=True runs the whole import for real inside a transaction and then rolls it back, so the answer you get is
                  exactly what the real run would do (including posting errors and records that depend on earlier records in the file).
  * ALL-OR-NOTHING.  If any record has a problem nothing is saved: a half-loaded file is harder to fix than an empty one.
  * NEW RECORDS ONLY (except customers / suppliers, which are matched on name and updated).  Re-loading the same file therefore fails
                  cleanly ("already exists") instead of duplicating invoices.
  * Columns are matched by name, in any order, case-insensitively; common aliases are accepted; unknown columns are ignored with a warning.
  * Dates: YYYY-MM-DD or DD/MM/YYYY.  Amounts: 1234.50, $1,234.50 or (1,234.50).

Entities
  customers, suppliers                  contacts (matched on name; existing ones are updated)
  quotes, invoices, credit_notes        sales documents   - one row per LINE, lines grouped by `number`
  purchase_orders, bills, supplier_credits   purchase documents - same layout
  receipts, supplier_payments           money received from customers / paid to suppliers, allocated to invoices / bills
  expense_claims                        one row per ITEM, grouped by `claim`; can be advanced to submitted / approved / paid / rejected
  inventory_items                       stock item master with optional opening stock
  stock_movements                       buy / sell / adjustment / opening movements by SKU
  fixed_assets                          asset register, with optional disposal

Journals and bank statement lines already have their own importers (/ledger/journal-import, /banking/lines/import-csv).
"""
import csv
import io
import re
from datetime import date, datetime
from decimal import Decimal, InvalidOperation

from sqlalchemy import func
from sqlalchemy.exc import SQLAlchemyError

from accfino_core import models as m
from accfino_core.assets import models as fa
from accfino_core.assets import service as FA
from accfino_core.books import docs as D
from accfino_core.books import expenses as EX
from accfino_core.books import models as b
from accfino_core.books.common import BooksError, as_date, bank_accounts, get_account, get_tax, money
from accfino_core.inventory import models as inv
from accfino_core.inventory import service as INV
from accfino_core.ledger import service as L

MAX_BYTES = 5_000_000
MAX_ROWS = 5000
MAX_ITEMS_RETURNED = 1000
Z = Decimal("0.00")


# ------------------------------------------------------------------------------------------------ parsing helpers --
def _decode(raw):
    if isinstance(raw, str):
        return raw.lstrip("\ufeff")
    try:
        return raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        return raw.decode("cp1252", errors="replace")          # Excel on Windows "CSV (Comma delimited)"


def _norm_header(h):
    return re.sub(r"[^a-z0-9]+", "_", (h or "").strip().lower()).strip("_")


def _grid(text):
    first = next((ln for ln in text.splitlines() if ln.strip()), "")
    delim = max((",", ";", "\t"), key=lambda d: first.count(d))          # Excel in some regions writes ; instead of ,
    rows = [r for r in csv.reader(io.StringIO(text), delimiter=delim) if any((c or "").strip() for c in r)]
    return rows


_DATE_FORMATS = ("%Y-%m-%d", "%d/%m/%Y", "%d/%m/%y", "%d-%m-%Y", "%d %b %Y", "%d-%b-%Y", "%d %B %Y", "%Y/%m/%d")


def _date(s, what="date"):
    s = (s or "").strip()
    if not s:
        return None
    for f in _DATE_FORMATS:
        try:
            return datetime.strptime(s, f).date()
        except ValueError:
            pass
    raise BooksError(f"'{s}' is not a valid {what} (use DD/MM/YYYY or YYYY-MM-DD)")


def _dec(s, what="amount", default=None):
    s = (s or "").strip() if isinstance(s, str) else s
    if s in (None, ""):
        return default
    if isinstance(s, Decimal):
        return s
    t = str(s).replace("$", "").replace(",", "").replace(" ", "")
    neg = t.startswith("(") and t.endswith(")")
    t = t.strip("()")
    try:
        v = Decimal(t)
    except InvalidOperation:
        raise BooksError(f"'{s}' is not a valid {what}")
    if not v.is_finite():
        raise BooksError(f"'{s}' is not a valid {what}")
    return -v if neg else v


def _int(s, what="number", default=None):
    s = (s or "").strip()
    if not s:
        return default
    try:
        return int(Decimal(s.replace(",", "")))
    except (InvalidOperation, ValueError):
        raise BooksError(f"'{s}' is not a valid {what}")


def _bool(s, default=None):
    t = (s or "").strip().lower()
    if not t:
        return default
    if t in ("y", "yes", "true", "1", "active"):
        return True
    if t in ("n", "no", "false", "0", "inactive", "archived"):
        return False
    raise BooksError(f"'{s}' is not yes/no")


def _sort_date(s):
    try:
        return _date(s) or date.max
    except BooksError:
        return date.max


def _key(s):
    return re.sub(r"[^a-z]", "", (s or "").lower())


_AMOUNTS_ARE = {"exclusive": {"exclusive", "taxexclusive", "gstexclusive", "excl", "ex", "exgst", "exclusiveofgst", "exclusiveoftax"},
                "inclusive": {"inclusive", "taxinclusive", "gstinclusive", "incl", "inc", "incgst", "inclusiveofgst", "inclusiveoftax"},
                "no_tax": {"notax", "nogst", "none", "taxfree", "notaxes"}}


def _amounts_are(s, default):
    k = _key(s)
    if not k:
        return default
    for canon, names in _AMOUNTS_ARE.items():
        if k in names:
            return canon
    raise BooksError(f"amounts_are '{s}' must be exclusive, inclusive or no_tax")


# ------------------------------------------------------------------------------------------------ specs --
class Col:
    def __init__(self, name, help, required=False, example="", aliases=()):
        self.name, self.help, self.required, self.example, self.aliases = name, help, required, example, tuple(aliases)


class Spec:
    def __init__(self, key, title, description, columns, handler, *, group_col=None, start_cols=(), header_cols=(), line_cols=(), notes=(),
                 template=None, post_check=None, sort_key=None, options=()):
        self.key, self.title, self.description, self.columns, self.handler = key, title, description, columns, handler
        self.group_col, self.start_cols, self.header_cols, self.line_cols = group_col, tuple(start_cols), tuple(header_cols), tuple(line_cols)
        self.notes, self.post_check, self.sort_key, self.options = list(notes), post_check, sort_key, tuple(options)
        self.template = template or []

    def alias_map(self):
        out = {}
        for c in self.columns:
            for a in (c.name,) + c.aliases:
                n = _norm_header(a)
                out.setdefault(n, c.name)
                out.setdefault(n.replace("_", ""), c.name)            # "ContactName" == contact_name
        return out

    def info(self):
        return dict(entity=self.key, title=self.title, description=self.description, notes=self.notes, options=list(self.options),
                    columns=[dict(name=c.name, required=c.required, help=c.help, example=c.example) for c in self.columns])


class Rec:
    """One record to create: the rows that make it up (lines of one document, allocations of one payment, ...)."""

    def __init__(self, key, row):
        self.key, self.row, self.rows = key, row, []          # rows: [(rownum, {canon: value})]
        self.fields = {}

    def first(self, name, default=""):
        return self.fields.get(name, default)

    def line_rows(self, cols):
        for n, r in self.rows:
            if any(r.get(c) for c in cols):
                yield n, r


def _records(spec, grid, result):
    head = [_norm_header(h) for h in grid[0]]
    amap = spec.alias_map()
    idx, unknown = {}, []
    for i, h in enumerate(head):
        canon = amap.get(h) or amap.get(h.replace("_", ""))
        if canon is None:
            if h:
                unknown.append(grid[0][i].strip())
        elif canon in idx:
            result["warnings"].append(f"Column '{grid[0][i].strip()}' repeats '{canon}' and was ignored")
        else:
            idx[canon] = i
    missing = [c.name for c in spec.columns if c.required and c.name not in idx]
    if missing:
        raise BooksError(f"The file is missing required column(s): {', '.join(missing)}. Columns found: {', '.join(h.strip() for h in grid[0] if h.strip())}")
    if unknown:
        result["warnings"].append("Ignored column(s) not used by this import: " + ", ".join(unknown))
    body = grid[1:]
    if len(body) > MAX_ROWS:
        raise BooksError(f"Too many rows ({len(body)}); the limit is {MAX_ROWS} per file. Split the file and import it in parts")
    rows = []
    for n, r in enumerate(body, start=2):
        rows.append((n, {c: (r[i].strip() if i < len(r) and r[i] is not None else "") for c, i in idx.items()}))
    recs, by_key, cur = [], {}, None
    for n, r in rows:
        if spec.group_col is None:
            cur = Rec("", n)
            recs.append(cur)
        else:
            k = r.get(spec.group_col, "")
            if k:
                cur = by_key.get(k)
                if cur is None:
                    cur = by_key[k] = Rec(k, n)
                    recs.append(cur)
            elif cur is None or any(r.get(c) for c in spec.start_cols):
                cur = Rec("", n)
                recs.append(cur)
        cur.rows.append((n, r))
    for rec in recs:                                   # header fields: first non-blank value; disagreements are reported, not guessed
        rec.conflicts = []
        for c in [col.name for col in spec.columns]:
            vals = [(n, r.get(c, "")) for n, r in rec.rows if r.get(c, "")]
            if vals:
                rec.fields[c] = vals[0][1]
                if c in spec.header_cols and any(v != vals[0][1] for _, v in vals):
                    rec.conflicts.append(f"rows {vals[0][0]} and {next(n for n, v in vals if v != vals[0][1])} give different values for '{c}'")
    return recs


# ------------------------------------------------------------------------------------------------ lookups --
def _contact(db, org, name, role, *, create=False, updates_role=False):
    name = (name or "").strip()
    if not name:
        raise BooksError(f"{role.title()} is required")
    c = db.query(b.Contact).filter(b.Contact.org_id == org.id, func.lower(b.Contact.name) == name.lower()).first()
    if c is None:
        raise BooksError(f"{role.title()} '{name}' does not exist. Import your {role}s first (or add the name to the contacts file)")
    if not c.is_active:
        raise BooksError(f"{role.title()} '{c.name}' is archived")
    if not (c.is_customer if role == "customer" else c.is_supplier):
        raise BooksError(f"'{c.name}' is not set up as a {role}")
    return c


def _contact_exists(db, org, name):
    return db.query(b.Contact.id).filter(b.Contact.org_id == org.id, func.lower(b.Contact.name) == (name or "").strip().lower()).first() is not None


def _only_bank(db, org, ref):
    if ref:
        return ref
    banks = bank_accounts(db, org)
    if len(banks) == 1:
        return banks[0].id
    raise BooksError("bank_account is required (this organisation has " + ("no bank accounts - add one in Banking first" if not banks else f"{len(banks)} bank accounts") + ")")


def _doc_by_number(db, org, doc_type, number):
    d = db.query(b.Doc).filter_by(org_id=org.id, doc_type=doc_type, number=number).first()
    if d is None:
        raise BooksError(f"{doc_type.replace('_', ' ').title()} '{number}' was not found (import it first)")
    return d


# ------------------------------------------------------------------------------------------------ contacts --
def _h_contact(role):
    def h(db, org, ctx, rec, opts):
        from accfino_core.api.books_docs import ContactIn, upsert_contact          # lazy: the API module imports the books package
        f = rec.fields
        name = f.get("name", "")
        if not name:
            raise BooksError("name is required")
        existing = db.query(b.Contact).filter(b.Contact.org_id == org.id, func.lower(b.Contact.name) == name.lower()).first()
        active = _bool(f.get("active"), None)
        body = ContactIn(name=name, email=f.get("email") or None, phone=f.get("phone") or None, abn=f.get("abn") or None, address=f.get("address") or None,
                         terms_days=_int(f.get("terms_days"), "terms_days"), credit_limit=_dec(f.get("credit_limit"), "credit_limit"),
                         default_account=f.get("default_account") or None, default_tax_code=f.get("default_tax_code") or None,
                         notes=f.get("notes") or None, is_active=active)
        warn = []
        if existing is not None and not (existing.is_customer if role == "customer" else existing.is_supplier):
            body.is_customer, body.is_supplier = (True, None) if role == "customer" else (None, True)
            warn.append(f"'{existing.name}' already exists as a {'supplier' if role == 'customer' else 'customer'}; it will become both")
        c = upsert_contact(db, ctx, body, existing, role)
        return dict(label=c.name, detail=("updates existing" if existing else "new") + (f" · {c.email}" if c.email else ""), amount=None,
                    action="update" if existing else "create", warnings=warn)
    return h


# ------------------------------------------------------------------------------------------------ documents --
DOC_META = {"quotes": ("quote", "customer"), "invoices": ("invoice", "customer"), "credit_notes": ("credit_note", "customer"),
            "purchase_orders": ("purchase_order", "supplier"), "bills": ("bill", "supplier"), "supplier_credits": ("supplier_credit", "supplier")}
_STATUS_WORDS = {"draft": "draft", "approved": "approved", "authorised": "approved", "authorized": "approved", "posted": "approved", "sent": "sent",
                 "accepted": "accepted", "declined": "declined", "rejected": "declined"}


def _h_doc(entity):
    doc_type, role = DOC_META[entity]

    def h(db, org, ctx, rec, opts):
        f = rec.fields
        warn = []
        contact = (f.get("contact") or "").strip()
        if not contact:
            raise BooksError(f"{role} is required")
        if not _contact_exists(db, org, contact):
            warn.append(f"New {role} '{contact}' will be created (import your {role}s first if this is a typo)")
        issue = _date(f.get("issue_date"), "issue date")
        if issue is None:
            raise BooksError("issue_date is required")
        due = _date(f.get("due_date"), "due date")
        amounts_are = _amounts_are(f.get("amounts_are"), opts.get("amounts_are") or "exclusive")
        raw_status = _key(f.get("status"))
        if raw_status:
            status = _STATUS_WORDS.get(raw_status)
            allowed = ("draft", "sent", "accepted", "declined") if doc_type == "quote" else ("draft", "approved")
            if status not in allowed:
                raise BooksError(f"status '{f.get('status')}' must be one of: {', '.join(allowed)}")
        else:
            status = "draft" if doc_type == "quote" else ("draft" if opts.get("mode") == "draft" else "approved")
        lines = []
        for n, r in rec.line_rows(("line_description", "unit_price", "qty", "account")):
            ln = dict(description=r.get("line_description") or "")
            if not ln["description"].strip():
                raise BooksError(f"Row {n}: line_description is required")
            if r.get("qty"):
                ln["qty"] = _dec(r["qty"], f"row {n} qty")
            if r.get("unit_price"):
                ln["unit_price"] = _dec(r["unit_price"], f"row {n} unit_price")
            if r.get("discount_pct"):
                ln["discount_pct"] = _dec(r["discount_pct"], f"row {n} discount_pct")
            if r.get("account"):
                ln["account"] = r["account"]
            if r.get("tax_code"):
                ln["tax_code"] = r["tax_code"]
            lines.append(ln)
        if not lines:
            raise BooksError("the document has no lines")
        data = dict(contact=contact, number=f.get("number") or None, issue_date=issue, due_date=due, reference=f.get("reference") or None, amounts_are=amounts_are,
                    notes=f.get("notes") or None, terms=f.get("terms") or None, source="import", lines=lines)
        doc = D.create_doc(db, org, ctx.user_id, doc_type, data, approve=(status == "approved"))
        if doc_type == "quote":
            if status == "sent":
                D.mark_sent(db, doc)
            elif status in ("accepted", "declined"):
                D.quote_decision(db, doc, status)
        apply_to = f.get("apply_to")
        if apply_to:
            if doc_type not in D.CREDIT_DOCS:
                raise BooksError("apply_to only applies to credit notes / supplier credits")
            if doc.status != "approved":
                raise BooksError("apply_to needs the credit to be imported as approved (not draft)")
            target = _doc_by_number(db, org, "invoice" if doc_type == "credit_note" else "bill", apply_to)
            amt = _dec(f.get("apply_amount"), "apply_amount") or min(doc.amount_due, target.amount_due)
            D.allocate_credit(db, org, doc, [dict(doc_id=target.id, amount=amt)])
        d_status = {"approved": "posted to ledger", "draft": "draft"}.get(doc.status, doc.status)
        return dict(label=f"{doc.number} · {doc.contact.name}", detail=f"{doc.issue_date.isoformat()} · {len(doc.lines)} line(s) · {d_status}",
                    amount=doc.total, action="create", warnings=warn)
    return h


# ------------------------------------------------------------------------------------------------ payments --
def _h_payment(entity):
    kind, role, main = ("receive", "customer", "invoice") if entity == "receipts" else ("pay", "supplier", "bill")

    def h(db, org, ctx, rec, opts):
        f = rec.fields
        contact = _contact(db, org, f.get("contact"), role)
        pay_date = _date(f.get("date"), "date")
        if pay_date is None:
            raise BooksError("date is required")
        allocs, unalloc = [], Z
        for n, r in rec.rows:
            amt = _dec(r.get("amount"), f"row {n} amount")
            if amt is None or amt <= 0:
                raise BooksError(f"Row {n}: amount must be greater than zero")
            num = r.get("document")
            if num:
                allocs.append(dict(doc_id=_doc_by_number(db, org, main, num).id, amount=amt))
            else:
                unalloc += amt
        total = sum((a["amount"] for a in allocs), Z) + unalloc
        warn = [f"{unalloc} is not allocated to a {main}: it will be held as an unallocated payment on the account"] if unalloc else []
        p = D.record_payment(db, org, ctx.user_id, kind=kind, contact=contact, pay_date=pay_date, amount=total, bank_ref=_only_bank(db, org, f.get("bank_account")),
                             reference=f.get("reference") or None, allocations=allocs, overpayment=unalloc > 0)
        return dict(label=f"{contact.name}" + (f" · {f['reference']}" if f.get("reference") else ""),
                    detail=f"{pay_date.isoformat()} · {len(allocs)} {main}(s)" + (" + unallocated" if unalloc else ""), amount=p.amount, action="create", warnings=warn)
    return h


# ------------------------------------------------------------------------------------------------ expense claims --
def _h_claim(db, org, ctx, rec, opts):
    f = rec.fields
    raw_status = _key(f.get("status")) or "draft"
    status = {"draft": "draft", "submitted": "submitted", "approved": "approved", "paid": "paid", "reimbursed": "paid", "rejected": "rejected"}.get(raw_status)
    if status is None:
        raise BooksError(f"status '{f.get('status')}' must be draft, submitted, approved, paid or rejected")
    items = []
    for n, r in rec.line_rows(("description", "amount", "account", "km")):
        kind = _key(r.get("kind")) or "receipt"
        it = dict(date=_date(r.get("date"), f"row {n} date"), merchant=r.get("merchant") or None, description=r.get("description") or "", account=r.get("account") or None,
                  kind=kind)
        if not it["account"]:
            raise BooksError(f"Row {n}: account is required")
        if kind == "mileage":
            it["km"] = _dec(r.get("km"), f"row {n} km")
            if r.get("rate_per_km"):
                it["rate_per_km"] = _dec(r["rate_per_km"], f"row {n} rate_per_km")
        else:
            it["amount"] = _dec(r.get("amount"), f"row {n} amount")
            if r.get("tax_code"):
                it["tax_code"] = r["tax_code"]
        items.append(it)
    if not items:
        raise BooksError("the claim has no items")
    title = f.get("title") or (rec.key if rec.key else None)
    claim = EX.create_claim(db, org, ctx, dict(title=title, items=items))
    if f.get("claimant"):
        claim.claimant_name = f["claimant"][:200]
    warn = []
    if status in ("submitted", "approved", "paid", "rejected"):
        EX.submit(db, org, ctx, claim)
    if status == "rejected":
        EX.reject(db, ctx, claim, f.get("reject_reason") or "Rejected (imported)")
    if status in ("approved", "paid"):
        EX.approve(db, org, ctx, claim, _date(f.get("approve_date"), "approve_date"))
    if status == "paid":
        pay_date = _date(f.get("paid_date"), "paid_date")
        if pay_date is None:
            raise BooksError("paid_date is required for a paid claim")
        EX.reimburse(db, org, ctx, claim, pay_date, _only_bank(db, org, f.get("bank_account")), f.get("reference") or None)
    if f.get("claimant"):
        warn.append("Claimant name is recorded as text; the claim belongs to the user who imported it (they are the one who sees it under 'My claims')")
    return dict(label=f"{claim.number} · {claim.claimant_name}", detail=f"{claim.title} · {len(items)} item(s) · {claim.status}", amount=claim.total,
                action="create", warnings=warn)


# ------------------------------------------------------------------------------------------------ inventory --
def _h_item(db, org, ctx, rec, opts):
    f = rec.fields
    data = dict(sku=f.get("sku"), name=f.get("name"), description=f.get("description") or None, inventory_account=f.get("inventory_account") or None,
                cogs_account=f.get("cogs_account") or None, sales_account=f.get("sales_account") or None, purchase_tax_code=f.get("purchase_tax_code") or None,
                sales_tax_code=f.get("sales_tax_code") or None, sale_price=_dec(f.get("sale_price"), "sale_price"))
    item = INV.create_item(db, org, data)
    qty = _dec(f.get("opening_qty"), "opening_qty")
    detail = "no opening stock"
    amount = None
    if qty:
        cost = _dec(f.get("opening_unit_cost"), "opening_unit_cost")
        if cost is None:
            raise BooksError("opening_unit_cost is required when opening_qty is given")
        if not f.get("opening_credit_account"):
            raise BooksError("opening_credit_account is required when opening_qty is given (the account the opening stock value is credited to, e.g. 960 Retained Earnings)")
        od = _date(f.get("opening_date"), "opening_date")
        if od is None:
            raise BooksError("opening_date is required when opening_qty is given")
        mv = INV.buy(db, org, ctx.user_id, item, mv_date=od, quantity=qty, unit_cost=cost, credit_account=f["opening_credit_account"], reference="Opening stock",
                     note="Opening stock (CSV import)", kind="opening")
        detail, amount = f"opening {qty:g} @ {cost}", mv.amount
    return dict(label=f"{item.sku} · {item.name}", detail=detail, amount=amount, action="create", warnings=[])


def _h_movement(db, org, ctx, rec, opts):
    f = rec.fields
    item = db.query(inv.StockItem).filter_by(org_id=org.id, sku=f.get("sku", "")).with_for_update().one_or_none()
    if item is None:
        raise BooksError(f"No stock item with SKU '{f.get('sku')}' (import the items first)")
    kind = _key(f.get("kind"))
    d = _date(f.get("date"), "date")
    if d is None:
        raise BooksError("date is required")
    data = dict(kind=kind, date=d, reference=f.get("reference") or None, note=f.get("note") or None)
    if kind in ("buy", "opening"):
        data.update(quantity=_dec(f.get("quantity"), "quantity"), unit_cost=_dec(f.get("unit_cost"), "unit_cost"), credit_account=f.get("account") or None)
        if data["quantity"] is None or data["unit_cost"] is None:
            raise BooksError("quantity and unit_cost are required for a buy / opening movement")
        if not data["credit_account"]:
            raise BooksError("account is required for a buy / opening movement (the account credited, e.g. your bank account)")
    elif kind == "sell":
        data.update(quantity=_dec(f.get("quantity"), "quantity"), debit_account=f.get("account") or None)
        if data["quantity"] is None:
            raise BooksError("quantity is required for a sell movement")
    elif kind == "adjustment":
        data.update(counted_quantity=_dec(f.get("counted_quantity"), "counted_quantity"), account=f.get("account") or None)
        if data["counted_quantity"] is None:
            raise BooksError("counted_quantity is required for an adjustment (the quantity actually counted)")
    else:
        raise BooksError("kind must be buy, sell, adjustment or opening")
    mv = INV.record_movement(db, org, ctx.user_id, item, data)
    return dict(label=f"{item.sku} · {kind}", detail=f"{d.isoformat()} · qty {mv.quantity:g} · now {item.quantity_on_hand:g} on hand", amount=mv.amount, action="create", warnings=[])


def _inventory_check(db, org):
    c = INV.control(db, org, date.today())
    return [f"Inventory account {a['account']}: ledger {a['ledger_balance']} vs stock items {a['subledger_total']}. Bring the ledger into line (opening balance journal or stock purchases)"
            for a in c["accounts"] if not a["reconciled"]]


# ------------------------------------------------------------------------------------------------ fixed assets --
def _h_asset(db, org, ctx, rec, opts):
    f = rec.fields
    mk = _key(f.get("method")) or "straightline"
    method = {"straightline": "straight_line", "sl": "straight_line", "prime": "straight_line", "diminishingvalue": "diminishing_value", "dv": "diminishing_value",
              "reducingbalance": "diminishing_value"}.get(mk)
    if method is None:
        raise BooksError(f"method '{f.get('method')}' must be straight_line or diminishing_value")
    data = dict(number=f.get("number") or None, name=f.get("name") or "", category=f.get("category") or None, asset_account=f.get("asset_account"),
                depreciation_account=f.get("depreciation_account"), expense_account=f.get("expense_account") or None, purchase_date=_date(f.get("purchase_date"), "purchase_date"),
                cost=_dec(f.get("cost"), "cost"), residual_value=_dec(f.get("residual_value"), "residual_value", Z), method=method,
                effective_life_months=_int(f.get("effective_life_months"), "effective_life_months"), dv_rate_pct=_dec(f.get("dv_rate_pct"), "dv_rate_pct"),
                opening_accumulated_depreciation=_dec(f.get("opening_accumulated_depreciation"), "opening_accumulated_depreciation", Z), notes=f.get("notes") or None)
    if not data["name"].strip():
        raise BooksError("name is required")
    if data["purchase_date"] is None:
        raise BooksError("purchase_date is required")
    if data["cost"] is None:
        raise BooksError("cost is required")
    if not data["asset_account"] or not data["depreciation_account"]:
        raise BooksError("asset_account and depreciation_account are required")
    existing = f.get("number") and db.query(fa.FixedAsset.id).filter_by(org_id=org.id, number=f["number"]).first()
    if existing:
        raise BooksError(f"Asset number {f['number']} already exists")
    asset = FA.register(db, org, ctx.user_id, data)
    detail = f"{asset.purchase_date.isoformat()} · cost {asset.cost}"
    if f.get("disposal_date"):
        dd = _date(f["disposal_date"], "disposal_date")
        proceeds = _dec(f.get("disposal_proceeds"), "disposal_proceeds", Z)
        res = FA.dispose(db, org, ctx.user_id, asset, disposal_date=dd, proceeds=proceeds, bank_ref=f.get("disposal_bank_account") or (_only_bank(db, org, None) if proceeds else None))
        detail += f" · disposed {dd.isoformat()} ({'gain' if Decimal(res['gain_or_loss']) >= 0 else 'loss'} {res['gain_or_loss']})"
    return dict(label=f"{asset.number} · {asset.name}", detail=detail, amount=asset.cost, action="create", warnings=[])


def _asset_check(db, org):
    c = FA.control(db, org, date.today())
    return [f"Ledger vs register: {p['asset_account']} cost {p['ledger_cost']} (ledger) vs {p['register_cost']} (register); {p['depreciation_account']} {p['ledger_accumulated']} vs {p['register_accumulated']}. "
            "The register does not post the cost - load it with an opening-balance journal or a bill coded to the asset account" for p in c["pairs"] if not p["reconciled"]]


# ------------------------------------------------------------------------------------------------ the registry --
def _doc_columns(role, amount_label):
    tax_ex, acct_ex = ("OUTPUT", "200") if role == "customer" else ("INPUT", "453")
    return [
        Col("number", "Document number. Lines with the same number form one document. Leave blank to get the next number (then a row with the contact and date starts a new document)", example="INV-0001"),
        Col("contact", f"The {role}'s name (as in your {role} list)", True, "Acme Pty Ltd" if role == "customer" else "Office Supplies Co", aliases=(role, "contact_name", "name", "party")),
        Col("issue_date", "Issue date", True, "2026-08-14", aliases=("date", "issued", "invoice_date", "bill_date", "order_date", "quote_date", "document_date", "date_raised")),
        Col("due_date", "Due date (quotes: expiry). Blank = the contact's payment terms", False, "2026-09-13", aliases=("due", "expiry_date", "expiry", "valid_until")),
        Col("reference", "Your reference / PO number - for bills the SUPPLIER's own invoice number (duplicate protection)", False, "PO-88123", aliases=("ref", "supplier_invoice", "supplier_invoice_number")),
        Col("amounts_are", "exclusive, inclusive or no_tax (default: the option you choose when importing)", False, "exclusive", aliases=("tax_treatment", "tax_type", "amounts")),
        Col("status", "draft or approved (approved posts to the ledger). Blank = the option you choose when importing", False, "approved"),
        Col("line_description", "Line description", True, "Consulting - August", aliases=("description", "item_description", "item", "details")),
        Col("qty", "Quantity (default 1)", False, "1", aliases=("quantity",)),
        Col("unit_price", amount_label, True, "1200.00", aliases=("unit_amount", "price", "unit_cost")),
        Col("discount_pct", "Discount % (0-100)", False, "0", aliases=("discount", "disc")),
        Col("account", "Account code or name for the line (blank = the contact's / organisation's default)", False, acct_ex, aliases=("account_code", "gl_account", "line_account")),
        Col("tax_code", "Tax code for the line, e.g. OUTPUT / INPUT / EXEMPTOUTPUT (blank = the account's default)", False, tax_ex, aliases=("tax", "gst", "tax_type_code")),
        Col("notes", "Notes", False, ""), Col("terms", "Terms shown on the document", False, ""),
    ]


_DOC_HEADER = ("contact", "issue_date", "due_date", "reference", "amounts_are", "status")
_DOC_LINE = ("line_description", "qty", "unit_price", "discount_pct", "account", "tax_code")
_DOC_MODE_OPTIONS = (dict(name="mode", label="Import as", choices=[["post", "Approved (posts to the ledger)"], ["draft", "Drafts for review"]], default="post",
                          help="Used for rows with no status column value"),
                     dict(name="amounts_are", label="Amounts are", choices=[["exclusive", "Tax exclusive"], ["inclusive", "Tax inclusive (GST included)"], ["no_tax", "No GST"]],
                          default="exclusive", help="Used when the file has no amounts_are column"))


def _doc_spec(entity, title, description, role, extra_cols=(), notes=(), template=None, options=_DOC_MODE_OPTIONS, amount_label="Unit price (per the document's 'amounts are' setting)"):
    return Spec(entity, title, description, _doc_columns(role, amount_label) + list(extra_cols), _h_doc(entity), group_col="number",
                start_cols=("contact", "issue_date"), header_cols=_DOC_HEADER, line_cols=_DOC_LINE, notes=notes, template=template or [], options=options)


_CREDIT_EXTRA = [Col("apply_to", "Optional: invoice/bill number to apply this credit to straight away", False, ""), Col("apply_amount", "Amount to apply (default: as much as possible)", False, "")]

SPECS = {}


def _reg(s):
    SPECS[s.key] = s


_CONTACT_COLS = [
    Col("name", "Name (existing names are updated, not duplicated)", True, "Acme Pty Ltd", aliases=("contact_name", "company", "customer", "supplier", "customer_name", "supplier_name")),
    Col("email", "Email", False, "accounts@acme.com.au", aliases=("email_address",)),
    Col("phone", "Phone", False, "02 9000 0000", aliases=("telephone", "mobile")),
    Col("abn", "ABN - must pass the ATO checksum", False, "51 824 753 556", aliases=("tax_number",)),
    Col("address", "Address", False, "1 George St, Sydney NSW 2000", aliases=("postal_address", "street_address")),
    Col("terms_days", "Payment terms in days", False, "14", aliases=("terms", "payment_terms", "payment_terms_days")),
    Col("credit_limit", "Credit limit", False, "20000", aliases=("creditlimit",)),
    Col("default_account", "Default account code for this contact's document lines", False, "200", aliases=("default_account_code",)),
    Col("default_tax_code", "Default tax code", False, "OUTPUT", aliases=("default_tax",)),
    Col("notes", "Notes", False, ""), Col("active", "yes / no (no = archived)", False, "yes", aliases=("is_active",)),
]
_reg(Spec("customers", "Customers", "People and businesses you sell to.", _CONTACT_COLS, _h_contact("customer"),
          notes=["Existing names are updated; nothing is duplicated.", "ABNs must pass the ATO checksum or the row is rejected."]))
_reg(Spec("suppliers", "Suppliers", "Businesses you buy from.", _CONTACT_COLS, _h_contact("supplier"),
          notes=["Existing names are updated; nothing is duplicated.", "ABNs must pass the ATO checksum or the row is rejected."]))
_reg(_doc_spec("invoices", "Sales invoices", "Tax invoices. Approved invoices post Dr Accounts Receivable, Cr Revenue, Cr GST, dated the issue date.", "customer",
               notes=["One row per line. Repeat the invoice number on each line (other columns only need to be filled on the first line).",
                      "Customers that do not exist yet are created; load your customers first to avoid typos creating new ones.",
                      "Record money received with the Receipts import."]))
_reg(_doc_spec("quotes", "Quotes", "Quotes have no ledger effect. Status can be draft, sent, accepted or declined.", "customer",
               notes=["Use the 'Convert to Invoice' button on an accepted quote to turn it into an invoice."],
               options=(dict(name="amounts_are", label="Amounts are", choices=[["exclusive", "Tax exclusive"], ["inclusive", "Tax inclusive (GST included)"], ["no_tax", "No GST"]],
                             default="exclusive", help="Used when the file has no amounts_are column"),)))
_reg(_doc_spec("credit_notes", "Credit notes", "Adjustment notes that reduce what a customer owes. Approved credit notes post the reverse of an invoice.", "customer", extra_cols=_CREDIT_EXTRA,
               notes=["Set apply_to to an invoice number to apply the credit straight away."]))
_reg(_doc_spec("purchase_orders", "Purchase orders", "Orders placed with suppliers. No ledger effect until converted to a bill.", "supplier",
               notes=["Approved purchase orders can be converted to bills with the 'Convert to Bill' button."],
               options=(dict(name="mode", label="Import as", choices=[["post", "Approved"], ["draft", "Drafts for review"]], default="post", help="Used for rows with no status"),
                        dict(name="amounts_are", label="Amounts are", choices=[["exclusive", "Tax exclusive"], ["inclusive", "Tax inclusive (GST included)"], ["no_tax", "No GST"]],
                            default="exclusive", help="Used when the file has no amounts_are column"))))
_reg(_doc_spec("bills", "Bills", "Supplier invoices. Approved bills post Dr Expense/COGS, Dr GST, Cr Accounts Payable.", "supplier",
               notes=["Put the supplier's own invoice number in `reference`: the same supplier + reference cannot be loaded twice (duplicate-bill protection).",
                      "Record money paid with the Supplier payments import."]))
_reg(_doc_spec("supplier_credits", "Supplier credits", "Credit notes received from suppliers.", "supplier", extra_cols=_CREDIT_EXTRA,
               notes=["Set apply_to to a bill number to apply the credit straight away."]))


def _pay_cols(role, main):
    return [
        Col("payment_ref", "Optional. Rows sharing a payment_ref are ONE payment split across several documents", False, "RCPT-1001", aliases=("payment", "receipt_no", "batch")),
        Col("date", "Payment date", True, "2026-09-05", aliases=("payment_date", "received", "paid")),
        Col("contact", f"The {role}'s name", True, "Acme Pty Ltd", aliases=(role, "contact_name", "name", "party")),
        Col("bank_account", "Bank account code or name (blank only if you have exactly one)", False, "090", aliases=("bank", "account", "deposit_to", "paid_from")),
        Col("document", f"{main.title()} number this row pays. Blank = unallocated (kept as a credit on the account)", False, "INV-0001", aliases=(main, f"{main}_number", "invoice_number", "bill_number", "document_number")),
        Col("amount", "Amount applied by this row", True, "1320.00", aliases=("allocated", "applied")),
        Col("reference", "Reference shown on the payment", False, "EFT 5531", aliases=("ref", "memo", "narration")),
    ]


_reg(Spec("receipts", "Receipts (money received from customers)", "Customer payments, allocated to invoices. Posts Dr Bank, Cr Accounts Receivable.",
          _pay_cols("customer", "invoice"), _h_payment("receipts"), group_col="payment_ref", start_cols=("date", "contact"), header_cols=("date", "contact", "bank_account"),
          line_cols=("document", "amount"),
          notes=["Invoices must already be loaded and approved; a receipt cannot exceed what is still owing on an invoice or pre-date it.",
                 "Rows with no invoice number become an unallocated payment (a credit on the customer's account)."]))
_reg(Spec("supplier_payments", "Supplier payments (money paid to suppliers)", "Payments to suppliers, allocated to bills. Posts Dr Accounts Payable, Cr Bank.",
          _pay_cols("supplier", "bill"), _h_payment("supplier_payments"), group_col="payment_ref", start_cols=("date", "contact"), header_cols=("date", "contact", "bank_account"),
          line_cols=("document", "amount"),
          notes=["Bills must already be loaded and approved; a payment cannot exceed what is still owing on a bill or pre-date it."]))

_reg(Spec("expense_claims", "Expense claims", "Employee expense claims: one row per receipt / mileage item.", [
    Col("claim", "Claim reference. Rows with the same value form one claim (the system numbers claims EXP-0001...)", False, "CLM-001", aliases=("claim_no", "claim_number", "claim_ref")),
    Col("title", "Claim title", False, "Sydney client visit", aliases=("claim_title",)),
    Col("claimant", "Employee name (recorded as text)", False, "Sam Lee", aliases=("employee", "claimant_name", "staff")),
    Col("status", "draft, submitted, approved, paid or rejected. Claims are advanced through the normal workflow (Owner/Admin only for approved/paid)", False, "approved"),
    Col("date", "Item date", True, "2026-08-14", aliases=("item_date", "expense_date")),
    Col("merchant", "Merchant / payee", False, "Qantas", aliases=("vendor", "payee", "supplier")),
    Col("description", "What it was for", True, "Flight SYD-MEL", aliases=("details", "item_description")),
    Col("account", "Expense account code or name", True, "493", aliases=("account_code", "gl_account")),
    Col("tax_code", "Tax code (blank = the account's default)", False, "INPUT", aliases=("tax", "gst")),
    Col("amount", "Amount paid, GST INCLUSIVE (receipts)", False, "72.50", aliases=("gross", "total")),
    Col("kind", "receipt (default) or mileage", False, "receipt", aliases=("type", "item_type")),
    Col("km", "Kilometres (mileage items)", False, ""), Col("rate_per_km", "Cents-per-km rate in dollars (blank = your books setting)", False, "0.88", aliases=("rate",)),
    Col("approve_date", "Ledger posting date when approving (blank = the last item date)", False, "", aliases=("approved_date",)),
    Col("paid_date", "Reimbursement date (required for paid)", False, "2026-09-10", aliases=("reimbursed_date", "payment_date")),
    Col("bank_account", "Bank account the reimbursement is paid from (paid claims)", False, "090", aliases=("bank",)),
    Col("reject_reason", "Reason (rejected claims)", False, ""), Col("reference", "Reimbursement reference", False, ""),
], _h_claim, group_col="claim", start_cols=("title", "claimant"), header_cols=("title", "claimant", "status", "paid_date", "bank_account"),
     line_cols=("description", "amount", "account", "km"),
     notes=["Submitting a claim enforces the ATO rule: a GST-bearing receipt over $82.50 needs the tax invoice attached first, so import those as draft and attach the receipt in the app.",
            "Approving your own claim is only allowed for an Owner/Admin (segregation of duties). Import as draft to hand the claims to an approver.",
            "Mileage items need km and either rate_per_km or a mileage rate in Books settings."]))

_reg(Spec("inventory_items", "Inventory items", "Stock items with optional opening stock (weighted-average cost).", [
    Col("sku", "Unique stock code", True, "WID-001", aliases=("code", "item_code", "product_code")),
    Col("name", "Item name", True, "Widget - standard", aliases=("item_name", "product", "item")),
    Col("description", "Description", False, ""),
    Col("inventory_account", "Inventory (asset) account. Blank = 630 Inventory", False, "630", aliases=("asset_account",)),
    Col("cogs_account", "Cost of goods sold account. Blank = 310", False, "310", aliases=("cogs",)),
    Col("sales_account", "Revenue account used when selling the item", False, "201", aliases=("revenue_account", "income_account")),
    Col("purchase_tax_code", "Tax code when buying", False, "INPUT"), Col("sales_tax_code", "Tax code when selling", False, "OUTPUT"),
    Col("sale_price", "Selling price (ex GST)", False, "49.00", aliases=("price", "unit_price")),
    Col("opening_qty", "Opening quantity on hand", False, "100", aliases=("opening_quantity", "quantity", "qty")),
    Col("opening_unit_cost", "Opening cost per unit (ex GST)", False, "22.50", aliases=("unit_cost", "cost")),
    Col("opening_date", "Date the opening stock is brought in", False, "2025-07-01"),
    Col("opening_credit_account", "Account credited with the opening stock value (e.g. 960 Retained Earnings)", False, "960", aliases=("credit_account", "opening_account")),
], _h_item, post_check=_inventory_check,
     notes=["Opening stock posts Dr Inventory, Cr the account you name - make sure you are not also loading the same stock in an opening-balance journal.",
            "An existing SKU is rejected; use stock movements to change quantities."]))
_reg(Spec("stock_movements", "Stock movements", "Purchases, sales (at average cost) and stocktake adjustments for existing items.", [
    Col("date", "Movement date", True, "2026-08-01"), Col("sku", "Stock code of an existing item", True, "WID-001", aliases=("code", "item", "item_code")),
    Col("kind", "buy, sell, adjustment or opening", True, "buy", aliases=("type", "movement")),
    Col("quantity", "Quantity moved (buy / sell / opening)", False, "50", aliases=("qty",)), Col("unit_cost", "Cost per unit (buy / opening)", False, "23.10", aliases=("cost",)),
    Col("counted_quantity", "Quantity actually counted (adjustment)", False, "", aliases=("counted", "stocktake_qty")),
    Col("account", "buy: account credited (e.g. bank 090). sell: account debited (blank = COGS). adjustment: variance account (blank = COGS)", False, "090", aliases=("credit_account", "debit_account")),
    Col("reference", "Reference", False, "PO-0004"), Col("note", "Note", False, ""),
], _h_movement, post_check=_inventory_check, sort_key=lambda row: _sort_date(row[1].get("date")),
     notes=["Rows are applied in date order (then file order) because the average cost depends on the sequence.",
            "A sell cannot exceed the quantity on hand. A sell posts only cost of goods sold - raise the sales invoice separately."]))

_reg(Spec("fixed_assets", "Fixed assets", "Asset register with straight-line or diminishing-value depreciation, and optional disposal.", [
    Col("number", "Asset number (blank = FA-0001...)", False, "FA-0001", aliases=("asset_number", "asset_no")),
    Col("name", "Asset name", True, "MacBook Pro 16", aliases=("asset", "asset_name", "description")),
    Col("category", "Label only: office_equipment, computer_equipment, motor_vehicle, other", False, "computer_equipment"),
    Col("asset_account", "Asset cost account code (e.g. 720 Computer Equipment)", True, "720", aliases=("cost_account",)),
    Col("depreciation_account", "Accumulated depreciation account code (e.g. 721)", True, "721", aliases=("accumulated_depreciation_account", "accum_dep_account")),
    Col("expense_account", "Depreciation expense account (blank = 416)", False, "416", aliases=("depreciation_expense_account",)),
    Col("purchase_date", "Purchase / in-service date", True, "2025-07-15", aliases=("date", "acquired")),
    Col("cost", "Cost (ex GST)", True, "3200.00", aliases=("purchase_price", "amount")),
    Col("residual_value", "Residual (salvage) value", False, "0", aliases=("salvage_value",)),
    Col("method", "straight_line or diminishing_value", False, "straight_line", aliases=("depreciation_method",)),
    Col("effective_life_months", "Effective life in months (straight line)", False, "36", aliases=("life_months", "useful_life_months")),
    Col("dv_rate_pct", "Annual % rate (diminishing value)", False, "", aliases=("rate_pct", "dv_rate")),
    Col("opening_accumulated_depreciation", "Depreciation already taken before this register", False, "0", aliases=("opening_depreciation", "accumulated_depreciation")),
    Col("notes", "Notes", False, ""),
    Col("disposal_date", "Optional: date the asset was sold / scrapped (posts the disposal)", False, "", aliases=("disposed",)),
    Col("disposal_proceeds", "Sale proceeds (0 if scrapped)", False, ""), Col("disposal_bank_account", "Bank account the proceeds were received in", False, ""),
], _h_asset, post_check=_asset_check,
     notes=["IMPORTANT: the register does not post the asset's cost. The cost (and any opening accumulated depreciation) must already be in the ledger - load an opening-balance journal, or a bill coded to the asset account - otherwise the Sub-ledger Control Check will show a difference.",
            "After loading, use 'Run depreciation to today' on the Fixed Assets page to post depreciation."]))


# ------------------------------------------------------------------------------------------------ templates --
_DOC_EXAMPLE_NO = {"invoices": "INV-0001", "quotes": "QU-0001", "credit_notes": "CN-0001", "purchase_orders": "PO-0001", "bills": "BILL-0001", "supplier_credits": "SC-0001"}


def _tmpl_rows(key):
    s = SPECS[key]
    names = [c.name for c in s.columns]
    ex = {c.name: c.example for c in s.columns}
    rows = [names]
    if key in DOC_META:
        no = _DOC_EXAMPLE_NO[key]
        nxt = no[:-1] + "2"
        first = dict(ex, number=no)
        cont = dict(number=no, line_description="Second line on the same document", qty="2", unit_price="150.00", account=ex.get("account", ""), tax_code=ex.get("tax_code", ""))
        other = dict(ex, number=nxt, issue_date="2026-08-20", due_date="2026-09-19", reference="", line_description="Another document", unit_price="480.00")
        for r in (first, cont, other):
            rows.append([r.get(n, "") for n in names])
    else:
        rows.append([ex.get(n, "") for n in names])
    return rows


def template_csv(key):
    rows = _tmpl_rows(key)
    role = {"customer": "customer", "supplier": "supplier"}.get(DOC_META.get(key, ("", ""))[1] or ("customer" if key == "receipts" else "supplier" if key == "supplier_payments" else ""))
    if role and "contact" in rows[0]:
        rows[0] = [role if c == "contact" else c for c in rows[0]]        # the friendlier header; `contact` is accepted too
    buf = io.StringIO()
    csv.writer(buf, lineterminator="\r\n").writerows(rows)
    return buf.getvalue()


def catalogue():
    return [s.info() for s in SPECS.values()]


# ------------------------------------------------------------------------------------------------ the runner --
def run_import(db, org, ctx, entity, raw, *, dry_run=True, options=None):
    """Validate (and, unless dry_run, stage) an import. The CALLER commits when `error` is empty and dry_run is False, and rolls back otherwise.
    -> dict(entity, dry_run, count, valid, invalid, saved, items[], warnings[], error, total)"""
    spec = SPECS.get(entity)
    if spec is None:
        raise BooksError(f"Unknown import '{entity}'. Available: {', '.join(SPECS)}", 404)
    if isinstance(raw, (bytes, bytearray)) and len(raw) > MAX_BYTES:
        raise BooksError("File too large (5 MB max). Split it and import it in parts", 413)
    grid = _grid(_decode(raw))
    if not grid:
        raise BooksError("The file is empty")
    if len(grid) == 1:
        raise BooksError("The file has a header row but no data rows")
    opts = dict(options or {})
    result = dict(entity=entity, dry_run=dry_run, count=0, valid=0, invalid=0, saved=0, items=[], warnings=[], error=None, total="0.00")
    recs = _records(spec, grid, result)
    if spec.sort_key:
        recs.sort(key=lambda rc: spec.sort_key(rc.rows[0]))
    result["count"] = len(recs)
    total = Z
    for rec in recs:
        item = dict(row=rec.row, key=rec.key, label=rec.key or f"row {rec.row}", detail="", amount=None, errors=[], warnings=[], action="create")
        try:
            if rec.conflicts:
                raise BooksError("; ".join(rec.conflicts).capitalize())
            with db.begin_nested():
                info = spec.handler(db, org, ctx, rec, opts)
            item.update(label=info["label"], detail=info["detail"], amount=str(info["amount"]) if info.get("amount") is not None else None,
                        action=info.get("action", "create"), warnings=list(info.get("warnings") or []))
            if info.get("amount") is not None:
                total += Decimal(str(info["amount"]))
        except (BooksError, L.LedgerError, ValueError, InvalidOperation, KeyError) as e:
            item["errors"].append(str(e.args[0]) if isinstance(e, KeyError) else str(e))
        except SQLAlchemyError as e:
            item["errors"].append("The database rejected this record: " + str(getattr(e, "orig", e)).splitlines()[0][:200])
        result["items"].append(item)
    result["invalid"] = sum(1 for i in result["items"] if i["errors"])
    result["valid"] = result["count"] - result["invalid"]
    result["total"] = str(total)
    if not result["invalid"] and spec.post_check:
        try:
            db.flush()
            result["warnings"] += spec.post_check(db, org)
        except (BooksError, L.LedgerError, SQLAlchemyError):
            pass
    if result["invalid"]:
        result["error"] = f"{result['invalid']} of {result['count']} record(s) have problems; nothing was imported. Fix the file and try again."
        db.rollback()
    elif dry_run:
        db.rollback()
    else:
        db.flush()
        result["saved"] = result["count"]
    result["items_truncated"] = max(0, len(result["items"]) - MAX_ITEMS_RETURNED)
    bad = [i for i in result["items"] if i["errors"]]
    ok = [i for i in result["items"] if not i["errors"]]
    result["items"] = (bad + ok)[:MAX_ITEMS_RETURNED]          # problems first, so they are never cut off
    return result
