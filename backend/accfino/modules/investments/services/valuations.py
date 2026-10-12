"""Dated values of properties, other assets and the balances of liabilities. The latest on or before a date is the value at that date."""
from datetime import date
from typing import Optional

from accfino.modules.investments.engine.money import q2
from accfino.modules.investments.models import inv as M
from accfino.modules.investments.services import core
from accfino.modules.investments.services.core import Access, InvError, NotFound

_OWNER = {"property": M.InvProperty, "other_asset": M.InvOtherAsset, "liability": M.InvLiability}


def _owner(db, ctx, owner_type, owner_id):
    if owner_type not in _OWNER:
        raise InvError(f"owner_type must be one of {', '.join(_OWNER)}")
    o = db.query(_OWNER[owner_type]).filter_by(org_id=ctx.org.id, id=owner_id).first()
    if o is None:
        raise NotFound(owner_type.replace("_", " ").title())
    return o


def latest(db, ctx, owner_type: str, owner_id: int, as_at: date) -> Optional[M.InvValuation]:
    return (db.query(M.InvValuation).filter(M.InvValuation.org_id == ctx.org.id, M.InvValuation.owner_type == owner_type, M.InvValuation.owner_id == owner_id, M.InvValuation.as_at <= as_at)
            .order_by(M.InvValuation.as_at.desc()).first())


def add(db, ctx, a: Access, owner_type: str, owner_id: int, as_at, value, basis: str = "", source: str = "manual") -> M.InvValuation:
    a.require("edit")
    o = _owner(db, ctx, owner_type, owner_id)
    d = core.parse_date(as_at, "as_at")
    if d is None or d > date.today():
        raise InvError("as_at is required and cannot be in the future")
    v = core.num(value, "value", required=True)
    row = db.query(M.InvValuation).filter_by(org_id=ctx.org.id, owner_type=owner_type, owner_id=owner_id, as_at=d).first()
    before = None if row is None else dict(value=str(row.value), basis=row.basis)
    if row is None:
        row = M.InvValuation(org_id=ctx.org.id, owner_type=owner_type, owner_id=owner_id, as_at=d, value=v, basis=(basis or "")[:40] or None, source=source, created_by=ctx.user_id)
        db.add(row)
    else:
        row.value, row.basis, row.source = v, (basis or "")[:40] or None, source
    db.flush()
    core.record(db, ctx, "valuation.set", f"inv_{owner_type}", owner_id, f"{getattr(o, 'name', '')}: {'balance' if owner_type == 'liability' else 'value'} {v} as at {d}", before, dict(value=str(v), as_at=d))
    return row


def history(db, ctx, owner_type: str, owner_id: int):
    _owner(db, ctx, owner_type, owner_id)
    return [dict(id=r.id, as_at=r.as_at.isoformat(), value=str(r.value), basis=r.basis, source=r.source) for r in db.query(M.InvValuation).filter_by(org_id=ctx.org.id, owner_type=owner_type, owner_id=owner_id).order_by(M.InvValuation.as_at.desc())]


def remove(db, ctx, a: Access, vid: int):
    a.require("edit")
    r = db.query(M.InvValuation).filter_by(org_id=ctx.org.id, id=vid).first()
    if r is None:
        raise NotFound("Valuation")
    core.record(db, ctx, "valuation.delete", f"inv_{r.owner_type}", r.owner_id, f"Valuation {r.value} as at {r.as_at} deleted", None, None)
    db.delete(r)
    db.flush()
