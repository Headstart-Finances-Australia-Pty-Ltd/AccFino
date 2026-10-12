"""Practice & Client Services HTTP API. Staff routes live under /practice (one router per module id, each plan-gated); client routes under /portal (authorised per client, no organisation context).
The API layer only validates, authorises and calls services."""
import io
from typing import List, Optional

from fastapi import APIRouter, Body, Depends, File, Form, Query, UploadFile
from fastapi.responses import FileResponse, Response
from sqlalchemy.orm import Session

from accfino.core.security.context import OrgContext, current_org
from accfino.modules.practice.api.deps import access, done, portal_login
from accfino.modules.practice.services import billing as BL, clients as CL, core, dashboard as DB, documents as DOC, engagements as EN, portal as PT, practice as PR, workpapers as WP
from accfino.modules.practice.services.core import Access, PcError
from accfino.shared.db.database import get_db

Ctx, Db, Acc = Depends(current_org), Depends(get_db), Depends(access)
MAX_UPLOAD = 25 * 1024 * 1024


async def _read(file: UploadFile, limit=MAX_UPLOAD) -> bytes:
    data = await file.read(limit + 1)
    if len(data) > limit:
        raise PcError("The file is too large", 413)
    return data


def _ids(v):
    return [int(x) for x in v or []]


# =============================================================================================================================== practice management
mgmt_router = APIRouter()


@mgmt_router.get("/me")
def me(ctx: OrgContext = Ctx, db: Session = Db):
    a = Access(db, ctx, require_member=False)
    if a.practice is None:
        return dict(has_practice=False, can_create=bool(ctx.is_org_admin))
    return dict(has_practice=True, is_member=a.member is not None, **(a.summary() if a.member else {}))


@mgmt_router.post("/workspace")
def create_workspace(body: dict = Body(...), ctx: OrgContext = Ctx, db: Session = Db):
    return done(db, PR.create(db, ctx, body.get("name"), **{k: v for k, v in body.items() if k in ("trading_name", "abn", "email", "phone", "address")}))


@mgmt_router.get("/profile")
def profile(a: Access = Acc):
    return PR.profile_get(a)


@mgmt_router.put("/profile")
def put_profile(body: dict = Body(...), ctx: OrgContext = Ctx, db: Session = Db, a: Access = Acc):
    PR.update_profile(db, ctx, a, body)
    return done(db, PR.profile_get(a))


@mgmt_router.put("/settings")
def put_settings(body: dict = Body(...), ctx: OrgContext = Ctx, db: Session = Db, a: Access = Acc):
    return done(db, PR.update_settings(db, ctx, a, body))


@mgmt_router.get("/members")
def members(db: Session = Db, a: Access = Acc):
    return PR.members(db, a)


@mgmt_router.post("/members")
def add_member(body: dict = Body(...), ctx: OrgContext = Ctx, db: Session = Db, a: Access = Acc):
    return done(db, PR.add_member(db, ctx, a, int(body.get("staff_id") or 0), body.get("role")))


@mgmt_router.put("/members/{member_id}")
def change_member(member_id: int, body: dict = Body(...), ctx: OrgContext = Ctx, db: Session = Db, a: Access = Acc):
    return done(db, PR.change_member(db, ctx, a, member_id, role=body.get("role"), status=body.get("status")))


@mgmt_router.delete("/members/{member_id}")
def remove_member(member_id: int, ctx: OrgContext = Ctx, db: Session = Db, a: Access = Acc):
    return done(db, PR.remove_member(db, ctx, a, member_id))


@mgmt_router.get("/teams")
def teams(db: Session = Db, a: Access = Acc):
    return PR.teams(db, a)


@mgmt_router.post("/teams")
def create_team(body: dict = Body(...), ctx: OrgContext = Ctx, db: Session = Db, a: Access = Acc):
    return done(db, PR.create_team(db, ctx, a, body.get("name"), _ids(body.get("staff_ids"))))


@mgmt_router.put("/teams/{team_id}/members")
def team_members(team_id: int, body: dict = Body(...), ctx: OrgContext = Ctx, db: Session = Db, a: Access = Acc):
    return done(db, PR.set_team_members(db, ctx, a, team_id, _ids(body.get("staff_ids"))))


@mgmt_router.delete("/teams/{team_id}")
def delete_team(team_id: int, ctx: OrgContext = Ctx, db: Session = Db, a: Access = Acc):
    return done(db, PR.delete_team(db, ctx, a, team_id))


@mgmt_router.get("/audit")
def audit(limit: int = Query(100, le=500), prefix: str = Query(""), db: Session = Db, a: Access = Acc):
    return PR.audit_trail(db, a, limit, prefix)


@mgmt_router.get("/dashboard")
def dash(db: Session = Db, a: Access = Acc):
    return DB.summary(db, a)


@mgmt_router.get("/dashboard/workload")
def workload(db: Session = Db, a: Access = Acc):
    return DB.workload(db, a)


@mgmt_router.get("/dashboard/{metric}")
def drill(metric: str, page: int = 1, size: int = 25, db: Session = Db, a: Access = Acc):
    return DB.drill(db, a, metric, page, size)


# =============================================================================================================================== clients & entities
clients_router = APIRouter()


