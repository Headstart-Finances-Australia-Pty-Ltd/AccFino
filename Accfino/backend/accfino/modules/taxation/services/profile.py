"""Tax profile (entity, GST/BAS/PAYG/FBT settings), rule overrides and the effective-rates view."""
from datetime import date, datetime
from typing import Optional

from accfino.modules.taxation.engine import rules as R
from accfino.modules.taxation.models import tax as T
from accfino.modules.taxation.services import core
from accfino.modules.taxation.services.core import TaxError

FIELDS = ("entity_type", "residency", "abn", "gst_registered", "gst_basis", "bas_frequency", "payg_withholding", "payg_instalment_method", "payg_instalment_amount",
          "payg_instalment_rate", "fbt_registered", "fbt_instalment_amount", "tpar_required", "aggregated_turnover", "aggregated_turnover_basis", "passive_income_ratio",
          "simplified_depreciation", "pool_opening_balance", "state", "uses_agent_program", "has_tax_agent", "tax_agent_name", "tax_agent_number", "asic_review_date",
          "extra_holidays", "allow_self_approval", "lodgement_policy", "notes")
STATES = ("NSW", "VIC", "QLD", "WA", "SA", "TAS", "ACT", "NT")
ORG_ENTITY = {"company": "company", "trust": "trust", "partnership": "partnership", "sole_trader": "sole_trader", "smsf": "smsf"}


def get(db, ctx) -> T.TaxProfile:
    """The organisation's profile, created on first use from what the organisation record already knows (ABN, entity type, GST settings)."""
    p = db.get(T.TaxProfile, ctx.org.id)
    if p is None:
        o = ctx.org
        p = T.TaxProfile(org_id=o.id, entity_type=ORG_ENTITY.get(o.entity_type or "", "company"), abn=o.abn, gst_registered=bool(o.gst_registered),
                         gst_basis=o.gst_basis or "accrual", bas_frequency="quarterly" if o.gst_registered else "quarterly")
        db.add(p)
        db.flush()
    return p


def to_dict(p: T.TaxProfile) -> dict:
    out = {k: core.plain(getattr(p, k)) for k in FIELDS}
    out["updated_at"] = core.plain(p.updated_at)
    out["is_small_business_entity_hint"] = None
    return out


def is_sbe(db, ctx, p: T.TaxProfile, rs) -> Optional[bool]:
    """True/False when aggregated turnover is known, None when it is not (callers must not assume)."""
    if p.aggregated_turnover is None:
        return None
    lim = rs.dec("small_business.sbe_turnover_limit")
    return None if lim is None else p.aggregated_turnover < lim


def save(db, ctx, a: core.Access, body: dict) -> T.TaxProfile:
    a.require("config")
    p = get(db, ctx)
    before = to_dict(p)
    ENUMS = dict(lodgement_policy=T.LODGEMENT_POLICIES, entity_type=T.ENTITY_TYPES, residency=("resident", "foreign"), bas_frequency=T.BAS_FREQUENCIES, payg_instalment_method=T.INSTALMENT_METHODS, gst_basis=("accrual", "cash"))
    upd = {}
    for k in FIELDS:                                                  # validate EVERYTHING first; nothing is written (and no session rollback is needed) if any value is bad
        if k not in body:
            continue
        v = body[k]
        if k in ENUMS and v not in ENUMS[k]:
            raise TaxError(f"{k} must be one of {', '.join(ENUMS[k])}")
        if k in ("payg_instalment_amount", "fbt_instalment_amount", "aggregated_turnover", "pool_opening_balance"):
            v = core.money_in(v, k)
        elif k == "payg_instalment_rate":
            v = core.money_in(v, k)
            if v is not None and v > 100:
                raise TaxError("payg_instalment_rate is a percentage between 0 and 100")
        elif k == "passive_income_ratio":
            v = core.money_in(v, k)
            if v is not None and v > 1:
                raise TaxError("passive_income_ratio is a ratio between 0 and 1")
        elif k == "state" and v not in (None, "") and v not in STATES:
            raise TaxError(f"state must be one of {', '.join(STATES)}")
        elif k == "asic_review_date" and v not in (None, ""):
            try:
                datetime.strptime("2000-" + v, "%Y-%m-%d")
            except ValueError:
                raise TaxError("asic_review_date must be MM-DD")
        elif k == "extra_holidays":
            v = [str(core.parse_date(x, "extra_holidays")) for x in (v or [])]
        elif k in ("gst_registered", "payg_withholding", "fbt_registered", "tpar_required", "simplified_depreciation", "uses_agent_program", "has_tax_agent", "allow_self_approval"):
            v = bool(v)
        upd[k] = v
    for k, v in upd.items():
        setattr(p, k, v)
    db.flush()
    after = to_dict(p)
    diff_b = {k: before[k] for k in FIELDS if before.get(k) != after.get(k)}
    diff_a = {k: after[k] for k in FIELDS if before.get(k) != after.get(k)}
    if diff_a:
        core.record(db, ctx, "profile.update", "tax_profile", ctx.org.id, "Tax profile changed: " + ", ".join(sorted(diff_a)), diff_b, diff_a)
        if "allow_self_approval" in diff_a:
            core.record(db, ctx, "profile.self_approval", "tax_profile", ctx.org.id, f"Self-approval {'ENABLED' if diff_a['allow_self_approval'] else 'disabled'}", None, None)
    return p


