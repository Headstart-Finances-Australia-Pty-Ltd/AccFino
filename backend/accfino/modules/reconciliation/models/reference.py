"""Reconciliation reference data tables: chart of accounts (classifier), knowledge base, LLM classifier cache."""
from datetime import datetime

from sqlalchemy import Column, Integer, String, Float, Boolean, JSON, TIMESTAMP

from accfino.shared.db.base import Base


class ChartOfAccount(Base):
    """Replaces ChartOfAccounts.csv as the source of truth. The CSV file is
    still regenerated on every write (see sync_coa_csv_from_db in
    accfino/modules/reconciliation/services/db_sync.py) purely so the existing TF-IDF
    classifier engine (accfino/modules/reconciliation/classification/engine.py) keeps working
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
    regenerated on every write so accfino/modules/reconciliation/classification/engine.py's
    independent file-based reader (with its own auto-reload-on-mtime-change
    logic) keeps working unchanged."""
    __tablename__ = "knowledge_base"

    id   = Column(Integer, primary_key=True)
    data = Column(JSON, nullable=False, default=dict)


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
