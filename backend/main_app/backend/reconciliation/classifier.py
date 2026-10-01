"""
backend/reconciliation/classifier.py
-------------------------------------
classify_transactions(df) - annotated DataFrame

Responsibilities
  1. Resolve ambiguous rows (both debit+credit non-zero)
  2. Match internal transfers across accounts (pair-id tagging)
  3. Classify every remaining row in one vectorised call via engine.classify_df
  4. Add Month, Year columns
"""

from __future__ import annotations

import itertools
from pathlib import Path
from typing import Optional

import pandas as pd

_ST = False  # streamlit removed

from backend.classifier.engine import classify_df, warm as _warm
from backend.reconciliation.company_resolver import CompanyResolver

_TRANSFER_KW = [
    "transfer","trf","tfr","internet transfer","inter-bank","interbank",
    "funds transfer","bank transfer","direct transfer","telegraphic","wire",
    "remittance","remit","bpay transfer","online transfer","account transfer",
    "internal transfer","own account","self transfer","sweep","redraw",
    "linked account",
    # FIX 6: directional patterns were being missed
    "transfer to","transfer from","tfr to","tfr from","trf to","trf from",
    "fast transfer","osko","pay anyone","ib transfer",
]
_EXCLUDE_KW = [
    "salary","wages","payroll","pay run","payg","superannuation","super",
    "dividend","invoice","bill payment","direct debit","insurance","mortgage",
    "loan repayment","subscription","direct credit","ato ","tax payment",
    "council ","rent ","lease ","refund",
]


class _NoOp:
    def progress(self, *a, **kw): pass
    def empty(self): pass


def _is_transfer(desc: str) -> bool:
    dl = desc.lower()
    if any(k in dl for k in _EXCLUDE_KW):
        return False
    return any(k in dl for k in _TRANSFER_KW)


import re as _re

def _extract_who(desc: str) -> str:
    """FIX 6: Extract To/From counterparty from transfer description.
    'Transfer to SAVINGS 12345' -> 'To: SAVINGS 12345'
    'TFR FROM CBA 9999'         -> 'From: CBA 9999'
    """
    m = _re.search(r"\b(?:transfer|tfr|trf)\s+to\s+([\w\s]{2,30})", desc, _re.IGNORECASE)
    if m: return f"To: {m.group(1).strip()}"
    m = _re.search(r"\b(?:transfer|tfr|trf)\s+from\s+([\w\s]{2,30})", desc, _re.IGNORECASE)
    if m: return f"From: {m.group(1).strip()}"
    return ""


def _parse_date(v):
    return pd.to_datetime(v, dayfirst=True, errors="coerce")


def _round2(v) -> float:
    try:
        return round(float(v), 2)
    except Exception:
        return 0.0


