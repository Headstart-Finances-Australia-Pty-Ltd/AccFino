"""
Subscription entitlements - what an organisation may use, decided from its plan + add-ons.

  * ENFORCEMENT IS OFF BY DEFAULT (Admin > Modules Management > Subscriptions). While off, every organisation can use everything,
    exactly as before this feature existed. Turn it on once plans are assigned.
  * An organisation with no subscription row is "grandfathered": all modules, never locked.
  * A module is allowed when the plan or any add-on lists it (or lists "*"). Platform administrators are never blocked.
  * An expired / cancelled-and-ended subscription is READ-ONLY: everything stays visible, but anything that posts or edits is refused.
    Data is never deleted.
  * Seats: plan seat_limit + extra_seats from add-ons; NULL plan limit = unlimited. Existing members are never removed.
"""
import json
from datetime import date, timedelta
from decimal import Decimal

from fastapi import Depends, HTTPException, Request
from sqlalchemy.orm import Session

from accfino_core import models as m
from accfino_core.subscription.models import Addon, OrgSubscription, Plan
from db_app.database import get_db

ENFORCED_KEY = "platform.subscriptions_enforced"
DEFAULT_PLAN_KEY = "platform.default_plan"
GRACE_DAYS = 7                                       # a lapsed payment keeps working this long before the organisation turns read-only
SAFE_METHODS = ("GET", "HEAD", "OPTIONS")

# The business domains and the modules inside each (mirrors frontend/src/config/modules.json - a test keeps the two in step).
# A plan or add-on can list single module ids, a whole domain as "domain:<id>", or "*" for everything.
DOMAINS = [
    ('accounting', 'Books and Accounting', ['dashboard-accounting', 'general-ledger', 'reconciliation', 'sales', 'purchases', 'expenses', 'inventory-trading', 'fixed-assets', 'financial-reports', 'bulk-import']),
    ('payroll_workforce', 'Payroll & Workforce', ['overview-payroll', 'employees', 'timesheets', 'pay-runs', 'leave-entitlements', 'superannuation', 'payg-withholding', 'payslips', 'stp-lodgement']),
    ('tax_compliance', 'Taxation & Compliance', ['tax-returns', 'cgt', 'gst-bas-ias', 'income-tax', 'fbt-other-taxes', 'tax-planning', 'tax-lodgement-ato']),
    ('assets_investments', 'Assets, Investments & Wealth', ['shares-etfs', 'crypto-digital-assets', 'property', 'funds-bonds', 'investment-portfolio', 'wealth-net-worth']),
    ('lending_treasury', 'Smart Lending, Credit & Treasury', ['financial-statement-analysis', 'credit-assessment', 'loan-origination', 'loan-management', 'collections', 'treasury-liquidity']),
    ('planning_insights', 'Planning & Intelligence', ['cash-flow-forecasting', 'budgeting-forecasting', 'scenario-planning', 'management-reporting', 'cfo-insights', 'ai-financial-assistant', 'risk-anomaly-detection']),
    ('practice', 'Practice & Client Services', ['practice-management', 'clients-entities', 'workpapers-documents', 'client-portal', 'engagements-workflows', 'billing']),
]
DOMAIN_IDS = [d[0] for d in DOMAINS]
DOMAIN_MODULES = {d[0]: list(d[2]) for d in DOMAINS}

