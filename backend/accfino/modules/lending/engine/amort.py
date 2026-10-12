"""Loan engine: pure functions over a loan's terms and its repayments (no database).

Two views, both recomputed on demand so they can never drift:
  contractual_schedule(terms)        what the contract says if every instalment is paid on time
  replay(terms, repayments, as_at)   what has actually happened: balance, arrears, days overdue, next instalment

Conventions (state them to users): interest for a period is charged on the principal outstanding at the START of the period at the rate in force then; an instalment is interest first, then principal;
payments are applied to the OLDEST unpaid instalment first (interest then principal) and anything beyond what is due reduces principal; extra payments keep the instalment and shorten the term;
a rate change re-amortises the principal outstanding over the remaining instalments; a lease or hire purchase may carry a balloon (residual) paid with the last instalment."""
from dataclasses import dataclass, field
from datetime import date, timedelta
from decimal import Decimal as D, ROUND_HALF_UP
from typing import Dict, List, Optional, Sequence, Tuple

PPY = {"weekly": 52, "fortnightly": 26, "monthly": 12, "quarterly": 4}
ZERO = D("0")
CENT = D("0.01")
EPS = D("0.005")
BUCKETS = ("Current", "1-30", "31-60", "61-90", "90+")


def q2(v) -> D:
    return D(str(v)).quantize(CENT, ROUND_HALF_UP)


def add_months(d: date, n: int) -> date:
    y, m = divmod(d.year * 12 + d.month - 1 + n, 12)
    m += 1
    last = [31, 29 if (y % 4 == 0 and (y % 100 != 0 or y % 400 == 0)) else 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31][m - 1]
    return date(y, m, min(d.day, last))


def due_date(first_due: date, freq: str, k: int) -> date:
    """Due date of instalment k (1-based). Monthly and quarterly keep the day of the month (clamped at month end)."""
    if freq == "weekly":
        return first_due + timedelta(days=7 * (k - 1))
    if freq == "fortnightly":
        return first_due + timedelta(days=14 * (k - 1))
    if freq == "monthly":
        return add_months(first_due, k - 1)
    if freq == "quarterly":
        return add_months(first_due, 3 * (k - 1))
    raise ValueError(f"frequency must be one of {', '.join(PPY)}")


def pmt(principal: D, period_rate: D, n: int, balloon: D = ZERO) -> D:
    """Level instalment that repays `principal` over n periods leaving `balloon` at the end."""
    principal, balloon = D(principal), D(balloon)
    if n <= 0:
        return principal
    if period_rate == 0:
        return q2((principal - balloon) / n)
    f = (1 + period_rate) ** n
    return q2((principal - balloon / f) * period_rate / (1 - 1 / f))


@dataclass
class Terms:
    principal: D
    annual_rate: D                     # a fraction: 0.0625 is 6.25% a year
    term_periods: int                  # number of instalments
    frequency: str                     # weekly / fortnightly / monthly / quarterly
    start_date: date                   # drawdown / settlement
    first_due: date
    interest_only_periods: int = 0
    balloon: D = ZERO                  # residual / balloon paid with the last instalment (leases, hire purchase)
    rate_changes: Sequence[Tuple[date, D]] = field(default_factory=tuple)

    def validate(self):
        if D(self.principal) <= 0:
            raise ValueError("principal must be greater than zero")
        if D(self.annual_rate) < 0 or D(self.annual_rate) > D("0.5"):
            raise ValueError("annual_rate must be a fraction between 0 and 0.5 (6.25% is 0.0625)")
        if self.frequency not in PPY:
            raise ValueError(f"frequency must be one of {', '.join(PPY)}")
        if not (1 <= int(self.term_periods) <= 2000):
            raise ValueError("term_periods must be between 1 and 2000")
        if self.first_due < self.start_date:
            raise ValueError("the first instalment cannot fall before the start date")
        if not (0 <= int(self.interest_only_periods) < int(self.term_periods)):
            raise ValueError("interest_only_periods must be fewer than the number of instalments")
        if D(self.balloon) < 0 or D(self.balloon) >= D(self.principal):
            raise ValueError("the balloon / residual must be at least zero and less than the amount borrowed")
        return self


def rate_at(t: Terms, d: date) -> D:
    r = D(t.annual_rate)
    for eff, new in sorted(((e, D(v)) for e, v in t.rate_changes), key=lambda x: x[0]):
        if eff <= d:
            r = new
    return r


