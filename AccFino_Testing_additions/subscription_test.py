"""Tests for per-organisation subscriptions. Run from backend/:  PYTHONPATH=. python -m pytest ../AccFino_Testing_additions/subscription_test.py -q"""
import os, sys
from datetime import date, timedelta
import pytest
sys.path.insert(0, os.path.dirname(__file__))
from csv_import_harness import make_db, make_org
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from fastapi.responses import JSONResponse
from accfino_core import models as m
from accfino_core.subscription import service as S
from accfino_core.subscription.models import OrgSubscription
from accfino_core.api import subscription_api, books_import, org as org_api
from accfino_core.books.common import BooksError
from accfino_core.security.context import OrgContext, current_org, current_auth
from db_app.database import get_db


@pytest.fixture()
def env():
    db = make_db(); org, ctx = make_org(db)
    S.ensure_catalogue(db); db.commit()
    yield db, org, ctx
    db.close()


def enforce(db, on=True):
    S.set_settings(db, enforced=on); db.commit()


def assign(db, org, plan, addons=(), status="active", **kw):
    row = db.get(OrgSubscription, org.id) or OrgSubscription(org_id=org.id, plan_id=plan)
    row.plan_id, row.status = plan, status
    import json; row.addons = json.dumps(list(addons))
    for k, v in kw.items(): setattr(row, k, v)
    db.merge(row); db.commit()


def fake_ctx(ctx, org, admin=False):
    return OrgContext(ctx.user_id, "u", admin, org, "owner")


# ---------------------------------------------------------------------------------------------- the rules
def test_default_catalogue_and_off_by_default(env):
    db, org, ctx = env
    assert {p.id for p in db.query(S.Plan)} == {"essentials", "business", "professional", "complete"}
    ent = S.entitlements(db, org.id)
    assert ent["enforced"] is False and ent["locked"] == [] and ent["grandfathered"]           # an organisation with no row is never locked
    assign(db, org, "essentials")                                                                 # even on Starter, nothing is locked while enforcement is off
    assert S.entitlements(db, org.id)["locked"] == []
    S.check(db, fake_ctx(ctx, org), ("inventory-trading",))                                    # no exception


def test_starter_locks_modules_and_blocks_the_api(env):
    db, org, ctx = env
    assign(db, org, "essentials"); enforce(db)
    ent = S.entitlements(db, org.id)
    assert {"expenses", "inventory-trading", "fixed-assets", "bulk-import"} <= set(ent["locked"]) and ent["seats"] == 1
    assert not {"sales", "purchases", "general-ledger", "reconciliation", "financial-reports", "cash-flow-forecasting"} & set(ent["locked"])
    assert {"employees", "tax-returns", "shares-etfs", "practice-management"} <= set(ent["locked"])                    # the other domains are not in Essentials
    S.check(db, fake_ctx(ctx, org), ("sales",))
    with pytest.raises(HTTPException) as e:
        S.check(db, fake_ctx(ctx, org), ("expenses",))
    assert e.value.status_code == 402 and "Essentials" in e.value.detail
    S.check(db, fake_ctx(ctx, org, admin=True), ("expenses",))                                 # platform admins are never blocked
    S.check(db, fake_ctx(ctx, org), ("sales", "purchases"))                                     # several ids = any of them


def test_addon_unlocks_immediately_and_seat_pack_adds_seats(env):
    db, org, ctx = env
    assign(db, org, "essentials"); enforce(db)
    assign(db, org, "essentials", addons=["addon-inventory", "addon-seats-5", "addon-bulk-import"])
    ent = S.entitlements(db, org.id)
    assert "inventory-trading" in ent["modules"] and "bulk-import" in ent["modules"] and "expenses" in ent["locked"] and ent["seats"] == 6


def test_complete_has_every_module_and_15_seats(env):
    db, org, ctx = env
    assign(db, org, "complete"); enforce(db)
    ent = S.entitlements(db, org.id)
    assert ent["locked"] == [] and ent["seats"] == 15 and set(ent["modules"]) == set(S.CATALOGUE_IDS)


