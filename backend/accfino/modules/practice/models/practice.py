"""
accfino.modules.practice.models.practice
----------------------------------------
Practice & Client Services tables (prefix pc_). A PRACTICE is the accounting firm's workspace and is anchored to one Organisation (the firm's own
organisation and books): pc_practices.org_id is unique. Every other row carries practice_id so isolation is a plain WHERE on an indexed column.
Money lives in the firm's general ledger (Accounting): pc_invoices only reference the accounting document; time entries hold the rate basis snapshot.
"""
from datetime import datetime

from sqlalchemy import JSON, Boolean, CheckConstraint, Column, Date, DateTime, ForeignKey, Index, Integer, String, Text, UniqueConstraint

from accfino.shared.db.base import Base
from accfino.shared.db.types import MONEY

_P = lambda: Column(Integer, ForeignKey("pc_practices.id", ondelete="CASCADE"), nullable=False, index=True)
_NOW = lambda: Column(DateTime, nullable=False, default=datetime.utcnow)


def _in(col, values):
    return f"{col} IN ({', '.join(repr(v) for v in values)})"


PRACTICE_ROLES = ("admin", "partner", "manager", "preparer", "reviewer", "billing", "readonly")
CLIENT_TYPES = ("individual", "organisation")
CLIENT_STATUSES = ("active", "inactive", "archived")
ENGAGEMENT_STATUSES = ("draft", "proposed", "accepted", "active", "completed", "terminated", "archived")
JOB_STATUSES = ("not_started", "in_progress", "awaiting_client", "ready_for_review", "changes_required", "completed", "blocked")
WP_STATUSES = ("draft", "in_preparation", "ready_for_review", "review_in_progress", "changes_required", "finalised")
REQUEST_STATUSES = ("requested", "partially_received", "submitted", "under_review", "accepted", "rejected", "cancelled")
TIME_STATUSES = ("draft", "submitted", "approved", "rejected", "billed", "written_off")
INVOICE_STATUSES = ("draft", "approved", "issued", "voided")


class PcPractice(Base):
    __tablename__ = "pc_practices"
    id = Column(Integer, primary_key=True)
    org_id = Column(Integer, ForeignKey("organisations.id", ondelete="CASCADE"), nullable=False, unique=True)
    name = Column(String(200), nullable=False)
    trading_name = Column(String(200))
    abn = Column(String(20))
    email = Column(String(200))
    phone = Column(String(40))
    address = Column(Text)
    brand_colour = Column(String(9))
    fy_end_month = Column(Integer, nullable=False, default=6)
    settings = Column(JSON, nullable=True)                 # retention_years, storage_limit_mb, max_file_mb, dedupe, holidays, billing {...}
    created_at = _NOW()


class PcMember(Base):
    __tablename__ = "pc_members"
    __table_args__ = (UniqueConstraint("practice_id", "user_id", name="uq_pc_member"), CheckConstraint(_in("role", PRACTICE_ROLES), name="ck_pc_member_role"))
    id = Column(Integer, primary_key=True)
    practice_id = _P()
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    role = Column(String(20), nullable=False)
    status = Column(String(12), nullable=False, default="active")      # active | suspended
    created_at = _NOW()


class PcTeam(Base):
    __tablename__ = "pc_teams"
    __table_args__ = (UniqueConstraint("practice_id", "name", name="uq_pc_team"),)
    id = Column(Integer, primary_key=True)
    practice_id = _P()
    name = Column(String(80), nullable=False)


class PcTeamMember(Base):
    __tablename__ = "pc_team_members"
    team_id = Column(Integer, ForeignKey("pc_teams.id", ondelete="CASCADE"), primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)


class PcClient(Base):
    __tablename__ = "pc_clients"
    __table_args__ = (UniqueConstraint("practice_id", "ref", name="uq_pc_client_ref"), CheckConstraint(_in("client_type", CLIENT_TYPES), name="ck_pc_client_type"),
                      CheckConstraint(_in("status", CLIENT_STATUSES), name="ck_pc_client_status"), Index("ix_pc_client_search", "practice_id", "status", "legal_name"))
    id = Column(Integer, primary_key=True)
    practice_id = _P()
    ref = Column(String(40), nullable=False)
    client_type = Column(String(14), nullable=False)
    legal_name = Column(String(200), nullable=False)
    preferred_name = Column(String(200))
    email = Column(String(200))
    phone = Column(String(40))
    postal_address = Column(Text)
    registered_address = Column(Text)
    status = Column(String(10), nullable=False, default="active")
    manager_id = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), index=True)
    preparer_id = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), index=True)
    reviewer_id = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), index=True)
    team_id = Column(Integer, ForeignKey("pc_teams.id", ondelete="SET NULL"), index=True)
    service_lines = Column(String(300))                      # comma separated service types the client buys
    comm_pref = Column(String(20), nullable=False, default="email")   # email | phone | portal | post
    important_dates = Column(JSON, nullable=True)            # [{label, date}]
    notes = Column(Text)                                     # INTERNAL notes: never sent to the portal
    linked_org_id = Column(Integer, ForeignKey("organisations.id", ondelete="SET NULL"), index=True)   # the client's own books, only when verified by an authorised user
    billing_contact_id = Column(Integer)                     # the customer contact in the PRACTICE's own books (Accounting) that this client is invoiced as
    archived_at = Column(DateTime)
    created_by = Column(Integer)
    created_at = _NOW()
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)


