"""Collections: practical visibility of repayment problems, not a debt-collection system.

Arrears, days overdue and the bucket are DERIVED from the loan's schedule and repayments (never typed in). What people do is recorded: activities, payment arrangements and hardship cases.
The collection status is derived with a fixed precedence so two agents looking at the same loan see the same thing."""
from datetime import date, timedelta
from decimal import Decimal
from typing import Dict, List, Optional

import accfino.modules.accounting.public as acct
from accfino.modules.lending import lend_models as M
from accfino.modules.lending.engine import amort as A
from accfino.modules.lending.svc import loans as LN
from accfino.modules.lending.svc.core import Access, Conflict, LendError, NotFound, audit, choice, no_tfn, num, parse_date, q2

ZERO = Decimal("0")
OPEN_HARDSHIP = ("requested", "assessing", "approved", "active")
HARDSHIP_FLOW = {"requested": ("assessing", "approved", "declined"), "assessing": ("approved", "declined"), "approved": ("active", "completed"), "active": ("completed",), "declined": (), "completed": ()}
RECENT_CONTACT_DAYS = 14
STATUS_LABELS = {"current": "Current", "in_arrears": "In arrears: no contact yet", "contacted": "Contacted", "promise_to_pay": "Promise to pay", "escalated": "Escalated", "arrangement": "On a payment arrangement", "hardship": "Hardship",
                 "written_off": "Written off", "closed": "Closed"}
PERIOD_DAYS = {"weekly": 7, "fortnightly": 14, "monthly": 30, "quarterly": 91}


def _periods_elapsed(start: date, freq: str, as_at: date) -> int:
    if as_at < start:
        return 0
    n = 1
    while A.due_date(start, freq, n + 1) <= as_at:
        n += 1
    return n


def _activities(db, ctx, loan_id) -> List[M.LendCollectionActivity]:
    return db.query(M.LendCollectionActivity).filter_by(org_id=ctx.org.id, loan_id=loan_id).order_by(M.LendCollectionActivity.activity_date.desc(), M.LendCollectionActivity.id.desc()).all()


def _arrangement(db, ctx, loan_id) -> Optional[M.LendArrangement]:
    return db.query(M.LendArrangement).filter_by(org_id=ctx.org.id, loan_id=loan_id, status="active").first()


def _open_hardship(db, ctx, loan_id) -> Optional[M.LendHardship]:
    return db.query(M.LendHardship).filter(M.LendHardship.org_id == ctx.org.id, M.LendHardship.loan_id == loan_id, M.LendHardship.status.in_(OPEN_HARDSHIP)).first()


def arrangement_progress(db, ctx, x: M.LendLoan, arr: M.LendArrangement, as_at: date) -> Dict:
    """Is the borrower keeping to the arrangement? Expected = the instalments that have fallen due since it started; paid = repayments received since then."""
    expected_n = _periods_elapsed(arr.start_date, arr.frequency, as_at)
    expected = q2(arr.amount_per_period * expected_n)
    paid = q2(sum((r.amount for r in LN.repayments_of(db, ctx, x) if r.paid_date >= arr.start_date and r.paid_date <= as_at), ZERO))
    behind = max(ZERO, expected - paid)
    return dict(expected=expected, paid=paid, behind=q2(behind), instalments_due=expected_n, compliance="behind" if behind >= arr.amount_per_period else "on_track")


def status_of(db, ctx, x: M.LendLoan, pos: Dict, as_at: date) -> Dict:
    acts = _activities(db, ctx, x.id)
    arr = _arrangement(db, ctx, x.id)
    hs = _open_hardship(db, ctx, x.id)
    last = acts[0] if acts else None
    if x.status == "written_off":
        st = "written_off"
    elif x.status != "active":
        st = "closed"
    elif pos["arrears_amount"] <= 0 and not hs and not arr:
        st = "current"
    elif hs:
        st = "hardship"
    elif arr:
        st = "arrangement"
    elif last and last.kind == "promise_to_pay" and last.next_action_date and last.next_action_date >= as_at:
        st = "promise_to_pay"
    elif last and last.kind == "escalated":
        st = "escalated"
    elif last and (as_at - last.activity_date).days <= RECENT_CONTACT_DAYS:
        st = "contacted"
    else:
        st = "in_arrears"
    return dict(status=st, label=STATUS_LABELS[st], last_activity=None if last is None else dict(date=last.activity_date, kind=last.kind, outcome=last.outcome), next_action_date=last.next_action_date if last else None,
                follow_up_due=bool(last and last.next_action_date and last.next_action_date <= as_at and pos["arrears_amount"] > 0), arrangement=None if arr is None else dict(id=arr.id, amount_per_period=arr.amount_per_period, frequency=arr.frequency, can_complete=pos["arrears_amount"] <= 0, **arrangement_progress(db, ctx, x, arr, as_at)),
                hardship=None if hs is None else dict(id=hs.id, status=hs.status, relief=hs.relief))


