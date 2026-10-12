"""Public surface of the Accounting module: the ONLY import path other modules may use."""
from accfino.modules.accounting.coa.legacy_bridge import register_refresh_hook as register_coa_refresh_hook  # noqa: F401


# ---- general-ledger facade used by Payroll (additive; signatures are stable) ------------------------------------------------------
from accfino.modules.accounting.ledger.service import LedgerError, post_journal, reverse_journal  # noqa: E402,F401


def seed_org_ledger_accounts(db, org):
    """Seed an organisation's standard chart of accounts and tax codes (idempotent)."""
    from accfino.modules.accounting.ledger.seed import seed_org_ledger
    return seed_org_ledger(db, org)


def ledger_accounts(db, org_id: int, active_only: bool = True):
    """[{id, code, name, type, system_key, is_active}] for the organisation's chart of accounts."""
    from accfino.modules.accounting.models import ledger as lm
    q = db.query(lm.LedgerAccount).filter(lm.LedgerAccount.org_id == org_id)
    if active_only:
        q = q.filter(lm.LedgerAccount.is_active.is_(True))
    return [dict(id=a.id, code=a.code, name=a.name, type=a.account_type, system_key=a.system_key, is_active=a.is_active)
            for a in q.order_by(lm.LedgerAccount.code)]


def ensure_ledger_account(db, org_id: int, *, code: str, name: str, account_type: str, system_key=None):
    """Return the account with this system_key (or code), creating it if missing. Returns {id, code, name}."""
    from accfino.modules.accounting.models import ledger as lm
    q = db.query(lm.LedgerAccount).filter(lm.LedgerAccount.org_id == org_id)
    a = (q.filter(lm.LedgerAccount.system_key == system_key).first() if system_key else None) or q.filter(lm.LedgerAccount.code == code).first()
    if a is None:
        a = lm.LedgerAccount(org_id=org_id, code=code, name=name, account_type=account_type, account_class=lm.ACCOUNT_TYPES[account_type],
                             system_key=system_key)
        db.add(a)
        db.flush()
    return dict(id=a.id, code=a.code, name=a.name)


def journal_summary(db, org_id: int, journal_id: int):
    """{id, journal_no, date, status, total} for a journal, or None."""
    from accfino.modules.accounting.models import ledger as lm
    j = db.query(lm.Journal).filter(lm.Journal.org_id == org_id, lm.Journal.id == journal_id).first()
    return None if j is None else dict(id=j.id, journal_no=j.journal_no, date=j.journal_date.isoformat(), status=j.status, total=str(j.total))


# ---- read-only facade used by Taxation & Compliance (additive; signatures are stable) ---------------------------------------------
def gst_summary(db, org, date_from, date_to, basis=None):
    """BAS-style GST report from the ledger (G1..G18, 1A, 1B) with the GST-account reconciliation check. `org` is the Organisation row."""
    from accfino.modules.accounting.books import reports as R
    return R.gst_summary(db, org, date_from, date_to, basis)


def payg_summary(db, org, date_from, date_to):
    """Wages (W1) and PAYG withheld (W2) as posted to the ledger by payroll, with the PAYG-liability reconciliation check."""
    from accfino.modules.accounting.books import reports_extra as X
    return X.payg_summary(db, org, date_from, date_to)


def profit_and_loss(db, org, date_from, date_to):
    """Ledger profit for a period: {revenue_total, expense_total, net_profit, revenue:[{code,name,type,amount}], expenses:[...]} (strings, cents)."""
    from decimal import Decimal
    from accfino.modules.accounting.books.common import money
    from accfino.modules.accounting.ledger import service as L
    accs = L._accounts(db, org)
    sums = L._sums(db, org, date_from, date_to)
    rev, exp, rt, et = [], [], Decimal("0"), Decimal("0")
    for aid, (d, c) in sums.items():
        a = accs.get(aid)
        if a is None or a.account_class not in ("revenue", "expense"):
            continue
        if a.account_class == "revenue":
            amt = money(c - d)
            rt += amt
            rev.append(dict(code=a.code, name=a.name, type=a.account_type, amount=str(amt)))
        else:
            amt = money(d - c)
            et += amt
            exp.append(dict(code=a.code, name=a.name, type=a.account_type, amount=str(amt)))
    key = lambda r: r["code"]
    return dict(date_from=date_from.isoformat(), date_to=date_to.isoformat(), revenue_total=str(money(rt)), expense_total=str(money(et)), net_profit=str(money(rt - et)),
                revenue=sorted(rev, key=key), expenses=sorted(exp, key=key))


