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
        self.kid = app_pub_jwk["kid"]
        self.registered_scopes = {"openid", "offline_access", "openfeed-au:data:banking:read"}
        self.registered_redirect = None
        self.data_scope_needs_localhost = False
        self.data_scope_requires_grant_mgmt = False
        self.data_scope_needs_https = False
        self.data_scope_needs_resource = False
        self.data_scope_only_without_openid = False
        self.data_scope_rejects_grant_mgmt = False
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
        """Returns the claims, or None when OpenFeed would answer invalid_client (unknown kid / wrong key / expired or future-dated)."""
        import time as _t
        try:
            if jwt.get_unverified_header(f["client_assertion"][0]).get("kid") != self.kid:           # the key is looked up by kid in the registered key set
                return None
            c = jwt.decode(f["client_assertion"][0], self.app_pub, algorithms=["PS256"], audience=ISS, options={"verify_exp": False, "verify_iat": False})
        except jwt.InvalidTokenError:
            return None
        if abs(c["iat"] - _t.time()) > 120 or c["exp"] < _t.time() or c["exp"] - c["iat"] > 60:                  # stale (a mis-set time zone), or lifetime too long
            return None
        assert c["iss"] == c["sub"] == "app-123" and c["jti"]
        return c

    INVALID_CLIENT = httpx.Response(401, json={"error": "invalid_client", "error_description": "client authentication failed"})

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
            if self._client_assertion(form) is None:
                return self.INVALID_CLIENT
            if "DPoP" not in req.headers:                                                                      # PAR needs a DPoP proof too
                return httpx.Response(400, json={"error": "invalid_dpop_proof", "error_description": "DPoP header missing"})
            self._dpop(req)
            if not set(form["scope"][0].split()) <= self.registered_scopes:
                return httpx.Response(400, json={"error": "invalid_scope", "error_description": "scope not enabled for this app"})
            if self.data_scope_needs_localhost and "openfeed-au:data:banking:read" in form["scope"][0].split() and form["redirect_uri"][0].startswith("http://127.0.0.1"):
                return httpx.Response(400, json={"error": "invalid_scope", "error_description": "requested scope is not allowed"})
            if self.registered_redirect and form["redirect_uri"][0] != self.registered_redirect:
                return httpx.Response(400, json={"error": "invalid_redirect_uri", "error_description": "redirect_uri is not registered"})
            assert form.get("resource", [API]) == [API]                                                       # the only resource there is
            if "openfeed-au:data:banking:read" in form["scope"][0].split():
                if self.data_scope_needs_resource and "resource" not in form:
                    return httpx.Response(400, json={"error": "invalid_scope", "error_description": "requested scope is not allowed"})
                if self.data_scope_only_without_openid and "openid" in form["scope"][0].split():
                    return httpx.Response(400, json={"error": "invalid_scope", "error_description": "requested scope is not allowed"})
            gm = form.get("grant_management_action", [None])[0]
            assert gm in (None, "create", "replace") and (gm != "replace" or form.get("grant_id"))           # replace needs the existing grant id
            if "openfeed-au:data:banking:read" in form["scope"][0].split():
                if self.data_scope_needs_https and not form["redirect_uri"][0].startswith("https://"):
                    return httpx.Response(400, json={"error": "invalid_scope", "error_description": "requested scope is not allowed"})
                if self.data_scope_requires_grant_mgmt and gm is None:
                    return httpx.Response(400, json={"error": "invalid_scope", "error_description": "requested scope is not allowed"})
                if self.data_scope_rejects_grant_mgmt and gm is not None:
                    return httpx.Response(400, json={"error": "invalid_scope", "error_description": "requested scope is not allowed"})
            assert form["code_challenge_method"] == ["S256"] and form["response_type"] == ["code"] and form["client_id"] == ["app-123"]
            rid = "urn:request:" + str(len(self.pars))
            self.pars[rid] = {k: v[0] for k, v in form.items()}
            return httpx.Response(201, json={"request_uri": rid, "expires_in": 60})
        if url == ISS + "/token":
            if self._client_assertion(form) is None:
                return self.INVALID_CLIENT
            if self.require_nonce and "nonce" not in jwt.decode(req.headers["DPoP"], options={"verify_signature": False}):
                return httpx.Response(400, json={"error": "use_dpop_nonce"}, headers={"DPoP-Nonce": "n-1"})
            self._dpop(req)
            assert form["client_id"] == ["app-123"] and form.get("resource", [API]) == [API]
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
    assert "offline_access" in par["scope"].split() and "openid" in par["scope"].split()                                               # the real sign-in asks for a refresh token
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
    assert st["status"] == "active" and st["accounts"] == [{"id": "acc1", "name": "Business Cheque", "masked": "xxxx1234", "provider": "Commonwealth Bank", "enabled": True}]
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


