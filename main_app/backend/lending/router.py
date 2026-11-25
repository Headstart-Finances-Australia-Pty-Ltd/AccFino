"""
Smart Lending — FastAPI Router  (v3)
Multi-file upload · per-file extraction · gap detection · deduplication · analysis
"""
import io, json, asyncio, tempfile, os
from typing import List, Optional
from fastapi import APIRouter, File, UploadFile, Form, HTTPException
from pydantic import BaseModel

from .classifier    import classify_transactions
from .metrics       import compute_metrics, metrics_to_dict
from .gap_detector  import detect_gaps, deduplicate_transactions
from .pdf_extractor import (
    extract_from_pdf_bytes_via_ie,
    extract_from_pdf_bytes_generic,
    extract_from_csv_text,
    extract_from_image_via_claude,
)

router = APIRouter(prefix="/lending", tags=["Smart Lending"])


class ManualTransaction(BaseModel):
    date:        str
    description: str
    debit:       float = 0.0
    credit:      float = 0.0

class LendingAnalysisRequest(BaseModel):
    transactions:    List[ManualTransaction]
    proposed_loan:   float = 0
    interest_rate:   float = 0.065
    loan_term_years: int   = 30
    household_type:  str   = "single_no_children"
    analysis_months: int   = 3


def _guess_months(file_results):
    cov = detect_gaps(file_results).get("coverage_summary", {})
    m   = cov.get("months_covered", 0)
    return max(1, round(m)) if m else 3


async def _extract_one(file: UploadFile) -> dict:
    """Extract transactions from one uploaded file. Returns per-file result dict."""
    raw    = await file.read()
    fname  = (file.filename or "unknown")
    flower = fname.lower()
    ctype  = (file.content_type or "").lower()

    transactions = []
    method = "unknown"
    meta   = {}
    error  = None

    try:
        if flower.endswith(".csv") or "csv" in ctype:
            text = raw.decode("utf-8-sig", errors="ignore")
            transactions = extract_from_csv_text(text)
            method = "csv"

        elif flower.endswith(".pdf") or "pdf" in ctype:
            # 1. Try the invoice_extractor bank parser (ANZ/CBA/Westpac etc.)
            transactions, meta = extract_from_pdf_bytes_via_ie(raw)
            method = "pdf_bank_parser"

            # 2. Fallback: pdfplumber generic
            if len(transactions) < 3:
                transactions = extract_from_pdf_bytes_generic(raw)
                method = "pdf_generic"

            # 3. Fallback: Claude Vision (for scanned PDFs)
            if len(transactions) < 3:
                transactions = await extract_from_image_via_claude(raw, "image/jpeg")
                method = "pdf_vision"

        elif ctype.startswith("image/") or flower.endswith((".jpg",".jpeg",".png",".webp")):
            img_ct = ctype if ctype.startswith("image/") else "image/jpeg"
            transactions = await extract_from_image_via_claude(raw, img_ct)
            method = "vision"

        else:
            # Last resort: try CSV
            try:
                text = raw.decode("utf-8-sig", errors="ignore")
                transactions = extract_from_csv_text(text)
                method = "csv_fallback"
            except Exception:
                error = "Unsupported file type"

    except Exception as exc:
        error = str(exc)[:300]

    return {
        "filename":          fname,
        "content_type":      ctype,
        "extraction_method": method,
        "transaction_count": len(transactions),
        "transactions":      transactions,
        "meta":              meta,
        "error":             error,
        "ok":                len(transactions) > 0,
    }


