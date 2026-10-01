"""
Keeps the classifier's account list in step with the organisation's ledger chart.

The ledger chart of accounts (ledger_accounts, per organisation) is the single
source of truth. The reconciliation classifier still matches on account *names*
from the legacy `chart_of_accounts` table / ChartOfAccounts.csv, so after every
ledger account change we mirror the names into that table and let main_app
refresh its in-memory list and classifier index (via a registered hook, which
avoids importing main_app from here).
"""
import logging

from sqlalchemy import text

from accfino_core import models as m

log = logging.getLogger(__name__)

# ledger account type -> legacy chart_of_accounts.type label
LEDGER_TO_LEGACY_TYPE = {
    "bank": "Bank", "current_asset": "Current Asset", "inventory": "Inventory",
    "fixed_asset": "Fixed Asset", "non_current_asset": "Fixed Asset",
    "credit_card": "Current Liability", "current_liability": "Current Liability",
    "non_current_liability": "Current Liability", "equity": "Equity",
    "revenue": "Revenue", "other_income": "Other Income", "direct_costs": "Direct Costs",
    "expense": "Expense", "other_expense": "Expense",
}

_hooks = []


def register_refresh_hook(fn):
    """main_app registers a callable that reloads its in-memory names + classifier index."""
    if fn not in _hooks:
        _hooks.append(fn)


def mirror_ledger_to_legacy(db, org_id: int) -> None:
    """Upsert active, non-bank, non-system ledger accounts into chart_of_accounts by name
    and drop archived ones. Never raises: the ledger change has already been committed."""
    try:
        accs = db.query(m.LedgerAccount).filter(m.LedgerAccount.org_id == org_id).all()
        for a in accs:
            if a.account_type == "bank" or a.system_key:
                continue
            legacy_type = LEDGER_TO_LEGACY_TYPE.get(a.account_type, "Expense")
            if a.is_active:
                db.execute(text(
                    "INSERT INTO chart_of_accounts (name, type) VALUES (:n, :t) "
                    "ON CONFLICT (name) DO UPDATE SET type = EXCLUDED.type"), {"n": a.name, "t": legacy_type})
            else:
                db.execute(text("DELETE FROM chart_of_accounts WHERE name = :n"), {"n": a.name})
        db.commit()
    except Exception as e:                      # e.g. legacy table absent, or a non-Postgres dev DB
        db.rollback()
        log.warning("Legacy chart mirror skipped: %s", e)
        return
    for fn in list(_hooks):
        try:
            fn()
        except Exception as e:
            log.warning("Classifier refresh hook failed: %s", e)
