"""Client portal. Portal users are ordinary platform users who have NO membership of the firm's organisation: they reach the practice ONLY through PcPortalAccess rows.
Every portal call re-evaluates, in the backend, that (a) the access row is active, (b) the client is active, (c) the contact link still grants portal use and has not ended,
(d) the record belongs to that client (and permitted entity). Internal notes, internal messages, tax identifiers and other clients' data are never selected."""
import datetime as dt
import hashlib
import logging
import secrets

import bcrypt
from sqlalchemy import func

import accfino.modules.accounting.public as accounting
from accfino.core import models as m
from accfino.core.identity.user import User
from accfino.modules.practice.models import practice as P
from accfino.modules.practice.services import clients as CL, core, documents as D
from accfino.modules.practice.services.core import Access, Conflict, Forbidden, NotFound, PcError

log = logging.getLogger("accfino.practice.portal")
MAX_ATTEMPTS = 3


def _h(tok: str) -> str:
    return hashlib.sha256((tok or "").encode()).hexdigest()


# ------------------------------------------------------------------ notifications (delivery status + safe retry)
def _send(email, subject, body):
    from accfino.core.security import messaging
    messaging.send_email(email, subject, body)


def notify(db, practice_id: int, *, user_id, audience, subject, email_to=None, email_body=None, client_id=None, ref_kind=None, ref_id=None, dedupe_key, store_body=True) -> P.PcNotification:
    """Idempotent on dedupe_key. Delivery failure never breaks the caller: the row is marked failed (attempts, short error) and can be retried."""
    ex = db.query(P.PcNotification).filter_by(practice_id=practice_id, dedupe_key=dedupe_key).first()
    if ex is not None:
        return ex
    n = P.PcNotification(practice_id=practice_id, user_id=user_id or 0, audience=audience, client_id=client_id, subject=subject[:200], body=(email_body if store_body else None), ref_kind=ref_kind,
                         ref_id=ref_id, dedupe_key=dedupe_key[:200], status="pending")
    db.add(n)
    db.flush()
    if email_to and email_body:
        _deliver(db, n, email_to, email_body)
    else:
        n.status, n.sent_at = "sent", core.now()        # in-app only
    return n


def _deliver(db, n: P.PcNotification, email_to: str, body: str):
    if db.info.get("bulk_dry_run"):                  # a bulk-load PREVIEW is rolled back: it must never send a real e-mail
        n.status = "sent"
        return
    n.attempts += 1
    try:
        with db.begin_nested():
            _send(email_to, n.subject, body)
        n.status, n.sent_at, n.last_error = "sent", core.now(), None
    except Exception as e:                       # noqa: BLE001 - delivery must never break the action
        n.status = "failed"
        n.last_error = (type(e).__name__ + ": " + str(e).replace(body[:40], "")[:200])[:300]
        log.warning("practice notification %s failed: %s", n.id, type(e).__name__)
    db.flush()


def retry_failed(db, practice_id: int) -> dict:
    """Retry failed notifications that kept their (non-secret) body, up to MAX_ATTEMPTS. Invitations are never retried: resend creates a new token."""
    retried = sent = 0
    for n in db.query(P.PcNotification).filter(P.PcNotification.practice_id == practice_id, P.PcNotification.status == "failed", P.PcNotification.attempts < MAX_ATTEMPTS,
                                               P.PcNotification.body.isnot(None)).order_by(P.PcNotification.id):
        u = db.get(User, n.user_id) if n.user_id else None
        if u is None or not u.email:
            continue
        retried += 1
        _deliver(db, n, u.email, n.body)
        sent += n.status == "sent"
    return dict(retried=retried, sent=sent)


def delivery_report(db, a: Access, client_id=None) -> list:
    a.require("portal")
    q = db.query(P.PcNotification).filter(P.PcNotification.practice_id == a.practice_id, P.PcNotification.audience == "client")
    if client_id:
        a.client(client_id)
        q = q.filter(P.PcNotification.client_id == client_id)
    else:
        q = q.filter(P.PcNotification.client_id.in_(a.client_ids()))
    return [dict(id=n.id, client_id=n.client_id, subject=n.subject, status=n.status, attempts=n.attempts, last_error=n.last_error, created_at=core.plain(n.created_at), sent_at=core.plain(n.sent_at))
            for n in q.order_by(P.PcNotification.id.desc()).limit(200)]


