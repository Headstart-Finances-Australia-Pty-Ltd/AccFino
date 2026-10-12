"""Applicant Financial Summary from CLASSIFIED statement lines (the existing classifier's output): month-by-month trend, recurring income and commitments, unusual transactions and conduct events.
Pure functions. Money in, money out: Income -> Expenses -> Existing commitments -> Surplus."""
import re
import statistics
import calendar
from collections import defaultdict
from datetime import date, datetime
from typing import Dict, List, Optional

FORMATS = ("%Y-%m-%d", "%d/%m/%Y", "%d/%m/%y", "%d-%m-%Y", "%d %b %Y", "%d %B %Y", "%d %b %y", "%Y/%m/%d")
_DISHONOUR_RE = re.compile(r"DISHONOU?R|\bOVERDRAWN\b|OVERDRAFT FEE|\bNSF\b|UNPAID ITEM|INSUFFICIENT FUNDS|REFERRED TO DRAWER|ARREARS FEE|LATE FEE|LATE PAYMENT")   # word boundaries: "NSF" must not match inside "TRANSFER"
_CASH_RE = re.compile(r"\bATM\b|CASH WITHDRAWAL|CASH OUT|CASHOUT")


def is_dishonour(desc) -> bool:
    return bool(_DISHONOUR_RE.search(str(desc or "").upper()))


def is_cash(desc) -> bool:
    return bool(_CASH_RE.search(str(desc or "").upper()))
LOAN_GROUPS = ("loans_debt",)


def to_date(s) -> Optional[date]:
    if isinstance(s, datetime):
        return s.date()
    if isinstance(s, date):
        return s
    s = str(s or "").strip()[:20]
    for f in FORMATS:
        try:
            return datetime.strptime(s, f).date()
        except ValueError:
            continue
    return None


def norm_desc(s: str) -> str:
    """A description with the changing parts (dates, reference numbers, card digits) removed, so the same payee groups together."""
    s = str(s or "").upper()
    s = re.sub(r"\b\d{1,2}[/-]\d{1,2}([/-]\d{2,4})?\b", " ", s)
    s = re.sub(r"[0-9X*#]{3,}", " ", s)
    s = re.sub(r"[^A-Z& ]", " ", s)
    return " ".join(s.split()[:4])


def _amt(l: Dict) -> float:
    return abs(float(l.get("amount") or 0)) or max(float(l.get("debit") or 0), float(l.get("credit") or 0))


def _is_credit(l: Dict) -> bool:
    return not l.get("is_debit", float(l.get("debit") or 0) > 0)


def prepare(lines: List[Dict]) -> List[Dict]:
    out = []
    for l in lines:
        d = to_date(l.get("date"))
        if d is None:
            continue
        out.append(dict(l, _d=d, _amt=_amt(l), _credit=_is_credit(l), _key=norm_desc(l.get("description")), _ym=f"{d.year}-{d.month:02d}", _group=l.get("hem_group") or "other"))
    return out


def monthly_series(P: List[Dict]) -> List[Dict]:
    """Income, spending and net by calendar month. Transfers between the applicant's own accounts are left out of both sides."""
    by = defaultdict(lambda: dict(income=0.0, spending=0.0, count=0, first=None, last=None))
    for l in P:
        m = by[l["_ym"]]
        m["count"] += 1
        m["first"] = l["_d"] if m["first"] is None or l["_d"] < m["first"] else m["first"]
        m["last"] = l["_d"] if m["last"] is None or l["_d"] > m["last"] else m["last"]
        if l["_group"] == "transfers":
            continue
        if l["_credit"]:
            m["income"] += l["_amt"]
        else:
            m["spending"] += l["_amt"]
    return [dict(month=k, income=round(v["income"], 2), spending=round(v["spending"], 2), net=round(v["income"] - v["spending"], 2), transactions=v["count"], first=v["first"].isoformat(), last=v["last"].isoformat()) for k, v in sorted(by.items())]