class PcIdentifier(Base):
    """Tax identifiers, SEALED (Fernet). Only the last digits are kept in clear for masking. owner_kind: client | entity | contact."""
    __tablename__ = "pc_identifiers"
    __table_args__ = (UniqueConstraint("practice_id", "owner_kind", "owner_id", "kind", name="uq_pc_ident"), Index("ix_pc_ident_hash", "practice_id", "kind", "value_hash"))
    id = Column(Integer, primary_key=True)
    practice_id = _P()
    owner_kind = Column(String(10), nullable=False)
    owner_id = Column(Integer, nullable=False)
    kind = Column(String(6), nullable=False)
    sealed = Column(Text, nullable=False)
    last_digits = Column(String(4), nullable=False)
    value_hash = Column(String(64), nullable=False)          # HMAC for duplicate detection without decrypting
    verified = Column(Boolean, nullable=False, default=False)
    verified_source = Column(String(200))
    verified_at = Column(DateTime)
    verified_by = Column(Integer)


class PcEntity(Base):
    __tablename__ = "pc_entities"
    __table_args__ = (UniqueConstraint("practice_id", "ref", name="uq_pc_entity_ref"), Index("ix_pc_entity_search", "practice_id", "status", "name"))
    id = Column(Integer, primary_key=True)
    practice_id = _P()
    ref = Column(String(40), nullable=False)
    name = Column(String(200), nullable=False)
    entity_type = Column(String(14), nullable=False)
    status = Column(String(10), nullable=False, default="active")
    fy_end_month = Column(Integer, nullable=False, default=6)
    gst_registered = Column(Boolean, nullable=False, default=False)
    gst_basis = Column(String(10))
    tax_notes = Column(Text)
    linked_org_id = Column(Integer, ForeignKey("organisations.id", ondelete="SET NULL"), index=True)
    created_at = _NOW()
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)


class PcClientEntity(Base):
    """Client <-> entity link (many to many) with effective dates and an explicit verification label."""
    __tablename__ = "pc_client_entities"
    id = Column(Integer, primary_key=True)
    practice_id = _P()
    client_id = Column(Integer, ForeignKey("pc_clients.id", ondelete="CASCADE"), nullable=False, index=True)
    entity_id = Column(Integer, ForeignKey("pc_entities.id", ondelete="CASCADE"), nullable=False, index=True)
    relationship = Column(String(60), nullable=False, default="manages")
    effective_from = Column(Date)
    effective_to = Column(Date)
    verified = Column(Boolean, nullable=False, default=False)
    verified_source = Column(String(200))


class PcEntityRelation(Base):
    """Parent -> child structure (ownership / control / trustee-of ...). Never inferred from contacts; 'verified' says whether a person confirmed it."""
    __tablename__ = "pc_entity_relations"
    __table_args__ = (CheckConstraint("parent_entity_id <> child_entity_id", name="ck_pc_rel_self"),)
    id = Column(Integer, primary_key=True)
    practice_id = _P()
    parent_entity_id = Column(Integer, ForeignKey("pc_entities.id", ondelete="CASCADE"), nullable=False, index=True)
    child_entity_id = Column(Integer, ForeignKey("pc_entities.id", ondelete="CASCADE"), nullable=False, index=True)
    kind = Column(String(30), nullable=False)             # owns | controls | trustee_of | partner_in | subsidiary_of
    percent = Column(MONEY)
    effective_from = Column(Date)
    effective_to = Column(Date)
    verified = Column(Boolean, nullable=False, default=False)
    verified_source = Column(String(200))


class PcContact(Base):
    __tablename__ = "pc_contacts"
    id = Column(Integer, primary_key=True)
    practice_id = _P()
    full_name = Column(String(200), nullable=False)
    email = Column(String(200), index=True)
    phone = Column(String(40))
    comm_pref = Column(String(20), nullable=False, default="email")
    user_id = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), index=True)   # set when the contact has accepted a portal invitation
    created_at = _NOW()


