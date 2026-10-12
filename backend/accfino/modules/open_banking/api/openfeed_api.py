"""Live bank feeds through OpenFeed (CDR) - the organisation never creates an OpenFeed account for AccFino; it just presses "Connect my bank".

  Platform (AccFino administrator, once - /openfeed/* is admin-guarded by the auth middleware):
    GET  /openfeed/status            is the platform's OpenFeed app set up?
    POST /openfeed/keys              generate the two keypairs; returns the PUBLIC key set to paste into the OpenFeed dashboard
    POST /openfeed/config            save the app's client id + app id (what the OpenFeed dashboard shows after registering)

  Organisation (Organisation Admin manages; any member of the organisation can see status):
    GET  /org/current/open-banking             status + the shared accounts
    POST /org/current/open-banking/connect     -> {url}  send the browser there (OpenFeed sign-in -> bank -> share with AccFino)
    POST /org/current/open-banking/sync        refresh the account list now
    POST /org/current/open-banking/pull        {account_id, from_date, to_date} -> transactions in the reconciliation layout
    POST /org/current/open-banking/account     {account_id, enabled} switch ONE shared account on/off in AccFino
    POST /org/current/open-banking/disconnect  stop the whole feed

  Browser redirects from OpenFeed (public: they carry a single-use state that identifies the organisation):
    GET  /open-banking/openfeed/callback         ?code&state&iss
    GET  /open-banking/openfeed/consent-return   ?grantId&consented
"""
import logging
from datetime import date

from fastapi import APIRouter, Body, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.orm import Session

from accfino.modules.open_banking import openfeed as OF
from accfino.core.security import audit
from accfino.core.subscription import service as S
from accfino.core.security.context import OrgContext, current_auth, current_org
from accfino.core.security.login import client_ip
from accfino.shared.db.database import get_db

log = logging.getLogger("accfino.openfeed")
platform = APIRouter()
org_router = APIRouter()
public = APIRouter()
COOKIE = "of_flow"


def _err(e: OF.OpenFeedError, admin: bool = False):
    """Clients get the plain message; the AccFino administrator also gets OpenFeed's own explanation so a set-up mistake can be fixed."""
    raise HTTPException(e.status, e.message + (f" [OpenFeed said: {e.detail}]" if admin and getattr(e, "detail", "") else ""))


def _admin(request: Request) -> dict:
    auth = current_auth(request)
    if not auth.get("is_admin"):
        raise HTTPException(403, "Administrators only")
    return auth


# ----------------------------------------------------------------------------------------------------- platform (AccFino admin) --
@platform.get("/status")
def platform_status(request: Request, db: Session = Depends(get_db)):
    _admin(request)
    cfg = OF.Cfg(db)
    return {"available": True, "ready": cfg.ready, "hasKeys": bool(cfg.app_key and cfg.dpop_key), "hasIds": bool(cfg.client_id and cfg.app_id),
            "clientId": cfg.client_id, "appId": cfg.app_id, "missing": cfg.missing(), "issuer": cfg.issuer,
            "needsRegenerate": bool(cfg.app_key and cfg.dpop_key and not cfg.kid),                    # keys made by an older release have no key id
            "redirectUri": OF._public_base(str(request.base_url)) + "/open-banking/openfeed/callback", "scopes": OF.SCOPE.split(), "dashboardScopes": [OF.DATA_SCOPE], "kid": cfg.kid}


@platform.post("/keys")
def platform_keys(request: Request, db: Session = Depends(get_db)):
    _admin(request)
    jwks = OF.generate_platform_keys(db)
    db.commit()
    return {"ok": True, "jwks": jwks, "message": "Keys generated. Paste the public key set into the OpenFeed dashboard when you register the AccFino app. "
                                                 "The private keys stay on the server, encrypted - generating again replaces them (then update OpenFeed)."}


@platform.get("/public-key")
def platform_public_key(request: Request, db: Session = Depends(get_db)):
    _admin(request)
    jwks = OF.public_jwks(db)
    if jwks is None:
        raise HTTPException(404, "No keys yet - generate them first.")
    return {"jwks": jwks, "kid": jwks["keys"][0]["kid"], "fingerprint": OF.thumbprint(jwks["keys"][0])}


@platform.post("/test")
def platform_test(request: Request, db: Session = Depends(get_db)):
    _admin(request)
    return OF.diagnose(db, str(request.base_url))