@clients_router.get("/clients")
def search(q: str = "", status: Optional[str] = None, client_type: Optional[str] = None, manager_id: Optional[int] = None, preparer_id: Optional[int] = None, reviewer_id: Optional[int] = None,
           team_id: Optional[int] = None, service: Optional[str] = None, entity_type: Optional[str] = None, sort: str = "name", direction: str = "asc", page: int = 1, size: int = 25,
           db: Session = Db, a: Access = Acc):
    return CL.search(db, a, q=q, status=status, client_type=client_type, manager_id=manager_id, preparer_id=preparer_id, reviewer_id=reviewer_id, team_id=team_id, service=service,
                     entity_type=entity_type, sort=sort, direction=direction, page_no=page, size=size)


@clients_router.post("/clients")
def create_client(body: dict = Body(...), allow_duplicate: bool = False, ctx: OrgContext = Ctx, db: Session = Db, a: Access = Acc):
    return done(db, CL.create_client(db, ctx, a, body, allow_duplicate=allow_duplicate))


@clients_router.post("/clients/assign")
def assign(body: dict = Body(...), ctx: OrgContext = Ctx, db: Session = Db, a: Access = Acc):
    kw = {k: body[k] for k in ("manager_id", "preparer_id", "reviewer_id", "team_id") if k in body}
    return done(db, CL.assign(db, ctx, a, _ids(body.get("client_ids")), **kw))


@clients_router.get("/clients/export")
def export(ctx: OrgContext = Ctx, db: Session = Db, a: Access = Acc):
    text = CL.export_csv(db, ctx, a)
    db.commit()
    return Response(text, media_type="text/csv", headers={"Content-Disposition": 'attachment; filename="clients.csv"', "Cache-Control": "no-store"})


@clients_router.post("/clients/import")
async def import_(file: UploadFile = File(...), apply: bool = Form(False), strict: bool = Form(True), ctx: OrgContext = Ctx, db: Session = Db, a: Access = Acc):
    text = (await _read(file, 2_000_000)).decode("utf-8-sig", "replace")
    return done(db, CL.import_csv(db, ctx, a, text, apply=apply, strict=strict))


@clients_router.get("/clients/duplicates")
def dups(status: str = "pending", db: Session = Db, a: Access = Acc):
    return CL.duplicate_reviews(db, a, status)


@clients_router.post("/clients/duplicates/scan")
def dup_scan(kind: str = "client", ctx: OrgContext = Ctx, db: Session = Db, a: Access = Acc):
    return done(db, CL.scan_duplicates(db, ctx, a, kind))


@clients_router.post("/clients/duplicates/{review_id}")
def dup_review(review_id: int, body: dict = Body(...), ctx: OrgContext = Ctx, db: Session = Db, a: Access = Acc):
    return done(db, CL.review_duplicate(db, ctx, a, review_id, body.get("decision"), body.get("note") or ""))


@clients_router.get("/clients/{client_id}")
def get_client(client_id: int, ctx: OrgContext = Ctx, db: Session = Db, a: Access = Acc):
    return done(db, CL.get_client(db, ctx, a, client_id))


@clients_router.put("/clients/{client_id}")
def update_client(client_id: int, body: dict = Body(...), ctx: OrgContext = Ctx, db: Session = Db, a: Access = Acc):
    return done(db, CL.update_client(db, ctx, a, client_id, body))


@clients_router.post("/clients/{client_id}/status")
def set_status(client_id: int, body: dict = Body(...), ctx: OrgContext = Ctx, db: Session = Db, a: Access = Acc):
    return done(db, CL.set_status(db, ctx, a, client_id, body.get("status"), body.get("reason") or ""))


@clients_router.post("/clients/{client_id}/identifiers")
def set_ident(client_id: int, body: dict = Body(...), ctx: OrgContext = Ctx, db: Session = Db, a: Access = Acc):
    return done(db, CL.set_identifier(db, ctx, a, "client", client_id, body.get("kind"), body.get("value"), verified=bool(body.get("verified")), verified_source=body.get("verified_source")))


@clients_router.post("/clients/{client_id}/identifiers/{kind}/reveal")
def reveal(client_id: int, kind: str, ctx: OrgContext = Ctx, db: Session = Db, a: Access = Acc):
    return done(db, CL.reveal_identifier(db, ctx, a, "client", client_id, kind))


@clients_router.post("/clients/{client_id}/notes")
def add_note(client_id: int, body: dict = Body(...), ctx: OrgContext = Ctx, db: Session = Db, a: Access = Acc):
    return done(db, CL.add_note(db, ctx, a, client_id, body.get("body"), body.get("kind") or "note", body.get("contact_id")))


@clients_router.get("/clients/{client_id}/consents")
def consents(client_id: int, db: Session = Db, a: Access = Acc):
    return CL.consents(db, a, client_id)


@clients_router.post("/clients/{client_id}/consents")
def consent(client_id: int, body: dict = Body(...), ctx: OrgContext = Ctx, db: Session = Db, a: Access = Acc):
    return done(db, CL.record_consent(db, ctx, a, client_id, body.get("key"), bool(body.get("granted"))))


@clients_router.get("/clients/{client_id}/structure")
def structure(client_id: int, db: Session = Db, a: Access = Acc):
    return CL.structure(db, a, client_id)


@clients_router.post("/clients/{client_id}/entities")
def create_entity(client_id: int, body: dict = Body(...), ctx: OrgContext = Ctx, db: Session = Db, a: Access = Acc):
    return done(db, CL.create_entity(db, ctx, a, body, client_id=client_id, relationship=body.get("relationship") or "manages", allow_duplicate=bool(body.get("allow_duplicate"))))


