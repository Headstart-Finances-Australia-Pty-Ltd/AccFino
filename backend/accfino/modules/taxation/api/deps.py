"""Shared API dependencies: the signed-in organisation context, the tax Access object. NOTE: no route or body here may use the names user_id / username
(the platform AuthGuard treats them as 'the caller')."""
from fastapi import Depends, HTTPException
from sqlalchemy.orm import Session

from accfino.core.security.context import OrgContext, current_org
from accfino.modules.taxation.services.core import Access
from accfino.shared.db.database import get_db


def access(ctx: OrgContext = Depends(current_org), db: Session = Depends(get_db)) -> Access:
    a = Access(db, ctx)
    if not a.has_any_access:
        raise HTTPException(403, "You do not have access to Taxation & Compliance in this organisation")
    return a
