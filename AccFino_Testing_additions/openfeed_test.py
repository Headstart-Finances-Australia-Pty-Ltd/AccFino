"""OpenFeed CDR connector against a MOCK OpenFeed (httpx.MockTransport) that enforces the real protocol rules from openfeed.au/llms-full.txt:
PAR is mandatory, client_assertion is PS256 with aud = issuer, every token/data call carries a valid DPoP proof (htu/htm/ath/jwk), tokens need `resource`,
data needs an active grant, 402/403 shapes. It proves AccFino's side is correct - it does NOT prove the live service accepts our app (that needs registration).
Run from backend/:  PYTHONPATH=. python -m pytest ../AccFino_Testing_additions/openfeed_test.py -q"""
import base64, hashlib, json, os, sys
from datetime import date
from urllib.parse import parse_qs, urlparse
import httpx, jwt, pytest
sys.path.insert(0, os.path.dirname(__file__))
from csv_import_harness import make_db, make_org
from cryptography.hazmat.primitives import serialization
from accfino_core import openfeed_cdr as OF, models as m

ISS, API, CONSENT = "https://auth.openfeed.au", "https://api.openfeed.au", "https://app.openfeed.au"


class MockOpenFeed:
    """Minimal OpenFeed. Records what it saw; fails loudly (400/401) when AccFino breaks a protocol rule."""
    def __init__(self, app_pub_jwk):
        self.app_pub = jwt.algorithms.RSAAlgorithm.from_jwk(json.dumps(app_pub_jwk))
        self.pars, self.codes, self.grant, self.revoked, self.calls = {}, {}, None, False, []
        self.refresh_n = 0
        self.require_nonce = False
        self.credit_ok = True
        self.accounts = [{"accountId": "acc1", "displayName": "Business Cheque", "maskedNumber": "xxxx1234", "providerName": "Commonwealth Bank"}]
        self.txns = [{"transactionId": "t1", "accountId": "acc1", "transactionDate": "2026-09-10", "amount": "-45.50", "description": "Office supplies"},
                     {"transactionId": "t2", "accountId": "acc1", "valueDate": "2026-09-12", "amount": "1200.00", "description": "Customer payment"},
                     {"transactionId": "t3", "accountId": "acc1", "amount": "5", "description": "No date at all"},
                     {"transactionId": "t4", "accountId": "acc1", "transactionDate": "2026-08-01", "amount": "-9", "description": "Out of range"}]

    # -- checks
    def _client_assertion(self, f):
        c = jwt.decode(f["client_assertion"][0], self.app_pub, algorithms=["PS256"], audience=ISS)
        assert c["iss"] == c["sub"] == "app-123" and c["exp"] - c["iat"] <= 60 and c["jti"]
        return c

    def _dpop(self, req, token=None):
        proof = req.headers["DPoP"]
        hdr = jwt.get_unverified_header(proof)
        assert hdr["typ"] == "dpop+jwt" and hdr["alg"] == "PS256" and "jwk" in hdr and "d" not in hdr["jwk"]          # public key only
        pub = jwt.algorithms.RSAAlgorithm.from_jwk(json.dumps(hdr["jwk"]))
        c = jwt.decode(proof, pub, algorithms=["PS256"], options={"verify_aud": False})
        assert c["htm"] == req.method and c["htu"] == str(req.url).split("?")[0]
        if token:
            assert c["ath"] == base64.urlsafe_b64encode(hashlib.sha256(token.encode()).digest()).rstrip(b"=").decode()
        return c, hdr["jwk"]

    def __call__(self, req: httpx.Request) -> httpx.Response:
        url, form = str(req.url), parse_qs(req.content.decode()) if req.content else {}
        self.calls.append((req.method, url.split("?")[0]))
        if url.endswith("/.well-known/openid-configuration"):
            return httpx.Response(200, json={"issuer": ISS, "token_endpoint": ISS + "/token", "authorization_endpoint": ISS + "/auth",
                                             "pushed_authorization_request_endpoint": ISS + "/par", "jwks_uri": ISS + "/jwks"})
        if url == ISS + "/par":
            self._client_assertion(form)
            assert form["code_challenge_method"] == ["S256"] and form["resource"] == [API] and form["response_type"] == ["code"] and form["client_id"] == ["app-123"]
            rid = "urn:request:" + str(len(self.pars))
            self.pars[rid] = {k: v[0] for k, v in form.items()}
            return httpx.Response(201, json={"request_uri": rid, "expires_in": 60})
        if url == ISS + "/token":
            self._client_assertion(form)
            if self.require_nonce and "nonce" not in jwt.decode(req.headers["DPoP"], options={"verify_signature": False}):
                return httpx.Response(400, json={"error": "use_dpop_nonce"}, headers={"DPoP-Nonce": "n-1"})
            self._dpop(req)
            assert form["resource"] == [API]
            if form["grant_type"] == ["authorization_code"]:
                par = self.codes.pop(form["code"][0])
                v = form["code_verifier"][0]
                assert base64.urlsafe_b64encode(hashlib.sha256(v.encode()).digest()).rstrip(b"=").decode() == par["code_challenge"]       # PKCE
                body = {"access_token": "AT-login", "token_type": "DPoP", "refresh_token": "RT-0", "expires_in": 3600}
                if self.grant:
                    body["authorization_details"] = [{"grant_id": self.grant}]
                return httpx.Response(200, json=body)
            if form["grant_type"] == ["refresh_token"]:
                if form["refresh_token"][0] != f"RT-{self.refresh_n}":
                    return httpx.Response(400, json={"error": "invalid_grant"})
                self.refresh_n += 1
                body = {"access_token": f"AT-{self.refresh_n}", "token_type": "DPoP", "refresh_token": f"RT-{self.refresh_n}", "expires_in": 3600}       # rotates
                if self.grant:
                    body["authorization_details"] = [{"grant_id": self.grant}]
                return httpx.Response(200, json=body)
        if url.startswith(API + "/v1/"):
            auth = req.headers["Authorization"]
            assert auth.startswith("DPoP ")
            self._dpop(req, auth[5:])
            if req.method == "DELETE":
                self.revoked, self.grant = True, None
                return httpx.Response(204)
            if self.revoked or not self.grant:
                return httpx.Response(403, json={"code": "disclosure_grant_required"})
            if not self.credit_ok:
                return httpx.Response(402, json={"code": "credit_exhausted"})
            path = urlparse(url).path
            if path == "/v1/banking/accounts":
                return httpx.Response(200, json={"version": "V1", "data": self.accounts, "links": {}})
            if path.endswith("/transactions"):
                q = parse_qs(urlparse(url).query)
                if q.get("offset") != ["1"] and len(self.txns) > 2:                  # two pages, to exercise links.next
                    return httpx.Response(200, json={"version": "V1", "data": self.txns[:2], "links": {"next": url + "&offset=1"}})
                return httpx.Response(200, json={"version": "V1", "data": self.txns[2:], "links": {}})
        return httpx.Response(404)

    def user_approves(self, grant="grant-1"):
        self.grant = grant


