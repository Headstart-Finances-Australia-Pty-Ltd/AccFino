"""
A6+ - the remaining Books & Accounting reports. Like reports.py, everything here is derived ONLY from the posted
ledger (journals) and the sub-ledger tables (documents, payments, bank lines, claims, stock, assets, budgets) -
never from the legacy single-user tables - and every report carries its own reconciliation check where one exists.

  gl_summary(...)            opening / debits / credits / closing for every account in a period
  journal_report(...)        every journal posted in a period, with lines, filterable by source / account
  cash_summary(...)          cash received and paid by category over the bank accounts, by month, reconciled to the bank movement
  account_summary(...)       month-by-month in / out / closing for every bank and credit-card account
  cash_validation(...)       duplicate, stale and unusual cash items an accountant would want to look at before a BAS
  expense_claims_report(...) claims by status, claimant and category
  payg_summary(...)          PAYG withholding (BAS W1 / W2), super and wages payable from the payroll journals
  management_report(...)     P&L (with comparative), balance sheet, aged totals, cash, GST, KPIs, trend - one pack
  budget_variance(...)       actual vs budget for income and expenses (+ get/save/generate budget)
  inventory_item_details(...) per-item quantities and values with movements, reconciled to the inventory ledger accounts
"""
from collections import defaultdict
from datetime import date, timedelta
from decimal import Decimal
from statistics import mean, pstdev

from sqlalchemy import func
from sqlalchemy.orm import selectinload

from accfino_core import models as m
from accfino_core.books import models as b
from accfino_core.books import reports as R
from accfino_core.books.common import BooksError, get_account, money
from accfino_core.inventory import models as inv
from accfino_core.ledger import service as L

Z = Decimal("0.00")
PL_CLASSES = ("revenue", "expense")
TYPE_ORDER = ("bank", "current_asset", "inventory", "fixed_asset", "non_current_asset", "credit_card", "current_liability",
              "non_current_liability", "equity", "revenue", "other_income", "direct_costs", "expense", "other_expense")
TYPE_LABEL = {"bank": "Bank", "current_asset": "Current Assets", "inventory": "Inventory", "fixed_asset": "Fixed Assets",
              "non_current_asset": "Non-current Assets", "credit_card": "Credit Cards", "current_liability": "Current Liabilities",
              "non_current_liability": "Non-current Liabilities", "equity": "Equity", "revenue": "Revenue", "other_income": "Other Income",
              "direct_costs": "Cost of Sales", "expense": "Operating Expenses", "other_expense": "Other Expenses"}


# ------------------------------------------------------------------------------------------------ helpers --
def _day_before(d):
    return d - timedelta(days=1)


def _month_start(d):
    return date(d.year, d.month, 1)


def _next_month(d):
    return date(d.year + (d.month == 12), d.month % 12 + 1, 1)


def _months(date_from, date_to):
    out, d = [], _month_start(date_from)
    while d <= date_to:
        out.append(d)
        d = _next_month(d)
    return out


def _natural(a, dr, cr):
    """Balance in the account's natural sign (assets / expenses are debit-normal)."""
    return (dr - cr) if a.account_class in ("asset", "expense") else (cr - dr)


def _check_range(date_from, date_to):
    if date_from > date_to:
        raise BooksError("The 'from' date is after the 'to' date")


def _accs(db, org):
    return {a.id: a for a in db.query(m.LedgerAccount).filter(m.LedgerAccount.org_id == org.id)}


def _by_key(accs, key):
    return next((a for a in accs.values() if a.system_key == key), None)


def _by_code(accs, code):
    return next((a for a in accs.values() if a.code == code), None)


def _bal_asat(db, org, upto, account_ids=None):
    """{account_id: debit - credit} for everything posted on or before `upto`."""
    q = db.query(m.JournalLine.account_id, func.coalesce(func.sum(m.JournalLine.debit - m.JournalLine.credit), 0)) \
        .join(m.Journal, m.Journal.id == m.JournalLine.journal_id).filter(m.JournalLine.org_id == org.id, m.Journal.journal_date <= upto)
    if account_ids is not None:
        q = q.filter(m.JournalLine.account_id.in_(list(account_ids)))
    return {a: money(v) for a, v in q.group_by(m.JournalLine.account_id).all()}


def _s(x):
    return str(x)


# ------------------------------------------------------------------------------------------------ GL summary --
def gl_summary(db, org, date_from, date_to):
    """Opening, debits, credits and closing per account. Balance-sheet accounts open at their cumulative balance; profit & loss
    accounts open at their balance since the start of the financial year that contains `date_from` (earlier years have rolled into
    retained earnings), which is how Xero / MYOB present it."""
    _check_range(date_from, date_to)
    accs = _accs(db, org)
    fy = L._fy_start(org, date_from)
    open_bs = L._sums(db, org, date_to=_day_before(date_from))
    open_pl = L._sums(db, org, date_from=fy, date_to=_day_before(date_from)) if fy < date_from else {}
    move = L._sums(db, org, date_from, date_to)
    ids = set(open_bs) | set(move)
    rows, td, tc = [], Z, Z
    for aid in ids:
        a = accs[aid]
        o = (open_pl if a.account_class in PL_CLASSES else open_bs).get(aid, (Z, Z))
        d, c = move.get(aid, (Z, Z))
        opening, closing = _natural(a, *o), _natural(a, o[0] + d, o[1] + c)
        if opening == 0 and d == 0 and c == 0 and closing == 0:
            continue
        td, tc = td + d, tc + c
        rows.append(dict(account_id=a.id, code=a.code, name=a.name, type=a.account_type, group=TYPE_LABEL.get(a.account_type, a.account_type),
                         account_class=a.account_class, opening=_s(opening), debit=_s(d), credit=_s(c), closing=_s(closing), movement=_s(closing - opening)))
    rows.sort(key=lambda r: (TYPE_ORDER.index(r["type"]) if r["type"] in TYPE_ORDER else 99, r["code"]))
    groups = []
    for t in TYPE_ORDER:
        rs = [r for r in rows if r["type"] == t]
        if rs:
            groups.append(dict(type=t, label=TYPE_LABEL[t], count=len(rs), debit=_s(sum((Decimal(r["debit"]) for r in rs), Z)),
                               credit=_s(sum((Decimal(r["credit"]) for r in rs), Z)), closing=_s(sum((Decimal(r["closing"]) for r in rs), Z))))
    return dict(date_from=date_from.isoformat(), date_to=date_to.isoformat(), financial_year_start=fy.isoformat(), rows=rows, groups=groups,
                total_debit=_s(td), total_credit=_s(tc), balanced=(td == tc), accounts=len(rows),
                note="Profit & loss accounts open at their balance since the start of the financial year; earlier years are in retained earnings.")


