"""ONE price list.

The organisation plans (table sub_plans, edited in Admin Console > Pricing) are the only source of truth. Everything older is DERIVED from them or relabelled to them,
so no screen and no table can show a different plan or price:

  * pricing_plans   - the old per-user plan table (Vault, Ultra ...). Now a mirror: rewritten from the active organisation plans at every start and after every plan edit.
  * organisations still on a retired v1 plan (starter / growth / premium) - moved to the smallest new plan that keeps their modules and fits their users.
  * the AccFino platform administrator's organisation(s) - always on the top plan, active, no end date.
  * licence_records.plan_id / licence_type - relabelled from the old slugs (base, premium ...) to the new plan ids.

Safe to run on every start: each step only changes what is out of line and reports what it changed.
"""
import json
import logging
from datetime import date
from decimal import Decimal
from typing import Optional

from sqlalchemy import text
from sqlalchemy.orm import Session

from accfino.core import models as m
from accfino.core.subscription import service as S
from accfino.core.subscription.models import OrgSubscription, Plan

log = logging.getLogger("accfino.align")

RETIRED_V1 = ("starter", "growth", "premium")          # the first generation of organisation plans (note: 'starter' also existed briefly as the entry plan before it was renamed Essential)
# Every older plan -> the new plan (+ add-ons that keep what that plan gave them). Used for per-user licence records and for organisations that have no plan yet.
#   Vault (base)          -> Essential       Ultra (premium) -> Ultra       Accounting Pro / cash flow -> Business (books + planning)
#   Payroll plans         -> Essential + Payroll          Taxation / trading -> Essential + Tax + Assets & Investments        Smart Lending -> Essential + Lending
LEGACY_TO_NEW = {
    "base": ("essential", []), "vault": ("essential", []), "accounting_starter": ("essential", []), "reconciliation": ("essential", []), "invoice": ("essential", []), "demo": ("essential", []),
    "starter": ("essential", []), "essentials": ("essential", []),
    "accounting_pro": ("business", []), "basic": ("business", []), "cashflow": ("business", []),
    "payroll_essential": ("essential", ["addon-payroll"]), "payroll_business": ("essential", ["addon-payroll"]),
    "taxation_basic": ("essential", ["addon-tax", "addon-assets"]), "taxation_complete": ("essential", ["addon-tax", "addon-assets"]), "trading": ("essential", ["addon-tax", "addon-assets"]),
    "lending_basic": ("essential", ["addon-lending"]),
    "premium": ("ultra", []), "ultra": ("ultra", []), "admin": ("ultra", []), "complete": ("ultra", []),
}
LICENCE_MAP = {k: v[0] for k, v in LEGACY_TO_NEW.items()}      # kept for the licence-record relabelling
PACK_PREFIX = "addon-pack-org-"                                # a user pack arranged with the AccFino team for ONE organisation


# ---------------------------------------------------------------------------------------------------------------- legacy shape --
def legacy_modules(allowed: set) -> list:
    """The old per-user module keys (dashboard, reconciliation, trading, cash-flow, invoice, payroll, lending ...) that correspond to a set of module ids."""
    out = ["dashboard"] if "dashboard-accounting" in allowed else []
    for key, ids in (("accounting", {"general-ledger", "sales", "purchases", "financial-reports"}), ("reconciliation", {"reconciliation"}), ("invoice", {"sales"}),
                     ("cash-flow", {"cash-flow-forecasting"}), ("payroll", set(S.DOMAIN_MODULES["payroll_workforce"])),
                     ("trading", set(S.DOMAIN_MODULES["tax_compliance"]) | set(S.DOMAIN_MODULES["assets_investments"])), ("lending", set(S.DOMAIN_MODULES["lending_treasury"]))):
        if allowed & ids and key not in out:
            out.append(key)
    return out


def plan_features(plan_modules, seat_limit) -> list:
    dom = {d[0]: d[1] for d in S.DOMAINS}
    mod = dict(S.CATALOGUE)
    feats = ["Unlimited users" if seat_limit is None else f"{seat_limit} {'user' if seat_limit == 1 else 'users'}", "Unlimited invoices and bills", "More users: a pack arranged with the AccFino team"]
    if "*" in plan_modules:
        feats.append("Every business domain, including future ones")
    else:
        feats += [f"{dom[x[7:]]} (whole domain)" for x in plan_modules if isinstance(x, str) and x.startswith("domain:") and x[7:] in dom]
        feats += [mod[x] for x in plan_modules if x in mod]
    return feats


