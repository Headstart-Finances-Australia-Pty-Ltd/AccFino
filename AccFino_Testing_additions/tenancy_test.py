"""Organisation-first signup, access codes, licence seats, tenant URLs and tenant isolation.
Run from backend/:  PYTHONPATH=. python -m pytest ../AccFino_Testing_additions/tenancy_test.py -q"""
import os, sys
from datetime import datetime, timedelta
import pytest
sys.path.insert(0, os.path.dirname(__file__))
from csv_import_harness import make_db, make_org, SD
from fastapi import FastAPI
from fastapi.testclient import TestClient
from accfino_core import models as m
from accfino_core.api import signup_api
from accfino_core.security import audit
from accfino_core.security.context import current_org
from accfino_core.subscription import service as S
from accfino_core.tenancy import service as T
from accfino_core.tenancy.models import OrgInvite, OrgProfile
from db_app.database import get_db

BASE = "acc.test"
VALID_ABN = "51 824 753 556"
VALID_ACN = "004 085 616"
PW = "Str0ng!Passw0rd#2026"


@pytest.fixture(autouse=True)
def tenant_env(monkeypatch):
    monkeypatch.setenv("TENANT_BASE_DOMAIN", BASE)
    monkeypatch.delenv("ACCFINO_OPEN_SIGNUP", raising=False)
    monkeypatch.setenv("CONTACT_VERIFICATION", "off")                      # (verification has its own tests: contact_verify_test.py)


@pytest.fixture()
def env(monkeypatch):
    from db_app.models import Role
    db = make_db(); org, ctx = make_org(db)                       # the platform's own seeded organisation + owner user
    if not db.query(Role).filter_by(name="user").first():
        db.add(Role(name="user")); db.commit()
    events = []
    monkeypatch.setattr(audit, "write", lambda action, **kw: events.append((action, kw)))
    S.ensure_catalogue(db)
    from decimal import Decimal                                                        # these tests are about seat behaviour, not today's price list: a plan with exactly 3 users
    db.add(S.Plan(id="seats3", name="Three seats", price_monthly=Decimal("1"), price_yearly=Decimal("10"), seat_limit=3, modules='["*"]', sort_order=90))
    db.add(S.Plan(id="seats-unlimited", name="No limit", price_monthly=Decimal("1"), price_yearly=Decimal("10"), seat_limit=None, modules='["*"]', sort_order=91))
    db.commit(); S.set_settings(db, default_plan="seats3"); db.commit()
    app = FastAPI()
    state = {"uid": ctx.user_id, "admin": False}
    for r, p in ((signup_api.tenant_router, "/tenant"), (signup_api.signup_router, "/signup"), (signup_api.invites_router, "/org/current/invites"), (signup_api.admin_tenant_router, "/org/current/tenant")):
        app.include_router(r, prefix=p)

    @app.get("/whoami")
    def whoami(c=__import__("fastapi").Depends(current_org)):
        return {"org": c.org.id, "role": c.role}

    @app.middleware("http")
    async def _auth(request, call_next):
        request.state.auth = {"user_id": state["uid"], "username": "u", "is_admin": state["admin"]}
        return await call_next(request)
    app.dependency_overrides[get_db] = lambda: db
    yield db, TestClient(app), state, events
    db.close()


def org_body(name="Alpha Accounting Pty Ltd", abn=VALID_ABN, **kw):
    d = dict(name=name, abn=abn, address="1 George St", city="Sydney", state="NSW", postcode="2000", contact_email="office@alpha.example", industry="Accounting")
    d.update(kw)
    return d


PHONE = "0412 345 678"


def user_body(email="owner@alpha.example", pw=PW, phone=PHONE):
    return dict(first_name="Olive", last_name="Owner", email=email, phone=phone, password=pw)


def signup_org(c, host=None, **kw):
    return c.post("/signup/organisation", json={"org": org_body(**kw), "user": user_body(kw.get("email", "owner@alpha.example") if "email" in kw else "owner@alpha.example")})


def sign_in_as(db, state, email):
    from db_app.models import User
    state["uid"] = db.query(User).filter(User.email == email).one().id


def make_codes(c, org_id, **body):
    r = c.post("/org/current/invites", json=body or {"role": "bookkeeper", "count": 1}, headers={"X-Org-Id": str(org_id)})
    assert r.status_code == 200, r.text
    return r.json()


def new_tenant(db, c, state, name="Alpha Accounting Pty Ltd", abn=VALID_ABN, email="owner@alpha.example"):
    r = c.post("/signup/organisation", json={"org": org_body(name=name, abn=abn), "user": user_body(email)})
    assert r.status_code == 200, r.text
    slug = r.json()["slug"]
    org_id = db.query(OrgProfile).filter_by(slug=slug).one().org_id
    sign_in_as(db, state, email)
    return slug, org_id, r.json()