# ------------------------------------------------------------------------------------------- the failure the administrator hit
def test_par_failure_is_explained_to_the_administrator_but_not_to_clients(env):
    db, org, ctx, mock = env
    mock.registered_scopes = {"openfeed-au:data:banking:read"}                      # app registered without openid / offline_access (what the old guide said)
    with pytest.raises(OF.OpenFeedError) as e: OF.start_connect(db, org.id, ctx.user_id, "http://x")
    assert e.value.code == "par_failed" and "contact AccFino support" in e.value.message and "invalid_scope" not in e.value.message      # clients: plain
    assert "invalid_scope" in e.value.detail                                                                                              # the administrator: the real reason


def test_diagnose_reports_what_to_fix_and_confirms_when_right(env):
    db, org, ctx, mock = env
    mock.registered_redirect = "https://somewhere-else.example/callback"
    out = OF.diagnose(db, "http://internal")
    assert out["ok"] is False and "invalid_redirect_uri" in out["message"] and out["redirect_uri"] == "https://app.accfino.test/open-banking/openfeed/callback"
    assert "not registered at OpenFeed" in " ".join(out["hints"]) and "APP_URL" in " ".join(out["hints"])
    mock.registered_redirect = out["redirect_uri"]
    assert OF.diagnose(db, "http://internal")["ok"] is True and "correct" in OF.diagnose(db, "http://internal")["message"]
    db.delete(db.get(m.SystemSetting, "openfeed.kid")); db.commit()                  # keys made by an older release carry no key id
    out = OF.diagnose(db, "http://internal"); assert out["ok"] is False and "key id" in out["message"]


def test_assertion_carries_the_kid_that_the_published_key_set_has(env):
    db, org, ctx, mock = env
    cfg = OF.Cfg(db)
    assert jwt.get_unverified_header(OF.client_assertion(cfg))["kid"] == cfg.kid == mock.kid


# ------------------------------------------------------------------------------- "invalid_client - client authentication failed"
def test_signatures_use_real_utc_time_whatever_the_server_time_zone(env, monkeypatch):
    """The old code used datetime.utcnow().timestamp(), which a server in Sydney shifts by 10 hours - OpenFeed then rejects every signature as invalid_client."""
    import time as _t
    db, org, ctx, mock = env
    monkeypatch.setenv("TZ", "Australia/Sydney"); _t.tzset()
    try:
        cfg = OF.Cfg(db)
        c = jwt.decode(OF.client_assertion(cfg), options={"verify_signature": False, "verify_aud": False})
        d = jwt.decode(OF.dpop_proof(cfg, "https://auth.openfeed.au/par", "POST"), options={"verify_signature": False, "verify_aud": False})
        assert abs(c["iat"] - _t.time()) < 5 and abs(d["iat"] - _t.time()) < 5 and c["exp"] > _t.time()
        assert OF.diagnose(db, "http://x")["ok"] is True                                         # and the mock (which rejects stale timestamps) accepts it
    finally:
        monkeypatch.delenv("TZ"); _t.tzset()


