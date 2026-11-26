"""
Smart Lending — PDF / Image / CSV Bank Statement Extractor  (v2)

Uses the existing AccFino invoice_extractor (which has purpose-built parsers for
ANZ, Westpac, CBA, NAB, Macquarie, HSBC, Suncorp etc.) as the primary extraction
engine for bank-statement PDFs, with Claude Vision as fallback for scanned/image files.

Priority order:
  PDF  → invoice_extractor.extract_from_pdf_bank  (best — bank-specific parsers)
         → pdfplumber generic table parse           (fallback)
         → Claude Vision                            (scanned PDF fallback)
  IMG  → Claude Vision
  CSV  → csv.DictReader                            (direct)
"""
import re
import time
import io
import os
import csv
import json
import base64
import tempfile
import pathlib
from typing import List, Dict, Optional
from datetime import datetime

try:
    import pdfplumber
    _PDFPLUMBER = True
except ImportError:
    _PDFPLUMBER = False

try:
    from backend.invoice_extractor.core import extract_from_pdf_bank as _ie_extract
    _IE_AVAILABLE = True
except Exception:
    try:
        from main_app.backend.invoice_extractor.core import extract_from_pdf_bank as _ie_extract
        _IE_AVAILABLE = True
    except Exception:
        _IE_AVAILABLE = False


# ── Date parsing ───────────────────────────────────────────────────────────────
DATE_FORMATS = [
    "%d/%m/%Y", "%d/%m/%y", "%d-%m-%Y", "%d-%m-%y", "%Y-%m-%d",
    "%d %b %Y", "%d %b %y", "%d %B %Y", "%d %B %y",
    "%m/%d/%Y", "%m/%d/%y",
]

def _parse_date(s: str) -> Optional[str]:
    s = s.strip()
    for fmt in DATE_FORMATS:
        try:
            return datetime.strptime(s, fmt).strftime("%Y-%m-%d")
        except ValueError:
            continue
    return None

def _parse_amount(s) -> float:
    try:
        return float(re.sub(r"[,$\s]", "", str(s).strip()))
    except (ValueError, AttributeError):
        return 0.0

DATE_RE   = re.compile(r"\b(\d{1,2}[/\-]\d{1,2}[/\-]\d{2,4}|\d{1,2}\s+(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\s+\d{2,4})\b", re.I)
AMOUNT_RE = re.compile(r"[-+]?\$?\s?[\d,]+\.\d{2}")


# ── Primary: invoice_extractor bank parser ─────────────────────────────────────
def extract_from_pdf_bytes_via_ie(pdf_bytes: bytes) -> tuple[List[Dict], Dict]:
    """
    Use the AccFino invoice_extractor (ANZ/Westpac/CBA/NAB parsers) to extract
    transactions from a bank statement PDF.
    Returns (transactions, meta)
    """
    if not _IE_AVAILABLE:
        return [], {}

    with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tmp:
        tmp.write(pdf_bytes)
        tmp_path = tmp.name

    try:
        results = _ie_extract(tmp_path)     # returns [{meta, transactions}]
        if not results:
            return [], {}
        # Merge all result blocks (multi-account PDFs)
        all_txns = []
        meta     = {}
        for blk in results:
            meta  = blk.get("meta", meta)
            for t in blk.get("transactions", []):
                all_txns.append({
                    "date":        t.get("date", ""),
                    "description": t.get("description", ""),
                    "debit":       float(t.get("debit")  or 0),
                    "credit":      float(t.get("credit") or 0),
                })
        return all_txns, meta
    except Exception:
        return [], {}
    finally:
        try:
            os.unlink(tmp_path)
        except Exception:
            pass


# ── Fallback: pdfplumber generic ───────────────────────────────────────────────
def extract_from_pdf_bytes_generic(pdf_bytes: bytes) -> List[Dict]:
    if not _PDFPLUMBER:
        return []
    txns = []
    try:
        with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
            for page in pdf.pages:
                tables = page.extract_tables()
                for table in tables:
                    for row in (table or []):
                        t = _parse_table_row(row)
                        if t:
                            txns.append(t)
                if not txns:
                    for line in (page.extract_text() or "").split("\n"):
                        t = _parse_text_line(line)
                        if t:
                            txns.append(t)
    except Exception:
        pass
    return txns


