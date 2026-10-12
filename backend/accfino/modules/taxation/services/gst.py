"""GST adjustments register. Not invoice lines (those come from the ledger): bad debts, change of extent, private use, goods returned and similar. CONFIRMED adjustments inside a BAS period
feed that statement (increasing -> 1A, decreasing -> 1B); drafts and voided ones never do. Edits are refused for periods whose statement is approved or lodged."""
from datetime import date
from decimal import Decimal
from typing import Optional

from accfino.modules.taxation.engine.money import ZERO, D, q2
from accfino.modules.taxation.models import tax as T
from accfino.modules.taxation.services import core
from accfino.modules.taxation.services.core import Conflict, NotFound, TaxError

REASON_LABEL = {"bad_debt": "Bad debt written off", "change_of_extent": "Change in extent of creditable purpose", "private_use": "Private or non-business use", "goods_returned": "Goods returned / supply cancelled",
                "price_change": "Price change after the invoice", "cancelled_supply": "Cancelled supply", "annual_apportionment": "Annual apportionment", "other": "Other (explain in the description)"}


def a_dict(x: T.TaxGstAdjustment) -> dict:
    return dict(id=x.id, adj_date=x.adj_date.isoformat(), adj_type=x.adj_type, reason=x.reason, reason_label=REASON_LABEL.get(x.reason, x.reason), description=x.description, amount_ex_gst=str(x.amount_ex_gst),
                gst_amount=str(x.gst_amount), reference=x.reference, status=x.status, source=x.source, created_at=core.plain(x.created_at))


def _locked(db, ctx, d: date, ignore_id: Optional[int] = None):
    s = db.query(T.TaxBasStatement).filter(T.TaxBasStatement.org_id == ctx.org.id, T.TaxBasStatement.status.in_(("approved", "lodged", "paid")),
                                           T.TaxBasStatement.period_start <= d, T.TaxBasStatement.period_end >= d).first()
    if s:
        raise Conflict(f"The {s.kind.upper()} for {s.period_start} to {s.period_end} is {s.status}: return it to draft before changing GST adjustments in that period.", "locked")


def clean(body: dict) -> dict:
    """Validation shared by the form and the CSV importer. Raises TaxError with a message a person can act on."""
    d = core.parse_date(body.get("adj_date"), "adj_date")
    if d is None:
        raise TaxError("adj_date is required")
    if d.year < 2000 or d > date.today().replace(year=date.today().year + 1):
        raise TaxError("adj_date is outside a sensible range")
    t = body.get("adj_type")
    if t not in T.GST_ADJ_TYPES:
        raise TaxError(f"adj_type must be one of {', '.join(T.GST_ADJ_TYPES)}")
    reason = body.get("reason") or "other"
    if reason not in T.GST_ADJ_REASONS:
        raise TaxError(f"reason must be one of {', '.join(T.GST_ADJ_REASONS)}")
    desc = (body.get("description") or "").strip()
    if not desc:
        raise TaxError("description is required")
    gst = core.money_in(body.get("gst_amount"), "gst_amount", required=True)
    ex = core.money_in(body.get("amount_ex_gst"), "amount_ex_gst") or ZERO
    if gst <= 0:
        raise TaxError("gst_amount must be greater than zero")
    if ex > 0 and gst > q2(ex * Decimal("0.10")) + Decimal("0.05"):
        raise TaxError(f"gst_amount ({gst}) is more than 10% of amount_ex_gst ({ex}): GST cannot exceed 1/11 of the GST-inclusive amount")
    status = body.get("status") or "confirmed"
    if status not in T.GST_ADJ_STATUSES:
        raise TaxError(f"status must be one of {', '.join(T.GST_ADJ_STATUSES)}")
    return dict(adj_date=d, adj_type=t, reason=reason, description=desc[:300], amount_ex_gst=ex, gst_amount=gst, reference=(body.get("reference") or "").strip()[:80] or None, status=status)


def warnings_for(c: dict) -> list:
    w = []
    if c["amount_ex_gst"] > 0 and c["gst_amount"] < q2(c["amount_ex_gst"] * Decimal("0.10")) - Decimal("0.05"):
        w.append("GST is less than 10% of the amount: confirm this is a partial claim or a GST-free component")
    if c["amount_ex_gst"] == 0:
        w.append("No amount excluding GST was given")
    if c["reason"] == "other":
        w.append("Reason 'other': the description must explain the adjustment")
    return w


