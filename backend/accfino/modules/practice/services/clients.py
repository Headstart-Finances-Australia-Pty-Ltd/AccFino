"""Clients & Entities: client register, tax identifiers (sealed + masked), entities, structures, contacts and authority, consent, duplicates, CSV import/export."""
import csv
import hashlib
import hmac
import io
import re
from typing import Optional

from sqlalchemy import func, or_

from accfino.core.security import secrets as _secrets
from accfino.modules.practice.engine import dedupe as DD, ids as IDS
from accfino.modules.practice.models import practice as P
from accfino.modules.practice.services import core
from accfino.modules.practice.services.core import Access, Conflict, Forbidden, NotFound, PcError

EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
COMM = ("email", "phone", "portal", "post")
REL_KINDS = ("owns", "controls", "trustee_of", "partner_in", "subsidiary_of")
CONTACT_ROLES = ("contact", "director", "trustee", "partner", "shareholder", "accountant", "other")
SERVICE_TYPES = ("bookkeeping", "financial_statements", "tax_return", "bas", "payroll", "advisory", "other")
IMPORT_COLUMNS = ["ref", "client_type", "legal_name", "preferred_name", "email", "phone", "abn", "postal_address"]


def _hash_key() -> bytes:
    from accfino.core.security import tokens
    return ("pc-ident|" + tokens._secret()).encode()


def ident_hash(kind: str, digits: str) -> str:
    return hmac.new(_hash_key(), f"{kind}:{digits}".encode(), hashlib.sha256).hexdigest()


# ------------------------------------------------------------------------------------------------------------------------------ identifiers
def set_identifier(db, ctx, a: Access, owner_kind: str, owner_id: int, kind: str, value, *, verified=False, verified_source=None) -> dict:
    a.require("tax_ids")
    _owner(db, a, owner_kind, owner_id)
    try:
        digits = IDS.validate(kind, value)
    except ValueError as e:
        raise PcError(str(e))
    if owner_kind == "entity":
        et = db.get(P.PcEntity, owner_id).entity_type
        if kind not in IDS.ENTITY_RULES[et]["allowed"]:
            raise PcError(f"A {et.replace('_', ' ')} cannot carry a {kind.upper()}")
    h = ident_hash(kind, digits)
    row = db.query(P.PcIdentifier).filter_by(practice_id=a.practice_id, owner_kind=owner_kind, owner_id=owner_id, kind=kind).first()
    other = db.query(P.PcIdentifier).filter(P.PcIdentifier.practice_id == a.practice_id, P.PcIdentifier.kind == kind, P.PcIdentifier.value_hash == h,
                                            ~((P.PcIdentifier.owner_kind == owner_kind) & (P.PcIdentifier.owner_id == owner_id))).first()
    if other is not None:
        raise Conflict(f"Another {other.owner_kind} in this practice already has that {kind.upper()} - review it as a possible duplicate", "duplicate_identifier")
    if row is None:
        row = P.PcIdentifier(practice_id=a.practice_id, owner_kind=owner_kind, owner_id=owner_id, kind=kind, sealed="", last_digits="", value_hash=h)
        db.add(row)
    row.sealed, row.last_digits, row.value_hash = _secrets.seal(digits), digits[-3:], h
    row.verified = bool(verified and verified_source)
    row.verified_source = core.text(verified_source, "Verification source", max_len=200) if row.verified else None
    row.verified_at, row.verified_by = (core.now(), ctx.user_id) if row.verified else (None, None)
    db.flush()
    core.audit(db, ctx, a.practice_id, "identifier.set", owner_kind, owner_id, kind=kind, verified=row.verified)     # never the value
    return _ident_dict(row, a)


def _ident_dict(r, a: Access, reveal=False) -> dict:
    d = dict(kind=r.kind, masked=IDS.mask(r.kind, r.last_digits), verified=r.verified, verified_source=r.verified_source, label="Verified" if r.verified else "Unverified (entered by staff)")
    if reveal and a.can("tax_ids"):
        d["value"] = _secrets.unseal(r.sealed)
    return d


def identifiers(db, a: Access, owner_kind: str, owner_id: int) -> list:
    """Masked identifiers. Staff without 'tax_ids' still see that an identifier exists but only its kind."""
    rows = db.query(P.PcIdentifier).filter_by(practice_id=a.practice_id, owner_kind=owner_kind, owner_id=owner_id).order_by(P.PcIdentifier.kind).all()
    if not a.can("tax_ids"):
        return [dict(kind=r.kind, masked="***", verified=r.verified) for r in rows]
    return [_ident_dict(r, a) for r in rows]


def reveal_identifier(db, ctx, a: Access, owner_kind: str, owner_id: int, kind: str) -> dict:
    a.require("tax_ids")
    _owner(db, a, owner_kind, owner_id)
    r = db.query(P.PcIdentifier).filter_by(practice_id=a.practice_id, owner_kind=owner_kind, owner_id=owner_id, kind=kind).first()
    if r is None:
        raise NotFound("Identifier")
    core.audit(db, ctx, a.practice_id, "identifier.revealed", owner_kind, owner_id, kind=kind)
    return _ident_dict(r, a, reveal=True)


def _owner(db, a: Access, owner_kind: str, owner_id: int):
    if owner_kind == "client":
        return a.client(owner_id)
    if owner_kind == "entity":
        return entity_row(db, a, owner_id)
    raise PcError("owner_kind must be client or entity")


# ------------------------------------------------------------------------------------------------------------------------------ clients
def _next_ref(db, a: Access, prefix="C") -> str:
    n = db.query(func.count(P.PcClient.id)).filter_by(practice_id=a.practice_id).scalar() + 1
    while db.query(P.PcClient.id).filter_by(practice_id=a.practice_id, ref=f"{prefix}-{n:04d}").first():
        n += 1
    return f"{prefix}-{n:04d}"