def _check_three_months(file_results: list) -> dict:
    """
    Validate that all uploaded files cover the SAME 3-month period.
    Returns {valid, reference_start, reference_end, files_outside, message}
    """
    from datetime import datetime, timedelta
    from .gap_detector import _to_date

    file_ranges = []
    for fr in file_results:
        if not fr.get("ok"):
            continue
        dates = [_to_date(t.get("date","")) for t in fr.get("transactions",[]) if t.get("date")]
        dates = [d for d in dates if d]
        if not dates:
            continue
        file_ranges.append({
            "filename": fr["filename"],
            "start":    min(dates),
            "end":      max(dates),
        })

    if not file_ranges:
        return {"valid": False, "message": "No valid date ranges found in any file."}

    # Find the 3-month reference window from the file with most transactions
    # Use overall start → start + 92 days as the reference period
    all_starts = [r["start"] for r in file_ranges]
    all_ends   = [r["end"]   for r in file_ranges]
    ref_start  = min(all_starts)
    ref_end    = max(all_ends)
    total_days = (ref_end - ref_start).days

    # Check each file is within ±7 days of the reference window
    TOLERANCE = timedelta(days=7)
    ref_window_start = ref_start - TOLERANCE
    ref_window_end   = ref_end   + TOLERANCE

    files_outside = []
    for r in file_ranges:
        if r["start"] < ref_window_start or r["end"] > ref_window_end:
            files_outside.append({
                "filename": r["filename"],
                "start":    r["start"].strftime("%Y-%m-%d"),
                "end":      r["end"].strftime("%Y-%m-%d"),
                "reason":   "Outside the primary 3-month reference period",
            })

    months_covered = total_days / 30.4
    valid = len(files_outside) == 0 and months_covered >= 2.5

    if months_covered < 2.5:
        message = (f"Only {months_covered:.1f} months of data detected. "
                   "ASIC RG 209 requires a minimum of 3 months continuous statements. "
                   "Please upload additional bank statements.")
    elif files_outside:
        message = (f"{len(files_outside)} file(s) fall outside the primary statement period "
                   f"({ref_start.strftime('%d/%m/%Y')} – {ref_end.strftime('%d/%m/%Y')}). "
                   "Transactions from these files may not be comparable and should be reviewed.")
    else:
        message = (f"All files cover a consistent period "
                   f"({ref_start.strftime('%d/%m/%Y')} – {ref_end.strftime('%d/%m/%Y')}, "
                   f"{months_covered:.1f} months). Period validation passed.")

    return {
        "valid":            valid,
        "reference_start":  ref_start.strftime("%Y-%m-%d"),
        "reference_end":    ref_end.strftime("%Y-%m-%d"),
        "months_covered":   round(months_covered, 1),
        "files_outside":    files_outside,
        "message":          message,
    }


def _date_range(txns):
    from .gap_detector import _to_date
    dates = [_to_date(t.get("date","")) for t in txns]
    dates = [d for d in dates if d]
    if not dates:
        return {"start": None, "end": None}
    return {"start": min(dates).strftime("%Y-%m-%d"), "end": max(dates).strftime("%Y-%m-%d")}


# ── Endpoints ─────────────────────────────────────────────────────────────────

@router.post("/upload-multi")
async def upload_multiple_statements(
    files:           List[UploadFile] = File(...),
    proposed_loan:   float            = Form(0),
    interest_rate:   float            = Form(0.065),
    loan_term_years: int              = Form(30),
    household_type:  str              = Form("single_no_children"),
    analysis_months: int              = Form(0),
):
    """
    Upload 1–20 bank statements (any mix of PDF / JPEG / PNG / CSV).
    Returns:
      - per-file extraction status & date coverage
      - traceability gap report (gaps / overlaps / duplicates)
      - merged + deduplicated classified transactions
      - full lending metrics (NDI, UMI, DSR, HEM, LTI, risk score)
    """
    if not files:
        raise HTTPException(400, "No files provided")
    if len(files) > 20:
        raise HTTPException(400, "Maximum 20 files per submission")

    # Extract all files in parallel
    file_results = list(await asyncio.gather(*[_extract_one(f) for f in files]))

    # Traceability gap analysis
    gap_report = detect_gaps(file_results)

    # Merge + deduplicate — carry source file + bank per transaction
    all_txns = []
    for fr in file_results:
        bank = fr.get("meta", {}).get("bank", "unknown")
        for t in fr.get("transactions", []):
            all_txns.append({
                **t,
                "_source_file": fr["filename"],
                "_bank":        bank,
            })

    merged = deduplicate_transactions(all_txns)

    if not merged:
        failed = [f["filename"] for f in file_results if not f["ok"]]
        raise HTTPException(
            422,
            f"No transactions could be extracted. "
            f"Failed: {', '.join(failed) if failed else 'all files'}. "
            "Ensure files are valid AU bank statements (PDF with text, image, or CSV export)."
        )

    months = analysis_months if analysis_months > 0 else _guess_months(file_results)

    classified = classify_transactions(merged)

    # ── 3-month period validation ─────────────────────────────────────────────
    period_check = _check_three_months(file_results)

    metrics = compute_metrics(
        classified,
        proposed_loan_amount   = proposed_loan,
        proposed_interest_rate = interest_rate,
        proposed_term_years    = loan_term_years,
        household_type         = household_type,
        analysis_months        = months,
    )

    file_summaries = [{
        "filename":          fr["filename"],
        "content_type":      fr["content_type"],
        "extraction_method": fr["extraction_method"],
        "transaction_count": fr["transaction_count"],
        "ok":                fr["ok"],
        "error":             fr.get("error"),
        "date_range":        _date_range(fr["transactions"]),
        "bank":              fr.get("meta", {}).get("bank", ""),
        "account_type":      fr.get("meta", {}).get("account_type", ""),
        "account_number":    fr.get("meta", {}).get("account_number", ""),
        "account_holder":    fr.get("meta", {}).get("account_holder", ""),
    } for fr in file_results]

    metrics_dict = metrics_to_dict(metrics)
    max_borrow   = metrics_dict.get("loan_assessment", {}).get("max_borrowing_capacity", 0)

    return {
        "file_summaries":    file_summaries,
        "gap_report":        gap_report,
        "transactions":      classified,
        "transaction_count": len(classified),
        "duplicate_count":   len(all_txns) - len(merged),
        "months_analysed":   months,
        "metrics":           metrics_dict,
        "max_borrowing_capacity": max_borrow,
        "period_check":      period_check,
    }


