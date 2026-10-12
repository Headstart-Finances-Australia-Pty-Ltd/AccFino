"""Loan applications: Applicant -> Loan request -> Financial analysis -> Credit assessment -> Documents -> Recommendation -> Approval -> Settlement.

Status machine, document checklist, assessment history and decisions. Every status change and decision is an immutable event with who, when and why (and a row in the platform audit log).
A person decides: the assessment RECOMMENDS. Going against the recommendation needs the override permission and a reason, which is recorded on the assessment."""
from datetime import datetime
from decimal import Decimal
from typing import Dict, List, Optional

import accfino.modules.accounting.public as acct
from accfino.modules.lending import lend_models as M
from accfino.modules.lending.engine import credit as C
from accfino.modules.lending.svc import analyses, applicants, settings
from accfino.modules.lending.svc.core import Access, Conflict, LendError, NotFound, audit, choice, contact_or_404, label, no_tfn, num, plain, q2

OPEN = ("draft", "submitted", "assessing", "more_information")
TRANSITIONS = {"draft": ("submitted", "withdrawn"), "submitted": ("assessing", "more_information", "withdrawn", "declined"), "assessing": ("more_information", "approved", "declined", "withdrawn"),
               "more_information": ("submitted", "assessing", "withdrawn", "declined"), "approved": ("settled", "withdrawn"), "declined": (), "settled": (), "withdrawn": ()}
DOC_LABELS = {"photo_id": "Photo identification", "income_evidence": "Evidence of income (payslips, tax return or BAS)", "security_valuation": "A valuation of the security", "contract_of_sale": "Contract of sale", "other": "Other document"}
APPROVE_OUTCOMES = ("approve", "approve_with_conditions")
DEFAULT_RATE = 0.065


def _app(db, ctx, app_id: int) -> M.LendApplication:
    x = db.query(M.LendApplication).filter_by(org_id=ctx.org.id, id=app_id).first()
    if x is None:
        raise NotFound("Application")
    return x


def _next_number(db, ctx) -> str:
    n = 0
    for (num_,) in db.query(M.LendApplication.number).filter_by(org_id=ctx.org.id):
        try:
            n = max(n, int(str(num_).split("-")[-1]))
        except ValueError:
            pass
    return f"APP-{n + 1:04d}"


def _event(db, ctx, app_id, kind, *, from_status=None, to_status=None, reason=None, detail=None):
    db.add(M.LendApplicationEvent(org_id=ctx.org.id, application_id=app_id, at=datetime.utcnow(), by_user_id=ctx.user_id, by_name=getattr(ctx, "username", None), kind=kind, from_status=from_status, to_status=to_status, reason=reason, detail=plain(detail)))


def terms(x: M.LendApplication) -> Dict:
    return dict(amount=str(x.amount), term_months=x.term_months, rate=str(x.rate) if x.rate is not None else None, loan_type=x.loan_type, interest_only=bool(x.interest_only), security_value=str(x.security_value) if x.security_value is not None else None)


def _validate(body: dict, existing: Optional[M.LendApplication] = None) -> Dict:
    g = lambda k, d=None: body.get(k, getattr(existing, k, d) if existing is not None else d)
    for k in ("purpose", "lender", "security_description", "notes"):
        no_tfn(body.get(k), k)
    amount = num(g("amount"), "amount", required=True, maximum=Decimal("1000000000"))
    if amount <= 0:
        raise LendError("The loan amount must be greater than zero")
    term = int(num(g("term_months"), "term_months", required=True, maximum=Decimal("600")))
    if term < 1:
        raise LendError("The term must be at least one month")
    rate = num(g("rate"), "rate", maximum=Decimal("1"))
    if rate is not None and rate > Decimal("0.5"):
        raise LendError("rate is a fraction: 6.5% is 0.065")
    sec = num(g("security_value"), "security_value")
    return dict(purpose=(g("purpose") or None), loan_type=choice(g("loan_type"), M.LOAN_TYPES, "loan_type", default="term_loan"), amount=q2(amount), term_months=term, rate=rate,
                repayment_frequency=choice(g("repayment_frequency"), M.FREQUENCIES, "repayment_frequency", default="monthly"), interest_only=bool(g("interest_only", False)) or g("loan_type") == "interest_only",
                lender=(g("lender") or None), security_description=(g("security_description") or None), security_value=q2(sec) if sec is not None else None, notes=(g("notes") or None))