def cdict(c: P.PcClient, db=None, a: Access = None, *, detail=False) -> dict:
    d = dict(id=c.id, ref=c.ref, client_type=c.client_type, legal_name=c.legal_name, preferred_name=c.preferred_name, email=c.email, phone=c.phone, status=c.status,
             manager_id=c.manager_id, preparer_id=c.preparer_id, reviewer_id=c.reviewer_id, team_id=c.team_id, service_lines=[s for s in (c.service_lines or "").split(",") if s],
             comm_pref=c.comm_pref, linked_org_id=c.linked_org_id, updated_at=core.plain(c.updated_at), archived_at=core.plain(c.archived_at))
    if detail:
        d.update(postal_address=c.postal_address, registered_address=c.registered_address, important_dates=c.important_dates or [], notes=c.notes, created_at=core.plain(c.created_at))
    return d


def _check_staff(a: Access, **ids):
    for label, uid in ids.items():
        a.require_member_user(uid, label.replace("_", " ").capitalize())


def _services(v) -> Optional[str]:
    items = [s.strip() for s in (v if isinstance(v, (list, tuple)) else str(v or "").split(",")) if str(s).strip()]
    bad = [s for s in items if s not in SERVICE_TYPES]
    if bad:
        raise PcError(f"Unknown service type(s): {', '.join(bad)}. Use: {', '.join(SERVICE_TYPES)}")
    return ",".join(dict.fromkeys(items)) or None


def _apply(c: P.PcClient, body: dict, a: Access, creating=False):
    def has(k):
        return k in body
    if creating or has("client_type"):
        t = body.get("client_type", c.client_type)
        if t not in P.CLIENT_TYPES:
            raise PcError("client_type must be individual or organisation")
        if not creating and t != c.client_type:
            raise PcError("The client type cannot be changed after creation; create a new client instead")
        c.client_type = t
    if creating or has("legal_name"):
        c.legal_name = core.text(body.get("legal_name"), "Legal name", required=True)
    for k, mx in (("preferred_name", 200), ("phone", 40), ("postal_address", 500), ("registered_address", 500), ("notes", 4000)):
        if has(k):
            setattr(c, k, core.text(body[k], k, max_len=mx))
    if has("email"):
        e = core.text(body["email"], "Email")
        if e and not EMAIL.match(e):
            raise PcError("Email address is not valid")
        c.email = e
    if has("comm_pref"):
        if body["comm_pref"] not in COMM:
            raise PcError(f"comm_pref must be one of {', '.join(COMM)}")
        c.comm_pref = body["comm_pref"]
    if has("service_lines"):
        c.service_lines = _services(body["service_lines"])
    if has("important_dates"):
        out = []
        for x in body["important_dates"] or []:
            out.append(dict(label=core.text(x.get("label"), "Date label", required=True, max_len=80), date=core.parse_date(x.get("date"), "Important date").isoformat()))
        c.important_dates = out
    _check_staff(a, manager=body.get("manager_id"), preparer=body.get("preparer_id"), reviewer=body.get("reviewer_id"))
    new_prep = (body["preparer_id"] or None) if has("preparer_id") else c.preparer_id
    new_rev = (body["reviewer_id"] or None) if has("reviewer_id") else c.reviewer_id
    if new_prep and new_prep == new_rev:                         # validate BEFORE mutating, so a skipped client in a bulk run is left untouched
        raise PcError("The preparer and the reviewer must be different people")
    if has("team_id") and body["team_id"] and not a.db.query(P.PcTeam.id).filter_by(practice_id=a.practice_id, id=body["team_id"]).first():
        raise PcError("Team not found in this practice")
    for k in ("manager_id", "preparer_id", "reviewer_id"):
        if has(k):
            setattr(c, k, body[k] or None)
    if has("team_id"):
        c.team_id = body["team_id"] or None


def _candidates(db, a: Access, cand: dict, *, exclude_id=None, kind="client") -> list:
    cfg = a.settings.get("dedupe") or {}
    out = []
    Mdl = P.PcClient if kind == "client" else P.PcEntity
    nm = Mdl.legal_name if kind == "client" else Mdl.name
    rows = db.query(Mdl).filter(Mdl.practice_id == a.practice_id)
    if exclude_id:
        rows = rows.filter(Mdl.id != exclude_id)
    idmap = {}
    for r in db.query(P.PcIdentifier).filter_by(practice_id=a.practice_id, owner_kind=kind):
        idmap.setdefault(r.owner_id, {})[r.kind] = r.value_hash
    for r in rows:
        theirs = dict(name=getattr(r, "legal_name", None) or r.name, email=getattr(r, "email", None), phone=getattr(r, "phone", None), identifiers=idmap.get(r.id, {}))
        res = DD.compare(cand, theirs, cfg)
        if res["reasons"]:
            out.append(dict(id=r.id, ref=r.ref, name=theirs["name"], status=r.status, **res))
    return sorted(out, key=lambda x: -x["score"])[:10]


def create_client(db, ctx, a: Access, body: dict, *, allow_duplicate=False) -> dict:
    a.require("clients_edit")
    c = P.PcClient(practice_id=a.practice_id, ref="tmp", client_type="", legal_name="", created_by=ctx.user_id)
    _apply(c, body, a, creating=True)
    ref = core.text(body.get("ref"), "Reference", max_len=40) or _next_ref(db, a)
    if db.query(P.PcClient.id).filter_by(practice_id=a.practice_id, ref=ref).first():
        raise Conflict(f"Client reference {ref} is already used")
    c.ref = ref
    idents = {}
    for k in IDS.KINDS:
        if body.get(k):
            try:
                idents[k] = ident_hash(k, IDS.validate(k, body[k]))
            except ValueError as e:
                raise PcError(str(e))
    cands = _candidates(db, a, dict(name=c.legal_name, email=c.email, phone=c.phone, identifiers=idents))
    strong = [x for x in cands if x["score"] >= 0.9]
    if strong and not allow_duplicate:
        raise Conflict("Possible duplicate client: " + "; ".join(f"{x['ref']} {x['name']} ({', '.join(x['reasons'])})" for x in strong[:3]) + ". Review it, or repeat the request with allow_duplicate to create it anyway.", "possible_duplicate")
    db.add(c)
    db.flush()
    for k in IDS.KINDS:
        if body.get(k):
            set_identifier(db, ctx, a, "client", c.id, k, body[k])
    core.audit(db, ctx, a.practice_id, "client.created", "client", c.id, ref=c.ref, duplicates_overridden=bool(strong))
    out = cdict(c, db, a, detail=True)
    out["duplicate_candidates"] = cands
    return out


