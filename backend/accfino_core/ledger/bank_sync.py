"""
accfino_core.ledger.bank_sync
-----------------------------
Posts reconciled bank transactions (legacy `transactions` table) into the ledger.

  money in  (credit):  Dr Bank            total
                       Cr GL account      total - GST   (tax code, GST carried on the line)
                       Cr GST (820)       GST
  money out (debit):   Dr GL account      total - GST
                       Dr GST (820)       GST
                       Cr Bank            total

Special cases
  * Internal transfers -> Transfers Clearing (855); both legs net to zero there.
  * Loan payments with a principal/interest split -> two debit lines.
  * Uncoded or unknown GL accounts -> Suspense (850), reported back to the user.
  * Dates on/before the lock date are never posted or changed ("locked").

Idempotent: each transaction is linked to its journal with a fingerprint.
Unchanged -> skipped. Changed -> original reversed and a new journal posted.
Deleted -> reversed.
"""
import hashlib
from collections import Counter
from datetime import date, datetime

from sqlalchemy import text

from accfino_core import models as m
from accfino_core.coa.au_standard import LEGACY_TYPE_MAP
from accfino_core.ledger.service import LedgerError, money, post_journal, reverse_journal

SOURCE = "bank_txn"


def _fingerprint(t) -> str:
    parts = [t.date, t.bank, t.account, t.description, t.debit, t.credit, t.gl_account, t.gst,
             t.gst_category, t.classification, t.is_loan_payment, t.loan_principal, t.loan_interest,
             t.loan_principal_gl, t.loan_interest_gl]
    return hashlib.sha256("|".join(str(p) for p in parts).encode()).hexdigest()


def _as_date(v) -> date:
    return v.date() if isinstance(v, datetime) else v


class _Resolver:
    def __init__(self, db, org):
        self.db, self.org = db, org
        self.by_name = {a.name.lower(): a for a in db.query(m.LedgerAccount).filter_by(org_id=org.id)}
        self.by_key = {a.system_key: a for a in self.by_name.values() if a.system_key}
        self.codes = {a.code for a in self.by_name.values()}
        self.tax = {t.name.lower(): t for t in db.query(m.TaxCode).filter_by(org_id=org.id)}
        self.legacy_types = None

    def _next_code(self, prefix):
        n = 1
        while f"{prefix}{n:03d}" in self.codes:
            n += 1
        code = f"{prefix}{n:03d}"
        self.codes.add(code)
        return code

    def bank(self, bank, account):
        name = f"{bank} - {account}"[:200]
        acc = self.by_name.get(name.lower())
        if acc is None:
            acc = m.LedgerAccount(org_id=self.org.id, code=self._next_code("B"), name=name,
                                  account_type="bank", account_class="asset", bank_name=bank,
                                  bank_account_ref=account, description="Created by bank transaction sync")
            self.db.add(acc)
            self.db.flush()
            self.by_name[name.lower()] = acc
        return acc

    def gl(self, name):
        """Find the org account for a legacy GL name; auto-create from the legacy COA if known."""
        if not name:
            return None
        acc = self.by_name.get(name.strip().lower())
        if acc is not None:
            return acc
        if self.legacy_types is None:
            try:
                rows = self.db.execute(text("SELECT name, type FROM chart_of_accounts")).fetchall()
            except Exception:
                rows = []
            self.legacy_types = {(n or "").strip().lower(): (n, t) for n, t in rows}
        hit = self.legacy_types.get(name.strip().lower())
        if hit is None:
            return None
        atype = LEGACY_TYPE_MAP.get((hit[1] or "").strip().lower(), "expense")
        acc = m.LedgerAccount(org_id=self.org.id, code=self._next_code("U"), name=hit[0][:200],
                              account_type=atype, account_class=m.ACCOUNT_TYPES[atype],
                              description="Created from legacy chart of accounts during bank sync")
        self.db.add(acc)
        self.db.flush()
        self.by_name[acc.name.lower()] = acc
        return acc

    def system(self, key):
        acc = self.by_key.get(key)
        if acc is None:
            raise LedgerError(f"System account '{key}' is missing from the chart of accounts")
        return acc

    def tax_code(self, name):
        return self.tax.get((name or "").strip().lower())


