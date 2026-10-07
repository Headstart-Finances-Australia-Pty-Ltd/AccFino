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