@clients_router.post("/clients/{client_id}/entities/{entity_id}/link")
def link_entity(client_id: int, entity_id: int, body: dict = Body(default={}), ctx: OrgContext = Ctx, db: Session = Db, a: Access = Acc):
    return done(db, CL.link_entity(db, ctx, a, client_id, entity_id, relationship=body.get("relationship") or "manages", effective_from=body.get("effective_from"), verified_source=body.get("verified_source")))


@clients_router.post("/clients/{client_id}/entities/{entity_id}/unlink")
def unlink_entity(client_id: int, entity_id: int, ctx: OrgContext = Ctx, db: Session = Db, a: Access = Acc):
    return done(db, CL.unlink_entity(db, ctx, a, client_id, entity_id))


@clients_router.put("/entities/{entity_id}")
def update_entity(entity_id: int, body: dict = Body(...), ctx: OrgContext = Ctx, db: Session = Db, a: Access = Acc):
    return done(db, CL.update_entity(db, ctx, a, entity_id, body))


@clients_router.post("/entities/{entity_id}/identifiers")
def set_ent_ident(entity_id: int, body: dict = Body(...), ctx: OrgContext = Ctx, db: Session = Db, a: Access = Acc):
    return done(db, CL.set_identifier(db, ctx, a, "entity", entity_id, body.get("kind"), body.get("value"), verified=bool(body.get("verified")), verified_source=body.get("verified_source")))


@clients_router.post("/relations")
def add_relation(body: dict = Body(...), ctx: OrgContext = Ctx, db: Session = Db, a: Access = Acc):
    return done(db, CL.add_relation(db, ctx, a, int(body.get("parent_id") or 0), int(body.get("child_id") or 0), body.get("kind"), percent=body.get("percent"),
                                    effective_from=body.get("effective_from"), verified_source=body.get("verified_source")))


@clients_router.post("/relations/{relation_id}/end")
def end_relation(relation_id: int, ctx: OrgContext = Ctx, db: Session = Db, a: Access = Acc):
    return done(db, CL.end_relation(db, ctx, a, relation_id))


@clients_router.post("/clients/{client_id}/contacts")
def add_contact(client_id: int, body: dict = Body(...), ctx: OrgContext = Ctx, db: Session = Db, a: Access = Acc):
    return done(db, CL.add_contact(db, ctx, a, client_id, body, entity_id=body.get("entity_id")))


@clients_router.get("/clients/{client_id}/contacts")
def contacts(client_id: int, db: Session = Db, a: Access = Acc):
    return CL.contacts_for(db, a, client_id=client_id)


@clients_router.put("/contact-links/{link_id}")
def authority(link_id: int, body: dict = Body(...), ctx: OrgContext = Ctx, db: Session = Db, a: Access = Acc):
    return done(db, CL.update_authority(db, ctx, a, link_id, body))


@clients_router.post("/contact-links/{link_id}/primary")
def primary(link_id: int, ctx: OrgContext = Ctx, db: Session = Db, a: Access = Acc):
    return done(db, CL.set_primary(db, ctx, a, link_id))


# =============================================================================================================================== workpapers & documents
docs_router = APIRouter()


@docs_router.get("/documents")
def list_docs(client_id: Optional[int] = None, entity_id: Optional[int] = None, category: Optional[str] = None, status: str = "active", q: str = "", fy: Optional[int] = None, page: int = 1, size: int = 25,
              db: Session = Db, a: Access = Acc):
    return DOC.list_docs(db, a, client_id=client_id, entity_id=entity_id, category=category, status=status, q=q, fy=fy, page_no=page, size=size)


@docs_router.post("/documents")
async def upload(client_id: int = Form(...), file: UploadFile = File(...), title: str = Form(""), category: str = Form("general"), entity_id: Optional[int] = Form(None), fy: Optional[int] = Form(None),
                 shared_with_portal: bool = Form(False), ctx: OrgContext = Ctx, db: Session = Db, a: Access = Acc):
    data = await _read(file, int(a.settings.get("max_file_mb", 10)) * 1024 * 1024)
    return done(db, DOC.upload(db, ctx, a, client_id, file.filename or "", data, title=title or None, category=category, entity_id=entity_id, fy=fy, shared_with_portal=shared_with_portal))


@docs_router.get("/documents/{doc_id}")
def get_doc(doc_id: int, db: Session = Db, a: Access = Acc):
    return DOC.get(db, a, doc_id)


@docs_router.put("/documents/{doc_id}")
def update_doc(doc_id: int, body: dict = Body(...), ctx: OrgContext = Ctx, db: Session = Db, a: Access = Acc):
    return done(db, DOC.update(db, ctx, a, doc_id, body))


@docs_router.post("/documents/{doc_id}/versions")
async def new_version(doc_id: int, file: UploadFile = File(...), reason: str = Form(""), ctx: OrgContext = Ctx, db: Session = Db, a: Access = Acc):
    data = await _read(file, int(a.settings.get("max_file_mb", 10)) * 1024 * 1024)
    return done(db, DOC.new_version(db, ctx, a, doc_id, file.filename or "", data, reason))


