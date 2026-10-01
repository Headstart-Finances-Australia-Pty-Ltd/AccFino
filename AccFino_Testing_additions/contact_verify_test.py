"""Email and phone VERIFICATION: codes, proof tokens, sign-up / join / profile enforcement, rate limits.
Run from backend/:  PYTHONPATH=. python -m pytest ../AccFino_Testing_additions/contact_verify_test.py -q"""
import os, re, sys
from datetime import datetime, timedelta
import pytest
sys.path.insert(0, os.path.dirname(__file__))
from csv_import_harness import make_db, make_org
from fastapi import FastAPI
from fastapi.testclient import TestClient
from accfino_core import models as m
from accfino_core.api import auth_ext, signup_api
from accfino_core.security import audit, messaging
from accfino_core.security import contact_verify as V
from accfino_core.subscription import service as S
from accfino_core.tenancy.models import OrgProfile
from db_app.database import get_db
from db_app.models import Role, User

PW = "Str0ng!Passw0rd#2026"
ABN = "51 824 753 556"


@pytest.fixture(autouse=True)
def _env(monkeypatch):
    monkeypatch.delenv("TENANT_BASE_DOMAIN", raising=False)
    monkeypatch.setenv("ACCFINO_NOTIFY_SYNC", "1")
    monkeypatch.setenv("CONTACT_VERIFICATION", "both")
    monkeypatch.delenv("SMS_ALLOWED_COUNTRY_CODES", raising=False)


@pytest.fixture()
def env(monkeypatch):
    db = make_db(); make_org(db)
    if not db.query(Role).filter_by(name="user").first():
        db.add(Role(name="user")); db.commit()
    S.ensure_catalogue(db); db.commit()
    mails, texts = [], []
    monkeypatch.setattr(audit, "write", lambda *a, **k: None)
    monkeypatch.setattr(messaging, "send_email", lambda to, subject, body: mails.append((to, subject, body)))
    monkeypatch.setattr(messaging, "send_sms", lambda to, body: texts.append((to, body)))
    app = FastAPI()
    app.include_router(signup_api.signup_router, prefix="/signup"); app.include_router(signup_api.invites_router, prefix="/org/current/invites"); app.include_router(auth_ext.router, prefix="/auth")
    state = {"uid": 1}

    @app.middleware("http")
    async def _a(request, call_next):
        request.state.auth = {"user_id": state["uid"], "username": "u", "is_admin": False, "org_id": None, "mfa": True, "amr": ["pwd"]}
        return await call_next(request)
    app.dependency_overrides[get_db] = lambda: db
    yield db, TestClient(app), state, mails, texts
    db.close()


def last_code(box):
    return re.search(r"code is (\d{6})", box[-1][-1]).group(1)


def clear_cooldown(db):
    db.query(m.MfaChallenge).update({"created_at": datetime.utcnow() - timedelta(minutes=2)}); db.commit()


def prove(db, c, mails, texts, email="owner@alpha.example", phone="0412 345 678"):
    """Run the whole flow for both channels -> (email_token, phone_token)."""
    r = c.post("/signup/contact/send", json={"channel": "email", "destination": email}); assert r.status_code == 200, r.text
    et = c.post("/signup/contact/verify", json={"channel": "email", "destination": email, "code": last_code(mails)}).json()["token"]
    pt = None
    if V.required("phone", "+61412345678") or phone:
        r = c.post("/signup/contact/send", json={"channel": "phone", "destination": phone}); assert r.status_code == 200, r.text
        if r.json()["required"]:
            pt = c.post("/signup/contact/verify", json={"channel": "phone", "destination": phone, "code": last_code(texts)}).json()["token"]
    return et, pt


def new_org(c, **user_extra):
    user = dict(first_name="Olive", last_name="Owner", email="owner@alpha.example", phone="0412 345 678", password=PW); user.update(user_extra)
    return c.post("/signup/organisation", json={"org": dict(name="Alpha Pty Ltd", abn=ABN, address="1 George St", city="Sydney", state="NSW"), "user": user})


