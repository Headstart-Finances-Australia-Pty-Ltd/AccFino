"""Saved statement analyses: classify -> correct own-account transfers -> metrics (the existing engine) -> Applicant Financial Summary. Re-run whenever the agent corrects a category."""
from dataclasses import asdict
from datetime import date
from typing import Dict, List, Optional

import accfino.modules.accounting.public as acct
from accfino.modules.lending import classifier, gap_detector, lend_models as M, metrics as MT
from accfino.modules.lending.engine import prep, summary as S
from accfino.modules.lending.svc import applicants
from accfino.modules.lending.svc.core import Access, LendError, NotFound, audit, choice, contact_or_404, parse_date, plain, q2


def _line_to_classified(l: M.LendAnalysisLine) -> Dict:
    cat = l.override_category or l.category
    hem = classifier.HEM_GROUP_MAP.get(cat, "other") if l.override_category else (l.hem_group or "other")
    income = (cat == "Income") if l.override_category else bool(l.is_income)
    debit, credit = float(l.debit or 0), float(l.credit or 0)
    return dict(date=l.line_date.isoformat() if l.line_date else "", description=l.description, debit=debit, credit=credit, balance=float(l.balance) if l.balance is not None else None, category=cat, hem_group=hem,
                exp_type="M" if (income and l.override_category) else (l.exp_type or "D"), in_or_out="O" if income else "I", is_income=income, is_debit=debit > 0, amount=debit or credit, reclassified=l.reclassified)


def _months(lines: List[Dict], given: Optional[int]) -> int:
    if given:
        return max(1, min(int(given), 24))
    ds = [d for d in (S.to_date(l.get("date")) for l in lines) if d]
    return max(1, min(24, round(((max(ds) - min(ds)).days + 1) / 30.44))) if ds else 1


def _compute(lines: List[Dict], inputs: Dict, months: int):
    m = asdict(MT.compute_metrics(lines, proposed_loan_amount=float(inputs.get("proposed_loan") or 0), proposed_interest_rate=float(inputs.get("interest_rate") or 0.065), proposed_term_years=int(inputs.get("loan_term_years") or 30),
                                  household_type=inputs.get("household_type") or "single_no_children", analysis_months=months))
    return m, S.build(lines, m)


def _store(an: M.LendAnalysis, m: Dict, summ: Dict, months: int):
    an.metrics, an.summary, an.months = plain(m), plain(summ), months
    st = summ.get("statement") or {}
    an.period_from = parse_date(st.get("from_date"), "from", False)
    an.period_to = parse_date(st.get("to_date"), "to", False)


def summary_dict(an: M.LendAnalysis) -> Dict:
    return dict(id=an.id, contact_id=an.contact_id, application_id=an.application_id, source=an.source, label=an.label, period_from=an.period_from, period_to=an.period_to, months=an.months, tx_count=an.tx_count, created_at=an.created_at,
                superseded=an.superseded, income_monthly=(an.summary or {}).get("headline", {}).get("income_monthly"), surplus_monthly=(an.summary or {}).get("headline", {}).get("surplus_monthly"))