def _complete(m: Dict) -> bool:
    """A month with transactions from near its start to near its end (a statement that begins or ends mid-month gives a partial first or last month)."""
    try:
        first, last = date.fromisoformat(str(m["first"])), date.fromisoformat(str(m["last"]))
    except (KeyError, ValueError, TypeError):
        return True
    return first.day <= 7 and last.day >= calendar.monthrange(last.year, last.month)[1] - 7


def trend(series: List[Dict], recurring_share=None) -> Dict:
    """Direction of income and spending.
    - If most income demonstrably RECURS (share given and 70%+), income is reported as steady recurring pay: fortnightly pay puts two or three pays in a month, so comparing single months would call steady pay 'falling'.
    - With four or more complete months, the first half is compared with the second half (income within 20% is steady, spending within 15%).
    - Otherwise (a short statement) the first and last months are compared, and the note says it is only indicative."""
    note = "A month with three pay dates looks higher than one with two, and a statement that starts or ends mid-month has partial months at either end, so one month is not a trend."
    if len(series) < 2:
        return dict(income="not enough months", spending="not enough months", note="At least two months are needed to see a trend.")

    def dirn(x, y, tol):
        if x <= 0:
            return "n/a"
        ch = (y - x) / x
        return "steady" if abs(ch) < tol else (("rising" if ch > 0 else "falling") + f" ({ch * 100:+.0f}%)")
    full = [m for m in series if _complete(m)]
    if len(full) >= 4:
        h = len(full) // 2
        avg = lambda ms, k: sum(m[k] for m in ms) / len(ms)
        inc = dirn(avg(full[:h], "income"), avg(full[-h:], "income"), 0.20)
        spd = dirn(avg(full[:h], "spending"), avg(full[-h:], "spending"), 0.15)
        basis = f"first {h} against last {h} complete months"
        frm, to = full[0]["month"], full[-1]["month"]
    else:
        a, b = series[0], series[-1]
        inc, spd, basis, frm, to = dirn(a["income"], b["income"], 0.05), dirn(a["spending"], b["spending"], 0.05), "first month against last month: indicative only", a["month"], b["month"]
    if recurring_share is not None and recurring_share >= 0.7:
        inc = "steady (recurring pay)"
    return dict(income=inc, spending=spd, from_month=frm, to_month=to, basis=basis, note=note)


def recurring(P: List[Dict], credit: bool) -> List[Dict]:
    groups = defaultdict(list)
    for l in P:
        if l["_credit"] == credit and l["_group"] != "transfers" and l["_key"]:
            groups[l["_key"]].append(l)
    out = []
    for key, ls in groups.items():
        months = {l["_ym"] for l in ls}
        if len(months) < 2:
            continue
        amts = [l["_amt"] for l in ls]
        med = statistics.median(amts)
        stable = [a for a in amts if med > 0 and abs(a - med) <= 0.25 * med]
        if len(stable) < max(2, 0.7 * len(amts)):
            continue
        ds = sorted(l["_d"] for l in ls)
        gaps = [(ds[i + 1] - ds[i]).days for i in range(len(ds) - 1) if (ds[i + 1] - ds[i]).days > 0]
        gap = statistics.median(gaps) if gaps else 30
        freq, mult = ("weekly", 52 / 12) if gap <= 9 else ("fortnightly", 26 / 12) if gap <= 18 else ("monthly", 1.0) if gap <= 40 else ("irregular", 1.0)
        cats = [l.get("category") for l in ls if l.get("category")]
        out.append(dict(label=key.title(), category=max(set(cats), key=cats.count) if cats else None, group=ls[0]["_group"], amount=round(med, 2), occurrences=len(ls), months=len(months), frequency=freq,
                        monthly_equivalent=round(med * mult, 2), last_date=ds[-1].isoformat()))
    return sorted(out, key=lambda r: -r["monthly_equivalent"])


