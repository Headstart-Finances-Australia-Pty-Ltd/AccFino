"""Portfolio: holdings, valuation, gains, income, returns, allocation, concentration and history, all calculated from the transactions and prices by the parcel engine."""
from collections import defaultdict
from datetime import date, timedelta
from decimal import Decimal
from typing import Dict, List, Optional

from accfino.modules.investments.engine import bond as BD, lots as LE, portfolio as PF, property as PR, returns as RT
from accfino.modules.investments.engine.money import ZERO, D, add_months, q2
from accfino.modules.investments.models import inv as M
from accfino.modules.investments.services import core, data

CG_DISCOUNT = PR.DISCOUNT
STALE_DAYS = 10


def _load(db, ctx):
    secs = {s.id: s for s in db.query(M.InvSecurity).filter_by(org_id=ctx.org.id)}
    accs = {a.id: a for a in db.query(M.InvAccount).filter_by(org_id=ctx.org.id)}
    txns = db.query(M.InvTransaction).filter_by(org_id=ctx.org.id, voided=False).all()
    return secs, accs, txns


def replay(db, ctx, as_at: Optional[date] = None, txns=None):
    s = data.get_settings(db, ctx)
    if txns is None:
        txns = db.query(M.InvTransaction).filter_by(org_id=ctx.org.id, voided=False).all()
    return LE.replay(txns, s.cgt_method, as_at)


def _unit_value(sec: M.InvSecurity, qty: Decimal, cost: Decimal, price, as_at: date):
    """(market value, price used, note). A term deposit is worth principal + accrued interest; with no price a holding is valued at COST and flagged."""
    if sec.kind == "term_deposit" and sec.maturity_date and sec.coupon_rate is not None:
        start = sec.issue_date or as_at
        acc = BD.term_deposit_interest(qty, sec.coupon_rate, start, sec.maturity_date, as_at)["accrued"] if as_at > start else ZERO
        return q2(qty + acc), None, "principal plus accrued interest"
    if price is None:
        return q2(cost), None, "no price: valued at cost"
    return q2(qty * D(price)), D(price), None


def holdings(db, ctx, as_at: Optional[date] = None, kind: str = "", account_id: Optional[int] = None) -> dict:
    as_at = as_at or date.today()
    secs, accs, txns = _load(db, ctx)
    res = replay(db, ctx, as_at, txns)
    prices = data.price_map(db, ctx, as_at)
    inc12 = defaultdict(lambda: ZERO)
    for i in res.income:
        if i.date > add_months(as_at, -12) and i.kind in ("dividend", "distribution", "interest", "drp"):
            inc12[(i.account_id, i.security_id)] += i.cash
    by_lots = defaultdict(list)
    for l in res.lots:
        by_lots[(l.account_id, l.security_id)].append(l)
    rows, warnings = [], []
    kinds = set(kind.split(",")) if kind else None
    for (acc, sid), h in LE.holdings(res).items():
        s = secs[sid]
        if (kinds and s.kind not in kinds) or (account_id and acc != account_id):
            continue
        pr = prices.get(sid)
        value, used, note = _unit_value(s, h["qty"], h["cost"], pr[0] if pr else None, as_at)
        stale = bool(pr and (as_at - pr[1]).days > STALE_DAYS)
        if note and note.startswith("no price"):
            warnings.append(dict(security_id=sid, code=s.code, message=f"{s.code}: no price on or before {as_at}: valued at cost"))
        elif stale:
            warnings.append(dict(security_id=sid, code=s.code, message=f"{s.code}: the latest price is from {pr[1]} ({(as_at - pr[1]).days} days old)"))
        elig = sum((l.qty for l in by_lots[(acc, sid)] if as_at > add_months(l.acquired, 12)), ZERO)
        gain = value - h["cost"]
        rows.append(dict(account_id=acc, account=accs[acc].name, security_id=sid, code=s.code, name=s.name, kind=s.kind, asset_class=s.asset_class, sector=s.sector, country=s.country, qty=h["qty"], cost_base=q2(h["cost"]),
                         unit_cost=(h["cost"] / h["qty"]) if h["qty"] else ZERO, price=used, price_date=pr[1].isoformat() if pr else None, price_stale=stale, price_note=note, value=value, unrealised=q2(gain),
                         unrealised_pct=float(gain / h["cost"]) if h["cost"] > 0 else None, qty_discount_eligible=elig, parcels=h["lots"], earliest=h["earliest"].isoformat(), income_12m=q2(inc12[(acc, sid)]),
                         yield_on_value=float(inc12[(acc, sid)] / value) if value > 0 else None))
    total = sum((r["value"] for r in rows), ZERO)
    for r in rows:
        r["weight"] = float(r["value"] / total) if total > 0 else 0.0
    rows.sort(key=lambda r: -r["value"])
    for w in res.warnings:
        warnings.append(dict(security_id=None, code=None, message=w["message"], txn_id=w["txn_id"]))
    return dict(as_at=as_at.isoformat(), rows=rows, total_value=q2(total), total_cost=q2(sum((r["cost_base"] for r in rows), ZERO)), warnings=warnings)