def join(c, slug, code, email, pw=PW):
    v = c.post("/signup/verify-code", json={"slug": slug, "code": code})
    if v.status_code != 200:
        return v
    return c.post("/signup/join", json={"signup_token": v.json()["signup_token"], "user": user_body(email, pw)})


# ---------------------------------------------------------------------------------------------- pure rules
def test_tenant_host_parsing(monkeypatch):
    f = T.tenant_from_host
    assert f("abc.acc.test") == "abc" and f("ABC.acc.test:8443") == "abc" and f("abc-def.acc.test") == "abc-def"
    for bad in ("acc.test", "www.acc.test", "api.acc.test", "a.b.acc.test", "evil.com", "abc.acc.test.evil.com", "abc.evilacc.test", "", None, "-x.acc.test"):
        assert f(bad) is None, bad
    monkeypatch.delenv("TENANT_BASE_DOMAIN")
    assert f("abc.acc.test") is None and T.tenant_url("abc") is None            # tenant URLs off -> single-host behaviour, nothing changes
    monkeypatch.setenv("TENANT_BASE_DOMAIN", BASE)
    assert T.tenant_url("abc") == "https://abc.acc.test"


def test_slug_rules(env):
    db, *_ = env
    assert T.slugify("Acme Pty Ltd") == "acme" and T.slugify("  A&B  Plumbing ") == "a-b-plumbing" and T.valid_slug("abc-accounting")
    for bad in ("ab", "-abc", "abc-", "a--b", "Abc", "www", "admin", "a" * 41, "a b"):
        assert not T.valid_slug(bad), bad
    o = m.Organisation(name="Acme"); db.add(o); db.flush(); db.add(OrgProfile(org_id=o.id, slug="acme")); db.flush()
    assert T.unique_slug(db, "Acme Pty Ltd") == "acme-2"


def test_tenant_decision_matrix():
    d = lambda **k: T.tenant_decision(**{**dict(org_id_of_tenant=5, role_in_tenant="owner", is_platform_admin=False, org_header=None), **k})
    assert d() is None and d(org_header="5") is None and d(org_header="") is None
    assert d(org_id_of_tenant=None)[0] == 404
    assert d(role_in_tenant=None)[:2] == (403, "tenant_forbidden")
    assert d(org_header="6")[:2] == (403, "tenant_mismatch")
    assert d(role_in_tenant=None, is_platform_admin=True) is None                  # platform support may enter any tenant
    assert d(role_in_tenant=None, is_platform_admin=True, org_header="6")[1] == "tenant_mismatch"


# ---------------------------------------------------------------------------------------------- creating an organisation
def test_new_organisation_signup_makes_an_owner_and_a_tenant_url(env):
    db, c, state, events = env
    r = signup_org(c)
    assert r.status_code == 200, r.text
    j = r.json()
    assert j["slug"] == "alpha-accounting" and j["tenant_url"] == "https://alpha-accounting.acc.test" and j["login_url"].endswith("/login")
    p = db.query(OrgProfile).filter_by(slug="alpha-accounting").one()
    from db_app.models import User
    u = db.query(User).filter_by(email="owner@alpha.example").one()
    mem = db.query(m.OrgMembership).filter_by(org_id=p.org_id).all()
    assert [(x.user_id, x.role) for x in mem] == [(u.id, "owner")]                  # the creator is the owner, and the only member
    assert db.query(m.OrgMembership).filter_by(user_id=u.id).count() == 1           # ...and has no extra "personal" organisation
    assert db.query(m.LedgerAccount).filter_by(org_id=p.org_id).count() > 50       # chart of accounts seeded
    assert S.entitlements(db, p.org_id)["seats"] == 3                               # the default plan's licensed users apply
    assert any(e[0] == "signup.organisation_created" for e in events)


def test_new_organisation_validation(env):
    db, c, state, events = env
    n = iter(range(100))
    post = lambda org=None, user=None: c.post("/signup/organisation", json={"org": org or org_body(), "user": user or user_body(f"owner{next(n)}@alpha.example")})
    assert post(org_body(abn=None, acn=None)).status_code == 422                     # an identifier is required
    assert post(org_body(abn="11 111 111 111")).status_code == 422                   # ATO checksum
    assert post(org_body(abn=None, acn="123 456 789")).status_code == 422            # ASIC checksum
    assert post(org_body(abn=None, acn=VALID_ACN)).status_code == 200                # an ACN alone is enough
    assert post(org_body(name="Other Co", abn=None, other_id="NZ-998877")).status_code == 200      # or another identifier
    assert post(org_body(name="X", abn=VALID_ABN)).status_code == 422                # name too short
    assert post(org_body(address="")).status_code == 422
    assert post(org_body(contact_email="nope")).status_code == 422
    assert post(org_body(name="Third Co", abn="53 004 085 616"), user_body("a@b.example", "weak")).status_code == 400
    assert post(org_body(name="Third Co", abn="53 004 085 616")).status_code == 200
    assert db.query(m.Organisation).filter_by(name="Third Co").count() == 1