# ------------------------------------------------------------------ invitations (staff side)
def _link(db, a: Access, client_id, contact_id) -> P.PcContactLink:
    l = db.query(P.PcContactLink).filter_by(practice_id=a.practice_id, client_id=client_id, contact_id=contact_id).first()
    if l is None:
        raise NotFound("Contact")
    if not l.can_use_portal:
        raise Conflict("This contact is not authorised to use the portal. Update their authority first.", "not_authorised")
    if l.effective_to and l.effective_to < core.today():
        raise Conflict("This contact's authority has ended")
    return l


def invite(db, ctx, a: Access, client_id: int, contact_id: int, entity_ids=None) -> dict:
    a.require("portal")
    c = a.client(client_id, allow_archived=False)
    if c.status != "active":
        raise Conflict("The client is not active")
    _link(db, a, c.id, contact_id)
    contact = db.get(P.PcContact, contact_id)
    if not contact.email:
        raise PcError("The contact has no email address")
    entity_ids = [int(x) for x in (entity_ids or [])]
    for eid in entity_ids:
        if not db.query(P.PcClientEntity.id).filter_by(client_id=c.id, entity_id=eid).first():
            raise PcError("An entity is not linked to this client")
    if contact.user_id and db.query(P.PcPortalAccess.id).filter_by(client_id=c.id, user_id=contact.user_id, status="active").first():
        raise Conflict("This contact already has portal access")
    for old in db.query(P.PcPortalInvite).filter_by(practice_id=a.practice_id, client_id=c.id, contact_id=contact.id, status="pending"):
        old.status = "revoked"                                       # one live invitation per contact
    return _create_invite(db, ctx, a, c, contact, entity_ids, 1)


def _create_invite(db, ctx, a, c, contact, entity_ids, send_count):
    tok = secrets.token_urlsafe(32)
    hours = int(a.settings.get("portal_invite_hours", 72))
    inv = P.PcPortalInvite(practice_id=a.practice_id, client_id=c.id, contact_id=contact.id, email=contact.email.lower(), token_hash=_h(tok), entity_ids=entity_ids,
                           expires_at=core.now() + dt.timedelta(hours=hours), created_by=ctx.user_id, send_count=send_count)
    db.add(inv)
    db.flush()
    body = (f"Hello {contact.full_name},\n\n{a.practice.name} has invited you to its secure client portal for {c.legal_name}.\n\n"
            f"Accept the invitation (single use, valid for {hours} hours): /portal/accept#token={tok}\n\nIf you did not expect this, ignore this message.")
    n = notify(db, a.practice_id, user_id=contact.user_id, audience="client", subject=f"{a.practice.name}: invitation to your client portal", email_to=contact.email, email_body=body,
               client_id=c.id, ref_kind="invite", ref_id=inv.id, dedupe_key=f"invite:{inv.id}", store_body=False)
    core.audit(db, ctx, a.practice_id, "portal.invited", "portal_invite", inv.id, client_id=c.id, contact_id=contact.id, delivery=n.status, send_count=send_count)
    return dict(id=inv.id, client_id=c.id, contact_id=contact.id, email=inv.email, status=inv.status, expires_at=core.plain(inv.expires_at), delivery_status=n.status, send_count=send_count)


def invites(db, a: Access, client_id=None) -> list:
    a.require("portal")
    q = db.query(P.PcPortalInvite).filter(P.PcPortalInvite.practice_id == a.practice_id, P.PcPortalInvite.client_id.in_(a.client_ids()))
    if client_id:
        q = q.filter(P.PcPortalInvite.client_id == client_id)
    out = []
    for i in q.order_by(P.PcPortalInvite.id.desc()).limit(200):
        status = "expired" if i.status == "pending" and i.expires_at < core.now() else i.status
        out.append(dict(id=i.id, client_id=i.client_id, contact_id=i.contact_id, email=i.email, status=status, expires_at=core.plain(i.expires_at), send_count=i.send_count, accepted_at=core.plain(i.accepted_at)))
    return out


def resend(db, ctx, a: Access, invite_id: int) -> dict:
    """Revokes the old token and issues a new one (the old link stops working immediately)."""
    a.require("portal")
    i = db.query(P.PcPortalInvite).filter_by(practice_id=a.practice_id, id=invite_id).first()
    if i is None:
        raise NotFound("Invitation")
    c = a.client(i.client_id, allow_archived=False)
    if i.status == "accepted":
        raise Conflict("This invitation was already accepted")
    _link(db, a, c.id, i.contact_id)
    i.status = "revoked"
    return _create_invite(db, ctx, a, c, db.get(P.PcContact, i.contact_id), i.entity_ids or [], i.send_count + 1)


