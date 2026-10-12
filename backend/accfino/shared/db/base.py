from sqlalchemy.ext.declarative import declarative_base

Base = declarative_base()

# ---- exact decimal storage for money-like values that legacy code still handles as Python floats ----------------
# (asdecimal=False keeps the existing arithmetic working; the DATABASE stores exact NUMERIC, rounded at the boundary.)
from sqlalchemy import Numeric as _Numeric

MoneyF = _Numeric(18, 2, asdecimal=False)      # amounts
UnitF = _Numeric(18, 4, asdecimal=False)       # unit prices / hourly rates (Xero-style 4 dp)
QtyF = _Numeric(18, 4, asdecimal=False)        # quantities
PctF = _Numeric(9, 4, asdecimal=False)         # percentages
HoursF = _Numeric(9, 2, asdecimal=False)       # timesheet hours
FxF = _Numeric(18, 8, asdecimal=False)         # exchange rates
