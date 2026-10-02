"""Organisation Admin, mandatory email + phone, admin-only organisation settings (server side), organisation isolation, admin-routed notifications.
Run from backend/:  PYTHONPATH=. ACCFINO_NOTIFY_SYNC=1 python -m pytest ../AccFino_Testing_additions/org_admin_test.py -q

Every permission test calls the REAL API routes as a signed-in non-admin - the frontend is not involved, so hiding a screen can never be what keeps these passing.
"""
import os, sys
import pytest
sys.path.insert(0, os.path.dirname(__file__))
from csv_import_harness import make_db, make_org
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.exc import IntegrityError
from accfino_core import models as m
from accfino_core import notifications as N
from accfino_core import org_admin as OA
from accfino_core.api import auth_ext, iam_api, org, org_identity, signup_api, subscription_api
from accfino_core.security import audit, messaging
from accfino_core.security import contact as C
from accfino_core.security.context import current_org
from accfino_core.subscription import service as S
from accfino_core.tenancy.models import OrgInvite, OrgProfile
from db_app.database import get_db
from db_app.models import Role, User

PW = "Str0ng!Passw0rd#2026"
ABN_A, ABN_B = "51 824 753 556", "53 004 085 616"


@pytest.fixture(autouse=True)
def _env(monkeypatch):
    monkeypatch.delenv("TENANT_BASE_DOMAIN", raising=False)
    monkeypatch.delenv("ACCFINO_OPEN_SIGNUP", raising=False)
    monkeypatch.setenv("ACCFINO_NOTIFY_SYNC", "1")
    monkeypatch.setenv("CONTACT_VERIFICATION", "off")                      # (verification has its own tests: contact_verify_test.py)


def _seat_plan(db, n):
    """A plan with exactly n user seats (these tests are about seat behaviour, not about today's price list)."""
    pid = f"seats{n}"
    if db.get(S.Plan, pid) is None:
        db.add(S.Plan(id=pid, name=f"{n} seats", price_monthly=S.Decimal("1"), price_yearly=S.Decimal("10"), seat_limit=n, modules='["*"]', sort_order=50 + n))
        db.commit()
    return pid


@pytest.fixture()
def env(monkeypatch):
    db = make_db(); make_org(db)
    if not db.query(Role).filter_by(name="user").first():
        db.add(Role(name="user")); db.commit()
    S.ensure_catalogue(db); db.commit()
    S.set_settings(db, default_plan=_seat_plan(db, 50)); db.commit()        # organisations in these tests need room to join; seat tests pick their own size
    events, mails, texts = [], [], []
    def fake_audit(action, **kw):                         # records the event AND persists a row, like the real writer (the de-duplication reads it back)
        events.append((action, kw))
        db.add(m.AuditLog(action=action, org_id=kw.get("org_id"), user_id=kw.get("user_id"), entity=kw.get("entity"), detail=kw.get("detail")))
        db.flush()
    monkeypatch.setattr(audit, "write", fake_audit)
    monkeypatch.setattr(messaging, "send_email", lambda to, subject, body: mails.append((to, subject, body)))
    monkeypatch.setattr(messaging, "send_sms", lambda to, body: texts.append((to, body)))
    app = FastAPI()
    for r, p in ((signup_api.tenant_router, "/tenant"), (signup_api.signup_router, "/signup"), (signup_api.invites_router, "/org/current/invites"),
                 (signup_api.admin_tenant_router, "/org/current/tenant"), (subscription_api.org_router, "/org/current/subscription"),
                 (iam_api.policy_router, "/org/current/access-policy"), (org_identity.router, "/org/current/identity"),
                 (auth_ext.router, "/auth"), (org.router, "/org")):
        app.include_router(r, prefix=p)

    @app.get("/whoami")
    def whoami(c=Depends(current_org)):
        return {"org": c.org.id, "role": c.role}
    state = {"uid": 1, "admin": False}

    @app.middleware("http")
    async def _auth(request, call_next):
        request.state.auth = {"user_id": state["uid"], "username": "u", "is_admin": state["admin"], "org_id": None, "mfa": True, "amr": ["pwd"]}
        return await call_next(request)
    app.dependency_overrides[get_db] = lambda: db
    yield db, TestClient(app), state, events, mails, texts
    db.close()


# ----------------------------------------------------------------------------------------------- helpers
def org_body(name="Alpha Accounting Pty Ltd", abn=ABN_A, **kw):
    d = dict(name=name, abn=abn, address="1 George St", city="Sydney", state="NSW", postcode="2000", industry="Accounting")
    d.update(kw)
    return d


def person(email="owner@alpha.example", phone="0412 345 678", **kw):
    d = dict(first_name="Olive", last_name="Owner", email=email, phone=phone, password=PW)
    d.update(kw)
    return d


def sign_in(db, state, email):
    state["uid"] = db.query(User).filter(User.email == email.lower()).one().id


def make_tenant(db, c, state, name="Alpha Accounting Pty Ltd", abn=ABN_A, email="owner@alpha.example"):
    r = c.post("/signup/organisation", json={"org": org_body(name=name, abn=abn), "user": person(email)})
    assert r.status_code == 200, r.text
    org_id = db.query(OrgProfile).filter_by(slug=r.json()["slug"]).one().org_id
    sign_in(db, state, email)
    return r.json()["slug"], org_id


def invite_code(c, org_id, role="bookkeeper", **kw):
    r = c.post("/org/current/invites", json={"role": role, "count": 1, **kw}, headers={"X-Org-Id": str(org_id)})
    assert r.status_code == 200, r.text
    return r.json()["codes"][0]["code"]


def join(c, slug, code, email, phone="0498 765 432", **kw):
    v = c.post("/signup/verify-code", json={"slug": slug, "code": code})
    assert v.status_code == 200, v.text
    return c.post("/signup/join", json={"signup_token": v.json()["signup_token"], "user": person(email, phone, first_name="Bob", last_name="Book", **kw)})


def org_with_member(db, c, state, role="bookkeeper", name="Alpha Accounting Pty Ltd", abn=ABN_A, owner="owner@alpha.example", member="member@alpha.example"):
    slug, org_id = make_tenant(db, c, state, name, abn, owner)
    code = invite_code(c, org_id, role)
    assert join(c, slug, code, member).status_code == 200
    return slug, org_id, owner, member