def update_client(db, ctx, a: Access, client_id: int, body: dict) -> dict:
    """Partial update: only the supplied fields change."""
    a.require("clients_edit")
    c = a.client(client_id)
    if c.status == "archived":
        raise Conflict("This client is archived. Reactivate it before editing.")
    before = cdict(c)
    _apply(c, body, a)
    db.flush()
    after = cdict(c)
    changed = sorted(k for k in after if after[k] != before[k] and k != "updated_at")
    core.audit(db, ctx, a.practice_id, "client.updated", "client", c.id, fields=changed)
    return cdict(c, db, a, detail=True)


def assign(db, ctx, a: Access, client_ids, *, manager_id=..., preparer_id=..., reviewer_id=..., team_id=...) -> dict:
    """Bulk (or single) assignment. Out-of-scope clients are reported, not touched. Takes effect on access immediately because scope is evaluated per request."""
    a.require("clients_edit")
    body = {k: v for k, v in dict(manager_id=manager_id, preparer_id=preparer_id, reviewer_id=reviewer_id, team_id=team_id).items() if v is not ...}
    if not body:
        raise PcError("Nothing to assign")
    done, skipped = [], []
    for cid in dict.fromkeys(client_ids or []):
        try:
            c = a.client(cid)
            if c.status == "archived":
                raise Conflict("archived")
            _apply(c, body, a)
            done.append(c.id)
        except PcError as e:
            skipped.append(dict(id=cid, reason=e.message if e.status != 404 else "not found"))
    db.flush()
    core.audit(db, ctx, a.practice_id, "client.assigned", "client", None, clients=done, changes=body)
    return dict(updated=done, skipped=skipped)


def set_status(db, ctx, a: Access, client_id: int, status: str, reason: str = "") -> dict:
    a.require("clients_archive")
    if status not in P.CLIENT_STATUSES:
        raise PcError("status must be active, inactive or archived")
    c = a.client(client_id)
    if c.status == status:
        raise Conflict(f"The client is already {status}")
    if status == "archived":
        open_eng = db.query(P.PcEngagement.id).filter(P.PcEngagement.practice_id == a.practice_id, P.PcEngagement.client_id == c.id,
                                                      P.PcEngagement.status.in_(("proposed", "accepted", "active"))).first()
        if open_eng:
            raise Conflict("Complete or terminate the client's open engagements before archiving")
    prev = c.status
    c.status = status
    c.archived_at = core.now() if status == "archived" else None
    if status != "active":                                # inactive/archived clients lose portal access at once; history is kept
        for pa in db.query(P.PcPortalAccess).filter_by(practice_id=a.practice_id, client_id=c.id, status="active"):
            pa.status, pa.revoked_at, pa.revoked_by = "revoked", core.now(), ctx.user_id
    db.flush()
    core.audit(db, ctx, a.practice_id, "client.status_changed", "client", c.id, before=prev, after=status, reason=(reason or "")[:200])
    return cdict(c)


def get_client(db, ctx, a: Access, client_id: int) -> dict:
    """Full client view (audited: roadmap exit criterion 'access to each client is audit-logged')."""
    c = a.client(client_id)
    core.audit(db, ctx, a.practice_id, "client.viewed", "client", c.id)
    d = cdict(c, db, a, detail=True)
    d["identifiers"] = identifiers(db, a, "client", c.id)
    d["entities"] = client_entities(db, a, c.id)
    d["contacts"] = contacts_for(db, a, client_id=c.id)
    d["open_engagements"] = [dict(id=e.id, title=e.title, service_type=e.service_type, status=e.status) for e in
                             db.query(P.PcEngagement).filter(P.PcEngagement.practice_id == a.practice_id, P.PcEngagement.client_id == c.id, P.PcEngagement.status.in_(("proposed", "accepted", "active")))]
    d["open_jobs"] = db.query(P.PcJob).filter(P.PcJob.practice_id == a.practice_id, P.PcJob.client_id == c.id, P.PcJob.status != "completed").count()
    d["outstanding_requests"] = db.query(P.PcRequest).filter(P.PcRequest.practice_id == a.practice_id, P.PcRequest.client_id == c.id, P.PcRequest.status.in_(("requested", "partially_received", "rejected"))).count()
    d["documents_awaiting_review"] = db.query(P.PcRequestItem).join(P.PcRequest, P.PcRequest.id == P.PcRequestItem.request_id).filter(P.PcRequest.client_id == c.id, P.PcRequestItem.status == "submitted").count()
    d["history"] = [dict(kind=n.kind, body=n.body, at=core.plain(n.created_at), by=n.author_id) for n in db.query(P.PcContactNote).filter_by(practice_id=a.practice_id, client_id=c.id).order_by(P.PcContactNote.id.desc()).limit(20)]
    return d


def search(db, a: Access, *, q="", status=None, client_type=None, manager_id=None, preparer_id=None, reviewer_id=None, team_id=None, service=None, entity_type=None,
           deadline_before=None, sort="name", direction="asc", page_no=1, size=25) -> dict:
    a.require("view")
    C = P.PcClient
    qs = a.scoped_clients()
    if status:
        qs = qs.filter(C.status == status)
    else:
        qs = qs.filter(C.status != "archived")
    if q:
        like = f"%{q.strip().lower()}%"
        qs = qs.filter(or_(func.lower(C.legal_name).like(like), func.lower(func.coalesce(C.preferred_name, "")).like(like), func.lower(C.ref).like(like), func.lower(func.coalesce(C.email, "")).like(like)))
    for col, v in ((C.client_type, client_type), (C.manager_id, manager_id), (C.preparer_id, preparer_id), (C.reviewer_id, reviewer_id), (C.team_id, team_id)):
        if v:
            qs = qs.filter(col == v)
    if service:
        qs = qs.filter(func.coalesce(C.service_lines, "").like(f"%{service}%"))
    if entity_type:
        qs = qs.filter(C.id.in_(db.query(P.PcClientEntity.client_id).join(P.PcEntity, P.PcEntity.id == P.PcClientEntity.entity_id).filter(P.PcEntity.entity_type == entity_type)))
    if deadline_before:
        d = core.parse_date(deadline_before, "deadline_before")
        qs = qs.filter(C.id.in_(db.query(P.PcDeadline.client_id).filter(P.PcDeadline.practice_id == a.practice_id, P.PcDeadline.status == "open", P.PcDeadline.due_date <= d)))
    sortcol = dict(name=C.legal_name, ref=C.ref, status=C.status, updated=C.updated_at, created=C.created_at).get(sort)
    if sortcol is None:
        raise PcError("sort must be name, ref, status, updated or created")
    qs = qs.order_by(sortcol.desc() if direction == "desc" else sortcol.asc(), C.id)
    meta, qs = core.page(qs, page_no, size)
    return dict(**meta, items=[cdict(c) for c in qs])


