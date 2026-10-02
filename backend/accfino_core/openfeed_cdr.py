"""OpenFeed (Biza) CDR connector - AccFino registers ONE app with OpenFeed; every organisation then connects its own bank accounts through it.

What the organisation does (once): Organisation Admin clicks "Connect my bank" in AccFino -> OpenFeed sign-in (email code, created on first use) ->
bank login at the bank (CDR consent, cannot be skipped: only the account holder can authorise it) -> OpenFeed "share with AccFino" screen -> back in AccFino.
What AccFino does after that, with no further action: keeps the refresh token (encrypted), pulls accounts and transactions on demand / on a schedule.

Protocol (docs: openfeed.au/llms-full.txt, Sharing API v4): OAuth 2.0 FAPI 2.0 profile - PAR (mandatory), PKCE S256, private_key_jwt client authentication
(PS256), DPoP-bound access tokens (PS256), `resource=https://api.openfeed.au`; the disclosure grant id comes back in `authorization_details[0].grant_id`.

Everything here is server-side; tokens and keys never reach the browser. Network access goes through `_client()` so tests can swap in a mock OpenFeed.
"""
import base64
import hashlib
import json
import logging
import os
import secrets
import time
import uuid
from datetime import date, datetime, timedelta
from typing import Optional
from urllib.parse import urlencode, urlparse

import httpx
import jwt
from cryptography.fernet import Fernet, InvalidToken
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from sqlalchemy import Column, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Session

from accfino_core import models as m
from accfino_core.models import Base

log = logging.getLogger("accfino.openfeed")

DEFAULT_ISSUER = "https://auth.openfeed.au"
DEFAULT_API = "https://api.openfeed.au"
DEFAULT_CONSENT = "https://app.openfeed.au"
DATA_SCOPE = "openfeed-au:data:banking:read"          # the ONLY scope that is a tick-box in the OpenFeed dashboard
SCOPE = "openid offline_access " + DATA_SCOPE      # exactly the scopes enabled on the registered app; anything else fails with invalid_scope
FLOW_MINUTES = 15
SYNC_MIN_GAP = timedelta(minutes=10)               # OpenFeed batch-refreshes banking every 4 hours: asking more often just wastes calls


# ------------------------------------------------------------------------------------------------------------------ tables --
class OpenFeedFlow(Base):
    """One in-progress "Connect my bank" attempt. Single use; ties the browser coming back from OpenFeed to the organisation that started it."""
    __tablename__ = "openfeed_flows"
    state = Column(String(64), primary_key=True)
    org_id = Column(Integer, ForeignKey("organisations.id", ondelete="CASCADE"), nullable=False, index=True)
    user_id = Column(Integer, nullable=False)
    code_verifier = Column(String(128), nullable=False)
    nonce = Column(String(64), nullable=False)
    redirect_uri = Column(String(500), nullable=False)
    return_to = Column(String(300), nullable=True)                      # where to send the browser in AccFino when done
    phase = Column(String(20), nullable=False, default="started")      # started -> awaiting_consent -> done
    expires_at = Column(DateTime, nullable=False)


class OpenFeedConnection(Base):
    """An organisation's live bank feed. One row per organisation; the refresh token is encrypted."""
    __tablename__ = "openfeed_connections"
    org_id = Column(Integer, ForeignKey("organisations.id", ondelete="CASCADE"), primary_key=True)
    status = Column(String(24), nullable=False, default="pending")     # pending | active | reconnect_required | paused | revoked
    grant_id = Column(String(64), nullable=True)
    refresh_token_enc = Column(Text, nullable=True)
    openfeed_sub = Column(String(64), nullable=True)
    accounts_json = Column(Text, nullable=False, default="[]")         # cached: [{id, name, masked, provider}]
    last_sync_at = Column(DateTime, nullable=True)
    last_error = Column(String(300), nullable=True)
    connected_by = Column(Integer, nullable=True)
    connected_at = Column(DateTime, nullable=True)


OPENFEED_TABLES = [OpenFeedFlow.__table__, OpenFeedConnection.__table__]


class OpenFeedError(Exception):
    """Something the user can act on. `code` is stable for the UI/tests."""
    def __init__(self, code: str, message: str, status: int = 400, detail: str = ""):
        super().__init__(message)
        self.code, self.message, self.status, self.detail = code, message, status, detail      # detail = OpenFeed's own words; for the administrator, never for clients


# ------------------------------------------------------------------------------------------------------- secrets at rest --
def _fernet() -> Fernet:
    raw = os.environ.get("FIELD_ENCRYPTION_KEY", "").strip()
    if raw:
        key = raw.encode()
    else:                                                               # derived from the app secret: stable across restarts, never stored
        from accfino_core.security import tokens
        key = base64.urlsafe_b64encode(hashlib.sha256(("openfeed|" + tokens._secret()).encode()).digest())
    return Fernet(key)


def seal(text: str) -> str:
    return _fernet().encrypt(text.encode()).decode()


def unseal(blob: str) -> Optional[str]:
    try:
        return _fernet().decrypt(blob.encode()).decode()
    except (InvalidToken, ValueError, AttributeError):
        return None


# ------------------------------------------------------------------------------------------------- platform configuration --
def _setting(db: Session, key: str) -> str:
    row = db.get(m.SystemSetting, key)
    return (row.value or "").strip() if row else ""


def _put_setting(db: Session, key: str, value: str):
    row = db.get(m.SystemSetting, key)
    if row is None:
        db.add(m.SystemSetting(key=key, value=value))
    else:
        row.value = value
    db.flush()