@pytest.fixture()
def env(monkeypatch):
    db = make_db(); org, ctx = make_org(db)
    monkeypatch.setenv("APP_URL", "https://app.accfino.test")
    for k in ("OPENFEED_CLIENT_ID", "OPENFEED_APP_ID", "OPENFEED_APP_PRIVATE_KEY", "OPENFEED_DPOP_PRIVATE_KEY"):
        monkeypatch.delenv(k, raising=False)
    jwks = OF.generate_platform_keys(db)                                        # the admin's one-time setup
    OF.save_platform_ids(db, "app-123", "11111111-2222-3333-4444-555555555555"); db.commit()
    mock = MockOpenFeed(jwks["keys"][0])
    monkeypatch.setattr(OF, "_transport", httpx.MockTransport(mock))
    OF._discovery_cache.clear(); OF._nonces.clear()
    yield db, org, ctx, mock
    db.close()


def go_through_openfeed(db, org, ctx, mock, approve_in_bank=True):
    """Drive the whole browser journey: Connect -> OpenFeed sign-in -> callback -> share screen -> consent-return."""
    url = OF.start_connect(db, org.id, ctx.user_id, "http://internal:8000", "/settings/open-banking"); db.commit()
    q = parse_qs(urlparse(url).query)
    assert url.startswith(ISS + "/auth?") and q["client_id"] == ["app-123"] and q["request_uri"][0] in mock.pars                      # PAR used; no raw params in the URL
    par = mock.pars[q["request_uri"][0]]
    assert par["redirect_uri"] == "https://app.accfino.test/open-banking/openfeed/callback"                                           # APP_URL, not the internal host
    mock.codes["code-1"] = par
    nxt, state = OF.handle_callback(db, {"code": "code-1", "state": par["state"], "iss": ISS}); db.commit()
    return par, nxt, state