def _ensure_requirements(db, ctx, x: M.LendApplication):
    have = {r.key for r in db.query(M.LendDocRequirement).filter_by(org_id=ctx.org.id, application_id=x.id)}
    want = ["photo_id", "income_evidence"] + (["security_valuation"] if (x.security_description or (x.security_value or 0) > 0) else [])
    for k in want:
        if k not in have:
            db.add(M.LendDocRequirement(org_id=ctx.org.id, application_id=x.id, key=k, label=DOC_LABELS[k], required=True))


def create(db, ctx, a: Access, body: dict) -> Dict:
    a.require("edit")
    c = contact_or_404(db, ctx, body.get("contact_id"))
    v = _validate(body)
    x = M.LendApplication(org_id=ctx.org.id, number=_next_number(db, ctx), contact_id=c["id"], status="draft", created_by=ctx.user_id, assigned_to=ctx.user_id, **v)
    db.add(x)
    db.flush()
    _ensure_requirements(db, ctx, x)
    _event(db, ctx, x.id, "status", to_status="draft", reason="Application started")
    audit(db, ctx, "application.create", "lend_application", x.id, number=x.number, contact_id=c["id"], amount=x.amount)
    return get(db, ctx, a, x.id)


def update(db, ctx, a: Access, app_id: int, body: dict) -> Dict:
    a.require("edit")
    x = _app(db, ctx, app_id)
    if x.status not in OPEN:
        raise Conflict(f"A {x.status.replace('_', ' ')} application can no longer be changed", "locked")
    before = terms(x)
    for k, v in _validate(body, x).items():
        setattr(x, k, v)
    db.flush()
    _ensure_requirements(db, ctx, x)
    after = terms(x)
    if before != after:
        _event(db, ctx, x.id, "note", reason="The loan terms changed: re-run the credit assessment", detail=dict(before=before, after=after))
        audit(db, ctx, "application.update", "lend_application", x.id, before=before, after=after)
    return get(db, ctx, a, x.id)


def _latest_analysis(db, ctx, x: M.LendApplication) -> Optional[M.LendAnalysis]:
    q = db.query(M.LendAnalysis).filter_by(org_id=ctx.org.id, contact_id=x.contact_id, superseded=False)
    return q.filter(M.LendAnalysis.application_id == x.id).order_by(M.LendAnalysis.id.desc()).first() or q.filter(M.LendAnalysis.application_id.is_(None)).order_by(M.LendAnalysis.id.desc()).first()


def _latest_assessment(db, ctx, x: M.LendApplication) -> Optional[M.LendAssessment]:
    return db.query(M.LendAssessment).filter_by(org_id=ctx.org.id, application_id=x.id).order_by(M.LendAssessment.version.desc()).first()


def _docs(db, ctx, x) -> List[Dict]:
    return [dict(key=r.key, label=r.label, required=r.required, received=r.attachment_id is not None, attachment_id=r.attachment_id, received_at=r.received_at)
            for r in db.query(M.LendDocRequirement).filter_by(org_id=ctx.org.id, application_id=x.id).order_by(M.LendDocRequirement.id)]


def assessment_dict(s: Optional[M.LendAssessment], x: M.LendApplication) -> Optional[Dict]:
    if s is None:
        return None
    r = s.result or {}
    stale = (r.get("application") or {}).get("terms") != terms(x)
    return dict(id=s.id, version=s.version, created_at=s.created_at, score=s.score, grade=s.grade, outcome=s.outcome, notes=s.notes, stale=stale, analysis_id=s.analysis_id, result=r,
                override=None if not s.override_outcome else dict(outcome=s.override_outcome, reason=s.override_reason, by=s.override_by_name, at=s.override_at))