class Cfg:
    """The platform's single OpenFeed app registration (env vars win over the Admin screen)."""
    def __init__(self, db: Session):
        e = os.environ.get
        self.client_id = e("OPENFEED_CLIENT_ID", "").strip() or _setting(db, "openfeed.client_id")      # app-<uuid>
        self.app_id = e("OPENFEED_APP_ID", "").strip() or _setting(db, "openfeed.app_id")                 # bare uuid (consent deep-link only)
        self.app_key = e("OPENFEED_APP_PRIVATE_KEY", "").strip() or (unseal(_setting(db, "openfeed.app_key")) or "")
        self.dpop_key = e("OPENFEED_DPOP_PRIVATE_KEY", "").strip() or (unseal(_setting(db, "openfeed.dpop_key")) or "")
        self.kid = e("OPENFEED_APP_KEY_ID", "").strip() or _setting(db, "openfeed.kid")
        self.send_resource = e("OPENFEED_SEND_RESOURCE", "0").strip() == "1"            # name the resource (RFC 8707) in the PAR and token requests; off unless the Test says OpenFeed needs it
        self.grant_mgmt = e("OPENFEED_GRANT_MANAGEMENT", "1").strip() != "0"          # send grant_management_action as OpenFeed recommends; set 0 only if OpenFeed refuses it                    # "kid" of the key set registered at OpenFeed
        self.issuer = e("OPENFEED_ISSUER", DEFAULT_ISSUER).rstrip("/")
        self.api = e("OPENFEED_API_BASE", DEFAULT_API).rstrip("/")
        self.consent = e("OPENFEED_CONSENT_BASE", DEFAULT_CONSENT).rstrip("/")

    @property
    def ready(self) -> bool:
        return bool(self.client_id and self.app_id and self.app_key and self.dpop_key and self.kid)

    def missing(self) -> list:
        return [n for n, v in (("OpenFeed app (client id)", self.client_id), ("OpenFeed app id", self.app_id), ("app signing key", self.app_key), ("DPoP key", self.dpop_key), ("key id (regenerate the keys)", self.kid)) if not v]


def generate_platform_keys(db: Session) -> dict:
    """Admin, once: make the two PS256/RSA keypairs. The private keys are stored encrypted; ONLY the public key set (for the OpenFeed dashboard) is returned."""
    def pem_pair():
        k = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        pem = k.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()).decode()
        return k, pem
    app_k, app_pem = pem_pair()
    _, dpop_pem = pem_pair()
    _put_setting(db, "openfeed.app_key", seal(app_pem))
    _put_setting(db, "openfeed.dpop_key", seal(dpop_pem))
    jwk = jwt.algorithms.RSAAlgorithm.to_jwk(app_k.public_key(), as_dict=True)
    kid = "accfino-" + secrets.token_hex(4)
    jwk.update({"use": "sig", "alg": "PS256", "kid": kid})
    _put_setting(db, "openfeed.kid", kid)                                                  # the client assertion must carry exactly this kid
    return {"keys": [jwk]}


def public_jwks(db: Session) -> Optional[dict]:
    """The PUBLIC key set for the OpenFeed dashboard, derived from the stored private key. Lets the administrator copy it again without regenerating."""
    cfg = Cfg(db)
    if not (cfg.app_key and cfg.kid):
        return None
    key = serialization.load_pem_private_key(cfg.app_key.encode(), password=None)
    jwk = jwt.algorithms.RSAAlgorithm.to_jwk(key.public_key(), as_dict=True)
    jwk.update({"use": "sig", "alg": "PS256", "kid": cfg.kid})
    return {"keys": [jwk]}


def thumbprint(jwk: dict) -> str:
    """RFC 7638 fingerprint: lets the administrator compare the key AccFino signs with against what is registered."""
    canon = json.dumps({"e": jwk["e"], "kty": jwk["kty"], "n": jwk["n"]}, separators=(",", ":"), sort_keys=True)
    return b64u(hashlib.sha256(canon.encode()).digest())


def save_platform_ids(db: Session, client_id: str, app_id: str):
    _put_setting(db, "openfeed.client_id", (client_id or "").strip())
    _put_setting(db, "openfeed.app_id", (app_id or "").strip())


# --------------------------------------------------------------------------------------------------------- HTTP plumbing --
_transport = None            # tests set an httpx.MockTransport here
_discovery_cache: dict = {}
_nonces: dict = {}           # DPoP-Nonce per host (RFC 9449 §8)


def _client() -> httpx.Client:
    return httpx.Client(timeout=20, transport=_transport, follow_redirects=False)


def b64u(b: bytes) -> str:
    return base64.urlsafe_b64encode(b).rstrip(b"=").decode()


def discovery(cfg: Cfg) -> dict:
    d = _discovery_cache.get(cfg.issuer)
    if d:
        return d
    with _client() as c:
        r = c.get(cfg.issuer + "/.well-known/openid-configuration")
    if r.status_code != 200:
        raise OpenFeedError("openfeed_unreachable", "Could not reach OpenFeed. Try again shortly.", 503)
    _discovery_cache[cfg.issuer] = r.json()
    return _discovery_cache[cfg.issuer]


def client_assertion(cfg: Cfg) -> str:
    """private_key_jwt: iss = sub = client id, aud = the ISSUER (not the endpoint URL), a fresh jti every time, never reused."""
    now = int(time.time())                                  # NOT datetime.utcnow().timestamp(): that is shifted by the server's time zone (10 hours in Sydney) and OpenFeed rejects it
    return jwt.encode({"iss": cfg.client_id, "sub": cfg.client_id, "aud": cfg.issuer, "jti": str(uuid.uuid4()), "iat": now, "exp": now + 60},
                      cfg.app_key, algorithm="PS256", headers={"kid": cfg.kid} if cfg.kid else None)


