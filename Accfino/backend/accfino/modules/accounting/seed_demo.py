"""
seed_demo - a complete, internally consistent demo organisation for testing every Books & Accounting module and report.

Everything goes through the SAME service layer the app uses (documents, payments, bank matching, expenses, inventory,
fixed assets, ledger posting), so each journal is validated and balanced exactly as production data would be, and every
sub-ledger control check (AR, AP, inventory, fixed assets, GST, cash) agrees by construction.

  python -m accfino_core.seed_demo --user demo@accfino.com            # new org for that user (created if missing, password Demo@12345)
  python -m accfino_core.seed_demo --user you@company.com --org-name "Test Co"
  python -m accfino_core.seed_demo --user demo@accfino.com --today 2026-09-30
  python -m accfino_core.seed_demo --sqlite /tmp/demo.db --verify     # offline check, no PostgreSQL needed

The data runs from 1 July of the PREVIOUS financial year up to "today" (default: the real date), so every report's default
period (this financial year to date) and last year's comparatives are both populated. Amounts are fictional.

What you get
  contacts & documents  11 customers, 11 suppliers, ~350 invoices, ~150 bills, credit notes/supplier credits, quotes, purchase orders,
                        drafts, a voided invoice, partial / late / unpaid / over-payments (all aged buckets populated), a refund
  banking               3 accounts (cheque, savings, credit card), statement lines, reconciled + unreconciled + excluded lines,
                        outstanding cheques, transfers, bank rules-style direct coding, GST-free and GST items, duplicates and stale items
  payroll journals      monthly pay runs for 6 staff (gross, PAYG, net, super), PAYG + super remittances, BAS payments, loan, dividend
  inventory             4 stock items: opening stock, purchases, sales at average cost, stocktake adjustment
  fixed assets          5 assets (SL + diminishing value), monthly depreciation, a purchase this year, a disposal
  expenses              claims in every status (draft, submitted, approved, rejected, paid) with receipts and mileage
  manual journals       prepayment releases, accrual + reversal, provisions, income-tax provision, director's loan
  budgets               last year's budget (with realistic +/- variances) and this year's (generated from last year + 8%)
"""
import argparse
import calendar
import random
import sys
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal

from accfino.core import models as m
from accfino.modules.accounting.models import ledger as lm
from accfino.modules.accounting.assets import models as fa_models
from accfino.modules.accounting.assets import service as FA
from accfino.modules.accounting.books import banking as K
from accfino.modules.accounting.books import docs as D
from accfino.modules.accounting.books import expenses as EX
from accfino.modules.accounting.books import models as b
from accfino.modules.accounting.books import reports as R
from accfino.modules.accounting.books import reports_extra as X
from accfino.modules.accounting.books.common import BooksError, money
from accfino.modules.accounting.inventory import models as inv_models
from accfino.modules.accounting.inventory import service as INV
from accfino.modules.accounting.ledger import fx as FX
from accfino.modules.accounting.ledger import journal_tools as JT
from accfino.modules.accounting.ledger import service as L

Z = Decimal("0.00")
DEMO_PASSWORD = "Demo@12345"


@dataclass
class Ctx:
    user_id: int
    username: str
    org: object
    role: str = "owner"
    is_admin: bool = False


def _eom(d):
    return date(d.year, d.month, calendar.monthrange(d.year, d.month)[1])


def _add_months(d, n):
    y, mo = divmod(d.month - 1 + n, 12)
    return date(d.year + y, mo + 1, 1)


def _last_business_day(d):
    e = _eom(d)
    while e.weekday() >= 5:
        e -= timedelta(days=1)
    return e


def _r(x):
    return money(Decimal(str(x)))


CUSTOMERS = [
    # name, kind, base monthly frequency, terms, region, pay behaviour (avg extra days), abn
    ("Harbour Digital Pty Ltd", "services", 1.0, 14, "Sydney", 2, "51 824 753 556"),
    ("Northshore Medical Group", "mixed", 0.9, 30, "Sydney", 6, "33 102 417 032"),
    ("Coastal Retail Co", "products", 0.9, 14, "Brisbane", 4, "12 004 044 937"),
    ("Summit Engineering Pty Ltd", "services", 0.85, 30, "Melbourne", 9, "98 007 152 349"),
    ("Bluegum Hospitality Group", "products", 0.8, 7, "Melbourne", 3, "64 603 476 918"),
    ("Pacific Rim Traders Ltd", "export", 0.7, 30, "Sydney", 12, None),
    ("Riverside City Council", "services", 0.75, 30, "Brisbane", 15, "44 110 219 732"),
    ("Kestrel Logistics", "mixed", 0.8, 14, "Brisbane", 5, "27 006 284 291"),
    ("Lumen Education Trust", "training", 0.6, 30, "Melbourne", 7, "58 090 118 645"),
    ("Metro Fitness Franchise", "products", 0.7, 14, "Sydney", 8, "70 120 903 517"),
    ("Delta Constructions Pty Ltd", "services", 0.45, 30, "Melbourne", 70, "82 005 421 076"),   # the chronic slow payer
]
SUPPLIERS = [
    # name, terms, abn
    ("Precinct Property Management", 30, "16 123 456 782"),
    ("Telstra Business", 14, "33 051 775 556"),
    ("AGL Energy", 21, "74 115 061 375"),
    ("Cloudware Software Pty Ltd", 30, "41 632 874 205"),
    ("Allianz Business Insurance", 30, "15 000 122 850"),
    ("Baker & Co Chartered Accountants", 14, "88 731 208 995"),
    ("Adwave Digital Marketing", 30, "23 615 390 128"),
    ("Apex Subcontractors Pty Ltd", 30, "67 402 155 630"),
    ("OfficeMax Supplies", 30, "90 004 551 217"),
    ("Global Widgets Wholesale", 0, "35 110 776 402"),
    ("AusPost Freight", 14, "28 864 970 579"),
]
PRODUCTS = [  # sku, name, unit cost, sale price
    ("CHR-100", "Ergonomic Office Chair", 182, 349),
    ("DSK-200", "Standing Desk Frame", 262, 495),
    ("MON-300", "27in LED Monitor", 212, 399),
    ("DCK-400", "USB-C Docking Station", 96, 189),
]
STAFF = [("Sarah Chen", 135000), ("Marcus Doyle", 98000), ("Aisha Rahman", 90000), ("Liam O'Brien", 78000), ("Emily Watson", 70000), ("Jack Nguyen", 64000)]


def _payg_rate(annual):
    return Decimal("0.16") if annual <= 45000 else Decimal("0.245") if annual <= 90000 else Decimal("0.295") if annual <= 135000 else Decimal("0.335")


