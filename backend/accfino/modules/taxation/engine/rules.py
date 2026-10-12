"""Statutory rule sets for Taxation & Compliance, loaded from ACCFINO_DATA_ROOT/reference/tax_statutory_rules.json (seeded from deploy/data-seed).
The engines never contain a rate or threshold: they ask the RuleSet that applies. Each value group carries provenance (how well it was verified), and an
organisation can override a value (audited, with a reason). Nothing here invents a figure: `null` means 'not loaded' and callers must warn."""
import copy
import json
import threading
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from accfino.modules.taxation.engine.money import D

RULES_FILE = "tax_statutory_rules.json"
OVERRIDABLE_PREFIXES = ("payroll_tax.", "individual.", "company.", "gst.", "small_business.", "fbt.", "div7a.", "cgt.", "payg_instalments.", "bas.", "super.", "income_tax_return.")


class RulesError(ValueError):
    """No usable statutory rules (e.g. no rule set covers the date)."""


def fy_label(start_year: int) -> str:
    return f"{start_year}-{str(start_year + 1)[-2:]}"


def fy_of(d: date, fy_end_month: int = 6) -> str:
    """Income-year label ('2026-27') of the year containing d, for a year ending on the last day of fy_end_month."""
    start_year = d.year if d.month > fy_end_month else d.year - 1
    return fy_label(start_year)


def fy_bounds(label: str, fy_end_month: int = 6) -> Tuple[date, date]:
    try:
        y = int(label[:4])
    except (ValueError, TypeError):
        raise RulesError(f"'{label}' is not an income year such as 2026-27")
    if len(label) != 7 or label[4] != "-" or int(label[5:]) != (y + 1) % 100:
        raise RulesError(f"'{label}' is not an income year such as 2026-27")
    end = date(y + 1, fy_end_month, 28)
    nxt = date(end.year + (1 if fy_end_month == 12 else 0), (fy_end_month % 12) + 1, 1)
    from datetime import timedelta
    last = nxt - timedelta(days=1)
    start = date(last.year - 1, last.month, last.day) + timedelta(days=1)
    return start, last


def fbt_year_label(d: date) -> str:
    """FBT year runs 1 April - 31 March; labelled by the year it ENDS in ('FBT2027' for 1 Apr 2026 - 31 Mar 2027)."""
    return f"FBT{d.year + 1 if d.month >= 4 else d.year}"


def fbt_bounds(label: str) -> Tuple[date, date]:
    try:
        if not (isinstance(label, str) and label.startswith("FBT") and len(label) == 7):
            raise ValueError
        y = int(label[3:])
    except ValueError:
        raise RulesError(f"'{label}' is not an FBT year such as FBT2027")
    return date(y - 1, 4, 1), date(y, 3, 31)


