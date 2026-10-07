"""Capital gains: the CGT event register (manual entries, property, and rows imported from Trading / Investments), the capital-loss register, and the
net-capital-gain computation that feeds the income tax return. Trading's disposal rows are accepted as DATA (the importer takes the same columns the
Trading export shows) so Taxation never imports Trading internals."""
import csv
import hashlib
import io
from datetime import date
from typing import List, Optional

from accfino.modules.taxation.engine import cgt as E, rules as R
from accfino.modules.taxation.engine.money import ZERO, D, q2
from accfino.modules.taxation.models import tax as T
from accfino.modules.taxation.services import core, profile as P
from accfino.modules.taxation.services.core import NotFound, TaxError

HOLDER_BY_ENTITY = {"individual": "individual", "sole_trader": "individual", "partnership": "individual", "trust": "trust", "company": "company", "smsf": "super"}
MONEY_FIELDS = ("proceeds", "acquisition_cost", "incidental_costs", "ownership_costs", "capital_improvements", "disposal_costs")


def ev_dict(e: T.TaxCgtEvent) -> dict:
    return dict(id=e.id, fy=e.fy, asset_class=e.asset_class, asset_name=e.asset_name, quantity=core.plain(e.quantity), acquire_date=e.acquire_date.isoformat(), dispose_date=e.dispose_date.isoformat(),
                proceeds=str(e.proceeds), acquisition_cost=str(e.acquisition_cost), incidental_costs=str(e.incidental_costs), ownership_costs=str(e.ownership_costs),
                capital_improvements=str(e.capital_improvements), disposal_costs=str(e.disposal_costs), pre_cgt=e.pre_cgt, main_residence_exempt=e.main_residence_exempt,
                small_business=e.small_business, source=e.source, source_ref=e.source_ref, excluded=e.excluded, notes=e.notes)


def _engine_event(e: T.TaxCgtEvent) -> dict:
    return dict(id=e.id, asset_name=e.asset_name, acquire_date=e.acquire_date, dispose_date=e.dispose_date, proceeds=e.proceeds, acquisition_cost=e.acquisition_cost,
                incidental_costs=e.incidental_costs, ownership_costs=e.ownership_costs, capital_improvements=e.capital_improvements, disposal_costs=e.disposal_costs,
                pre_cgt=e.pre_cgt, main_residence_exempt=e.main_residence_exempt, small_business=e.small_business)


def _fill(ctx, e: T.TaxCgtEvent, body: dict):
    name = (body.get("asset_name") or "").strip()
    if not name:
        raise TaxError("asset_name is required")
    ac = body.get("asset_class") or "shares"
    if ac not in T.CGT_CLASSES:
        raise TaxError(f"asset_class must be one of {', '.join(T.CGT_CLASSES)}")
    acq, disp = core.parse_date(body.get("acquire_date"), "acquire_date"), core.parse_date(body.get("dispose_date"), "dispose_date")
    if not acq or not disp:
        raise TaxError("acquire_date and dispose_date are required")
    if disp < acq:
        raise TaxError("The disposal date cannot be before the acquisition date")
    if disp > date.today().replace(year=date.today().year + 1):
        raise TaxError("The disposal date is too far in the future")
    e.asset_name, e.asset_class, e.acquire_date, e.dispose_date = name[:200], ac, acq, disp
    e.fy = R.fy_of(disp, ctx.org.fy_end_month or 6)
    e.proceeds = core.money_in(body.get("proceeds"), "proceeds", required=True)
    for k in MONEY_FIELDS[1:]:
        setattr(e, k, core.money_in(body.get(k), k) or ZERO)
    q = body.get("quantity")
    e.quantity = None if q in (None, "") else D(q)
    e.pre_cgt, e.main_residence_exempt = bool(body.get("pre_cgt")), bool(body.get("main_residence_exempt"))
    if e.main_residence_exempt and ac != "property":
        raise TaxError("The main residence exemption applies to property only")
    sb = body.get("small_business")
    if sb:
        bad = set(sb) - {"active_asset_reduction", "exempt_15yr", "retirement_exemption", "rollover"}
        if bad:
            raise TaxError(f"Unknown small business option(s): {', '.join(sorted(bad))}")
    e.small_business = sb or None
    e.notes = (body.get("notes") or "")[:500] or None