def test_duplicate_abn_email_and_slug_are_refused(env):
    db, c, state, events = env
    assert signup_org(c).status_code == 200
    again = c.post("/signup/organisation", json={"org": org_body(name="Copycat"), "user": user_body("someone@x.example")})
    assert again.status_code == 409 and "already registered" in again.json()["detail"] and "access code" in again.json()["detail"]
    r = c.post("/signup/organisation", json={"org": org_body(name="Beta Co", abn="53 004 085 616"), "user": user_body("owner@alpha.example")})
    assert r.status_code == 409 and "email" in r.json()["detail"]
    r = c.post("/signup/organisation", json={"org": org_body(name="Beta Co", abn="53 004 085 616", slug="alpha-accounting"), "user": user_body("b@x.example")})
    assert r.status_code == 409 and "web address" in r.json()["detail"]
    for slug in ("www", "ab", "Bad_Slug"):
        r = c.post("/signup/organisation", json={"org": org_body(name="Beta Co", abn="53 004 085 616", slug=slug), "user": user_body("b@x.example")})
        assert r.status_code == 422, slug
    assert db.query(m.Organisation).filter_by(name="Beta Co").count() == 0           # rejected requests leave nothing behind


def test_validate_endpoint_saves_nothing(env):
    db, c, *_ = env
    n = db.query(m.Organisation).count()
    r = c.post("/signup/organisation/validate", json=org_body())
    assert r.status_code == 200 and r.json()["slug"] == "alpha-accounting" and db.query(m.Organisation).count() == n


def test_organisation_creation_is_rate_limited(env):
    db, c, *_ = env
    abns = ["51 824 753 556", "53 004 085 616", "12 004 044 937", "83 914 571 673", "33 051 775 556"]
    codes = []
    for i, a in enumerate(abns):
        codes.append(c.post("/signup/organisation", json={"org": org_body(name=f"Org {i} Pty Ltd", abn=a), "user": user_body(f"o{i}@x.example")}).status_code)
    assert codes.count(200) >= 1 and set(codes) <= {200, 422}
    ok = sum(1 for x in codes if x == 200)
    for _ in range(5 - ok):
        T.record_attempt(db, "testclient", "create", success=True)
    db.commit()
    r = c.post("/signup/organisation", json={"org": org_body(name="One More Pty Ltd", abn="51 824 753 556"), "user": user_body("late@x.example")})
    assert r.status_code == 429 and r.headers.get("Retry-After")


# ---------------------------------------------------------------------------------------------- access codes
def test_codes_are_random_hashed_and_shown_once(env):
    db, c, state, events = env
    slug, org_id, _ = new_tenant(db, c, state)
    out = make_codes(c, org_id, role="bookkeeper", count=2)
    codes = [x["code"] for x in out["codes"]]
    assert len(set(codes)) == 2 and all(len(x) == 13 and x.startswith("ALP-") for x in codes)
    rows = db.query(OrgInvite).filter_by(org_id=org_id).all()
    for row in rows:                                                                    # the plain code is nowhere in the database
        blob = " ".join(str(getattr(row, col.name)) for col in OrgInvite.__table__.columns)
        assert not any(code in blob or code.replace("-", "") in blob for code in codes)
        assert len(row.code_hash) == 64 and row.code_hint.endswith("....")
    listing = c.get("/org/current/invites", headers={"X-Org-Id": str(org_id)}).json()
    assert "code" not in listing["items"][0] and all(i["code_hint"].endswith("....") for i in listing["items"])        # never retrievable again
    assert any(e[0] == "invite.created" and "code" not in str(e[1]) for e in events)