def fixed_assets_for_tax(db, org_id: int, date_from, date_to):
    """Fixed-asset register rows for the tax depreciation review, with the book depreciation posted between the dates."""
    from sqlalchemy import func
    from accfino.modules.accounting.assets.models import DepreciationRun, FixedAsset
    book = dict(db.query(DepreciationRun.asset_id, func.coalesce(func.sum(DepreciationRun.amount), 0)).filter(
        DepreciationRun.org_id == org_id, DepreciationRun.as_at.between(date_from, date_to)).group_by(DepreciationRun.asset_id).all())
    out = []
    for a in db.query(FixedAsset).filter(FixedAsset.org_id == org_id).order_by(FixedAsset.number):
        out.append(dict(id=a.id, number=a.number, name=a.name, category=a.category, cost=a.cost, purchase_date=a.purchase_date, status=a.status,
                        disposal_date=a.disposal_date, disposal_proceeds=a.disposal_proceeds, book_depreciation=book.get(a.id, 0)))
    return out


def account_balance(db, org, account_id: int, as_at):
    """Closing balance of one ledger account at a date (debit-positive for assets, credit-positive for liabilities/equity, as the books show it) or None."""
    from accfino.modules.accounting.books.common import money
    from accfino.modules.accounting.ledger import service as L
    accs = L._accounts(db, org)
    a = accs.get(account_id)
    if a is None:
        return None
    d, c = L._sums(db, org, date_to=as_at).get(account_id, (0, 0))
    return str(money((d - c) if a.account_class in ("asset", "expense") else (c - d)))


def system_account_balance(db, org, system_key: str, as_at):
    """Balance of a system account (e.g. 'suspense', 'payg_withholding', 'super_payable') or None when the organisation has no such account."""
    from accfino.modules.accounting.models import ledger as lm
    a = db.query(lm.LedgerAccount).filter_by(org_id=org.id, system_key=system_key).first()
    return None if a is None else account_balance(db, org, a.id, as_at)


def attachment_info(db, org_id: int, attachment_id: int):
    """{id, filename, content_type, size, owner_kind, owner_id} of a stored document, or None (never another organisation's)."""
    from accfino.modules.accounting.books.models import Attachment
    a = db.query(Attachment).filter(Attachment.org_id == org_id, Attachment.id == attachment_id).first()
    return None if a is None else dict(id=a.id, filename=a.filename, content_type=a.content_type, size=a.size, owner_kind=a.owner_kind, owner_id=a.owner_id)


def balances_by_account(db, org, as_at):
    """[{id, code, name, type, class, balance}] for every active account at a date, each balance in the sign the books show it (debit-positive for assets and expenses, credit-positive otherwise)."""
    from accfino.modules.accounting.books.common import money
    from accfino.modules.accounting.ledger import service as L
    sums = L._sums(db, org, date_to=as_at)
    out = []
    for a in L._accounts(db, org).values():
        if not getattr(a, "is_active", True):
            continue
        d, c = sums.get(a.id, (0, 0))
        out.append(dict(id=a.id, code=a.code, name=a.name, type=a.account_type, system_key=a.system_key, **{"class": a.account_class}, balance=str(money((d - c) if a.account_class in ("asset", "expense") else (c - d)))))
    return out


# ---- Smart Lending, Credit & Treasury facade (additive): applicants are contacts, documents are attachments, statements are bank lines --------------------------------------------------
def _contact_dict(c):
    return dict(id=c.id, name=c.name, email=c.email, phone=c.phone, abn=c.abn, address=c.address, notes=c.notes, is_customer=c.is_customer, is_active=c.is_active)


