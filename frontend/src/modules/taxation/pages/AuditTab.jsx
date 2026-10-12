import React from 'react'
import * as api from '../lib/taxApi.js'
import { act, Async, DataGrid, Disclaimer, Section, useLoad } from '../components/kit.jsx'
import toast from 'react-hot-toast'

export default function AuditTab({ me }) {
  const can = me.capabilities.includes('audit_view')
  const q = useLoad(() => (can ? api.audit({ limit: 200 }) : Promise.resolve([])), [can])
  const verify = async () => { const r = await act(() => api.verifyAudit()); if (r) (r.ok ? toast.success(`Audit chain intact: ${r.events} events`) : toast.error(`Audit chain BROKEN at event #${r.broken_at}`)) }
  if (!can) return <div style={{ padding: 16 }} className="text-muted">The audit trail is available to Accountants and the Organisation Admin.</div>
  return (
    <div style={{ padding: 16 }}>
      <Disclaimer />
      <Section title="Compliance history" hint="Every profile change, rate override, calculation, approval, lodgement record and evidence upload. Each event is chained to the previous one by a hash, so edits or deletions are detectable."
        actions={<><button className="btn btn-outline btn-sm" onClick={verify}>Verify integrity</button><button className="btn btn-outline btn-sm" onClick={q.reload}>Refresh</button></>}>
        <Async q={q}>{rows => <DataGrid rows={rows} rowKey="seq" searchKeys={['summary', 'action', 'user']} empty="No activity yet" pageSize={25} columns={[{ key: 'seq', label: '#' }, { key: 'at', label: 'When', render: a => new Date(a.at + 'Z').toLocaleString('en-AU') },
          { key: 'user', label: 'Who' }, { key: 'action', label: 'Action', render: a => <span className="mono text-xs">{a.action}</span> }, { key: 'summary', label: 'What happened' }]} />}</Async>
      </Section>
    </div>)
}
