"""Smart Lending, Credit & Treasury HTTP API (mounted under /lending by api.py). Thin: it authenticates (current_org), authorises (Access) and calls the services; every rule lives in svc/ and engine/.
NOTE: no route or body here may use the names user_id / username (the platform AuthGuard treats them as 'the caller')."""
from datetime import date
from typing import List, Optional

from fastapi import APIRouter, Body, Depends, File, Form, HTTPException, Query, UploadFile
from fastapi.responses import Response
from sqlalchemy.orm import Session

from accfino.core.security.context import OrgContext, current_org
import accfino.modules.accounting.public as acct
from accfino.modules.lending import classifier, lend_models as M, metrics as MT
from accfino.modules.lending.engine import amort as A, credit as C
from accfino.modules.lending.svc import analyses, applicants, applications, collections, loans, settings, treasury
from accfino.modules.lending.svc.core import Access, plain as P
from accfino.shared.db.database import get_db

from accfino.core.subscription import service as SUB                      # noqa: E402
from accfino.core.subscription.service import feature_gate                # noqa: E402

router = APIRouter()                                                       # common: me, reference, settings, dashboard, bank and ledger account lists
# Each area needs ITS OWN module in the plan (an organisation on Statement Analysis only cannot call origination, loans, collections or treasury directly, whatever its screens hide).
stmt = APIRouter(dependencies=[Depends(feature_gate("financial-statement-analysis"))])        # saved statement analyses
people = APIRouter(dependencies=[Depends(feature_gate("financial-statement-analysis", "loan-origination", "credit-assessment", "loan-management", "collections"))])   # applicants are shared by every area but treasury
orig = APIRouter(dependencies=[Depends(feature_gate("loan-origination", "credit-assessment"))])
lns = APIRouter(dependencies=[Depends(feature_gate("loan-management"))])
col = APIRouter(dependencies=[Depends(feature_gate("collections"))])
tre = APIRouter(dependencies=[Depends(feature_gate("treasury-liquidity"))])
Ctx, Db = Depends(current_org), Depends(get_db)
MAX_FILE = 10 * 1024 * 1024
MAX_FILES = 12


def access(ctx: OrgContext = Depends(current_org), db: Session = Depends(get_db)) -> Access:
    a = Access(db, ctx)
    if not a.has_any_access:
        raise HTTPException(403, "You do not have access to Smart Lending in this organisation")
    return a


Acc = Depends(access)


def _d(v):
    return date.fromisoformat(v) if v else None


# ---------------------------------------------------------------------------------------------------------------------------------- reference, settings, dashboard
@router.get("/me")
def me(a: Access = Acc):
    return a.summary()


@router.get("/reference")
def reference(a: Access = Acc):
    return dict(loan_types=M.LOAN_TYPES, frequencies=M.FREQUENCIES, households=M.HOUSEHOLDS, employment=M.EMPLOYMENT, commitment_kinds=M.COMMITMENT_KINDS, collection_kinds=M.COLLECTION_KINDS, hardship_statuses=M.HARDSHIP_STATUSES,
                facility_types=M.FACILITY_TYPES, application_statuses=M.APP_STATUSES, buckets=A.BUCKETS, categories=analyses.categories(), grades=[dict(min=c, grade=g, band=b) for c, g, b in C.POLICY["grades"]],
                factors=[dict(key=k, label=C.LABELS[k], max=v) for k, v in C.MAX_POINTS.items()], policy_defaults={k: C.POLICY[k] for k in settings.RANGES}, hem_households=list(MT.HEM_BENCHMARKS))


@router.get("/settings")
def get_settings(ctx: OrgContext = Ctx, db: Session = Db, a: Access = Acc):
    return P(settings.get(db, ctx, a))


@router.put("/settings")
def put_settings(body: dict = Body(...), ctx: OrgContext = Ctx, db: Session = Db, a: Access = Acc):
    out = settings.save(db, ctx, a, body)
    db.commit()
    return P(out)