def _next_action(x, analysis, assess, docs) -> str:
    if x.status in ("declined", "withdrawn", "settled"):
        return f"This application is {x.status}."
    if x.status == "approved":
        return "Settle the loan: record the loan details to create it in the register."
    if analysis is None:
        return "Analyse the applicant's statements (upload them, or use the bank accounts already in Accfino)."
    if assess is None or assessment_dict(assess, x)["stale"]:
        return "Run the credit assessment" + (" again: the loan terms changed." if assess is not None else ".")
    missing = [d["label"] for d in docs if d["required"] and not d["received"]]
    if missing:
        return f"Obtain: {missing[0]}" + (f" (and {len(missing) - 1} more)" if len(missing) > 1 else "")
    if x.status == "draft":
        return "Submit the application."
    if x.status == "more_information":
        return "Resubmit once the extra information is in."
    return "Make the decision: approve or decline, with the reason."


def get(db, ctx, a: Access, app_id: int) -> Dict:
    a.require("view")
    x = _app(db, ctx, app_id)
    contact = contact_or_404(db, ctx, x.contact_id)
    an, s, docs = _latest_analysis(db, ctx, x), _latest_assessment(db, ctx, x), _docs(db, ctx, x)
    ad = assessment_dict(s, x)
    ev = [dict(id=e.id, at=e.at, by=e.by_name, kind=e.kind, from_status=e.from_status, to_status=e.to_status, reason=e.reason, detail=e.detail) for e in db.query(M.LendApplicationEvent).filter_by(org_id=ctx.org.id, application_id=x.id).order_by(M.LendApplicationEvent.id)]
    missing = list(dict.fromkeys(((ad or {}).get("result") or {}).get("missing_info", []) + [f"{d['label']} has not been received" for d in docs if d["required"] and not d["received"]]))
    return dict(application=dict(id=x.id, number=x.number, contact_id=x.contact_id, purpose=x.purpose, loan_type=x.loan_type, amount=x.amount, term_months=x.term_months, rate=x.rate, repayment_frequency=x.repayment_frequency,
                                 interest_only=x.interest_only, lender=x.lender, security_description=x.security_description, security_value=x.security_value, status=x.status, submitted_at=x.submitted_at, decided_at=x.decided_at,
                                 decision_reason=x.decision_reason, loan_id=x.loan_id, notes=x.notes, created_at=x.created_at, allowed_next=list(TRANSITIONS[x.status])),
                applicant=dict(contact=contact, **{k: v for k, v in applicants.get(db, ctx, a, x.contact_id).items() if k != "contact"}), analysis=None if an is None else analyses.summary_dict(an) | dict(headline=(an.summary or {}).get("headline")),
                assessment=ad, documents=docs, missing=missing, events=ev, next_action=_next_action(x, an, s, docs))


def list_(db, ctx, a: Access, status: str = "", q: str = "", contact_id: Optional[int] = None, limit: int = 200) -> Dict:
    a.require("view")
    qs = db.query(M.LendApplication).filter_by(org_id=ctx.org.id)
    if status:
        qs = qs.filter(M.LendApplication.status == status)
    if contact_id:
        qs = qs.filter(M.LendApplication.contact_id == int(contact_id))
    rows = qs.order_by(M.LendApplication.id.desc()).limit(max(1, min(int(limit), 500))).all()
    names = {r["id"]: r["name"] for r in acct.contacts_search(db, ctx.org.id, "", 100)}
    out = []
    for x in rows:
        c = acct.contact(db, ctx.org.id, x.contact_id) or {}
        s = _latest_assessment(db, ctx, x)
        row = dict(id=x.id, number=x.number, applicant=c.get("name"), contact_id=x.contact_id, purpose=x.purpose, loan_type=x.loan_type, amount=x.amount, status=x.status, grade=s.grade if s else None, score=s.score if s else None,
                   outcome=(s.override_outcome or s.outcome) if s else None, created_at=x.created_at, age_days=(datetime.utcnow() - x.created_at).days if x.created_at else None)
        if not q or q.lower() in f"{x.number} {row['applicant']} {x.purpose or ''}".lower():
            out.append(row)
    counts = {st: 0 for st in M.APP_STATUSES}
    for (st,) in db.query(M.LendApplication.status).filter_by(org_id=ctx.org.id):
        counts[st] = counts.get(st, 0) + 1
    return dict(rows=out, counts=counts, total=sum(counts.values()))


