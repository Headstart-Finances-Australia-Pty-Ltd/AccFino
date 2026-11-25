"""
backend/classifier/engine.py
-------------------------------------------------------------------------------
Single-call transaction classifier.

    from backend.classifier.engine import classify, warm, ClassifyResult

    result = classify("Telstra mobile bill", debit=110.0, credit=0.0)
    result.gl_account    # "Telephone & Internet"
    result.gst_category  # "GST on Expenses"
    result.gst_amount    # 10.00
    result.matched       # True
    result.source        # "tfidf" | "rdr" | "transfer" | "fallback"

Pipeline (first match wins)
---------------------------
  1. RDR rules      - rdr_rules.json keyword/regex overrides
  2. Transfer gate  - structural bank patterns (TFR, TRANSFER FROM -)
                      - Equity account / BAS Excluded / $0 GST
  3. TF-IDF match   - cosine similarity against COA *Name + *Description
  4. Fallback       - first COA row matching debit/credit direction

Zero hardcoding
---------------
- GL names and tax codes come exclusively from ChartOfAccounts.csv
- GST taxability: any tax code containing "gst on" is taxable (1/11th)
- Transfer gate resolves its GL from COA at runtime (looks for
  "owner", "equity", "clearing" etc. in *Name)
- New COA rows are picked up automatically on next rebuild()
"""

from __future__ import annotations

import csv
import json
import math
import re
import threading
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import numpy as np
from scipy.sparse import csr_matrix
from scipy.sparse.linalg import norm as sp_norm

# -- Paths ------------------------------------------------------------------
_HERE            = Path(__file__).resolve()
_MAIN_APP        = _HERE.parents[2]          # main_app/
DEFAULT_COA_PATH = _MAIN_APP / "data" / "ChartOfAccounts.csv"
_RDR_PATHS: List[Path] = [
    _MAIN_APP / "data" / "rdr_rules.json",
    _MAIN_APP.parent / "rdr_rules.json",
]

# -- Constants ---------------------------------------------------------------
MIN_SIMILARITY  = 0.08
_GST_RATE       = 0.10
# Account types that are VALID for credit (Incoming) transactions.
# Revenue is the primary type; Equity is valid (owner injecting capital, dividends).
# BAS Excluded accounts (Wages, Super) are valid for credits (salary refunds etc.)
# - they are handled by neutral types below, not blocked.
_INCOME_TYPES   = frozenset({"revenue", "income", "other income", "sales"})
# Account types that are VALID for debit (Outgoing) transactions.
_EXPENSE_TYPES  = frozenset({"expense", "direct costs", "overhead", "other expense"})
# Types that carry no directional restriction (valid for either side).
# Fixed Asset, Inventory, Equity, GST - not forced to income or expense.
_NEUTRAL_TYPES  = frozenset({"fixed asset", "inventory", "equity", "gst"})
_STOP: frozenset = frozenset({
    "a","an","the","and","or","of","in","to","for","with","at","by","from",
    "on","is","it","as","be","this","that","are","was","were","has","have",
    "had","any","your","their","its","our","which","while",
    "incurred","expenses","expenditure","eg","ie",
})

# Transfer description patterns (structural bank narrative - not merchant names)
_TRANSFER_PATTERNS: Tuple[str, ...] = (
    "transfer from", "transfer to",
    "tfr from", "tfr to",
    "trf from", "trf to",
    " tfr ",
    "interbank", "own transfer",
)

# COA *Name fragments that identify balance-sheet / clearing accounts
_TRANSFER_GL_FRAGMENTS: Tuple[str, ...] = (
    "owner", "equity", "loan - director",
    "inter-entity", "intercompany", "clearing", "suspense",
    "internal transfer",   # matches new COA row "Internal Transfer"
)