@docs_router.post("/documents/{doc_id}/{action}")
def doc_action(doc_id: int, action: str, body: dict = Body(default={}), ctx: OrgContext = Ctx, db: Session = Db, a: Access = Acc):
    if action in ("archive", "restore"):
        return done(db, DOC.set_status(db, ctx, a, doc_id, action))
    if action == "hold":
        return done(db, DOC.set_hold(db, ctx, a, doc_id, bool(body.get("hold", True)), body.get("reason") or ""))
    if action == "delete":
        return done(db, DOC.delete(db, ctx, a, doc_id, body.get("reason") or ""))
    if action == "preview":
        return done(db, DOC.preview(db, ctx, a, doc_id))
    if action == "ticket":
        return done(db, DOC.issue_ticket(db, ctx, a, doc_id, body.get("version")))
    raise PcError("Unknown action", 404)


def _file_response(out: dict) -> FileResponse:
    inline = out["inline"]
    headers = {"Cache-Control": "no-store", "X-Content-Type-Options": "nosniff", "Content-Security-Policy": "sandbox; default-src 'none'"}
    return FileResponse(out["path"], media_type=out["content_type"], filename=out["file_name"], content_disposition_type="inline" if inline else "attachment", headers=headers)


@docs_router.post("/documents-download")
def download(body: dict = Body(...), ctx: OrgContext = Ctx, db: Session = Db, a: Access = Acc):
    out = DOC.staff_download(db, ctx, a, body.get("ticket") or "")
    db.commit()
    return _file_response(out)


@docs_router.get("/workpaper-templates")
def wp_templates(db: Session = Db, a: Access = Acc):
    return WP.templates(db, a)


@docs_router.post("/workpaper-templates")
def wp_template_create(body: dict = Body(...), ctx: OrgContext = Ctx, db: Session = Db, a: Access = Acc):
    return done(db, WP.create_template(db, ctx, a, body.get("name"), body.get("category"), body.get("lines") or []))


@docs_router.get("/workpapers")
def wp_list(client_id: Optional[int] = None, status: Optional[str] = None, mine: bool = False, page: int = 1, size: int = 25, db: Session = Db, a: Access = Acc):
    return WP.listing(db, a, client_id=client_id, status=status, mine=mine, page_no=page, size=size)


@docs_router.post("/workpapers")
def wp_create(body: dict = Body(...), ctx: OrgContext = Ctx, db: Session = Db, a: Access = Acc):
    return done(db, WP.create(db, ctx, a, int(body.get("client_id") or 0), body.get("title"), category=body.get("category") or "general", template_id=body.get("template_id"),
                              entity_id=body.get("entity_id"), engagement_id=body.get("engagement_id"), period_from=body.get("period_from"), period_to=body.get("period_to"), reviewer_id=body.get("reviewer_id")))


@docs_router.get("/workpapers/{wid}")
def wp_get(wid: int, db: Session = Db, a: Access = Acc):
    return WP.get(db, a, wid)


@docs_router.put("/workpapers/{wid}")
def wp_save(wid: int, body: dict = Body(...), ctx: OrgContext = Ctx, db: Session = Db, a: Access = Acc):
    return done(db, WP.save_content(db, ctx, a, wid, content=body.get("content"), title=body.get("title"), expected_version=body.get("expected_version")))


@docs_router.post("/workpapers/{wid}/transition")
def wp_transition(wid: int, body: dict = Body(...), ctx: OrgContext = Ctx, db: Session = Db, a: Access = Acc):
    return done(db, WP.transition(db, ctx, a, wid, body.get("action"), body.get("reason") or ""))


@docs_router.post("/workpapers/{wid}/comments")
def wp_comment(wid: int, body: dict = Body(...), ctx: OrgContext = Ctx, db: Session = Db, a: Access = Acc):
    return done(db, WP.add_comment(db, ctx, a, wid, body.get("body"), kind=body.get("kind") or "comment", mandatory=bool(body.get("mandatory")), parent_id=body.get("parent_id")))


@docs_router.post("/workpapers/{wid}/comments/{cid}/resolve")
def wp_resolve(wid: int, cid: int, ctx: OrgContext = Ctx, db: Session = Db, a: Access = Acc):
    return done(db, WP.resolve_comment(db, ctx, a, wid, cid))


@docs_router.post("/workpapers/{wid}/documents")
def wp_attach(wid: int, body: dict = Body(...), ctx: OrgContext = Ctx, db: Session = Db, a: Access = Acc):
    return done(db, WP.attach_document(db, ctx, a, wid, int(body.get("document_id") or 0)))


@docs_router.delete("/workpapers/{wid}/documents/{doc_id}")
def wp_detach(wid: int, doc_id: int, ctx: OrgContext = Ctx, db: Session = Db, a: Access = Acc):
    return done(db, WP.detach_document(db, ctx, a, wid, doc_id))


@docs_router.post("/workpapers/{wid}/refs")
def wp_ref(wid: int, body: dict = Body(...), ctx: OrgContext = Ctx, db: Session = Db, a: Access = Acc):
    return done(db, WP.add_ref(db, ctx, a, wid, body.get("kind"), body.get("params") or {}, body.get("note") or ""))


@docs_router.get("/workpapers/{wid}/refs/check")
def wp_refs_check(wid: int, ctx: OrgContext = Ctx, db: Session = Db, a: Access = Acc):
    return WP.check_refs(db, ctx, a, wid)


# =============================================================================================================================== engagements & workflows
eng_router = APIRouter()


@eng_router.get("/engagement-templates")
def eng_templates(db: Session = Db, a: Access = Acc):
    return EN.templates(db, a)


