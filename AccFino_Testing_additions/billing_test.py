"""Automatic subscription billing through Square - against a MOCK Square (httpx.MockTransport) that behaves like the real one where it matters:
same idempotency key = same payment, declines come back as errors, a payment needs a card on file for a customer.
Run from backend/:  PYTHONPATH=. python -m pytest ../AccFino_Testing_additions/billing_test.py -q"""
import json, os, re, sys
from datetime import date, datetime, timedelta
from decimal import Decimal
import httpx, pytest
sys.path.insert(0, os.path.dirname(__file__))
from csv_import_harness import make_db, make_org
from accfino_core import models as m, notifications as N
from accfino_core.billing import service as B, square_client as SQ
from accfino_core.billing.models import BillingCharge, OrgBilling
from accfino_core.subscription import service as S
from accfino_core.subscription.models import OrgSubscription


class MockSquare:
    def __init__(self):
        self.payments, self.by_key, self.cards, self.customers, self.calls = [], {}, {}, {}, []
        self.decline = False            # next payments are declined while True
        self.down = False
        self.currency, self.country = "AUD", "AU"

    def __call__(self, req: httpx.Request) -> httpx.Response:
        if self.down:
            raise httpx.ConnectError("down")
        path, body = req.url.path, (json.loads(req.content) if req.content else {})
        self.calls.append((req.method, path))
        assert req.headers["Authorization"] == "Bearer TOKEN-1" and req.headers["Square-Version"]
        if path.startswith("/v2/locations/"):
            return httpx.Response(200, json={"location": {"id": "L1", "name": "AccFino HQ", "currency": self.currency, "country": self.country}})
        if path == "/v2/customers":
            cid = "CUST-" + str(len(self.customers) + 1); self.customers[cid] = body
            return httpx.Response(200, json={"customer": {"id": cid}})
        if path == "/v2/cards":
            assert body["source_id"].startswith("cnon:") and body["card"]["customer_id"] in self.customers          # a one-time token from the browser, never a card number
            cid = "ccof:" + str(len(self.cards) + 1); self.cards[cid] = {"enabled": True}
            return httpx.Response(200, json={"card": {"id": cid, "card_brand": "VISA", "last_4": "1111", "exp_month": 12, "exp_year": 2030}})
        mm = re.match(r"/v2/cards/(.+)/disable", path)
        if mm:
            self.cards[mm.group(1)]["enabled"] = False; return httpx.Response(200, json={"card": {}})
        if path == "/v2/payments":
            k = body["idempotency_key"]
            if k in self.by_key:                                                                                       # the real API returns the ORIGINAL payment
                return httpx.Response(200, json={"payment": self.by_key[k]})
            assert self.cards[body["source_id"]]["enabled"] and body["customer_id"] in self.customers and body["amount_money"]["currency"] == "AUD" and body["autocomplete"] is True
            if self.decline:
                return httpx.Response(402, json={"errors": [{"category": "PAYMENT_METHOD_ERROR", "code": "CARD_DECLINED", "detail": "The card was declined."}]})
            p = {"id": f"PAY-{len(self.payments) + 1}", "status": "COMPLETED", "receipt_url": f"https://squareup.com/receipt/{len(self.payments) + 1}", "amount_money": body["amount_money"]}
            self.payments.append(body); self.by_key[k] = p
            return httpx.Response(200, json={"payment": p})
        return httpx.Response(404)


@pytest.fixture()
def env(monkeypatch):
    for k in ("SQUARE_ACCESS_TOKEN", "SQUARE_APPLICATION_ID", "SQUARE_LOCATION_ID", "SQUARE_ENVIRONMENT"):
        monkeypatch.delenv(k, raising=False)
    db = make_db(); org, ctx = make_org(db)
    S.ensure_catalogue(db); S.start_subscription(db, org.id); db.commit()
    mock = MockSquare(); monkeypatch.setattr(SQ, "_transport", httpx.MockTransport(mock))
    B.save_square(db, access_token="TOKEN-1", application_id="sq0idp-APP", location_id="L1", environment="sandbox"); db.commit()
    sent = []
    monkeypatch.setattr(N, "notify_org_admin", lambda db, org_id, kind, subject, body, **kw: sent.append((kind, subject, body)) or True)
    yield db, org, ctx, mock, sent
    db.close()


