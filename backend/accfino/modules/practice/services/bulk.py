"""Practice & Client Services: CSV bulk loading of every table that people enter by hand.

Each importer calls the SAME service function the screen uses, so permissions, client scope, duplicate checks, validation and audit all apply row by row.
Staff are named by e-mail address and clients/entities by their reference, so a file can be written without knowing any database id.

NOT bulk-loadable on purpose (they are produced by workflows, carry files/secrets, or would send e-mail to clients):
  documents and versions (files, not CSV rows), portal invitations (each carries a one-time link e-mailed to a person), workpaper content after creation (review workflow),
  jobs / tasks / checklists (generated from the engagement template), invoices and invoice lines (generated from approved time),
  write-offs, notifications, download tickets, audit log, run logs, duplicate-review decisions (decisions are made by a person)."""
from sqlalchemy import func

from accfino.shared import bulkload as BL
from accfino.shared.bulkload import Column as C, RowError, Spec, as_bool, as_date, as_int, as_json, as_list, need

from accfino.core import models as m
from accfino.core.identity.user import User
from accfino.modules.practice.models import practice as P
from accfino.modules.practice.services import billing as BIL, clients as CL, core, engagements as EN, portal as PT, practice as PR, workpapers as WP
from accfino.modules.practice.services.core import PcError

CAP = "import"            # every bulk load needs the practice 'import' capability (admin, partner, manager) on top of the table's own capability


# ------------------------------------------------------------------------------------------------------------------------------ lookups by e-mail / reference
def staff(db, a, email, what="Staff member", required=False):
    e = (email or "").strip().lower()
    if not e:
        if required:
            raise RowError(f"{what} e-mail is required")
        return None
    u = db.query(User).filter(func.lower(User.email) == e).first()
    if u is None or not a.member_of(u.id):
        raise RowError(f"{what} {e}: no active member of this practice has that e-mail address")
    return u.id


def client(db, a, ref, required=True, allow_archived=True):
    r = (ref or "").strip()
    if not r:
        if required:
            raise RowError("client_ref is required")
        return None
    c = a.scoped_clients().filter(P.PcClient.ref == r).first()
    if c is None:
        raise RowError(f"Client {r} was not found (or you are not allowed to see it)")
    return c


def entity(db, a, ref, required=False):
    r = (ref or "").strip()
    if not r:
        if required:
            raise RowError("entity_ref is required")
        return None
    e = db.query(P.PcEntity).filter_by(practice_id=a.practice_id, ref=r).first()
    if e is None:
        raise RowError(f"Entity {r} was not found")
    CL.entity_row(db, a, e.id)                       # scope check: 404 -> row error
    return e


def team_id(db, a, name):
    n = (name or "").strip()
    if not n:
        return None
    t = db.query(P.PcTeam).filter_by(practice_id=a.practice_id, name=n).first()
    if t is None:
        raise RowError(f"Team '{n}' does not exist (load the teams table first)")
    return t.id


def by_name(db, a, model, name, what):
    n = (name or "").strip()
    if not n:
        return None
    r = db.query(model).filter_by(practice_id=a.practice_id, name=n).first()
    if r is None:
        raise RowError(f"{what} '{n}' does not exist (load it first)")
    return r


def engagement(db, a, c, title):
    t = (title or "").strip()
    if not t:
        return None
    e = db.query(P.PcEngagement).filter_by(practice_id=a.practice_id, client_id=c.id, title=t).order_by(P.PcEngagement.id.desc()).first()
    if e is None:
        raise RowError(f"Engagement '{t}' for client {c.ref} does not exist (load engagements first)")
    return e


def drop_none(d):
    return {k: v for k, v in d.items() if v not in (None, "")}