@eng_router.post("/engagement-templates")
def eng_template_create(body: dict = Body(...), ctx: OrgContext = Ctx, db: Session = Db, a: Access = Acc):
    return done(db, EN.create_template(db, ctx, a, body.get("name"), body.get("service_type"), body.get("jobs"), body.get("deadline_rule_id")))


@eng_router.get("/deadline-rules")
def rules(db: Session = Db, a: Access = Acc):
    return EN.rules(db, a)


@eng_router.post("/deadline-rules")
def rule_create(body: dict = Body(...), ctx: OrgContext = Ctx, db: Session = Db, a: Access = Acc):
    return done(db, EN.create_rule(db, ctx, a, body.get("name"), body.get("kind"), body.get("rule") or {}, service_type=body.get("service_type"), source=body.get("source"), source_verified_at=body.get("source_verified_at")))


@eng_router.get("/engagements")
def eng_list(client_id: Optional[int] = None, status: Optional[str] = None, service_type: Optional[str] = None, page: int = 1, size: int = 25, db: Session = Db, a: Access = Acc):
    return EN.listing(db, a, client_id=client_id, status=status, service_type=service_type, page_no=page, size=size)


@eng_router.post("/engagements")
def eng_create(body: dict = Body(...), ctx: OrgContext = Ctx, db: Session = Db, a: Access = Acc):
    keys = ("template_id", "period_from", "period_to", "entity_id", "billing_basis", "fixed_fee", "scope", "deliverables", "manager_id", "preparer_id", "reviewer_id")
    return done(db, EN.create(db, ctx, a, int(body.get("client_id") or 0), body.get("title"), body.get("service_type"), **{k: body[k] for k in keys if k in body}))


@eng_router.get("/engagements/{eid}")
def eng_get(eid: int, db: Session = Db, a: Access = Acc):
    return EN.get(db, a, eid)


@eng_router.post("/engagements/{eid}/transition")
def eng_transition(eid: int, body: dict = Body(...), ctx: OrgContext = Ctx, db: Session = Db, a: Access = Acc):
    return done(db, EN.transition(db, ctx, a, eid, body.get("action"), reason=body.get("reason"), accepted_by=body.get("accepted_by")))


@eng_router.post("/engagements/{eid}/renew")
def eng_renew(eid: int, ctx: OrgContext = Ctx, db: Session = Db, a: Access = Acc):
    return done(db, EN.renew(db, ctx, a, eid))


@eng_router.post("/engagements/{eid}/deadlines")
def dl_add(eid: int, body: dict = Body(...), ctx: OrgContext = Ctx, db: Session = Db, a: Access = Acc):
    return done(db, EN.add_deadline(db, ctx, a, eid, int(body.get("rule_id") or 0), period_end=body.get("period_end"), title=body.get("title"), job_id=body.get("job_id")))


@eng_router.get("/deadlines")
def dl_list(client_id: Optional[int] = None, kind: Optional[str] = None, state: Optional[str] = None, status: Optional[str] = None, page: int = 1, size: int = 50, db: Session = Db, a: Access = Acc):
    return EN.deadlines(db, a, client_id=client_id, kind=kind, state=state, status=status, page_no=page, size=size)


@eng_router.post("/deadlines/{did}/verify")
def dl_verify(did: int, body: dict = Body(...), ctx: OrgContext = Ctx, db: Session = Db, a: Access = Acc):
    return done(db, EN.verify_deadline(db, ctx, a, did, body.get("source")))


@eng_router.post("/deadlines/{did}/override")
def dl_override(did: int, body: dict = Body(...), ctx: OrgContext = Ctx, db: Session = Db, a: Access = Acc):
    return done(db, EN.override_deadline(db, ctx, a, did, body.get("new_due"), body.get("reason")))


@eng_router.post("/deadlines/{did}/complete")
def dl_complete(did: int, ctx: OrgContext = Ctx, db: Session = Db, a: Access = Acc):
    return done(db, EN.complete_deadline(db, ctx, a, did))


@eng_router.get("/my-work")
def my_work(page: int = 1, size: int = 50, db: Session = Db, a: Access = Acc):
    return EN.my_work(db, a, page_no=page, size=size)


@eng_router.post("/jobs/{jid}/transition")
def job_transition(jid: int, body: dict = Body(...), ctx: OrgContext = Ctx, db: Session = Db, a: Access = Acc):
    return done(db, EN.job_transition(db, ctx, a, jid, body.get("action"), reason=body.get("reason")))


@eng_router.put("/jobs/{jid}/assignment")
def job_assign(jid: int, body: dict = Body(...), ctx: OrgContext = Ctx, db: Session = Db, a: Access = Acc):
    return done(db, EN.assign_job(db, ctx, a, jid, owner_id=body.get("owner_id"), reviewer_id=body.get("reviewer_id")))


@eng_router.get("/jobs/{jid}/review-points")
def points(jid: int, db: Session = Db, a: Access = Acc):
    return EN.points(db, a, jid)


@eng_router.post("/jobs/{jid}/review-points")
def point_raise(jid: int, body: dict = Body(...), ctx: OrgContext = Ctx, db: Session = Db, a: Access = Acc):
    return done(db, EN.raise_point(db, ctx, a, jid, body.get("finding"), bool(body.get("mandatory", True))))