def test_expired_subscription_is_read_only_not_deleted(env):
    db, org, ctx = env
    assign(db, org, "business", period_end=date.today() - timedelta(days=S.GRACE_DAYS + 1)); enforce(db)
    ent = S.entitlements(db, org.id)
    assert ent["status"] == "expired" and ent["read_only"] and "sales" in ent["modules"]       # still visible
    S.check(db, fake_ctx(ctx, org), ("sales",), "GET")
    with pytest.raises(HTTPException) as e:
        S.check(db, fake_ctx(ctx, org), ("sales",), "POST")
    assert e.value.status_code == 402 and "read-only" in e.value.detail
    assign(db, org, "business", period_end=date.today() - timedelta(days=2))                    # inside the grace period: still fully working
    assert not S.entitlements(db, org.id)["read_only"]
    assign(db, org, "business", status="trial", trial_ends=date.today() - timedelta(days=1))
    assert S.entitlements(db, org.id)["read_only"]
    assign(db, org, "business", status="cancelled", period_end=date.today() + timedelta(days=10))
    assert not S.entitlements(db, org.id)["read_only"]                                         # cancelled but paid up to the period end


def test_seat_limit_blocks_new_members_only(env):
    db, org, ctx = env
    assign(db, org, "business"); enforce(db)                   # Business = 3 users
    for i in range(2):                                          # owner already counts as 1 -> 3 seats used
        from csv_import_harness import SD
        u, _ = SD._get_or_create_user(db, f"member{i}@example.com")
        db.flush(); db.add(m.OrgMembership(org_id=org.id, user_id=u.id, role="bookkeeper")); db.commit()
    assert S.entitlements(db, org.id)["seats_used"] == 3
    with pytest.raises(HTTPException) as e:
        S.check_seat(db, fake_ctx(ctx, org))
    assert e.value.status_code == 402 and "3 user" in e.value.detail
    assign(db, org, "business", addons=["addon-seats-5"]); S.check_seat(db, fake_ctx(ctx, org))  # seat pack frees room
    assign(db, org, "complete"); S.check_seat(db, fake_ctx(ctx, org))


def test_new_organisation_gets_the_default_plan(env):
    db, org, ctx = env
    S.set_settings(db, default_plan="business")
    o2 = m.Organisation(name="Second Co"); db.add(o2); db.flush()
    S.start_subscription(db, o2.id); db.commit()
    assert db.get(OrgSubscription, o2.id).plan_id == "business"


# ---------------------------------------------------------------------------------------------- over HTTP
def make_client(db, org, ctx, admin=False, role="owner"):
    app = FastAPI()
    from accfino_core.api import books_expenses
    app.include_router(subscription_api.org_router, prefix="/org/current/subscription")
    app.include_router(subscription_api.admin_router, prefix="/admin/subscriptions")
    from fastapi import Depends
    app.include_router(books_expenses.router, prefix="/expenses", dependencies=[Depends(S.feature_gate("expenses"))])
    app.include_router(books_import.router, prefix="/imports")
    app.exception_handler(BooksError)(lambda req, exc: JSONResponse({"detail": str(exc)}, status_code=exc.status))
    state = dict(admin=admin, role=role)
    @app.middleware("http")
    async def _auth(request, call_next):                       # what the real AuthGuard does: put the signed-in user on the request
        request.state.auth = {"user_id": ctx.user_id, "username": "tester", "is_admin": state["admin"]}
        return await call_next(request)
    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[current_org] = lambda: OrgContext(ctx.user_id, "tester", state["admin"], org, state["role"])
    app.dependency_overrides[current_auth] = lambda: {"user_id": ctx.user_id, "username": "tester", "is_admin": state["admin"]}
    return TestClient(app), state


