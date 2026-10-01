from sqlalchemy import Column, Integer, String, Float, Boolean, JSON, TIMESTAMP
from datetime import datetime
from .base import Base


class ChartOfAccount(Base):
    """Replaces ChartOfAccounts.csv as the source of truth. The CSV file is
    still regenerated on every write (see sync_coa_csv_from_db in
    main_app/backend/utils/db_sync.py) purely so the existing TF-IDF
    classifier engine (backend/classifier/engine.py) keeps working
    completely unchanged -- that engine's CSV-parsing/caching internals
    weren't touched, to avoid risking classification-accuracy regressions
    in an untested rewrite. Postgres is authoritative; the CSV is a
    generated artifact, not something anyone edits directly anymore."""
    __tablename__ = "chart_of_accounts"

    id   = Column(Integer, primary_key=True)
    name = Column(String(300), nullable=False, unique=True, index=True)
    type = Column(String(100), nullable=True)


class KnowledgeBase(Base):
    """Replaces knowledge_base.json. Single-row JSON blob (id is always 1)
    since the existing code already treats the whole document as one
    atomic unit (loaded/saved wholesale). The JSON file is still
    regenerated on every write so backend/classifier/engine.py's
    independent file-based reader (with its own auto-reload-on-mtime-change
    logic) keeps working unchanged."""
    __tablename__ = "knowledge_base"

    id   = Column(Integer, primary_key=True)
    data = Column(JSON, nullable=False, default=dict)


class LendingClassification(Base):
    """Replaces lending_classifications.json (a flat list of keyword rules).
    Fully relational -- the lending module's reader is shallow enough that
    this is a safe, direct conversion with no bridge file needed."""
    __tablename__ = "lending_classifications"

    id         = Column(Integer, primary_key=True)
    keyword    = Column(String(300), nullable=False, index=True)
    category   = Column(String(100), nullable=True)
    exp_type   = Column(String(10), nullable=True)
    in_or_out  = Column(String(10), nullable=True)
    weight     = Column(Integer, default=0)
    source     = Column(String(50), nullable=True)


class PricingPlan(Base):
    """Replaces pricing.json. One row per plan slug ("base", "pro", etc.).

    Split into real columns (rather than one opaque JSON blob) so the
    plan is actually browsable/editable field-by-field in the Tables
    admin UI -- previously `data` held the whole payload as one JSON
    value and showed as "[object Object]" in any plain table view.

    `features` and `modules` stay as JSON columns since they're genuinely
    variable-length lists, not scalar fields -- everything else that's a
    single value in pricing.json gets its own column."""
    __tablename__ = "pricing_plans"

    slug                  = Column(String(50), primary_key=True)
    name                  = Column(String(200), nullable=True)
    description           = Column(String(1000), nullable=True)
    price_monthly         = Column(Integer, default=0)
    price_yearly          = Column(Integer, default=0)
    badge                 = Column(String(50), nullable=True)
    highlight             = Column(Boolean, default=False)
    category              = Column(String(50), nullable=True)
    features              = Column(JSON, nullable=False, default=list)
    modules               = Column(JSON, nullable=False, default=list)
    price_effective_from  = Column(String(20), nullable=True)  # kept as text ("2026-06-27") to match the JSON exactly, no date-parsing risk
    sort_order            = Column(Integer, default=0)
    updated_at            = Column(TIMESTAMP, default=datetime.utcnow, onupdate=datetime.utcnow)

    def to_dict(self) -> dict:
        """Reconstructs the exact same nested-dict shape every consumer
        (react_api.py, payments.py) already expects -- callers don't need
        to change just because storage moved from one JSON blob to real
        columns."""
        return {
            "name": self.name,
            "description": self.description,
            "price_monthly": self.price_monthly,
            "price_yearly": self.price_yearly,
            "badge": self.badge,
            "highlight": self.highlight,
            "category": self.category,
            "features": self.features or [],
            "modules": self.modules or [],
            "price_effective_from": self.price_effective_from,
        }


class ClassifierCache(Base):
    """Replaces ollama_cache.json (classify_category.py's disk cache of
    already-classified transaction descriptions). Same key-value shape as
    the old JSON blob (cache_key -> {category, gst_category}), just as
    rows instead of one giant dict, so repeated re-classification of the
    same description across runs/users is skipped."""
    __tablename__ = "classifier_cache"

    cache_key    = Column(String(64), primary_key=True)
    category     = Column(String(100), nullable=True)
    gst_category = Column(String(100), nullable=True)
    updated_at   = Column(TIMESTAMP, default=datetime.utcnow, onupdate=datetime.utcnow)


class TradingCostBase(Base):
    """Replaces main_app/backend/trading/data/local_cost_base_db.json.
    Single-row JSON blob, mirrored from the file after every write by
    local_cost_base_db.py -- that module's FIFO capital-gains-tax lot
    matching and duplicate-detection logic was left completely untouched
    (it has its own backup/versioning safety net already), so Postgres
    here is a synced mirror for File Manager visibility rather than a
    from-scratch rewrite of tax-sensitive logic."""
    __tablename__ = "trading_cost_base"

    id   = Column(Integer, primary_key=True)
    data = Column(JSON, nullable=False, default=dict)