def dpop_proof(cfg: Cfg, htu: str, htm: str, access_token: str = None, nonce: str = None) -> str:
    key = serialization.load_pem_private_key(cfg.dpop_key.encode(), password=None)
    jwk = jwt.algorithms.RSAAlgorithm.to_jwk(key.public_key(), as_dict=True)          # PUBLIC key only in the header
    claims = {"htu": htu.split("?")[0].split("#")[0], "htm": htm, "iat": int(time.time()), "jti": str(uuid.uuid4())}
    if access_token:
        claims["ath"] = b64u(hashlib.sha256(access_token.encode()).digest())
    if nonce:
        claims["nonce"] = nonce
    return jwt.encode(claims, cfg.dpop_key, algorithm="PS256", headers={"typ": "dpop+jwt", "jwk": jwk})


def _post_token(cfg: Cfg, form: dict) -> dict:
    """POST to the token endpoint with a DPoP proof; if the server demands a nonce, retry exactly once with it."""
    url = discovery(cfg)["token_endpoint"]
    body = {"client_id": cfg.client_id, "client_assertion_type": "urn:ietf:params:oauth:client-assertion-type:jwt-bearer", **form}
    if cfg.send_resource:
        body["resource"] = cfg.api
    for attempt in (0, 1):
        body["client_assertion"] = client_assertion(cfg)
        with _client() as c:
            r = c.post(url, data=body, headers={"DPoP": dpop_proof(cfg, url, "POST", nonce=_nonces.get(url))})
        if r.status_code == 400 and attempt == 0 and r.headers.get("DPoP-Nonce") and (r.json() or {}).get("error") == "use_dpop_nonce":
            _nonces[url] = r.headers["DPoP-Nonce"]
            continue
        return {"status": r.status_code, "json": (r.json() if r.content else {})}
    return {"status": 400, "json": {}}


class SharingApiError(OpenFeedError):
    pass


def api_get(cfg: Cfg, access_token: str, path_or_url: str, nonce_retry: bool = True) -> Optional[dict]:
    url = path_or_url if path_or_url.startswith("http") else cfg.api + path_or_url
    host = urlparse(url).netloc
    for attempt in (0, 1):
        proof = dpop_proof(cfg, url, "GET", access_token=access_token, nonce=_nonces.get(host))
        with _client() as c:
            r = c.get(url, headers={"Authorization": f"DPoP {access_token}", "DPoP": proof})
        if r.status_code == 400 and attempt == 0 and nonce_retry and r.headers.get("DPoP-Nonce"):
            _nonces[host] = r.headers["DPoP-Nonce"]
            continue
        break
    s = r.status_code
    body = {}
    try:
        body = r.json() if r.content else {}
    except ValueError:
        pass
    if s == 200:
        return body
    if s == 404:
        return None
    code = (body or {}).get("code") or (body or {}).get("error") or ""
    if s == 401:
        raise SharingApiError("token_expired", "The bank connection needs to be renewed.", 401)
    if s == 402:
        raise SharingApiError("credit_exhausted", "Bank data access is paused. Please contact AccFino support.", 402)
    if s == 403 and code == "disclosure_grant_required":
        raise SharingApiError("grant_revoked", "Access to your bank data was withdrawn. Reconnect your bank to continue.", 403)
    if s == 403 and code == "balance_unavailable":
        raise SharingApiError("balance_unavailable", "Balance not available for this account.", 403)
    if s == 429:
        raise SharingApiError("rate_limited", "OpenFeed is busy. Try again in a minute.", 429)
    raise SharingApiError("openfeed_error", f"OpenFeed returned {s}. Try again shortly.", 502)


def fetch_all(cfg: Cfg, access_token: str, path: str) -> list:
    out, url = [], path
    while url:
        page = api_get(cfg, access_token, url)
        if not page:
            break
        d = page.get("data")
        out.extend(d if isinstance(d, list) else ([d] if d else []))
        url = (page.get("links") or {}).get("next")                      # absent on the last page
    return out


# ------------------------------------------------------------------------------------------------------ connect (browser) --
def _public_base(request_base: str) -> str:
    return (os.environ.get("APP_URL", "").strip() or request_base).rstrip("/")


def start_connect(db: Session, org_id: int, user_id: int, request_base: str, return_to: str = "/settings/open-banking") -> str:
    """Organisation Admin pressed 'Connect my bank'. Returns the OpenFeed URL to send the browser to."""
    cfg = Cfg(db)
    if not cfg.ready:
        raise OpenFeedError("not_configured", "Live bank feeds are not switched on for this platform yet. Please contact AccFino support.", 503)
    db.query(OpenFeedFlow).filter(OpenFeedFlow.expires_at < datetime.utcnow()).delete()
    verifier = b64u(secrets.token_bytes(32))
    flow = OpenFeedFlow(state=str(uuid.uuid4()), org_id=org_id, user_id=user_id, code_verifier=verifier, nonce=str(uuid.uuid4()),
                        redirect_uri=_public_base(request_base) + "/open-banking/openfeed/callback", return_to=return_to[:300],
                        expires_at=datetime.utcnow() + timedelta(minutes=FLOW_MINUTES))
    db.add(flow)
    d = discovery(cfg)
    par_url = d["pushed_authorization_request_endpoint"]
    par_form = {"client_assertion_type": "urn:ietf:params:oauth:client-assertion-type:jwt-bearer", "client_assertion": client_assertion(cfg),
                "response_type": "code", "client_id": cfg.client_id, "redirect_uri": flow.redirect_uri, "scope": SCOPE,
                "code_challenge": b64u(hashlib.sha256(verifier.encode()).digest()), "code_challenge_method": "S256", "nonce": flow.nonce, "state": flow.state}
    existing = db.get(OpenFeedConnection, org_id)
    par_form.update(par_extras(cfg, existing.grant_id if existing is not None else None))
    r = _post_par(cfg, par_url, par_form)
    ok = r.status_code in (200, 201) and r.content and r.json().get("request_uri")
    if not ok:
        db.rollback()
        why = _provider_error(r)
        log.error("OpenFeed PAR failed: %s %s", r.status_code, why)
        raise OpenFeedError("par_failed", "OpenFeed did not accept the request. Platform setup may be incomplete - please contact AccFino support.", 502, detail=why)
    conn = db.get(OpenFeedConnection, org_id) or OpenFeedConnection(org_id=org_id)
    if not (conn.grant_id and conn.status in ("active", "paused")):         # adding / removing accounts on a live connection must not switch the feed off if the person cancels half way
        conn.status = "pending"
    conn.connected_by, conn.last_error = user_id, None
    db.merge(conn)
    db.flush()
    return d["authorization_endpoint"] + "?" + urlencode({"client_id": cfg.client_id, "request_uri": r.json()["request_uri"]})


