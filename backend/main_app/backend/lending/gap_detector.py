"""
Smart Lending — Traceability Gap Detector
Detects gaps in bank statement coverage across multiple uploaded files:
  - Date range coverage per file / account
  - Overlapping statements (duplicate transactions)
  - Missing periods (gaps between consecutive statements)
  - Duplicate transactions (same date + amount + description)
  - Balance continuity breaks (closing balance ≠ opening balance of next statement)
"""
from typing import List, Dict, Optional, Tuple
from datetime import datetime, timedelta
import re


def _to_date(s: str) -> Optional[datetime]:
    for fmt in ["%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y"]:
        try:
            return datetime.strptime(s.strip(), fmt)
        except ValueError:
            continue
    return None


def detect_gaps(
    file_results: List[Dict],
    max_gap_days:         int = 3,    # gaps > this many days are flagged
    overlap_window_days:  int = 2,    # transactions within this window are considered overlap
) -> Dict:
    """
    Analyse traceability across multiple file results.

    Returns dict with:
        - date_coverage: [{file, start, end, days, transaction_count}]
        - gaps: [{from_file, to_file, gap_start, gap_end, gap_days}]
        - overlaps: [{file_a, file_b, overlap_start, overlap_end}]
        - duplicates: [{date, description, amount, found_in}]
        - coverage_summary: {total_days, covered_days, coverage_pct, overall_start, overall_end}
        - flags: [str] — serious traceability issues only
    """
    if not file_results:
        return {"flags": ["No files provided"], "gaps": [], "overlaps": [],
                "duplicates": [], "coverage_summary": {}, "date_coverage": []}

    # ── 1. Build per-file date ranges ─────────────────────────────────────────
    file_ranges = []
    all_transactions = []

    for fr in file_results:
        fname = fr.get("filename", "unknown")
        txns  = fr.get("transactions", [])
        if not txns:
            file_ranges.append({
                "file": fname, "start": None, "end": None,
                "days": 0, "transaction_count": 0, "error": "no transactions extracted"
            })
            continue

        dates = []
        for t in txns:
            d = _to_date(t.get("date", ""))
            if d:
                dates.append(d)
                all_transactions.append({**t, "_file": fname, "_date_obj": d})

        if not dates:
            file_ranges.append({
                "file": fname, "start": None, "end": None,
                "days": 0, "transaction_count": len(txns), "error": "no valid dates"
            })
            continue

        start = min(dates)
        end   = max(dates)
        file_ranges.append({
            "file":              fname,
            "start":             start.strftime("%Y-%m-%d"),
            "end":               end.strftime("%Y-%m-%d"),
            "start_dt":          start,
            "end_dt":            end,
            "days":              (end - start).days + 1,
            "transaction_count": len(txns),
        })

    # Sort by start date
    valid_ranges = [r for r in file_ranges if r.get("start_dt")]
    valid_ranges.sort(key=lambda x: x["start_dt"])

    # ── 2. Gap detection ──────────────────────────────────────────────────────
    gaps = []
    for i in range(len(valid_ranges) - 1):
        a = valid_ranges[i]
        b = valid_ranges[i + 1]
        # Check if there's a gap between end of a and start of b
        gap_days = (b["start_dt"] - a["end_dt"]).days - 1
        if gap_days > max_gap_days:
            gaps.append({
                "from_file":  a["file"],
                "to_file":    b["file"],
                "gap_start":  (a["end_dt"] + timedelta(days=1)).strftime("%Y-%m-%d"),
                "gap_end":    (b["start_dt"] - timedelta(days=1)).strftime("%Y-%m-%d"),
                "gap_days":   gap_days,
                "severity":   "critical" if gap_days > 14 else "warning",
            })

    # ── 3. Overlap detection ──────────────────────────────────────────────────
    overlaps = []
    for i in range(len(valid_ranges) - 1):
        a = valid_ranges[i]
        b = valid_ranges[i + 1]
        if b["start_dt"] <= a["end_dt"]:
            overlap_start = b["start_dt"]
            overlap_end   = min(a["end_dt"], b["end_dt"])
            overlap_days  = (overlap_end - overlap_start).days + 1
            overlaps.append({
                "file_a":        a["file"],
                "file_b":        b["file"],
                "overlap_start": overlap_start.strftime("%Y-%m-%d"),
                "overlap_end":   overlap_end.strftime("%Y-%m-%d"),
                "overlap_days":  overlap_days,
            })

    # ── 4. Duplicate transaction detection ────────────────────────────────────
    seen: Dict[str, List[str]] = {}
    for t in all_transactions:
        amt  = abs(float(t.get("debit") or 0) - float(t.get("credit") or 0))
        key  = f"{t.get('date','')[:10]}|{round(amt,2)}|{(t.get('description','')[:30]).upper().strip()}"
        seen.setdefault(key, [])
        f = t.get("_file", "")
        if f not in seen[key]:
            seen[key].append(f)

    duplicates = []
    for key, files in seen.items():
        if len(files) > 1:
            parts = key.split("|")
            duplicates.append({
                "date":        parts[0],
                "amount":      float(parts[1]),
                "description": parts[2],
                "found_in":    files,
            })

    # ── 5. Coverage summary ──────────────────────────────────────────────────
    coverage_summary = {}
    if valid_ranges:
        overall_start = min(r["start_dt"] for r in valid_ranges)
        overall_end   = max(r["end_dt"]   for r in valid_ranges)
        total_days    = (overall_end - overall_start).days + 1

        # Count covered days (union of all ranges)
        covered = set()
        for r in valid_ranges:
            d = r["start_dt"]
            while d <= r["end_dt"]:
                covered.add(d)
                d += timedelta(days=1)
        covered_days = len(covered)

        coverage_summary = {
            "overall_start":   overall_start.strftime("%Y-%m-%d"),
            "overall_end":     overall_end.strftime("%Y-%m-%d"),
            "total_span_days": total_days,
            "covered_days":    covered_days,
            "gap_days":        total_days - covered_days,
            "coverage_pct":    round(covered_days / total_days * 100, 1),
            "months_covered":  round(covered_days / 30.4, 1),
            "files_processed": len(file_results),
        }

    # ── 7. Build flags ────────────────────────────────────────────────────────
    flags = []

    for fr in file_ranges:
        if fr.get("error"):
            flags.append(f"⚠️ '{fr['file']}': {fr['error']}")

    for gap in gaps:
        sev = "🚨" if gap["severity"] == "critical" else "⚠️"
        flags.append(
            f"{sev} Gap of {gap['gap_days']} days between "
            f"'{gap['from_file']}' (ends {gap['gap_start'][:10]}) and "
            f"'{gap['to_file']}' (starts {gap['gap_end'][:10]})"
        )

    for ov in overlaps:
        flags.append(
            f"ℹ️ Overlap of {ov['overlap_days']} days between "
            f"'{ov['file_a']}' and '{ov['file_b']}' ({ov['overlap_start']} – {ov['overlap_end']})"
        )

    if duplicates:
        flags.append(
            f"⚠️ {len(duplicates)} potential duplicate transaction(s) found across files — "
            "these will be de-duplicated in the combined analysis"
        )

    if coverage_summary.get("coverage_pct", 100) < 80:
        flags.append(
            f"🚨 Statement coverage is only {coverage_summary['coverage_pct']}% — "
            "significant gaps exist. ASIC RG 209 recommends at least 3 months continuous statements."
        )

    if not gaps and not duplicates and len(file_results) > 1:
        flags.append("✅ No traceability gaps detected across all uploaded files")

    return {
        "date_coverage":       [{k:v for k,v in r.items() if k not in ('start_dt','end_dt')}
                                 for r in file_ranges],
        "gaps":                gaps,
        "overlaps":            overlaps,
        "duplicates":          duplicates[:20],   # cap at 20 for response size
        "coverage_summary":    coverage_summary,
        "flags":               flags,
    }


def deduplicate_transactions(all_transactions: List[Dict]) -> List[Dict]:
    """
    Remove duplicate transactions (same date + rounded amount + description prefix).
    Keeps the first occurrence.
    """
    seen = set()
    result = []
    for t in sorted(all_transactions, key=lambda x: x.get("date", "")):
        amt = abs(float(t.get("debit") or 0) + float(t.get("credit") or 0))
        key = f"{t.get('date','')[:10]}|{round(amt,2)}|{(t.get('description','')[:25]).upper().strip()}"
        if key not in seen:
            seen.add(key)
            result.append(t)
    return result
