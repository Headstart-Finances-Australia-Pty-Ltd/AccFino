"""
react_api_helpers.py
====================
Drop these functions into main_app/react_api.py (or import from here).
They are called by the modified /reconcile/process and /reconcile/process-with-session.

IMPORT TO ADD at the top of react_api.py:
    from backend.reconciliation.currency_service import convert_to_aud, SUPPORTED_CURRENCIES
"""

import pandas as pd
import logging

logger = logging.getLogger(__name__)

# ─────────────────────────────────────────────────────────────────────────────
# LOAN KEYWORDS — same patterns as rdr_rules.json "out_loan"
# ─────────────────────────────────────────────────────────────────────────────
_LOAN_KEYWORDS = [
    "bmw financial", "bmw finance", "toyota finance", "toyota financial",
    "mercedes finance", "mercedes benz financial", "vw finance",
    "volkswagen financial", "nissan finance", "mazda finance",
    "honda finance", "hyundai finance", "subaru finance", "kia finance",
    "ford finance", "macquarie leasing", "macquarie asset finance",
    "westpac asset finance", "nab asset finance", "anz asset finance",
    "angle finance", "selfco leasing", "pepper asset",
    "car loan", "auto loan", "vehicle loan", "vehicle finance",
    "principal & interest", "interest & principal",
    "hire purchase", "chattel mortgage", "mortgage repayment",
    "home loan repayment", "home loan", "personal loan",
    "business loan", "loan repayment", "loan payment",
]

# Typical interest portion as a fraction of total payment when unknown
_DEFAULT_INTEREST_RATE_PA = 10.0   # 10% per annum


def _apply_currency_conversion(df: pd.DataFrame, currency: str) -> pd.DataFrame:
    """
    Convert Debit and Credit columns from `currency` to AUD in-place.
    Adds columns: Currency, Amount_Original_Debit, Amount_Original_Credit, Exchange_Rate.
    """
    from backend.reconciliation.currency_service import convert_to_aud

    currency = (currency or "AUD").upper().strip()

    # Store original amounts before conversion
    if "debit" in df.columns:
        df["amount_original_debit"] = df["debit"].copy()
    if "credit" in df.columns:
        df["amount_original_credit"] = df["credit"].copy()

    df["currency"] = currency

    if currency == "AUD":
        df["exchange_rate"] = 1.0
        return df

    # Fetch rate once for the whole batch
    try:
        from backend.reconciliation.currency_service import get_rate_to_aud
        rate = get_rate_to_aud(currency)
    except Exception as e:
        logger.warning(f"Exchange rate fetch failed ({currency}): {e} — using 1.0")
        rate = 1.0

    df["exchange_rate"] = rate

    if "debit" in df.columns:
        df["debit"] = (df["debit"].fillna(0) * rate).round(4)
    if "credit" in df.columns:
        df["credit"] = (df["credit"].fillna(0) * rate).round(4)
    if "balance" in df.columns:
        df["balance"] = df["balance"].apply(
            lambda x: round(float(x) * rate, 4) if x is not None and str(x) not in ("", "nan") else None
        )

    logger.info(f"Currency conversion: {currency}->AUD @ {rate}, rows={len(df)}")
    return df