def add_card(db, org, ctx, token="cnon:card-1"):
    b = B.save_card(db, org, ctx.user_id, token); db.commit(); return b


# --------------------------------------------------------------------------------------------------------- platform config --
def test_platform_square_is_sealed_blank_token_keeps_and_status_has_no_secret(env, monkeypatch):
    db, org, ctx, mock, sent = env
    raw = db.get(m.SystemSetting, "square.access_token").value
    assert "TOKEN-1" not in raw and B.unseal(raw) == "TOKEN-1"
    st = B.square_status(db); assert st["configured"] and "TOKEN-1" not in str(st) and st["environment"] == "sandbox"
    B.save_square(db, access_token="", environment="production"); db.commit()
    assert B.SquareCfg(db).access_token == "TOKEN-1" and B.SquareCfg(db).environment == "production"             # blank keeps the token
    with pytest.raises(B.BillingError): B.save_square(db, environment="staging")
    monkeypatch.setenv("SQUARE_ACCESS_TOKEN", "ENV-TOKEN"); assert B.SquareCfg(db).access_token == "ENV-TOKEN" and B.square_status(db)["locked_by_environment"]


def test_test_button_checks_the_location_and_the_currency(env):
    db, org, ctx, mock, sent = env
    assert B.test_square(db)["ok"] and "AccFino HQ" in B.test_square(db)["message"]
    mock.currency = "USD"; r = B.test_square(db); assert r["ok"] is False and "AUD" in r["message"]


# -------------------------------------------------------------------------------------------------------------- pricing --
def test_amounts_follow_the_plan_period_and_add_ons_and_month_ends_are_clamped(env):
    db, org, ctx, mock, sent = env
    sub = db.get(OrgSubscription, org.id)
    sub.plan_id, sub.addons, sub.billing_period = "essentials", "[]", "monthly"
    assert B.amount_for(db, sub) == Decimal("25.00") and B.cents(B.amount_for(db, sub)) == 2500
    sub.billing_period = "yearly"; assert B.amount_for(db, sub) == Decimal("250.00")
    sub.addons = json.dumps(["addon-payroll"]); assert B.amount_for(db, sub) == Decimal("400.00")                # 250 + 15 x 10 months
    sub.billing_period = "monthly"; assert B.amount_for(db, sub) == Decimal("40.00")
    assert B.add_period(date(2026, 1, 31), "monthly") == date(2026, 2, 28) and B.add_period(date(2028, 2, 29), "yearly") == date(2029, 2, 28)


# ------------------------------------------------------------------------------------------------------------------ card --
def test_card_is_saved_via_token_only_and_replacing_it_disables_the_old_one(env):
    db, org, ctx, mock, sent = env
    b = add_card(db, org, ctx)
    assert (b.card_brand, b.card_last4, b.square_customer_id) == ("Visa", "1111", "CUST-1")
    cols = " ".join(str(getattr(b, c.name)) for c in OrgBilling.__table__.columns)
    assert "cnon:" not in cols and "4111" not in cols                                                              # no token, no card number stored
    first = b.card_id; b2 = add_card(db, org, ctx, "cnon:card-2")
    assert b2.card_id != first and mock.cards[first]["enabled"] is False and len(mock.customers) == 1             # same Square customer, old card no longer chargeable
    B.remove_card(db, org.id); db.commit(); assert db.get(OrgBilling, org.id).card_id is None and db.get(OrgBilling, org.id).auto_renew is False


def test_card_cannot_be_saved_until_the_platform_is_set_up(env):
    db, org, ctx, mock, sent = env
    B.save_square(db, application_id="", location_id=""); db.commit()
    with pytest.raises(B.BillingError) as e: B.save_card(db, org, ctx.user_id, "cnon:x")
    assert e.value.code == "not_configured" and "contact AccFino support" in e.value.message