def create(db, ctx, a: Access, contact_id: int, files: List[Dict], *, source: str = "upload", label: str = "", household_type: Optional[str] = None, proposed_loan=0, interest_rate=0.065, loan_term_years=30,
           application_id: Optional[int] = None, analysis_months: Optional[int] = None) -> Dict:
    """files: [{filename, transactions: [{date, description, debit, credit, balance?}]}] (the shape the existing extractors produce)."""
    a.require("assess")
    c = contact_or_404(db, ctx, contact_id)
    if application_id is not None:
        app = db.query(M.LendApplication).filter_by(org_id=ctx.org.id, id=application_id).first()
        if app is None or app.contact_id != c["id"]:
            raise NotFound("Application for this applicant")
    all_tx = []
    for f in files:
        for t in f.get("transactions") or []:
            d = S.to_date(t.get("date"))
            if d is None:
                continue
            all_tx.append(dict(t, date=d.isoformat(), _source_file=f.get("filename", "statement")))
    if not all_tx:
        raise LendError("No dated transactions were found in the statements. Check the files (PDF, CSV or image of a bank statement) and try again.")
    prof = applicants.profile_dict(applicants._profile(db, ctx, c["id"])) or {}
    ht = choice(household_type or prof.get("household_type"), M.HOUSEHOLDS, "household_type", default="single_no_children")
    inputs = dict(household_type=ht, proposed_loan=float(proposed_loan or 0), interest_rate=float(interest_rate or 0.065), loan_term_years=int(loan_term_years or 30))
    deduped = gap_detector.deduplicate_transactions(all_tx)
    classified, reviewed = prep.reclassify_transfers(classifier.classify_transactions(deduped))
    gap = gap_detector.detect_gaps([dict(filename=f.get("filename", "statement"), transactions=[dict(t, date=S.to_date(t.get("date")).isoformat()) for t in (f.get("transactions") or []) if S.to_date(t.get("date"))]) for f in files])
    months = _months(classified, analysis_months)
    m, summ = _compute(classified, inputs, months)
    an = M.LendAnalysis(org_id=ctx.org.id, contact_id=c["id"], application_id=application_id, source=choice(source, ("upload", "books"), "source", default="upload"), label=(label or "")[:200] or None, tx_count=len(classified),
                        reviewed=plain(reviewed), gap_report=plain(gap), inputs=inputs, created_by=ctx.user_id)
    _store(an, m, summ, months)
    db.add(an)
    db.flush()
    for old in db.query(M.LendAnalysis).filter(M.LendAnalysis.org_id == ctx.org.id, M.LendAnalysis.contact_id == c["id"], M.LendAnalysis.id != an.id, M.LendAnalysis.application_id == application_id, M.LendAnalysis.superseded.is_(False)):
        old.superseded = True                                                                 # the newest analysis for this applicant (and application) is the current one; older ones stay for the record
    for l in classified:
        db.add(M.LendAnalysisLine(org_id=ctx.org.id, analysis_id=an.id, line_date=S.to_date(l["date"]), description=str(l.get("description", ""))[:500], debit=q2(l.get("debit") or 0), credit=q2(l.get("credit") or 0),
                                  balance=q2(l["balance"]) if l.get("balance") not in (None, "") else None, category=l.get("category"), hem_group=l.get("hem_group"), exp_type=l.get("exp_type"), is_income=bool(l.get("is_income")),
                                  reclassified=l.get("reclassified"), source_file=str(l.get("source_file") or l.get("_source_file") or "")[:200] or None))
    db.flush()
    audit(db, ctx, "analysis.create", "lend_analysis", an.id, contact_id=c["id"], source=an.source, transactions=an.tx_count, months=months, application_id=application_id)
    return get(db, ctx, a, an.id)


def from_books(db, ctx, a: Access, contact_id: int, account_ids: List[int], date_from, date_to, **kw) -> Dict:
    """Analyse bank transactions ALREADY in Accfino for the chosen bank accounts: nothing is re-entered or re-uploaded."""
    a.require("assess")
    df, dt = parse_date(date_from, "date_from"), parse_date(date_to, "date_to")
    if dt < df:
        raise LendError("date_to cannot be before date_from")
    valid = {b["id"] for b in acct.bank_accounts(db, ctx.org.id)}
    ids = [int(x) for x in account_ids if int(x) in valid]
    if not ids:
        raise LendError("Choose at least one of the organisation's bank accounts")
    rows = acct.bank_lines(db, ctx.org.id, ids, df, dt)
    tx = [dict(date=r["date"].isoformat(), description=r["description"], debit=float(-r["amount"]) if r["amount"] < 0 else 0.0, credit=float(r["amount"]) if r["amount"] > 0 else 0.0, balance=float(r["balance"]) if r["balance"] is not None else None) for r in rows]
    return create(db, ctx, a, contact_id, [dict(filename="Accfino bank accounts", transactions=tx)], source="books", **kw)


def _get(db, ctx, analysis_id: int) -> M.LendAnalysis:
    an = db.query(M.LendAnalysis).filter_by(org_id=ctx.org.id, id=analysis_id).first()
    if an is None:
        raise NotFound("Analysis")
    return an


def get(db, ctx, a: Access, analysis_id: int, lines: bool = False) -> Dict:
    a.require("view")
    an = _get(db, ctx, analysis_id)
    out = dict(summary_dict(an), metrics=an.metrics, summary=an.summary, reviewed=an.reviewed, gap_report=an.gap_report, inputs=an.inputs)
    if lines:
        out["lines"] = line_list(db, ctx, an.id)
    return out