def revoke_invite(db, ctx, a: Access, invite_id: int) -> dict:
    a.require("portal")
    i = db.query(P.PcPortalInvite).filter_by(practice_id=a.practice_id, id=invite_id).first()
    if i is None:
        raise NotFound("Invitation")
    a.client(i.client_id)
    if i.status != "pending":
        raise Conflict(f"This invitation is {i.status}")
    i.status = "revoked"
    db.flush()
    core.audit(db, ctx, a.practice_id, "portal.invite_revoked", "portal_invite", i.id)
    return dict(id=i.id, status=i.status)


def _valid_invite(db, token: str) -> P.PcPortalInvite:
    i = db.query(P.PcPortalInvite).filter_by(token_hash=_h(token)).first() if token else None
    if i is None or i.status != "pending" or i.expires_at < core.now():
        raise NotFound("Invitation")                   # one answer for unknown / used / revoked / expired: nothing to learn from probing
    c = db.get(P.PcClient, i.client_id)
    if c is None or c.status != "active":
        raise NotFound("Invitation")
    try:
        l = db.query(P.PcContactLink).filter_by(client_id=i.client_id, contact_id=i.contact_id).first()
        if l is None or not l.can_use_portal or (l.effective_to and l.effective_to < core.today()):
            raise NotFound("Invitation")
    except NotFound:
        raise
    return i


def lookup_invite(db, token: str) -> dict:
    i = _valid_invite(db, token)
    pr = db.get(P.PcPractice, i.practice_id)
    c = db.get(P.PcClient, i.client_id)
    exists = db.query(User.id).filter(func.lower(User.email) == i.email).first() is not None
    return dict(practice=pr.name, client=c.legal_name, email=_mask_email(i.email), account_exists=exists, expires_at=core.plain(i.expires_at))


def _mask_email(e):
    n, _, d = e.partition("@")
    return (n[:1] + "***@" + d)


def _grant(db, i: P.PcPortalInvite, user_id: int):
    n = db.query(P.PcPortalInvite).filter(P.PcPortalInvite.id == i.id, P.PcPortalInvite.status == "pending").update({"status": "accepted", "accepted_at": core.now(), "accepted_user_id": user_id})
    if n != 1:
        raise NotFound("Invitation")                   # lost the race: single use
    contact = db.get(P.PcContact, i.contact_id)
    contact.user_id = user_id
    pa = db.query(P.PcPortalAccess).filter_by(practice_id=i.practice_id, client_id=i.client_id, user_id=user_id).first()
    if pa is None:
        db.add(P.PcPortalAccess(practice_id=i.practice_id, client_id=i.client_id, user_id=user_id, contact_id=i.contact_id, entity_ids=i.entity_ids or [], status="active", granted_by=i.created_by))
    else:
        pa.status, pa.revoked_at, pa.revoked_by, pa.entity_ids, pa.contact_id = "active", None, None, i.entity_ids or [], i.contact_id
    db.flush()
    pr = db.get(P.PcPractice, i.practice_id)
    org = db.get(m.Organisation, pr.org_id)
    core.audit(db, core.SystemCtx(org, f"portal-user-{user_id}"), i.practice_id, "portal.invite_accepted", "portal_invite", i.id, client_id=i.client_id, portal_user=user_id)


def accept_new_account(db, token: str, full_name: str, password: str, phone: str) -> dict:
    """Public route: creates the login for an invited email address. The email comes from the invitation, never from the request."""
    i = _valid_invite(db, token)
    if db.query(User.id).filter(func.lower(User.email) == i.email).first():
        raise Conflict("An account with this email already exists. Sign in, then accept the invitation.", "account_exists")
    from accfino.core.security import contact as C
    from accfino.core.security.passwords import validate_new_password
    try:
        _e, ph = C.validate_contact(i.email, phone)
    except C.ContactError as e:
        raise PcError(str(e))
    validate_new_password(password)
    fn = core.text(full_name, "Name", required=True, max_len=200)
    base = i.email
    u = User(username=base, full_name=fn, email=i.email, password=bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode(), phone=ph or "", home_company="")
    db.add(u)
    db.flush()
    try:
        from accfino.core.migrate import ensure_user_security
        ensure_user_security(db, u.id)
    except Exception:                                  # noqa: BLE001
        pass
    _grant(db, i, u.id)
    return dict(accepted=True, email=_mask_email(i.email))


def claim(db, auth_user_id: int, token: str) -> dict:
    """Signed-in user accepts an invitation. Their account email must equal the invited email."""
    i = _valid_invite(db, token)
    u = db.get(User, auth_user_id)
    if u is None or (u.email or "").lower() != i.email:
        raise NotFound("Invitation")
    _grant(db, i, u.id)
    return dict(accepted=True)