@eng_router.post("/review-points/{pid}/respond")
def point_respond(pid: int, body: dict = Body(...), ctx: OrgContext = Ctx, db: Session = Db, a: Access = Acc):
    return done(db, EN.respond_point(db, ctx, a, pid, body.get("response")))


@eng_router.post("/review-points/{pid}/resolve")
def point_resolve(pid: int, ctx: OrgContext = Ctx, db: Session = Db, a: Access = Acc):
    return done(db, EN.resolve_point(db, ctx, a, pid))


@eng_router.post("/tasks/{tid}/{action}")
def task_action(tid: int, action: str, ctx: OrgContext = Ctx, db: Session = Db, a: Access = Acc):
    return done(db, EN.task_transition(db, ctx, a, tid, action))


@eng_router.post("/checklist/{item_id}")
def tick(item_id: int, body: dict = Body(default={}), ctx: OrgContext = Ctx, db: Session = Db, a: Access = Acc):
    return done(db, EN.tick(db, ctx, a, item_id, bool(body.get("done", True))))


@eng_router.post("/recurrences")
def recurrence(body: dict = Body(...), ctx: OrgContext = Ctx, db: Session = Db, a: Access = Acc):
    return done(db, EN.create_recurrence(db, ctx, a, int(body.get("client_id") or 0), int(body.get("template_id") or 0), body.get("frequency"), body.get("next_period_end")))


@eng_router.post("/recurrences/run")
def recurrence_run(ctx: OrgContext = Ctx, db: Session = Db, a: Access = Acc):
    a.require("engagements")
    out = EN.run_recurrences(db, a.practice_id, core.today())
    out["reminders"] = EN.run_reminders(db, a.practice_id, core.today())
    return done(db, out)


# =============================================================================================================================== client portal (staff side)
portal_staff_router = APIRouter()


@portal_staff_router.post("/portal/invitations")
def invite(body: dict = Body(...), ctx: OrgContext = Ctx, db: Session = Db, a: Access = Acc):
    return done(db, PT.invite(db, ctx, a, int(body.get("client_id") or 0), int(body.get("contact_id") or 0), body.get("entity_ids")))


@portal_staff_router.get("/portal/invitations")
def invites(client_id: Optional[int] = None, db: Session = Db, a: Access = Acc):
    return PT.invites(db, a, client_id)


@portal_staff_router.post("/portal/invitations/{iid}/resend")
def resend(iid: int, ctx: OrgContext = Ctx, db: Session = Db, a: Access = Acc):
    return done(db, PT.resend(db, ctx, a, iid))


@portal_staff_router.post("/portal/invitations/{iid}/revoke")
def revoke_inv(iid: int, ctx: OrgContext = Ctx, db: Session = Db, a: Access = Acc):
    return done(db, PT.revoke_invite(db, ctx, a, iid))


@portal_staff_router.get("/portal/access/{client_id}")
def accesses(client_id: int, db: Session = Db, a: Access = Acc):
    return PT.accesses(db, a, client_id)


@portal_staff_router.post("/portal/access/{aid}/revoke")
def revoke_access(aid: int, ctx: OrgContext = Ctx, db: Session = Db, a: Access = Acc):
    return done(db, PT.revoke_access(db, ctx, a, aid))


@portal_staff_router.get("/portal/requests")
def reqs(client_id: Optional[int] = None, status: Optional[str] = None, db: Session = Db, a: Access = Acc):
    return PT.requests_staff(db, a, client_id, status)


@portal_staff_router.post("/portal/requests")
def req_create(body: dict = Body(...), ctx: OrgContext = Ctx, db: Session = Db, a: Access = Acc):
    return done(db, PT.create_request(db, ctx, a, int(body.get("client_id") or 0), body.get("title"), body.get("items") or [], description=body.get("description"), due_date=body.get("due_date"),
                                      entity_id=body.get("entity_id"), engagement_id=body.get("engagement_id")))


@portal_staff_router.post("/portal/request-items/{item_id}/review")
def req_review(item_id: int, body: dict = Body(...), ctx: OrgContext = Ctx, db: Session = Db, a: Access = Acc):
    return done(db, PT.review_item(db, ctx, a, item_id, body.get("decision"), body.get("note") or ""))


@portal_staff_router.post("/portal/requests/{rid}/cancel")
def req_cancel(rid: int, ctx: OrgContext = Ctx, db: Session = Db, a: Access = Acc):
    return done(db, PT.cancel_request(db, ctx, a, rid))


@portal_staff_router.get("/portal/messages/{client_id}")
def msgs(client_id: int, db: Session = Db, a: Access = Acc):
    return PT.messages_staff(db, a, client_id)


@portal_staff_router.post("/portal/messages/{client_id}")
def msg_post(client_id: int, body: dict = Body(...), ctx: OrgContext = Ctx, db: Session = Db, a: Access = Acc):
    return done(db, PT.post_staff(db, ctx, a, client_id, body.get("body"), body.get("visibility") or "internal", request_id=body.get("request_id")))


@portal_staff_router.get("/portal/deliveries")
def deliveries(client_id: Optional[int] = None, db: Session = Db, a: Access = Acc):
    return PT.delivery_report(db, a, client_id)


@portal_staff_router.post("/portal/deliveries/retry")
def retry(ctx: OrgContext = Ctx, db: Session = Db, a: Access = Acc):
    a.require("portal")
    return done(db, PT.retry_failed(db, a.practice_id))