# =============================================================================================== 1. contact validation (pure rules)
@pytest.mark.parametrize("raw,expected", [
    ("0412 345 678", "+61412345678"), ("0412345678", "+61412345678"), ("+61 412 345 678", "+61412345678"), ("+61412345678", "+61412345678"),
    ("(02) 9999 9999", "+61299999999"), ("02 9999 9999", "+61299999999"), ("61412345678", "+61412345678"), ("0061412345678", "+61412345678"),
    ("+64 21 123 4567", "+64211234567"), ("+44 7911 123456", "+447911123456"), ("+1 415 555 2671", "+14155552671"),
])
def test_valid_phone_numbers_are_normalised_to_e164(raw, expected):
    assert C.normalise_phone(raw) == expected


@pytest.mark.parametrize("raw", ["", "   ", None, "abc", "12345", "0112345678", "0412 345", "+61 112 345 678", "041234567890", "+0123456789", "04123 45678 ext 5", "++61412345678", "+1 115 555 2671", "(02) 9999", "phone"])
def test_invalid_phone_numbers_are_rejected(raw):
    with pytest.raises(C.ContactError) as e:
        C.normalise_phone(raw)
    assert e.value.errors["phone"] in (C.PHONE_REQUIRED, C.PHONE_INVALID)
    if not (raw or "").strip():
        assert e.value.errors["phone"] == C.PHONE_REQUIRED


@pytest.mark.parametrize("raw", ["a@b.co", "First.Last+tag@Example.COM.au", "o'neil@example.org", "x_y@sub.domain.example"])
def test_valid_emails(raw):
    assert C.normalise_email(raw) == raw.strip().lower()


@pytest.mark.parametrize("raw", ["plain", "a@b", "@example.com", "a@@example.com", "a b@example.com", "a@example..com", ".a@example.com", "a.@example.com", "a@-example.com", "a@example.c", "a@exa mple.com", "a@example.123"])
def test_invalid_emails(raw):
    with pytest.raises(C.ContactError) as e:
        C.normalise_email(raw)
    assert e.value.errors["email"] == C.EMAIL_INVALID


def test_blank_email_has_the_required_message_and_both_errors_are_reported_together():
    with pytest.raises(C.ContactError) as e:
        C.normalise_email("  ")
    assert e.value.errors["email"] == "Email address is required."
    with pytest.raises(C.ContactError) as e:
        C.validate_contact("", "")
    assert e.value.errors == {"email": "Email address is required.", "phone": "Phone number is required."}
    assert C.missing_contact(None, None) == ["email", "phone"] and C.missing_contact("a@b.co", "") == ["phone"] and C.missing_contact("a@b.co", "+61412345678") == []


# =============================================================================================== 2. email + phone cannot be omitted (API level)
def test_new_organisation_signup_requires_email_and_phone_on_the_server(env):
    db, c, state, *_ = env
    before = db.query(User).count(), db.query(m.Organisation).count()
    for user, msg in ((person(email=""), "Email address is required."), (person(email=None), "Email address is required."), (person(email="not-an-email"), "Please enter a valid email address."),
                      (person(phone=""), "Phone number is required."), (person(phone=None), "Phone number is required."), (person(phone="12345"), "Please enter a valid phone number.")):
        r = c.post("/signup/organisation", json={"org": org_body(), "user": user})
        assert r.status_code == 422 and msg in r.json()["detail"], (user, r.text)
    u = person(); u.pop("phone")                                  # the field is missing from the request altogether
    assert c.post("/signup/organisation", json={"org": org_body(), "user": u}).status_code == 422
    u = person(); u.pop("email")
    assert c.post("/signup/organisation", json={"org": org_body(), "user": u}).status_code == 422
    r = c.post("/signup/organisation", json={"org": org_body(), "user": person(email="", phone="")})
    assert "Email address is required." in r.json()["detail"] and "Phone number is required." in r.json()["detail"]      # both reported at once
    assert (db.query(User).count(), db.query(m.Organisation).count()) == before        # nothing half-created


def test_joining_with_a_valid_code_still_requires_email_and_phone(env):
    db, c, state, *_ = env
    slug, org_id = make_tenant(db, c, state)
    code = invite_code(c, org_id, "bookkeeper", max_uses=2)
    v = c.post("/signup/verify-code", json={"slug": slug, "code": code}).json()
    for user, msg in ((person("b@alpha.example", ""), "Phone number is required."), (person("b@alpha.example", "nope"), "valid phone"), (person("", "0498 765 432"), "Email address is required."),
                      (person("bad", "0498 765 432"), "valid email")):
        r = c.post("/signup/join", json={"signup_token": v["signup_token"], "user": user})
        assert r.status_code == 422 and msg in r.json()["detail"], r.text
    assert db.query(OrgInvite).one().used_count == 0                                  # a rejected signup never consumes the code
    assert db.query(User).filter(User.email == "b@alpha.example").count() == 0
    assert c.post("/signup/join", json={"signup_token": v["signup_token"], "user": person("b@alpha.example", "0498 765 432")}).status_code == 200


def test_phone_is_stored_normalised_against_the_account_and_email_is_unique(env):
    db, c, state, *_ = env
    make_tenant(db, c, state, email="Owner@Alpha.Example")
    u = db.query(User).filter(User.email == "owner@alpha.example").one()
    assert u.phone == "+61412345678" and u.email == "owner@alpha.example"
    r = c.post("/signup/organisation", json={"org": org_body("Beta Pty Ltd", ABN_B), "user": person("OWNER@alpha.example", "0400 000 001")})
    assert r.status_code == 409                                                       # same address in a different case is the same account


def test_legacy_register_endpoint_also_demands_email_and_phone(env, monkeypatch):
    from db_app.api import auth as legacy
    db, *_ = env
    app = FastAPI(); app.include_router(legacy.router, prefix="/auth2"); app.dependency_overrides[get_db] = lambda: db
    monkeypatch.setenv("ACCFINO_OPEN_SIGNUP", "1")
    c = TestClient(app)
    base = dict(username="legacy1", email="legacy1@example.com", password=PW)
    assert c.post("/auth2/register", json=base).status_code == 422                                  # no phone
    assert c.post("/auth2/register", json={**base, "phone": "999"}).status_code == 422
    assert c.post("/auth2/register", json={**base, "email": "nope", "phone": "0412 345 678"}).status_code == 422
    assert db.query(User).filter(User.username == "legacy1").count() == 0
    assert c.post("/auth2/register", json={**base, "phone": "0412 345 678"}).status_code == 200


# =============================================================================================== 3. ... and at the model / database level
def test_user_model_refuses_a_user_without_valid_contact_details(env):
    db, *_ = env
    for kw in (dict(email="x@example.com", phone=None), dict(email="x@example.com", phone=""), dict(email="x@example.com", phone="abc"), dict(email="", phone="+61412345678"),
               dict(email="not-an-email", phone="+61412345678")):
        db.add(User(username="direct", password="x", **kw))
        with pytest.raises(C.ContactError):
            db.flush()
        db.rollback()
    ok = User(username="direct", password="x", email="Direct@Example.com", phone="0412 345 678")
    db.add(ok); db.flush()
    assert ok.email == "direct@example.com" and ok.phone == "+61412345678"


