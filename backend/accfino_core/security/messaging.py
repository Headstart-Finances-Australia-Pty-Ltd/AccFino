"""
accfino_core.security.messaging
-------------------------------
Delivery of one-time codes by SMS and email, behind one small interface so the
provider is a configuration choice:

  SMS_PROVIDER = console       development only: writes the message to the log / SMS_OUTBOX_FILE
               | messagemedia  Australian provider (MESSAGEMEDIA_API_KEY, MESSAGEMEDIA_API_SECRET)
               | twilio        (TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN, TWILIO_FROM)

  Email uses the System Email settings saved in Admin Console > API Keys (database), falling back to the
  SMTP_HOST / SMTP_PORT / SMTP_USER / SMTP_PASSWORD / FROM_EMAIL environment variables. Without either it uses the console outbox.

The console provider must never be used in production (the admin security checklist flags it).
"""
import json
import logging
import os
import smtplib
from datetime import datetime
from email.mime.text import MIMEText

import httpx

log = logging.getLogger("accfino.messaging")


class DeliveryError(RuntimeError):
    pass


def sms_provider() -> str:
    return os.environ.get("SMS_PROVIDER", "console").strip().lower()


def _db_email_settings() -> dict:
    """System Email (SMTP) saved in Admin Console > API Keys (platform_settings, service='system_email').
    Returns {} when none are saved or the database can't be read - callers then fall back to the environment."""
    try:
        from db_app.database import SessionLocal
        from db_app.models.platform_setting import PlatformSetting
        db = SessionLocal()
        try:
            rows = db.query(PlatformSetting).filter(PlatformSetting.service == "system_email").all()
            return {r.key_name: (r.key_value or "").strip() for r in rows if (r.key_value or "").strip()}
        finally:
            db.close()
    except Exception as e:                                       # never break sending because the lookup failed
        log.warning("could not read system_email settings from the database: %s", e)
        return {}


def smtp_settings() -> dict:
    """Effective SMTP settings. Admin Console values win; environment variables (SMTP_*) are the fallback.
    -> {} when no host is configured anywhere (development outbox)."""
    d = _db_email_settings()
    host = d.get("host") or os.environ.get("SMTP_HOST", "").strip()
    if not host:
        return {}
    user = d.get("username") or os.environ.get("SMTP_USER", "").strip()
    try:
        port = int(d.get("port") or os.environ.get("SMTP_PORT") or 587)
    except ValueError:
        port = 587
    return {"host": host, "port": port, "user": user,
            "password": d.get("password") or os.environ.get("SMTP_PASSWORD", ""),
            "from_email": d.get("from_email") or os.environ.get("FROM_EMAIL", "").strip() or user}


def email_provider() -> str:
    return "smtp" if smtp_settings() else "console"


def _outbox(channel: str, to: str, body: str):
    log.warning("[DEV %s OUTBOX] to=%s :: %s", channel.upper(), to, body)
    path = os.environ.get("SMS_OUTBOX_FILE")
    if path:
        with open(path, "a", encoding="utf-8") as f:
            f.write(json.dumps({"at": datetime.utcnow().isoformat(), "channel": channel, "to": to, "body": body}) + "\n")


def send_sms(to_e164: str, body: str) -> None:
    p = sms_provider()
    try:
        if p == "console":
            _outbox("sms", to_e164, body)
        elif p == "messagemedia":
            r = httpx.post("https://api.messagemedia.com/v1/messages",
                           auth=(os.environ["MESSAGEMEDIA_API_KEY"], os.environ["MESSAGEMEDIA_API_SECRET"]),
                           json={"messages": [{"content": body, "destination_number": to_e164, "format": "SMS"}]},
                           timeout=15)
            if r.status_code >= 300:
                raise DeliveryError(f"MessageMedia returned {r.status_code}")
        elif p == "twilio":
            sid = os.environ["TWILIO_ACCOUNT_SID"]
            r = httpx.post(f"https://api.twilio.com/2010-04-01/Accounts/{sid}/Messages.json",
                           auth=(sid, os.environ["TWILIO_AUTH_TOKEN"]),
                           data={"To": to_e164, "From": os.environ["TWILIO_FROM"], "Body": body}, timeout=15)
            if r.status_code >= 300:
                raise DeliveryError(f"Twilio returned {r.status_code}")
        else:
            raise DeliveryError(f"Unknown SMS_PROVIDER '{p}'")
    except KeyError as e:
        raise DeliveryError(f"SMS provider '{p}' is missing setting {e}")
    except httpx.HTTPError as e:
        raise DeliveryError(f"SMS delivery failed: {e}")


def send_email(to: str, subject: str, body: str) -> None:
    cfg = smtp_settings()
    if not cfg:
        _outbox("email", to, f"{subject} :: {body}")
        return
    msg = MIMEText(body, "plain", "utf-8")
    msg["Subject"], msg["From"], msg["To"] = subject, cfg["from_email"], to
    try:
        if cfg["port"] == 465:                                   # implicit TLS
            with smtplib.SMTP_SSL(cfg["host"], 465, timeout=15) as s:
                if cfg["user"]:
                    s.login(cfg["user"], cfg["password"])
                s.send_message(msg)
        else:                                                    # STARTTLS (587 / 25)
            with smtplib.SMTP(cfg["host"], cfg["port"], timeout=15) as s:
                s.ehlo()
                s.starttls()
                s.ehlo()
                if cfg["user"]:
                    s.login(cfg["user"], cfg["password"])
                s.send_message(msg)
    except Exception as e:
        log.error("SMTP send to %s via %s:%s failed: %s", to, cfg["host"], cfg["port"], e)
        raise DeliveryError(f"Email delivery failed: {e}")