@portal_staff_router.get("/portal/activity/{client_id}")
def activity(client_id: int, db: Session = Db, a: Access = Acc):
    return PT.activity_staff(db, a, client_id)


# =============================================================================================================================== billing
billing_router = APIRouter()


@billing_router.get("/billing/dashboard")
def bill_dash(date_from: Optional[str] = None, date_to: Optional[str] = None, db: Session = Db, a: Access = Acc):
    return BL.dashboard(db, a, date_from=date_from, date_to=date_to)


@billing_router.get("/billing/rates")
def rates(db: Session = Db, a: Access = Acc):
    return BL.rates(db, a)


@billing_router.post("/billing/rates")
def rate_set(body: dict = Body(...), ctx: OrgContext = Ctx, db: Session = Db, a: Access = Acc):
    return done(db, BL.set_rate(db, ctx, a, body.get("hourly_rate"), user_id=body.get("staff_id"), client_id=body.get("client_id"), service_type=body.get("service_type"),
                                effective_from=body.get("effective_from"), effective_to=body.get("effective_to")))


@billing_router.get("/billing/time")
def time_list(mine: bool = False, client_id: Optional[int] = None, status: Optional[str] = None, staff_id: Optional[int] = None, date_from: Optional[str] = None, date_to: Optional[str] = None,
              page: int = 1, size: int = 50, db: Session = Db, a: Access = Acc):
    return BL.list_time(db, a, mine=mine, client_id=client_id, status=status, user_id=staff_id, date_from=date_from, date_to=date_to, page_no=page, size=size)


@billing_router.post("/billing/time")
def time_log(body: dict = Body(...), ctx: OrgContext = Ctx, db: Session = Db, a: Access = Acc):
    return done(db, BL.log_time(db, ctx, a, int(body.get("client_id") or 0), body.get("work_date"), body.get("minutes"), body.get("description"), billable=bool(body.get("billable", True)),
                                engagement_id=body.get("engagement_id"), job_id=body.get("job_id"), task_id=body.get("task_id"), entity_id=body.get("entity_id")))


@billing_router.put("/billing/time/{tid}")
def time_update(tid: int, body: dict = Body(...), ctx: OrgContext = Ctx, db: Session = Db, a: Access = Acc):
    return done(db, BL.update_time(db, ctx, a, tid, body))


@billing_router.delete("/billing/time/{tid}")
def time_delete(tid: int, ctx: OrgContext = Ctx, db: Session = Db, a: Access = Acc):
    return done(db, BL.delete_time(db, ctx, a, tid))


@billing_router.post("/billing/time/submit")
def time_submit(body: dict = Body(...), ctx: OrgContext = Ctx, db: Session = Db, a: Access = Acc):
    return done(db, BL.submit_time(db, ctx, a, _ids(body.get("ids"))))


@billing_router.post("/billing/time/approve")
def time_approve(body: dict = Body(...), ctx: OrgContext = Ctx, db: Session = Db, a: Access = Acc):
    return done(db, BL.approve_time(db, ctx, a, _ids(body.get("ids"))))


@billing_router.post("/billing/time/reject")
def time_reject(body: dict = Body(...), ctx: OrgContext = Ctx, db: Session = Db, a: Access = Acc):
    return done(db, BL.reject_time(db, ctx, a, _ids(body.get("ids")), body.get("reason")))


@billing_router.post("/billing/time/{tid}/write-off")
def time_writeoff(tid: int, body: dict = Body(...), ctx: OrgContext = Ctx, db: Session = Db, a: Access = Acc):
    return done(db, BL.write_off(db, ctx, a, tid, body.get("reason")))


@billing_router.get("/billing/invoices")
def inv_list(client_id: Optional[int] = None, status: Optional[str] = None, page: int = 1, size: int = 25, db: Session = Db, a: Access = Acc):
    return BL.invoices(db, a, client_id=client_id, status=status, page_no=page, size=size)


@billing_router.post("/billing/invoices")
def inv_generate(body: dict = Body(...), ctx: OrgContext = Ctx, db: Session = Db, a: Access = Acc):
    return done(db, BL.generate(db, ctx, a, int(body.get("client_id") or 0), time_entry_ids=body.get("time_entry_ids"), engagement_id=body.get("engagement_id"),
                                fixed_fee_engagement_id=body.get("fixed_fee_engagement_id"), adjustments=body.get("adjustments"), idempotency_key=body.get("idempotency_key"), reference=body.get("reference")))


@billing_router.get("/billing/invoices/{iid}")
def inv_get(iid: int, db: Session = Db, a: Access = Acc):
    return BL.get_invoice(db, a, iid)


@billing_router.post("/billing/invoices/{iid}/adjustments")
def inv_adjust(iid: int, body: dict = Body(...), ctx: OrgContext = Ctx, db: Session = Db, a: Access = Acc):
    return done(db, BL.add_adjustment(db, ctx, a, iid, body.get("description"), body.get("amount"), body.get("reason")))


@billing_router.post("/billing/invoices/{iid}/issue")
def inv_issue(iid: int, body: dict = Body(default={}), ctx: OrgContext = Ctx, db: Session = Db, a: Access = Acc):
    return done(db, BL.issue(db, ctx, a, iid, issue_date=body.get("issue_date")))


@billing_router.post("/billing/invoices/{iid}/void")
def inv_void(iid: int, body: dict = Body(...), ctx: OrgContext = Ctx, db: Session = Db, a: Access = Acc):
    return done(db, BL.void(db, ctx, a, iid, body.get("reason")))


