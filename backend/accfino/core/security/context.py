"""FastAPI dependencies: current user, current organisation and role checks."""
from dataclasses import dataclass

from fastapi import Depends, HTTPException, Request
from sqlalchemy.orm import Session

from accfino.core import models as m
from accfino.shared.db.database import get_db

# role -> permissions
#
#   org_admin   ORGANISATION ADMINISTRATION: organisation details and contact information, licence / subscription, users, invitations and
#               access codes, roles, access policy / security, identity management, notifications, transferring the organisation.
#               Held ONLY by the Organisation Admin ("owner" - exactly one per organisation).
#   members     kept as the permission name the user-management endpoints already check; held by the same single role.
#   settings    day-to-day ACCOUNTING configuration (chart of accounts, tax codes, tracking categories, bank-account and document set-up).
#               Not organisation administration; an Accountant keeps it. To make this Organisation-Admin-only as well, remove it from
#               "accountant" and "admin" below.
#
# The legacy "admin" organisation role no longer administers the organisation (it is treated like an accountant); it cannot be newly assigned.
ROLE_PERMS = {
    "owner":      {"read", "post", "settings", "members", "audit", "org_admin"},
    "admin":      {"read", "post", "settings", "audit"},
    "accountant": {"read", "post", "settings", "audit"},
    "bookkeeper": {"read", "post"},
    "payroll":    {"read"},                                  # Payroll Manager (payroll permissions live in accfino.modules.payroll.access)
    "payroll_admin": {"read"},                               # Payroll Administrator
    "employee":   set(),                                      # self-service only: no ledger or books access at all
    "readonly":   {"read"},
}


@dataclass
class OrgContext:
    user_id: int
    username: str
    is_admin: bool
    org: "m.Organisation"
    role: str

    def can(self, perm: str) -> bool:
        return self.is_admin or perm in ROLE_PERMS.get(self.role, set())

    @property
    def is_org_admin(self) -> bool:
        """True for the Organisation Admin of THIS organisation (and for AccFino platform support staff, who may enter any organisation)."""
        return self.is_admin or self.role == m.ADMIN_ROLE

    def require(self, perm: str):
        if not self.can(perm):
            if perm in ("org_admin", "members"):
                raise HTTPException(403, "Only the Organisation Admin can manage this organisation's settings, users, invitations and licence")
            raise HTTPException(403, f"Your role '{self.role}' does not allow '{perm}' in this organisation")

    def require_org_admin(self):
        """Every organisation-level administrative operation starts with this. Server-side, on every such endpoint."""
        self.require("org_admin")


def current_auth(request: Request) -> dict:
    auth = getattr(request.state, "auth", None)
    if not auth:
        raise HTTPException(401, "Not authenticated")
    return auth


def current_org(request: Request, db: Session = Depends(get_db)) -> OrgContext:
    auth = current_auth(request)
    wanted = request.headers.get("x-org-id") or request.query_params.get("org_id")
    # Tenant address (https://<org>.<domain>): the organisation is whatever the address says. A different X-Org-Id / ?org_id= is refused,
    # so changing the id can never move a signed-in user into another tenant.
    from accfino.core.tenancy import service as _tenancy
    slug = _tenancy.request_tenant(request.headers)
    if slug:
        tid = _tenancy.org_id_for_slug(db, slug)
        t_org = db.get(m.Organisation, tid) if tid else None
        if t_org is None or not t_org.is_active:
            raise HTTPException(404, "This organisation address does not exist.")
        if wanted and str(wanted).strip() != str(tid):
            raise HTTPException(403, "That request names a different organisation than this address.")
        wanted = str(tid)
    q = db.query(m.OrgMembership).filter(m.OrgMembership.user_id == auth["user_id"])
    mem = None
    if wanted:
        try:
            wanted_id = int(wanted)
        except ValueError:
            raise HTTPException(400, "Invalid organisation id")
        mem = q.filter(m.OrgMembership.org_id == wanted_id).first()
        if mem is None:
            if auth["is_admin"] and db.get(m.Organisation, wanted_id):
                org = db.get(m.Organisation, wanted_id)
                return OrgContext(auth["user_id"], auth["username"], True, org, "admin")
            raise HTTPException(403, "You are not a member of that organisation")
    else:
        mem = q.filter(m.OrgMembership.is_default.is_(True)).first() or q.first()
    if mem is None:
        raise HTTPException(404, "No organisation found for this user")
    if mem.suspended_at and not auth["is_admin"]:
        raise HTTPException(403, "Your access to this organisation has been suspended by its administrator")
    org = db.get(m.Organisation, mem.org_id)
    if not org or not org.is_active:
        raise HTTPException(404, "Organisation is inactive")
    return OrgContext(auth["user_id"], auth["username"], auth["is_admin"], org, mem.role)
