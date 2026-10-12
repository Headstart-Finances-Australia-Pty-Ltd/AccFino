import React from 'react'
import * as api from '../lib/planningApi.js'
import { fmtAUD, fmtDate, label } from '../lib/format.js'
import { useLoad, Async, Stat, Section, Basis, Provenance, Money, StatusBadge, EmptyState } from '../components/kit.jsx'

const TileError = ({ t }) => <div role="alert" className="text-sm" style={{ color: 'var(--danger)' }}>This figure could not be loaded: {t.error}</div>

// Landing page: every tile is computed server-side from the same services the tabs use. A failed tile shows its own error and never blanks the page.
export default function Home({ go }) {
  const q = useLoad(() => api.overview(), [])
  return (
    <div style={{ padding: 16 }}>
      <Async q={q}>{o => {
        const { cash, forecast: fc, profit, budget, risk, insights: ins, scenarios, assistant } = o
        const stale = cash && !cash.error && cash.stale
        return (
          <>
            <Provenance d={{ organisation: o.organisation, currency: o.currency, as_at: o.as_at, source: 'ledger, budgets, forecasts and rule engines' }} />
            {stale && <div role="note" className="alert alert-warning" style={{ marginBottom: 12 }}>⚠ Bank data may be stale: the latest bank line is {fmtDate(cash.last_bank_line)}. Cash figures and forecasts rely on it.</div>}
            {cash && !cash.error && cash.accounts === 0 && <div role="note" className="alert alert-info" style={{ marginBottom: 12 }}>No bank account is set up in the ledger yet, so cash and forecast figures are indicative only.</div>}
            <div className="stat-grid" style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit,minmax(210px,1fr))', gap: 12, marginBottom: 14 }}>
              {cash?.error ? <TileError t={cash} /> : <Stat label="Cash at bank" basis="ACTUAL" value={fmtAUD(cash?.balance)} sub={`${cash?.accounts ?? 0} bank account(s) · ${cash?.unreconciled ?? 0} unreconciled line(s)`} onClick={() => go('cashflow')} />}
              {fc?.error ? <TileError t={fc} /> : <Stat label="Lowest forecast cash" basis="FORECAST" tone={fc?.goes_negative ? 'danger' : undefined} value={fmtAUD(fc?.minimum?.balance)}
                sub={`${fc?.minimum?.label || ''} · confidence ${fc?.confidence} · ${fc?.warnings} warning(s)`} onClick={() => go('cashflow')} />}
              {profit?.error ? <TileError t={profit} /> : <Stat label="Profit, financial year to date" basis="ACTUAL" tone={Number(profit?.net_profit) < 0 ? 'danger' : undefined} value={fmtAUD(profit?.net_profit)}
                sub={`Revenue ${fmtAUD(profit?.revenue)} · expenses ${fmtAUD(profit?.expenses)}`} onClick={() => go('reporting')} />}
              {budget?.error ? <TileError t={budget} /> : budget?.status === 'none' ? <Stat label="Budget vs actual" basis="BUDGET" value="No budget" sub={budget.note} onClick={() => go('budgeting')} />
                : <Stat label="Profit vs budget" basis="BUDGET" tone={Number(budget?.profit?.variance) < 0 ? 'danger' : 'success'} value={fmtAUD(budget?.profit?.variance)}
                  sub={`${budget?.name} · ${budget?.period}${budget?.pending ? ` · ${budget.pending} awaiting approval` : ''}`} onClick={() => go('budgeting')} />}
              {risk?.error ? <TileError t={risk} /> : <Stat label="Open risk alerts" basis="RULE" tone={risk?.by_severity?.high ? 'danger' : undefined} value={risk?.new ?? 0}
                sub={`${risk?.by_severity?.high || 0} high · ${risk?.by_severity?.medium || 0} medium · ${risk?.by_severity?.low || 0} low`} onClick={() => go('risk')} />}
              {ins?.error ? <TileError t={ins} /> : <Stat label="CFO insights" basis="RULE" value={(ins?.counts?.high || 0) + (ins?.counts?.medium || 0) + (ins?.counts?.low || 0) + (ins?.counts?.info || 0)}
                sub={`${ins?.counts?.high || 0} high · ${ins?.counts?.medium || 0} medium · ${ins?.counts?.low || 0} low`} onClick={() => go('cfo')} />}
            </div>
            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit,minmax(320px,1fr))', gap: 14 }}>
              <Section title="Top insights" hint={ins?.period ? `Period ${ins.period} · rule results, not advice` : undefined} actions={<button className="btn btn-outline btn-sm" onClick={() => go('cfo')}>Open</button>}>
                {ins?.error ? <TileError t={ins} /> : !ins?.top?.length ? <EmptyState icon="✅" title="No insights triggered" hint="Nothing in this period crossed a rule threshold." />
                  : <ul style={{ margin: 0, paddingLeft: 18 }}>{ins.top.map((t, i) => <li key={i} style={{ marginBottom: 6 }}><StatusBadge status={t.severity} /> {t.title}</li>)}</ul>}
              </Section>
              <Section title="Planning activity" hint="Hypothetical and read-only work is kept apart from your books">
                <div className="text-sm" style={{ display: 'grid', gap: 6 }}>
                  <div><Basis basis="SCENARIO" /> {scenarios?.error ? 'unavailable' : `${scenarios?.active ?? 0} active scenario(s)${scenarios?.last_run_at ? ` · last run ${fmtDate(scenarios.last_run_at)}` : ''}`}</div>
                  <div><Basis basis="AI" /> {assistant?.error ? 'unavailable' : `${assistant?.questions_24h ?? 0} question(s) in the last 24 hours`}</div>
                  <div>Report snapshots stored: {o.reports?.error ? 'unavailable' : o.reports?.snapshots ?? 0}</div>
                  <div>Cash threshold: <Money v={o.settings?.min_cash_threshold} /> · horizon {o.settings?.horizon_weeks} weeks</div>
                </div>
              </Section>
            </div>
          </>)
      }}</Async>
    </div>)
}