def _instalment(t: Terms, k: int, opening: D, pay: Optional[D], prev_rate: Optional[D], period_start: date) -> Tuple[D, D, D, D, D]:
    """-> (due, rate, interest, payment, principal_part) for instalment k on an opening principal. `pay` is the level instalment carried from before (None to compute)."""
    ppy = PPY[t.frequency]
    due = due_date(t.first_due, t.frequency, k)
    rate = rate_at(t, period_start)
    pr = rate / ppy
    interest = q2(opening * pr)
    remaining = int(t.term_periods) - k + 1
    io = k <= int(t.interest_only_periods)
    if io:
        payment = interest
    else:
        if pay is None or prev_rate is None or rate != prev_rate or k == int(t.interest_only_periods) + 1:
            pay = pmt(opening, pr, remaining, D(t.balloon))
        payment = pay
    if k >= int(t.term_periods) or opening + interest <= payment:
        payment = opening + interest                                       # the last instalment clears whatever is left (including the balloon)
    return due, rate, interest, payment, (payment - interest)


def contractual_schedule(t: Terms) -> List[Dict]:
    """Every instalment if all are paid on time: [{n, due, opening, rate, interest, principal, payment, closing}]."""
    t.validate()
    rows, bal, pay, prev_rate, start = [], q2(t.principal), None, None, t.start_date
    for k in range(1, int(t.term_periods) + 1):
        due, rate, interest, payment, principal = _instalment(t, k, bal, pay, prev_rate, start)
        if not (k <= int(t.interest_only_periods)):
            pay = payment if (k < int(t.term_periods) and bal + interest > payment) else pay
        prev_rate = rate
        closing = bal - principal
        rows.append(dict(n=k, due=due, opening=bal, rate=rate, interest=interest, principal=principal, payment=payment, closing=closing if closing > EPS else ZERO))
        bal, start = (closing if closing > EPS else ZERO), due
        if bal == 0:
            break
    return rows


def bucket_of(days_overdue: int) -> str:
    if days_overdue <= 0:
        return "Current"
    if days_overdue <= 30:
        return "1-30"
    if days_overdue <= 60:
        return "31-60"
    if days_overdue <= 90:
        return "61-90"
    return "90+"