def _parse_table_row(row) -> Optional[Dict]:
    cells = [str(c or "").strip() for c in row]
    text  = " ".join(cells)
    dm    = DATE_RE.search(text)
    if not dm:
        return None
    date = _parse_date(dm.group())
    if not date:
        return None
    amounts = AMOUNT_RE.findall(text)
    if not amounts:
        return None
    desc = re.sub(r"\s+", " ", DATE_RE.sub("", AMOUNT_RE.sub("", text))).strip()
    if len(desc) < 3:
        return None
    vals = [_parse_amount(a) for a in amounts]
    is_cr = any(x in text.upper() for x in ["CR", "CREDIT", "+"])
    return {"date": date, "description": desc,
            "debit":  0.0 if is_cr else (vals[0] if vals else 0.0),
            "credit": vals[0] if is_cr and vals else 0.0}


def _parse_text_line(line: str) -> Optional[Dict]:
    line = line.strip()
    if len(line) < 10:
        return None
    dm = DATE_RE.search(line)
    if not dm:
        return None
    date = _parse_date(dm.group())
    if not date:
        return None
    amounts = AMOUNT_RE.findall(line)
    if not amounts:
        return None
    desc = re.sub(r"\s{2,}", " ",
                  DATE_RE.sub("", AMOUNT_RE.sub("", line))).strip()
    if len(desc) < 3:
        return None
    vals  = [_parse_amount(a) for a in amounts]
    is_cr = "CR" in line.upper()
    return {"date": date, "description": desc,
            "debit":  0.0 if is_cr else (vals[0] if vals else 0.0),
            "credit": vals[0] if is_cr and vals else 0.0}


def _json_array_from(text: str):
    """Pull the JSON array out of Claude's reply, even with extra words around it
    or when the reply was cut off part-way (keeps every complete row)."""
    text = re.sub(r"```(?:json)?", "", text or "")
    start = text.find("[")
    if start < 0:
        raise ValueError(f"no JSON list in reply: {text[:200]!r}")
    end = text.rfind("]")
    if end > start:
        try:
            return json.loads(text[start:end + 1])
        except ValueError:
            pass
    body = text[start:]
    cut = body.rfind("}")
    while cut > 0:
        try:
            return json.loads(body[:cut + 1] + "]")
        except ValueError:
            cut = body.rfind("}", 0, cut)
    raise ValueError(f"reply was not a JSON list: {text[:200]!r}")


