#!/usr/bin/env python3
"""
generate_mock_data.py - a complete, internally consistent mock data set for AccFino Books & Accounting, written as CSV files.

    python mockdata/generate_mock_data.py                       # writes mockdata/csv/*.csv  (data to 30 Sep 2026)
    python mockdata/generate_mock_data.py --today 2026-12-31    # any "today": the data runs from 1 July of the previous financial year
    python mockdata/generate_mock_data.py --bank-code 091       # if your operating bank account is not 090

No database, no dependencies (Python 3.9+ standard library only). The same seed always gives the same files.

The business is a fictional Sydney IT-services company that also resells hardware (services + stock), GST-registered, June year end.
The files are built so the sub-ledgers agree with the ledger by construction (this is what the verification in docs/CSV_IMPORT.md checks):

  * receipts / supplier payments settle exactly what is owing on each invoice / bill (partial, part-paid, late, unpaid and over-paid all appear)
  * the opening-balance journal + monthly depreciation journals put the asset cost and accumulated depreciation in the ledger that the asset register expects
  * every bank movement that the ledger records also appears on the bank statement file, plus a few statement-only lines for you to code
  * BAS payments are the exact GST position of each quarter; PAYG and super remittances are the exact amounts accrued by the pay journals

Files are numbered in the order they must be loaded.
"""
import argparse
import calendar
import csv
import os
import random
from collections import defaultdict
from datetime import date, timedelta
from decimal import ROUND_HALF_UP, Decimal as D

CENT = D("0.01")
RATE = D("0.10")


def m2(x):
    return D(x).quantize(CENT, ROUND_HALF_UP)


def add_months(d, n):
    y, mo = divmod(d.year * 12 + d.month - 1 + n, 12)
    return date(y, mo + 1, min(d.day, calendar.monthrange(y, mo + 1)[1]))


def eom(d):
    return date(d.year, d.month, calendar.monthrange(d.year, d.month)[1])


def bday(d, forward=True):
    step = 1 if forward else -1
    while d.weekday() >= 5:
        d += timedelta(days=step)
    return d


def abn(entity9):
    w = [10, 1, 3, 5, 7, 9, 11, 13, 15, 17, 19]
    for pre in range(10, 100):
        s = f"{pre}{entity9}"
        nums = [int(c) for c in s]
        nums[0] -= 1
        if sum(a * b for a, b in zip(w, nums)) % 89 == 0:
            return f"{s[:2]} {s[2:5]} {s[5:8]} {s[8:]}"
    raise ValueError(entity9)


def line_calc(qty, price, disc, rate, amounts_are):
    """Exactly the app's per-line maths (books/docs.py calc_line): -> net, tax, gross."""
    base = qty * price * (D(1) - disc / D(100))
    if amounts_are == "inclusive":
        gross = m2(base)
        tax = m2(gross * rate / (D(1) + rate)) if rate else D("0.00")
        return gross - tax, tax, gross
    net = m2(base)
    tax = m2(net * rate) if (rate and amounts_are != "no_tax") else D("0.00")
    return net, tax, net + tax


TAX_RATE = {"OUTPUT": RATE, "INPUT": RATE, "CAPEXINPUT": RATE, "EXEMPTOUTPUT": D(0), "EXEMPTEXP": D(0), "BASEXCLUDED": D(0), "": D(0)}


class Doc:
    def __init__(self, kind, contact, issue, lines, *, amounts_are="exclusive", due=None, terms=14, reference="", status="approved", notes=""):
        self.kind, self.contact, self.issue, self.lines = kind, contact, issue, lines
        self.amounts_are, self.reference, self.status, self.notes = amounts_are, reference, status, notes
        self.due = due or (issue + timedelta(days=terms))
        self.explicit_due = due is not None
        self.number = ""
        self.net = self.tax = self.total = D("0.00")
        for ln in lines:
            n, t, g = line_calc(ln["qty"], ln["price"], ln.get("disc", D(0)), TAX_RATE[ln.get("tax", "")], amounts_are)
            self.net, self.tax, self.total = self.net + n, self.tax + t, self.total + g
        self.paid = D("0.00")            # receipts / payments (and applied credits) against it

    @property
    def open(self):
        return self.total - self.paid


# ============================================================================================ reference data ==
CUSTOMERS = [  # name, abn9, email, phone, address, terms, avg days late (negative = early), credit limit
    ("Bondi Beach Cafe Group Pty Ltd", "824753556", "accounts@bondicafe.example", "02 9365 1100", "14 Campbell Parade, Bondi Beach NSW 2026", 14, 4, 15000),
    ("Harbour Legal Partners", "310482977", "finance@harbourlegal.example", "02 9221 4400", "Level 12, 45 Clarence St, Sydney NSW 2000", 30, 11, 40000),
    ("Northshore Dental Clinic Pty Ltd", "651203988", "admin@northshoredental.example", "02 9436 7788", "8 Pacific Hwy, St Leonards NSW 2065", 14, 2, 12000),
    ("Parramatta Logistics Pty Ltd", "447860213", "ap@parralogistics.example", "02 9635 2200", "120 Church St, Parramatta NSW 2150", 30, 27, 50000),
    ("Redfern Design Studio", "207714356", "studio@redferndesign.example", "02 9699 3010", "33 Redfern St, Redfern NSW 2016", 14, 1, 8000),
    ("Blue Mountains Tourism Ltd", "931580427", "payables@bmtourism.example", "02 4782 5500", "9 Katoomba St, Katoomba NSW 2780", 30, 17, 25000),
    ("Coastal Builders Pty Ltd", "568341092", "office@coastalbuilders.example", "02 4229 8800", "77 Keira St, Wollongong NSW 2500", 30, 38, 30000),
    ("Kiama Wholesale Foods Pty Ltd", "720965431", "accounts@kiamafoods.example", "02 4232 6100", "5 Terralong St, Kiama NSW 2533", 14, 7, 20000),
    ("Sydney Sports Academy", "386907125", "admin@sydneysportsacademy.example", "02 9744 9090", "60 Olympic Blvd, Sydney Olympic Park NSW 2127", 14, 5, 10000),
    ("Wollongong Medical Centre", "153207846", "manager@wollmedical.example", "02 4228 3300", "21 Crown St, Wollongong NSW 2500", 30, 9, 30000),
    ("Darlinghurst Hotel Group Pty Ltd", "694052318", "finance@darlohotels.example", "02 9331 7700", "200 Oxford St, Darlinghurst NSW 2010", 30, 21, 35000),
    ("Penrith Auto Group Pty Ltd", "275418093", "accounts@penrithauto.example", "02 4731 2400", "300 High St, Penrith NSW 2750", 14, 14, 18000),
]

