"""Net worth: investments (market value from the register), property (your share of the latest valuation), cash and other assets and the liabilities from the LEDGER, plus manually recorded other
assets and liabilities. No double counting: the ledger account that holds investments at cost is excluded from the ledger side (the register's market value replaces it), and a liability linked to a
ledger account is read from the ledger only."""
from datetime import date, timedelta
from typing import Optional

import accfino.modules.accounting.public as acct
from accfino.modules.investments.engine.money import ZERO, D, add_months, q2
from accfino.modules.investments.models import inv as M
from accfino.modules.investments.services import core, data, portfolio, property_svc, valuations
from accfino.modules.investments.services.core import Access, Conflict, InvError, NotFound

GROUPS = {"share": "Shares & ETFs", "etf": "Shares & ETFs", "crypto": "Crypto", "managed_fund": "Managed funds", "bond": "Bonds & term deposits", "term_deposit": "Bonds & term deposits"}
LIQUID = {"Cash", "Shares & ETFs", "Managed funds", "Crypto"}


# ---------------------------------------------------------------------------------------------------------------------- other assets and liabilities
def oa_dict(x: M.InvOtherAsset, value=None, as_at=None) -> dict:
    return dict(id=x.id, name=x.name, kind=x.kind, notes=x.notes, active=x.active, value=None if value is None else str(value), value_as_at=core.plain(as_at))


def other_assets(db, ctx, as_at: Optional[date] = None):
    as_at = as_at or date.today()
    out = []
    for x in db.query(M.InvOtherAsset).filter_by(org_id=ctx.org.id).order_by(M.InvOtherAsset.name):
        v = valuations.latest(db, ctx, "other_asset", x.id, as_at)
        out.append(oa_dict(x, v.value if v else None, v.as_at if v else None))
    return out


def save_other_asset(db, ctx, a: Access, body: dict, oid: Optional[int] = None) -> M.InvOtherAsset:
    a.require("edit")
    name = (body.get("name") or "").strip()
    kind = body.get("kind") or "other"
    if not name:
        raise InvError("name is required")
    if kind not in M.OTHER_ASSET_KINDS:
        raise InvError(f"kind must be one of {', '.join(M.OTHER_ASSET_KINDS)}")
    x = db.query(M.InvOtherAsset).filter_by(org_id=ctx.org.id, id=oid).first() if oid else M.InvOtherAsset(org_id=ctx.org.id)
    if oid and x is None:
        raise NotFound("Asset")
    if db.query(M.InvOtherAsset).filter(M.InvOtherAsset.org_id == ctx.org.id, M.InvOtherAsset.name == name, M.InvOtherAsset.id != (x.id or 0)).first():
        raise Conflict(f"An asset named '{name}' already exists")
    before = oa_dict(x) if oid else None
    x.name, x.kind, x.notes = name[:120], kind, (body.get("notes") or None)
    if "active" in body:
        x.active = bool(body["active"])
    if not oid:
        db.add(x)
    db.flush()
    core.record(db, ctx, "other_asset.save", "inv_other_asset", x.id, f"{x.kind} '{x.name}'", before, oa_dict(x))
    return x


def li_dict(x: M.InvLiability, balance=None, as_at=None) -> dict:
    return dict(id=x.id, name=x.name, kind=x.kind, lender=x.lender, limit_amount=None if x.limit_amount is None else str(x.limit_amount), interest_rate=None if x.interest_rate is None else str(x.interest_rate),
                ledger_account_id=x.ledger_account_id, active=x.active, balance=None if balance is None else str(balance), balance_as_at=core.plain(as_at))


def liabilities(db, ctx, as_at: Optional[date] = None):
    as_at = as_at or date.today()
    out = []
    for x in db.query(M.InvLiability).filter_by(org_id=ctx.org.id).order_by(M.InvLiability.name):
        v = valuations.latest(db, ctx, "liability", x.id, as_at)
        out.append(li_dict(x, v.value if v else None, v.as_at if v else None))
    return out