def par_extras(cfg: Cfg, grant_id: Optional[str]) -> dict:
    """Optional PAR parameters beyond the basics: the grant action, and the resource if OPENFEED_SEND_RESOURCE=1."""
    return {**grant_params(cfg, grant_id), **({"resource": cfg.api} if cfg.send_resource else {})}


def grant_params(cfg: Cfg, grant_id: Optional[str]) -> dict:
    """OpenFeed 'Grant management' (OIDF FAPI): a first share is `create`; changing what is shared is `replace` + the existing grant_id. Recommended, not mandatory."""
    out = {"grant_management_action": "replace", "grant_id": grant_id} if grant_id else {"grant_management_action": "create"}
    return out if cfg.grant_mgmt else {}


def _provider_error(r) -> str:
    """OpenFeed's own explanation (error / error_description) for the AccFino administrator."""
    try:
        j = r.json()
        return f"HTTP {r.status_code}: {j.get('error', '')} - {j.get('error_description', '')}".strip(" -")
    except Exception:
        return f"HTTP {r.status_code}: {(r.text or '')[:200]}"


def _clock_skew(r) -> Optional[float]:
    """Seconds this server is BEHIND OpenFeed (negative = ahead), from the HTTP Date header; None if unavailable."""
    try:
        from email.utils import parsedate_to_datetime
        return parsedate_to_datetime(r.headers["Date"]).timestamp() - time.time()
    except Exception:
        return None


def _post_par(cfg: Cfg, url: str, form: dict):
    """PAR needs a DPoP proof as well as the signed client assertion. A server-demanded DPoP nonce is retried once with a FRESH assertion."""
    for attempt in (0, 1):
        form = {**form, "client_assertion": client_assertion(cfg)}
        with _client() as c:
            r = c.post(url, data=form, headers={"DPoP": dpop_proof(cfg, url, "POST", nonce=_nonces.get(url))})
        if r.status_code == 400 and attempt == 0 and r.headers.get("DPoP-Nonce"):
            _nonces[url] = r.headers["DPoP-Nonce"]
            continue
        return r
    return r