class PcContactLink(Base):
    __tablename__ = "pc_contact_links"
    id = Column(Integer, primary_key=True)
    practice_id = _P()
    contact_id = Column(Integer, ForeignKey("pc_contacts.id", ondelete="CASCADE"), nullable=False, index=True)
    client_id = Column(Integer, ForeignKey("pc_clients.id", ondelete="CASCADE"), index=True)
    entity_id = Column(Integer, ForeignKey("pc_entities.id", ondelete="CASCADE"), index=True)
    role = Column(String(40), nullable=False, default="contact")      # contact | director | trustee | partner | accountant | other
    is_primary = Column(Boolean, nullable=False, default=False)
    is_authorised_rep = Column(Boolean, nullable=False, default=False)
    can_receive_documents = Column(Boolean, nullable=False, default=False)
    can_approve_work = Column(Boolean, nullable=False, default=False)
    can_use_portal = Column(Boolean, nullable=False, default=False)
    services = Column(String(300))                                    # restrict to these service types (empty = all)
    effective_from = Column(Date)
    effective_to = Column(Date)
    __table_args__ = (CheckConstraint("client_id IS NOT NULL OR entity_id IS NOT NULL", name="ck_pc_link_target"),)


class PcContactNote(Base):
    """Internal contact history (calls, meetings, file notes). Never visible in the portal."""
    __tablename__ = "pc_contact_notes"
    id = Column(Integer, primary_key=True)
    practice_id = _P()
    client_id = Column(Integer, ForeignKey("pc_clients.id", ondelete="CASCADE"), nullable=False, index=True)
    contact_id = Column(Integer, ForeignKey("pc_contacts.id", ondelete="SET NULL"))
    kind = Column(String(20), nullable=False, default="note")
    body = Column(Text, nullable=False)
    author_id = Column(Integer)
    created_at = _NOW()


class PcConsent(Base):
    __tablename__ = "pc_consents"
    id = Column(Integer, primary_key=True)
    practice_id = _P()
    client_id = Column(Integer, ForeignKey("pc_clients.id", ondelete="CASCADE"), nullable=False, index=True)
    contact_id = Column(Integer)
    key = Column(String(60), nullable=False)             # e.g. marketing_email, engagement_letter:<id>, privacy_collection
    granted = Column(Boolean, nullable=False)
    text_hash = Column(String(64))
    source = Column(String(20), nullable=False, default="staff")     # staff | portal
    recorded_by = Column(Integer)
    recorded_at = _NOW()


class PcDupReview(Base):
    __tablename__ = "pc_dup_reviews"
    __table_args__ = (UniqueConstraint("practice_id", "kind", "a_id", "b_id", name="uq_pc_dup"),)
    id = Column(Integer, primary_key=True)
    practice_id = _P()
    kind = Column(String(10), nullable=False)             # client | entity
    a_id = Column(Integer, nullable=False)
    b_id = Column(Integer, nullable=False)
    score = Column(MONEY, nullable=False)
    reasons = Column(JSON)
    status = Column(String(14), nullable=False, default="pending")   # pending | not_duplicate | confirmed
    reviewed_by = Column(Integer)
    reviewed_at = Column(DateTime)
    note = Column(Text)


# --------------------------------------------------------------------------------------------------------------------- documents
class PcDocument(Base):
    __tablename__ = "pc_documents"
    __table_args__ = (Index("ix_pc_doc_scope", "practice_id", "client_id", "status"),)
    id = Column(Integer, primary_key=True)
    practice_id = _P()
    client_id = Column(Integer, ForeignKey("pc_clients.id", ondelete="RESTRICT"), index=True)
    entity_id = Column(Integer, ForeignKey("pc_entities.id", ondelete="SET NULL"), index=True)
    engagement_id = Column(Integer, index=True)
    job_id = Column(Integer, index=True)
    fy = Column(Integer)
    category = Column(String(40), nullable=False, default="general")
    title = Column(String(200), nullable=False)
    source = Column(String(20), nullable=False, default="staff")     # staff | client_portal | system
    status = Column(String(12), nullable=False, default="active")    # active | archived | deleted
    shared_with_portal = Column(Boolean, nullable=False, default=False)
    current_version = Column(Integer, nullable=False, default=1)
    legal_hold = Column(Boolean, nullable=False, default=False)
    retain_until = Column(Date)
    deleted_at = Column(DateTime)
    deleted_by = Column(Integer)
    created_by = Column(Integer)
    created_at = _NOW()
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)


class PcDocVersion(Base):
    __tablename__ = "pc_doc_versions"
    __table_args__ = (UniqueConstraint("document_id", "version", name="uq_pc_docver"),)
    id = Column(Integer, primary_key=True)
    practice_id = _P()
    document_id = Column(Integer, ForeignKey("pc_documents.id", ondelete="CASCADE"), nullable=False, index=True)
    version = Column(Integer, nullable=False)
    original_name = Column(String(255), nullable=False)
    content_type = Column(String(100), nullable=False)
    size = Column(Integer, nullable=False)
    sha256 = Column(String(64), nullable=False)
    storage_key = Column(String(300), nullable=False)      # relative to the practice documents root; never a URL
    scan_status = Column(String(20), nullable=False, default="not_scanned")
    uploaded_by = Column(Integer)
    uploaded_by_portal = Column(Boolean, nullable=False, default=False)
    uploaded_at = _NOW()
    purged_at = Column(DateTime)