@platform.post("/config")
def platform_config(request: Request, body: dict = Body(...), db: Session = Depends(get_db)):
    _admin(request)
    cid, aid = str(body.get("client_id", "")).strip(), str(body.get("app_id", "")).strip()
    if cid and not cid.startswith("app-"):
        raise HTTPException(422, "The OAuth2 Client ID starts with 'app-'. (The bare App ID is the other field.)")
    OF.save_platform_ids(db, cid, aid)
    db.commit()
    return {"ok": True}


# ---------------------------------------------------------------------------------------------------------------- organisation --
@org_router.get("")
def org_status(ctx: OrgContext = Depends(current_org), db: Session = Depends(get_db)):
    out = OF.status(db, ctx.org.id)
    out["can_manage"] = ctx.is_org_admin
    ent = S.entitlements(db, ctx.org.id)
    out["plan_allows"] = S.is_allowed(ent, ("open-banking",)) or bool(ctx.is_admin)             # Open banking is a function each plan switches on or off (Admin > Pricing)
    out["plan_name"] = ent["plan_name"]
    return out


@org_router.post("/connect")
def org_connect(request: Request, body: dict = Body(default={}), ctx: OrgContext = Depends(current_org), db: Session = Depends(get_db)):
    S.check(db, ctx, ("open-banking",), "POST")                              # 402 when the organisation's plan does not include live bank feeds
    ctx.require_org_admin()
    # the browser sends where it is (a path) and, when the flow runs in a pop-up, its own origin so the pop-up can tell it when it is finished
    return_to = OF.encode_return(str(body.get("return_to") or "/settings/open-banking"), str(body.get("popup_origin") or "") or None)   # never redirect off-site
    try:
        url = OF.start_connect(db, ctx.org.id, ctx.user_id, str(request.base_url), return_to)
        db.commit()
    except OF.OpenFeedError as e:
        db.rollback()
        _err(e, admin=bool(getattr(ctx, "is_admin", False)))
    audit.write("openbanking.connect_started", user_id=ctx.user_id, username=ctx.username, org_id=ctx.org.id, entity="openfeed", ip=client_ip(request))
    return {"url": url}


@org_router.post("/sync")
def org_sync(ctx: OrgContext = Depends(current_org), db: Session = Depends(get_db)):
    S.check(db, ctx, ("open-banking",), "POST")                              # 402 when the organisation's plan does not include live bank feeds
    ctx.require_org_admin()
    try:
        out = OF.sync(db, ctx.org.id, force=True)
        db.commit()
        return out
    except OF.OpenFeedError as e:
        db.commit()                                                           # keep the status the failure produced (reconnect_required, revoked ...)
        _err(e)


@org_router.post("/account")
def org_account(request: Request, body: dict = Body(...), ctx: OrgContext = Depends(current_org), db: Session = Depends(get_db)):
    S.check(db, ctx, ("open-banking",), "POST")                              # 402 when the organisation's plan does not include live bank feeds
    """Switch ONE shared account on or off in AccFino: {account_id, enabled}."""
    ctx.require_org_admin()
    try:
        out = OF.set_account_enabled(db, ctx.org.id, str(body.get("account_id", "")), bool(body.get("enabled")))
        db.commit()
    except OF.OpenFeedError as e:
        db.rollback()
        _err(e)
    audit.write("openbanking.account_switched", user_id=ctx.user_id, username=ctx.username, org_id=ctx.org.id, entity="openfeed_account",
                detail="on" if body.get("enabled") else "off", ip=client_ip(request))
    return out


@org_router.post("/pull")
def org_pull(body: dict = Body(...), ctx: OrgContext = Depends(current_org), db: Session = Depends(get_db)):
    S.check(db, ctx, ("open-banking",), "POST")                              # 402 when the organisation's plan does not include live bank feeds
    try:
        d_from = date.fromisoformat(str(body.get("from_date"))[:10])
        d_to = date.fromisoformat(str(body.get("to_date"))[:10])
    except ValueError:
        raise HTTPException(400, "From and To must be dates (YYYY-MM-DD)")
    if d_from > d_to:
        raise HTTPException(400, "From date must be on or before To date")
    try:
        rows = OF.pull_rows(db, ctx.org.id, str(body.get("account_id", "")), d_from, d_to)
        db.commit()
    except OF.OpenFeedError as e:
        db.commit()
        _err(e)
    return {"rows": rows, "count": len(rows), "from_date": d_from.isoformat(), "to_date": d_to.isoformat()}