def test_http_upgrade_takes_effect_immediately(env):
    db, org, ctx = env
    assign(db, org, "essentials"); enforce(db)
    c, st = make_client(db, org, ctx)
    sub = c.get("/org/current/subscription").json()
    assert "expenses" in sub["locked"] and sub["can_manage"] and {p["id"] for p in sub["plans"]} >= {"essentials", "business", "professional", "complete"}
    r = c.get("/expenses/summary")                                                                       # the module API itself is refused, not just hidden
    assert r.status_code == 402 and "not included" in r.json()["detail"]
    assert c.get("/imports/status").json() == {"enabled": False}                                 # bulk import is an add-on on Starter
    assert c.post("/org/current/subscription/request", json={"plan_id": "business", "message": "please"}).json()["ok"]
    st["admin"] = True                                                                           # the platform administrator applies it
    out = c.put(f"/admin/subscriptions/orgs/{org.id}", json={"plan_id": "business", "addons": ["addon-bulk-import"], "status": "active"}).json()
    assert "expenses" in out["modules"] and "bulk-import" in out["modules"]
    st["admin"] = False
    assert "expenses" not in c.get("/org/current/subscription").json()["locked"]
    assert c.get("/expenses/summary").status_code != 402
    assert c.get("/imports/status").json() == {"enabled": True}


def test_http_admin_endpoints_are_admin_only_and_validated(env):
    db, org, ctx = env
    c, st = make_client(db, org, ctx)
    assert c.get("/admin/subscriptions").status_code == 403
    assert c.put("/admin/subscriptions/settings", json={"enforced": True}).status_code == 403
    st["admin"] = True
    ov = c.get("/admin/subscriptions").json()
    assert ov["settings"]["enforced"] is False and any(o["org_id"] == org.id for o in ov["organisations"])
    assert c.put("/admin/subscriptions/plans/bad id", json={"name": "x"}).status_code == 422
    assert c.put("/admin/subscriptions/plans/gold", json={"name": "Gold", "modules": ["nope"]}).status_code == 422
    assert c.put("/admin/subscriptions/plans/gold", json={"name": "Gold", "price_monthly": "-5", "modules": ["sales"]}).status_code == 422
    ok = c.put("/admin/subscriptions/plans/gold", json={"name": "Gold", "price_monthly": "49", "seat_limit": 5, "modules": ["sales", "purchases"]})
    assert ok.status_code == 200 and ok.json()["price_monthly"] == "49.00"
    c.put(f"/admin/subscriptions/orgs/{org.id}", json={"plan_id": "gold"})
    assert c.delete("/admin/subscriptions/plans/gold").status_code == 409                       # in use
    assert c.put(f"/admin/subscriptions/orgs/{org.id}", json={"plan_id": "gold", "status": "weird"}).status_code == 422
    assert c.put(f"/admin/subscriptions/orgs/{org.id}", json={"plan_id": "nope"}).status_code == 404
    assert c.put("/admin/subscriptions/settings", json={"enforced": True, "default_plan": "nope"}).status_code == 404
    c.put(f"/admin/subscriptions/orgs/{org.id}", json={"plan_id": "essentials"})
    assert c.delete("/admin/subscriptions/plans/gold").status_code == 200
    assert c.put("/admin/subscriptions/settings", json={"enforced": True}).json()["enforced"] is True


def test_only_owner_or_admin_can_request_a_change(env):
    db, org, ctx = env
    c, st = make_client(db, org, ctx, role="bookkeeper")
    assert c.post("/org/current/subscription/request", json={"plan_id": "business"}).status_code == 403


# ------------------------------------------------------------------------------------------ domain-based plans (catalogue v2)
def test_domain_tokens_expand_and_plans_are_grouped_by_business_domain(env):
    db, org, ctx = env
    assert S.expand(["domain:payroll_workforce"]) == set(S.DOMAIN_MODULES["payroll_workforce"]) and S.expand(["*"]) == set(S.CATALOGUE_IDS)
    assert S.expand(["domain:nope", "nonsense", "sales"]) == {"sales"}
    assign(db, org, "professional"); enforce(db)                                                           # Books + Payroll + Tax + Planning
    ent = S.entitlements(db, org.id)
    for d in ("accounting", "payroll_workforce", "tax_compliance", "planning_insights"):
        assert set(S.DOMAIN_MODULES[d]) <= set(ent["modules"])
    for d in ("assets_investments", "lending_treasury", "practice"):
        assert set(S.DOMAIN_MODULES[d]) <= set(ent["locked"])
    assign(db, org, "essentials", addons=["addon-payroll"])                                                # one domain bolted onto a small plan
    ent = S.entitlements(db, org.id)
    assert set(S.DOMAIN_MODULES["payroll_workforce"]) <= set(ent["modules"]) and "tax-returns" in ent["locked"]


