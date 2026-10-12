"""Admin Console > Open Banking: the PLATFORM set-up of both bank-feed providers, in one place (AccFino administrator only).

  GET  /admin/open-banking               status of Basiq and OpenFeed (never any secret)
  PUT  /admin/open-banking/basiq         {api_key?, base_url?, version?, clear?}  blank api_key keeps the saved one
  POST /admin/open-banking/basiq/test    ask Basiq for a token with the saved settings
OpenFeed's own steps (generate keys, paste the two IDs) stay on /openfeed/* and are shown in the same Admin screen.
Once set up, an Organisation Admin connects their own accounts from Settings > Open Banking - they never see this."""
from fastapi import APIRouter, Body, Depends, HTTPException, Request
from sqlalchemy.orm import Session

from accfino.modules.open_banking import basiq_setup as OB
from accfino.modules.open_banking import openfeed as OF
from accfino.core.security import audit
from accfino.core.security.context import current_auth
from accfino.core.security.login import client_ip
from accfino.shared.db.database import get_db

router = APIRouter()


def _admin(request: Request) -> dict:
    auth = current_auth(request)
    if not auth.get("is_admin"):
        raise HTTPException(403, "Administrators only")
    return auth


@router.get("")
def status(request: Request, db: Session = Depends(get_db)):
    _admin(request)
    cfg = OF.Cfg(db)
    return {"basiq": OB.basiq_status(db),
            "openfeed": {"ready": cfg.ready, "hasKeys": bool(cfg.app_key and cfg.dpop_key), "hasIds": bool(cfg.client_id and cfg.app_id), "missing": cfg.missing()}}


@router.put("/basiq")
def save_basiq(request: Request, body: dict = Body(...), db: Session = Depends(get_db)):
    auth = _admin(request)
    if OB.basiq_status(db)["locked_by_environment"] and (body.get("api_key") or body.get("clear")):
        raise HTTPException(409, "The Basiq key is set by the server environment (BASIQ_API_KEY) and can't be changed here.")
    try:
        OB.save_basiq(db, api_key=body.get("api_key"), base_url=body.get("base_url"), version=body.get("version"), clear=bool(body.get("clear")))
    except ValueError as e:
        raise HTTPException(422, str(e))
    db.commit()
    audit.write("openbanking.basiq_saved", user_id=auth.get("user_id"), username=auth.get("username"), entity="basiq", ip=client_ip(request))
    return OB.basiq_status(db)


@router.post("/basiq/test")
def test_basiq(request: Request, db: Session = Depends(get_db)):
    _admin(request)
    return OB.test_basiq(db)