def _cents(x) -> int:
    return int((Decimal(str(x)) * 100).to_integral_value())


def _legacy_fields(p, i: int) -> dict:
    mods = S._loads(p.modules) if not isinstance(p, dict) else p["modules"]
    seat = p.seat_limit if not isinstance(p, dict) else p["seat_limit"]
    allowed = S.expand(mods)
    get = (lambda k: getattr(p, k)) if not isinstance(p, dict) else (lambda k: p[k])
    return {"name": get("name"), "description": (get("description") or "")[:1000], "price_monthly": _cents(get("price_monthly")), "price_yearly": _cents(get("price_yearly")),
            "badge": "Best value" if get("id") == "business" else None, "highlight": get("id") == "business", "category": "plan",
            "features": plan_features(mods, seat), "modules": legacy_modules(allowed), "price_effective_from": date.today().isoformat(), "sort_order": i}


def legacy_plans_dict() -> dict:
    """The shipped plans in the old pricing_plans shape (the fallback when the table cannot be read)."""
    out = {}
    for i, p in enumerate(S.DEFAULT_PLANS):
        f = _legacy_fields(p, i)
        f.pop("sort_order")
        out[p["id"]] = f
    return out


# --------------------------------------------------------------------------------------------------------------------- steps --
def sync_pricing_plans(db: Session) -> dict:
    """Rewrite the legacy pricing_plans table from the active organisation plans (adds/updates those, removes the rest)."""
    try:
        from accfino.core.subscription.pricing_model import PricingPlan
        with db.begin_nested():                                        # a missing table fails here, inside a savepoint, without poisoning the caller's transaction
            db.query(PricingPlan).limit(1).all()
    except Exception as e:
        return {"skipped": "pricing_plans table not there yet" if "pricing_plans" in str(e) else str(e)[:120]}
    plans = db.query(Plan).filter_by(is_active=True).order_by(Plan.sort_order, Plan.id).all()
    if not plans:
        return {"skipped": "no active plans"}
    for i, p in enumerate(plans):
        row = db.get(PricingPlan, p.id)
        if row is None:
            row = PricingPlan(slug=p.id)
            db.add(row)
        for k, v in _legacy_fields(p, i).items():
            setattr(row, k, v)
    stale = [r.slug for r in db.query(PricingPlan).all() if r.slug not in {p.id for p in plans}]
    for slug in stale:
        db.delete(db.get(PricingPlan, slug))
    db.flush()
    return {"plans": [p.id for p in plans], "removed": stale}


def top_plan(db: Session) -> Optional[Plan]:
    """The highest plan: the active one with the highest monthly price."""
    return max(db.query(Plan).filter_by(is_active=True).all(), key=lambda p: (Decimal(p.price_monthly), -p.sort_order), default=None)


def _used_seats(db: Session, org_id: int) -> int:
    """Active members + codes waiting to be used. Counted directly (the usual helper reads the plan, and this runs while the plans are being replaced)."""
    from datetime import datetime
    from accfino.core.tenancy.models import OrgInvite
    active = db.query(m.OrgMembership).filter_by(org_id=org_id).filter(m.OrgMembership.suspended_at.is_(None)).count()
    pending = 0
    for i in db.query(OrgInvite).filter_by(org_id=org_id).filter(OrgInvite.revoked_at.is_(None), OrgInvite.expires_at > datetime.utcnow()):
        pending += max(0, (i.max_uses or 1) - (i.used_count or 0))
    return active + pending


def pick_plan(needed: set, plans=None) -> dict:
    """The cheapest of the four plans that includes every module in `needed` (the biggest one if none does). Every plan is for 1 user: extra users are a pack."""
    plans = plans or sorted(S.DEFAULT_PLANS, key=lambda p: Decimal(p["price_monthly"]))
    for p in plans:
        if needed <= S.expand(p["modules"]):
            return p
    return plans[-1]