def test_the_organisation_just_presses_connect_and_the_data_flows(env):
    db, org, ctx, mock = env
    par, nxt, state = go_through_openfeed(db, org, ctx, mock)
    assert nxt.startswith(CONSENT + "/grants/disclosure?") and "appId=11111111-2222-3333-4444-555555555555" in nxt                  # first time: share screen
    assert "redirectUri=https%3A%2F%2Fapp.accfino.test%2Fopen-banking%2Fopenfeed%2Fconsent-return" in nxt
    assert OF.status(db, org.id)["status"] == "pending"
    mock.user_approves("grant-1")                                                                                                     # the person ticks the account
    back = OF.handle_consent_return(db, state, {"grantId": "grant-1", "consented": "true"}); db.commit()
    assert back == "/settings/open-banking?openfeed=connected"
    st = OF.status(db, org.id)
    assert st["status"] == "active" and st["accounts"] == [{"id": "acc1", "name": "Business Cheque", "masked": "xxxx1234", "provider": "Commonwealth Bank"}]
    assert st["last_sync"]                                                                                                            # first pull happened by itself
    rows = OF.pull_rows(db, org.id, "acc1", date(2026, 9, 1), date(2026, 9, 30)); db.commit()
    assert [(r["date"], r["debit"], r["credit"], r["description"]) for r in rows] == [("10/09/2026", 45.5, 0.0, "Office supplies"), ("12/09/2026", 0.0, 1200.0, "Customer payment")]
    assert rows[0]["bank"] == "Commonwealth Bank" and rows[0]["account"] == "xxxx1234"                                                  # undated / out-of-range rows dropped, valueDate used when needed


def test_tokens_are_encrypted_at_rest_and_the_refresh_token_rotation_is_kept(env):
    db, org, ctx, mock = env
    par, nxt, state = go_through_openfeed(db, org, ctx, mock); mock.user_approves()
    OF.handle_consent_return(db, state, {"grantId": "grant-1", "consented": "true"}); db.commit()
    conn = db.get(OF.OpenFeedConnection, org.id)
    assert "RT-" not in conn.refresh_token_enc and OF.unseal(conn.refresh_token_enc).startswith("RT-")                                # sealed
    first = OF.unseal(conn.refresh_token_enc)
    OF.pull_rows(db, org.id, "acc1", date(2026, 9, 1), date(2026, 9, 30)); db.commit()
    OF.pull_rows(db, org.id, "acc1", date(2026, 9, 1), date(2026, 9, 30)); db.commit()                                                 # would 400 if the old token were reused
    assert OF.unseal(db.get(OF.OpenFeedConnection, org.id).refresh_token_enc) != first


def test_a_returning_user_who_already_shared_skips_the_share_screen(env):
    db, org, ctx, mock = env
    mock.user_approves("grant-9")
    par, nxt, state = go_through_openfeed(db, org, ctx, mock)
    assert nxt == "/settings/open-banking?openfeed=connected" and OF.status(db, org.id)["status"] == "active"


def test_declining_the_share_screen_leaves_nothing_connected(env):
    db, org, ctx, mock = env
    par, nxt, state = go_through_openfeed(db, org, ctx, mock)
    assert OF.handle_consent_return(db, state, {"consented": "false", "reason": "declined"}) == "/settings/open-banking?openfeed=declined"; db.commit()
    assert OF.status(db, org.id)["status"] == "pending" and OF.status(db, org.id)["accounts"] == []


def test_safety_checks_state_issuer_grant_binding_and_single_use(env):
    db, org, ctx, mock = env
    url = OF.start_connect(db, org.id, ctx.user_id, "http://x", "/settings/open-banking"); db.commit()
    par = mock.pars[parse_qs(urlparse(url).query)["request_uri"][0]]; mock.codes["c"] = par
    with pytest.raises(OF.OpenFeedError) as e: OF.handle_callback(db, {"code": "c", "state": "forged", "iss": ISS})
    assert e.value.code == "flow_expired"                                                                                              # unknown state
    with pytest.raises(OF.OpenFeedError) as e: OF.handle_callback(db, {"code": "c", "state": par["state"], "iss": "https://evil.example"})
    assert e.value.code == "issuer_mismatch"                                                                                           # RFC 9207
    nxt, state = OF.handle_callback(db, {"code": "c", "state": par["state"], "iss": ISS}); db.commit()
    mock.user_approves("grant-1")
    with pytest.raises(OF.OpenFeedError) as e: OF.handle_consent_return(db, state, {"grantId": "someone-elses-grant", "consented": "true"})
    assert e.value.code == "grant_mismatch"                                                                                            # token must be bound to the grant just approved
    with pytest.raises(OF.OpenFeedError) as e: OF.handle_consent_return(db, "", {"grantId": "grant-1", "consented": "true"})
    assert e.value.code == "flow_expired"                                                                                              # no cookie, no way in