@dataclass
class TaxRuleSet:
    id: str
    label: str
    effective_from: date
    effective_to: Optional[date]
    raw: dict
    div7a_history: Dict[str, Decimal] = field(default_factory=dict)
    overrides: Dict[str, Any] = field(default_factory=dict)       # dotted path -> value applied from the organisation

    # ---- access ------------------------------------------------------------------------------------------------------------------
    def get(self, path: str, default=None):
        cur: Any = self.raw
        for part in path.split("."):
            if not isinstance(cur, dict) or part not in cur:
                return default
            cur = cur[part]
        return default if cur is None and default is not None else cur

    def has_value(self, path: str) -> bool:
        return self.get(path) is not None

    def dec(self, path: str, default: Optional[Decimal] = None) -> Optional[Decimal]:
        v = self.get(path)
        return default if v is None else D(v)

    def req(self, path: str) -> Decimal:
        v = self.get(path)
        if v is None:
            raise RulesError(f"Rule '{path}' is not loaded for {self.id}. Load it under Tax > Rates & Settings.")
        return D(v)

    def text(self, path: str) -> str:
        v = self.get(path)
        if v is None:
            raise RulesError(f"Rule '{path}' is not loaded for {self.id}.")
        return str(v)

    def brackets(self, path: str) -> List[Tuple[Optional[Decimal], Decimal]]:
        return [(None if up is None else D(up), D(rate)) for up, rate in self.get(path, [])]

    def provenance(self, path: str) -> dict:
        """Provenance for a dotted path. The closest annotation wins: a per-value entry in an ancestor's `_provenance_keys` beats that ancestor's `_provenance`,
        and a deeper level beats a shallower one (so `bas.quarterly_due.Q1` inherits the note written for `bas.quarterly_due`)."""
        found: dict = {}
        cur: Any = self.raw
        for p in path.split("."):
            if not isinstance(cur, dict):
                break
            if "_provenance" in cur:
                found = cur["_provenance"]
            if p in (cur.get("_provenance_keys") or {}):
                found = cur["_provenance_keys"][p]
            cur = cur.get(p)
        if isinstance(cur, dict) and "_provenance" in cur:
            found = cur["_provenance"]
        return found

    def is_overridden(self, path: str) -> bool:
        return path in self.overrides

    def with_overrides(self, overrides: Dict[str, Any]) -> "TaxRuleSet":
        raw = copy.deepcopy(self.raw)
        for path, value in overrides.items():
            if not path.startswith(OVERRIDABLE_PREFIXES):
                raise RulesError(f"'{path}' cannot be overridden")
            cur = raw
            parts = path.split(".")
            for p in parts[:-1]:
                if not isinstance(cur, dict) or p not in cur:
                    raise RulesError(f"Unknown rule '{path}'")
                cur = cur[p]
            if not isinstance(cur, dict) or parts[-1] not in cur or parts[-1].startswith("_"):
                raise RulesError(f"Unknown rule '{path}'")
            cur[parts[-1]] = value
        return TaxRuleSet(self.id, self.label, self.effective_from, self.effective_to, raw, self.div7a_history, dict(overrides))

    def flat(self) -> List[dict]:
        """Every leaf value with its provenance, for the Rates & Settings screen."""
        rows: List[dict] = []

        def walk(node, prefix):
            for k, v in node.items():
                if k.startswith("_") or (prefix == "" and k in ("id", "label", "effective_from", "effective_to", "provisional")):          # rule-set metadata is skipped at the root ONLY
                    continue
                path = f"{prefix}{k}"
                if isinstance(v, dict):
                    walk(v, path + ".")
                else:
                    p = self.provenance(path)
                    rows.append(dict(path=path, value=v, overridden=path in self.overrides, loaded=v is not None,
                                     verification=p.get("verification", "knowledge_unverified"), source=p.get("source", ""), checked_on=p.get("checked_on", "")))
        walk(self.raw, "")
        return rows

    @property
    def provisional(self) -> bool:
        """A rule set prepared before its figures were published: everything it holds must be treated as an assumption."""
        return bool(self.raw.get("provisional"))

    def summary(self) -> dict:
        return dict(provisional=self.provisional, id=self.id, label=self.label, effective_from=self.effective_from.isoformat(), effective_to=self.effective_to.isoformat() if self.effective_to else None)


class RuleBook:
    def __init__(self, sets: List[TaxRuleSet], history: Dict[str, Decimal]):
        self.sets = sorted(sets, key=lambda r: r.effective_from)
        self.div7a_history = history

    def for_date(self, d: date) -> TaxRuleSet:
        found = None
        for rs in self.sets:
            if rs.effective_from <= d and (rs.effective_to is None or d <= rs.effective_to):
                found = rs
        if found is None:
            have = ", ".join(r.id for r in self.sets) or "none"
            raise RulesError(f"No statutory tax rules cover {d.isoformat()} (rule sets loaded: {have}). Add a rule set to {RULES_FILE}.")
        return found

    def for_fy(self, label: str, fy_end_month: int = 6) -> TaxRuleSet:
        start, _ = fy_bounds(label, fy_end_month)
        return self.for_date(start)

    def for_fbt_year(self, label: str) -> TaxRuleSet:
        """The rule set holding the FBT parameters for an FBT year is the one covering its 31 March end date."""
        return self.for_date(fbt_bounds(label)[1])


def load_rulebook(path: Optional[Path] = None) -> RuleBook:
    if path is None:
        from accfino.shared import paths
        path = paths.reference_file(RULES_FILE)
    try:
        raw = json.loads(Path(path).read_text(encoding="utf-8"))
    except FileNotFoundError:
        raise RulesError(f"Tax statutory rules file not found: {path}")
    except json.JSONDecodeError as e:
        raise RulesError(f"Tax statutory rules file {path} is not valid JSON: {e}")
    hist = {k: D(v) for k, v in (raw.get("div7a_benchmark_history") or {}).items() if not k.startswith("_")}
    sets = []
    for r in raw.get("rule_sets", []):
        try:
            sets.append(TaxRuleSet(id=r["id"], label=r.get("label", r["id"]), effective_from=date.fromisoformat(r["effective_from"]),
                                   effective_to=date.fromisoformat(r["effective_to"]) if r.get("effective_to") else None, raw=r, div7a_history=hist))
        except (KeyError, ValueError) as e:
            raise RulesError(f"Rule set {r.get('id', '?')} is malformed: {e!r}")
    return RuleBook(sets, hist)


_lock = threading.Lock()
_cache: dict = {}


def rulebook() -> RuleBook:
    """Cached by file path + modification time, so editing the file takes effect without a restart."""
    from accfino.shared import paths
    p = paths.reference_file(RULES_FILE)
    key = (str(p), p.stat().st_mtime_ns if p.exists() else 0)
    with _lock:
        if _cache.get("key") != key:
            _cache["key"], _cache["book"] = key, load_rulebook(p)
        return _cache["book"]
