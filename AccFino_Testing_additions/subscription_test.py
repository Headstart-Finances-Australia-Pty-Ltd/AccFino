"""Tests for per-organisation subscriptions. Run from backend/:  PYTHONPATH=. python -m pytest ../AccFino_Testing_additions/subscription_test.py -q"""
import json
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
def test_default_catalogue_and_on_by_default(env):
    db, org, ctx = env
    assert {p.id for p in db.query(S.Plan)} == {"essential", "business", "professional", "ultra"}
    ent = S.entitlements(db, org.id)
    assert ent["enforced"] is True and ent["locked"] == [] and ent["grandfathered"]            # an organisation with no row is never locked
    assign(db, org, "essential")
    assert "employees" in S.entitlements(db, org.id)["locked"]                                  # plans are applied by default
    S.check(db, fake_ctx(ctx, org), ("inventory-trading",))                                     # all of Books & Accounting is in Starter: no exception
    enforce(db, False)
    assert S.entitlements(db, org.id)["locked"] == []                                           # an administrator can still switch enforcement off


def test_starter_locks_every_other_domain_and_blocks_the_api(env):
    db, org, ctx = env
    assign(db, org, "essential"); enforce(db)
    ent = S.entitlements(db, org.id)
    assert {"employees", "tax-returns", "shares-etfs", "practice-management", "cash-flow-forecasting", "credit-assessment"} <= set(ent["locked"]) and ent["seats"] == 1
    assert not set(S.DOMAIN_MODULES["accounting"]) & set(ent["locked"])                         # every Books & Accounting module is in Starter
    S.check(db, fake_ctx(ctx, org), ("sales",)); S.check(db, fake_ctx(ctx, org), ("expenses",))
    with pytest.raises(HTTPException) as e:
        S.check(db, fake_ctx(ctx, org), ("employees",))
    assert e.value.status_code == 402 and "Essential" in e.value.detail
    S.check(db, fake_ctx(ctx, org, admin=True), ("employees",))                                 # platform admins are never blocked
    S.check(db, fake_ctx(ctx, org), ("employees", "sales"))                                     # several ids = any of them


def test_domain_add_on_unlocks_immediately_and_a_user_pack_adds_seats(env):
    db, org, ctx = env
    assign(db, org, "essential"); enforce(db)
    db.add(S.Addon(id="addon-pack-test", name="Extra users (arranged)", price_monthly=S.Decimal("30"), modules="[]", extra_seats=4, sort_order=100)); db.commit()   # a pack arranged with the AccFino team
    assign(db, org, "essential", addons=["addon-payroll", "addon-pack-test"])
    ent = S.entitlements(db, org.id)
    assert set(S.DOMAIN_MODULES["payroll_workforce"]) <= set(ent["modules"]) and "tax-returns" in ent["locked"] and ent["seats"] == 5          # 1 in the plan + 4 in the pack


def test_ultra_has_every_module_and_1_user(env):
    db, org, ctx = env
    assign(db, org, "ultra"); enforce(db)
    ent = S.entitlements(db, org.id)
    assert ent["locked"] == [] and ent["seats"] == 1 and set(ent["modules"]) == set(S.CATALOGUE_IDS) and ent["plan_name"] == "Ultra"


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
    assign(db, org, "business"); enforce(db)                   # every plan is 1 user: the owner takes it
    assert S.entitlements(db, org.id)["seats_used"] == 1
    with pytest.raises(HTTPException) as e:
        S.check_seat(db, fake_ctx(ctx, org))
    assert e.value.status_code == 402 and "1 user" in e.value.detail
    db.add(S.Addon(id="addon-pack-test", name="Extra users (arranged)", price_monthly=S.Decimal("30"), modules="[]", extra_seats=2, sort_order=100)); db.commit()
    assign(db, org, "business", addons=["addon-pack-test"]); S.check_seat(db, fake_ctx(ctx, org))          # a user pack arranged with the team frees room
    assign(db, org, "ultra"); 
    with pytest.raises(HTTPException): S.check_seat(db, fake_ctx(ctx, org))                                 # a bigger plan does NOT add users: only a pack does


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
    db.add(S.Plan(id="lite", name="Lite", price_monthly=S.Decimal("5"), price_yearly=S.Decimal("50"), seat_limit=3, modules='["sales", "purchases"]', sort_order=90)); db.commit()   # a small plan, to see a module API refused
    assign(db, org, "lite"); enforce(db)
    c, st = make_client(db, org, ctx)
    sub = c.get("/org/current/subscription").json()
    assert "expenses" in sub["locked"] and sub["can_manage"] and {p["id"] for p in sub["plans"]} >= {"essential", "business", "professional", "ultra"}
    r = c.get("/expenses/summary")                                                                       # the module API itself is refused, not just hidden
    assert r.status_code == 402 and "not included" in r.json()["detail"]
    assert c.get("/imports/status").json() == {"enabled": False}
    assert c.post("/org/current/subscription/request", json={"plan_id": "essential", "message": "please"}).json()["ok"]
    st["admin"] = True                                                                           # the platform administrator applies it
    out = c.put(f"/admin/subscriptions/orgs/{org.id}", json={"plan_id": "essential", "addons": [], "status": "active"}).json()
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
    assert ov["settings"]["enforced"] is True and any(o["org_id"] == org.id for o in ov["organisations"])
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
    c.put(f"/admin/subscriptions/orgs/{org.id}", json={"plan_id": "essential"})
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
    assign(db, org, "essential", addons=["addon-payroll"])                                                # one domain bolted onto a small plan
    ent = S.entitlements(db, org.id)
    assert set(S.DOMAIN_MODULES["payroll_workforce"]) <= set(ent["modules"]) and "tax-returns" in ent["locked"]


