"""
accfino_core.notifications
--------------------------
Who gets told what.

    ORGANISATION-level communication  ->  the Organisation Admin (their email; their phone for security alerts when switched on)
    INDIVIDUAL account communication  ->  the individual user it is about

Organisation-level means: organisation created, new user joined, organisation settings changed, user / role / access changes, licence nearly full,
licence limit reached, subscription changes and expiry, security alerts (access-code guessing, access-policy changes), admin transfer, announcements.
An ordinary member's email address or phone number is NEVER used for any of these.

Delivery uses accfino_core.security.messaging (SMTP email; SMS provider), so with no SMTP configured messages go to the development outbox.
Sending happens on a small background pool so a slow mail server can't hold up a request; set ACCFINO_NOTIFY_SYNC=1 to send inline (tests).
Failures are logged and audited, and never break the action that triggered them. Message bodies are never written to the audit log.
"""
import logging
import os
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
from typing import Optional

from accfino_core import models as m
from accfino_core import org_admin as OA
from accfino_core.security import audit, messaging
from accfino_core.security import contact as C

log = logging.getLogger("accfino.notifications")
_pool = ThreadPoolExecutor(max_workers=2, thread_name_prefix="accfino-notify")


def _sync() -> bool:
    return os.environ.get("ACCFINO_NOTIFY_SYNC", "").strip().lower() in ("1", "true", "yes")


def _sms_alerts_on() -> bool:
    return os.environ.get("ACCFINO_ORG_SMS_ALERTS", "").strip().lower() in ("1", "true", "yes")


def _deliver(email: Optional[str], subject: str, body: str, sms_to: Optional[str], sms_body: Optional[str]) -> None:
    try:
        if email:
            messaging.send_email(email, subject, body)
    except Exception as e:                                      # never raise into the caller
        log.warning("notification email failed: %s", e)
    try:
        if sms_to and sms_body:
            messaging.send_sms(sms_to, sms_body)
    except Exception as e:
        log.warning("notification SMS failed: %s", e)


def _dispatch(*args) -> None:
    if _sync():
        _deliver(*args)
    else:
        _pool.submit(_deliver, *args)


def _recently_sent(db, org_id: int, kind: str, minutes: int) -> bool:
    since = datetime.utcnow() - timedelta(minutes=minutes)
    return db.query(m.AuditLog.id).filter(m.AuditLog.action == "notify.org_admin", m.AuditLog.org_id == org_id,
                                         m.AuditLog.entity == kind, m.AuditLog.occurred_at > since).first() is not None


# ------------------------------------------------------------------------------------------------ core --
def notify_org_admin(db, org_id: int, kind: str, subject: str, body: str, *, sms: Optional[str] = None, dedupe_minutes: Optional[int] = None) -> bool:
    """Send an ORGANISATION-level message to the Organisation Admin. -> True when it was handed to the mail system.
    `dedupe_minutes` suppresses repeats of the same `kind` (used for alerts that can fire in bursts)."""
    org = db.get(m.Organisation, org_id)
    c = OA.org_contact(db, org_id)
    if org is None or not c["email"] or not C.is_valid_email(c["email"]):
        audit.write("notify.org_admin_unroutable", org_id=org_id, entity=kind, detail={"reason": "no_admin_email"})
        return False
    if dedupe_minutes and _recently_sent(db, org_id, kind, dedupe_minutes):
        return False
    sms_to = c["phone"] if (sms and _sms_alerts_on() and C.is_valid_phone(c["phone"])) else None
    audit.write("notify.org_admin", org_id=org_id, entity=kind, entity_id=c["user_id"], detail={"kind": kind})   # own session: committed, so de-duplication sees it
    _dispatch(c["email"], f"[{org.name}] {subject}", f"Hello {c['name'] or 'Organisation Admin'},\n\n{body}\n\n— AccFino\n(You receive this because you are the Organisation Admin of {org.name}.)",
              sms_to, f"AccFino ({org.name}): {sms}" if sms_to else None)
    return True


def notify_user(db, user, subject: str, body: str, *, kind: str = "account", org_id: Optional[int] = None, to: Optional[str] = None) -> bool:
    """Send an INDIVIDUAL message about the user's own account or actions, to that user (`to` overrides the address, e.g. the OLD address after an email change)."""
    addr = to or getattr(user, "email", None)
    if user is None or not C.is_valid_email(addr):
        return False
    audit.write("notify.user", user_id=user.id, org_id=org_id, entity=kind, detail={"kind": kind})
    _dispatch(addr, subject, f"Hello {user.full_name or user.username},\n\n{body}\n\n— AccFino", None, None)
    return True


