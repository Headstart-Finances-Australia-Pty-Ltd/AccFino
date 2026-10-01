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
SCOPE = "openid openfeed-au:data:banking:read"
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
    def __init__(self, code: str, message: str, status: int = 400):
        super().__init__(message)
        self.code, self.message, self.status = code, message, status


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
        self.issuer = e("OPENFEED_ISSUER", DEFAULT_ISSUER).rstrip("/")
        self.api = e("OPENFEED_API_BASE", DEFAULT_API).rstrip("/")
        self.consent = e("OPENFEED_CONSENT_BASE", DEFAULT_CONSENT).rstrip("/")

    @property
    def ready(self) -> bool:
        return bool(self.client_id and self.app_id and self.app_key and self.dpop_key)

    def missing(self) -> list:
        return [n for n, v in (("OpenFeed app (client id)", self.client_id), ("OpenFeed app id", self.app_id), ("app signing key", self.app_key), ("DPoP key", self.dpop_key)) if not v]


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
    jwk.update({"use": "sig", "alg": "PS256", "kid": "accfino-" + datetime.utcnow().strftime("%Y%m%d")})
    return {"keys": [jwk]}


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
    now = int(datetime.utcnow().timestamp())
    return jwt.encode({"iss": cfg.client_id, "sub": cfg.client_id, "aud": cfg.issuer, "jti": str(uuid.uuid4()), "iat": now, "exp": now + 60},
                      cfg.app_key, algorithm="PS256")


def dpop_proof(cfg: Cfg, htu: str, htm: str, access_token: str = None, nonce: str = None) -> str:
    key = serialization.load_pem_private_key(cfg.dpop_key.encode(), password=None)
    jwk = jwt.algorithms.RSAAlgorithm.to_jwk(key.public_key(), as_dict=True)          # PUBLIC key only in the header
    claims = {"htu": htu.split("?")[0].split("#")[0], "htm": htm, "iat": int(datetime.utcnow().timestamp()), "jti": str(uuid.uuid4())}
    if access_token:
        claims["ath"] = b64u(hashlib.sha256(access_token.encode()).digest())
    if nonce:
        claims["nonce"] = nonce
    return jwt.encode(claims, cfg.dpop_key, algorithm="PS256", headers={"typ": "dpop+jwt", "jwk": jwk})


def _post_token(cfg: Cfg, form: dict) -> dict:
    """POST to the token endpoint with a DPoP proof; if the server demands a nonce, retry exactly once with it."""
    url = discovery(cfg)["token_endpoint"]
    body = {"client_assertion_type": "urn:ietf:params:oauth:client-assertion-type:jwt-bearer", "resource": cfg.api, **form}
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
    with _client() as c:
        r = c.post(d["pushed_authorization_request_endpoint"], data={
            "client_assertion_type": "urn:ietf:params:oauth:client-assertion-type:jwt-bearer", "client_assertion": client_assertion(cfg),
            "response_type": "code", "client_id": cfg.client_id, "redirect_uri": flow.redirect_uri, "scope": SCOPE, "resource": cfg.api,
            "code_challenge": b64u(hashlib.sha256(verifier.encode()).digest()), "code_challenge_method": "S256",
            "nonce": flow.nonce, "state": flow.state, "grant_management_action": "create"})
    if r.status_code not in (200, 201) or not r.json().get("request_uri"):
        db.rollback()
        log.error("OpenFeed PAR failed: %s %s", r.status_code, r.text[:200])
        raise OpenFeedError("par_failed", "OpenFeed did not accept the request. Platform setup may be incomplete - please contact AccFino support.", 502)
    conn = db.get(OpenFeedConnection, org_id) or OpenFeedConnection(org_id=org_id)
    conn.status, conn.connected_by, conn.last_error = "pending", user_id, None
    db.merge(conn)
    db.flush()
    return d["authorization_endpoint"] + "?" + urlencode({"client_id": cfg.client_id, "request_uri": r.json()["request_uri"]})


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
        return query_return("/settings/open-banking", "declined"), None
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
        return query_return(flow.return_to or "/settings/open-banking", "connected"), flow.state
    flow.phase = "awaiting_consent"                                                        # first time: pick the accounts to share with AccFino
    return cfg.consent + "/grants/disclosure?" + urlencode({"appId": cfg.app_id, "redirectUri": _public_base_from(flow.redirect_uri) + "/open-banking/openfeed/consent-return"}), flow.state


def _public_base_from(redirect_uri: str) -> str:
    p = urlparse(redirect_uri)
    return f"{p.scheme}://{p.netloc}"


def query_return(path: str, result: str) -> str:
    return path + ("&" if "?" in path else "?") + "openfeed=" + result


def handle_consent_return(db: Session, flow_state: str, query: dict) -> str:
    """Browser is back from the 'share with AccFino' screen (?grantId&consented). Uses the cookie that links it to the flow."""
    flow = _flow(db, flow_state)
    back = flow.return_to or "/settings/open-banking"
    if flow.phase != "awaiting_consent":
        raise OpenFeedError("flow_state", "That connection attempt is not waiting for approval.", 400)
    if query.get("consented") != "true":
        conn = db.get(OpenFeedConnection, flow.org_id)
        if conn is not None and not conn.grant_id:
            conn.status = "pending"
        db.delete(flow)
        return query_return(back, "declined")
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
    return query_return(back, "connected")


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
    conn.accounts_json = json.dumps([{"id": a.get("accountId"), "name": a.get("displayName") or a.get("nickname") or "Account", "masked": a.get("maskedNumber") or "",
                                      "provider": a.get("providerName") or ""} for a in accts if a.get("accountId")])
    conn.last_sync_at, conn.last_error, conn.status = datetime.utcnow(), None, "active"
    db.flush()
    return status(db, org_id)


def status(db: Session, org_id: int) -> dict:
    cfg = Cfg(db)
    conn = db.get(OpenFeedConnection, org_id)
    accts = json.loads(conn.accounts_json or "[]") if conn else []
    return {"available": cfg.ready, "status": conn.status if conn else "not_connected", "accounts": accts,
            "last_sync": conn.last_sync_at.isoformat() + "Z" if conn and conn.last_sync_at else None, "error": conn.last_error if conn else None,
            "connected_at": conn.connected_at.isoformat() + "Z" if conn and conn.connected_at else None}


def org_accounts(db: Session, org_id: int) -> list:
    conn = db.get(OpenFeedConnection, org_id)
    if conn is None or conn.status != "active":
        return []
    return json.loads(conn.accounts_json or "[]")


def pull_rows(db: Session, org_id: int, account_id: str, d_from: date, d_to: date) -> list:
    """Transactions for one shared account in the reconciliation layout (debit/credit columns, d/m/Y)."""
    cfg = Cfg(db)
    conn = db.get(OpenFeedConnection, org_id)
    if conn is None or conn.status != "active":
        raise OpenFeedError("not_connected", "No bank is connected for this organisation.", 409)
    acc = next((a for a in json.loads(conn.accounts_json or "[]") if a["id"] == account_id), None)
    if acc is None:
        raise OpenFeedError("unknown_account", "That account is not shared with AccFino.", 400)
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