def diagnose(db: Session, request_base: str) -> dict:
    """Admin 'Test OpenFeed set-up': discovery + a real PAR with a throw-away request, reporting OpenFeed's exact answer. Creates nothing."""
    cfg = Cfg(db)
    if not cfg.ready:
        return {"ok": False, "step": "setup", "message": "Set-up is incomplete: " + ", ".join(cfg.missing()) + "."}
    try:
        d = discovery(cfg)
    except OpenFeedError as e:
        return {"ok": False, "step": "discovery", "message": e.message}
    par_url = d["pushed_authorization_request_endpoint"]
    redirect = _public_base(request_base) + "/open-banking/openfeed/callback"

    def try_par(scope: str, redirect_uri: Optional[str] = None, extra: Optional[dict] = None):
        verifier = b64u(secrets.token_bytes(32))
        form = {"client_assertion_type": "urn:ietf:params:oauth:client-assertion-type:jwt-bearer", "client_assertion": "", "response_type": "code", "client_id": cfg.client_id,
                "redirect_uri": redirect_uri or redirect, "scope": scope, "code_challenge": b64u(hashlib.sha256(verifier.encode()).digest()), "code_challenge_method": "S256",
                "nonce": str(uuid.uuid4()), "state": str(uuid.uuid4()), **(par_extras(cfg, None) if extra is None else extra)}
        return _post_par(cfg, par_url, form)

    try:
        r = try_par(SCOPE)
    except Exception:
        return {"ok": False, "step": "par", "message": "Could not reach OpenFeed's request endpoint."}
    form = {"redirect_uri": redirect}
    if r.status_code in (200, 201) and r.content and r.json().get("request_uri"):
        return {"ok": True, "step": "par", "message": "OpenFeed accepted AccFino's request. Set-up is correct.", "redirect_uri": form["redirect_uri"], "client_id": cfg.client_id, "kid": cfg.kid}
    out = {"ok": False, "step": "par", "message": _provider_error(r), "redirect_uri": form["redirect_uri"], "scope": SCOPE, "hints": [], "client_id": cfg.client_id, "kid": cfg.kid}
    skew = _clock_skew(r)
    if skew is not None and abs(skew) > 30:
        out["hints"].append(f"This server's clock is {abs(skew):.0f} seconds {'behind' if skew > 0 else 'ahead of'} OpenFeed's. Signed requests are rejected when the clock is out by more than about a minute - fix the server time (NTP).")
    if "invalid_scope" in out["message"]:
        out["scope_check"] = _probe_scopes(try_par)
        bad = [x["scope"] for x in out["scope_check"] if x["ok"] is False]
        for sc in bad:
            if sc == DATA_SCOPE:
                if cfg.grant_mgmt:                                              # is it the grant_management_action parameter that the banking scope objects to?
                    try:
                        r2 = try_par("openid " + DATA_SCOPE, None, {"resource": cfg.api} if cfg.send_resource else {})
                        if r2.status_code in (200, 201) and r2.content and r2.json().get("request_uri"):
                            out["hints"].append("OpenFeed accepts the banking scope WITHOUT the grant_management_action parameter but refuses it with it. Set OPENFEED_GRANT_MANAGEMENT=0 and restart AccFino.")
                            continue
                    except Exception:
                        pass
                out["variant_check"] = _probe_variants(try_par, cfg)
                for v in out["variant_check"]:
                    if v["ok"] and v["key"] == "resource":
                        out["hints"].append("OpenFeed accepts the banking scope when the request names its resource (https://api.openfeed.au). Set OPENFEED_SEND_RESOURCE=1 and restart AccFino.")
                    elif v["ok"] and v["key"] == "no_openid":
                        out["hints"].append("OpenFeed accepts the banking scope only WITHOUT 'openid' in the same request. That needs a two-step sign-in (sign in first, then ask for data) - please send me this result.")
                if any(v["ok"] for v in out["variant_check"]):
                    continue
                out["redirect_check"] = _probe_redirects(try_par, redirect)
                works = [x["redirect_uri"] for x in out["redirect_check"] if x["ok"]]
                if works:                                                       # the scope is fine - it is the redirect ADDRESS the banking scope objects to
                    if works[0].startswith("https://") and not redirect.startswith("https://"):
                        out["hints"].append(f"OpenFeed accepts the banking scope only with an https redirect address (it accepted {works[0]} but not {redirect}). "
                                            "Run AccFino at an https address: your live site, or a tunnel (Cloudflare Tunnel / ngrok) to localhost, then set APP_URL to that https address and restart.")
                    else:
                        out["hints"].append(f"OpenFeed accepts the banking scope with the redirect address {works[0]} but not with {redirect}. Use that address: open AccFino on it and/or set APP_URL to it.")
                    continue
                out["hints"].append("Everything on AccFino's side checks out: the signature, the Client ID, the key, openid and offline_access, the redirect address (http and https) and the grant parameter. "
                                    "OpenFeed itself is refusing the banking scope for this app, so the next step is OpenFeed - post this result in their Discord (discord.gg/jHYEd2MMHk).")
                out["hints"].append("In the OpenFeed dashboard, under 'Requested scopes', tick 'Banking accounts and transactions' (" + DATA_SCOPE + ") and press 'Save changes'. Leave Energy unticked.")
                out["hints"].append(f"If it is ticked already: this test signed in as Client ID {cfg.client_id}. It must be the Client ID of the app you ticked it on - check you have not created a second app. "
                                    "Reload the app page in the dashboard to confirm the tick was really saved (a stale 'App updated successfully' message can stay on screen).")
            else:
                out["hints"].append(f"OpenFeed refuses '{sc}' for this app. 'openid' and 'offline_access' are not tick-boxes in the dashboard - AccFino requests them automatically at every sign-in - "
                                    "so this needs OpenFeed to look at the app's registration (their Discord is the quickest way).")
        if not bad:
            out["hints"].append("Each scope is accepted on its own but OpenFeed refuses them together - please ask OpenFeed about this app's registration.")
    if "invalid_redirect_uri" in out["message"]:
        out["hints"].append("OpenFeed refused the redirect address AccFino sends with each sign-in: " + redirect + ". It is not registered at OpenFeed, but some addresses are refused "
                            "(for example plain http on anything other than localhost). On a live site set APP_URL to your public https address.")
    if "invalid_client" in out["message"]:
        pub = (public_jwks(db) or {"keys": [{}]})["keys"][0]
        fp = thumbprint(pub) if pub.get("n") else "?"
        out["hints"] += [f"OpenFeed could not verify AccFino's signature. The key AccFino signs with has key id {cfg.kid} and fingerprint {fp}.",
                         "In the OpenFeed dashboard the app's public key set must be exactly the one shown by 'Show public key set' below (same key id). If you generated keys again after registering, paste the NEW set into OpenFeed and save.",
                         f"The OAuth2 Client ID must be the one starting with 'app-' (currently {cfg.client_id[:12]}...) - not the App ID.",
                         "The app's authentication method at OpenFeed must be private_key_jwt with the key set pasted in as an inline JWKS."]
    return out


def _probe_variants(try_par, cfg: Cfg) -> list:
    """Two more ways of asking for the banking scope, in case OpenFeed wants it presented differently. Throw-away requests only."""
    def ok(scope, extra):
        try:
            r = try_par(scope, None, extra)
            return r.status_code in (200, 201) and bool(r.content) and bool(r.json().get("request_uri"))
        except Exception:
            return None
    base = par_extras(cfg, None)
    return [{"key": "resource", "label": "banking scope + resource https://api.openfeed.au", "ok": ok("openid " + DATA_SCOPE, {**base, "resource": cfg.api})},
            {"key": "no_openid", "label": "banking scope alone (without openid)", "ok": ok(DATA_SCOPE, base)}]


