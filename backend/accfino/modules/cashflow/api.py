"""
Cash Flow HTTP API: column detection, model leaderboard run, next-month prediction.
"""
import os
import sys
from pathlib import Path
import threading
import time
from fastapi import APIRouter, Depends
from accfino.core.security.context import OrgContext, current_org
from accfino.shared import paths as _paths

router = APIRouter()
_cf_cache: dict = {}
_LOCK = threading.Lock()          # the pipeline writes its plot/CSV outputs to shared files: one run at a time, read and clear them before anyone else can
RUN_TTL_SECONDS = 3600
MAX_RUNS_PER_ORG = 10
MAX_UPLOAD_BYTES = 5 * 1024 * 1024
MAX_ROWS = 50_000
CASHFLOW_ROLES = ("owner", "admin", "accountant", "bookkeeper", "readonly")


def _require(ctx: OrgContext):
    """Company-wide financial data: finance roles only (payroll and employee roles are refused). Platform admins are allowed."""
    if not (ctx.is_admin or ctx.role in CASHFLOW_ROLES):
        raise HTTPException(403, f"Your role '{ctx.role}' does not allow Cash Flow analysis in this organisation")


def _purge(now=None):
    now = now or time.time()
    for k in [k for k, v in _cf_cache.items() if now - v["at"] > RUN_TTL_SECONDS]:
        _cf_cache.pop(k, None)


def _put(ctx: OrgContext, payload: dict) -> str:
    _purge()
    mine = sorted((k for k, v in _cf_cache.items() if v["org_id"] == ctx.org.id), key=lambda k: _cf_cache[k]["at"])
    for k in mine[:max(0, len(mine) - MAX_RUNS_PER_ORG + 1)]:
        _cf_cache.pop(k, None)
    run_id = str(uuid.uuid4())
    _cf_cache[run_id] = dict(payload, org_id=ctx.org.id, user_id=ctx.user_id, at=time.time())
    return run_id


def _get(ctx: OrgContext, run_id: str):
    _purge()
    e = _cf_cache.get(run_id)
    if not e or e["org_id"] != ctx.org.id:                  # another organisation's run looks exactly like an expired one
        raise HTTPException(404, "Run expired - please re-run pipeline")
    return e

import logging
logger = logging.getLogger("accfino")


import base64, io, json, logging, os, sys, uuid
import pandas as pd
from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile, Body
from pydantic import BaseModel
try:
    from accfino.modules.cashflow.pipeline import auto_detect_columns, preprocess, validate_date_span, monthly_features, train_leaderboard, predict_next_month, LEADERBOARD_CSV, NEXT_MONTH_CSV, LEADERBOARD_PLOT, NEXT_MONTH_PLOT
except Exception:
    auto_detect_columns = preprocess = validate_date_span = monthly_features = None
    train_leaderboard = predict_next_month = None
    LEADERBOARD_CSV = NEXT_MONTH_CSV = LEAD = None

@router.post("/cashflow/detect")
async def cf_detect(file: UploadFile=File(...), ctx: OrgContext = Depends(current_org)):
    _require(ctx)
    raw = await file.read()
    if len(raw) > MAX_UPLOAD_BYTES:
        raise HTTPException(413, f"The file is larger than {MAX_UPLOAD_BYTES // (1024 * 1024)} MB")
    try:
        df = pd.read_csv(io.BytesIO(raw), nrows=MAX_ROWS + 1)
    except Exception:
        raise HTTPException(400, "The file could not be read as a CSV")
    if len(df) > MAX_ROWS:
        raise HTTPException(413, f"More than {MAX_ROWS} rows; split the file")
    detected = auto_detect_columns(df)
    cols = [c for c in df.columns if not c.startswith("_")]
    rows = df.to_dict(orient="records")
    return {"detected": detected, "columns": cols, "row_count": len(df),
            "sample": df.head(5).to_dict(orient="records"), "rows": rows}

class CfRunReq(BaseModel):
    rows: list; col_map: dict

@router.post("/cashflow/run")
def cf_run(body: CfRunReq, ctx: OrgContext = Depends(current_org)):
    _require(ctx)
    if not body.rows: raise HTTPException(400, "No data")
    if len(body.rows) > MAX_ROWS: raise HTTPException(413, f"More than {MAX_ROWS} rows; split the file")
    df_raw  = pd.DataFrame(body.rows)
    col_map = {k: (v if v != "(none)" else None) for k, v in body.col_map.items()}
    missing = [r for r in ("date", "debit", "credit") if not col_map.get(r)]
    if missing: raise HTTPException(400, f"Unmapped: {missing}")
    with _LOCK:
        try:
            df_proc, _t, _o = preprocess(df_raw, col_map)
            months_span, d_min, d_max = validate_date_span(df_proc)
            monthly = monthly_features(df_proc)
            lb, trained_models, feature_cols, data = train_leaderboard(monthly)
        except Exception as e:
            raise HTTPException(500, str(e))
        lb_img = base64.b64encode(LEADERBOARD_PLOT.read_bytes()).decode() if LEADERBOARD_PLOT.exists() else ""
        for _p in (LEADERBOARD_PLOT, LEADERBOARD_CSV):
            try: _p.unlink()
            except Exception: pass
    run_id = _put(ctx, dict(trained_models=trained_models, feature_cols=feature_cols, monthly=monthly, data=data))
    return {"run_id": run_id, "months_span": months_span,
            "date_min": str(d_min), "date_max": str(d_max),
            "model_names": lb["model"].tolist(),
            "leaderboard": lb.to_dict(orient="records"),
            "leaderboard_plot_b64": lb_img}

@router.post("/cashflow/predict/{run_id}")
def cf_predict(run_id: str, model_name: str=Body(..., embed=True), ctx: OrgContext = Depends(current_org)):
    _require(ctx)
    cache = _get(ctx, run_id)
    with _LOCK:
        try:
            pred = predict_next_month(model_name, cache["trained_models"],
                                      cache["feature_cols"], cache["monthly"], cache["data"])
        except Exception as e:
            raise HTTPException(500, str(e))
        plot_b64 = base64.b64encode(NEXT_MONTH_PLOT.read_bytes()).decode() if NEXT_MONTH_PLOT.exists() else ""
        csv_data = NEXT_MONTH_CSV.read_text(encoding="utf-8") if NEXT_MONTH_CSV.exists() else ""
        for _p in (NEXT_MONTH_PLOT, NEXT_MONTH_CSV):
            try: _p.unlink()
            except Exception: pass
    return {**pred, "forecast_plot_b64": plot_b64, "forecast_csv": csv_data}