# ---------------------------------------------------------------------------------------------------------------------------------- documents
def _req(db, ctx, x, key) -> Optional[M.LendDocRequirement]:
    return db.query(M.LendDocRequirement).filter_by(org_id=ctx.org.id, application_id=x.id, key=key).first()


def request_document(db, ctx, a: Access, app_id: int, key: str, label_: str = "", required: bool = True) -> List[Dict]:
    a.require("edit")
    x = _app(db, ctx, app_id)
    key = (key or "").strip().lower().replace(" ", "_")[:40]
    if not key:
        raise LendError("A document name is required")
    if _req(db, ctx, x, key) is None:
        db.add(M.LendDocRequirement(org_id=ctx.org.id, application_id=x.id, key=key, label=(label_ or DOC_LABELS.get(key) or label(key))[:200], required=bool(required)))
        db.flush()
        audit(db, ctx, "application.document_request", "lend_application", x.id, key=key)
    return _docs(db, ctx, x)


def attach_document(db, ctx, a: Access, app_id: int, key: str, filename: str, content_type: str, data: bytes) -> List[Dict]:
    a.require("upload")
    x = _app(db, ctx, app_id)
    r = _req(db, ctx, x, key)
    if r is None:
        raise NotFound("Document requirement")
    try:
        meta = acct.add_attachment(db, ctx.org.id, "lend_app", x.id, filename, content_type, data, ctx.user_id)
    except ValueError as e:
        raise LendError(str(e))
    if r.attachment_id:
        acct.delete_attachment(db, ctx.org.id, r.attachment_id)                                # a replacement supersedes the earlier file
    r.attachment_id, r.received_at, r.received_by = meta["id"], datetime.utcnow(), ctx.user_id
    db.flush()
    _event(db, ctx, x.id, "document", reason=f"{r.label}: {meta['filename']} received", detail=dict(key=key, attachment_id=meta["id"], size=meta["size"]))
    audit(db, ctx, "application.document", "lend_application", x.id, key=key, filename=meta["filename"], size=meta["size"])
    return _docs(db, ctx, x)


def download_document(db, ctx, a: Access, app_id: int, key: str):
    a.require("view")
    x = _app(db, ctx, app_id)
    r = _req(db, ctx, x, key)
    if r is None or not r.attachment_id:
        raise NotFound("Document")
    got = acct.get_attachment(db, ctx.org.id, r.attachment_id)
    if got is None or got[0]["owner_kind"] != "lend_app" or got[0]["owner_id"] != x.id:                  # never serve a file that belongs to something else
        raise NotFound("Document")
    audit(db, ctx, "application.document_download", "lend_application", x.id, key=key)
    return got


def remove_document(db, ctx, a: Access, app_id: int, key: str) -> List[Dict]:
    a.require("edit")
    x = _app(db, ctx, app_id)
    r = _req(db, ctx, x, key)
    if r is None or not r.attachment_id:
        raise NotFound("Document")
    acct.delete_attachment(db, ctx.org.id, r.attachment_id)
    r.attachment_id = r.received_at = r.received_by = None
    db.flush()
    _event(db, ctx, x.id, "document", reason=f"{r.label}: file removed")
    audit(db, ctx, "application.document_remove", "lend_application", x.id, key=key)
    return _docs(db, ctx, x)