def contact(db, org_id: int, contact_id: int):
    """{id, name, email, phone, abn, address, notes, is_customer, is_active} or None (never another organisation's)."""
    from accfino.modules.accounting.books.models import Contact
    c = db.query(Contact).filter(Contact.org_id == org_id, Contact.id == contact_id).first()
    return None if c is None else _contact_dict(c)


def contacts_search(db, org_id: int, q: str = "", limit: int = 25):
    """Active contacts whose name, email, phone or ABN contains `q`, by name."""
    from accfino.modules.accounting.books.models import Contact
    query = db.query(Contact).filter(Contact.org_id == org_id, Contact.is_active.is_(True))
    q = (q or "").strip()
    if q:
        like = f"%{q}%"
        query = query.filter((Contact.name.ilike(like)) | (Contact.email.ilike(like)) | (Contact.phone.ilike(like)) | (Contact.abn.ilike(like)))
    return [_contact_dict(c) for c in query.order_by(Contact.name).limit(max(1, min(int(limit), 100)))]


def create_contact(db, org_id: int, *, name: str, email=None, phone=None, abn=None, address=None, notes=None):
    """Create a customer contact, or return the existing one with that exact name. -> (contact dict, created: bool)."""
    from accfino.modules.accounting.books.models import Contact
    name = (name or "").strip()
    if not name:
        raise ValueError("A name is required")
    c = db.query(Contact).filter(Contact.org_id == org_id, Contact.name == name).first()
    if c is not None:
        return _contact_dict(c), False
    c = Contact(org_id=org_id, name=name[:255], is_customer=True, email=email or None, phone=phone or None, abn=abn or None, address=address or None, notes=notes or None)
    db.add(c)
    db.flush()
    return _contact_dict(c), True


def add_attachment(db, org_id: int, owner_kind: str, owner_id: int, filename: str, content_type: str, data: bytes, uploaded_by=None):
    """Store a document with the SAME size and type limits as Accounting's own attachments. -> {id, filename, content_type, size}."""
    from accfino.modules.accounting.api.books_docs import ALLOWED_TYPES, MAX_ATTACH
    from accfino.modules.accounting.books.models import Attachment
    if not data:
        raise ValueError("The file is empty")
    if len(data) > MAX_ATTACH:
        raise ValueError(f"The file is larger than {MAX_ATTACH // (1024 * 1024)} MB")
    if content_type not in ALLOWED_TYPES:
        raise ValueError("Only PDF, image (PNG, JPEG, GIF, WebP), text and CSV files can be attached")
    a = Attachment(org_id=org_id, owner_kind=owner_kind[:20], owner_id=owner_id, filename=(filename or "document")[:255], content_type=content_type, size=len(data), data=data, uploaded_by=uploaded_by)
    db.add(a)
    db.flush()
    return dict(id=a.id, filename=a.filename, content_type=a.content_type, size=a.size)


def get_attachment(db, org_id: int, attachment_id: int):
    """(meta dict, bytes) or None (never another organisation's)."""
    from accfino.modules.accounting.books.models import Attachment
    a = db.query(Attachment).filter(Attachment.org_id == org_id, Attachment.id == attachment_id).first()
    return None if a is None else (dict(id=a.id, filename=a.filename, content_type=a.content_type, size=a.size, owner_kind=a.owner_kind, owner_id=a.owner_id), bytes(a.data))


def delete_attachment(db, org_id: int, attachment_id: int) -> bool:
    from accfino.modules.accounting.books.models import Attachment
    a = db.query(Attachment).filter(Attachment.org_id == org_id, Attachment.id == attachment_id).first()
    if a is None:
        return False
    db.delete(a)
    db.flush()
    return True


def bank_accounts(db, org_id: int):
    """The organisation's ledger BANK accounts: [{id, code, name}]."""
    return [dict(id=a["id"], code=a["code"], name=a["name"]) for a in ledger_accounts(db, org_id) if a["type"] == "bank"]


