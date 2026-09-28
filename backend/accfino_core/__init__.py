"""
AccFino platform core (Phase 0 foundation).

install(app) is called once from main_app/react_api.py, immediately BEFORE the
StripApiPrefix middleware is added, so the auth guard runs after the /api prefix
is stripped and sees the real route path. Routers are included before the SPA
catch-all route so their GET endpoints are not shadowed.
"""


def install(app):
    from accfino_core.api import admin_api, audit_api, auth_ext, iam_api, ledger, mfa_api, org, org_identity
    from accfino_core.security.middleware import AuthGuard

    app.include_router(auth_ext.router, prefix="/auth", tags=["auth"])
    app.include_router(mfa_api.router, prefix="/auth/mfa", tags=["auth-mfa"])
    app.include_router(iam_api.sessions_router, prefix="/auth/sessions", tags=["auth-sessions"])
    app.include_router(iam_api.policy_router, prefix="/org/current/access-policy", tags=["organisation"])
    app.include_router(org_identity.router, prefix="/org/current/identity", tags=["organisation-identity"])
    app.include_router(org.router, prefix="/org", tags=["organisation"])
    app.include_router(iam_api.admin_router, prefix="/admin/users", tags=["admin-identity"])
    app.include_router(ledger.router, prefix="/ledger", tags=["ledger"])
    app.include_router(audit_api.router, prefix="/audit", tags=["audit"])
    app.include_router(admin_api.router, prefix="/admin", tags=["admin"])
    app.add_middleware(AuthGuard, fastapi_app=app)