def test_public_key_set_can_be_shown_again_and_is_exactly_what_signs(env):
    db, org, ctx, mock = env
    jwks = OF.public_jwks(db); k = jwks["keys"][0]
    assert k["kid"] == OF.Cfg(db).kid and "d" not in k and k["alg"] == "PS256"
    pub = jwt.algorithms.RSAAlgorithm.from_jwk(json.dumps(k))
    jwt.decode(OF.client_assertion(OF.Cfg(db)), pub, algorithms=["PS256"], audience=ISS)         # the re-shown set verifies AccFino's signature
    assert len(OF.thumbprint(k)) == 43 and OF.thumbprint(k) == OF.thumbprint(OF.public_jwks(db)["keys"][0])


def test_invalid_client_names_the_likely_causes_and_the_key_to_compare(env):
    db, org, ctx, mock = env
    other = OF.generate_platform_keys(db); db.commit()                                           # keys regenerated in AccFino AFTER the old set was registered at OpenFeed
    out = OF.diagnose(db, "http://x")
    assert out["ok"] is False and "invalid_client" in out["message"]
    text = " ".join(out["hints"]); cfg = OF.Cfg(db)
    assert cfg.kid in text and "Show public key set" in text and "app-" in text and "private_key_jwt" in text
    assert OF.thumbprint(OF.public_jwks(db)["keys"][0]) in text


def test_clock_skew_is_reported_when_the_server_time_is_wrong(env, monkeypatch):
    from email.utils import formatdate
    import time as _t
    db, org, ctx, mock = env
    orig = mock.__call__
    def late(req):
        r = orig(req)
        if str(req.url).endswith("/par"): r.headers["Date"] = formatdate(_t.time() + 600, usegmt=True)   # OpenFeed's clock is 10 minutes ahead of ours
        return r
    mock.registered_scopes = set()                                                               # force a failure so the diagnosis is shown
    monkeypatch.setattr(OF, "_transport", httpx.MockTransport(late))
    out = OF.diagnose(db, "http://x")
    assert any("clock" in h and "behind" in h for h in out["hints"])


def test_http_public_key_endpoint_is_admin_only_and_public_only(env):
    db, org, ctx, mock = env
    c, st = http_client(db, org, ctx, admin=False)
    assert c.get("/openfeed/public-key").status_code == 403
    st["admin"] = True
    out = c.get("/openfeed/public-key").json()
    assert out["kid"] == OF.Cfg(db).kid and "d" not in out["jwks"]["keys"][0] and "PRIVATE" not in json.dumps(out)


# ----------------------------------------------------------------------- "invalid_scope - requested scope is not allowed"
def test_invalid_redirect_uri_hint_shows_the_value_AccFino_sends(env):
    db, org, ctx, mock = env
    mock.registered_redirect = "http://localhost:8001/open-banking/openfeed/callback"              # registered with 'localhost', AccFino sends 127.0.0.1 / its APP_URL
    out = OF.diagnose(db, "http://x")
    assert "invalid_redirect_uri" in out["message"] and "https://app.accfino.test/open-banking/openfeed/callback" in " ".join(out["hints"])


# ------------------------------------------------------------- "invalid_scope - requested scope is not allowed": say WHICH scope
def test_scope_probe_names_the_banking_scope_when_it_is_not_ticked(env):
    db, org, ctx, mock = env
    mock.registered_scopes = {"openid", "offline_access"}                          # banking not ticked in the dashboard
    out = OF.diagnose(db, "http://x")
    assert out["ok"] is False and "invalid_scope" in out["message"]
    assert out["scope_check"] == [{"scope": "openid", "ok": True}, {"scope": "offline_access", "ok": True}, {"scope": "openfeed-au:data:banking:read", "ok": False}]
    text = " ".join(out["hints"]); assert "Banking accounts and transactions" in text and "Save changes" in text and "Energy" in text


def test_scope_probe_when_openid_itself_is_refused(env):
    db, org, ctx, mock = env
    mock.registered_scopes = {"openfeed-au:data:banking:read"}
    out = OF.diagnose(db, "http://x")
    assert out["scope_check"][0] == {"scope": "openid", "ok": False} and all(x["ok"] is None for x in out["scope_check"][1:])      # the rest cannot be judged
    assert "not tick-boxes" in " ".join(out["hints"]) and "openid" in " ".join(out["hints"])