# ---------------------------------------------------------------------------
# RESULT
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class ClassifyResult:
    """
    Immutable result for one transaction.  All fields resolved in one pass.

    gl_account   - COA *Name  (e.g. "Telephone & Internet")
    gst_category - COA *Tax Code  (e.g. "GST on Expenses")
    gst_amount   - 1/11th of the taxable amount, or 0.00
    matched      - False = directional fallback, may need review
    score        - confidence 0-1 (1.0 for RDR/transfer, 0.0 for fallback)
    source       - "rdr" | "transfer" | "tfidf" | "fallback"
    """
    gl_account:   str
    gl_type:      str
    gst_category: str
    gst_amount:   float
    matched:      bool
    score:        float
    source:       str

    def as_dict(self) -> dict:
        return {
            "gl_account":   self.gl_account,
            "gl_type":      self.gl_type,
            "gst_category": self.gst_category,
            "gst_amount":   self.gst_amount,
            "matched":      self.matched,
            "score":        round(self.score, 4),
            "source":       self.source,
        }


# ---------------------------------------------------------------------------
# GST HELPERS
# ---------------------------------------------------------------------------

def _is_taxable(tax_code: str) -> bool:
    """Any tax code containing 'gst on' is taxable - no hardcoded list."""
    return "gst on" in (tax_code or "").lower()


def _calc_gst(debit: float, credit: float, tax_code: str) -> float:
    """1/11th rule. $0.00 for non-taxable categories."""
    if not _is_taxable(tax_code):
        return 0.0
    amount = credit if credit > 0 else debit
    return round(amount * _GST_RATE / (1 + _GST_RATE), 2) if amount > 0 else 0.0


# ---------------------------------------------------------------------------
# TEXT UTILITIES
# ---------------------------------------------------------------------------

def _tokenise(text: str) -> List[str]:
    text   = re.sub(r"([a-z])([A-Z])", r"\1 \2", text)
    text   = text.replace("&", " ").replace("/", " ")
    tokens = re.split(r"[^a-z0-9]+", text.lower())
    return [t for t in tokens if t and t not in _STOP and len(t) > 1]


def _freq(tokens: List[str]) -> Dict[str, int]:
    d: Dict[str, int] = defaultdict(int)
    for t in tokens:
        d[t] += 1
    return dict(d)


def _acronyms(tokens: List[str]) -> List[str]:
    """Auto-generate acronyms so 'MV' matches 'Motor Vehicle -'"""
    if len(tokens) < 2:
        return []
    letters = [t[0] for t in tokens]
    full    = "".join(letters)
    pairs   = ["".join(letters[i:i+2]) for i in range(len(letters) - 1)]
    return list({full} | set(pairs))


# ---------------------------------------------------------------------------
# COA ROW
# ---------------------------------------------------------------------------

class _Row:
    __slots__ = ("name", "tax_code", "atype", "tokens")

    def __init__(self, name: str, tax_code: str, atype: str, description: str):
        self.name     = name
        self.tax_code = tax_code
        self.atype    = atype
        nt            = _tokenise(name)
        self.tokens   = nt * 3 + _tokenise(atype) + _tokenise(description) + _acronyms(nt)


# ---------------------------------------------------------------------------
# TF-IDF INDEX
# ---------------------------------------------------------------------------