def by_security(h: dict) -> List[dict]:
    """Holdings merged across accounts."""
    g: Dict[int, dict] = {}
    for r in h["rows"]:
        x = g.setdefault(r["security_id"], dict(r, accounts=[], qty=ZERO, cost_base=ZERO, value=ZERO, unrealised=ZERO, income_12m=ZERO, qty_discount_eligible=ZERO, parcels=0))
        x["accounts"].append(r["account"])
        for k in ("qty", "cost_base", "value", "unrealised", "income_12m", "qty_discount_eligible"):
            x[k] += r[k]
        x["parcels"] += r["parcels"]
    out = list(g.values())
    for x in out:
        x["unit_cost"] = (x["cost_base"] / x["qty"]) if x["qty"] else ZERO
        x["unrealised_pct"] = float(x["unrealised"] / x["cost_base"]) if x["cost_base"] > 0 else None
        x["yield_on_value"] = float(x["income_12m"] / x["value"]) if x["value"] > 0 else None
    return sorted(out, key=lambda r: -r["value"])


def disposals(db, ctx, fy: str = "", kind: str = "", security_id: Optional[int] = None) -> dict:
    secs, accs, txns = _load(db, ctx)
    res = replay(db, ctx, None, txns)
    s = data.get_settings(db, ctx)
    lo, hi = core.fy_bounds(fy) if fy else (None, None)
    kinds = set(kind.split(",")) if kind else None
    rows = []
    for d in res.disposals:
        sec = secs[d.security_id]
        if (lo and not lo <= d.dispose_date <= hi) or (kinds and sec.kind not in kinds) or (security_id and d.security_id != security_id):
            continue
        rows.append(dict(txn_id=d.txn_id, account=accs[d.account_id].name, security_id=d.security_id, code=sec.code, name=sec.name, kind=sec.kind, dispose_date=d.dispose_date.isoformat(), acquire_date=d.acquire_date.isoformat(), qty=d.qty,
                         proceeds=q2(d.proceeds_gross), selling_costs=q2(d.selling_costs), proceeds_net=q2(d.proceeds_net), cost_base=q2(d.cost_base), gain=q2(d.gain), discount_eligible=d.discount_eligible and d.gain > 0, days_held=d.days_held,
                         method=d.method, fy=core.fy_of(d.dispose_date)))
    rows.sort(key=lambda r: (r["dispose_date"], r["code"]))
    excess = [dict(date=e["date"].isoformat(), code=secs[e["security_id"]].code, amount=q2(e["amount"]), reason=e["reason"], fy=core.fy_of(e["date"])) for e in res.excess_gains if not lo or lo <= e["date"] <= hi]
    return dict(rows=rows, excess_gains=excess, summary=_cgt_summary(rows, excess, s.holder), holder=s.holder, method=s.cgt_method)


