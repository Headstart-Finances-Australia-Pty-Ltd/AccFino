# Planning & Intelligence  (`accfino.modules.planning`)

Cash-flow forecasting, budgeting, scenario planning, management reporting, CFO insights, a read-only AI financial assistant, and risk / anomaly review. The general ledger is the single source of truth; this module only READS it (through `accounting.public`) and stores its own plans, snapshots, alerts and audit log. It never posts a journal and never edits a ledger or sub-ledger record.

| | |
|---|---|
| Backend | `backend/accfino/modules/planning/` (`engine/` pure Decimal maths, `services/` orchestration, `api/` HTTP) |
| Frontend | `frontend/src/modules/planning/` (tabs are composed by `core/hubs/PlanningPage.jsx`) |
| Tests | `python AccFino_Testing/run_tests.py planning` (and `cashflow` for the legacy CSV forecaster) |
| Owns tables | `plan_settings`, `plan_budgets`, `plan_forecast_snapshots`, `plan_scenarios`, `plan_scenario_runs`, `plan_report_snapshots`, `plan_alerts`, `plan_ai_log` |
| Uses (public facades) | `accounting`, `lending`, `taxation` |
| Uses (shared services) | `contracts`, `db` |
| Public API for other modules | none |
| Extra docs | `AccFino_Testing/tests/modules/planning/ORACLES.md`, `MANUAL_TESTS.md` |

## Rules this module keeps
1. Money is `Decimal`, rounded explicitly (2 dp, half-up). No floats in amounts.
2. Results are deterministic: same ledger + same inputs = same output. "Today" comes from `core.business_today()`.
3. Every figure is stamped with period, organisation, currency and source. Actuals, budgets, forecasts and scenarios are labelled and never mixed silently.
4. Scenarios, forecasts, insights, risk scans and the assistant never post journals or change accounting records.
5. The assistant is read-only: a fixed intent router, a whitelist of parameterised tools, a permission check per tool call, bounded output, a per-user rate limit (`ACCFINO_PLAN_AI_RATE`, default 30/hour), a timeout (`ACCFINO_PLAN_AI_TIMEOUT`, default 20 s) and a masked audit log. Numbers in answers are verified against tool output.
6. Risk alerts mean "unusual - please review". They are never labelled fraud and never block anything.
7. Management reports are labelled "management report - not a statutory financial statement".
8. Budget approval uses separation of duties (the organisation owner or a platform admin may self-approve). Route and body field names `user_id` / `username` are reserved by the platform and must not be used.

## HTTP API (prefix `/planning`, 50 routes, each sub-router gated by its own module id)
| Area | Module id | Routes |
|---|---|---|
| landing (`/me`, `/overview`, `/settings`, `/drilldown`) | any planning module | 5 |
| `/forecast...` | `cash-flow-forecasting` | 5 |
| `/budgets...` | `budgeting-forecasting` | 13 |
| `/scenarios...` | `scenario-planning` | 11 |
| `/reports...` | `management-reporting` | 5 |
| `/insights...` | `cfo-insights` | 2 |
| `/assistant...` | `ai-financial-assistant` | 3 |
| `/risk...` | `risk-anomaly-detection` | 6 |

## Known limitations
Only monthly recurring patterns are detected; bills not yet entered are not forecast; tax obligations without an amount are warned about rather than forecast; scenario base cash assumes profit converts to cash in the same month; the assistant answers recognised question types only (no LLM); legacy `/accounting` budget edits bypass the Planning approval workflow; no PDF export (browser print is available); statistical models are deliberately simple.
