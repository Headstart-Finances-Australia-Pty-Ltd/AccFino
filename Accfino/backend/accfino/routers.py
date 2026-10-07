"""
accfino.routers
---------------
Includes the platform and module routers that used to be registered by accfino_core.install(app) - same prefixes, same order,
same plan/feature gates - and then adds the server-side AuthGuard. Called by accfino.app (composition code: it may know the modules;
no Core business logic imports a module).
"""
from fastapi import Depends
from fastapi.responses import JSONResponse


def install_platform(app):
    from accfino.core.api import (admin_api, audit_api, auth_ext, force_delete_api, iam_api, mfa_api, org, org_directory_api,
                                  org_identity, public_pricing_api, signup_api, subscription_api)
    from accfino.modules.accounting.api import (assets_api, books_banking, books_docs, books_expenses, books_import, books_legacy,
                                                books_reports, inventory_api, ledger, ledger_tools)
    from accfino.modules.billing.api import billing_api
    from accfino.modules.open_banking.api import admin_api as openbanking_admin_api, openfeed_api
    from accfino.modules.accounting.books.common import BooksError
    from accfino.core.subscription.service import feature_gate
    from accfino.core.security.middleware import AuthGuard

    @app.exception_handler(BooksError)
    async def _books_error(request, exc):      # business-rule violations from the Books modules -> clean JSON errors
        return JSONResponse({"detail": str(exc)}, status_code=exc.status)

    app.include_router(auth_ext.router, prefix="/auth", tags=["auth"])
    app.include_router(mfa_api.router, prefix="/auth/mfa", tags=["auth-mfa"])
    app.include_router(iam_api.sessions_router, prefix="/auth/sessions", tags=["auth-sessions"])
    app.include_router(iam_api.policy_router, prefix="/org/current/access-policy", tags=["organisation"])
    app.include_router(org_identity.router, prefix="/org/current/identity", tags=["organisation-identity"])
    app.include_router(signup_api.tenant_router, prefix="/tenant", tags=["tenancy"])
    app.include_router(signup_api.signup_router, prefix="/signup", tags=["signup"])
    app.include_router(signup_api.invites_router, prefix="/org/current/invites", tags=["organisation"])
    app.include_router(signup_api.admin_tenant_router, prefix="/org/current/tenant", tags=["organisation"])
    app.include_router(subscription_api.org_router, prefix="/org/current/subscription", tags=["subscription"])
    app.include_router(subscription_api.admin_router, prefix="/admin/subscriptions", tags=["admin"])
    app.include_router(org.router, prefix="/org", tags=["organisation"])
    app.include_router(iam_api.admin_router, prefix="/admin/users", tags=["admin-identity"])
    app.include_router(ledger.router, prefix="/ledger", tags=["ledger"], dependencies=[Depends(feature_gate("general-ledger"))])
    app.include_router(ledger_tools.router, prefix="/ledger", tags=["ledger"], dependencies=[Depends(feature_gate("general-ledger"))])
    from accfino.modules.accounting.ledger import scheduler as _sched          # background run of repeating journals that opted in (ACCFINO_SCHEDULER=0 disables)
    app.add_event_handler("startup", _sched.start)
    app.add_event_handler("shutdown", _sched.stop)
    app.include_router(audit_api.router, prefix="/audit", tags=["audit"])
    app.include_router(admin_api.router, prefix="/admin", tags=["admin"])
    app.include_router(force_delete_api.router, prefix="/admin/force-delete", tags=["admin"])
    app.include_router(org_directory_api.router, prefix="/admin/org-directory", tags=["admin"])
    app.include_router(public_pricing_api.router, prefix="/public/pricing", tags=["public"])
    app.include_router(openfeed_api.platform, prefix="/openfeed", tags=["admin"])
    app.include_router(openbanking_admin_api.router, prefix="/admin/open-banking", tags=["admin"])
    app.include_router(billing_api.admin_router, prefix="/admin/billing", tags=["admin"])
    app.include_router(billing_api.org_router, prefix="/org/current/billing", tags=["billing"])
    app.include_router(openfeed_api.org_router, prefix="/org/current/open-banking", tags=["open-banking"])
    app.include_router(openfeed_api.public, prefix="/open-banking/openfeed", tags=["open-banking"])
    # ---- Phase 1: Books & Accounting engine ----
    app.include_router(books_docs.sales_router, prefix="/sales", tags=["sales"], dependencies=[Depends(feature_gate("sales"))])
    app.include_router(books_docs.purchases_router, prefix="/purchases", tags=["purchases"], dependencies=[Depends(feature_gate("purchases"))])
    app.include_router(books_docs.contacts_router, prefix="/contacts", tags=["contacts"], dependencies=[Depends(feature_gate("sales", "purchases"))])
    app.include_router(books_docs.attachments_router, prefix="/attachments", tags=["attachments"])
    app.include_router(books_docs.settings_router, prefix="/org/current/books-settings", tags=["organisation"])
    app.include_router(books_banking.router, prefix="/banking", tags=["banking"], dependencies=[Depends(feature_gate("reconciliation"))])
    app.include_router(books_expenses.router, prefix="/expenses", tags=["expenses"], dependencies=[Depends(feature_gate("expenses"))])
    app.include_router(books_import.router, prefix="/imports", tags=["imports"])
    app.include_router(books_import.admin_router, prefix="/admin/bulk-import", tags=["admin"])
    app.include_router(books_legacy.org_router, prefix="/books/legacy", tags=["books-legacy"])
    app.include_router(books_legacy.admin_router, prefix="/admin/books", tags=["admin"])
    app.include_router(books_reports.sales_reports, prefix="/sales/reports", tags=["sales"], dependencies=[Depends(feature_gate("financial-reports"))])
    app.include_router(books_reports.purchases_reports, prefix="/purchases/reports", tags=["purchases"], dependencies=[Depends(feature_gate("financial-reports"))])
    app.include_router(books_reports.ledger_reports, prefix="/ledger/reports", tags=["ledger"], dependencies=[Depends(feature_gate("financial-reports"))])
    app.include_router(books_banking.coa_rules_router, prefix="/org/current/coa-rules", tags=["organisation"])
    # ---- Phase 3: Fixed assets & Inventory ----
    app.include_router(assets_api.router, prefix="/assets", tags=["assets"], dependencies=[Depends(feature_gate("fixed-assets"))])
    app.include_router(inventory_api.router, prefix="/inventory", tags=["inventory"], dependencies=[Depends(feature_gate("inventory-trading"))])
    app.add_middleware(AuthGuard, fastapi_app=app)