def test_every_module_belongs_to_exactly_one_domain_and_matches_the_registry():
    import json, pathlib
    reg = json.loads((pathlib.Path(__file__).parent.parent / "frontend/src/config/modules.json").read_text())
    sellable = {m["id"] for m in reg["modules"] if not m.get("area")}
    server = [i for ms in S.DOMAIN_MODULES.values() for i in ms]
    assert len(server) == len(set(server)) == len(S.CATALOGUE_IDS) - len(S.FEATURE_IDS)                   # functions (Open banking) are plan switches, not menu modules
    assert set(server) - {"bulk-import"} == sellable                                                       # bulk-import is a capability, not a menu module
    assert set(S.DOMAIN_IDS) == {d["id"] for d in reg["domains"]}


def test_public_pricing_is_public_live_and_matches_the_catalogue(env):
    from accfino_core.api import public_pricing_api as PP
    from accfino_core.security.middleware import PUBLIC_ROUTES
    from fastapi import Response
    db, org, ctx = env
    assert "/public/pricing" in PUBLIC_ROUTES                                                      # no sign-in needed for the website
    out = PP.public_pricing(Response(), db)
    assert [p["id"] for p in out["plans"]] == ["essential", "business", "professional", "ultra"]
    assert out["plans"][0]["price_monthly"] == 25.0 and out["plans"][0]["price_yearly"] == 275.0 and out["plans"][3]["seat_limit"] == 1 and out["plans"][3]["all"] is True and out["yearly_months"] == 11
    assert out["plans"][2]["domains"] == ["Books and Accounting", "Payroll & Workforce", "Taxation & Compliance", "Planning & Intelligence"]
    assert len(out["domains"]) == 7 and all(a["extra_seats"] == 0 for a in out["addons"]) and "arranged with the AccFino team" in out["extra_users"]       # user packs are never listed with a public price
    db.add(S.Addon(id="addon-pack-org-9", name="Extra users", price_monthly=S.Decimal("20"), modules="[]", extra_seats=3, sort_order=100)); db.commit()
    assert "addon-pack-org-9" not in [a["id"] for a in PP.public_pricing(Response(), db)["addons"]]
    p = db.get(S.Plan, "essential"); p.price_monthly = S.Decimal("27.00"); db.commit()            # an admin edit shows on the website at once
    assert PP.public_pricing(Response(), db)["plans"][0]["price_monthly"] == 27.0
    p.is_active = False; db.commit()                                                              # hidden plans are not advertised
    assert "essential" not in [x["id"] for x in PP.public_pricing(Response(), db)["plans"]]


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
def test_every_plan_is_one_user_and_yearly_is_eleven_months(env):
    db, org, ctx = env
    plans = {p.id: p for p in db.query(S.Plan).filter_by(is_active=True)}
    assert [(p, int(plans[p].price_monthly), int(plans[p].price_yearly), plans[p].seat_limit) for p in ("essential", "business", "professional", "ultra")] == \
           [("essential", 25, 275, 1), ("business", 59, 649, 1), ("professional", 99, 1089, 1), ("ultra", 179, 1969, 1)]
    assert all(plans[p].price_yearly == plans[p].price_monthly * 11 for p in plans)                        # one month free
    assert not [a.id for a in db.query(S.Addon) if (a.extra_seats or 0) > 0]                               # no public seat packs: more users are arranged with the AccFino team
    db.add(S.Addon(id="addon-pack-org-1", name="Extra users", price_monthly=S.Decimal("20"), modules="[]", extra_seats=3, sort_order=100)); db.commit()
    assign(db, org, "essential", addons=["addon-pack-org-1", "addon-pack-org-1"]); assert S.entitlements(db, org.id)["seats"] == 1 + 3         # listed twice, counted once