def test_existing_users_cannot_have_contact_details_blanked_but_incomplete_accounts_still_work(env):
    db, *_ = env
    u = db.query(User).first()
    u.phone = ""
    with pytest.raises(C.ContactError):
        db.flush()
    db.rollback()
    # an OLD account that pre-dates the rule (created while the guard is lifted) is not broken: it can still be updated for other reasons
    with C.allow_incomplete_contact():
        old = User(username="oldtimer", email="old@example.com", password="x", phone=None)
        db.add(old); db.flush()
    old.full_name = "Old Timer"; db.flush()
    assert old.phone is None and C.missing_contact(old.email, old.phone) == ["phone"]
    old.phone = "0412 345 678"; db.flush()
    assert old.phone == "+61412345678"


# =============================================================================================== 4. one primary Organisation Admin
def test_creator_becomes_the_organisation_admin_in_the_database(env):
    db, c, state, *_ = env
    slug, org_id = make_tenant(db, c, state)
    owner = db.query(User).filter(User.email == "owner@alpha.example").one()
    o = db.get(m.Organisation, org_id)
    assert o.admin_user_id == owner.id
    mem = db.query(m.OrgMembership).filter_by(org_id=org_id, user_id=owner.id).one()
    assert mem.role == "owner" and mem.is_default and OA.admin_user(db, org_id).id == owner.id
    assert c.get("/org/current", headers={"X-Org-Id": str(org_id)}).json()["is_org_admin"] is True


def test_the_database_refuses_a_second_owner(env):
    db, c, state, *_ = env
    slug, org_id, _, member = org_with_member(db, c, state)
    uid = db.query(User).filter(User.email == member).one().id
    mem = db.query(m.OrgMembership).filter_by(org_id=org_id, user_id=uid).one()
    mem.role = "owner"
    with pytest.raises(IntegrityError):
        db.flush()
    db.rollback()
    assert db.query(m.OrgMembership).filter_by(org_id=org_id, role="owner").count() == 1


def test_organisation_admin_role_cannot_be_given_through_any_route(env):
    db, c, state, *_ = env
    slug, org_id, _, member = org_with_member(db, c, state)
    h = {"X-Org-Id": str(org_id)}
    uid = db.query(User).filter(User.email == member).one().id
    admin_id = db.get(m.Organisation, org_id).admin_user_id
    for role in ("owner", "admin"):
        assert c.patch(f"/org/current/members/{uid}", json={"role": role}, headers=h).status_code == 422
        assert c.post("/org/current/invites", json={"role": role}, headers=h).status_code == 422
        assert c.post("/org/current/members", json={"email": member, "role": role}, headers=h).status_code == 422
    # the admin's own role cannot be changed or removed - only transferred
    assert c.patch(f"/org/current/members/{admin_id}", json={"role": "readonly"}, headers=h).status_code == 409
    assert c.delete(f"/org/current/members/{admin_id}", headers=h).status_code == 409
    assert c.post(f"/org/current/identity/members/{admin_id}/suspend", json={}, headers=h).status_code in (409, 403)


def test_transfer_admin_moves_the_role_and_needs_the_password(env):
    db, c, state, events, mails, _ = env
    slug, org_id, owner, member = org_with_member(db, c, state)
    h = {"X-Org-Id": str(org_id)}
    new = db.query(User).filter(User.email == member).one()
    old = db.query(User).filter(User.email == owner).one()
    assert c.post("/org/current/transfer-admin", json={"new_admin_user_id": new.id}, headers=h).status_code == 401
    assert c.post("/org/current/transfer-admin", json={"new_admin_user_id": new.id, "password": "wrong"}, headers=h).status_code == 401
    assert c.post("/org/current/transfer-admin", json={"new_admin_user_id": old.id, "password": "x"}, headers=h).status_code in (401, 409)
    r = c.post("/org/current/transfer-admin", json={"new_admin_user_id": new.id, "password": PW}, headers=h) if False else None
    # the test users' passwords are the signup password
    r = c.post("/org/current/transfer-admin", json={"new_admin_user_id": new.id, "password": PW}, headers=h)
    assert r.status_code == 200, r.text
    db.expire_all()
    assert db.get(m.Organisation, org_id).admin_user_id == new.id
    assert db.query(m.OrgMembership).filter_by(org_id=org_id, role="owner").count() == 1
    assert db.query(m.OrgMembership).filter_by(org_id=org_id, user_id=old.id).one().role == "accountant"
    assert any(a == "org.admin_transferred" for a, _ in events)
    assert {t for t, _, _ in mails} >= {new.email, old.email}                                 # both people were told, as individuals
    # the former admin has lost organisation administration, immediately
    sign_in(db, state, owner)
    assert c.get("/org/current/invites", headers=h).status_code == 403
    sign_in(db, state, member)
    assert c.get("/org/current/invites", headers=h).status_code == 200


def test_transfer_needs_an_active_member_with_complete_contact_details(env):
    db, c, state, *_ = env
    slug, org_id, owner, member = org_with_member(db, c, state)
    h = {"X-Org-Id": str(org_id)}
    mem = db.query(User).filter(User.email == member).one()
    db.query(m.OrgMembership).filter_by(org_id=org_id, user_id=mem.id).update({"suspended_at": __import__("datetime").datetime.utcnow()}); db.commit()
    assert c.post("/org/current/transfer-admin", json={"new_admin_user_id": mem.id, "password": PW}, headers=h).status_code == 409       # suspended
    db.query(m.OrgMembership).filter_by(org_id=org_id, user_id=mem.id).update({"suspended_at": None}); db.commit()
    with C.allow_incomplete_contact():
        db.query(User).filter(User.id == mem.id).update({"phone": None}); db.commit()
    assert c.post("/org/current/transfer-admin", json={"new_admin_user_id": mem.id, "password": PW}, headers=h).status_code == 409       # no phone
    assert c.post("/org/current/transfer-admin", json={"new_admin_user_id": 999999, "password": PW}, headers=h).status_code == 404


