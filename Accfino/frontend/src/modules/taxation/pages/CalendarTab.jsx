import React, { useState } from 'react'
import * as api from '../lib/taxApi.js'
import { act, Async, DataGrid, Disclaimer, Input, Modal, Section, Select, StatusBadge, useForm, useLoad, usePrompt } from '../components/kit.jsx'
import { fmtAUD, fmtDate, label } from '../lib/format.js'

export default function CalendarTab({ me, fy }) {
  const ob = useLoad(() => api.obligations({ fy }), [fy])
  const regs = useLoad(() => api.registrations(), [])
  const ref = useLoad(() => api.reference(fy), [fy])
  const pt = useLoad(() => api.payrollTaxWatch(fy), [fy])
  const [dialog, ask] = usePrompt()
  const [add, setAdd] = useState(false)
  const [reg, setReg] = useState(null)
  const caps = me.capabilities
  const gen = async () => { const r = await act(() => api.generateObligations(fy)); if (r) { ob.reload(); r.created ? null : null } }
  const mark = async o => {
    const r = await ask({ title: o.title, message: o.linked_type ? 'This obligation is linked to a prepared document: lodgement and payment are recorded on that document.' : 'Update status. Recording lodgement or payment needs lodge permission.', confirmLabel: 'Update',
      fields: [{ key: 'status', label: 'Status (upcoming, in_progress, prepared, lodged, paid, completed, not_required)', value: o.status }, { key: 'reference', label: 'ATO reference', value: o.reference || '', required: false }, { key: 'due_date', label: 'Due date (change only if the ATO or your agent set another)', type: 'date', value: o.due_date }] })
    if (r.ok && await act(() => api.updateObligation(o.id, r.values), 'Updated')) ob.reload()
  }
  const del = async o => { if (await act(() => api.deleteObligation(o.id), 'Deleted')) ob.reload() }
  return (
    <div style={{ padding: 16 }}>
      {dialog}
      <Disclaimer />
      <Section title={`Due dates ${fy}`} hint="Generated from your tax profile. A due date on a weekend or national holiday rolls to the next business day; add your state’s public holidays in Rates & Settings. Confirm dates on ato.gov.au."
        actions={caps.includes('prepare') && <><button className="btn btn-outline btn-sm" onClick={gen}>Generate due dates</button><button className="btn btn-primary btn-sm" onClick={() => setAdd(true)}>+ Custom</button></>}>
        <Async q={ob}>{rows => <DataGrid rows={rows} empty="No obligations yet" hint="Generate the year’s due dates from your tax profile." searchKeys={['title']} columns={[
          { key: 'title', label: 'Obligation', render: o => <>{o.title}{o.note && <div className="text-xs text-muted">{o.note}</div>}</> }, { key: 'authority', label: 'Authority' },
          { key: 'due_date', label: 'Due', render: o => <>{fmtDate(o.due_date)}{o.original_due_date && o.original_due_date !== o.due_date && <div className="text-xs text-muted">was {fmtDate(o.original_due_date)} (weekend/holiday)</div>}{o.agent_due_date && <div className="text-xs text-muted">agent program {fmtDate(o.agent_due_date)}</div>}</> },
          { key: 'status', label: 'Status', render: o => <><StatusBadge status={o.display_status} text={o.display_status === 'overdue' ? 'Overdue' : o.display_status === 'due_soon' ? `Due in ${o.days_to_due} days` : label(o.status)} />{o.linked_type && <span className="text-xs text-muted"> linked</span>}</> },
          { key: 'reference', label: 'Reference' }, { key: 'x', label: '', render: o => caps.includes('prepare') && <span className="flex gap-1"><button className="btn btn-ghost btn-xs" onClick={() => mark(o)}>Update</button>{!o.auto_generated && <button className="btn btn-ghost btn-xs" onClick={() => del(o)}>Delete</button>}</span> }]} />}</Async>
      </Section>
      <Section title="Tax registrations" hint="A record of what the organisation is registered for. Never enter a Tax File Number."
        actions={caps.includes('config') && <button className="btn btn-primary btn-sm" onClick={() => setReg({})}>+ Registration</button>}>
        <Async q={regs}>{rows => <DataGrid rows={rows} empty="No registrations recorded" columns={[{ key: 'kind', label: 'Registration', render: r => label(r.kind) }, { key: 'authority', label: 'Authority' }, { key: 'identifier', label: 'Identifier' }, { key: 'registered_on', label: 'Registered', date: true },
          { key: 'active', label: 'Status', render: r => <StatusBadge status={r.active ? 'active' : 'void'} text={r.active ? 'Active' : 'Cancelled'} /> }, { key: 'x', label: '', render: r => caps.includes('config') && <span className="flex gap-1"><button className="btn btn-ghost btn-xs" onClick={() => setReg(r)}>Edit</button>
            <button className="btn btn-ghost btn-xs" onClick={async () => { if (await act(() => api.deleteRegistration(r.id), 'Deleted')) regs.reload() }}>Delete</button></span> }]} />}</Async>
      </Section>
      <Section title="State payroll tax (monitor)" hint="Compares wages from Payroll with your state's registration threshold. It does not calculate payroll tax.">
        <Async q={pt}>{w => (
          <div className="text-sm">
            <div style={{ marginBottom: 6 }}><StatusBadge status={w.status === 'above' ? 'overdue' : w.status === 'approaching' ? 'due_soon' : w.status === 'below' ? 'completed' : 'upcoming'}
              text={{ above: 'At or above threshold', approaching: 'Approaching threshold', below: 'Below threshold', not_loaded: 'Threshold not loaded', no_state: 'No state set' }[w.status]} /> {w.state || ''}</div>
            <div>{w.message}</div>
            {w.threshold && <div style={{ marginTop: 6 }}>Wages so far {fmtAUD(w.wages_ytd)} · projected full year {fmtAUD(w.projected_wages)} · {w.state} threshold {fmtAUD(w.threshold)}</div>}
            {w.indicative_tax && <div style={{ marginTop: 6 }}>Indicative flat-rate amount on Payroll wages only: <strong>{fmtAUD(w.indicative_tax)}</strong> — {w.indicative_note}</div>}
            {!w.indicative_tax && w.indicative_note && <div className="text-muted" style={{ marginTop: 6 }}>{w.indicative_note}</div>}
            {w.action && <div style={{ marginTop: 6, color: 'var(--warning)' }}>▲ {w.action}</div>}
            <details style={{ marginTop: 8 }}><summary className="text-xs" style={{ cursor: 'pointer' }}>Basis and what is not assessed</summary>
              <div className="text-xs text-muted" style={{ marginTop: 4 }}>{w.basis}<ul style={{ margin: '6px 0 0 16px' }}>{w.not_assessed.map(n => <li key={n}>{n}</li>)}</ul></div></details>
          </div>)}</Async>
      </Section>
      {add && <Custom kinds={ref.data?.obligation_kinds || ['custom']} onClose={() => setAdd(false)} onSaved={() => { setAdd(false); ob.reload() }} />}
      {reg && <Reg item={reg} kinds={ref.data?.registration_kinds || []} onClose={() => setReg(null)} onSaved={() => { setReg(null); regs.reload() }} />}
    </div>)
}