def test_every_module_belongs_to_exactly_one_domain_and_matches_the_registry():
    import json, pathlib
    reg = json.loads((pathlib.Path(__file__).parent.parent / "frontend/src/config/modules.json").read_text())
    sellable = {m["id"] for m in reg["modules"] if not m.get("area")}
    server = [i for ms in S.DOMAIN_MODULES.values() for i in ms]
    assert len(server) == len(set(server)) == len(S.CATALOGUE_IDS)
    assert set(server) - {"bulk-import"} == sellable                                                       # bulk-import is a capability, not a menu module
    assert set(S.DOMAIN_IDS) == {d["id"] for d in reg["domains"]}


def test_v1_installation_is_moved_once_to_the_new_plans_without_touching_existing_organisations(env):
    import json
    from decimal import Decimal
    db, org, ctx = env
    for k in (S.CATALOGUE_VERSION_KEY, S.DEFAULT_PLAN_KEY):                                                # rebuild what a v1 database looks like
        row = db.get(m.SystemSetting, k)
        if row is not None: db.delete(row)
    for t in (S.Plan, S.Addon):
        db.query(t).delete()
    for pid, name, seats, mods in (("starter", "Starter", 3, ["sales"]), ("growth", "Growth", 10, ["sales", "expenses"]), ("premium", "Premium", None, ["*"])):
        db.add(S.Plan(id=pid, name=name, price_monthly=Decimal("29"), price_yearly=Decimal("290"), seat_limit=seats, modules=json.dumps(mods), sort_order=1))
    db.add(S.Plan(id="custom-deal", name="Custom deal", price_monthly=Decimal("5"), price_yearly=Decimal("50"), seat_limit=2, modules="[]", sort_order=9))
    db.add(S.Addon(id="addon-inventory", name="Inventory", price_monthly=Decimal("15.00"), modules=json.dumps(["inventory-trading"]), sort_order=1))
    db.commit()
    assign(db, org, "growth")                                                                              # an organisation already on an old plan
    S.ensure_catalogue(db); db.commit()
    plans = {p.id: p for p in db.query(S.Plan)}
    assert {"essentials", "business", "professional", "complete"} <= set(plans) and plans["custom-deal"].is_active   # admin's own plan untouched
    assert not any(plans[i].is_active for i in ("starter", "growth", "premium"))                          # retired: no new sign-ups
    assert S.get_settings(db)["default_plan"] == "essentials"
    assert db.get(S.Addon, "addon-inventory").price_monthly == Decimal("12.00")                            # unedited v1 add-on re-priced
    assert db.get(OrgSubscription, org.id).plan_id == "growth" and S.entitlements(db, org.id)["plan_name"] == "Growth"   # existing organisation keeps its plan
    plans["essentials"].price_monthly = Decimal("27.00"); db.commit()
    S.ensure_catalogue(db); db.commit()
    assert db.get(S.Plan, "essentials").price_monthly == Decimal("27.00")                                  # runs once: later edits are never overwritten


# ------------------------------------------------------------------------------------------------ public landing page pricing
def test_public_pricing_is_public_live_and_matches_the_catalogue(env):
    from accfino_core.api import public_pricing_api as PP
    from accfino_core.security.middleware import PUBLIC_ROUTES
    from fastapi import Response
    db, org, ctx = env
    assert "/public/pricing" in PUBLIC_ROUTES                                                      # no sign-in needed for the website
    out = PP.public_pricing(Response(), db)
    assert [p["id"] for p in out["plans"]] == ["essentials", "business", "professional", "complete"]
    assert out["plans"][0]["price_monthly"] == 25.0 and out["plans"][3]["seat_limit"] == 15 and out["plans"][3]["all"] is True
    assert out["plans"][2]["domains"] == ["Books and Accounting", "Payroll & Workforce", "Taxation & Compliance", "Planning & Intelligence"]
    assert len(out["domains"]) == 7 and any(a["id"] == "addon-seats-5" and a["extra_seats"] == 5 for a in out["addons"])
    p = db.get(S.Plan, "essentials"); p.price_monthly = S.Decimal("27.00"); db.commit()            # an admin edit shows on the website at once
    assert PP.public_pricing(Response(), db)["plans"][0]["price_monthly"] == 27.0
    p.is_active = False; db.commit()                                                              # hidden plans are not advertised
    assert "essentials" not in [x["id"] for x in PP.public_pricing(Response(), db)["plans"]]