def save(db, ctx, a: core.Access, body: dict, aid: Optional[int] = None, source: str = "manual") -> T.TaxGstAdjustment:
    a.require("prepare")
    c = clean(body)
    if aid:
        x = db.query(T.TaxGstAdjustment).filter_by(org_id=ctx.org.id, id=aid).first()
        if x is None:
            raise NotFound("GST adjustment")
        _locked(db, ctx, x.adj_date)
    else:
        x = T.TaxGstAdjustment(org_id=ctx.org.id, created_by=ctx.user_id, source=source)
    _locked(db, ctx, c["adj_date"])
    before = a_dict(x) if aid else None
    for k, v in c.items():
        setattr(x, k, v)
    if not aid:
        db.add(x)
    db.flush()
    core.record(db, ctx, "gst.adjustment.save", "tax_gst_adjustment", x.id, f"GST adjustment {x.adj_type} {x.gst_amount} on {x.adj_date} ({x.status})", before, a_dict(x))
    return x


def set_status(db, ctx, a: core.Access, aid: int, status: str):
    a.require("prepare")
    x = db.query(T.TaxGstAdjustment).filter_by(org_id=ctx.org.id, id=aid).first()
    if x is None:
        raise NotFound("GST adjustment")
    if status not in T.GST_ADJ_STATUSES:
        raise TaxError(f"status must be one of {', '.join(T.GST_ADJ_STATUSES)}")
    _locked(db, ctx, x.adj_date)
    before = x.status
    x.status = status
    core.record(db, ctx, "gst.adjustment.status", "tax_gst_adjustment", x.id, f"GST adjustment status {before} -> {status}", dict(status=before), dict(status=status))
    return x


def delete(db, ctx, a: core.Access, aid: int):
    a.require("prepare")
    x = db.query(T.TaxGstAdjustment).filter_by(org_id=ctx.org.id, id=aid).first()
    if x is None:
        raise NotFound("GST adjustment")
    _locked(db, ctx, x.adj_date)
    core.record(db, ctx, "gst.adjustment.delete", "tax_gst_adjustment", x.id, "GST adjustment deleted", a_dict(x), None)
    db.delete(x)


def listing(db, ctx, date_from=None, date_to=None, adj_type="", status="", reason="", q=""):
    qs = db.query(T.TaxGstAdjustment).filter(T.TaxGstAdjustment.org_id == ctx.org.id)
    if date_from:
        qs = qs.filter(T.TaxGstAdjustment.adj_date >= date_from)
    if date_to:
        qs = qs.filter(T.TaxGstAdjustment.adj_date <= date_to)
    for col, v in ((T.TaxGstAdjustment.adj_type, adj_type), (T.TaxGstAdjustment.status, status), (T.TaxGstAdjustment.reason, reason)):
        if v:
            qs = qs.filter(col == v)
    rows = [a_dict(x) for x in qs.order_by(T.TaxGstAdjustment.adj_date.desc(), T.TaxGstAdjustment.id.desc())]
    if q:
        t = q.strip().lower()
        rows = [r for r in rows if t in (r["description"] or "").lower() or t in (r["reference"] or "").lower()]
    return rows


def period_totals(db, ctx, start: date, end: date) -> dict:
    """What the activity statement for this period takes from the register. Only CONFIRMED adjustments count."""
    inc = dec = ZERO
    n = drafts = 0
    for x in db.query(T.TaxGstAdjustment).filter(T.TaxGstAdjustment.org_id == ctx.org.id, T.TaxGstAdjustment.adj_date.between(start, end)):
        if x.status == "draft":
            drafts += 1
        elif x.status == "confirmed":
            n += 1
            if x.adj_type == "increasing":
                inc += x.gst_amount
            else:
                dec += x.gst_amount
    return dict(increasing=str(q2(inc)), decreasing=str(q2(dec)), count=n, drafts=drafts)


def summary(db, ctx, date_from: date, date_to: date) -> dict:
    rows = listing(db, ctx, date_from, date_to)
    out = dict(period_start=date_from.isoformat(), period_end=date_to.isoformat(), count=len(rows), by_status={}, by_reason={}, increasing_confirmed=ZERO, decreasing_confirmed=ZERO)
    for r in rows:
        out["by_status"][r["status"]] = out["by_status"].get(r["status"], 0) + 1
        out["by_reason"][r["reason"]] = out["by_reason"].get(r["reason"], 0) + 1
        if r["status"] == "confirmed":
            k = "increasing_confirmed" if r["adj_type"] == "increasing" else "decreasing_confirmed"
            out[k] += D(r["gst_amount"])
    out["increasing_confirmed"], out["decreasing_confirmed"] = str(q2(out["increasing_confirmed"])), str(q2(out["decreasing_confirmed"]))
    out["net_effect_on_label_9"] = str(q2(D(out["increasing_confirmed"]) - D(out["decreasing_confirmed"])))
    return out