# Every sellable module, in domain order. The accounting modules are also gated on the server (see install()); a locked module in the other
# domains is hidden from the menu and its tabs.
CATALOGUE = [
    ('dashboard-accounting', 'Dashboard'),
    ('general-ledger', 'General Ledger & Accounting'),
    ('reconciliation', 'Banking & Reconciliation'),
    ('sales', 'Sales & Receivables'),
    ('purchases', 'Purchases & Payables'),
    ('expenses', 'Expenses'),
    ('inventory-trading', 'Inventory & Trading'),
    ('fixed-assets', 'Fixed Assets'),
    ('financial-reports', 'Financial Reports'),
    ('bulk-import', 'Bulk data import (CSV)'),
    ('overview-payroll', 'Dashboard'),
    ('employees', 'Employees'),
    ('timesheets', 'Timesheets'),
    ('pay-runs', 'Pay Runs'),
    ('leave-entitlements', 'Leave & Entitlements'),
    ('superannuation', 'Superannuation'),
    ('payg-withholding', 'PAYG Withholding'),
    ('payslips', 'Payslips'),
    ('stp-lodgement', 'STP & Payroll Lodgement'),
    ('tax-returns', 'Tax Returns'),
    ('cgt', 'CGT'),
    ('gst-bas-ias', 'GST / BAS / IAS'),
    ('income-tax', 'Income Tax'),
    ('fbt-other-taxes', 'FBT & Other Taxes'),
    ('tax-planning', 'Tax Planning'),
    ('tax-lodgement-ato', 'Tax Lodgement & ATO'),
    ('shares-etfs', 'Shares & ETFs'),
    ('crypto-digital-assets', 'Crypto & Digital Assets'),
    ('property', 'Property'),
    ('funds-bonds', 'Funds & Bonds'),
    ('investment-portfolio', 'Investment Portfolio'),
    ('wealth-net-worth', 'Wealth & Net Worth'),
    ('financial-statement-analysis', 'Financial & Statement Analysis'),
    ('credit-assessment', 'Credit Assessment'),
    ('loan-origination', 'Loan Origination'),
    ('loan-management', 'Loan Management'),
    ('collections', 'Collections'),
    ('treasury-liquidity', 'Treasury & Liquidity'),
    ('cash-flow-forecasting', 'Cash Flow Forecasting'),
    ('budgeting-forecasting', 'Budgeting & Forecasting'),
    ('scenario-planning', 'Scenario Planning'),
    ('management-reporting', 'Management Reporting'),
    ('cfo-insights', 'CFO Insights'),
    ('ai-financial-assistant', 'AI Financial Assistant'),
    ('risk-anomaly-detection', 'Risk & Anomaly Detection'),
    ('practice-management', 'Practice Management'),
    ('clients-entities', 'Clients & Entities'),
    ('workpapers-documents', 'Workpapers & Documents'),
    ('client-portal', 'Client Portal'),
    ('engagements-workflows', 'Engagements & Workflows'),
    ('billing', 'Billing'),
]
CATALOGUE_IDS = [c[0] for c in CATALOGUE]


def expand(mods) -> set:
    """Turn a plan/add-on module list into plain module ids: "*" = everything, "domain:<id>" = every module of that domain."""
    out = set()
    for x in mods or []:
        if x == "*":
            return set(CATALOGUE_IDS)
        if isinstance(x, str) and x.startswith("domain:"):
            out |= set(DOMAIN_MODULES.get(x[7:], []))
        elif x in CATALOGUE_IDS:
            out.add(x)
    return out