class _Index:

    def __init__(self, rows: List[_Row]):
        self._rows   = rows
        self._vocab: Dict[str, int] = {}
        self._idf:   np.ndarray     = np.array([])
        self._mat:   csr_matrix     = csr_matrix((0, 0))
        self._build(rows)

    def _build(self, rows: List[_Row]) -> None:
        N = len(rows)
        if not N:
            return
        df: Dict[str, int] = defaultdict(int)
        freqs = []
        for row in rows:
            f = _freq(row.tokens)
            freqs.append(f)
            for t in f:
                df[t] += 1

        self._vocab = {t: i for i, t in enumerate(sorted(df))}
        V = len(self._vocab)
        idf = np.array([math.log((N + 1) / (df[t] + 1)) + 1.0 for t in sorted(df)])
        self._idf = idf

        ri, ci, data = [], [], []
        for doc_i, f in enumerate(freqs):
            tot = sum(f.values()) or 1
            for term, cnt in f.items():
                if term in self._vocab:
                    ri.append(doc_i)
                    ci.append(self._vocab[term])
                    data.append((cnt / tot) * idf[self._vocab[term]])

        mat   = csr_matrix((data, (ri, ci)), shape=(N, V))
        norms = np.asarray(sp_norm(mat, axis=1)).ravel()
        norms[norms == 0] = 1.0
        self._mat = mat.multiply(1.0 / norms[:, None])

    def query(self, desc: str, restrict_types: Optional[frozenset] = None,
              min_sim: Optional[float] = None,
              ) -> Tuple[Optional[_Row], float]:
        """TF-IDF cosine similarity match.
        restrict_types: if set, only COA rows whose atype is in this frozenset are considered.
        min_sim: override the module-level MIN_SIMILARITY threshold (use 0.0 to get best
                 match even if score is very low - useful for direction-restricted fallback).
        """
        if not self._rows or not self._mat.shape[0]:
            return None, 0.0
        tokens = _tokenise(desc) + _acronyms(_tokenise(desc))
        if not tokens:
            return None, 0.0
        V   = len(self._vocab)
        q   = np.zeros(V)
        f   = _freq(tokens)
        tot = sum(f.values())
        for term, cnt in f.items():
            if term in self._vocab:
                q[self._vocab[term]] = (cnt / tot) * self._idf[self._vocab[term]]
        qn = np.linalg.norm(q)
        if qn == 0:
            return None, 0.0
        q /= qn
        sims = self._mat.dot(q)
        # FIX 1: zero out wrong-direction rows if restrict_types given
        if restrict_types:
            type_mask = np.array(
                [(r.atype or "").lower() in restrict_types for r in self._rows],
                dtype=float,
            )
            sims = sims * type_mask
            if sims.max() == 0:
                return None, 0.0
        best_idx  = int(np.argmax(sims))
        score     = float(sims[best_idx])
        threshold = min_sim if min_sim is not None else MIN_SIMILARITY
        return (self._rows[best_idx], score) if score >= threshold else (None, score)

    def first_of_type(self, types: frozenset) -> Optional[_Row]:
        for r in self._rows:
            if r.atype.lower() in types:
                return r
        return self._rows[0] if self._rows else None

    def first_name_fragment(self, frags: Tuple[str, ...]) -> Optional[_Row]:
        for r in self._rows:
            if any(f in r.name.lower() for f in frags):
                return r
        return None

    def row_by_name(self, name: str) -> Optional[_Row]:
        """Return the _Row whose name matches exactly (case-insensitive)."""
        nl = name.strip().lower()
        for r in self._rows:
            if r.name.lower() == nl:
                return r
        return None

    @property
    def size(self) -> int:
        return len(self._rows)


# ---------------------------------------------------------------------------
# COA LOADER
# ---------------------------------------------------------------------------

def _load_coa(path: Path) -> List[_Row]:
    rows: List[_Row] = []
    with open(path, newline="", encoding="utf-8-sig") as f:
        for r in csv.DictReader(f):
            name = (r.get("*Name") or r.get("Name") or "").strip()
            if not name:
                continue
            rows.append(_Row(
                name        = name,
                tax_code    = (r.get("*Tax Code") or r.get("Tax Code") or "").strip(),
                atype       = (r.get("*Type")     or r.get("Type")     or "").strip(),
                description = (r.get("Description") or "").strip(),
            ))
    if not rows:
        raise ValueError(f"COA at {path} has 0 valid accounts.")
    return rows


# ---------------------------------------------------------------------------
# RDR ENGINE
# ---------------------------------------------------------------------------

