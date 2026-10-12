import React, { useState } from 'react'
import * as api from '../lib/taxApi.js'
import { act, Async, DataGrid, Disclaimer, Findings, Input, KindTag, Modal, Money, Section, StatusBadge, usePrompt, useForm, useLoad, WorkflowBar, Check } from '../components/kit.jsx'
import { fmtDate, METHOD, saveBlob, todayISO } from '../lib/format.js'
import LodgementPanel, { useLodgement } from '../components/LodgementPanel.jsx'

const quarterOf = () => { const d = new Date(), q = Math.floor(d.getMonth() / 3), y = d.getFullYear(), s = new Date(Date.UTC(y, q * 3 - 3 < 0 ? 9 : q * 3 - 3, 1)); const sy = q === 0 ? y - 1 : y
  const e = new Date(Date.UTC(sy, s.getUTCMonth() + 3, 0)); return [new Date(Date.UTC(sy, s.getUTCMonth(), 1)).toISOString().slice(0, 10), e.toISOString().slice(0, 10)] }

export default function BasTab({ me, fy }) {
  const [open, setOpen] = useState(null)
  const [creating, setCreating] = useState(false)
  const q = useLoad(() => api.bas.list({ fy }), [fy])
  const can = me.capabilities.includes('prepare')
  if (open) return <Detail id={open} me={me} onBack={() => { setOpen(null); q.reload() }} />
  return (
    <div style={{ padding: 16 }}>
      <Disclaimer />
      <div className="flex items-center justify-between" style={{ marginBottom: 12, flexWrap: 'wrap', gap: 8 }}><h3 style={{ margin: 0 }}>Activity statements {fy}</h3>{can && <button className="btn btn-primary" onClick={() => setCreating(true)}>+ New BAS / IAS</button>}</div>
      <Async q={q}>{rows => <DataGrid rows={rows} empty="No activity statements for this year" hint="Create one for a period, then calculate it from the ledger." onRowClick={r => setOpen(r.id)}
        columns={[{ key: 'kind', label: 'Type', render: r => r.kind.toUpperCase() }, { key: 'period_start', label: 'Period', render: r => `${fmtDate(r.period_start)} – ${fmtDate(r.period_end)}` },
          { key: 'status', label: 'Status', render: r => <><StatusBadge status={r.status} />{r.has_errors && <span className="badge badge-danger" style={{ marginLeft: 4 }}>errors</span>}</> },
          { key: 'due_date', label: 'Due', date: true }, { key: 'amount_payable', label: 'Payable (label 9)', money: true }, { key: 'lodgement_reference', label: 'ATO reference' }]} />}</Async>
      {creating && <Create fy={fy} onClose={() => setCreating(false)} onDone={id => { setCreating(false); q.reload(); setOpen(id) }} />}
    </div>)
}

function Create({ fy, onClose, onDone }) {
  const [a, b] = quarterOf()
  const [f, set] = useForm({ period_start: a, period_end: b })
  const go = async () => { const r = await act(() => api.bas.create(f), 'Statement created'); if (r) onDone(r.id) }
  return (
    <Modal title="New activity statement" onClose={onClose} width={440}>
      <Input label="Period start" type="date" value={f.period_start} onChange={set('period_start')} /><Input label="Period end" type="date" value={f.period_end} onChange={set('period_end')} />
      <p className="text-xs text-muted">The statement type (BAS or IAS) follows the GST registration in your tax profile. Periods cannot overlap an existing statement.</p>
      <div className="flex gap-1" style={{ justifyContent: 'flex-end' }}><button className="btn btn-outline" onClick={onClose}>Cancel</button><button className="btn btn-primary" onClick={go}>Create</button></div>
    </Modal>)
}

