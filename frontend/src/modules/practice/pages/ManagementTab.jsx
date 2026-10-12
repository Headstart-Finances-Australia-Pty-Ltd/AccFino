import React, { useState } from 'react'
import { BulkLoadButton } from '../../../core/components/ui/BulkLoadButton.jsx'
import { Async, Section, Stat, Table, StatusBadge, useLoad, act, Input, Select, useForm, Money, Modal } from '../components/kit.jsx'
import * as api from '../lib/practiceApi.js'

const TILES = [
  ['clients_active', 'Active clients'], ['clients_unassigned', 'Clients with no manager'], ['engagements_active', 'Active engagements'], ['jobs_overdue', 'Overdue jobs'],
  ['jobs_due_soon', 'Jobs due soon'], ['deadlines_overdue', 'Overdue deadlines'], ['deadlines_due_soon', 'Deadlines due soon'], ['statutory_unverified', 'Unverified statutory dates'],
  ['workpapers_awaiting_review', 'Workpapers awaiting review'], ['requests_outstanding', 'Client requests outstanding'], ['requests_to_review', 'Client responses to review'], ['time_awaiting_approval', 'Time awaiting approval'],
]
const ROLES = ['admin', 'partner', 'manager', 'preparer', 'reviewer', 'billing', 'readonly']

function Drill({ metric, title, onClose }) {
  const q = useLoad(() => api.dashboard.drill(metric, 1, 100), [metric])
  return (
    <Modal title={title} onClose={onClose} wide>
      <Async q={q}>{d => (
        <>
          <div className="text-sm text-muted" style={{ marginBottom: 8 }}>{d.total} record(s) — the same records counted on the tile.</div>
          <Table caption={title} rows={d.items} columns={[
            { key: 'id', label: 'ID' }, { key: 'title', label: 'Item', render: r => r.title || r.legal_name || r.description || `#${r.id}` }, { key: 'client_id', label: 'Client' },
            { key: 'status', label: 'Status', render: r => <StatusBadge status={r.status || r.state} /> }, { key: 'due_date', label: 'Due', date: true }]} />
        </>)}
      </Async>
    </Modal>)
}

export default function ManagementTab({ can }) {
  const dash = useLoad(() => api.dashboard.summary(), [])
  const work = useLoad(() => api.dashboard.workload(), [])
  const members = useLoad(() => api.members.list(), [])
  const [drill, setDrill] = useState(null)
  const [m, setM] = useForm({ staff_id: '', role: 'preparer' })
  return (
    <div style={{ padding: 16 }}>
      <div style={{ display: 'flex', justifyContent: 'flex-end', marginBottom: 8 }}><BulkLoadButton base="/practice/bulk" areas={["Practice"]} onDone={() => window.location.reload()} /></div>
      <Async q={dash}>{d => (
        <>
          <div className="text-xs text-muted" style={{ marginBottom: 8 }}>As at {d.as_of} · {d.scope} · role {d.role}</div>
          <div className="stat-grid" style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit,minmax(170px,1fr))', gap: 10 }}>
            {TILES.filter(([k]) => d.tiles[k]).map(([k, l]) => <Stat key={k} label={l} value={d.tiles[k].count} onClick={() => setDrill([k, l])} />)}
          </div>
          {d.billing && <Section title="Billing snapshot" hint="Same figures as the Billing tab">
            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit,minmax(170px,1fr))', gap: 10 }}>
              <Stat label="Unbilled work in progress" value={<Money v={d.billing.wip} />} /><Stat label="Invoiced this month (ex tax)" value={<Money v={d.billing.invoiced_net} />} />
              <Stat label="Realisation" value={d.billing.realisation_pct == null ? 'n/a' : `${d.billing.realisation_pct}%`} /><Stat label="Receivables" value={<Money v={d.billing.receivables} />} sub={<>Overdue <Money v={d.billing.receivables_overdue} /></>} />
            </div></Section>}
        </>)}
      </Async>
      <Section title="Workload" hint="Clients and open jobs per person">
        <Async q={work}>{rows => <Table caption="Workload" rows={rows} rowKey="staff_id" columns={[{ key: 'staff_id', label: 'Staff' }, { key: 'role', label: 'Role' }, { key: 'managed', label: 'Manages' }, { key: 'prepared', label: 'Prepares' },
          { key: 'reviewed', label: 'Reviews' }, { key: 'open_jobs', label: 'Open jobs' }, { key: 'overdue_jobs', label: 'Overdue jobs' }]} />}</Async>
      </Section>
      <Section title="Members" hint="Practice membership builds on organisation membership">
        <Async q={members}>{rows => (
          <>
            <Table caption="Members" rows={rows} columns={[{ key: 'name', label: 'Name' }, { key: 'email', label: 'Email' }, { key: 'role', label: 'Role' }, { key: 'status', label: 'Status', render: r => <StatusBadge status={r.status} /> },
              { key: 'x', label: '', render: r => can('members') && <button className="btn btn-outline btn-sm" onClick={async () => { const role = window.prompt('New role: ' + ROLES.join(', '), r.role); if (role && await act(() => api.members.change(r.id, { role }), 'Role updated')) members.reload() }}>Change role</button> }]} />
            {can('members') && <div className="flex items-center gap-1" style={{ marginTop: 10, flexWrap: 'wrap' }}>
              <Input label="Staff login id" type="number" value={m.staff_id} onChange={setM('staff_id')} /><Select label="Role" value={m.role} onChange={setM('role')} options={ROLES} />
              <button className="btn btn-primary btn-sm" disabled={!m.staff_id} onClick={async () => { if (await act(() => api.members.add(Number(m.staff_id), m.role), 'Member added')) members.reload() }}>Add member</button></div>}
          </>)}
        </Async>
      </Section>
      {drill && <Drill metric={drill[0]} title={drill[1]} onClose={() => setDrill(null)} />}
    </div>)
}