@router.get("/dashboard")
def dashboard(ctx: OrgContext = Ctx, db: Session = Db, a: Access = Acc):
    """What needs attention: the pipeline, the book, arrears by bucket, the 30-day liquidity view and the things waiting on someone. A section appears only if the plan includes its module."""
    ent = SUB.entitlements(db, ctx.org.id)
    ok = lambda *f: bool(ctx.is_admin or SUB.is_allowed(ent, f))
    pipe = applications.list_(db, ctx, a, limit=200) if ok("loan-origination", "credit-assessment") else None
    book = loans.list_(db, ctx, a) if ok("loan-management") else None
    col_ = collections.register(db, ctx, a) if ok("collections") else None
    tre_ = treasury.position(db, ctx, a) if ok("treasury-liquidity") else None
    attention = []
    for r in (pipe["rows"] if pipe else []):
        if r["status"] == "more_information":
            attention.append(dict(kind="application", id=r["id"], text=f"{r['number']} ({r['applicant']}) is waiting for more information"))
        elif r["status"] in ("submitted", "assessing"):
            attention.append(dict(kind="application", id=r["id"], text=f"{r['number']} ({r['applicant']}) is waiting for a decision"))
    for r in (col_["rows"] if col_ else []):
        if r["follow_up_due"]:
            attention.append(dict(kind="loan", id=r["loan_id"], text=f"{r['number']} ({r['applicant']}): follow-up due, {r['days_overdue']} days overdue"))
        if (r["arrangement"] or {}).get("compliance") == "behind":
            attention.append(dict(kind="loan", id=r["loan_id"], text=f"{r['number']} ({r['applicant']}): behind on the payment arrangement"))
    liquidity = None
    if tre_:
        w30 = [w for w in tre_["windows"] if w["days"] == 30][0]
        liquidity = dict(cash=tre_["cash"]["total"], status=w30["status"], closing_committed=w30["closing_committed"], closing_forecast=w30["closing_forecast"], funding_required=w30["shortfall_committed"]["funding_required"], facility_available=tre_["facilities"]["available"])
        for f in tre_["facilities"]["rows"]:
            if f["status"] == "active" and f["expiry_warning"]:
                attention.append(dict(kind="facility", id=f["id"], text=f"{f['name']} expires in {f['days_to_expiry']} days"))
    return P(dict(pipeline=None if pipe is None else dict(counts=pipe["counts"], total=pipe["total"]), book=None if book is None else book["totals"], arrears=None if col_ is None else dict(buckets=col_["buckets"], summary=col_["summary"]),
                  liquidity=liquidity, attention=attention[:30]))


# ---------------------------------------------------------------------------------------------------------------------------------- applicants and analyses
@people.get("/applicants")
def applicants_list(q: str = "", limit: int = 25, ctx: OrgContext = Ctx, db: Session = Db, a: Access = Acc):
    return P(applicants.search(db, ctx, a, q, limit))


@people.post("/applicants")
def applicants_create(body: dict = Body(...), ctx: OrgContext = Ctx, db: Session = Db, a: Access = Acc):
    out = applicants.create(db, ctx, a, body)
    db.commit()
    return P(out)


@people.get("/applicants/{cid}")
def applicants_get(cid: int, ctx: OrgContext = Ctx, db: Session = Db, a: Access = Acc):
    return P(applicants.get(db, ctx, a, cid))


@people.put("/applicants/{cid}/profile")
def applicants_profile(cid: int, body: dict = Body(...), ctx: OrgContext = Ctx, db: Session = Db, a: Access = Acc):
    out = applicants.save_profile(db, ctx, a, cid, body)
    db.commit()
    return P(out)


@people.post("/applicants/{cid}/commitments")
def commitments_add(cid: int, body: dict = Body(...), ctx: OrgContext = Ctx, db: Session = Db, a: Access = Acc):
    out = applicants.save_commitment(db, ctx, a, cid, body)
    db.commit()
    return P(out)


@people.put("/applicants/{cid}/commitments/{kid}")
def commitments_update(cid: int, kid: int, body: dict = Body(...), ctx: OrgContext = Ctx, db: Session = Db, a: Access = Acc):
    out = applicants.save_commitment(db, ctx, a, cid, body, kid)
    db.commit()
    return P(out)


@people.delete("/applicants/{cid}/commitments/{kid}")
def commitments_delete(cid: int, kid: int, ctx: OrgContext = Ctx, db: Session = Db, a: Access = Acc):
    applicants.delete_commitment(db, ctx, a, cid, kid)
    db.commit()
    return dict(ok=True)