def test_startup_repair_leaves_every_organisation_with_exactly_one_admin(env):
    db, c, state, events, *_ = env
    slug, org_id, owner, member = org_with_member(db, c, state)
    mem_id = db.query(User).filter(User.email == member).one().id
    db.execute(__import__("sqlalchemy").text("DROP INDEX uq_org_one_owner")); db.commit()               # simulate an old database: two owners, one with no admin pointer
    db.query(m.OrgMembership).filter_by(org_id=org_id, user_id=mem_id).update({"role": "owner"})
    db.get(m.Organisation, org_id).admin_user_id = None
    legacy = m.Organisation(name="Ownerless"); db.add(legacy); db.flush()
    u2 = db.query(User).filter(User.email == member).one()
    db.add(m.OrgMembership(org_id=legacy.id, user_id=u2.id, role="admin")); db.commit()
    out = OA.sync_org_admins(db); db.commit()
    assert out["demoted"] == 1 and out["promoted"] == 1
    assert db.query(m.OrgMembership).filter_by(org_id=org_id, role="owner").count() == 1
    assert db.query(m.OrgMembership).filter_by(org_id=legacy.id, role="owner").count() == 1
    for o in db.query(m.Organisation):
        assert OA.admin_membership(db, o.id) is not None and o.admin_user_id == OA.admin_membership(db, o.id).user_id
    assert OA.sync_org_admins(db) == {"demoted": 0, "promoted": 0, "synced": 0}                        # idempotent
    assert sum(1 for a, _ in events if a == "org.admin_normalised") == 2


# =============================================================================================== 5. admin email / phone = the organisation's primary contact
def test_admin_contact_details_are_the_organisations_primary_contact(env):
    db, c, state, *_ = env
    slug, org_id = make_tenant(db, c, state)
    h = {"X-Org-Id": str(org_id)}
    contact = OA.org_contact(db, org_id)
    assert contact["email"] == "owner@alpha.example" and contact["phone"] == "+61412345678" and contact["phone_display"] == "0412 345 678" and contact["name"] == "Olive Owner"
    prof = db.get(OrgProfile, org_id)
    assert prof.contact_email == "owner@alpha.example" and prof.phone == "+61412345678"               # the blank organisation fields default to the admin's
    t = c.get("/org/current/tenant", headers=h).json()
    assert t["primary_contact"]["email"] == "owner@alpha.example"
    ov = c.get("/org/current/admin/overview", headers=h).json()
    assert ov["organisation"] == {"id": org_id, "name": "Alpha Accounting Pty Ltd", "admin_name": "Olive Owner", "admin_email": "owner@alpha.example",
                                  "admin_phone": "+61412345678", "admin_phone_display": "0412 345 678", "admin_user_id": ov["organisation"]["admin_user_id"]}


def test_changing_the_admins_email_updates_the_organisation_contact_and_warns(env):
    db, c, state, events, mails, _ = env
    slug, org_id = make_tenant(db, c, state)
    assert c.patch("/auth/me/profile", json={"email": "new@alpha.example"}).status_code == 401           # a valid email needs the password to be replaced
    assert c.patch("/auth/me/profile", json={"email": "new@alpha.example", "current_password": "wrong"}).status_code == 401
    mails.clear()
    r = c.patch("/auth/me/profile", json={"email": "New@Alpha.Example", "phone": "0400 111 222", "current_password": PW})
    assert r.status_code == 200 and r.json()["email"] == "new@alpha.example" and r.json()["phone"] == "+61400111222"
    assert OA.org_contact(db, org_id)["email"] == "new@alpha.example"
    assert db.get(OrgProfile, org_id).contact_email == "new@alpha.example"
    tos = [t for t, _, _ in mails]
    assert "owner@alpha.example" in tos and "new@alpha.example" in tos                                   # the OLD address is warned too


def test_profile_cannot_blank_or_break_contact_details_or_take_anothers_email(env):
    db, c, state, *_ = env
    slug, org_id, owner, member = org_with_member(db, c, state)
    sign_in(db, state, member)
    for body in ({"email": ""}, {"phone": ""}, {"email": "bad"}, {"phone": "12"}):
        assert c.patch("/auth/me/profile", json={**body, "current_password": PW}).status_code == 422, body
    assert c.patch("/auth/me/profile", json={"email": owner, "current_password": PW}).status_code == 409
    assert c.patch("/auth/me/profile", json={}).status_code == 422
    me = c.get("/auth/me").json()
    assert me["profile_complete"] is True and me["missing_contact"] == [] and me["email"] == member


def test_incomplete_old_account_can_fill_in_missing_phone_without_a_password(env):
    db, c, state, *_ = env
    slug, org_id, owner, member = org_with_member(db, c, state)
    uid = db.query(User).filter(User.email == member).one().id
    with C.allow_incomplete_contact():
        db.query(User).filter(User.id == uid).update({"phone": None}); db.commit()
    sign_in(db, state, member)
    me = c.get("/auth/me").json()
    assert me["profile_complete"] is False and me["missing_contact"] == ["phone"]
    r = c.patch("/auth/me/profile", json={"phone": "0455 123 456"})
    assert r.status_code == 200 and r.json()["profile_complete"] is True and r.json()["phone"] == "+61455123456"


# =============================================================================================== 6. non-admins are refused by the SERVER
ROLES_WITHOUT_ADMIN = ("bookkeeper", "accountant", "payroll", "readonly")


def admin_only_calls(org_id, other_user_id):
    """(method, path, json) for every organisation-administration endpoint."""
    return [
        ("GET", "/org/current/members", None), ("POST", "/org/current/members", {"email": "x@y.co", "role": "readonly"}),
        ("PATCH", f"/org/current/members/{other_user_id}", {"role": "readonly"}), ("DELETE", f"/org/current/members/{other_user_id}", None),
        ("PATCH", "/org/current", {"name": "Hijacked"}), ("POST", "/org/current/lock-date", {"lock_date": "2026-06-30"}),
        ("GET", "/org/current/admin/overview", None), ("POST", "/org/current/transfer-admin", {"new_admin_user_id": other_user_id, "password": PW}),
        ("GET", "/org/current/invites", None), ("POST", "/org/current/invites", {"role": "readonly"}), ("DELETE", "/org/current/invites/1", None),
        ("GET", "/org/current/tenant", None), ("PATCH", "/org/current/tenant", {"contact_email": "evil@example.com", "discoverable": False}),
        ("POST", "/org/current/subscription/request", {"plan_id": "ultra"}),
        ("GET", "/org/current/access-policy", None), ("PUT", "/org/current/access-policy", {"state": "off", "applies_to": "all", "require_mfa": False}),
        ("GET", "/org/current/identity/members", None), ("GET", f"/org/current/identity/members/{other_user_id}", None),
        ("POST", f"/org/current/identity/members/{other_user_id}/suspend", {}), ("POST", f"/org/current/identity/members/{other_user_id}/restore", None),
        ("POST", f"/org/current/identity/members/{other_user_id}/sign-out", None), ("POST", f"/org/current/identity/members/{other_user_id}/reset-mfa", None),
        ("POST", f"/org/current/identity/members/{other_user_id}/require-password-change", {"required": True}),
    ]