def bank_lines(db, org_id: int, account_ids, date_from, date_to, limit: int = 20000):
    """Bank transactions already in Accfino for some bank accounts: [{id, date, description, amount (+ in, - out), balance, bank_account_id}], oldest first."""
    from accfino.modules.accounting.books.models import BankLine
    q = db.query(BankLine).filter(BankLine.org_id == org_id, BankLine.bank_account_id.in_(list(account_ids) or [-1]), BankLine.line_date >= date_from, BankLine.line_date <= date_to, BankLine.status != "excluded")
    return [dict(id=b.id, date=b.line_date, description=b.description, amount=b.amount, balance=b.balance, bank_account_id=b.bank_account_id) for b in q.order_by(BankLine.line_date, BankLine.id).limit(limit)]


def open_items(db, org, as_at):
    """Open (unpaid) invoices and bills with due dates: [{side: receivable|payable, kind, number, contact, due (date), amount (Decimal), days_overdue}] from the same ageing the reports use."""
    from datetime import date as _d
    from decimal import Decimal
    from accfino.modules.accounting.books import reports as R
    out = []
    for side, label in (("sales", "receivable"), ("purchases", "payable")):
        for c in R.aged(db, org, side, as_at)["contacts"]:
            for d in c["docs"]:
                if d["kind"] in ("invoice", "bill") and "due" in d:
                    amt = Decimal(d["amount"])
                    if amt > 0:
                        out.append(dict(side=label, kind=d["kind"], number=d["number"], contact=c["contact"], due=_d.fromisoformat(d["due"]), amount=amt, days_overdue=int(d.get("days_overdue", 0))))
    return out


def fixed_asset(db, org_id: int, asset_id: int):
    """{id, number, name, category, cost, status} of a fixed asset (for linking a lease or hire purchase to its asset), or None (never another organisation's)."""
    from accfino.modules.accounting.assets.models import FixedAsset
    a = db.query(FixedAsset).filter(FixedAsset.org_id == org_id, FixedAsset.id == asset_id).first()
    return None if a is None else dict(id=a.id, number=a.number, name=a.name, category=a.category, cost=a.cost, status=a.status)


# ---- Planning & Intelligence facade (additive, READ-ONLY): the ledger and sub-ledgers as the single source of truth for forecasts, budgets, reports and alerts ----------------------------
def ledger_lines(db, org_id: int, date_from, date_to, *, account_classes=None, account_id=None, source_types=None, bank_touching: bool = False, limit: int = 5000):
    """Posted journal lines in a period, oldest first, for drill-down and analytics:
    [{journal_id, journal_no, date, source_type, narration, reference, account_id, account_code, account_name, account_type, account_class, debit, credit, contact_name}] (Decimals).
    `bank_touching` keeps only journals that also post to a bank account. Reversal pairs are returned as posted (they net to zero). Never another organisation's rows."""
    from accfino.modules.accounting.models import ledger as lm
    q = db.query(lm.JournalLine, lm.Journal, lm.LedgerAccount).join(lm.Journal, lm.Journal.id == lm.JournalLine.journal_id) \
        .join(lm.LedgerAccount, lm.LedgerAccount.id == lm.JournalLine.account_id) \
        .filter(lm.Journal.org_id == org_id, lm.JournalLine.org_id == org_id, lm.Journal.journal_date >= date_from, lm.Journal.journal_date <= date_to)
    if account_classes:
        q = q.filter(lm.LedgerAccount.account_class.in_(list(account_classes)))
    if account_id:
        q = q.filter(lm.JournalLine.account_id == account_id)
    if source_types:
        q = q.filter(lm.Journal.source_type.in_(list(source_types)))
    if bank_touching:
        bank_ids = [a.id for a in db.query(lm.LedgerAccount.id).filter(lm.LedgerAccount.org_id == org_id, lm.LedgerAccount.account_type == "bank")]
        q = q.filter(lm.Journal.id.in_(db.query(lm.JournalLine.journal_id).filter(lm.JournalLine.org_id == org_id, lm.JournalLine.account_id.in_(bank_ids or [-1]))))
    out = []
    for jl, j, a in q.order_by(lm.Journal.journal_date, lm.Journal.id, lm.JournalLine.line_no).limit(max(1, min(int(limit), 50000))):
        out.append(dict(journal_id=j.id, journal_no=j.journal_no, date=j.journal_date, source_type=j.source_type, narration=j.narration or "", reference=j.reference or "",
                        account_id=a.id, account_code=a.code, account_name=a.name, account_type=a.account_type, account_class=a.account_class,
                        debit=jl.debit, credit=jl.credit, contact_name=jl.contact_name or "", description=jl.description or ""))
    return out