def unusual(P: List[Dict], regular_income_monthly: float = 0.0, recurring_keys: Optional[set] = None) -> List[Dict]:
    keys = recurring_keys or set()
    debits = [l["_amt"] for l in P if not l["_credit"] and l["_group"] != "transfers"]
    med = statistics.median(debits) if debits else 0.0
    big_debit = max(1000.0, 3 * med)
    big_credit = max(2000.0, regular_income_monthly)                          # a one-off deposit as large as a whole month of regular income is worth asking about
    out = []
    for l in sorted(P, key=lambda x: x["_d"]):
        desc, a, base = l.get("description", ""), l["_amt"], dict(date=l["_d"].isoformat(), description=str(l.get("description", ""))[:80], amount=round(l["_amt"], 2))
        up = str(desc).upper()
        if is_dishonour(desc):
            out.append(dict(base, kind="dishonour", reason="A dishonour, overdrawn or late-payment fee: check the conduct of the account."))
        elif l["_group"] == "gambling":
            out.append(dict(base, kind="gambling", reason="Gambling transaction."))
        elif not l["_credit"] and (l["_group"] == "cash" or is_cash(desc)) and a >= 500:
            out.append(dict(base, kind="cash_withdrawal", reason=f"Cash withdrawal of {a:,.0f}: ask what it was for."))
        elif l["_credit"] and l["_group"] != "transfers" and l["_key"] not in keys and a >= big_credit:
            out.append(dict(base, kind="unexplained_deposit", reason=f"A one-off deposit of {a:,.0f} that is not regular income: ask for the source."))
        elif not l["_credit"] and l["_group"] != "transfers" and l["_key"] not in keys and a >= big_debit:
            out.append(dict(base, kind="large_payment", reason=f"A payment of {a:,.0f}, well above this account's usual spending: ask what it was for."))
    return out[:25]


def conduct(P: List[Dict]) -> Dict:
    dis = [l for l in P if is_dishonour(l.get("description"))]
    overdrawn_days = len({l["_d"] for l in P if l.get("balance") is not None and _num(l.get("balance")) < 0})
    return dict(dishonours=len(dis), overdrawn_days=overdrawn_days, events=len(dis) + (1 if overdrawn_days else 0))


def _num(v) -> float:
    try:
        return float(v)
    except (TypeError, ValueError):
        return 0.0


def build(classified: List[Dict], metrics: Dict) -> Dict:
    P = prepare(classified)
    series = monthly_series(P)
    inc, exp = recurring(P, True), recurring(P, False)
    commitments = [r for r in exp if r["group"] in LOAN_GROUPS or (r["category"] or "") in ("Loans", "Interest Payment", "Credit Card Payment")]
    m = metrics or {}
    rec_month = round(sum(x["monthly_equivalent"] for x in inc), 2)                       # income that genuinely RECURS (the classifier's own "regular" flag also counts one-off deposits)
    income = float(m.get("total_income_monthly") or 0)
    existing = float(m.get("loans_monthly") or 0) + float(m.get("credit_card_monthly") or 0)
    spending = float(m.get("total_expenses_monthly") or 0)
    return dict(
        statement=dict(from_date=min((l["_d"] for l in P), default=None) and min(l["_d"] for l in P).isoformat(), to_date=max((l["_d"] for l in P), default=None) and max(l["_d"] for l in P).isoformat(),
                       transactions=len(P), skipped_undated=len(classified) - len(P), months=len(series)),
        headline=dict(income_monthly=round(income, 2), recurring_income_monthly=rec_month, non_recurring_income_monthly=round(max(0.0, income - rec_month), 2), income_verified_pct=round(min(100.0, rec_month / income * 100), 0) if income > 0 else None,
                      expenses_monthly=round(max(0.0, spending - existing), 2), existing_commitments_monthly=round(existing, 2), surplus_monthly=round(float(m.get("umi") or 0), 2)),
        months=series, trend=trend(series, round(min(100.0, rec_month / income * 100) / 100, 4) if income > 0 else None), recurring_income=inc, recurring_commitments=commitments, recurring_other=[r for r in exp if r not in commitments][:15],
        unusual=unusual(P, rec_month if rec_month > 0 else float(m.get("regular_income_monthly") or 0), {r["label"].upper() for r in inc + exp}), conduct=conduct(P))