# ------------------------------------------------------------------------------------------------ journal report --
def journal_report(db, org, date_from, date_to, *, source_type=None, account_id=None, include_reversed=True, limit=500):
    _check_range(date_from, date_to)
    limit = max(1, min(int(limit or 500), 2000))
    q = db.query(m.Journal).options(selectinload(m.Journal.lines).selectinload(m.JournalLine.account), selectinload(m.Journal.lines).selectinload(m.JournalLine.tax_code)) \
        .filter(m.Journal.org_id == org.id, m.Journal.journal_date.between(date_from, date_to))
    if source_type:
        q = q.filter(m.Journal.source_type == source_type)
    if not include_reversed:
        q = q.filter(m.Journal.status == "posted", m.Journal.reversal_of_id.is_(None))
    if account_id:
        q = q.filter(m.Journal.id.in_(db.query(m.JournalLine.journal_id).filter(m.JournalLine.org_id == org.id, m.JournalLine.account_id == int(account_id))))
    total = q.count()
    js = q.order_by(m.Journal.journal_date, m.Journal.journal_no).limit(limit).all()
    out, td, tc, by_src = [], Z, Z, defaultdict(lambda: dict(count=0, total=Z))
    for j in js:
        d = sum((l.debit for l in j.lines), Z)
        c = sum((l.credit for l in j.lines), Z)
        td, tc = td + d, tc + c
        by_src[j.source_type]["count"] += 1
        by_src[j.source_type]["total"] += j.total
        out.append(dict(id=j.id, journal_no=j.journal_no, date=j.journal_date.isoformat(), narration=j.narration, source_type=j.source_type,
                        source_ref=j.source_ref, status=j.status, reversal_of_id=j.reversal_of_id, total=_s(j.total), balanced=(d == c),
                        lines=[dict(line_no=l.line_no, account_code=l.account.code if l.account else None, account_name=l.account.name if l.account else None,
                                    description=l.description, debit=_s(l.debit), credit=_s(l.credit), tax_code=l.tax_code.code if l.tax_code else None,
                                    tax_amount=_s(l.tax_amount), contact=l.contact_name) for l in j.lines]))
    sources = sorted(r[0] for r in db.query(m.Journal.source_type).filter(m.Journal.org_id == org.id).distinct())
    return dict(date_from=date_from.isoformat(), date_to=date_to.isoformat(), journals=out, count=len(out), total_count=total, truncated=total > len(out),
                total_debit=_s(td), total_credit=_s(tc), balanced=(td == tc), sources=sources,
                by_source={k: dict(count=v["count"], total=_s(v["total"])) for k, v in sorted(by_src.items())})


# ------------------------------------------------------------------------------------------------ cash summary --
def _section_of(a):
    k = a.system_key
    if k == "ar_control":
        return "Customers"
    if k == "ap_control":
        return "Suppliers"
    if k == "gst":
        return "GST"
    if k in ("wages_payable", "payg_withholding", "super_payable", "expense_claims"):
        return "Payroll, PAYG, super & claims"
    if a.account_class == "revenue":
        return "Income received directly"
    if a.account_class == "expense":
        return "Expenses paid directly"
    if a.account_type in ("fixed_asset", "non_current_asset"):
        return "Asset purchases & sales"
    if a.account_class == "asset":
        return "Other assets"
    if a.account_class == "equity":
        return "Owner / equity"
    return "Loans, credit cards & other liabilities"


SECTION_ORDER = ("Customers", "Suppliers", "Income received directly", "Expenses paid directly", "Payroll, PAYG, super & claims", "GST",
                 "Asset purchases & sales", "Other assets", "Loans, credit cards & other liabilities", "Owner / equity")


def _bank_movements(db, org, date_from, date_to, bank_ids):
    """Yield (journal_date, counter_account, signed_cash_effect) - the cash effect attributed to each non-bank line of every journal that touches a bank account.
    A journal balances, so the signed effects of its non-bank lines add up to the net bank movement; bank-to-bank transfers therefore net to zero and drop out."""
    jids = db.query(m.JournalLine.journal_id).filter(m.JournalLine.org_id == org.id, m.JournalLine.account_id.in_(list(bank_ids)))
    q = db.query(m.JournalLine, m.Journal).join(m.Journal, m.Journal.id == m.JournalLine.journal_id) \
        .filter(m.JournalLine.org_id == org.id, m.Journal.journal_date.between(date_from, date_to), m.Journal.id.in_(jids),
                ~m.JournalLine.account_id.in_(list(bank_ids)))
    for jl, j in q:
        yield j.journal_date, jl.account_id, jl.credit - jl.debit