# ------------------------------------------------------------------------------------------------ policy
def test_policy_modes_and_sms_reach(monkeypatch):
    assert V.mode() == "both" and V.required("email", "a@b.co") and V.required("phone", "+61412345678") and V.required("phone", "+64211234567")
    assert not V.required("phone", "+447911123456")                                   # no SMS route to the UK: not blockable
    monkeypatch.setenv("SMS_ALLOWED_COUNTRY_CODES", "61,64,44"); assert V.required("phone", "+447911123456")
    monkeypatch.setenv("CONTACT_VERIFICATION", "email"); assert V.required("email", "a@b.co") and not V.required("phone", "+61412345678")
    monkeypatch.setenv("CONTACT_VERIFICATION", "off"); assert not V.required("email", "a@b.co") and not V.required("phone", "+61412345678")
    monkeypatch.setenv("CONTACT_VERIFICATION", "garbage"); assert V.mode() == "both"          # a typo never switches verification off


# ------------------------------------------------------------------------------------------------ sign-up enforcement
def test_signup_without_proof_is_refused_by_the_server(env):
    db, c, state, mails, texts = env
    r = new_org(c)
    assert r.status_code == 422 and r.json()["detail"] == "Please verify your email address."
    assert db.query(User).filter(User.email == "owner@alpha.example").count() == 0 and db.query(m.Organisation).filter(m.Organisation.name == "Alpha Pty Ltd").count() == 0
    et, pt = prove(db, c, mails, texts)
    assert new_org(c, email_token=et).json()["detail"] == "Please verify your phone number."
    assert new_org(c, phone_token=pt).json()["detail"] == "Please verify your email address."
    assert new_org(c, email_token="garbage", phone_token="garbage").status_code == 422


def test_full_flow_creates_a_verified_admin(env):
    db, c, state, mails, texts = env
    et, pt = prove(db, c, mails, texts)
    assert mails[-1][0] == "owner@alpha.example" and texts[-1][0] == "+61412345678"                # the codes went to the right places
    r = new_org(c, email_token=et, phone_token=pt)
    assert r.status_code == 200, r.text
    u = db.query(User).filter(User.email == "owner@alpha.example").one()
    sec = db.get(m.UserSecurity, u.id)
    assert sec.email_verified_at and sec.phone_verified_at
    state["uid"] = u.id
    me = c.get("/auth/me").json()
    assert me["email_verified"] and me["phone_verified"] and me["verification"]["email_needed"] is False and me["verification"]["phone_needed"] is False


def test_a_proof_for_one_address_is_useless_for_another(env):
    db, c, state, mails, texts = env
    et, pt = prove(db, c, mails, texts, email="mine@alpha.example")
    r = new_org(c, email="someone-else@alpha.example", email_token=et, phone_token=pt)               # token proves mine@..., not someone-else@...
    assert r.status_code == 422 and r.json()["detail"] == "Please verify your email address."
    et2, pt2 = prove(db, c, mails, texts, email="owner@alpha.example", phone="0400 000 111")
    assert new_org(c, phone="0400 000 222", email_token=et2, phone_token=pt2).json()["detail"] == "Please verify your phone number."
    assert not V.token_ok(et, "phone", "mine@alpha.example")                                          # nor for the other channel
    assert not V.token_ok(None, "email", "x@y.co") and not V.token_ok("", "email", "x@y.co")


def test_proof_tokens_expire_and_cannot_be_forged(env, monkeypatch):
    import jwt
    from accfino_core.security import tokens
    db, c, state, mails, texts = env
    now = datetime.utcnow()
    good = dict(typ="contact", ch="email", dst="a@b.co", iat=now, exp=now + timedelta(minutes=5))
    assert V.token_ok(jwt.encode(good, tokens._secret(), algorithm="HS256"), "email", "a@b.co")
    assert not V.token_ok(jwt.encode({**good, "exp": now - timedelta(seconds=5)}, tokens._secret(), algorithm="HS256"), "email", "a@b.co")      # expired
    assert not V.token_ok(jwt.encode(good, "some-other-secret", algorithm="HS256"), "email", "a@b.co")                                         # forged
    assert not V.token_ok(jwt.encode({**good, "typ": "access"}, tokens._secret(), algorithm="HS256"), "email", "a@b.co")                       # an access token is not a proof
    assert not V.token_ok(jwt.encode({**good, "typ": "signup"}, tokens._secret(), algorithm="HS256"), "email", "a@b.co")


