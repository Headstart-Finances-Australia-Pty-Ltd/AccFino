"""Duplicate detection (pure). Produces CANDIDATES with the reasons and a score; it never decides a merge."""
import re
from difflib import SequenceMatcher

DEFAULTS = dict(name_threshold=0.88, match_email=True, match_phone=True, match_identifier=True)
_NOISE = re.compile(r"\b(pty|ltd|limited|proprietary|the|trust|trustee|for|atf|as)\b|[^a-z0-9 ]")


def norm_name(s: str) -> str:
    return re.sub(r"\s+", " ", _NOISE.sub(" ", (s or "").lower())).strip()


def norm_phone(s: str) -> str:
    d = re.sub(r"\D", "", s or "")
    return ("0" + d[2:]) if d.startswith("61") and len(d) == 11 else d


def similarity(a: str, b: str) -> float:
    a, b = norm_name(a), norm_name(b)
    if not a or not b:
        return 0.0
    ta, tb = sorted(a.split()), sorted(b.split())
    return max(SequenceMatcher(None, a, b).ratio(), SequenceMatcher(None, " ".join(ta), " ".join(tb)).ratio())


def compare(a: dict, b: dict, cfg: dict = None) -> dict:
    """a, b: {name, email, phone, identifiers: {kind: digits}}. Returns {score, reasons[]} - reasons empty means 'not a candidate'."""
    c = dict(DEFAULTS, **(cfg or {}))
    reasons, score = [], 0.0
    if c["match_identifier"]:
        for k, v in (a.get("identifiers") or {}).items():
            if v and (b.get("identifiers") or {}).get(k) == v:
                reasons.append(f"same {k.upper()}"); score = max(score, 1.0)
    if c["match_email"] and a.get("email") and (a.get("email") or "").strip().lower() == (b.get("email") or "").strip().lower():
        reasons.append("same email"); score = max(score, 0.9)
    if c["match_phone"] and norm_phone(a.get("phone")) and norm_phone(a.get("phone")) == norm_phone(b.get("phone")):
        reasons.append("same phone"); score = max(score, 0.8)
    s = similarity(a.get("name", ""), b.get("name", ""))
    if s >= c["name_threshold"]:
        reasons.append(f"similar name ({round(s * 100)}%)"); score = max(score, s)
    return dict(score=round(score, 3), reasons=reasons)