# ------------------------------------------------------------------ portal access management (staff)
def accesses(db, a: Access, client_id: int) -> list:
    a.require("portal")
    a.client(client_id)
    return [dict(id=p.id, login_id=p.user_id, contact_id=p.contact_id, entity_ids=p.entity_ids or [], status=p.status, granted_at=core.plain(p.granted_at), revoked_at=core.plain(p.revoked_at))
            for p in db.query(P.PcPortalAccess).filter_by(practice_id=a.practice_id, client_id=client_id).order_by(P.PcPortalAccess.id)]


def revoke_access(db, ctx, a: Access, access_id: int) -> dict:
    a.require("portal")
    p = db.query(P.PcPortalAccess).filter_by(practice_id=a.practice_id, id=access_id).first()
    if p is None:
        raise NotFound("Portal access")
    a.client(p.client_id)
    if p.status != "active":
        raise Conflict("Already revoked")
    p.status, p.revoked_at, p.revoked_by = "revoked", core.now(), ctx.user_id
    for t in db.query(P.PcDownloadTicket).filter_by(practice_id=a.practice_id, user_id=p.user_id, portal=True, used_at=None):
        t.revoked_at = core.now()
    db.flush()
    core.audit(db, ctx, a.practice_id, "portal.access_revoked", "portal_access", p.id, client_id=p.client_id)
    return dict(id=p.id, status=p.status)


# ------------------------------------------------------------------ the portal user's view
class View:
    """Authorisation object for ONE portal user and ONE client. Built fresh on every portal request."""

    def __init__(self, db, user_id: int, client_id: int):
        self.db, self.user_id = db, user_id
        pa = db.query(P.PcPortalAccess).filter_by(user_id=user_id, client_id=client_id, status="active").first() if client_id else None
        if pa is None:
            raise NotFound("Client")
        c = db.get(P.PcClient, client_id)
        if c is None or c.status != "active" or c.practice_id != pa.practice_id:
            raise NotFound("Client")
        link = db.query(P.PcContactLink).filter_by(practice_id=pa.practice_id, client_id=client_id, contact_id=pa.contact_id).first() if pa.contact_id else None
        if link is None or not link.can_use_portal or (link.effective_to and link.effective_to < core.today()):
            raise NotFound("Client")
        self.access, self.client, self.link, self.practice_id = pa, c, link, pa.practice_id
        self.entity_ids = list(pa.entity_ids or [])           # [] = client level (all of this client's records); ids = restricted to those entities
        self.practice = db.get(P.PcPractice, pa.practice_id)
        self.org_id = self.practice.org_id
        try:                                                  # the firm's plan must still include the client portal
            from accfino.core.subscription.service import check
            check(db, core.SystemCtx(db.get(m.Organisation, self.org_id)), ("client-portal",), "GET")
        except Exception as e:                                # noqa: BLE001
            if getattr(e, "status_code", 0) == 402:
                raise NotFound("Client")
            raise

    def allows_entity(self, entity_id) -> bool:
        return not self.entity_ids or entity_id is None or entity_id in self.entity_ids

    def allows_service(self, service_type) -> bool:
        svc = [s for s in (self.link.services or "").split(",") if s]
        return not svc or not service_type or service_type in svc

    def require_approval_right(self):
        if not self.link.can_approve_work:
            raise Forbidden("You are not authorised to approve work for this client")

    def ctx(self):
        org = self.db.get(m.Organisation, self.org_id)
        return core.SystemCtx(org, f"portal-user-{self.user_id}")


def my_clients(db, user_id: int) -> list:
    """Clients this login may open. Computed per request; a revoked/inactive/unauthorised row is simply absent."""
    out = []
    for pa in db.query(P.PcPortalAccess).filter_by(user_id=user_id, status="active").order_by(P.PcPortalAccess.id):
        try:
            v = View(db, user_id, pa.client_id)
        except NotFound:
            continue
        out.append(dict(client_id=v.client.id, name=v.client.legal_name, practice=v.practice.name, entity_ids=v.entity_ids))
    return out


