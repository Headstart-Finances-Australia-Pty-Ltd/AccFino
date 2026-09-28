"""
accfino_core.security.middleware
--------------------------------
Server-side authentication and authorisation for EVERY route, with or without
the /api prefix (runs after StripApiPrefix, so it sees the real route path).

Policy per request (decided by the route that will actually handle it):
  public  - login, registration, password reset, health, SPA pages, static, legal
  auth    - any valid access token
  admin   - token with admin role (DB browser, file manager, key pool, licences ...)

Ownership (non-admin callers):
  * user_id / username in path, query, JSON body or form must be the caller's own
  * if a route optionally accepts user_id / username and none was sent, the
    caller's own id is injected so the response is scoped to them
    (fixes e.g. GET /payroll/employees returning every tenant's employees)

Every non-GET request by an authenticated caller is written to the audit log.
AUTH_MODE=report turns enforcement into log-only (emergency rollback switch).
"""
import json
import logging
from urllib.parse import parse_qsl, urlencode

import anyio
import jwt
from starlette.datastructures import Headers
from starlette.responses import JSONResponse
from starlette.routing import Match, Mount

from accfino_core import config
from accfino_core.security import audit, iam, tokens

log = logging.getLogger("accfino.auth")

PUBLIC_ROUTES = {
    "/health", "/ready", "/", "/{spa_path:path}", "/login", "/reset-password", "/upgrade",
    "/index-marketing.html", "/robots.txt", "/sitemap.xml", "/legal", "/legal/{doc_name}",
    "/auth/register", "/auth/forgot-password", "/auth/reset-password", "/auth/verify-reset-token",
    "/auth/reset-admin", "/auth/reset-admin-full", "/auth/mfa/login",
    "/auth/mfa/challenge/send", "/auth/mfa/passkeys/auth/options", "/auth/mfa/passkeys/auth/verify",
    "/payments/plans", "/payments/webhook",
}
# GET /module-visibility is public: it only says which modules are switched on (the public landing page
# already shows the same), and the SPA reads it on /login before anyone is signed in.
PUBLIC_METHOD_ROUTES = {("POST", "/auth/login"), ("GET", "/pricing/plans"), ("GET", "/module-visibility")}
BLOCKED_METHOD_ROUTES = {("GET", "/auth/login"): "Password login over GET is disabled. Use POST /auth/login."}
PUBLIC_MOUNTS = {"/assets"}
# Handlers that only return the static SPA shell / marketing HTML (no data). A browser
# can't attach a bearer token when loading a page URL, so these must stay public;
# the React <Guard> sends signed-out users to /login.
PUBLIC_ENDPOINTS = {"root", "public_spa_routes", "auth_spa_routes", "spa_fallback", "marketing_html",
                    "robots_txt", "sitemap_xml", "serve_legal_doc", "legal_index", "module_registry"}

# (methods or None for all, route path, match mode)
ADMIN_RULES = [
    (None, "/db-browser", "prefix"),
    (None, "/filemanager", "prefix"),
    (None, "/groq-pool", "prefix"),
    ({"GET"}, "/licence/list", "exact"),
    ({"POST"}, "/licence/save", "exact"),
    (None, "/licence/user/", "prefix"),
    (None, "/payments/admin/", "prefix"),
    ({"POST", "PATCH", "PUT", "DELETE"}, "/pricing/plans", "prefix"),
    ({"POST", "PATCH", "PUT", "DELETE"}, "/module-visibility", "exact"),   # platform-wide switch: admin only
    ({"POST"}, "/company/approve/", "prefix"),
    ({"POST"}, "/ml/train", "exact"),
    (None, "/debug/", "prefix"),
    (None, "/shutdown", "exact"),
    (None, "/admin/", "prefix"),
    (None, "/audit/all", "prefix"),
    (None, "/docs", "prefix"), (None, "/redoc", "prefix"), (None, "/openapi.json", "exact"),
]
DOC_ROUTES = {"/docs", "/docs/oauth2-redirect", "/redoc", "/openapi.json"}
MFA_ALLOWED_WHEN_NOT_ENROLLED = ("/auth/me", "/auth/mfa/", "/auth/logout", "/auth/verify/", "/licence/my-modules",
                                 "/payments/my-plan/")