def test_scope_probe_leaves_nothing_behind_and_a_correct_setup_is_still_clean(env):
    db, org, ctx, mock = env
    n_flows = db.query(OF.OpenFeedFlow).count()
    out = OF.diagnose(db, "http://x")
    assert out["ok"] is True and "scope_check" not in out and db.query(OF.OpenFeedFlow).count() == n_flows == 0                   # throw-away requests create no flow, no connection


def test_status_tells_the_dashboard_only_one_scope_is_a_tick_box(env):
    db, org, ctx, mock = env
    c, st = http_client(db, org, ctx, admin=True)
    s = c.get("/openfeed/status").json()
    assert s["dashboardScopes"] == ["openfeed-au:data:banking:read"] and s["scopes"] == ["openid", "offline_access", "openfeed-au:data:banking:read"]


# ---------------------------------------- banking scope "not allowed" although it is ticked: is it the redirect address, or the wrong app?
def test_banking_scope_refused_only_for_127_0_0_1_is_diagnosed_as_a_redirect_problem(env, monkeypatch):
    db, org, ctx, mock = env
    monkeypatch.delenv("APP_URL", raising=False)                                   # local test: AccFino sends http://127.0.0.1:8001/...
    mock.data_scope_needs_localhost = True
    out = OF.diagnose(db, "http://127.0.0.1:8001/")
    assert out["ok"] is False and "invalid_scope" in out["message"]
    assert out["redirect_check"][:2] == [{"redirect_uri": "http://127.0.0.1:8001/open-banking/openfeed/callback", "ok": False},
                                         {"redirect_uri": "http://localhost:8001/open-banking/openfeed/callback", "ok": True}]
    assert out["redirect_check"][2]["redirect_uri"].startswith("https://") and out["redirect_check"][2]["ok"] is True                  # the https probe is always included
    text = " ".join(out["hints"]); assert "http://localhost:8001" in text and "APP_URL" in text and "tick" not in text.lower()        # does not wrongly tell them to tick again


def test_banking_scope_really_not_enabled_tells_them_to_compare_the_client_id_and_reload(env):
    db, org, ctx, mock = env
    mock.registered_scopes = {"openid", "offline_access"}
    out = OF.diagnose(db, "http://x")
    text = " ".join(out["hints"])
    assert out["client_id"] == "app-123" and out["kid"] == OF.Cfg(db).kid
    assert "Client ID app-123" in text and "second app" in text and "Reload the app page" in text


def test_every_test_result_says_which_client_id_it_used(env):
    db, org, ctx, mock = env
    ok = OF.diagnose(db, "http://x")
    assert ok["ok"] and ok["client_id"] == "app-123"


# ---------------------------------------------------------------------------- grant management (create / replace), per OpenFeed's guide
def test_a_first_connect_asks_for_a_new_grant_and_a_reconnect_replaces_the_existing_one(env):
    db, org, ctx, mock = env
    par, nxt, state = go_through_openfeed(db, org, ctx, mock)
    assert par["grant_management_action"] == "create" and "grant_id" not in par
    mock.user_approves("grant-1")
    OF.handle_consent_return(db, state, {"grantId": "grant-1", "consented": "true"}); db.commit()
    url = OF.start_connect(db, org.id, ctx.user_id, "http://x", "/settings/open-banking"); db.commit()                    # "Change shared accounts"
    again = mock.pars[parse_qs(urlparse(url).query)["request_uri"][0]]
    assert again["grant_management_action"] == "replace" and again["grant_id"] == "grant-1"


def test_banking_scope_that_needs_the_grant_parameter_works_because_we_send_it(env):
    db, org, ctx, mock = env
    mock.data_scope_requires_grant_mgmt = True
    assert OF.diagnose(db, "http://x")["ok"] is True
    par, nxt, state = go_through_openfeed(db, org, ctx, mock)                                                            # the real flow too
    assert nxt.startswith(CONSENT)