# ------------------------------------------------------------------------------------------------------------------------------ entities
def entity_row(db, a: Access, entity_id: int) -> P.PcEntity:
    """An entity is visible when it belongs to the practice AND (is linked to a client in the member's scope OR is unlinked and the member is admin/partner)."""
    e = db.query(P.PcEntity).filter_by(practice_id=a.practice_id, id=entity_id).first()
    if e is None:
        raise NotFound("Entity")
    if a.role not in ("admin", "partner"):
        ok = db.query(P.PcClientEntity.id).filter(P.PcClientEntity.entity_id == e.id, P.PcClientEntity.client_id.in_(a.client_ids())).first()
        if not ok:
            raise NotFound("Entity")
    return e


def edict(e: P.PcEntity, db=None, a: Access = None) -> dict:
    d = dict(id=e.id, ref=e.ref, name=e.name, entity_type=e.entity_type, status=e.status, fy_end_month=e.fy_end_month, gst_registered=e.gst_registered, gst_basis=e.gst_basis, linked_org_id=e.linked_org_id)
    if db is not None and a is not None:
        d["identifiers"] = identifiers(db, a, "entity", e.id)
        have = {i["kind"] for i in d["identifiers"]}
        d["missing_identifiers"] = [k for k in IDS.ENTITY_RULES[e.entity_type]["required"] if k not in have]
    return d


def create_entity(db, ctx, a: Access, body: dict, *, client_id=None, relationship="manages", allow_duplicate=False) -> dict:
    a.require("clients_edit")
    et = body.get("entity_type")
    if et not in IDS.ENTITY_RULES:
        raise PcError(f"entity_type must be one of {', '.join(IDS.ENTITY_TYPES)}")
    name = core.text(body.get("name"), "Entity name", required=True)
    cl = a.client(client_id, allow_archived=False) if client_id else None
    if cl is None and a.role not in ("admin", "partner"):
        raise Forbidden("Create the entity from one of your clients so it stays inside your scope")
    ref = core.text(body.get("ref"), "Reference", max_len=40) or f"E-{db.query(func.count(P.PcEntity.id)).filter_by(practice_id=a.practice_id).scalar() + 1:04d}"
    while db.query(P.PcEntity.id).filter_by(practice_id=a.practice_id, ref=ref).first() and not body.get("ref"):
        ref += "x"
    if db.query(P.PcEntity.id).filter_by(practice_id=a.practice_id, ref=ref).first():
        raise Conflict(f"Entity reference {ref} is already used")
    fy = int(body.get("fy_end_month", 6))
    if not 1 <= fy <= 12:
        raise PcError("fy_end_month must be 1 to 12")
    idents = {}
    for k in IDS.KINDS:
        if body.get(k):
            if k not in IDS.ENTITY_RULES[et]["allowed"]:
                raise PcError(f"A {et.replace('_', ' ')} cannot carry a {k.upper()}")
            try:
                idents[k] = ident_hash(k, IDS.validate(k, body[k]))
            except ValueError as e:
                raise PcError(str(e))
    strong = [x for x in _candidates(db, a, dict(name=name, identifiers=idents), kind="entity") if x["score"] >= 0.9]
    if strong and not allow_duplicate:
        raise Conflict("Possible duplicate entity: " + "; ".join(f"{x['ref']} {x['name']} ({', '.join(x['reasons'])})" for x in strong[:3]) + ". Link the existing entity instead, or repeat with allow_duplicate.", "possible_duplicate")
    e = P.PcEntity(practice_id=a.practice_id, ref=ref, name=name, entity_type=et, fy_end_month=fy, gst_registered=bool(body.get("gst_registered")), gst_basis=body.get("gst_basis"),
                   tax_notes=core.text(body.get("tax_notes"), "Tax notes", max_len=2000))
    db.add(e)
    db.flush()
    for k in IDS.KINDS:
        if body.get(k):
            set_identifier(db, ctx, a, "entity", e.id, k, body[k])
    if cl is not None:
        link_entity(db, ctx, a, cl.id, e.id, relationship=relationship, _audit=False)
    core.audit(db, ctx, a.practice_id, "entity.created", "entity", e.id, ref=e.ref, entity_type=et, client_id=client_id)
    return edict(e, db, a)


def update_entity(db, ctx, a: Access, entity_id: int, body: dict) -> dict:
    a.require("clients_edit")
    e = entity_row(db, a, entity_id)
    if "name" in body:
        e.name = core.text(body["name"], "Entity name", required=True)
    if "fy_end_month" in body:
        if not 1 <= int(body["fy_end_month"]) <= 12:
            raise PcError("fy_end_month must be 1 to 12")
        e.fy_end_month = int(body["fy_end_month"])
    for k in ("gst_registered",):
        if k in body:
            setattr(e, k, bool(body[k]))
    if "gst_basis" in body:
        if body["gst_basis"] not in (None, "", "cash", "accrual"):
            raise PcError("gst_basis must be cash or accrual")
        e.gst_basis = body["gst_basis"] or None
    if "status" in body:
        if body["status"] not in ("active", "inactive"):
            raise PcError("status must be active or inactive")
        e.status = body["status"]
    db.flush()
    core.audit(db, ctx, a.practice_id, "entity.updated", "entity", e.id, fields=sorted(body))
    return edict(e, db, a)