def replay(t: Terms, repayments: Sequence[Tuple[date, D]], as_at: date) -> Dict:
    """The loan's ACTUAL position at `as_at` from the repayments received.

    repayments: [(date, amount)] or [(date, amount, ref)] in any order; those after as_at are ignored. `ref` (for example the repayment id) comes back on `allocations`.
    Returns balance (principal outstanding), arrears_amount (unpaid on instalments due BEFORE as_at), days_overdue (as_at less the due date of the oldest unpaid instalment), missed_count,
    bucket, next instalment, totals, and the instalments with what was paid against each."""
    t.validate()
    pays = sorted(((r[0], q2(r[1]), (r[2] if len(r) > 2 else None)) for r in repayments if r[0] <= as_at and q2(r[1]) > 0), key=lambda x: x[0])
    alloc = [dict(date=p[0], amount=p[1], ref=p[2], interest=ZERO, principal=ZERO, extra_principal=ZERO, overpaid=ZERO) for p in pays]      # how each repayment was actually applied
    pi = 0
    bal = q2(t.principal)
    insts: List[Dict] = []
    pay_amt, prev_rate, start = None, None, t.start_date
    total_paid = interest_paid = principal_paid = prepaid = overpaid = ZERO

    def apply(amount: D, idx: int) -> D:
        """Oldest unpaid instalment first, interest then principal. Returns what is left over."""
        nonlocal bal, interest_paid, principal_paid
        for it in insts:
            if amount <= 0:
                break
            ni = min(amount, it["interest_due"] - it["interest_paid"])
            if ni > 0:
                it["interest_paid"] += ni
                interest_paid += ni
                alloc[idx]["interest"] += ni
                amount -= ni
            npr = min(amount, it["principal_due"] - it["principal_paid"])
            if npr > 0:
                it["principal_paid"] += npr
                principal_paid += npr
                alloc[idx]["principal"] += npr
                bal -= npr
                amount -= npr
        return amount

    def unpaid() -> D:
        return sum((it["interest_due"] - it["interest_paid"] + it["principal_due"] - it["principal_paid"] for it in insts), ZERO)

    nxt = None
    for k in range(1, int(t.term_periods) + 1):
        if bal <= EPS and unpaid() <= EPS:
            break
        due, rate, interest, payment, principal = _instalment(t, k, bal, pay_amt, prev_rate, start)
        if not (k <= int(t.interest_only_periods)):
            pay_amt = payment if (k < int(t.term_periods) and bal + interest > payment) else pay_amt
        prev_rate = rate
        if due > as_at:
            nxt = dict(n=k, due=due, amount=payment, interest=interest, principal=principal, rate=rate)
            break
        insts.append(dict(n=k, due=due, rate=rate, interest_due=interest, principal_due=principal, interest_paid=ZERO, principal_paid=ZERO))
        while pi < len(pays) and pays[pi][0] <= due:                        # money received up to this due date goes to what is owed, oldest first
            left = apply(pays[pi][1], pi)
            total_paid += pays[pi][1]
            if left > 0:
                cut = min(left, bal)                                         # more than was owed: it reduces principal now
                bal -= cut
                prepaid += cut
                overpaid += left - cut
                alloc[pi]["extra_principal"] += cut
                alloc[pi]["overpaid"] += left - cut
            pi += 1
        start = due
    while pi < len(pays):                                                    # received after the last instalment that has fallen due
        left = apply(pays[pi][1], pi)
        total_paid += pays[pi][1]
        if left > 0:
            cut = min(left, bal)
            bal -= cut
            prepaid += cut
            overpaid += left - cut
            alloc[pi]["extra_principal"] += cut
            alloc[pi]["overpaid"] += left - cut
        pi += 1
    if nxt is None and bal > EPS:                                            # the next instalment after the last processed one
        k = len(insts) + 1
        if k <= int(t.term_periods):
            due, rate, interest, payment, principal = _instalment(t, k, bal, pay_amt, prev_rate, start)
            nxt = dict(n=k, due=due, amount=payment, interest=interest, principal=principal, rate=rate)
    overdue = [it for it in insts if (it["interest_due"] - it["interest_paid"] + it["principal_due"] - it["principal_paid"]) > EPS and it["due"] < as_at]
    arrears = sum((it["interest_due"] - it["interest_paid"] + it["principal_due"] - it["principal_paid"] for it in overdue), ZERO)
    due_today = sum((it["interest_due"] - it["interest_paid"] + it["principal_due"] - it["principal_paid"] for it in insts if it["due"] == as_at), ZERO)
    days = (as_at - min(it["due"] for it in overdue)).days if overdue else 0
    last_due = insts[-1]["due"] if insts else t.start_date
    accrued = q2(bal * rate_at(t, last_due) * (as_at - last_due).days / 365) if bal > EPS and as_at > last_due else ZERO
    unpaid_interest = sum((it["interest_due"] - it["interest_paid"] for it in insts), ZERO)
    paid_out = bal <= EPS and unpaid() <= EPS
    matured_unpaid = len(insts) >= int(t.term_periods) and (bal > EPS or unpaid() > EPS)
    status = "paid_out" if paid_out else ("matured_unpaid" if matured_unpaid else ("arrears" if arrears > EPS else "current"))
    for it in insts:
        owed = it["interest_due"] + it["principal_due"]
        paid = it["interest_paid"] + it["principal_paid"]
        it["status"] = "paid" if owed - paid <= EPS else ("part" if paid > EPS else "unpaid")
    return dict(as_at=as_at, balance=q2(bal if bal > EPS else ZERO), arrears_amount=q2(arrears), amount_due_today=q2(due_today), days_overdue=days, missed_count=len(overdue), bucket=bucket_of(days), status=status,
                next=None if (paid_out or nxt is None) else {**nxt, "amount": q2(nxt["amount"]), "interest": q2(nxt["interest"]), "principal": q2(nxt["principal"])},
                allocations=[dict(a, amount=q2(a["amount"]), interest=q2(a["interest"]), principal=q2(a["principal"]), extra_principal=q2(a["extra_principal"]), overpaid=q2(a["overpaid"])) for a in alloc],
                total_paid=q2(total_paid), interest_paid=q2(interest_paid), principal_paid=q2(principal_paid), prepaid=q2(prepaid), overpaid=q2(overpaid),
                payout_estimate=q2((bal if bal > EPS else ZERO) + unpaid_interest + accrued) if not paid_out else ZERO, accrued_interest=accrued,
                instalments=[{**it, "interest_due": q2(it["interest_due"]), "principal_due": q2(it["principal_due"]), "interest_paid": q2(it["interest_paid"]), "principal_paid": q2(it["principal_paid"])} for it in insts])


def totals(schedule: List[Dict]) -> Dict:
    return dict(instalments=len(schedule), total_interest=q2(sum((r["interest"] for r in schedule), ZERO)), total_paid=q2(sum((r["payment"] for r in schedule), ZERO)), first_payment=schedule[0]["payment"] if schedule else ZERO,
                final_due=schedule[-1]["due"] if schedule else None)