class _Rdr:
    """Loads rdr_rules.json; auto-reloads on file change."""

    def __init__(self, paths: List[Path]):
        self._paths = paths
        self._rules: list = []
        self._sig:   tuple = ()
        self._lock   = threading.Lock()

    def _sig_now(self) -> tuple:
        return tuple(
            (str(p), p.stat().st_mtime_ns if p.exists() else None)
            for p in self._paths
        )

    def _reload(self) -> None:
        for path in self._paths:
            if not path.exists():
                continue
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
                if not isinstance(data, list):
                    continue
                cleaned = []
                for item in data:
                    if not isinstance(item, dict):
                        continue
                    cond = item.get("if", {})
                    if not isinstance(cond, dict):
                        continue
                    gl  = str(item.get("then", "")).strip()
                    gst = str(item.get("then_gst_category",
                              item.get("then_gst",
                              item.get("gst_category", "")))).strip()
                    if gl or gst:
                        cleaned.append(item)
                cleaned.sort(key=lambda r: int(r.get("priority", 0)), reverse=True)
                self._rules = cleaned
                return
            except Exception:
                continue
        self._rules = []

    def apply(self, desc: str, debit: float, credit: float) -> Optional[dict]:
        sig = self._sig_now()
        with self._lock:
            if sig != self._sig:
                self._reload()
                self._sig = sig
            rules = self._rules

        text = (desc or "").strip().lower()
        if not text:
            return None

        for rule in rules:
            cond = rule.get("if", {}) or {}
            try:
                if "debit_gt"  in cond and not (float(debit  or 0) > float(cond["debit_gt"])):
                    continue
                if "credit_gt" in cond and not (float(credit or 0) > float(cond["credit_gt"])):
                    continue
            except Exception:
                continue

            # Direction conditions
            if "credit_only" in cond and cond["credit_only"]:
                if not (credit > 0 and debit == 0):
                    continue
            if "debit_only" in cond and cond["debit_only"]:
                if not (debit > 0 and credit == 0):
                    continue

            if "contains_any" in cond:
                needles = cond["contains_any"]
                if not isinstance(needles, list) or not any(str(k).lower() in text for k in needles):
                    continue

            # not_contains_any: rule must NOT match if any of these are in desc
            if "not_contains_any" in cond:
                blockers = cond["not_contains_any"]
                if isinstance(blockers, list) and any(str(k).lower() in text for k in blockers):
                    continue

            # also_contains_any: ALL conditions must match (secondary AND filter)
            if "also_contains_any" in cond:
                also = cond["also_contains_any"]
                if isinstance(also, list) and not any(str(k).lower() in text for k in also):
                    continue

            if "regex_any" in cond:
                patterns = cond["regex_any"]
                if not isinstance(patterns, list):
                    continue
                try:
                    if not any(re.search(rx, text) for rx in patterns):
                        continue
                except re.error:
                    continue

            gl      = str(rule.get("then", "")).strip()
            gst     = str(rule.get("then_gst_category",
                          rule.get("then_gst",
                          rule.get("gst_category", "")))).strip()
            gl_type = str(rule.get("then_gl_type", "")).strip()
            if gl or gst:
                return {"gl": gl, "gst": gst, "gl_type": gl_type}

        return None


# ---------------------------------------------------------------------------
# KNOWLEDGE BASE LOADER
_KB_PATHS = [
    _MAIN_APP / "data" / "knowledge_base.json",
    _MAIN_APP.parent / "knowledge_base.json",
]
_kb_cache: dict = {}
_kb_mtime: float = 0.0
_kb_lock = threading.Lock()

def _load_knowledge_base() -> dict:
    """Load knowledge_base.json; auto-reload when file changes."""
    global _kb_cache, _kb_mtime
    kb_path = next((p for p in _KB_PATHS if p.exists()), None)
    if not kb_path:
        return {}
    try:
        mtime = kb_path.stat().st_mtime
        with _kb_lock:
            if mtime != _kb_mtime:
                _kb_cache = json.loads(kb_path.read_text(encoding="utf-8"))
                _kb_mtime = mtime
        return _kb_cache
    except Exception:
        return _kb_cache or {}