OWNER_KEYS = ("user_id", "username")
# Paths a user can still reach while blocked by Conditional Access or a forced password change,
# so they can fix the problem (enrol MFA, change password, sign out, switch organisation).
REMEDIATION_PATHS = ("/auth/me", "/auth/mfa/", "/auth/logout", "/auth/sessions", "/auth/change-password",
                     "/org/mine", "/licence/my-modules", "/payments/my-plan/")


def _match_admin(method, path):
    for methods, rpath, mode in ADMIN_RULES:
        if methods and method not in methods:
            continue
        if (mode == "exact" and path == rpath) or (mode == "prefix" and path.startswith(rpath)):
            return True
    return False


def _param_names(route, kind):
    dep = getattr(route, "dependant", None)
    if dep is None:
        return set()
    names = set()
    fields = getattr(dep, f"{kind}_params", []) or []
    for f in fields:
        ann = getattr(getattr(f, "field_info", None), "annotation", None)
        mf = getattr(ann, "model_fields", None)
        if kind == "body" and mf:
            names |= set(mf.keys())
        names.add(getattr(f, "alias", None) or f.name)
    return names


def _same_user(key, value, auth):
    if value is None:
        return True
    v = str(value).strip()
    if key == "user_id":
        return v == str(auth["user_id"])
    v = v.lower()
    usr = (auth.get("username") or "").lower()
    eml = (auth.get("email") or "").lower()
    allowed = {usr, eml, usr.split("@")[0], eml.split("@")[0]} - {""}
    return v in allowed


