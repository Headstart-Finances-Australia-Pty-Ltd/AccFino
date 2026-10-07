from sqlalchemy import Column, Integer, String, Text, TIMESTAMP, UniqueConstraint
from datetime import datetime
from accfino.shared.db.base import Base


class PlatformSetting(Base):
    """Generic platform-wide (not per-user, not per-organisation) settings
    store used by Admin Console > API Keys for the Database, S3 Bucket
    Storage, System Email (SMTP), Calendly and Meeting Link panels.

    Deliberately a plain (service, key_name) -> key_value table, the same
    shape as GroqKeyPool's "one row per credential" approach elsewhere in
    this app, rather than a bespoke table per integration - a new panel
    just needs a new `service` string, not a migration.

    `service` groups related fields together (e.g. service="database" has
    key_name in {"provider", "connection_url"}; service="system_email" has
    key_name in {"host","port","username","password","from_email"}).
    Values that are genuine secrets (passwords, connection strings, API
    keys) are masked to their last 4 characters before ever leaving the
    server - see db_app/api/platform_settings.py's UNMASKED_FIELDS.
    """
    __tablename__ = "platform_settings"

    id         = Column(Integer, primary_key=True)
    service    = Column(String(50), nullable=False, index=True)
    key_name   = Column(String(100), nullable=False)
    key_value  = Column(Text, nullable=False)
    updated_at = Column(TIMESTAMP, default=datetime.utcnow, onupdate=datetime.utcnow)

    __table_args__ = (
        UniqueConstraint("service", "key_name", name="uq_platform_setting_service_key"),
    )