def _cgt_summary(rows, excess, holder) -> dict:
    """Estimate for ONE income year's worth of rows: current-year losses offset non-discount gains first, then discountable gains; the discount applies to what is left of the discountable gains.
    The authoritative CGT calculation (prior losses, concessions, the entity's other gains) is in Taxation > CGT once the events are sent there."""
    by_fy: Dict[str, dict] = {}
    for r in rows:
        f = by_fy.setdefault(r["fy"], dict(fy=r["fy"], gains_discountable=ZERO, gains_other=ZERO, losses=ZERO))
        if r["gain"] > 0:
            f["gains_discountable" if r["discount_eligible"] else "gains_other"] += r["gain"]
        else:
            f["losses"] += -r["gain"]
    for e in excess:
        f = by_fy.setdefault(e["fy"], dict(fy=e["fy"], gains_discountable=ZERO, gains_other=ZERO, losses=ZERO))
        f["gains_other"] += e["amount"]
    disc = CG_DISCOUNT.get(holder, ZERO)
    out = []
    for fy in sorted(by_fy):
        f = by_fy[fy]
        loss = f["losses"]
        other = max(f["gains_other"] - loss, ZERO)
        loss = max(loss - f["gains_other"], ZERO)
        dg = max(f["gains_discountable"] - loss, ZERO)
        carried = max(loss - f["gains_discountable"], ZERO)
        out.append(dict(fy=fy, gains_discountable=q2(f["gains_discountable"]), gains_other=q2(f["gains_other"]), losses=q2(f["losses"]), discount=q2(dg * disc), net_capital_gain=q2(other + dg - dg * disc), losses_carried_forward=q2(carried)))
    return dict(by_fy=out, holder=holder, discount_rate=float(disc), note="Estimate from this register only. The authoritative net capital gain is calculated in Taxation > CGT (prior-year losses, other events) after you send the events there.")


def income(db, ctx, fy: str = "") -> dict:
    secs, accs, txns = _load(db, ctx)
    res = replay(db, ctx, None, txns)
    lo, hi = core.fy_bounds(fy) if fy else (None, None)
    rows, by_fy, by_sec = [], {}, {}
    for i in res.income:
        if lo and not lo <= i.date <= hi:
            continue
        s = secs[i.security_id]
        r = dict(txn_id=i.txn_id, date=i.date.isoformat(), fy=core.fy_of(i.date), code=s.code, name=s.name, kind=s.kind, type=i.kind, cash=q2(i.cash), franked=q2(i.franked), unfranked=q2(i.unfranked), franking_credits=q2(i.franking_credits),
                 foreign_income=q2(i.foreign_income), cg_discount_part=q2(i.cg_discount_part), cg_other_part=q2(i.cg_other_part), tax_deferred=q2(i.tax_deferred), withholding=q2(i.withholding), value_in_kind=q2(i.value_in_kind))
        rows.append(r)
        for bucket, key in ((by_fy, r["fy"]), (by_sec, r["code"])):
            b = bucket.setdefault(key, dict(key=key, cash=ZERO, franked=ZERO, unfranked=ZERO, franking_credits=ZERO, foreign_income=ZERO, capital_gain_components=ZERO, tax_deferred=ZERO, interest=ZERO, staking_airdrop=ZERO))
            b["cash"] += i.cash
            b["franked"] += i.franked
            b["unfranked"] += i.unfranked
            b["franking_credits"] += i.franking_credits
            b["foreign_income"] += i.foreign_income
            b["capital_gain_components"] += i.cg_discount_part + i.cg_other_part
            b["tax_deferred"] += i.tax_deferred
            b["staking_airdrop"] += i.value_in_kind
            if i.kind == "interest":
                b["interest"] += i.cash
    fmt = lambda b: {k: (q2(v) if isinstance(v, Decimal) else v) for k, v in b.items()}
    flags = []
    for f, b in by_fy.items():                                            # the holding period rule matters once franking credits reach $5,000 in a year (ATO)
        if b["franking_credits"] >= Decimal(5000):
            flags.append(dict(fy=f, message=f"Franking credits for {f} are {q2(b['franking_credits'])}: the 45-day holding period rule applies (the small shareholder exemption stops at $5,000). Check each parcel was held at risk for 45 days (90 for some preference shares) around the ex-dividend date; AccFino only sees payment dates."))
    return dict(rows=sorted(rows, key=lambda r: r["date"], reverse=True), by_fy=[fmt(by_fy[k]) for k in sorted(by_fy)], by_security=sorted([fmt(b) for b in by_sec.values()], key=lambda b: -b["cash"]), flags=flags,
                total=q2(sum((b["cash"] for b in by_fy.values()), ZERO)), total_franking=q2(sum((b["franking_credits"] for b in by_fy.values()), ZERO)))