# ---------------------------------------------------------------------------
# PER-ACCOUNT INDEX CACHE
# ---------------------------------------------------------------------------

class _Cache:

    def __init__(self):
        self._lock   = threading.Lock()
        self._idx:   Dict[str, _Index]            = {}
        self._paths: Dict[str, Path]              = {}
        self._xfer:  Dict[str, Optional[_Row]]    = {}

    def register(self, account_id: str, coa_path: Path) -> None:
        with self._lock:
            if self._paths.get(account_id) != coa_path:
                self._idx.pop(account_id, None)
                self._xfer.pop(account_id, None)
            self._paths[account_id] = coa_path

    def get_index(self, account_id: str) -> _Index:
        with self._lock:
            if account_id in self._idx:
                return self._idx[account_id]
        path  = self._paths.get(account_id, DEFAULT_COA_PATH)
        rows  = _load_coa(path)
        index = _Index(rows)
        with self._lock:
            if account_id not in self._idx:
                self._idx[account_id] = index
            return self._idx[account_id]

    def get_transfer_row(self, account_id: str, index: _Index) -> Optional[_Row]:
        with self._lock:
            if account_id in self._xfer:
                return self._xfer[account_id]
        row = index.first_name_fragment(_TRANSFER_GL_FRAGMENTS)
        with self._lock:
            self._xfer[account_id] = row
        return row

    def evict(self, account_id: str) -> None:
        with self._lock:
            self._idx.pop(account_id, None)
            self._paths.pop(account_id, None)
            self._xfer.pop(account_id, None)


_cache          = _Cache()
_rdr            = _Rdr(_RDR_PATHS)
_DEFAULT_ACCT   = "__default__"


# ---------------------------------------------------------------------------
# PUBLIC API
# ---------------------------------------------------------------------------

def warm(account_id: str = _DEFAULT_ACCT,
         coa_path: Optional[Path] = None) -> None:
    """Pre-warm TF-IDF index. Call at app startup - no-op if already loaded."""
    if coa_path:
        _cache.register(account_id, Path(coa_path))
    _cache.get_index(account_id)


def rebuild(account_id: str = _DEFAULT_ACCT,
            coa_path: Optional[Path] = None) -> None:
    """Evict and rebuild after a COA change."""
    _cache.evict(account_id)
    warm(account_id, coa_path)


def evict(account_id: str = _DEFAULT_ACCT) -> None:
    """Release cached index. Call at logout."""
    _cache.evict(account_id)