def link_entity(db, ctx, a: Access, client_id: int, entity_id: int, *, relationship="manages", effective_from=None, effective_to=None, verified_source=None, _audit=True) -> dict:
    a.require("clients_edit")
    c = a.client(client_id, allow_archived=False)
    e = db.query(P.PcEntity).filter_by(practice_id=a.practice_id, id=entity_id).first()
    if e is None:
        raise NotFound("Entity")
    f, t = core.parse_date(effective_from, "effective_from"), core.parse_date(effective_to, "effective_to")
    if f and t and t < f:
        raise PcError("effective_to cannot be before effective_from")
    exists = db.query(P.PcClientEntity).filter_by(practice_id=a.practice_id, client_id=c.id, entity_id=e.id, relationship=relationship).filter(P.PcClientEntity.effective_to.is_(None)).first()
    if exists:
        raise Conflict("That client is already linked to the entity with that relationship")
    link = P.PcClientEntity(practice_id=a.practice_id, client_id=c.id, entity_id=e.id, relationship=core.text(relationship, "Relationship", required=True, max_len=60), effective_from=f, effective_to=t,
                            verified=bool(verified_source), verified_source=core.text(verified_source, "Verification source", max_len=200))
    db.add(link)
    db.flush()
    if _audit:
        core.audit(db, ctx, a.practice_id, "entity.linked", "entity", e.id, client_id=c.id, relationship=relationship)
    return dict(id=link.id, client_id=c.id, entity_id=e.id, relationship=link.relationship, verified=link.verified)


def unlink_entity(db, ctx, a: Access, client_id: int, entity_id: int, *, end_date=None) -> dict:
    """Ends the relationship (keeps the history) rather than deleting it."""
    a.require("clients_edit")
    c = a.client(client_id)
    links = db.query(P.PcClientEntity).filter_by(practice_id=a.practice_id, client_id=c.id, entity_id=entity_id).filter(P.PcClientEntity.effective_to.is_(None)).all()
    if not links:
        raise NotFound("Client-entity link")
    d = core.parse_date(end_date, "end_date", core.today())
    for l in links:
        l.effective_to = d
    db.flush()
    core.audit(db, ctx, a.practice_id, "entity.unlinked", "entity", entity_id, client_id=c.id, ended=d)
    return dict(ended=len(links), effective_to=d.isoformat())


def client_entities(db, a: Access, client_id: int, *, include_ended=False) -> list:
    q = db.query(P.PcClientEntity, P.PcEntity).join(P.PcEntity, P.PcEntity.id == P.PcClientEntity.entity_id).filter(P.PcClientEntity.practice_id == a.practice_id, P.PcClientEntity.client_id == client_id)
    if not include_ended:
        q = q.filter(P.PcClientEntity.effective_to.is_(None))
    return [dict(edict(e, db, a), relationship=l.relationship, link_id=l.id, effective_from=core.plain(l.effective_from), effective_to=core.plain(l.effective_to), verified=l.verified,
                 verified_label="Verified: " + (l.verified_source or "") if l.verified else "Unverified") for l, e in q.order_by(P.PcEntity.name)]


def entity_clients(db, a: Access, entity_id: int) -> list:
    e = entity_row(db, a, entity_id)
    ids_ = set(a.client_ids())
    rows = db.query(P.PcClientEntity, P.PcClient).join(P.PcClient, P.PcClient.id == P.PcClientEntity.client_id).filter(P.PcClientEntity.entity_id == e.id, P.PcClientEntity.effective_to.is_(None)).all()
    return [dict(client_id=c.id, ref=c.ref, name=c.legal_name, relationship=l.relationship) for l, c in rows if c.id in ids_ or a.role in ("admin", "partner")]


def _creates_cycle(db, a, parent_id, child_id) -> bool:
    """Adding parent->child is a cycle when the parent is already reachable from the child (following current relations downwards)."""
    seen, stack = set(), [child_id]
    while stack:
        n = stack.pop()
        if n == parent_id:
            return True
        if n in seen:
            continue
        seen.add(n)
        stack += [c for (c,) in db.query(P.PcEntityRelation.child_entity_id).filter_by(practice_id=a.practice_id, parent_entity_id=n).filter(P.PcEntityRelation.effective_to.is_(None))]
    return False


def add_relation(db, ctx, a: Access, parent_id: int, child_id: int, kind: str, *, percent=None, effective_from=None, effective_to=None, verified_source=None) -> dict:
    a.require("clients_edit")
    if kind not in REL_KINDS:
        raise PcError(f"kind must be one of {', '.join(REL_KINDS)}")
    if parent_id == child_id:
        raise PcError("An entity cannot be related to itself")
    entity_row(db, a, parent_id), entity_row(db, a, child_id)
    pc = None
    if percent not in (None, ""):
        from decimal import Decimal, InvalidOperation
        try:
            pc = Decimal(str(percent))
        except InvalidOperation:
            raise PcError("percent must be a number")
        if not 0 < pc <= 100:
            raise PcError("percent must be above 0 and at most 100")
    if _creates_cycle(db, a, parent_id, child_id):
        raise Conflict("That relationship would create a circular ownership/control structure")
    if db.query(P.PcEntityRelation.id).filter_by(practice_id=a.practice_id, parent_entity_id=parent_id, child_entity_id=child_id, kind=kind).filter(P.PcEntityRelation.effective_to.is_(None)).first():
        raise Conflict("That relationship already exists")
    r = P.PcEntityRelation(practice_id=a.practice_id, parent_entity_id=parent_id, child_entity_id=child_id, kind=kind, percent=pc, effective_from=core.parse_date(effective_from, "effective_from"),
                           effective_to=core.parse_date(effective_to, "effective_to"), verified=bool(verified_source), verified_source=core.text(verified_source, "Verification source", max_len=200))
    db.add(r)
    db.flush()
    core.audit(db, ctx, a.practice_id, "entity.relation_added", "entity", child_id, parent=parent_id, kind=kind)
    return dict(id=r.id, parent_entity_id=parent_id, child_entity_id=child_id, kind=kind, percent=core.plain(r.percent), verified=r.verified)


def end_relation(db, ctx, a: Access, relation_id: int, end_date=None) -> dict:
    a.require("clients_edit")
    r = db.query(P.PcEntityRelation).filter_by(practice_id=a.practice_id, id=relation_id).first()
    if r is None:
        raise NotFound("Relationship")
    entity_row(db, a, r.parent_entity_id)
    r.effective_to = core.parse_date(end_date, "end_date", core.today())
    db.flush()
    core.audit(db, ctx, a.practice_id, "entity.relation_ended", "entity", r.child_entity_id, relation=r.id)
    return dict(id=r.id, effective_to=r.effective_to.isoformat())