# ---------------------------------------------------------------------------------------------------------------------------------
# PRICING (AUD per month, GST included - the way Xero quotes it). Positioned against the July-2026 Australian list prices:
#   Xero  Ignite $37 | Grow $78 | Comprehensive $107 | Ultimate 10 $143       (invoices/bills capped on Ignite; payroll, expenses, projects extra)
#   MYOB  Business Lite $35 | Pro $70 | AccountRight Plus ~$141 | Premier ~$210   (payroll +$3/employee, inventory +$22)
#   Zoho  Books Standard $16.50 | Professional $33 | Premium $44 | Elite $181.50   (annual billing, 3-15 users, per-organisation)
#   ERPNext  free licence; Frappe Cloud ~US$50 for the managed Small Business plan with unlimited users (you do the set-up yourself)
# Users: Xero and ERPNext include unlimited users; Zoho Books caps them (3 / 5 / 10 / 10 / 15) and sells extra users at about A$4.40 each; MYOB prices payroll
# per employee. AccFino follows the Zoho model so price tracks the people using it: 1 / 3 / 6 / 15 users, extra users A$6 each (A$25 for 5).
# AccFino: unlimited invoices, bills and bank rules on every plan; the plan decides WHICH BUSINESS DOMAINS you get and how many users.
# Yearly = 10 x monthly (two months free). All of this is editable in Admin > Modules Management > Subscriptions.
# ---------------------------------------------------------------------------------------------------------------------------------
_CORE = ["dashboard-accounting", "general-ledger", "reconciliation", "sales", "purchases", "financial-reports"]
DEFAULT_PLANS = [
    dict(id="essentials", name="Essentials", description="Books for a sole trader or one-person business: ledger, banking, sales, purchases, reports and cash-flow forecasting. Unlimited invoices and bills. 1 user.",
         price_monthly="25.00", price_yearly="250.00", seat_limit=1, modules=_CORE + ["cash-flow-forecasting"], sort_order=1),
    dict(id="business", name="Business", description="The whole Books & Accounting domain (expenses, inventory, fixed assets, bulk import) plus Planning & Intelligence, for a small team. 3 users.",
         price_monthly="59.00", price_yearly="590.00", seat_limit=3, modules=["domain:accounting", "domain:planning_insights"], sort_order=2),
    dict(id="professional", name="Professional", description="Books + Payroll & Workforce + Taxation & Compliance + Planning & Intelligence, for a growing team. 6 users.",
         price_monthly="99.00", price_yearly="990.00", seat_limit=6, modules=["domain:accounting", "domain:payroll_workforce", "domain:tax_compliance", "domain:planning_insights"], sort_order=3),
    dict(id="complete", name="Complete", description="Every business domain, including Assets & Investments, Smart Lending & Treasury and Practice, for larger teams. 15 users.",
         price_monthly="179.00", price_yearly="1790.00", seat_limit=15, modules=["*"], sort_order=4),
]
# One add-on per domain (so a small plan can bolt on exactly the domain it needs), a few single-module packs, and extra users.
DEFAULT_ADDONS = [
    dict(id="addon-payroll", name="Payroll & Workforce", description="Employees, timesheets, pay runs, payslips and STP.", price_monthly="15.00", modules=["domain:payroll_workforce"], extra_seats=0, sort_order=1),
    dict(id="addon-tax", name="Taxation & Compliance", description="Tax returns, CGT, GST/BAS/IAS and ATO lodgement.", price_monthly="15.00", modules=["domain:tax_compliance"], extra_seats=0, sort_order=2),
    dict(id="addon-planning", name="Planning & Intelligence", description="Cash-flow forecasting, budgets, scenarios and management reporting.", price_monthly="15.00", modules=["domain:planning_insights"], extra_seats=0, sort_order=3),
    dict(id="addon-assets", name="Assets, Investments & Wealth", description="Shares, crypto, property and portfolio tracking.", price_monthly="12.00", modules=["domain:assets_investments"], extra_seats=0, sort_order=4),
    dict(id="addon-lending", name="Smart Lending, Credit & Treasury", description="Credit assessment, loans, collections and treasury.", price_monthly="19.00", modules=["domain:lending_treasury"], extra_seats=0, sort_order=5),
    dict(id="addon-practice", name="Practice & Client Services", description="Client entities, workpapers, engagements, portal and billing for accountants and bookkeepers.", price_monthly="25.00", modules=["domain:practice"], extra_seats=0, sort_order=6),
    dict(id="addon-inventory", name="Inventory", description="Stock items, movements and valuation.", price_monthly="12.00", modules=["inventory-trading"], extra_seats=0, sort_order=7),
    dict(id="addon-expenses", name="Expense claims", description="Employee expense claims with approval and reimbursement.", price_monthly="6.00", modules=["expenses"], extra_seats=0, sort_order=8),
    dict(id="addon-fixed-assets", name="Fixed assets", description="Asset register and depreciation.", price_monthly="10.00", modules=["fixed-assets"], extra_seats=0, sort_order=9),
    dict(id="addon-bulk-import", name="Bulk data import", description="CSV upload of journals, contacts, documents, stock and assets.", price_monthly="8.00", modules=["bulk-import"], extra_seats=0, sort_order=10),
    dict(id="addon-seat-1", name="1 extra user", description="Adds one more user seat.", price_monthly="6.00", modules=[], extra_seats=1, sort_order=11),
    dict(id="addon-seats-5", name="5 extra users", description="Adds five more user seats (A$5 per user).", price_monthly="25.00", modules=[], extra_seats=5, sort_order=12),
]
CATALOGUE_VERSION_KEY = "platform.catalogue_version"
CATALOGUE_VERSION = "3"          # 1 = original Starter/Growth/Premium; 2 = domain-based plans; 3 = seats scale with price (1/3/6/15) + extra-user add-ons
_OLD_PLAN_IDS = ("starter", "growth", "premium")
# What version 2 shipped (seats, description start) - a plan is only moved to version 3 while it still looks exactly like this (i.e. nobody edited it).
_V2_PLANS = {"essentials": (3, "Books for a small business: ledger, banking, sales, purchases and reports."), "business": (10, "The whole Books & Accounting domain"),
             "professional": (25, "Books + Payroll & Workforce + Taxation & Compliance + Planning & Intelligence. 25"), "complete": (None, "Every business domain, including")}
_OLD_ADDON_IDS = ("addon-bulk-import", "addon-expenses", "addon-inventory", "addon-fixed-assets", "addon-seats-5")


def _loads(s):
    try:
        v = json.loads(s or "[]")
        return v if isinstance(v, list) else []
    except ValueError:
        return []


def _plan_row(p):
    return Plan(**{**p, "modules": json.dumps(p["modules"]), "price_monthly": Decimal(p["price_monthly"]), "price_yearly": Decimal(p["price_yearly"])})


