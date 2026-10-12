"""Parcel (lot) engine. Pure functions over a list of transactions: no database, no rates, no I/O.

What it implements, and the Australian rule behind each point (ATO guidance on shares, funds, crypto):
  * Cost base of a parcel = price paid + brokerage/fees (brokerage on a purchase is NOT deductible: it is cost base).
  * Selling: the parcels sold are chosen by the method (FIFO default; LIFO / HIFO allowed but the user must be able to support them; SPECIFIC identification by naming the buy).
    Selling costs reduce the capital proceeds. A disposal is discount-eligible when held MORE than 12 months (disposal after the acquisition date plus 12 months).
  * Dividend reinvestment (DRP): the dividend is income AND its amount is the cost base of the new shares.
  * Bonus issue: not a dividend -> the original cost base is spread over original + bonus shares (bonus shares take the original acquisition date); a taxable bonus -> new parcel at the dividend amount.
  * Split / consolidation: units change, total cost base does not.
  * Return of capital and tax-deferred distribution amounts: reduce cost base; reduction beyond the cost base is a capital gain.
  * AMIT cost base net amount (from an AMMA statement): increases or decreases cost base. A decrease beyond cost base is a capital gain.
  * Staking / airdrop receipts (income in kind): income at the AUD value at receipt, which becomes the cost base of the new parcel.
  * Transfers between own accounts or wallets are NOT disposals: parcels keep their cost base and acquisition date.
  * Crypto swaps are modelled as a sell plus a buy (the service creates the pair).
Nothing is guessed: an oversold quantity is reported as a warning and produces no disposal row."""
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from typing import Dict, List, Optional, Tuple

from accfino.modules.investments.engine.money import ZERO, D, add_months, q2

ACQUIRE = {"buy", "drp", "income_in_kind"}
CORPORATE = {"split", "bonus", "return_of_capital", "cost_base_adjustment"}
# Order WITHIN a day: acquisitions, then a transfer OUT, then the matching transfer IN (an exchange withdrawal and the wallet deposit usually carry the same date, and the arrival needs the
# departure's parcels to carry their cost base), then corporate actions, then sales.
_PRIORITY = {**{t: 0 for t in ACQUIRE}, "transfer_out": 1, "transfer_in": 2, **{t: 3 for t in CORPORATE}, "sell": 4}


@dataclass
class Lot:
    id: int
    account_id: int
    security_id: int
    acquired: date
    qty: Decimal
    cost: Decimal                     # total cost base of the REMAINING units, AUD
    origin: str = "buy"

    @property
    def unit_cost(self) -> Decimal:
        return self.cost / self.qty if self.qty else ZERO


@dataclass
class Disposal:
    txn_id: int
    account_id: int
    security_id: int
    dispose_date: date
    acquire_date: date
    qty: Decimal
    proceeds_gross: Decimal
    selling_costs: Decimal
    cost_base: Decimal
    lot_id: int
    method: str

    @property
    def proceeds_net(self) -> Decimal:
        return self.proceeds_gross - self.selling_costs

    @property
    def gain(self) -> Decimal:
        return self.proceeds_net - self.cost_base

    @property
    def discount_eligible(self) -> bool:
        return self.dispose_date > add_months(self.acquire_date, 12)

    @property
    def days_held(self) -> int:
        return (self.dispose_date - self.acquire_date).days


@dataclass
class Income:
    txn_id: int
    account_id: int
    security_id: int
    date: date
    kind: str
    cash: Decimal = ZERO
    franked: Decimal = ZERO
    unfranked: Decimal = ZERO
    franking_credits: Decimal = ZERO
    foreign_income: Decimal = ZERO
    foreign_tax: Decimal = ZERO
    cg_discount_part: Decimal = ZERO
    cg_other_part: Decimal = ZERO
    tax_deferred: Decimal = ZERO
    withholding: Decimal = ZERO
    value_in_kind: Decimal = ZERO