@org_router.post("/disconnect")
def org_disconnect(request: Request, ctx: OrgContext = Depends(current_org), db: Session = Depends(get_db)):
    S.check(db, ctx, ("open-banking",), "POST")                              # 402 when the organisation's plan does not include live bank feeds
    ctx.require_org_admin()
    OF.disconnect(db, ctx.org.id)
    db.commit()
    audit.write("openbanking.disconnected", user_id=ctx.user_id, username=ctx.username, org_id=ctx.org.id, entity="openfeed", ip=client_ip(request))
    return {"ok": True}


# -------------------------------------------------------------------------------------------------- browser comes back from OpenFeed --
def _fail(reason: str, return_to: str = None) -> RedirectResponse:
    r = RedirectResponse(OF.done_url(return_to, "error", reason), status_code=303)
    r.delete_cookie(COOKIE, path="/open-banking/openfeed/")
    return r


@public.get("/callback")
def callback(request: Request, db: Session = Depends(get_db)):
    q = dict(request.query_params)
    try:
        url, state = OF.handle_callback(db, q)
        db.commit()
    except OF.OpenFeedError as e:
        db.rollback()
        log.warning("OpenFeed callback: %s", e.code)
        return _fail(e.code, OF.flow_return_to(db, q.get("state")))
    r = RedirectResponse(url, status_code=303)
    if state:
        r.set_cookie(COOKIE, state, max_age=OF.FLOW_MINUTES * 60, httponly=True, secure=request.url.scheme == "https", samesite="lax", path="/open-banking/openfeed/")
    return r


@public.get("/consent-return")
def consent_return(request: Request, db: Session = Depends(get_db)):
    try:
        url = OF.handle_consent_return(db, request.cookies.get(COOKIE, ""), dict(request.query_params))
        db.commit()
    except OF.OpenFeedError as e:
        db.rollback()
        log.warning("OpenFeed consent-return: %s", e.code)
        return _fail(e.code, OF.flow_return_to(db, request.cookies.get(COOKIE, "")))
    r = RedirectResponse(url, status_code=303)
    r.delete_cookie(COOKIE, path="/open-banking/openfeed/")
    return r


DONE_PAGE = r"""<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>AccFino</title>
<style>body{font-family:system-ui,sans-serif;text-align:center;padding:48px 24px;color:#1a202c}a{color:#2b6cb0}</style></head><body>
<h2 id="t">Finishing…</h2><p id="m"></p><p><a id="back" href="/settings/open-banking">Return to AccFino</a></p>
<script>
(function () {
  var q = new URLSearchParams(location.search), result = q.get('result') || 'error', reason = q.get('reason') || '', origin = q.get('origin') || '';
  var to = q.get('to') || '/settings/open-banking'; if (!/^\/(?!\/)/.test(to)) to = '/settings/open-banking';
  var msg = { type: 'accfino-openfeed', result: result, reason: reason };
  document.getElementById('back').href = to + (to.indexOf('?') < 0 ? '?' : '&') + 'openfeed=' + encodeURIComponent(result) + (reason ? '&reason=' + encodeURIComponent(reason) : '');
  var words = { connected: 'Your bank is connected', declined: 'Nothing was shared', error: 'The connection could not be completed' };
  document.getElementById('t').textContent = words[result] || words.error;
  document.getElementById('m').textContent = 'You can close this window.';
  try { if (window.opener && /^https?:\/\/[^\/\s]+$/.test(origin)) window.opener.postMessage(msg, origin); } catch (e) {}
  try { var bc = new BroadcastChannel('accfino-openfeed'); bc.postMessage(msg); bc.close(); } catch (e) {}   // reaches the main window even if the browser cut the opener link
  setTimeout(function () { try { window.close(); } catch (e) {} }, 400);
})();
</script></body></html>"""


@public.get("/done")
def done():
    """The last page of the pop-up flow. Carries no secrets: it only reports connected / declined / error to the window that opened it, then closes itself."""
    return HTMLResponse(DONE_PAGE, headers={"Cache-Control": "no-store", "Referrer-Policy": "no-referrer"})