def cash_summary(db, org, date_from, date_to):
    _check_range(date_from, date_to)
    accs = _accs(db, org)
    bank_ids = [i for i, a in accs.items() if a.account_type == "bank"]
    if not bank_ids:
        return dict(date_from=date_from.isoformat(), date_to=date_to.isoformat(), has_bank=False, sections=[], months=[], opening_cash=_s(Z), closing_cash=_s(Z),
                    total_receipts=_s(Z), total_payments=_s(Z), net_movement=_s(Z), reconciled=True, difference=_s(Z))
    b0, b1 = _bal_asat(db, org, _day_before(date_from), bank_ids), _bal_asat(db, org, date_to, bank_ids)
    opening, closing = sum(b0.values(), Z), sum(b1.values(), Z)
    by_acc, months = defaultdict(lambda: dict(receipts=Z, payments=Z)), defaultdict(lambda: dict(receipts=Z, payments=Z))
    for jd, aid, eff in _bank_movements(db, org, date_from, date_to, bank_ids):
        key = "receipts" if eff > 0 else "payments"
        by_acc[aid][key] += abs(eff)
        months[_month_start(jd)][key] += abs(eff)
    sections = defaultdict(list)
    for aid, v in by_acc.items():
        a = accs[aid]
        sections[_section_of(a)].append(dict(account_id=a.id, code=a.code, name=a.name, receipts=_s(v["receipts"]), payments=_s(v["payments"]),
                                             net=_s(v["receipts"] - v["payments"])))
    sec_out, tr, tp = [], Z, Z
    for name in SECTION_ORDER:
        rs = sorted(sections.get(name, []), key=lambda r: r["code"])
        if not rs:
            continue
        r_ = sum((Decimal(x["receipts"]) for x in rs), Z)
        p_ = sum((Decimal(x["payments"]) for x in rs), Z)
        tr, tp = tr + r_, tp + p_
        sec_out.append(dict(section=name, receipts=_s(r_), payments=_s(p_), net=_s(r_ - p_), rows=rs))
    run, mrows = opening, []
    for ms in _months(date_from, date_to):
        v = months.get(ms, dict(receipts=Z, payments=Z))
        run += v["receipts"] - v["payments"]
        mrows.append(dict(month=ms.strftime("%Y-%m"), receipts=_s(v["receipts"]), payments=_s(v["payments"]), net=_s(v["receipts"] - v["payments"]), closing=_s(run)))
    net = tr - tp
    return dict(date_from=date_from.isoformat(), date_to=date_to.isoformat(), has_bank=True, sections=sec_out, months=mrows, opening_cash=_s(opening),
                closing_cash=_s(closing), total_receipts=_s(tr), total_payments=_s(tp), net_movement=_s(net), reconciled=(opening + net == closing),
                difference=_s(closing - opening - net), bank_accounts=[dict(code=accs[i].code, name=accs[i].name, opening=_s(b0.get(i, Z)), closing=_s(b1.get(i, Z))) for i in sorted(bank_ids, key=lambda x: accs[x].code)],
                note="Cash = bank accounts. Transfers between your own bank accounts net to zero and are not shown.")


# ------------------------------------------------------------------------------------------------ account summary --
def account_summary(db, org, date_from, date_to):
    _check_range(date_from, date_to)
    accs = [a for a in _accs(db, org).values() if a.account_type in ("bank", "credit_card") and a.is_active]
    accs.sort(key=lambda a: a.code)
    ms = _months(date_from, date_to)
    ids = [a.id for a in accs]
    opening = _bal_asat(db, org, _day_before(date_from), ids) if ids else {}
    grid = defaultdict(lambda: defaultdict(lambda: dict(inflow=Z, outflow=Z)))
    if ids:
        for jl, j in db.query(m.JournalLine, m.Journal).join(m.Journal, m.Journal.id == m.JournalLine.journal_id) \
                .filter(m.JournalLine.org_id == org.id, m.JournalLine.account_id.in_(ids), m.Journal.journal_date.between(date_from, date_to)):
            cell = grid[jl.account_id][_month_start(j.journal_date)]
            cell["inflow"] += jl.debit
            cell["outflow"] += jl.credit
    out = []
    for a in accs:
        sign = Decimal(1) if a.account_type == "bank" else Decimal(-1)          # a credit card balance is shown as the amount owing
        bal = sign * opening.get(a.id, Z)
        rows, tin, tout = [], Z, Z
        for mth in ms:
            c = grid[a.id][mth] if a.id in grid and mth in grid[a.id] else dict(inflow=Z, outflow=Z)
            i_, o_ = (c["inflow"], c["outflow"]) if a.account_type == "bank" else (c["outflow"], c["inflow"])
            bal += i_ - o_
            tin, tout = tin + i_, tout + o_
            rows.append(dict(month=mth.strftime("%Y-%m"), inflow=_s(i_), outflow=_s(o_), closing=_s(bal)))
        unrec = db.query(func.count(b.BankLine.id)).filter_by(org_id=org.id, bank_account_id=a.id, status="unreconciled").scalar()
        last = db.query(func.max(b.BankLine.line_date)).filter_by(org_id=org.id, bank_account_id=a.id).scalar()
        out.append(dict(account_id=a.id, code=a.code, name=a.name, type=a.account_type, bank_name=a.bank_name, opening=_s(sign * opening.get(a.id, Z)),
                        total_in=_s(tin), total_out=_s(tout), closing=_s(bal), months=rows, unreconciled_lines=unrec,
                        last_statement_date=last.isoformat() if last else None))
    return dict(date_from=date_from.isoformat(), date_to=date_to.isoformat(), months=[x.strftime("%Y-%m") for x in ms], accounts=out,
                totals=dict(opening=_s(sum((Decimal(x["opening"]) for x in out if x["type"] == "bank"), Z)),
                            closing=_s(sum((Decimal(x["closing"]) for x in out if x["type"] == "bank"), Z))),
                note="Bank accounts show money in / out; credit cards show spend / repayments and the closing amount owing.")


# ------------------------------------------------------------------------------------------------ cash validation --
def _item_cap(items, cap=100):
    return items[:cap]