def dashboard(db, v: View) -> dict:
    R = P.PcRequest
    reqs = db.query(R).filter(R.client_id == v.client.id, R.status.in_(("requested", "partially_received", "rejected")))
    docs = db.query(P.PcDocument).filter(P.PcDocument.client_id == v.client.id, P.PcDocument.shared_with_portal.is_(True), P.PcDocument.status == "active")
    if v.entity_ids:
        docs = docs.filter((P.PcDocument.entity_id.is_(None)) | (P.PcDocument.entity_id.in_(v.entity_ids)))
    msgs = db.query(P.PcMessage).filter(P.PcMessage.client_id == v.client.id, P.PcMessage.visibility == "client", P.PcMessage.author_kind == "staff")
    invs = db.query(P.PcInvoice).filter(P.PcInvoice.client_id == v.client.id, P.PcInvoice.visible_to_client.is_(True), P.PcInvoice.status == "issued")
    return dict(client=dict(id=v.client.id, name=v.client.legal_name), practice=v.practice.name, open_requests=reqs.count(), shared_documents=docs.count(), staff_messages=msgs.count(),
                invoices=invs.count(), unread_notifications=db.query(P.PcNotification).filter_by(practice_id=v.practice_id, user_id=v.user_id, audience="client", status="sent", read_at=None).count(),
                can_approve=v.link.can_approve_work)


# ---- documents
def documents(db, v: View, page_no=1, size=25) -> dict:
    q = db.query(P.PcDocument).filter(P.PcDocument.client_id == v.client.id, P.PcDocument.practice_id == v.practice_id, P.PcDocument.shared_with_portal.is_(True), P.PcDocument.status == "active")
    if v.entity_ids:
        q = q.filter((P.PcDocument.entity_id.is_(None)) | (P.PcDocument.entity_id.in_(v.entity_ids)))
    meta, q = core.page(q.order_by(P.PcDocument.id.desc()), page_no, size)
    items = []
    for d in q:
        ver = D._ver_or_none(db, d)
        items.append(dict(id=d.id, title=d.title, category=d.category, file_name=ver.original_name if ver else None, size=ver.size if ver else None, uploaded_at=core.plain(ver.uploaded_at) if ver else None, source=d.source))
    return dict(**meta, items=items)


def _doc_allowed(v: View, d: P.PcDocument) -> bool:
    return d.client_id == v.client.id and d.shared_with_portal and d.status == "active" and v.allows_entity(d.entity_id)


def doc_ticket(db, v: View, doc_id: int) -> dict:
    d = db.query(P.PcDocument).filter_by(practice_id=v.practice_id, id=doc_id).first()
    if d is None or not _doc_allowed(v, d) or not v.link.can_receive_documents and d.source != "client_portal":
        raise NotFound("Document")
    ver = D._ver(db, d)
    return D._issue(db, v.ctx(), v.practice_id, ver, v.user_id, True, int(core.get_settings(v.practice).get("download_ticket_seconds", 120)), d)


def doc_download(db, v: View, ticket: str) -> dict:
    return D.redeem(db, v.ctx(), v.practice_id, ticket, v.user_id, portal=True, allowed=lambda d: _doc_allowed(v, d) and (v.link.can_receive_documents or d.source == "client_portal"))


# ---- requests
def rdict(r: P.PcRequest, items=None, staff=False) -> dict:
    d = dict(id=r.id, client_id=r.client_id, entity_id=r.entity_id, title=r.title, description=r.description, due_date=core.plain(r.due_date), status=r.status, created_at=core.plain(r.created_at))
    if items is not None:
        d["items"] = [dict(id=i.id, description=i.description, response_types=i.response_types, status=i.status, response_text=i.response_text, document_id=i.document_id,
                           review_note=i.review_note, submitted_at=core.plain(i.submitted_at)) for i in items]
    return d


def create_request(db, ctx, a: Access, client_id: int, title: str, items: list, *, description=None, due_date=None, entity_id=None, engagement_id=None) -> dict:
    a.require("portal")
    c = a.client(client_id, allow_archived=False)
    if not items:
        raise PcError("A request needs at least one item")
    if entity_id and not db.query(P.PcClientEntity.id).filter_by(client_id=c.id, entity_id=entity_id).first():
        raise PcError("That entity is not linked to this client")
    r = P.PcRequest(practice_id=a.practice_id, client_id=c.id, entity_id=entity_id, engagement_id=engagement_id, title=core.text(title, "Title", required=True), description=core.text(description, "Description", max_len=2000),
                    due_date=core.parse_date(due_date, "Due date"), created_by=ctx.user_id)
    db.add(r)
    db.flush()
    for it in items:
        rt = it.get("response_types", "file")
        if rt not in ("file", "text", "file,text"):
            raise PcError("response_types must be file, text or file,text")
        db.add(P.PcRequestItem(practice_id=a.practice_id, request_id=r.id, description=core.text(it.get("description"), "Item description", required=True, max_len=300), response_types=rt))
    db.flush()
    core.audit(db, ctx, a.practice_id, "request.created", "request", r.id, client_id=c.id, items=len(items))
    _notify_client(db, a, c, f"New request: {r.title}", f"{a.practice.name} has asked for information. Sign in to your client portal to respond.", f"req:{r.id}:new", "request", r.id)
    return rdict(r, db.query(P.PcRequestItem).filter_by(request_id=r.id).order_by(P.PcRequestItem.id).all())