def _row(db, ctx, x: M.LendLoan, as_at: date) -> Dict:
    pos = LN.position(db, ctx, x, as_at)
    c = acct.contact(db, ctx.org.id, x.contact_id) or {}
    reps = LN.repayments_of(db, ctx, x)
    last_pay = reps[-1] if reps else None
    overdue = [i for i in pos.get("instalments", []) if i["status"] != "paid" and i["due"] < as_at]
    oldest = min((i["due"] for i in overdue), default=None)
    s = status_of(db, ctx, x, pos, as_at)
    return dict(loan_id=x.id, number=x.number, contact_id=x.contact_id, applicant=c.get("name"), phone=c.get("phone"), email=c.get("email"), lender=x.lender, balance=pos["balance"], oldest_due_date=oldest, amount_due=pos["amount_due_today"] + pos["arrears_amount"],
                amount_paid=last_pay.amount if last_pay else ZERO, last_payment_date=last_pay.paid_date if last_pay else None, arrears_amount=pos["arrears_amount"], days_overdue=pos["days_overdue"], missed_payments=pos["missed_count"], bucket=pos["bucket"], **s)


def register(db, ctx, a: Access, as_at: Optional[date] = None, bucket: str = "", status: str = "", q: str = "", arrears_only: bool = True) -> Dict:
    """Every active loan with its arrears position and collection state, the five buckets, and the follow-ups due."""
    a.require("view")
    as_at = as_at or date.today()
    rows = [_row(db, ctx, x, as_at) for x in db.query(M.LendLoan).filter(M.LendLoan.org_id == ctx.org.id, M.LendLoan.status == "active").order_by(M.LendLoan.id)]
    buckets = {b: dict(loans=0, arrears=ZERO, balance=ZERO) for b in A.BUCKETS}
    for r in rows:
        b = buckets[r["bucket"]]
        b["loans"] += 1
        b["arrears"] += r["arrears_amount"]
        b["balance"] += r["balance"]
    out = rows
    if arrears_only:
        out = [r for r in out if r["arrears_amount"] > 0 or r["status"] in ("hardship", "arrangement")]
    if bucket:
        out = [r for r in out if r["bucket"] == bucket]
    if status:
        out = [r for r in out if r["status"] == status]
    if q:
        out = [r for r in out if q.lower() in f"{r['number']} {r['applicant']} {r['lender'] or ''}".lower()]
    out.sort(key=lambda r: (-r["days_overdue"], -float(r["arrears_amount"])))
    summ = dict(loans=len(rows), in_arrears=len([r for r in rows if r["arrears_amount"] > 0]), arrears_total=q2(sum((r["arrears_amount"] for r in rows), ZERO)), hardship=len([r for r in rows if r["status"] == "hardship"]),
                arrangements=len([r for r in rows if r["status"] == "arrangement"]), broken_arrangements=len([r for r in rows if (r["arrangement"] or {}).get("compliance") == "behind"]), follow_ups_due=len([r for r in rows if r["follow_up_due"]]),
                promises=len([r for r in rows if r["status"] == "promise_to_pay"]))
    return dict(as_at=as_at, rows=out, buckets=[dict(bucket=k, loans=v["loans"], arrears=q2(v["arrears"]), balance=q2(v["balance"])) for k, v in buckets.items()], summary=summ,
                note="Days overdue are counted from the oldest instalment that is not fully paid. 'Current' includes loans that are paid up to date.")


