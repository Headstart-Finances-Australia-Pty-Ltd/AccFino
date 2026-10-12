"""Shared SQLAlchemy column types (money / rates), used by Core and every domain module."""
from sqlalchemy import Numeric

MONEY = Numeric(18, 2)
RATE = Numeric(9, 6)
FXRATE = Numeric(18, 8)       # exchange rates: 1 unit of foreign currency = N units of the base currency