def test_if_openfeed_refuses_the_grant_parameter_the_test_says_so_and_the_switch_fixes_it(env, monkeypatch):
    db, org, ctx, mock = env
    mock.data_scope_rejects_grant_mgmt = True
    out = OF.diagnose(db, "http://x")
    assert out["ok"] is False and "OPENFEED_GRANT_MANAGEMENT=0" in " ".join(out["hints"])
    monkeypatch.setenv("OPENFEED_GRANT_MANAGEMENT", "0")
    assert OF.diagnose(db, "http://x")["ok"] is True
    par, nxt, state = go_through_openfeed(db, org, ctx, mock)
    assert "grant_management_action" not in par


# ----------------------------------------------- every local variant fails: https probe, and the "it is OpenFeed's side" conclusion
def test_banking_scope_that_needs_an_https_redirect_is_diagnosed_with_the_tunnel_advice(env, monkeypatch):
    db, org, ctx, mock = env
    monkeypatch.delenv("APP_URL", raising=False); mock.data_scope_needs_https = True
    out = OF.diagnose(db, "http://127.0.0.1:8001/")
    assert [(x["redirect_uri"].split("/open")[0], x["ok"]) for x in out["redirect_check"]] == [("http://127.0.0.1:8001", False), ("http://localhost:8001", False), ("https://www.accfino.com", True)]
    text = " ".join(out["hints"]); assert "only with an https redirect" in text and "tunnel" in text and "APP_URL" in text


def test_when_nothing_on_our_side_explains_it_the_test_says_to_ask_openfeed(env, monkeypatch):
    db, org, ctx, mock = env
    monkeypatch.delenv("APP_URL", raising=False); mock.registered_scopes = {"openid", "offline_access"}                   # OpenFeed refuses banking whatever we send
    out = OF.diagnose(db, "http://127.0.0.1:8001/")
    assert all(x["ok"] is False for x in out["redirect_check"])
    text = " ".join(out["hints"]); assert "OpenFeed itself is refusing the banking scope" in text and "discord" in text.lower() and out["client_id"] == "app-123"


# ------------------------------------------------------ other ways OpenFeed might want the banking scope presented (resource indicator, no openid)
def test_banking_scope_that_needs_the_resource_named_is_found_and_the_switch_fixes_it(env, monkeypatch):
    db, org, ctx, mock = env
    mock.data_scope_needs_resource = True
    out = OF.diagnose(db, "http://x")
    assert out["ok"] is False and {v["key"]: v["ok"] for v in out["variant_check"]} == {"resource": True, "no_openid": False}
    assert "OPENFEED_SEND_RESOURCE=1" in " ".join(out["hints"]) and "redirect_check" not in out                              # no need to go on to redirects
    monkeypatch.setenv("OPENFEED_SEND_RESOURCE", "1")
    assert OF.diagnose(db, "http://x")["ok"] is True
    par, nxt, state = go_through_openfeed(db, org, ctx, mock)                                                               # the real flow names it too, in PAR and token calls
    assert par["resource"] == "https://api.openfeed.au" and nxt.startswith(CONSENT)


def test_banking_scope_that_only_works_without_openid_is_reported(env):
    db, org, ctx, mock = env
    mock.data_scope_only_without_openid = True
    out = OF.diagnose(db, "http://x")
    assert {v["key"]: v["ok"] for v in out["variant_check"]} == {"resource": False, "no_openid": True} and "WITHOUT 'openid'" in " ".join(out["hints"])


def test_resource_is_not_sent_unless_asked(env):
    db, org, ctx, mock = env
    par, nxt, state = go_through_openfeed(db, org, ctx, mock)
    assert "resource" not in par



# ------------------------------------------------------------------------------------------------- the connect flow in a pop-up window
def test_popup_return_is_encoded_safely_and_hostile_origins_fall_back_to_a_normal_page():
    assert OF.encode_return("/settings/open-banking", "http://localhost:3000") == "popup|http://localhost:3000|/settings/open-banking"
    assert OF.split_return("popup|https://www.accfino.com|/settings/open-banking") == ("https://www.accfino.com", "/settings/open-banking")
    for bad in ("javascript:alert(1)", "http://x/evil", "ftp://x", "http://a b", "https://x.com/path"):
        assert OF.encode_return("/settings/open-banking", bad) == "/settings/open-banking"                    # not a plain origin -> ordinary full-page flow
    assert OF.encode_return("//evil.example", "http://localhost:3000") == "popup|http://localhost:3000|/settings/open-banking"   # never off-site
    assert OF.split_return("popup|javascript:x|//evil") == (None, "/settings/open-banking")