class PcDownloadTicket(Base):
    """Short-lived, single-use delivery ticket. It is bound to one user and one version and re-checked against current permissions when redeemed."""
    __tablename__ = "pc_download_tickets"
    id = Column(Integer, primary_key=True)
    practice_id = _P()
    token_hash = Column(String(64), nullable=False, unique=True)
    version_id = Column(Integer, ForeignKey("pc_doc_versions.id", ondelete="CASCADE"), nullable=False, index=True)
    user_id = Column(Integer, nullable=False)
    portal = Column(Boolean, nullable=False, default=False)
    expires_at = Column(DateTime, nullable=False)
    used_at = Column(DateTime)
    revoked_at = Column(DateTime)


# --------------------------------------------------------------------------------------------------------------------- workpapers
class PcWpTemplate(Base):
    __tablename__ = "pc_wp_templates"
    __table_args__ = (UniqueConstraint("practice_id", "name", name="uq_pc_wptpl"),)
    id = Column(Integer, primary_key=True)
    practice_id = _P()
    name = Column(String(120), nullable=False)
    category = Column(String(40), nullable=False)
    lines = Column(JSON)             # [{label, kind}]
    active = Column(Boolean, nullable=False, default=True)


class PcWorkpaper(Base):
    __tablename__ = "pc_workpapers"
    __table_args__ = (Index("ix_pc_wp_scope", "practice_id", "client_id", "status"),)
    id = Column(Integer, primary_key=True)
    practice_id = _P()
    client_id = Column(Integer, ForeignKey("pc_clients.id", ondelete="RESTRICT"), nullable=False, index=True)
    entity_id = Column(Integer, ForeignKey("pc_entities.id", ondelete="SET NULL"), index=True)
    engagement_id = Column(Integer, index=True)
    template_id = Column(Integer)
    title = Column(String(200), nullable=False)
    category = Column(String(40), nullable=False, default="general")
    period_from = Column(Date)
    period_to = Column(Date)
    status = Column(String(20), nullable=False, default="draft")
    prepared_by = Column(Integer)
    reviewer_id = Column(Integer)
    prepared_at = Column(DateTime)
    review_started_at = Column(DateTime)
    reviewed_by = Column(Integer)
    reviewed_at = Column(DateTime)
    finalised_by = Column(Integer)
    finalised_at = Column(DateTime)
    version = Column(Integer, nullable=False, default=1)
    content = Column(JSON)
    content_hash = Column(String(64))
    reopen_count = Column(Integer, nullable=False, default=0)
    created_by = Column(Integer)
    created_at = _NOW()
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)


class PcWpVersion(Base):
    __tablename__ = "pc_wp_versions"
    __table_args__ = (UniqueConstraint("workpaper_id", "version", name="uq_pc_wpver"),)
    id = Column(Integer, primary_key=True)
    practice_id = _P()
    workpaper_id = Column(Integer, ForeignKey("pc_workpapers.id", ondelete="CASCADE"), nullable=False, index=True)
    version = Column(Integer, nullable=False)
    content = Column(JSON)
    content_hash = Column(String(64), nullable=False)
    status = Column(String(20), nullable=False)
    changed_by = Column(Integer)
    reason = Column(String(300))
    created_at = _NOW()


class PcWpComment(Base):
    __tablename__ = "pc_wp_comments"
    id = Column(Integer, primary_key=True)
    practice_id = _P()
    workpaper_id = Column(Integer, ForeignKey("pc_workpapers.id", ondelete="CASCADE"), nullable=False, index=True)
    parent_id = Column(Integer)
    kind = Column(String(10), nullable=False, default="comment")   # comment | query | response
    body = Column(Text, nullable=False)
    mandatory = Column(Boolean, nullable=False, default=False)
    status = Column(String(10), nullable=False, default="open")    # open | resolved
    author_id = Column(Integer, nullable=False)
    created_at = _NOW()
    resolved_by = Column(Integer)
    resolved_at = Column(DateTime)


class PcWpDoc(Base):
    __tablename__ = "pc_wp_docs"
    workpaper_id = Column(Integer, ForeignKey("pc_workpapers.id", ondelete="CASCADE"), primary_key=True)
    document_id = Column(Integer, ForeignKey("pc_documents.id", ondelete="RESTRICT"), primary_key=True)
    practice_id = _P()


