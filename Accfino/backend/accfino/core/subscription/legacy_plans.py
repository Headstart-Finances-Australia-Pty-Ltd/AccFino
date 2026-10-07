"""Legacy plan catalogue (pricing_plans table -> pricing.json in the data root -> built-in fallback). Used by the pricing endpoints and by Stripe checkout."""
import os as _os
from pathlib import Path as _Path

# pricing.json lives in the data root (ACCFINO_DATA_ROOT/reference)
from accfino.shared import paths as _paths
_PRICING_CANDIDATES = [_paths.reference_file("pricing.json")]

def _find_pricing_file():
    for p in _PRICING_CANDIDATES:
        if p.exists():
            return p
    return None

def _load_plans() -> dict:
    """Load plans -- Postgres (pricing_plans table) is now authoritative,
    matching every other data source in this app. Falls back to
    pricing.json (if the table is empty/unreachable, e.g. a brand-new DB
    before the startup migration has run), then to the hardcoded dict as
    a last resort so the app never has zero plans to show."""
    try:
        from accfino.shared.db.database import SessionLocal
        from accfino.core.subscription.pricing_model import PricingPlan
        db = SessionLocal()
        try:
            rows = db.query(PricingPlan).order_by(PricingPlan.sort_order).all()
            if rows:
                return {r.slug: r.to_dict() for r in rows}
        finally:
            db.close()
    except Exception:
        pass  # DB not ready yet -- fall through to JSON/hardcoded

    p = _find_pricing_file()
    if p:
        try:
            import json as _j
            data = _j.loads(p.read_text(encoding="utf-8"))
            if data and isinstance(data, dict):
                return data
        except Exception:
            pass
    # Final fallback to hardcoded plans - must match pricing_plans table exactly
    return _FALLBACK_PLANS

_FALLBACK_PLANS = {
    # ── Free base / Vault plan ─────────────────────────────────────────────────
    "base":          {"name":"Vault",          "price_monthly":0,    "price_yearly":0,
                      "modules":["dashboard","accounting","reconciliation"],
                      "features":["Unlimited CSV Reconciliation","GL & GST auto-classify","Sales & Purchases","Customers & Suppliers","Excel export"],
                      "highlight":False,"badge":"Free","category":"accounting",
                      "description":"Free forever — CSV Reconciliation + Sales, Purchases, Customers & Suppliers"},

    # ── Accounting plans ────────────────────────────────────────────────────────
    "accounting_pro":     {"name":"Accounting Pro",    "price_monthly":2900,"price_yearly":29000,
                      "modules":["dashboard","accounting","reconciliation","cash-flow"],
                      "features":["Everything in Starter","Open Banking","ML Cash Flow forecast","Financial Reports (P&L, BS, BAS)","20+ reports"],
                      "highlight":True,"badge":"Popular","category":"accounting",
                      "description":"Full accounting suite with Open Banking, Cash Flow & 20+ financial reports"},

    # ── Trading & Taxation plans ────────────────────────────────────────────────
    "taxation_complete":  {"name":"Taxation Complete", "price_monthly":2500,"price_yearly":25000,
                      "modules":["dashboard","trading"],
                      "features":["Everything in Basic","Property CGT calculator","Tax Return Data (full ITR)","All income, deductions & offsets","HELP/HECS repayment"],
                      "highlight":False,"badge":"","category":"trading",
                      "description":"Complete Australian tax — CGT (Crypto, Shares, Property) + full ITR data"},

    # ── Payroll plans ───────────────────────────────────────────────────────────
    "payroll_business":   {"name":"Payroll Business",  "price_monthly":4900,"price_yearly":49000,
                      "modules":["dashboard","payroll"],
                      "features":["Everything in Essential","Unlimited employees","STP Phase 2 / ATO filing","Annual payment summaries","Priority support"],
                      "highlight":True,"badge":"Popular","category":"payroll",
                      "description":"Full Australian payroll with STP Phase 2, unlimited employees & ATO compliance"},

    # ── Bundle plans ────────────────────────────────────────────────────────────
    "premium":                    {"name":"Ultra Plan",            "price_monthly":7900,"price_yearly":79000,
                      "modules":["dashboard","accounting","reconciliation","trading","cash-flow","payroll"],
                      "features":["Everything in Accounting Pro","Everything in Taxation Complete","Full Payroll Business","Open Banking","Priority support","Early access features"],
                      "highlight":True,"badge":"Best Value","category":"bundle",
                      "description":"Ultra Plan — all modules — Accounting, Taxation & Payroll — best value complete suite"},
}

# Load plans dynamically - refreshed on each request via property
try:                                              # the hard-coded fallback is the shipped organisation plans in the old shape (never the retired Vault / Ultra list)
    from accfino.core.subscription.align import legacy_plans_dict as _legacy_plans_dict
    _FALLBACK_PLANS = _legacy_plans_dict()
except Exception:
    pass
PLANS = _load_plans()