def _notify_client(db, a_or_practice, c: P.PcClient, subject, body, key, kind, ref_id):
    pid = a_or_practice.practice_id
    for l, ct in db.query(P.PcContactLink, P.PcContact).join(P.PcContact, P.PcContact.id == P.PcContactLink.contact_id).filter(
            P.PcContactLink.client_id == c.id, P.PcContactLink.can_use_portal.is_(True), P.PcContact.user_id.isnot(None)):
        if l.effective_to and l.effective_to < core.today():
            continue
        u = db.get(User, ct.user_id)
        if db.query(P.PcPortalAccess.id).filter_by(client_id=c.id, user_id=ct.user_id, status="active").first() and u and u.email:
            notify(db, pid, user_id=u.id, audience="client", subject=subject, email_to=u.email, email_body=body, client_id=c.id, ref_kind=kind, ref_id=ref_id, dedupe_key=f"{key}:{u.id}")


def _recalc(db, r: P.PcRequest):
    if r.status == "cancelled":
        return
    st = [i.status for i in db.query(P.PcRequestItem).filter_by(request_id=r.id)]
    if all(s == "accepted" for s in st):
        r.status = "accepted"
    elif "pending" in st:
        r.status = "requested" if all(s == "pending" for s in st) else "partially_received"
    elif "submitted" in st:
        r.status = "submitted"
    else:
        r.status = "rejected"


def requests_staff(db, a: Access, client_id=None, status=None) -> list:
    a.require("portal")
    q = db.query(P.PcRequest).filter(P.PcRequest.practice_id == a.practice_id, P.PcRequest.client_id.in_(a.client_ids()))
    if client_id:
        q = q.filter(P.PcRequest.client_id == client_id)
    if status:
        q = q.filter(P.PcRequest.status == status)
    return [rdict(r, db.query(P.PcRequestItem).filter_by(request_id=r.id).order_by(P.PcRequestItem.id).all()) for r in q.order_by(P.PcRequest.id.desc()).limit(200)]


def review_item(db, ctx, a: Access, item_id: int, decision: str, note: str = "") -> dict:
    a.require("portal")
    it = db.query(P.PcRequestItem).filter_by(practice_id=a.practice_id, id=item_id).first()
    if it is None:
        raise NotFound("Request item")
    r = db.get(P.PcRequest, it.request_id)
    a.client(r.client_id)
    if decision not in ("accepted", "rejected"):
        raise PcError("decision must be accepted or rejected")
    if it.status != "submitted":
        raise Conflict(f"Only submitted items can be reviewed (this one is {it.status})")
    if decision == "rejected" and not core.text(note, "Note", required=True, max_len=500):
        raise PcError("Tell the client why")
    it.status, it.review_note, it.reviewed_by, it.reviewed_at = decision, (note or None), ctx.user_id, core.now()
    if decision == "rejected":
        it.status = "pending"                             # goes back to the client with the note; history kept in audit
    _recalc(db, r)
    if decision == "rejected":
        r.status = "rejected"
    db.flush()
    core.audit(db, ctx, a.practice_id, f"request.item_{decision}", "request", r.id, item=it.id)
    if decision == "rejected":
        _notify_client(db, a, db.get(P.PcClient, r.client_id), f"More needed: {r.title}", "Some information needs to be provided again. Sign in to your client portal.", f"req:{r.id}:rej:{it.id}:{core.now().isoformat()[:19]}", "request", r.id)
    return rdict(r, db.query(P.PcRequestItem).filter_by(request_id=r.id).order_by(P.PcRequestItem.id).all())


def cancel_request(db, ctx, a: Access, request_id: int) -> dict:
    a.require("portal")
    r = db.query(P.PcRequest).filter_by(practice_id=a.practice_id, id=request_id).first()
    if r is None:
        raise NotFound("Request")
    a.client(r.client_id)
    if r.status in ("accepted", "cancelled"):
        raise Conflict(f"This request is {r.status}")
    r.status = "cancelled"
    db.flush()
    core.audit(db, ctx, a.practice_id, "request.cancelled", "request", r.id)
    return rdict(r)