class PcWpRef(Base):
    """A reference to an authoritative AccFino record (trial balance, ledger report, reconciliation, tax calculation). A hash of what was seen is kept so later drift is visible."""
    __tablename__ = "pc_wp_refs"
    id = Column(Integer, primary_key=True)
    practice_id = _P()
    workpaper_id = Column(Integer, ForeignKey("pc_workpapers.id", ondelete="CASCADE"), nullable=False, index=True)
    kind = Column(String(30), nullable=False)       # trial_balance | profit_loss | balance_sheet | ledger_account | reconciliation | tax_calc
    params = Column(JSON)
    seen_hash = Column(String(64))
    seen_at = Column(DateTime)
    note = Column(String(300))


# --------------------------------------------------------------------------------------------------------------------- engagements
class PcEngTemplate(Base):
    __tablename__ = "pc_eng_templates"
    __table_args__ = (UniqueConstraint("practice_id", "name", name="uq_pc_engtpl"),)
    id = Column(Integer, primary_key=True)
    practice_id = _P()
    name = Column(String(120), nullable=False)
    service_type = Column(String(40), nullable=False)
    jobs = Column(JSON, nullable=False)       # [{key,title,due_offset_days,tasks:[{key,title,mandatory,needs:[key],due_offset_days,checklist:[str]}]}]
    deadline_rule_id = Column(Integer)
    active = Column(Boolean, nullable=False, default=True)


class PcEngagement(Base):
    __tablename__ = "pc_engagements"
    __table_args__ = (CheckConstraint(_in("status", ENGAGEMENT_STATUSES), name="ck_pc_eng_status"), Index("ix_pc_eng_scope", "practice_id", "client_id", "status"))
    id = Column(Integer, primary_key=True)
    practice_id = _P()
    client_id = Column(Integer, ForeignKey("pc_clients.id", ondelete="RESTRICT"), nullable=False, index=True)
    entity_id = Column(Integer, ForeignKey("pc_entities.id", ondelete="SET NULL"), index=True)
    service_type = Column(String(40), nullable=False)
    template_id = Column(Integer)
    title = Column(String(200), nullable=False)
    status = Column(String(12), nullable=False, default="draft")
    period_from = Column(Date)
    period_to = Column(Date)
    manager_id = Column(Integer)
    preparer_id = Column(Integer)
    reviewer_id = Column(Integer)
    scope = Column(Text)
    deliverables = Column(Text)
    billing_basis = Column(String(12), nullable=False, default="hourly")     # hourly | fixed
    fixed_fee = Column(MONEY)
    accepted_at = Column(DateTime)
    accepted_by = Column(String(200))
    terminated_at = Column(DateTime)
    termination_reason = Column(Text)
    renewed_from_id = Column(Integer)
    created_by = Column(Integer)
    created_at = _NOW()
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)


class PcJob(Base):
    __tablename__ = "pc_jobs"
    __table_args__ = (UniqueConstraint("engagement_id", "tkey", name="uq_pc_job_key"), Index("ix_pc_job_scope", "practice_id", "status", "due_date"))
    id = Column(Integer, primary_key=True)
    practice_id = _P()
    engagement_id = Column(Integer, ForeignKey("pc_engagements.id", ondelete="CASCADE"), nullable=False, index=True)
    client_id = Column(Integer, nullable=False, index=True)
    tkey = Column(String(40), nullable=False)
    title = Column(String(200), nullable=False)
    status = Column(String(20), nullable=False, default="not_started")
    owner_id = Column(Integer, index=True)
    reviewer_id = Column(Integer)
    team_id = Column(Integer)
    due_date = Column(Date)
    completed_at = Column(DateTime)
    completed_by = Column(Integer)
    blocker = Column(String(300))
    created_at = _NOW()


class PcTask(Base):
    __tablename__ = "pc_tasks"
    __table_args__ = (UniqueConstraint("job_id", "tkey", name="uq_pc_task_key"),)
    id = Column(Integer, primary_key=True)
    practice_id = _P()
    job_id = Column(Integer, ForeignKey("pc_jobs.id", ondelete="CASCADE"), nullable=False, index=True)
    tkey = Column(String(40), nullable=False)
    title = Column(String(200), nullable=False)
    status = Column(String(20), nullable=False, default="not_started")
    owner_id = Column(Integer, index=True)
    due_date = Column(Date)
    mandatory = Column(Boolean, nullable=False, default=True)
    blocker = Column(String(300))
    completed_at = Column(DateTime)
    completed_by = Column(Integer)


class PcTaskDep(Base):
    __tablename__ = "pc_task_deps"
    task_id = Column(Integer, ForeignKey("pc_tasks.id", ondelete="CASCADE"), primary_key=True)
    needs_task_id = Column(Integer, ForeignKey("pc_tasks.id", ondelete="CASCADE"), primary_key=True)


class PcChecklistItem(Base):
    __tablename__ = "pc_checklist_items"
    id = Column(Integer, primary_key=True)
    practice_id = _P()
    task_id = Column(Integer, ForeignKey("pc_tasks.id", ondelete="CASCADE"), nullable=False, index=True)
    text = Column(String(300), nullable=False)
    done = Column(Boolean, nullable=False, default=False)
    done_by = Column(Integer)
    done_at = Column(DateTime)