# ------------------------------------------------------------------------------------------------ events --
def org_created(db, org, admin_user, slug: Optional[str] = None):
    notify_org_admin(db, org.id, "org_created", "Your organisation has been created",
                     f"{org.name} is set up in AccFino and you are its Organisation Admin.\n\nOrganisation ID: {org.id}\n"
                     + (f"Web address name: {slug}\n" if slug else "")
                     + "\nAs Organisation Admin you manage the organisation's settings, users, access codes and licence under Settings. "
                       "Account, licence, billing and security notices for the organisation are sent to this email address.")


def user_joined(db, org, new_user, role: str):
    notify_org_admin(db, org.id, "user_joined", "A new user joined your organisation",
                     f"{new_user.full_name or new_user.username} ({new_user.email}) joined {org.name} as {role} using an access code you issued.")


def settings_changed(db, org, actor_name: str, what: str):
    notify_org_admin(db, org.id, "settings_changed", "Organisation settings were changed",
                     f"{actor_name} changed: {what}.\n\nIf this was not you, review Settings > IAM Setup and your access codes.")


def member_changed(db, org, actor_name: str, target_user, action: str, detail: str = ""):
    """Organisation-level: tell the Admin. Individual-level: tell the member whose access changed."""
    who = f"{target_user.full_name or target_user.username} ({target_user.email})"
    notify_org_admin(db, org.id, f"member_{action}", f"User access changed: {action.replace('_', ' ')}", f"{actor_name}: {action.replace('_', ' ')} for {who}. {detail}".strip())
    if target_user.id != OA.org_contact(db, org.id)["user_id"]:
        notify_user(db, target_user, f"Your access to {org.name} changed", f"Your Organisation Admin updated your access to {org.name}: {action.replace('_', ' ')}. {detail}".strip(), kind=f"member_{action}", org_id=org.id)


def licence_usage(db, org, st: dict):
    """Call after seats are taken: warns the admin when the licence is nearly full or full."""
    if st.get("licensed") is None:
        return
    left = st["available"]
    if left == 0:
        notify_org_admin(db, org.id, "licence_full", "Licensed user limit reached",
                         f"{org.name} has used all {st['licensed']} licensed users ({st['active']} active, {st['pending']} reserved by access codes). "
                         "New people cannot join until you free a slot or upgrade the plan.", dedupe_minutes=24 * 60)
    elif left <= 1:
        notify_org_admin(db, org.id, "licence_near_limit", "Licensed users nearly full",
                         f"{org.name} has {left} licensed user slot left of {st['licensed']} ({st['active']} active, {st['pending']} reserved by access codes).", dedupe_minutes=24 * 60)


def licence_rejected(db, org_id: int):
    notify_org_admin(db, org_id, "licence_join_refused", "Someone could not join: licence limit reached",
                     "A person with a valid access code was refused because every licensed user slot is in use. Free a slot or upgrade the plan.", dedupe_minutes=6 * 60)


def subscription_changed(db, org_id: int, status: str, plan_name: Optional[str], detail: str = ""):
    name = {"expired": "Licence expired", "cancelled": "Subscription cancelled", "past_due": "Subscription payment is overdue"}.get(status, "Subscription updated")
    notify_org_admin(db, org_id, f"subscription_{status}", name, f"Plan: {plan_name or 'none'}. Status: {status}. {detail}".strip())


def security_alert(db, org_id: int, title: str, detail: str, *, dedupe_minutes: int = 60):
    notify_org_admin(db, org_id, "security_" + title.lower().replace(" ", "_")[:40], f"Security alert: {title}", detail, sms=f"Security alert: {title}", dedupe_minutes=dedupe_minutes)


def admin_transferred(db, org, old_user, new_user):
    notify_user(db, old_user, f"You are no longer the Organisation Admin of {org.name}",
                f"{new_user.full_name or new_user.username} is now the Organisation Admin of {org.name}. You keep access as an Accountant.", kind="admin_transfer", org_id=org.id)
    notify_user(db, new_user, f"You are now the Organisation Admin of {org.name}",
                f"You were made the Organisation Admin of {org.name}. You now manage its settings, users, access codes and licence, and receive its account notices.", kind="admin_transfer", org_id=org.id)
    # (the new Organisation Admin - who is now the organisation's contact - got the message above; the former admin got theirs as an individual)