@router.get("/bank-accounts")
def bank_accounts(ctx: OrgContext = Ctx, db: Session = Db, a: Access = Acc):
    a.require("view")
    return P(acct.bank_accounts(db, ctx.org.id))


@router.get("/ledger-accounts")
def ledger_accounts(ctx: OrgContext = Ctx, db: Session = Db, a: Access = Acc):
    """The organisation's chart of accounts (id, code, name, type), for linking a loan to the ledger."""
    a.require("view")
    return P(acct.ledger_accounts(db, ctx.org.id))


@stmt.post("/applicants/{cid}/analyses/upload")
async def analyses_upload(cid: int, files: List[UploadFile] = File(...), household_type: str = Form(""), proposed_loan: float = Form(0), interest_rate: float = Form(0.065), loan_term_years: int = Form(30),
                          application_id: Optional[int] = Form(None), label: str = Form(""), analysis_months: Optional[int] = Form(None), ctx: OrgContext = Ctx, db: Session = Db, a: Access = Acc):
    """Upload statements (PDF, CSV or an image of a statement): extract, classify, analyse and SAVE against the applicant."""
    from accfino.modules.lending.api import _extract_one                      # the existing extractor, reused as it is
    a.require("upload")
    a.require("assess")
    if len(files) > MAX_FILES:
        raise HTTPException(422, f"At most {MAX_FILES} statement files can be analysed at once")
    results = []
    for f in files:
        raw = await f.read()
        if len(raw) > MAX_FILE:
            raise HTTPException(422, f"'{f.filename}' is larger than {MAX_FILE // (1024 * 1024)} MB")
        await f.seek(0)
        results.append(await _extract_one(f))
    if not any(r["ok"] for r in results):
        raise HTTPException(422, "No transactions could be read from the uploaded files: " + "; ".join(f"{r['filename']}: {r['error'] or 'nothing found'}" for r in results))
    out = analyses.create(db, ctx, a, cid, [dict(filename=r["filename"], transactions=r["transactions"]) for r in results if r["ok"]], household_type=household_type or None, proposed_loan=proposed_loan, interest_rate=interest_rate,
                          loan_term_years=loan_term_years, application_id=application_id, label=label, analysis_months=analysis_months)
    db.commit()
    return P(dict(out, files=[dict(filename=r["filename"], method=r["extraction_method"], transactions=r["transaction_count"], error=r["error"], ok=r["ok"]) for r in results]))


@stmt.post("/applicants/{cid}/analyses/books")
def analyses_books(cid: int, body: dict = Body(...), ctx: OrgContext = Ctx, db: Session = Db, a: Access = Acc):
    out = analyses.from_books(db, ctx, a, cid, body.get("account_ids") or [], body.get("date_from"), body.get("date_to"), household_type=body.get("household_type"), proposed_loan=body.get("proposed_loan") or 0,
                              interest_rate=body.get("interest_rate") or 0.065, loan_term_years=body.get("loan_term_years") or 30, application_id=body.get("application_id"), label=body.get("label") or "")
    db.commit()
    return P(out)


@stmt.get("/applicants/{cid}/analyses")
def analyses_list(cid: int, ctx: OrgContext = Ctx, db: Session = Db, a: Access = Acc):
    return P(analyses.list_for(db, ctx, a, cid))


@stmt.get("/analyses/{aid}")
def analyses_get(aid: int, lines: bool = False, ctx: OrgContext = Ctx, db: Session = Db, a: Access = Acc):
    return P(analyses.get(db, ctx, a, aid, lines))


@stmt.get("/analyses/{aid}/lines")
def analyses_lines(aid: int, flagged: bool = False, ctx: OrgContext = Ctx, db: Session = Db, a: Access = Acc):
    a.require("view")
    analyses._get(db, ctx, aid)
    return P(analyses.line_list(db, ctx, aid, flagged))


@stmt.post("/analyses/{aid}/reanalyse")
def analyses_reanalyse(aid: int, body: dict = Body({}), ctx: OrgContext = Ctx, db: Session = Db, a: Access = Acc):
    out = analyses.reanalyse(db, ctx, a, aid, household_type=body.get("household_type"), proposed_loan=body.get("proposed_loan"), interest_rate=body.get("interest_rate"), loan_term_years=body.get("loan_term_years"))
    db.commit()
    return P(out)


