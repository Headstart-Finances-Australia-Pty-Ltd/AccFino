"""
Trading / Capital Gains HTTP API: crypto/trading analysis + export, stock/equity CGT pipeline.
"""
import os
import sys
from pathlib import Path
from fastapi import APIRouter
from accfino.shared import paths as _paths

router = APIRouter()

import logging
logger = logging.getLogger("accfino")


import os
import base64, io, json, logging, os, sys, uuid
from typing import Any, Dict, List, Optional
import pandas as pd
from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile, Body
from fastapi.responses import Response, StreamingResponse
from accfino.modules.trading.data_parser import parse_trading_file
from accfino.modules.trading.report_presentation import generate_report_df
from accfino.modules.trading.trading_exporter import export_report_trading
import os as _os
import tempfile as _tempfile, uuid as _uuid
try:
    from accfino.modules.trading.equity_pipeline import run_trading_pipeline, TradingPipelineResult
    from accfino.modules.trading.equity.equity_engine import disposals_to_df, income_to_df, summary_to_df
    from accfino.modules.trading.exporters.excel_exporter import export_to_excel
    from accfino.modules.trading.common.local_cost_base_db import ensure_local_db, get_resolution_log
    _trading_module_ok = True
except Exception as _te:
    _trading_import_err = str(_te)

@router.post("/trading/analyze")
async def trading_analyze(file: UploadFile=File(...)):
    import tempfile, os as _os
    raw = await file.read()
    suffix = ".json" if (file.filename or "").lower().endswith(".json") else ".csv"
    with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
        tmp.write(raw); tmp_path = tmp.name
    try:
        trades_df = parse_trading_file(open(tmp_path, "rb"))
        _os.unlink(tmp_path)
    except Exception as e:
        raise HTTPException(400, f"Parse failed: {e}")
    if trades_df is None or trades_df.empty:
        raise HTTPException(400, "No valid trading records found")
    try:
        per_symbol_df, totals_df, tax_df = generate_report_df(trades_df)
    except Exception as e:
        raise HTTPException(500, f"Report failed: {e}")

    def sdf(df):
        if df is None or df.empty: return []
        d = df.copy()
        for c in d.columns:
            d[c] = d[c].apply(lambda x: None if (isinstance(x, float) and pd.isna(x)) else
                              (str(x) if hasattr(x, "isoformat") else x))
        return d.to_dict(orient="records")

    return {"trades": sdf(trades_df), "tax": sdf(tax_df),
            "per_symbol": sdf(per_symbol_df), "count": len(trades_df)}