# ── Claude Vision extraction ───────────────────────────────────────────────────
async def extract_from_image_via_claude(
    image_bytes: bytes,
    media_type:  str = "image/jpeg",
    api_key:     str = "",
) -> List[Dict]:
    """Extract transactions from an image or a PDF the built-in readers could not handle.
    Uses Groq when GROQ_API_KEY is set, otherwise Claude (ANTHROPIC_API_KEY)."""
    groq_key = (os.environ.get("GROQ_API_KEY") or "").strip()
    if groq_key and not api_key:
        return _extract_via_groq(image_bytes, media_type, groq_key)
    try:
        import anthropic
        key = (api_key or os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("CLAUDE_API_KEY")
               or os.environ.get("ANTHROPIC_KEY") or "").strip()
        if not key:
            print("[accfino] AI statement extraction skipped: neither GROQ_API_KEY nor ANTHROPIC_API_KEY is set", flush=True)
            return []
        client = anthropic.Anthropic(api_key=key)
        b64 = base64.b64encode(image_bytes).decode()
        # PDFs must be sent as a "document" block; sending them as an image fails
        is_pdf = media_type == "application/pdf" or image_bytes[:5] == b"%PDF-"
        if is_pdf:
            file_block = {"type": "document",
                          "source": {"type": "base64", "media_type": "application/pdf", "data": b64}}
        else:
            file_block = {"type": "image",
                          "source": {"type": "base64", "media_type": media_type, "data": b64}}
        _started = time.time()
        resp = client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=16000,
            messages=[{"role": "user", "content": [
                file_block,
                {"type": "text", "text": (
                    "Extract ALL bank transactions from this bank statement. "
                    "Return ONLY a JSON array — no other text, no markdown. "
                    "Each object: {\"date\":\"YYYY-MM-DD\",\"description\":\"string\","
                    "\"debit\":number_or_0,\"credit\":number_or_0}. "
                    "Debits are money going OUT, credits are money coming IN. "
                    "Include every row — salary, rent, groceries, ATM withdrawals, etc."
                )},
            ]}],
        )
        # Token usage for Prama Monitor (runs in the background, never raises)
        try:
            from main_app.prama_monitor import report_anthropic
            report_anthropic(resp, started_at=_started, operation="bank-statement-vision")
        except Exception:
            pass
        text = "".join(getattr(b, "text", "") for b in resp.content
                       if getattr(b, "type", "text") == "text")
        print(f"[accfino] Claude statement extraction: stop={getattr(resp, 'stop_reason', '?')} "
              f"chars={len(text)}", flush=True)
        data = _json_array_from(text)
        if isinstance(data, list):
            return [{"date": t.get("date",""), "description": t.get("description",""),
                     "debit": float(t.get("debit") or 0),
                     "credit": float(t.get("credit") or 0)}
                    for t in data if t.get("description")]
    except Exception as e:
        print(f"[accfino] Claude statement extraction failed: {type(e).__name__}: {e}", flush=True)
    return []


# ── Groq extraction ────────────────────────────────────────────────────────────
GROQ_URL = "https://api.groq.com/openai/v1/chat/completions"
_PROMPT = (
    "Extract ALL bank transactions from this bank statement. "
    "Return ONLY a JSON array — no other text, no markdown. "
    "Each object: {\"date\":\"YYYY-MM-DD\",\"description\":\"string\","
    "\"debit\":number_or_0,\"credit\":number_or_0}. "
    "Debits are money going OUT, credits are money coming IN. "
    "Include every row — salary, rent, groceries, ATM withdrawals, etc. "
    "Skip opening/closing balance lines and page headers."
)


def _pdf_text(pdf_bytes: bytes) -> str:
    if not _PDFPLUMBER:
        return ""
    try:
        with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
            return "\n\n".join((pg.extract_text(layout=True) or "") for pg in pdf.pages)
    except Exception:
        return ""


def _pdf_page_images(pdf_bytes: bytes, limit: int = 3) -> List[bytes]:
    try:
        from pdf2image import convert_from_bytes
        pages = convert_from_bytes(pdf_bytes, dpi=150, first_page=1, last_page=limit)
        out = []
        for pg in pages:
            buf = io.BytesIO()
            pg.convert("RGB").save(buf, format="JPEG", quality=85)
            out.append(buf.getvalue())
        return out
    except Exception as e:
        print(f"[accfino] could not turn PDF pages into images: {e}", flush=True)
        return []


def _groq_call(key: str, model: str, content, operation: str) -> List[Dict]:
    import requests
    started = time.time()
    r = requests.post(GROQ_URL, timeout=120,
                      headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
                      json={"model": model, "temperature": 0, "max_completion_tokens": 16000,
                            "messages": [{"role": "user", "content": content}]})
    if r.status_code != 200:
        raise RuntimeError(f"Groq HTTP {r.status_code}: {r.text[:300]}")
    data = r.json()
    try:
        from main_app.prama_monitor import report_openai_style
        report_openai_style("groq", data, started_at=started, operation=operation)
    except Exception:
        pass
    choice = (data.get("choices") or [{}])[0]
    text = (choice.get("message") or {}).get("content") or ""
    print(f"[accfino] Groq statement extraction: model={model} "
          f"finish={choice.get('finish_reason', '?')} chars={len(text)}", flush=True)
    return _json_array_from(text)


