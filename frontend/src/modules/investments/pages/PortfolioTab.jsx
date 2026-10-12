import React, { useState } from 'react'
import * as api from '../lib/invApi.js'
import { Async, Disclaimer, Money, Notice, Pct, Section, Stat, useLoad } from '../components/kit.jsx'
import { Bars, Donut, HistoryChart } from '../components/charts.jsx'
import { HoldingsPanel, ReportsBar, SettingsButton } from '../components/panels.jsx'
import BulkDocs from '../components/BulkDocs.jsx'
import ImportPanel from '../components/ImportPanel.jsx'
import { fmtPct } from '../lib/format.js'

// Everything the user holds in one place: value, gains, income, return, allocation, concentration, history and drill-down.
export default function PortfolioTab({ me }) {
  const [bump, setBump] = useState(0)
  const perf = useLoad(() => api.portfolio.performance({}), [bump])
  const alloc = useLoad(() => api.portfolio.allocation({}), [bump])
  const hist = useLoad(() => api.portfolio.history(24), [bump])
  const inc = useLoad(() => api.portfolio.income({}), [bump])
  const disp = useLoad(() => api.portfolio.disposals({}), [bump])
  return (
    <div style={{ padding: 16 }}>
      <div className="flex items-center justify-between" style={{ flexWrap: 'wrap', gap: 8 }}><Disclaimer /><span className="flex gap-1" role="group" aria-label="Settings and bulk uploads"><BulkDocs caps={me.capabilities} onDone={() => setBump(n => n + 1)} /><ImportPanel datasets={[{ key: 'settings', label: 'Investment settings' }]} caps={me.capabilities} onDone={() => setBump(n => n + 1)} buttonLabel="Import settings (CSV)" /><SettingsButton me={me} onSaved={() => setBump(n => n + 1)} /></span></div>
      <Async q={perf}>{p => (
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit,minmax(170px,1fr))', gap: 12, marginBottom: 12 }}>
          <Stat label="Portfolio value" value={<Money v={p.market_value} strong />} /><Stat label="Total return" value={<Money v={p.total_return} strong />} sub={<Pct v={p.total_return_pct} />} tone={Number(p.total_return) < 0 ? 'danger' : undefined} />
          <Stat label="Annual return since start (XIRR)" value={<Pct v={p.xirr_since_inception} />} sub="money-weighted" /><Stat label="Annual return, last 12 months" value={<Pct v={p.xirr_last_12_months} />} />
          <Stat label="Invested to date" value={<Money v={p.total_invested} />} /><Stat label="Returned (sales and income)" value={<Money v={p.total_returned} />} /></div>)}</Async>
      <Async q={alloc}>{a => (
        <>
          <Notice items={a.warnings.map(w => w.message)} />
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit,minmax(300px,1fr))', gap: 12 }}>
            <Section title="By asset class"><Donut data={a.by_class} title="Allocation by asset class" /></Section><Section title="By investment type"><Donut data={a.by_kind} title="Allocation by type" /></Section>
            <Section title="By country"><Donut data={a.by_country} title="Allocation by country" /></Section><Section title="By sector"><Donut data={a.by_sector} title="Allocation by sector" /></Section>
            <Section title="By account"><Donut data={a.by_account} title="Allocation by account" /></Section>
            <Section title="Diversification" hint="Advisory: how concentrated the portfolio is. Not a recommendation.">
              {a.diversification.hhi == null ? <div className="text-sm text-muted">Add holdings with prices to measure diversification.</div> : (
                <div>
                  <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 10 }}><Stat label="Holdings" value={a.diversification.holdings} /><Stat label="Effective holdings" value={a.diversification.effective_holdings.toFixed(1)} sub="1 ÷ concentration index" />
                    <Stat label="Largest holding" value={fmtPct(a.diversification.top1, 1)} /><Stat label="Top 5 holdings" value={fmtPct(a.diversification.top5, 1)} /></div>
                  {a.diversification.over_limit.length > 0 && <div className="text-sm" style={{ marginTop: 8, color: 'var(--warning)' }}>▲ Above {fmtPct(a.diversification.limit, 0)} of the portfolio: {a.diversification.over_limit.map(o => `${o.name} ${fmtPct(o.weight, 1)}`).join(', ')}</div>}
                </div>)}</Section></div>
        </>)}</Async>
      <Section title="Portfolio history" hint="Month-end market value against cost base, from your transactions and the prices you have recorded."><Async q={hist}>{h => <HistoryChart points={h.points} series={[{ key: 'value', name: 'Market value' }, { key: 'cost', name: 'Cost base' }, { key: 'invested_to_date', name: 'Invested to date' }]} />}</Async></Section>
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit,minmax(300px,1fr))', gap: 12 }}>
        <Section title="Income by income year"><Async q={inc}>{i => <Bars data={i.by_fy.map(r => ({ name: r.key, value: r.cash }))} />}</Async></Section>
        <Section title="Realised gains by income year (estimate)"><Async q={disp}>{d => <Bars data={d.summary.by_fy.map(r => ({ name: r.fy, value: r.net_capital_gain }))} />}</Async></Section></div>
      <Section title="Holdings" hint="Click a holding for its parcels, disposals, income, return and documents." actions={<ReportsBar />}><HoldingsPanel kind="" caps={me.capabilities} bump={bump} /></Section>
    </div>)
}