class AuthGuard:
    def __init__(self, app, fastapi_app=None):
        self.app = app
        self.fastapi_app = fastapi_app

    # ------------------------------------------------------------ routing --
    def _resolve(self, scope):
        router = self.fastapi_app.router if self.fastapi_app else None
        if router is None:
            return None, {}
        partial = None
        for route in router.routes:
            match, child = route.matches(scope)
            if match == Match.FULL:
                return route, child
            if match == Match.PARTIAL and partial is None:
                partial = (route, child)
        return partial if partial else (None, {})

    def _policy(self, route, method, path):
        if route is None:
            return "public", None          # unknown path -> normal 404
        if isinstance(route, Mount):
            return ("public" if route.path in PUBLIC_MOUNTS else "auth"), route.path
        rpath = route.path
        if method == "GET" and getattr(getattr(route, "endpoint", None), "__name__", "") in PUBLIC_ENDPOINTS:
            return "public", rpath
        if (method, rpath) in BLOCKED_METHOD_ROUTES:
            return "blocked", rpath
        if rpath in DOC_ROUTES and config.ENABLE_API_DOCS:
            return "public", rpath
        if rpath in PUBLIC_ROUTES or (method, rpath) in PUBLIC_METHOD_ROUTES:
            return "public", rpath
        if _match_admin(method, rpath):
            return "admin", rpath
        return "auth", rpath

    # ----------------------------------------------------------- identity --
    @staticmethod
    def _authenticate(headers):
        authz = headers.get("authorization", "")
        if not authz.lower().startswith("bearer "):
            return None, "missing_token"
        try:
            data = tokens.decode(authz.split(" ", 1)[1].strip(), "access")
        except jwt.ExpiredSignatureError:
            return None, "token_expired"
        except jwt.PyJWTError:
            return None, "invalid_token"
        uid = int(data["sub"])
        if int(data.get("tv", 0)) != tokens.current_token_version(uid):
            return None, "token_revoked"
        sid = data.get("sid")
        started = None
        if sid:
            revoked, started = iam.session_info(sid)
            if revoked:
                return None, "session_ended"
        state = iam.account_state(uid)
        if state["disabled"]:
            return None, "account_disabled"
        return {"user_id": uid, "username": data.get("usr"), "email": data.get("eml"),
                "is_admin": bool(data.get("adm")), "org_id": data.get("org"),
                "mfa": bool(data.get("mfa")), "jti": data.get("jti"), "sid": sid,
                "amr": data.get("amr") or ["pwd"], "session_started": started,
                "must_change_password": state["must_change_password"]}, None

    # --------------------------------------------------------------- asgi --
    async def __call__(self, scope, receive, send):
        if scope["type"] != "http" or scope["method"] == "OPTIONS":
            return await self.app(scope, receive, send)

        method, path = scope["method"], scope["path"]
        route, child = self._resolve(scope)
        policy, rpath = self._policy(route, method, path)
        headers = Headers(scope=scope)
        ip = iam.client_ip_from(headers, (scope.get("client") or ("", 0))[0])
        report_only = config.AUTH_MODE == "report"

        if policy == "blocked":
            return await JSONResponse({"detail": BLOCKED_METHOD_ROUTES[(method, rpath)]}, 405)(scope, receive, send)

        auth, err = self._authenticate(headers)
        scope.setdefault("state", {})["auth"] = auth

        if policy == "public":
            return await self.app(scope, receive, send)

        if auth is None:
            if report_only:
                log.warning("AUTH(report) anonymous %s %s (%s)", method, path, err)
                return await self.app(scope, receive, send)
            return await JSONResponse({"detail": "Not authenticated", "code": err}, 401,
                                      headers={"WWW-Authenticate": "Bearer"})(scope, receive, send)

        if policy == "admin" and not auth["is_admin"]:
            if rpath == "/shutdown" or not report_only:
                return await JSONResponse({"detail": "Administrator access required"}, 403)(scope, receive, send)
            log.warning("AUTH(report) non-admin %s %s", method, path)

        if rpath == "/shutdown" and not config.ALLOW_SHUTDOWN:
            return await JSONResponse({"detail": "Shutdown endpoint is disabled"}, 403)(scope, receive, send)

        if auth.get("sid"):
            await anyio.to_thread.run_sync(iam.touch_session, auth["sid"])

        if auth.get("must_change_password") and not path.startswith(REMEDIATION_PATHS):
            return await JSONResponse({"detail": "You must change your password before continuing.",
                                       "code": "password_change_required"}, 403)(scope, receive, send)

        # ---------------- Conditional Access (organisation policy) --------------
        if not auth["is_admin"] and not path.startswith(REMEDIATION_PATHS):
            org_hdr = headers.get("x-org-id")
            try:
                org_id = int(org_hdr) if org_hdr else auth.get("org_id")
            except ValueError:
                org_id = auth.get("org_id")
            if org_id:
                policy = iam.org_policy(org_id)
                role = iam.member_role(auth["user_id"], org_id) if policy else None
                if policy and role:
                    decision = iam.evaluate(policy, role=role, ip=ip, mfa_verified=auth["mfa"], amr=auth["amr"],
                                            session_started=auth.get("session_started"))
                    if decision:
                        code, msg = decision
                        audit.write("ca.blocked" if policy["state"] == "on" else "ca.report_only",
                                    user_id=auth["user_id"], username=auth["username"], org_id=org_id, ip=ip,
                                    method=method, path=path, detail={"code": code})
                        if policy["state"] == "on" and not report_only:
                            status = 401 if code == "ca_reauth_required" else 403
                            return await JSONResponse({"detail": msg, "code": code}, status)(scope, receive, send)

        if config.MFA_ENFORCED and not auth["mfa"] and not path.startswith(MFA_ALLOWED_WHEN_NOT_ENROLLED):
            return await JSONResponse({"detail": "Multi-factor authentication enrolment required",
                                       "code": "mfa_enrolment_required"}, 403)(scope, receive, send)

        # ---------------- ownership enforcement for non-admin callers ----------
        if not auth["is_admin"] and route is not None and not isinstance(route, Mount):
            violation, receive = await self._enforce_ownership(scope, receive, route, child, auth)
            if violation:
                log.warning("AUTH ownership violation user=%s %s %s: %s", auth["user_id"], method, path, violation)
                audit.write("security.ownership_violation", user_id=auth["user_id"], username=auth["username"],
                            ip=ip, method=method, path=path, status_code=403, detail={"reason": violation})
                if not report_only:
                    return await JSONResponse({"detail": "You can only access your own data"}, 403)(scope, receive, send)

        # ---------------- run the app, capture status for the audit log --------
        status_holder = {}

        async def send_wrapper(message):
            if message["type"] == "http.response.start":
                status_holder["status"] = message["status"]
            await send(message)

        await self.app(scope, receive, send_wrapper)

        if method in ("POST", "PUT", "PATCH", "DELETE"):
            await anyio.to_thread.run_sync(lambda: audit.write(
                "http.write", user_id=auth["user_id"], username=auth["username"], org_id=auth.get("org_id"),
                ip=ip, method=method, path=path, status_code=status_holder.get("status"),
                entity=rpath))

    # ---------------------------------------------------------- ownership --
    async def _enforce_ownership(self, scope, receive, route, child, auth):
        # 1. path parameters
        for k, v in (child.get("path_params") or {}).items():
            if k in OWNER_KEYS and not _same_user(k, v, auth):
                return f"path {k}={v}", receive

        # 2. query string: verify, and inject when the route accepts it but it's absent
        qnames = _param_names(route, "query")
        pairs = parse_qsl(scope.get("query_string", b"").decode(), keep_blank_values=True)
        present = {k for k, _ in pairs}
        for k, v in pairs:
            if k in OWNER_KEYS and not _same_user(k, v, auth):
                return f"query {k}={v}", receive
        changed = False
        for k in OWNER_KEYS:
            if k in qnames and k not in present:
                pairs.append((k, str(auth["user_id"]) if k == "user_id" else (auth.get("username") or "")))
                changed = True
        if changed:
            scope["query_string"] = urlencode(pairs).encode()

        # 3. body (JSON or form) when the route declares body fields
        bnames = _param_names(route, "body")
        if scope["method"] not in ("POST", "PUT", "PATCH", "DELETE"):
            return None, receive
        headers = Headers(scope=scope)
        ctype = headers.get("content-type", "")
        if not (bnames & set(OWNER_KEYS)) and "json" not in ctype:
            return None, receive

        body, extra = await _read_body(receive)
        new_body = body
        if "json" in ctype and body:
            try:
                data = json.loads(body)
            except Exception:
                data = None
            if isinstance(data, dict):
                for k in OWNER_KEYS:
                    if k in data and data[k] not in (None, "") and not _same_user(k, data[k], auth):
                        return f"body {k}={data[k]}", _replay(body, receive)
                injected = False
                for k in OWNER_KEYS:
                    if k in bnames and data.get(k) in (None, ""):
                        data[k] = auth["user_id"] if k == "user_id" else auth.get("username")
                        injected = True
                if injected:
                    new_body = json.dumps(data).encode()
        elif ("multipart/form-data" in ctype or "application/x-www-form-urlencoded" in ctype) \
                and bnames & set(OWNER_KEYS) and body:
            form = await _parse_form(scope, body)
            for k in OWNER_KEYS:
                v = form.get(k)
                if isinstance(v, str) and v and not _same_user(k, v, auth):
                    return f"form {k}={v}", _replay(body, receive)

        if new_body is not body:
            hdrs = [(n, v) for n, v in scope["headers"] if n.lower() != b"content-length"]
            hdrs.append((b"content-length", str(len(new_body)).encode()))
            scope["headers"] = hdrs
        return None, _replay(new_body, receive)


async def _read_body(receive):
    chunks, more = [], True
    while more:
        msg = await receive()
        if msg["type"] == "http.disconnect":
            break
        chunks.append(msg.get("body", b""))
        more = msg.get("more_body", False)
    return b"".join(chunks), None


def _replay(body, original_receive):
    sent = {"done": False}

    async def receive():
        if not sent["done"]:
            sent["done"] = True
            return {"type": "http.request", "body": body, "more_body": False}
        return await original_receive()
    return receive


async def _parse_form(scope, body):
    from starlette.requests import Request
    req = Request(scope, _replay(body, None))
    try:
        form = await req.form()
        out = {k: v for k, v in form.items() if isinstance(v, str)}
        await form.close()
        return out
    except Exception:
        return {}