@router.post("/trading/export")
async def trading_export(file: UploadFile=File(...)):
    import tempfile, os as _os
    raw = await file.read()
    suffix = ".json" if (file.filename or "").lower().endswith(".json") else ".csv"
    with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
        tmp.write(raw); tmp_path = tmp.name
    trades_df = parse_trading_file(open(tmp_path, "rb")); _os.unlink(tmp_path)
    per_symbol_df, totals_df, tax_df = generate_report_df(trades_df)
    xlsx = export_report_trading(trades_df, per_symbol_df, tax_df, None)
    return Response(content=xlsx,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": "attachment; filename=trading_report.xlsx"})

_EQUITY_DIR        = _paths.module_dir("trading")

_trading_module_ok = False

_trading_import_err = ""

def _stocks_clean(df) -> list:
    if df is None or df.empty: return []
    d = df.copy()
    for c in d.columns:
        d[c] = d[c].apply(lambda x: None if (isinstance(x, float) and pd.isna(x)) else
                          (str(x) if hasattr(x, "strftime") or hasattr(x, "isoformat") else x))
    return d.to_dict(orient="records")

@router.get("/stocks/status")
def stocks_status():
    return {
        "available":   _trading_module_ok,
        "module_root": str(_EQUITY_DIR),
        "error":       _trading_import_err if not _trading_module_ok else None,
    }

@router.post("/stocks/analyze")
async def stocks_analyze(
    files:          List[UploadFile] = File(...),
    financial_year: str              = Form("2024-25"),
):
    """
    Accept one or more broker Excel/CSV files.
    Runs the full HSLedger equity CGT pipeline (FIFO, ATO rules).
    Returns disposals, income, summary, and missing-buy flags.
    """
    if not _trading_module_ok:
        raise HTTPException(503, f"Stock trading module not available: {_trading_import_err}")

    # Write uploads to a temp directory
    tmp_dir = _tempfile.mkdtemp(prefix="accfino_stocks_")
    try:
        for upload in files:
            raw  = await upload.read()
            dest = os.path.join(tmp_dir, upload.filename or f"file_{_uuid.uuid4()}.xlsx")
            with open(dest, "wb") as f:
                f.write(raw)

        local_db = str(_paths.module_dir("trading", "cost_base") / "local_cost_base_db.json")
        ensure_local_db(local_db)

        result: TradingPipelineResult = run_trading_pipeline(
            source        = tmp_dir,
            local_db_path = local_db,
            target_fy     = financial_year,
            interactive_missing = False,
        )

        disposals_df = disposals_to_df(result.disposals)
        income_df    = income_to_df(result.income)
        summary_df   = summary_to_df({financial_year: result.summary})

        # Missing buys
        missing = []
        for flag in (result.missing_buys or []):
            missing.append({
                "code":           flag.code,
                "qty_unmatched":  flag.qty_unmatched,
                "disposal_date":  str(flag.disposal_date),
                "broker":         flag.broker,
                "reference":      flag.reference,
                "proceeds_per_unit": flag.proceeds_per_unit,
            })

        return {
            "financial_year":  financial_year,
            "disposals":       _stocks_clean(disposals_df),
            "income":          _stocks_clean(income_df),
            "summary":         _stocks_clean(summary_df),
            "missing_buys":    missing,
            "total_disposals": len(result.disposals),
            "load_report":     result.load_report.__dict__ if result.load_report else {},
        }
    except Exception as e:
        raise HTTPException(500, f"Pipeline failed: {e}")
    finally:
        import shutil as _shutil
        _shutil.rmtree(tmp_dir, ignore_errors=True)

@router.post("/stocks/export")
async def stocks_export(
    files:          List[UploadFile] = File(...),
    financial_year: str              = Form("2024-25"),
):
    """Run the full pipeline and return a formatted Excel report."""
    if not _trading_module_ok:
        raise HTTPException(503, "Stock trading module not available")

    tmp_dir    = _tempfile.mkdtemp(prefix="accfino_stocks_")
    output_xlsx = os.path.join(tmp_dir, "report.xlsx")
    try:
        for upload in files:
            raw  = await upload.read()
            dest = os.path.join(tmp_dir, upload.filename or f"file_{_uuid.uuid4()}.xlsx")
            with open(dest, "wb") as f:
                f.write(raw)

        local_db = str(_paths.module_dir("trading", "cost_base") / "local_cost_base_db.json")
        ensure_local_db(local_db)

        result = run_trading_pipeline(
            source        = tmp_dir,
            output_path   = output_xlsx,
            local_db_path = local_db,
            target_fy     = financial_year,
        )

        if not os.path.exists(output_xlsx):
            # Build it manually via exporter
            export_to_excel(result, output_path=output_xlsx, target_fy=financial_year)

        with open(output_xlsx, "rb") as f:
            content = f.read()

        return Response(
            content    = content,
            media_type = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            headers    = {"Content-Disposition": f"attachment; filename=HSLedger_CGT_{financial_year}.xlsx"},
        )
    except Exception as e:
        raise HTTPException(500, f"Export failed: {e}")
    finally:
        import shutil as _shutil
        _shutil.rmtree(tmp_dir, ignore_errors=True)