def test_join_by_code_also_requires_verification(env):
    db, c, state, mails, texts = env
    monkeypatch_off = os.environ.get("CONTACT_VERIFICATION")
    os.environ["CONTACT_VERIFICATION"] = "off"
    try:
        slug = new_org(c).json()["slug"]
        oid = db.query(OrgProfile).filter_by(slug=slug).one().org_id
        state["uid"] = db.query(User).filter(User.email == "owner@alpha.example").one().id
        code = c.post("/org/current/invites", json={"role": "bookkeeper", "count": 1}, headers={"X-Org-Id": str(oid)}).json()["codes"][0]["code"]
    finally:
        os.environ["CONTACT_VERIFICATION"] = monkeypatch_off or "both"
    tok = c.post("/signup/verify-code", json={"slug": slug, "code": code}).json()["signup_token"]
    user = dict(first_name="Bob", last_name="Book", email="bob@alpha.example", phone="0498 765 432", password=PW)
    r = c.post("/signup/join", json={"signup_token": tok, "user": user})
    assert r.status_code == 422 and r.json()["detail"] == "Please verify your email address."
    et, pt = prove(db, c, mails, texts, email="bob@alpha.example", phone="0498 765 432")
    assert c.post("/signup/join", json={"signup_token": tok, "user": {**user, "email_token": et, "phone_token": pt}}).status_code == 200


def test_modes_email_only_and_off(env, monkeypatch):
    db, c, state, mails, texts = env
    monkeypatch.setenv("CONTACT_VERIFICATION", "email")
    et, _ = None, None
    c.post("/signup/contact/send", json={"channel": "email", "destination": "owner@alpha.example"})
    et = c.post("/signup/contact/verify", json={"channel": "email", "destination": "owner@alpha.example", "code": last_code(mails)}).json()["token"]
    assert c.post("/signup/contact/send", json={"channel": "phone", "destination": "0412 345 678"}).json()["required"] is False and texts == []
    assert new_org(c, email_token=et).status_code == 200                                              # phone needs no proof in this mode
    monkeypatch.setenv("CONTACT_VERIFICATION", "off")
    assert new_org(c, email="two@alpha.example", phone="0400 000 333").status_code in (200, 409)       # no proofs at all
    assert c.get("/signup/contact/config").json()["mode"] == "off"


def test_overseas_numbers_are_not_blocked_but_stay_unverified(env):
    db, c, state, mails, texts = env
    r = c.post("/signup/contact/send", json={"channel": "phone", "destination": "+44 7911 123456"})
    assert r.status_code == 200 and r.json()["required"] is False and r.json()["reason"] == "sms_unavailable" and texts == []
    c.post("/signup/contact/send", json={"channel": "email", "destination": "owner@alpha.example"})
    et = c.post("/signup/contact/verify", json={"channel": "email", "destination": "owner@alpha.example", "code": last_code(mails)}).json()["token"]
    assert new_org(c, phone="+44 7911 123456", email_token=et).status_code == 200
    u = db.query(User).filter(User.email == "owner@alpha.example").one()
    assert db.get(m.UserSecurity, u.id).email_verified_at and not db.get(m.UserSecurity, u.id).phone_verified_at


# ------------------------------------------------------------------------------------------------ code rules
def test_wrong_codes_lock_out_after_five_attempts_and_a_new_code_is_needed(env):
    db, c, state, mails, texts = env
    c.post("/signup/contact/send", json={"channel": "email", "destination": "owner@alpha.example"})
    right = last_code(mails); wrong = "000000" if right != "000000" else "111111"
    for _ in range(5):
        assert c.post("/signup/contact/verify", json={"channel": "email", "destination": "owner@alpha.example", "code": wrong}).status_code == 401
    r = c.post("/signup/contact/verify", json={"channel": "email", "destination": "owner@alpha.example", "code": right})
    assert r.status_code == 429                                                                       # even the right code is refused now
    clear_cooldown(db)
    c.post("/signup/contact/send", json={"channel": "email", "destination": "owner@alpha.example"})
    assert c.post("/signup/contact/verify", json={"channel": "email", "destination": "owner@alpha.example", "code": last_code(mails)}).status_code == 200


