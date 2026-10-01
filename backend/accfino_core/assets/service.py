"""
Fixed asset service.

  register(...)         add an asset to the register. Does not post anything - the cost is assumed
                        already in the ledger (typically a bill coded to the asset account).
  run_depreciation(...)  for each active asset, work out the TOTAL depreciation that should have
                        accumulated by `as_at` (never from the previous run's amount - always
                        recomputed from the purchase date, so per-run rounding can never drift),
                        and post the difference against what is already on the books.
  dispose(...)           runs depreciation up to the disposal date, then clears the asset and its
                        accumulated depreciation out of the ledger, banks the proceeds, and posts
                        the resulting gain or loss.
  register_report / control   the asset register with book values, and a check that the register's
                        totals agree with the ledger balances of the accounts assets are coded to.
"""
from collections import defaultdict
from datetime import date
from decimal import ROUND_HALF_UP, Decimal

from sqlalchemy import func

from accfino_core import models as m
from accfino_core.assets import models as a
from accfino_core.books.common import BooksError, as_date, bank_account, get_account, money, system_acct
from accfino_core.ledger import service as L

Z = Decimal("0.00")


def _number(db, org):
    n = db.query(func.count(a.FixedAsset.id)).filter_by(org_id=org.id).scalar() + 1
    while db.query(a.FixedAsset.id).filter_by(org_id=org.id, number=f"FA-{n:04d}").first():
        n += 1
    return f"FA-{n:04d}"


def _months_between(start: date, end: date) -> int:
    """Whole calendar months from the purchase month to `end`'s month, inclusive of both -
    e.g. bought 5 Jul, run to 30 Sep = Jul, Aug, Sep = 3 months. A part-month still counts as one."""
    return max(0, (end.year * 12 + end.month) - (start.year * 12 + start.month) + 1)


def _depreciable_base(asset):
    return money(asset.cost) - money(asset.residual_value)


def cumulative_depreciation(asset, as_at: date) -> Decimal:
    """Total depreciation that should be on the books by `as_at`, from scratch every time (so
    rounding from one run to the next never compounds into drift). Capped at cost less residual."""
    base = _depreciable_base(asset)
    if base <= 0 or as_at < asset.purchase_date:
        return money(asset.opening_accumulated_depreciation)
    months = _months_between(asset.purchase_date, as_at)
    if asset.method == "straight_line":
        life = asset.effective_life_months or 1
        total = base * min(months, life) / life
    else:                                                          # diminishing_value: compounds monthly on the written-down value
        life_months_cap = 1200                                     # a sane ceiling (100 years) so a tiny rate can't loop forever
        rate = (asset.dv_rate_pct or Decimal(0)) / Decimal(100) / Decimal(12)
        wdv = base - money(asset.opening_accumulated_depreciation)
        total = money(asset.opening_accumulated_depreciation)
        for _ in range(min(months, life_months_cap)):
            if wdv <= 0:
                break
            step = money(wdv * rate)
            wdv -= step
            total += step
    return min(money(total), base)


def register(db, org, user_id, data: dict):
    asset_acc = get_account(db, org, data.get("asset_account"), what="Asset account")
    dep_acc = get_account(db, org, data.get("depreciation_account"), what="Accumulated depreciation account")
    if asset_acc.id == dep_acc.id:
        raise BooksError("The asset account and its accumulated depreciation account must be different")
    exp_ref = data.get("expense_account")
    exp_acc = get_account(db, org, exp_ref, what="Depreciation expense account") if exp_ref else _default_expense_account(db, org)
    method = data.get("method") or "straight_line"
    if method not in a.METHODS:
        raise BooksError("method must be straight_line or diminishing_value")
    cost = money(data.get("cost"))
    if cost <= 0:
        raise BooksError("Cost must be greater than zero")
    residual = money(data.get("residual_value") or 0)
    if residual < 0 or residual >= cost:
        raise BooksError("Residual value must be zero or more, and less than the cost")
    if method == "straight_line" and not data.get("effective_life_months"):
        raise BooksError("Straight-line assets need an effective life in months")
    if method == "diminishing_value" and not data.get("dv_rate_pct"):
        raise BooksError("Diminishing-value assets need an annual rate")
    opening = money(data.get("opening_accumulated_depreciation") or 0)
    if opening < 0 or opening > cost - residual:
        raise BooksError("Opening accumulated depreciation cannot exceed cost less residual value")
    asset = a.FixedAsset(
        org_id=org.id, number=(data.get("number") or "").strip() or _number(db, org), name=data["name"].strip(),
        category=data.get("category"), asset_account_id=asset_acc.id, depreciation_account_id=dep_acc.id, expense_account_id=exp_acc.id,
        purchase_date=as_date(data.get("purchase_date"), "purchase date"), cost=cost, residual_value=residual, method=method,
        effective_life_months=data.get("effective_life_months"), dv_rate_pct=data.get("dv_rate_pct"),
        opening_accumulated_depreciation=opening, accumulated_depreciation=opening, notes=data.get("notes"), created_by=user_id)
    db.add(asset)
    db.flush()
    return asset