def classify(
    description: str,
    debit:       float = 0.0,
    credit:      float = 0.0,
    account_id:  str   = _DEFAULT_ACCT,
    coa_path:    Optional[Path] = None,
) -> ClassifyResult:
    """
    Classify one transaction - GL account + GST category + GST amount.

    All three come from the same COA row in a single pass.
    Never call gst_calculator separately - the result already contains gst_amount.

    Parameters
    ----------
    description  Bank narrative / memo text
    debit        Amount out  (positive, 0 if credit)
    credit       Amount in   (positive, 0 if debit)
    account_id   Per-user cache key (optional)
    coa_path     Override path to ChartOfAccounts.csv (optional)
    """
    if coa_path is not None:
        _cache.register(account_id, Path(coa_path))

    index = _cache.get_index(account_id)
    desc  = (description or "").strip()

    # -- Stage 1: RDR override --------------------------------------------
    rdr_hit = _rdr.apply(desc, debit, credit)
    if rdr_hit:
        gl  = rdr_hit["gl"]
        gst = rdr_hit["gst"]
        # If RDR only provided one field, fill the other from TF-IDF
        if not gl or not gst:
            row, _ = index.query(desc)
            if row:
                gl  = gl  or row.name
                gst = gst or row.tax_code
        # Use gl_type from rule if specified, else lookup from COA
        _rdr_type = rdr_hit.get("gl_type", "")
        if not _rdr_type and gl:
            for _r in index._rows:
                if _r.name.lower() == gl.lower():
                    _rdr_type = _r.atype
                    break

        # Direction guard for RDR results - same rule as Stage 3:
        # a credit-only transaction must not resolve to an Expense-type GL.
        # If the RDR rule returned a wrong-direction GL, override with the
        # best direction-correct TF-IDF match from the COA.
        _is_credit_only = credit > 0 and debit == 0
        _is_debit_only  = debit  > 0 and credit == 0
        _rdr_type_lower = _rdr_type.lower()
        _direction_wrong = (
            # Credit row must NOT get an Expense/Direct Costs GL
            # EXCEPT "Return" type is allowed on credit (refund of expense)
            (_is_credit_only and _rdr_type_lower in _EXPENSE_TYPES
             and _rdr_type_lower != "return") or
            # Debit row must NOT get a Revenue/Return GL
            (_is_debit_only  and _rdr_type_lower in _INCOME_TYPES)
            # Neutral types (Equity, Fixed Asset, GST, Inventory) are allowed on either side
        )
        if _direction_wrong and gl:
            _target = _INCOME_TYPES if _is_credit_only else _EXPENSE_TYPES
            _fix_row, _ = index.query(gl, restrict_types=_target)
            if not _fix_row:
                _fix_row = index.first_of_type(_target)
            if _fix_row:
                gl        = _fix_row.name
                _rdr_type = _fix_row.atype
                gst       = _fix_row.tax_code

        return ClassifyResult(
            gl_account   = gl,
            gl_type      = _rdr_type,
            gst_category = gst,
            gst_amount   = _calc_gst(debit, credit, gst),
            matched      = True,
            score        = 1.0,
            source       = "rdr",
        )

    # -- Stage 2: Transfer intercept --------------------------------------
    if desc:
        padded = f" {desc.lower()} "
        if any(pat in padded for pat in _TRANSFER_PATTERNS):
            xrow = _cache.get_transfer_row(account_id, index)
            if xrow:
                return ClassifyResult(
                    gl_account   = xrow.name,
                    gl_type      = xrow.atype,
                    gst_category = xrow.tax_code,
                    gst_amount   = 0.0,   # transfers never carry GST
                    matched      = True,
                    score        = 1.0,
                    source       = "transfer",
                )

    # -- Stage 2.5: Knowledge-base lookup ----------------------------------
    # knowledge_base.json: vendor_map (WHO->GL) + keyword_map (desc->GL)
    # User-editable, auto-reloaded. No hardcoding needed.
    if desc:
        _kb      = _load_knowledge_base()
        _kbtext  = desc.lower()
        _is_out  = debit  > 0 and credit == 0
        _is_in   = credit > 0 and debit  == 0

        # Extract WHO suffix added by react_api: "desc|who:microsoft"
        _who_str = ""
        if "|who:" in _kbtext:
            _parts  = _kbtext.split("|who:", 1)
            _kbtext = _parts[0].strip()
            _who_str = _parts[1].strip()

        # Internal transfer detection
        for _ik in _kb.get("internal_keywords", []):
            if _ik in _kbtext:
                return ClassifyResult(
                    gl_account="", gl_type="", gst_category="BAS Excluded",
                    gst_amount=0.0, matched=True, score=0.9, source="kb_internal")

        # Return/refund prefix detection
        _is_return = any(_kbtext.startswith(p) for p in _kb.get("return_prefixes", []))

        # 1. Vendor map: try WHO first, then description text
        # For return/refund transactions, ignore direction (return reverses original)
        # IMPORTANT: sort vendor keys longest-first so "uber eats" wins over "uber",
        # "xero payroll" wins over "xero", "google ads" wins over "google", etc.
        _vm = _kb.get("vendor_map", {})
        _vm_sorted = sorted(_vm.items(), key=lambda kv: -len(kv[0]))
        _match = None
        for _search_who in [True, False]:  # True = search WHO text first, then desc text
            _txt = _who_str if _search_who else _kbtext
            if not _txt:
                continue
            for _vk, _ve in _vm_sorted:
                if _vk not in _txt:
                    continue
                # When matching against WHO text: skip shorter keys if a longer key
                # from the same vendor_map also matches (e.g. skip "uber" when
                # "uber eats" also appears in _txt — longest-first sort handles this
                # automatically since we break on first match).
                if not _is_return:
                    _d = _ve.get("direction", "")
                    if _d == "debit"  and not _is_out: continue
                    if _d == "credit" and not _is_in:  continue
                _match = _ve
                break
            if _match:
                break

        # 2. Keyword map: fallback if no vendor match
        # Sort longest-first so specific phrases ("rent payment") beat short ones ("rent")
        if not _match:
            _km_sorted = sorted(_kb.get("keyword_map", {}).items(), key=lambda kv: -len(kv[0]))
            for _kk, _ke in _km_sorted:
                if _kk not in _kbtext: continue
                if not _is_return:
                    _d = _ke.get("direction","")
                    if _d == "debit"  and not _is_out: continue
                    if _d == "credit" and not _is_in:  continue
                _match = _ke; break

        if _match:
            _mgl  = _match.get("gl","")
            _mtyp = _match.get("gl_type","")
            _mgst = _match.get("gst","")
            # For returns/refunds, keep the same GL and GST as the original purchase.
            # _run_classify_gl handles the vendor-GL lookup from prior rows; the engine
            # only reaches here when no prior row exists, so just use the vendor's GL as-is.
            if _mgl and not _mtyp:
                _r2 = index.row_by_name(_mgl)
                if _r2: _mtyp = _r2.atype; _mgst = _mgst or _r2.tax_code
            return ClassifyResult(
                gl_account=_mgl, gl_type=_mtyp, gst_category=_mgst,
                gst_amount=_calc_gst(debit, credit, _mgst),
                matched=bool(_mgl), score=0.9, source="kb")

        # Return/refund with no vendor match — fall through to TF-IDF
        # (don't hard-code Other Revenue; let direction-aware TF-IDF decide)

    # -- Stage 3: TF-IDF semantic match - direction-first ----------------
    # -- Stage 3: TF-IDF semantic match - direction-first ----------------
    if desc:
        # Determine which COA account types are valid for this transaction direction.
        # A credit (money IN)  must map to a Revenue/Income GL account.
        # A debit  (money OUT) must map to an Expense/Cost GL account.
        # Mixed or zero amounts have no restriction.
        # This is applied BEFORE picking the best row, not as a post-hoc correction,
        # so "Interest Expense" can never win over "Interest Income" for a credit tx.
        _is_credit_only = credit > 0 and debit == 0
        _is_debit_only  = debit  > 0 and credit == 0

        if _is_credit_only:
            _direction_types = _INCOME_TYPES
        elif _is_debit_only:
            _direction_types = _EXPENSE_TYPES
        else:
            _direction_types = None   # no restriction for mixed/zero amounts

        # First try: query restricted to the correct direction type.
        # This ensures "interest received" (credit) always resolves to
        # Interest Income (Revenue) not Interest Expense (Expense), even if the
        # TF-IDF score for the expense account is marginally higher.
        row, score = index.query(desc, restrict_types=_direction_types)

        if not row and _direction_types is not None:
            # Nothing matched within the correct type at MIN_SIMILARITY.
            # Try with min_sim=0 (take the best score even if weak) but STAY
            # restricted to the correct direction type - never cross into
            # Expense for a credit row or Revenue for a debit row.
            row, score = index.query(desc, restrict_types=_direction_types, min_sim=0.0)
            # If still nothing (e.g. all Revenue accounts scored exactly 0),
            # try including neutral types (Equity, Fixed Asset, Inventory, GST)
            # but still exclude the wrong-direction types entirely.
            if not row:
                _allowed = _direction_types | _NEUTRAL_TYPES
                row, score = index.query(desc, restrict_types=_allowed, min_sim=0.0)

        if row:
            return ClassifyResult(
                gl_account   = row.name,
                gl_type      = row.atype,
                gst_category = row.tax_code,
                gst_amount   = _calc_gst(debit, credit, row.tax_code),
                matched      = True,
                score        = score,
                source       = "tfidf",
            )

    # -- Stage 4: Directional fallback ------------------------------------
    # For credit rows: try Revenue first, then include Equity/neutral types.
    # For debit rows: try Expense/Direct Costs first.
    # Never return an Expense-type GL for a credit row.
    if credit > 0 and debit == 0:
        target = _INCOME_TYPES | _NEUTRAL_TYPES
    elif debit > 0 and credit == 0:
        target = _EXPENSE_TYPES
    else:
        target = _INCOME_TYPES | _EXPENSE_TYPES | _NEUTRAL_TYPES
    fb     = index.first_of_type(target)
    if fb:
        return ClassifyResult(
            gl_account   = fb.name,
            gl_type      = fb.atype,
            gst_category = fb.tax_code,
            gst_amount   = _calc_gst(debit, credit, fb.tax_code),
            matched      = False,
            score        = 0.0,
            source       = "fallback",
        )

    return ClassifyResult(
        gl_account="", gl_type="", gst_category="", gst_amount=0.0,
        matched=False, score=0.0, source="fallback",
    )


