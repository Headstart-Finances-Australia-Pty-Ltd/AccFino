"""Statutory rule sets, loaded from ACCFINO_DATA_ROOT/reference/payroll_statutory_rules.json (seeded from deploy/data-seed on first use).
The engine never contains a rate or threshold: it asks the RuleSet that applies to the pay date."""
import json
import threading
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from accfino.modules.payroll.engine.money import D

RULES_FILE = "payroll_statutory_rules.json"
Row = Tuple[Optional[Decimal], Decimal, Decimal]       # (x < upper (None = no limit), a, b)


class RulesError(ValueError):
    """No usable statutory rules (e.g. no rule set covers the pay date)."""


def _rows(raw) -> List[Row]:
    return [(None if r[0] is None else D(r[0]), D(r[1]), D(r[2])) for r in raw]


@dataclass
class RuleSet:
    id: str
    label: str
    effective_from: date
    effective_to: Optional[date]
    scales: Dict[str, List[Row]]
    scale4: Dict[str, Decimal]
    offset_pct: Dict[str, Decimal]
    stsl_tft: List[Row]
    stsl_no_tft: List[Row]
    method_a_cap: Decimal
    sg_rate: Decimal
    mcb_annual: Decimal
    super_due_business_days: int
    etp: Dict[str, Decimal]
    preservation_age: int
    term_leave_pre1993_rate: Decimal
    leave_defaults: Dict[str, Decimal]
    sources: dict = field(default_factory=dict)

    def summary(self) -> dict:
        return {"id": self.id, "label": self.label, "effective_from": self.effective_from.isoformat(),
                "effective_to": self.effective_to.isoformat() if self.effective_to else None,
                "sg_rate": str(self.sg_rate), "max_contribution_base_annual": str(self.mcb_annual),
                "super_due_business_days": self.super_due_business_days, "etp_cap": str(self.etp["cap"]),
                "scales": sorted(self.scales), "sources": self.sources}


def parse_rule_set(raw: dict) -> RuleSet:
    try:
        p, s = raw["payg"], raw["super"]
        etp = {k: D(v) for k, v in raw["etp"].items() if k not in ("note", "preservation_age")}
        return RuleSet(
            id=raw["id"], label=raw.get("label", raw["id"]), effective_from=date.fromisoformat(raw["effective_from"]),
            effective_to=date.fromisoformat(raw["effective_to"]) if raw.get("effective_to") else None,
            scales={k: _rows(v) for k, v in p["scales"].items()}, scale4={k: D(v) for k, v in p["scale4_rates"].items()},
            offset_pct={k: D(v) for k, v in p["offset_percent_of_claim"].items()},
            stsl_tft=_rows(raw["study_loan"]["tax_free_threshold_or_foreign"]), stsl_no_tft=_rows(raw["study_loan"]["no_tax_free_threshold"]),
            method_a_cap=D(raw["additional_payments"]["method_a_cap_rate"]), sg_rate=D(s["sg_rate"]),
            mcb_annual=D(s["max_contribution_base_annual"]), super_due_business_days=int(s["due_business_days_after_payday"]),
            etp=etp, preservation_age=int(raw["etp"]["preservation_age"]),
            term_leave_pre1993_rate=D(raw["termination_leave"]["pre_1993_flat_rate"]),
            leave_defaults={k: D(v) for k, v in raw["leave_defaults"].items()}, sources=raw.get("sources", {}))
    except (KeyError, TypeError, IndexError) as e:
        raise RulesError(f"Rule set {raw.get('id', '?')} is incomplete or malformed: {e!r}")


class RuleBook:
    def __init__(self, sets: List[RuleSet]):
        self.sets = sorted(sets, key=lambda r: r.effective_from)

    def for_date(self, d: date) -> RuleSet:
        found = None
        for rs in self.sets:
            if rs.effective_from <= d and (rs.effective_to is None or d <= rs.effective_to):
                found = rs
        if found is None:
            have = ", ".join(r.id for r in self.sets) or "none"
            raise RulesError(f"No statutory payroll rules cover {d.isoformat()} (rule sets loaded: {have}). Add a rule set to {RULES_FILE}.")
        return found


def load_rulebook(path: Optional[Path] = None) -> RuleBook:
    if path is None:
        from accfino.shared import paths
        path = paths.reference_file(RULES_FILE)
    try:
        raw = json.loads(Path(path).read_text(encoding="utf-8"))
    except FileNotFoundError:
        raise RulesError(f"Statutory rules file not found: {path}")
    except json.JSONDecodeError as e:
        raise RulesError(f"Statutory rules file {path} is not valid JSON: {e}")
    return RuleBook([parse_rule_set(r) for r in raw.get("rule_sets", [])])


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