def _owner_licence_plan(db: Session, org_id: int) -> str:
    """The old per-user plan slug of the organisation's owner (Vault, Ultra ...), or '' if there is none."""
    try:
        from accfino.core.subscription.licence import LicenceRecord
    except Exception:
        return ""
    mem = db.query(m.OrgMembership).filter_by(org_id=org_id).order_by((m.OrgMembership.role == m.ADMIN_ROLE).desc(), m.OrgMembership.id).first()
    if mem is None:
        return ""
    lic = db.query(LicenceRecord).filter(LicenceRecord.user_id == mem.user_id).first()
    return (lic.plan_id or lic.licence_type or "") if lic is not None else ""


def add_feature_to_plans(db: Session, fid: str) -> list:
    """Add a plan-level function (e.g. 'open-banking') to every plan that does not already include it ('*' includes everything). One-off, so nothing an administrator removes later comes back."""
    done = []
    for p in db.query(Plan).all():
        mods = S._loads(p.modules)
        if "*" not in mods and fid not in mods:
            p.modules = json.dumps(mods + [fid]); done.append(p.id)
    db.flush()
    return done


def _seat_addons(db: Session) -> dict:
    from accfino.core.subscription.models import Addon
    return {a.id: a for a in db.query(Addon).all() if (a.extra_seats or 0) > 0}