def _probe_redirects(try_par, current: str) -> list:
    """Is it the banking scope or the redirect ADDRESS that is refused? Try the same request from loopback 'localhost' and from https. Throw-away requests only."""
    from urllib.parse import urlparse
    path = "/open-banking/openfeed/callback"
    u = urlparse(current)
    variants = []
    if u.hostname == "127.0.0.1":
        variants.append(f"{u.scheme}://localhost{':' + str(u.port) if u.port else ''}{path}")
    if u.scheme == "http" and u.hostname not in ("127.0.0.1", "localhost"):
        variants.append(f"https://{u.netloc}{path}")
    if u.scheme != "https":                                                  # FAPI 2.0 apps are normally expected to use https redirect addresses: try one (nothing is contacted; the address is only carried in the request)
        base = os.environ.get("APP_URL", "").strip().rstrip("/")
        variants.append((base if base.startswith("https://") else "https://www.accfino.com") + path)
    out = [{"redirect_uri": current, "ok": False}]
    for v in variants:
        try:
            r = try_par("openid " + DATA_SCOPE, v)
            out.append({"redirect_uri": v, "ok": r.status_code in (200, 201) and bool(r.content) and bool(r.json().get("request_uri"))})
        except Exception:
            out.append({"redirect_uri": v, "ok": None})
    return out


def _probe_scopes(try_par) -> list:
    """Ask for each scope on its own (always with openid, which the others need) so the administrator is told WHICH box to tick. ok=None means 'could not tell'."""
    def accepted(scope: str):
        try:
            r = try_par(scope)
            return r.status_code in (200, 201) and bool(r.content) and bool(r.json().get("request_uri"))
        except Exception:
            return None
    wanted = SCOPE.split()
    if not accepted("openid"):
        return [{"scope": "openid", "ok": False}] + [{"scope": x, "ok": None} for x in wanted if x != "openid"]
    return [{"scope": "openid", "ok": True}] + [{"scope": x, "ok": accepted("openid " + x)} for x in wanted if x != "openid"]


def _flow(db: Session, state: str) -> OpenFeedFlow:
    f = db.get(OpenFeedFlow, state or "")
    if f is None or f.expires_at < datetime.utcnow():
        raise OpenFeedError("flow_expired", "That connection attempt expired. Start again from Settings > Open Banking.", 400)
    return f


def _store_tokens(db: Session, org_id: int, tok: dict):
    conn = db.get(OpenFeedConnection, org_id) or OpenFeedConnection(org_id=org_id)
    if tok.get("refresh_token"):
        conn.refresh_token_enc = seal(tok["refresh_token"])
    gid = ((tok.get("authorization_details") or [{}])[0] or {}).get("grant_id")
    if gid:
        conn.grant_id = gid
    db.merge(conn)
    db.flush()
    return conn, gid


def handle_callback(db: Session, query: dict) -> tuple:
    """Browser is back from OpenFeed sign-in with ?code&state&iss. -> (redirect_url, flow_state_for_cookie)."""
    cfg = Cfg(db)
    if query.get("error"):
        return done_url(flow_return_to(db, query.get("state")), "declined"), None
    flow = _flow(db, query.get("state", ""))
    if query.get("iss") and query["iss"].rstrip("/") != cfg.issuer:                       # RFC 9207 mix-up defence
        raise OpenFeedError("issuer_mismatch", "Unexpected response from OpenFeed.", 400)
    res = _post_token(cfg, {"grant_type": "authorization_code", "code": query.get("code", ""), "code_verifier": flow.code_verifier, "redirect_uri": flow.redirect_uri})
    tok = res["json"]
    if res["status"] != 200 or not tok.get("access_token"):
        log.error("OpenFeed token exchange failed: %s %s", res["status"], str(tok)[:200])
        raise OpenFeedError("token_failed", "OpenFeed sign-in could not be completed. Please try again.", 502)
    if tok.get("id_token"):                                                                # verify before trusting a single claim
        try:
            claims = jwt.decode(tok["id_token"], jwt.PyJWKClient(discovery(cfg)["jwks_uri"]).get_signing_key_from_jwt(tok["id_token"]).key,
                                algorithms=["PS256", "RS256", "ES256"], audience=cfg.client_id, issuer=cfg.issuer)
            if claims.get("nonce") != flow.nonce:
                raise OpenFeedError("nonce_mismatch", "Unexpected response from OpenFeed.", 400)
        except OpenFeedError:
            raise
        except Exception:
            raise OpenFeedError("id_token_invalid", "OpenFeed sign-in could not be verified. Please try again.", 400)
    conn, gid = _store_tokens(db, flow.org_id, tok)
    if gid:                                                                                  # already shared before: nothing more to approve
        conn.status = "active"
        flow.phase = "done"
        return done_url(flow.return_to, "connected"), flow.state
    flow.phase = "awaiting_consent"                                                        # first time: pick the accounts to share with AccFino
    return cfg.consent + "/grants/disclosure?" + urlencode({"appId": cfg.app_id, "redirectUri": _public_base_from(flow.redirect_uri) + "/open-banking/openfeed/consent-return"}), flow.state


def _public_base_from(redirect_uri: str) -> str:
    p = urlparse(redirect_uri)
    return f"{p.scheme}://{p.netloc}"


POPUP_PREFIX = "popup|"
_ORIGIN_RE = __import__("re").compile(r"^https?://[A-Za-z0-9.\-\[\]:]+$")


def encode_return(path: str, popup_origin: Optional[str] = None) -> str:
    """Where to go when the flow ends. With popup_origin the flow runs in a pop-up window and ends on a small 'done' page that tells the opener and closes itself."""
    path = path if (path or "").startswith("/") and not (path or "").startswith("//") else "/settings/open-banking"
    if popup_origin and _ORIGIN_RE.match(popup_origin):
        return f"{POPUP_PREFIX}{popup_origin.rstrip('/')}|{path}"
    return path