def test_popup_flow_ends_on_the_self_closing_done_page_for_every_outcome(env):
    from urllib.parse import parse_qs, urlparse
    db, org, ctx, mock = env
    rt = OF.encode_return("/settings/open-banking", "http://localhost:3000")
    url = OF.start_connect(db, org.id, ctx.user_id, "http://x", rt); db.commit()
    par = mock.pars[parse_qs(urlparse(url).query)["request_uri"][0]]; mock.codes["c"] = par
    nxt, state = OF.handle_callback(db, {"code": "c", "state": par["state"], "iss": ISS}); db.commit()
    assert nxt.startswith(CONSENT)                                                                                   # the consent screen shows in the pop-up
    mock.user_approves("grant-1")
    back = OF.handle_consent_return(db, state, {"grantId": "grant-1", "consented": "true"}); db.commit()
    q = parse_qs(urlparse(back).query)
    assert urlparse(back).path == "/open-banking/openfeed/done" and q["result"] == ["connected"] and q["origin"] == ["http://localhost:3000"] and q["to"] == ["/settings/open-banking"]
    # declined at the share screen
    url = OF.start_connect(db, org.id, ctx.user_id, "http://x", rt); db.commit()
    par = mock.pars[parse_qs(urlparse(url).query)["request_uri"][-1]]
    mock.codes["c2"] = par; mock.grant = None
    nxt, state = OF.handle_callback(db, {"code": "c2", "state": par["state"], "iss": ISS}); db.commit()
    assert "result=declined" in OF.handle_consent_return(db, state, {"consented": "false"}) and "origin=http" in OF.handle_consent_return.__globals__["done_url"](rt, "declined")
    # declined at OpenFeed's sign-in itself, and a failed attempt: both still end on the done page (not on a blank pop-up)
    url = OF.start_connect(db, org.id, ctx.user_id, "http://x", rt); db.commit()
    par = mock.pars[parse_qs(urlparse(url).query)["request_uri"][-1]]
    assert OF.handle_callback(db, {"error": "access_denied", "state": par["state"]})[0].startswith("/open-banking/openfeed/done?result=declined")
    assert OF.flow_return_to(db, par["state"]) == rt and OF.done_url(rt, "error", "flow_expired").startswith("/open-banking/openfeed/done?result=error") and "reason=flow_expired" in OF.done_url(rt, "error", "flow_expired")


def test_full_page_mode_is_unchanged_when_no_popup_origin_is_given(env):
    db, org, ctx, mock = env
    assert OF.done_url("/settings/open-banking", "connected") == "/settings/open-banking?openfeed=connected"
    assert OF.done_url(None, "error", "token_failed") == "/settings/open-banking?openfeed=error&reason=token_failed"


def test_http_connect_accepts_the_popup_origin_and_the_done_page_is_public_and_inert(env):
    db, org, ctx, mock = env
    c, st = http_client(db, org, ctx)
    r = c.post("/org/current/open-banking/connect", json={"return_to": "/settings/open-banking", "popup_origin": "http://localhost:3000"})
    assert r.status_code == 200 and db.query(OF.OpenFeedFlow).one().return_to == "popup|http://localhost:3000|/settings/open-banking"
    db.query(OF.OpenFeedFlow).delete(); db.commit()
    c.post("/org/current/open-banking/connect", json={"popup_origin": "javascript:alert(1)"})
    assert db.query(OF.OpenFeedFlow).one().return_to == "/settings/open-banking"                                   # hostile value ignored
    page = c.get("/open-banking/openfeed/done?result=connected&origin=http%3A%2F%2Flocalhost%3A3000")
    assert page.status_code == 200 and "text/html" in page.headers["content-type"] and page.headers["cache-control"] == "no-store"
    assert "accfino-openfeed" in page.text and "postMessage" in page.text and "BroadcastChannel" in page.text and "window.close" in page.text
    assert "token" not in page.text.lower().replace("accfino-openfeed", "") and "grant" not in page.text.lower()   # nothing sensitive in it
    from accfino_core.security.middleware import PUBLIC_ROUTES
    assert "/open-banking/openfeed/done" in PUBLIC_ROUTES