@dataclass
class Result:
    lots: List[Lot] = field(default_factory=list)
    disposals: List[Disposal] = field(default_factory=list)
    income: List[Income] = field(default_factory=list)
    fees: List[Tuple[int, int, int, date, Decimal]] = field(default_factory=list)       # standalone fee transactions: (txn, account, security, date, amount)
    excess_gains: List[dict] = field(default_factory=list)                              # cost base reduced below zero: the excess is a capital gain
    warnings: List[dict] = field(default_factory=list)


def _g(t, k, default=None):
    return t[k] if isinstance(t, dict) else getattr(t, k, default)


def _warn(res: Result, txn, kind: str, msg: str):
    res.warnings.append(dict(txn_id=_g(txn, "id"), kind=kind, message=msg))


def _reduce(lots: List[Lot], amount: Decimal) -> Decimal:
    """Reduce total cost base across the lots pro rata by units. Returns the excess that could not be absorbed (a capital gain)."""
    total = sum((l.cost for l in lots), ZERO)
    if amount <= 0 or not lots:
        return ZERO
    if amount >= total:
        for l in lots:
            l.cost = ZERO
        return amount - total
    left = amount
    for i, l in enumerate(lots):
        part = left if i == len(lots) - 1 else amount * l.cost / total
        l.cost -= part
        left -= part
    return ZERO


def _raise(lots: List[Lot], amount: Decimal):
    total_q = sum((l.qty for l in lots), ZERO)
    if amount <= 0 or not total_q:
        return
    left = amount
    for i, l in enumerate(lots):
        part = left if i == len(lots) - 1 else amount * l.qty / total_q
        l.cost += part
        left -= part


def _order(lots: List[Lot], method: str) -> List[Lot]:
    if method == "lifo":
        return sorted(lots, key=lambda l: (l.acquired, l.id), reverse=True)
    if method == "hifo":
        return sorted(lots, key=lambda l: (-l.unit_cost, l.acquired, l.id))
    return sorted(lots, key=lambda l: (l.acquired, l.id))


