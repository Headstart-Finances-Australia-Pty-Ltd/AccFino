"""Approval notifications and the pending-approvals count.

Who is asked to approve: the employee's manager (when the manager has a login). An employee with no manager, or whose manager has no login,
goes to the payroll team (organisation owner, Payroll Administrator, Payroll Manager). Nobody is ever asked to approve their own request.

Every notification is stored (the bell in the Payroll screen reads them) and also emailed, best effort: a mail failure never blocks or rolls back the
payroll action. Emails are queued on the session while the action runs and sent by deliver() AFTER the commit, so nobody is emailed about a change
that was rolled back. Set PAYROLL_EMAIL_NOTIFICATIONS=0 to switch emails off (in-app notifications stay on).
"""
import logging
import os
from typing import Iterable, List, Optional

from accfino.modules.payroll.models.payroll import PayEmployee, PayLeaveRequest, PayNotification, PayTimesheet
from accfino.modules.payroll.services.employees import display_name

log = logging.getLogger("accfino.payroll.notify")
STAFF_ROLES = ("owner", "payroll_admin", "payroll")


# -- who approves ------------------------------------------------------------------------------------------------------------------
def _manager(db, e: PayEmployee) -> Optional[PayEmployee]:
    return db.get(PayEmployee, e.manager_id) if e.manager_id else None


def approver_user_ids(db, org_id: int, e: PayEmployee) -> List[int]:
    """Logins that can decide this employee's timesheets and leave (never the employee themselves)."""
    from accfino.core import models as m
    mgr = _manager(db, e)
    ids = [mgr.user_id] if (mgr is not None and mgr.user_id) else []
    if not ids:
        ids = [uid for (uid,) in db.query(m.OrgMembership.user_id).filter(m.OrgMembership.org_id == org_id, m.OrgMembership.role.in_(STAFF_ROLES))]
    return [i for i in dict.fromkeys(ids) if i != e.user_id]


def approver_label(db, e: PayEmployee) -> str:
    """Plain-words answer to 'who approves my requests?' (shown to the employee)."""
    mgr = _manager(db, e)
    if mgr is not None and mgr.user_id:
        return display_name(mgr)
    return "the payroll team"


# -- creating notifications ---------------------------------------------------------------------------------------------------------
def queue(db, ctx, recipients: Iterable[int], kind: str, title: str, body: str = "", entity_type: str = "", entity_id: Optional[int] = None,
          tab: str = "timeleave", sub: str = "") -> int:
    """Store a notification for each recipient login (except the person acting) and queue the emails. Returns how many were stored."""
    from accfino.core.identity.user import User
    n = 0
    for uid in dict.fromkeys(recipients):
        if not uid or uid == ctx.user_id:
            continue
        row = PayNotification(org_id=ctx.org.id, recipient_id=uid, kind=kind, title=title[:200], body=(body or "")[:500] or None, entity_type=entity_type or None,
                              entity_id=entity_id, link_tab=tab or None, link_sub=sub or None)
        db.add(row)
        db.flush()
        n += 1
        u = db.get(User, uid)
        if u is not None and u.email:
            db.info.setdefault("pay_outbox", []).append((row.id, u.email, f"[{ctx.org.name}] {title}", _email_body(ctx, u, title, body)))
    return n


def _email_body(ctx, user, title: str, body: str) -> str:
    base = (os.environ.get("APP_BASE_URL") or "").rstrip("/")
    where = f"\nOpen Payroll: {base}/payroll\n" if base else "\nOpen Payroll in AccFino to take a look.\n"
    return f"Hi {(user.full_name or user.username or '').split(' ')[0] or 'there'},\n\n{title}\n{body or ''}\n{where}\n{ctx.org.name} · AccFino Payroll"


def deliver(db) -> None:
    """Send the queued emails. Call AFTER db.commit(); never raises."""
    box = db.info.pop("pay_outbox", [])
    if not box or os.environ.get("PAYROLL_EMAIL_NOTIFICATIONS", "1") == "0":
        return
    try:
        from accfino.core.security.messaging import send_email
    except Exception:                                                    # pragma: no cover - messaging unavailable
        return
    sent = []
    for nid, to, subject, text in box:
        try:
            send_email(to, subject, text)
            sent.append(nid)
        except Exception as ex:
            log.warning("Payroll notification email to %s failed: %s", to, ex)
    if sent:
        try:
            db.query(PayNotification).filter(PayNotification.id.in_(sent)).update({"emailed": True}, synchronize_session=False)
            db.commit()
        except Exception as ex:                                          # pragma: no cover
            db.rollback()
            log.warning("Could not mark notifications as emailed: %s", ex)


# -- the bell ------------------------------------------------------------------------------------------------------------------------
def _ser(n: PayNotification) -> dict:
    return {"id": n.id, "kind": n.kind, "title": n.title, "body": n.body, "tab": n.link_tab, "sub": n.link_sub, "entity_type": n.entity_type,
            "entity_id": n.entity_id, "is_read": bool(n.is_read), "created_at": n.created_at.isoformat() if n.created_at else None}


def _mine(db, ctx):
    return db.query(PayNotification).filter(PayNotification.org_id == ctx.org.id, PayNotification.recipient_id == ctx.user_id)


def list_mine(db, ctx, limit: int = 30) -> dict:
    rows = _mine(db, ctx).order_by(PayNotification.id.desc()).limit(limit).all()
    return {"unread": _mine(db, ctx).filter(PayNotification.is_read.is_(False)).count(), "items": [_ser(r) for r in rows]}


def mark_read(db, ctx, notification_id: Optional[int] = None) -> int:
    """Mark one notification (or all, when no id) as read. Only the recipient's own rows are ever touched."""
    q = _mine(db, ctx).filter(PayNotification.is_read.is_(False))
    if notification_id is not None:
        q = q.filter(PayNotification.id == notification_id)
    return q.update({"is_read": True}, synchronize_session=False)


# -- what is waiting for me to approve --------------------------------------------------------------------------------------------
def pending_approvals(db, ctx, access) -> dict:
    """Submitted timesheets and pending leave requests the caller may decide (their reports', or everyone's for payroll staff), never their own."""
    own = access.employee.id if access.employee else None
    out = {"timesheets": 0, "leave": 0}
    for key, cap, model, status in (("timesheets", "timesheets_approve", PayTimesheet, "submitted"), ("leave", "leave_approve", PayLeaveRequest, "pending")):
        sc = access.scope(cap)
        if sc is not None and not (set(sc) - {own}):
            continue                                                     # an ordinary employee, or a manager with no reports: nothing to decide
        q = db.query(model.id).filter(model.org_id == ctx.org.id, model.status == status)
        if sc is not None:
            q = q.filter(model.employee_id.in_(sc))
        if own is not None:
            q = q.filter(model.employee_id != own)
        out[key] = q.count()
    out["total"] = out["timesheets"] + out["leave"]
    return out