def cash_validation(db, org, date_from, date_to):
    """Everything here is a prompt to look, not proof of an error; each check says what it looked for and why it matters."""
    _check_range(date_from, date_to)
    accs = _accs(db, org)
    checks = []

    def add(key, title, severity, why, items):
        checks.append(dict(key=key, title=title, severity=severity, why=why, count=len(items), items=_item_cap(items), truncated=len(items) > 100))

    # 1. identical bank lines (same account, date, amount and description) - a statement imported twice, or a double-keyed line
    groups = defaultdict(list)
    for l in db.query(b.BankLine).filter(b.BankLine.org_id == org.id, b.BankLine.line_date.between(date_from, date_to), b.BankLine.status != "excluded"):
        groups[(l.bank_account_id, l.line_date, l.amount, l.description.strip().lower())].append(l)
    add("duplicate_bank_lines", "Identical bank statement lines", "high", "Same account, date, amount and description more than once - a statement imported twice or a genuine repeat that needs confirming.",
        [dict(date=k[1].isoformat(), account=accs[k[0]].code + " " + accs[k[0]].name if k[0] in accs else str(k[0]), description=v[0].description, amount=_s(k[2]), occurrences=len(v),
              statuses=sorted({x.status for x in v})) for k, v in sorted(groups.items(), key=lambda kv: kv[0][1]) if len(v) > 1])

    # 2. duplicate payments
    pg = defaultdict(list)
    for p in db.query(b.Payment).filter(b.Payment.org_id == org.id, b.Payment.status == "posted", b.Payment.payment_date.between(date_from, date_to)):
        pg[(p.contact_id, p.payment_date, p.amount, p.kind)].append(p)
    add("duplicate_payments", "Duplicate payments", "high", "The same contact paid or received the same amount on the same day more than once.",
        [dict(date=k[1].isoformat(), contact=v[0].contact.name, kind=k[3], amount=_s(k[2]), occurrences=len(v), references=[x.reference for x in v]) for k, v in pg.items() if len(v) > 1])

    # 3. possible duplicate invoices / bills (same contact and total within a week, different documents)
    dd = defaultdict(list)
    for d in db.query(b.Doc).filter(b.Doc.org_id == org.id, b.Doc.doc_type.in_(("invoice", "bill")), b.Doc.status.in_(("approved", "paid")), b.Doc.issue_date.between(date_from, date_to)):
        dd[(d.doc_type, d.contact_id, d.total)].append(d)
    dups = []
    for (dt, _, total), ds in dd.items():
        ds.sort(key=lambda x: x.issue_date)
        for a_, b_ in zip(ds, ds[1:]):
            if (b_.issue_date - a_.issue_date).days <= 7:
                dups.append(dict(kind=dt, contact=a_.contact.name, total=_s(total), first=a_.number, first_date=a_.issue_date.isoformat(), second=b_.number, second_date=b_.issue_date.isoformat(),
                                 references=[a_.reference, b_.reference]))
    add("possible_duplicate_documents", "Possible duplicate invoices / bills", "medium", "Same customer/supplier and total within 7 days on two different documents.", dups)

    # 4. stale unreconciled bank lines
    cutoff = date_to - timedelta(days=30)
    stale = [dict(date=l.line_date.isoformat(), account=accs[l.bank_account_id].code + " " + accs[l.bank_account_id].name, description=l.description, amount=_s(l.amount),
                  days_old=(date_to - l.line_date).days)
             for l in db.query(b.BankLine).filter(b.BankLine.org_id == org.id, b.BankLine.status == "unreconciled", b.BankLine.line_date <= cutoff).order_by(b.BankLine.line_date)]
    add("stale_unreconciled", "Bank lines unreconciled for over 30 days", "medium", "Old statement lines that have not been matched or coded leave the books out of step with the bank.", stale)

    # 5. round-sum spend coded directly to an expense account
    rnd = []
    for jl, j in db.query(m.JournalLine, m.Journal).join(m.Journal, m.Journal.id == m.JournalLine.journal_id).join(m.LedgerAccount, m.LedgerAccount.id == m.JournalLine.account_id) \
            .filter(m.JournalLine.org_id == org.id, m.Journal.journal_date.between(date_from, date_to), m.Journal.source_type == "bank_line", m.JournalLine.debit >= 1000,
                    m.LedgerAccount.account_class == "expense"):
        if jl.debit % 500 == 0:
            rnd.append(dict(date=j.journal_date.isoformat(), journal_no=j.journal_no, account=accs[jl.account_id].code + " " + accs[jl.account_id].name, description=jl.description or j.narration, amount=_s(jl.debit)))
    add("round_amount_spend", "Large round-sum spend money", "low", "Spend of $1,000+ in exact $500 multiples coded straight to an expense (no bill) - worth confirming there is an invoice behind it.", rnd)

    # 6. unusual amounts vs the account's own history (mean + 3 sd, at least 6 postings)
    hist = defaultdict(list)
    for jl, j in db.query(m.JournalLine, m.Journal).join(m.Journal, m.Journal.id == m.JournalLine.journal_id).join(m.LedgerAccount, m.LedgerAccount.id == m.JournalLine.account_id) \
            .filter(m.JournalLine.org_id == org.id, m.Journal.journal_date <= date_to, m.LedgerAccount.account_type.in_(("expense", "direct_costs")), m.JournalLine.debit > 0):
        if "depreciation" not in accs[jl.account_id].name.lower():
            hist[jl.account_id].append((j.journal_date, j.journal_no, jl.description or j.narration, jl.debit))
    odd = []
    for aid, rows_ in hist.items():
        vals = [float(r[3]) for r in rows_]
        if len(vals) < 6:
            continue
        thr = mean(vals) + 3 * pstdev(vals)
        for d_, no, desc, amt in rows_:
            if date_from <= d_ <= date_to and float(amt) > thr and pstdev(vals) > 0:
                odd.append(dict(date=d_.isoformat(), journal_no=no, account=accs[aid].code + " " + accs[aid].name, description=desc, amount=_s(amt), typical=_s(money(mean(vals)))))
    add("unusual_amounts", "Unusually large expense postings", "medium", "More than three standard deviations above that account's usual posting (accounts with 6+ postings).", odd)

    # 7. suspense
    susp = _by_key(accs, "suspense")
    if susp:
        bal = -_bal_asat(db, org, date_to, [susp.id]).get(susp.id, Z)
        lines = [dict(date=j.journal_date.isoformat(), journal_no=j.journal_no, description=jl.description or j.narration, debit=_s(jl.debit), credit=_s(jl.credit))
                 for jl, j in db.query(m.JournalLine, m.Journal).join(m.Journal, m.Journal.id == m.JournalLine.journal_id)
                 .filter(m.JournalLine.org_id == org.id, m.JournalLine.account_id == susp.id, m.Journal.journal_date.between(date_from, date_to)).order_by(m.Journal.journal_date)]
        add("suspense", f"Suspense account activity (balance {bal})", "high" if bal != 0 else "low", "Uncoded items are parked in Suspense; a non-zero balance means transactions still need a proper account.", lines if bal != 0 or lines else [])

    # 8. unallocated payments (credit sitting on the account)
    un = []
    for p in db.query(b.Payment).filter(b.Payment.org_id == org.id, b.Payment.status == "posted", b.Payment.payment_date <= date_to, b.Payment.kind.in_(("receive", "pay"))):
        used = sum((a.amount for a in p.allocations if a.alloc_date <= date_to), Z)
        if p.amount - used > 0:
            un.append(dict(date=p.payment_date.isoformat(), contact=p.contact.name, kind=p.kind, reference=p.reference, amount=_s(p.amount), unallocated=_s(p.amount - used)))
    add("unallocated_payments", "Payments not fully allocated", "medium", "Overpayments / prepayments held as credit; apply them to documents so the aged reports are clean.", un)

    # 9. bank accounts overdrawn at the end date
    over = []
    for i, bal in _bal_asat(db, org, date_to, [a.id for a in accs.values() if a.account_type == "bank"]).items():
        if bal < 0:
            over.append(dict(account=accs[i].code + " " + accs[i].name, balance=_s(bal)))
    add("overdrawn", "Bank accounts overdrawn", "high", "A negative ledger balance on a bank account usually means a missing deposit or a mis-coded transfer.", over)

    sev = {"high": 0, "medium": 0, "low": 0}
    for c in checks:
        sev[c["severity"]] += c["count"]
    return dict(date_from=date_from.isoformat(), date_to=date_to.isoformat(), checks=checks, issues=sum(c["count"] for c in checks),
                by_severity=sev, clean=all(c["count"] == 0 for c in checks))