def requests_portal(db, v: View) -> list:
    q = db.query(P.PcRequest).filter(P.PcRequest.client_id == v.client.id, P.PcRequest.practice_id == v.practice_id, P.PcRequest.status != "cancelled")
    return [rdict(r, db.query(P.PcRequestItem).filter_by(request_id=r.id).order_by(P.PcRequestItem.id).all()) for r in q.order_by(P.PcRequest.id.desc()) if v.allows_entity(r.entity_id)]


def _item_for(db, v: View, item_id: int):
    it = db.query(P.PcRequestItem).filter_by(practice_id=v.practice_id, id=item_id).first()
    r = db.get(P.PcRequest, it.request_id) if it else None
    if it is None or r.client_id != v.client.id or r.status == "cancelled" or not v.allows_entity(r.entity_id):
        raise NotFound("Request item")
    if it.status in ("accepted",):
        raise Conflict("This item has already been accepted")
    if it.status == "submitted":
        raise Conflict("This item has been submitted and is awaiting review")
    return it, r


def respond_text(db, v: View, item_id: int, text: str) -> dict:
    it, r = _item_for(db, v, item_id)
    if "text" not in it.response_types:
        raise PcError("This item needs a file, not text")
    it.response_text, it.status, it.submitted_at, it.submitted_by = core.text(text, "Response", required=True, max_len=4000), "submitted", core.now(), v.user_id
    return _after_submit(db, v, it, r)


def upload_for_item(db, v: View, item_id: int, filename: str, data: bytes) -> dict:
    it, r = _item_for(db, v, item_id)
    if "file" not in it.response_types:
        raise PcError("This item needs a text answer, not a file")
    a_stub = type("A", (), dict(practice_id=v.practice_id, settings=core.get_settings(v.practice)))()
    doc = D.upload(db, v.ctx(), a_stub, v.client.id, filename, data, title=f"{r.title}: {it.description}"[:200], category="general", entity_id=r.entity_id, shared_with_portal=True, source="client_portal",
                   engagement_id=r.engagement_id, portal_user_id=v.user_id)
    it.document_id, it.status, it.submitted_at, it.submitted_by = doc["id"], "submitted", core.now(), v.user_id
    return _after_submit(db, v, it, r)


def _after_submit(db, v: View, it, r):
    _recalc(db, r)
    db.flush()
    core.audit(db, v.ctx(), v.practice_id, "request.item_submitted", "request", r.id, item=it.id, portal_user=v.user_id)
    if v.client.manager_id:
        notify(db, v.practice_id, user_id=v.client.manager_id, audience="staff", subject=f"Client response: {r.title} ({v.client.legal_name})", client_id=v.client.id, ref_kind="request", ref_id=r.id,
               dedupe_key=f"req:{r.id}:resp:{it.id}:{it.submitted_at.isoformat()}")
    return rdict(r, db.query(P.PcRequestItem).filter_by(request_id=r.id).order_by(P.PcRequestItem.id).all())


# ---- messages: internal vs client-visible
def post_staff(db, ctx, a: Access, client_id: int, body: str, visibility: str, *, request_id=None, job_id=None) -> dict:
    a.require("portal") if visibility == "client" else a.require("view")
    c = a.client(client_id)
    if visibility not in ("internal", "client"):
        raise PcError("visibility must be internal or client")
    if visibility == "client" and c.status != "active":
        raise Conflict("The client is not active")
    msg = P.PcMessage(practice_id=a.practice_id, client_id=c.id, request_id=request_id, job_id=job_id, visibility=visibility, author_kind="staff", author_id=ctx.user_id,
                      body=core.text(body, "Message", required=True, max_len=4000))
    db.add(msg)
    db.flush()
    core.audit(db, ctx, a.practice_id, "message.posted", "message", msg.id, client_id=c.id, visibility=visibility)
    if visibility == "client":
        _notify_client(db, a, c, f"New message from {a.practice.name}", "You have a new message in your client portal.", f"msg:{msg.id}", "message", msg.id)
    return mdict(msg)


def mdict(x: P.PcMessage) -> dict:
    return dict(id=x.id, visibility=x.visibility, author_kind=x.author_kind, author_id=x.author_id, body=x.body, request_id=x.request_id, created_at=core.plain(x.created_at))


def messages_staff(db, a: Access, client_id: int) -> list:
    a.require("view")
    a.client(client_id)
    return [mdict(x) for x in db.query(P.PcMessage).filter_by(practice_id=a.practice_id, client_id=client_id).order_by(P.PcMessage.id)]


