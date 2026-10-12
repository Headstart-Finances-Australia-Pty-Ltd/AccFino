"""The loan register. A loan is its TERMS plus its RATE CHANGES plus its REPAYMENTS: the balance, arrears and schedule are always recomputed from those by engine/amort.py, never stored.

Optional ledger link, ONLY for the organisation's own borrowing (a liability): repayments post as Dr loan account (principal), Dr interest expense, Cr bank. A loan the agent merely tracks for a client does not touch the books."""
from datetime import date
from decimal import Decimal
from typing import Dict, List, Optional

import accfino.modules.accounting.public as acct
from accfino.modules.lending import lend_models as M
from accfino.modules.lending.engine import amort as A
from accfino.modules.lending.svc import applications
from accfino.modules.lending.svc.core import Access, Conflict, LendError, NotFound, audit, choice, contact_or_404, label, no_tfn, num, parse_date, plain, q2

ZERO = Decimal("0")


def periods_for(term_months: int, frequency: str) -> int:
    n = {"monthly": term_months, "quarterly": term_months / 3, "fortnightly": term_months * 26 / 12, "weekly": term_months * 52 / 12}[frequency]
    return max(1, int(round(n)))


def first_due_default(start: date, freq: str) -> date:
    """One period after settlement, unless the first instalment date is given."""
    return {"weekly": lambda: start.fromordinal(start.toordinal() + 7), "fortnightly": lambda: start.fromordinal(start.toordinal() + 14), "monthly": lambda: A.add_months(start, 1), "quarterly": lambda: A.add_months(start, 3)}[freq]()


def _loan(db, ctx, loan_id: int) -> M.LendLoan:
    x = db.query(M.LendLoan).filter_by(org_id=ctx.org.id, id=loan_id).first()
    if x is None:
        raise NotFound("Loan")
    return x


def _next_number(db, ctx) -> str:
    n = 0
    for (v,) in db.query(M.LendLoan.number).filter_by(org_id=ctx.org.id):
        try:
            n = max(n, int(str(v).split("-")[-1]))
        except ValueError:
            pass
    return f"LN-{n + 1:04d}"


def terms_of(db, ctx, x: M.LendLoan) -> A.Terms:
    rc = [(r.effective_date, Decimal(r.rate)) for r in db.query(M.LendRateChange).filter_by(org_id=ctx.org.id, loan_id=x.id).order_by(M.LendRateChange.effective_date)]
    return A.Terms(principal=Decimal(x.original_amount), annual_rate=Decimal(x.rate), term_periods=x.term_periods, frequency=x.frequency, start_date=x.start_date, first_due=x.first_due, interest_only_periods=x.interest_only_periods,
                   balloon=Decimal(x.balloon or 0), rate_changes=rc)


def repayments_of(db, ctx, x: M.LendLoan, include_voided=False) -> List[M.LendRepayment]:
    q = db.query(M.LendRepayment).filter_by(org_id=ctx.org.id, loan_id=x.id)
    if not include_voided:
        q = q.filter(M.LendRepayment.voided.is_(False))
    return q.order_by(M.LendRepayment.paid_date, M.LendRepayment.id).all()


def position(db, ctx, x: M.LendLoan, as_at: Optional[date] = None) -> Dict:
    as_at = as_at or date.today()
    t = terms_of(db, ctx, x)
    p = A.replay(t, [(r.paid_date, r.amount) for r in repayments_of(db, ctx, x)], as_at)
    p["current_rate"] = A.rate_at(t, as_at)
    p["maturity"] = A.due_date(x.first_due, x.frequency, x.term_periods)
    return p