def replay(txns, method: str = "fifo", as_at: Optional[date] = None) -> Result:
    """Replay the transactions in date order. `txns` are dicts or objects with: id, account_id, security_id, trade_date, txn_type, quantity, price, amount, fees, franked, unfranked,
    franking_credits, foreign_income, foreign_tax_paid, cg_discount_part, cg_other_part, tax_deferred, cost_base_adj, withholding_tax, lot_ref, reference, voided."""
    res = Result()
    live = [t for t in txns if not _g(t, "voided", False) and (as_at is None or _g(t, "trade_date") <= as_at)]
    live.sort(key=lambda t: (_g(t, "trade_date"), _PRIORITY.get(_g(t, "txn_type"), 3), _g(t, "id") or 0))
    book: Dict[Tuple[int, int], List[Lot]] = {}
    pool: Dict[str, List[Lot]] = {}                                  # parcels in transit between accounts, keyed by the transfer reference
    for t in live:
        typ, acc, sec, day = _g(t, "txn_type"), _g(t, "account_id"), _g(t, "security_id"), _g(t, "trade_date")
        qty, amount, fees, tid = D(_g(t, "quantity")), D(_g(t, "amount")), D(_g(t, "fees")), _g(t, "id")
        lots = book.setdefault((acc, sec), [])
        if typ == "buy":
            if qty <= 0:
                _warn(res, t, "bad_quantity", "A purchase needs a quantity greater than zero"); continue
            lots.append(Lot(tid, acc, sec, day, qty, amount + fees, "buy"))
        elif typ == "drp":
            if qty <= 0:
                _warn(res, t, "bad_quantity", "A dividend reinvestment needs the number of units issued"); continue
            res.income.append(Income(tid, acc, sec, day, "drp", cash=amount, franked=D(_g(t, "franked")), unfranked=D(_g(t, "unfranked")), franking_credits=D(_g(t, "franking_credits")), withholding=D(_g(t, "withholding_tax"))))
            lots.append(Lot(tid, acc, sec, day, qty, amount + fees, "drp"))
        elif typ == "income_in_kind":
            if qty <= 0:
                _warn(res, t, "bad_quantity", "Staking / airdrop income needs the number of units received"); continue
            res.income.append(Income(tid, acc, sec, day, "income_in_kind", value_in_kind=amount))
            lots.append(Lot(tid, acc, sec, day, qty, amount, "income"))
        elif typ == "split":
            num, den = qty, D(_g(t, "price"))
            if num <= 0 or den <= 0:
                _warn(res, t, "bad_ratio", "A split needs both numbers of the ratio (new units for old units)"); continue
            for l in lots:
                l.qty = l.qty * num / den
        elif typ == "bonus":
            if qty <= 0:
                _warn(res, t, "bad_quantity", "A bonus issue needs the number of bonus units"); continue
            if amount > 0:                                           # assessable bonus (taxed as a dividend): a new parcel at the dividend amount
                lots.append(Lot(tid, acc, sec, day, qty, amount + fees, "bonus"))
            else:                                                    # tax-free bonus: spread the original cost base across original + bonus units
                held = sum((l.qty for l in lots), ZERO)
                if held <= 0:
                    _warn(res, t, "no_holding", "A bonus issue arrived with nothing held to attach it to"); continue
                for l in list(lots):
                    share = qty * l.qty / held
                    moved = l.cost * share / (l.qty + share) if (l.qty + share) else ZERO
                    l.cost -= moved
                    lots.append(Lot(tid, acc, sec, l.acquired, share, moved, "bonus"))
        elif typ == "return_of_capital":
            ex = _reduce([l for l in lots if l.qty > 0], amount)
            if ex > 0:
                res.excess_gains.append(dict(txn_id=tid, account_id=acc, security_id=sec, date=day, amount=ex, reason="Return of capital exceeded the cost base"))
        elif typ == "cost_base_adjustment":
            adj = D(_g(t, "cost_base_adj"))
            if adj >= 0:
                _raise(lots, adj)
            else:
                ex = _reduce(lots, -adj)
                if ex > 0:
                    res.excess_gains.append(dict(txn_id=tid, account_id=acc, security_id=sec, date=day, amount=ex, reason="AMIT cost base decrease exceeded the cost base"))
        elif typ in ("dividend", "distribution", "interest"):
            inc = Income(tid, acc, sec, day, typ, cash=amount, franked=D(_g(t, "franked")), unfranked=D(_g(t, "unfranked")), franking_credits=D(_g(t, "franking_credits")), foreign_income=D(_g(t, "foreign_income")),
                         foreign_tax=D(_g(t, "foreign_tax_paid")), cg_discount_part=D(_g(t, "cg_discount_part")), cg_other_part=D(_g(t, "cg_other_part")), tax_deferred=D(_g(t, "tax_deferred")), withholding=D(_g(t, "withholding_tax")))
            res.income.append(inc)
            if typ == "distribution":
                if inc.tax_deferred > 0:
                    ex = _reduce([l for l in lots if l.qty > 0], inc.tax_deferred)
                    if ex > 0:
                        res.excess_gains.append(dict(txn_id=tid, account_id=acc, security_id=sec, date=day, amount=ex, reason="Tax-deferred amount exceeded the cost base"))
                adj = D(_g(t, "cost_base_adj"))
                if adj > 0:
                    _raise(lots, adj)
                elif adj < 0:
                    ex = _reduce(lots, -adj)
                    if ex > 0:
                        res.excess_gains.append(dict(txn_id=tid, account_id=acc, security_id=sec, date=day, amount=ex, reason="AMIT cost base decrease exceeded the cost base"))
        elif typ == "fee":
            res.fees.append((tid, acc, sec, day, amount + fees))
        elif typ == "transfer_out":
            ref = _g(t, "reference") or ""
            taken, left = [], qty
            for l in _order(lots, "fifo"):
                if left <= 0:
                    break
                use = min(l.qty, left)
                part = l.cost * use / l.qty
                taken.append(Lot(l.id, acc, sec, l.acquired, use, part, l.origin))
                l.cost -= part
                l.qty -= use
                left -= use
            if left > 0:
                _warn(res, t, "oversold", f"Transfer out of {qty} units but only {qty - left} held")
            if not ref:
                _warn(res, t, "no_reference", "A transfer needs a reference shared by its two halves, otherwise cost base cannot be carried across")
            pool.setdefault(f"{sec}:{ref}", []).extend(taken)
        elif typ == "transfer_in":
            ref = _g(t, "reference") or ""
            arriving = pool.pop(f"{sec}:{ref}", None) if ref else None
            if arriving:
                got = sum((l.qty for l in arriving), ZERO)
                if abs(got - qty) > D("0.00000001"):
                    _warn(res, t, "transfer_mismatch", f"Transferred out {got} units but {qty} arrived: cost base carried for the units that left")
                for l in arriving:
                    lots.append(Lot(l.id, acc, sec, l.acquired, l.qty, l.cost, l.origin))
            else:
                _warn(res, t, "unmatched_transfer", "No matching transfer out: treated as an acquisition at the amount given (check the original cost base)")
                lots.append(Lot(tid, acc, sec, day, qty, amount + fees, "transfer"))
        elif typ == "sell":
            if qty <= 0:
                _warn(res, t, "bad_quantity", "A sale needs a quantity greater than zero"); continue
            ref = _g(t, "lot_ref")
            remaining = qty
            pieces: List[Tuple[Lot, Decimal, Decimal, str]] = []
            if ref is not None:
                for l in lots:
                    if l.id == ref and l.qty > 0:
                        use = min(l.qty, remaining)
                        pieces.append((l, use, l.cost * use / l.qty, "specific"))
                        remaining -= use
                        break
                else:
                    _warn(res, t, "lot_not_found", f"The parcel identified (purchase {ref}) has nothing left: the rest is matched by {method.upper()}")
            if ref is not None and pieces:
                l0, u0, c0, m0 = pieces[0]
                l0.cost -= c0
                l0.qty -= u0
            for l in _order([x for x in lots if x.qty > 0], method):
                if remaining <= 0:
                    break
                use = min(l.qty, remaining)
                pieces.append((l, use, l.cost * use / l.qty, method))
                l.cost -= l.cost * use / l.qty
                l.qty -= use
                remaining -= use
            if remaining > 0:
                _warn(res, t, "oversold", f"Sold {qty} but only {qty - remaining} held at that date: add the missing purchase or the transfer in")
            matched = qty - remaining
            if matched <= 0:
                continue
            gross_total, fee_total = amount * matched / qty, fees * matched / qty
            given_g = given_f = ZERO
            for i, (l, use, part_cost, m) in enumerate(pieces):
                last = i == len(pieces) - 1
                g = gross_total - given_g if last else q2(gross_total * use / matched)
                f = fee_total - given_f if last else q2(fee_total * use / matched)
                given_g, given_f = given_g + g, given_f + f
                res.disposals.append(Disposal(tid, acc, sec, day, l.acquired, use, g, f, part_cost, l.id, m))
            lots[:] = [l for l in lots if l.qty > D("0.000000001")]
    for ls in book.values():
        res.lots.extend(l for l in ls if l.qty > D("0.000000001"))
    return res


def holdings(res: Result) -> Dict[Tuple[int, int], dict]:
    """Remaining units and cost base per (account, security)."""
    out: Dict[Tuple[int, int], dict] = {}
    for l in res.lots:
        h = out.setdefault((l.account_id, l.security_id), dict(account_id=l.account_id, security_id=l.security_id, qty=ZERO, cost=ZERO, lots=0, earliest=l.acquired))
        h["qty"] += l.qty
        h["cost"] += l.cost
        h["lots"] += 1
        h["earliest"] = min(h["earliest"], l.acquired)
    return out