def test_http_a_failure_inside_the_popup_also_lands_on_the_done_page(env):
    db, org, ctx, mock = env
    c, st = http_client(db, org, ctx)
    c.post("/org/current/open-banking/connect", json={"popup_origin": "http://localhost:3000"})
    flow = db.query(OF.OpenFeedFlow).one()
    r = c.get("/open-banking/openfeed/callback", params={"code": "bad-code", "state": flow.state, "iss": "https://evil.example"})
    assert r.status_code == 303 and r.headers["location"].startswith("/open-banking/openfeed/done?result=error") and "reason=issuer_mismatch" in r.headers["location"]


# ---------------------------------------------------------------------------------------- several accounts, several banks, one switch each
THREE = [{"accountId": "acc1", "displayName": "ANZ One Offset", "maskedNumber": "xxxx1912", "providerName": "ANZ"},
         {"accountId": "acc2", "displayName": "ANZ Business Saver", "maskedNumber": "xxxx7788", "providerName": "ANZ"},
         {"accountId": "acc3", "displayName": "Everyday Account", "maskedNumber": "xxxx4455", "providerName": "Commonwealth Bank"}]


def connected(env, accounts=None):
    db, org, ctx, mock = env
    if accounts: mock.accounts = accounts
    par, nxt, state = go_through_openfeed(db, org, ctx, mock); mock.user_approves("grant-1")
    OF.handle_consent_return(db, state, {"grantId": "grant-1", "consented": "true"}); db.commit()
    return db, org, ctx, mock


def test_every_shared_account_from_every_bank_is_listed_with_counts(env):
    db, org, ctx, mock = connected(env, THREE)
    st = OF.status(db, org.id)
    assert [a["id"] for a in st["accounts"]] == ["acc1", "acc2", "acc3"] and st["bank_count"] == 2 and all(a["enabled"] for a in st["accounts"])
    assert [a["id"] for a in OF.org_accounts(db, org.id)] == ["acc1", "acc2", "acc3"]                                      # all offered for reconciliation


def test_switching_one_account_off_leaves_the_others_and_the_connection_alone(env):
    db, org, ctx, mock = connected(env, THREE)
    out = OF.set_account_enabled(db, org.id, "acc2", False); db.commit()
    assert [(a["id"], a["enabled"]) for a in out["accounts"]] == [("acc1", True), ("acc2", False), ("acc3", True)] and out["status"] == "active"
    assert [a["id"] for a in OF.org_accounts(db, org.id)] == ["acc1", "acc3"]                                              # gone from reconciliation
    assert len(OF.pull_rows(db, org.id, "acc1", date(2026, 9, 1), date(2026, 9, 30))) == 2                                  # the others still pull
    with pytest.raises(OF.OpenFeedError) as e: OF.pull_rows(db, org.id, "acc2", date(2026, 9, 1), date(2026, 9, 30))
    assert e.value.code == "account_off" and "switched off" in e.value.message
    with pytest.raises(OF.OpenFeedError) as e: OF.set_account_enabled(db, org.id, "nope", False)
    assert e.value.code == "unknown_account"
    OF.set_account_enabled(db, org.id, "acc2", True); db.commit()
    assert len(OF.org_accounts(db, org.id)) == 3


