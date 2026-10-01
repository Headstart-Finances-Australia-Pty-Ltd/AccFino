"""
main_app/backend/utils/db_sync.py
-----------------------------------------------------------------------------
Postgres is now authoritative for Chart of Accounts, Knowledge Base, and the
trading module's local cost-base cache. These three each have a legacy
flat-file reader whose internals were deliberately left untouched (the
TF-IDF classifier engine, and the FIFO capital-gains-tax lot-matching logic)
-- both are the kind of thing you don't want to blind-rewrite without being
able to fully test the result.

Instead, call the relevant sync_*_from_db() function here after every write
to the corresponding table, and the legacy file gets regenerated to match.
The file becomes a derived, read-only cache from the app's point of view --
nobody edits it by hand anymore, and if it's ever deleted, the next sync
call recreates it from Postgres.
"""
import json
import csv
from pathlib import Path

from db_app.database import SessionLocal
from db_app.models.app_data import ChartOfAccount, KnowledgeBase, TradingCostBase

_ROOT = Path(__file__).resolve().parents[3]  # AccFino-main/
_COA_PATH = _ROOT / "main_app" / "data" / "ChartOfAccounts.csv"
_KB_PATH = _ROOT / "main_app" / "data" / "knowledge_base.json"
_COST_BASE_PATH = _ROOT / "main_app" / "backend" / "trading" / "data" / "local_cost_base_db.json"


def sync_coa_csv_from_db():
    """Regenerates ChartOfAccounts.csv from the chart_of_accounts table."""
    db = SessionLocal()
    try:
        rows = db.query(ChartOfAccount).order_by(ChartOfAccount.name).all()
        _COA_PATH.parent.mkdir(parents=True, exist_ok=True)
        with open(_COA_PATH, "w", newline="", encoding="utf-8-sig") as f:
            writer = csv.writer(f)
            writer.writerow(["*Name", "*Type"])
            for r in rows:
                writer.writerow([r.name, r.type or ""])
    finally:
        db.close()


def sync_kb_json_from_db():
    """Regenerates knowledge_base.json from the knowledge_base table (row id=1)."""
    db = SessionLocal()
    try:
        row = db.get(KnowledgeBase, 1)
        data = row.data if row else {}
        _KB_PATH.parent.mkdir(parents=True, exist_ok=True)
        _KB_PATH.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    finally:
        db.close()


def sync_cost_base_json_from_db():
    """Regenerates local_cost_base_db.json from the trading_cost_base table (row id=1)."""
    db = SessionLocal()
    try:
        row = db.get(TradingCostBase, 1)
        data = row.data if row else {"version": "1.0", "historical_lots": [], "resolution_log": []}
        _COST_BASE_PATH.parent.mkdir(parents=True, exist_ok=True)
        _COST_BASE_PATH.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    finally:
        db.close()


def push_cost_base_json_to_db():
    """The reverse direction -- local_cost_base_db.py still owns writes to
    its own file (backup/versioning logic untouched); call this after it
    writes, to mirror the new state back into Postgres so File Manager and
    every other DB-based view of the data stays current."""
    db = SessionLocal()
    try:
        if not _COST_BASE_PATH.exists():
            return
        data = json.loads(_COST_BASE_PATH.read_text(encoding="utf-8"))
        row = db.get(TradingCostBase, 1)
        if row:
            row.data = data
        else:
            db.add(TradingCostBase(id=1, data=data))
        db.commit()
    finally:
        db.close()