def test_full_join_flow_and_single_use(env):
    db, c, state, events = env
    slug, org_id, _ = new_tenant(db, c, state)
    code = make_codes(c, org_id, role="accountant", count=1)["codes"][0]["code"]
    found = c.get("/signup/organisations/search", params={"q": "alpha acc"}).json()["items"]
    assert found == [{"slug": slug, "name": "Alpha Accounting Pty Ltd", "location": "Sydney, NSW"}]          # nothing but name and town
    r = join(c, slug, code, "new.user@alpha.example")
    assert r.status_code == 200, r.text
    assert r.json()["tenant_url"] == f"https://{slug}.acc.test"
    from db_app.models import User
    u = db.query(User).filter_by(email="new.user@alpha.example").one()
    mem = db.query(m.OrgMembership).filter_by(user_id=u.id).all()
    assert [(x.org_id, x.role) for x in mem] == [(org_id, "accountant")]              # the code's role, in that organisation only
    again = c.post("/signup/verify-code", json={"slug": slug, "code": code})
    assert again.status_code == 400 and "not valid" in again.json()["detail"]         # single use
    assert {"signup.invite_redeemed", "signup.code_failed"} <= {e[0] for e in events}
    assert any(e[0] == "signup.code_failed" and e[1]["detail"]["reason"] == "already_used" for e in events)


def test_a_code_can_be_typed_loosely(env):
    db, c, state, events = env
    slug, org_id, _ = new_tenant(db, c, state)
    code = make_codes(c, org_id)["codes"][0]["code"]
    sloppy = " " + code.lower().replace("-", " ") + " "
    assert c.post("/signup/verify-code", json={"slug": slug.upper(), "code": sloppy}).status_code == 200


def test_invalid_expired_revoked_and_foreign_codes_get_the_same_answer(env):
    db, c, state, events = env
    slugA, orgA, _ = new_tenant(db, c, state)
    codes = [x for x in make_codes(c, orgA, role="bookkeeper", count=2)["codes"]]
    # a second organisation with its own code
    slugB, orgB, _ = new_tenant(db, c, state, name="Beta Builders Pty Ltd", abn="53 004 085 616", email="owner@beta.example")
    codeB = make_codes(c, orgB)["codes"][0]["code"]
    msg = "That access code is not valid, or has expired. Check it with your organisation administrator."
    bad = [c.post("/signup/verify-code", json={"slug": slugA, "code": "ZZZ-AAAA-BBBB"}),                # never existed
           c.post("/signup/verify-code", json={"slug": slugA, "code": "short"}),                         # malformed
           c.post("/signup/verify-code", json={"slug": slugA, "code": codeB}),                           # real code, WRONG organisation
           c.post("/signup/verify-code", json={"slug": "no-such-org", "code": codes[0]["code"]})]         # right code, unknown organisation
    state["uid"] = db.query(m.OrgMembership).filter_by(org_id=orgA, role="owner").one().user_id
    db.query(OrgInvite).filter_by(id=codes[1]["id"]).update({"expires_at": datetime.utcnow() - timedelta(seconds=1)}); db.commit()
    bad.append(c.post("/signup/verify-code", json={"slug": slugA, "code": codes[1]["code"]}))             # expired
    assert c.delete(f"/org/current/invites/{codes[0]['id']}", headers={"X-Org-Id": str(orgA)}).status_code == 200
    bad.append(c.post("/signup/verify-code", json={"slug": slugA, "code": codes[0]["code"]}))             # revoked
    assert all(r.status_code == 400 and r.json()["detail"] == msg for r in bad), [(r.status_code, r.text) for r in bad]
    reasons = {e[1]["detail"]["reason"] for e in events if e[0] == "signup.code_failed"}
    assert {"unknown_code", "malformed", "wrong_organisation", "unknown_organisation", "expired", "revoked"} <= reasons      # the audit log knows exactly why
    assert db.query(m.OrgMembership).filter_by(org_id=orgA).count() == 1


def test_revoking_after_verification_blocks_join(env):
    db, c, state, events = env
    slug, org_id, _ = new_tenant(db, c, state)
    made = make_codes(c, org_id)["codes"][0]
    v = c.post("/signup/verify-code", json={"slug": slug, "code": made["code"]}).json()
    assert c.delete(f"/org/current/invites/{made['id']}", headers={"X-Org-Id": str(org_id)}).status_code == 200
    r = c.post("/signup/join", json={"signup_token": v["signup_token"], "user": user_body("late@alpha.example")})
    assert r.status_code == 400 and "no longer valid" in r.json()["detail"]
    from db_app.models import User
    assert db.query(User).filter_by(email="late@alpha.example").count() == 0