def case(db, ctx, a: Access, loan_id: int, as_at: Optional[date] = None) -> Dict:
    a.require("view")
    x = LN._loan(db, ctx, loan_id)
    as_at = as_at or date.today()
    row = _row(db, ctx, x, as_at)
    acts = [dict(id=v.id, date=v.activity_date, kind=v.kind, outcome=v.outcome, notes=v.notes, next_action_date=v.next_action_date) for v in _activities(db, ctx, x.id)]
    arrs = [dict(id=v.id, start_date=v.start_date, end_date=v.end_date, amount_per_period=v.amount_per_period, frequency=v.frequency, arrears_at_start=v.arrears_at_start, status=v.status, notes=v.notes) for v in db.query(M.LendArrangement).filter_by(org_id=ctx.org.id, loan_id=x.id).order_by(M.LendArrangement.id.desc())]
    hs = [dict(id=v.id, requested_date=v.requested_date, reason=v.reason, status=v.status, relief=v.relief, outcome=v.outcome, review_date=v.review_date, arrangement_id=v.arrangement_id, decided_at=v.decided_at, allowed_next=list(HARDSHIP_FLOW[v.status]))
          for v in db.query(M.LendHardship).filter_by(org_id=ctx.org.id, loan_id=x.id).order_by(M.LendHardship.id.desc())]
    return dict(summary=row, activities=acts, arrangements=arrs, hardship=hs)


def log_activity(db, ctx, a: Access, loan_id: int, body: dict) -> Dict:
    a.require("collect")
    x = LN._loan(db, ctx, loan_id)
    d = parse_date(body.get("activity_date") or date.today(), "activity_date")
    if d > date.today():
        raise LendError("An activity cannot be dated in the future")
    nxt = parse_date(body.get("next_action_date"), "next_action_date", False)
    if nxt and nxt < d:
        raise LendError("The next action date cannot be before the activity date")
    for k in ("outcome", "notes"):
        no_tfn(body.get(k), k)
    v = M.LendCollectionActivity(org_id=ctx.org.id, loan_id=x.id, activity_date=d, kind=choice(body.get("kind"), M.COLLECTION_KINDS, "kind"), outcome=((body.get("outcome") or "")[:200] or None), notes=(body.get("notes") or None), next_action_date=nxt, created_by=ctx.user_id)
    if v.kind == "promise_to_pay" and not nxt:
        raise LendError("A promise to pay needs the date it was promised for (next action date)")
    db.add(v)
    db.flush()
    audit(db, ctx, "collections.activity", "lend_loan", x.id, kind=v.kind, outcome=v.outcome, next_action_date=nxt)
    return case(db, ctx, a, x.id)


def create_arrangement(db, ctx, a: Access, loan_id: int, body: dict) -> Dict:
    a.require("collect")
    x = LN._loan(db, ctx, loan_id)
    if x.status != "active":
        raise Conflict("Only an active loan can have a payment arrangement", "locked")
    pos = LN.position(db, ctx, x)
    if pos["arrears_amount"] <= 0:
        raise Conflict("This loan is not in arrears: there is nothing to arrange", "no_arrears")
    if _arrangement(db, ctx, x.id) is not None:
        raise Conflict("There is already an active arrangement on this loan: complete or cancel it first", "exists")
    amt = q2(num(body.get("amount_per_period"), "amount_per_period", required=True))
    if amt <= 0:
        raise LendError("The arrangement amount must be greater than zero")
    start = parse_date(body.get("start_date") or date.today(), "start_date")
    end = parse_date(body.get("end_date"), "end_date", False)
    if end and end <= start:
        raise LendError("The end date must be after the start date")
    no_tfn(body.get("notes"), "notes")
    v = M.LendArrangement(org_id=ctx.org.id, loan_id=x.id, start_date=start, end_date=end, amount_per_period=amt, frequency=choice(body.get("frequency"), M.FREQUENCIES, "frequency", default="fortnightly"),
                          arrears_at_start=pos["arrears_amount"], status="active", notes=(body.get("notes") or None), created_by=ctx.user_id)
    db.add(v)
    db.flush()
    db.add(M.LendCollectionActivity(org_id=ctx.org.id, loan_id=x.id, activity_date=date.today(), kind="note", outcome="Payment arrangement agreed", notes=f"{amt} {v.frequency} from {start}", created_by=ctx.user_id))
    audit(db, ctx, "collections.arrangement", "lend_loan", x.id, arrangement_id=v.id, amount=amt, frequency=v.frequency, arrears=pos["arrears_amount"])
    return case(db, ctx, a, x.id)


