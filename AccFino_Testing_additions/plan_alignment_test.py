"""ONE price list - Starter / Business / Professional / Complete - and visibility by plan.
Old plans (Vault, Ultra, Starter v1, Growth, Premium ...) are removed; people are moved to the new plans; Essential = ALL of Books & Accounting and nothing else.
Run from backend/:  PYTHONPATH=. python -m pytest ../AccFino_Testing_additions/plan_alignment_test.py -q"""
import json, os, sys
from datetime import date, datetime, timedelta
from decimal import Decimal
import pytest
sys.path.insert(0, os.path.dirname(__file__))
from csv_import_harness import make_db, make_org
from accfino_core import models as m
from accfino_core.subscription import align as AL, service as S
from accfino_core.subscription.models import Addon, OrgSubscription, Plan
from accfino_core.tenancy.models import OrgInvite
from db_app.models.base import Base as LegacyBase
from db_app.models.app_data import PricingPlan
from db_app.models.licence import LicenceRecord
from db_app.models import Role, User

ACCOUNTING = set(S.DOMAIN_MODULES["accounting"])


@pytest.fixture()
def env():
    db = make_db(); org, ctx = make_org(db); db.commit()
    LegacyBase.metadata.create_all(bind=db.get_bind(), tables=[PricingPlan.__table__, LicenceRecord.__table__])
    yield db, org, ctx
    db.close()


def new_org(db, name="Org"):
    o = m.Organisation(name=name); db.add(o); db.flush(); return o


def an_old_v3_database(db):
    """What a database from the previous release holds: Essentials..Complete, the first-generation Starter/Growth/Premium (retired), old add-ons, enforcement off."""
    db.query(Plan).delete(); db.query(Addon).delete(); db.query(OrgSubscription).delete(); db.query(m.SystemSetting).delete()
    for pid, name, seats, mods, price in (("essentials", "Essentials", 1, ["dashboard-accounting", "general-ledger", "reconciliation", "sales", "purchases", "financial-reports", "cash-flow-forecasting"], "25.00"),
                                          ("business", "Business", 3, ["domain:accounting", "domain:planning_insights"], "59.00"),
                                          ("professional", "Professional", 6, ["domain:accounting", "domain:payroll_workforce", "domain:tax_compliance", "domain:planning_insights"], "99.00"),
                                          ("complete", "Complete", 15, ["*"], "179.00"),
                                          ("starter", "Starter", 3, ["sales", "purchases", "general-ledger"], "29.00"), ("growth", "Growth", 10, ["sales", "expenses", "inventory-trading"], "79.00"),
                                          ("premium", "Premium", None, ["*"], "149.00")):
        db.add(Plan(id=pid, name=name, price_monthly=Decimal(price), price_yearly=Decimal(price) * 10, seat_limit=seats, modules=json.dumps(mods), is_active=pid in ("essentials", "business", "professional", "complete"), sort_order=1))
    for aid, mods in (("addon-inventory", ["inventory-trading"]), ("addon-expenses", ["expenses"]), ("addon-payroll", ["domain:payroll_workforce"])):
        db.add(Addon(id=aid, name=aid, price_monthly=Decimal("10"), modules=json.dumps(mods), extra_seats=0, sort_order=1))
    db.add(m.SystemSetting(key=S.CATALOGUE_VERSION_KEY, value="3")); db.add(m.SystemSetting(key=S.ENFORCED_KEY, value="off")); db.add(m.SystemSetting(key=S.DEFAULT_PLAN_KEY, value="essentials"))
    db.commit()


# ------------------------------------------------------------------------------------------------------ the four plans and what each can see
def test_fresh_install_has_exactly_the_four_plans_enforced_with_starter_as_default(env):
    db, org, ctx = env
    db.query(Plan).delete(); db.query(Addon).delete(); db.query(m.SystemSetting).delete(); db.commit()
    S.ensure_catalogue(db); db.commit()
    plans = db.query(Plan).order_by(Plan.sort_order).all()
    assert [(p.id, p.name, int(p.price_monthly), int(p.price_yearly), p.seat_limit) for p in plans] == [("essential", "Essential", 25, 275, 1), ("business", "Business", 59, 649, 1), ("professional", "Professional", 99, 1089, 1), ("ultra", "Ultra", 179, 1969, 1)]
    cfg = S.get_settings(db); assert cfg == {"enforced": True, "default_plan": "essential"}
    assert {a.id for a in db.query(Addon)} == {"addon-payroll", "addon-tax", "addon-planning", "addon-assets", "addon-lending", "addon-practice"}          # no public seat packs


