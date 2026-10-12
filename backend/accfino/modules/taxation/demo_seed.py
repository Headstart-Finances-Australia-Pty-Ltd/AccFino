"""Demo / training data for Taxation & Compliance. Idempotent: running it twice adds nothing. It creates a tax profile, registrations, the year's due dates, a couple of
manual adjustments (one an unreviewed estimate), a CGT event and loss, an FBT benefit, a Division 7A loan and a workpaper. It does NOT post ledger journals (the Accounting
demo data does that); it never creates a lodged or approved document, so a trainee walks the workflow themselves. Intended for demonstration organisations only."""
from datetime import date

from accfino.modules.taxation.models import tax as T
from accfino.modules.taxation.services import cgt, core, div7a, fbt, obligations, profile, returns, workpapers


def seed(db, ctx, fy: str = "2026-27") -> dict:
    a = core.Access(db, ctx)
    made = {}
    p = profile.get(db, ctx)
    if p.aggregated_turnover is None:
        profile.save(db, ctx, a, dict(aggregated_turnover="850000", passive_income_ratio="0.05", bas_frequency="quarterly", fbt_registered=True, state="NSW", allow_self_approval=False))
        made["profile"] = 1
    if not db.query(T.TaxRegistration).filter_by(org_id=ctx.org.id).count():
        for kind, ident in (("abn", ctx.org.abn), ("gst", ctx.org.abn), ("payg_withholding", ""), ("fbt", "")):
            obligations.save_registration(db, ctx, a, dict(kind=kind, identifier=ident or "", registered_on=f"{fy[:4]}-07-01"))
        made["registrations"] = 4
    if not db.query(T.TaxAdjustment).filter_by(org_id=ctx.org.id, fy=fy, source="manual").count():
        returns.save_adjustment(db, ctx, a, fy, dict(code="ENTERTAINMENT", direction="add", amount="1800", description="Client entertainment (non-deductible)"))
        returns.save_adjustment(db, ctx, a, fy, dict(code="DONATIONS", direction="deduct", amount="500", description="Donations to DGR (estimate: receipts outstanding)", category="estimate"))
        made["adjustments"] = 2
    if not db.query(T.TaxCgtEvent).filter_by(org_id=ctx.org.id).count():
        cgt.save_event(db, ctx, a, dict(asset_name="Demo Shares Ltd", asset_class="shares", acquire_date=f"{int(fy[:4]) - 2}-03-01", dispose_date=f"{fy[:4]}-09-15", proceeds="12000", acquisition_cost="8000"))
        cgt.add_loss(db, ctx, a, f"{int(fy[:4]) - 1}-{fy[:4][-2:]}", "1000", "Demo capital loss brought forward")
        made["cgt"] = 1
    if not db.query(T.TaxFbtBenefit).filter_by(org_id=ctx.org.id).count():
        fbt.save_benefit(db, ctx, a, f"FBT{int(fy[:4]) + 1}", dict(benefit_type="car", employee="Demo Employee", description="Company car", inputs=dict(base_value="45000", days_available="365")))
        made["fbt"] = 1
    if not db.query(T.TaxDiv7aLoan).filter_by(org_id=ctx.org.id).count():
        div7a.save_loan(db, ctx, a, dict(borrower="Demo Director", advance_date=f"{int(fy[:4]) - 1}-08-01", principal="60000", term_years=7, agreement_date=f"{int(fy[:4]) - 1}-08-01"))
        made["div7a"] = 1
    if not db.query(T.TaxWorkpaper).filter_by(org_id=ctx.org.id).count():
        workpapers.save(db, ctx, a, dict(area="general", fy=fy, title="Year-end tax checklist", reference="WP-DEMO",
                                         content=dict(lines=[dict(label="Reconcile suspense account to nil", kind="review"), dict(label="Confirm super paid by due date", kind="review")], conclusion="")))
        made["workpapers"] = 1
    made["obligations"] = obligations.generate(db, ctx, a, fy)["created"]          # last: the loan and benefits above change which obligations apply
    return made