def test_landing_page_fallback_pricing_matches_the_shipped_catalogue():
    import json, pathlib, re
    html = (pathlib.Path(__file__).parent.parent / "frontend/public/index-marketing.html").read_text()
    m = re.search(r"var DEFAULTS=(\{.*?\});\n", html, re.S)
    data = json.loads(m.group(1))
    assert [(p["id"], p["price_monthly"], p["price_yearly"], p["seat_limit"]) for p in data["plans"]] == \
           [(p["id"], float(p["price_monthly"]), float(p["price_yearly"]), p["seat_limit"]) for p in S.DEFAULT_PLANS]
    assert [(a["id"], a["price_monthly"]) for a in data["addons"]] == [(a["id"], float(a["price_monthly"])) for a in S.DEFAULT_ADDONS]
    assert len(data["domains"]) == len(S.DOMAINS)
    for old in ("Vault", "Opus", "api/pricing/plans", "Free base plan"):
        assert old not in html


# ------------------------------------------------------------------------------------------------ users scale with price (v3)
def test_users_grow_with_the_price_and_extra_users_are_sold_per_head(env):
    db, org, ctx = env
    plans = {p.id: p for p in db.query(S.Plan).filter_by(is_active=True)}
    assert [(p, int(plans[p].price_monthly), plans[p].seat_limit) for p in ("essentials", "business", "professional", "complete")] == \
           [("essentials", 25, 1), ("business", 59, 3), ("professional", 99, 6), ("complete", 179, 15)]
    assert all(plans[p].seat_limit is not None for p in plans)                                           # no plan is unlimited
    per_user = {a.id: float(a.price_monthly) / a.extra_seats for a in db.query(S.Addon) if a.extra_seats}
    assert per_user == {"addon-seat-1": 6.0, "addon-seats-5": 5.0}                                         # A$5-6 a head, near Zoho's A$4.40
    assign(db, org, "essentials", addons=["addon-seat-1", "addon-seat-1"]); assert S.entitlements(db, org.id)["seats"] == 1 + 1     # the same add-on twice is one add-on: ids are a set


def test_v2_installation_moves_to_v3_seats_only_while_untouched(env):
    from decimal import Decimal
    db, org, ctx = env
    ver = db.get(m.SystemSetting, S.CATALOGUE_VERSION_KEY); ver.value = "2"
    v2 = {"essentials": (3, "Books for a small business: ledger, banking, sales, purchases and reports. 3 users."), "business": (10, "The whole Books & Accounting domain ... 10 users."),
          "professional": (25, "Books + Payroll & Workforce + Taxation & Compliance + Planning & Intelligence. 25 users."), "complete": (None, "Every business domain, including everything. Unlimited users.")}
    for pid, (seats, desc) in v2.items():
        row = db.get(S.Plan, pid); row.seat_limit, row.description = seats, desc
    db.get(S.Plan, "business").seat_limit = 12                                                           # an administrator had already changed this one
    row = db.get(S.Addon, "addon-seats-5"); row.price_monthly = Decimal("15.00")
    db.query(S.Addon).filter_by(id="addon-seat-1").delete(); db.commit()
    S.ensure_catalogue(db); db.commit()
    seats = {p.id: p.seat_limit for p in db.query(S.Plan)}
    assert seats["essentials"] == 1 and seats["professional"] == 6 and seats["complete"] == 15           # untouched v2 plans moved
    assert seats["business"] == 12                                                                         # the edited plan is left alone
    assert db.get(S.Addon, "addon-seats-5").price_monthly == Decimal("25.00") and db.get(S.Addon, "addon-seat-1").extra_seats == 1
    assert db.get(m.SystemSetting, S.CATALOGUE_VERSION_KEY).value == "3"