# ---- rules & overrides ---------------------------------------------------------------------------------------------------
def effective_rules(db, ctx, fy: str) -> dict:
    core.check_fy(ctx, fy)
    rs = core.rules_for_fy(db, ctx, fy)
    return dict(rule_set=rs.summary(), rows=rs.flat(), overrides=[dict(path=o.path, value=o.value, reason=o.reason, set_at=core.plain(o.set_at), set_by=o.set_by)
                                                                 for o in db.query(T.TaxRuleOverride).filter_by(org_id=ctx.org.id, rule_set_id=rs.id).order_by(T.TaxRuleOverride.path)],
                verification_summary=_verification_summary(rs.flat()))


def _verification_summary(rows) -> dict:
    out = {}
    for r in rows:
        out[r["verification"]] = out.get(r["verification"], 0) + 1
    return out


def set_override(db, ctx, a: core.Access, fy: str, path: str, value, reason: str) -> dict:
    a.require("config")
    if not reason or len(reason.strip()) < 5:
        raise TaxError("A reason (at least 5 characters, e.g. the ATO page or ruling) is required for every override")
    base = R.rulebook().for_fy(core.check_fy(ctx, fy), ctx.org.fy_end_month or 6)
    try:
        base.with_overrides({path: value})                               # validates the path
    except R.RulesError as e:
        raise TaxError(str(e))
    if isinstance(value, str) and value.strip() == "":
        value = None
    row = db.query(T.TaxRuleOverride).filter_by(org_id=ctx.org.id, rule_set_id=base.id, path=path).first()
    before = row.value if row else base.get(path)
    if row is None:
        row = T.TaxRuleOverride(org_id=ctx.org.id, rule_set_id=base.id, path=path)
        db.add(row)
    row.value, row.reason, row.set_by, row.set_at = value, reason.strip(), ctx.user_id, datetime.utcnow()
    db.flush()
    core.record(db, ctx, "rules.override", "tax_rule", f"{base.id}:{path}", f"Override of {path}: {before!r} -> {value!r} ({reason.strip()[:120]})", dict(value=before), dict(value=value))
    return dict(path=path, value=value, reason=row.reason)


def clear_override(db, ctx, a: core.Access, fy: str, path: str):
    a.require("config")
    base = R.rulebook().for_fy(core.check_fy(ctx, fy), ctx.org.fy_end_month or 6)
    row = db.query(T.TaxRuleOverride).filter_by(org_id=ctx.org.id, rule_set_id=base.id, path=path).first()
    if row is None:
        raise core.NotFound("Override")
    core.record(db, ctx, "rules.override_removed", "tax_rule", f"{base.id}:{path}", f"Override of {path} removed", dict(value=row.value), None)
    db.delete(row)
    db.flush()