# ------------------------------------------------------------------------------------------------ expense claims --
def expense_claims_report(db, org, date_from, date_to):
    _check_range(date_from, date_to)
    claims = db.query(b.ExpenseClaim).options(selectinload(b.ExpenseClaim.items).selectinload(b.ExpenseItem.account)).filter(b.ExpenseClaim.org_id == org.id).all()
    rows, by_status, by_claimant, by_cat = [], defaultdict(lambda: dict(count=0, total=Z, gst=Z)), defaultdict(lambda: dict(count=0, total=Z, gst=Z)), defaultdict(lambda: dict(count=0, gross=Z, gst=Z, net=Z))
    for c in claims:
        if not c.items:
            continue
        cd = max(i.item_date for i in c.items)
        if not (date_from <= cd <= date_to):
            continue
        rows.append(dict(id=c.id, number=c.number, claimant=c.claimant_name, title=c.title, status=c.status, date=cd.isoformat(), items=len(c.items), net=_s(c.total - c.tax_total),
                         gst=_s(c.tax_total), total=_s(c.total), submitted_at=c.submitted_at.date().isoformat() if c.submitted_at else None,
                         paid_at=c.paid_at.date().isoformat() if c.paid_at else None, rejected_reason=c.rejected_reason))
        for grp, k in ((by_status, c.status), (by_claimant, c.claimant_name)):
            grp[k]["count"] += 1
            grp[k]["total"] += c.total
            grp[k]["gst"] += c.tax_total
        for i in c.items:
            v = by_cat[f"{i.account.code} {i.account.name}"]
            v["count"] += 1
            v["gross"] += i.gross
            v["gst"] += i.tax
            v["net"] += i.net
    rows.sort(key=lambda r: (r["date"], r["number"]))
    fmt = lambda d, keys: [dict(name=k, **{x: (_s(v[x]) if isinstance(v[x], Decimal) else v[x]) for x in keys}) for k, v in sorted(d.items())]
    outstanding = sum((Decimal(r["total"]) for r in rows if r["status"] == "approved"), Z)
    pending = sum((Decimal(r["total"]) for r in rows if r["status"] == "submitted"), Z)
    return dict(date_from=date_from.isoformat(), date_to=date_to.isoformat(), claims=rows, count=len(rows), total=_s(sum((Decimal(r["total"]) for r in rows), Z)),
                gst=_s(sum((Decimal(r["gst"]) for r in rows), Z)), awaiting_approval=_s(pending), approved_unpaid=_s(outstanding),
                by_status=fmt(by_status, ("count", "total", "gst")), by_claimant=fmt(by_claimant, ("count", "total", "gst")), by_category=fmt(by_cat, ("count", "net", "gst", "gross")))


# ------------------------------------------------------------------------------------------------ PAYG summary --
def payg_summary(db, org, date_from, date_to):
    _check_range(date_from, date_to)
    accs = _accs(db, org)
    wages, sup_exp = _by_code(accs, "477") or next((a for a in accs.values() if a.name.lower() == "wages and salaries"), None), \
        _by_code(accs, "478") or next((a for a in accs.values() if a.name.lower() == "superannuation"), None)
    payg, sup_pay, wages_pay = _by_key(accs, "payg_withholding"), _by_key(accs, "super_payable"), _by_key(accs, "wages_payable")
    ids = [a.id for a in (wages, sup_exp, payg, sup_pay, wages_pay) if a]
    sums = L._sums(db, org, date_from, date_to)
    g = lambda a: sums.get(a.id, (Z, Z)) if a else (Z, Z)
    w1 = g(wages)[0] - g(wages)[1]
    w2, remitted = g(payg)[1], g(payg)[0]
    sup_accrued, sup_paid = g(sup_pay)[1], g(sup_pay)[0]
    months = defaultdict(lambda: dict(gross=Z, withheld=Z, remitted=Z, super_accrued=Z, super_paid=Z))
    runs = []
    if ids:
        for jl, j in db.query(m.JournalLine, m.Journal).join(m.Journal, m.Journal.id == m.JournalLine.journal_id) \
                .filter(m.JournalLine.org_id == org.id, m.JournalLine.account_id.in_(ids), m.Journal.journal_date.between(date_from, date_to)):
            mo, a = months[_month_start(j.journal_date)], jl.account_id
            if wages and a == wages.id:
                mo["gross"] += jl.debit - jl.credit
            elif payg and a == payg.id:
                mo["withheld"] += jl.credit
                mo["remitted"] += jl.debit
            elif sup_pay and a == sup_pay.id:
                mo["super_accrued"] += jl.credit
                mo["super_paid"] += jl.debit
        for j in db.query(m.Journal).options(selectinload(m.Journal.lines)).filter(m.Journal.org_id == org.id, m.Journal.source_type == "payroll_run", m.Journal.journal_date.between(date_from, date_to)).order_by(m.Journal.journal_date):
            amt = lambda acc, side: sum((getattr(l, side) for l in j.lines if acc and l.account_id == acc.id), Z)
            runs.append(dict(journal_no=j.journal_no, date=j.journal_date.isoformat(), narration=j.narration, gross=_s(amt(wages, "debit")), payg=_s(amt(payg, "credit")),
                             net_pay=_s(amt(wages_pay, "credit") or amt(wages, "debit") - amt(payg, "credit")), super=_s(amt(sup_pay, "credit"))))
    bal = _bal_asat(db, org, date_to, ids) if ids else {}
    liab = lambda a: -bal.get(a.id, Z) if a else Z
    mrows = [dict(month=ms.strftime("%Y-%m"), **{k: _s(v) for k, v in months.get(ms, dict(gross=Z, withheld=Z, remitted=Z, super_accrued=Z, super_paid=Z)).items()}) for ms in _months(date_from, date_to)]
    return dict(date_from=date_from.isoformat(), date_to=date_to.isoformat(), has_payroll=bool(runs or w1 or w2),
                bas=dict(W1=_s(w1), W2=_s(w2), W3="0.00", W4="0.00", W5="0.00", total_withheld=_s(w2)),
                super=dict(accrued=_s(sup_accrued), paid=_s(sup_paid), expense=_s(g(sup_exp)[0] - g(sup_exp)[1])), remitted_to_ato=_s(remitted),
                liabilities_at_end=dict(payg_withholding=_s(liab(payg)), superannuation=_s(liab(sup_pay)), wages_payable=_s(liab(wages_pay))),
                months=mrows, runs=runs,
                check=dict(payg_expected=_s(w2 - remitted), payg_ledger_movement=_s(-(g(payg)[0] - g(payg)[1])), reconciled=(w2 - remitted == -(g(payg)[0] - g(payg)[1]))),
                note="W1 = gross wages (account 477), W2 = PAYG withheld (credits to account 825). Figures come from payroll journals posted to the ledger; "
                     "payroll runs kept only in the Payroll module appear here once they are posted.")


