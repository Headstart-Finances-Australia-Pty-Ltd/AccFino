"""Payroll audit trail: who, when, what, on which record, before / after. Sensitive values are scrubbed before they are stored."""
import datetime as _dt
import decimal
from typing import Optional

from accfino.modules.payroll.models.payroll import PayAudit
from accfino.modules.payroll.services.protect import scrub


def _plain(v):
    if isinstance(v, (_dt.date, _dt.datetime)):
        return v.isoformat()
    if isinstance(v, decimal.Decimal):
        return str(v)
    if isinstance(v, dict):
        return {k: _plain(x) for k, x in v.items()}
    if isinstance(v, (list, tuple)):
        return [_plain(x) for x in v]
    return v


def record(db, ctx, action: str, entity_type: str, entity_id=None, label: str = "", summary: str = "", before: Optional[dict] = None,
           after: Optional[dict] = None) -> PayAudit:
    row = PayAudit(org_id=ctx.org.id, user_id=ctx.user_id, username=ctx.username, action=action, entity_type=entity_type,
                   entity_id=None if entity_id is None else str(entity_id), entity_label=(label or "")[:200], summary=(summary or "")[:500],
                   before=_plain(scrub(before)), after=_plain(scrub(after)))
    db.add(row)
    return row


def diff(old: dict, new: dict, keys) -> tuple:
    """(before, after) containing only the fields that changed."""
    b, a = {}, {}
    for k in keys:
        if old.get(k) != new.get(k):
            b[k], a[k] = old.get(k), new.get(k)
    return b, a
