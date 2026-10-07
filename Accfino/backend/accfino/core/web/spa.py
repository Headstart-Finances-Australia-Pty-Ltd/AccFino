"""
SPA + marketing site + legal documents + sitemap/robots + brand files, and the /api prefix-stripping middleware.
"""
import os
import sys
from pathlib import Path
from fastapi import APIRouter
from accfino.shared import paths as _paths

router = APIRouter()

import logging
logger = logging.getLogger("accfino")

from accfino.core.subscription.legacy_pricing_api import _load_pricing
from accfino.core.platform_admin.module_visibility import _load_module_visibility


import os
import base64, io, json, logging, os, sys, uuid
from pathlib import Path
from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile, Body
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request as _SReq
from fastapi.staticfiles import StaticFiles
from fastapi.responses   import FileResponse as _FileResponse
from fastapi.responses import FileResponse as _FileResponse

class StripApiPrefix(BaseHTTPMiddleware):
    async def dispatch(self, request: _SReq, call_next):
        scope = request.scope
        path  = scope.get("path", "")
        if path.startswith("/api/"):
            new_path = path[4:]                    # "/api/banks" - "/banks"
            scope["path"] = new_path
            qs = scope.get("query_string", b"")
            scope["raw_path"] = (
                new_path + ("?" + qs.decode() if qs else "")
            ).encode()
        elif path == "/api":
            scope["path"]     = "/"
            scope["raw_path"] = b"/"
        # All other paths pass through unchanged
        return await call_next(request)

_ROOT       = _paths.package_root()        # application root (frontend/dist is built UI, not data)

_DIST       = _ROOT / "frontend" / "dist"

_PUBLIC     = _ROOT / "frontend" / "public"   # Vite public folder (dev mode)

_MARKETING  = _DIST / "index-marketing.html" if (_DIST / "index-marketing.html").exists()               else _PUBLIC / "index-marketing.html"

_APP_INDEX  = _DIST / "index.html"

def _serve_marketing():
    """Return the marketing homepage with pricing always injected from pricing.json.

    Three-layer sync so homepage, login and upgrade always match pricing.json:
      Layer 1 - server injects window.__ACCFINO_PRICING__ into <head> (instant, no flash)
      Layer 2 - client JS uses window.__ACCFINO_PRICING__ before any fetch completes
      Layer 3 - client fetches /api/pricing/plans and re-renders (updates after load)

    Additionally regenerates the BUNDLES variable inside the marketing script so
    bundle vs module card layout stays correct when pricing.json changes.
    """
    if not _MARKETING.exists():
        return {"error": "Marketing page not found. Check frontend/public/index-marketing.html"}
    import json as _json_mkt, re as _re_mkt
    from fastapi.responses import HTMLResponse as _HTMLResponse
    html = _MARKETING.read_text(encoding="utf-8")
    try:
        pricing = _load_pricing()

        # -- Layer 1: inject window.__ACCFINO_PRICING__ into <head> ----------
        pricing_json = _json_mkt.dumps(pricing, ensure_ascii=False)
        inject = f'''<script>
// Pricing injected server-side from pricing.json - single source of truth
window.__ACCFINO_PRICING__ = {pricing_json};
</script>'''
        html = html.replace("</head>", inject + "\n</head>", 1)

        # -- Layer 2: keep DEFAULTS fallback in sync with pricing.json --------
        # Replace the hardcoded DEFAULTS object so the page renders correctly
        # even if window.__ACCFINO_PRICING__ is not set (e.g. cached HTML).
        defaults_js = _json_mkt.dumps(pricing, ensure_ascii=False, separators=(',', ':'))
        html = _re_mkt.sub(
            r'var DEFAULTS=window\.__ACCFINO_PRICING__\|\|\{.*?\};',
            f'var DEFAULTS=window.__ACCFINO_PRICING__||{defaults_js};',
            html, count=1, flags=_re_mkt.DOTALL
        )

        # -- Layer 3: regenerate BUNDLES array from pricing.json ---------------
        # A plan is a "bundle" if it includes 2+ non-base modules.
        _base_mods = {"dashboard", "reconciliation"}
        bundle_keys = _json_mkt.dumps([
            k for k, p in pricing.items()
            if sum(1 for m in p.get("modules", []) if m not in _base_mods) >= 2
        ])
        html = _re_mkt.sub(r'BUNDLES=\[.*?\]', f'BUNDLES={bundle_keys}', html)

    except Exception:
        pass  # Fall back gracefully - client-side fetch still works
    return _HTMLResponse(content=html, status_code=200)