# ------------------------------------------------------------------------------------------------------------- subscribe --
def test_subscribe_takes_the_first_payment_and_never_twice_for_a_paid_period(env):
    db, org, ctx, mock, sent = env
    add_card(db, org, ctx)
    res = B.subscribe(db, org.id, "monthly", ctx.user_id); db.commit()
    assert res["status"] == "paid" and res["amount"] == 25.0 and len(mock.payments) == 1
    sub, b = db.get(OrgSubscription, org.id), db.get(OrgBilling, org.id)
    assert sub.status == "active" and sub.period_end == B.add_period(date.today(), "monthly") and b.auto_renew is True
    p = mock.payments[0]; assert p["amount_money"] == {"amount": 2500, "currency": "AUD"} and p["location_id"] == "L1" and "essentials" in p["note"].lower()
    ch = db.query(BillingCharge).one(); assert ch.status == "paid" and ch.square_payment_id == "PAY-1" and ch.receipt_url
    again = B.subscribe(db, org.id, "monthly", ctx.user_id); db.commit()
    assert again["status"] == "scheduled" and len(mock.payments) == 1                                               # already paid up: no second charge
    with pytest.raises(B.BillingError): B.subscribe(db, org.id, "weekly", ctx.user_id)


def test_yearly_subscription_charges_the_yearly_price(env):
    db, org, ctx, mock, sent = env
    add_card(db, org, ctx)
    res = B.subscribe(db, org.id, "yearly", ctx.user_id); db.commit()
    assert res["amount"] == 250.0 and db.get(OrgSubscription, org.id).period_end == B.add_period(date.today(), "yearly")


def test_a_declined_first_payment_is_reported_and_does_not_activate(env):
    db, org, ctx, mock, sent = env
    add_card(db, org, ctx); mock.decline = True
    res = B.subscribe(db, org.id, "monthly", ctx.user_id); db.commit()
    assert res["status"] == "failed" and "declined" in res["error"] and db.get(OrgSubscription, org.id).period_end is None


# -------------------------------------------------------------------------------------------------------------- renewals --
def subscribed(env, period="monthly"):
    db, org, ctx, mock, sent = env
    add_card(db, org, ctx); B.subscribe(db, org.id, period, ctx.user_id); db.commit(); return db, org, ctx, mock, sent


def test_renewal_charges_when_the_period_ends_once_and_keeps_the_dates_continuous(env):
    db, org, ctx, mock, sent = subscribed(env)
    end = db.get(OrgSubscription, org.id).period_end
    assert B.run_due(lambda: db_factory(db), today=end - timedelta(days=1))["skipped"] == 1 and len(mock.payments) == 1      # not due yet
    r = B.run_due(lambda: db_factory(db), today=end); assert r["paid"] == 1 and len(mock.payments) == 2
    assert db.get(OrgSubscription, org.id).period_end == B.add_period(end, "monthly")                                       # continues from the old end date
    r = B.run_due(lambda: db_factory(db), today=end); assert r["paid"] == 0 and len(mock.payments) == 2                        # same day again: nothing


def test_paying_late_starts_the_new_period_today_not_in_the_past(env):
    db, org, ctx, mock, sent = subscribed(env)
    late = db.get(OrgSubscription, org.id).period_end + timedelta(days=5)
    B.run_due(lambda: db_factory(db), today=late)
    assert db.get(OrgSubscription, org.id).period_end == B.add_period(late, "monthly")


def test_two_workers_cannot_charge_the_same_renewal(env):
    db, org, ctx, mock, sent = subscribed(env)
    end = db.get(OrgSubscription, org.id).period_end
    key = f"accfino-{org.id}-{end.isoformat()}-monthly-0"
    db.add(BillingCharge(org_id=org.id, idempotency_key=key, amount_cents=2500, status="pending", created_at=datetime.utcnow())); db.commit()   # another worker got there first
    assert B.charge_now(db, org.id, today=end)["status"] == "skipped" and len(mock.payments) == 1