def test_signup_token_cannot_be_forged_or_reused_for_another_org(env):
    db, c, state, events = env
    slug, org_id, _ = new_tenant(db, c, state)
    assert c.post("/signup/join", json={"signup_token": "garbage", "user": user_body("x@y.example")}).status_code == 400
    import jwt
    forged = jwt.encode({"typ": "signup", "org": org_id, "inv": 1, "exp": datetime.utcnow() + timedelta(minutes=5)}, "wrong-secret", algorithm="HS256")
    assert c.post("/signup/join", json={"signup_token": forged, "user": user_body("x@y.example")}).status_code == 400
    from accfino_core.security import tokens
    access_like = jwt.encode({"typ": "access", "org": org_id, "inv": 1, "exp": datetime.utcnow() + timedelta(minutes=5)}, tokens._secret(), algorithm="HS256")
    assert c.post("/signup/join", json={"signup_token": access_like, "user": user_body("x@y.example")}).status_code == 400


def test_multi_use_code_counts_uses(env):
    db, c, state, events = env
    slug, org_id, _ = new_tenant(db, c, state)
    from accfino_core.subscription.models import OrgSubscription
    db.get(OrgSubscription, org_id).plan_id = "seats-unlimited"; db.commit()                                         # unlimited seats for this test
    code = make_codes(c, org_id, role="readonly", count=1, max_uses=2)["codes"][0]["code"]
    assert join(c, slug, code, "a1@alpha.example").status_code == 200
    assert join(c, slug, code, "a2@alpha.example").status_code == 200
    assert join(c, slug, code, "a3@alpha.example").status_code == 400


def test_expired_code_with_max_lifetime_and_limits(env):
    db, c, state, events = env
    slug, org_id, _ = new_tenant(db, c, state)
    h = {"X-Org-Id": str(org_id)}
    for body in (dict(count=0), dict(count=51), dict(expires_in_days=0), dict(expires_in_days=91), dict(max_uses=0), dict(role="superuser")):
        assert c.post("/org/current/invites", json=body, headers=h).status_code == 422, body


# ---------------------------------------------------------------------------------------------- licence seats
def test_licence_seats_reserve_slots_and_block_signup(env):
    db, c, state, events = env
    slug, org_id, _ = new_tenant(db, c, state)                                           # Starter: 3 users, owner = 1
    h = {"X-Org-Id": str(org_id)}
    s = c.get("/org/current/invites", headers=h).json()["summary"]
    assert (s["licensed_users"], s["active_users"], s["pending_invitations"], s["available_slots"]) == (3, 1, 0, 2)
    made = make_codes(c, org_id, count=2)
    s = made["summary"]
    assert (s["pending_invitations"], s["available_slots"], s["codes"]["unused"]) == (2, 0, 2)
    r = c.post("/org/current/invites", json={"count": 1}, headers=h)
    assert r.status_code == 409 and "licensed user slots" in r.json()["detail"]         # nothing left to hand out
    assert join(c, slug, made["codes"][0]["code"], "u1@alpha.example").status_code == 200
    # the organisation fills up by another route while a valid code is still outstanding
    from db_app.models import User
    other = SD._get_or_create_user(db, "filler@example.com")[0]; db.flush()
    db.add(m.OrgMembership(org_id=org_id, user_id=other.id, role="readonly")); db.commit()
    r = c.post("/signup/verify-code", json={"slug": slug, "code": made["codes"][1]["code"]})
    assert r.status_code == 403 and r.json()["detail"] == T.SEAT_MESSAGE                 # valid code, but no licensed slot left
    assert any(e[0] == "signup.rejected_seat_limit" for e in events)
    s = c.get("/org/current/invites", headers=h).json()["summary"]
    assert s["active_users"] == 3 and s["codes"]["used"] == 1


def test_seat_is_rechecked_when_the_account_is_created(env):
    db, c, state, events = env
    slug, org_id, _ = new_tenant(db, c, state)
    code = make_codes(c, org_id, count=1)["codes"][0]["code"]
    v = c.post("/signup/verify-code", json={"slug": slug, "code": code}).json()           # verified while a seat is free...
    for i in range(2):                                                                    # ...then the seats are taken before the form is submitted
        u = SD._get_or_create_user(db, f"late{i}@example.com")[0]; db.flush()
        db.add(m.OrgMembership(org_id=org_id, user_id=u.id, role="readonly"))
    db.commit()
    r = c.post("/signup/join", json={"signup_token": v["signup_token"], "user": user_body("slow@alpha.example")})
    assert r.status_code == 403 and r.json()["detail"] == T.SEAT_MESSAGE


def test_direct_member_add_respects_licence_even_without_module_enforcement(env):
    db, c, state, events = env
    slug, org_id, _ = new_tenant(db, c, state)
    assert S.get_settings(db)["enforced"] is False
    from accfino_core.security.context import OrgContext
    org = db.get(m.Organisation, org_id)
    ctx = OrgContext(state["uid"], "u", False, org, "owner")
    S.check_seat(db, ctx)                                                                  # 1 of 3 used: fine
    make_codes(c, org_id, count=2)                                                         # both remaining seats now reserved by codes
    from fastapi import HTTPException
    with pytest.raises(HTTPException) as e:
        S.check_seat(db, ctx)
    assert e.value.status_code == 402 and "reserved by access codes" in e.value.detail


