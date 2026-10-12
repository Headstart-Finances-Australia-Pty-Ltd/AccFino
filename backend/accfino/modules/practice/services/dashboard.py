"""Multi-client practice dashboard. Every number is COUNT(*) of the SAME query that the click-through list runs (metric -> builder), restricted to the member's client scope,
so a tile can never disagree with the list behind it."""
import datetime as dt

from sqlalchemy import func

from accfino.modules.practice.models import practice as P
from accfino.modules.practice.services import billing as BL, clients as CL, core, engagements as E
from accfino.modules.practice.services.core import Access, PcError


def _builders(a: Access):
    today = core.today()
    soon = today + dt.timedelta(days=int(a.settings.get("dashboard_soon_days", 14)))
    ids = a.client_ids()
    C, J, DL, W, R, X, Q = P.PcClient, P.PcJob, P.PcDeadline, P.PcWorkpaper, P.PcRequest, P.PcEngagement, P.PcTimeEntry

    def scoped(model, q=None):
        q = q if q is not None else a.db.query(model)
        return q.filter(model.practice_id == a.practice_id, model.client_id.in_(ids or [0]))
    def clients(status):
        return lambda: a.scoped_clients().filter(C.status == status)
    open_job = J.status != "completed"
    return {
        "clients_active": ("clients", clients("active")), "clients_inactive": ("clients", clients("inactive")), "clients_archived": ("clients", clients("archived")),
        "clients_unassigned": ("clients", lambda: a.scoped_clients().filter(C.status == "active", C.manager_id.is_(None))),
        "engagements_active": ("engagements", lambda: scoped(X).filter(X.status == "active")),
        "engagements_proposed": ("engagements", lambda: scoped(X).filter(X.status.in_(("draft", "proposed", "accepted")))),
        "jobs_open": ("jobs", lambda: scoped(J).filter(open_job)),
        "jobs_overdue": ("jobs", lambda: scoped(J).filter(open_job, J.due_date < today)),
        "jobs_due_soon": ("jobs", lambda: scoped(J).filter(open_job, J.due_date >= today, J.due_date <= soon)),
        "jobs_awaiting_client": ("jobs", lambda: scoped(J).filter(J.status == "awaiting_client")),
        "jobs_in_review": ("jobs", lambda: scoped(J).filter(J.status == "ready_for_review")),
        "deadlines_overdue": ("deadlines", lambda: scoped(DL).filter(DL.status == "open", DL.due_date < today)),
        "deadlines_due_soon": ("deadlines", lambda: scoped(DL).filter(DL.status == "open", DL.due_date >= today, DL.due_date <= soon)),
        "statutory_unverified": ("deadlines", lambda: scoped(DL).filter(DL.status == "open", DL.kind == "statutory", DL.verified.is_(False))),
        "workpapers_in_progress": ("workpapers", lambda: scoped(W).filter(W.status.in_(("draft", "in_preparation", "changes_required")))),
        "workpapers_awaiting_review": ("workpapers", lambda: scoped(W).filter(W.status.in_(("ready_for_review", "review_in_progress")))),
        "requests_outstanding": ("requests", lambda: scoped(R).filter(R.status.in_(("requested", "partially_received", "rejected")))),
        "requests_to_review": ("requests", lambda: scoped(R).filter(R.status == "submitted")),
        "time_awaiting_approval": ("time", lambda: scoped(Q).filter(Q.status == "submitted")),
    }


ORDER = {
    "clients": lambda: (P.PcClient.legal_name, P.PcClient.id), "engagements": lambda: (P.PcEngagement.id.desc(),), "jobs": lambda: (P.PcJob.due_date, P.PcJob.id),
    "deadlines": lambda: (P.PcDeadline.due_date, P.PcDeadline.id), "workpapers": lambda: (P.PcWorkpaper.updated_at.desc(), P.PcWorkpaper.id), "requests": lambda: (P.PcRequest.id.desc(),),
    "time": lambda: (P.PcTimeEntry.work_date.desc(), P.PcTimeEntry.id.desc()),
}
LISTERS = {
    "clients": lambda db, q, a: [CL.cdict(c) for c in q],
    "engagements": lambda db, q, a: [E.edict(e) for e in q],
    "jobs": lambda db, q, a: [dict(id=j.id, engagement_id=j.engagement_id, client_id=j.client_id, title=j.title, status=j.status, owner_id=j.owner_id, due_date=core.plain(j.due_date)) for j in q],
    "deadlines": lambda db, q, a: [E.ddict(d, core.today()) for d in q],
    "workpapers": lambda db, q, a: [dict(id=w.id, client_id=w.client_id, title=w.title, status=w.status, prepared_by=w.prepared_by, reviewer_id=w.reviewer_id) for w in q],
    "requests": lambda db, q, a: [dict(id=r.id, client_id=r.client_id, title=r.title, status=r.status, due_date=core.plain(r.due_date)) for r in q],
    "time": lambda db, q, a: [BL.tdict(t) for t in q],
}


def summary(db, a: Access) -> dict:
    a.require("view")
    b = _builders(a)
    tiles = {}
    for name, (kind, build) in b.items():
        if name == "time_awaiting_approval" and not a.can("time_approve"):
            continue
        tiles[name] = dict(count=build().count(), list=kind, drill=f"/practice/dashboard/{name}")
    out = dict(as_of=core.today().isoformat(), role=a.role, scope=("all clients" if a.role in ("admin", "partner") else "your assigned clients"), tiles=tiles)
    if a.can("billing"):
        d = BL.dashboard(db, a)
        out["billing"] = {k: d[k] for k in ("wip", "drafted_unissued", "invoiced_net", "realisation_pct", "receivables", "receivables_overdue")}
    return out


def drill(db, a: Access, metric: str, page_no=1, size=25) -> dict:
    a.require("view")
    b = _builders(a)
    if metric not in b or (metric == "time_awaiting_approval" and not a.can("time_approve")):
        raise PcError("Unknown metric", 404)
    kind, build = b[metric]
    meta, q = core.page(build().order_by(*ORDER[kind]()), page_no, size)
    return dict(metric=metric, kind=kind, **meta, items=LISTERS[kind](db, q, a))


def workload(db, a: Access) -> list:
    """Per practice member: clients they manage / prepare / review and their open + overdue jobs. Managers see their own scope; admin/partner see everyone."""
    a.require("view")
    today = core.today()
    ids = a.client_ids()
    rows = []
    members = db.query(P.PcMember).filter_by(practice_id=a.practice_id, status="active").all() if a.role in ("admin", "partner") else [a.member]
    for mem in members:
        uid = mem.user_id
        def cnt(col):
            return a.scoped_clients().filter(P.PcClient.status == "active", col == uid).count()
        J = P.PcJob
        jq = db.query(J).filter(J.practice_id == a.practice_id, J.client_id.in_(ids or [0]), J.owner_id == uid, J.status != "completed")
        rows.append(dict(staff_id=uid, role=mem.role, managed=cnt(P.PcClient.manager_id), prepared=cnt(P.PcClient.preparer_id), reviewed=cnt(P.PcClient.reviewer_id), open_jobs=jq.count(),
                         overdue_jobs=jq.filter(J.due_date < today).count()))
    return rows