def _detect_loan_payments(df: pd.DataFrame) -> pd.DataFrame:
    """
    Detect loan payment rows and populate is_loan_payment, loan_principal,
    loan_interest columns.

    If the description contains known loan keywords, the transaction is flagged.
    The split is:
      - If both a 'principal' and 'interest' amount can be parsed from the
        description (e.g. "P&I $1,200 / $250"), use those.
      - Otherwise, use the 30/70 interest/principal heuristic.
    """
    import re

    df = df.copy()

    for col in ("is_loan_payment", "loan_principal", "loan_interest"):
        if col not in df.columns:
            df[col] = None
    df["is_loan_payment"] = False

    # Build description column reference (handles mixed case col names)
    desc_col = None
    for c in ("Description", "description"):
        if c in df.columns:
            desc_col = c
            break
    if not desc_col:
        return df

    def _is_loan(desc: str) -> bool:
        d = str(desc).lower()
        return any(kw in d for kw in _LOAN_KEYWORDS)

    def _parse_split(desc: str, total: float):
        """Try to extract explicit principal/interest from description."""
        # Patterns like "P $1200 I $230", "principal 1200 interest 230", "$1200 / $230"
        patterns = [
            r"principal[:\s$]*([0-9,]+\.?[0-9]*)[^0-9]*interest[:\s$]*([0-9,]+\.?[0-9]*)",
            r"p[:\s$]*([0-9,]+\.?[0-9]*)[^0-9]*i[:\s$]*([0-9,]+\.?[0-9]*)",
            r"([0-9,]+\.?[0-9]*)\s*/\s*([0-9,]+\.?[0-9]*)",
        ]
        d = str(desc).lower()
        for pat in patterns:
            m = re.search(pat, d)
            if m:
                try:
                    a, b = float(m.group(1).replace(",", "")), float(m.group(2).replace(",", ""))
                    if abs(a + b - total) < total * 0.05:  # within 5% of total
                        return round(a, 2), round(b, 2)
                except Exception:
                    pass
        return None, None

    debit_col  = "Debit"  if "Debit"  in df.columns else "debit"  if "debit"  in df.columns else None
    credit_col = "Credit" if "Credit" in df.columns else "credit" if "credit" in df.columns else None

    for idx in df.index:
        desc = str(df.at[idx, desc_col])
        if not _is_loan(desc):
            continue

        # Only flag debit (outgoing) transactions as loan payments
        debit_val  = float(df.at[idx, debit_col]  or 0) if debit_col  else 0
        credit_val = float(df.at[idx, credit_col] or 0) if credit_col else 0
        total = debit_val if debit_val > 0 else credit_val
        if total <= 0:
            continue

        df.at[idx, "is_loan_payment"] = True

        principal, interest = _parse_split(desc, total)
        if principal is not None:
            df.at[idx, "loan_principal"] = principal
            df.at[idx, "loan_interest"]  = interest
        else:
            r = _DEFAULT_INTEREST_RATE_PA / 100 / 12
            principal_amt = round(total / (1 + r), 2)
            interest_amt  = round(total - principal_amt, 2)
            df.at[idx, "loan_principal"] = principal_amt
            df.at[idx, "loan_interest"]  = interest_amt
        p = float(df.at[idx, "loan_principal"] or 0)
        i = float(df.at[idx, "loan_interest"]  or 0)
        df.at[idx, "loan_interest_rate"] = round((i/p)*12*100,2) if (p>0 and i>0) else _DEFAULT_INTEREST_RATE_PA

    return df