# ------------------------------------------------------------------------------------------------ budget --
def _period_key(v):
    s = str(v)[:7]
    try:
        y, mo = int(s[:4]), int(s[5:7])
        return date(y, mo, 1)
    except Exception:
        raise BooksError(f"Invalid period {v!r} (use YYYY-MM)")


def get_budget(db, org, scenario="Budget", fy_start=None):
    q = db.query(b.BudgetLine).filter_by(org_id=org.id, scenario=scenario)
    if fy_start:
        q = q.filter(b.BudgetLine.period >= fy_start, b.BudgetLine.period < date(fy_start.year + 1, fy_start.month, 1))
    lines = q.all()
    accs = _accs(db, org)
    by = defaultdict(dict)
    for l in lines:
        by[l.account_id][l.period.strftime("%Y-%m")] = _s(l.amount)
    scen = sorted({r[0] for r in db.query(b.BudgetLine.scenario).filter_by(org_id=org.id).distinct()})
    return dict(scenario=scenario, scenarios=scen or ["Budget"], fy_start=fy_start.isoformat() if fy_start else None,
                accounts=[dict(account_id=i, code=accs[i].code, name=accs[i].name, type=accs[i].account_type, periods=p) for i, p in sorted(by.items(), key=lambda kv: accs[kv[0]].code)],
                line_count=len(lines))


def save_budget(db, org, scenario, lines):
    """lines: [{account: id|code|name, period: 'YYYY-MM', amount}] - upsert; amount 0 removes the line."""
    if not (scenario or "").strip():
        raise BooksError("A budget needs a name")
    n = 0
    for ln in lines or []:
        acc = get_account(db, org, ln.get("account"), what="Budget account")
        if acc.account_class not in PL_CLASSES:
            raise BooksError(f"{acc.code} {acc.name} is a balance-sheet account; budgets are for income and expense accounts")
        per, amt = _period_key(ln.get("period")), money(ln.get("amount"))
        row = db.query(b.BudgetLine).filter_by(org_id=org.id, scenario=scenario, account_id=acc.id, period=per).first()
        if amt == 0:
            if row:
                db.delete(row)
        elif row:
            row.amount = amt
        else:
            db.add(b.BudgetLine(org_id=org.id, scenario=scenario, account_id=acc.id, period=per, amount=amt))
        n += 1
    db.flush()
    return dict(saved=n)


