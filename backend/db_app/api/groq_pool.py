"""
db_app/api/groq_pool.py
-----------------------------------------------------------------------------
REST API for managing the shared Groq key pool (db_app.models.GroqKeyPool).

Routes (all prefixed /groq-pool in react_api.py):
  GET    /groq-pool               List all keys (masked)
  POST   /groq-pool               Add a new key
  PATCH  /groq-pool/{id}          Enable/disable a key, or change its model override
  DELETE /groq-pool/{id}          Remove a key from the pool
  POST   /groq-pool/models        Fetch the live list of models available to a given key
                                   (queries Groq's own API -- avoids a hardcoded model
                                   list going stale when Groq adds/retires models)
"""
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session
from typing import List, Optional

from db_app.database import get_db
from db_app.models.groq_key_pool import GroqKeyPool

router = APIRouter()


def _mask_key(key_value: str) -> str:
    if not key_value:
        return ""
    tail = key_value[-4:] if len(key_value) >= 4 else key_value
    return f"...{tail}"


class GroqPoolKeyIn(BaseModel):
    key_value: str
    model: Optional[str] = None


class GroqPoolKeyOut(BaseModel):
    id: int
    key_preview: str  # never the real key -- last 4 chars only
    model: Optional[str] = None
    is_active: bool
    consecutive_errors: int
    cooldown_until: Optional[str] = None
    last_used_at: Optional[str] = None
    added_at: Optional[str] = None


def _to_out(e: GroqKeyPool) -> GroqPoolKeyOut:
    return GroqPoolKeyOut(
        id=e.id,
        key_preview=_mask_key(e.key_value),
        model=e.model,
        is_active=e.is_active,
        consecutive_errors=e.consecutive_errors,
        cooldown_until=e.cooldown_until.isoformat() if e.cooldown_until else None,
        last_used_at=e.last_used_at.isoformat() if e.last_used_at else None,
        added_at=e.added_at.isoformat() if e.added_at else None,
    )


@router.get("", response_model=List[GroqPoolKeyOut])
def list_groq_pool(db: Session = Depends(get_db)):
    entries = db.query(GroqKeyPool).order_by(GroqKeyPool.added_at.desc()).all()
    return [_to_out(e) for e in entries]


@router.post("", response_model=GroqPoolKeyOut, status_code=201)
def add_groq_pool_key(payload: GroqPoolKeyIn, db: Session = Depends(get_db)):
    key_value = payload.key_value.strip()
    if not key_value:
        raise HTTPException(400, "API key value is required.")

    existing = db.query(GroqKeyPool).filter(GroqKeyPool.key_value == key_value).first()
    if existing:
        raise HTTPException(409, "This exact key is already in the pool.")

    entry = GroqKeyPool(key_value=key_value, model=(payload.model or "").strip() or None, is_active=True)
    db.add(entry)
    db.commit()
    db.refresh(entry)
    return _to_out(entry)


class GroqPoolKeyPatch(BaseModel):
    is_active: Optional[bool] = None
    model: Optional[str] = None


@router.patch("/{pool_id}", response_model=GroqPoolKeyOut)
def update_groq_pool_key(pool_id: int, payload: GroqPoolKeyPatch, db: Session = Depends(get_db)):
    entry = db.get(GroqKeyPool, pool_id)
    if not entry:
        raise HTTPException(404, "Pool key not found.")
    if payload.is_active is not None:
        entry.is_active = payload.is_active
    if payload.model is not None:
        entry.model = payload.model.strip() or None
    # Reactivating a key clears any lingering cooldown/error streak -- an
    # admin flipping it back on is a deliberate "trust this again" signal.
    if payload.is_active is True:
        entry.consecutive_errors = 0
        entry.cooldown_until = None
    db.commit()
    db.refresh(entry)
    return _to_out(entry)


@router.delete("/{pool_id}")
def delete_groq_pool_key(pool_id: int, db: Session = Depends(get_db)):
    entry = db.get(GroqKeyPool, pool_id)
    if not entry:
        raise HTTPException(404, "Pool key not found.")
    db.delete(entry)
    db.commit()
    return {"message": "Deleted"}


class GroqModelsQuery(BaseModel):
    key_value: str


@router.post("/models")
def list_groq_models_for_key(payload: GroqModelsQuery):
    """Fetches the REAL, current list of models available to a Groq key,
    directly from Groq's own API -- rather than a hardcoded list that
    goes stale the moment Groq adds/retires a model. Also doubles as a
    validity check for a key before it's added to the pool."""
    import requests

    key_value = payload.key_value.strip()
    if not key_value:
        raise HTTPException(400, "API key value is required.")
    try:
        resp = requests.get(
            "https://api.groq.com/openai/v1/models",
            headers={"Authorization": f"Bearer {key_value}"},
            timeout=10,
        )
        resp.raise_for_status()
        data = resp.json()
        models = sorted(m["id"] for m in data.get("data", []) if m.get("id"))
        return {"models": models}
    except requests.exceptions.HTTPError as e:
        status = e.response.status_code if e.response is not None else 0
        if status == 401:
            raise HTTPException(400, "This key was rejected by Groq -- check it's correct and active.")
        raise HTTPException(400, f"Groq returned an error (status {status}) when listing models for this key.")
    except Exception as e:
        raise HTTPException(400, f"Could not reach Groq to list models: {type(e).__name__}")