# --------------------------------------------------------------------------------------------------------------------------------------------- handlers
def h_members(db, ctx, a, r):
    need(r, "email", "role")
    u = db.query(User).filter(func.lower(User.email) == r["email"].lower()).first()
    if u is None:
        raise RowError("No user with that e-mail address (add the user in Settings > Users first)")
    PR.add_member(db, ctx, a, u.id, r["role"].strip().lower())


def h_teams(db, ctx, a, r):
    need(r, "team")
    ids = [staff(db, a, e, "Team member") for e in BL.as_list(r.get("member_emails"))]
    t = db.query(P.PcTeam).filter_by(practice_id=a.practice_id, name=r["team"].strip()).first()
    if t is None:
        PR.create_team(db, ctx, a, r["team"], ids)
    else:
        PR.set_team_members(db, ctx, a, t.id, ids)


def h_clients(db, ctx, a, r):
    need(r, "client_type", "legal_name")
    body = drop_none(dict(ref=r.get("ref"), client_type=r["client_type"].lower(), legal_name=r["legal_name"], preferred_name=r.get("preferred_name"), email=r.get("email"), phone=r.get("phone"),
                          abn=r.get("abn"), postal_address=r.get("postal_address"), manager_id=staff(db, a, r.get("manager_email"), "Manager"),
                          preparer_id=staff(db, a, r.get("preparer_email"), "Preparer"), reviewer_id=staff(db, a, r.get("reviewer_email"), "Reviewer"), team_id=team_id(db, a, r.get("team"))))
    CL.create_client(db, ctx, a, body, allow_duplicate=as_bool(r.get("allow_duplicate"), "allow_duplicate"))


def h_assignments(db, ctx, a, r):
    c = client(db, a, r.get("client_ref"))
    body = drop_none(dict(manager_id=staff(db, a, r.get("manager_email"), "Manager"), preparer_id=staff(db, a, r.get("preparer_email"), "Preparer"),
                          reviewer_id=staff(db, a, r.get("reviewer_email"), "Reviewer"), team_id=team_id(db, a, r.get("team"))))
    if not body:
        raise RowError("Nothing to assign: give at least one of manager_email, preparer_email, reviewer_email, team")
    CL.update_client(db, ctx, a, c.id, body)


def h_entities(db, ctx, a, r):
    need(r, "entity_type", "name")
    c = client(db, a, r.get("client_ref"), required=False)
    body = drop_none(dict(entity_type=r["entity_type"].lower(), name=r["name"], ref=r.get("ref"), abn=r.get("abn"), acn=r.get("acn")))
    CL.create_entity(db, ctx, a, body, client_id=c.id if c else None, relationship=(r.get("relationship") or "manages"), allow_duplicate=as_bool(r.get("allow_duplicate"), "allow_duplicate"))


def h_relations(db, ctx, a, r):
    need(r, "parent_ref", "child_ref", "kind")
    CL.add_relation(db, ctx, a, entity(db, a, r["parent_ref"], True).id, entity(db, a, r["child_ref"], True).id, r["kind"].lower(), percent=r.get("percent") or None,
                    effective_from=r.get("effective_from") or None, effective_to=r.get("effective_to") or None, verified_source=r.get("verified_source") or None)


def h_contacts(db, ctx, a, r):
    need(r, "full_name")
    c = client(db, a, r.get("client_ref"))
    e = entity(db, a, r.get("entity_ref"))
    flags = {k: as_bool(r.get(k), k) for k in ("is_primary", "can_use_portal", "is_authorised_rep", "can_approve_work", "can_receive_documents")}
    CL.add_contact(db, ctx, a, c.id, dict(full_name=r["full_name"], email=r.get("email") or None, phone=r.get("phone") or None, **flags), entity_id=e.id if e else None)


def h_consents(db, ctx, a, r):
    need(r, "key")
    CL.record_consent(db, ctx, a, client(db, a, r.get("client_ref")).id, r["key"], as_bool(r.get("granted"), "granted", default=None))