def monthly_pl(db, org_id: int, date_from, date_to):
    """Profit-and-loss accounts by calendar month straight from the ledger, in the natural sign (revenue = credits - debits, expenses = debits - credits):
    [{account_id, code, name, type, class, months: {'YYYY-MM': Decimal}}]. Only accounts with activity are returned."""
    from collections import defaultdict
    from decimal import Decimal
    from sqlalchemy import func
    from accfino.modules.accounting.models import ledger as lm
    rows = db.query(lm.JournalLine.account_id, lm.Journal.journal_date, func.sum(lm.JournalLine.debit), func.sum(lm.JournalLine.credit)) \
        .join(lm.Journal, lm.Journal.id == lm.JournalLine.journal_id).join(lm.LedgerAccount, lm.LedgerAccount.id == lm.JournalLine.account_id) \
        .filter(lm.Journal.org_id == org_id, lm.Journal.journal_date >= date_from, lm.Journal.journal_date <= date_to, lm.LedgerAccount.account_class.in_(("revenue", "expense"))) \
        .group_by(lm.JournalLine.account_id, lm.Journal.journal_date).all()
    accs = {a.id: a for a in db.query(lm.LedgerAccount).filter(lm.LedgerAccount.org_id == org_id)}
    acc = defaultdict(lambda: defaultdict(lambda: Decimal("0")))
    for aid, d, dr, cr in rows:
        a = accs[aid]
        amt = (Decimal(str(cr or 0)) - Decimal(str(dr or 0))) if a.account_class == "revenue" else (Decimal(str(dr or 0)) - Decimal(str(cr or 0)))
        acc[aid][d.strftime("%Y-%m")] += amt
    return [dict(account_id=aid, code=accs[aid].code, name=accs[aid].name, type=accs[aid].account_type, **{"class": accs[aid].account_class}, months=dict(sorted(m.items())))
            for aid, m in sorted(acc.items(), key=lambda kv: accs[kv[0]].code)]


def balance_sheet(db, org, as_at):
    """The ledger balance sheet at a date (assets, liabilities, equity with current-year earnings)."""
    from accfino.modules.accounting.ledger import service as L
    return L.balance_sheet(db, org, as_at)


def aged_report(db, org, side: str, as_at):
    """Ageing of receivables (side='sales') or payables (side='purchases'), with its control-account reconciliation."""
    from accfino.modules.accounting.books import reports as R
    return R.aged(db, org, side, as_at)


def cash_summary(db, org, date_from, date_to):
    """Cash receipts/payments by section and month with opening/closing bank balance (same as the Cash Summary report)."""
    from accfino.modules.accounting.books import reports_extra as X
    return X.cash_summary(db, org, date_from, date_to)


def cash_validation(db, org, date_from, date_to):
    """Cash data-quality checks for a period (unreconciled lines, unusual cash, control checks)."""
    from accfino.modules.accounting.books import reports_extra as X
    return X.cash_validation(db, org, date_from, date_to)


def management_report(db, org, date_from, date_to):
    """The existing management report (KPIs, trend, alerts) for a period."""
    from accfino.modules.accounting.books import reports_extra as X
    return X.management_report(db, org, date_from, date_to)


def budget_lines(db, org, scenario: str = "Budget", fy_start=None):
    """The saved monthly budget for a scenario name: the existing get_budget result."""
    from accfino.modules.accounting.books import reports_extra as X
    return X.get_budget(db, org, scenario, fy_start)