def _flows(txns, secs) -> List[tuple]:
    out = []
    for t in txns:
        a, fee = D(t.amount), D(t.fees)
        if t.txn_type == "buy":
            out.append((t.trade_date, -(a + fee)))
        elif t.txn_type == "sell":
            out.append((t.trade_date, a - fee))
        elif t.txn_type in ("dividend", "distribution", "interest"):
            out.append((t.trade_date, a - D(t.withholding_tax)))
        elif t.txn_type == "fee":
            out.append((t.trade_date, -(a + fee)))
    return out


def performance(db, ctx, as_at: Optional[date] = None, security_id: Optional[int] = None) -> dict:
    """Money-weighted return (XIRR): purchases out; sales, income and the closing market value in. Dividend reinvestments net to nothing and are left out of the flows."""
    as_at = as_at or date.today()
    secs, accs, txns = _load(db, ctx)
    txns = [t for t in txns if t.trade_date <= as_at and (not security_id or t.security_id == security_id)]
    h = holdings(db, ctx, as_at)
    held = [r for r in h["rows"] if not security_id or r["security_id"] == security_id]
    close = sum((r["value"] for r in held), ZERO)
    flows = _flows(txns, secs)
    since = RT.xirr(flows + ([(as_at, close)] if close > 0 else []))
    start = add_months(as_at, -12)
    opening = holdings(db, ctx, start)
    open_val = sum((r["value"] for r in opening["rows"] if not security_id or r["security_id"] == security_id), ZERO)
    win = [(d, a) for d, a in flows if start < d <= as_at]
    last12 = RT.xirr(([(start, -open_val)] if open_val > 0 else []) + win + ([(as_at, close)] if close > 0 else []))
    invested = sum((-a for d, a in flows if a < 0), ZERO)
    taken = sum((a for d, a in flows if a > 0), ZERO)
    return dict(as_at=as_at.isoformat(), xirr_since_inception=since, xirr_last_12_months=last12, total_invested=q2(invested), total_returned=q2(taken), market_value=q2(close),
                total_return=q2(close + taken - invested), total_return_pct=RT.simple_return(invested, close, 0, taken), note="Money-weighted (XIRR) over dated cash flows. A holding with no price is valued at cost, which understates or overstates return until you add a price.")


def allocation(db, ctx, as_at: Optional[date] = None) -> dict:
    h = holdings(db, ctx, as_at)
    items = [dict(r, value=r["value"]) for r in h["rows"]]
    sec = by_security(h)
    return dict(as_at=h["as_at"], total=h["total_value"], by_class=PF.allocate(items, "asset_class"), by_kind=PF.allocate(items, "kind"), by_sector=PF.allocate(items, "sector"), by_country=PF.allocate(items, "country"),
                by_account=PF.allocate([dict(r, name=r["account"]) for r in items], "account"), diversification=PF.diversification([dict(r, name=r["code"]) for r in sec]), warnings=h["warnings"])