function Detail({ id, me, onBack }) {
  const q = useLoad(() => api.bas.get(id), [id])
  const rd = useLoad(() => api.readiness('bas_statement', id), [id, q.data?.status, q.data?.version])
  const [dialog, ask] = usePrompt()
  const caps = me.capabilities
  const lg = useLodgement('bas_statement', id, q.data?.status)
  const after = () => { q.reload(); lg.reload() }
  const override = async (lb, cur) => { const r = await ask({ title: `Override label ${lb}`, message: `Current value ${cur}. Overrides are audited and need a workpaper.`, confirmLabel: 'Override',
    fields: [{ key: 'value', label: 'New value', type: 'number' }, { key: 'reason', label: 'Reason (at least 5 characters)' }] }); if (r.ok && await act(() => api.bas.override(id, { label: lb, ...r.values }), 'Override applied')) after() }
  const unover = async lb => { if (await act(() => api.bas.removeOverride(id, lb), 'Override removed')) after() }
  const workpaper = async () => { if (await act(() => api.workpapers.generate({ kind: 'bas_statement', doc_id: id }), 'Workpaper created (see Workpapers & Evidence)')) rd.reload() }
  const csv = async () => saveBlob(`bas_${id}.csv`, await api.exportCsv({ what: 'bas', doc_id: id }))
  return (
    <div style={{ padding: 16 }}>
      {dialog}
      <button className="btn btn-ghost btn-sm" onClick={onBack}>← All statements</button>
      <Async q={q}>{s => {
        const editable = ['draft', 'prepared'].includes(s.status)
        return (
          <>
            <h3 style={{ margin: '6px 0' }}>{s.kind.toUpperCase()} {fmtDate(s.period_start)} – {fmtDate(s.period_end)} <span className="text-sm text-muted">({s.basis} basis)</span></h3>
            <WorkflowBar doc={s} caps={caps} api={api.bas} noun="activity statement" onChange={after} declarationOk={lg.data ? lg.data.declaration_ok : undefined}
              extra={<><button className="btn btn-outline btn-sm" onClick={csv} disabled={!s.calculated}>Export CSV</button>{caps.includes('prepare') && s.calculated && <button className="btn btn-outline btn-sm" onClick={workpaper}>Create workpaper</button>}</>} />
            {s.lodgement_reference && <div className="text-sm">Lodged {fmtDate(s.lodged_on)} via {METHOD[s.lodgement_method] || s.lodgement_method} — reference <strong>{s.lodgement_reference}</strong>{s.paid_on && ` · paid ${fmtDate(s.paid_on)}`}</div>}
            {!s.calculated ? <p className="text-muted">Not calculated yet. Calculate pulls GST from the ledger and PAYG from payroll for this period.</p> : (
              <>
                <Section title="Labels" hint="Whole-dollar figures are for keying into the ATO form.">
                  <table className="data-table"><thead><tr><th>Label</th><th>Description</th><th>Basis</th><th className="text-right">Amount</th><th className="text-right">To lodge ($)</th><th /></tr></thead>
                    <tbody>{(s.label_order || Object.keys(s.final)).map(lb => [lb, s.final[lb]]).map(([lb, v]) => (
                      <tr key={lb}><td><strong>{lb}</strong></td><td>{s.label_names?.[lb] || ''}<div className="text-xs text-muted">{v.source}{v.note ? ` — ${v.note}` : ''}</div></td><td><KindTag kind={v.kind} /></td>
                        <td className="text-right"><Money v={v.value} strong={['8A', '8B', '9'].includes(lb)} /></td><td className="text-right mono">{s.lodgement_figures[lb]}</td>
                        <td>{editable && caps.includes('prepare') && !['8A', '8B', '9', 'W5', '4'].includes(lb) && <button className="btn btn-ghost btn-xs" onClick={() => override(lb, v.value)}>Override</button>}
                          {s.overrides?.[lb] && editable && <button className="btn btn-ghost btn-xs" onClick={() => unover(lb)}>Undo</button>}</td></tr>))}</tbody></table>
                </Section>
                <Section title="Checks and findings"><Findings items={s.findings} /></Section>
              </>)}
            <LodgementPanel st={lg} caps={caps} docType="bas_statement" docId={id} onChange={() => q.reload()} />
            <Async q={rd}>{r => <Section title="Lodgement readiness" hint="A checklist, not a submission.">{r.checks.map(c => <div key={c.key} className="text-sm" style={{ color: c.ok ? 'var(--success)' : 'var(--warning)' }}>{c.ok ? '✔' : '○'} {c.label}{!c.ok && c.detail ? <span className="text-xs text-muted"> — {c.detail}</span> : null}</div>)}</Section>}</Async>
          </>)
      }}</Async>
    </div>)
}