def budget_save(db, org, scenario: str, lines):
    """Upsert budget lines [{account: id|code|name, period: 'YYYY-MM', amount}] (amount 0 removes a line). P&L accounts only."""
    from accfino.modules.accounting.books import reports_extra as X
    return X.save_budget(db, org, scenario, lines)


def budget_variance_report(db, org, date_from, date_to, scenario: str = "Budget", by_month: bool = False):
    """Existing budget-vs-actual report (favourable-positive variance)."""
    from accfino.modules.accounting.books import reports_extra as X
    return X.budget_variance(db, org, date_from, date_to, scenario, by_month)


def budget_scenarios(db, org_id: int):
    """[{scenario, lines, first_period, last_period}] - every budget name the organisation has saved."""
    from sqlalchemy import func
    from accfino.modules.accounting.books.models import BudgetLine
    return [dict(scenario=s, lines=int(n), first_period=lo, last_period=hi) for s, n, lo, hi in
            db.query(BudgetLine.scenario, func.count(BudgetLine.id), func.min(BudgetLine.period), func.max(BudgetLine.period)).filter(BudgetLine.org_id == org_id).group_by(BudgetLine.scenario).order_by(BudgetLine.scenario)]


def delete_budget_scenario(db, org_id: int, scenario: str) -> int:
    """Remove every line of a budget name (used when an unapproved copy is discarded). Returns the number of lines removed."""
    from accfino.modules.accounting.books.models import BudgetLine
    n = db.query(BudgetLine).filter(BudgetLine.org_id == org_id, BudgetLine.scenario == scenario).delete(synchronize_session=False)
    db.flush()
    return int(n)


def settled_documents(db, org_id: int, date_from, date_to):
    """Invoices and bills FULLY settled with their payment timing, for collection/payment-behaviour analysis:
    [{side: receivable|payable, number, contact, contact_id, issue (date), due (date|None), paid (date), amount (Decimal)}] where `paid` is the last allocation date."""
    from sqlalchemy import func
    from accfino.modules.accounting.books.models import Allocation, Contact, Doc
    last = db.query(Allocation.doc_id, func.max(Allocation.alloc_date).label("paid")).filter(Allocation.org_id == org_id, Allocation.doc_id.isnot(None)).group_by(Allocation.doc_id).subquery()
    q = db.query(Doc, Contact.name, last.c.paid).join(Contact, Contact.id == Doc.contact_id).join(last, last.c.doc_id == Doc.id) \
        .filter(Doc.org_id == org_id, Doc.doc_type.in_(("invoice", "bill")), Doc.status.notin_(("voided", "archived", "draft", "cancelled")), last.c.paid >= date_from, last.c.paid <= date_to)
    out = []
    for d, cname, paid in q.order_by(last.c.paid, Doc.id):
        if (d.total or 0) - (d.amount_paid or 0) - (d.amount_credited or 0) != 0 or (d.total or 0) <= 0:
            continue
        out.append(dict(side="receivable" if d.doc_type == "invoice" else "payable", number=d.number, contact=cname, contact_id=d.contact_id, issue=d.issue_date, due=d.due_date, paid=paid, amount=d.total))
    return out


def open_document_items(db, org_id: int, as_at):
    """Open invoices and bills with their ids for drill-down: [{id, side, number, contact, issue, due, amount_due (Decimal)}] (posted/approved documents only)."""
    from accfino.modules.accounting.books.models import Contact, Doc
    out = []
    q = db.query(Doc, Contact.name).join(Contact, Contact.id == Doc.contact_id).filter(
        Doc.org_id == org_id, Doc.doc_type.in_(("invoice", "bill")), Doc.status.notin_(("voided", "archived", "draft", "cancelled", "paid")), Doc.issue_date <= as_at)
    for d, cname in q.order_by(Doc.due_date, Doc.id):
        due_amt = (d.total or 0) - (d.amount_paid or 0) - (d.amount_credited or 0)
        if due_amt > 0 and d.journal_id is not None:
            out.append(dict(id=d.id, side="receivable" if d.doc_type == "invoice" else "payable", number=d.number, contact=cname, issue=d.issue_date, due=d.due_date or d.issue_date, amount_due=due_amt))
    return out