def h_notes(db, ctx, a, r):
    need(r, "body")
    CL.add_note(db, ctx, a, client(db, a, r.get("client_ref")).id, r["body"], (r.get("kind") or "note").lower())


def h_identifiers(db, ctx, a, r):
    need(r, "owner_kind", "owner_ref", "kind", "value")
    k = r["owner_kind"].lower()
    if k == "client":
        oid = client(db, a, r["owner_ref"]).id
    elif k == "entity":
        oid = entity(db, a, r["owner_ref"], True).id
    else:
        raise RowError("owner_kind must be client or entity")
    CL.set_identifier(db, ctx, a, k, oid, r["kind"].lower(), r["value"])


def h_wp_templates(db, ctx, a, r):
    need(r, "name", "category")
    WP.create_template(db, ctx, a, r["name"], r["category"], as_json(r.get("lines_json"), "lines_json", []))


def h_workpapers(db, ctx, a, r):
    need(r, "title")
    c = client(db, a, r.get("client_ref"))
    t = by_name(db, a, P.PcWpTemplate, r.get("template"), "Workpaper template")
    e = entity(db, a, r.get("entity_ref"))
    WP.create(db, ctx, a, c.id, r["title"], category=(r.get("category") or (t.category if t else "general")), template_id=t.id if t else None, entity_id=e.id if e else None,
              period_from=as_date(r.get("period_from"), "period_from"), period_to=as_date(r.get("period_to"), "period_to"), reviewer_id=staff(db, a, r.get("reviewer_email"), "Reviewer"))


def h_rules(db, ctx, a, r):
    need(r, "name", "kind", "rule_json")
    EN.create_rule(db, ctx, a, r["name"], r["kind"].lower(), as_json(r["rule_json"], "rule_json"), service_type=r.get("service_type") or None, source=r.get("source") or None,
                   source_verified_at=as_date(r.get("source_verified_at"), "source_verified_at"))


def h_eng_templates(db, ctx, a, r):
    need(r, "name", "service_type", "jobs_json")
    rule = by_name(db, a, P.PcDeadlineRule, r.get("deadline_rule"), "Deadline rule")
    EN.create_template(db, ctx, a, r["name"], r["service_type"].lower(), as_json(r["jobs_json"], "jobs_json"), deadline_rule_id=rule.id if rule else None)


def h_engagements(db, ctx, a, r):
    need(r, "title", "service_type")
    c = client(db, a, r.get("client_ref"))
    t = by_name(db, a, P.PcEngTemplate, r.get("template"), "Engagement template")
    e = entity(db, a, r.get("entity_ref"))
    EN.create(db, ctx, a, c.id, r["title"], r["service_type"].lower(), template_id=t.id if t else None, period_from=as_date(r.get("period_from"), "period_from"), period_to=as_date(r.get("period_to"), "period_to"),
              entity_id=e.id if e else None, billing_basis=(r.get("billing_basis") or "hourly").lower(), fixed_fee=r.get("fixed_fee") or None, scope=r.get("scope") or None,
              manager_id=staff(db, a, r.get("manager_email"), "Manager"), preparer_id=staff(db, a, r.get("preparer_email"), "Preparer"), reviewer_id=staff(db, a, r.get("reviewer_email"), "Reviewer"))


def h_deadlines(db, ctx, a, r):
    need(r, "engagement_title", "rule")
    c = client(db, a, r.get("client_ref"))
    EN.add_deadline(db, ctx, a, engagement(db, a, c, r["engagement_title"]).id, by_name(db, a, P.PcDeadlineRule, r["rule"], "Deadline rule").id, period_end=as_date(r.get("period_end"), "period_end"), title=r.get("title") or None)


def h_recurrences(db, ctx, a, r):
    need(r, "template", "frequency", "next_period_end")
    EN.create_recurrence(db, ctx, a, client(db, a, r.get("client_ref")).id, by_name(db, a, P.PcEngTemplate, r["template"], "Engagement template").id, r["frequency"].lower(), as_date(r["next_period_end"], "next_period_end", True))