def _extract_via_groq(file_bytes: bytes, media_type: str, key: str) -> List[Dict]:
    text_model = os.environ.get("GROQ_TEXT_MODEL", "openai/gpt-oss-120b")
    vision_model = os.environ.get("GROQ_VISION_MODEL", "qwen/qwen3.8-27b")
    try:
        is_pdf = media_type == "application/pdf" or file_bytes[:5] == b"%PDF-"
        if is_pdf:
            text = _pdf_text(file_bytes)
            if len(text.strip()) > 200:
                # PDF with real text: send the text (cheaper and more accurate than pictures)
                data = _groq_call(key, text_model,
                                  _PROMPT + "\n\nSTATEMENT TEXT:\n" + text[:300000],
                                  "bank-statement-text")
            else:
                # Scanned PDF: send the first pages as pictures (Groq allows 3 per request)
                imgs = _pdf_page_images(file_bytes, 3)
                if not imgs:
                    return []
                parts = [{"type": "text", "text": _PROMPT}] + [
                    {"type": "image_url", "image_url": {
                        "url": "data:image/jpeg;base64," + base64.b64encode(b).decode()}}
                    for b in imgs]
                data = _groq_call(key, vision_model, parts, "bank-statement-vision")
        else:
            parts = [{"type": "text", "text": _PROMPT},
                     {"type": "image_url", "image_url": {
                         "url": f"data:{media_type or 'image/jpeg'};base64,"
                                + base64.b64encode(file_bytes).decode()}}]
            data = _groq_call(key, vision_model, parts, "bank-statement-vision")
        if isinstance(data, list):
            return [{"date": t.get("date", ""), "description": t.get("description", ""),
                     "debit": float(t.get("debit") or 0),
                     "credit": float(t.get("credit") or 0)}
                    for t in data if isinstance(t, dict) and t.get("description")]
    except Exception as e:
        print(f"[accfino] Groq statement extraction failed: {type(e).__name__}: {e}", flush=True)
    return []


# ── CSV parser ─────────────────────────────────────────────────────────────────
def extract_from_csv_text(csv_text: str) -> List[Dict]:
    txns = []
    # Try multiple encodings / BOM
    text = csv_text.lstrip("\ufeff")

    # Auto-detect delimiter
    delim = ","
    for d in [",", ";", "\t", "|"]:
        if text.count(d) > text.count(","):
            delim = d
            break

    reader = csv.DictReader(io.StringIO(text), delimiter=delim)
    if not reader.fieldnames:
        return []

    # Flexible column matching
    def _col(names):
        return next((k for k in (reader.fieldnames or [])
                     if k.strip().lower() in names), None)

    date_k   = _col({"date","transaction date","txn date","value date","posted date","settled date"})
    desc_k   = _col({"description","narrative","memo","details","particulars","reference","transaction","narration","merchant name"})
    debit_k  = _col({"debit","withdrawal","withdrawals","dr","amount","debit amount","debit (aud)"})
    credit_k = _col({"credit","deposit","deposits","cr","credit amount","credit (aud)"})
    amount_k = _col({"amount","net amount","transaction amount"}) if not debit_k else None

    if not (date_k and desc_k):
        return []

    for row in reader:
        date = _parse_date(str(row.get(date_k, "") or ""))
        if not date:
            continue
        desc = str(row.get(desc_k, "") or "").strip()
        if not desc:
            continue

        debit  = _parse_amount(row.get(debit_k,  0) or 0) if debit_k  else 0.0
        credit = _parse_amount(row.get(credit_k, 0) or 0) if credit_k else 0.0

        # If single amount column, positive = credit, negative = debit
        if amount_k and not debit and not credit:
            amt = _parse_amount(row.get(amount_k, 0) or 0)
            if amt < 0:
                debit  = abs(amt)
            else:
                credit = amt

        # Some banks put both in one "Amount" col with DR/CR suffix
        if debit_k and not credit_k:
            val = str(row.get(debit_k, "") or "")
            if "CR" in val.upper():
                credit = _parse_amount(val)
                debit  = 0.0

        txns.append({"date": date, "description": desc,
                     "debit": debit, "credit": credit})
    return txns