def line_list(db, ctx, analysis_id: int, only_flagged: bool = False) -> List[Dict]:
    q = db.query(M.LendAnalysisLine).filter_by(org_id=ctx.org.id, analysis_id=analysis_id).order_by(M.LendAnalysisLine.line_date, M.LendAnalysisLine.id)
    rows = [dict(id=l.id, date=l.line_date, description=l.description, debit=l.debit, credit=l.credit, balance=l.balance, category=l.override_category or l.category, original_category=l.category, hem_group=l.hem_group, is_income=l.is_income,
                 reclassified=l.reclassified, override_reason=l.override_reason, overridden=bool(l.override_category)) for l in q]
    return [r for r in rows if r["reclassified"] or r["overridden"]] if only_flagged else rows


def list_for(db, ctx, a: Access, contact_id: int) -> List[Dict]:
    a.require("view")
    contact_or_404(db, ctx, contact_id)
    return [summary_dict(x) for x in db.query(M.LendAnalysis).filter_by(org_id=ctx.org.id, contact_id=contact_id).order_by(M.LendAnalysis.id.desc())]


def categories() -> List[str]:
    return sorted(classifier.HEM_GROUP_MAP)


def override_line(db, ctx, a: Access, analysis_id: int, line_id: int, category: str, reason: str) -> Dict:
    """The agent corrects one line's category (for example a transfer that really is rent income). The reason is required and recorded; the whole analysis is re-computed."""
    a.require("assess")
    an = _get(db, ctx, analysis_id)
    l = db.query(M.LendAnalysisLine).filter_by(org_id=ctx.org.id, analysis_id=an.id, id=line_id).first()
    if l is None:
        raise NotFound("Transaction")
    reason = (reason or "").strip()
    if len(reason) < 5:
        raise LendError("Give a reason of at least five characters: it is kept with the analysis")
    if category not in classifier.HEM_GROUP_MAP:
        raise LendError(f"category must be one of the listed categories (got '{category}')")
    before = l.override_category or l.category
    l.override_category, l.override_reason, l.override_by = category, reason[:300], ctx.user_id
    db.flush()
    reanalyse(db, ctx, a, an.id, _audit=False)
    audit(db, ctx, "analysis.override_line", "lend_analysis", an.id, line_id=l.id, description=l.description, before=before, after=category, reason=reason)
    return get(db, ctx, a, an.id)


def reanalyse(db, ctx, a: Access, analysis_id: int, *, household_type: Optional[str] = None, proposed_loan=None, interest_rate=None, loan_term_years=None, _audit=True) -> Dict:
    """Re-run the metrics and summary from the saved lines (with any corrections), optionally for a different household or a different proposed loan."""
    a.require("assess")
    an = _get(db, ctx, analysis_id)
    inputs = dict(an.inputs or {})
    if household_type:
        inputs["household_type"] = choice(household_type, M.HOUSEHOLDS, "household_type")
    if proposed_loan is not None:
        inputs["proposed_loan"] = float(proposed_loan)
    if interest_rate is not None:
        inputs["interest_rate"] = float(interest_rate)
    if loan_term_years is not None:
        inputs["loan_term_years"] = int(loan_term_years)
    lines = [_line_to_classified(l) for l in db.query(M.LendAnalysisLine).filter_by(org_id=ctx.org.id, analysis_id=an.id).order_by(M.LendAnalysisLine.line_date, M.LendAnalysisLine.id)]
    m, summ = _compute(lines, inputs, an.months)
    an.inputs = inputs
    _store(an, m, summ, an.months)
    db.flush()
    if _audit:
        audit(db, ctx, "analysis.reanalyse", "lend_analysis", an.id, inputs=inputs)
    return get(db, ctx, a, an.id)


def suggest_commitments(db, ctx, a: Access, analysis_id: int) -> List[Dict]:
    """Recurring loan, card and interest payments found in the statements, as suggestions the agent can confirm as the applicant's existing debts."""
    a.require("view")
    an = _get(db, ctx, analysis_id)
    out = []
    for r in (an.summary or {}).get("recurring_commitments", []):
        lab = (r.get("label") or "").upper()
        kind = "credit_card" if (r.get("category") == "Credit Card Payment" or "CARD" in lab) else "car_loan" if ("CAR" in lab or "AUTO" in lab or "TOYOTA" in lab or "FINANCE" in lab) else "home_loan" if ("MORTGAGE" in lab or "HOME LOAN" in lab) else "personal_loan"
        out.append(dict(kind=kind, lender=r["label"], monthly_repayment=r["monthly_equivalent"], source="detected", last_seen=r.get("last_date"), occurrences=r.get("occurrences")))
    return out