def test_a_crashed_charge_is_completed_safely_with_the_same_key(env):
    db, org, ctx, mock, sent = subscribed(env)
    end = db.get(OrgSubscription, org.id).period_end
    key = f"accfino-{org.id}-{end.isoformat()}-monthly-0"
    mock.by_key[key] = {"id": "PAY-LOST", "status": "COMPLETED", "receipt_url": "r"}                                          # Square DID take the money before our server died
    mock.payments.append({}); db.add(BillingCharge(org_id=org.id, idempotency_key=key, amount_cents=2500, status="pending", created_at=datetime.utcnow() - timedelta(hours=1))); db.commit()
    res = B.charge_now(db, org.id, today=end); db.commit()
    assert res["status"] == "paid" and res["payment_id"] == "PAY-LOST" and len(mock.payments) == 2                              # no third payment: same key returned the original


def test_declines_retry_on_day_3_and_6_then_stop_and_a_new_card_fixes_it(env):
    db, org, ctx, mock, sent = subscribed(env)
    end = db.get(OrgSubscription, org.id).period_end
    mock.decline = True
    r = B.run_due(lambda: db_factory(db), today=end); assert r["failed"] == 1
    b, sub = db.get(OrgBilling, org.id), db.get(OrgSubscription, org.id)
    assert sub.status == "past_due" and b.failure_count == 1 and b.next_attempt_on == end + timedelta(days=3) and "declined" in b.last_error
    assert sent and sent[-1][0] == "billing_failed" and "update your card" in sent[-1][2].lower()                          # the Organisation Admin is told
    assert B.run_due(lambda: db_factory(db), today=end + timedelta(days=1))["skipped"] == 1                                 # waits until day 3
    B.run_due(lambda: db_factory(db), today=end + timedelta(days=3)); assert db.get(OrgBilling, org.id).failure_count == 2
    B.run_due(lambda: db_factory(db), today=end + timedelta(days=6))
    b = db.get(OrgBilling, org.id); assert b.failure_count == 3 and b.next_attempt_on is None
    calls = len(mock.calls)
    assert B.run_due(lambda: db_factory(db), today=end + timedelta(days=30))["skipped"] == 1 and len(mock.calls) == calls   # stops: no more hits on the card
    mock.decline = False
    add_card(db, org, ctx, "cnon:new-card")                                                                                  # a new card resets the counter
    assert db.get(OrgBilling, org.id).failure_count == 0
    assert B.charge_now(db, org.id, today=end + timedelta(days=31))["status"] == "paid" and db.get(OrgSubscription, org.id).status == "active"


def test_square_being_down_is_recorded_not_raised(env):
    db, org, ctx, mock, sent = subscribed(env)
    end = db.get(OrgSubscription, org.id).period_end; mock.down = True
    r = B.run_due(lambda: db_factory(db), today=end)
    assert r["failed"] == 1 and r["errors"] == 0 and db.get(OrgBilling, org.id).failure_count == 1


def test_trial_converts_to_paid_on_the_trial_end_date_and_free_plans_just_roll_on(env):
    db, org, ctx, mock, sent = env
    add_card(db, org, ctx); b = db.get(OrgBilling, org.id); b.auto_renew = True
    sub = db.get(OrgSubscription, org.id); sub.status, sub.trial_ends, sub.period_end = "trial", date.today(), None; db.commit()
    assert B.run_due(lambda: db_factory(db), today=date.today())["paid"] == 1 and db.get(OrgSubscription, org.id).status == "active"
    from accfino_core.subscription.models import Plan
    db.get(Plan, "essentials").price_monthly = Decimal("0"); sub = db.get(OrgSubscription, org.id); sub.period_end = date.today(); db.commit()
    n = len(mock.payments); assert B.run_due(lambda: db_factory(db), today=date.today())["free"] == 1 and len(mock.payments) == n


