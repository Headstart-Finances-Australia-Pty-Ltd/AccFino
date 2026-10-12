import React from 'react'
import * as api from '../lib/taxApi.js'
import { Async, Disclaimer, Section, Stat, StatusBadge, useLoad } from '../components/kit.jsx'
import { fmtDate, label } from '../lib/format.js'

const TONE = { error: 'var(--danger)', warn: 'var(--warning)', info: 'var(--text-muted)' }

export default function OverviewTab({ go }) {
  const q = useLoad(() => api.dashboard(), [])
  return (
    <div style={{ padding: 16 }}>
      <Async q={q}>{d => (
        <>
          <Disclaimer />
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit,minmax(170px,1fr))', gap: 12, marginBottom: 14 }}>
            <Stat label="Overdue" value={d.calendar.overdue.length} tone={d.calendar.overdue.length ? 'danger' : undefined} onClick={() => go('calendar')} />
            <Stat label="Due in 14 days" value={d.calendar.due_soon.length} tone={d.calendar.due_soon.length ? 'warning' : undefined} onClick={() => go('calendar')} />
            <Stat label={`Activity statements ${d.fy}`} value={d.bas.count} sub={Object.entries(d.bas.by_status).map(([k, v]) => `${v} ${k}`).join(' · ') || 'none yet'} onClick={() => go('gst')} />
            <Stat label="Adjustments to review" value={d.open_adjustments_for_review} tone={d.open_adjustments_for_review ? 'warning' : undefined} onClick={() => go('income')} />
            <Stat label="Division 7A loans" value={d.div7a.active_loans} onClick={() => go('fbt')} />
          </div>
          {d.alerts.length > 0 && <Section title="Needs attention">{d.alerts.map((a, i) => <div key={i} className="text-sm" style={{ color: TONE[a.level] || undefined, padding: '2px 0' }}>{a.level === 'error' ? '✖' : '▲'} {a.text}</div>)}</Section>}
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit,minmax(340px,1fr))', gap: 14 }}>
            <Section title="Next due" actions={<button className="btn btn-outline btn-sm" onClick={() => go('calendar')}>Calendar</button>}>
              {d.calendar.next.length === 0 ? <div className="text-sm text-muted">No open obligations. Open the Compliance Calendar and generate the year’s due dates.</div> :
                d.calendar.next.map(o => <div key={o.id} className="flex items-center justify-between text-sm" style={{ padding: '3px 0' }}><span>{o.title}</span><span>{fmtDate(o.due_date)} <StatusBadge status={o.display_status} /></span></div>)}
            </Section>
            <Section title="Data health" hint={d.health.ok ? 'No blocking problems' : 'Fix errors before preparing statements'} actions={<button className="btn btn-outline btn-sm" onClick={() => go('settings')}>Settings</button>}>
              {d.health.items.length === 0 ? <div className="text-sm text-muted">All checks passed.</div> : d.health.items.slice(0, 8).map(i => <div key={i.key} className="text-sm" style={{ padding: '2px 0', color: TONE[i.severity] }}>{i.severity === 'error' ? '✖' : i.severity === 'warn' ? '▲' : 'ℹ'} {i.message}</div>)}
            </Section>
            <Section title="Current documents">
              <div className="text-sm">{d.returns.length ? d.returns.map(r => <div key={r.id}>Income tax return {r.fy} v{r.version} <StatusBadge status={r.status} /></div>) : 'No income tax return started for this year.'}</div>
              {d.fbt.map(r => <div key={r.id} className="text-sm">FBT return {r.fbt_year} <StatusBadge status={r.status} /></div>)}
              <div className="text-sm" style={{ marginTop: 6 }}>Workpapers: {Object.entries(d.workpapers).map(([k, v]) => `${v} ${label(k)}`).join(', ') || 'none'}</div>
            </Section>
            <Section title="Recent activity" actions={<button className="btn btn-outline btn-sm" onClick={() => go('audit')}>Audit trail</button>}>
              {d.recent_activity.length === 0 ? <div className="text-sm text-muted">Nothing yet.</div> : d.recent_activity.map(a => <div key={a.seq} className="text-xs" style={{ padding: '2px 0' }}><strong>{fmtDate(a.at)}</strong> {a.summary}</div>)}
            </Section>
          </div>
        </>)}</Async>
    </div>)
}
