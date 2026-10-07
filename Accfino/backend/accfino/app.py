"""
accfino.app - composition root
==============================
The ONLY place that knows every module. It builds the FastAPI app and wires, in a fixed and explicit order:

    1. routers      (Core, then the domain modules; same URLs and the same relative order as before the modular split)
    2. middleware   (CORS -> AuthGuard -> /api prefix stripping -> static-asset shortcut; Starlette runs the LAST one added FIRST)
    3. SPA          (static assets + client-side routes are registered LAST so every API route takes priority)

Run:  python -m uvicorn accfino.app:app --host 0.0.0.0 --port 8001      (from backend/)
Modules never import each other's internals; they only meet here and in accfino.shared.contracts.
"""
import logging
import os

from fastapi import Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.requests import Request
from fastapi.responses import JSONResponse

from accfino.shared.contracts import registry

logger = logging.getLogger("accfino")

registry.load_all()                       # every module's manifest (tables, hooks) is known before any request is served
registry.import_all_models()              # every model class must exist before ANY code touches the ORM (some routes query the database while importing)

app = FastAPI(title="Accfino API", version="2.0")


def _include(module_path: str, attr: str, optional_msg: str = "", **kw):
    """include_router for a router that may be missing in a stripped-down deployment (graceful degradation, as before)."""
    try:
        import importlib
        router = getattr(importlib.import_module(module_path), attr)
        app.include_router(router, **kw)
        return True
    except Exception as e:
        if optional_msg:
            print(f"[accfino] WARNING: {optional_msg}: {e}")
            return False
        raise


# --------------------------------------------------------------------------------------------------- 1. routers --
# Reconciliation: company directory (optional)
if _include("accfino.modules.reconciliation.api.company", "router", "Company DB router not loaded", prefix="/company", tags=["company"]):
    print("[accfino] Company DB router registered OK")

# ---- CORS (extend via CORS_ORIGINS env var, comma-separated)
_extra_origins = [o.strip() for o in os.environ.get("CORS_ORIGINS", "").split(",") if o.strip()]
_CORS_ORIGINS = [
    "http://localhost:3000", "http://127.0.0.1:3000",
    "http://localhost:5173", "http://127.0.0.1:5173",
    "https://www.accfino.com", "https://accfino.com",
] + _extra_origins
app.add_middleware(CORSMiddleware,
                   allow_origins=_CORS_ORIGINS,
                   allow_origin_regex=r"https://.*\.northflank\.app",       # all Northflank preview URLs
                   allow_credentials=True, allow_methods=["*"], allow_headers=["*"])


@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    """Catch any unhandled exception and return JSON instead of crashing."""
    import traceback
    logging.getLogger("accfino").error(f"Unhandled: {exc}\n{traceback.format_exc()}")
    return JSONResponse(status_code=500, content={"detail": f"Server error: {type(exc).__name__}: {str(exc)[:500]}"})


from accfino.core.web import startup as _startup
app.add_event_handler("startup", _startup.on_startup)

# ---- routes that used to be defined inline in main_app/react_api.py, grouped by owner
from accfino.core.identity import admin_reset
from accfino.core.web import health
from accfino.modules.reconciliation.api import routes as reconciliation_routes
app.include_router(reconciliation_routes.router)          # /debug, /profile, /company/capture-who, /reconcile, /sessions, /kb, /rdr, /gl, /gst, /ml, /coa, ...
app.include_router(admin_reset.router)                     # /auth/reset-admin(-full)
app.include_router(health.router)                          # /ready /health /shutdown

# ---- routers that lived in db_app/api (legacy layer), now owned by their module
from accfino.core.subscription.service import feature_gate  # noqa: F401  (used below)
from accfino.modules.accounting.books.legacy import legacy_write_guard as _legacy_guard   # switchable read-only mode for the legacy write endpoints
from accfino.core.api import legacy_auth, password_reset, platform_settings, db_browser, groq_pool
from accfino.modules.reconciliation.api import transactions as rec_transactions
from accfino.modules.accounting.api import invoices as acc_invoices, reports as acc_reports
from accfino.modules.billing.api import stripe_payments

app.include_router(legacy_auth.router, prefix="/auth", tags=["auth"])
app.include_router(rec_transactions.router, prefix="/transactions", tags=["transactions"], dependencies=[Depends(_legacy_guard)])
app.include_router(acc_invoices.router, prefix="/invoice", tags=["invoice"], dependencies=[Depends(_legacy_guard)])
app.include_router(password_reset.router, prefix="/auth", tags=["auth"])
app.include_router(stripe_payments.router, prefix="/payments", tags=["payments"])
app.include_router(groq_pool.router, prefix="/groq-pool", tags=["groq-pool"])
app.include_router(platform_settings.router, prefix="/platform-settings", tags=["platform-settings"])
app.include_router(db_browser.router, prefix="/db-browser", tags=["db-browser"])
app.include_router(acc_reports.router, prefix="/reports", tags=["reports"])

_include("accfino.modules.accounting.api.legacy_documents", "router", "Accounting router not loaded", prefix="/accounting", tags=["accounting"], dependencies=[Depends(_legacy_guard)])
_include("accfino.modules.payroll.api", "router", "Payroll router not loaded", prefix="/payroll", tags=["payroll"])
_include("accfino.modules.taxation.api", "router", "Taxation router not loaded", prefix="/tax", tags=["tax"],
         dependencies=[Depends(feature_gate("tax-returns", "cgt", "gst-bas-ias", "income-tax", "fbt-other-taxes", "tax-planning", "tax-lodgement-ato"))])
_include("accfino.modules.lending.api", "router", "Lending router not loaded", tags=["lending"])

# ---- remaining inline routes (module-owned)
from accfino.modules.cashflow import api as cashflow_api
from accfino.modules.trading import api as trading_api
from accfino.modules.accounting.api import invoice_extractor_api
from accfino.modules.open_banking.api import reconciliation_feed
from accfino.modules.billing.api import gateway_config
from accfino.core.platform_admin import file_manager, module_visibility
from accfino.core.subscription import legacy_licence_api, legacy_pricing_api
app.include_router(trading_api.router)                     # /trading, /stocks
app.include_router(cashflow_api.router)                    # /cashflow
app.include_router(invoice_extractor_api.router)           # /invoice-extractor
app.include_router(reconciliation_feed.router)             # /openbanking
app.include_router(gateway_config.router)                  # /square /stripe /bank-account
app.include_router(file_manager.router)                    # /filemanager
app.include_router(legacy_licence_api.router)              # /licence
app.include_router(legacy_pricing_api.router)              # /pricing, /payments/plans
app.include_router(module_visibility.router)               # /module-visibility

# ---- platform + module routers (formerly accfino_core.install), in the original order
from accfino.routers import install_platform
install_platform(app)

# --------------------------------------------------------------------------------------------------- 2. middleware --
from accfino.core.web.spa import StripApiPrefix, install_spa_fallbacks, install_static_assets
from accfino.core.web import spa
app.add_middleware(StripApiPrefix)

# --------------------------------------------------------------------------------------------------- 3. SPA ------
install_static_assets(app)
app.include_router(spa.router)
install_spa_fallbacks(app)