def bank_reconciliation_status(db, org, as_at):
    """Per bank account: ledger balance at a date vs the latest imported statement balance, plus unreconciled statement lines:
    [{account_id, code, name, ledger_balance (Decimal), statement_balance (Decimal|None), statement_date, difference (Decimal|None), unreconciled_count, unreconciled_amount (Decimal), last_line_date}].
    A difference is only meaningful when the statement balance is the line on/before `as_at` and every earlier line is imported."""
    from decimal import Decimal
    from sqlalchemy import func
    from accfino.modules.accounting.books.models import BankLine
    from accfino.modules.accounting.ledger import service as L
    sums = L._sums(db, org, date_to=as_at)
    out = []
    for a in bank_accounts(db, org.id):
        d, c = sums.get(a["id"], (Decimal(0), Decimal(0)))
        led = Decimal(d) - Decimal(c)
        last = db.query(BankLine).filter(BankLine.org_id == org.id, BankLine.bank_account_id == a["id"], BankLine.line_date <= as_at, BankLine.balance.isnot(None)) \
            .order_by(BankLine.line_date.desc(), BankLine.id.desc()).first()
        n, amt = db.query(func.count(BankLine.id), func.coalesce(func.sum(BankLine.amount), 0)).filter(
            BankLine.org_id == org.id, BankLine.bank_account_id == a["id"], BankLine.status == "unreconciled", BankLine.line_date <= as_at).one()
        lastd = db.query(func.max(BankLine.line_date)).filter(BankLine.org_id == org.id, BankLine.bank_account_id == a["id"], BankLine.line_date <= as_at).scalar()
        out.append(dict(account_id=a["id"], code=a["code"], name=a["name"], ledger_balance=led, statement_balance=last.balance if last else None, statement_date=last.line_date if last else None,
                        difference=(led - Decimal(last.balance)) if last else None, unreconciled_count=int(n or 0), unreconciled_amount=Decimal(amt or 0), last_line_date=lastd))
    return out


def ledger_activity_dates(db, org_id: int, exclude_source_types=()):
    """{first, last, months} of posted journal dates: how much history the organisation has (None values when there are no journals).
    exclude_source_types: e.g. ('opening_balance',) so that a balance carried in on day one does not count as history."""
    from sqlalchemy import func
    from accfino.modules.accounting.models import ledger as lm
    q = db.query(func.min(lm.Journal.journal_date), func.max(lm.Journal.journal_date)).filter(lm.Journal.org_id == org_id)
    if exclude_source_types:
        q = q.filter(lm.Journal.source_type.notin_(tuple(exclude_source_types)))
    lo, hi = q.one()
    months = 0 if lo is None else (hi.year - lo.year) * 12 + hi.month - lo.month + 1
    return dict(first=lo, last=hi, months=months)


def budget_generate(db, org, scenario: str, fy_start, uplift_pct=0):
    """Create a 12-month budget from the previous year's ledger actuals lifted by uplift_pct (the existing generator): {scenario, fy_start, lines, saved}."""
    from decimal import Decimal
    from accfino.modules.accounting.books import reports_extra as X
    return X.generate_budget(db, org, scenario, fy_start, Decimal(str(uplift_pct or 0)))


# ---- Practice & Client Services facade (additive): a practice raises client invoices through the SAME receivables ledger (no second ledger) -------------------------------------


def create_sales_invoice(db, org, user_id: int, *, contact_id: int, issue_date, due_date=None, reference=None, lines, source: str = "practice"):
    """Create AND approve (post) a sales invoice. lines: [{description, qty, unit_price, account?, tax_code?}] (amounts ex tax). Returns the invoice dict. Raises BooksError on rule violations."""
    from accfino.modules.accounting.books import docs
    doc = docs.create_doc(db, org, user_id, "invoice", dict(contact_id=contact_id, issue_date=issue_date, due_date=due_date, reference=reference, lines=lines, source=source, amounts_are="exclusive"), approve=True)
    return docs.doc_dict(db, doc)


