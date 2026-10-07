"""
Cash Flow HTTP API: column detection, model leaderboard run, next-month prediction.
"""
import os
import sys
from pathlib import Path
from fastapi import APIRouter
from accfino.shared import paths as _paths

router = APIRouter()
_cf_cache: dict = {}

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
async def cf_detect(file: UploadFile=File(...)):
    df = pd.read_csv(io.BytesIO(await file.read()))
    detected = auto_detect_columns(df)
    cols = [c for c in df.columns if not c.startswith("_")]
    rows = df.to_dict(orient="records")
    return {"detected": detected, "columns": cols, "row_count": len(df),
            "sample": df.head(5).to_dict(orient="records"), "rows": rows}

class CfRunReq(BaseModel):
    rows: list; col_map: dict

@router.post("/cashflow/run")
def cf_run(body: CfRunReq):
    if not body.rows: raise HTTPException(400, "No data")
    df_raw  = pd.DataFrame(body.rows)
    col_map = {k: (v if v != "(none)" else None) for k, v in body.col_map.items()}
    missing = [r for r in ("date", "debit", "credit") if not col_map.get(r)]
    if missing: raise HTTPException(400, f"Unmapped: {missing}")
    try:
        df_proc, _t, _o = preprocess(df_raw, col_map)
        months_span, d_min, d_max = validate_date_span(df_proc)
        monthly = monthly_features(df_proc)
        lb, trained_models, feature_cols, data = train_leaderboard(monthly)
    except Exception as e:
        raise HTTPException(500, str(e))
    run_id = str(uuid.uuid4())
    _cf_cache[run_id] = dict(trained_models=trained_models, feature_cols=feature_cols,
                              monthly=monthly, data=data)
    lb_img = base64.b64encode(LEADERBOARD_PLOT.read_bytes()).decode() if LEADERBOARD_PLOT.exists() else ""
    return {"run_id": run_id, "months_span": months_span,
            "date_min": str(d_min), "date_max": str(d_max),
            "model_names": lb["model"].tolist(),
            "leaderboard": lb.to_dict(orient="records"),
            "leaderboard_plot_b64": lb_img}

@router.post("/cashflow/predict/{run_id}")
def cf_predict(run_id: str, model_name: str=Body(..., embed=True)):
    cache = _cf_cache.get(run_id)
    if not cache: raise HTTPException(404, "Run expired - please re-run pipeline")
    try:
        pred = predict_next_month(model_name, cache["trained_models"],
                                  cache["feature_cols"], cache["monthly"], cache["data"])
    except Exception as e:
        raise HTTPException(500, str(e))
    plot_b64 = base64.b64encode(NEXT_MONTH_PLOT.read_bytes()).decode() if NEXT_MONTH_PLOT.exists() else ""
    csv_data = NEXT_MONTH_CSV.read_text(encoding="utf-8") if NEXT_MONTH_CSV.exists() else ""
    return {**pred, "forecast_plot_b64": plot_b64, "forecast_csv": csv_data}