def save_liability(db, ctx, a: Access, body: dict, lid: Optional[int] = None) -> M.InvLiability:
    a.require("edit")
    name = (body.get("name") or "").strip()
    kind = body.get("kind") or "mortgage"
    if not name:
        raise InvError("name is required")
    if kind not in M.LIABILITY_KINDS:
        raise InvError(f"kind must be one of {', '.join(M.LIABILITY_KINDS)}")
    rate = core.num(body.get("interest_rate"), "interest_rate", places=8)
    if rate is not None and rate > 60:
        raise InvError("interest_rate is a percentage a year (6.2 means 6.2%)")
    limit = core.num(body.get("limit_amount"), "limit_amount")
    acc_id = body.get("ledger_account_id") or None
    if acc_id:
        accs = {x["id"] for x in acct.ledger_accounts(db, ctx.org.id)}
        if int(acc_id) not in accs:
            raise InvError("ledger_account_id is not one of your ledger accounts")
    x = db.query(M.InvLiability).filter_by(org_id=ctx.org.id, id=lid).first() if lid else M.InvLiability(org_id=ctx.org.id)
    if lid and x is None:
        raise NotFound("Liability")
    if db.query(M.InvLiability).filter(M.InvLiability.org_id == ctx.org.id, M.InvLiability.name == name, M.InvLiability.id != (x.id or 0)).first():
        raise Conflict(f"A liability named '{name}' already exists")
    before = li_dict(x) if lid else None
    x.name, x.kind, x.lender, x.interest_rate, x.limit_amount, x.ledger_account_id = name[:120], kind, (body.get("lender") or None), rate, limit, int(acc_id) if acc_id else None
    if "active" in body:
        x.active = bool(body["active"])
    if not lid:
        db.add(x)
    db.flush()
    core.record(db, ctx, "liability.save", "inv_liability", x.id, f"{x.kind} '{x.name}'", before, li_dict(x))
    return x


# ---------------------------------------------------------------------------------------------------------------------- net worth
def _ledger_map(db, ctx):
    return (data.get_settings(db, ctx).ledger_map or data.DEFAULT_LEDGER_MAP)