@stmt.post("/analyses/{aid}/lines/{lid}/override")
def analyses_override(aid: int, lid: int, body: dict = Body(...), ctx: OrgContext = Ctx, db: Session = Db, a: Access = Acc):
    out = analyses.override_line(db, ctx, a, aid, lid, body.get("category"), body.get("reason"))
    db.commit()
    return P(out)


@stmt.get("/analyses/{aid}/commitment-suggestions")
def analyses_suggestions(aid: int, ctx: OrgContext = Ctx, db: Session = Db, a: Access = Acc):
    return P(analyses.suggest_commitments(db, ctx, a, aid))


# ---------------------------------------------------------------------------------------------------------------------------------- applications
@orig.get("/applications")
def apps_list(status: str = "", q: str = "", contact_id: Optional[int] = None, ctx: OrgContext = Ctx, db: Session = Db, a: Access = Acc):
    return P(applications.list_(db, ctx, a, status, q, contact_id))


@orig.post("/applications")
def apps_create(body: dict = Body(...), ctx: OrgContext = Ctx, db: Session = Db, a: Access = Acc):
    out = applications.create(db, ctx, a, body)
    db.commit()
    return P(out)


@orig.get("/applications/{aid}")
def apps_get(aid: int, ctx: OrgContext = Ctx, db: Session = Db, a: Access = Acc):
    return P(applications.get(db, ctx, a, aid))


@orig.put("/applications/{aid}")
def apps_update(aid: int, body: dict = Body(...), ctx: OrgContext = Ctx, db: Session = Db, a: Access = Acc):
    out = applications.update(db, ctx, a, aid, body)
    db.commit()
    return P(out)


@orig.post("/applications/{aid}/assess")
def apps_assess(aid: int, body: dict = Body({}), ctx: OrgContext = Ctx, db: Session = Db, a: Access = Acc):
    out = applications.assess(db, ctx, a, aid, body.get("notes", ""))
    db.commit()
    return P(out)


@orig.post("/applications/{aid}/status")
def apps_status(aid: int, body: dict = Body(...), ctx: OrgContext = Ctx, db: Session = Db, a: Access = Acc):
    out = applications.change_status(db, ctx, a, aid, body.get("status"), body.get("reason", ""))
    db.commit()
    return P(out)


@orig.post("/applications/{aid}/decision")
def apps_decide(aid: int, body: dict = Body(...), ctx: OrgContext = Ctx, db: Session = Db, a: Access = Acc):
    out = applications.decide(db, ctx, a, aid, body.get("decision"), body.get("reason"))
    db.commit()
    return P(out)


@orig.post("/applications/{aid}/documents")
def apps_request_doc(aid: int, body: dict = Body(...), ctx: OrgContext = Ctx, db: Session = Db, a: Access = Acc):
    out = applications.request_document(db, ctx, a, aid, body.get("key"), body.get("label", ""), body.get("required", True))
    db.commit()
    return P(out)


@orig.post("/applications/{aid}/documents/{key}")
async def apps_upload_doc(aid: int, key: str, file: UploadFile = File(...), ctx: OrgContext = Ctx, db: Session = Db, a: Access = Acc):
    raw = await file.read()
    out = applications.attach_document(db, ctx, a, aid, key, file.filename or "document", (file.content_type or "").lower(), raw)
    db.commit()
    return P(out)


@orig.get("/applications/{aid}/documents/{key}/download")
def apps_download_doc(aid: int, key: str, ctx: OrgContext = Ctx, db: Session = Db, a: Access = Acc):
    meta, data = applications.download_document(db, ctx, a, aid, key)
    db.commit()                                                                                      # the download is audited
    safe = "".join(c for c in meta["filename"] if c not in '"\\\r\n')
    return Response(data, media_type=meta["content_type"] or "application/octet-stream", headers={"Content-Disposition": f'attachment; filename="{safe}"', "X-Content-Type-Options": "nosniff"})


@orig.delete("/applications/{aid}/documents/{key}")
def apps_remove_doc(aid: int, key: str, ctx: OrgContext = Ctx, db: Session = Db, a: Access = Acc):
    out = applications.remove_document(db, ctx, a, aid, key)
    db.commit()
    return P(out)


