"""
Inventory service - weighted-average costing, exactly as Xero and MYOB compute it:

  buy         quantity_on_hand += qty; value_on_hand += qty * unit_cost; average_cost = value / qty
              Dr Inventory, Cr (the account given - a bill, a bank line, or a suspense/clearing account)
  sell        COGS = qty * current average_cost (rounded once, at the point of sale); value_on_hand
              and quantity_on_hand fall by that quantity and that exact COGS amount (never re-derived
              from the new average, so a sale can never leave the average cost of what remains skewed)
              Dr Cost of Goods Sold, Cr Inventory
  adjustment  a stocktake correction to a COUNTED quantity; the variance is costed at the current
              average (increases) or drawn down at the current average (decreases, same as a sale)
              posts the variance to Inventory against the item's COGS account
  opening     like a buy, but dated and reported separately (bringing existing stock into the ledger
              for the first time)

Every movement keeps quantity_on_hand and value_on_hand exactly in step, so the item's own average
cost is always value_on_hand / quantity_on_hand - never drifting the way an independently-rounded
"cost per unit" field would.
"""
from datetime import date
from decimal import ROUND_HALF_UP, Decimal

from sqlalchemy import func

from accfino.core import models as m
from accfino.modules.accounting.models import ledger as lm
from accfino.modules.accounting.books.common import BooksError, as_date, get_account, get_tax, money
from accfino.modules.accounting.inventory import models as inv
from accfino.modules.accounting.ledger import service as L

Z = Decimal("0.00")
QTYQ = Decimal("0.0001")
COSTQ = Decimal("0.000001")


def qty(x) -> Decimal:
    try:
        return Decimal(str(x)).quantize(QTYQ, rounding=ROUND_HALF_UP)
    except Exception:
        raise BooksError(f"'{x}' is not a valid quantity")


def unit_cost_of(value: Decimal, quantity: Decimal) -> Decimal:
    if quantity == 0:
        return Z
    return (value / quantity).quantize(COSTQ, rounding=ROUND_HALF_UP)


def item_dict(it):
    return dict(id=it.id, sku=it.sku, name=it.name, description=it.description, inventory_account_id=it.inventory_account_id,
                inventory_account=f"{it.inventory_account.code} {it.inventory_account.name}" if it.inventory_account else None,
                cogs_account_id=it.cogs_account_id, cogs_account=f"{it.cogs_account.code} {it.cogs_account.name}" if it.cogs_account else None,
                sales_account_id=it.sales_account_id, sale_price=str(it.sale_price) if it.sale_price is not None else None,
                quantity_on_hand=str(it.quantity_on_hand), average_cost=str(it.average_cost.quantize(Decimal("0.0001"))),
                value_on_hand=str(it.value_on_hand), is_active=it.is_active)


def movement_dict(mv):
    return dict(id=mv.id, item_id=mv.item_id, kind=mv.kind, date=mv.movement_date.isoformat(), quantity=str(mv.quantity),
                unit_cost=str(mv.unit_cost.quantize(Decimal("0.0001"))) if mv.unit_cost is not None else None, amount=str(mv.amount),
                quantity_after=str(mv.quantity_after), average_cost_after=str(mv.average_cost_after.quantize(Decimal("0.0001"))),
                reference=mv.reference, note=mv.note, journal_id=mv.journal_id)


def create_item(db, org, data: dict):
    sku = (data.get("sku") or "").strip()
    if not sku:
        raise BooksError("An item needs a SKU")
    if db.query(inv.StockItem.id).filter_by(org_id=org.id, sku=sku).first():
        raise BooksError(f"An item with SKU '{sku}' already exists", 409)
    if not (data.get("name") or "").strip():
        raise BooksError("An item needs a name")
    inv_acc = get_account(db, org, data.get("inventory_account") or _default(db, org, "inventory"), what="Inventory account")
    cogs_acc = get_account(db, org, data.get("cogs_account") or _default(db, org, "cogs"), what="Cost of goods sold account")
    sales_ref = data.get("sales_account")
    sales_acc = get_account(db, org, sales_ref, what="Sales account") if sales_ref else None
    ptax = get_tax(db, org, data["purchase_tax_code"]) if data.get("purchase_tax_code") else None
    stax = get_tax(db, org, data["sales_tax_code"]) if data.get("sales_tax_code") else None
    item = inv.StockItem(org_id=org.id, sku=sku, name=data["name"].strip(), description=data.get("description"),
                         inventory_account_id=inv_acc.id, cogs_account_id=cogs_acc.id, sales_account_id=sales_acc.id if sales_acc else None,
                         purchase_tax_code_id=ptax.id if ptax else None, sales_tax_code_id=stax.id if stax else None,
                         sale_price=money(data["sale_price"]) if data.get("sale_price") not in (None, "") else None)
    db.add(item)
    db.flush()
    return item


def _default(db, org, key):
    acc = db.query(lm.LedgerAccount).filter_by(org_id=org.id, system_key=key).first()
    if acc is None:
        raise BooksError(f"No default account found for '{key}'; pass the account explicitly", 422)
    return acc.code


