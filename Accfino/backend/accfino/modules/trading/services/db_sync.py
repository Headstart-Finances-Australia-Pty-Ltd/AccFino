"""
accfino.modules.trading.services.db_sync
----------------------------------------
Trading cost base: the FIFO lot-matching code owns its JSON file (with its own backup/versioning); Postgres holds a synced mirror
so the File Manager and DB views stay current. The file lives in the data root (modules/trading/cost_base/).
"""
import json

from accfino.modules.trading.models import TradingCostBase
from accfino.shared import paths
from accfino.shared.db.database import SessionLocal


def _cost_base_path():
    return paths.module_dir("trading", "cost_base") / "local_cost_base_db.json"


def sync_cost_base_json_from_db():
    """Regenerates local_cost_base_db.json from the trading_cost_base table (row id=1)."""
    db = SessionLocal()
    try:
        row = db.get(TradingCostBase, 1)
        data = row.data if row else {"version": "1.0", "historical_lots": [], "resolution_log": []}
        _cost_base_path().write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    finally:
        db.close()


def push_cost_base_json_to_db():
    """The reverse direction: after local_cost_base_db writes its file, mirror the new state into Postgres."""
    db = SessionLocal()
    try:
        path = _cost_base_path()
        if not path.exists():
            return
        data = json.loads(path.read_text(encoding="utf-8"))
        row = db.get(TradingCostBase, 1)
        if row:
            row.data = data
        else:
            db.add(TradingCostBase(id=1, data=data))
        db.commit()
    finally:
        db.close()