# ---------------------------------------------------------------------------------------------- brute force & enumeration
def test_brute_force_guessing_locks_out_even_the_right_code(env):
    db, c, state, events = env
    slug, org_id, _ = new_tenant(db, c, state)
    code = make_codes(c, org_id)["codes"][0]["code"]
    for i in range(5):
        assert c.post("/signup/verify-code", json={"slug": slug, "code": f"AAA-BBBB-{i:04d}".replace("0", "C")}).status_code == 400
    r = c.post("/signup/verify-code", json={"slug": slug, "code": code})                  # the correct code, but the guesser is locked out
    assert r.status_code == 429 and r.headers["Retry-After"] == str(15 * 60)
    assert any(e[0] == "signup.code_lockout" for e in events)
    assert sum(1 for e in events if e[0] == "signup.code_failed") == 5


def test_guessing_across_many_addresses_is_limited_per_organisation(env):
    db, c, state, events = env
    slug, org_id, _ = new_tenant(db, c, state)
    for i in range(25):                                                                   # the same organisation attacked from many addresses
        T.record_attempt(db, f"10.0.0.{i}", "code", org_id=org_id, success=False, reason="unknown_code")
    db.commit()
    assert c.post("/signup/verify-code", json={"slug": slug, "code": "ABC-DEFG-HJKL"}).status_code == 429


def test_search_exposes_only_name_and_town_and_is_enumeration_resistant(env):
    db, c, state, events = env
    slug, org_id, _ = new_tenant(db, c, state)
    for i in range(7):
        o = m.Organisation(name=f"Gamma Group {i}"); db.add(o); db.flush(); T.ensure_profile(db, o, city="Perth", state="WA")
    hidden = m.Organisation(name="Gamma Secret Ltd"); db.add(hidden); db.flush(); T.ensure_profile(db, hidden, discoverable=False); db.commit()
    assert c.get("/signup/organisations/search", params={"q": "ga"}).status_code == 422                 # too short to enumerate with
    items = c.get("/signup/organisations/search", params={"q": "gamma"}).json()["items"]
    assert len(items) == 5 and all(set(i) == {"slug", "name", "location"} for i in items)               # capped, minimal
    assert "Gamma Secret Ltd" not in [i["name"] for i in items]
    assert c.get("/signup/organisations/search", params={"q": "%%%"}).json()["items"] == []             # wildcards are not wildcards
    hp = db.query(OrgProfile).filter_by(org_id=hidden.id).one()
    assert c.get("/signup/organisations/lookup", params={"slug": hp.slug}).json()["name"] == "Gamma Secret Ltd"     # exact address still works
    assert c.get("/signup/organisations/lookup", params={"slug": "nope-nope"}).status_code == 404
    for _ in range(60):
        T.record_attempt(db, "testclient", "lookup", success=True)
    db.commit()
    assert c.get("/signup/organisations/search", params={"q": "gamma"}).status_code == 429               # scraping is throttled


# ---------------------------------------------------------------------------------------------- tenant isolation
def test_tenant_address_isolation(env):
    db, c, state, events = env
    slugA, orgA, _ = new_tenant(db, c, state)
    slugB, orgB, _ = new_tenant(db, c, state, name="Beta Builders Pty Ltd", abn="53 004 085 616", email="owner@beta.example")
    sign_in_as(db, state, "owner@alpha.example")                                         # an Alpha owner
    host = lambda s: {"Host": f"{s}.acc.test"}
    assert c.get("/whoami", headers=host(slugA)).json() == {"org": orgA, "role": "owner"}              # their own tenant: context comes from the ADDRESS
    r = c.get("/whoami", headers=host(slugB))
    assert r.status_code == 403                                                                        # someone else's tenant: refused
    r = c.get("/whoami", headers={**host(slugA), "X-Org-Id": str(orgB)})
    assert r.status_code == 403 and "different organisation" in r.json()["detail"]                       # changing the org id header does not hop tenants
    assert c.get("/whoami", headers=host(slugA), params={"org_id": orgB}).status_code == 403             # nor does the query string
    assert c.get("/whoami", headers={**host(slugA), "X-Org-Id": str(orgA)}).status_code == 200          # a matching id is fine
    assert c.get("/whoami", headers=host("ghost-org")).status_code == 404
    assert c.get("/whoami", headers={"Host": f"{slugB}.acc.test.evil.com"}).status_code in (200, 403)  # not a tenant address: ordinary membership rules apply
    assert c.get("/whoami", headers={"X-Org-Id": str(orgB)}).status_code == 403                         # apex address: still membership-checked
    state["admin"] = True
    assert c.get("/whoami", headers=host(slugB)).json()["org"] == orgB                                  # platform administrators may enter any tenant


