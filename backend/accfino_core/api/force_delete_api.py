"""/admin/force-delete: the Force delete switch and bulk delete of users / organisations (platform administrators only - the /admin/ prefix is
admin-guarded by the auth middleware, and every call re-checks it).

  GET  /admin/force-delete/settings        {enabled}
  PUT  /admin/force-delete/settings        {enabled}                 tick / untick 'Force delete' in Modules Management
  POST /admin/force-delete/users           {ids:[...], force:bool}   delete the selected users
  POST /admin/force-delete/organisations   {ids:[...], force:bool}   delete the selected organisations AND their users

force=true is only accepted while the switch is on. Each id is processed on its own, so one failure never blocks the rest.
"""
import logging
from typing import List

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy.orm import Session

from accfino_core import force_delete as FD
from accfino_core.security import audit
from accfino_core.security.context import current_auth
from accfino_core.security.login import client_ip
from db_app.database import get_db

router = APIRouter()
log = logging.getLogger("accfino.force_delete")


class SwitchIn(BaseModel):
    enabled: bool


class BulkIn(BaseModel):
    ids: List[int]
    force: bool = False


def _admin(request: Request) -> dict:
    auth = current_auth(request)
    if not auth.get("is_admin"):
        raise HTTPException(403, "Administrators only")
    return auth


@router.get("/settings")
def get_settings(request: Request, db: Session = Depends(get_db)):
    _admin(request)
    return {"enabled": FD.force_delete_enabled(db)}


@router.put("/settings")
def put_settings(body: SwitchIn, request: Request, db: Session = Depends(get_db)):
    auth = _admin(request)
    FD.set_force_delete(db, body.enabled)
    db.commit()
    audit.write("admin.force_delete_switch", user_id=auth["user_id"], username=auth["username"], entity="system", entity_id="force_delete",
                ip=client_ip(request), detail={"enabled": body.enabled})
    return {"enabled": body.enabled}


def _run(kind: str, body: BulkIn, request: Request, db: Session, fn):
    auth = _admin(request)
    ids = list(dict.fromkeys(body.ids))
    if not ids:
        raise HTTPException(422, "Select at least one row")
    if body.force:
        FD.require_force_enabled(db)
    results = []
    for i in ids:
        try:
            info = fn(db, i, actor_id=auth["user_id"], force=body.force)
            db.commit()
            audit.write(f"admin.{kind}_{'force_' if body.force else ''}deleted", user_id=auth["user_id"], username=auth["username"],
                        entity=kind, entity_id=i, ip=client_ip(request), detail=info)
            results.append({"id": i, "ok": True, **info})
        except HTTPException as e:
            db.rollback()
            results.append({"id": i, "ok": False, "error": e.detail})
        except Exception as e:                       # never leave the session in a failed transaction for the next id
            db.rollback()
            log.exception("%s %s delete failed", kind, i)
            results.append({"id": i, "ok": False, "error": f"Delete failed: {str(e).splitlines()[0] if str(e) else type(e).__name__}"})
    ok = sum(1 for r in results if r["ok"])
    return {"deleted": ok, "failed": len(results) - ok, "results": results}


@router.post("/users")
def delete_users(body: BulkIn, request: Request, db: Session = Depends(get_db)):
    return _run("user", body, request, db, FD.delete_user)


@router.post("/organisations")
def delete_organisations(body: BulkIn, request: Request, db: Session = Depends(get_db)):
    return _run("organisation", body, request, db, FD.delete_organisation)
