"""
accfino.modules.planning.models.plan
------------------------------------
Planning & Intelligence tables (prefix plan_). Every row belongs to an organisation (org_id). The ledger stays the only source of financial truth:
these tables hold only what the ledger cannot - settings, budget workflow state, stored forecast/scenario/report snapshots, alerts and the assistant log.
Budget AMOUNTS stay in Accounting's org_budget_lines (reused); plan_budgets adds ownership, versions and approval state around them.
"""
from datetime import datetime

from sqlalchemy import JSON, Boolean, CheckConstraint, Column, Date, DateTime, ForeignKey, Index, Integer, String, Text, UniqueConstraint

from accfino.shared.db.base import Base
from accfino.shared.db.types import MONEY

_ORG = lambda: Column(Integer, ForeignKey("organisations.id", ondelete="CASCADE"), nullable=False, index=True)


def _in(col, values):
    return f"{col} IN ({', '.join(repr(v) for v in values)})"


BUDGET_STATUSES = ("draft", "submitted", "approved", "archived")
SCENARIO_KINDS = ("base", "optimistic", "downside", "custom")
SCENARIO_STATUSES = ("active", "archived")
ALERT_STATUSES = ("new", "acknowledged", "dismissed", "resolved")
SEVERITIES = ("low", "medium", "high")
REPORT_KINDS = ("board_pack", "profit_loss", "balance_sheet", "cash", "budget_vs_actual", "ageing", "working_capital", "kpis", "forecast_vs_actual", "scenario_comparison")