def history(db, ctx, months: int = 24, as_at: Optional[date] = None) -> dict:
    """Month-end value, cost base and unrealised gain, from replaying the register at each date with the prices then known."""
    as_at = as_at or date.today()
    months = max(1, min(int(months), 120))
    secs, accs, txns = _load(db, ctx)
    first = min((t.trade_date for t in txns), default=None)
    pts = []
    for i in range(months, -1, -1):
        d = add_months(as_at.replace(day=1), -i)
        d = (add_months(d, 1) - timedelta(days=1)) if i else as_at
        if first is None or d < first:
            continue
        h = holdings(db, ctx, d)
        flows = sum((a for dd, a in _flows([t for t in txns if t.trade_date <= d], secs) if a < 0), ZERO)
        pts.append(dict(date=d.isoformat(), value=h["total_value"], cost=h["total_cost"], unrealised=q2(h["total_value"] - h["total_cost"]), invested_to_date=q2(-flows)))
    return dict(points=pts)


def security_detail(db, ctx, security_id: int, as_at: Optional[date] = None) -> dict:
    s = data.get_security(db, ctx, security_id)
    as_at = as_at or date.today()
    h = holdings(db, ctx, as_at)
    mine = [r for r in h["rows"] if r["security_id"] == security_id]
    res = replay(db, ctx, as_at)
    lots = [dict(lot_id=l.id, account_id=l.account_id, acquired=l.acquired.isoformat(), qty=l.qty, cost_base=q2(l.cost), unit_cost=l.unit_cost, origin=l.origin, discount_eligible=as_at > add_months(l.acquired, 12)) for l in res.lots if l.security_id == security_id]
    d = disposals(db, ctx, "", "", security_id)
    inc = [r for r in income(db, ctx)["rows"] if r["code"] == s.code]
    perf = performance(db, ctx, as_at, security_id)
    out = dict(security=data.sec_dict(s), holdings=mine, parcels=sorted(lots, key=lambda l: l["acquired"]), disposals=d["rows"], income=inc, performance=perf, prices=data.prices(db, ctx, security_id, 60),
               transactions=data.list_txns(db, ctx, security_id=security_id, include_voided=True), warnings=[w for w in h["warnings"] if w.get("security_id") == security_id])
    if s.kind == "bond" and s.maturity_date and s.coupon_rate is not None and s.coupon_freq and as_at < s.maturity_date:
        pr = data.price_map(db, ctx, as_at).get(security_id)
        face = D(s.face_value)
        acc = BD.accrued_interest(face, s.coupon_rate, s.coupon_freq, as_at, s.maturity_date, s.day_count)
        b = dict(next_coupon=BD.neighbours(as_at, s.maturity_date, s.coupon_freq)[1].isoformat(), accrued_interest_per_bond=q2(acc), annual_coupon=q2(face * D(s.coupon_rate)), maturity_date=s.maturity_date.isoformat(), days_to_maturity=(s.maturity_date - as_at).days,
                 cashflows=[dict(date=d_.isoformat(), amount=q2(a)) for d_, a in BD.cashflows(face, s.coupon_rate, s.coupon_freq, as_at, s.maturity_date)])
        if pr:
            clean = float(pr[0]) / float(face) * 100 if face else 0
            y = BD.ytm(clean, 100, float(s.coupon_rate), s.coupon_freq, as_at, s.maturity_date, s.day_count)
            b.update(price_per_100=round(clean, 4), ytm=y, current_yield=(float(s.coupon_rate) * 100 / clean) if clean else None, duration=BD.duration(y, 100, float(s.coupon_rate), s.coupon_freq, as_at, s.maturity_date) if y is not None else None)
        out["bond"] = b
    return out