def _serve_app() -> _FileResponse:
    """Return the React SPA shell (only available after npm run build)."""
    if _APP_INDEX.exists():
        return _FileResponse(str(_APP_INDEX))
    return {"error": "React app not built. Run: cd frontend && npm run build"}

@router.get("/index-marketing.html", include_in_schema=False)
def marketing_html():
    return _serve_marketing()

@router.get("/modules.json", include_in_schema=False)
def module_registry():
    """Module registry (single source of truth for the public marketing page - the
    in-app side panel and Home page bundle this file at build time instead, and
    apply /module-visibility themselves at runtime). Domains/modules an admin has
    switched off via /module-visibility are filtered out here too, so a hidden
    module never shows up on the landing page a signed-out visitor sees."""
    registry = None
    for p in (_DIST / "modules.json", _ROOT / "frontend" / "src" / "core" / "config" / "modules.json"):
        if p.exists():
            registry = json.loads(p.read_text(encoding="utf-8"))
            break
    if registry is None:
        return {"version": 0, "domains": [], "modules": []}

    vis = _load_module_visibility()
    dom_vis = vis.get("domains", {})
    mod_vis = vis.get("modules", {})
    registry = dict(registry)
    registry["domains"] = [d for d in registry.get("domains", []) if dom_vis.get(d["id"], True)]
    visible_domain_ids = {d["id"] for d in registry["domains"]}
    registry["modules"] = [m for m in registry.get("modules", [])
                            if m["domain"] in visible_domain_ids and mod_vis.get(m["id"], True) and not m.get("area")]   # Settings/Admin switches are not landing-page content
    return registry

def install_static_assets(app):
    """Serve the built React assets (called by the composition root after the SPA router)."""
    if _DIST.exists() and (_DIST / "assets").exists():
        app.mount("/assets", StaticFiles(directory=str(_DIST / "assets")), name="assets")

        # The fixed-assets API is ALSO mounted at /assets (as /assets/{id}, reached by the browser as /api/assets/{id}). Router order made it win over the
        # static mount above for single-segment files such as /assets/index-abc123.js, so the signed-out login page could not load its own JavaScript
        # (401 "Not authenticated") when the built app was served by this backend. Requests for files that really exist in the built dist/assets folder are
        # therefore answered first, before routing. API calls always arrive as /api/... so they are untouched.
        from starlette.middleware.base import BaseHTTPMiddleware as _BHM
        from fastapi.responses import FileResponse as _FileResponse
        _DIST_ASSETS = (_DIST / "assets").resolve()

        class StaticAssetsFirst(_BHM):
            async def dispatch(self, request, call_next):
                p = request.url.path
                if request.method in ("GET", "HEAD") and p.startswith("/assets/"):
                    f = (_DIST_ASSETS / p[len("/assets/"):]).resolve()
                    if _DIST_ASSETS in f.parents and f.is_file():          # (resolve() + parent check: no path traversal out of dist/assets)
                        return _FileResponse(f, headers={"Cache-Control": "public, max-age=31536000, immutable"})
                return await call_next(request)

        app.add_middleware(StaticAssetsFirst)                                # added last = runs first


_LEGAL_DIR = _paths.legal_dir()

LEGAL_DOCS = {
    "terms-of-service":         "terms_of_service.pdf",
    "privacy-policy":           "privacy_policy.pdf",
    "acceptable-use-policy":    "acceptable_use_policy.pdf",
    "subscription-refund-policy": "subscription_refund_policy.pdf",
    "cookie-policy":            "cookie_policy.pdf",
    "disclaimer":               "disclaimer.pdf",
}

@router.get("/legal/{doc_name}", include_in_schema=False)
def serve_legal_doc(doc_name: str):
    from fastapi.responses import FileResponse as _FR
    filename = LEGAL_DOCS.get(doc_name)
    if not filename:
        raise HTTPException(404, "Document not found")
    path = _LEGAL_DIR / filename
    if not path.exists():
        raise HTTPException(404, "Document file not found")
    return _FR(str(path), media_type="application/pdf",
               headers={"Content-Disposition": f"inline; filename={filename}"})

@router.get("/legal", include_in_schema=False)
def legal_index():
    from fastapi.responses import JSONResponse
    return JSONResponse({"documents": list(LEGAL_DOCS.keys())})

_SITE_ORIGIN = "https://accfino.com"

_SITEMAP_PATHS = [
    ("/",               "1.0", "daily"),
    ("/login",          "0.6", "monthly"),
    ("/upgrade",        "0.8", "monthly"),
    ("/dashboard",      "0.9", "weekly"),
    ("/reconciliation", "0.9", "weekly"),
    ("/trading",        "0.9", "weekly"),
    ("/cash-flow",      "0.9", "weekly"),
    ("/invoice",        "0.9", "weekly"),
]

