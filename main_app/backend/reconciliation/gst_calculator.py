"""
backend/reconciliation/gst_calculator.py
-----------------------------------------
Thin compatibility shim.

All real logic lives in backend.classifier.engine.
This module exists so existing imports in react_api.py keep working:

    from backend.reconciliation.gst_calculator import (
        calculate_gst, calculate_gst_value, GST_CATEGORY_OPTIONS,
    )
"""

from __future__ import annotations

import pandas as pd
from pathlib import Path
from typing import Optional

from backend.classifier.engine import (
    _calc_gst         as _engine_calc,
    _is_taxable,
    gst_category_options,
    classify_df,
    DEFAULT_COA_PATH,
)

# -- GST_CATEGORY_OPTIONS - for UI dropdowns -------------------------------
# Derived from COA at import time; call gst_category_options() to refresh.
GST_CATEGORY_OPTIONS: list = gst_category_options(DEFAULT_COA_PATH)


def calculate_gst_value(debit: float, credit: float, gst_category: str) -> float:
    """1/11th rule. Returns 0.0 for non-taxable categories."""
    return _engine_calc(
        float(debit)  if pd.notnull(debit)  else 0.0,
        float(credit) if pd.notnull(credit) else 0.0,
        gst_category,
    )


def calculate_gst(df: pd.DataFrame, account_id: str = "__default__",
                  coa_path: Optional[Path] = None) -> pd.DataFrame:
    """
    Annotate a DataFrame with GST Category and GST columns.

    If GL Account is already present, the engine is NOT called - GST
    is computed purely from the existing GL Account's tax code.

    If GL Account is absent, classify_df() fills GL Account, GST Category
    and GST in one pass.
    """
    df = df.copy()
    df.columns = df.columns.str.strip().str.lower()

    has_gl = "gl account" in df.columns or "gl_account" in df.columns

    if not has_gl:
        df = classify_df(df, account_id=account_id, coa_path=coa_path)
        df = df.rename(columns={
            "gl_account":   "GL Account",
            "gst_category": "GST Category",
            "gst_amount":   "GST",
        })
        return df

    # GL already populated - just compute GST amounts from tax codes
    gl_col  = "gl account" if "gl account" in df.columns else "gl_account"
    gst_col = "gst category" if "gst category" in df.columns else \
              ("gst_category" if "gst_category" in df.columns else None)

    df["debit"]  = pd.to_numeric(df.get("debit",  0), errors="coerce").fillna(0.0)
    df["credit"] = pd.to_numeric(df.get("credit", 0), errors="coerce").fillna(0.0)

    if gst_col:
        df["GST"] = df.apply(
            lambda r: _engine_calc(r["debit"], r["credit"], str(r[gst_col] or "")),
            axis=1,
        )
    else:
        df["GST"] = 0.0

    return df