def save_event(db, ctx, a: core.Access, body: dict, eid: Optional[int] = None) -> T.TaxCgtEvent:
    a.require("prepare")
    if eid:
        e = db.query(T.TaxCgtEvent).filter_by(org_id=ctx.org.id, id=eid).first()
        if e is None:
            raise NotFound("CGT event")
    else:
        e = T.TaxCgtEvent(org_id=ctx.org.id, created_by=ctx.user_id, source=body.get("source") or "manual")
    _guard_year(db, ctx, R.fy_of(core.parse_date(body.get("dispose_date"), "dispose_date") or date.today(), ctx.org.fy_end_month or 6), e)
    before = ev_dict(e) if eid else None
    _fill(ctx, e, body)
    if not eid:
        db.add(e)
    db.flush()
    core.record(db, ctx, "cgt.event.save", "tax_cgt_event", e.id, f"CGT event {e.asset_name} ({e.fy}) {'updated' if eid else 'added'}", before, ev_dict(e))
    return e


def _guard_year(db, ctx, fy, e=None):
    """Events of a year whose return is approved or lodged cannot change under it."""
    for fy_ in {fy, getattr(e, "fy", None)} - {None}:
        r = db.query(T.TaxReturn).filter(T.TaxReturn.org_id == ctx.org.id, T.TaxReturn.fy == fy_, T.TaxReturn.status.in_(("approved", "lodged", "paid"))).first()
        if r:
            raise core.Conflict(f"The {fy_} income tax return is {r.status}: return it to draft (or lodge an amendment) before changing its CGT events.", "locked")


def delete_event(db, ctx, a: core.Access, eid: int):
    a.require("prepare")
    e = db.query(T.TaxCgtEvent).filter_by(org_id=ctx.org.id, id=eid).first()
    if e is None:
        raise NotFound("CGT event")
    _guard_year(db, ctx, e.fy, e)
    core.record(db, ctx, "cgt.event.delete", "tax_cgt_event", e.id, f"CGT event {e.asset_name} deleted", ev_dict(e), None)
    db.delete(e)


def set_excluded(db, ctx, a: core.Access, eid: int, excluded: bool):
    a.require("prepare")
    e = db.query(T.TaxCgtEvent).filter_by(org_id=ctx.org.id, id=eid).first()
    if e is None:
        raise NotFound("CGT event")
    _guard_year(db, ctx, e.fy, e)
    e.excluded = bool(excluded)
    core.record(db, ctx, "cgt.event.exclude", "tax_cgt_event", e.id, f"CGT event {e.asset_name} {'excluded from' if excluded else 'included in'} the return", None, None)
    return e


def events(db, ctx, fy: str = "") -> List[dict]:
    q = db.query(T.TaxCgtEvent).filter_by(org_id=ctx.org.id)
    if fy:
        q = q.filter(T.TaxCgtEvent.fy == fy)
    return [ev_dict(e) for e in q.order_by(T.TaxCgtEvent.dispose_date, T.TaxCgtEvent.id)]


# ---- import from Trading / Investments -------------------------------------------------------------------------------------------
TRADING_COLS = {"disposal_date": ("Disposal Date",), "name": ("Asset Name", "Asset Code"), "qty": ("Qty Disposed",), "proceeds": ("Total Proceeds ($)",), "cost": ("Total Cost Base ($)",),
                "acq": ("Acquisition Date",), "ref": ("Reference",), "code": ("Asset Code",), "event": ("Event Type",)}


def _pick(row: dict, key: str):
    for c in TRADING_COLS[key]:
        if c in row and row[c] not in (None, ""):
            return row[c]
    return None


def import_rows(db, ctx, a: core.Access, rows: List[dict], *, asset_class: str = "shares", dry_run: bool = False) -> dict:
    """rows use the Trading disposal export columns. Duplicates (same row content) are skipped, so the same file can be imported twice safely."""
    a.require("prepare")
    if asset_class not in T.CGT_CLASSES:
        raise TaxError("invalid asset_class")
    added, skipped, errors = [], 0, []
    existing = {r[0] for r in db.query(T.TaxCgtEvent.source_ref).filter(T.TaxCgtEvent.org_id == ctx.org.id, T.TaxCgtEvent.source == "trading_import")}
    seen = set()
    for i, row in enumerate(rows, start=1):
        try:
            disp, acq = core.parse_date(str(_pick(row, "disposal_date"))[:10], "Disposal Date"), core.parse_date(str(_pick(row, "acq"))[:10], "Acquisition Date")
            if not disp or not acq:
                raise TaxError("Disposal Date and Acquisition Date are required")
            name = str(_pick(row, "name") or "").strip()
            key = hashlib.sha1("|".join(str(x) for x in (name, disp, acq, _pick(row, "qty"), _pick(row, "proceeds"), _pick(row, "cost"), _pick(row, "ref"))).encode()).hexdigest()
            if key in existing or key in seen:
                skipped += 1
                continue
            seen.add(key)
            body = dict(asset_name=name, asset_class=asset_class, acquire_date=acq, dispose_date=disp, proceeds=_pick(row, "proceeds"), acquisition_cost=_pick(row, "cost") or 0,
                        quantity=_pick(row, "qty"), source="trading_import", notes=f"Imported from Trading ({_pick(row, 'ref') or 'no reference'})")
            if dry_run:
                tmp = T.TaxCgtEvent(org_id=ctx.org.id)
                _fill(ctx, tmp, body)
                added.append(dict(row=i, asset=name, fy=tmp.fy))
            else:
                _guard_year(db, ctx, R.fy_of(disp, ctx.org.fy_end_month or 6))
                e = T.TaxCgtEvent(org_id=ctx.org.id, created_by=ctx.user_id, source="trading_import", source_ref=key)
                _fill(ctx, e, body)
                db.add(e)
                db.flush()
                added.append(dict(row=i, asset=name, fy=e.fy, id=e.id))
        except (TaxError, ValueError) as ex:
            errors.append(dict(row=i, error=str(getattr(ex, "message", ex))))
    if not dry_run and added:
        core.record(db, ctx, "cgt.import", "tax_cgt_event", None, f"Imported {len(added)} disposals from Trading ({skipped} duplicates skipped, {len(errors)} rejected)", None, dict(added=len(added)))
    return dict(added=len(added), skipped_duplicates=skipped, rejected=len(errors), errors=errors, rows=added, dry_run=dry_run)