def _addon_row(a):
    return Addon(**{**a, "modules": json.dumps(a["modules"]), "price_monthly": Decimal(a["price_monthly"])})


def ensure_catalogue(db: Session):
    """Create the starting plans/add-ons the first time. An installation still on the original Starter/Growth/Premium set is moved ONCE to the
    domain-based plans: the new plans are added, the old default plans are retired (hidden from new sign-ups, but organisations already on them keep
    working and keep their modules), and the default plan for new organisations becomes Essentials. Anything an administrator added is never touched."""
    if db.query(Plan).count() == 0:
        for p in DEFAULT_PLANS:
            db.add(_plan_row(p))
    if db.query(Addon).count() == 0:
        for a in DEFAULT_ADDONS:
            db.add(_addon_row(a))
    db.flush()
    ver = db.get(m.SystemSetting, CATALOGUE_VERSION_KEY)
    have = (ver.value or "0") if ver is not None else "0"
    if have >= CATALOGUE_VERSION:
        return
    if have < "2":                                                                # v1 -> v2: domain-based plans
        for p in DEFAULT_PLANS:
            if db.get(Plan, p["id"]) is None:
                db.add(_plan_row(p))
        for pid in _OLD_PLAN_IDS:
            old = db.get(Plan, pid)
            if old is not None:
                old.is_active = False
        for a in DEFAULT_ADDONS:
            row = db.get(Addon, a["id"])
            if row is None:
                db.add(_addon_row(a))
            elif a["id"] in _OLD_ADDON_IDS and row.price_monthly in (Decimal("10.00"), Decimal("15.00"), Decimal("25.00")):      # unedited v1 price -> current price
                row.price_monthly, row.description = Decimal(a["price_monthly"]), a["description"]
        cfg = db.get(m.SystemSetting, DEFAULT_PLAN_KEY)
        if cfg is None:
            db.add(m.SystemSetting(key=DEFAULT_PLAN_KEY, value="essentials"))
        elif (cfg.value or "starter") in _OLD_PLAN_IDS:
            cfg.value = "essentials"
        db.flush()
    if have < "3":                                                                # v2 -> v3: users scale with price; extra-user add-ons
        for p in DEFAULT_PLANS:
            row = db.get(Plan, p["id"])
            if row is None:
                db.add(_plan_row(p))
            elif p["id"] in _V2_PLANS and row.seat_limit == _V2_PLANS[p["id"]][0] and (row.description or "").startswith(_V2_PLANS[p["id"]][1]):
                row.seat_limit, row.description = p["seat_limit"], p["description"]                                          # untouched v2 plan -> new users + wording
        for a in DEFAULT_ADDONS:
            row = db.get(Addon, a["id"])
            if row is None:
                db.add(_addon_row(a))
            elif a["id"] == "addon-seats-5" and row.price_monthly == Decimal("15.00"):                                         # unedited v2 pack -> A$5 per user
                row.price_monthly, row.description = Decimal(a["price_monthly"]), a["description"]
    if ver is None:
        db.add(m.SystemSetting(key=CATALOGUE_VERSION_KEY, value=CATALOGUE_VERSION))
    else:
        ver.value = CATALOGUE_VERSION
    db.flush()


def get_settings(db: Session) -> dict:
    e = db.get(m.SystemSetting, ENFORCED_KEY)
    d = db.get(m.SystemSetting, DEFAULT_PLAN_KEY)
    return {"enforced": bool(e and (e.value or "").lower() == "on"), "default_plan": (d.value if d and d.value else "essentials")}


def set_settings(db: Session, enforced=None, default_plan=None):
    for key, val in ((ENFORCED_KEY, None if enforced is None else ("on" if enforced else "off")), (DEFAULT_PLAN_KEY, default_plan)):
        if val is None:
            continue
        row = db.get(m.SystemSetting, key)
        if row is None:
            db.add(m.SystemSetting(key=key, value=val))
        else:
            row.value = val
    db.flush()


def start_subscription(db: Session, org_id: int):
    """Called when an organisation is created: it gets the platform's default plan (harmless while enforcement is off)."""
    ensure_catalogue(db)
    plan = db.get(Plan, get_settings(db)["default_plan"]) or db.query(Plan).filter_by(is_active=True).order_by(Plan.sort_order).first()
    if plan and db.get(OrgSubscription, org_id) is None:
        db.add(OrgSubscription(org_id=org_id, plan_id=plan.id, status="active"))
        db.flush()