def _ledger_check(db, ctx, body: dict) -> Dict:
    out = {}
    accts = {a["id"]: a for a in acct.ledger_accounts(db, ctx.org.id)}
    for key, want in (("ledger_loan_account_id", ("liability", "current_liability", "non_current_liability", "long_term_liability")), ("ledger_interest_account_id", None), ("ledger_bank_account_id", ("bank",))):
        v = body.get(key)
        if v in (None, ""):
            out[key] = None
            continue
        a = accts.get(int(v))
        if a is None:
            raise LendError(f"{key.replace('_', ' ')}: that account was not found in this organisation")
        if want and not any(w in str(a["type"]).lower() for w in want):
            raise LendError(f"{a['code']} {a['name']} is a {a['type']} account: choose a {want[0].replace('_', ' ')} account for {key.replace('_id', '').replace('_', ' ')}")
        out[key] = a["id"]
    if any(out.values()) and not all(out.values()):
        raise LendError("To post repayments to the ledger give all three accounts: the loan (liability), the interest expense and the bank account. Leave all three empty to track the loan without posting.")
    return out


def _validate(db, ctx, body: dict) -> Dict:
    for k in ("lender", "purpose", "security_description", "notes"):
        no_tfn(body.get(k), k)
    amount = q2(num(body.get("original_amount"), "original_amount", required=True))
    freq = choice(body.get("frequency"), M.FREQUENCIES, "frequency", default="monthly")
    periods = int(num(body.get("term_periods"), "term_periods", required=True)) if body.get("term_periods") else periods_for(int(num(body.get("term_months"), "term_months", required=True)), freq)
    rate = num(body.get("rate"), "rate", required=True)
    if rate > 1:
        raise LendError("rate is a fraction: 6.5% is 0.065")
    start = parse_date(body.get("start_date"), "start_date")
    first = parse_date(body.get("first_due"), "first_due", False) or first_due_default(start, freq)
    io = int(num(body.get("interest_only_periods", 0) or 0, "interest_only_periods"))
    balloon = q2(num(body.get("balloon", 0) or 0, "balloon"))
    ltype = choice(body.get("loan_type"), M.LOAN_TYPES, "loan_type", default="term_loan")
    if ltype == "interest_only" and not io:
        io = min(periods - 1, max(1, periods // 5)) if periods > 1 else 0
    try:
        A.Terms(principal=amount, annual_rate=rate, term_periods=periods, frequency=freq, start_date=start, first_due=first, interest_only_periods=io, balloon=balloon).validate()
    except ValueError as e:
        raise LendError(str(e))
    if body.get("fixed_asset_id") not in (None, ""):
        if acct.fixed_asset(db, ctx.org.id, int(body["fixed_asset_id"])) is None:
            raise LendError("The fixed asset was not found in this organisation")
    return dict(lender=(body.get("lender") or None), loan_type=ltype, purpose=(body.get("purpose") or None), original_amount=amount, rate=rate, term_periods=periods, frequency=freq, start_date=start, first_due=first,
                interest_only_periods=io, balloon=balloon, security_description=(body.get("security_description") or None), fixed_asset_id=int(body["fixed_asset_id"]) if body.get("fixed_asset_id") not in (None, "") else None,
                notes=(body.get("notes") or None), **_ledger_check(db, ctx, body))


def create(db, ctx, a: Access, body: dict, application_id: Optional[int] = None) -> Dict:
    """Create a loan in the register (a loan arranged elsewhere, a lease, hire purchase) or settle an approved application into one."""
    a.require("settle")
    app = None
    if application_id is not None:
        app = db.query(M.LendApplication).filter_by(org_id=ctx.org.id, id=application_id).first()
        if app is None:
            raise NotFound("Application")
        if app.status != "approved":
            raise Conflict("Only an approved application can be settled into a loan", "bad_transition")
        body = dict(dict(contact_id=app.contact_id, original_amount=app.amount, rate=app.rate, term_months=app.term_months, frequency=app.repayment_frequency, loan_type=app.loan_type, lender=app.lender, purpose=app.purpose,
                         security_description=app.security_description, interest_only_periods=0), **{k: v for k, v in body.items() if v not in (None, "")})
        if body.get("rate") is None:
            raise LendError("The application has no rate: enter the rate the loan settles at")
    c = contact_or_404(db, ctx, body.get("contact_id"))
    v = _validate(db, ctx, body)
    x = M.LendLoan(org_id=ctx.org.id, number=_next_number(db, ctx), contact_id=c["id"], application_id=application_id, status="active", created_by=ctx.user_id, **v)
    db.add(x)
    db.flush()
    if app is not None:
        applications.mark_settled(db, ctx, app, x.id)
    audit(db, ctx, "loan.create", "lend_loan", x.id, number=x.number, contact_id=c["id"], amount=x.original_amount, rate=x.rate, application_id=application_id)
    return get(db, ctx, a, x.id)


def loan_row(db, ctx, x: M.LendLoan, as_at: date) -> Dict:
    p = position(db, ctx, x, as_at)
    c = acct.contact(db, ctx.org.id, x.contact_id) or {}
    return dict(id=x.id, number=x.number, contact_id=x.contact_id, applicant=c.get("name"), lender=x.lender, loan_type=x.loan_type, original_amount=x.original_amount, balance=p["balance"], rate=p["current_rate"], term_periods=x.term_periods,
                frequency=x.frequency, next_due=(p["next"] or {}).get("due"), next_amount=(p["next"] or {}).get("amount"), maturity=p["maturity"], status=x.status, performance=p["status"], arrears_amount=p["arrears_amount"], days_overdue=p["days_overdue"],
                bucket=p["bucket"], missed_count=p["missed_count"])


def list_(db, ctx, a: Access, status: str = "", q: str = "", contact_id: Optional[int] = None, as_at: Optional[date] = None) -> Dict:
    a.require("view")
    as_at = as_at or date.today()
    qs = db.query(M.LendLoan).filter_by(org_id=ctx.org.id)
    if status:
        qs = qs.filter(M.LendLoan.status == status)
    if contact_id:
        qs = qs.filter(M.LendLoan.contact_id == int(contact_id))
    rows = [loan_row(db, ctx, x, as_at) for x in qs.order_by(M.LendLoan.id.desc())]
    if q:
        rows = [r for r in rows if q.lower() in f"{r['number']} {r['applicant']} {r['lender'] or ''} {r['loan_type']}".lower()]
    active = [r for r in rows if r["status"] == "active"]
    return dict(rows=rows, as_at=as_at, totals=dict(loans=len(rows), active=len(active), balance=q2(sum((r["balance"] for r in active), ZERO)), original=q2(sum((r["original_amount"] for r in active), ZERO)),
                                                      in_arrears=len([r for r in active if r["arrears_amount"] > 0]), arrears=q2(sum((r["arrears_amount"] for r in active), ZERO))))


def get(db, ctx, a: Access, loan_id: int, as_at: Optional[date] = None) -> Dict:
    a.require("view")
    x = _loan(db, ctx, loan_id)
    as_at = as_at or date.today()
    p = position(db, ctx, x, as_at)
    c = acct.contact(db, ctx.org.id, x.contact_id) or {}
    rc = [dict(id=r.id, effective_date=r.effective_date, rate=r.rate, note=r.note) for r in db.query(M.LendRateChange).filter_by(org_id=ctx.org.id, loan_id=x.id).order_by(M.LendRateChange.effective_date)]
    reps = [dict(id=r.id, paid_date=r.paid_date, amount=r.amount, method=r.method, reference=r.reference, journal_id=r.journal_id, voided=r.voided, voided_reason=r.voided_reason) for r in repayments_of(db, ctx, x, include_voided=True)]
    return dict(loan=dict(id=x.id, number=x.number, contact_id=x.contact_id, applicant=c.get("name"), application_id=x.application_id, lender=x.lender, loan_type=x.loan_type, purpose=x.purpose, original_amount=x.original_amount, rate=x.rate,
                          term_periods=x.term_periods, frequency=x.frequency, start_date=x.start_date, first_due=x.first_due, interest_only_periods=x.interest_only_periods, balloon=x.balloon, status=x.status, security_description=x.security_description,
                          fixed_asset_id=x.fixed_asset_id, refinanced_from_id=x.refinanced_from_id, refinanced_to_id=x.refinanced_to_id, ledger_posting=bool(x.ledger_loan_account_id), notes=x.notes, closed_at=x.closed_at),
                position={k: v for k, v in p.items() if k != "instalments"}, rate_changes=rc, repayments=reps)


def amortisation(db, ctx, a: Access, loan_id: int, as_at: Optional[date] = None) -> Dict:
    """The contractual schedule (interest and principal split of every instalment) with what has actually happened beside each instalment that has fallen due."""
    a.require("view")
    x = _loan(db, ctx, loan_id)
    as_at = as_at or date.today()
    t = terms_of(db, ctx, x)
    sched = A.contractual_schedule(t)
    act = {i["n"]: i for i in A.replay(t, [(r.paid_date, r.amount) for r in repayments_of(db, ctx, x)], as_at)["instalments"]}
    rows = []
    for r in sched:
        i = act.get(r["n"])
        rows.append(dict(r, status=i["status"] if i else "future", actual_paid=q2(i["interest_paid"] + i["principal_paid"]) if i else ZERO, actual_interest=i["interest_due"] if i else None, actual_principal=i["principal_due"] if i else None))
    tot = A.totals(sched)
    by_year = {}
    for r in sched:
        y = by_year.setdefault(r["due"].year, dict(year=r["due"].year, interest=ZERO, principal=ZERO))
        y["interest"] += r["interest"]
        y["principal"] += r["principal"]
    return dict(as_at=as_at, loan_id=x.id, contractual=rows, totals=tot, by_year=[dict(y, interest=q2(y["interest"]), principal=q2(y["principal"])) for y in by_year.values()],
                note="The contractual schedule shows every instalment as if paid on time at the rates now known; the status column shows what has actually been received.")


# ---------------------------------------------------------------------------------------------------------------------------------- repayments
def add_repayment(db, ctx, a: Access, loan_id: int, body: dict, post: bool = False) -> Dict:
    a.require("edit")
    x = _loan(db, ctx, loan_id)
    if x.status != "active":
        raise Conflict(f"A {x.status.replace('_', ' ')} loan cannot take repayments", "locked")
    amount = q2(num(body.get("amount"), "amount", required=True))
    if amount <= 0:
        raise LendError("The repayment must be greater than zero")
    paid = parse_date(body.get("paid_date"), "paid_date")
    if paid < x.start_date:
        raise LendError("A repayment cannot be dated before the loan started")
    if paid > date.today():
        raise LendError("A repayment cannot be dated in the future")
    ref = (body.get("reference") or None)
    no_tfn(ref, "reference")
    dup = db.query(M.LendRepayment).filter_by(org_id=ctx.org.id, loan_id=x.id, paid_date=paid, amount=amount, voided=False).filter((M.LendRepayment.reference == ref) | (M.LendRepayment.reference.is_(None) if ref is None else False)).first()
    if dup is not None and not body.get("allow_duplicate"):
        raise Conflict("A repayment of the same amount on the same date (and reference) is already recorded. If this is a genuine second payment, record it with allow_duplicate.", "duplicate")
    r = M.LendRepayment(org_id=ctx.org.id, loan_id=x.id, paid_date=paid, amount=amount, method=(body.get("method") or None), reference=ref, bank_line_id=body.get("bank_line_id") or None, created_by=ctx.user_id)
    db.add(r)
    db.flush()
    audit(db, ctx, "loan.repayment", "lend_loan", x.id, repayment_id=r.id, amount=amount, paid_date=paid, reference=ref)
    out = dict(repayment_id=r.id, **{k: v for k, v in position(db, ctx, x).items() if k in ("balance", "arrears_amount", "days_overdue", "bucket", "status")})
    if post:
        out["journal"] = post_repayment(db, ctx, a, x.id, r.id)
    return out


def split_of(db, ctx, x: M.LendLoan, repayment: M.LendRepayment) -> Dict:
    """How ONE repayment was applied: the engine allocates every repayment as it replays the whole history (so money paid a day early still goes to the instalment it settles, interest first)."""
    t = terms_of(db, ctx, x)
    reps = repayments_of(db, ctx, x)
    out = A.replay(t, [(r.paid_date, r.amount, r.id) for r in reps], date.today())
    al = next((a for a in out["allocations"] if a["ref"] == repayment.id), None)
    if al is None:
        raise NotFound("Repayment")
    return dict(interest=al["interest"], principal=q2(al["principal"] + al["extra_principal"] + al["overpaid"]))


def post_repayment(db, ctx, a: Access, loan_id: int, repayment_id: int) -> Dict:
    a.require("settle")
    x = _loan(db, ctx, loan_id)
    if not x.ledger_loan_account_id:
        raise Conflict("This loan is not linked to ledger accounts. Link them on the loan to post repayments (only for the organisation's own borrowing).", "no_ledger")
    r = db.query(M.LendRepayment).filter_by(org_id=ctx.org.id, loan_id=x.id, id=repayment_id).first()
    if r is None or r.voided:
        raise NotFound("Repayment")
    if r.journal_id:
        raise Conflict("This repayment is already posted to the ledger", "posted")
    s = split_of(db, ctx, x, r)
    lines = [dict(account_id=x.ledger_bank_account_id, debit=ZERO, credit=r.amount)]
    if s["principal"] > 0:
        lines.append(dict(account_id=x.ledger_loan_account_id, debit=s["principal"], credit=ZERO))
    if s["interest"] > 0:
        lines.append(dict(account_id=x.ledger_interest_account_id, debit=s["interest"], credit=ZERO))
    try:
        j = acct.post_journal(db, ctx.org, journal_date=r.paid_date, narration=f"Loan repayment {x.number}", lines=lines, created_by=ctx.user_id, source_type="lending", source_ref=f"lend:{r.id}", reference=r.reference)
    except acct.LedgerError as e:
        raise Conflict(str(e), "ledger_refused")
    r.journal_id = j.id
    db.flush()
    audit(db, ctx, "loan.repayment_post", "lend_loan", x.id, repayment_id=r.id, journal_id=j.id, principal=s["principal"], interest=s["interest"])
    return dict(journal_id=j.id, journal_no=getattr(j, "journal_no", None), principal=s["principal"], interest=s["interest"])


def void_repayment(db, ctx, a: Access, loan_id: int, repayment_id: int, reason: str) -> Dict:
    a.require("edit")
    x = _loan(db, ctx, loan_id)
    r = db.query(M.LendRepayment).filter_by(org_id=ctx.org.id, loan_id=x.id, id=repayment_id).first()
    if r is None:
        raise NotFound("Repayment")
    if r.voided:
        raise Conflict("That repayment is already void", "voided")
    if r.journal_id:
        raise Conflict("This repayment is posted to the ledger. Reverse its journal in Accounting first, then void it here.", "posted")
    if len((reason or "").strip()) < 5:
        raise LendError("Give a reason of at least five characters")
    r.voided, r.voided_reason = True, reason.strip()[:300]
    db.flush()
    audit(db, ctx, "loan.repayment_void", "lend_loan", x.id, repayment_id=r.id, amount=r.amount, reason=reason)
    return get(db, ctx, a, x.id)


# ---------------------------------------------------------------------------------------------------------------------------------- rate change, refinance, status
def add_rate_change(db, ctx, a: Access, loan_id: int, effective_date, rate, note: str = "") -> Dict:
    a.require("settle")
    x = _loan(db, ctx, loan_id)
    eff = parse_date(effective_date, "effective_date")
    rt = num(rate, "rate", required=True)
    if rt > 1 or rt > Decimal("0.5"):
        raise LendError("rate is a fraction between 0 and 0.5: 6.5% is 0.065")
    if eff < x.start_date:
        raise LendError("A rate change cannot take effect before the loan started")
    ex = db.query(M.LendRateChange).filter_by(org_id=ctx.org.id, loan_id=x.id, effective_date=eff).first()
    before = None if ex is None else ex.rate
    if ex is None:
        db.add(M.LendRateChange(org_id=ctx.org.id, loan_id=x.id, effective_date=eff, rate=rt, note=(note or None), created_by=ctx.user_id))
    else:
        ex.rate, ex.note = rt, (note or None)
    db.flush()
    audit(db, ctx, "loan.rate_change", "lend_loan", x.id, effective_date=eff, rate=rt, previous=before)
    return get(db, ctx, a, x.id)


def refinance(db, ctx, a: Access, loan_id: int, body: dict) -> Dict:
    """Pay out the loan on a date (what is owing, including interest to that date) and start a new loan, linked both ways."""
    a.require("settle")
    old = _loan(db, ctx, loan_id)
    if old.status != "active":
        raise Conflict(f"A {old.status.replace('_', ' ')} loan cannot be refinanced", "locked")
    on = parse_date(body.get("refinance_date"), "refinance_date")
    if on < old.start_date or on > date.today():
        raise LendError("The refinance date must be after the loan started and not in the future")
    payout = position(db, ctx, old, on)["payout_estimate"]
    if payout <= 0:
        raise Conflict("Nothing is owing on this loan", "paid_out")
    nb = dict(body, contact_id=old.contact_id, start_date=on, original_amount=body.get("original_amount") or payout)
    nb.setdefault("lender", old.lender)
    nb.setdefault("loan_type", old.loan_type)
    v = _validate(db, ctx, nb)
    db.add(M.LendRepayment(org_id=ctx.org.id, loan_id=old.id, paid_date=on, amount=payout, method="refinance", reference=f"Refinanced on {on}", created_by=ctx.user_id))
    new = M.LendLoan(org_id=ctx.org.id, number=_next_number(db, ctx), contact_id=old.contact_id, status="active", refinanced_from_id=old.id, created_by=ctx.user_id, **v)
    db.add(new)
    db.flush()
    old.status, old.refinanced_to_id, old.closed_at = "refinanced", new.id, __import__("datetime").datetime.utcnow()
    db.flush()
    audit(db, ctx, "loan.refinance", "lend_loan", old.id, new_loan_id=new.id, new_number=new.number, payout=payout, on=on, new_amount=new.original_amount, new_rate=new.rate)
    return dict(old=get(db, ctx, a, old.id), new=get(db, ctx, a, new.id), payout=payout)


def set_status(db, ctx, a: Access, loan_id: int, status: str, reason: str) -> Dict:
    """Write a loan off, or cancel one created in error. Needs the approve permission and a reason."""
    a.require("approve")
    x = _loan(db, ctx, loan_id)
    status = choice(status, ("written_off", "cancelled"), "status")
    if x.status != "active":
        raise Conflict(f"A {x.status.replace('_', ' ')} loan cannot be changed", "locked")
    if len((reason or "").strip()) < 5:
        raise LendError("Give a reason of at least five characters")
    if status == "cancelled" and repayments_of(db, ctx, x):
        raise Conflict("A loan with repayments cannot be cancelled: write it off or refinance it instead", "has_repayments")
    prev = x.status
    x.status, x.closed_at = status, __import__("datetime").datetime.utcnow()
    db.flush()
    audit(db, ctx, "loan.status", "lend_loan", x.id, from_status=prev, to_status=status, reason=reason, balance=position(db, ctx, x)["balance"])
    return get(db, ctx, a, x.id)