@orig.post("/applications/{aid}/settle")
def apps_settle(aid: int, body: dict = Body({}), ctx: OrgContext = Ctx, db: Session = Db, a: Access = Acc):
    out = loans.create(db, ctx, a, body, application_id=aid)
    db.commit()
    return P(out)


# ---------------------------------------------------------------------------------------------------------------------------------- loans
@lns.get("/loans")
def loans_list(status: str = "", q: str = "", contact_id: Optional[int] = None, as_at: Optional[str] = None, ctx: OrgContext = Ctx, db: Session = Db, a: Access = Acc):
    return P(loans.list_(db, ctx, a, status, q, contact_id, _d(as_at)))


@lns.post("/loans")
def loans_create(body: dict = Body(...), ctx: OrgContext = Ctx, db: Session = Db, a: Access = Acc):
    out = loans.create(db, ctx, a, body)
    db.commit()
    return P(out)


@lns.get("/loans/{lid}")
def loans_get(lid: int, as_at: Optional[str] = None, ctx: OrgContext = Ctx, db: Session = Db, a: Access = Acc):
    return P(loans.get(db, ctx, a, lid, _d(as_at)))


@lns.get("/loans/{lid}/schedule")
def loans_schedule(lid: int, as_at: Optional[str] = None, ctx: OrgContext = Ctx, db: Session = Db, a: Access = Acc):
    return P(loans.amortisation(db, ctx, a, lid, _d(as_at)))


@lns.post("/loans/{lid}/repayments")
def loans_repay(lid: int, body: dict = Body(...), post: bool = False, ctx: OrgContext = Ctx, db: Session = Db, a: Access = Acc):
    out = loans.add_repayment(db, ctx, a, lid, body, post=post)
    db.commit()
    return P(out)


@lns.post("/loans/{lid}/repayments/{rid}/post")
def loans_repay_post(lid: int, rid: int, ctx: OrgContext = Ctx, db: Session = Db, a: Access = Acc):
    out = loans.post_repayment(db, ctx, a, lid, rid)
    db.commit()
    return P(out)


@lns.post("/loans/{lid}/repayments/{rid}/void")
def loans_repay_void(lid: int, rid: int, body: dict = Body(...), ctx: OrgContext = Ctx, db: Session = Db, a: Access = Acc):
    out = loans.void_repayment(db, ctx, a, lid, rid, body.get("reason"))
    db.commit()
    return P(out)


@lns.post("/loans/{lid}/rate-changes")
def loans_rate(lid: int, body: dict = Body(...), ctx: OrgContext = Ctx, db: Session = Db, a: Access = Acc):
    out = loans.add_rate_change(db, ctx, a, lid, body.get("effective_date"), body.get("rate"), body.get("note", ""))
    db.commit()
    return P(out)


@lns.post("/loans/{lid}/refinance")
def loans_refinance(lid: int, body: dict = Body(...), ctx: OrgContext = Ctx, db: Session = Db, a: Access = Acc):
    out = loans.refinance(db, ctx, a, lid, body)
    db.commit()
    return P(out)


@lns.post("/loans/{lid}/status")
def loans_status(lid: int, body: dict = Body(...), ctx: OrgContext = Ctx, db: Session = Db, a: Access = Acc):
    out = loans.set_status(db, ctx, a, lid, body.get("status"), body.get("reason"))
    db.commit()
    return P(out)


# ---------------------------------------------------------------------------------------------------------------------------------- collections
@col.get("/collections")
def col_register(as_at: Optional[str] = None, bucket: str = "", status: str = "", q: str = "", all: bool = False, ctx: OrgContext = Ctx, db: Session = Db, a: Access = Acc):
    return P(collections.register(db, ctx, a, _d(as_at), bucket, status, q, arrears_only=not all))


@col.get("/collections/{lid}")
def col_case(lid: int, ctx: OrgContext = Ctx, db: Session = Db, a: Access = Acc):
    return P(collections.case(db, ctx, a, lid))


@col.post("/collections/{lid}/activities")
def col_activity(lid: int, body: dict = Body(...), ctx: OrgContext = Ctx, db: Session = Db, a: Access = Acc):
    out = collections.log_activity(db, ctx, a, lid, body)
    db.commit()
    return P(out)