def test_a_switched_off_account_stays_off_after_a_refresh_and_new_accounts_start_on(env):
    db, org, ctx, mock = connected(env, THREE)
    OF.set_account_enabled(db, org.id, "acc3", False); db.commit()
    mock.accounts = THREE + [{"accountId": "acc4", "displayName": "NAB Cheque", "maskedNumber": "xxxx9", "providerName": "NAB"}]       # the person added a third bank at OpenFeed
    st = OF.sync(db, org.id, force=True); db.commit()
    assert {a["id"]: a["enabled"] for a in st["accounts"]} == {"acc1": True, "acc2": True, "acc3": False, "acc4": True} and st["bank_count"] == 3
    mock.accounts = THREE[:2]                                                                                               # ...and later un-ticked one on OpenFeed's screen
    st = OF.sync(db, org.id, force=True); db.commit()
    assert [a["id"] for a in st["accounts"]] == ["acc1", "acc2"]


def test_cancelling_add_or_remove_accounts_does_not_switch_a_live_feed_off(env):
    """Used to flip the connection to 'pending': reconciliation then lost every account until the person reconnected."""
    db, org, ctx, mock = connected(env, THREE)
    OF.start_connect(db, org.id, ctx.user_id, "http://x", "/settings/open-banking"); db.commit()                             # opens the window ... and it is closed again
    assert OF.status(db, org.id)["status"] == "active" and len(OF.org_accounts(db, org.id)) == 3


def test_legacy_rows_without_the_flag_count_as_on(env):
    db, org, ctx, mock = connected(env, THREE)
    conn = db.get(OF.OpenFeedConnection, org.id)
    conn.accounts_json = json.dumps([{"id": "acc1", "name": "Old", "masked": "x", "provider": "ANZ"}]); db.commit()            # saved by an older release
    assert OF.status(db, org.id)["accounts"][0]["enabled"] is True and [a["id"] for a in OF.org_accounts(db, org.id)] == ["acc1"]


def test_http_per_account_switch_is_organisation_admin_only(env):
    db, org, ctx, mock = connected(env, THREE)
    c, st = http_client(db, org, ctx, role="accountant")
    assert c.post("/org/current/open-banking/account", json={"account_id": "acc1", "enabled": False}).status_code == 403
    st["role"] = "owner"
    out = c.post("/org/current/open-banking/account", json={"account_id": "acc1", "enabled": False}).json()
    assert out["accounts"][0]["enabled"] is False and out["status"] == "active"
    assert c.post("/org/current/open-banking/account", json={"account_id": "zzz", "enabled": True}).status_code == 404
    assert [a["id"] for a in c.get("/org/current/open-banking").json()["accounts"] if a["enabled"]] == ["acc2", "acc3"]


# ------------------------------------------------------------------------------------------------ the plan's "Open banking" function
def test_a_plan_without_open_banking_cannot_connect_and_the_status_says_why(env):
    from accfino_core.subscription import service as S
    from accfino_core.subscription.models import OrgSubscription, Plan
    db, org, ctx, mock = env
    S.ensure_catalogue(db); db.query(OrgSubscription).delete(); db.add(OrgSubscription(org_id=org.id, plan_id="essential", status="active")); db.commit()
    c, st = http_client(db, org, ctx)
    assert c.get("/org/current/open-banking").json()["plan_allows"] is True                                          # included by default
    assert c.post("/org/current/open-banking/connect").status_code == 200
    db.get(Plan, "essential").modules = json.dumps(["domain:accounting"]); db.commit()                                 # an administrator switches the function off for the plan
    s = c.get("/org/current/open-banking").json()
    assert s["plan_allows"] is False and s["plan_name"] == "Essential"
    for call in (lambda: c.post("/org/current/open-banking/connect"), lambda: c.post("/org/current/open-banking/sync"), lambda: c.post("/org/current/open-banking/disconnect"),
                 lambda: c.post("/org/current/open-banking/account", json={"account_id": "a", "enabled": False}),
                 lambda: c.post("/org/current/open-banking/pull", json={"account_id": "a", "from_date": "2026-09-01", "to_date": "2026-09-30"})):
        r = call(); assert r.status_code == 402 and "Open banking" in r.json()["detail"]
    st["admin"] = True                                                                                                # platform administrators are never blocked
    assert c.get("/org/current/open-banking").json()["plan_allows"] is True
