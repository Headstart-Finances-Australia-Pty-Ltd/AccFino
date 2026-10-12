"""Platform switch + plan check shared by every module's CSV bulk-load router (the engine itself is accfino.shared.bulkload).
Bulk loading is on unless the platform administrator set SystemSetting 'platform.bulk_import' to 'off', and needs the 'bulk-import' plan feature."""
from fastapi import HTTPException

from accfino.core import models as m


def switched_on(db) -> bool:
    row = db.get(m.SystemSetting, "platform.bulk_import")
    return not (row and (row.value or "").strip().lower() == "off")


def enabled(db, ctx) -> bool:
    from accfino.core.subscription import service as S
    return switched_on(db) and S.is_allowed(S.entitlements(db, ctx.org.id), ("bulk-import",))


def gate(db, ctx):
    from accfino.core.subscription import service as S
    if not switched_on(db):
        raise HTTPException(403, "Bulk data import has been switched off by your platform administrator (Admin > Modules Management).")
    S.check(db, ctx, ("bulk-import",), "POST")