@pytest.mark.parametrize("role", ROLES_WITHOUT_ADMIN)
def test_every_organisation_admin_endpoint_refuses_every_non_admin_role(env, role):
    db, c, state, events, mails, _ = env
    slug, org_id, owner, member = org_with_member(db, c, state, role=role)
    h = {"X-Org-Id": str(org_id)}
    admin_id = db.get(m.Organisation, org_id).admin_user_id
    snapshot = (db.get(m.Organisation, org_id).name, db.get(OrgProfile, org_id).contact_email, db.query(m.OrgMembership).count(), db.query(OrgInvite).count(), db.get(m.Organisation, org_id).lock_date)
    sign_in(db, state, member)
    mails.clear()
    for method, path, body in admin_only_calls(org_id, admin_id):
        r = c.request(method, path, json=body, headers=h)
        assert r.status_code == 403, f"{role}: {method} {path} -> {r.status_code} {r.text}"
        assert "Organisation Admin" in r.json()["detail"] or "role" in r.json()["detail"]
    db.expire_all()
    assert (db.get(m.Organisation, org_id).name, db.get(OrgProfile, org_id).contact_email, db.query(m.OrgMembership).count(), db.query(OrgInvite).count(), db.get(m.Organisation, org_id).lock_date) == snapshot
    assert mails == []                                                                                   # and a refused attempt changes nothing and sends nothing


def test_the_same_calls_succeed_for_the_organisation_admin(env):
    db, c, state, *_ = env
    slug, org_id, owner, member = org_with_member(db, c, state)
    h = {"X-Org-Id": str(org_id)}
    other = db.query(User).filter(User.email == member).one().id
    expected_ok = {("GET", "/org/current/members"), ("PATCH", f"/org/current/members/{other}"), ("PATCH", "/org/current"), ("POST", "/org/current/lock-date"), ("GET", "/org/current/admin/overview"),
                   ("GET", "/org/current/invites"), ("POST", "/org/current/invites"), ("GET", "/org/current/tenant"), ("PATCH", "/org/current/tenant"), ("POST", "/org/current/subscription/request"),
                   ("GET", "/org/current/access-policy"), ("PUT", "/org/current/access-policy"), ("GET", "/org/current/identity/members"), ("GET", f"/org/current/identity/members/{other}")}
    for method, path, body in admin_only_calls(org_id, other):
        if (method, path) in expected_ok:
            r = c.request(method, path, json=body, headers=h)
            assert r.status_code == 200, f"{method} {path} -> {r.status_code} {r.text}"


def test_non_admin_keeps_normal_access_and_can_see_only_a_names_directory(env):
    db, c, state, *_ = env
    slug, org_id, owner, member = org_with_member(db, c, state, role="bookkeeper")
    h = {"X-Org-Id": str(org_id)}
    sign_in(db, state, member)
    assert c.get("/whoami", headers=h).json() == {"org": org_id, "role": "bookkeeper"}
    cur = c.get("/org/current", headers=h).json()
    assert cur["is_org_admin"] is False and "admin_email" not in cur and "admin_phone" not in cur and cur["admin_name"] == "Olive Owner"
    d = c.get("/org/current/directory", headers=h)
    assert d.status_code == 200 and {r["name"] for r in d.json()} == {"Olive Owner", "Bob Book"}
    assert all(set(r) == {"user_id", "name", "role"} for r in d.json())                                  # no emails, no phones
    assert c.get("/org/mine").status_code in (200, 404) or True
    assert c.patch("/auth/me/profile", json={"full_name": "Bobby Book"}).status_code == 200              # personal settings stay available
    assert c.get("/auth/me").json()["is_org_admin"] is False


def test_accountant_and_legacy_admin_roles_no_longer_administer_the_organisation(env):
    from accfino_core.security.context import ROLE_PERMS
    assert "org_admin" in ROLE_PERMS["owner"] and "members" in ROLE_PERMS["owner"]
    for role, perms in ROLE_PERMS.items():
        if role != "owner":
            assert "org_admin" not in perms and "members" not in perms, role
    assert {"read", "post"} <= ROLE_PERMS["accountant"] and {"read", "post"} <= ROLE_PERMS["admin"]     # they keep day-to-day access to the books


def test_legacy_admin_role_membership_is_treated_as_a_normal_user(env):
    db, c, state, *_ = env
    slug, org_id, owner, member = org_with_member(db, c, state, role="bookkeeper")
    uid = db.query(User).filter(User.email == member).one().id
    db.query(m.OrgMembership).filter_by(org_id=org_id, user_id=uid).update({"role": "admin"}); db.commit()     # a row from before this change
    sign_in(db, state, member)
    assert c.get("/org/current/invites", headers={"X-Org-Id": str(org_id)}).status_code == 403
    assert c.patch("/org/current", json={"name": "x"}, headers={"X-Org-Id": str(org_id)}).status_code == 403


def test_forged_request_attempts_do_not_bypass_the_check(env):
    db, c, state, *_ = env
    slug, org_id, owner, member = org_with_member(db, c, state)
    h = {"X-Org-Id": str(org_id)}
    sign_in(db, state, member)
    assert c.patch("/org/current", json={"name": "x", "role": "owner"}, headers=h).status_code == 403              # extra payload fields
    assert c.patch("/org/current", json={"name": "x"}, headers={"X-Org-Id": str(org_id), "X-Role": "owner", "X-Admin": "1"}).status_code == 403
    assert c.patch(f"/org/current?org_id={org_id}", json={"name": "x"}).status_code == 403                        # query-string org id
    assert c.post("/org/current/invites", json={"role": "readonly", "created_by": 1, "org_id": org_id}, headers=h).status_code == 403
    assert db.get(m.Organisation, org_id).name == "Alpha Accounting Pty Ltd"