def split_return(return_to: Optional[str]) -> tuple:
    """-> (popup_origin or None, path)"""
    rt = return_to or "/settings/open-banking"
    if rt.startswith(POPUP_PREFIX):
        _, origin, path = (rt.split("|", 2) + ["/settings/open-banking"])[:3]
        return (origin if _ORIGIN_RE.match(origin or "") else None), (path if path.startswith("/") and not path.startswith("//") else "/settings/open-banking")
    return None, (rt if rt.startswith("/") and not rt.startswith("//") else "/settings/open-banking")


def done_url(return_to: Optional[str], result: str, reason: Optional[str] = None) -> str:
    """Where the browser goes when the flow is over: back to the Settings page (full-page mode) or to the self-closing 'done' page (pop-up mode)."""
    origin, path = split_return(return_to)
    if origin:
        return "/open-banking/openfeed/done?" + urlencode({"result": result, "origin": origin, "to": path, **({"reason": reason} if reason else {})})
    return query_return(path, result) + (f"&reason={reason}" if reason else "")


def flow_return_to(db: Session, state: Optional[str]) -> Optional[str]:
    f = db.get(OpenFeedFlow, state or "") if state else None
    return f.return_to if f is not None else None


def query_return(path: str, result: str) -> str:
    return path + ("&" if "?" in path else "?") + "openfeed=" + result


def handle_consent_return(db: Session, flow_state: str, query: dict) -> str:
    """Browser is back from the 'share with AccFino' screen (?grantId&consented). Uses the cookie that links it to the flow."""
    flow = _flow(db, flow_state)
    back = flow.return_to
    if flow.phase != "awaiting_consent":
        raise OpenFeedError("flow_state", "That connection attempt is not waiting for approval.", 400)
    if query.get("consented") != "true":
        conn = db.get(OpenFeedConnection, flow.org_id)
        if conn is not None and not conn.grant_id:
            conn.status = "pending"
        db.delete(flow)
        return done_url(back, "declined")
    cfg = Cfg(db)
    conn = db.get(OpenFeedConnection, flow.org_id)
    rt = unseal(conn.refresh_token_enc) if conn and conn.refresh_token_enc else None
    if not rt:
        raise OpenFeedError("no_session", "The connection attempt lost its session. Start again.", 400)
    res = _post_token(cfg, {"grant_type": "refresh_token", "refresh_token": rt})
    tok = res["json"]
    gid = ((tok.get("authorization_details") or [{}])[0] or {}).get("grant_id")
    if res["status"] != 200 or not gid:
        raise OpenFeedError("grant_not_bound", "OpenFeed did not confirm the share. Please try again.", 502)
    if query.get("grantId") and query["grantId"] != gid:                                   # token must be bound to the grant just approved
        raise OpenFeedError("grant_mismatch", "OpenFeed returned an unexpected grant. Please try again.", 400)
    _store_tokens(db, flow.org_id, tok)
    conn.status, conn.connected_at, conn.last_error = "active", datetime.utcnow(), None
    db.delete(flow)
    try:                                                                                   # first pull straight away so the accounts show immediately
        sync(db, flow.org_id, force=True, access_token=tok["access_token"])
    except OpenFeedError as e:
        log.warning("first OpenFeed sync failed for org %s: %s", flow.org_id, e.code)
    return done_url(back, "connected")


# ------------------------------------------------------------------------------------------------------ unattended access --
def _access_token(db: Session, cfg: Cfg, conn: OpenFeedConnection) -> str:
    rt = unseal(conn.refresh_token_enc) if conn.refresh_token_enc else None
    if not rt:
        conn.status = "reconnect_required"
        raise OpenFeedError("reconnect_required", "Reconnect your bank to continue.", 409)
    res = _post_token(cfg, {"grant_type": "refresh_token", "refresh_token": rt})
    tok = res["json"]
    if res["status"] != 200 or not tok.get("access_token"):
        conn.status, conn.last_error = "reconnect_required", "The bank connection expired"
        db.flush()
        raise OpenFeedError("reconnect_required", "The bank connection expired. Reconnect your bank to continue.", 409)
    _store_tokens(db, conn.org_id, tok)                                                    # refresh tokens may rotate: always keep the newest
    return tok["access_token"]


def _mark(db: Session, conn: OpenFeedConnection, e: SharingApiError):
    if e.code == "grant_revoked":
        conn.status, conn.grant_id, conn.accounts_json, conn.last_error = "revoked", None, "[]", "Access was withdrawn at OpenFeed"
    elif e.code == "credit_exhausted":
        conn.status, conn.last_error = "paused", "Bank data access is paused"
    elif e.code == "token_expired":
        conn.status, conn.last_error = "reconnect_required", "The bank connection expired"
    else:
        conn.last_error = e.message[:290]
    db.flush()


def sync(db: Session, org_id: int, force: bool = False, access_token: str = None) -> dict:
    """Refresh the cached account list. Never raises for 'try again later' conditions - the status explains."""
    cfg = Cfg(db)
    conn = db.get(OpenFeedConnection, org_id)
    if conn is None or conn.status in ("pending", "revoked"):
        raise OpenFeedError("not_connected", "No bank is connected for this organisation.", 409)
    if not force and conn.last_sync_at and datetime.utcnow() - conn.last_sync_at < SYNC_MIN_GAP:
        return status(db, org_id)
    try:
        token = access_token or _access_token(db, cfg, conn)
        accts = fetch_all(cfg, token, "/v1/banking/accounts")
    except SharingApiError as e:
        _mark(db, conn, e)
        raise
    before = {a["id"]: a.get("enabled", True) for a in json.loads(conn.accounts_json or "[]")}          # an account the organisation switched off stays off after a refresh
    conn.accounts_json = json.dumps([{"id": a.get("accountId"), "name": a.get("displayName") or a.get("nickname") or "Account", "masked": a.get("maskedNumber") or "",
                                      "provider": a.get("providerName") or "", "enabled": before.get(a.get("accountId"), True)} for a in accts if a.get("accountId")])
    conn.last_sync_at, conn.last_error, conn.status = datetime.utcnow(), None, "active"
    db.flush()
    return status(db, org_id)


