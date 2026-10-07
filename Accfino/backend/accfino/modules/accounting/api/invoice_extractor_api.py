"""
Invoice / receipt extraction endpoints (document capability lives in accfino.shared.documents).
"""
import os
import sys
from pathlib import Path
from fastapi import APIRouter
from accfino.shared import paths as _paths

router = APIRouter()

import logging
logger = logging.getLogger("accfino")


import base64, io, json, logging, os, sys, uuid
from pathlib import Path
from typing import Any, Dict, List, Optional
from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile, Body
try:
    from accfino.shared.documents.invoice_extractor import process_files as ie_process_files, get_dependency_status
    IE_AVAILABLE = True
except Exception:
    IE_AVAILABLE = False
import os as _os

@router.get("/invoice-extractor/status")
def ie_status():
    if not IE_AVAILABLE: return {"available": False, "reason": "Module not installed"}
    try: return {"available": True, **get_dependency_status()}
    except Exception as e: return {"available": False, "reason": str(e)}

@router.post("/invoice-extractor/process")
async def ie_process(
    files: List[UploadFile]=File(...),
    tesseract_cmd: str=Form(""), poppler_bin: str=Form(""),
):
    if not IE_AVAILABLE: raise HTTPException(503, "Invoice extractor not available")
    import tempfile, os as _os
    tmp_files = []
    try:
        for upload in files:
            raw = await upload.read()
            suffix = Path(upload.filename or "file").suffix or ".pdf"
            with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
                tmp.write(raw); tmp_files.append(tmp.name)
        kwargs = {}
        if tesseract_cmd: kwargs["tesseract_cmd"] = tesseract_cmd
        if poppler_bin:   kwargs["poppler_bin"]   = poppler_bin
        bank_results, invoice_results, excel_bytes = ie_process_files(
            [Path(p) for p in tmp_files], **kwargs)
        all_txns = []
        for result, src in bank_results:
            meta = result["meta"]
            for txn in result["transactions"]:
                all_txns.append({**txn, "bank": meta.get("bank", ""),
                    "account_type": meta.get("account_type", ""), "source_file": src})
        all_inv = [{"source_file": src, **res} for res, src in invoice_results]
        excel_b64 = base64.b64encode(excel_bytes).decode() if excel_bytes else ""
        return {"bank_transactions": all_txns, "invoices": all_inv, "excel_b64": excel_b64}
    finally:
        for p in tmp_files:
            try: _os.unlink(p)
            except: pass