def import_csv(db, ctx, a: core.Access, text: str, *, asset_class="shares", dry_run=False) -> dict:
    rows = list(csv.DictReader(io.StringIO(text.lstrip("\ufeff"))))
    if not rows:
        raise TaxError("The file has no rows")
    return import_rows(db, ctx, a, rows, asset_class=asset_class, dry_run=dry_run)


# ---- capital losses ----------------------------------------------------------------------------------------------------------------
def losses(db, ctx) -> List[dict]:
    return [dict(id=l.id, fy_incurred=l.fy_incurred, amount=str(l.amount), note=l.note) for l in db.query(T.TaxCapitalLoss).filter_by(org_id=ctx.org.id).order_by(T.TaxCapitalLoss.fy_incurred, T.TaxCapitalLoss.id)]


def add_loss(db, ctx, a: core.Access, fy_incurred: str, amount, note: str = "") -> T.TaxCapitalLoss:
    a.require("prepare")
    core.check_fy(ctx, fy_incurred)
    amt = core.money_in(amount, "amount", required=True)
    if amt <= 0:
        raise TaxError("amount must be greater than zero")
    l = T.TaxCapitalLoss(org_id=ctx.org.id, fy_incurred=fy_incurred, amount=amt, note=(note or "")[:300] or None, created_by=ctx.user_id)
    db.add(l)
    db.flush()
    core.record(db, ctx, "cgt.loss.add", "tax_capital_loss", l.id, f"Capital loss brought forward {amt} from {fy_incurred}", None, dict(amount=str(amt)))
    return l


def delete_loss(db, ctx, a: core.Access, lid: int):
    a.require("prepare")
    l = db.query(T.TaxCapitalLoss).filter_by(org_id=ctx.org.id, id=lid).first()
    if l is None:
        raise NotFound("Capital loss")
    core.record(db, ctx, "cgt.loss.delete", "tax_capital_loss", l.id, "Capital loss entry deleted", dict(amount=str(l.amount)), None)
    db.delete(l)


# ---- computation -------------------------------------------------------------------------------------------------------------------
def compute(db, ctx, fy: str, holder: Optional[str] = None) -> dict:
    core.check_fy(ctx, fy)
    p = P.get(db, ctx)
    holder = holder or HOLDER_BY_ENTITY.get(p.entity_type, "individual")
    if holder not in E.HOLDERS:
        raise TaxError(f"holder must be one of {', '.join(E.HOLDERS)}")
    rs = core.rules_for_fy(db, ctx, fy)
    evs = [e for e in db.query(T.TaxCgtEvent).filter_by(org_id=ctx.org.id, fy=fy, excluded=False).order_by(T.TaxCgtEvent.dispose_date, T.TaxCgtEvent.id)]
    prior = sum((l.amount for l in db.query(T.TaxCapitalLoss).filter(T.TaxCapitalLoss.org_id == ctx.org.id, T.TaxCapitalLoss.fy_incurred < fy)), ZERO)
    res = E.net_capital_gain(rs, [_engine_event(e) for e in evs], holder, prior_losses=prior, foreign_resident=(p.residency == "foreign"))
    reform_from = (rs.get("cgt.reform") or {}).get("effective_from")
    post = [e for e in evs if reform_from and e.dispose_date >= date.fromisoformat(reform_from)]
    res.update(post_reform_events=len(post), fy=fy, event_count=len(evs), prior_losses_available=str(q2(prior)), rule_set=rs.id,
               loss_register_note="Prior-year capital losses are the entries in the loss register dated before this year. AccFino does not roll losses forward automatically: after each return is finalised, "
                                  "update the register with the carried-forward amount shown here.")
    if p.entity_type == "partnership":
        res["review"] = sorted(set(res["review"] + ["Partnership: net capital gain is calculated at partnership level and distributed to partners, who apply their own discounts and losses."]))
    return res