def classify_df(
    df:          "pd.DataFrame",
    account_id:  str = _DEFAULT_ACCT,
    coa_path:    Optional[Path] = None,
) -> "pd.DataFrame":
    """
    Classify all rows in a DataFrame in one call.

    Expects columns: description, debit, credit  (case-insensitive)
    Adds columns:    gl_account, gst_category, gst_amount, matched, source

    Returns the DataFrame with new columns filled.
    """
    import pandas as pd

    df = df.copy()
    df.columns = df.columns.str.strip().str.lower()

    if "debit"  not in df.columns: df["debit"]  = 0.0
    if "credit" not in df.columns: df["credit"] = 0.0
    if "description" not in df.columns: df["description"] = ""

    df["debit"]  = pd.to_numeric(df["debit"],  errors="coerce").fillna(0.0)
    df["credit"] = pd.to_numeric(df["credit"], errors="coerce").fillna(0.0)

    # Pre-warm once
    warm(account_id, coa_path)

    results = [
        classify(
            description = str(row.description),
            debit       = float(row.debit),
            credit      = float(row.credit),
            account_id  = account_id,
        )
        for row in df.itertuples(index=False)
    ]

    df["gl_account"]   = [r.gl_account   for r in results]
    df["gl_type"]      = [r.gl_type      for r in results]
    df["gst_category"] = [r.gst_category for r in results]
    df["gst_amount"]   = [r.gst_amount   for r in results]
    df["matched"]      = [r.matched      for r in results]
    df["source"]       = [r.source       for r in results]
    return df


# -- GST_CATEGORY_OPTIONS - used by UI dropdowns ---------------------------
def gst_category_options(coa_path: Optional[Path] = None) -> List[str]:
    """
    Return all unique *Tax Code values from the COA, sorted.
    Derived at runtime - no hardcoded list.
    """
    path = coa_path or DEFAULT_COA_PATH
    options: set = set()
    try:
        with open(path, newline="", encoding="utf-8-sig") as f:
            for r in csv.DictReader(f):
                tc = (r.get("*Tax Code") or r.get("Tax Code") or "").strip()
                if tc:
                    options.add(tc)
    except Exception:
        pass
    return sorted(options)