def test_suspended_member_is_locked_out_of_the_tenant(env):
    db, c, state, events = env
    slug, org_id, _ = new_tenant(db, c, state)
    db.query(m.OrgMembership).filter_by(org_id=org_id).update({"suspended_at": datetime.utcnow()}); db.commit()
    assert c.get("/whoami", headers={"Host": f"{slug}.acc.test"}).status_code == 403


def test_tenant_current_tells_the_page_who_it_is_without_leaking(env):
    db, c, state, events = env
    slug, org_id, _ = new_tenant(db, c, state)
    j = c.get("/tenant/current", headers={"Host": f"{slug}.acc.test"}).json()
    assert j == {"tenant": slug, "found": True, "name": "Alpha Accounting Pty Ltd", "tenant_urls_enabled": True}
    assert c.get("/tenant/current", headers={"Host": "ghost.acc.test"}).json()["found"] is False
    assert c.get("/tenant/current").json()["tenant"] is None


# ---------------------------------------------------------------------------------------------- administration
def test_only_owners_and_admins_manage_codes(env):
    db, c, state, events = env
    slug, org_id, _ = new_tenant(db, c, state)
    code = make_codes(c, org_id, role="bookkeeper", count=1)["codes"][0]
    h = {"X-Org-Id": str(org_id)}
    assert join(c, slug, code["code"], "book@alpha.example").status_code == 200
    sign_in_as(db, state, "book@alpha.example")                                           # a bookkeeper
    assert c.get("/org/current/invites", headers=h).status_code == 403
    assert c.post("/org/current/invites", json={}, headers=h).status_code == 403
    assert c.delete(f"/org/current/invites/{code['id']}", headers=h).status_code == 403
    assert c.patch("/org/current/tenant", json={"discoverable": False}, headers=h).status_code == 403


def test_other_organisations_codes_are_invisible_and_cannot_be_revoked(env):
    db, c, state, events = env
    slugA, orgA, _ = new_tenant(db, c, state)
    idA = make_codes(c, orgA)["codes"][0]["id"]
    slugB, orgB, _ = new_tenant(db, c, state, name="Beta Builders Pty Ltd", abn="53 004 085 616", email="owner@beta.example")
    assert c.delete(f"/org/current/invites/{idA}", headers={"X-Org-Id": str(orgB)}).status_code == 404
    assert c.get("/org/current/invites", headers={"X-Org-Id": str(orgB)}).json()["items"] == []
    assert c.get("/org/current/invites", headers={"X-Org-Id": str(orgA)}).status_code == 403          # B's owner cannot read A's by changing the header


def test_codes_can_never_create_an_organisation_admin(env):
    """Exactly one Organisation Admin per organisation: neither 'owner' nor the legacy 'admin' can be issued through an access code."""
    db, c, state, events = env
    slug, org_id, _ = new_tenant(db, c, state)
    h = {"X-Org-Id": str(org_id)}
    for role in ("owner", "admin", "superuser"):
        assert c.post("/org/current/invites", json={"role": role}, headers=h).status_code == 422, role
    assert c.post("/org/current/invites", json={"role": "readonly"}, headers=h).status_code == 200
    assert db.query(m.OrgMembership).filter_by(org_id=org_id, role="owner").count() == 1


def test_tenant_profile_and_discoverability(env):
    db, c, state, events = env
    slug, org_id, _ = new_tenant(db, c, state)
    h = {"X-Org-Id": str(org_id)}
    t = c.get("/org/current/tenant", headers=h).json()
    assert t["slug"] == slug and t["tenant_url"] == f"https://{slug}.acc.test" and t["discoverable"] and t["licence"]["licensed_users"] == 3
    c.patch("/org/current/tenant", json={"discoverable": False, "phone": "02 9000 0000"}, headers=h)
    assert c.get("/signup/organisations/search", params={"q": "alpha"}).json()["items"] == []
    assert c.patch("/org/current/tenant", json={"contact_email": "bad"}, headers=h).status_code == 422
    assert any(e[0] == "org.profile_updated" for e in events)