@col.post("/collections/{lid}/arrangements")
def col_arrange(lid: int, body: dict = Body(...), ctx: OrgContext = Ctx, db: Session = Db, a: Access = Acc):
    out = collections.create_arrangement(db, ctx, a, lid, body)
    db.commit()
    return P(out)


@col.post("/collections/{lid}/arrangements/{rid}/close")
def col_arrange_close(lid: int, rid: int, body: dict = Body(...), ctx: OrgContext = Ctx, db: Session = Db, a: Access = Acc):
    out = collections.close_arrangement(db, ctx, a, lid, rid, body.get("status"), body.get("notes", ""))
    db.commit()
    return P(out)


@col.post("/collections/{lid}/hardship")
def col_hardship(lid: int, body: dict = Body(...), ctx: OrgContext = Ctx, db: Session = Db, a: Access = Acc):
    out = collections.request_hardship(db, ctx, a, lid, body)
    db.commit()
    return P(out)


@col.post("/collections/{lid}/hardship/{hid}")
def col_hardship_action(lid: int, hid: int, body: dict = Body(...), ctx: OrgContext = Ctx, db: Session = Db, a: Access = Acc):
    out = collections.hardship_action(db, ctx, a, lid, hid, body.get("action"), relief=body.get("relief", ""), outcome=body.get("outcome", ""), review_date=body.get("review_date"), arrangement_id=body.get("arrangement_id"))
    db.commit()
    return P(out)


# ---------------------------------------------------------------------------------------------------------------------------------- treasury
@tre.get("/treasury/position")
def tre_position(as_at: Optional[str] = None, horizon: int = 90, ctx: OrgContext = Ctx, db: Session = Db, a: Access = Acc):
    return P(treasury.position(db, ctx, a, _d(as_at), horizon))


@tre.get("/treasury/facilities")
def tre_facilities(ctx: OrgContext = Ctx, db: Session = Db, a: Access = Acc):
    return P(treasury.list_facilities(db, ctx, a))


@tre.post("/treasury/facilities")
def tre_fac_create(body: dict = Body(...), ctx: OrgContext = Ctx, db: Session = Db, a: Access = Acc):
    out = treasury.save_facility(db, ctx, a, body)
    db.commit()
    return P(out)


@tre.put("/treasury/facilities/{fid}")
def tre_fac_update(fid: int, body: dict = Body(...), ctx: OrgContext = Ctx, db: Session = Db, a: Access = Acc):
    out = treasury.save_facility(db, ctx, a, body, fid)
    db.commit()
    return P(out)


@tre.get("/treasury/forecast-items")
def tre_items(date_from: Optional[str] = None, date_to: Optional[str] = None, status: str = "", ctx: OrgContext = Ctx, db: Session = Db, a: Access = Acc):
    return P(treasury.list_items(db, ctx, a, _d(date_from), _d(date_to), status))


@tre.post("/treasury/forecast-items")
def tre_item_create(body: dict = Body(...), ctx: OrgContext = Ctx, db: Session = Db, a: Access = Acc):
    out = treasury.save_item(db, ctx, a, body)
    db.commit()
    return P(out)


@tre.put("/treasury/forecast-items/{iid}")
def tre_item_update(iid: int, body: dict = Body(...), ctx: OrgContext = Ctx, db: Session = Db, a: Access = Acc):
    out = treasury.save_item(db, ctx, a, body, iid)
    db.commit()
    return P(out)


# ---------------------------------------------------------------------------------------------------------------------------------- assemble (after every route is declared)
from accfino.shared import bulkload as _BL                                  # noqa: E402
from accfino.modules.lending.svc import bulk as _bulk                       # noqa: E402

# CSV bulk loading: one router for the module. Each table's own capability (edit / settle / configure) is enforced by the service per row; the platform switch and the plan's 'bulk-import' feature by gate().
bulk = _BL.build_router(_bulk.SPECS, ctx_dep=current_org, db_dep=get_db, access_dep=access, gate=_bulk.gate, enabled=_bulk.enabled)

for _r in (stmt, people, orig, lns, col, tre, bulk):
    router.include_router(_r)