class PlanSetting(Base):
    __tablename__ = "plan_settings"
    org_id = Column(Integer, ForeignKey("organisations.id", ondelete="CASCADE"), primary_key=True)
    min_cash_threshold = Column(MONEY, nullable=False, default=0)
    horizon_weeks = Column(Integer, nullable=False, default=13)
    overdue_collection_pct = Column(Integer, nullable=False, default=80)          # share of an overdue receivable expected to be collected
    overdue_collection_days = Column(Integer, nullable=False, default=14)         # ...within this many days of the as-at date
    stale_days = Column(Integer, nullable=False, default=7)                       # ledger/bank data older than this is flagged stale
    recurring_weight_pct = Column(Integer, nullable=False, default=100)           # confidence applied to expected (not yet invoiced) recurring sales/purchases
    insight_cfg = Column(JSON, nullable=True)
    risk_cfg = Column(JSON, nullable=True)
    benchmarks = Column(JSON, nullable=True)                                      # only entries with a cited source are ever stored
    updated_by = Column(Integer, nullable=True)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class PlanBudget(Base):
    """Workflow wrapper for one named budget whose monthly lines live in org_budget_lines (scenario == name)."""
    __tablename__ = "plan_budgets"
    id = Column(Integer, primary_key=True)
    org_id = _ORG()
    name = Column(String(40), nullable=False)
    fy_start = Column(Date, nullable=False)
    interval = Column(String(10), nullable=False, default="monthly")
    status = Column(String(10), nullable=False, default="draft")
    version = Column(Integer, nullable=False, default=1)
    parent_id = Column(Integer, nullable=True)
    owner_id = Column(Integer, nullable=True)
    owner_name = Column(String(100), nullable=True)
    notes = Column(Text, nullable=True)
    submitted_by = Column(Integer, nullable=True)
    submitted_at = Column(DateTime, nullable=True)
    approved_by = Column(Integer, nullable=True)
    approved_at = Column(DateTime, nullable=True)
    created_by = Column(Integer, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    __table_args__ = (UniqueConstraint("org_id", "name", name="uq_plan_budget_name"), CheckConstraint(_in("status", BUDGET_STATUSES), name="ck_plan_budget_status"),
                      CheckConstraint("interval IN ('monthly','quarterly','annual')", name="ck_plan_budget_interval"))


class PlanForecastSnapshot(Base):
    __tablename__ = "plan_forecast_snapshots"
    id = Column(Integer, primary_key=True)
    org_id = _ORG()
    as_at = Column(Date, nullable=False)
    granularity = Column(String(8), nullable=False, default="week")
    periods = Column(Integer, nullable=False, default=13)
    label = Column(String(100), nullable=True)
    summary = Column(JSON, nullable=False)
    result = Column(JSON, nullable=False)            # buckets, drivers, assumptions, confidence, backtest
    input_hash = Column(String(64), nullable=False)
    created_by = Column(Integer, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    __table_args__ = (Index("ix_plan_fc_org_asat", "org_id", "as_at"),)


class PlanScenario(Base):
    __tablename__ = "plan_scenarios"
    id = Column(Integer, primary_key=True)
    org_id = _ORG()
    name = Column(String(80), nullable=False)
    kind = Column(String(12), nullable=False, default="custom")
    status = Column(String(10), nullable=False, default="active")
    assumptions = Column(JSON, nullable=False, default=dict)
    base_source = Column(String(60), nullable=False, default="run_rate")          # run_rate | budget:<name>
    months = Column(Integer, nullable=False, default=12)
    version = Column(Integer, nullable=False, default=1)
    parent_id = Column(Integer, nullable=True)
    notes = Column(Text, nullable=True)
    created_by = Column(Integer, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    __table_args__ = (UniqueConstraint("org_id", "name", name="uq_plan_scenario_name"), CheckConstraint(_in("kind", SCENARIO_KINDS), name="ck_plan_scenario_kind"),
                      CheckConstraint(_in("status", SCENARIO_STATUSES), name="ck_plan_scenario_status"))


class PlanScenarioRun(Base):
    __tablename__ = "plan_scenario_runs"
    id = Column(Integer, primary_key=True)
    org_id = _ORG()
    scenario_id = Column(Integer, ForeignKey("plan_scenarios.id", ondelete="CASCADE"), nullable=False, index=True)
    scenario_version = Column(Integer, nullable=False)
    as_at = Column(Date, nullable=False)
    assumptions = Column(JSON, nullable=False)
    base = Column(JSON, nullable=False)
    result = Column(JSON, nullable=False)
    input_hash = Column(String(64), nullable=False)
    created_by = Column(Integer, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)


class PlanReportSnapshot(Base):
    __tablename__ = "plan_report_snapshots"
    id = Column(Integer, primary_key=True)
    org_id = _ORG()
    kind = Column(String(24), nullable=False)
    title = Column(String(200), nullable=False)
    period_from = Column(Date, nullable=False)
    period_to = Column(Date, nullable=False)
    params = Column(JSON, nullable=True)
    payload = Column(JSON, nullable=False)
    input_hash = Column(String(64), nullable=False)
    commentary = Column(Text, nullable=True)
    created_by = Column(Integer, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    __table_args__ = (CheckConstraint(_in("kind", REPORT_KINDS), name="ck_plan_report_kind"),)


class PlanAlert(Base):
    __tablename__ = "plan_alerts"
    id = Column(Integer, primary_key=True)
    org_id = _ORG()
    rule = Column(String(24), nullable=False, index=True)
    rule_version = Column(String(24), nullable=False)
    ref = Column(String(120), nullable=True)
    severity = Column(String(8), nullable=False)
    title = Column(String(300), nullable=False)
    reason = Column(Text, nullable=False)
    evidence = Column(JSON, nullable=True)
    baseline = Column(JSON, nullable=True)
    amount = Column(MONEY, nullable=True)
    event_date = Column(Date, nullable=True)
    dedupe_key = Column(String(160), nullable=False)
    status = Column(String(14), nullable=False, default="new")
    reviewer_id = Column(Integer, nullable=True)
    reviewer_name = Column(String(100), nullable=True)
    review_note = Column(Text, nullable=True)
    reviewed_at = Column(DateTime, nullable=True)
    first_seen = Column(DateTime, default=datetime.utcnow)
    last_seen = Column(DateTime, default=datetime.utcnow)
    seen_count = Column(Integer, nullable=False, default=1)
    __table_args__ = (UniqueConstraint("org_id", "dedupe_key", name="uq_plan_alert_dedupe"), CheckConstraint(_in("status", ALERT_STATUSES), name="ck_plan_alert_status"),
                      CheckConstraint(_in("severity", SEVERITIES), name="ck_plan_alert_severity"), Index("ix_plan_alert_state", "org_id", "status", "severity"))


class PlanAiLog(Base):
    __tablename__ = "plan_ai_log"
    id = Column(Integer, primary_key=True)
    org_id = _ORG()
    user_id = Column(Integer, nullable=True)
    question = Column(String(500), nullable=False)
    intent = Column(String(40), nullable=True)
    tools = Column(JSON, nullable=True)
    status = Column(String(10), nullable=False, default="ok")        # ok | clarify | refused | error | limited
    answer_hash = Column(String(64), nullable=True)
    duration_ms = Column(Integer, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, index=True)


PLAN_TABLES = [m.__table__ for m in (PlanSetting, PlanBudget, PlanForecastSnapshot, PlanScenario, PlanScenarioRun, PlanReportSnapshot, PlanAlert, PlanAiLog)]