# ---------------------------------------------------------------------------------------------- the old open signup
def test_legacy_open_registration_is_closed(env, monkeypatch):
    db, c, state, events = env
    from fastapi import HTTPException
    from db_app.api import auth
    req = auth.RegisterRequest(username="sneaky", email="sneaky@x.example", password=PW)
    with pytest.raises(HTTPException) as e:
        auth.register(req, db)
    assert e.value.status_code == 403 and "organisation" in e.value.detail
    assert T.legacy_signup_allowed(db) is False
    monkeypatch.setenv("ACCFINO_OPEN_SIGNUP", "1")
    assert T.legacy_signup_allowed(db) is True                                           # deliberate emergency switch only


def test_existing_organisations_get_a_tenant_address(env):
    db, c, state, events = env
    o = m.Organisation(name="Legacy Org"); db.add(o); db.commit()
    assert db.get(OrgProfile, o.id) is None
    assert T.backfill_profiles(db) >= 1 and db.get(OrgProfile, o.id).slug == "legacy-org"
    assert T.backfill_profiles(db) == 0                                                  # idempotent


# ---------------------------------------------------------------------------------------------- the real auth middleware
def test_auth_middleware_enforces_tenant_isolation_on_every_authenticated_route(env, monkeypatch):
    from accfino_core.security import iam
    from accfino_core.security.middleware import AuthGuard
    db, _, state, events = env
    A = db.query(m.Organisation).count()                                                              # (just to have a handle on ids)
    app = FastAPI()
    for r, p in ((signup_api.tenant_router, "/tenant"), (signup_api.signup_router, "/signup")):
        app.include_router(r, prefix=p)

    @app.get("/anything")
    def anything(): return {"ok": True}

    @app.post("/anything")
    def anything_post(): return {"ok": True}

    @app.get("/auth/me")
    def me(): return {"me": True}
    app.dependency_overrides[get_db] = lambda: db
    app.add_middleware(AuthGuard, fastapi_app=app)

    members = {(1, 10): "owner", (2, 20): "owner"}                        # user 1 belongs to org 10, user 2 to org 20
    slugs = {"alpha": 10, "beta": 20}
    users = {"u1": dict(user_id=1, is_admin=False), "u2": dict(user_id=2, is_admin=False), "root": dict(user_id=99, is_admin=True)}

    def fake_auth(headers):
        k = headers.get("x-test-user")
        if not k:
            return None, "missing_token"
        return {**users[k], "username": k, "email": k, "org_id": None, "mfa": True, "jti": "j", "sid": None, "amr": ["pwd"], "session_started": None, "must_change_password": False}, None
    monkeypatch.setattr(AuthGuard, "_authenticate", staticmethod(fake_auth))
    monkeypatch.setattr(iam, "tenant_org_id", lambda slug: slugs.get(slug))
    monkeypatch.setattr(iam, "member_role", lambda uid, oid: members.get((uid, oid)))
    monkeypatch.setattr(iam, "org_policy", lambda oid: None)
    monkeypatch.setattr(iam, "contact_missing", lambda uid: [])                                         # (these fake users have complete profiles)
    c = TestClient(app)
    go = lambda host, user="u1", method="GET", path="/anything", **h: c.request(method, path, headers={"Host": host, "x-test-user": user, **h})

    assert go("alpha.acc.test").status_code == 200                                        # a member in their own tenant
    r = go("beta.acc.test")
    assert r.status_code == 403 and r.json()["code"] == "tenant_forbidden"                 # ...but not in another tenant
    assert go("beta.acc.test", method="POST").status_code == 403                           # writes too
    r = go("alpha.acc.test", **{"x-org-id": "20"})
    assert r.status_code == 403 and r.json()["code"] == "tenant_mismatch"                  # changing the org id header does nothing
    assert go("alpha.acc.test", **{"x-org-id": "10"}).status_code == 200
    assert go("ghost.acc.test").status_code == 404 and go("ghost.acc.test").json()["code"] == "tenant_unknown"
    assert go("beta.acc.test", user="root").status_code == 200                              # platform administrator
    assert go("beta.acc.test", path="/auth/me").status_code == 200                          # who-am-I and sign-out stay reachable
    assert go("acc.test").status_code == 200 and go("localhost:8000").status_code == 200    # no tenant address: unchanged behaviour
    assert c.get("/anything", headers={"Host": "alpha.acc.test"}).status_code == 401        # no credentials at all
    assert c.get("/tenant/current", headers={"Host": "alpha.acc.test"}).status_code == 200  # signup/tenant endpoints stay public on any address
    assert c.post("/signup/verify-code", headers={"Host": "beta.acc.test"}, json={"slug": "x", "code": "y"}).status_code == 400
    denied = [e for e in events if e[0] == "tenant.access_denied"]
    assert {e[1]["detail"]["code"] for e in denied} == {"tenant_forbidden", "tenant_mismatch", "tenant_unknown"}
    assert all(e[1]["detail"]["tenant"] for e in denied)