def generate_budget(db, org, scenario, fy_start, uplift_pct=Decimal(0)):
    """Build a 12-month budget for the year starting `fy_start` from the actuals of the year before, lifted by uplift_pct."""
    if fy_start.day != 1:
        raise BooksError("The budget year must start on the first of a month")
    accs = _accs(db, org)
    prior_start = date(fy_start.year - 1, fy_start.month, 1)
    factor = Decimal(1) + Decimal(str(uplift_pct or 0)) / Decimal(100)
    lines = []
    for i in range(12):
        ps = date(prior_start.year + (prior_start.month - 1 + i) // 12, (prior_start.month - 1 + i) % 12 + 1, 1)
        pe = _next_month(ps) - timedelta(days=1)
        for aid, (d, c) in L._sums(db, org, ps, pe).items():
            a = accs[aid]
            if a.account_class not in PL_CLASSES:
                continue
            amt = money(_natural(a, d, c) * factor)
            if amt > 0:
                cur = date(fy_start.year + (fy_start.month - 1 + i) // 12, (fy_start.month - 1 + i) % 12 + 1, 1)
                lines.append(dict(account=a.id, period=cur.strftime("%Y-%m"), amount=amt))
    res = save_budget(db, org, scenario, lines)
    return dict(scenario=scenario, fy_start=fy_start.isoformat(), lines=len(lines), **res)


def budget_variance(db, org, date_from, date_to, scenario="Budget", by_month=False):
    _check_range(date_from, date_to)
    accs = _accs(db, org)
    first = _month_start(date_from)
    actual = L._sums(db, org, date_from, date_to)
    bl = defaultdict(lambda: Z)
    monthly_b = defaultdict(lambda: defaultdict(lambda: Z))
    q = db.query(b.BudgetLine).filter(b.BudgetLine.org_id == org.id, b.BudgetLine.scenario == scenario, b.BudgetLine.period >= first, b.BudgetLine.period <= date_to)
    has = db.query(func.count(b.BudgetLine.id)).filter_by(org_id=org.id, scenario=scenario).scalar() > 0
    for l in q:
        bl[l.account_id] += l.amount
        monthly_b[l.account_id][l.period] += l.amount
    monthly_a = defaultdict(lambda: defaultdict(lambda: Z))
    if by_month:
        for jl, j in db.query(m.JournalLine, m.Journal).join(m.Journal, m.Journal.id == m.JournalLine.journal_id).join(m.LedgerAccount, m.LedgerAccount.id == m.JournalLine.account_id) \
                .filter(m.JournalLine.org_id == org.id, m.Journal.journal_date.between(date_from, date_to), m.LedgerAccount.account_class.in_(PL_CLASSES)):
            monthly_a[jl.account_id][_month_start(j.journal_date)] += _natural(accs[jl.account_id], jl.debit, jl.credit)
    months = _months(date_from, date_to)
    order = {"revenue": 0, "direct_costs": 1, "expense": 2, "other_income": 3, "other_expense": 4}
    sections = {k: dict(rows=[], actual=Z, budget=Z) for k in order}
    for aid in set(actual) | set(bl):
        a = accs[aid]
        if a.account_class not in PL_CLASSES:
            continue
        act = _natural(a, *actual.get(aid, (Z, Z)))
        bud = bl.get(aid, Z)
        if act == 0 and bud == 0:
            continue
        income_like = a.account_class == "revenue"
        var = (act - bud) if income_like else (bud - act)          # favourable is positive in both cases
        row = dict(account_id=a.id, code=a.code, name=a.name, actual=_s(act), budget=_s(bud), variance=_s(var),
                   variance_pct=(_s((var / bud * 100).quantize(Decimal("0.1"))) if bud else None),
                   status="on_budget" if var == 0 else "favourable" if var > 0 else "unfavourable", unbudgeted=(bud == 0 and act != 0))
        if by_month:
            row["monthly"] = [dict(month=ms.strftime("%Y-%m"), actual=_s(monthly_a[aid].get(ms, Z)), budget=_s(monthly_b[aid].get(ms, Z))) for ms in months]
        s_ = sections[a.account_type]
        s_["rows"].append(row)
        s_["actual"] += act
        s_["budget"] += bud
    for s_ in sections.values():
        s_["rows"].sort(key=lambda r: r["code"])

    def sec(k):
        s_ = sections[k]
        inc = k in ("revenue", "other_income")
        var = (s_["actual"] - s_["budget"]) if inc else (s_["budget"] - s_["actual"])
        return dict(rows=s_["rows"], actual=_s(s_["actual"]), budget=_s(s_["budget"]), variance=_s(var))

    a_, b_ = {k: sections[k]["actual"] for k in order}, {k: sections[k]["budget"] for k in order}
    net_a = a_["revenue"] - a_["direct_costs"] - a_["expense"] + a_["other_income"] - a_["other_expense"]
    net_b = b_["revenue"] - b_["direct_costs"] - b_["expense"] + b_["other_income"] - b_["other_expense"]
    gross_a, gross_b = a_["revenue"] - a_["direct_costs"], b_["revenue"] - b_["direct_costs"]
    trend = []
    if by_month:
        for ms in months:
            ia = sum((monthly_a[i].get(ms, Z) * (1 if accs[i].account_class == "revenue" else -1) for i in monthly_a), Z)
            ib = sum((monthly_b[i].get(ms, Z) * (1 if accs[i].account_class == "revenue" else -1) for i in monthly_b if accs[i].account_class in PL_CLASSES), Z)
            trend.append(dict(month=ms.strftime("%Y-%m"), actual_profit=_s(ia), budget_profit=_s(ib)))
    return dict(date_from=date_from.isoformat(), date_to=date_to.isoformat(), scenario=scenario, has_budget=has, months=[x.strftime("%Y-%m") for x in months],
                income=sec("revenue"), cost_of_sales=sec("direct_costs"), expenses=sec("expense"), other_income=sec("other_income"), other_expenses=sec("other_expense"),
                gross_profit=dict(actual=_s(gross_a), budget=_s(gross_b), variance=_s(gross_a - gross_b)),
                net_profit=dict(actual=_s(net_a), budget=_s(net_b), variance=_s(net_a - net_b), variance_pct=_s(((net_a - net_b) / abs(net_b) * 100).quantize(Decimal("0.1"))) if net_b else None),
                trend=trend, note="Variance is shown so that favourable is positive: income above budget, or expenses below budget.")


# ------------------------------------------------------------------------------------------------ management report --
def _pct(n, d):
    return _s((n / d * 100).quantize(Decimal("0.1"))) if d else None


def _ratio(n, d):
    return _s((n / d).quantize(Decimal("0.01"))) if d else None


def management_report(db, org, date_from, date_to):
    _check_range(date_from, date_to)
    span = (date_to - date_from).days + 1
    prior_to = _day_before(date_from)
    prior_from = prior_to - timedelta(days=span - 1)
    pl, pl0 = L.profit_and_loss(db, org, date_from, date_to), L.profit_and_loss(db, org, prior_from, prior_to)
    bs = L.balance_sheet(db, org, date_to)
    ar, ap = R.aged(db, org, "sales", date_to), R.aged(db, org, "purchases", date_to)
    cash = cash_summary(db, org, date_from, date_to)
    gst = R.gst_summary(db, org, date_from, date_to)
    D = Decimal
    income, cogs, opex = D(pl["total_income"]), D(pl["total_cost_of_sales"]), D(pl["total_expenses"])
    net, gross = D(pl["net_profit"]), D(pl["gross_profit"])
    tot = lambda groups, keys: sum((D(r["amount"]) for k in keys for r in groups.get(k, [])), Z)
    cur_assets = tot(bs["assets"], ("bank", "current_asset", "inventory"))
    quick_assets = tot(bs["assets"], ("bank", "current_asset"))
    cur_liab = tot(bs["liabilities"], ("credit_card", "current_liability"))
    ar_t, ap_t = D(ar["total"]), D(ap["total"])
    kpis = dict(gross_margin_pct=_pct(gross, income), net_margin_pct=_pct(net, income), expense_ratio_pct=_pct(cogs + opex, income),
                current_ratio=_ratio(cur_assets, cur_liab), quick_ratio=_ratio(quick_assets, cur_liab), working_capital=_s(cur_assets - cur_liab),
                debtor_days=_s((ar_t / income * span).quantize(D("0.1"))) if income else None,
                creditor_days=_s((ap_t / (cogs + opex) * span).quantize(D("0.1"))) if (cogs + opex) else None,
                cash_balance=_s(D(cash["closing_cash"])), net_cash_movement=_s(D(cash["net_movement"])),
                income_change_pct=_pct(income - D(pl0["total_income"]), D(pl0["total_income"])), profit_change=_s(net - D(pl0["net_profit"])))
    # 12-month trend ending at date_to
    t_from = _month_start(date_to)
    for _ in range(11):
        t_from = _month_start(t_from - timedelta(days=1))
    trend = []
    for ms in _months(t_from, date_to):
        me = min(_next_month(ms) - timedelta(days=1), date_to)
        p = L.profit_and_loss(db, org, ms, me)
        trend.append(dict(month=ms.strftime("%Y-%m"), income=p["total_income"], expenses=_s(D(p["total_cost_of_sales"]) + D(p["total_expenses"]) + D(p["total_other_expenses"])), profit=p["net_profit"]))
    top_c, top_s = R.by_contact(db, org, "sales", date_from, date_to), R.by_contact(db, org, "purchases", date_from, date_to)
    alerts = []
    if D(ar["buckets"].get("90+", "0")) > 0:
        alerts.append(dict(level="warning", text=f"Receivables over 90 days overdue: {ar['buckets']['90+']}"))
    if D(cash["closing_cash"]) < 0:
        alerts.append(dict(level="danger", text="Bank accounts are overdrawn in total."))
    if not ar["control"]["reconciled"] or not ap["control"]["reconciled"]:
        alerts.append(dict(level="warning", text="A sub-ledger does not agree with its control account."))
    if not bs["balanced"]:
        alerts.append(dict(level="danger", text="The balance sheet does not balance."))
    if D(gst["net_gst_payable"]) > 0:
        alerts.append(dict(level="info", text=f"Net GST payable for the period: {gst['net_gst_payable']}"))
    return dict(organisation=dict(name=org.name, abn=org.abn), date_from=date_from.isoformat(), date_to=date_to.isoformat(), prior=dict(date_from=prior_from.isoformat(), date_to=prior_to.isoformat()),
                pl=pl, pl_prior=pl0, balance_sheet=bs, aged_receivables=dict(buckets=ar["buckets"], total=ar["total"], top=[dict(contact=c["contact"], total=c["total"]) for c in sorted(ar["contacts"], key=lambda c: -D(c["total"]))[:5]], control=ar["control"]),
                aged_payables=dict(buckets=ap["buckets"], total=ap["total"], top=[dict(contact=c["contact"], total=c["total"]) for c in sorted(ap["contacts"], key=lambda c: -D(c["total"]))[:5]], control=ap["control"]),
                cash=dict(opening=cash["opening_cash"], closing=cash["closing_cash"], receipts=cash["total_receipts"], payments=cash["total_payments"], months=cash["months"]),
                gst=dict(gst_on_sales_1A=gst["gst_on_sales_1A"], gst_on_purchases_1B=gst["gst_on_purchases_1B"], net_gst_payable=gst["net_gst_payable"]),
                kpis=kpis, trend=trend, top_customers=top_c["rows"][:5], top_suppliers=top_s["rows"][:5], alerts=alerts)


# ------------------------------------------------------------------------------------------------ inventory item details --
def inventory_item_details(db, org, date_from, date_to):
    _check_range(date_from, date_to)
    items = db.query(inv.StockItem).filter_by(org_id=org.id).order_by(inv.StockItem.sku).all()
    mv_by = defaultdict(list)
    for mv in db.query(inv.StockMovement).filter_by(org_id=org.id).order_by(inv.StockMovement.id):
        mv_by[mv.item_id].append(mv)
    out, tot = [], dict(opening_value=Z, purchases_value=Z, cogs_value=Z, adjustments_value=Z, closing_value=Z)
    for it in items:
        qty = val = Z
        prev_q = Decimal(0)
        o_q, o_v = Decimal(0), Z
        buys_q, buys_v, sells_q, sells_v, adj_q, adj_v = Decimal(0), Z, Decimal(0), Z, Decimal(0), Z
        moves, run_q, run_v = [], Decimal(0), Z
        for mv in mv_by[it.id]:
            delta = mv.quantity_after - prev_q
            prev_q = mv.quantity_after
            sq = mv.quantity if mv.kind in ("buy", "opening") else (-mv.quantity if mv.kind == "sell" else delta)
            sv = mv.amount if sq > 0 else -mv.amount
            if mv.movement_date <= date_to:
                qty, val = qty + sq, val + sv
            if mv.movement_date < date_from:
                o_q, o_v = o_q + sq, o_v + sv
            elif mv.movement_date <= date_to:
                if mv.kind in ("buy", "opening"):
                    buys_q, buys_v = buys_q + sq, buys_v + sv
                elif mv.kind == "sell":
                    sells_q, sells_v = sells_q + sq, sells_v + sv
                else:
                    adj_q, adj_v = adj_q + sq, adj_v + sv
                run_q, run_v = o_q + buys_q + sells_q + adj_q, o_v + buys_v + sells_v + adj_v
                moves.append(dict(date=mv.movement_date.isoformat(), kind=mv.kind, quantity=_s(sq), unit_cost=_s(mv.unit_cost.quantize(Decimal("0.0001"))) if mv.unit_cost is not None else None,
                                  amount=_s(sv), balance_qty=_s(run_q), balance_value=_s(run_v), reference=mv.reference, note=mv.note))
        avg = (val / qty).quantize(Decimal("0.0001")) if qty else Decimal("0.0000")
        for k, v in (("opening_value", o_v), ("purchases_value", buys_v), ("cogs_value", -sells_v), ("adjustments_value", adj_v), ("closing_value", val)):
            tot[k] += v
        out.append(dict(item_id=it.id, sku=it.sku, name=it.name, is_active=it.is_active, sale_price=_s(it.sale_price) if it.sale_price is not None else None,
                        opening_qty=_s(o_q), opening_value=_s(o_v), purchased_qty=_s(buys_q), purchased_value=_s(buys_v), sold_qty=_s(-sells_q), cogs_value=_s(-sells_v),
                        adjustment_qty=_s(adj_q), adjustment_value=_s(adj_v), closing_qty=_s(qty), closing_value=_s(val), average_cost=_s(avg),
                        margin_pct=_pct(it.sale_price - avg, it.sale_price) if it.sale_price else None, movements=moves,
                        low_stock=bool(qty <= 0 and it.is_active)))
    inv_ids = {i.inventory_account_id for i in items}
    led = sum(_bal_asat(db, org, date_to, inv_ids).values(), Z) if inv_ids else Z
    return dict(date_from=date_from.isoformat(), date_to=date_to.isoformat(), items=out, count=len(out),
                totals={k: _s(v) for k, v in tot.items()},
                control=dict(ledger_balance=_s(led), subledger_total=_s(tot["closing_value"]), difference=_s(led - tot["closing_value"]), reconciled=(led == tot["closing_value"])))