def test_starter_sees_ALL_of_books_and_accounting_and_no_other_business_domain(env):
    db, org, ctx = env
    S.ensure_catalogue(db); db.query(OrgSubscription).delete(); db.add(OrgSubscription(org_id=org.id, plan_id="essential", status="active")); db.commit()
    ent = S.entitlements(db, org.id)
    assert set(ent["modules"]) - {"open-banking"} == ACCOUNTING and len(ACCOUNTING) == 10                    # every module of the domain, including expenses, inventory, fixed assets, bulk import (+ the Open banking function)
    for must in ("dashboard-accounting", "general-ledger", "reconciliation", "sales", "purchases", "expenses", "inventory-trading", "fixed-assets", "financial-reports", "bulk-import"):
        assert must in ent["modules"]
    for domain in ("payroll_workforce", "tax_compliance", "assets_investments", "lending_treasury", "planning_insights", "practice"):
        assert set(S.DOMAIN_MODULES[domain]) <= set(ent["locked"]), domain                                     # not one module of any other domain
    assert "cash-flow-forecasting" in ent["locked"]                                                          # forecasting is Planning & Intelligence: Business and above
    assert ent["enforced"] is True and ent["seats"] == 1


@pytest.mark.parametrize("plan, domains", [("essential", {"accounting"}), ("business", {"accounting", "planning_insights"}),
                                           ("professional", {"accounting", "payroll_workforce", "tax_compliance", "planning_insights"}), ("ultra", set(S.DOMAIN_IDS))])
def test_each_plan_shows_exactly_its_domains_and_nothing_else(env, plan, domains):
    db, org, ctx = env
    S.ensure_catalogue(db); db.query(OrgSubscription).delete(); db.add(OrgSubscription(org_id=org.id, plan_id=plan, status="active")); db.commit()
    ent = S.entitlements(db, org.id)
    visible = {d for d in S.DOMAIN_IDS if set(S.DOMAIN_MODULES[d]) <= set(ent["modules"])}
    touched = {d for d in S.DOMAIN_IDS if set(S.DOMAIN_MODULES[d]) & set(ent["modules"])}
    assert visible == touched == domains


def test_a_domain_bolted_on_as_an_add_on_appears_and_only_that_domain(env):
    db, org, ctx = env
    S.ensure_catalogue(db); db.query(OrgSubscription).delete(); db.add(OrgSubscription(org_id=org.id, plan_id="essential", status="active", addons=json.dumps(["addon-payroll"]))); db.commit()
    ent = S.entitlements(db, org.id)
    assert set(ent["modules"]) - {"open-banking"} == ACCOUNTING | set(S.DOMAIN_MODULES["payroll_workforce"]) and "employees" in ent["modules"] and "tax-returns" in ent["locked"]