# ---------------------------------------------------------------------------------------------------------------------------------- assessment
def assess(db, ctx, a: Access, app_id: int, notes: str = "") -> Dict:
    a.require("assess")
    x = _app(db, ctx, app_id)
    if x.status not in OPEN:
        raise Conflict(f"A {x.status.replace('_', ' ')} application cannot be re-assessed", "locked")
    an = _latest_analysis(db, ctx, x)
    if an is None:
        raise Conflict("Analyse the applicant's statements first: the assessment needs their income and spending.", "no_analysis")
    prof = applicants.profile_dict(applicants._profile(db, ctx, x.contact_id)) or {}
    m = dict(an.metrics or {})
    declared = sum((c.monthly_repayment for c in db.query(M.LendCommitment).filter_by(org_id=ctx.org.id, contact_id=x.contact_id)), Decimal("0"))
    seen = float(m.get("loans_monthly") or 0) + float(m.get("credit_card_monthly") or 0)
    adj = max(0.0, float(declared) - seen)                                                           # declared debts the statements do not show are added, never double-counted
    if adj > 0:
        m["umi"] = float(m.get("umi") or 0) - adj
        m["loans_monthly"] = float(m.get("loans_monthly") or 0) + adj
    conduct = (an.summary or {}).get("conduct", {})
    got = [d["key"] for d in _docs(db, ctx, x) if d["received"]]
    extras = dict(has_analysis=True, documents_received=got, recurring_income_monthly=((an.summary or {}).get("headline") or {}).get("recurring_income_monthly"), dishonours=conduct.get("events", 0),
                  unusual_count=len((an.summary or {}).get("unusual", [])))
    app_in = dict(amount=float(x.amount), term_months=x.term_months, rate=float(x.rate) if x.rate is not None else DEFAULT_RATE, security=x.security_description, security_value=float(x.security_value or 0), interest_only=bool(x.interest_only))
    res = C.assess(m, app_in, prof, extras, settings.policy(db, ctx))
    res["application"] = dict(terms=terms(x), number=x.number, rate_assumed=x.rate is None)
    res["analysis_id"], res["declared_commitments_added"] = an.id, round(adj, 2)
    ver = (db.query(M.LendAssessment).filter_by(org_id=ctx.org.id, application_id=x.id).count()) + 1
    s = M.LendAssessment(org_id=ctx.org.id, application_id=x.id, analysis_id=an.id, version=ver, score=res["score"], grade=res["grade"], outcome=res["recommendation"]["outcome"], result=plain(res), notes=(notes or None), created_by=ctx.user_id)
    db.add(s)
    db.flush()
    if x.status == "submitted":
        _move(db, ctx, x, "assessing", "Assessment started")
    _event(db, ctx, x.id, "assessment", reason=f"Version {ver}: grade {s.grade} ({s.score}), recommends {label(s.outcome).lower()}", detail=dict(assessment_id=s.id, analysis_id=an.id, score=s.score, grade=s.grade, outcome=s.outcome))
    audit(db, ctx, "application.assess", "lend_application", x.id, version=ver, score=s.score, grade=s.grade, outcome=s.outcome)
    return assessment_dict(s, x)


# ---------------------------------------------------------------------------------------------------------------------------------- status and decisions
def _move(db, ctx, x, to: str, reason: str, detail=None):
    if to not in TRANSITIONS[x.status]:
        raise Conflict(f"An application that is {x.status.replace('_', ' ')} cannot become {to.replace('_', ' ')}. It can become: {', '.join(t.replace('_', ' ') for t in TRANSITIONS[x.status]) or 'nothing (it is final)'}.", "bad_transition")
    frm = x.status
    x.status = to
    if to == "submitted":
        x.submitted_at = datetime.utcnow()
    _event(db, ctx, x.id, "status", from_status=frm, to_status=to, reason=reason, detail=detail)
    audit(db, ctx, "application.status", "lend_application", x.id, number=x.number, from_status=frm, to_status=to, reason=reason)