def structure(db, a: Access, client_id: int) -> dict:
    """The client's entity hierarchy: nodes are the client's entities and the entities related to them, edges are the relationships with their verification label."""
    c = a.client(client_id)
    root_ids = {e["id"] for e in client_entities(db, a, c.id)}
    nodes, edges, frontier = {}, [], set(root_ids)
    while frontier:
        batch = set(frontier)
        frontier = set()
        for r in db.query(P.PcEntityRelation).filter(P.PcEntityRelation.practice_id == a.practice_id, P.PcEntityRelation.effective_to.is_(None),
                                                       or_(P.PcEntityRelation.parent_entity_id.in_(batch), P.PcEntityRelation.child_entity_id.in_(batch))):
            edges.append(dict(id=r.id, parent=r.parent_entity_id, child=r.child_entity_id, kind=r.kind, percent=core.plain(r.percent), verified=r.verified,
                              label="Verified: " + (r.verified_source or "") if r.verified else "Unverified - not confirmed"))
            for n in (r.parent_entity_id, r.child_entity_id):
                if n not in nodes and n not in root_ids:
                    frontier.add(n)
                nodes.setdefault(n, None)
        for n in list(batch):
            nodes.setdefault(n, None)
    out_nodes = []
    for n in nodes:
        e = db.get(P.PcEntity, n)
        if e is not None and e.practice_id == a.practice_id:
            out_nodes.append(dict(id=e.id, ref=e.ref, name=e.name, entity_type=e.entity_type, direct=n in root_ids))
    uniq = {e["id"]: e for e in edges}
    return dict(client_id=c.id, nodes=out_nodes, edges=list(uniq.values()),
                note="Relationships are shown as recorded. Unverified ones are not confirmed facts of legal or beneficial ownership.")


# ------------------------------------------------------------------------------------------------------------------------------ contacts
def _contact_dict(c: P.PcContact, l: P.PcContactLink = None) -> dict:
    d = dict(id=c.id, full_name=c.full_name, email=c.email, phone=c.phone, comm_pref=c.comm_pref, has_portal_login=c.user_id is not None)
    if l is not None:
        d.update(link_id=l.id, client_id=l.client_id, entity_id=l.entity_id, role=l.role, is_primary=l.is_primary, is_authorised_rep=l.is_authorised_rep, can_receive_documents=l.can_receive_documents,
                 can_approve_work=l.can_approve_work, can_use_portal=l.can_use_portal, services=[s for s in (l.services or "").split(",") if s], effective_to=core.plain(l.effective_to))
    return d


def add_contact(db, ctx, a: Access, client_id: int, body: dict, *, entity_id=None) -> dict:
    a.require("clients_edit")
    cl = a.client(client_id, allow_archived=False)
    if entity_id:
        if not db.query(P.PcClientEntity.id).filter_by(practice_id=a.practice_id, client_id=cl.id, entity_id=entity_id).first():
            raise PcError("That entity is not linked to this client")
    email = core.text(body.get("email"), "Email")
    if email and not EMAIL.match(email):
        raise PcError("Email address is not valid")
    contact = None
    if body.get("contact_id"):
        contact = db.query(P.PcContact).filter_by(practice_id=a.practice_id, id=body["contact_id"]).first()
        if contact is None:
            raise NotFound("Contact")
    else:
        if email:
            contact = db.query(P.PcContact).filter(P.PcContact.practice_id == a.practice_id, func.lower(P.PcContact.email) == email.lower()).first()
        if contact is None:
            contact = P.PcContact(practice_id=a.practice_id, full_name=core.text(body.get("full_name"), "Contact name", required=True), email=email, phone=core.text(body.get("phone"), "Phone", max_len=40),
                                  comm_pref=body.get("comm_pref") if body.get("comm_pref") in COMM else "email")
            db.add(contact)
            db.flush()
    role = body.get("role", "contact")
    if role not in CONTACT_ROLES:
        raise PcError(f"role must be one of {', '.join(CONTACT_ROLES)}")
    if db.query(P.PcContactLink.id).filter_by(practice_id=a.practice_id, contact_id=contact.id, client_id=cl.id, entity_id=entity_id, role=role).filter(P.PcContactLink.effective_to.is_(None)).first():
        raise Conflict("That contact already has this role on this client/entity")
    link = P.PcContactLink(practice_id=a.practice_id, contact_id=contact.id, client_id=cl.id, entity_id=entity_id, role=role, services=_services(body.get("services")),
                           is_authorised_rep=bool(body.get("is_authorised_rep")), can_receive_documents=bool(body.get("can_receive_documents")), can_approve_work=bool(body.get("can_approve_work")),
                           can_use_portal=bool(body.get("can_use_portal")), effective_from=core.parse_date(body.get("effective_from"), "effective_from"))
    if (link.can_approve_work or link.can_use_portal) and not (link.is_authorised_rep or role == "contact"):
        pass
    db.add(link)
    db.flush()
    if body.get("is_primary"):
        set_primary(db, ctx, a, link.id, _audit=False)
    core.audit(db, ctx, a.practice_id, "contact.added", "contact", contact.id, client_id=cl.id, role=role, authorised_rep=link.is_authorised_rep, portal=link.can_use_portal)
    return _contact_dict(contact, link)


def set_primary(db, ctx, a: Access, link_id: int, _audit=True) -> dict:
    a.require("clients_edit")
    l = db.query(P.PcContactLink).filter_by(practice_id=a.practice_id, id=link_id).first()
    if l is None:
        raise NotFound("Contact link")
    a.client(l.client_id)
    db.query(P.PcContactLink).filter_by(practice_id=a.practice_id, client_id=l.client_id, entity_id=l.entity_id).update({"is_primary": False})
    l.is_primary = True
    db.flush()
    if _audit:
        core.audit(db, ctx, a.practice_id, "contact.primary_set", "contact", l.contact_id, client_id=l.client_id)
    return dict(link_id=l.id, is_primary=True)


