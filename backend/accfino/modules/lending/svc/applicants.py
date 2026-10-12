"""Applicants are existing contacts (so nothing is entered twice) plus a lending profile and their declared or detected commitments."""
from decimal import Decimal
from typing import Dict, Optional

import accfino.modules.accounting.public as acct
from accfino.modules.lending import lend_models as M
from accfino.modules.lending.svc.core import Access, LendError, NotFound, audit, choice, contact_or_404, no_tfn, num, plain, q2


def _profile(db, ctx, contact_id) -> Optional[M.LendApplicantProfile]:
    return db.query(M.LendApplicantProfile).filter_by(org_id=ctx.org.id, contact_id=contact_id).first()


def profile_dict(p) -> Optional[Dict]:
    return None if p is None else dict(household_type=p.household_type, dependants=p.dependants, employment_type=p.employment_type, employer=p.employer, employment_months=p.employment_months, residency=p.residency, notes=p.notes)


def commitment_dict(c) -> Dict:
    return dict(id=c.id, kind=c.kind, lender=c.lender, limit_amount=c.limit_amount, balance=c.balance, monthly_repayment=c.monthly_repayment, interest_rate=c.interest_rate, source=c.source, notes=c.notes)


def search(db, ctx, a: Access, q: str = "", limit: int = 25):
    a.require("view")
    rows = acct.contacts_search(db, ctx.org.id, q, limit)
    ids = [r["id"] for r in rows]
    apps = {}
    if ids:
        for x in db.query(M.LendApplication).filter(M.LendApplication.org_id == ctx.org.id, M.LendApplication.contact_id.in_(ids)):
            apps.setdefault(x.contact_id, []).append(x)
    return [dict(r, applications=len(apps.get(r["id"], [])), open_applications=len([x for x in apps.get(r["id"], []) if x.status in ("draft", "submitted", "assessing", "more_information")])) for r in rows]


def create(db, ctx, a: Access, body: dict) -> Dict:
    a.require("edit")
    name = (body.get("name") or "").strip()
    if not name:
        raise LendError("The applicant's name is required")
    for k in ("name", "email", "phone", "address", "notes"):
        no_tfn(body.get(k), k)
    try:
        c, created = acct.create_contact(db, ctx.org.id, name=name, email=body.get("email"), phone=body.get("phone"), abn=body.get("abn"), address=body.get("address"), notes=body.get("notes"))
    except ValueError as e:
        raise LendError(str(e))
    if created:
        audit(db, ctx, "applicant.create", "contact", c["id"], name=name)
    return dict(c, created=created)


def get(db, ctx, a: Access, contact_id: int) -> Dict:
    a.require("view")
    c = contact_or_404(db, ctx, contact_id)
    cms = db.query(M.LendCommitment).filter_by(org_id=ctx.org.id, contact_id=c["id"]).order_by(M.LendCommitment.id).all()
    return dict(contact=c, profile=profile_dict(_profile(db, ctx, c["id"])), commitments=[commitment_dict(x) for x in cms],
                commitments_monthly=q2(sum((x.monthly_repayment for x in cms), 0)))


def save_profile(db, ctx, a: Access, contact_id: int, body: dict) -> Dict:
    a.require("edit")
    c = contact_or_404(db, ctx, contact_id)
    for k in ("employer", "residency", "notes"):
        no_tfn(body.get(k), k)
    months = body.get("employment_months")
    if months not in (None, ""):
        months = int(num(months, "employment_months", maximum=num(1200, "x")))
    deps = int(num(body.get("dependants", 0) or 0, "dependants", maximum=num(20, "x")))
    p = _profile(db, ctx, c["id"])
    before = profile_dict(p)
    vals = dict(household_type=choice(body.get("household_type"), M.HOUSEHOLDS, "household_type", default="single_no_children"), dependants=deps, employment_type=choice(body.get("employment_type"), M.EMPLOYMENT, "employment_type", required=False),
                employer=(body.get("employer") or None), employment_months=months if months not in (None, "") else None, residency=(body.get("residency") or None), notes=(body.get("notes") or None))
    if p is None:
        p = M.LendApplicantProfile(org_id=ctx.org.id, contact_id=c["id"], created_by=ctx.user_id, **vals)
        db.add(p)
    else:
        for k, v in vals.items():
            setattr(p, k, v)
    db.flush()
    audit(db, ctx, "applicant.profile", "contact", c["id"], before=before, after=profile_dict(p))
    return profile_dict(p)


def save_commitment(db, ctx, a: Access, contact_id: int, body: dict, commitment_id: Optional[int] = None) -> Dict:
    a.require("edit")
    c = contact_or_404(db, ctx, contact_id)
    no_tfn(body.get("lender"), "lender")
    no_tfn(body.get("notes"), "notes")
    rate = num(body.get("interest_rate"), "interest_rate")
    vals = dict(kind=choice(body.get("kind"), M.COMMITMENT_KINDS, "kind"), lender=(body.get("lender") or None), limit_amount=num(body.get("limit_amount"), "limit_amount"), balance=num(body.get("balance"), "balance"),
                monthly_repayment=num(body.get("monthly_repayment", 0), "monthly_repayment", required=True), interest_rate=rate, source=choice(body.get("source"), ("declared", "detected"), "source", default="declared"), notes=(body.get("notes") or None))
    if rate is not None and rate > Decimal("0.5"):
        raise LendError("interest_rate is a fraction: 6.5% is 0.065")
    if commitment_id is None:
        x = M.LendCommitment(org_id=ctx.org.id, contact_id=c["id"], created_by=ctx.user_id, **vals)
        db.add(x)
    else:
        x = db.query(M.LendCommitment).filter_by(org_id=ctx.org.id, contact_id=c["id"], id=commitment_id).first()
        if x is None:
            raise NotFound("Commitment")
        for k, v in vals.items():
            setattr(x, k, v)
    db.flush()
    audit(db, ctx, "commitment.save", "lend_commitment", x.id, contact_id=c["id"], kind=x.kind, monthly=x.monthly_repayment)
    return commitment_dict(x)


def delete_commitment(db, ctx, a: Access, contact_id: int, commitment_id: int):
    a.require("edit")
    x = db.query(M.LendCommitment).filter_by(org_id=ctx.org.id, contact_id=contact_id, id=commitment_id).first()
    if x is None:
        raise NotFound("Commitment")
    audit(db, ctx, "commitment.delete", "lend_commitment", x.id, contact_id=contact_id, kind=x.kind, monthly=x.monthly_repayment)
    db.delete(x)
    db.flush()