# ------------------------------------------------------------------------------------------------------------ old plans are gone, people are moved
def test_old_database_is_moved_to_the_new_price_list_once_and_old_plans_are_deleted(env):
    db, org, ctx = env
    an_old_v3_database(db)                                       # version "3": Essentials/Business/Professional/Complete + first-generation Starter/Growth/Premium
    o_ess, o_start, o_growth, o_prem, o_complete = (new_org(db, n) for n in ("OnEssentials", "OnOldStarter", "OnGrowth", "OnPremium", "OnComplete"))
    for o, pid in ((o_ess, "essentials"), (o_start, "starter"), (o_growth, "growth"), (o_prem, "premium"), (o_complete, "complete")):
        db.add(OrgSubscription(org_id=o.id, plan_id=pid, status="active"))
    owner = ctx.user_id
    db.add(m.OrgMembership(org_id=o_start.id, user_id=owner, role="owner")); db.commit()                       # the old Starter organisation has 3 people: 1 member + 2 codes
    for i in range(2):
        db.add(OrgInvite(org_id=o_start.id, code_hash=f"h{i}", code_hint="ABCD", role="readonly", max_uses=1, used_count=0, expires_at=datetime.utcnow() + timedelta(days=5), created_by=owner))
    db.commit()

    S.ensure_catalogue(db); db.commit()

    assert [p.id for p in db.query(Plan).order_by(Plan.sort_order)] == ["essential", "business", "professional", "ultra"]                    # nothing else survives
    plans = {p.id: p for p in db.query(Plan)}
    assert [(p.name, p.seat_limit, int(p.price_yearly)) for p in plans.values()] == [("Essential", 1, 275), ("Business", 1, 649), ("Professional", 1, 1089), ("Ultra", 1, 1969)]
    assert json.loads(plans["essential"].modules) == ["domain:accounting", "open-banking"]
    assert {a.id for a in db.query(Addon) if not a.id.startswith("addon-pack-org-")} == {"addon-payroll", "addon-tax", "addon-planning", "addon-assets", "addon-lending", "addon-practice"}
    plan_of = lambda o: db.get(OrgSubscription, o.id).plan_id
    assert plan_of(o_ess) == "essential" and plan_of(o_complete) == "ultra"                                 # renamed, same customers
    assert plan_of(o_start) == "essential" and plan_of(o_growth) == "essential"                              # their modules (sales, expenses ...) are all Books & Accounting
    assert plan_of(o_prem) == "ultra"                                                                        # Ultra / Premium -> Ultra
    # the old Starter organisation had 3 people: they keep access through a pack for the 2 beyond the 1 in the plan (price to be arranged with the AccFino team)
    pack = db.get(Addon, f"addon-pack-org-{o_start.id}")
    assert pack is not None and pack.extra_seats == 2 and Decimal(pack.price_monthly) == 0 and f"addon-pack-org-{o_start.id}" in json.loads(db.get(OrgSubscription, o_start.id).addons)
    ent = S.entitlements(db, o_start.id); assert ent["seats"] == 3 and ent["seats_used"] == 1
    assert S.get_settings(db) == {"enforced": True, "default_plan": "essential"} and db.get(m.SystemSetting, S.CATALOGUE_VERSION_KEY).value == "6"
    S.ensure_catalogue(db); db.commit()                                                                      # runs once
    assert db.get(OrgSubscription, o_prem.id).notes.count("Moved from") == 1


def test_users_already_bought_as_seat_packs_become_one_pack_with_the_same_price(env):
    db, org, ctx = env
    an_old_v3_database(db)
    db.add(Addon(id="addon-seat-1", name="1 extra user", price_monthly=Decimal("6.00"), modules="[]", extra_seats=1, sort_order=11))
    db.add(Addon(id="addon-seats-5", name="5 extra users", price_monthly=Decimal("25.00"), modules="[]", extra_seats=5, sort_order=12)); db.commit()
    o = new_org(db, "Buyer"); db.add(OrgSubscription(org_id=o.id, plan_id="business", status="active", addons=json.dumps(["addon-seat-1", "addon-seats-5", "addon-payroll"]))); db.commit()
    S.ensure_catalogue(db); db.commit()
    sub = db.get(OrgSubscription, o.id)
    ids = json.loads(sub.addons); pack = db.get(Addon, f"addon-pack-org-{o.id}")
    assert "addon-seat-1" not in ids and "addon-seats-5" not in ids and "addon-payroll" in ids and pack.id in ids                       # the public packs are gone, the domain add-on stays
    assert pack.extra_seats == 6 and Decimal(pack.price_monthly) == Decimal("31.00")                                                    # what they paid for extra users is kept
    assert db.get(Addon, "addon-seat-1") is None and db.get(Addon, "addon-seats-5") is None
    assert S.entitlements(db, o.id)["seats"] == 7


def test_yearly_prices_become_eleven_months_unless_an_administrator_set_their_own(env):
    db, org, ctx = env
    an_old_v3_database(db)
    db.get(Plan, "professional").price_yearly = Decimal("1000.00"); db.commit()                              # an administrator's own yearly price
    S.ensure_catalogue(db); db.commit()
    got = {p.id: int(p.price_yearly) for p in db.query(Plan)}
    assert got["essential"] == 275 and got["business"] == 649 and got["ultra"] == 1969 and got["professional"] == 1000


