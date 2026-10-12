"""Taxation facade for other modules. Other modules must not import taxation internals: they call these functions."""


def record_cgt_events(db, ctx, events, dry_run: bool = False) -> dict:
    """Add CGT events from another module (Investments). `events`: dicts with asset_class, asset_name, quantity, acquire_date, dispose_date, proceeds, acquisition_cost, incidental_costs,
    capital_improvements, disposal_costs, main_residence_exempt, notes and a stable source_ref. Events whose source_ref already exists for this organisation are skipped, so sending twice is safe;
    an event in a locked period or with invalid data is reported, never half-saved. Needs the tax 'prepare' permission. dry_run validates and saves nothing."""
    from accfino.modules.taxation.models import tax as T
    from accfino.modules.taxation.services import cgt, core
    a = core.Access(db, ctx)
    a.require("prepare")
    have = {r[0] for r in db.query(T.TaxCgtEvent.source_ref).filter(T.TaxCgtEvent.org_id == ctx.org.id, T.TaxCgtEvent.source == "investments")}
    out = dict(added=0, skipped_duplicates=0, rejected=0, errors=[], dry_run=dry_run)
    for i, ev in enumerate(events, start=1):
        ref = ev.get("source_ref")
        if ref and ref in have:
            out["skipped_duplicates"] += 1
            continue
        sp = db.begin_nested()
        try:
            cgt.save_event(db, ctx, a, dict(ev, source="investments"))
            if dry_run:
                sp.rollback()
            else:
                sp.commit()
                have.add(ref)
            out["added"] += 1
        except core.TaxError as e:
            sp.rollback()
            out["rejected"] += 1
            out["errors"].append(dict(row=i, source_ref=ref, error=e.message))
    return out


def upcoming_obligations(db, ctx, start, end):
    """Unlodged/unpaid tax obligations due between two dates (read-only, no role check - the caller checks its own permission):
    [{id, kind, title, due_date (date), period_start, period_end, status, amount (Decimal|None: payable +, refundable -)}]."""
    from accfino.modules.taxation.models import tax as T
    q = db.query(T.TaxObligation).filter(T.TaxObligation.org_id == ctx.org.id, T.TaxObligation.due_date >= start, T.TaxObligation.due_date <= end,
                                         T.TaxObligation.paid_on.is_(None), T.TaxObligation.status.notin_(("paid", "completed", "not_required")))
    return [dict(id=o.id, kind=o.kind, title=o.title, due_date=o.due_date, period_start=o.period_start, period_end=o.period_end, status=o.status, amount=o.amount)
            for o in q.order_by(T.TaxObligation.due_date, T.TaxObligation.id)]