def post_portal(db, v: View, body: str, request_id=None) -> dict:
    if request_id and not db.query(P.PcRequest.id).filter_by(id=request_id, client_id=v.client.id).first():
        raise NotFound("Request")
    msg = P.PcMessage(practice_id=v.practice_id, client_id=v.client.id, request_id=request_id, visibility="client", author_kind="client", author_id=v.user_id, body=core.text(body, "Message", required=True, max_len=4000))
    db.add(msg)
    db.flush()
    core.audit(db, v.ctx(), v.practice_id, "message.client_posted", "message", msg.id, client_id=v.client.id, portal_user=v.user_id)
    if v.client.manager_id:
        notify(db, v.practice_id, user_id=v.client.manager_id, audience="staff", subject=f"Client message ({v.client.legal_name})", client_id=v.client.id, ref_kind="message", ref_id=msg.id, dedupe_key=f"msg:{msg.id}:staff")
    return mdict(msg)


def messages_portal(db, v: View) -> list:
    return [mdict(x) for x in db.query(P.PcMessage).filter(P.PcMessage.practice_id == v.practice_id, P.PcMessage.client_id == v.client.id, P.PcMessage.visibility == "client").order_by(P.PcMessage.id)]


# ---- invoices (read only) and consent
def invoices_portal(db, v: View) -> list:
    out = []
    for i in db.query(P.PcInvoice).filter(P.PcInvoice.client_id == v.client.id, P.PcInvoice.practice_id == v.practice_id, P.PcInvoice.visible_to_client.is_(True), P.PcInvoice.status == "issued").order_by(P.PcInvoice.id.desc()):
        s = accounting.sales_document(db, v.org_id, i.accounting_doc_id) or {}
        out.append(dict(id=i.id, number=i.accounting_number, issue_date=core.plain(i.issue_date), due_date=core.plain(i.due_date), total=core.plain(i.total), status=s.get("status"), amount_due=str(s.get("amount_due", ""))))
    return out


def consents_portal(db, v: View) -> list:
    return [
        dict(key=c.key, granted=c.granted, recorded_at=core.plain(c.recorded_at)) for c in db.query(P.PcConsent).filter_by(client_id=v.client.id).order_by(P.PcConsent.id)]


def record_consent_portal(db, v: View, key: str, granted: bool) -> dict:
    import re
    if not key or not re.fullmatch(r"[a-z0-9_:\-]{1,60}", key):
        raise PcError("Consent key is not valid")
    row = P.PcConsent(practice_id=v.practice_id, client_id=v.client.id, contact_id=v.access.contact_id, key=key, granted=bool(granted), source="portal", recorded_by=v.user_id)
    db.add(row)
    db.flush()
    core.audit(db, v.ctx(), v.practice_id, "consent.recorded", "client", v.client.id, key=key, granted=bool(granted), source="portal")
    return dict(key=key, granted=bool(granted))


def notifications_portal(db, v: View) -> list:
    return [dict(id=n.id, subject=n.subject, status=n.status, created_at=core.plain(n.created_at), read=n.read_at is not None)
            for n in db.query(P.PcNotification).filter_by(practice_id=v.practice_id, user_id=v.user_id, audience="client", client_id=v.client.id).order_by(P.PcNotification.id.desc()).limit(50)]


def mark_read(db, v: View, nid: int) -> dict:
    n = db.query(P.PcNotification).filter_by(practice_id=v.practice_id, user_id=v.user_id, id=nid).first()
    if n is None:
        raise NotFound("Notification")
    n.read_at = n.read_at or core.now()
    n.status = "read" if n.status == "sent" else n.status
    return dict(id=n.id, read=True)


def activity_staff(db, a: Access, client_id: int, limit=100) -> list:
    """Portal activity for a client, from the audit log (logins to the portal are not logged here; actions are)."""
    a.require("portal")
    a.client(client_id)
    rows = db.query(m.AuditLog).filter(m.AuditLog.org_id == a.practice.org_id, m.AuditLog.action.like("practice.portal.%") | m.AuditLog.action.like("practice.request.%") | m.AuditLog.action.like("practice.message.%")
                                       | m.AuditLog.action.in_(("practice.document.downloaded", "practice.consent.recorded"))).order_by(m.AuditLog.id.desc()).limit(500).all()
    out = []
    import json
    for r in rows:
        try:
            det = json.loads(r.detail or "{}")
        except ValueError:
            det = {}
        if det.get("client_id") == client_id or (r.entity == "client" and r.entity_id == client_id):
            out.append(dict(at=core.plain(r.created_at) if hasattr(r, "created_at") else None, action=r.action, portal_user=det.get("portal_user"), outcome=det.get("outcome")))
        if len(out) >= limit:
            break
    return out