def test_growth_org_fits_essential_when_it_has_one_person(env):
    db, org, ctx = env
    an_old_v3_database(db)
    o = new_org(db, "Solo"); db.add(OrgSubscription(org_id=o.id, plan_id="growth", status="active")); db.add(m.OrgMembership(org_id=o.id, user_id=ctx.user_id, role="owner")); db.commit()
    S.ensure_catalogue(db); db.commit()
    assert db.get(OrgSubscription, o.id).plan_id == "essential"                                              # modules (sales, expenses, inventory) are all Books & Accounting


def test_organisations_without_a_plan_get_one_from_their_owners_old_plan(env):
    db, org, ctx = env
    S.ensure_catalogue(db); db.query(OrgSubscription).delete(); db.commit()
    cases = {"base": ("essential", []), "vault": ("essential", []), "premium": ("ultra", []), "ultra": ("ultra", []), "accounting_pro": ("business", []),
             "payroll_business": ("essential", ["addon-payroll"]), "taxation_complete": ("essential", ["addon-tax", "addon-assets"]), "lending_basic": ("essential", ["addon-lending"]), "": ("essential", [])}
    made = {}
    for i, legacy in enumerate(cases):
        u = User(username=f"u{i}", full_name="U", email=f"u{i}@x.com", password="x", phone="+61400000000"); db.add(u); db.flush()
        o = new_org(db, f"Org{i}"); db.add(m.OrgMembership(org_id=o.id, user_id=u.id, role="owner"))
        if legacy: db.add(LicenceRecord(user_id=u.id, plan_id=legacy, licence_type=legacy))
        made[legacy] = o.id
    db.commit()
    AL.run_alignment(db); db.commit()
    for legacy, (plan, addons) in cases.items():
        sub = db.get(OrgSubscription, made[legacy]); assert (sub.plan_id, json.loads(sub.addons)) == (plan, addons), legacy
    ent = S.entitlements(db, made["lending_basic"]); assert "credit-assessment" in ent["modules"] and "payslips" in ent["locked"]       # keeps exactly what Smart Lending gave them
    assert S.entitlements(db, made["premium"])["locked"] == []


def test_the_platform_administrator_has_the_top_plan_full_access_and_no_end(env):
    db, org, ctx = env
    S.ensure_catalogue(db); db.query(OrgSubscription).delete(); db.commit()
    role = Role(name="admin"); db.add(role); db.flush()
    u = db.get(User, ctx.user_id) or User(username="admin", full_name="Admin", email="admin@accfino.com", password="x", phone="+61400000000")
    db.add(u); db.flush(); u.roles.append(role)
    if not db.query(m.OrgMembership).filter_by(org_id=org.id, user_id=u.id).first(): db.add(m.OrgMembership(org_id=org.id, user_id=u.id, role="owner"))
    db.commit()
    out = AL.run_alignment(db); db.commit()
    sub = db.get(OrgSubscription, org.id)
    assert org.id in out["admin_orgs"] and (sub.plan_id, sub.status, sub.period_end, sub.trial_ends) == ("ultra", "active", None, None)
    sub.plan_id, sub.status, sub.period_end = "essential", "expired", date(2020, 1, 1); db.commit()           # however it is changed, it is put back
    AL.run_alignment(db); db.commit()
    assert (sub.plan_id, sub.status, sub.period_end) == ("ultra", "active", None)
    ent = S.entitlements(db, org.id); assert (ent["plan_name"], ent["seats"], ent["locked"], ent["read_only"]) == ("Ultra", 1, [], False)
    mine = AL.build_my_plan(db, u.id); assert (mine["plan_id"], mine["plan_name"], mine["end_date"]) == ("ultra", "Ultra", "9999-12-31")      # the badge: never "Ultra Plan"