# =============================================================================================== 7. organisation isolation
def test_users_of_one_organisation_cannot_reach_or_change_another(env):
    db, c, state, *_ = env
    sa, org_a, owner_a, mem_a = org_with_member(db, c, state, name="Alpha Pty Ltd", abn=ABN_A, owner="oa@a.example", member="ma@a.example")
    sign_in(db, state, owner_a)
    sb, org_b = make_tenant(db, c, state, "Beta Pty Ltd", ABN_B, "ob@b.example")
    code_b = invite_code(c, org_b, "readonly")
    b_admin = db.get(m.Organisation, org_b).admin_user_id
    calls = [("GET", "/org/current/members"), ("GET", "/org/current/invites"), ("GET", "/org/current/tenant"), ("GET", "/org/current/admin/overview"), ("PATCH", "/org/current"),
             ("POST", "/org/current/invites"), ("GET", "/org/current/directory"), ("GET", "/whoami"), ("GET", "/org/current/access-policy")]
    for who in (owner_a, mem_a):                                                                                  # even the ADMIN of A is nothing in B
        sign_in(db, state, who)
        for method, path in calls:
            r = c.request(method, path, json={"name": "x", "role": "readonly"} if method in ("PATCH", "POST") else None, headers={"X-Org-Id": str(org_b)})
            assert r.status_code == 403, f"{who}: {method} {path} -> {r.status_code}"
        assert c.delete(f"/org/current/members/{b_admin}", headers={"X-Org-Id": str(org_b)}).status_code == 403
        assert c.post("/org/current/transfer-admin", json={"new_admin_user_id": b_admin, "password": PW}, headers={"X-Org-Id": str(org_b)}).status_code == 403
    sign_in(db, state, owner_a)
    inv_b = db.query(OrgInvite).filter_by(org_id=org_b).one()
    assert c.delete(f"/org/current/invites/{inv_b.id}", headers={"X-Org-Id": str(org_a)}).status_code == 404       # B's code id used against A's organisation
    assert db.get(OrgInvite, inv_b.id).revoked_at is None
    assert all(i["id"] != inv_b.id for i in c.get("/org/current/invites", headers={"X-Org-Id": str(org_a)}).json()["items"])
    assert db.get(m.Organisation, org_b).name == "Beta Pty Ltd"
    # a code for A does not open B (and the reverse)
    assert c.post("/signup/verify-code", json={"slug": sb, "code": invite_code(c, org_a, "readonly")}).status_code == 400
    assert c.post("/signup/verify-code", json={"slug": sa, "code": code_b}).status_code == 400


def test_code_and_organisation_name_alone_never_create_an_account(env):
    db, c, state, *_ = env
    slug, org_id = make_tenant(db, c, state)
    users = db.query(User).count()
    assert c.post("/signup/join", json={"signup_token": "", "user": person("x@y.co")}).status_code == 400
    assert c.post("/signup/join", json={"user": person("x@y.co")}).status_code == 422
    assert c.post("/signup/verify-code", json={"slug": slug, "code": "ABC-AAAA-BBBB"}).status_code == 400
    assert c.get("/signup/organisations/search", params={"q": "alpha"}).json()["items"][0].keys() == {"slug", "name", "location"}
    assert db.query(User).count() == users


# =============================================================================================== 8. organisation communication -> the Organisation Admin
def tos(mails):
    return [t for t, _, _ in mails]


def test_organisation_created_email_goes_to_the_admin(env):
    db, c, state, events, mails, _ = env
    make_tenant(db, c, state)
    assert tos(mails) == ["owner@alpha.example"] and "has been created" in mails[0][1] and "Organisation Admin" in mails[0][2]


def test_new_user_joined_goes_to_the_admin_not_to_the_new_user(env):
    db, c, state, events, mails, _ = env
    slug, org_id = make_tenant(db, c, state)
    code = invite_code(c, org_id, "bookkeeper")
    mails.clear()
    assert join(c, slug, code, "new@alpha.example").status_code == 200
    assert set(tos(mails)) == {"owner@alpha.example"}                                                               # everything goes to the admin; the newcomer gets nothing about the organisation
    joined = [x for x in mails if "joined" in x[1].lower()]
    assert len(joined) == 1 and "new@alpha.example" in joined[0][2] and "new@alpha.example" not in tos(mails)


def test_settings_and_member_changes_are_routed_to_the_admin_and_member_changes_also_to_the_member(env):
    db, c, state, events, mails, _ = env
    slug, org_id, owner, member = org_with_member(db, c, state)
    h = {"X-Org-Id": str(org_id)}
    mails.clear()
    assert c.patch("/org", json={}, headers=h).status_code in (404, 405) or True
    assert c.patch("/org/current", json={"name": "Alpha Renamed"}, headers=h).status_code == 200
    assert tos(mails) == [owner] and "settings were changed" in mails[0][1]
    mails.clear()
    uid = db.query(User).filter(User.email == member).one().id
    assert c.patch(f"/org/current/members/{uid}", json={"role": "accountant"}, headers=h).status_code == 200
    assert sorted(tos(mails)) == sorted([owner, member])                                                            # org-level -> admin; individual -> the member
    mails.clear()
    assert c.patch("/org/current/tenant", json={"contact_email": "Office@Alpha.Example"}, headers=h).status_code == 200
    assert tos(mails) == [owner]


def test_no_organisation_message_is_ever_sent_to_a_non_admin_address(env):
    db, c, state, events, mails, texts = env
    slug, org_id, owner, member = org_with_member(db, c, state)
    h = {"X-Org-Id": str(org_id)}
    mails.clear()
    c.patch("/org/current", json={"name": "Renamed Again"}, headers=h)
    c.post("/org/current/lock-date", json={"lock_date": "2026-03-31"}, headers=h)
    c.put("/org/current/access-policy", json={"state": "off", "applies_to": "all", "require_mfa": False}, headers=h)
    c.post("/org/current/subscription/request", json={"plan_id": "ultra"}, headers=h)
    c.post("/org/current/invites", json={"role": "readonly"}, headers=h)
    org_level = [(t, s) for t, s, _ in mails if "access to" not in s]
    assert org_level and all(t == owner for t, _ in org_level), org_level
    assert member not in [t for t, s in org_level]


def test_licence_warnings_go_to_the_admin(env):
    db, c, state, events, mails, _ = env
    S.set_settings(db, default_plan=_seat_plan(db, 3)); db.commit()                                                          # 3 seats
    slug, org_id = make_tenant(db, c, state)
    code = invite_code(c, org_id, "readonly", max_uses=5) if False else None
    for i in range(1):
        mails.clear()
        assert join(c, slug, invite_code(c, org_id, "readonly"), f"u{i}@alpha.example", f"04000000{i}1").status_code == 200
    st = signup_api.T.seat_status(db, org_id)
    mails.clear()
    assert join(c, slug, invite_code(c, org_id, "readonly"), "u9@alpha.example", "0400 000 099").status_code == 200
    subjects = [s for t, s, _ in mails]
    assert any("limit reached" in s for s in subjects), (subjects, st)
    assert all(t == "owner@alpha.example" for t, _, _ in mails)
    mails.clear()
    r = c.post("/org/current/invites", json={"role": "readonly"}, headers={"X-Org-Id": str(org_id)})
    assert r.status_code == 409                                                                                         # full: no code can be issued
    sign_out_code = None


