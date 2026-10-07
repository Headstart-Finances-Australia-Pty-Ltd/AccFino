import React, { useState } from 'react'
import * as api from '../lib/taxApi.js'
import { act, Async, DataGrid, Input, Modal, Section, Select, Stat, StatusBadge, useForm, useLoad, usePrompt } from '../components/kit.jsx'
import HistoryButton from '../components/HistoryButton.jsx'
import ImportPanel from '../components/ImportPanel.jsx'
import LodgementTab from './LodgementTab.jsx'
import { fmtDate, label } from '../lib/format.js'

const STATUSES = ['upcoming', 'in_progress', 'prepared', 'lodged', 'paid', 'completed', 'not_required']

// Lodgment Readiness = the readiness checklist for each document + the lodgment tracker (every due date and its status) + registrations. AccFino records lodgment; it does not submit to the ATO.
export default function LodgmentReadinessTab({ me, fy, go }) {
  const [f, set] = useForm({ status: '', kind: '', q: '' })
  const ob = useLoad(() => api.obligations({ fy, status: f.status, kind: f.kind }), [fy, f.status, f.kind])
  const regs = useLoad(() => api.registrations(), [])
  const ref = useLoad(() => api.reference(fy), [fy])
  const [dialog, ask] = usePrompt()
  const [add, setAdd] = useState(false)
  const caps = me.capabilities
  const reload = () => { ob.reload(); regs.reload() }
  const rows = (ob.data || []).filter(o => !f.q.trim() || `${o.title} ${o.reference || ''}`.toLowerCase().includes(f.q.trim().toLowerCase()))
  const counts = rows.reduce((m, o) => ({ ...m, [o.display_status]: (m[o.display_status] || 0) + 1 }), {})
  const gen = async () => { const r = await act(() => api.generateObligations(fy), undefined); if (r) { ob.reload(); } }
  const update = async o => {
    const r = await ask({ title: o.title, message: o.linked_type ? 'This row is linked to a prepared document: lodgment and payment are recorded on that document.' : 'Update the status of this lodgment.', confirmLabel: 'Update',
      fields: [{ key: 'status', label: `Status (${STATUSES.join(', ')})`, value: o.status }, { key: 'reference', label: 'ATO reference', value: o.reference || '', required: false }, { key: 'due_date', label: 'Due date', type: 'date', value: o.due_date }] })
    if (r.ok && await act(() => api.updateObligation(o.id, r.values), 'Updated')) reload()
  }
  return (
    <div>
      {dialog}
      <LodgementTab fy={fy} go={go} />
      <div style={{ padding: '0 16px 16px' }}>
        <Section title={`Lodgment tracker ${fy}`} hint="Every due date and where it stands. Overdue and due-soon are worked out from today's date; imported history keeps the status you gave it."
          actions={<>{caps.includes('prepare') && <button className="btn btn-outline btn-sm" onClick={gen}>Generate due dates</button>}{caps.includes('prepare') && <button className="btn btn-outline btn-sm" onClick={() => setAdd(true)}>+ Custom</button>}
            <ImportPanel datasets={[{ key: 'lodgment_obligations', label: 'Lodgment tracker (due dates and status)' }, { key: 'lodgment_registrations', label: 'Tax registrations' }]} caps={caps} onDone={reload} /></>}>
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit,minmax(150px,1fr))', gap: 8, alignItems: 'end' }}>
            <Select label="Status" value={f.status} blank="All" onChange={set('status')} options={STATUSES} /><Select label="Kind" value={f.kind} blank="All" onChange={set('kind')} options={ref.data?.obligation_kinds || []} />
            <Input label="Search title / reference" value={f.q} onChange={set('q')} /></div>
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit,minmax(130px,1fr))', gap: 10, margin: '8px 0' }}>
            {['overdue', 'due_soon', 'upcoming', 'in_progress', 'prepared', 'lodged', 'paid'].map(k => <Stat key={k} label={label(k)} value={counts[k] || 0} tone={k === 'overdue' && counts[k] ? 'danger' : undefined} />)}</div>
          <Async q={ob}>{() => <DataGrid rows={rows} empty="No lodgments for this year" hint="Generate the year's due dates from your tax profile, or import a CSV." columns={[
            { key: 'title', label: 'Obligation', render: o => <>{o.title}<div className="text-xs text-muted">{label(o.kind)} · {o.authority}{o.auto_generated ? '' : ' · entered/imported'}</div></> },
            { key: 'due_date', label: 'Due', render: o => <>{fmtDate(o.due_date)}{o.original_due_date && o.original_due_date !== o.due_date && <div className="text-xs text-muted">was {fmtDate(o.original_due_date)}</div>}</> },
            { key: 'status', label: 'Status', render: o => <StatusBadge status={o.display_status} text={o.display_status === 'overdue' ? 'Overdue' : o.display_status === 'due_soon' ? `Due in ${o.days_to_due} days` : label(o.status)} /> },
            { key: 'lodged_on', label: 'Lodged', render: o => (o.lodged_on ? fmtDate(o.lodged_on) : '—') }, { key: 'reference', label: 'Reference' }, { key: 'amount', label: 'Amount', money: true },
            { key: 'x', label: '', render: o => <span className="flex gap-1">{caps.includes('prepare') && <button className="btn btn-ghost btn-xs" onClick={() => update(o)}>Update</button>}
              {caps.includes('prepare') && !o.auto_generated && <button className="btn btn-ghost btn-xs" onClick={async () => { if (await act(() => api.deleteObligation(o.id), 'Deleted')) reload() }}>Delete</button>}<HistoryButton type="tax_obligation" id={o.id} caps={caps} /></span> }]} />}</Async>
        </Section>
        <Section title="Tax registrations">
          <Async q={regs}>{r => <DataGrid rows={r} empty="No registrations recorded" columns={[{ key: 'kind', label: 'Registration', render: x => label(x.kind) }, { key: 'authority', label: 'Authority' }, { key: 'identifier', label: 'Identifier' },
            { key: 'registered_on', label: 'Registered', date: true }, { key: 'active', label: 'Status', render: x => <StatusBadge status={x.active ? 'active' : 'void'} text={x.active ? 'Active' : 'Cancelled'} /> }]} />}</Async>
        </Section>
      </div>
      {add && <Custom kinds={ref.data?.obligation_kinds || ['custom']} onClose={() => setAdd(false)} onSaved={() => { setAdd(false); reload() }} />}
    </div>)
}

function Custom({ kinds, onClose, onSaved }) {
  const [f, set] = useForm({ title: '', due_date: '', kind: 'custom', authority: '', note: '' })
  return (
    <Modal title="Custom lodgment" onClose={onClose} width={460}>
      <Input label="Title" value={f.title} onChange={set('title')} /><Input label="Due date" type="date" value={f.due_date} onChange={set('due_date')} /><Select label="Kind" value={f.kind} onChange={set('kind')} options={kinds} />
      <Input label="Authority" value={f.authority} onChange={set('authority')} /><Input label="Note" value={f.note} onChange={set('note')} />
      <div className="flex gap-1" style={{ justifyContent: 'flex-end' }}><button className="btn btn-outline" onClick={onClose}>Cancel</button><button className="btn btn-primary" disabled={!f.title.trim() || !f.due_date} onClick={async () => { if (await act(() => api.addObligation(f), 'Added')) onSaved() }}>Add</button></div>
    </Modal>)
}