@router.post("/upload")
async def upload_single_statement(
    file:            UploadFile = File(...),
    proposed_loan:   float      = Form(0),
    interest_rate:   float      = Form(0.065),
    loan_term_years: int        = Form(30),
    household_type:  str        = Form("single_no_children"),
    analysis_months: int        = Form(3),
):
    """Single-file upload (backward compatible)."""
    result = await _extract_one(file)
    if not result["ok"]:
        raise HTTPException(422, result.get("error") or "No transactions extracted")
    classified = classify_transactions(result["transactions"])
    metrics    = compute_metrics(classified,
        proposed_loan_amount=proposed_loan, proposed_interest_rate=interest_rate,
        proposed_term_years=loan_term_years, household_type=household_type,
        analysis_months=analysis_months)
    fr = result
    return {
        "file_summaries":    [{"filename": file.filename, "extraction_method": fr["extraction_method"],
                                "transaction_count": fr["transaction_count"], "ok": True,
                                "date_range": _date_range(fr["transactions"]),
                                "bank": fr.get("meta",{}).get("bank",""),
                                "account_type": fr.get("meta",{}).get("account_type",""),
                                "account_holder": fr.get("meta",{}).get("account_holder","")}],
        "gap_report":        detect_gaps([result]),
        "transactions":      classified,
        "transaction_count": len(classified),
        "duplicate_count":   0,
        "months_analysed":   analysis_months,
        "metrics":           metrics_to_dict(metrics),
    }


@router.post("/analyse")
def analyse_transactions(body: LendingAnalysisRequest):
    txns       = [t.dict() for t in body.transactions]
    classified = classify_transactions(txns)
    metrics    = compute_metrics(classified, proposed_loan_amount=body.proposed_loan,
        proposed_interest_rate=body.interest_rate, proposed_term_years=body.loan_term_years,
        household_type=body.household_type, analysis_months=body.analysis_months)
    return {"transactions": classified, "metrics": metrics_to_dict(metrics),
            "gap_report": {}, "file_summaries": []}


@router.post("/classify")
def classify_only(transactions: List[ManualTransaction]):
    return classify_transactions([t.dict() for t in transactions])


@router.get("/categories")
def get_categories():
    from .classifier import HEM_GROUP_MAP
    from .metrics    import HEM_BENCHMARKS
    return {"categories": list(set(HEM_GROUP_MAP.keys())),
            "hem_groups":  list(set(HEM_GROUP_MAP.values())),
            "hem_benchmarks": HEM_BENCHMARKS}


@router.get("/regulatory")
def get_regulatory_thresholds():
    from .metrics import (DTI_LIMIT, HOUSEHOLD_EXPENSE_LIMIT, SERVICEABILITY_BUFFER,
                           MIN_UMI_MONTHLY, MAX_LTI, GAMBLING_THRESHOLD)
    return {
        "dti_limit_pct": DTI_LIMIT*100, "household_expense_limit_pct": HOUSEHOLD_EXPENSE_LIMIT*100,
        "serviceability_buffer_pct": SERVICEABILITY_BUFFER*100, "min_umi_monthly": MIN_UMI_MONTHLY,
        "max_lti": MAX_LTI, "gambling_threshold_pct": GAMBLING_THRESHOLD*100,
        "references": {"NCCP": "National Consumer Credit Protection Act 2009",
                       "RG209": "ASIC Regulatory Guide 209",
                       "APS220": "APRA APS 220", "APG223": "APRA APG 223",
                       "HEM": "Household Expenditure Measure — Melbourne Institute"},
    }