class PcReviewPoint(Base):
    __tablename__ = "pc_review_points"
    id = Column(Integer, primary_key=True)
    practice_id = _P()
    job_id = Column(Integer, ForeignKey("pc_jobs.id", ondelete="CASCADE"), nullable=False, index=True)
    finding = Column(Text, nullable=False)
    mandatory = Column(Boolean, nullable=False, default=True)
    status = Column(String(10), nullable=False, default="open")    # open | responded | resolved
    response = Column(Text)
    raised_by = Column(Integer, nullable=False)
    raised_at = _NOW()
    responded_by = Column(Integer)
    resolved_by = Column(Integer)
    resolved_at = Column(DateTime)


class PcJobNote(Base):
    __tablename__ = "pc_job_notes"
    id = Column(Integer, primary_key=True)
    practice_id = _P()
    job_id = Column(Integer, ForeignKey("pc_jobs.id", ondelete="CASCADE"), nullable=False, index=True)
    kind = Column(String(12), nullable=False, default="comment")    # comment | handover | status
    body = Column(Text, nullable=False)
    author_id = Column(Integer)
    created_at = _NOW()


class PcDeadlineRule(Base):
    __tablename__ = "pc_deadline_rules"
    __table_args__ = (UniqueConstraint("practice_id", "name", name="uq_pc_dlrule"),)
    id = Column(Integer, primary_key=True)
    practice_id = _P()
    name = Column(String(120), nullable=False)
    service_type = Column(String(40))
    kind = Column(String(12), nullable=False, default="internal")          # internal | statutory
    rule = Column(JSON, nullable=False)                                    # see engine.deadlines.from_rule
    source = Column(String(300))                                           # where a statutory rule comes from (required for statutory)
    source_verified_at = Column(Date)
    active = Column(Boolean, nullable=False, default=True)


class PcDeadline(Base):
    __tablename__ = "pc_deadlines"
    __table_args__ = (Index("ix_pc_dl_scope", "practice_id", "status", "due_date"),)
    id = Column(Integer, primary_key=True)
    practice_id = _P()
    client_id = Column(Integer, nullable=False, index=True)
    engagement_id = Column(Integer, index=True)
    job_id = Column(Integer, index=True)
    title = Column(String(200), nullable=False)
    kind = Column(String(12), nullable=False)                              # internal | statutory
    due_date = Column(Date, nullable=False)
    calculated_date = Column(Date)                                         # what the rule produced
    rule_id = Column(Integer)
    source = Column(String(300))
    verified = Column(Boolean, nullable=False, default=False)
    verified_at = Column(DateTime)
    verified_by = Column(Integer)
    override_reason = Column(String(300))
    status = Column(String(10), nullable=False, default="open")            # open | completed | cancelled
    completed_at = Column(DateTime)
    created_at = _NOW()


class PcRecurrence(Base):
    __tablename__ = "pc_recurrences"
    id = Column(Integer, primary_key=True)
    practice_id = _P()
    client_id = Column(Integer, nullable=False)
    template_id = Column(Integer, nullable=False)
    frequency = Column(String(10), nullable=False)       # monthly | quarterly | annual
    next_period_end = Column(Date, nullable=False)
    active = Column(Boolean, nullable=False, default=True)
    manager_id = Column(Integer)


class PcRunLog(Base):
    """Idempotency ledger for background work: one row per (kind, key). A retry that finds the key does nothing."""
    __tablename__ = "pc_run_log"
    __table_args__ = (UniqueConstraint("practice_id", "kind", "key", name="uq_pc_runlog"),)
    id = Column(Integer, primary_key=True)
    practice_id = _P()
    kind = Column(String(20), nullable=False)
    key = Column(String(200), nullable=False)
    ref_id = Column(Integer)
    created_at = _NOW()


# --------------------------------------------------------------------------------------------------------------------- portal and communication
class PcPortalInvite(Base):
    __tablename__ = "pc_portal_invites"
    id = Column(Integer, primary_key=True)
    practice_id = _P()
    client_id = Column(Integer, ForeignKey("pc_clients.id", ondelete="CASCADE"), nullable=False, index=True)
    contact_id = Column(Integer, nullable=False)
    email = Column(String(200), nullable=False)
    token_hash = Column(String(64), nullable=False, unique=True)
    entity_ids = Column(JSON)                      # [] = client level only; ids = access to those entities
    status = Column(String(10), nullable=False, default="pending")   # pending | accepted | revoked | expired
    expires_at = Column(DateTime, nullable=False)
    created_by = Column(Integer)
    created_at = _NOW()
    accepted_at = Column(DateTime)
    accepted_user_id = Column(Integer)
    send_count = Column(Integer, nullable=False, default=1)