class Seeder:
    def __init__(self, db, org, user_id, today, log=print, foreign_demo=True):
        self.foreign_demo = foreign_demo
        self.db, self.org, self.uid, self.today, self.log = db, org, user_id, today, log
        self.rng = random.Random(today.toordinal())
        self.ctx = Ctx(user_id, "owner", org)
        self.fy_start = date(today.year if today.month >= 7 else today.year - 1, 7, 1)
        self.start = date(self.fy_start.year - 1, 7, 1)
        self.months = []
        d = self.start
        while d <= today:
            self.months.append(d)
            d = _add_months(d, 1)
        self.acc = {}                # code -> LedgerAccount
        self.contacts = {}
        self.events = []             # bank statement events, see _event()
        self.payments = []
        self.counts = {}

    # ------------------------------------------------------------------ small helpers
    def a(self, code):
        return self.acc[code]

    def bump(self, k, n=1):
        self.counts[k] = self.counts.get(k, 0) + n

    def journal(self, when, lines, narration, source, ref=None):
        reference = f"PAY-{ref.split(':')[1]}" if source == "payroll_run" and ref and ":" in ref else None
        j = L.post_journal(self.db, self.org, journal_date=when, lines=lines, narration=narration, source_type=source, source_ref=ref, created_by=self.uid, reference=reference)
        self.bump("journals")
        return j

    def dl(self, code, dr=None, cr=None, desc=None, tax=None, tax_amount=None, contact=None):
        d = dict(account_id=self.a(code).id, description=desc)
        if dr is not None:
            d["debit"] = dr
        if cr is not None:
            d["credit"] = cr
        if tax:
            d["tax_code_id"] = self.tax[tax].id
            d["tax_amount"] = tax_amount or Z
        if contact:
            d["contact_name"] = contact
        return d

    def event(self, account, when, desc, amount, *, payment=None, code=None, batch=1, reconcile=True, exclude=False):
        """A bank statement line. batch 1 = has (or will have) a ledger journal to adopt/match; batch 2 = coded from the line itself."""
        self.events.append(dict(account=account, date=when, desc=desc, amount=money(amount), payment=payment, code=code, batch=batch, reconcile=reconcile, exclude=exclude, seq=len(self.events)))

    # ------------------------------------------------------------------ setup
    def setup(self):
        db, org = self.db, self.org
        org.gst_registered, org.gst_basis, org.fy_end_month, org.base_currency = True, "accrual", 6, "AUD"
        org.entity_type = org.entity_type or "company"
        from accfino.modules.accounting.ledger.seed import seed_org_ledger
        seed_org_ledger(db, org)
        self.tax = {t.code: t for t in db.query(lm.TaxCode).filter_by(org_id=org.id)}
        # bank accounts + a couple of extra accounts the standard chart does not carry
        extra = [("090", "Business Cheque Account", "bank", "NAB", "082-001 4477 1290"), ("091", "Business Savings Account", "bank", "NAB", "082-001 4477 3381"),
                 ("092", "Company Credit Card", "credit_card", "NAB", "5163 **** **** 8842"), ("805", "Accrued Expenses", "current_liability", None, None),
                 ("612", "Bad Debts Expense", "expense", None, None)]
        for code, name, typ, bank, ref in extra:
            if not db.query(lm.LedgerAccount.id).filter_by(org_id=org.id, code=code).first() and not db.query(lm.LedgerAccount.id).filter_by(org_id=org.id, name=name).first():
                db.add(lm.LedgerAccount(org_id=org.id, code=code, name=name, account_type=typ, account_class=lm.ACCOUNT_TYPES[typ], bank_name=bank, bank_account_ref=ref,
                                       default_tax_code_id=self.tax["BASEXCLUDED"].id if typ not in ("bank", "credit_card") else None))
        db.flush()
        self.acc = {a.code: a for a in db.query(lm.LedgerAccount).filter_by(org_id=org.id)}
        # tracking
        self.track = {}
        for cat, opts in (("Region", ["Sydney", "Melbourne", "Brisbane"]), ("Department", ["Consulting", "Products", "Admin"])):
            c = db.query(lm.TrackingCategory).filter_by(org_id=org.id, name=cat).first() or lm.TrackingCategory(org_id=org.id, name=cat)
            db.add(c)
            db.flush()
            for o in opts:
                op = db.query(lm.TrackingOption).filter_by(category_id=c.id, name=o).first() or lm.TrackingOption(category_id=c.id, name=o)
                db.add(op)
                db.flush()
                self.track[o] = op.id
        # contacts
        for name, kind, freq, terms, region, late, abn in CUSTOMERS:
            self._contact(name, True, False, terms, abn)
        for name, terms, abn in SUPPLIERS:
            self._contact(name, False, True, terms, abn)
        db.flush()
        self.cheque, self.savings, self.card = self.a("090"), self.a("091"), self.a("092")
        self.log(f"  setup: chart, {len(self.acc)} accounts, {len(self.contacts)} contacts")

    def _contact(self, name, cust, sup, terms, abn):
        c = self.db.query(b.Contact).filter_by(org_id=self.org.id, name=name).first()
        if c is None:
            slug = "".join(ch for ch in name.lower() if ch.isalnum())[:14]
            c = b.Contact(org_id=self.org.id, name=name, is_customer=cust, is_supplier=sup, terms_days=terms, abn=abn, email=f"accounts@{slug}.example.com.au",
                          phone=f"02 {self.rng.randint(8000, 9999)} {self.rng.randint(1000, 9999)}", address="1 Example St, Sydney NSW 2000")
            self.db.add(c)
        self.contacts[name] = c

    # ------------------------------------------------------------------ fixed assets + opening balances
    def opening(self):
        db, org = self.db, self.org
        S = "straight_line"
        specs = [("Office fit-out & furniture", "office_equipment", "710", "711", date(2023, 7, 1), 18000, 0, S, 120, None),
                 ("Laptops & workstations", "computer_equipment", "720", "721", date(2024, 1, 15), 12000, 0, S, 36, None),
                 ("Delivery van", "motor_vehicle", "730", "731", date(2023, 10, 10), 45000, 5000, "diminishing_value", None, Decimal("20")),
                 ("Old plotter printer", "office_equipment", "710", "711", date(2022, 7, 1), 4000, 0, S, 60, None)]
        self.assets = []
        cost_by, acc_by = {}, {}
        for name, cat, ac, dc, pd_, cost, resid, meth, life, dv in specs:
            asset = FA.register(db, org, self.uid, dict(name=name, category=cat, asset_account=ac, depreciation_account=dc, expense_account="416", purchase_date=pd_, cost=cost,
                                                        residual_value=resid, method=meth, effective_life_months=life, dv_rate_pct=dv))
            cum = FA.cumulative_depreciation(asset, self.start - timedelta(days=1))
            asset.opening_accumulated_depreciation = asset.accumulated_depreciation = cum
            asset.last_depreciation_date = self.start - timedelta(days=1)
            self.assets.append(asset)
            cost_by[ac] = cost_by.get(ac, 0) + cost
            acc_by[dc] = acc_by.get(dc, Z) + cum
            self.bump("assets")
        db.flush()
        # opening stock: registered now, posted below against retained earnings
        self.items = {}
        for sku, name, cost, price in PRODUCTS:
            it = INV.create_item(db, org, dict(sku=sku, name=name, sale_price=price, sales_account="201", sales_tax_code="OUTPUT", purchase_tax_code="INPUT"))
            self.items[sku] = it
        db.flush()
        cash_open = {"090": Decimal("85000.00"), "091": Decimal("40000.00")}
        loan, capital = Decimal("60000.00"), Decimal("50000.00")
        lines = [self.dl(c, dr=v, desc="Opening balance") for c, v in cash_open.items()]
        lines += [self.dl(c, dr=money(v), desc="Opening balance") for c, v in cost_by.items()]
        lines += [self.dl(c, cr=v, desc="Opening balance") for c, v in acc_by.items()]
        lines += [self.dl("900", cr=loan, desc="Opening balance"), self.dl("970", cr=capital, desc="Opening balance")]
        drs = sum((l.get("debit", Z) for l in lines), Z)
        crs = sum((l.get("credit", Z) for l in lines), Z)
        lines.append(self.dl("960", cr=drs - crs, desc="Opening retained earnings"))
        self.journal(self.start, lines, "Opening balances", "opening_balance", "opening")
        self.event(self.cheque, self.start, "Opening balance", cash_open["090"])
        self.event(self.savings, self.start, "Opening balance", cash_open["091"])
        for sku, qty, uc in (("CHR-100", 40, 170), ("DSK-200", 25, 245), ("MON-300", 30, 198), ("DCK-400", 60, 90)):
            INV.buy(db, org, self.uid, self.items[sku], mv_date=self.start, quantity=qty, unit_cost=uc, credit_account="960", reference="Opening stock", kind="opening")
        self.opening_cash = cash_open
        self.log(f"  opening balances + {len(self.assets)} assets + opening stock")

    # ------------------------------------------------------------------ sales
    def _tracks(self, region, dept):
        return [self.track[region], self.track[dept]]

    def sales(self):
        rng, db, org = self.rng, self.db, self.org
        self.open_invoices = []
        products = list(self.items.values())
        for idx, mstart in enumerate(self.months):
            growth = 1 + 0.012 * idx
            self._stock_buys(mstart)
            for name, kind, freq, terms, region, late, abn in CUSTOMERS:
                if rng.random() > freq:
                    continue
                for n in range(2 if ((kind in ("products", "mixed") and rng.random() < 0.35) or (kind == "services" and rng.random() < 0.2)) else 1):
                    day = rng.randint(1, min(28, calendar.monthrange(mstart.year, mstart.month)[1]))
                    when = date(mstart.year, mstart.month, day)
                    if when > self.today:
                        continue
                    lines, stock_sales = self._invoice_lines(kind, region, growth, products, when)
                    if not lines:
                        continue
                    try:
                        inv = D.create_doc(db, org, self.uid, "invoice", dict(customer=name, issue_date=when, reference=f"PO-{rng.randint(10000, 99999)}", lines=lines))
                    except BooksError as e:
                        self.log(f"    ! invoice skipped: {e}")
                        continue
                    self.bump("invoices")
                    for it, q in stock_sales:
                        INV.sell(db, org, self.uid, it, mv_date=when, quantity=q, reference=inv.number, note=f"Sold on {inv.number}")
                    self.open_invoices.append((inv, late, terms))
        self._sales_extras()
        self.log(f"  sales: {self.counts.get('invoices', 0)} invoices")

    def _stock_buys(self, ms):
        """Cash-on-delivery stock purchases on the 1st of each month, sized to roughly replace what the month sells (so stock stays sensible)."""
        rng = self.rng
        for sku, name, cost, price in PRODUCTS:
            if rng.random() < 0.85 and ms <= self.today:
                q, uc = rng.randint(12, 32), _r(cost * rng.uniform(0.96, 1.05))
                INV.buy(self.db, self.org, self.uid, self.items[sku], mv_date=ms, quantity=q, unit_cost=uc, credit_account="090", reference=f"COD {ms:%d%b}", note="Global Widgets Wholesale - cash on delivery")
                self.event(self.cheque, ms, "Global Widgets Wholesale COD", -(q * uc))
                self.bump("stock_buys")

    def _invoice_lines(self, kind, region, growth, products, when):
        rng = self.rng
        lines, stock = [], []
        t_c = self._tracks(region, "Consulting")
        t_p = self._tracks(region, "Products")

        def svc(desc, hrs, rate, tax="OUTPUT", acct="200", tr=t_c):
            return dict(description=desc, qty=hrs, unit_price=rate, account=acct, tax_code=tax, tracking_option_ids=tr)
        month = when.strftime("%B %Y")
        if kind in ("services", "mixed"):
            lines.append(svc(f"Consulting services - {month}", int(rng.randint(28, 72) * growth), 165))
            if rng.random() < 0.35:
                lines.append(svc("Project delivery milestone", 1, _r(rng.randint(3000, 9000) * growth)))
        if kind in ("products", "mixed"):
            for it in rng.sample(products, k=rng.randint(1, 3)):
                q = rng.randint(3, 14)
                q = min(q, int(it.quantity_on_hand))
                if q >= 1:
                    lines.append(dict(description=f"{it.name} ({it.sku})", qty=q, unit_price=it.sale_price, account="201", tax_code="OUTPUT", tracking_option_ids=t_p))
                    stock.append((it, q))
        if kind == "export":
            lines.append(svc(f"Software licence & support - export - {month}", 1, _r(rng.randint(6000, 15000) * growth), tax="EXPORT"))
        if kind == "training":
            lines.append(svc(f"Training workshop - {month}", rng.randint(1, 4), 2400, tax="EXEMPTOUTPUT"))
        return lines, stock

    def _sales_extras(self):
        """Quotes, drafts, a voided invoice, credit notes (applied, unapplied and refunded), an over-payment."""
        rng, db, org = self.rng, self.db, self.org
        recent = self.today - timedelta(days=12)
        t = self._tracks("Sydney", "Consulting")
        line = lambda desc, q, p, tax="OUTPUT": [dict(description=desc, qty=q, unit_price=p, account="200", tax_code=tax, tracking_option_ids=t)]
        q1 = D.create_doc(db, org, self.uid, "quote", dict(customer="Harbour Digital Pty Ltd", issue_date=recent, lines=line("Website replatform - discovery & build", 1, 18500)))
        D.mark_sent(db, q1)
        q2 = D.create_doc(db, org, self.uid, "quote", dict(customer="Summit Engineering Pty Ltd", issue_date=recent - timedelta(days=20), lines=line("Data migration project", 1, 32000)))
        D.mark_sent(db, q2)
        D.quote_decision(db, q2, "accepted")
        q3 = D.create_doc(db, org, self.uid, "quote", dict(customer="Bluegum Hospitality Group", issue_date=recent - timedelta(days=45), lines=line("POS integration", 1, 7400)))
        D.mark_sent(db, q3)
        D.quote_decision(db, q3, "declined")
        # an accepted quote converted to an invoice
        q4 = D.create_doc(db, org, self.uid, "quote", dict(customer="Northshore Medical Group", issue_date=self.today - timedelta(days=50), lines=line("Compliance audit & report", 1, 12600)))
        D.mark_sent(db, q4)
        D.quote_decision(db, q4, "accepted")
        conv = D.convert(db, org, q4, self.uid, approve=False)
        conv.issue_date, conv.due_date = self.today - timedelta(days=38), self.today - timedelta(days=8)
        D.approve_doc(db, org, conv, self.uid)
        self.open_invoices.append((conv, 6, 30))
        # drafts (no ledger effect)
        D.create_doc(db, org, self.uid, "invoice", dict(customer="Kestrel Logistics", issue_date=self.today - timedelta(days=2), lines=line("Consulting - draft for review", 20, 165)), approve=False)
        D.create_doc(db, org, self.uid, "invoice", dict(customer="Lumen Education Trust", issue_date=self.today - timedelta(days=1), lines=line("Training workshop - draft", 2, 2400, "EXEMPTOUTPUT")), approve=False)
        # a voided invoice
        v = D.create_doc(db, org, self.uid, "invoice", dict(customer="Riverside City Council", issue_date=self.start + timedelta(days=200), lines=line("Consulting - raised in error", 10, 165)))
        D.void_doc(db, org, v, self.uid)
        self.bump("voided")
        # credit notes: pick paid-late-safe candidates (recent, unpaid invoices are chosen later by the payment step, so use older ones we will leave open)
        cands = [i for i, _, _ in self.open_invoices if 40 < (self.today - i.issue_date).days < 260]
        rng.shuffle(cands)
        self.credit_targets = []
        for inv_, purpose in zip(cands[:3], ("applied", "unapplied", "refunded")):
            amt = _r(min(inv_.total * Decimal("0.25"), Decimal("1800")))
            cn = D.create_doc(db, org, self.uid, "credit_note", dict(customer=inv_.contact.name, issue_date=min(inv_.issue_date + timedelta(days=20), self.today),
                                                                   reference=f"Credit for {inv_.number}", lines=[dict(description=f"Credit against {inv_.number} - service credit", qty=1, unit_price=amt, account="200", tax_code="OUTPUT",
                                                                                                                  tracking_option_ids=t)]))
            self.bump("credit_notes")
            self.credit_targets.append((cn, inv_, purpose))

    # ------------------------------------------------------------------ purchases
    def purchases(self):
        rng, db, org = self.rng, self.db, self.org
        self.open_bills = []

        def bill(supplier, when, lines, ref, amounts="exclusive"):
            if when > self.today:
                return None
            try:
                bl = D.create_doc(db, org, self.uid, "bill", dict(supplier=supplier, issue_date=when, reference=ref, lines=lines, amounts_are=amounts))
            except BooksError as e:
                self.log(f"    ! bill skipped: {e}")
                return None
            self.bump("bills")
            self.open_bills.append(bl)
            return bl

        ln = lambda desc, amt, acct, tax="INPUT", tr=None: [dict(description=desc, qty=1, unit_price=_r(amt), account=acct, tax_code=tax, tracking_option_ids=tr)]
        adm = [self.track["Admin"]]
        for idx, ms in enumerate(self.months):
            mon = ms.strftime("%b %Y")
            first = ms + timedelta(days=rng.randint(0, 3))
            bill("Precinct Property Management", first, ln(f"Office rent - {mon}", 6800 if ms < date(self.fy_start.year, 7, 1) else 7100, "469", tr=adm), f"PPM-{ms:%y%m}")
            bill("Telstra Business", ms + timedelta(days=rng.randint(6, 12)), ln(f"Telephone & internet - {mon}", rng.randint(390, 460), "489", tr=adm), f"TEL-{rng.randint(100000, 999999)}")
            winter = ms.month in (6, 7, 8, 12, 1, 2)
            bill("AGL Energy", ms + timedelta(days=rng.randint(10, 18)), ln(f"Electricity - {mon}", rng.randint(520, 760) + (140 if winter else 0), "445", tr=adm), f"AGL-{rng.randint(100000, 999999)}")
            bill("Cloudware Software Pty Ltd", ms + timedelta(days=rng.randint(1, 5)), ln(f"SaaS subscriptions - {mon}", 1250 + 40 * (idx // 4), "485", tr=adm), f"CW-{ms:%y%m}-{rng.randint(10, 99)}")
            bill("Adwave Digital Marketing", ms + timedelta(days=rng.randint(4, 20)), ln(f"Campaign management - {mon}", rng.randint(1800, 4200), "401", tr=[self.track["Consulting"]]), f"ADW-{rng.randint(1000, 9999)}")
            bill("Apex Subcontractors Pty Ltd", ms + timedelta(days=rng.randint(8, 24)), ln(f"Subcontract delivery - {mon}", rng.randint(5000, 11000) * (1 + 0.012 * idx), "313", tr=[self.track["Consulting"]]), f"APX-{rng.randint(10000, 99999)}")
            office = rng.randint(150, 900) if idx != 7 else 8900                     # one genuine outlier for the validation report
            bill("OfficeMax Supplies", ms + timedelta(days=rng.randint(2, 25)), ln(f"Stationery & office supplies - {mon}", office, "453", tr=adm), f"OM-{rng.randint(10000, 99999)}")
            bill("AusPost Freight", ms + timedelta(days=rng.randint(3, 26)), ln(f"Freight & courier - {mon}", rng.randint(180, 420), "425", tr=[self.track["Products"]]), f"AP-{rng.randint(10000, 99999)}")
            bill("Baker & Co Chartered Accountants", ms + timedelta(days=rng.randint(10, 20)), ln(f"Bookkeeping & BAS preparation - {mon}", 650, "412", tr=adm), f"BAK-{ms:%y%m}")
            if ms.month in (9, 12, 3, 6):
                bill("Baker & Co Chartered Accountants", ms + timedelta(days=24), ln(f"Quarterly advisory - {mon}", 1800, "412", tr=adm), f"BAK-Q{ms:%y%m}")
        # insurance: annual premium prepaid (Jul each FY), released monthly by journal below
        self.prepaid = []
        for fy in (self.start, date(self.start.year + 1, 7, 1)):
            prem = 6600 if fy == self.start else 6900
            bl = bill("Allianz Business Insurance", fy + timedelta(days=4), ln(f"Business insurance premium {fy.year}/{str(fy.year + 1)[2:]} (prepaid)", prem, "620"), f"ALZ-{fy.year}")
            if bl:
                self.prepaid.append((fy + timedelta(days=4), Decimal(prem) / 12))
        # duplicate-looking bills (same supplier + total within days, different references)
        dup_day = self.today - timedelta(days=118)
        bill("Baker & Co Chartered Accountants", dup_day, ln("Tax planning workshop", 1800, "412"), "BAK-TP-01")
        bill("Baker & Co Chartered Accountants", dup_day + timedelta(days=3), ln("Tax planning workshop", 1800, "412"), "BAK-TP-02")
        # capital purchase this year -> registered as an asset
        cap_day = max(self.fy_start + timedelta(days=42), self.start)
        cap = bill("Cloudware Software Pty Ltd" if False else "OfficeMax Supplies", cap_day if cap_day <= self.today else self.today - timedelta(days=3),
                   ln("Laptop fleet (5 x MacBook Pro 14in)", 9800, "720", tax="CAPEXINPUT"), "OM-CAPEX-01")
        if cap:
            self.new_asset = FA.register(db, org, self.uid, dict(name="Laptop fleet (5 x MacBook Pro)", category="computer_equipment", asset_account="720", depreciation_account="721",
                                                                  expense_account="416", purchase_date=cap.issue_date, cost=9800, residual_value=0, method="straight_line", effective_life_months=36))
            self.bump("assets")
        # purchase orders: one open, one converted to a bill
        po1 = D.create_doc(db, org, self.uid, "purchase_order", dict(supplier="Apex Subcontractors Pty Ltd", issue_date=self.today - timedelta(days=9), lines=ln("Q4 delivery capacity (PO)", 14500, "313")), approve=False)
        D.approve_doc(db, org, po1, self.uid)
        po2 = D.create_doc(db, org, self.uid, "purchase_order", dict(supplier="Adwave Digital Marketing", issue_date=self.today - timedelta(days=40), lines=ln("Brand refresh campaign (PO)", 5200, "401")), approve=False)
        D.approve_doc(db, org, po2, self.uid)
        cb = D.convert(db, org, po2, self.uid, approve=False)
        cb.issue_date, cb.due_date, cb.reference = self.today - timedelta(days=24), self.today + timedelta(days=6), "ADW-BRAND-77"
        D.approve_doc(db, org, cb, self.uid)
        self.open_bills.append(cb)
        # a draft bill and a supplier credit
        D.create_doc(db, org, self.uid, "bill", dict(supplier="AGL Energy", issue_date=self.today - timedelta(days=1), reference="AGL-DRAFT", lines=ln("Electricity - awaiting approval", 690, "445")), approve=False)
        sc_when = self.today - timedelta(days=75)
        self.supplier_credit = D.create_doc(db, org, self.uid, "supplier_credit", dict(supplier="Adwave Digital Marketing", issue_date=sc_when, reference="ADW-CR-02", lines=ln("Credit for under-delivered campaign", 550, "401")))
        self.bump("supplier_credits")
        self.log(f"  purchases: {self.counts.get('bills', 0)} bills, {self.counts.get('stock_buys', 0)} stock buys")

    # ------------------------------------------------------------------ settlement (payments, credits, refund, over-payment)
    def settlements(self):
        rng, db, org = self.rng, self.db, self.org
        recon_cut = self.today - timedelta(days=25)
        stale_pick = 0

        def bank_event(pay, desc, sign):
            nonlocal stale_pick
            # recent payments have not all cleared the bank yet; a handful of older ones are deliberately left unreconciled
            recent_out = sign < 0 and (self.today - pay.payment_date).days <= 5
            if recent_out:
                return                                                      # outstanding cheque: in the ledger, not yet on the statement
            rec = pay.payment_date <= recon_cut or rng.random() < 0.4
            if pay.payment_date <= recon_cut and (stale_pick := stale_pick + 1) % 37 == 0:
                rec = False
            self.event(self.cheque, pay.payment_date, desc, sign * pay.amount, payment=pay, reconcile=rec)

        credit_map = {}
        for cn, inv_, purpose in getattr(self, "credit_targets", []):
            credit_map[inv_.id] = (cn, purpose)
        for inv_, late, terms in self.open_invoices:
            if inv_.status != "approved":
                continue
            owing = inv_.amount_due
            if inv_.id in credit_map:
                cn, purpose = credit_map[inv_.id]
                if purpose == "applied":
                    D.allocate_credit(db, org, cn, [dict(doc_id=inv_.id, amount=min(cn.total, owing))], alloc_date=max(cn.issue_date, inv_.issue_date))
                    owing = inv_.amount_due
                    db.refresh(cn)
                    if owing <= 0:
                        continue
            slow = late >= 60
            if slow:
                pay_off = terms + rng.randint(25, 110)
                will_pay = rng.random() < 0.45
            else:
                pay_off = max(1, terms + rng.randint(-4, late + 6))
                will_pay = (self.today - inv_.issue_date).days > pay_off or rng.random() < 0.15
            pdate = inv_.issue_date + timedelta(days=pay_off)
            if not will_pay or pdate > self.today:
                continue
            partial = rng.random() < 0.08 and owing > 500
            amt = _r(owing * Decimal("0.6")) if partial else owing
            pay = D.record_payment(db, org, self.uid, kind="receive", contact=inv_.contact, pay_date=pdate, amount=amt, bank_ref=self.cheque.id,
                                   reference=f"EFT {inv_.number}", allocations=[dict(doc_id=inv_.id, amount=amt)])
            self.bump("receipts")
            self._receipts = getattr(self, "_receipts", []) + [pay]
            bank_event(pay, f"EFT {inv_.contact.name} {inv_.number}", 1)
            if partial and rng.random() < 0.55 and pdate + timedelta(days=20) <= self.today:
                rest = inv_.amount_due
                p2 = D.record_payment(db, org, self.uid, kind="receive", contact=inv_.contact, pay_date=pdate + timedelta(days=20), amount=rest, bank_ref=self.cheque.id,
                                      reference=f"EFT {inv_.number} balance", allocations=[dict(doc_id=inv_.id, amount=rest)])
                self.bump("receipts")
                bank_event(p2, f"EFT {inv_.contact.name} {inv_.number} balance", 1)
        # a customer who paid the same invoice twice: an identical second payment, held as an unallocated credit
        cand = [p for p in getattr(self, "_receipts", []) if 20 < (self.today - p.payment_date).days < 100 and p.amount > 1500]
        if cand:
            first = cand[0]
            dupe = D.record_payment(db, org, self.uid, kind="receive", contact=first.contact, pay_date=first.payment_date, amount=first.amount, bank_ref=self.cheque.id,
                                    reference=f"{first.reference} (paid twice)", allocations=[], overpayment=True)
            self.event(self.cheque, dupe.payment_date, f"{first.reference} duplicate receipt", dupe.amount, payment=dupe, reconcile=True)
        # unapplied credit stays open; refunded credit is paid back to the customer
        for cn, inv_, purpose in getattr(self, "credit_targets", []):
            if purpose == "refunded":
                rd = min(cn.issue_date + timedelta(days=6), self.today)
                pay = D.record_payment(db, org, self.uid, kind="refund_out", contact=cn.contact, pay_date=rd, amount=cn.total, bank_ref=self.cheque.id,
                                       reference=f"Refund {cn.number}", allocations=[dict(doc_id=cn.id, amount=cn.total)])
                bank_event(pay, f"Refund to {cn.contact.name} {cn.number}", -1)
        # a customer deposit received before the invoice exists: an unallocated payment
        dep = D.record_payment(db, org, self.uid, kind="receive", contact=self.contacts["Kestrel Logistics"], pay_date=self.today - timedelta(days=9), amount=Decimal("3300.00"),
                               bank_ref=self.cheque.id, reference="Deposit - Q4 project", allocations=[], overpayment=True)
        bank_event(dep, "Deposit Kestrel Logistics", 1)
        # bills
        sc = self.supplier_credit
        target = next((bl for bl in self.open_bills if bl.contact_id == sc.contact_id and bl.status == "approved" and bl.issue_date >= sc.issue_date and bl.total > sc.total), None)
        if target:
            D.allocate_credit(db, org, sc, [dict(doc_id=target.id, amount=sc.total)], alloc_date=target.issue_date)
        unpaid_overdue = {"Cloudware Software Pty Ltd": 0}                         # keep the two most recent Cloudware bills before today unpaid -> overdue buckets
        for bl in sorted(self.open_bills, key=lambda x: x.issue_date):
            if bl.status != "approved":
                continue
            terms = bl.contact.terms_days or 0
            if bl.contact.name in unpaid_overdue and (self.today - bl.issue_date).days < 75:
                continue
            if bl.doc_type == "bill" and bl.reference in ("BAK-TP-02",):
                continue                                                         # leave the duplicate-looking bill unpaid so the validation report has something to say
            pay_off = max(0, terms + rng.randint(-6, 9))
            pdate = bl.issue_date + timedelta(days=pay_off)
            if pdate > self.today or (rng.random() < 0.05 and (self.today - bl.issue_date).days < 120):
                continue
            owing = bl.amount_due
            if owing <= 0:
                continue
            pay = D.record_payment(db, org, self.uid, kind="pay", contact=bl.contact, pay_date=pdate, amount=owing, bank_ref=self.cheque.id, reference=f"EFT {bl.reference or bl.number}",
                                   allocations=[dict(doc_id=bl.id, amount=owing)])
            self.bump("supplier_payments")
            bank_event(pay, f"EFT {bl.contact.name} {bl.reference or bl.number}", -1)
        self.log(f"  settlements: {self.counts.get('receipts', 0)} receipts, {self.counts.get('supplier_payments', 0)} supplier payments")

    # ------------------------------------------------------------------ payroll, remittances, BAS, loan, equity, prepayments, accruals
    def ledger_journals(self):
        rng, db, org = self.rng, self.db, self.org
        # payroll
        runs = []
        for ms in self.months:
            pay_date = _last_business_day(ms)
            if pay_date > self.today:
                continue
            gross = payg = Z
            roster = [(n, int(sal * (1.04 if ms >= self.fy_start else 1))) for n, sal in STAFF]
            if ms >= self.fy_start:
                roster.append(("Nina Patel", 72000))                              # new hire from the start of the current financial year
            for _, sal in roster:
                g = money(Decimal(sal) / 12)
                gross += g
                payg += money(g * _payg_rate(sal))
            sup = money(gross * Decimal("0.12"))
            net = gross - payg
            self.journal(pay_date, [self.dl("477", dr=gross, desc=f"Gross wages {ms:%B %Y}"), self.dl("825", cr=payg, desc=f"PAYG withheld {ms:%B %Y}"),
                                    self.dl("090", cr=net, desc=f"Net pay {ms:%B %Y}"), self.dl("478", dr=sup, desc=f"Superannuation {ms:%B %Y}"),
                                    self.dl("826", cr=sup, desc=f"Super payable {ms:%B %Y}")], f"Pay run {ms:%B %Y} - {len(roster)} employees", "payroll_run", f"payrun:{ms:%Y-%m}")
            self.event(self.cheque, pay_date, f"Payroll - pay run {ms:%b %Y}", -net)
            runs.append((ms, payg, sup))
            self.bump("pay_runs")
        # PAYG remittance monthly (21st of following month), super quarterly
        by_month = {ms: payg for ms, payg, _ in runs}
        for ms, payg in by_month.items():
            d = _add_months(ms, 1).replace(day=21)
            if d <= self.today:
                self.journal(d, [self.dl("825", dr=payg, desc=f"PAYG remittance {ms:%b %Y}"), self.dl("090", cr=payg, desc=f"ATO PAYG {ms:%b %Y}")], f"PAYG withholding remitted - {ms:%B %Y}", "payg_remittance")
                self.event(self.cheque, d, f"ATO - PAYG withholding {ms:%b %Y}", -payg)
        quarters = {}
        for ms, payg, sup in runs:
            q_end = _add_months(ms, (3 - (ms.month - 1) % 3) % 3 + 0)
            qs = date(ms.year, ((ms.month - 1) // 3) * 3 + 1, 1)
            quarters[qs] = quarters.get(qs, Z) + sup
        for qs, sup in quarters.items():
            d = _add_months(qs, 3).replace(day=28)
            if d <= self.today:
                self.journal(d, [self.dl("826", dr=sup, desc="Quarterly super contributions"), self.dl("090", cr=sup, desc="Super clearing house")], f"Superannuation paid - quarter from {qs:%b %Y}", "super_payment")
                self.event(self.cheque, d, f"Super clearing house - quarter {qs:%b %Y}", -sup)
        # BAS: GST settled quarterly on the 28th of the month after quarter end
        gq = date(self.start.year, 7, 1)
        while gq <= self.today:
            qe = _eom(_add_months(gq, 2))
            pay_d = _add_months(gq, 3).replace(day=28)
            if pay_d <= self.today:
                gst = R.gst_summary(db, org, gq, qe, "accrual")
                net = money(gst["net_gst_payable"])
                if net > 0:
                    self.journal(pay_d, [self.dl("820", dr=net, desc=f"BAS {gq:%b}-{qe:%b %Y}"), self.dl("090", cr=net, desc="ATO BAS payment")], f"BAS payment - quarter ended {qe:%d %b %Y}", "bas_payment")
                    self.event(self.cheque, pay_d, f"ATO - BAS quarter {qe:%b %Y}", -net)
                elif net < 0:
                    self.journal(pay_d, [self.dl("090", dr=-net, desc="ATO BAS refund"), self.dl("820", cr=-net, desc=f"BAS refund {gq:%b}-{qe:%b %Y}")], f"BAS refund - quarter ended {qe:%d %b %Y}", "bas_payment")
                    self.event(self.cheque, pay_d, f"ATO - BAS refund {qe:%b %Y}", -net)
            gq = _add_months(gq, 3)
        # loan repayments (15th), director's loan, dividend
        for ms in self.months:
            d = ms.replace(day=15)
            if d <= self.today:
                self.journal(d, [self.dl("900", dr=Decimal("1900.00"), desc="Principal"), self.dl("437", dr=Decimal("420.00"), desc="Interest"), self.dl("090", cr=Decimal("2320.00"), desc="Loan repayment")],
                             f"Business loan repayment {ms:%b %Y}", "loan_repayment")
                self.event(self.cheque, d, f"NAB Business Loan repayment {ms:%b %Y}", Decimal("-2320.00"))
        d_loan = self.start + timedelta(days=92)
        if d_loan <= self.today:
            self.journal(d_loan, [self.dl("090", dr=Decimal("15000.00"), desc="Funds introduced"), self.dl("910", cr=Decimal("15000.00"), desc="Director loan")], "Director's loan - funds introduced", "manual")
            self.event(self.cheque, d_loan, "Transfer from S Chen - director loan", Decimal("15000.00"))
        d_div = date(self.start.year + 1, 3, 25)
        if d_div <= self.today:
            self.journal(d_div, [self.dl("981", dr=Decimal("30000.00"), desc="Interim dividend"), self.dl("090", cr=Decimal("30000.00"), desc="Dividend paid")], "Interim dividend paid", "manual")
            self.event(self.cheque, d_div, "Dividend payment - shareholders", Decimal("-30000.00"))
        # prepayment releases
        for start_d, monthly in self.prepaid:
            for k in range(12):
                rd = _eom(_add_months(start_d.replace(day=1), k))
                if rd <= self.today and rd >= start_d:
                    self.journal(rd, [self.dl("433", dr=money(monthly), desc="Insurance expense"), self.dl("620", cr=money(monthly), desc="Release prepayment")], f"Insurance prepayment release {rd:%b %Y}", "manual", "prepay")
        # accrual at prior year end, reversed on day 1
        ye = self.fy_start - timedelta(days=1)
        if ye >= self.start:
            acc_j = self.journal(ye, [self.dl("412", dr=Decimal("3200.00"), desc="Audit fee accrued"), self.dl("805", cr=Decimal("3200.00"), desc="Accrued audit fee")], "Accrual - FY audit fee", "manual", "accrual")
            L.reverse_journal(db, org, acc_j.id, reversal_date=self.fy_start, narration="Reversal of year-end audit fee accrual", created_by=self.uid)
            self.journal(ye, [self.dl("612", dr=Decimal("1500.00"), desc="Provision for doubtful debts"), self.dl("611", cr=Decimal("1500.00"), desc="Provision")], "Provision for doubtful debts - year end", "manual")
        self.log(f"  ledger journals: {self.counts.get('pay_runs', 0)} pay runs, remittances, BAS, loan, prepayments, accruals")

    # ------------------------------------------------------------------ depreciation + disposal, inventory stocktake
    def assets_and_stock(self):
        db, org = self.db, self.org
        disp_date = min(self.fy_start + timedelta(days=50), self.today - timedelta(days=5))
        for ms in self.months:
            me = _eom(ms)
            if me > self.today:
                me = self.today
            if ms == self.months[-1] and me < _eom(ms):
                pass
            FA.run_depreciation(db, org, self.uid, as_at=me)
            if disp_date and me >= disp_date and disp_date >= self.fy_start and not getattr(self, "_disposed", False):
                old = next(a for a in self.assets if a.name.startswith("Old plotter"))
                res = FA.dispose(db, org, self.uid, old, disposal_date=disp_date, proceeds=Decimal("450.00"), bank_ref=self.cheque.id)
                self.event(self.cheque, disp_date, "Sale of old plotter printer - Gumtree", Decimal("450.00"))
                self._disposed = True
                self.log(f"  disposal: plotter book value {res['book_value']} sold for 450 ({res['gain_or_loss']})")
        # stocktake: shrinkage on two items
        st_date = min(self.fy_start - timedelta(days=1), self.today) if self.fy_start > self.start else self.today
        for sku, delta in (("CHR-100", -2), ("MON-300", -1)):
            it = self.items[sku]
            if it.quantity_on_hand > abs(delta):
                INV.adjust(db, org, self.uid, it, mv_date=st_date, counted_quantity=it.quantity_on_hand + delta, note="Annual stocktake - shrinkage")
                self.bump("stocktakes")

    # ------------------------------------------------------------------ expense claims
    def expenses(self):
        db, org, t = self.db, self.org, self.today
        owner = self.ctx
        people = [Ctx(9001, "Priya Nair", org, "bookkeeper"), Ctx(9002, "Tom Becker", org, "bookkeeper"), Ctx(9003, "Lena Fischer", org, "bookkeeper")]
        st = None

        def att(claim):
            for it in claim.items:
                if it.kind == "receipt" and it.tax > 0 and it.gross > EX.TAX_INVOICE_THRESHOLD:
                    db.add(b.Attachment(org_id=org.id, owner_kind="expense_item", owner_id=it.id, filename=f"receipt-{it.id}.pdf", content_type="application/pdf", size=18, data=b"%PDF-1.4 demo receipt", uploaded_by=claim.claimant_user_id))
            db.flush()

        def item(days_ago, merchant, desc, amt, acct, tax="INPUT"):
            return dict(date=t - timedelta(days=days_ago), merchant=merchant, description=desc, amount=amt, account=acct, tax_code=tax)

        plans = [
            (people[0], "Sydney client workshop - travel", [item(150, "Qantas", "Return flights SYD-MEL", 486.20, "493"), item(150, "Uber", "Airport transfers", 96.40, "493"), item(149, "Hotel Melbourne", "1 night accommodation", 312.00, "493")], "paid", 140),
            (people[1], "Team lunch & client entertainment", [item(120, "Bills Surry Hills", "Client lunch - Northshore", 214.50, "406", "EXEMPTEXP"), item(118, "Officeworks", "Whiteboards & markers", 137.90, "453")], "paid", 105),
            (people[2], "Conference registration", [item(95, "Tech Summit AU", "Conference ticket", 890.00, "422"), item(95, "Sydney Trains", "Travel to venue", 18.60, "493", "EXEMPTEXP")], "paid", 80),
            (people[0], "October site visits", [dict(kind="mileage", date=t - timedelta(days=60), description="Site visits - Parramatta (client audit)", km=184, rate_per_km=0.88, account="449", tax_code="EXEMPTEXP"),
                                                  item(59, "Shell Coles Express", "Fuel", 88.30, "449")], "approved", None),
            (people[1], "Software & training", [item(20, "Udemy", "Online course licence", 129.00, "422"), item(19, "Figma", "Design tool - team seat", 75.00, "485")], "submitted", None),
            (people[2], "Home office equipment", [item(9, "JB Hi-Fi", "Webcam & headset", 268.00, "453")], "draft", None),
            (people[0], "Personal purchases - not claimable", [item(30, "Dan Murphy's", "Client gifts (no invoice)", 340.00, "411")], "rejected", None),
        ]
        for ctx, title, items, status, pay_days in plans:
            claim = EX.create_claim(db, org, ctx, dict(title=title, items=items))
            att(claim)
            if status in ("submitted", "approved", "paid", "rejected"):
                EX.submit(db, org, ctx, claim)
            if status == "rejected":
                EX.reject(db, owner, claim, "Gifts need a tax invoice and a business purpose - please resubmit with one.")
            if status in ("approved", "paid"):
                EX.approve(db, org, owner, claim)
            if status == "paid":
                pd_ = t - timedelta(days=pay_days)
                pd_ = max(pd_, max(i.item_date for i in claim.items))
                EX.reimburse(db, org, owner, claim, pd_, self.cheque.id, f"Reimburse {claim.number}")
                self.event(self.cheque, pd_, f"Reimburse {claim.claimant_name} {claim.number}", -claim.total)
            self.bump("claims")
        self.log(f"  expenses: {self.counts.get('claims', 0)} claims")

    # ------------------------------------------------------------------ direct-coded bank activity: fees, interest, card, transfers, oddities
    def bank_activity(self):
        rng = self.rng
        card_month = {}
        for ms in self.months:
            fee_d = _eom(ms)
            if fee_d <= self.today:
                self.event(self.cheque, fee_d, "Monthly account service fee", Decimal("-30.00"), code=dict(account="404", tax_code="EXEMPTEXP"), batch=2)
                self.event(self.savings, fee_d, "Interest paid", money(rng.uniform(95, 165)), code=dict(account="270", tax_code="EXEMPTOUTPUT"), batch=2)
            # credit-card spend
            spend = Z
            for desc, acct, tax, lo, hi, prob in (("Shell Coles Express fuel", "449", "INPUT", 70, 140, 0.9), ("Uber trip", "493", "INPUT", 18, 65, 0.8), ("Bunnings Warehouse", "473", "INPUT", 25, 210, 0.4),
                                                  ("Zoom subscription", "485", "INPUT", 21, 21, 1.0), ("Client coffee meeting", "406", "EXEMPTEXP", 28, 96, 0.7), ("Toll charges Linkt", "457", "INPUT", 34, 88, 0.85)):
                if rng.random() < prob:
                    d = ms + timedelta(days=rng.randint(0, 26))
                    if d > self.today:
                        continue
                    amt = money(rng.uniform(lo, hi))
                    spend += amt
                    self.event(self.card, d, desc, -amt, code=dict(account=acct, tax_code=tax), batch=2, reconcile=True)
            card_month[ms] = spend
        # card repayment the following month + savings top-up transfers (both legs, paired)
        for ms, spend in card_month.items():
            d = _add_months(ms, 1).replace(day=3)
            if spend > 0 and d <= self.today:
                self.event(self.cheque, d, "BPAY - company credit card", -spend, code=dict(transfer=self.card), batch=2)
                self.event(self.card, d, "Payment received - thank you", spend, code=dict(transfer=None), batch=2)
        for ms in self.months:
            d = ms.replace(day=12)
            if d <= self.today and ms.month in (8, 11, 2, 5):
                self.event(self.cheque, d, "Transfer to NAB Savings", Decimal("-10000.00"), code=dict(transfer=self.savings), batch=2)
                self.event(self.savings, d, "Transfer from NAB Cheque", Decimal("10000.00"), code=dict(transfer=None), batch=2)
        # oddities for the cash-validation report
        d_dup = self.today - timedelta(days=16)
        for _ in range(2):                                                    # the same card charge twice on the same day
            self.event(self.card, d_dup, "Uber *TRIP Sydney NSW", Decimal("-47.85"), code=None, batch=2, reconcile=False)
        self.event(self.cheque, self.today - timedelta(days=52), "Cash - subcontractor Ravi (no invoice)", Decimal("-2500.00"), code=dict(account="313", tax_code="EXEMPTEXP"), batch=2)
        self.event(self.cheque, self.today - timedelta(days=41), "Unknown card purchase 4471", Decimal("-189.90"), code=dict(account="850", tax_code="BASEXCLUDED"), batch=2)
        self.event(self.cheque, self.today - timedelta(days=44), "Direct debit - GYM MEMBERSHIP", Decimal("-79.00"), code=None, batch=2, reconcile=False)          # stale
        self.event(self.cheque, self.today - timedelta(days=39), "Deposit - unidentified", Decimal("1250.00"), code=None, batch=2, reconcile=False)                 # stale
        self.event(self.cheque, self.today - timedelta(days=33), "Bank error correction - duplicate fee", Decimal("-30.00"), code=None, batch=2, exclude=True)         # excluded
        self.event(self.cheque, self.today - timedelta(days=4), "Direct debit - Netflix Business", Decimal("-22.99"), code=None, batch=2, reconcile=False)
        self.event(self.cheque, self.today - timedelta(days=2), "Deposit - PayPal transfer", Decimal("684.15"), code=None, batch=2, reconcile=False)
        self.event(self.cheque, self.today - timedelta(days=1), "Merchant fees - Square", Decimal("-63.40"), code=dict(account="404", tax_code="EXEMPTEXP"), batch=2, reconcile=False)

    # ------------------------------------------------------------------ import the statement lines and reconcile
    def statements(self):
        db, org = self.db, self.org
        by_acc = {}
        for e in self.events:
            by_acc.setdefault(e["account"].id, []).append(e)
        for acc_id, evs in by_acc.items():
            acc = db.get(lm.LedgerAccount, acc_id)
            evs.sort(key=lambda e: (e["date"], e["batch"], e["seq"]))
            bal = Z
            for e in evs:
                bal += e["amount"]
                e["balance"] = bal if acc.account_type == "bank" else None
            for batch in (1, 2):
                sub = [e for e in evs if e["batch"] == batch]
                if not sub:
                    continue
                res = K.import_lines(db, org, self.uid, acc, [dict(date=e["date"], description=e["desc"], amount=e["amount"], balance=e["balance"]) for e in sub], adopt_existing=(batch == 1))
                for e, lid in zip(sub, res["line_ids"]):
                    e["line"] = db.get(b.BankLine, lid)
                self.bump("bank_lines", res["created"])
                self.bump("adopted", res["adopted_from_ledger"])
        # reconcile
        for e in self.events:
            line = e.get("line")
            if line is None:
                continue
            try:
                if e["exclude"]:
                    K.exclude(db, line)
                elif e["payment"] is not None:
                    if e["reconcile"] and line.status == "unreconciled":
                        K.match_payment(db, org, self.uid, line, e["payment"].id)
                        self.bump("reconciled")
                elif e["code"] and line.status == "unreconciled" and e["reconcile"]:
                    code = e["code"]
                    if "transfer" in code:
                        if code["transfer"] is not None:
                            K.transfer(db, org, self.uid, line, code["transfer"].id)
                    else:
                        K.create_from_line(db, org, self.uid, line, account=code["account"], tax_code=code.get("tax_code"), contact=code.get("contact"), learn=False)
                    self.bump("coded")
                elif e["code"] and not e["reconcile"] and "transfer" not in e["code"]:
                    pass
            except BooksError as ex:
                self.log(f"    ! reconcile skipped ({e['desc']}): {ex}")
        db.flush()
        self.log(f"  banking: {self.counts.get('bank_lines', 0)} statement lines, {self.counts.get('adopted', 0)} adopted from ledger, {self.counts.get('reconciled', 0)} payments matched, {self.counts.get('coded', 0)} coded")

    # ------------------------------------------------------------------ income tax provision + budgets
    def tax_and_budgets(self):
        db, org = self.db, self.org
        ye = self.fy_start - timedelta(days=1)
        if ye >= self.start:
            pl = L.profit_and_loss(db, org, self.start, ye)
            profit = money(pl["net_profit"])
            if profit > 0:
                tax = money(profit * Decimal("0.25"))
                self.journal(ye, [self.dl("505", dr=tax, desc="Income tax expense FY"), self.dl("830", cr=tax, desc="Income tax payable")], "Income tax provision - prior financial year (25% base rate entity)", "manual", "tax-provision")
                self.log(f"  income tax provision: {tax} on profit {profit}")
        # last year's budget: actuals with a deterministic variance so every status (favourable / unfavourable / on budget) shows
        accs = {a.id: a for a in db.query(lm.LedgerAccount).filter_by(org_id=org.id)}
        lines = []
        for k, ms in enumerate(_m for _m in self.months if _m < self.fy_start):
            me = _eom(ms)
            for aid, (d, c) in L._sums(db, org, ms, me).items():
                a = accs[aid]
                if a.account_class not in ("revenue", "expense"):
                    continue
                natural = (c - d) if a.account_class == "revenue" else (d - c)
                if natural <= 0:
                    continue
                factor = Decimal(str(round(self.rng.uniform(0.88, 1.12), 3)))
                if "depreciation" in a.name.lower() or a.code in ("477", "478", "469"):
                    factor = Decimal("1.00")                                        # fixed costs are budgeted exactly
                lines.append(dict(account=aid, period=ms.strftime("%Y-%m"), amount=money(round(float(natural * factor) / 50) * 50)))
        X.save_budget(db, org, "Budget", [l for l in lines if l["amount"] > 0])
        if self.fy_start <= self.today:
            prior_end = self.fy_start - timedelta(days=1)
            cur = []
            for aid, (d, c) in L._sums(db, org, self.start, prior_end).items():
                a = accs[aid]
                if a.account_class not in ("revenue", "expense"):
                    continue
                natural = (c - d) if a.account_class == "revenue" else (d - c)
                if natural <= 0:
                    continue
                monthly = money(round(float(natural) / 12 * 1.08 / 50) * 50)
                for k in range(12):
                    cur.append(dict(account=aid, period=_add_months(self.fy_start, k).strftime("%Y-%m"), amount=monthly))
            X.save_budget(db, org, "Budget", [l for l in cur if l["amount"] > 0])
            self.log(f"  budgets: {len(lines)} lines last year + {len(cur)} for this year (last year's monthly average + 8%)")


    # ------------------------------------------------------------------ journal workflow demo: rules -> AI suggestions, drafts, repeating, GST/auto-reversal
    def ledger_extras(self):
        db, org, t = self.db, self.org, self.today
        owner = self.ctx
        priya = Ctx(9001, "Priya Nair", org, "bookkeeper")
        # bank rules (per organisation) so the suggestion engine has evidence to work from
        for name, pat, code, tax in (("Netflix subscription", "netflix", "485", "INPUT"), ("Uber trips", "uber", "493", "INPUT"), ("Gym membership - staff amenities", "gym membership", "405", "INPUT")):
            db.add(b.BankRule(org_id=org.id, name=name, priority=100, direction="out", match_type="contains", pattern=pat, account_id=self.a(code).id, tax_code_id=self.tax[tax].id))
        db.flush()
        # two statement lines that match open invoices exactly (-> "match this receipt to INV-xxxx" suggestions)
        open_inv = sorted([i for i, _, _ in self.open_invoices if i.status == "approved" and i.amount_due > 0 and (t - i.issue_date).days < 60], key=lambda i: i.issue_date, reverse=True)
        seen, picks = set(), []
        for i in open_inv:
            if i.contact_id not in seen:
                seen.add(i.contact_id)
                picks.append(i)
            if len(picks) == 2:
                break
        last = db.query(b.BankLine).filter(b.BankLine.org_id == org.id, b.BankLine.bank_account_id == self.cheque.id, b.BankLine.balance.isnot(None)).order_by(b.BankLine.line_date.desc(), b.BankLine.id.desc()).first()
        if picks and last:
            bal, rows = last.balance, []
            for i in picks:
                bal += i.amount_due
                rows.append(dict(date=t, description=f"EFT {i.contact.name} {i.number}", amount=i.amount_due, balance=bal))
            K.import_lines(db, org, self.uid, self.cheque, rows, adopt_existing=False)
        sug = JT.suggest_bank_journals(db, org, owner)
        self.bump("ai_suggestions", sug["created"])
        # drafts in every state
        adm = [self.track["Admin"]]
        JT.create_draft(db, org, owner, dict(date=t, narration="DRAFT - reclass software licence to prepayments (awaiting invoice)", reference="WP-114", lines=[
            dict(account_id=self.a("620").id, debit="1800.00", description="Prepay annual licence"), dict(account_id=self.a("485").id, credit="1800.00", description="Reclass from subscriptions")]))
        d2 = JT.create_draft(db, org, priya, dict(date=t, narration="Accrue September audit fee", reference="AUD-ACC-09", amounts_are="exclusive", auto_reverse_date=t + timedelta(days=31), lines=[
            dict(account_id=self.a("412").id, debit="3200.00", tax_code_id=self.tax["INPUT"].id, description="Audit fee accrual", tracking_option_ids=adm, contact_name="Baker & Co Chartered Accountants"),
            dict(account_id=self.a("805").id, credit="3520.00", description="Accrued audit fee (incl. GST)")]))
        JT.submit_draft(db, org, priya, d2)
        d3 = JT.create_draft(db, org, priya, dict(date=t, narration="Move director's loan to dividends", lines=[
            dict(account_id=self.a("910").id, debit="5000.00"), dict(account_id=self.a("981").id, credit="5000.00")]))
        JT.submit_draft(db, org, priya, d3)
        JT.reject_draft(db, owner, d3, "Dividends need a board resolution - attach it and resubmit.")
        # repeating templates (dormant until run; the first is due next month)
        nxt = _add_months(t.replace(day=1), 1)
        JT.save_repeating(db, org, owner, dict(name="Monthly insurance prepayment release", frequency="monthly", next_date=nxt.replace(day=28), mode="draft",
                                               narration="Insurance prepayment release - {month} {year}", reference="PREPAY-{mon}{year}", auto_run=True, lines=[
            dict(account_id=self.a("433").id, debit="575.00", description="Insurance {month}"), dict(account_id=self.a("620").id, credit="575.00", description="Release prepayment {month}")]))
        JT.save_repeating(db, org, owner, dict(name="Quarterly director fee accrual (auto-reverses)", frequency="quarterly", next_date=_add_months(t.replace(day=1), 3).replace(day=1), mode="post",
                                               narration="Director fee accrual - {quarter} {fy}", reverse_after_days=31, lines=[
            dict(account_id=self.a("412").id, debit="2500.00", description="Director fee {quarter}"), dict(account_id=self.a("805").id, credit="2500.00", description="Accrued director fee")]))
        JT.save_repeating(db, org, owner, dict(name="Overdue example - fortnightly depreciation review", frequency="fortnightly", next_date=t - timedelta(days=15), mode="draft",
                                               narration="Fixed asset review - {date}", lines=[
            dict(account_id=self.a("416").id, debit="1.00", description="Placeholder"), dict(account_id=self.a("711").id, credit="1.00", description="Placeholder")]))
        # a posted GST-exclusive accrual with a reference, tracking, and an auto-reversing journal dated tomorrow
        j, rj = JT.post_journal_full(db, org, self.uid, journal_date=t, narration="Accrual - September electricity (auto-reverses next month)", reference="ACC-ELEC", amounts_are="exclusive",
                                     auto_reverse_date=t + timedelta(days=1), lines=[
            dict(account_id=self.a("445").id, debit="640.00", tax_code_id=self.tax["INPUT"].id, description="Electricity to 30 Sep", tracking_option_ids=adm, contact_name="AGL Energy"),
            dict(account_id=self.a("805").id, credit="704.00", description="Accrued electricity incl. GST")])
        # multi-currency: the organisation's own USD rates, and a USD journal (ledger holds AUD, the original USD amounts are kept)
        # rates are AUD per 1 USD (about 1.5), like the rest of the ledger
        JT.set_fx_rate(db, org, owner, "USD", t - timedelta(days=40), "1.5430", "manual")
        JT.set_fx_rate(db, org, owner, "USD", t - timedelta(days=5), "1.5140", "manual")
        JT.post_journal_full(db, org, self.uid, journal_date=t - timedelta(days=3), narration="US software licence - annual (USD 1,800)", reference="USD-LIC-01", currency="USD", lines=[
            dict(account_id=self.a("485").id, debit="1800.00", description="Annual licence, billed in USD", contact_name="Cloudware Inc"),
            dict(account_id=self.a("805").id, credit="1800.00", description="Accrued - payable in USD")])
        # split a line across jobs (MYOB-style): shared rent-type cost, 50/30/20 across three regions
        regions = [n for n in ("Sydney", "Melbourne", "Brisbane") if n in self.track]
        if len(regions) == 3:
            JT.post_journal_full(db, org, self.uid, journal_date=t - timedelta(days=2), narration="Shared marketing spend split across regions", reference="SPLIT-MKT", amounts_are="exclusive", lines=[
                dict(account_id=self.a("445").id, debit="1200.00", tax_code_id=self.tax["INPUT"].id, description="Shared campaign",
                     allocations=[dict(tracking_option_ids=[self.track["Sydney"]], percent="50"), dict(tracking_option_ids=[self.track["Melbourne"]], percent="30"), dict(tracking_option_ids=[self.track["Brisbane"]], percent="20")]),
                dict(account_id=self.a("805").id, credit="1320.00", description="Accrued incl. GST")])
        if self.foreign_demo:
            self.foreign_currency_demo(t)
        self.bump("drafts", 3)
        self.log(f"  ledger extras: {sug['created']} suggestions ({sug['matches']} matches, {sug['coded']} coded), 3 drafts, 3 repeating templates, accrual journal {j.journal_no} + auto-reversal {rj.journal_no}")

    def foreign_currency_demo(self, t):
        """A USD bank account: opening deposit, a client receipt, a GST-coded purchase, a realised gain on spending, and a period-end revaluation."""
        db, org = self.db, self.org
        acc = lm.LedgerAccount(org_id=org.id, code="USD-OPS", name="USD Operating Account", account_type="bank", account_class="asset", currency="AUD")
        db.add(acc)
        db.flush()
        FX.set_account_currency(db, org, acc.id, "USD")
        FX.ensure_fx_accounts(db, org)
        eq = db.query(lm.LedgerAccount).filter(lm.LedgerAccount.org_id == org.id, lm.LedgerAccount.account_class == "equity", lm.LedgerAccount.system_key.is_(None)).order_by(lm.LedgerAccount.code).first()
        d1, d2, d3 = t - timedelta(days=35), t - timedelta(days=20), t - timedelta(days=12)
        JT.set_fx_rate(db, org, self.ctx, "USD", d3, "1.5390", "manual")
        rows = [dict(date=d1, description="Opening USD deposit - owner funds", amount=Decimal("12000.00"), balance=Decimal("12000.00")),
                dict(date=d2, description="Cloudware Inc - client payment USD", amount=Decimal("3500.00"), balance=Decimal("15500.00")),
                dict(date=d3, description="Stripe payout fees and hosting USD", amount=Decimal("-900.00"), balance=Decimal("14600.00"))]
        K.import_lines(db, org, self.uid, acc, rows, adopt_existing=False)
        lines = db.query(b.BankLine).filter_by(org_id=org.id, bank_account_id=acc.id).order_by(b.BankLine.line_date).all()
        K.create_from_line(db, org, self.uid, lines[0], account=eq.code, tax_code="BASEXCLUDED", learn=False)
        K.create_from_line(db, org, self.uid, lines[1], account="200", tax_code="EXEMPTOUTPUT", contact="Cloudware Inc", learn=False)
        K.create_from_line(db, org, self.uid, lines[2], account="445", tax_code="INPUT", learn=False)
        res = FX.revalue(db, org, self.uid, t, reverse=True)
        self.bump("fx", 1)
        self.log(f"  foreign currency: USD account (3 statement lines reconciled, GST on a USD purchase), revalued at {t.isoformat()} ({', '.join(p['currency'] for p in res['posted'])}), auto-reversing")

    # ------------------------------------------------------------------ run
    def run(self):
        self.setup()
        self.opening()
        self.sales()
        self.purchases()
        self.settlements()
        self.ledger_journals()
        self.assets_and_stock()
        self.expenses()
        self.bank_activity()
        self.statements()
        self.tax_and_budgets()
        self.ledger_extras()
        self.db.flush()
        return self.counts


# ---------------------------------------------------------------------------------------------- verification --
def verify(db, org, today=None, log=print):
    """Cross-checks every control the reports rely on. Returns (passed, failed) lists of (name, detail)."""
    today = today or date.today()
    fy = L._fy_start(org, today)
    start = date(fy.year - 1, 7, 1)
    ok, bad = [], []

    def chk(name, cond, detail=""):
        (ok if cond else bad).append((name, detail))

    tb = L.trial_balance(db, org, today)
    chk("Trial balance: debits = credits", tb["balanced"], f"{tb['total_debit']} vs {tb['total_credit']}")
    bs = L.balance_sheet(db, org, today)
    chk("Balance sheet: net assets = equity", bs["balanced"], f"{bs['net_assets']} vs {bs['total_equity']}")
    for side, nm in (("sales", "Receivables"), ("purchases", "Payables")):
        r = R.aged(db, org, side, today)
        chk(f"Aged {nm} reconcile to control account", r["control"]["reconciled"], f"diff {r['control']['difference']}")
    g = R.gst_summary(db, org, fy, today, "accrual")
    chk("GST/BAS: GST account movement = 1A - 1B", g["ledger_check"]["reconciled"], g["ledger_check"].get("difference", ""))
    cf = R.cash_flow(db, org, fy, today)
    chk("Cash flow statement reconciles to bank movement", cf["reconciled"], cf["difference"])
    cs = X.cash_summary(db, org, fy, today)
    chk("Cash summary reconciles to bank movement", cs["reconciled"], cs["difference"])
    gl = X.gl_summary(db, org, fy, today)
    chk("GL summary: period debits = credits", gl["balanced"], f"{gl['total_debit']} vs {gl['total_credit']}")
    jr = X.journal_report(db, org, start, today, limit=2000)
    chk("Journal report: every journal balances", jr["balanced"] and all(j["balanced"] for j in jr["journals"]), f"{jr['count']} journals")
    ic = INV.control(db, org, today)
    chk("Inventory sub-ledger = inventory account", ic["reconciled"], str(ic["accounts"]))
    ii = X.inventory_item_details(db, org, fy, today)
    chk("Inventory item report reconciles to ledger", ii["control"]["reconciled"], str(ii["control"]))
    ac = FA.control(db, org, today)
    chk("Fixed-asset register = ledger", ac["reconciled"] if "reconciled" in ac else all(r["reconciled"] for r in ac["accounts"]), "")
    pg = X.payg_summary(db, org, fy, today)
    chk("PAYG withholding reconciles to ledger", pg["check"]["reconciled"], str(pg["check"]))
    for bk in db.query(lm.LedgerAccount).filter_by(org_id=org.id, account_type="bank"):
        rr = K.reconciliation_report(db, org, bk, today)
        if rr.get("statement_balance") is not None:
            chk(f"Bank reconciliation {bk.code}: statement explains ledger", Decimal(rr["difference"]) == 0, f"diff {rr['difference']}")
    mg = X.management_report(db, org, fy, today)
    chk("Management report builds; no 'does not balance' alert", not any("does not balance" in a["text"] for a in mg["alerts"]), str([a["text"] for a in mg["alerts"]]))
    bv = X.budget_variance(db, org, fy, today)
    chk("Budget variance has a budget (and actuals once the year is under way)", bv["has_budget"] and (Decimal(bv["income"]["actual"]) > 0 or (today - fy).days < 30), "")
    cv = X.cash_validation(db, org, start, today)
    chk("Cash validation finds the seeded oddities", cv["issues"] > 0, f"{cv['issues']} findings: " + ", ".join(f"{c['key']}={c['count']}" for c in cv["checks"] if c["count"]))
    from accfino.modules.accounting.ledger.journal_models import JournalDraft, RepeatingJournal
    hl = JT.ledger_health(db, org, today)
    chk("Ledger health: drafts, approvals and AI suggestions exist", hl["drafts"] >= 1 and hl["awaiting_approval"] >= 1 and hl["ai_suggestions"] >= 1, str({k: hl[k] for k in ("drafts", "awaiting_approval", "ai_suggestions", "rejected", "repeating_due")}))
    chk("Drafts never touch the ledger (no journal from a non-posted draft)", db.query(JournalDraft).filter(JournalDraft.status != "posted", JournalDraft.posted_journal_id.isnot(None)).count() == 0, "")
    gd = JT.general_ledger_detail(db, org, fy, today, group_by="account")
    tbm = {r["account_id"]: Decimal(r["debit"]) - Decimal(r["credit"]) for r in tb["rows"]}
    accs_ = {x.id: x for x in db.query(lm.LedgerAccount).filter_by(org_id=org.id)}
    bad_acc = []
    for g in gd["groups"]:
        a_ = accs_[g["account_id"]]
        if a_.account_class in ("asset", "liability", "equity"):
            net = tbm.get(g["account_id"], Decimal("0.00"))
            want = net if a_.account_class == "asset" else -net
            if Decimal(g["closing"]) != want:
                bad_acc.append(f"{a_.code}: ledger {g['closing']} vs TB {want}")
    n_bs = sum(1 for g in gd["groups"] if accs_[g["account_id"]].account_class in ("asset", "liability", "equity"))
    chk("Detailed ledger: every balance-sheet account's closing balance equals the trial balance", n_bs >= 5 and not bad_acc, f"{n_bs} accounts compared; " + "; ".join(bad_acc[:3]))
    fxa = FX.foreign_accounts(db, org)
    if fxa:
        pv = FX.revaluation_preview(db, org, today)
        chk("Foreign currency: every foreign account has a rate and is revalued at today's closing rate", not pv["missing_rates"] and all(Decimal(r["to_post"]) == 0 for r in pv["rows"]),
            str([(r["code"], r["to_post"]) for r in pv["rows"] if Decimal(r["to_post"]) != 0]))
        fxr = FX.gains_losses_report(db, org, start, today)
        ur = db.query(lm.LedgerAccount).filter_by(org_id=org.id, system_key="fx_unrealised").first()
        booked = sum((Decimal(r["already_booked"]) for r in pv["rows"]), Decimal("0.00"))
        chk("Foreign currency: unrealised gain/loss booked equals the revaluation adjustments", Decimal(fxr["unrealised"]["total"]) == booked, f"{fxr['unrealised']['total']} vs {booked}")
        chk("Foreign currency: account stated at foreign balance x closing rate", all(Decimal(p["revalued_base"]) == Decimal(FX.q2(Decimal(p["foreign_balance"]) * Decimal(p["rate"]))) for p in fxr["positions"] if p["rate"]), "")
    ec = X.expense_claims_report(db, org, start, today)
    chk("Expense claims report has all statuses", {r["status"] for r in ec["claims"]} >= {"draft", "submitted", "approved", "rejected", "paid"}, str(sorted({r['status'] for r in ec['claims']})))
    return ok, bad


# ---------------------------------------------------------------------------------------------- entry point --
def _make_org(db, user, name):
    org = m.Organisation(name=name, legal_name=name, abn="51 824 753 556", entity_type="company", gst_registered=True, gst_basis="accrual", fy_end_month=6)
    db.add(org)
    db.flush()
    db.add(m.OrgMembership(org_id=org.id, user_id=user.id, role="owner", is_default=not db.query(m.OrgMembership).filter_by(user_id=user.id).first()))
    db.flush()
    return org


def _get_or_create_user(db, email):
    from accfino.core.identity.user import User
    u = db.query(User).filter((User.email == email) | (User.username == email)).first()
    if u:
        return u, False
    import bcrypt
    u = User(username=email.split("@")[0], full_name="Demo Owner", email=email, phone="+61400000000", password=bcrypt.hashpw(DEMO_PASSWORD.encode(), bcrypt.gensalt()).decode(), home_company="")
    db.add(u)
    db.flush()
    from accfino.core.migrate import ensure_user_security
    ensure_user_security(db, u.id)
    return u, True


def main(argv=None):
    ap = argparse.ArgumentParser(description="Seed a complete demo organisation for AccFino Books & Accounting.")
    ap.add_argument("--user", default="demo@accfino.com", help="email/username that will own the demo organisation (created if it does not exist)")
    ap.add_argument("--org-name", default=None, help="name for the new demo organisation")
    ap.add_argument("--today", default=None, help="treat this ISO date as today (default: real date)")
    ap.add_argument("--sqlite", default=None, help="offline mode: build the schema in this SQLite file and seed it (no PostgreSQL); for checking the seed itself")
    ap.add_argument("--verify", action="store_true", help="run the cross-report reconciliation checks afterwards")
    ap.add_argument("--no-foreign-demo", action="store_true", help="skip the USD bank account / revaluation example (used by the test fixtures for a clean slate)")
    args = ap.parse_args(argv)
    today = date.fromisoformat(args.today) if args.today else date.today()
    if args.sqlite:
        from sqlalchemy import create_engine, event
        from sqlalchemy.orm import sessionmaker
        import os
        os.environ.setdefault("DATABASE_URL", "postgresql://offline:offline@localhost/none")
        from accfino.shared.contracts import registry; registry.import_all_models()  # noqa: F401
        eng = create_engine(f"sqlite:///{args.sqlite}")
        event.listen(eng, "connect", lambda c, _: c.execute("PRAGMA foreign_keys=ON"))
        m.Base.metadata.create_all(eng)
        db = sessionmaker(bind=eng, autoflush=False)()
    else:
        from accfino.shared.db.database import SessionLocal
        db = SessionLocal()
    try:
        user, created = _get_or_create_user(db, args.user)
        name = args.org_name or f"AccFino Demo Pty Ltd ({today:%d %b %Y})"
        org = _make_org(db, user, name)
        print(f"Seeding '{name}' (org {org.id}) for {user.email} - data {date(today.year if today.month >= 7 else today.year - 1, 7, 1).replace(year=(today.year if today.month >= 7 else today.year - 1) - 1)} to {today}")
        seeder = Seeder(db, org, user.id, today, foreign_demo=not args.no_foreign_demo)
        counts = seeder.run()
        db.commit()
        print("Seeded:", ", ".join(f"{k}={v}" for k, v in sorted(counts.items())))
        if created:
            print(f"Created login  {args.user}  /  {DEMO_PASSWORD}")
        rc = 0
        if args.verify:
            ok, bad = verify(db, org, today)
            for n, d in ok:
                print(f"  PASS  {n}")
            for n, d in bad:
                print(f"  FAIL  {n}  -> {d}")
            rc = 1 if bad else 0
        print(f"Open the app and switch to organisation '{name}'.")
        return rc
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


if __name__ == "__main__":
    sys.exit(main())