def _legal_doc_lastmod(filename: str) -> str:
    """ISO date the legal PDF was last modified on disk, for sitemap <lastmod>."""
    import datetime as _dt
    path = _LEGAL_DIR / filename
    if path.exists():
        return _dt.datetime.utcfromtimestamp(path.stat().st_mtime).strftime("%Y-%m-%d")
    return _dt.datetime.utcnow().strftime("%Y-%m-%d")

@router.get("/sitemap.xml", include_in_schema=False)
def sitemap_xml():
    from fastapi.responses import Response as _XmlResponse

    entries = [
        {"loc": path, "priority": priority, "changefreq": freq, "lastmod": None}
        for path, priority, freq in _SITEMAP_PATHS
    ]
    # Legal documents — low priority, rarely change, but genuinely indexable
    # public pages (each /legal/{doc} route serves a real PDF).
    for slug, filename in LEGAL_DOCS.items():
        entries.append({
            "loc": f"/legal/{slug}",
            "priority": "0.2",
            "changefreq": "yearly",
            "lastmod": _legal_doc_lastmod(filename),
        })

    url_blocks = []
    for e in entries:
        lastmod_tag = f"\n    <lastmod>{e['lastmod']}</lastmod>" if e["lastmod"] else ""
        url_blocks.append(
            f"  <url>\n"
            f"    <loc>{_SITE_ORIGIN}{e['loc']}</loc>{lastmod_tag}\n"
            f"    <changefreq>{e['changefreq']}</changefreq>\n"
            f"    <priority>{e['priority']}</priority>\n"
            f"  </url>"
        )

    xml = (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'
        + "\n".join(url_blocks) +
        "\n</urlset>"
    )
    return _XmlResponse(content=xml, media_type="application/xml")

@router.get("/robots.txt", include_in_schema=False)
def robots_txt():
    from fastapi.responses import PlainTextResponse as _TxtResponse
    body = (
        "User-agent: *\n"
        "Allow: /\n"
        "Allow: /login\n"
        "Allow: /upgrade\n"
        "Allow: /legal\n"
        "Allow: /dashboard\n"
        "Allow: /reconciliation\n"
        "Allow: /trading\n"
        "Allow: /cash-flow\n"
        "Allow: /invoice\n"
        "Disallow: /admin\n"
        "Disallow: /file-manager\n"
        "Disallow: /licence\n"
        "Disallow: /pricing-admin\n"
        "Disallow: /reset-password\n"
        f"\nSitemap: {_SITE_ORIGIN}/sitemap.xml\n"
    )
    return _TxtResponse(content=body)

_BRAND_FILES = {"accfino-logo.svg": "image/svg+xml", "accfino-logo.png": "image/png"}

def _brand_file(name: str):
    for base in (_DIST, _ROOT / "frontend" / "public"):
        f = base / name
        if f.is_file():
            return _FileResponse(str(f), media_type=_BRAND_FILES[name], headers={"Cache-Control": "public, max-age=86400"})
    raise HTTPException(404, "Not found")

@router.get("/accfino-logo.svg", include_in_schema=False)
def brand_logo_svg():
    return _brand_file("accfino-logo.svg")

@router.get("/accfino-logo.png", include_in_schema=False)
def brand_logo_png():
    return _brand_file("accfino-logo.png")

@router.get("/", include_in_schema=False)
def root():
    return _serve_marketing()

def install_spa_fallbacks(app):
    """Client-side routes + catch-all. MUST be installed last so every API route takes priority."""
    if _DIST.exists() and _APP_INDEX.exists():

        # Public SPA routes (no auth required)
        @app.get("/login",          include_in_schema=False)
        @app.get("/reset-password", include_in_schema=False)
        @app.get("/upgrade",        include_in_schema=False)
        def public_spa_routes():
            return _serve_app()

        # Authenticated SPA routes
        @app.get("/dashboard",      include_in_schema=False)
        @app.get("/reconciliation", include_in_schema=False)
        @app.get("/trading",        include_in_schema=False)
        @app.get("/cash-flow",      include_in_schema=False)
        @app.get("/invoice",        include_in_schema=False)
        @app.get("/admin",          include_in_schema=False)
        @app.get("/file-manager",   include_in_schema=False)
        @app.get("/licence",        include_in_schema=False)
        @app.get("/pricing-admin",  include_in_schema=False)
        def auth_spa_routes():
            return _serve_app()

        # Catch-all for deep SPA paths
        @app.get("/{spa_path:path}", include_in_schema=False)
        def spa_fallback(spa_path: str = ""):
            return _serve_app()