@billing_router.post("/billing/invoices/{iid}/credit-note")
def inv_credit(iid: int, body: dict = Body(...), ctx: OrgContext = Ctx, db: Session = Db, a: Access = Acc):
    return done(db, BL.credit_note(db, ctx, a, iid, body.get("amount"), body.get("reason")))


@billing_router.post("/billing/invoices/{iid}/share")
def inv_share(iid: int, body: dict = Body(default={}), ctx: OrgContext = Ctx, db: Session = Db, a: Access = Acc):
    return done(db, BL.share_invoice(db, ctx, a, iid, bool(body.get("visible", True))))


# =============================================================================================================================== client portal (client side)
portal_router = APIRouter()
Login = Depends(portal_login)


def _view(db, login, client_id):
    return PT.View(db, login, client_id)


@portal_router.post("/invitations/lookup")
def inv_lookup(body: dict = Body(...), db: Session = Db):
    return PT.lookup_invite(db, body.get("token") or "")


@portal_router.post("/invitations/accept")
def inv_accept(body: dict = Body(...), db: Session = Db):
    return done(db, PT.accept_new_account(db, body.get("token") or "", body.get("full_name"), body.get("password") or "", body.get("phone") or ""))


@portal_router.post("/invitations/claim")
def inv_claim(body: dict = Body(...), login: int = Login, db: Session = Db):
    return done(db, PT.claim(db, login, body.get("token") or ""))


@portal_router.get("/clients")
def my_clients(login: int = Login, db: Session = Db):
    return PT.my_clients(db, login)


@portal_router.get("/clients/{client_id}/dashboard")
def p_dash(client_id: int, login: int = Login, db: Session = Db):
    return PT.dashboard(db, _view(db, login, client_id))


@portal_router.get("/clients/{client_id}/documents")
def p_docs(client_id: int, page: int = 1, size: int = 25, login: int = Login, db: Session = Db):
    return PT.documents(db, _view(db, login, client_id), page, size)


@portal_router.post("/clients/{client_id}/documents/{doc_id}/ticket")
def p_ticket(client_id: int, doc_id: int, login: int = Login, db: Session = Db):
    return done(db, PT.doc_ticket(db, _view(db, login, client_id), doc_id))


@portal_router.post("/clients/{client_id}/download")
def p_download(client_id: int, body: dict = Body(...), login: int = Login, db: Session = Db):
    out = PT.doc_download(db, _view(db, login, client_id), body.get("ticket") or "")
    db.commit()
    return _file_response(out)


@portal_router.get("/clients/{client_id}/requests")
def p_reqs(client_id: int, login: int = Login, db: Session = Db):
    return PT.requests_portal(db, _view(db, login, client_id))


@portal_router.post("/clients/{client_id}/request-items/{item_id}/text")
def p_text(client_id: int, item_id: int, body: dict = Body(...), login: int = Login, db: Session = Db):
    return done(db, PT.respond_text(db, _view(db, login, client_id), item_id, body.get("text")))


@portal_router.post("/clients/{client_id}/request-items/{item_id}/file")
async def p_file(client_id: int, item_id: int, file: UploadFile = File(...), login: int = Login, db: Session = Db):
    v = _view(db, login, client_id)
    data = await _read(file, int(core.get_settings(v.practice).get("max_file_mb", 10)) * 1024 * 1024)
    return done(db, PT.upload_for_item(db, v, item_id, file.filename or "", data))


@portal_router.get("/clients/{client_id}/messages")
def p_msgs(client_id: int, login: int = Login, db: Session = Db):
    return PT.messages_portal(db, _view(db, login, client_id))


@portal_router.post("/clients/{client_id}/messages")
def p_msg(client_id: int, body: dict = Body(...), login: int = Login, db: Session = Db):
    return done(db, PT.post_portal(db, _view(db, login, client_id), body.get("body"), body.get("request_id")))


@portal_router.get("/clients/{client_id}/invoices")
def p_invoices(client_id: int, login: int = Login, db: Session = Db):
    return PT.invoices_portal(db, _view(db, login, client_id))


@portal_router.get("/clients/{client_id}/consents")
def p_consents(client_id: int, login: int = Login, db: Session = Db):
    return PT.consents_portal(db, _view(db, login, client_id))


@portal_router.post("/clients/{client_id}/consents")
def p_consent(client_id: int, body: dict = Body(...), login: int = Login, db: Session = Db):
    return done(db, PT.record_consent_portal(db, _view(db, login, client_id), body.get("key"), bool(body.get("granted"))))


@portal_router.get("/clients/{client_id}/notifications")
def p_notes(client_id: int, login: int = Login, db: Session = Db):
    return PT.notifications_portal(db, _view(db, login, client_id))


@portal_router.post("/clients/{client_id}/notifications/{nid}/read")
def p_read(client_id: int, nid: int, login: int = Login, db: Session = Db):
    return done(db, PT.mark_read(db, _view(db, login, client_id), nid))


# =============================================================================================================================== bulk CSV loading
from accfino.modules.practice.services import bulk as BK          # noqa: E402
from accfino.shared import bulkload as _BL                        # noqa: E402

bulk_router = _BL.build_router(BK.SPECS, ctx_dep=current_org, db_dep=get_db, access_dep=access, gate=BK.gate, enabled=BK.enabled, audit=BK.audit)