def h_requests(db, ctx, a, r):
    need(r, "title", "items")
    c = client(db, a, r.get("client_ref"))
    e = entity(db, a, r.get("entity_ref"))
    rt = (r.get("response_types") or "file").lower()
    PT.create_request(db, ctx, a, c.id, r["title"], [dict(description=x, response_types=rt) for x in BL.as_list(r["items"], "|")], description=r.get("description") or None,
                      due_date=as_date(r.get("due_date"), "due_date"), entity_id=e.id if e else None)


def h_rates(db, ctx, a, r):
    need(r, "hourly_rate")
    c = client(db, a, r.get("client_ref"), required=False)
    BIL.set_rate(db, ctx, a, r["hourly_rate"], user_id=staff(db, a, r.get("staff_email"), "Staff member"), client_id=c.id if c else None, service_type=r.get("service_type") or None,
                 effective_from=as_date(r.get("effective_from"), "effective_from"), effective_to=as_date(r.get("effective_to"), "effective_to"))


def h_time(db, ctx, a, r):
    need(r, "work_date", "minutes", "description")
    c = client(db, a, r.get("client_ref"), allow_archived=False)
    e = engagement(db, a, c, r.get("engagement_title"))
    BIL.log_time(db, ctx, a, c.id, as_date(r["work_date"], "work_date", True), as_int(r["minutes"], "minutes", True), r["description"], billable=as_bool(r.get("billable"), "billable", default=True),
                 engagement_id=e.id if e else None, for_staff_id=staff(db, a, r.get("staff_email"), "Staff member"))


def _spec(order, key, label, area, cap, cols, handler, notes=""):
    return Spec(key=key, label=label, area=area, capability=CAP, columns=cols, handler=_guard(cap, handler), order=order, notes=notes)


def _guard(cap, handler):
    """The table's own capability is checked row by row by the service; this adds the explicit check up front so a role without it is refused (403) before any row is read."""
    def wrapped(db, ctx, a, r):
        a.require(cap)
        return handler(db, ctx, a, r)
    return wrapped


