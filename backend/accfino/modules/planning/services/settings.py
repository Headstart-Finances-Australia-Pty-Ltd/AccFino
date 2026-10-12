"""Planning settings (minimum cash threshold, horizon, collection assumptions). Changing them is audited."""
from accfino.modules.planning.engine.money import D, q2
from . import core


def get(db, ctx, a) -> dict:
    a.require("view")
    return core.settings_dict(core.settings(db, ctx))


def save(db, ctx, a, body: dict) -> dict:
    a.require("config")
    st = core.settings(db, ctx)
    before = core.settings_dict(st)
    try:
        if "min_cash_threshold" in body:
            v = q2(D(body["min_cash_threshold"]))
            if v < 0 or v > 10**12:
                raise core.PlanError("min_cash_threshold must be zero or more")
            st.min_cash_threshold = v
        for k, lo, hi in (("horizon_weeks", 4, 52), ("overdue_collection_pct", 0, 100), ("overdue_collection_days", 0, 180), ("stale_days", 1, 90), ("recurring_weight_pct", 0, 100)):
            if k in body:
                v = int(D(body[k]))
                if not lo <= v <= hi:
                    raise core.PlanError(f"{k} must be between {lo} and {hi}")
                setattr(st, k, v)
    except ValueError:
        raise core.PlanError("Settings must be numbers")
    st.updated_by = ctx.user_id
    core.audit(db, ctx, "settings.save", "plan_settings", ctx.org.id, before=before, after=core.settings_dict(st))
    return core.settings_dict(st)