def update_item(db, item, data: dict):
    if "name" in data and data["name"]:
        item.name = data["name"].strip()
    if "description" in data:
        item.description = data["description"]
    if "sale_price" in data:
        item.sale_price = money(data["sale_price"]) if data["sale_price"] not in (None, "") else None
    if "is_active" in data:
        item.is_active = bool(data["is_active"])
    db.flush()
    return item


def delete_item(db, item):
    if item.movements:
        raise BooksError("This item has movements posted against it; make it inactive instead of deleting it", 409)
    db.delete(item)
    db.flush()


# ---------------------------------------------------------------------------------------------- movements --
def _post(db, org, user_id, item, *, kind, mv_date, quantity, unit_cost, amount, reference, note, dr_account_id, cr_account_id, tax_code_id=None, tax_amount=None):
    lines = [{"account_id": dr_account_id, "debit": amount, "description": (note or kind.title())[:500]},
             {"account_id": cr_account_id, "credit": amount, "description": (note or kind.title())[:500]}]
    if tax_code_id and tax_amount:
        gst_acc = _system(db, org, "gst")
        # the tax portion rides on the non-inventory side of the entry (a buy's supplier/bank leg, or a sale's revenue leg)
        lines[1]["tax_code_id"] = tax_code_id
        lines[1]["tax_amount"] = tax_amount
        lines.append({"account_id": gst_acc.id, "debit": tax_amount if kind == "buy" else Z, "credit": tax_amount if kind != "buy" else Z,
                      "tax_code_id": tax_code_id, "description": f"GST - {note or kind}"[:500]})
    try:
        j = L.post_journal(db, org, journal_date=mv_date, lines=lines, narration=f"{kind.title()} - {item.sku} {item.name}"[:500],
                           source_type=f"inventory_{kind}", source_ref=f"item:{item.id}", created_by=user_id)
    except L.LedgerError as e:
        raise BooksError(str(e), 422)
    mv = inv.StockMovement(org_id=org.id, item_id=item.id, kind=kind, movement_date=mv_date, quantity=quantity, unit_cost=unit_cost,
                           amount=amount, quantity_after=item.quantity_on_hand, average_cost_after=item.average_cost, reference=reference,
                           note=note, journal_id=j.id, created_by=user_id)
    db.add(mv)
    db.flush()
    return mv


def _system(db, org, key):
    acc = db.query(lm.LedgerAccount).filter_by(org_id=org.id, system_key=key).first()
    if acc is None:
        raise BooksError(f"The organisation has no '{key}' system account", 500)
    return acc


def buy(db, org, user_id, item, *, mv_date, quantity, unit_cost, credit_account, reference=None, note=None, kind="buy"):
    q, uc = qty(quantity), money(unit_cost) if isinstance(unit_cost, str) else Decimal(str(unit_cost))
    if q <= 0:
        raise BooksError("Quantity must be greater than zero")
    if uc < 0:
        raise BooksError("Unit cost cannot be negative")
    amount = (q * uc).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    cr = get_account(db, org, credit_account, what="Credit account")
    if cr.id == item.inventory_account_id:
        raise BooksError("The credit account must be different from the item's inventory account")
    item.quantity_on_hand = qty(item.quantity_on_hand) + q
    item.value_on_hand = money(item.value_on_hand) + amount
    item.average_cost = unit_cost_of(item.value_on_hand, item.quantity_on_hand)
    return _post(db, org, user_id, item, kind=kind, mv_date=as_date(mv_date, "date"), quantity=q, unit_cost=uc, amount=amount,
                reference=reference, note=note, dr_account_id=item.inventory_account_id, cr_account_id=cr.id)


def sell(db, org, user_id, item, *, mv_date, quantity, debit_account=None, reference=None, note=None):
    q = qty(quantity)
    if q <= 0:
        raise BooksError("Quantity must be greater than zero")
    if q > item.quantity_on_hand:
        raise BooksError(f"Only {item.quantity_on_hand} units of {item.sku} are on hand")
    avg = item.average_cost
    cogs = (q * avg).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    debit_acc = get_account(db, org, debit_account, what="Debit account") if debit_account else item.cogs_account
    if q == qty(item.quantity_on_hand):
        cogs = money(item.value_on_hand)          # the last unit takes ALL the remaining value, so the ledger and the item both end at exactly zero (no stray cents)
    item.quantity_on_hand = qty(item.quantity_on_hand) - q
    item.value_on_hand = money(item.value_on_hand) - cogs
    if item.quantity_on_hand == 0:
        item.value_on_hand = Z                                  # guard against a stray fraction of a cent when the last unit leaves
    return _post(db, org, user_id, item, kind="sell", mv_date=as_date(mv_date, "date"), quantity=q, unit_cost=avg, amount=cogs,
                reference=reference, note=note, dr_account_id=debit_acc.id, cr_account_id=item.inventory_account_id)