def test_cancelled_and_no_auto_renew_organisations_are_never_charged(env):
    db, org, ctx, mock, sent = subscribed(env)
    end = db.get(OrgSubscription, org.id).period_end
    db.get(OrgBilling, org.id).auto_renew = False; db.commit()
    assert B.run_due(lambda: db_factory(db), today=end)["paid"] == 0
    db.get(OrgBilling, org.id).auto_renew = True; db.get(OrgSubscription, org.id).status = "cancelled"; db.commit()
    assert B.run_due(lambda: db_factory(db), today=end)["paid"] == 0 and len(mock.payments) == 1


def db_factory(db):
    """run_due opens/closes its own sessions; tests share one in-memory session, so hand back a non-closing view of it."""
    class Keep:
        def __getattr__(self, n): return getattr(db, n)
        def close(self): db.commit()
    return Keep()


# ------------------------------------------------------------------------------------------------------------------- HTTP --
def http(env, role="owner", admin=False):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from accfino_core.api import billing_api as API
    from accfino_core.security.context import OrgContext, current_org
    from db_app.database import get_db
    db, org, ctx, mock, sent = env
    app = FastAPI(); st = dict(role=role, admin=admin)
    app.include_router(API.admin_router, prefix="/admin/billing"); app.include_router(API.org_router, prefix="/org/current/billing")
    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[current_org] = lambda: OrgContext(ctx.user_id, "tester", st["admin"], org, st["role"])
    @app.middleware("http")
    async def _a(request, call_next):
        request.state.auth = {"user_id": ctx.user_id, "username": "tester", "is_admin": st["admin"]}
        return await call_next(request)
    return TestClient(app), st


def test_http_only_the_organisation_admin_manages_billing_and_nothing_secret_is_returned(env):
    c, st = http(env, role="accountant")
    v = c.get("/org/current/billing").json()
    assert v["available"] and v["can_manage"] is False and v["square"]["applicationId"] == "sq0idp-APP" and "TOKEN-1" not in json.dumps(v)     # app id is public, the token never is
    assert c.post("/org/current/billing/card", json={"source_id": "cnon:x"}).status_code == 403
    assert c.post("/org/current/billing/subscribe", json={"billing_period": "monthly"}).status_code == 403
    assert c.delete("/org/current/billing/card").status_code == 403
    st["role"] = "owner"
    assert c.post("/org/current/billing/subscribe", json={"billing_period": "monthly"}).status_code == 409                    # no card yet
    out = c.post("/org/current/billing/card", json={"source_id": "cnon:card-1"}).json()
    assert out["card"]["last4"] == "1111" and "cnon" not in json.dumps(out)
    sub = c.post("/org/current/billing/subscribe", json={"billing_period": "yearly"}).json()
    assert sub["charge"]["status"] == "paid" and sub["amount_next"] == 250.0 and sub["auto_renew"] is True and sub["charges"][0]["status"] == "paid"
    assert c.post("/org/current/billing/auto-renew", json={"enabled": False}).json()["auto_renew"] is False


def test_http_a_declined_subscribe_is_a_clear_402(env):
    c, st = http(env); db, org, ctx, mock, sent = env
    c.post("/org/current/billing/card", json={"source_id": "cnon:card-1"}); mock.decline = True
    r = c.post("/org/current/billing/subscribe", json={"billing_period": "monthly"})
    assert r.status_code == 402 and "declined" in r.json()["detail"]


def test_http_platform_square_set_up_is_admin_only(env):
    c, st = http(env)
    assert c.get("/admin/billing/square").status_code == 403 and c.put("/admin/billing/square", json={}).status_code == 403 and c.post("/admin/billing/run").status_code == 403
    st["admin"] = True
    s = c.get("/admin/billing/square").json(); assert s["configured"] and "TOKEN-1" not in json.dumps(s)
    assert c.put("/admin/billing/square", json={"environment": "nope"}).status_code == 422
    assert c.post("/admin/billing/square/test").json()["ok"] is True
    assert c.get("/admin/billing/overview").json()["organisations"] == []