def classify_transactions(
    df:            pd.DataFrame,
    home_company:  str = "",
    db=None,
    account_id:    str            = "__default__",
    coa_path:      Optional[Path] = None,
    show_progress: bool            = True,
) -> pd.DataFrame:
    """
    Full reconciliation pipeline:
      1. Normalise columns
      2. Resolve ambiguous debit+credit rows
      3. Match internal transfers (pair IDs)
      4. Classify remaining rows (GL / GST category / GST amount)
      5. Add Month, Year columns

    Returns the annotated DataFrame.
    """
    df = df.copy()
    df.columns = df.columns.str.strip().str.lower()
    df = df.reset_index(drop=True)

    df["debit"]  = pd.to_numeric(df.get("debit",  0), errors="coerce").fillna(0.0)
    df["credit"] = pd.to_numeric(df.get("credit", 0), errors="coerce").fillna(0.0)

    # -- 1. Resolve ambiguous rows ----------------------------------------
    def _resolve(row):
        d, c = row.get("debit", 0), row.get("credit", 0)
        if not (d > 0 and c > 0):
            return row
        desc = str(row.get("description", "")).lower()
        if any(k in desc for k in ["transfer to","payment","card","bill","invoice"]):
            row["debit"], row["credit"] = d, 0
        elif any(k in desc for k in ["direct credit","salary","refund","fast transfer from"]):
            row["debit"], row["credit"] = 0, c
        else:
            row["debit"], row["credit"] = d, 0
        return row

    # Vectorised resolve: rows where both debit>0 and credit>0 simultaneously
    _both = (df["debit"] > 0) & (df["credit"] > 0)
    if _both.any():
        _desc = df.loc[_both, "description"].astype(str).str.lower() if "description" in df.columns else pd.Series("", index=df.index[_both])
        _debit_kw  = _desc.str.contains("transfer to|payment|card|bill|invoice", na=False)
        _credit_kw = _desc.str.contains("direct credit|salary|refund|fast transfer from", na=False)
        # Default: treat as debit
        df.loc[_both & _debit_kw,  "credit"] = 0
        df.loc[_both & _credit_kw & ~_debit_kw, "debit"] = 0
        df.loc[_both & ~_debit_kw & ~_credit_kw, "credit"] = 0

    # -- Initialise output columns ----------------------------------------
    df["classification"] = None
    df["pairid"]         = None
    df["GL Account"]     = ""
    df["GL Type"]        = ""
    df["GST"]            = 0.0
    df["GST Category"]   = ""

    pair_counter    = itertools.count(1)
    matched_debits  = set()
    matched_credits = set()

    # -- 2. Internal transfer matching ------------------------------------
    # NOTE: use df.index directly - avoids itertuples() _-prefix attribute
    # bug where pandas silently renames columns starting with underscore.
    pb = _NoOp()
    if show_progress and _ST:
        try:
            pb = st.progress(0, text="Matching internal transfers-")
        except Exception:
            pass

    has_date = "date" in df.columns
    has_bank = "bank" in df.columns
    has_acct = "account" in df.columns
    has_desc = "description" in df.columns

    debit_by_amt:  dict = {}
    credit_by_amt: dict = {}

    for idx in df.index:
        d    = _round2(df.at[idx, "debit"])
        c    = _round2(df.at[idx, "credit"])
        desc = str(df.at[idx, "description"]) if has_desc else ""
        dt   = _parse_date(df.at[idx, "date"])  if has_date else pd.NaT
        bank = str(df.at[idx, "bank"])           if has_bank else ""
        acct = str(df.at[idx, "account"])        if has_acct else ""

        if d > 0:
            debit_by_amt.setdefault(d, []).append((idx, dt, bank, acct, desc))
        if c > 0:
            credit_by_amt.setdefault(c, []).append((idx, dt, bank, acct, desc))

    MAX_DAYS = 5
    MAX_CANDIDATES = 50   # cap per-amount bucket to prevent O(n²) blowup

    # -- Scoring helper -------------------------------------------------------
    # A pair qualifies as an internal transfer if it meets AT LEAST ONE of:
    #   A) Both descriptions contain transfer keywords
    #   B) One description contains a transfer keyword (the initiating side)
    #   C) Descriptions reference each other's account/bank name
    #   D) Different accounts/banks, same amount, debit date <= credit date,
    #      within MAX_DAYS - structural match (no keyword needed)
    #
    # Issue 6 fix: the old code required BOTH rows to have transfer keywords.
    # Many real transfers only have a keyword on one side (e.g. "TFR TO SAVINGS"
    # on the debit row, but just "CREDIT RECEIVED" on the credit row).
    # Now we score all viable pairs and use a minimum score threshold.

    MIN_PAIR_SCORE = 5   # at least one positive signal required

    for amount in sorted(debit_by_amt):
        if amount not in credit_by_amt:
            continue

        debits = sorted(
            [x for x in debit_by_amt[amount]  if x[0] not in matched_debits],
            key=lambda x: x[1] if pd.notnull(x[1]) else pd.Timestamp.max,
        )[:MAX_CANDIDATES]
        credits = sorted(
            [x for x in credit_by_amt[amount] if x[0] not in matched_credits],
            key=lambda x: x[1] if pd.notnull(x[1]) else pd.Timestamp.max,
        )[:MAX_CANDIDATES]
        if not debits or not credits:
            continue

        scores = []
        for i, (di, ddt, dbk, dac, dds) in enumerate(debits):
            for j, (ci, cdt, cbk, cac, cds) in enumerate(credits):

                # Rule: must be different account or different bank
                if dac == cac and dbk == cbk:
                    continue

                # Rule: skip if either description has an exclude keyword
                # (salary, payroll, invoice etc — these are NOT internal transfers)
                _ddl, _cdl = dds.lower(), cds.lower()
                if any(k in _ddl for k in _EXCLUDE_KW) or any(k in _cdl for k in _EXCLUDE_KW):
                    continue

                # Rule: dates must be available
                if pd.isna(ddt) or pd.isna(cdt):
                    # Allow if at least one description has transfer keyword
                    if not (_is_transfer(dds) or _is_transfer(cds)):
                        continue
                    # Can't apply date ordering without dates - allow with keyword
                    sc = 0
                    dl, cl2 = dds.lower(), cds.lower()
                    if _is_transfer(dds): sc += 15
                    if _is_transfer(cds): sc += 15
                    if dac.lower() in cl2 or cac.lower() in dl: sc += 20
                    if dbk.lower() in cl2 or cbk.lower() in dl: sc += 10
                    if sc >= MIN_PAIR_SCORE:
                        scores.append((sc, i, j, di, ci))
                    continue

                # Rule: credit date must NOT be earlier than debit date
                # (money must leave before it arrives - allow same day)
                if cdt < ddt:
                    continue

                day_diff = (cdt - ddt).days   # signed: credit is after debit
                if day_diff > MAX_DAYS:
                    continue

                sc = 0
                dl, cl2 = dds.lower(), cds.lower()

                # Keyword signals (either side counts)
                if _is_transfer(dds): sc += 15
                if _is_transfer(cds): sc += 15

                # Cross-reference: description mentions the other account/bank
                if dac.lower() in cl2 or cac.lower() in dl: sc += 20
                if dbk.lower() in cl2 or cbk.lower() in dl: sc += 10

                # Different bank is a stronger transfer signal
                if dbk != cbk: sc += 8

                # Closer dates = higher score
                sc += (MAX_DAYS - day_diff) * 4

                # Structural match: same amount, different accounts,
                # debit before credit, within window - even without keywords
                # this is a meaningful signal (score from date proximity alone
                # will be > 0, but we also give a base structural bonus)
                if sc == (MAX_DAYS - day_diff) * 4 + (8 if dbk != cbk else 0):
                    # Only structural signal - require different banks to avoid
                    # false positives on same-bank same-account-holder payments
                    if dbk == cbk:
                        continue   # same bank, no keywords - too risky to auto-pair

                if sc >= MIN_PAIR_SCORE:
                    scores.append((sc, i, j, di, ci))

        scores.sort(key=lambda x: -x[0])
        used_d, used_c = set(), set()
        for sc, i, j, di, ci in scores:
            if i in used_d or j in used_c:
                continue
            if di in matched_debits or ci in matched_credits:
                continue
            pid = f"PAIR{next(pair_counter):05d}"
            df.loc[int(di), ["classification", "pairid"]] = ["-Internal", pid]
            df.loc[int(ci), ["classification", "pairid"]] = ["-Internal", pid]
            matched_debits.add(int(di))
            matched_credits.add(int(ci))
            used_d.add(i); used_c.add(j)

    # -- Pass 2: fuzzy amount matching (same-direction within 0.5%) --------------
    # Handles cases where a bank fee is deducted in transit:
    # e.g. debit $1,000 - credit $999.50 (fee deducted by receiving bank)
    # Both rows must have at least one transfer keyword to qualify.
    TOLERANCE = 0.005

    unmatched_d = [
        (idx, dt, bk, ac, ds, amt)
        for amt, rows in debit_by_amt.items()
        for (idx, dt, bk, ac, ds) in rows
        if idx not in matched_debits and _is_transfer(ds)
    ]
    unmatched_c = [
        (idx, dt, bk, ac, ds, amt)
        for amt, rows in credit_by_amt.items()
        for (idx, dt, bk, ac, ds) in rows
        if idx not in matched_credits and _is_transfer(ds)
    ]

    for d_idx, d_dt, d_bk, d_ac, d_ds, d_amt in unmatched_d:
        if d_idx in matched_debits or d_amt == 0:
            continue
        best_ci, best_sc = None, -1
        for c_idx, c_dt, c_bk, c_ac, c_ds, c_amt in unmatched_c:
            if c_idx in matched_credits:
                continue
            if d_ac == c_ac and d_bk == c_bk:
                continue
            diff_pct = abs(d_amt - c_amt) / d_amt
            if diff_pct > TOLERANCE:
                continue
            if pd.isna(d_dt) or pd.isna(c_dt):
                continue
            if c_dt < d_dt:
                continue
            day_diff = (c_dt - d_dt).days
            if day_diff > MAX_DAYS:
                continue
            sc = 50 - day_diff * 4   # base score for fuzzy match
            if d_bk != c_bk: sc += 8
            dl, cl2 = d_ds.lower(), c_ds.lower()
            if d_ac.lower() in cl2 or c_ac.lower() in dl: sc += 20
            if sc > best_sc:
                best_sc = sc
                best_ci = c_idx
        if best_ci is not None:
            pid = f"PAIR{next(pair_counter):05d}"
            df.loc[int(d_idx), ["classification", "pairid"]] = ["-Internal", pid]
            df.loc[int(best_ci), ["classification", "pairid"]] = ["-Internal", pid]
            matched_debits.add(int(d_idx))
            matched_credits.add(int(best_ci))

    pb.progress(1.0, text="Transfer matching complete -")

    # -- 3. Classify non-internal rows via engine -------------------------
    mask = df["classification"].isna()

    if mask.any():
        _warm(account_id, coa_path)
        sub = df[mask].copy()
        sub = classify_df(sub, account_id=account_id, coa_path=coa_path)

        df.loc[mask, "GL Account"]   = sub["gl_account"].values
        df.loc[mask, "GL Type"]      = sub["gl_type"].values
        df.loc[mask, "GST Category"] = sub["gst_category"].values
        df.loc[mask, "GST"]          = sub["gst_amount"].values

        df.loc[mask & (df["debit"]  > 0), "classification"] = "-Outgoing"
        df.loc[mask & (df["credit"] > 0), "classification"] = "-Incoming"

    df["classification"] = df["classification"].fillna("-Unclassified")

    # -- Who field: CompanyResolver (home company, DB, bank patterns) ---------
    if "Who" not in df.columns:
        df["Who"] = ""

    resolver = CompanyResolver(db=db, home_company=home_company)

    for idx in df.index:
        desc   = str(df.at[idx, "description"]) if "description" in df.columns else ""
        debit  = float(df.at[idx, "debit"])     if "debit"       in df.columns else 0.0
        credit = float(df.at[idx, "credit"])    if "credit"      in df.columns else 0.0
        cl     = str(df.at[idx, "classification"])

        who, is_internal = resolver.resolve(desc, debit, credit)

        # Home company match — only mark as Internal when the row has not
        # already been classified as Incoming or Outgoing. This prevents the
        # company name appearing in a supplier/payee description from
        # incorrectly overriding a legitimate expense or income transaction.
        # Rows that are already "-Internal" (pair-matched) are left alone too.
        already_classified = cl in ("-Incoming", "-Outgoing", "-Internal")
        if is_internal and not already_classified:
            df.at[idx, "classification"] = "-Internal"
            df.at[idx, "GL Account"]     = ""
            df.at[idx, "GST Category"]   = ""
            df.at[idx, "GST"]            = 0.0

        if who:
            df.at[idx, "Who"] = who
        elif cl == "-Internal":
            extracted = _extract_who(desc)
            if extracted:
                df.at[idx, "Who"] = extracted

    # -- 4. Date parts ----------------------------------------------------
    if has_date:
        df["Month"] = df["date"].apply(lambda x: getattr(x, "month", None))
        df["Year"]  = df["date"].apply(lambda x: getattr(x, "year",  None))

    return df