def change_status(db, ctx, a: Access, app_id: int, to: str, reason: str = "") -> Dict:
    """Submit, move to assessing or more information, or withdraw. Approve / decline go through decide() (they need authority and a reason); settling goes through the loan register."""
    a.require("edit")
    x = _app(db, ctx, app_id)
    to = choice(to, M.APP_STATUSES, "status")
    if to in ("approved", "declined"):
        raise LendError("Approve or decline with a decision and a reason (decide)")
    if to == "settled":
        raise LendError("An application is settled by creating its loan in the register")
    if to == "submitted":
        if x.amount <= 0 or x.term_months < 1:
            raise LendError("Complete the loan amount and term before submitting")
    if to in ("more_information", "withdrawn") and len((reason or "").strip()) < 5:
        raise LendError("Give a reason of at least five characters")
    _move(db, ctx, x, to, (reason or "").strip() or f"Moved to {to.replace('_', ' ')}")
    db.flush()
    return get(db, ctx, a, x.id)


def decide(db, ctx, a: Access, app_id: int, decision: str, reason: str) -> Dict:
    """Approve or decline. Needs the approve permission and a reason. Going AGAINST the recommendation also needs the override permission, and is recorded on the assessment as an override."""
    a.require("approve")
    x = _app(db, ctx, app_id)
    decision = choice(decision, ("approved", "declined"), "decision")
    reason = (reason or "").strip()
    if len(reason) < 5:
        raise LendError("A decision needs a reason of at least five characters: it is recorded with your name and the date")
    if x.status not in ("submitted", "assessing", "more_information"):
        raise Conflict(f"An application that is {x.status.replace('_', ' ')} cannot be {decision} now", "bad_transition")
    s = _latest_assessment(db, ctx, x)
    if s is None:
        raise Conflict("Run the credit assessment before deciding: a decision must rest on one.", "no_assessment")
    if assessment_dict(s, x)["stale"]:
        raise Conflict("The loan terms changed after the last assessment: run it again before deciding.", "stale_assessment")
    rec = s.outcome
    against = (decision == "approved" and rec == "decline") or (decision == "declined" and rec in APPROVE_OUTCOMES)
    if against:
        a.require("override")                                                                          # checked FIRST: a refused attempt changes nothing
    if x.status == "submitted":
        _move(db, ctx, x, "assessing", "Assessment started")
    if against:
        s.override_outcome, s.override_reason, s.override_by, s.override_by_name, s.override_at = decision, reason, ctx.user_id, getattr(ctx, "username", None), datetime.utcnow()
        _event(db, ctx, x.id, "override", reason=reason, detail=dict(recommended=rec, decided=decision, assessment_id=s.id, grade=s.grade, score=s.score))
        audit(db, ctx, "application.override", "lend_application", x.id, recommended=rec, decided=decision, reason=reason, assessment_id=s.id)
    x.decided_at, x.decided_by, x.decision_reason = datetime.utcnow(), ctx.user_id, reason
    _move(db, ctx, x, decision, reason, detail=dict(recommended=rec, overridden=against, assessment_id=s.id))
    _event(db, ctx, x.id, "decision", reason=reason, detail=dict(decision=decision, recommended=rec, overridden=against, grade=s.grade, score=s.score))
    audit(db, ctx, "application.decision", "lend_application", x.id, decision=decision, recommended=rec, overridden=against, reason=reason)
    db.flush()
    return get(db, ctx, a, x.id)


def mark_settled(db, ctx, x: M.LendApplication, loan_id: int):
    """Used by the loan register when the loan is created from an approved application."""
    if x.status != "approved":
        raise Conflict("Only an approved application can be settled", "bad_transition")
    x.loan_id = loan_id
    _move(db, ctx, x, "settled", "Loan created in the register", detail=dict(loan_id=loan_id))
