from sqlalchemy import Column, String, Integer, Float, Boolean, Text, JSON, TIMESTAMP
from datetime import datetime
from .base import Base


class RDRRule(Base):
    """A single Ripple-Down-Rule override for transaction classification.

    Split into real columns (rather than one opaque `if_condition` JSON
    blob) so a rule is actually browsable/editable field-by-field in the
    Tables admin UI.

    `keywords` is a pipe-separated TEXT column (e.g. "uber|didi|taxi"),
    not a JSON array -- this matches exactly how SetupPage.jsx's RDR
    editor already reads/writes keywords via CSV export/import
    (`.join('|')` / `.split('|')`), so the column shows real readable
    text in the Tables browser instead of a JSON array needing a
    textarea to edit.

    `regex_any` stays JSON (not pipe-delimited) because regex patterns
    routinely use "|" themselves for alternation -- pipe-joining them
    would make it impossible to tell a pattern separator from a literal
    "|" inside a pattern.

    to_dict() reconstructs the exact same {id, name, priority, if, then,
    then_gst_category} shape every consumer (react_api.py, rdr.py)
    already expects, so callers don't need to change just because
    storage moved from one blob to real columns.

    id stays a String (not an autoincrement int) because the frontend
    already generates ids client-side as f"rule_{timestamp_ms}" and the
    API contract (PUT/DELETE /rdr/rules/{rule_id}) depends on that.
    """
    __tablename__ = "rdr_rules"

    id                 = Column(String(64), primary_key=True)
    name               = Column(String(200), nullable=True)
    priority           = Column(Integer, default=100, nullable=False)

    # -- split out of the old if_condition JSON blob --
    keywords           = Column(Text, nullable=True)                  # pipe-separated, e.g. "uber|didi|taxi"
    regex_any          = Column(JSON, nullable=False, default=list)   # list[str] regex patterns
    debit_gt           = Column(Float, nullable=True)
    credit_gt          = Column(Float, nullable=True)
    debit_only         = Column(Boolean, default=False, nullable=False)
    credit_only        = Column(Boolean, default=False, nullable=False)

    then               = Column(String(200), nullable=True)           # GL account name
    then_gst_category  = Column(String(100), nullable=True)
    created_at         = Column(TIMESTAMP, default=datetime.utcnow)
    updated_at         = Column(TIMESTAMP, default=datetime.utcnow, onupdate=datetime.utcnow)

    @property
    def contains_any(self) -> list:
        """list[str] view of `keywords` for code that wants the list
        form (matches the shape rdr.py/react_api.py expect in `if`)."""
        if not self.keywords:
            return []
        return [k.strip() for k in self.keywords.split("|") if k.strip()]

    def to_dict(self) -> dict:
        """Matches the exact JSON shape every consumer already expects
        (see main_app/react_api.py's rdr_* endpoints and rdr.py's
        load_rdr_rules)."""
        cond = {}
        if self.contains_any:
            cond["contains_any"] = self.contains_any
        if self.regex_any:
            cond["regex_any"] = self.regex_any
        if self.debit_gt is not None:
            cond["debit_gt"] = self.debit_gt
        if self.credit_gt is not None:
            cond["credit_gt"] = self.credit_gt
        if self.debit_only:
            cond["debit_only"] = True
        if self.credit_only:
            cond["credit_only"] = True
        return {
            "id": self.id,
            "name": self.name,
            "priority": self.priority,
            "if": cond,
            "then": self.then,
            "then_gst_category": self.then_gst_category,
        }

    def set_condition(self, cond: dict):
        """Splits an incoming {"if": {...}} dict back into the real
        columns -- the inverse of to_dict()'s "if" reconstruction."""
        cond = cond or {}
        kws = cond.get("contains_any", []) or []
        self.keywords = "|".join(str(k).strip() for k in kws if str(k).strip()) or None
        self.regex_any = cond.get("regex_any", []) or []
        self.debit_gt = cond.get("debit_gt")
        self.credit_gt = cond.get("credit_gt")
        self.debit_only = bool(cond.get("debit_only", False))
        self.credit_only = bool(cond.get("credit_only", False))