def _default_expense_account(db, org):
    acc = db.query(m.LedgerAccount).filter(m.LedgerAccount.org_id == org.id, m.LedgerAccount.code == "416").first()
    if acc is None:
        raise BooksError("No depreciation expense account found (expected account 416); pass expense_account explicitly", 422)
    return acc


def update(db, org, asset, data: dict):
    if asset.status != "active":
        raise BooksError("A disposed asset cannot be edited", 409)
    if "name" in data and data["name"]:
        asset.name = data["name"].strip()
    if "category" in data:
        asset.category = data["category"]
    if "notes" in data:
        asset.notes = data["notes"]
    if asset.runs:
        # once depreciation has been posted, changing the cost/method/life would silently rewrite history - refuse it
        locked = {"cost", "residual_value", "method", "effective_life_months", "dv_rate_pct", "opening_accumulated_depreciation", "purchase_date"}
        if locked & data.keys():
            raise BooksError("Depreciation has already been posted for this asset; its cost, method and dates can no longer be changed", 409)
    else:
        for f in ("purchase_date",):
            if data.get(f):
                setattr(asset, f, as_date(data[f], f))
        for f in ("cost", "residual_value", "opening_accumulated_depreciation"):
            if data.get(f) is not None:
                setattr(asset, f, money(data[f]))
        if data.get("method"):
            asset.method = data["method"]
        if data.get("effective_life_months") is not None:
            asset.effective_life_months = data["effective_life_months"]
        if data.get("dv_rate_pct") is not None:
            asset.dv_rate_pct = data["dv_rate_pct"]
        asset.accumulated_depreciation = money(asset.opening_accumulated_depreciation)
    db.flush()
    return asset


def delete(db, asset):
    if asset.runs:
        raise BooksError("This asset has posted depreciation; dispose of it instead of deleting it", 409)
    db.delete(asset)
    db.flush()


def run_depreciation(db, org, user_id, *, as_at: date, asset_ids=None):
    q = db.query(a.FixedAsset).filter_by(org_id=org.id, status="active")
    if asset_ids:
        q = q.filter(a.FixedAsset.id.in_(asset_ids))
    results, skipped = [], []
    for asset in q.order_by(a.FixedAsset.id):
        if as_at < asset.purchase_date:
            skipped.append(dict(asset_id=asset.id, number=asset.number, reason="run date is before the purchase date"))
            continue
        target = cumulative_depreciation(asset, as_at)
        delta = target - money(asset.accumulated_depreciation)
        if delta <= 0:
            skipped.append(dict(asset_id=asset.id, number=asset.number, reason="fully depreciated" if target >= _depreciable_base(asset) else "nothing new to post"))
            continue
        try:
            j = L.post_journal(db, org, journal_date=as_at,
                               lines=[{"account_id": asset.expense_account_id, "debit": delta, "description": f"Depreciation - {asset.name} ({asset.number})"},
                                      {"account_id": asset.depreciation_account_id, "credit": delta, "description": f"Depreciation - {asset.name} ({asset.number})"}],
                               narration=f"Depreciation to {as_at.isoformat()} - {asset.name} ({asset.number})",
                               source_type="asset_depreciation", source_ref=f"asset:{asset.id}", created_by=user_id)
        except L.LedgerError as e:
            raise BooksError(str(e), 422)
        asset.accumulated_depreciation = target
        asset.last_depreciation_date = as_at
        db.add(a.DepreciationRun(org_id=org.id, asset_id=asset.id, as_at=as_at, amount=delta, accumulated_after=target, journal_id=j.id, created_by=user_id))
        results.append(dict(asset_id=asset.id, number=asset.number, name=asset.name, amount=str(delta), accumulated_depreciation=str(target),
                            book_value=str(money(asset.cost) - target), journal_id=j.id))
    db.flush()
    return dict(as_at=as_at.isoformat(), posted=results, skipped=skipped)


def dispose(db, org, user_id, asset, *, disposal_date, proceeds, bank_ref=None):
    if asset.status != "active":
        raise BooksError("This asset has already been disposed of", 409)
    disposal_date = as_date(disposal_date, "disposal date")
    if disposal_date < asset.purchase_date:
        raise BooksError("Disposal date cannot be before the purchase date")
    if asset.last_depreciation_date is None or asset.last_depreciation_date < disposal_date:
        run_depreciation(db, org, user_id, as_at=disposal_date, asset_ids=[asset.id])
    book_value = money(asset.cost) - money(asset.accumulated_depreciation)
    proceeds = money(proceeds or 0)
    gain = proceeds - book_value
    lines = [{"account_id": asset.depreciation_account_id, "debit": asset.accumulated_depreciation, "description": f"Dispose {asset.number}"},
             {"account_id": asset.asset_account_id, "credit": asset.cost, "description": f"Dispose {asset.number}"}]
    if proceeds:
        bank = bank_account(db, org, bank_ref) if bank_ref else None
        if bank is None:
            raise BooksError("A bank account is required when disposal proceeds are greater than zero")
        lines.append({"account_id": bank.id, "debit": proceeds, "description": f"Proceeds - {asset.number}"})
    disposal_acc = system_acct(db, org, "asset_disposal")
    if gain > 0:
        lines.append({"account_id": disposal_acc.id, "credit": gain, "description": f"Gain on disposal - {asset.number}"})
    elif gain < 0:
        lines.append({"account_id": disposal_acc.id, "debit": -gain, "description": f"Loss on disposal - {asset.number}"})
    try:
        j = L.post_journal(db, org, journal_date=disposal_date, lines=lines, narration=f"Disposal of {asset.name} ({asset.number})",
                           source_type="asset_disposal", source_ref=f"asset:{asset.id}", created_by=user_id)
    except L.LedgerError as e:
        raise BooksError(str(e), 422)
    asset.status, asset.disposal_date, asset.disposal_proceeds, asset.disposal_journal_id = "disposed", disposal_date, proceeds, j.id
    db.flush()
    return dict(journal_id=j.id, book_value=str(book_value), proceeds=str(proceeds), gain_or_loss=str(gain))


