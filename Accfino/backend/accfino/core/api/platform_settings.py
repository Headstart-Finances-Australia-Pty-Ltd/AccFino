"""
db_app/api/platform_settings.py
-----------------------------------------------------------------------------
REST API for Admin Console > API Keys' platform-wide settings panels:
Database, S3 Bucket Storage, System Email (SMTP), Calendly, and Meeting
Link (Zoom / Teams / Google Meet). Same "admin-only write, no server-side
role check" convention as groq_pool.py and the other admin endpoints in
this app - enforced by the frontend's Guard adminOnly on the /admin route.

Routes (all prefixed /platform-settings in react_api.py):
  GET    /platform-settings                 List all settings (secrets masked)
  POST   /platform-settings                 Save/replace one (service, key_name) pair
  DELETE /platform-settings/{id}            Remove one saved setting
  POST   /platform-settings/test-database   Try a Postgres connection string (never persists)
  POST   /platform-settings/test-s3         Try an S3 bucket connection (never persists)
"""
from datetime import datetime
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from accfino.shared.db.database import get_db
from accfino.core.platform_setting import PlatformSetting

router = APIRouter()

# (service, key_name) pairs that are NOT secrets and are safe to return in
# full (dropdown choices, hostnames, bucket names...). Everything else is
# masked to its last 4 characters, same approach as the Groq key pool.
UNMASKED_FIELDS = {
    ("database", "provider"),
    ("s3", "bucket_name"),
    ("s3", "region"),
    ("s3", "endpoint_url"),
    ("system_email", "host"),
    ("system_email", "port"),
    ("system_email", "username"),
    ("system_email", "from_email"),
    ("calendly", "booking_url"),
    ("calendly", "event_type_uri"),
    ("meeting_link", "platform"),
    ("meeting_link", "link"),
}


def _mask(value: str) -> str:
    if not value:
        return ""
    tail = value[-4:] if len(value) >= 4 else value
    return f"••••{tail}"


def _preview(service: str, key_name: str, value: str) -> str:
    return value if (service, key_name) in UNMASKED_FIELDS else _mask(value)


class SettingIn(BaseModel):
    service: str
    key_name: str
    key_value: str


class SettingOut(BaseModel):
    id: int
    service: str
    key_name: str
    key_preview: str
    updated_at: Optional[str] = None


def _to_out(row: PlatformSetting) -> SettingOut:
    return SettingOut(
        id=row.id, service=row.service, key_name=row.key_name,
        key_preview=_preview(row.service, row.key_name, row.key_value),
        updated_at=row.updated_at.isoformat() if row.updated_at else None,
    )


@router.get("", response_model=List[SettingOut])
def list_settings(service: Optional[str] = None, db: Session = Depends(get_db)):
    q = db.query(PlatformSetting)
    if service:
        q = q.filter(PlatformSetting.service == service)
    return [_to_out(r) for r in q.order_by(PlatformSetting.service, PlatformSetting.key_name).all()]


@router.post("", response_model=SettingOut, status_code=201)
def save_setting(payload: SettingIn, db: Session = Depends(get_db)):
    service = payload.service.strip()
    key_name = payload.key_name.strip()
    value = payload.key_value.strip() if payload.key_value else ""
    if not service or not key_name:
        raise HTTPException(400, "service and key_name are required.")

    existing = db.query(PlatformSetting).filter(
        PlatformSetting.service == service, PlatformSetting.key_name == key_name
    ).first()
    if existing:
        existing.key_value = value
        existing.updated_at = datetime.utcnow()
        db.commit(); db.refresh(existing)
        return _to_out(existing)

    row = PlatformSetting(service=service, key_name=key_name, key_value=value)
    db.add(row); db.commit(); db.refresh(row)
    return _to_out(row)


@router.delete("/{setting_id}")
def delete_setting(setting_id: int, db: Session = Depends(get_db)):
    row = db.query(PlatformSetting).filter(PlatformSetting.id == setting_id).first()
    if not row:
        raise HTTPException(404, "Setting not found.")
    db.delete(row); db.commit()
    return {"ok": True}


# ── Test Connection — never persist anything, just check reachability ──────

class DbTestIn(BaseModel):
    connection_url: str


@router.post("/test-database")
def test_database(payload: DbTestIn):
    url = (payload.connection_url or "").strip()
    if not url:
        return {"ok": False, "message": "Enter a connection string first."}
    try:
        import psycopg2
    except ImportError:
        return {"ok": False, "message": "psycopg2 is not installed on this server, cannot test the connection."}
    try:
        conn = psycopg2.connect(url, connect_timeout=5)
        conn.close()
        return {"ok": True, "message": "Connected successfully."}
    except Exception as e:
        return {"ok": False, "message": f"Could not connect: {e}"}


class S3TestIn(BaseModel):
    access_key_id: str
    secret_access_key: str
    bucket_name: str
    region: Optional[str] = None
    endpoint_url: Optional[str] = None


@router.post("/test-s3")
def test_s3(payload: S3TestIn):
    if not (payload.access_key_id and payload.secret_access_key and payload.bucket_name):
        return {"ok": False, "message": "Access key, secret key and bucket name are all required."}
    try:
        import boto3
        from botocore.exceptions import ClientError, EndpointConnectionError
    except ImportError:
        return {"ok": False, "message": "boto3 is not installed on this server, cannot test the connection."}
    try:
        client = boto3.client(
            "s3",
            aws_access_key_id=payload.access_key_id,
            aws_secret_access_key=payload.secret_access_key,
            region_name=payload.region or None,
            endpoint_url=payload.endpoint_url or None,
        )
        client.head_bucket(Bucket=payload.bucket_name)
        return {"ok": True, "message": f"Connected to bucket '{payload.bucket_name}'."}
    except ClientError as e:
        return {"ok": False, "message": f"Could not reach bucket: {e.response.get('Error', {}).get('Message', str(e))}"}
    except EndpointConnectionError as e:
        return {"ok": False, "message": f"Could not reach endpoint: {e}"}
    except Exception as e:
        return {"ok": False, "message": f"Could not connect: {e}"}
