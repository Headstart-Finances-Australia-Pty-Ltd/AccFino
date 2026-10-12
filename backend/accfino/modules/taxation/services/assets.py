"""Tax depreciation review of the Fixed Assets register for small business entities (instant asset write-off + simplified pool), producing book-to-tax adjustments."""
from datetime import date

import accfino.modules.accounting.public as accounting
from accfino.modules.taxation.engine import assets_tax as E, rules as R
from accfino.modules.taxation.models import tax as T
from accfino.modules.taxation.services import core, profile as P

SOURCE_KEY = "assets_review"


def review(db, ctx, fy: str) -> dict:
    core.check_fy(ctx, fy)
    start, end = R.fy_bounds(fy, ctx.org.fy_end_month or 6)
    p = P.get(db, ctx)
    rs = core.rules_for_fy(db, ctx, fy)
    sbe = P.is_sbe(db, ctx, p, rs)
    assets = accounting.fixed_assets_for_tax(db, ctx.org.id, start, end)
    res = E.review(rs, assets, fy_start=start, fy_end=end, is_sbe=bool(sbe), gst_registered=p.gst_registered, pool_opening=p.pool_opening_balance or 0, use_simplified=p.simplified_depreciation)
    if sbe is None:
        res["warnings"].insert(0, "Aggregated turnover is not entered in the tax profile, so small business entity status is unknown. Enter it to compute the instant asset write-off and pool.")
    res.update(fy=fy, rule_set=rs.id, sbe=sbe)
    return res


def generate_adjustments(db, ctx, a: core.Access, fy: str) -> dict:
    """Replace the generated depreciation adjustments for the year: add back book depreciation, deduct tax depreciation. Both flagged for review."""
    a.require("prepare")
    res = review(db, ctx, fy)
    r = db.query(T.TaxReturn).filter(T.TaxReturn.org_id == ctx.org.id, T.TaxReturn.fy == fy, T.TaxReturn.status.in_(("approved", "lodged", "paid"))).first()
    if r:
        raise core.Conflict(f"The {fy} return is {r.status}; return it to draft before regenerating adjustments.", "locked")
    if not res["computed"]:
        raise core.TaxError("Tax depreciation could not be computed (not a small business entity or turnover unknown), so no adjustments were generated. Enter adjustments manually.")
    db.query(T.TaxAdjustment).filter_by(org_id=ctx.org.id, fy=fy, source=SOURCE_KEY).delete()
    made = []
    from accfino.modules.taxation.engine.money import D
    book, tax = D(res["book_depreciation"]), D(res["tax_depreciation"])
    for code, desc, direction, amt in (("BOOK_DEPRECIATION", "Add back book depreciation (accounts)", "add", book), ("TAX_DEPRECIATION", "Deduct tax depreciation (instant asset write-off + small business pool)", "deduct", tax)):
        if amt > 0:
            row = T.TaxAdjustment(org_id=ctx.org.id, fy=fy, code=code, description=desc, direction=direction, amount=amt, category="calculated", source=SOURCE_KEY, source_key=f"{SOURCE_KEY}:{code}",
                                  requires_review=True, review_note="Generated from the Fixed Assets register. Confirm asset eligibility, business-use % and the pool opening balance.", created_by=ctx.user_id)
            db.add(row)
            made.append(code)
    db.flush()
    core.record(db, ctx, "assets.adjustments", "tax_adjustment", None, f"Depreciation adjustments regenerated for {fy}: add back {book}, deduct {tax}", None, dict(book=str(book), tax=str(tax)))
    return dict(fy=fy, generated=made, book=str(book), tax=str(tax))