def migrate_catalogue(db: Session, have: str = "0") -> dict:
    """One-off (catalogue version 5): ONE price list - Essential / Business / Professional / Ultra, 1 user each, yearly = 11 months.
    Moves every organisation to those plans, deletes every older plan and the add-ons Books & Accounting now includes, renames Starter/Essentials -> Essential and
    Complete -> Ultra, turns existing extra users into a per-organisation pack (so nobody loses access; the AccFino team then arranges the pricing), switches enforcement on.
    `have` = the catalogue version this database was on. Never raises for odd data."""
    from accfino.core.subscription.models import Addon
    report = {"moved": [], "deleted_plans": [], "deleted_addons": [], "renamed": {}, "packs": []}
    defaults = {p["id"]: p for p in S.DEFAULT_PLANS}
    plans = {p.id: p for p in db.query(Plan).all()}

    # 1. which existing plans survive under a new id, and which are old?
    rename = {}
    if "essentials" in plans:
        rename["essentials"] = "essential"
    if "starter" in plans and have >= "4":                        # from version 4 on, 'starter' IS the entry plan; before that it was the retired first-generation Starter
        rename["starter"] = "essential"
    if "complete" in plans:
        rename["complete"] = "ultra"
    for old, new in list(rename.items()):
        if new in plans or new in rename.values() and list(rename.values()).count(new) > 1:
            rename.pop(old)                                       # the new id is already there: the old row is just an old plan
    old_ids = {pid for pid in plans if pid not in defaults and pid not in rename}

    # 2. organisations on an old plan move to the cheapest new plan that holds their modules
    moves = {}
    for sub in db.query(OrgSubscription).all():
        old = plans.get(sub.plan_id)
        if sub.plan_id in old_ids or old is None:
            need = S.expand(S._loads(old.modules)) if old is not None else set()
            pick = defaults["ultra"] if sub.plan_id == "premium" else pick_plan(need)
            moves[sub.org_id] = (sub.plan_id, pick["id"])
    for pid in sorted(old_ids):
        db.delete(plans[pid]); report["deleted_plans"].append(pid)
    db.flush()

    # 3. renames: plan rows, organisations, payment history, the default-plan setting
    for old, new in rename.items():
        row = db.get(Plan, old)
        if row is None:
            continue
        row.id = new
        db.flush()
        for sub in db.query(OrgSubscription).filter_by(plan_id=old).all():
            sub.plan_id = new
        from accfino.shared.contracts import registry
        registry.plan_renamed(db, old, new)                  # e.g. Billing re-points its payment history
        report["renamed"][old] = new
    cfgrow = db.get(m.SystemSetting, S.DEFAULT_PLAN_KEY)
    if cfgrow is not None and cfgrow.value in rename:
        cfgrow.value = rename[cfgrow.value]

    # 4. the four plans exist with the new definitions: name, text, modules and 1 user; yearly = 11 months unless an administrator set their own yearly price
    for p in S.DEFAULT_PLANS:
        row = db.get(Plan, p["id"])
        if row is None:
            db.add(S._plan_row(p))
            continue
        edited_yearly = Decimal(row.price_yearly) not in (Decimal(row.price_monthly) * 10, Decimal(row.price_monthly) * S.YEARLY_MONTHS)
        row.name, row.description, row.seat_limit, row.modules, row.sort_order, row.is_active = p["name"], p["description"], 1, json.dumps(p["modules"]), p["sort_order"], True
        if not edited_yearly:
            row.price_yearly = (Decimal(row.price_monthly) * S.YEARLY_MONTHS).quantize(Decimal("0.01"))
    db.flush()

    # 5. add-ons: the domain add-ons exist; the ones Books & Accounting now includes and the public seat packs are removed
    for a in S.DEFAULT_ADDONS:
        if db.get(Addon, a["id"]) is None:
            db.add(S._addon_row(a))
    for aid in ("addon-inventory", "addon-expenses", "addon-fixed-assets", "addon-bulk-import"):
        row = db.get(Addon, aid)
        if row is not None:
            db.delete(row); report["deleted_addons"].append(aid)
    db.flush()
    seat_addons = _seat_addons(db)                                # addon-seat-1, addon-seats-5 and any other add-on that carries users
    for key, val in ((S.DEFAULT_PLAN_KEY, "essential"), (S.ENFORCED_KEY, "on")):
        row = db.get(m.SystemSetting, key)
        if row is None:
            db.add(m.SystemSetting(key=key, value=val))
        elif key == S.ENFORCED_KEY or row.value not in defaults:
            row.value = val
    db.flush()

    # 6. apply the plan moves, then give every organisation the users it already has as a pack (1 user is in the plan)
    for sub in db.query(OrgSubscription).all():
        if sub.org_id in moves:
            frm, to = moves[sub.org_id]
            sub.plan_id = to
            sub.notes = ((sub.notes + " | ") if sub.notes else "") + f"Moved from the old {frm} plan to the {to} plan"
            report["moved"].append({"org_id": sub.org_id, "from": frm, "to": to})
        ids = list(dict.fromkeys(S._loads(sub.addons)))
        carried_seats = sum(seat_addons[i].extra_seats for i in ids if i in seat_addons)
        carried_price = sum((Decimal(seat_addons[i].price_monthly) for i in ids if i in seat_addons), Decimal("0"))
        needed = max(carried_seats, _used_seats(db, sub.org_id) - 1, 0)
        if needed > 0:
            pid = PACK_PREFIX + str(sub.org_id)
            pack = db.get(Addon, pid)
            if pack is None:
                pack = Addon(id=pid, name="Extra users (arranged with AccFino)", description="Users beyond the 1 in the plan, as arranged with the AccFino team for this organisation.", price_monthly=Decimal("0.00"),
                             modules="[]", extra_seats=0, sort_order=100, is_active=True)
                db.add(pack)
            pack.extra_seats = needed
            pack.price_monthly = max(Decimal(pack.price_monthly), carried_price)          # what they paid for extra users before is kept; otherwise 0 until the team agrees a price
            sub.addons = json.dumps([i for i in ids if i not in seat_addons] + [pid])
            report["packs"].append({"org_id": sub.org_id, "extra_seats": needed, "price_monthly": str(pack.price_monthly)})
        elif any(i in seat_addons for i in ids):
            sub.addons = json.dumps([i for i in ids if i not in seat_addons])
    db.flush()
    for aid in list(seat_addons):                                 # the public seat packs leave the price list
        if not aid.startswith(PACK_PREFIX):
            row = db.get(Addon, aid)
            if row is not None:
                db.delete(row); report["deleted_addons"].append(aid)
    db.flush()
    report["more"] = run_alignment(db, _migrating=True)
    return report


def admin_organisations(db: Session) -> list:
    from accfino.core.identity.user import User
    ids = []
    for u in db.query(User).all():
        if any(r.name == "admin" for r in u.roles):
            ids += [r[0] for r in db.query(m.OrgMembership.org_id).filter(m.OrgMembership.user_id == u.id).all()]
    return sorted(set(ids))


def ensure_admin_top_plan(db: Session) -> list:
    """The AccFino administrator has the highest plan and full access: top plan, active, no trial and no end date."""
    top = top_plan(db)
    changed = []
    if top is None:
        return changed
    for org_id in admin_organisations(db):
        sub = db.get(OrgSubscription, org_id)
        if sub is None:
            db.add(OrgSubscription(org_id=org_id, plan_id=top.id, status="active", billing_period="yearly", addons="[]", notes="AccFino administrator - highest plan"))
            changed.append(org_id)
        elif (sub.plan_id, sub.status, sub.trial_ends, sub.period_end) != (top.id, "active", None, None):
            sub.plan_id, sub.status, sub.trial_ends, sub.period_end = top.id, "active", None, None
            changed.append(org_id)
    db.flush()
    return changed