def adjust(db, org, user_id, item, *, mv_date, counted_quantity, reference=None, note=None, adjustment_account=None):
    """Stocktake: set the quantity to what was actually counted. Backed out at the current average
    if lower (a shrinkage), added at the current average if higher (a found surplus)."""
    counted = qty(counted_quantity)
    if counted < 0:
        raise BooksError("Counted quantity cannot be negative")
    variance = counted - qty(item.quantity_on_hand)
    if variance == 0:
        raise BooksError("The counted quantity matches what is already on hand - nothing to adjust")
    adj_acc = get_account(db, org, adjustment_account, what="Adjustment account") if adjustment_account else item.cogs_account
    avg = item.average_cost if item.quantity_on_hand > 0 else Z
    amount = (abs(variance) * avg).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    if amount == 0 and variance != 0:
        raise BooksError("This item has no cost yet (nothing has ever been bought in) - adjust it with a 'buy' movement instead")
    if counted == 0 and variance < 0:
        amount = money(item.value_on_hand)        # writing off the last units removes all remaining value (see sell())
    item.quantity_on_hand = counted
    if variance > 0:
        item.value_on_hand = money(item.value_on_hand) + amount
        dr, cr = item.inventory_account_id, adj_acc.id
    else:
        item.value_on_hand = money(item.value_on_hand) - amount
        if item.quantity_on_hand == 0:
            item.value_on_hand = Z
        dr, cr = adj_acc.id, item.inventory_account_id
    item.average_cost = unit_cost_of(item.value_on_hand, item.quantity_on_hand) if item.quantity_on_hand else Z
    return _post(db, org, user_id, item, kind="adjustment", mv_date=as_date(mv_date, "date"), quantity=abs(variance), unit_cost=avg,
                amount=amount, reference=reference, note=note or f"Stocktake: {counted} counted", dr_account_id=dr, cr_account_id=cr)


def record_movement(db, org, user_id, item, data: dict):
    kind = data.get("kind")
    mv_date = data.get("date") or date.today()
    if kind in ("buy", "opening"):
        return buy(db, org, user_id, item, mv_date=mv_date, quantity=data["quantity"], unit_cost=data["unit_cost"],
                  credit_account=data.get("credit_account") or data.get("account"), reference=data.get("reference"), note=data.get("note"), kind=kind)
    if kind == "sell":
        return sell(db, org, user_id, item, mv_date=mv_date, quantity=data["quantity"], debit_account=data.get("debit_account") or data.get("account"),
                   reference=data.get("reference"), note=data.get("note"))
    if kind == "adjustment":
        return adjust(db, org, user_id, item, mv_date=mv_date, counted_quantity=data["counted_quantity"], reference=data.get("reference"),
                     note=data.get("note"), adjustment_account=data.get("account"))
    raise BooksError("kind must be buy, sell, adjustment or opening")


# ---------------------------------------------------------------------------------------------- reports --
def valuation_report(db, org):
    items = db.query(inv.StockItem).filter_by(org_id=org.id, is_active=True).order_by(inv.StockItem.sku).all()
    rows = [item_dict(i) for i in items]
    total = sum((Decimal(r["value_on_hand"]) for r in rows), Z)
    return dict(items=rows, total_value=str(total))


def control(db, org, as_at: date):
    """Sum of every item's value_on_hand vs the ledger balance of each Inventory account they use -
    the same pattern as the AR/AP/fixed-asset control checks elsewhere in Books & Accounting."""
    items = db.query(inv.StockItem).filter_by(org_id=org.id).all()
    by_account = {}
    for i in items:
        by_account.setdefault(i.inventory_account_id, Z)
        by_account[i.inventory_account_id] += money(i.value_on_hand)
    out, all_ok = [], True
    for acc_id, subledger_total in by_account.items():
        acc = db.get(lm.LedgerAccount, acc_id)
        ledger_balance = money(db.query(func.coalesce(func.sum(lm.JournalLine.debit - lm.JournalLine.credit), 0))
                              .join(lm.Journal, lm.Journal.id == lm.JournalLine.journal_id)
                              .filter(lm.JournalLine.org_id == org.id, lm.JournalLine.account_id == acc_id, lm.Journal.journal_date <= as_at).scalar())
        ok = ledger_balance == subledger_total
        all_ok = all_ok and ok
        out.append(dict(account=f"{acc.code} {acc.name}", subledger_total=str(subledger_total), ledger_balance=str(ledger_balance),
                        difference=str(ledger_balance - subledger_total), reconciled=ok))
    return dict(as_at=as_at.isoformat(), accounts=out, reconciled=all_ok)


def movements_report(db, org, item_id=None, date_from=None, date_to=None):
    q = db.query(inv.StockMovement).filter_by(org_id=org.id)
    if item_id:
        q = q.filter(inv.StockMovement.item_id == item_id)
    if date_from:
        q = q.filter(inv.StockMovement.movement_date >= date_from)
    if date_to:
        q = q.filter(inv.StockMovement.movement_date <= date_to)
    return [movement_dict(mv) for mv in q.order_by(inv.StockMovement.movement_date, inv.StockMovement.id)]