# ------------------------------------------------------------------------------------------------------ the old tables and labels
def test_the_old_plan_table_is_a_mirror_of_the_four_plans(env):
    db, org, ctx = env
    for slug, name, pm in (("base", "Vault", 0), ("premium", "Ultra Plan", 6900), ("accounting_pro", "Accounting Pro", 1900), ("taxation_complete", "Taxation Complete", 2500)):
        db.add(PricingPlan(slug=slug, name=name, price_monthly=pm, price_yearly=pm * 10, features=[], modules=["dashboard"], sort_order=9))
    db.commit()
    AL.run_alignment(db); db.commit()
    rows = {r.slug: r for r in db.query(PricingPlan).order_by(PricingPlan.sort_order)}
    assert list(rows) == ["essential", "business", "professional", "ultra"]
    assert [(r.price_monthly, r.price_yearly) for r in rows.values()] == [(2500, 27500), (5900, 64900), (9900, 108900), (17900, 196900)]          # yearly = 11 months
    assert not {"Vault", "Ultra Plan", "Accounting Pro"} & {r.name for r in rows.values()}
    assert rows["essential"].features[0] == "1 user" and "Books and Accounting (whole domain)" in rows["essential"].features and "payroll" not in rows["essential"].modules
    assert rows["essential"].modules == ["dashboard", "accounting", "reconciliation", "invoice"] and "cash-flow" in rows["business"].modules and "payroll" in rows["professional"].modules and "lending" in rows["ultra"].modules
    db.get(Plan, "essential").price_monthly = Decimal("27.00"); db.commit()                                     # an edit in Admin > Pricing shows in the old table at once
    AL.sync_pricing_plans(db); db.commit(); assert db.get(PricingPlan, "essential").price_monthly == 2700
    again = AL.run_alignment(db); assert again["admin_orgs"] == [] and again["assigned"] == [] and again["licences_relabelled"] == 0


def test_old_licence_records_are_relabelled_to_the_new_plan_ids(env):
    db, org, ctx = env
    S.ensure_catalogue(db)
    users = []
    for i in range(5):
        u = User(username=f"lic{i}", full_name="L", email=f"lic{i}@x.com", password="x", phone="+61400000000"); db.add(u); db.flush(); users.append(u.id)
    for uid, (pid, lt) in zip(users, (("premium", "premium"), ("base", "base"), ("accounting_pro", "demo"), ("admin", "admin"), ("ultra", "ultra"))):
        db.add(LicenceRecord(user_id=uid, plan_id=pid, licence_type=lt, modules=json.dumps(["dashboard", "reconciliation", "trading"]))); db.commit()
    assert AL.relabel_licences(db) > 0; db.commit()
    got = {l.user_id: (l.plan_id, l.licence_type) for l in db.query(LicenceRecord)}
    assert [got[u] for u in users] == [("ultra", "ultra"), ("essential", "essential"), ("business", "demo"), ("ultra", "admin"), ("ultra", "ultra")]


def test_plan_badge_data_comes_from_the_organisation_plan_and_never_says_vault_or_ultra(env):
    db, org, ctx = env
    S.ensure_catalogue(db); db.query(OrgSubscription).delete()
    db.add(OrgSubscription(org_id=org.id, plan_id="business", status="active", billing_period="monthly", period_end=date(2026, 11, 2)))
    if not db.query(m.OrgMembership).filter_by(org_id=org.id, user_id=ctx.user_id).first(): db.add(m.OrgMembership(org_id=org.id, user_id=ctx.user_id, role="owner"))
    db.commit()
    mine = AL.build_my_plan(db, ctx.user_id)
    assert (mine["plan_id"], mine["plan_name"], mine["end_date"]) == ("business", "Business", "2026-11-02") and "payroll" not in mine["modules"] and "cash-flow" in mine["modules"]


def test_fallback_plans_are_the_new_plans_in_the_old_shape():
    legacy = AL.legacy_plans_dict()
    assert list(legacy) == ["essential", "business", "professional", "ultra"] and legacy["ultra"]["price_monthly"] == 17900 and legacy["essential"]["name"] == "Essential"
    assert not {"base", "premium", "accounting_pro", "essentials"} & set(legacy)


