"""Practice API dependencies. NOTE: no route or body may use the names user_id / username (the platform AuthGuard treats them as 'the caller'); staff are addressed as staff_id."""
from fastapi import Depends
from sqlalchemy.orm import Session

from accfino.core.security.context import OrgContext, current_auth, current_org
from accfino.modules.practice.services import portal as PT
from accfino.modules.practice.services.core import Access
from accfino.shared.db.database import get_db
from fastapi import Request


def access(ctx: OrgContext = Depends(current_org), db: Session = Depends(get_db)) -> Access:
    return Access(db, ctx)                      # raises 403 unless an active member of THIS organisation's practice


def portal_login(request: Request) -> int:
    """The signed-in login for portal routes. No organisation is involved: access is decided per client by PcPortalAccess."""
    return int(current_auth(request)["user_id"])


def done(db: Session, result):
    db.commit()
    return result
