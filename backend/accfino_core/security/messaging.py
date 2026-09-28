"""
accfino_core.security.messaging
-------------------------------
Delivery of one-time codes by SMS and email, behind one small interface so the
provider is a configuration choice:

  SMS_PROVIDER = console       development only: writes the message to the log / SMS_OUTBOX_FILE
               | messagemedia  Australian provider (MESSAGEMEDIA_API_KEY, MESSAGEMEDIA_API_SECRET)
               | twilio        (TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN, TWILIO_FROM)

  Email uses the same SMTP settings as password reset (SMTP_HOST, SMTP_PORT, SMTP_USER,
  SMTP_PASSWORD, FROM_EMAIL). Without SMTP it falls back to the console outbox.

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


def email_provider() -> str:
    return "smtp" if os.environ.get("SMTP_HOST") else "console"


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
    if email_provider() == "console":
        _outbox("email", to, f"{subject} :: {body}")
        return
    host = os.environ["SMTP_HOST"]
    port = int(os.environ.get("SMTP_PORT", "587"))
    user, pw = os.environ.get("SMTP_USER", ""), os.environ.get("SMTP_PASSWORD", "")
    msg = MIMEText(body, "plain", "utf-8")
    msg["Subject"], msg["From"], msg["To"] = subject, os.environ.get("FROM_EMAIL", user), to
    try:
        with smtplib.SMTP(host, port, timeout=15) as s:
            s.starttls()
            if user:
                s.login(user, pw)
            s.send_message(msg)
    except Exception as e:
        raise DeliveryError(f"Email delivery failed: {e}")
