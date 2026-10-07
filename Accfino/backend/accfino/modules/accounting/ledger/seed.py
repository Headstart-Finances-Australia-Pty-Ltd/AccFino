"""Organisation provisioning for Accounting: seed the AU standard chart of accounts and GST tax codes (idempotent). Moved out of core.migrate."""
from decimal import Decimal

from sqlalchemy import text

from accfino.modules.accounting.coa.au_standard import ACCOUNTS, LEGACY_TYPE_MAP, TAX_CODES
from accfino.modules.accounting.models import ledger as lm
from accfino.core.models import Organisation


def seed_org_ledger(db, org: "Organisation") -> None:
    """Seed tax codes and the AU standard COA for an organisation (idempotent)."""
    existing_tax = {t.name: t for t in db.query(lm.TaxCode).filter_by(org_id=org.id)}
    for code, name, rate, applies, labels in TAX_CODES:
        if name not in existing_tax:
            t = lm.TaxCode(org_id=org.id, code=code, name=name, rate=Decimal(rate),
                          applies_to=applies, bas_labels=labels, is_system=True)
            db.add(t)
            existing_tax[name] = t
    db.flush()

    existing = {a.name.lower(): a for a in db.query(lm.LedgerAccount).filter_by(org_id=org.id)}
    codes = {a.code for a in existing.values()}
    for code, name, atype, tax_name, sys_key in ACCOUNTS:
        if name.lower() in existing or code in codes:
            continue
        acc = lm.LedgerAccount(
            org_id=org.id, code=code, name=name, account_type=atype,
            account_class=lm.ACCOUNT_TYPES[atype],
            default_tax_code_id=existing_tax[tax_name].id if tax_name in existing_tax else None,
            system_key=sys_key,
        )
        db.add(acc)
        existing[name.lower()] = acc
        codes.add(code)
    db.flush()

    # Accounts users previously added to the legacy (global) chart_of_accounts table
    try:
        legacy = db.execute(text("SELECT name, type FROM chart_of_accounts")).fetchall()
    except Exception:
        db.rollback()
        legacy = []
    n = 1
    for name, ltype in legacy:
        if not name or name.lower() in existing:
            continue
        atype = LEGACY_TYPE_MAP.get((ltype or "").strip().lower(), "expense")
        while f"U{n:03d}" in codes:
            n += 1
        code = f"U{n:03d}"
        acc = lm.LedgerAccount(org_id=org.id, code=code, name=name[:200], account_type=atype,
                              account_class=lm.ACCOUNT_TYPES[atype],
                              description="Imported from legacy chart of accounts")
        db.add(acc)
        existing[name.lower()] = acc
        codes.add(code)
    db.flush()