SUPPLIERS = [  # name, abn9, email, phone, address, terms, default account
    ("Harbourside Property Trust", "412907365", "rent@harbourside.example", "02 9252 1200", "Level 3, 10 Bridge St, Sydney NSW 2000", 7, "469"),
    ("TeleConnect Australia Pty Ltd", "733190584", "billing@teleconnect.example", "1300 555 010", "PO Box 500, Sydney NSW 2001", 14, "489"),
    ("PowerGrid Energy Pty Ltd", "598316720", "accounts@powergrid.example", "13 15 15", "GPO Box 77, Sydney NSW 2001", 14, "445"),
    ("SecureCover Insurance Brokers Pty Ltd", "871245093", "premiums@securecover.example", "02 9299 4500", "Level 8, 1 Martin Pl, Sydney NSW 2000", 14, "620"),
    ("CloudSoft Licensing Pty Ltd", "246809135", "billing@cloudsoft.example", "02 8003 9900", "5 Talavera Rd, Macquarie Park NSW 2113", 14, "485"),
    ("TechSource Distribution Pty Ltd", "360412879", "orders@techsource.example", "02 9748 6600", "40 Parramatta Rd, Lidcombe NSW 2141", 30, "310"),
    ("Vision AV Solutions Pty Ltd", "915627340", "accounts@visionav.example", "02 9905 2200", "12 Chandos St, St Leonards NSW 2065", 14, "710"),
    ("Fenwick & Associates Accountants", "183059642", "fees@fenwickaccountants.example", "02 9223 8800", "Level 5, 70 Pitt St, Sydney NSW 2000", 14, "412"),
    ("Spark Digital Marketing Pty Ltd", "629174835", "invoices@sparkdigital.example", "02 9699 5150", "Suite 4, 88 Cleveland St, Chippendale NSW 2008", 14, "401"),
    ("Paper & Pixel Office Supplies", "507381926", "sales@paperpixel.example", "02 9555 0100", "19 Parramatta Rd, Camperdown NSW 2050", 14, "453"),
    ("SwiftCourier Express Pty Ltd", "842096173", "accounts@swiftcourier.example", "1300 794 388", "Unit 7, 50 Sydney Park Rd, Alexandria NSW 2015", 14, "425"),
    ("Codeforge Contracting Pty Ltd", "174539068", "billing@codeforge.example", "02 9188 4040", "Level 2, 30 Hunter St, Newcastle NSW 2300", 14, "313"),
    ("Metro Motors Pty Ltd", "395718240", "fleet@metromotors.example", "02 9647 3300", "500 Pacific Hwy, Artarmon NSW 2064", 14, "730"),
    ("Green Clean Services Pty Ltd", "460827391", "hello@greenclean.example", "0412 555 880", "PO Box 12, Marrickville NSW 2204", 14, "408"),
]

STOCK = [  # sku, name, sale price, typical unit cost, opening qty, opening cost, reorder target
    ("LAP-14", "Business laptop 14 inch", D("1450.00"), D("980.00"), 10, D("950.00"), 12),
    ("MON-27", "Monitor 27 inch 4K", D("499.00"), D("310.00"), 20, D("300.00"), 24),
    ("KBD-WL", "Wireless keyboard", D("79.00"), D("38.00"), 40, D("36.00"), 50),
    ("MSE-WL", "Wireless mouse", D("49.00"), D("22.00"), 50, D("21.00"), 60),
    ("DOCK-C", "USB-C docking station", D("189.00"), D("115.00"), 15, D("110.00"), 20),
    ("CAB-HD2", "HDMI cable 2m", D("19.95"), D("6.50"), 100, D("6.20"), 100),
]

# asset: number, name, category, asset acct, dep acct, purchase date, cost, residual, SL life months, source ("opening" = in the opening-balance journal, "bill" = bought on a bill)
ASSETS = [
    ("FA-0001", "Office furniture and fittings", "office_equipment", "710", "711", date(2023, 3, 1), D("14400.00"), D("0.00"), 120, "opening"),
    ("FA-0002", "Laptops and workstations (staff)", "computer_equipment", "720", "721", date(2024, 7, 1), D("9600.00"), D("0.00"), 36, "opening"),
    ("FA-0003", "Server and network equipment", "computer_equipment", "720", "721", date(2024, 11, 15), D("7500.00"), D("500.00"), 48, "opening"),
    ("FA-0004", "Toyota HiLux service vehicle", "motor_vehicle", "730", "731", date(2024, 2, 10), D("42000.00"), D("10000.00"), 96, "opening"),
    ("FA-0005", "Large-format plotter / printer", "office_equipment", "710", "711", date(2022, 9, 1), D("5200.00"), D("0.00"), 60, "opening"),
    ("FA-0006", "Conference room AV system", "office_equipment", "710", "711", date(2026, 1, 12), D("6250.00"), D("0.00"), 60, "bill"),
    ("FA-0007", "Ford Transit delivery van", "motor_vehicle", "730", "731", date(2026, 8, 5), D("36000.00"), D("6000.00"), None, "bill"),       # diminishing value, bought this year
]


def sl_cum(cost, residual, life, start, as_at):
    """Straight-line accumulated depreciation, exactly the app's formula (assets/service.py cumulative_depreciation)."""
    base = cost - residual
    if as_at < start:
        return D("0.00")
    months = max(0, (as_at.year * 12 + as_at.month) - (start.year * 12 + start.month) + 1)
    return min(m2(base * min(months, life) / life), base)


