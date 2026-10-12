"""GET /public/pricing - the live plans, add-ons and business domains for the public landing page (no sign-in).

Read-only and free of anything personal: only active plans/add-ons from the same catalogue the Subscriptions admin screen edits, so the website can never
disagree with what an organisation is actually offered. Prices are AUD per month, GST included."""
from fastapi import APIRouter, Depends, Response
from sqlalchemy.orm import Session

from accfino.core.subscription import service as S
from accfino.core.subscription.models import Addon, Plan
from accfino.shared.db.database import get_db

router = APIRouter()


def _names(mods) -> dict:
    """What a plan/add-on module list means in plain words: whole domains, single modules, or everything."""
    if "*" in (mods or []):
        return {"all": True, "domains": [], "modules": []}
    dom = {d[0]: d[1] for d in S.DOMAINS}
    mod = dict(S.CATALOGUE)
    return {"all": False,
            "domains": [dom[x[7:]] for x in mods if isinstance(x, str) and x.startswith("domain:") and x[7:] in dom],
            "modules": [mod[x] for x in mods if x in mod]}


@router.get("")
def public_pricing(response: Response, db: Session = Depends(get_db)):
    S.ensure_catalogue(db)
    db.commit()
    response.headers["Cache-Control"] = "public, max-age=300"
    plans = []
    for p in db.query(Plan).filter_by(is_active=True).order_by(Plan.sort_order, Plan.id):
        plans.append({"id": p.id, "name": p.name, "description": p.description or "", "price_monthly": float(p.price_monthly), "price_yearly": float(p.price_yearly),
                      "seat_limit": p.seat_limit, **_names(S._loads(p.modules))})
    addons = []
    for a in db.query(Addon).filter_by(is_active=True).order_by(Addon.sort_order, Addon.id):
        if (a.extra_seats or 0) > 0:                       # user packs are arranged with the AccFino team for each organisation: never listed with a public price
            continue
        addons.append({"id": a.id, "name": a.name, "description": a.description or "", "price_monthly": float(a.price_monthly), "extra_seats": a.extra_seats or 0,
                       **_names(S._loads(a.modules))})
    return {"currency": "AUD", "gst_included": True, "yearly_months": S.YEARLY_MONTHS, "plans": plans, "addons": addons,
            "extra_users": "Every plan is for 1 user. Need more? A user pack is arranged with the AccFino team to suit your organisation.",
            "domains": [{"id": i, "name": n, "module_count": len(ms)} for i, n, ms in S.DOMAINS]}
