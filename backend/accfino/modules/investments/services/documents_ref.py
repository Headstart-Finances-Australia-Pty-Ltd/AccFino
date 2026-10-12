"""Tiny shared helper so property/wealth can count documents without importing the documents service (which imports them)."""
from accfino.modules.investments.models import inv as M


def count(db, ctx, owner_type, owner_id) -> int:
    return db.query(M.InvDocument.id).filter_by(org_id=ctx.org.id, owner_type=owner_type, owner_id=owner_id).count()