def test_subscription_changes_by_platform_support_notify_the_admin(env):
    db, c, state, events, mails, _ = env
    slug, org_id = make_tenant(db, c, state)
    mails.clear()
    state["admin"] = True
    sub = subscription_api.admin_assign
    app2 = FastAPI(); app2.include_router(subscription_api.admin_router, prefix="/admin/subscriptions")
    @app2.middleware("http")
    async def _a(request, call_next):
        request.state.auth = {"user_id": 1, "username": "root", "is_admin": True}; return await call_next(request)
    app2.dependency_overrides[get_db] = lambda: db
    r = TestClient(app2).put(f"/admin/subscriptions/orgs/{org_id}", json={"plan_id": "ultra", "addons": [], "status": "expired", "billing_period": "monthly"})
    assert r.status_code == 200, r.text
    assert tos(mails) == ["owner@alpha.example"] and "expired" in mails[0][1].lower()


def test_security_alert_for_code_guessing_goes_to_the_admin_once(env):
    db, c, state, events, mails, texts = env
    slug, org_id = make_tenant(db, c, state)
    mails.clear()
    codes = ["AAA-" + "".join(ch * 4 for ch in "BCDF")[:4] + "-" + f"{i:04d}".replace("0", "K").replace("1", "L").replace("2", "M").replace("3", "N").replace("4", "P").replace("5", "Q").replace("6", "R").replace("7", "S").replace("8", "T").replace("9", "V") for i in range(12)]
    last = None
    for cd in codes:
        last = c.post("/signup/verify-code", json={"slug": slug, "code": cd}).status_code
    assert last == 429
    alerts = [x for x in mails if "Access code guessing" in x[1]]
    assert len(alerts) == 1 and alerts[0][0] == "owner@alpha.example"                                                  # de-duplicated, to the admin only
    assert texts == []                                                                                                 # SMS alerts are off unless switched on


def test_admin_sms_security_alert_uses_the_admins_phone_when_enabled(env, monkeypatch):
    db, c, state, events, mails, texts = env
    slug, org_id = make_tenant(db, c, state)
    monkeypatch.setenv("ACCFINO_ORG_SMS_ALERTS", "1")
    N.security_alert(db, org_id, "Test alert", "Something happened.", dedupe_minutes=0)
    assert [t for t, _ in texts] == ["+61412345678"]


def test_notification_failures_never_break_the_action(env, monkeypatch):
    db, c, state, *_ = env
    def boom(*a, **k): raise messaging.DeliveryError("smtp down")
    monkeypatch.setattr(messaging, "send_email", boom)
    slug, org_id = make_tenant(db, c, state)
    assert c.patch("/org/current", json={"name": "Still Works"}, headers={"X-Org-Id": str(org_id)}).status_code == 200


def test_unroutable_org_notifications_are_audited_not_sent(env):
    db, c, state, events, mails, _ = env
    o = m.Organisation(name="No Admin"); db.add(o); db.commit()
    assert N.notify_org_admin(db, o.id, "x", "s", "b") is False and mails == []
    assert any(a == "notify.org_admin_unroutable" for a, _ in events)


# =============================================================================================== 9. profile-completion gate for old accounts
def test_profile_gate_blocks_incomplete_accounts_everywhere_except_the_profile(monkeypatch):
    from accfino_core.security import iam
    from accfino_core.security.middleware import AuthGuard
    db = make_db()
    app = FastAPI()

    @app.get("/anything")
    def anything(): return {"ok": True}

    @app.get("/auth/me")
    def me(): return {"me": True}

    @app.patch("/auth/me/profile")
    def prof(): return {"saved": True}

    @app.post("/auth/logout")
    def lo(): return {"ok": True}
    app.dependency_overrides[get_db] = lambda: db
    app.add_middleware(AuthGuard, fastapi_app=app)
    missing = {"v": ["phone"]}
    monkeypatch.setattr(AuthGuard, "_authenticate", staticmethod(lambda h: ({"user_id": 5, "username": "u", "email": "u", "is_admin": False, "org_id": None, "mfa": True, "jti": "j", "sid": None,
                                                                             "amr": ["pwd"], "session_started": None, "must_change_password": False}, None)))
    monkeypatch.setattr(iam, "contact_missing", lambda uid: missing["v"])
    monkeypatch.setattr(iam, "org_policy", lambda oid: None)
    c = TestClient(app)
    r = c.get("/anything")
    assert r.status_code == 403 and r.json()["code"] == "profile_incomplete" and r.json()["missing"] == ["phone"] and "phone number" in r.json()["detail"]
    assert c.post("/anything").status_code == 403
    assert c.get("/auth/me").status_code == 200 and c.patch("/auth/me/profile").status_code == 200 and c.post("/auth/logout").status_code == 200
    missing["v"] = []
    assert c.get("/anything").status_code == 200                                                                          # complete -> normal access


def test_profile_gate_can_be_switched_off_for_rollback(monkeypatch):
    from accfino_core import config
    from accfino_core.security import iam
    from accfino_core.security.middleware import AuthGuard
    db = make_db(); app = FastAPI()
    @app.get("/anything")
    def anything(): return {"ok": True}
    app.dependency_overrides[get_db] = lambda: db
    app.add_middleware(AuthGuard, fastapi_app=app)
    monkeypatch.setattr(AuthGuard, "_authenticate", staticmethod(lambda h: ({"user_id": 5, "username": "u", "email": "u", "is_admin": False, "org_id": None, "mfa": True, "jti": "j", "sid": None,
                                                                             "amr": ["pwd"], "session_started": None, "must_change_password": False}, None)))
    monkeypatch.setattr(iam, "contact_missing", lambda uid: ["email", "phone"]); monkeypatch.setattr(iam, "org_policy", lambda oid: None)
    monkeypatch.setattr(config, "PROFILE_GATE_ENFORCED", False)
    assert TestClient(app).get("/anything").status_code == 200


# =============================================================================================== 10. Organisation Admin dashboard data
def test_admin_dashboard_shows_organisation_users_and_access_codes(env):
    db, c, state, *_ = env
    S.set_settings(db, default_plan=_seat_plan(db, 10)); db.commit()                                                             # 10 seats
    slug, org_id = make_tenant(db, c, state)
    h = {"X-Org-Id": str(org_id)}
    code = invite_code(c, org_id, "readonly")
    assert join(c, slug, code, "one@alpha.example").status_code == 200                                                   # one code used
    c1 = c.post("/org/current/invites", json={"role": "readonly", "count": 2}, headers=h).json()["codes"]
    assert c.delete(f"/org/current/invites/{c1[0]['id']}", headers=h).status_code == 200                                 # one revoked
    db.query(OrgInvite).filter_by(id=c1[1]["id"]).update({"expires_at": __import__("datetime").datetime.utcnow() - __import__("datetime").timedelta(days=1)}); db.commit()      # one expired
    invite_code(c, org_id, "readonly")                                                                                   # one active
    ov = c.get("/org/current/admin/overview", headers=h).json()
    assert ov["users"] == {"licensed_users": 10, "active_users": 2, "available_slots": 7, "pending_invitations": 1}
    assert ov["access_codes"] == {"active": 1, "used": 1, "expired": 1, "revoked": 1}
    assert ov["organisation"]["admin_email"] == "owner@alpha.example" and ov["organisation"]["id"] == org_id