def _expired(sub: OrgSubscription, today: date) -> bool:
    if sub.status == "expired":
        return True
    if sub.status == "trial":
        return bool(sub.trial_ends and sub.trial_ends < today)
    if sub.status == "cancelled":
        return not sub.period_end or sub.period_end < today
    return bool(sub.period_end and sub.period_end + timedelta(days=GRACE_DAYS) < today)        # active / past_due


def member_count(db: Session, org_id: int) -> int:
    return db.query(m.OrgMembership).filter_by(org_id=org_id).count()


def entitlements(db: Session, org_id: int, today: date = None) -> dict:
    """-> enforced, grandfathered, plan_id, plan_name, status, read_only, modules (list), locked (list), seats, seats_used, addons, dates."""
    today = today or date.today()
    ensure_catalogue(db)
    cfg = get_settings(db)
    sub = db.get(OrgSubscription, org_id)
    used = member_count(db, org_id)
    base = dict(enforced=cfg["enforced"], seats_used=used, catalogue=[dict(id=i, name=n) for i, n in CATALOGUE], domains=[dict(id=i, name=n, modules=ms) for i, n, ms in DOMAINS])
    if sub is None or db.get(Plan, sub.plan_id) is None:
        return {**base, "grandfathered": True, "plan_id": None, "plan_name": "All modules (no plan assigned)", "status": "active", "read_only": False,
                "modules": list(CATALOGUE_IDS), "locked": [], "seats": None, "addons": [], "trial_ends": None, "period_end": None, "billing_period": None}
    plan = db.get(Plan, sub.plan_id)
    ads = [a for a in (db.get(Addon, i) for i in dict.fromkeys(_loads(sub.addons))) if a]               # each add-on once, however often it is listed
    allowed = expand(_loads(plan.modules))
    for a in ads:
        allowed |= expand(_loads(a.modules))
    seats = None if plan.seat_limit is None else plan.seat_limit + sum(a.extra_seats or 0 for a in ads)
    expired = _expired(sub, today)
    locked = [] if not cfg["enforced"] else [i for i in CATALOGUE_IDS if i not in allowed]
    return {**base, "grandfathered": False, "plan_id": plan.id, "plan_name": plan.name, "status": "expired" if expired else sub.status, "read_only": bool(expired and cfg["enforced"]),
            "modules": [i for i in CATALOGUE_IDS if i in allowed], "locked": locked, "seats": seats, "addons": [dict(id=a.id, name=a.name) for a in ads],
            "trial_ends": sub.trial_ends.isoformat() if sub.trial_ends else None, "period_end": sub.period_end.isoformat() if sub.period_end else None, "billing_period": sub.billing_period}


def is_allowed(ent: dict, features) -> bool:
    if not ent["enforced"] or ent["grandfathered"]:
        return True
    return any(f in ent["modules"] for f in features)


def check(db: Session, ctx, features, method: str = "GET"):
    """Raise 402 when this organisation's subscription does not cover the feature (or is read-only and the call changes data)."""
    if ctx.is_admin:                                   # platform administrators (support) are never blocked
        return
    ent = entitlements(db, ctx.org.id)
    if not ent["enforced"]:
        return
    if ent["read_only"] and method not in SAFE_METHODS:
        raise HTTPException(402, "This organisation's subscription has expired, so it is read-only. Renew the plan to post or edit (Settings > Business Setup > Organisation > Subscription).")
    if not is_allowed(ent, features):
        label = {i: n for i, n in CATALOGUE}.get(features[0], features[0])
        raise HTTPException(402, f"'{label}' is not included in your {ent['plan_name']} plan. Ask an owner to upgrade or add it (Settings > Business Setup > Organisation > Subscription).")


def feature_gate(*features):
    """Router-level dependency: include_router(..., dependencies=[Depends(feature_gate('sales'))]). Several ids = any of them."""
    from accfino_core.security.context import current_org

    def dep(request: Request, ctx=Depends(current_org), db: Session = Depends(get_db)):
        check(db, ctx, features, request.method)
    return dep


def check_seat(db: Session, ctx):
    """Block adding a member beyond the licensed users. Licensed seats are a licence term, so this applies whether or not module enforcement is on;
    codes still waiting to be used count as taken. Existing members are never removed."""
    if ctx.is_admin:
        return
    from accfino_core.tenancy.service import seat_status
    st = seat_status(db, ctx.org.id)
    if st["available"] is not None and st["available"] <= 0:
        plan = entitlements(db, ctx.org.id)["plan_name"]
        raise HTTPException(402, f"Your {plan} plan allows {st['licensed']} user(s) and all are in use or reserved by access codes. Upgrade the plan, revoke unused access codes, or add a seat pack.")