# ------------------------------------------------------------------------------------------------ Open banking: a function each plan switches on/off
def test_open_banking_is_a_plan_function_included_by_default_and_switched_off_per_plan(env):
    db, org, ctx = env
    assert "open-banking" in S.CATALOGUE_IDS and "open-banking" not in sum(S.DOMAIN_MODULES.values(), [])           # a function, not part of any business domain
    for pid in ("essential", "business", "professional"):
        assert "open-banking" in S.expand(json.loads(db.get(S.Plan, pid).modules))
    assign(db, org, "essential"); enforce(db)
    assert "open-banking" in S.entitlements(db, org.id)["modules"]
    S.check(db, fake_ctx(ctx, org), ("open-banking",))
    plan = db.get(S.Plan, "essential"); plan.modules = json.dumps(["domain:accounting"]); db.commit()               # the administrator unticks the function in Admin > Pricing > Edit plan
    ent = S.entitlements(db, org.id)
    assert "open-banking" in ent["locked"] and set(S.DOMAIN_MODULES["accounting"]) <= set(ent["modules"])             # only that function goes; all of Books & Accounting stays
    with pytest.raises(HTTPException) as e:
        S.check(db, fake_ctx(ctx, org), ("open-banking",))
    assert e.value.status_code == 402 and "Open banking" in e.value.detail and "Essential" in e.value.detail
    assert {f["id"] for f in ent["features"]} == {"open-banking"}


def test_an_add_on_can_sell_the_function_to_a_plan_that_does_not_have_it(env):
    db, org, ctx = env
    db.get(S.Plan, "essential").modules = json.dumps(["domain:accounting"])
    db.add(S.Addon(id="addon-open-banking", name="Open banking", price_monthly=S.Decimal("10"), modules=json.dumps(["open-banking"]), extra_seats=0, sort_order=50)); db.commit()
    assign(db, org, "essential"); enforce(db)
    assert "open-banking" in S.entitlements(db, org.id)["locked"]
    assign(db, org, "essential", addons=["addon-open-banking"])
    assert "open-banking" in S.entitlements(db, org.id)["modules"]


def test_ultra_always_has_the_function_and_the_admin_api_accepts_it_in_a_plan(env):
    db, org, ctx = env
    assign(db, org, "ultra"); enforce(db)
    assert "open-banking" in S.entitlements(db, org.id)["modules"] and S.entitlements(db, org.id)["locked"] == []
    c, st = make_client(db, org, ctx); st["admin"] = True
    ov = c.get("/admin/subscriptions").json()
    assert [f["id"] for f in ov["features"]] == ["open-banking"] and "open-banking" in [x["id"] for x in ov["catalogue"]]
    ok = c.put("/admin/subscriptions/plans/gold", json={"name": "Gold", "price_monthly": "49", "seat_limit": 1, "modules": ["domain:accounting", "open-banking"]})
    assert ok.status_code == 200 and "open-banking" in ok.json()["modules"]


def test_catalogue_version_5_databases_get_the_function_once_and_it_stays_off_when_removed(env):
    db, org, ctx = env
    db.get(S.Plan, "essential").modules = json.dumps(["domain:accounting"]); db.get(m.SystemSetting, S.CATALOGUE_VERSION_KEY).value = "5"; db.commit()           # a database from the previous release
    S.ensure_catalogue(db); db.commit()
    assert "open-banking" in json.loads(db.get(S.Plan, "essential").modules) and "open-banking" in json.loads(db.get(S.Plan, "business").modules)
    assert db.get(m.SystemSetting, S.CATALOGUE_VERSION_KEY).value == "6"
    db.get(S.Plan, "essential").modules = json.dumps(["domain:accounting"]); db.commit()                              # switched off by the administrator ...
    S.ensure_catalogue(db); db.commit()
    assert "open-banking" not in json.loads(db.get(S.Plan, "essential").modules)                                      # ... and it does not come back