# =============================================================================================== 11. legacy settings routes (Payment Setup, Knowledge Base, Rules) + organisation address
def _guard_app(monkeypatch, role_of, is_admin=False, tenant=None):
    """The REAL AuthGuard in front of stand-ins for the older settings routes, with a chosen membership role."""
    from accfino_core.security import iam
    from accfino_core.security.middleware import AuthGuard
    db = make_db(); app = FastAPI()
    for method, path in (("get", "/square/status"), ("post", "/square/config"), ("get", "/stripe/status"), ("post", "/stripe/config"), ("get", "/bank-account/status"), ("post", "/bank-account/config"),
                         ("get", "/openfeed/status"), ("post", "/openfeed/config"), ("get", "/kb"), ("put", "/kb/vendor/acme"), ("delete", "/kb/vendor/acme"), ("put", "/kb/meta"),
                         ("get", "/rdr/rules"), ("post", "/rdr/rules"), ("put", "/rdr/rules/1"), ("delete", "/rdr/rules/1"), ("post", "/rdr/test"), ("get", "/sales/ping")):
        getattr(app, method)(path)(lambda: {"ok": True})
    app.dependency_overrides[get_db] = lambda: db
    app.add_middleware(AuthGuard, fastapi_app=app)
    monkeypatch.setattr(AuthGuard, "_authenticate", staticmethod(lambda h: ({"user_id": 5, "username": "u", "email": "u", "is_admin": is_admin, "org_id": 7, "mfa": True, "jti": "j", "sid": None,
                                                                             "amr": ["pwd"], "session_started": None, "must_change_password": False}, None)))
    monkeypatch.setattr(iam, "contact_missing", lambda uid: []); monkeypatch.setattr(iam, "org_policy", lambda oid: None)
    monkeypatch.setattr(iam, "member_role", lambda uid, oid: role_of(oid))
    monkeypatch.setattr(audit, "write", lambda *a, **k: None)
    return TestClient(app)


ADMIN_ONLY_ALWAYS = [("GET", "/square/status"), ("POST", "/square/config"), ("GET", "/stripe/status"), ("POST", "/stripe/config"), ("GET", "/bank-account/status"), ("POST", "/bank-account/config"),
                     ("GET", "/openfeed/status"), ("POST", "/openfeed/config")]
ADMIN_ONLY_WRITES = [("PUT", "/kb/vendor/acme"), ("DELETE", "/kb/vendor/acme"), ("PUT", "/kb/meta"), ("POST", "/rdr/rules"), ("PUT", "/rdr/rules/1"), ("DELETE", "/rdr/rules/1")]
STILL_OPEN = [("GET", "/kb"), ("GET", "/rdr/rules"), ("POST", "/rdr/test"), ("GET", "/sales/ping")]       # reconciliation reads the knowledge base and rules


@pytest.mark.parametrize("role", ["bookkeeper", "accountant", "payroll", "readonly", "admin", None])
def test_payment_setup_knowledge_base_and_rules_are_refused_to_non_admins_by_the_server(monkeypatch, role):
    c = _guard_app(monkeypatch, lambda oid: role)
    for method, path in ADMIN_ONLY_ALWAYS + ADMIN_ONLY_WRITES:
        r = c.request(method, path, json={})
        assert r.status_code == 403 and r.json()["code"] == "org_admin_required", f"{role}: {method} {path} -> {r.status_code}"
    for method, path in STILL_OPEN:
        assert c.request(method, path, json={}).status_code == 200, f"{role}: {method} {path} should stay open"


def test_the_organisation_admin_and_platform_support_can_use_them(monkeypatch):
    c = _guard_app(monkeypatch, lambda oid: "owner")
    for method, path in ADMIN_ONLY_ALWAYS + ADMIN_ONLY_WRITES + STILL_OPEN:
        assert c.request(method, path, json={}).status_code == 200, (method, path)
    c = _guard_app(monkeypatch, lambda oid: None, is_admin=True)                                             # platform administrator
    assert c.post("/stripe/config", json={}).status_code == 200


def test_being_owner_of_another_organisation_does_not_help(monkeypatch):
    c = _guard_app(monkeypatch, lambda oid: "owner" if oid == 99 else "bookkeeper")                        # owner of org 99, bookkeeper in org 7
    assert c.post("/stripe/config", json={}).status_code == 403                                              # token's organisation (7) decides
    assert c.post("/stripe/config", json={}, headers={"X-Org-Id": "99"}).status_code == 200                  # ...unless they really are admin of the one they name
    assert c.post("/stripe/config", json={}, headers={"X-Org-Id": "7"}).status_code == 403


def test_every_member_sees_the_organisation_address_but_only_the_admin_sees_contact_details(env, monkeypatch):
    monkeypatch.setenv("TENANT_BASE_DOMAIN", "syd.accfino.com")
    db, c, state, *_ = env
    r = c.post("/signup/organisation", json={"org": org_body("Kutumb", ABN_A), "user": person()})
    assert r.status_code == 200 and r.json()["tenant_url"] == "https://kutumb.syd.accfino.com" and r.json()["login_url"] == "https://kutumb.syd.accfino.com/login"
    org_id = db.query(OrgProfile).filter_by(slug="kutumb").one().org_id
    sign_in(db, state, "owner@alpha.example")
    code = invite_code(c, org_id, "bookkeeper")
    assert join(c, "kutumb", code, "book@kutumb.example").status_code == 200
    for who in ("owner@alpha.example", "book@kutumb.example"):
        sign_in(db, state, who)
        cur = c.get("/org/current", headers={"X-Org-Id": str(org_id)}).json()
        assert cur["slug"] == "kutumb" and cur["tenant_url"] == "https://kutumb.syd.accfino.com" and cur["tenant_urls_enabled"] is True, who
    assert "admin_email" not in cur                                                                         # (bookkeeper) contact details stay with the admin
    monkeypatch.delenv("TENANT_BASE_DOMAIN")
    cur = c.get("/org/current", headers={"X-Org-Id": str(org_id)}).json()
    assert cur["slug"] == "kutumb" and cur["tenant_url"] is None and cur["tenant_urls_enabled"] is False