# ---- crypto: match disposals to acquisitions from a trade list ---------------------------------------------------------------------------------------
METHODS = ("fifo", "lifo", "hifo")
METHOD_NOTE = ("Lots are matched by the method you choose; use the same method consistently and keep records. Not handled: crypto-to-crypto swaps, staking, airdrops, DeFi and transfers between your own wallets "
               "unless they appear as AUD buy/sell rows. Each sell is split across the lots it consumes so every piece has its own acquisition date (needed for the 12-month discount).")


def _dt(v) -> date:
    return date.fromisoformat(str(v)[:10])


def crypto_disposals(trades: List[dict], method: str = "fifo") -> tuple:
    """Trades (Date, Symbol, Side, Quantity, Price, Proceeds, Cost, Fee) -> disposal rows in the Trading export format plus the sells that could not be matched.
    Buy cost = Cost (or Price x Quantity) + fee; sell proceeds = Proceeds (or Price x Quantity) - fee. Pieces of one sell share its proceeds pro rata (the last takes the rounding remainder)."""
    if method not in METHODS:
        raise TaxError(f"method must be one of {', '.join(METHODS)}")
    rows, unmatched, lots = [], [], {}
    norm = []
    for i, t in enumerate(trades or []):
        try:
            side = str(t.get("Side") or "").strip().lower()
            side = "buy" if side in ("buy", "b", "purchase", "bought") else "sell" if side in ("sell", "s", "sale", "sold") else ""
            qty = abs(D(t.get("Quantity")))
            if not side or qty <= 0:
                continue
            price, fee = D(t.get("Price")), abs(D(t.get("Fee")))
            amount = D(t.get("Cost" if side == "buy" else "Proceeds"))
            amount = abs(amount) if amount else price * qty
            norm.append((_dt(t.get("Date")), i, str(t.get("Symbol") or "").strip().upper(), side, qty, amount, fee))
        except (ValueError, TypeError):
            unmatched.append(dict(row=i + 1, symbol=str(t.get("Symbol") or ""), reason="Could not read this trade (date, quantity or amount)"))
    for d, i, sym, side, qty, amount, fee in sorted(norm, key=lambda x: (x[0], x[1])):
        if side == "buy":
            lots.setdefault(sym, []).append(dict(date=d, qty=qty, unit=(amount + fee) / qty, idx=i))
            continue
        net = amount - fee
        remaining, pieces = qty, []
        pool = lots.get(sym, [])
        while remaining > 0:
            avail = [l for l in pool if l["qty"] > 0]
            if not avail:
                break
            lot = (min(avail, key=lambda l: (l["date"], l["idx"])) if method == "fifo" else max(avail, key=lambda l: (l["date"], l["idx"])) if method == "lifo"
                   else max(avail, key=lambda l: (l["unit"], -l["idx"])))
            take = min(lot["qty"], remaining)
            lot["qty"] -= take
            remaining -= take
            pieces.append((lot, take))
        if remaining > 0:
            unmatched.append(dict(row=i + 1, symbol=sym, date=d.isoformat(), quantity=str(remaining), reason=f"{remaining} {sym} sold on {d.isoformat()} has no earlier purchase to match: add the missing acquisition or exclude this sell"))
        given = ZERO
        matched_qty = qty - remaining
        for n, (lot, take) in enumerate(pieces):
            share = q2(net * take / qty) if n < len(pieces) - 1 or remaining > 0 else q2(net * matched_qty / qty - given)
            given += share
            rows.append({"Disposal Date": d.isoformat(), "Asset Name": sym, "Qty Disposed": str(take), "Total Proceeds ($)": str(share), "Total Cost Base ($)": str(q2(lot["unit"] * take)),
                         "Acquisition Date": lot["date"].isoformat(), "Reference": f"crypto:{method}:{sym}:{d.isoformat()}:{lot['date'].isoformat()}:{lot['idx']}:{take}"})
    return rows, unmatched


def import_trades(db, ctx, a: core.Access, trades: List[dict], method: str = "fifo", dry_run: bool = False) -> dict:
    a.require("prepare")
    rows, unmatched = crypto_disposals(trades, method)
    res = import_rows(db, ctx, a, rows, asset_class="crypto", dry_run=dry_run)
    res.update(method=method, trades_read=len(trades or []), disposals=len(rows), unmatched=unmatched, note=METHOD_NOTE)
    return res