def _persist_transactions_to_db(username: str, transactions: list, currency: str = "AUD") -> None:
    """Bulk-upsert with batch dedup to avoid CardinalityViolation."""
    from db_app.database import SessionLocal
    from db_app.models.user import User
    from db_app.models.transaction import Transaction
    from sqlalchemy.dialects.postgresql import insert as pg_insert
    from datetime import datetime
    db = SessionLocal()
    try:
        user = db.query(User).filter(User.username == username).first()
        if not user:
            logger.warning(f"DB persist: no user found for '{username}'"); return
        uid = user.id
        rows, seen, skipped = [], set(), 0
        for tx in transactions:
            try:
                raw = tx.get("date") or tx.get("Date")
                dt = None
                if isinstance(raw, str):
                    for fmt in ("%d/%m/%Y","%Y-%m-%d","%m/%d/%Y"):
                        try: dt = datetime.strptime(raw, fmt); break
                        except ValueError: pass
                elif isinstance(raw, datetime): dt = raw
                if not dt: skipped+=1; continue
                bk = str(tx.get("bank", tx.get("Bank",""))).strip()
                ac = str(tx.get("account", tx.get("Account",""))).strip()
                ds = str(tx.get("description", tx.get("Description",""))).strip()
                db_ = float(tx.get("debit",  tx.get("Debit",  0)) or 0)
                cr  = float(tx.get("credit", tx.get("Credit", 0)) or 0)
                if not bk or not ac or not ds: skipped+=1; continue
                key = (uid, dt.date(), bk, ac, ds, db_, cr)
                if key in seen: skipped+=1; continue
                seen.add(key)
                bal = tx.get("balance")
                bb  = float(bal) if bal is not None and str(bal) not in ("","nan","None") else None
                rows.append({"user_id":uid,"date":dt,"bank":bk,"account":ac,"description":ds,
                    "debit":db_,"credit":cr,"bank_balance":bb,"currency":currency,
                    "amount_original": float(tx.get("amount_original_debit") or tx.get("amount_original_credit") or 0) or None,
                    "exchange_rate": float(tx.get("exchange_rate",1.0) or 1.0),
                    "classification":tx.get("classification"),
                    "pair_id":tx.get("pairid") or tx.get("pair_id"),
                    "gl_account":tx.get("gl_account"),"gst":float(tx.get("gst",0) or 0),
                    "gst_category":tx.get("gst_category"),"who":tx.get("who"),
                    "is_loan_payment":bool(tx.get("is_loan_payment",False)),
                    "loan_principal": float(tx["loan_principal"]) if tx.get("loan_principal") is not None else None,
                    "loan_interest":  float(tx["loan_interest"])  if tx.get("loan_interest")  is not None else None,
                    "loan_interest_rate": float(tx["loan_interest_rate"]) if tx.get("loan_interest_rate") is not None else None,
                    "loan_principal_gl":tx.get("loan_principal_gl"),
                    "loan_interest_gl":tx.get("loan_interest_gl"),
                })
            except Exception as e: logger.warning(f"Row prep: {e}"); skipped+=1
        if not rows: logger.info(f"DB persist: nothing (skipped={skipped})"); return
        try:
            stmt = pg_insert(Transaction).values(rows)
            stmt = stmt.on_conflict_do_update(constraint="uq_transaction", set_={
                "classification":stmt.excluded.classification,
                "gl_account":stmt.excluded.gl_account,
                "gst_category":stmt.excluded.gst_category,"gst":stmt.excluded.gst,
                "who":stmt.excluded.who,"pair_id":stmt.excluded.pair_id,
                "bank_balance":stmt.excluded.bank_balance,
                "is_loan_payment":stmt.excluded.is_loan_payment,
                "loan_principal":stmt.excluded.loan_principal,
                "loan_interest":stmt.excluded.loan_interest,
                "loan_interest_rate":stmt.excluded.loan_interest_rate,
                "loan_principal_gl":stmt.excluded.loan_principal_gl,
                "loan_interest_gl":stmt.excluded.loan_interest_gl,
            })
            db.execute(stmt); db.commit()
            logger.info(f"DB persist bulk: {len(rows)} upserted, {skipped} skipped")
        except Exception as be:
            logger.warning(f"Bulk failed, row-by-row: {be!s:.150}"); db.rollback(); saved=0
            for rd in rows:
                try:
                    ex = db.query(Transaction).filter(
                        Transaction.user_id==uid, Transaction.date==rd["date"],
                        Transaction.bank==rd["bank"], Transaction.account==rd["account"],
                        Transaction.description==rd["description"],
                        Transaction.debit==rd["debit"], Transaction.credit==rd["credit"],
                        Transaction.currency==currency).first()
                    if ex:
                        for k in ("classification","gl_account","gst_category","gst","who","pair_id"):
                            if rd.get(k) is not None: setattr(ex,k,rd[k])
                    else: db.add(Transaction(**rd))
                    saved+=1
                except:
                    try: db.rollback()
                    except: pass
                    skipped+=1
            try: db.commit()
            except: pass
            logger.info(f"DB persist row-by-row: saved={saved}, skipped={skipped}")
    finally:
        db.close()