def networth(db, ctx, as_at: Optional[date] = None) -> dict:
    as_at = as_at or date.today()
    warnings, assets, liabs = [], [], []
    h = portfolio.holdings(db, ctx, as_at)
    inv_groups = {}
    for r in h["rows"]:
        g = GROUPS[r["kind"]]
        inv_groups[g] = inv_groups.get(g, ZERO) + r["value"]
    for g, v in inv_groups.items():
        assets.append(dict(group=g, name=g, value=q2(v), source="investments register (market value)"))
    warnings += [w["message"] for w in h["warnings"] if w.get("security_id")]
    for p in db.query(M.InvProperty).filter_by(org_id=ctx.org.id, active=True):
        if p.sale_contract_date and p.sale_contract_date <= as_at:
            continue
        if p.contract_date and p.contract_date > as_at:
            continue
        value, basis = property_svc.current_value(db, ctx, p, as_at)
        if "no valuation" in basis:
            warnings.append(f"{p.name}: valued at the purchase price: add a current valuation")
        assets.append(dict(group="Property", name=p.name, value=q2(value * p.ownership_pct / D(100)), source=f"property register, {basis}" + ("" if p.ownership_pct == 100 else f", your {p.ownership_pct}% share")))
    lm = _ledger_map(db, ctx)
    inv_code, inv_key = lm["asset"]["code"], lm["asset"]["key"]
    bal = acct.balances_by_account(db, ctx.org, as_at)
    for b in bal:
        v = D(b["balance"])
        if b["type"] == "bank" and v != 0:
            assets.append(dict(group="Cash", name=f"{b['code']} {b['name']}", value=q2(v), source="ledger (bank account)"))
        elif b["type"] in ("current_asset", "inventory", "fixed_asset", "non_current_asset") and v != 0:
            if b["code"] == inv_code:
                warnings.append(f"Ledger account {b['code']} '{b['name']}' (investments at cost) is excluded: the register's market value is used instead") if v != 0 else None
                continue
            assets.append(dict(group="Other ledger assets", name=f"{b['code']} {b['name']}", value=q2(v), source=f"ledger ({b['type'].replace('_', ' ')})"))
    for x in db.query(M.InvOtherAsset).filter_by(org_id=ctx.org.id, active=True):
        v = valuations.latest(db, ctx, "other_asset", x.id, as_at)
        if v is None:
            warnings.append(f"{x.name}: no value recorded")
            continue
        assets.append(dict(group="Other assets", name=x.name, value=q2(v.value), source=f"valuation {v.as_at}"))
    ledger_liab_ids = {x.ledger_account_id for x in db.query(M.InvLiability).filter_by(org_id=ctx.org.id) if x.ledger_account_id}
    names = {x.ledger_account_id: x.name for x in db.query(M.InvLiability).filter_by(org_id=ctx.org.id) if x.ledger_account_id}
    for b in bal:
        v = D(b["balance"])
        if b["class"] == "liability" and v != 0:
            grp = {"credit_card": "Credit cards", "non_current_liability": "Loans & borrowings"}.get(b["type"], "Other liabilities (payables, GST, PAYG)")
            liabs.append(dict(group=grp, name=names.get(b["id"]) or f"{b['code']} {b['name']}", value=q2(v), source="ledger"))
    for x in db.query(M.InvLiability).filter_by(org_id=ctx.org.id, active=True):
        if x.ledger_account_id:
            continue
        v = valuations.latest(db, ctx, "liability", x.id, as_at)
        if v is None:
            warnings.append(f"{x.name}: no balance recorded")
            continue
        liabs.append(dict(group="Loans & borrowings" if x.kind != "credit_card" else "Credit cards", name=x.name, value=q2(v.value), source=f"balance {v.as_at}"))
    ta, tl = sum((r["value"] for r in assets), ZERO), sum((r["value"] for r in liabs), ZERO)
    grp = lambda rows: sorted(({"name": g, "value": q2(sum((r["value"] for r in rows if r["group"] == g), ZERO))} for g in {r["group"] for r in rows}), key=lambda x: -x["value"])
    ag, lg = grp(assets), grp(liabs)
    for x in ag:
        x["weight"] = float(x["value"] / ta) if ta > 0 else 0.0
    liquid = sum((x["value"] for x in ag if x["name"] in LIQUID), ZERO)
    return dict(as_at=as_at.isoformat(), total_assets=q2(ta), total_liabilities=q2(tl), net_worth=q2(ta - tl), assets_by_group=ag, liabilities_by_group=lg, assets=sorted(assets, key=lambda r: (-r["value"])), liabilities=sorted(liabs, key=lambda r: -r["value"]),
                ratios=dict(debt_to_assets=float(tl / ta) if ta > 0 else None, liquid_assets=q2(liquid), liquid_share=float(liquid / ta) if ta > 0 else None), warnings=sorted(set(warnings)))


def history(db, ctx, months: int = 24, as_at: Optional[date] = None) -> dict:
    as_at = as_at or date.today()
    months = max(1, min(int(months), 120))
    pts = []
    snaps = db.query(M.InvSnapshot).filter_by(org_id=ctx.org.id).order_by(M.InvSnapshot.as_at).all()
    for i in range(months, -1, -1):
        d = add_months(as_at.replace(day=1), -i)
        first = d
        d = (add_months(d, 1) - timedelta(days=1)) if i else as_at
        n = networth(db, ctx, d)
        if n["total_assets"] == 0 and n["total_liabilities"] == 0:
            in_month = [s for s in snaps if first <= s.as_at <= d]                    # no records yet for this month: use a saved or imported snapshot taken in it, if there is one
            if in_month:
                s = in_month[-1]
                pts.append(dict(date=s.as_at.isoformat(), assets=s.total_assets, liabilities=s.total_liabilities, net_worth=s.net_worth, by_group={}, from_snapshot=True))
            continue
        pts.append(dict(date=d.isoformat(), assets=n["total_assets"], liabilities=n["total_liabilities"], net_worth=n["net_worth"], by_group={x["name"]: x["value"] for x in n["assets_by_group"]}))
    return dict(points=pts, change=None if len(pts) < 2 else dict(from_date=pts[0]["date"], amount=q2(pts[-1]["net_worth"] - pts[0]["net_worth"]), pct=float((pts[-1]["net_worth"] - pts[0]["net_worth"]) / abs(pts[0]["net_worth"])) if pts[0]["net_worth"] else None))