def test_dpop_nonce_is_retried_once(env):
    db, org, ctx, mock = env
    mock.require_nonce = True
    par, nxt, state = go_through_openfeed(db, org, ctx, mock)
    assert nxt.startswith(CONSENT)                                                                                                     # token call survived the nonce demand


def test_revoking_at_openfeed_stops_the_feed_and_asks_to_reconnect(env):
    db, org, ctx, mock = env
    par, nxt, state = go_through_openfeed(db, org, ctx, mock); mock.user_approves()
    OF.handle_consent_return(db, state, {"grantId": "grant-1", "consented": "true"}); db.commit()
    mock.grant = None                                                                                                                  # the person switched AccFino off in their OpenFeed dashboard
    with pytest.raises(OF.OpenFeedError) as e: OF.pull_rows(db, org.id, "acc1", date(2026, 9, 1), date(2026, 9, 30))
    db.commit()
    assert e.value.code == "grant_revoked"
    st = OF.status(db, org.id)
    assert st["status"] == "revoked" and st["accounts"] == [] and OF.org_accounts(db, org.id) == []                                     # cached data cleared, not offered for reconciliation


def test_credit_exhausted_pauses_without_losing_the_connection(env):
    db, org, ctx, mock = env
    par, nxt, state = go_through_openfeed(db, org, ctx, mock); mock.user_approves()
    OF.handle_consent_return(db, state, {"grantId": "grant-1", "consented": "true"}); db.commit()
    mock.credit_ok = False
    with pytest.raises(OF.OpenFeedError) as e: OF.sync(db, org.id, force=True)
    db.commit()
    assert e.value.code == "credit_exhausted" and OF.status(db, org.id)["status"] == "paused" and db.get(OF.OpenFeedConnection, org.id).grant_id == "grant-1"
    mock.credit_ok = True
    assert OF.sync(db, org.id, force=True)["status"] == "active"                                                                         # tops up -> recovers by itself


def test_disconnect_revokes_at_openfeed_and_forgets_everything(env):
    db, org, ctx, mock = env
    par, nxt, state = go_through_openfeed(db, org, ctx, mock); mock.user_approves()
    OF.handle_consent_return(db, state, {"grantId": "grant-1", "consented": "true"}); db.commit()
    OF.disconnect(db, org.id); db.commit()
    assert mock.revoked and ("DELETE", API + "/v1/grants/grant-1") in mock.calls
    assert OF.status(db, org.id)["status"] == "not_connected" and db.get(OF.OpenFeedConnection, org.id) is None


def test_not_configured_is_a_clear_message_not_a_crash(env, monkeypatch):
    db, org, ctx, mock = env
    for k in ("openfeed.client_id", "openfeed.app_id"):
        db.delete(db.get(m.SystemSetting, k))
    db.commit()
    with pytest.raises(OF.OpenFeedError) as e: OF.start_connect(db, org.id, ctx.user_id, "http://x")
    assert e.value.code == "not_configured" and "contact AccFino support" in e.value.message
    assert OF.status(db, org.id)["available"] is False


def test_platform_keys_only_expose_the_public_half(env):
    db, org, ctx, mock = env
    jwks = OF.generate_platform_keys(db); db.commit()
    k = jwks["keys"][0]
    assert k["kty"] == "RSA" and k["alg"] == "PS256" and "d" not in k and "p" not in k                                                    # nothing private leaves the server
    assert "BEGIN" not in db.get(m.SystemSetting, "openfeed.app_key").value                                                              # stored encrypted