def relabel_licences(db: Session) -> int:
    """licence_records.plan_id / licence_type: old slugs -> new plan ids. ('admin' stays as the licence TYPE of the administrator; 'demo' is not a plan.)"""
    try:
        from accfino.core.subscription.licence import LicenceRecord
    except Exception:
        return 0
    n = 0
    valid = {p.id for p in db.query(Plan).all()}
    for lic in db.query(LicenceRecord).all():
        for field, skip in (("plan_id", ()), ("licence_type", ("admin", "demo"))):
            cur = getattr(lic, field)
            if cur in LICENCE_MAP and cur not in skip and LICENCE_MAP[cur] in valid:
                setattr(lic, field, LICENCE_MAP[cur])
                n += 1
    db.flush()
    return n


def assign_missing_plans(db: Session) -> list:
    """Every organisation has a plan (visibility follows the plan). One with none gets the plan that matches its owner's old per-user plan (Vault -> Starter, Ultra -> Complete ...), else Starter."""
    out = []
    plans = {p.id for p in db.query(Plan).all()}
    addon_ids = {x.id for x in db.query(S.Addon).all()}
    for org in db.query(m.Organisation).all():
        if db.get(OrgSubscription, org.id) is not None:
            continue
        target, addons = LEGACY_TO_NEW.get(_owner_licence_plan(db, org.id), ("essential", []))
        if target not in plans:
            continue
        db.add(OrgSubscription(org_id=org.id, plan_id=target, status="active", billing_period="monthly", addons=json.dumps([a for a in addons if a in addon_ids]),
                               notes="Plan assigned when the plans were aligned"))
        out.append({"org_id": org.id, "plan": target, "addons": addons})
    db.flush()
    return out


def run_alignment(db: Session, _migrating: bool = False) -> dict:
    """Idempotent: the administrator on the top plan, every organisation on a plan, old licence labels relabelled, the old plan table mirroring the new plans. The caller commits."""
    if not _migrating:
        S.ensure_catalogue(db)
    out = {"admin_orgs": ensure_admin_top_plan(db), "assigned": assign_missing_plans(db), "licences_relabelled": relabel_licences(db), "mirror": sync_pricing_plans(db)}
    if out["admin_orgs"] or out["assigned"] or out["licences_relabelled"]:
        log.info("plans aligned: %s", {k: v for k, v in out.items() if k != "mirror"})
    return out


def build_my_plan(db: Session, user_id: int) -> Optional[dict]:
    """What the plan badge / upgrade prompts show for this person: their ORGANISATION's plan (the AccFino administrator always shows the top plan). None = no organisation."""
    from accfino.core.identity.user import User
    try:
        from accfino.core.subscription.licence import LicenceRecord
        lic = db.query(LicenceRecord).filter(LicenceRecord.user_id == user_id).first()
    except Exception:
        lic = None
    lic_mods = json.loads(lic.modules) if lic is not None and lic.modules else None
    start = (lic.start_date if lic is not None else "") or ""
    user = db.get(User, user_id)
    if user is not None and any(r.name == "admin" for r in user.roles):
        top = top_plan(db)
        if top is not None:
            return {"plan_id": top.id, "plan_name": top.name, "licence_type": top.id, "billing_period": "yearly", "start_date": start, "end_date": "9999-12-31",
                    "modules": lic_mods or legacy_modules(set(S.CATALOGUE_IDS)), "grandfathered": False, "status": "active"}
    rows = db.query(m.OrgMembership).filter_by(user_id=user_id).all()
    mem = next((r for r in rows if r.role == m.ADMIN_ROLE), rows[0] if rows else None)
    if mem is None:
        return None
    ent = S.entitlements(db, mem.org_id)
    return {"plan_id": ent["plan_id"] or "", "plan_name": ent["plan_name"], "licence_type": ent["plan_id"] or "", "billing_period": ent.get("billing_period") or "", "start_date": start,
            "end_date": ent.get("period_end") or ent.get("trial_ends") or "", "status": ent["status"], "grandfathered": bool(ent["grandfathered"]),
            "modules": lic_mods or legacy_modules(set(ent["modules"]))}