def asset_dict(a_):
    book_value = money(a_.cost) - money(a_.accumulated_depreciation)
    return dict(id=a_.id, number=a_.number, name=a_.name, category=a_.category, asset_account_id=a_.asset_account_id,
                asset_account=f"{a_.asset_account.code} {a_.asset_account.name}" if a_.asset_account else None,
                depreciation_account_id=a_.depreciation_account_id,
                depreciation_account=f"{a_.depreciation_account.code} {a_.depreciation_account.name}" if a_.depreciation_account else None,
                expense_account_id=a_.expense_account_id, expense_account=f"{a_.expense_account.code} {a_.expense_account.name}" if a_.expense_account else None,
                purchase_date=a_.purchase_date.isoformat(), cost=str(a_.cost), residual_value=str(a_.residual_value), method=a_.method,
                effective_life_months=a_.effective_life_months, dv_rate_pct=str(a_.dv_rate_pct) if a_.dv_rate_pct is not None else None,
                opening_accumulated_depreciation=str(a_.opening_accumulated_depreciation), accumulated_depreciation=str(a_.accumulated_depreciation),
                book_value=str(book_value), last_depreciation_date=a_.last_depreciation_date.isoformat() if a_.last_depreciation_date else None,
                status=a_.status, disposal_date=a_.disposal_date.isoformat() if a_.disposal_date else None,
                disposal_proceeds=str(a_.disposal_proceeds) if a_.disposal_proceeds is not None else None,
                disposal_journal_id=a_.disposal_journal_id, notes=a_.notes)


def register_report(db, org, as_at: date = None):
    q = db.query(a.FixedAsset).filter_by(org_id=org.id).order_by(a.FixedAsset.number)
    rows = [asset_dict(x) for x in q]
    active = [r for r in rows if r["status"] == "active"]
    totals = dict(cost=sum((Decimal(r["cost"]) for r in active), Z), accumulated_depreciation=sum((Decimal(r["accumulated_depreciation"]) for r in active), Z),
                  book_value=sum((Decimal(r["book_value"]) for r in active), Z))
    return dict(assets=rows, totals={k: str(v) for k, v in totals.items()})


def control(db, org, as_at: date):
    """Group active assets by (asset account, depreciation account) and compare the register's totals
    against those two accounts' ledger balances - the same kind of check as the AR/AP control report."""
    rows = db.query(a.FixedAsset).filter_by(org_id=org.id, status="active").all()
    by_pair = defaultdict(lambda: dict(cost=Z, accumulated=Z))
    for asset in rows:
        key = (asset.asset_account_id, asset.depreciation_account_id)
        by_pair[key]["cost"] += money(asset.cost)
        by_pair[key]["accumulated"] += money(asset.accumulated_depreciation)
    out = []
    all_ok = True
    for (acc_id, dep_id), tot in by_pair.items():
        acc, dep = db.get(m.LedgerAccount, acc_id), db.get(m.LedgerAccount, dep_id)
        led_cost = money(db.query(func.coalesce(func.sum(m.JournalLine.debit - m.JournalLine.credit), 0)).join(m.Journal, m.Journal.id == m.JournalLine.journal_id)
                         .filter(m.JournalLine.org_id == org.id, m.JournalLine.account_id == acc_id, m.Journal.journal_date <= as_at).scalar())
        led_dep = -money(db.query(func.coalesce(func.sum(m.JournalLine.debit - m.JournalLine.credit), 0)).join(m.Journal, m.Journal.id == m.JournalLine.journal_id)
                         .filter(m.JournalLine.org_id == org.id, m.JournalLine.account_id == dep_id, m.Journal.journal_date <= as_at).scalar())
        ok = (led_cost == tot["cost"]) and (led_dep == tot["accumulated"])
        all_ok = all_ok and ok
        out.append(dict(asset_account=f"{acc.code} {acc.name}", depreciation_account=f"{dep.code} {dep.name}",
                        register_cost=str(tot["cost"]), ledger_cost=str(led_cost), register_accumulated=str(tot["accumulated"]),
                        ledger_accumulated=str(led_dep), reconciled=ok))
    return dict(as_at=as_at.isoformat(), pairs=out, reconciled=all_ok)