# ============================================================================================ the generator ==
class Gen:
    def __init__(self, today, bank):
        self.today, self.bank = today, bank
        self.rng = random.Random(today.toordinal())
        fy = date(today.year if today.month >= 7 else today.year - 1, 7, 1)
        self.fy_start = fy
        self.dep_cut = date(fy.year, 6, 30)
        self.start = date(fy.year - 1, 7, 1)                      # 1 July of the previous financial year
        self.months = []
        d = self.start
        while d <= today:
            self.months.append(d)
            d = add_months(d, 1)
        self.cust = {c[0]: c for c in CUSTOMERS}
        self.supp = {s[0]: s for s in SUPPLIERS}
        self.bank_events = []          # (date, signed amount, description, order)
        self.journals = []             # dict(date, narration, ref, lines=[(acct, desc, dr, cr)])
        self.dated = lambda d: d <= today

    # ------------------------------------------------------------------------------------------ utilities
    def rnd_day(self, month_start, lo=1, hi=None):
        last = calendar.monthrange(month_start.year, month_start.month)[1]
        return date(month_start.year, month_start.month, self.rng.randint(lo, min(hi or last, last)))

    def bank_ev(self, when, amount, desc):
        self.bank_events.append((when, m2(amount), desc, len(self.bank_events)))

    def jrn(self, when, narration, ref, lines, bank_line=True):
        """lines: (account, description, debit, credit). Any line on the bank account is also a statement line."""
        self.journals.append(dict(date=when, narration=narration, ref=ref, lines=lines))
        for acct, desc, dr, cr in lines:
            if acct == self.bank:
                self.bank_ev(when, (dr or 0) - (cr or 0), narration)

    # ------------------------------------------------------------------------------------------ sales
    def make_sales(self):
        rng, today = self.rng, self.today
        svc = [("Web development sprint", D("1800.00"), (1, 3), "200"), ("IT consulting (hours)", D("165.00"), (6, 24), "200"),
               ("Cloud migration - project milestone", D("5400.00"), (1, 2), "200"), ("Security and penetration test", D("3200.00"), (1, 1), "200"),
               ("Training workshop (per day)", D("1600.00"), (1, 3), "200"), ("Systems integration - analysis and build", D("4200.00"), (1, 2), "200")]
        invoices = []
        weights = [3, 3, 2, 4, 1, 3, 4, 2, 2, 3, 2, 2]
        names = [c[0] for c in CUSTOMERS]
        retainers = {"Bondi Beach Cafe Group Pty Ltd": D("1450.00"), "Wollongong Medical Centre": D("1900.00"), "Harbour Legal Partners": D("2400.00")}
        for mi, ms in enumerate(self.months):
            for cname, amt in retainers.items():            # recurring monthly retainers, issued on the 1st
                issue = ms
                if issue <= today:
                    invoices.append(Doc("invoice", cname, issue, [dict(desc=f"Managed IT support retainer - {issue:%B %Y}", qty=D(1), price=amt, account="200", tax="OUTPUT")],
                                        terms=self.cust[cname][5], reference=f"RET-{issue:%Y%m}"))
            n = 7 + mi // 7 + rng.randint(0, 3)
            for _ in range(n):
                issue = self.rnd_day(ms, 2)
                if issue > today:
                    continue
                cname = rng.choices(names, weights)[0]
                terms = self.cust[cname][5]
                aa = "inclusive" if rng.random() < 0.10 else "exclusive"
                lines = []
                if rng.random() < 0.36:                                        # a product invoice
                    for _ in range(rng.choice([1, 1, 2, 3])):
                        sku, name, price, *_ = rng.choice(STOCK)
                        q = rng.choice([1, 2, 3]) if price > 400 else rng.choice([2, 4, 6, 10])
                        lines.append(dict(desc=name, qty=D(q), price=price, account="201", tax="OUTPUT", sku=sku))
                    if rng.random() < 0.3:
                        lines.append(dict(desc="Delivery and on-site setup", qty=D(1), price=D("180.00"), account="200", tax="OUTPUT"))
                else:
                    for _ in range(rng.choice([1, 1, 2])):
                        desc, price, (lo, hi), acct = rng.choice(svc)
                        tax = "OUTPUT"
                        if desc.startswith("Training") and cname == "Sydney Sports Academy":
                            desc, tax = "Accredited first-aid IT safety course (GST-free)", "EXEMPTOUTPUT"
                        lines.append(dict(desc=f"{desc}" + (f" - {issue:%b %Y}" if "sprint" in desc or "milestone" in desc else ""), qty=D(rng.randint(lo, hi)), price=price, account=acct, tax=tax))
                ref = f"PO-{rng.randint(1000, 9999)}" if rng.random() < 0.5 else ""
                invoices.append(Doc("invoice", cname, issue, lines, amounts_are=aa, terms=terms, reference=ref))
        invoices.sort(key=lambda d: d.issue)
        for i, d in enumerate(invoices, 1):
            d.number = f"INV-{i:04d}"
        # the newest two invoices stay drafts (they do not post, and carry no stock movement)
        for d in invoices[-2:]:
            d.status = "draft"
            d.lines = [ln for ln in d.lines if "sku" not in ln] or [dict(desc="Web development sprint - draft", qty=D(2), price=D("1800.00"), account="200", tax="OUTPUT")]
            d.net = d.tax = d.total = D("0.00")
            for ln in d.lines:
                n, t, g = line_calc(ln["qty"], ln["price"], D(0), TAX_RATE[ln["tax"]], d.amounts_are)
                d.net, d.tax, d.total = d.net + n, d.tax + t, d.total + g
        self.invoices = invoices
        # quotes (no ledger effect)
        quotes = []
        qstat = ["accepted", "accepted", "accepted", "accepted", "accepted", "sent", "sent", "sent", "sent", "declined", "declined", "declined", "draft", "draft", "sent", "accepted"]
        for i, st in enumerate(qstat):
            issue = today - timedelta(days=rng.randint(6, 240))
            cname = rng.choice(names)
            lines = [dict(desc=rng.choice(["Website redesign and build", "Office network refresh", "Cloud migration - discovery and plan", "Managed services onboarding", "Hardware refresh - 10 seats", "Cyber security uplift program"]),
                          qty=D(1), price=D(rng.randrange(4000, 22000, 250)), account="200", tax="OUTPUT")]
            if rng.random() < 0.5:
                lines.append(dict(desc="Project management", qty=D(rng.randint(10, 30)), price=D("150.00"), account="200", tax="OUTPUT"))
            quotes.append(Doc("quote", cname, issue, lines, terms=30, status=st, reference=f"RFQ-{rng.randint(100, 999)}"))
        quotes.sort(key=lambda d: d.issue)
        for i, d in enumerate(quotes, 1):
            d.number = f"QU-{i:04d}"
        self.quotes = quotes
        # credit notes: partial credits applied to an open invoice, and one left unapplied
        elig = [d for d in invoices if d.status == "approved" and d.total > 900 and d.issue < today - timedelta(days=50)]
        self.credit_notes = []
        picks = [elig[len(elig) // 5], elig[len(elig) // 2], elig[(3 * len(elig)) // 5], elig[(4 * len(elig)) // 5]]
        for i, inv in enumerate(picks):
            amt = m2(inv.total * D(rng.choice(["0.10", "0.15", "0.20"])))
            cn = Doc("credit_note", inv.contact, inv.issue + timedelta(days=rng.randint(6, 25)),
                     [dict(desc=f"Credit: service adjustment on {inv.number}", qty=D(1), price=m2(amt / (1 + RATE)), account="200", tax="OUTPUT")], terms=14)
            cn.apply_to = inv.number if i != 2 else ""          # the third is left unapplied (use 'Allocate' in the app)
            cn.target = inv
            self.credit_notes.append(cn)
        self.credit_notes.sort(key=lambda d: d.issue)
        for i, d in enumerate(self.credit_notes, 1):
            d.number = f"CN-{i:04d}"
            if d.apply_to:
                d.apply_amount = min(d.total, d.target.total)
                d.target.paid += d.apply_amount
        self.simulate_receipts()

    def simulate_receipts(self):
        rng, today = self.rng, self.today
        events = []                        # (customer, date, invoice, amount)
        for inv in self.invoices:
            if inv.status != "approved":
                continue
            due_amt = inv.open
            if due_amt <= 0:
                continue
            _, _, _, _, _, terms, late, _ = self.cust[inv.contact]
            pay = inv.due + timedelta(days=int(round(rng.gauss(late, 4))))
            pay = bday(max(pay, inv.issue + timedelta(days=2)))
            age = (today - inv.due).days
            if late >= 35 and age > 55 and rng.random() < 0.35:      # the slow payer: some invoices are never paid
                continue
            if inv.contact == "Parramatta Logistics Pty Ltd" and inv.issue >= today - timedelta(days=75) and rng.random() < 0.6:
                continue
            if pay > today:
                continue
            if rng.random() < 0.08 and due_amt > 800:                    # two part-payments
                first = m2(due_amt * D("0.5"))
                events.append((inv.contact, pay, inv, first))
                second_date = bday(pay + timedelta(days=rng.randint(12, 30)))
                if second_date <= today:
                    events.append((inv.contact, second_date, inv, due_amt - first))
                continue
            if rng.random() < 0.05 and due_amt > 800 and (today - inv.issue).days > 25:   # a part-payment that is still part-paid
                events.append((inv.contact, pay, inv, m2(due_amt * D("0.6"))))
                continue
            events.append((inv.contact, pay, inv, due_amt))
        # merge same-customer payments in the same ISO week into one receipt (one payment settling several invoices)
        groups = defaultdict(list)
        for e in events:
            groups[(e[0], e[1].isocalendar()[:2])].append(e)
        self.receipts = []
        for (cust, _), evs in sorted(groups.items(), key=lambda kv: (max(x[1] for x in kv[1]), kv[0][0])):
            when = max(x[1] for x in evs)
            evs.sort(key=lambda x: x[2].number)
            self.receipts.append(dict(contact=cust, date=when, rows=[(x[2].number, x[3]) for x in evs], unalloc=D("0.00"), ref=""))
        self.receipts.sort(key=lambda r: (r["date"], r["contact"]))
        # two customers overpay (an unallocated credit stays on the account)
        full = [r for r in self.receipts if len(r["rows"]) == 1 and r["date"] < today - timedelta(days=20)]
        for r, extra in ((full[len(full) // 3], D("150.00")), (full[(2 * len(full)) // 3], D("66.00"))):
            r["unalloc"] = extra
        for i, r in enumerate(self.receipts, 1):
            r["ref_no"] = f"RCPT-{i:04d}"
            r["ref"] = rng.choice(["EFT", "EFT", "EFT", "BPAY", "DEPOSIT"]) + f" {rng.randint(10000, 99999)}"
        by_no = {d.number: d for d in self.invoices}
        for r in self.receipts:
            for num, amt in r["rows"]:
                by_no[num].paid += amt
            total = sum((a for _, a in r["rows"]), D("0.00")) + r["unalloc"]
            self.bank_ev(r["date"], total, f"DEPOSIT {r['contact'].upper()[:28]} {'/'.join(n for n, _ in r['rows'][:3])}")

    # ------------------------------------------------------------------------------------------ purchases
    def make_purchases(self):
        rng, today = self.rng, self.today
        bills = []

        def bill(supplier, issue, lines, ref, *, aa="exclusive", due=None):
            if issue > today:
                return
            terms = self.supp[supplier][5]
            bills.append(Doc("bill", supplier, issue, lines, amounts_are=aa, due=due or (issue + timedelta(days=terms)), terms=terms, reference=ref))

        for mi, ms in enumerate(self.months):
            bump = D("1.04") if ms >= date(2026, 7, 1) else D(1)
            bill("Harbourside Property Trust", ms, [dict(desc=f"Office rent - {ms:%B %Y}", qty=D(1), price=m2(D("4800.00") * bump), account="469", tax="INPUT")], f"HPT-{ms:%Y%m}", due=ms)
            bill("TeleConnect Australia Pty Ltd", self.rnd_day(ms, 3, 9), [dict(desc=f"Business internet and mobiles - {ms:%b %Y}", qty=D(1), price=m2(D("262.00") + D(rng.randint(0, 4000)) / 100), account="489", tax="INPUT")], f"TC-{rng.randint(100000, 999999)}")
            bill("CloudSoft Licensing Pty Ltd", self.rnd_day(ms, 1, 4), [dict(desc=f"Software subscriptions ({14 + mi // 3} seats) - {ms:%b %Y}", qty=D(14 + mi // 3), price=D("38.50"), account="485", tax="INPUT")], f"CS-{ms:%Y%m}-{rng.randint(10, 99)}")
            bill("Spark Digital Marketing Pty Ltd", self.rnd_day(ms, 5, 12), [dict(desc=f"Digital marketing campaign - {ms:%b %Y}", qty=D(1), price=D(rng.randrange(800, 2600, 50)), account="401", tax="INPUT")], f"SDM-{rng.randint(1000, 9999)}")
            hrs = rng.randint(36, 96)
            bill("Codeforge Contracting Pty Ltd", self.rnd_day(ms, 18, 27), [dict(desc=f"Contract development - {hrs} hours ({ms:%b %Y})", qty=D(hrs), price=D("95.00"), account="313", tax="INPUT")], f"CF-{rng.randint(2000, 2999)}")
            bill("Green Clean Services Pty Ltd", self.rnd_day(ms, 20, 28), [dict(desc=f"Office cleaning - {ms:%b %Y}", qty=D(4), price=D("82.00"), account="408", tax="INPUT")], f"GC-{rng.randint(300, 999)}")
            if ms.month in (7, 10, 1, 4):                                                   # quarterly
                bill("PowerGrid Energy Pty Ltd", self.rnd_day(ms, 8, 14), [dict(desc="Electricity - quarter", qty=D(1), price=D(rng.randrange(540, 760, 5)), account="445", tax="INPUT")], f"PG-{rng.randint(100000, 999999)}")
                bill("Fenwick & Associates Accountants", self.rnd_day(ms, 10, 20), [dict(desc="Bookkeeping review and BAS preparation - quarter", qty=D(1), price=D("1650.00"), account="412", tax="INPUT")], f"FA-{rng.randint(1000, 9999)}")
            if mi % 2 == 0:
                bill("Paper & Pixel Office Supplies", self.rnd_day(ms, 4, 25), [dict(desc=rng.choice(["Stationery and printer toner", "Office consumables", "Whiteboards and desk accessories"]), qty=D(1), price=D(rng.randrange(70, 420, 5)), account="453", tax="INPUT")], f"PP-{rng.randint(10000, 99999)}")
            if mi % 3 == 1:
                bill("SwiftCourier Express Pty Ltd", self.rnd_day(ms, 6, 26), [dict(desc="Courier and freight", qty=D(1), price=D(rng.randrange(60, 240, 5)), account="425", tax="INPUT")], f"SC-{rng.randint(10000, 99999)}")
        # insurance: annual premium paid to Prepayments, released monthly by journal
        for when, prem in ((date(self.start.year, 7, 1), D("6600.00")), (date(self.fy_start.year, 7, 1), D("7150.00"))):
            bill("SecureCover Insurance Brokers Pty Ltd", when, [dict(desc=f"Business insurance premium {when.year}/{str(when.year + 1)[2:]}", qty=D(1), price=prem, account="620", tax="INPUT")], f"SCI-{when.year}")
        for i, (when, desc, price, acct, tax, sup, ref) in enumerate([
                (date(self.start.year + 1, 1, 12), "Conference room AV system - supply and install", D("6250.00"), "710", "CAPEXINPUT", "Vision AV Solutions Pty Ltd", "VAV-7781"),
                (date(self.fy_start.year, 8, 5), "Ford Transit van - purchase", D("36000.00"), "730", "CAPEXINPUT", "Metro Motors Pty Ltd", "MM-55120"),
                (date(self.start.year + 1, 3, 9), "Contract review and advice", D("1800.00"), "441", "INPUT", "Fenwick & Associates Accountants", "FA-LEG-1"),
                (date(self.start.year + 1, 5, 20), "Air-conditioning service", D("640.00"), "473", "INPUT", "Green Clean Services Pty Ltd", "GC-REP-1")]):
            bill(sup, when, [dict(desc=desc, qty=D(1), price=price, account=acct, tax=tax)], ref)
        bills.sort(key=lambda d: (d.issue, d.contact))
        for i, d in enumerate(bills, 1):
            d.number = f"BILL-{i:04d}"
        self.bills = bills
        # supplier credits (one applied, one left to allocate)
        cs = [b for b in bills if b.contact == "CloudSoft Licensing Pty Ltd" and b.issue < today - timedelta(days=70)]
        sc1, sc2 = cs[len(cs) // 3], cs[(2 * len(cs)) // 3]
        self.supplier_credits = []
        for i, (b, apply) in enumerate(((sc1, True), (sc2, False))):
            d = Doc("supplier_credit", b.contact, b.issue + timedelta(days=9), [dict(desc=f"Credit: seat true-up on {b.number}", qty=D(1), price=D("154.00"), account="485", tax="INPUT")], terms=14,
                    reference=f"CR-{rng.randint(1000, 9999)}")
            d.number, d.apply_to, d.target = f"SC-{i + 1:04d}", (b.number if apply else ""), b
            d.apply_amount = min(d.total, b.total)
            if apply:
                b.paid += d.apply_amount
            self.supplier_credits.append(d)
        # purchase orders
        pos = []
        specs = [("Codeforge Contracting Pty Ltd", "Contract development - project Atlas", D("95.00"), 120, "313", "approved"), ("Codeforge Contracting Pty Ltd", "Contract development - project Borealis", D("95.00"), 80, "313", "approved"),
                 ("Codeforge Contracting Pty Ltd", "Contract development - project Cirrus", D("95.00"), 60, "313", "draft"),
                 ("Spark Digital Marketing Pty Ltd", "Spring campaign - creative and media", D("1".ljust(1)) * D("3200.00"), 1, "401", "approved"), ("Spark Digital Marketing Pty Ltd", "Trade show collateral", D("950.00"), 1, "401", "approved"),
                 ("TechSource Distribution Pty Ltd", "Laptops - reorder", D("985.00"), 8, "310", "approved"), ("TechSource Distribution Pty Ltd", "Monitors - reorder", D("312.00"), 12, "310", "approved"),
                 ("TechSource Distribution Pty Ltd", "Docks and accessories", D("116.00"), 15, "310", "approved"), ("TechSource Distribution Pty Ltd", "Peripherals bulk buy", D("30.00"), 40, "310", "draft"),
                 ("Vision AV Solutions Pty Ltd", "Boardroom microphone upgrade", D("1480.00"), 1, "710", "approved"), ("Paper & Pixel Office Supplies", "Annual stationery order", D("620.00"), 1, "453", "approved"),
                 ("Metro Motors Pty Ltd", "Vehicle fit-out - racking", D("2250.00"), 1, "730", "approved")]
        for sup, desc, price, qty, acct, st in specs:
            pos.append(Doc("purchase_order", sup, today - timedelta(days=rng.randint(4, 200)), [dict(desc=desc, qty=D(qty), price=price, account=acct, tax="INPUT")], terms=30, status=st, reference=f"PRJ-{rng.randint(10, 99)}"))
        pos.sort(key=lambda d: d.issue)
        for i, d in enumerate(pos, 1):
            d.number = f"PO-{i:04d}"
        self.purchase_orders = pos
        self.simulate_payments()

    def simulate_payments(self):
        rng, today = self.rng, self.today
        events = []
        special_unpaid = {("Spark Digital Marketing Pty Ltd", (today - timedelta(days=36)).strftime("%Y-%m")), ("Codeforge Contracting Pty Ltd", (today - timedelta(days=100)).strftime("%Y-%m")),
                          ("Paper & Pixel Office Supplies", (today - timedelta(days=260)).strftime("%Y-%m"))}
        partial_done = False
        for b in self.bills:
            due_amt = b.open
            if due_amt <= 0:
                continue
            pay = bday(b.due + timedelta(days=rng.choice([0, 0, 1, 2, 3])))
            if pay > today:
                continue
            if (b.contact, b.issue.strftime("%Y-%m")) in special_unpaid:
                continue
            if not partial_done and b.contact == "Codeforge Contracting Pty Ltd" and b.issue.strftime("%Y-%m") == (today - timedelta(days=45)).strftime("%Y-%m"):
                events.append((b.contact, pay, b, m2(due_amt / 2)))            # half paid, half still owing
                partial_done = True
                continue
            events.append((b.contact, pay, b, due_amt))
        groups = defaultdict(list)
        for e in events:
            groups[(e[0], e[1].isocalendar()[:2])].append(e)
        self.payments = []
        for (sup, _), evs in sorted(groups.items(), key=lambda kv: (max(x[1] for x in kv[1]), kv[0][0])):
            when = max(x[1] for x in evs)
            evs.sort(key=lambda x: x[2].number)
            self.payments.append(dict(contact=sup, date=when, rows=[(x[2].number, x[3]) for x in evs]))
        self.payments.sort(key=lambda r: (r["date"], r["contact"]))
        by_no = {d.number: d for d in self.bills}
        for i, p in enumerate(self.payments, 1):
            p["ref_no"] = f"PAY-{i:04d}"
            p["ref"] = "EFT " + str(rng.randint(100000, 999999))
            for num, amt in p["rows"]:
                by_no[num].paid += amt
            self.bank_ev(p["date"], -sum((a for _, a in p["rows"]), D("0.00")), f"EFT PAYMENT {p['contact'].upper()[:26]} {p['rows'][0][0]}")

    # ------------------------------------------------------------------------------------------ stock
    def make_stock(self):
        rng, today = self.rng, self.today
        first = self.start
        onhand = {s[0]: s[4] for s in STOCK}
        cost = {s[0]: s[3] for s in STOCK}
        target = {s[0]: s[6] for s in STOCK}
        moves = []
        sells = []
        for inv in self.invoices:
            if inv.status != "approved":
                continue
            for ln in inv.lines:
                if "sku" in ln:
                    sells.append((inv.issue, ln["sku"], int(ln["qty"]), inv.number))
        sells.sort()
        pending = []
        for when, sku, q, num in sells:
            for ev in [e for e in moves if False]:
                pass
            # reorder before the sale if the shelf would run short (goods arrive two days earlier)
            if onhand[sku] - q < 3:
                buy_q = target[sku] - onhand[sku] + q
                bdate = max(when - timedelta(days=3), first + timedelta(days=1))
                uc = m2(cost[sku] * D(1 + rng.randint(-2, 4) / 100))
                moves.append(dict(date=bdate, sku=sku, kind="buy", qty=D(buy_q), cost=uc, account=self.bank, ref=f"PO-{rng.randint(10, 99)}", note="Reorder", order=0))
                onhand[sku] += buy_q
                self.bank_ev(bdate, -(D(buy_q) * uc).quantize(CENT, ROUND_HALF_UP), f"EFT PAYMENT TECHSOURCE DISTRIBUTION {sku}")
            moves.append(dict(date=when, sku=sku, kind="sell", qty=D(q), cost=None, account="", ref=num, note="", order=1))
            onhand[sku] -= q
        # stocktake adjustments: replay in date order to know the on-hand count at the time
        moves.sort(key=lambda m: (m["date"], m["order"]))
        for adj_date, sku, delta in ((date(self.start.year + 1, 3, 31), "CAB-HD2", -4), (date(self.start.year + 1, 6, 30), "KBD-WL", -2), (date(self.start.year + 1, 6, 30), "MSE-WL", 1)):
            if adj_date > today:
                continue
            q = {s[0]: s[4] for s in STOCK}[sku]
            for m in moves:
                if m["date"] <= adj_date and m["sku"] == sku:
                    q += int(m["qty"]) if m["kind"] == "buy" else -int(m["qty"])
            moves.append(dict(date=adj_date, sku=sku, kind="adjustment", qty=None, cost=None, account="", counted=D(q + delta), ref="Stocktake", note="Annual stocktake" if adj_date.month == 6 else "Half-year stocktake", order=2))
        moves.sort(key=lambda m: (m["date"], m["order"]))
        self.moves = moves
        self.opening_date = self.start

    # ------------------------------------------------------------------------------------------ expense claims
    def make_claims(self):
        t = self.today
        d = lambda back: t - timedelta(days=back)
        R = "receipt"
        self.claims = [
            dict(key="CLM-001", title="Client visit - Wollongong", who="Priya Nair", status="paid", paid=d(58), items=[(d(84), "Uber", "Ride to client site", "493", "INPUT", D("46.20"), R), (d(84), "Wilson Parking", "Client site parking", "457", "INPUT", D("28.00"), R), (d(84), "Coastal Cafe", "Lunch with client", "421", "INPUT", D("62.90"), R)]),
            dict(key="CLM-002", title="August mileage - site visits", who="Tom Becker", status="paid", paid=d(14), items=[(d(40), "", "Mileage Sydney to Penrith client", "449", "", None, "mileage", D("86"), "0.88"), (d(33), "", "Mileage Sydney to Kiama client", "449", "", None, "mileage", D("240"), "0.88"), (d(25), "", "Mileage Parramatta site visits", "449", "", None, "mileage", D("64"), "0.88")]),
            dict(key="CLM-003", title="Team lunch - project go-live", who="Chloe Ward", status="paid", paid=d(20), items=[(d(48), "The Grounds", "Go-live team lunch", "405", "INPUT", D("79.50"), R), (d(48), "Dan Murphy's", "Celebration drinks (non-alcohol)", "405", "INPUT", D("34.00"), R)]),
            dict(key="CLM-004", title="Conference travel - Melbourne", who="Sam Lee", status="approved", items=[(d(18), "Uber", "Airport transfer", "493", "INPUT", D("58.00"), R), (d(17), "Hotel breakfast", "Breakfast", "493", "INPUT", D("24.50"), R), (d(17), "Parking", "Airport parking", "457", "INPUT", D("40.00"), R)]),
            dict(key="CLM-005", title="Office supplies - urgent", who="Priya Nair", status="approved", items=[(d(12), "Officeworks", "Whiteboard markers and paper", "453", "INPUT", D("71.40"), R), (d(12), "Coles", "Kitchen supplies", "405", "INPUT", D("39.85"), R)]),
            dict(key="CLM-006", title="Training day - Sydney", who="Tom Becker", status="submitted", items=[(d(9), "Uber", "Ride to training venue", "493", "INPUT", D("35.60"), R), (d(9), "Training Cafe", "Lunch", "405", "INPUT", D("24.00"), R)]),
            dict(key="CLM-007", title="Client dinner", who="Chloe Ward", status="submitted", items=[(d(6), "Establishment Bar", "Client dinner (entertainment)", "406", "EXEMPTEXP", D("78.00"), R)]),
            dict(key="CLM-008", title="Taxi - after-hours", who="Sam Lee", status="rejected", reason="Personal trip - not a business expense", items=[(d(30), "13cabs", "Taxi home (personal)", "493", "INPUT", D("44.00"), R)]),
            dict(key="CLM-009", title="Flights and hotel - Brisbane workshop", who="Priya Nair", status="draft", items=[(d(5), "Qantas", "Return flight SYD-BNE", "493", "INPUT", D("412.00"), R), (d(5), "Ibis Brisbane", "1 night accommodation", "493", "INPUT", D("198.00"), R)]),
            dict(key="CLM-010", title="Laptop bag and peripherals", who="Tom Becker", status="draft", items=[(d(3), "JB Hi-Fi", "Laptop bag", "453", "INPUT", D("149.00"), R), (d(3), "JB Hi-Fi", "USB hub", "453", "INPUT", D("119.00"), R)]),
        ]
        for c in self.claims:
            if c["status"] == "paid":                            # reimbursements leave the bank on the paid date
                total = D("0.00")
                for it in c["items"]:
                    total += (m2(it[7] * D(it[8])) if it[6] == "mileage" else it[5])
                c["total"] = total
                self.bank_ev(c["paid"], -total, f"EFT REIMBURSEMENT {c['who'].upper()} {c['key']}")

    # ------------------------------------------------------------------------------------------ journals
    def make_journals(self):
        rng, today, B = self.rng, self.today, self.bank
        s = self.start
        # 1. opening balances (1 July of the first year)
        dep_open = {}
        lines = [(B, "Opening bank balance", D("85000.00"), None)]
        for n, name, cat, aa, da, pd, cost, res, life, src in ASSETS:
            if src == "opening":
                cum = sl_cum(cost, res, life, pd, s - timedelta(days=1))
                lines.append((aa, f"{name} - cost", cost, None))
                dep_open[da] = dep_open.get(da, D("0.00")) + cum
        for da, v in dep_open.items():
            lines.append((da, "Accumulated depreciation b/f", None, v))
        lines += [("900", "Business loan balance b/f", None, D("40000.00")), ("970", "Share capital", None, D("10000.00"))]
        dr = sum((l[2] or D(0)) for l in lines)
        cr = sum((l[3] or D(0)) for l in lines)
        lines.append(("960", "Retained earnings b/f (balancing figure)", None, dr - cr))
        self.jrn(s, "Opening balances", "OPEN", lines)
        # 2. payroll: gross, PAYG, super (12%); net wages paid the same day; PAYG remitted on the 21st of the next month, super quarterly
        payg_due, super_due, payg_accr, super_accr = [], [], defaultdict(D), defaultdict(D)
        for ms in self.months:
            when = bday(eom(ms), forward=False)
            if when > today:
                continue
            gross = D("17500.00") * (D("1.04") if ms >= date(2026, 7, 1) else D(1))
            payg, sup = m2(gross * D("0.2150")), m2(gross * D("0.12"))
            net = gross - payg
            self.jrn(when, f"Pay run {ms:%B %Y}", f"PAY-{ms:%Y%m}", [("477", "Gross wages", gross, None), ("478", "Superannuation (12%)", sup, None), ("825", "PAYG withheld", None, payg),
                                                                     ("826", "Superannuation payable", None, sup), (B, "Net wages paid", None, net)])
            payg_due.append((add_months(ms, 1).replace(day=21), payg, ms))
            super_due.append((ms, sup))
        for when, amt, ms in payg_due:
            if bday(when) <= today:
                self.jrn(bday(when), f"PAYG withholding remitted - {ms:%B %Y}", "", [("825", f"PAYG {ms:%b %Y}", amt, None), (B, "Remittance to ATO", None, amt)])
        q_total = defaultdict(D)
        for ms, amt in super_due:
            qs = date(ms.year, ((ms.month - 1) // 3) * 3 + 1, 1)
            q_total[qs] += amt
        for qs, amt in sorted(q_total.items()):
            pay = bday(add_months(qs, 3).replace(day=28))
            if qs.month in (7, 10, 1, 4) and eom(add_months(qs, 2)) < today and pay <= today:
                self.jrn(pay, f"Superannuation contributions - quarter from {qs:%b %Y}", "", [("826", "Super remitted", amt, None), (B, "Super clearing house", None, amt)])
        # 3. loan repayments: $1,000 principal + interest at 8.95% on the running balance
        bal = D("40000.00")
        for ms in self.months:
            when = bday(ms.replace(day=15))
            if when > today:
                continue
            interest = m2(bal * D("0.0895") / 12)
            self.jrn(when, f"Business loan repayment {ms:%b %Y}", "", [("900", "Principal", D("1000.00"), None), ("437", "Interest", interest, None), (B, "Loan repayment", None, D("1000.00") + interest)])
            bal -= D("1000.00")
        # 4. insurance: release the prepaid premium monthly
        for yr, prem in ((self.start.year, D("6600.00")), (self.fy_start.year, D("7150.00"))):
            for k in range(12):
                ms = add_months(date(yr, 7, 1), k)
                when = eom(ms)
                if when <= today and (ms <= self.months[-1]):
                    self.jrn(when, f"Insurance - release prepayment {ms:%b %Y}", "", [("433", "Insurance expense", m2(prem / 12), None), ("620", "Prepayments", None, m2(prem / 12))])
        # 5. depreciation for the prior financial year, month by month (this year's is posted with 'Run depreciation' in the app)
        self.dep_cut = date(self.fy_start.year, 6, 30)
        prev = {}
        for k in range(12):
            ms = add_months(self.start, k)
            when = eom(ms)
            per = defaultdict(D)
            for n, name, cat, aa, da, pd, cost, res, life, src in ASSETS:
                if life is None or pd > when:
                    continue
                cur = sl_cum(cost, res, life, pd, when)
                step = cur - prev.get(n, sl_cum(cost, res, life, pd, self.start - timedelta(days=1)))
                prev[n] = cur
                if step:
                    per[da] += step
            if per and when <= today:
                lines = [("416", "Depreciation", sum(per.values()), None)] + [(da, "Accumulated depreciation", None, v) for da, v in per.items()]
                self.jrn(when, f"Depreciation {ms:%B %Y}", f"DEP-{ms:%Y%m}", lines)
        # 6. monthly bank fees and quarterly interest
        for ms in self.months:
            when = eom(ms)
            if when <= today:
                self.jrn(bday(when, False), f"Bank fees {ms:%b %Y}", "", [("404", "Account keeping fees", D("15.00"), None), (B, "Bank fees", None, D("15.00"))])
            if ms.month in (9, 12, 3, 6) and when <= today:
                amt = m2(D("18.40") + D(rng.randint(0, 900)) / 100)
                self.jrn(bday(when, False), f"Interest received {ms:%b %Y}", "", [(B, "Interest", amt, None), ("270", "Interest income", None, amt)])
        # 7. owners: a director's loan out and partly repaid, and a dividend
        fy1 = self.start.year
        for when, narr, lines in ((date(fy1, 11, 10), "Loan to director", [("640", "Loan to director", D("4000.00"), None), (B, "Transfer", None, D("4000.00"))]),
                                  (date(fy1 + 1, 2, 12), "Director repays part of loan", [(B, "Repayment", D("2500.00"), None), ("640", "Loan repayment", None, D("2500.00"))]),
                                  (date(fy1 + 1, 3, 16), "Dividend paid", [("981", "Dividend", D("8000.00"), None), (B, "Dividend", None, D("8000.00"))]),
                                  (date(fy1 + 1, 6, 30), "Income tax provision FY", [("505", "Income tax expense", D("14500.00"), None), ("830", "Income tax payable", None, D("14500.00"))])):
            if when <= today:
                self.jrn(bday(when, False) if any(l[0] == B for l in lines) else when, narr, "", lines)
        # 8. BAS: the exact GST position of each quarter, paid on the 28th of the month after the next quarter starts
        gst = defaultdict(D)
        for d in self.invoices + self.credit_notes + self.bills + self.supplier_credits:
            if d.status != "approved":
                continue
            qs = date(d.issue.year, ((d.issue.month - 1) // 3) * 3 + 1, 1)
            sign = D(1) if d.kind in ("invoice", "supplier_credit") else D(-1) if d.kind in ("bill",) else D(-1)
            # sales side: invoice +, credit note -; purchase side: bill -, supplier credit +
            gst[qs] += d.tax if d.kind == "invoice" else -d.tax if d.kind == "credit_note" else -d.tax if d.kind == "bill" else d.tax
        for c in self.claims:
            if c["status"] in ("approved", "paid"):
                when = max(i[0] for i in c["items"])
                qs = date(when.year, ((when.month - 1) // 3) * 3 + 1, 1)
                for it in c["items"]:
                    if it[6] == "receipt" and it[4] == "INPUT":
                        gst[qs] -= m2(it[5] * RATE / (1 + RATE))
        for qs, net in sorted(gst.items()):
            pay = bday(add_months(qs, 4).replace(day=28) if qs.month != 1 else date(qs.year, 4, 28))
            if qs.month == 7:
                pay = bday(date(qs.year, 10, 28))
            elif qs.month == 10:
                pay = bday(date(qs.year + 1, 2, 28))
            elif qs.month == 1:
                pay = bday(date(qs.year, 4, 28))
            elif qs.month == 4:
                pay = bday(date(qs.year, 7, 28))
            if pay <= today and net != 0:
                if net > 0:
                    self.jrn(pay, f"BAS payment - quarter from {qs:%b %Y}", f"BAS-{qs:%Y%m}", [("820", "GST payable settled", net, None), (B, "Paid to ATO", None, net)])
                else:
                    self.jrn(pay, f"BAS refund - quarter from {qs:%b %Y}", f"BAS-{qs:%Y%m}", [(B, "Refund from ATO", -net, None), ("820", "GST refundable settled", None, -net)])
        self.journals.sort(key=lambda j: j["date"])

    # ------------------------------------------------------------------------------------------ fixed assets / disposal / extras
    def make_assets(self):
        t = self.today
        rows = []
        for n, name, cat, aa, da, pd, cost, res, life, src in ASSETS:
            if pd > t:
                continue
            if life:   # straight line: the register is loaded as if already depreciated to the end of last financial year (the ledger has those journals)
                opening = sl_cum(cost, res, life, pd, self.dep_cut)
                row = dict(number=n, name=name, category=cat, asset_account=aa, depreciation_account=da, expense_account="416", purchase_date=pd, cost=cost, residual_value=res,
                           method="straight_line", effective_life_months=life, dv_rate_pct="", opening_accumulated_depreciation=opening, notes=f"Mock data - {src}")
            else:
                row = dict(number=n, name=name, category=cat, asset_account=aa, depreciation_account=da, expense_account="416", purchase_date=pd, cost=cost, residual_value=res,
                           method="diminishing_value", effective_life_months="", dv_rate_pct="25", opening_accumulated_depreciation=D("0.00"), notes="Mock data - bought this year on a bill; depreciation is posted by 'Run depreciation'")
            row.update(disposal_date="", disposal_proceeds="", disposal_bank_account="")
            if n == "FA-0005":          # the plotter is sold this year
                dd = date(self.fy_start.year, 8, 20)
                if dd <= t:
                    row.update(disposal_date=dd, disposal_proceeds=D("400.00"), disposal_bank_account=self.bank)
                    self.bank_ev(dd, D("400.00"), "DEPOSIT SALE OF PLOTTER - PRINT BROKER")
            rows.append(row)
        self.assets = rows

    def statement_extras(self):
        """Lines that are on the bank statement but not in the ledger yet - something to code in Banking > Reconcile."""
        t, rng = self.today, self.rng
        for back, amt, desc in ((9, D("-64.90"), "WOOLWORTHS 2217 SURRY HILLS"), (16, D("-129.00"), "ADOBE SYSTEMS SYDNEY"), (21, D("250.00"), "STRIPE PAYOUT ST-88120"), (27, D("-48.35"), "BP EXPRESS ROZELLE"),
                                (33, D("-312.00"), "AUSTRALIA POST EXPRESS"), (40, D("-18.00"), "SQ *THE GROUNDS ALEXANDRIA")):
            when = bday(t - timedelta(days=back), False)
            self.bank_ev(when, amt, desc)

    def statement_rows(self):
        ev = sorted(self.bank_events, key=lambda e: (e[0], e[3]))
        bal = D("0.00")
        out = []
        for when, amt, desc, _ in ev:
            bal += amt
            out.append((when, desc, amt, bal))
        return out


# ============================================================================================ writers ==
def write_csv(path, header, rows):
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f, lineterminator="\r\n")
        w.writerow(header)
        w.writerows(rows)


def f2(x):
    return f"{D(x):.2f}"


def iso(d):
    return d.isoformat() if d else ""


def doc_rows(g, docs, role, extra=()):
    """One row per line. Header columns only on the first line of each document (the importer groups by number)."""
    header = ["number", role, "issue_date", "due_date", "reference", "amounts_are", "status", "line_description", "qty", "unit_price", "discount_pct", "account", "tax_code", "notes"] + list(extra)
    rows = []
    for d in docs:
        for i, ln in enumerate(d.lines):
            first = i == 0
            r = [d.number, d.contact if first else "", iso(d.issue) if first else "", iso(d.due) if (first and (d.explicit_due or d.kind in ("bill", "purchase_order"))) else "",
                 d.reference if first else "", d.amounts_are if first else "", ("approved" if d.kind != "quote" else d.status) if (first and d.status != "draft" and d.kind != "quote") else (d.status if first else ""),
                 ln["desc"], f"{ln['qty']:g}", f2(ln["price"]), "", ln.get("account", ""), ln.get("tax", ""), d.notes if first else ""]
            if first and d.status == "approved" and d.kind != "quote":
                r[6] = "approved"
            if "apply_to" in extra:
                r += [getattr(d, "apply_to", "") if first else "", f2(getattr(d, "apply_amount", 0)) if (first and getattr(d, "apply_to", "")) else ""]
            rows.append(r)
    return header, rows


def main():
    ap = argparse.ArgumentParser(description="Generate AccFino mock data CSV files.")
    ap.add_argument("--today", default="2026-09-30", help="the 'as at' date (default 2026-09-30). Data starts on 1 July of the previous financial year")
    ap.add_argument("--bank-code", default="090", help="account code of your operating bank account (default 090)")
    ap.add_argument("--out", default=os.path.join(os.path.dirname(os.path.abspath(__file__)), "csv"), help="output folder")
    a = ap.parse_args()
    today = date.fromisoformat(a.today)
    g = Gen(today, a.bank_code)
    g.make_sales()
    g.make_purchases()
    g.make_stock()
    g.make_claims()
    g.make_assets()
    g.make_journals()
    g.statement_extras()
    os.makedirs(a.out, exist_ok=True)
    P = lambda n: os.path.join(a.out, n)

    write_csv(P("01_customers.csv"), ["name", "email", "phone", "abn", "address", "terms_days", "credit_limit", "default_account", "default_tax_code", "notes"],
              [[c[0], c[2], c[3], abn(c[1]), c[4], c[5], c[7], "200", "OUTPUT", "Mock data"] for c in CUSTOMERS])
    write_csv(P("02_suppliers.csv"), ["name", "email", "phone", "abn", "address", "terms_days", "default_account", "default_tax_code", "notes"],
              [[s[0], s[2], s[3], abn(s[1]), s[4], s[5], s[6], "INPUT", "Mock data"] for s in SUPPLIERS])
    # 03 journals
    jr = []
    for j in g.journals:
        for i, (acct, desc, dr, cr) in enumerate(j["lines"]):
            jr.append([iso(j["date"]) if i == 0 else "", j["narration"] if i == 0 else "", j["ref"] if i == 0 else "", acct, desc, f2(dr) if dr else "", f2(cr) if cr else ""])
    write_csv(P("03_journals.csv"), ["Date", "Narration", "Reference", "Account", "Description", "Debit", "Credit"], jr)
    # 04 inventory items (with opening stock) and 05 fixed assets
    write_csv(P("04_inventory_items.csv"), ["sku", "name", "description", "inventory_account", "cogs_account", "sales_account", "purchase_tax_code", "sales_tax_code", "sale_price", "opening_qty", "opening_unit_cost", "opening_date", "opening_credit_account"],
              [[s[0], s[1], "Mock data", "630", "310", "201", "INPUT", "OUTPUT", f2(s[2]), s[4], f2(s[5]), iso(g.opening_date), "960"] for s in STOCK])
    write_csv(P("13_fixed_assets.csv"), ["number", "name", "category", "asset_account", "depreciation_account", "expense_account", "purchase_date", "cost", "residual_value", "method", "effective_life_months", "dv_rate_pct",
                                          "opening_accumulated_depreciation", "notes", "disposal_date", "disposal_proceeds", "disposal_bank_account"],
              [[r["number"], r["name"], r["category"], r["asset_account"], r["depreciation_account"], r["expense_account"], iso(r["purchase_date"]), f2(r["cost"]), f2(r["residual_value"]), r["method"], r["effective_life_months"], r["dv_rate_pct"],
                f2(r["opening_accumulated_depreciation"]), r["notes"], iso(r["disposal_date"]) if r["disposal_date"] else "", f2(r["disposal_proceeds"]) if r["disposal_proceeds"] != "" else "", r["disposal_bank_account"]] for r in g.assets])
    h, r = doc_rows(g, g.quotes, "customer")
    write_csv(P("05_quotes.csv"), h, r)
    h, r = doc_rows(g, g.invoices, "customer")
    write_csv(P("06_invoices.csv"), h, r)
    h, r = doc_rows(g, g.credit_notes, "customer", extra=("apply_to", "apply_amount"))
    write_csv(P("07_credit_notes.csv"), h, r)
    write_csv(P("08_receipts.csv"), ["payment_ref", "date", "customer", "bank_account", "invoice", "amount", "reference"],
              [[p["ref_no"], iso(p["date"]) if i == 0 else "", p["contact"] if i == 0 else "", g.bank if i == 0 else "", num, f2(amt), p["ref"] if i == 0 else ""] for p in g.receipts for i, (num, amt) in enumerate(p["rows"])] +
              [[p["ref_no"], "", "", "", "", f2(p["unalloc"]), ""] for p in g.receipts if p["unalloc"]])
    h, r = doc_rows(g, g.purchase_orders, "supplier")
    write_csv(P("09_purchase_orders.csv"), h, r)
    h, r = doc_rows(g, g.bills, "supplier")
    write_csv(P("10_bills.csv"), h, r)
    h, r = doc_rows(g, g.supplier_credits, "supplier", extra=("apply_to", "apply_amount"))
    write_csv(P("11_supplier_credits.csv"), h, r)
    write_csv(P("12_supplier_payments.csv"), ["payment_ref", "date", "supplier", "bank_account", "bill", "amount", "reference"],
              [[p["ref_no"], iso(p["date"]) if i == 0 else "", p["contact"] if i == 0 else "", g.bank if i == 0 else "", num, f2(amt), p["ref"] if i == 0 else ""] for p in g.payments for i, (num, amt) in enumerate(p["rows"])])
    cl = []
    for c in g.claims:
        for i, it in enumerate(c["items"]):
            date_, merchant, desc, acct, tax, amt, kind = it[:7]
            km, rate = (f"{it[7]:g}", it[8]) if kind == "mileage" else ("", "")
            cl.append([c["key"], c["title"] if i == 0 else "", c["who"] if i == 0 else "", c["status"] if i == 0 else "", iso(date_), merchant, desc, acct, tax, f2(amt) if amt is not None else "", kind, km, rate,
                       "", iso(c.get("paid")) if (i == 0 and c.get("paid")) else "", g.bank if (i == 0 and c.get("paid")) else "", c.get("reason", "") if i == 0 else "", ""])
    write_csv(P("14_expense_claims.csv"), ["claim", "title", "claimant", "status", "date", "merchant", "description", "account", "tax_code", "amount", "kind", "km", "rate_per_km", "approve_date", "paid_date", "bank_account", "reject_reason", "reference"], cl)
    write_csv(P("15_stock_movements.csv"), ["date", "sku", "kind", "quantity", "unit_cost", "counted_quantity", "account", "reference", "note"],
              [[iso(m["date"]), m["sku"], m["kind"], f"{m['qty']:g}" if m.get("qty") is not None else "", f2(m["cost"]) if m.get("cost") is not None else "", f"{m['counted']:g}" if m.get("counted") is not None else "", m["account"], m["ref"], m["note"]] for m in g.moves])
    write_csv(P("16_bank_statement_%s.csv" % a.bank_code), ["Date", "Description", "Amount", "Balance"],
              [[iso(d), desc, f2(amt), f2(bal)] for d, desc, amt, bal in g.statement_rows()])

    def tot(docs, status="approved"):
        return sum((d.total for d in docs if d.status == status), D("0.00"))
    print(f"Mock data written to {a.out}  (data {g.start} to {today}, bank account {a.bank_code})")
    for name, n in (("customers", len(CUSTOMERS)), ("suppliers", len(SUPPLIERS)), ("journals", len(g.journals)), ("inventory items", len(STOCK)), ("stock movements", len(g.moves)), ("fixed assets", len(g.assets)),
                    ("quotes", len(g.quotes)), ("invoices", len(g.invoices)), ("credit notes", len(g.credit_notes)), ("receipts", len(g.receipts)), ("purchase orders", len(g.purchase_orders)), ("bills", len(g.bills)),
                    ("supplier credits", len(g.supplier_credits)), ("supplier payments", len(g.payments)), ("expense claims", len(g.claims)), ("bank statement lines", len(g.bank_events))):
        print(f"  {name:22s}{n:>6}")
    print(f"  invoiced (gross)      {tot(g.invoices):>12,.2f}   open {sum((d.open for d in g.invoices if d.status == 'approved'), D(0)):>12,.2f}")
    print(f"  billed (gross)        {tot(g.bills):>12,.2f}   open {sum((d.open for d in g.bills), D(0)):>12,.2f}")


if __name__ == "__main__":
    main()