def sales_document(db, org_id: int, doc_id: int):
    """{id,number,doc_type,status,total,amount_paid,amount_credited,amount_due,issue_date,due_date} or None (only this organisation's)."""
    from accfino.modules.accounting.books.models import Doc
    d = db.query(Doc).filter(Doc.org_id == org_id, Doc.id == doc_id, Doc.doc_type.in_(("invoice", "credit_note"))).first()
    if d is None:
        return None
    return dict(id=d.id, number=d.number, doc_type=d.doc_type, status=d.status, total=d.total, amount_paid=d.amount_paid, amount_credited=d.amount_credited, amount_due=d.amount_due,
                issue_date=d.issue_date, due_date=d.due_date, subtotal=d.subtotal, tax_total=d.tax_total)


def void_sales_invoice(db, org, user_id: int, doc_id: int):
    """Void an approved invoice by reversing its journal. Refused (BooksError) when payments or credits are applied."""
    from accfino.modules.accounting.books import docs
    from accfino.modules.accounting.books.models import Doc
    d = db.query(Doc).filter(Doc.org_id == org.id, Doc.id == doc_id, Doc.doc_type == "invoice").with_for_update().first()
    if d is None:
        from accfino.modules.accounting.books.common import BooksError
        raise BooksError("Invoice not found", 404)
    return docs.doc_dict(db, docs.void_doc(db, org, d, user_id), detail=False)


def credit_sales_invoice(db, org, user_id: int, invoice_id: int, *, lines, issue_date, reason: str = ""):
    """Issue an approved credit note against an invoice and apply it (no ledger shortcut: the credit note posts its own journal). Returns the credit note dict."""
    from accfino.modules.accounting.books import docs
    from accfino.modules.accounting.books.common import BooksError
    from accfino.modules.accounting.books.models import Doc
    inv = db.query(Doc).filter(Doc.org_id == org.id, Doc.id == invoice_id, Doc.doc_type == "invoice").with_for_update().first()
    if inv is None:
        raise BooksError("Invoice not found", 404)
    cn = docs.create_doc(db, org, user_id, "credit_note", dict(contact_id=inv.contact_id, issue_date=issue_date, reference=inv.number, notes=(reason or None), lines=lines, source="practice",
                                                               amounts_are="exclusive"), approve=True)
    docs.allocate_credit(db, org, cn, [dict(doc_id=inv.id, amount=cn.total)])
    return docs.doc_dict(db, cn, detail=False)


# ---- request-scoped read memo (additive) -----------------------------------------------------------------------------------------
# A landing page (e.g. Planning overview) asks the ledger the same read-only question from several tiles. Inside `with read_memo(db):` identical
# calls are answered once and each caller receives its own copy. Outside the block nothing is cached. With a remote database every avoided
# statement saves a network round trip.
import contextlib as _cl
import copy as _copy
import functools as _ft


@_cl.contextmanager
def read_memo(db):
    outer = db.info.get("read_memo")
    if outer is None:
        db.info["read_memo"] = {}
    try:
        yield
    finally:
        if outer is None:
            db.info.pop("read_memo", None)


def _memoised(fn):
    @_ft.wraps(fn)
    def wrapper(db, *args, **kwargs):
        memo = db.info.get("read_memo")
        if memo is None:
            return fn(db, *args, **kwargs)
        try:
            key = (fn.__name__, tuple(getattr(a, "id", a) if not isinstance(a, (str, int, float)) and hasattr(a, "id") else a for a in args), tuple(sorted(kwargs.items())))
            hash(key)
        except TypeError:
            return fn(db, *args, **kwargs)
        if key not in memo:
            memo[key] = fn(db, *args, **kwargs)
        return _copy.deepcopy(memo[key])
    return wrapper


for _n in ("profit_and_loss", "system_account_balance", "balances_by_account", "open_items", "ledger_lines", "balance_sheet", "aged_report", "cash_summary",
           "bank_reconciliation_status", "ledger_activity_dates"):
    globals()[_n] = _memoised(globals()[_n])
