"""Shared API dependencies: the signed-in organisation context, the payroll Access object and a commit helper."""
from datetime import date
from typing import Optional

from fastapi import Depends, HTTPException
from sqlalchemy.orm import Session

from accfino.core.security.context import OrgContext, current_org
from accfino.modules.payroll.access import Access
from accfino.shared.db.database import get_db


def access(ctx: OrgContext = Depends(current_org), db: Session = Depends(get_db)) -> Access:
    a = Access(db, ctx)
    if not a.has_any_access:
        raise HTTPException(403, "You do not have access to Payroll in this organisation")
    return a


def parse_date(v: Optional[str], name: str) -> Optional[date]:
    if not v:
        return None
    try:
        return date.fromisoformat(v)
    except ValueError:
        raise HTTPException(422, f"{name} must be a date (YYYY-MM-DD)")