def status(db: Session, org_id: int) -> dict:
    cfg = Cfg(db)
    conn = db.get(OpenFeedConnection, org_id)
    accts = [{**a, "enabled": a.get("enabled", True)} for a in (json.loads(conn.accounts_json or "[]") if conn else [])]
    return {"available": cfg.ready, "status": conn.status if conn else "not_connected", "accounts": accts,
            "bank_count": len({a.get("provider") or "" for a in accts}),
            "last_sync": conn.last_sync_at.isoformat() + "Z" if conn and conn.last_sync_at else None, "error": conn.last_error if conn else None,
            "connected_at": conn.connected_at.isoformat() + "Z" if conn and conn.connected_at else None}


def set_account_enabled(db: Session, org_id: int, account_id: str, enabled: bool) -> dict:
    """Use / don't use ONE shared account in AccFino (reconciliation and refreshes). The other accounts, and the connection, are untouched.
    This is AccFino's side only: whether OpenFeed still shares the account is changed on OpenFeed's own screen (Add or remove accounts)."""
    conn = db.get(OpenFeedConnection, org_id)
    if conn is None:
        raise OpenFeedError("not_connected", "No bank is connected for this organisation.", 409)
    accts = json.loads(conn.accounts_json or "[]")
    hit = next((a for a in accts if a["id"] == account_id), None)
    if hit is None:
        raise OpenFeedError("unknown_account", "That account is not shared with AccFino.", 404)
    hit["enabled"] = bool(enabled)
    conn.accounts_json = json.dumps(accts)
    db.flush()
    return status(db, org_id)


def org_accounts(db: Session, org_id: int) -> list:
    conn = db.get(OpenFeedConnection, org_id)
    if conn is None or conn.status != "active":
        return []
    return [a for a in json.loads(conn.accounts_json or "[]") if a.get("enabled", True)]


def pull_rows(db: Session, org_id: int, account_id: str, d_from: date, d_to: date) -> list:
    """Transactions for one shared account in the reconciliation layout (debit/credit columns, d/m/Y)."""
    cfg = Cfg(db)
    conn = db.get(OpenFeedConnection, org_id)
    if conn is None or conn.status != "active":
        raise OpenFeedError("not_connected", "No bank is connected for this organisation.", 409)
    acc = next((a for a in json.loads(conn.accounts_json or "[]") if a["id"] == account_id), None)
    if acc is None:
        raise OpenFeedError("unknown_account", "That account is not shared with AccFino.", 400)
    if not acc.get("enabled", True):
        raise OpenFeedError("account_off", "That account is switched off in AccFino. Switch it on in Settings > Open Banking.", 409)
    try:
        token = _access_token(db, cfg, conn)
        txns = fetch_all(cfg, token, f"/v1/banking/accounts/{account_id}/transactions?" + urlencode({"oldestDate": d_from.isoformat(), "newestDate": d_to.isoformat(), "limit": 1000}))
    except SharingApiError as e:
        _mark(db, conn, e)
        raise
    rows = []
    for t in txns:
        raw = next((t.get(k) for k in ("transactionDate", "valueDate", "postedDateTime", "executionDateTime") if t.get(k)), None)   # first non-null of the four
        try:
            day = datetime.strptime(str(raw)[:10], "%Y-%m-%d").date()
        except (TypeError, ValueError):
            continue
        if not (d_from <= day <= d_to):
            continue
        try:
            amt = float(t.get("amount") or 0)                      # OpenFeed: negative = money out
        except (TypeError, ValueError):
            amt = 0.0
        rows.append({"date": day.strftime("%d/%m/%Y"), "description": (t.get("description") or t.get("reference") or "").strip(),
                     "debit": abs(amt) if amt < 0 else 0.0, "credit": amt if amt > 0 else 0.0, "balance": "",
                     "bank": acc["provider"] or "OpenFeed", "account": acc["masked"] or acc["id"]})
    rows.sort(key=lambda r: datetime.strptime(r["date"], "%d/%m/%Y"))
    return rows


def disconnect(db: Session, org_id: int):
    """Stop collecting. Local data is cleared; the person can also revoke from their OpenFeed dashboard (that never breaks other apps)."""
    conn = db.get(OpenFeedConnection, org_id)
    if conn is None:
        return
    cfg = Cfg(db)
    if cfg.ready and conn.grant_id and conn.refresh_token_enc:
        try:                                                              # best effort: revoke the grant at OpenFeed too (needs the grant:self:revoke scope)
            token = _access_token(db, cfg, conn)
            url = f"{cfg.api}/v1/grants/{conn.grant_id}"
            with _client() as c:
                c.delete(url, headers={"Authorization": f"DPoP {token}", "DPoP": dpop_proof(cfg, url, "DELETE", access_token=token)})
        except Exception as e:
            log.info("OpenFeed grant revoke skipped: %s", e)
    db.delete(conn)
    db.query(OpenFeedFlow).filter(OpenFeedFlow.org_id == org_id).delete()
    db.flush()