# ------------------------------------------------------------------------------------------------ Admin > Users & Licence > Plans by user
def test_plans_by_user_shows_each_persons_organisation_plan_and_the_admin_on_the_top_plan(env):
    from accfino_core.api import org_directory_api as OD
    db, org, ctx = env
    S.ensure_catalogue(db); db.query(OrgSubscription).delete(); db.commit()
    role = Role(name="admin"); db.add(role); db.flush()
    admin = User(username="admin", full_name="Administrator", email="admin@accfino.com", password="x", phone="+61400000000"); db.add(admin); db.flush(); admin.roles.append(role)
    ann = User(username="ann", full_name="Ann", email="ann@x.com", password="x", phone="+61411111111"); loose = User(username="loose", full_name="Loose", email="l@x.com", password="x", phone="+61422222222")
    db.add_all([ann, loose]); db.flush()
    ao, bo = new_org(db, "Admin Org"), new_org(db, "Ann Pty Ltd")
    db.add_all([m.OrgMembership(org_id=ao.id, user_id=admin.id, role="owner"), m.OrgMembership(org_id=bo.id, user_id=ann.id, role="owner")])
    db.add(OrgSubscription(org_id=bo.id, plan_id="business", status="active", billing_period="yearly", period_end=date(2027, 4, 2), addons=json.dumps(["addon-payroll"]))); db.commit()
    AL.run_alignment(db); db.commit()
    out = OD.user_plan_rows(db)
    by = {r["username"]: r for r in out["rows"]}
    assert by["admin"]["org"]["plan_name"] == "Ultra" and by["admin"]["platform_admin"] is True and out["top_plan"] == "Ultra"
    a = by["ann"]["org"]
    assert (a["plan_id"], a["plan_name"], a["billing_period"], a["period_end"], a["status"]) == ("business", "Business", "yearly", "2027-04-02", "active")
    assert a["addons"] == ["Payroll & Workforce"] and a["seats_allowed"] == 1 and a["seats_used"] == 1
    assert a["domains"] == ["Books and Accounting", "Payroll & Workforce", "Planning & Intelligence"]          # exactly what Business + the payroll add-on shows
    assert by["loose"]["org"] is None and by["loose"]["role_label"] == "No organisation"
    assert [p["name"] for p in out["plans"]] == ["Essential", "Business", "Professional", "Ultra"]               # the only plans to choose from


def test_changing_a_plan_from_that_table_changes_only_the_plan_and_is_admin_only(env):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from accfino_core.api import org_directory_api as OD
    from db_app.database import get_db
    db, org, ctx = env
    S.ensure_catalogue(db); db.query(OrgSubscription).delete()
    o = new_org(db, "Acme"); db.add(OrgSubscription(org_id=o.id, plan_id="business", status="active", billing_period="yearly", period_end=date(2027, 4, 2), addons=json.dumps(["addon-payroll"]), notes="keep me")); db.commit()
    st = {"admin": False}
    app = FastAPI(); app.include_router(OD.router, prefix="/admin/org-directory"); app.dependency_overrides[get_db] = lambda: db
    @app.middleware("http")
    async def _a(request, call_next):
        request.state.auth = {"user_id": 1, "username": "t", "is_admin": st["admin"]}
        return await call_next(request)
    c = TestClient(app)
    assert c.get("/admin/org-directory/user-plans").status_code == 403 and c.put(f"/admin/org-directory/org/{o.id}/plan", json={"plan_id": "ultra"}).status_code == 403
    st["admin"] = True
    assert c.put(f"/admin/org-directory/org/{o.id}/plan", json={"plan_id": "ultra"}).json()["plan_name"] == "Ultra"
    sub = db.get(OrgSubscription, o.id); db.refresh(sub)
    assert (sub.plan_id, sub.billing_period, str(sub.period_end), sub.addons, sub.notes, sub.status) == ("ultra", "yearly", "2027-04-02", json.dumps(["addon-payroll"]), "keep me", "active")
    assert c.put(f"/admin/org-directory/org/{o.id}/plan", json={"plan_id": "nope"}).status_code == 404 and c.put("/admin/org-directory/org/99999/plan", json={"plan_id": "ultra"}).status_code == 404
    db.get(Plan, "business").is_active = False; db.commit()
    assert c.put(f"/admin/org-directory/org/{o.id}/plan", json={"plan_id": "business"}).status_code == 404              # a hidden plan cannot be assigned