def close_arrangement(db, ctx, a: Access, loan_id: int, arrangement_id: int, status: str, notes: str = "") -> Dict:
    a.require("collect")
    x = LN._loan(db, ctx, loan_id)
    v = db.query(M.LendArrangement).filter_by(org_id=ctx.org.id, loan_id=x.id, id=arrangement_id).first()
    if v is None:
        raise NotFound("Arrangement")
    if v.status != "active":
        raise Conflict(f"That arrangement is already {v.status}", "closed")
    v.status = choice(status, ("completed", "broken", "cancelled"), "status")
    v.notes = ((v.notes + " | ") if v.notes else "") + notes if notes else v.notes
    db.flush()
    audit(db, ctx, "collections.arrangement_close", "lend_loan", x.id, arrangement_id=v.id, status=v.status, notes=notes)
    return case(db, ctx, a, x.id)


def request_hardship(db, ctx, a: Access, loan_id: int, body: dict) -> Dict:
    a.require("collect")
    x = LN._loan(db, ctx, loan_id)
    if x.status != "active":
        raise Conflict("Only an active loan can have a hardship case", "locked")
    if _open_hardship(db, ctx, x.id) is not None:
        raise Conflict("There is already an open hardship case on this loan", "exists")
    reason = (body.get("reason") or "").strip()
    if len(reason) < 5:
        raise LendError("Give the reason for the hardship request (at least five characters)")
    no_tfn(reason, "reason")
    v = M.LendHardship(org_id=ctx.org.id, loan_id=x.id, requested_date=parse_date(body.get("requested_date") or date.today(), "requested_date"), reason=reason[:300], status="requested", notes=(body.get("notes") or None), created_by=ctx.user_id)
    db.add(v)
    db.flush()
    db.add(M.LendCollectionActivity(org_id=ctx.org.id, loan_id=x.id, activity_date=date.today(), kind="note", outcome="Hardship requested", notes=reason[:300], created_by=ctx.user_id))
    audit(db, ctx, "collections.hardship_request", "lend_loan", x.id, hardship_id=v.id, reason=reason)
    return case(db, ctx, a, x.id)


def hardship_action(db, ctx, a: Access, loan_id: int, hardship_id: int, action: str, *, relief: str = "", outcome: str = "", review_date=None, arrangement_id: Optional[int] = None) -> Dict:
    """Move a hardship case along. Approving or declining needs the approve permission and an outcome (the reason); assessing and the later steps need the collect permission."""
    x = LN._loan(db, ctx, loan_id)
    v = db.query(M.LendHardship).filter_by(org_id=ctx.org.id, loan_id=x.id, id=hardship_id).first()
    if v is None:
        raise NotFound("Hardship case")
    action = choice(action, M.HARDSHIP_STATUSES, "action")
    if action not in HARDSHIP_FLOW[v.status]:
        raise Conflict(f"A hardship case that is {v.status} cannot become {action}. It can become: {', '.join(HARDSHIP_FLOW[v.status]) or 'nothing (it is final)'}.", "bad_transition")
    a.require("approve" if action in ("approved", "declined") else "collect")
    if action in ("approved", "declined") and len((outcome or "").strip()) < 5:
        raise LendError("A hardship decision needs an outcome of at least five characters: it is recorded with your name and the date")
    if action == "approved" and not (relief or "").strip():
        raise LendError("State the relief being given (for example reduced repayments, a pause or an extended term)")
    review = parse_date(review_date, "review_date", False) if review_date else None                      # validate EVERYTHING before changing anything
    if arrangement_id and db.query(M.LendArrangement).filter_by(org_id=ctx.org.id, loan_id=x.id, id=arrangement_id).first() is None:
        raise NotFound("Arrangement")
    prev = v.status
    v.status = action
    if relief:
        v.relief = relief[:60]
    if outcome:
        v.outcome = outcome.strip()
    if review:
        v.review_date = review
    if arrangement_id:
        v.arrangement_id = arrangement_id
    if action in ("approved", "declined"):
        v.decided_by, v.decided_at = ctx.user_id, __import__("datetime").datetime.utcnow()
    db.add(M.LendCollectionActivity(org_id=ctx.org.id, loan_id=x.id, activity_date=date.today(), kind="note", outcome=f"Hardship {action}", notes=(outcome or None), created_by=ctx.user_id))
    db.flush()
    audit(db, ctx, "collections.hardship", "lend_loan", x.id, hardship_id=v.id, from_status=prev, to_status=action, relief=v.relief, outcome=outcome)
    return case(db, ctx, a, x.id)