class PcPortalAccess(Base):
    __tablename__ = "pc_portal_access"
    __table_args__ = (UniqueConstraint("practice_id", "client_id", "user_id", name="uq_pc_portal"), Index("ix_pc_portal_user", "user_id", "status"))
    id = Column(Integer, primary_key=True)
    practice_id = _P()
    client_id = Column(Integer, ForeignKey("pc_clients.id", ondelete="CASCADE"), nullable=False, index=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    contact_id = Column(Integer)
    entity_ids = Column(JSON)
    status = Column(String(10), nullable=False, default="active")    # active | revoked
    granted_by = Column(Integer)
    granted_at = _NOW()
    revoked_at = Column(DateTime)
    revoked_by = Column(Integer)


class PcRequest(Base):
    __tablename__ = "pc_requests"
    __table_args__ = (CheckConstraint(_in("status", REQUEST_STATUSES), name="ck_pc_req_status"), Index("ix_pc_req_scope", "practice_id", "client_id", "status"))
    id = Column(Integer, primary_key=True)
    practice_id = _P()
    client_id = Column(Integer, ForeignKey("pc_clients.id", ondelete="CASCADE"), nullable=False, index=True)
    entity_id = Column(Integer)
    engagement_id = Column(Integer)
    job_id = Column(Integer)
    title = Column(String(200), nullable=False)
    description = Column(Text)
    due_date = Column(Date)
    status = Column(String(20), nullable=False, default="requested")
    assigned_to = Column(Integer)
    created_by = Column(Integer)
    created_at = _NOW()
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)


class PcRequestItem(Base):
    __tablename__ = "pc_request_items"
    id = Column(Integer, primary_key=True)
    practice_id = _P()
    request_id = Column(Integer, ForeignKey("pc_requests.id", ondelete="CASCADE"), nullable=False, index=True)
    description = Column(String(300), nullable=False)
    response_types = Column(String(60), nullable=False, default="file")     # file | text | file,text
    status = Column(String(10), nullable=False, default="pending")           # pending | submitted | accepted | rejected
    response_text = Column(Text)
    document_id = Column(Integer)
    review_note = Column(Text)               # shown to the client when an item is rejected
    submitted_at = Column(DateTime)
    submitted_by = Column(Integer)
    reviewed_by = Column(Integer)
    reviewed_at = Column(DateTime)


class PcMessage(Base):
    __tablename__ = "pc_messages"
    __table_args__ = (Index("ix_pc_msg_scope", "practice_id", "client_id", "visibility"),)
    id = Column(Integer, primary_key=True)
    practice_id = _P()
    client_id = Column(Integer, ForeignKey("pc_clients.id", ondelete="CASCADE"), nullable=False, index=True)
    request_id = Column(Integer)
    job_id = Column(Integer)
    engagement_id = Column(Integer)
    visibility = Column(String(10), nullable=False)      # internal | client
    author_kind = Column(String(8), nullable=False)      # staff | client
    author_id = Column(Integer, nullable=False)
    body = Column(Text, nullable=False)
    created_at = _NOW()


class PcNotification(Base):
    __tablename__ = "pc_notifications"
    __table_args__ = (UniqueConstraint("practice_id", "dedupe_key", name="uq_pc_notif"), Index("ix_pc_notif_user", "user_id", "status"))
    id = Column(Integer, primary_key=True)
    practice_id = _P()
    user_id = Column(Integer, nullable=False)
    audience = Column(String(8), nullable=False)         # staff | client
    client_id = Column(Integer)
    subject = Column(String(200), nullable=False)
    body = Column(Text)
    ref_kind = Column(String(20))
    ref_id = Column(Integer)
    dedupe_key = Column(String(200), nullable=False)
    status = Column(String(10), nullable=False, default="pending")   # pending | sent | failed | read
    attempts = Column(Integer, nullable=False, default=0)
    last_error = Column(String(300))
    created_at = _NOW()
    sent_at = Column(DateTime)
    read_at = Column(DateTime)


# --------------------------------------------------------------------------------------------------------------------- billing
class PcRate(Base):
    __tablename__ = "pc_rates"
    id = Column(Integer, primary_key=True)
    practice_id = _P()
    user_id = Column(Integer)
    client_id = Column(Integer)
    service_type = Column(String(40))
    hourly_rate = Column(MONEY, nullable=False)
    effective_from = Column(Date, nullable=False)
    effective_to = Column(Date)
    created_by = Column(Integer)
    created_at = _NOW()