def _build_lines(t, r: _Resolver):
    """Returns (lines, flags) for one legacy transaction."""
    flags = []
    amount_in, amount_out = money(abs(t.credit or 0)), money(abs(t.debit or 0))
    if amount_in == 0 and amount_out == 0:
        return None, ["zero"]
    inflow = amount_in > 0
    total = amount_in if inflow else amount_out
    bank = r.bank(t.bank or "Bank", t.account or "Account")
    desc = (t.description or "")[:500]
    who = (t.who or None)
    tc = r.tax_code(t.gst_category)
    gst = money(abs(t.gst or 0))
    if gst >= total:
        gst = money(0)
        flags.append("gst_ignored")

    contra_lines = []
    if t.classification and "internal" in t.classification.lower():
        contra_lines.append((r.system("transfer_clearing"), total, None, money(0)))
        gst = money(0)
    elif t.is_loan_payment and (t.loan_principal or t.loan_interest) and not inflow:
        principal, interest = money(t.loan_principal or 0), money(t.loan_interest or 0)
        p_acc = r.gl(t.loan_principal_gl) or r.system("suspense")
        i_acc = r.gl(t.loan_interest_gl) or r.gl("Interest Expense") or r.system("suspense")
        if principal:
            contra_lines.append((p_acc, principal, None, money(0)))
        if interest:
            contra_lines.append((i_acc, interest, None, money(0)))
        diff = total - principal - interest
        if diff != 0:
            if diff < 0:
                return None, ["loan_split_exceeds_payment"]
            contra_lines.append((r.system("suspense"), diff, None, money(0)))
            flags.append("suspense")
        gst = money(0)
    else:
        acc = r.gl(t.gl_account)
        if acc is None:
            acc = r.system("suspense")
            flags.append("suspense")
            gst = money(0)
        net = total - gst
        contra_lines.append((acc, net, tc, gst))

    lines = []
    bank_line = dict(account_id=bank.id, description=desc, contact_name=who)
    bank_line["debit" if inflow else "credit"] = total
    lines.append(bank_line)
    for acc, amt, taxc, taxamt in contra_lines:
        ln = dict(account_id=acc.id, description=desc, contact_name=who,
                  tax_code_id=taxc.id if taxc else None, tax_amount=taxamt)
        ln["credit" if inflow else "debit"] = amt
        lines.append(ln)
    if gst > 0:
        g = dict(account_id=r.system("gst").id, description=f"GST - {desc}"[:500], contact_name=who,
                 tax_code_id=tc.id if tc else None)
        g["credit" if inflow else "debit"] = gst
        lines.append(g)
    return lines, flags


def sync_bank_transactions(db, org, *, user_id=None, created_by=None, dry_run=False):
    from db_app.models.transaction import Transaction
    uid = user_id or org.legacy_user_id
    if not uid:
        return {"ok": False, "detail": "This organisation has no linked bank transaction data"}
    r = _Resolver(db, org)
    links = {l.source_id: l for l in db.query(m.LedgerSourceLink).filter_by(org_id=org.id, source_type=SOURCE)}
    stats = Counter()
    suspense_items = []
    seen = set()
    txns = db.query(Transaction).filter(Transaction.user_id == uid).order_by(Transaction.date, Transaction.id).all()

    for t in txns:
        sid = str(t.id)
        seen.add(sid)
        fp = _fingerprint(t)
        link = links.get(sid)
        if link and link.fingerprint == fp and link.status in ("posted", "skipped"):
            stats["unchanged"] += 1
            continue
        tdate = _as_date(t.date)
        if org.lock_date and tdate <= org.lock_date:
            stats["locked"] += 1
            if link is None and not dry_run:
                db.add(m.LedgerSourceLink(org_id=org.id, source_type=SOURCE, source_id=sid, fingerprint=fp,
                                          status="locked", note="Transaction date is in a locked period"))
            continue
        lines, flags = _build_lines(t, r)
        if lines is None:
            stats[f"skipped_{flags[0]}"] += 1
            if not dry_run:
                if link:
                    link.fingerprint, link.status, link.note = fp, "skipped", flags[0]
                else:
                    db.add(m.LedgerSourceLink(org_id=org.id, source_type=SOURCE, source_id=sid,
                                              fingerprint=fp, status="skipped", note=flags[0]))
            continue
        if "suspense" in flags:
            stats["to_suspense"] += 1
            if len(suspense_items) < 50:
                suspense_items.append({"transaction_id": t.id, "date": tdate.isoformat(),
                                       "description": t.description, "gl_account": t.gl_account})
        if dry_run:
            stats["would_update" if (link and link.journal_id) else "would_post"] += 1
            continue
        if link and link.journal_id:
            old = db.get(m.Journal, link.journal_id)
            if old and old.status == "posted":
                if org.lock_date and old.journal_date <= org.lock_date:
                    stats["locked"] += 1
                    continue
                reverse_journal(db, org, old.id, narration=f"Bank transaction {sid} changed - reversal",
                                created_by=created_by)
        j = post_journal(db, org, journal_date=tdate, lines=lines,
                         narration=(t.description or "Bank transaction")[:500],
                         source_type=SOURCE, source_ref=f"txn:{sid}", created_by=created_by)
        if link and link.journal_id:
            stats["updated"] += 1
            link.journal_id, link.fingerprint, link.status, link.note = j.id, fp, "posted", None
        elif link:   # previously skipped or locked, now posted for the first time
            stats["posted"] += 1
            link.journal_id, link.fingerprint, link.status, link.note = j.id, fp, "posted", None
        else:
            stats["posted"] += 1
            db.add(m.LedgerSourceLink(org_id=org.id, source_type=SOURCE, source_id=sid,
                                      journal_id=j.id, fingerprint=fp, status="posted"))

    # transactions deleted from the legacy table -> reverse their journals
    for sid, link in links.items():
        if sid in seen or link.status != "posted" or not link.journal_id:
            continue
        old = db.get(m.Journal, link.journal_id)
        if old is None or old.status != "posted":
            continue
        if org.lock_date and old.journal_date <= org.lock_date:
            stats["locked"] += 1
            continue
        if dry_run:
            stats["would_reverse_deleted"] += 1
            continue
        reverse_journal(db, org, old.id, narration=f"Bank transaction {sid} deleted - reversal",
                        created_by=created_by)
        link.status, link.note = "skipped", "source deleted"
        stats["reversed_deleted"] += 1

    if not dry_run:
        db.flush()
    return {"ok": True, "dry_run": dry_run, "transactions": len(txns), **dict(stats),
            "suspense_items": suspense_items}