# ------------------------------------------------------------------------------------------------------------------ over HTTP --
def http_client(db, org, ctx, role="owner", admin=False):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from accfino_core.api import openfeed_api as API
    from accfino_core.security.context import OrgContext, current_org, current_auth
    from db_app.database import get_db
    app = FastAPI()
    app.include_router(API.platform, prefix="/openfeed"); app.include_router(API.org_router, prefix="/org/current/open-banking"); app.include_router(API.public, prefix="/open-banking/openfeed")
    st = dict(role=role, admin=admin)
    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[current_org] = lambda: OrgContext(ctx.user_id, "tester", st["admin"], org, st["role"])
    app.dependency_overrides[current_auth] = lambda: {"user_id": ctx.user_id, "username": "tester", "is_admin": st["admin"]}
    @app.middleware("http")
    async def _auth(request, call_next):
        request.state.auth = {"user_id": ctx.user_id, "username": "tester", "is_admin": st["admin"]}
        return await call_next(request)
    return TestClient(app, base_url="https://app.accfino.test", follow_redirects=False), st


def test_http_journey_only_the_organisation_admin_connects_and_the_cookie_links_the_return(env):
    db, org, ctx, mock = env
    c, st = http_client(db, org, ctx, role="accountant")
    assert c.get("/org/current/open-banking").json()["status"] == "not_connected"
    assert c.get("/org/current/open-banking").json()["can_manage"] is False
    assert c.post("/org/current/open-banking/connect").status_code == 403                                   # not the Organisation Admin
    st["role"] = "owner"
    r = c.post("/org/current/open-banking/connect", json={"return_to": "https://evil.example/x"})
    assert r.status_code == 200
    par = mock.pars[parse_qs(urlparse(r.json()["url"]).query)["request_uri"][0]]
    assert par["redirect_uri"].startswith("https://app.accfino.test/")
    mock.codes["c1"] = par
    cb = c.get("/open-banking/openfeed/callback", params={"code": "c1", "state": par["state"], "iss": ISS})   # OpenFeed redirects the browser here (no session header)
    assert cb.status_code == 303 and cb.headers["location"].startswith(CONSENT + "/grants/disclosure") and "of_flow=" in cb.headers["set-cookie"] and "HttpOnly" in cb.headers["set-cookie"]
    mock.user_approves("grant-1")
    back = c.get("/open-banking/openfeed/consent-return", params={"grantId": "grant-1", "consented": "true"})
    assert back.status_code == 303 and back.headers["location"] == "/settings/open-banking?openfeed=connected"      # return_to off-site was ignored
    assert c.get("/org/current/open-banking").json()["accounts"][0]["name"] == "Business Cheque"
    pull = c.post("/org/current/open-banking/pull", json={"account_id": "acc1", "from_date": "2026-09-01", "to_date": "2026-09-30"}).json()
    assert pull["count"] == 2
    assert c.post("/org/current/open-banking/pull", json={"account_id": "acc1", "from_date": "2026-10-01", "to_date": "2026-09-01"}).status_code == 400
    assert c.post("/org/current/open-banking/disconnect").json()["ok"] and c.get("/org/current/open-banking").json()["status"] == "not_connected"


def test_http_a_replayed_or_cookieless_return_goes_nowhere_useful(env):
    db, org, ctx, mock = env
    c, st = http_client(db, org, ctx)
    r = c.get("/open-banking/openfeed/consent-return", params={"grantId": "g", "consented": "true"})              # no cookie
    assert r.status_code == 303 and "openfeed=error" in r.headers["location"] and "reason=flow_expired" in r.headers["location"]
    r = c.get("/open-banking/openfeed/callback", params={"error": "access_denied"})
    assert "openfeed=declined" in r.headers["location"]


def test_http_platform_setup_is_admin_only_and_never_returns_private_keys(env):
    db, org, ctx, mock = env
    c, st = http_client(db, org, ctx, admin=False)
    assert c.get("/openfeed/status").status_code == 403 and c.post("/openfeed/keys").status_code == 403
    st["admin"] = True
    assert c.get("/openfeed/status").json()["ready"] is True
    k = c.post("/openfeed/keys").json()
    assert "d" not in k["jwks"]["keys"][0] and "PRIVATE" not in json.dumps(k)
    assert c.post("/openfeed/config", json={"client_id": "11111111-bare-uuid", "app_id": "x"}).status_code == 422      # catches pasting the wrong id
    assert c.post("/openfeed/config", json={"client_id": "app-999", "app_id": "uuid"}).json()["ok"]