function Custom({ kinds, onClose, onSaved }) {
  const [f, set] = useForm({ title: '', due_date: '', kind: 'custom', authority: '', note: '' })
  return (
    <Modal title="Custom obligation" onClose={onClose} width={460}>
      <Input label="Title" value={f.title} onChange={set('title')} /><Input label="Due date" type="date" value={f.due_date} onChange={set('due_date')} /><Select label="Kind" value={f.kind} onChange={set('kind')} options={kinds} />
      <Input label="Authority (e.g. State Revenue Office, ASIC)" value={f.authority} onChange={set('authority')} /><Input label="Note" value={f.note} onChange={set('note')} />
      <div className="flex gap-1" style={{ justifyContent: 'flex-end' }}><button className="btn btn-outline" onClick={onClose}>Cancel</button><button className="btn btn-primary" disabled={!f.title.trim() || !f.due_date} onClick={async () => { if (await act(() => api.addObligation(f), 'Added')) onSaved() }}>Add</button></div>
    </Modal>)
}

function Reg({ item, kinds, onClose, onSaved }) {
  const [f, set] = useForm({ kind: 'gst', authority: 'ATO', identifier: '', registered_on: '', cancelled_on: '', notes: '', ...Object.fromEntries(Object.entries(item).map(([k, v]) => [k, v ?? ''])) })
  return (
    <Modal title={item.id ? 'Edit registration' : 'New registration'} onClose={onClose} width={460}>
      <Select label="Registration" value={f.kind} onChange={set('kind')} options={kinds} /><Input label="Authority" value={f.authority} onChange={set('authority')} /><Input label="Identifier (ABN, state number — never a TFN)" value={f.identifier} onChange={set('identifier')} />
      <Input label="Registered on" type="date" value={f.registered_on} onChange={set('registered_on')} /><Input label="Cancelled on" type="date" value={f.cancelled_on} onChange={set('cancelled_on')} />
      <div className="flex gap-1" style={{ justifyContent: 'flex-end' }}><button className="btn btn-outline" onClick={onClose}>Cancel</button><button className="btn btn-primary" onClick={async () => { const b = { ...f }; delete b.id; delete b.active; if (await act(() => api.saveRegistration(b, item.id), 'Saved')) onSaved() }}>Save</button></div>
    </Modal>)
}