def test_codes_expire_are_single_use_and_bound_to_the_destination(env):
    db, c, state, mails, texts = env
    c.post("/signup/contact/send", json={"channel": "email", "destination": "owner@alpha.example"}); code = last_code(mails)
    assert c.post("/signup/contact/verify", json={"channel": "email", "destination": "other@alpha.example", "code": code}).status_code == 400      # a code can't verify a different address
    assert c.post("/signup/contact/verify", json={"channel": "email", "destination": "owner@alpha.example", "code": code}).status_code == 200
    assert c.post("/signup/contact/verify", json={"channel": "email", "destination": "owner@alpha.example", "code": code}).status_code == 400      # used
    clear_cooldown(db)
    c.post("/signup/contact/send", json={"channel": "email", "destination": "owner@alpha.example"}); code2 = last_code(mails)
    db.query(m.MfaChallenge).update({"expires_at": datetime.utcnow() - timedelta(seconds=1)}); db.commit()
    r = c.post("/signup/contact/verify", json={"channel": "email", "destination": "owner@alpha.example", "code": code2})
    assert r.status_code == 400 and "expired" in r.json()["detail"]
    assert c.post("/signup/contact/verify", json={"channel": "phone", "destination": "0412 345 678", "code": code2}).status_code == 400            # an email code is not a phone code


def test_codes_are_hashed_at_rest(env):
    db, c, state, mails, texts = env
    c.post("/signup/contact/send", json={"channel": "email", "destination": "owner@alpha.example"}); code = last_code(mails)
    row = db.query(m.MfaChallenge).one()
    assert code not in (row.code_hash or "") and len(row.code_hash) == 64 and row.user_id is None and row.destination == "owner@alpha.example"


def test_sending_is_rate_limited_per_address_and_per_ip(env):
    db, c, state, mails, texts = env
    assert c.post("/signup/contact/send", json={"channel": "email", "destination": "owner@alpha.example"}).status_code == 200
    assert c.post("/signup/contact/send", json={"channel": "email", "destination": "owner@alpha.example"}).status_code == 429               # 30-second cooldown
    for _ in range(5):
        clear_cooldown(db); assert c.post("/signup/contact/send", json={"channel": "email", "destination": "owner@alpha.example"}).status_code == 200
    clear_cooldown(db)
    db.query(m.MfaChallenge).update({"created_at": datetime.utcnow() - timedelta(minutes=2)}); db.commit()
    assert c.post("/signup/contact/send", json={"channel": "email", "destination": "owner@alpha.example"}).status_code == 429               # 6 per hour
    n = 0                                                                                                                                 # many different addresses from one IP
    for i in range(40):
        r = c.post("/signup/contact/send", json={"channel": "email", "destination": f"user{i}@alpha.example"})
        n += r.status_code == 200
    assert n <= V.MAX_PER_IP_HOUR


def test_invalid_input_is_rejected_before_anything_is_sent(env):
    db, c, state, mails, texts = env
    for body in ({"channel": "email", "destination": "nope"}, {"channel": "email", "destination": ""}, {"channel": "phone", "destination": "12"}, {"channel": "fax", "destination": "x"}):
        assert c.post("/signup/contact/send", json=body).status_code == 422, body
    assert mails == [] and texts == []


def test_delivery_failure_is_reported_without_leaking_details(env, monkeypatch):
    db, c, state, mails, texts = env
    def boom(*a): raise messaging.DeliveryError("smtp password wrong at mail.internal:587")
    monkeypatch.setattr(messaging, "send_email", boom)
    r = c.post("/signup/contact/send", json={"channel": "email", "destination": "owner@alpha.example"})
    assert r.status_code == 502 and "smtp" not in r.text.lower() and "internal" not in r.text