def update_authority(db, ctx, a: Access, link_id: int, body: dict) -> dict:
    """Authorised representative / document / approval / portal flags and service restriction. Takes effect on the portal immediately."""
    a.require("clients_edit")
    l = db.query(P.PcContactLink).filter_by(practice_id=a.practice_id, id=link_id).first()
    if l is None:
        raise NotFound("Contact link")
    a.client(l.client_id)
    before = _contact_dict(db.get(P.PcContact, l.contact_id), l)
    for k in ("is_authorised_rep", "can_receive_documents", "can_approve_work", "can_use_portal"):
        if k in body:
            setattr(l, k, bool(body[k]))
    if "services" in body:
        l.services = _services(body["services"])
    if "role" in body:
        if body["role"] not in CONTACT_ROLES:
            raise PcError(f"role must be one of {', '.join(CONTACT_ROLES)}")
        l.role = body["role"]
    if "effective_to" in body:
        l.effective_to = core.parse_date(body["effective_to"], "effective_to")
    if not l.can_use_portal or l.effective_to:
        c = db.get(P.PcContact, l.contact_id)
        if c.user_id:
            for pa in db.query(P.PcPortalAccess).filter_by(practice_id=a.practice_id, client_id=l.client_id, user_id=c.user_id, status="active"):
                pa.status, pa.revoked_at, pa.revoked_by = "revoked", core.now(), ctx.user_id
    db.flush()
    core.audit(db, ctx, a.practice_id, "contact.authority_changed", "contact", l.contact_id, client_id=l.client_id, before={k: before[k] for k in ("is_authorised_rep", "can_approve_work", "can_use_portal", "can_receive_documents")},
               after={k: getattr(l, k) for k in ("is_authorised_rep", "can_approve_work", "can_use_portal", "can_receive_documents")})
    return _contact_dict(db.get(P.PcContact, l.contact_id), l)


def contacts_for(db, a: Access, *, client_id=None, entity_id=None) -> list:
    if client_id:
        a.client(client_id)                       # 404 when outside the member's scope
    elif entity_id:
        entity_row(db, a, entity_id)
    else:
        raise PcError("client_id or entity_id is required")
    q = db.query(P.PcContact, P.PcContactLink).join(P.PcContactLink, P.PcContactLink.contact_id == P.PcContact.id).filter(P.PcContactLink.practice_id == a.practice_id)
    if client_id:
        q = q.filter(P.PcContactLink.client_id == client_id)
    if entity_id:
        q = q.filter(P.PcContactLink.entity_id == entity_id)
    return [_contact_dict(c, l) for c, l in q.filter(or_(P.PcContactLink.effective_to.is_(None), P.PcContactLink.effective_to >= core.today())).order_by(P.PcContactLink.is_primary.desc(), P.PcContact.full_name)]


def add_note(db, ctx, a: Access, client_id: int, body: str, kind: str = "note", contact_id=None) -> dict:
    a.require("clients_edit")
    c = a.client(client_id)
    if kind not in ("note", "call", "meeting", "email"):
        raise PcError("kind must be note, call, meeting or email")
    n = P.PcContactNote(practice_id=a.practice_id, client_id=c.id, contact_id=contact_id, kind=kind, body=core.text(body, "Note", required=True, max_len=4000), author_id=ctx.user_id)
    db.add(n)
    db.flush()
    core.audit(db, ctx, a.practice_id, "client.note_added", "client", c.id, kind=kind)
    return dict(id=n.id, kind=kind, body=n.body)


def record_consent(db, ctx, a: Access, client_id: int, key: str, granted: bool, *, text_hash=None, contact_id=None, source="staff") -> dict:
    a.require("clients_edit")
    c = a.client(client_id)
    r = P.PcConsent(practice_id=a.practice_id, client_id=c.id, contact_id=contact_id, key=core.text(key, "Consent key", required=True, max_len=60), granted=bool(granted), text_hash=text_hash, source=source, recorded_by=ctx.user_id)
    db.add(r)
    db.flush()
    core.audit(db, ctx, a.practice_id, "client.consent_recorded", "client", c.id, key=r.key, granted=r.granted, source=source)
    return dict(id=r.id, key=r.key, granted=r.granted, at=core.plain(r.recorded_at))


def consents(db, a: Access, client_id: int) -> list:
    a.client(client_id)
    return [dict(id=r.id, key=r.key, granted=r.granted, source=r.source, at=core.plain(r.recorded_at)) for r in db.query(P.PcConsent).filter_by(practice_id=a.practice_id, client_id=client_id).order_by(P.PcConsent.id.desc())]


# ------------------------------------------------------------------------------------------------------------------------------ duplicates
def scan_duplicates(db, ctx, a: Access, kind: str = "client") -> dict:
    """Creates review items for candidate pairs (idempotent). Nothing is ever merged automatically."""
    a.require("clients_edit")
    if kind not in ("client", "entity"):
        raise PcError("kind must be client or entity")
    Mdl = P.PcClient if kind == "client" else P.PcEntity
    rows = db.query(Mdl).filter_by(practice_id=a.practice_id).order_by(Mdl.id).all()
    idmap = {}
    for r in db.query(P.PcIdentifier).filter_by(practice_id=a.practice_id, owner_kind=kind):
        idmap.setdefault(r.owner_id, {})[r.kind] = r.value_hash
    cfg, created = a.settings.get("dedupe") or {}, 0
    for i, x in enumerate(rows):
        for y in rows[i + 1:]:
            ax = dict(name=getattr(x, "legal_name", None) or x.name, email=getattr(x, "email", None), phone=getattr(x, "phone", None), identifiers=idmap.get(x.id, {}))
            by = dict(name=getattr(y, "legal_name", None) or y.name, email=getattr(y, "email", None), phone=getattr(y, "phone", None), identifiers=idmap.get(y.id, {}))
            res = DD.compare(ax, by, cfg)
            if res["reasons"] and not db.query(P.PcDupReview.id).filter_by(practice_id=a.practice_id, kind=kind, a_id=x.id, b_id=y.id).first():
                db.add(P.PcDupReview(practice_id=a.practice_id, kind=kind, a_id=x.id, b_id=y.id, score=res["score"], reasons=res["reasons"]))
                created += 1
    db.flush()
    core.audit(db, ctx, a.practice_id, "duplicates.scanned", kind, None, created=created)
    return dict(created=created, pending=db.query(P.PcDupReview).filter_by(practice_id=a.practice_id, kind=kind, status="pending").count())


