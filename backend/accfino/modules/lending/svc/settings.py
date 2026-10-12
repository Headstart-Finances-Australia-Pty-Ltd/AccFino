"""Organisation policy: overrides of the assessment policy (buffer, DTI, LTI, LVR...) and the minimum cash buffer treasury plans against. Needs the configuration permission to change."""
from decimal import Decimal
from typing import Dict

from accfino.modules.lending import lend_models as M
from accfino.modules.lending.engine import credit as C
from accfino.modules.lending.svc.core import Access, LendError, audit, num, plain, q2

RANGES = dict(dti_limit=(0.1, 0.8), serviceability_buffer=(0.0, 0.1), min_umi=(0.0, 5000.0), max_lti=(1.0, 12.0), lvr_cap=(0.3, 0.95), min_months=(1, 12), min_classification=(0.5, 1.0), gambling_threshold=(0.0, 0.3), min_recurring_share=(0.0, 1.0))


def _row(db, ctx) -> M.LendSettings:
    r = db.query(M.LendSettings).filter_by(org_id=ctx.org.id).first()
    if r is None:
        r = M.LendSettings(org_id=ctx.org.id, policy={}, min_cash_buffer=0)
        db.add(r)
        db.flush()
    return r


def policy(db, ctx) -> Dict:
    """The policy the engine uses for this organisation: the defaults with the organisation's overrides."""
    return dict(C.POLICY, **{k: v for k, v in (_row(db, ctx).policy or {}).items() if k in RANGES})


def get(db, ctx, a: Access) -> Dict:
    a.require("view")
    r = _row(db, ctx)
    p = policy(db, ctx)
    return dict(policy={k: p[k] for k in RANGES}, defaults={k: C.POLICY[k] for k in RANGES}, ranges=RANGES, min_cash_buffer=r.min_cash_buffer,
                note="These are indicative guides taken from public lending guidance (ASIC RG 209, APRA). Your lending policy and the lender's credit policy govern.")


def save(db, ctx, a: Access, body: dict) -> Dict:
    a.require("configure")
    r = _row(db, ctx)
    before = dict(policy=dict(r.policy or {}), min_cash_buffer=r.min_cash_buffer)
    new = dict(r.policy or {})
    for k, v in (body.get("policy") or {}).items():
        if k not in RANGES:
            raise LendError(f"'{k}' is not a policy setting you can change ({', '.join(RANGES)})")
        if v in (None, ""):
            new.pop(k, None)                                                           # back to the default
            continue
        lo, hi = RANGES[k]
        x = float(num(v, k))
        if not (lo <= x <= hi):
            raise LendError(f"{k} must be between {lo:g} and {hi:g}")
        new[k] = int(x) if k == "min_months" else x
    r.policy = new
    if body.get("min_cash_buffer") not in (None, ""):
        r.min_cash_buffer = q2(num(body["min_cash_buffer"], "min_cash_buffer"))
    r.updated_by = ctx.user_id
    db.flush()
    audit(db, ctx, "settings.save", "lend_settings", ctx.org.id, before=before, after=dict(policy=new, min_cash_buffer=r.min_cash_buffer))
    return get(db, ctx, a)
