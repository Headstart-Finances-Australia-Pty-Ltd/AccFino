"""Trading data model: the capital-gains cost-base mirror."""
from datetime import datetime

from sqlalchemy import Column, Integer, String, Float, Boolean, JSON, TIMESTAMP

from accfino.shared.db.base import Base


class TradingCostBase(Base):
    """Replaces the trading cost-base file (ACCFINO_DATA_ROOT/modules/trading/cost_base/local_cost_base_db.json).
    Single-row JSON blob, mirrored from the file after every write by
    accfino/modules/trading/common/local_cost_base_db.py -- that module's FIFO capital-gains-tax lot
    matching and duplicate-detection logic was left completely untouched
    (it has its own backup/versioning safety net already), so Postgres
    here is a synced mirror for File Manager visibility rather than a
    from-scratch rewrite of tax-sensitive logic."""
    __tablename__ = "trading_cost_base"

    id   = Column(Integer, primary_key=True)
    data = Column(JSON, nullable=False, default=dict)