# ------------------------------------------------------------------------------------------------ profile
def make_user(c, db, mails, texts):
    et, pt = prove(db, c, mails, texts)
    assert new_org(c, email_token=et, phone_token=pt).status_code == 200
    u = db.query(User).filter(User.email == "owner@alpha.example").one()
    return u.id


def test_changing_email_or_phone_needs_a_fresh_proof_and_resets_verification(env):
    db, c, state, mails, texts = env
    state["uid"] = make_user(c, db, mails, texts)
    r = c.patch("/auth/me/profile", json={"email": "new@alpha.example", "current_password": PW})
    assert r.status_code == 422 and r.json()["detail"] == "Please verify your email address."
    c.post("/auth/me/contact/send", json={"channel": "email", "destination": "new@alpha.example"})
    et = c.post("/auth/me/contact/verify", json={"channel": "email", "destination": "new@alpha.example", "code": last_code(mails)}).json()["token"]
    assert c.patch("/auth/me/profile", json={"email": "other@alpha.example", "email_token": et, "current_password": PW}).status_code == 422          # proof is for another address
    r = c.patch("/auth/me/profile", json={"email": "new@alpha.example", "email_token": et, "current_password": PW})
    assert r.status_code == 200 and r.json()["email"] == "new@alpha.example" and r.json()["email_verified"] is True
    # phone: change without proof is refused; with proof it is accepted
    assert c.patch("/auth/me/profile", json={"phone": "0455 123 456", "current_password": PW}).json()["detail"] == "Please verify your phone number."
    clear_cooldown(db)
    c.post("/auth/me/contact/send", json={"channel": "phone", "destination": "0455 123 456"})
    pt = c.post("/auth/me/contact/verify", json={"channel": "phone", "destination": "0455 123 456", "code": last_code(texts)}).json()["token"]
    r = c.patch("/auth/me/profile", json={"phone": "0455 123 456", "phone_token": pt, "current_password": PW})
    assert r.status_code == 200 and r.json()["phone"] == "+61455123456" and r.json()["phone_verified"] is True


def test_an_existing_unverified_account_can_verify_what_it_already_has(env, monkeypatch):
    db, c, state, mails, texts = env
    monkeypatch.setenv("CONTACT_VERIFICATION", "off")
    assert new_org(c).status_code == 200                                                              # an account that pre-dates verification
    u = db.query(User).filter(User.email == "owner@alpha.example").one(); state["uid"] = u.id
    monkeypatch.setenv("CONTACT_VERIFICATION", "both")
    me = c.get("/auth/me").json()
    assert me["email_verified"] is False and me["verification"]["email_needed"] is True and me["verification"]["phone_needed"] is True
    assert c.get("/org/current/../../auth/me").status_code in (200, 404)
    c.post("/auth/me/contact/send", json={"channel": "email", "destination": "owner@alpha.example"})
    et = c.post("/auth/me/contact/verify", json={"channel": "email", "destination": "owner@alpha.example", "code": last_code(mails)}).json()["token"]
    r = c.patch("/auth/me/profile", json={"email_token": et})                                         # no change, just proving the current address
    assert r.status_code == 200 and r.json()["email_verified"] is True and r.json()["phone_verified"] is False
    assert c.patch("/auth/me/profile", json={"email_token": "junk"}).status_code == 200               # a junk token proves nothing and changes nothing
    assert c.get("/auth/me").json()["phone_verified"] is False


def test_contact_endpoints_for_signed_in_users_need_a_session(env):
    db, c, state, mails, texts = env
    from accfino_core.security.context import current_auth
    app = FastAPI(); app.include_router(auth_ext.router, prefix="/auth"); app.dependency_overrides[get_db] = lambda: db
    anon = TestClient(app)
    assert anon.post("/auth/me/contact/send", json={"channel": "email", "destination": "a@b.co"}).status_code == 401
    assert anon.post("/auth/me/contact/verify", json={"channel": "email", "destination": "a@b.co", "code": "123456"}).status_code == 401
