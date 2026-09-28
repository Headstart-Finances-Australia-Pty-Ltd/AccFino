"""FastAPI dependencies: current user, current organisation and role checks."""
from dataclasses import dataclass

from fastapi import Depends, HTTPException, Request
from sqlalchemy.orm import Session

from accfino_core import models as m
from db_app.database import get_db

# role -> permissions
ROLE_PERMS = {
    "owner":      {"read", "post", "settings", "members", "audit"},
    "admin":      {"read", "post", "settings", "members", "audit"},
    "accountant": {"read", "post", "settings", "audit"},
    "bookkeeper": {"read", "post"},
    "payroll":    {"read"},
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

    def require(self, perm: str):
        if not self.can(perm):
            raise HTTPException(403, f"Your role '{self.role}' does not allow '{perm}' in this organisation")


def current_auth(request: Request) -> dict:
    auth = getattr(request.state, "auth", None)
    if not auth:
        raise HTTPException(401, "Not authenticated")
    return auth


def current_org(request: Request, db: Session = Depends(get_db)) -> OrgContext:
    auth = current_auth(request)
    wanted = request.headers.get("x-org-id") or request.query_params.get("org_id")
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