def take_snapshot(db, ctx, a: Access, as_at=None, source="manual") -> M.InvSnapshot:
    a.require("edit")
    d = core.parse_date(as_at, "as_at") or date.today()
    n = networth(db, ctx, d)
    s = db.query(M.InvSnapshot).filter_by(org_id=ctx.org.id, as_at=d).first()
    if s is None:
        s = M.InvSnapshot(org_id=ctx.org.id, as_at=d, total_assets=n["total_assets"], total_liabilities=n["total_liabilities"], net_worth=n["net_worth"], detail=core.plain(dict(assets=n["assets_by_group"], liabilities=n["liabilities_by_group"], warnings=n["warnings"])), source=source)
        db.add(s)
    else:
        s.total_assets, s.total_liabilities, s.net_worth, s.source = n["total_assets"], n["total_liabilities"], n["net_worth"], source
        s.detail = core.plain(dict(assets=n["assets_by_group"], liabilities=n["liabilities_by_group"], warnings=n["warnings"]))
    db.flush()
    core.record(db, ctx, "networth.snapshot", "inv_snapshot", s.id, f"Net worth snapshot as at {d}: {n['net_worth']}", None, dict(net_worth=n["net_worth"]))
    return s


def import_snapshot(db, ctx, a: Access, as_at, assets, liabilities, net_worth, note: str = "") -> M.InvSnapshot:
    """A net worth figure recorded elsewhere (a statement, a spreadsheet, an earlier system) for a date before AccFino held the detail. Replaces a snapshot on the same date."""
    a.require("edit")
    d = core.parse_date(as_at, "as_at")
    if d is None or d > date.today():
        raise InvError("as_at is required and cannot be in the future")
    ta, tl, nw = core.num(assets, "total_assets", required=True), core.num(liabilities, "total_liabilities", required=True), core.num(net_worth, "net_worth", required=True, allow_negative=True)
    if abs((ta - tl) - nw) > D("0.01"):
        raise InvError(f"net_worth ({nw}) must equal total_assets less total_liabilities ({q2(ta - tl)})")
    s = db.query(M.InvSnapshot).filter_by(org_id=ctx.org.id, as_at=d).first()
    before = None if s is None else dict(net_worth=str(s.net_worth))
    if s is None:
        s = M.InvSnapshot(org_id=ctx.org.id, as_at=d, total_assets=ta, total_liabilities=tl, net_worth=nw, source="import", detail=dict(imported=True, note=(note or "")[:200]))
        db.add(s)
    else:
        s.total_assets, s.total_liabilities, s.net_worth, s.source, s.detail = ta, tl, nw, "import", dict(imported=True, note=(note or "")[:200])
    db.flush()
    core.record(db, ctx, "networth.snapshot_import", "inv_snapshot", s.id, f"Imported net worth snapshot as at {d}: {nw}", before, dict(net_worth=str(nw)))
    return s


def snapshots(db, ctx):
    return [dict(id=s.id, as_at=s.as_at.isoformat(), total_assets=str(s.total_assets), total_liabilities=str(s.total_liabilities), net_worth=str(s.net_worth), source=s.source) for s in db.query(M.InvSnapshot).filter_by(org_id=ctx.org.id).order_by(M.InvSnapshot.as_at.desc())]