def duplicate_reviews(db, a: Access, status="pending") -> list:
    a.require("view")
    out = []
    for r in db.query(P.PcDupReview).filter_by(practice_id=a.practice_id, status=status).order_by(P.PcDupReview.score.desc(), P.PcDupReview.id):
        Mdl = P.PcClient if r.kind == "client" else P.PcEntity
        x, y = db.get(Mdl, r.a_id), db.get(Mdl, r.b_id)
        if r.kind == "client":
            try:
                a.client(r.a_id), a.client(r.b_id)
            except PcError:
                continue
        out.append(dict(id=r.id, kind=r.kind, score=core.plain(r.score), reasons=r.reasons, a=dict(id=x.id, ref=x.ref, name=getattr(x, "legal_name", None) or x.name), b=dict(id=y.id, ref=y.ref, name=getattr(y, "legal_name", None) or y.name), status=r.status))
    return out


def review_duplicate(db, ctx, a: Access, review_id: int, decision: str, note: str = "") -> dict:
    a.require("clients_edit")
    if decision not in ("not_duplicate", "confirmed"):
        raise PcError("decision must be not_duplicate or confirmed")
    r = db.query(P.PcDupReview).filter_by(practice_id=a.practice_id, id=review_id).first()
    if r is None:
        raise NotFound("Duplicate review")
    if r.status != "pending":
        raise Conflict("That review has already been decided")
    r.status, r.reviewed_by, r.reviewed_at, r.note = decision, ctx.user_id, core.now(), core.text(note, "Note", max_len=500)
    db.flush()
    core.audit(db, ctx, a.practice_id, "duplicates.reviewed", r.kind, r.id, decision=decision)
    return dict(id=r.id, status=r.status, note="Records are never merged automatically; 'confirmed' only records the decision. Archive the extra record if appropriate.")


# ------------------------------------------------------------------------------------------------------------------------------ CSV import / export
def _safe(v):
    s = "" if v is None else str(v)
    return "'" + s if s[:1] in ("=", "+", "-", "@", "\t", "\r") else s


def export_csv(db, ctx, a: Access) -> str:
    a.require("import")
    out = io.StringIO()
    w = csv.writer(out)
    w.writerow(IMPORT_COLUMNS[:-2] + ["abn_masked", "status", "postal_address"])
    for c in a.scoped_clients().order_by(P.PcClient.legal_name):
        ab = db.query(P.PcIdentifier).filter_by(practice_id=a.practice_id, owner_kind="client", owner_id=c.id, kind="abn").first()
        w.writerow([_safe(x) for x in (c.ref, c.client_type, c.legal_name, c.preferred_name, c.email, c.phone, IDS.mask("abn", ab.last_digits) if ab else "", c.status, c.postal_address)])
    core.audit(db, ctx, a.practice_id, "clients.exported", "client", None)
    return out.getvalue()


def import_csv(db, ctx, a: Access, text: str, *, apply=False, strict=True, allow_duplicates=False) -> dict:
    """Validate (and optionally apply) a clients CSV. Row-level errors are returned with row numbers. strict=True applies nothing if any row is rejected."""
    a.require("import")
    if len(text or "") > 2_000_000:
        raise PcError("The file is too large (limit 2 MB)")
    rd = csv.DictReader(io.StringIO(text or ""))
    cols = [(c or "").strip().lower() for c in (rd.fieldnames or [])]
    missing = [c for c in ("client_type", "legal_name") if c not in cols]
    if missing:
        raise PcError(f"CSV needs the columns: {', '.join(missing)}. Template: {','.join(IMPORT_COLUMNS)}")
    unknown = [c for c in cols if c and c not in IMPORT_COLUMNS]
    rows, rejected, seen_refs, seen_ids = [], [], set(), set()
    for n, raw in enumerate(rd, start=2):
        r = {(k or "").strip().lower(): (v or "").strip() for k, v in raw.items() if k}
        err = None
        try:
            if r.get("client_type") not in P.CLIENT_TYPES:
                raise PcError("client_type must be individual or organisation")
            if not r.get("legal_name"):
                raise PcError("legal_name is required")
            if r.get("email") and not EMAIL.match(r["email"]):
                raise PcError("email is not valid")
            if r.get("abn"):
                IDS.validate("abn", r["abn"])
            if r.get("ref"):
                if r["ref"] in seen_refs:
                    raise PcError(f"Duplicate reference {r['ref']} within the file")
                if db.query(P.PcClient.id).filter_by(practice_id=a.practice_id, ref=r["ref"]).first():
                    raise PcError(f"Reference {r['ref']} already exists (the import never overwrites)")
                seen_refs.add(r["ref"])
            if r.get("abn"):
                dg = IDS.digits(r["abn"])
                if dg in seen_ids:
                    raise PcError("Duplicate ABN within the file")
                seen_ids.add(dg)
            cands = _candidates(db, a, dict(name=r["legal_name"], email=r.get("email"), phone=r.get("phone"), identifiers=({"abn": ident_hash("abn", IDS.digits(r["abn"]))} if r.get("abn") else {})))
            strong = [x for x in cands if x["score"] >= 0.9]
            if strong and not allow_duplicates:
                raise PcError("Possible duplicate of existing client " + ", ".join(x["ref"] for x in strong[:3]))
        except ValueError as e:
            err = str(e)
        except PcError as e:
            err = e.message
        (rejected if err else rows).append(dict(row=n, error=err) if err else dict(row=n, data=r))
    result = dict(valid_rows=len(rows), rejected=rejected, ignored_columns=unknown, applied=0, dry_run=not apply, strict=strict)
    if not apply or (strict and rejected):
        if apply and rejected:
            result["note"] = "Nothing was imported because strict mode refuses a file with rejected rows"
        return result
    for x in rows:
        r = x["data"]
        body = {k: r.get(k) for k in ("ref", "client_type", "legal_name", "preferred_name", "email", "phone", "postal_address") if r.get(k)}
        if r.get("abn"):
            body["abn"] = r["abn"]
        create_client(db, ctx, a, body, allow_duplicate=True)
        result["applied"] += 1
    core.audit(db, ctx, a.practice_id, "clients.imported", "client", None, applied=result["applied"], rejected=len(rejected))
    return result