SPECS = {s.key: s for s in [
    _spec(10, "members", "Practice members", "Practice", "members", [C("email", True, "E-mail of an existing organisation user", "priya.partner@firm.example"), C("role", True, "admin, partner, manager, preparer, reviewer, billing, readonly", "partner")], h_members,
          "Users must already exist in Settings > Users. Payroll-only users are refused."),
    _spec(20, "teams", "Teams", "Practice", "members", [C("team", True, "Team name (created, or its members replaced if it exists)", "Tax Team"), C("member_emails", False, "Practice members, separated by ;", "a@firm.example;b@firm.example")], h_teams),
    _spec(30, "clients", "Clients", "Clients", "clients_edit", [C("ref", False, "Your own reference; blank = next number", "C0001"), C("client_type", True, "individual or organisation", "organisation"), C("legal_name", True, "", "Acme Pty Ltd"),
          C("preferred_name"), C("email"), C("phone", False, "", "+61412345678"), C("abn", False, "Checksum validated, stored sealed", "51 824 753 556"), C("postal_address"), C("manager_email"), C("preparer_email"), C("reviewer_email"),
          C("team", False, "An existing team name"), C("allow_duplicate", False, "yes to create despite a strong duplicate match", "no")], h_clients,
          "A strong duplicate (same ABN, or the same name and e-mail) is rejected unless allow_duplicate = yes. Nothing is ever merged automatically."),
    _spec(40, "client_assignments", "Client assignments", "Clients", "clients_edit", [C("client_ref", True, "", "C0001"), C("manager_email"), C("preparer_email"), C("reviewer_email"), C("team")], h_assignments,
          "Only the columns you fill are changed. Preparer and reviewer must be different people."),
    _spec(50, "entities", "Entities", "Clients", "clients_edit", [C("ref", False, "", "E-0001"), C("entity_type", True, "individual, sole_trader, company, trust, partnership, smsf", "trust"), C("name", True, "", "Smith Family Trust"),
          C("abn"), C("acn", False, "Required for a company"), C("client_ref", False, "Link to this client", "C0001"), C("relationship", False, "default manages", "manages"), C("allow_duplicate")], h_entities),
    _spec(60, "entity_relations", "Entity relationships", "Clients", "clients_edit", [C("parent_ref", True, "", "E-0002"), C("child_ref", True, "", "E-0001"), C("kind", True, "owns, controls, trustee_of, partner_in, subsidiary_of", "trustee_of"),
          C("percent", False, "0-100, only for owns", ""), C("effective_from"), C("effective_to"), C("verified_source", False, "Where it was verified; blank = shown as UNVERIFIED", "")], h_relations,
          "Cycles are refused. Ownership is never inferred from other rows."),
    _spec(70, "contacts", "Contacts and authority", "Clients", "clients_edit", [C("client_ref", True, "", "C0001"), C("entity_ref"), C("full_name", True, "", "Olivia Okafor"), C("email"), C("phone"), C("is_primary", False, "yes/no"),
          C("can_use_portal"), C("is_authorised_rep"), C("can_approve_work"), C("can_receive_documents")], h_contacts),
    _spec(80, "consents", "Consents", "Clients", "clients_edit", [C("client_ref", True, "", "C0001"), C("key", True, "e.g. email_contact", "email_contact"), C("granted", True, "yes/no", "yes")], h_consents,
          "Each row is appended to the consent history; nothing is overwritten."),
    _spec(90, "client_notes", "Contact history notes", "Clients", "clients_edit", [C("client_ref", True, "", "C0001"), C("kind", False, "note, call, meeting, email", "call"), C("body", True, "", "Called about BAS")], h_notes),
    _spec(100, "identifiers", "Tax identifiers", "Clients", "tax_ids", [C("owner_kind", True, "client or entity", "client"), C("owner_ref", True, "Client or entity reference", "C0002"), C("kind", True, "tfn, abn or acn", "tfn"), C("value", True, "Checksum validated, sealed at rest, never echoed", "")], h_identifiers),
    _spec(110, "workpaper_templates", "Workpaper templates", "Workpapers", "settings", [C("name", True, "", "BAS review"), C("category", True, "", "bas"), C("lines_json", False, 'JSON list: [{"label":"Net GST","kind":"calculated"}]', '[{"label":"Net GST","kind":"calculated"}]')], h_wp_templates),
    _spec(120, "workpapers", "Workpapers", "Workpapers", "wp_prepare", [C("client_ref", True, "", "C0001"), C("title", True, "", "FY26 trial balance review"), C("category"), C("template", False, "An existing template name"), C("entity_ref"),
          C("period_from"), C("period_to"), C("reviewer_email", False, "Must differ from the preparer (you)")], h_workpapers, "Workpapers are created as drafts owned by the person loading them."),
    _spec(130, "deadline_rules", "Deadline rules", "Engagements", "settings", [C("name", True, "", "Internal target"), C("kind", True, "internal or statutory", "internal"), C("rule_json", True, 'e.g. {"basis":"period_end","months":4,"day_of_month":28}', '{"basis":"period_end","months":4,"day_of_month":28}'),
          C("service_type"), C("source", False, "REQUIRED for statutory: where the date rule comes from"), C("source_verified_at", False, "REQUIRED for statutory: when you last verified it")], h_rules,
          "AccFino ships no statutory dates. A statutory rule without a source and verification date is rejected."),
    _spec(140, "engagement_templates", "Engagement templates", "Engagements", "settings", [C("name", True, "", "Annual accounts"), C("service_type", True, "bookkeeping, financial_statements, tax_return, bas, payroll, advisory, other", "bas"),
          C("jobs_json", True, "JSON list of jobs with tasks, checklists and dependencies", '[{"key":"j","title":"Prepare","tasks":[{"key":"t","title":"Reconcile"}]}]'), C("deadline_rule", False, "An existing rule name")], h_eng_templates,
          "Dependency cycles between tasks are rejected."),
    _spec(150, "engagements", "Engagements", "Engagements", "engagements", [C("client_ref", True, "", "C0001"), C("title", True, "", "FY26 accounts"), C("service_type", True, "", "financial_statements"), C("template"), C("entity_ref"),
          C("period_from"), C("period_to"), C("billing_basis", False, "hourly or fixed", "hourly"), C("fixed_fee"), C("scope"), C("manager_email"), C("preparer_email"), C("reviewer_email")], h_engagements),
    _spec(160, "deadlines", "Deadlines", "Engagements", "engagements", [C("client_ref", True, "", "C0001"), C("engagement_title", True, "", "FY26 accounts"), C("rule", True, "An existing rule name", "Internal target"), C("period_end"), C("title")], h_deadlines,
          "Calculated from the rule. Statutory deadlines start UNVERIFIED until a manager or partner verifies them."),
    _spec(170, "recurrences", "Recurrences", "Engagements", "engagements", [C("client_ref", True, "", "C0004"), C("template", True, "", "Monthly bookkeeping"), C("frequency", True, "monthly, quarterly, annual", "monthly"), C("next_period_end", True, "", "2026-09-30")], h_recurrences,
          "Creating the recurrence does not run it: use Run in Engagements."),
    _spec(180, "client_requests", "Client document requests", "Client Portal", "portal", [C("client_ref", True, "", "C0001"), C("title", True, "", "FY26 records"), C("items", True, "One or more items separated by |", "Bank statements|Loan statement"),
          C("response_types", False, "file, text or file,text", "file"), C("description"), C("due_date"), C("entity_ref")], h_requests,
          "Each row creates one request and notifies the client. A check-only run sends NO e-mail; an actual import e-mails the clients."),
    _spec(190, "rates", "Billing rates", "Billing", "billing_admin", [C("hourly_rate", True, "", "180"), C("staff_email"), C("client_ref"), C("service_type"), C("effective_from", False, "default today", "2026-07-01"), C("effective_to")], h_rates,
          "The most specific rate wins: client + staff, client, staff + service, staff, service."),
    _spec(200, "time_entries", "Time entries", "Billing", "time", [C("client_ref", True, "", "C0001"), C("staff_email", False, "Blank = you. Another person needs billing administration", ""), C("work_date", True, "Not in the future", "2026-09-01"),
          C("minutes", True, "1 to 1440", "90"), C("description", True, "", "BAS preparation"), C("billable", False, "yes/no, default yes", "yes"), C("engagement_title")], h_time,
          "Entries are created as DRAFT. The staff member submits them; a different person approves."),
]}


# ---------------------------------------------------------------------------------------------------------------------------------------------- gate + audit
def switched_on(db) -> bool:
    row = db.get(m.SystemSetting, "platform.bulk_import")
    return not (row and (row.value or "").strip().lower() == "off")


def enabled(db, ctx) -> bool:
    from accfino.core.subscription import service as S
    return switched_on(db) and S.is_allowed(S.entitlements(db, ctx.org.id), ("bulk-import",))


def gate(db, ctx):
    from accfino.core.subscription import service as S
    if not switched_on(db):
        raise core.Forbidden("Bulk data import has been switched off by your platform administrator (Admin > Modules Management).")
    S.check(db, ctx, ("bulk-import",), "POST")


def audit(db, ctx, a, key, applied, rejected):
    core.audit(db, ctx, a.practice_id, "bulk.imported", "bulk", None, table=key, applied=applied, rejected=rejected)
