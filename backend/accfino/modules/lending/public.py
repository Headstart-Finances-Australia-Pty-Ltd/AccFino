"""Public surface of the Lending module (read-only): the ONLY import path other modules may use."""
from datetime import date
from decimal import Decimal
from typing import List


def treasury_flows(db, ctx, start: date, end: date) -> List[dict]:
    """Treasury cash flows the organisation is committed to or expects, from `start` to `end`, WITHOUT bills and invoices (Accounting owns those):
    [{date, amount (Decimal, inflow +, outflow -), kind: committed|forecast, label, source: facility|loan|forecast}].
    Facility and ledger-linked loan repayments are committed; Treasury forecast items are expectations. No role check here: the caller (Planning) checks its own permission."""
    from accfino.modules.lending import lend_models as M
    from accfino.modules.lending.svc import treasury as TR
    flows = []
    for f in db.query(M.LendFacility).filter_by(org_id=ctx.org.id).order_by(M.LendFacility.id):
        flows += TR._facility_repayments(f, start, end)
    flows += TR._own_loan_flows(db, ctx, start, end)
    for i in db.query(M.LendForecastItem).filter(M.LendForecastItem.org_id == ctx.org.id, M.LendForecastItem.status == "expected",
                                                  M.LendForecastItem.item_date >= start, M.LendForecastItem.item_date <= end):
        flows.append(dict(date=i.item_date, amount=Decimal(i.amount), kind="forecast", label=i.description, source="forecast"))
    return sorted(flows, key=lambda f: (f["date"], f["label"]))