class PcTimeEntry(Base):
    __tablename__ = "pc_time_entries"
    __table_args__ = (CheckConstraint(_in("status", TIME_STATUSES), name="ck_pc_time_status"), CheckConstraint("minutes > 0", name="ck_pc_time_minutes"),
                      Index("ix_pc_time_scope", "practice_id", "status", "work_date"))
    id = Column(Integer, primary_key=True)
    practice_id = _P()
    user_id = Column(Integer, nullable=False, index=True)
    client_id = Column(Integer, ForeignKey("pc_clients.id", ondelete="RESTRICT"), nullable=False, index=True)
    entity_id = Column(Integer)
    engagement_id = Column(Integer, index=True)
    job_id = Column(Integer)
    task_id = Column(Integer)
    work_date = Column(Date, nullable=False)
    minutes = Column(Integer, nullable=False)
    description = Column(String(500), nullable=False)
    billable = Column(Boolean, nullable=False, default=True)
    status = Column(String(12), nullable=False, default="draft")
    rate_applied = Column(MONEY)                     # snapshot of the rate when the entry was approved
    rate_source = Column(String(60))
    amount = Column(MONEY)                           # snapshot: minutes x rate_applied
    submitted_at = Column(DateTime)
    approved_by = Column(Integer)
    approved_at = Column(DateTime)
    rejection_reason = Column(String(300))
    corrects_id = Column(Integer)                    # a correction (negative history is kept as a new entry, never an edit of billed time)
    timer_started_at = Column(DateTime)
    created_at = _NOW()


class PcInvoice(Base):
    __tablename__ = "pc_invoices"
    __table_args__ = (UniqueConstraint("practice_id", "idempotency_key", name="uq_pc_inv_idem"), CheckConstraint(_in("status", INVOICE_STATUSES), name="ck_pc_inv_status"))
    id = Column(Integer, primary_key=True)
    practice_id = _P()
    client_id = Column(Integer, ForeignKey("pc_clients.id", ondelete="RESTRICT"), nullable=False, index=True)
    entity_id = Column(Integer)
    engagement_id = Column(Integer)
    status = Column(String(10), nullable=False, default="draft")
    issue_date = Column(Date)
    due_date = Column(Date)
    reference = Column(String(100))
    net = Column(MONEY, nullable=False, default=0)
    tax = Column(MONEY, nullable=False, default=0)
    total = Column(MONEY, nullable=False, default=0)
    accounting_doc_id = Column(Integer, unique=True)       # the Accounting invoice (Doc) once issued
    accounting_number = Column(String(40))
    idempotency_key = Column(String(80))
    visible_to_client = Column(Boolean, nullable=False, default=False)
    credit_doc_ids = Column(JSON)                          # accounting credit notes issued against this invoice
    created_by = Column(Integer)
    approved_by = Column(Integer)
    issued_by = Column(Integer)
    issued_at = Column(DateTime)
    voided_at = Column(DateTime)
    void_reason = Column(String(300))
    created_at = _NOW()


class PcInvoiceLine(Base):
    __tablename__ = "pc_invoice_lines"
    __table_args__ = (UniqueConstraint("active_time_key", name="uq_pc_line_time_active"),)
    id = Column(Integer, primary_key=True)
    practice_id = _P()
    invoice_id = Column(Integer, ForeignKey("pc_invoices.id", ondelete="CASCADE"), nullable=False, index=True)
    kind = Column(String(12), nullable=False)             # time | fixed | adjustment | discount
    description = Column(String(500), nullable=False)
    quantity = Column(MONEY, nullable=False, default=1)
    unit_price = Column(MONEY, nullable=False, default=0)
    tax_rate = Column(MONEY, nullable=False, default=0)
    amount = Column(MONEY, nullable=False)                # ex tax; negative for discounts
    time_entry_id = Column(Integer)
    active_time_key = Column(Integer)                     # = time_entry_id while the invoice is live, NULL once voided: the DB itself stops double billing
    reason = Column(String(300))
    created_by = Column(Integer)


class PcWriteOff(Base):
    __tablename__ = "pc_writeoffs"
    id = Column(Integer, primary_key=True)
    practice_id = _P()
    time_entry_id = Column(Integer, nullable=False, index=True)
    amount = Column(MONEY, nullable=False)
    reason = Column(String(300), nullable=False)
    approved_by = Column(Integer, nullable=False)
    created_at = _NOW()


PRACTICE_TABLES = [m.__table__ for m in (
    PcPractice, PcMember, PcTeam, PcTeamMember, PcClient, PcIdentifier, PcEntity, PcClientEntity, PcEntityRelation, PcContact, PcContactLink, PcContactNote, PcConsent, PcDupReview,
    PcDocument, PcDocVersion, PcDownloadTicket, PcWpTemplate, PcWorkpaper, PcWpVersion, PcWpComment, PcWpDoc, PcWpRef,
    PcEngTemplate, PcEngagement, PcJob, PcTask, PcTaskDep, PcChecklistItem, PcReviewPoint, PcJobNote, PcDeadlineRule, PcDeadline, PcRecurrence, PcRunLog,
    PcPortalInvite, PcPortalAccess, PcRequest, PcRequestItem, PcMessage, PcNotification, PcRate, PcTimeEntry, PcInvoice, PcInvoiceLine, PcWriteOff)]
