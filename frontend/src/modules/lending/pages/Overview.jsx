import React from 'react'
import * as L from '../lib/lendApi.js'
import { Async, Money, Stat, StatusBadge, useLoad } from '../components/kit.jsx'
import { fmtAUD, label } from '../lib/format.js'

const TAB_OF = { application: 'origination', loan: 'collections', facility: 'treasury' }

// One glance: the pipeline, the book, who is behind, the next 30 days of cash, and the things waiting on someone.
export default function Overview({ onGo, refreshKey = 0 }) {
  const q = useLoad(() => L.dashboard(), [refreshKey])
  return (
    <Async q={q}>{d => {
      const p = d.pipeline, bk = d.book, ar = d.arrears, lq = d.liquidity                        // a section is null when the plan does not include its module
      const open = p ? ['draft', 'submitted', 'assessing', 'more_information'].reduce((n, s) => n + (p.counts[s] || 0), 0) : 0
      const behind = ar ? ar.buckets.filter(b => b.bucket !== 'Current').reduce((n, b) => n + b.loans, 0) : 0
      return (
        <div style={{ padding: '12px 16px', borderBottom: '1px solid var(--border)' }} aria-label="Lending overview">
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit,minmax(170px,1fr))', gap: 10 }}>
            {p && <Stat label="Applications open" value={open} sub={`${p.counts.approved || 0} approved, awaiting settlement`} onClick={() => onGo('origination')} />}
            {bk && <Stat label="Loans on the book" value={bk.active} sub={`${fmtAUD(bk.balance)} outstanding`} onClick={() => onGo('management')} />}
            {ar && <Stat label="Loans behind" value={behind} tone={behind ? 'danger' : undefined} sub={`${fmtAUD(ar.summary.arrears_total)} in arrears`} onClick={() => onGo('collections')} />}
            {lq && <Stat label="Cash today" value={<Money v={lq.cash} strong />} sub={`${fmtAUD(lq.facility_available)} available to draw`} onClick={() => onGo('treasury')} />}
            {lq && <Stat label="Next 30 days" value={<StatusBadge status={lq.status} text={label(lq.status)} />} sub={`committed ${fmtAUD(lq.closing_committed)}`} onClick={() => onGo('treasury')} />}</div>
          {d.attention.length > 0 && <div style={{ marginTop: 8 }} aria-label="Needs attention"><div className="text-sm" style={{ fontWeight: 600 }}>Needs attention</div>
            {d.attention.slice(0, 6).map((a, i) => <div key={i} className="text-sm"><button className="btn btn-ghost btn-xs" onClick={() => onGo(TAB_OF[a.kind])}>{a.text}</button></div>)}</div>}
        </div>)
    }}</Async>)
}
