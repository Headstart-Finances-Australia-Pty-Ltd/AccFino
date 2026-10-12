import React, { useState } from 'react'
import * as api from '../lib/taxApi.js'
import { act, Async, Check, Input, Modal, Section, Select, StatusBadge, useLoad } from './kit.jsx'
import { fmtDate, label, saveBlob } from '../lib/format.js'

const CAP = { taxpayer: 'Taxpayer / authorised person', tax_agent: 'Registered tax agent', bas_agent: 'Registered BAS agent' }

export function useLodgement(docType, docId, status) {
  return useLoad(() => api.lodgement.state(docType, docId), [docType, docId, status])
}

// Declarations, tax-agent sign-off and the lodgement route for one document. It states plainly what each route actually does: AccFino itself does not lodge with the ATO.
export default function LodgementPanel({ st, caps, docType, docId, onChange }) {
  const [signing, setSigning] = useState(false)
  const s = st.data
  if (!s) return null
  const approved = s.doc_status === 'approved'
  const done = ['lodged', 'paid'].includes(s.doc_status)
  if (!approved && !done && !s.signoffs.length && !s.lodgements.length) return null
  const can = caps.includes('lodge')
  const run = async (fn, ok) => { const r = await act(fn, ok); if (r) { st.reload(); onChange && onChange() } return r }
  const revoke = async so => { const reason = window.prompt(`Revoke the sign-off by ${so.signer_name}? Reason (at least 5 characters):`); if (reason) run(() => api.lodgement.revoke(so.id, reason), 'Sign-off revoked') }
  const pack = async () => { const r = await run(() => api.lodgement.submit(docType, docId, 'agent_pack'), 'Hand-off recorded'); if (r) saveBlob(`handoff_${docType}_${docId}.zip`, await api.lodgement.pack(docType, docId)) }
  const via = prov => run(() => api.lodgement.submit(docType, docId, prov), prov === 'sandbox' ? 'Simulated (nothing sent to the ATO)' : 'Submitted')
  const prov = Object.fromEntries(s.providers.map(p => [p.name, p]))
  return (
    <Section title="Sign-off & lodgement" hint="The declaration is recorded here. AccFino does not lodge with the ATO on its own: a route below does.">
      <div className="text-sm" style={{ marginBottom: 8 }}>
        <StatusBadge status={s.declaration_ok ? 'completed' : 'due_soon'} text={s.declaration_ok ? 'Declaration recorded' : 'Declaration needed'} />{' '}
        <span className="text-muted">{s.policy === 'agent_signoff_required' ? 'Policy: a registered agent must sign off' : 'Policy: the taxpayer or an agent may sign'}</span>
        {!s.declaration_ok && !done && <div style={{ marginTop: 4 }}>{s.requirement}</div>}
      </div>
      {s.signoffs.length > 0 && <table className="data-table" style={{ marginBottom: 10 }}><thead><tr><th>Signed by</th><th>Capacity</th><th>Agent no.</th><th>When</th><th>Status</th><th /></tr></thead>
        <tbody>{s.signoffs.map(so => <tr key={so.id}><td>{so.signer_name}</td><td>{CAP[so.capacity]}</td><td className="mono">{so.agent_number || '—'}</td><td>{fmtDate(so.signed_at)}</td>
          <td><StatusBadge status={so.status === 'valid' ? (so.counts ? 'completed' : 'due_soon') : 'void'} text={so.status === 'valid' && !so.counts ? 'Figures changed' : label(so.status)} /></td>
          <td>{so.status === 'valid' && approved && can && <button className="btn btn-ghost btn-xs" onClick={() => revoke(so)}>Revoke</button>}</td></tr>)}</tbody></table>}
      {approved && can && <div className="flex gap-1" style={{ flexWrap: 'wrap', marginBottom: 12 }}>
        <button className="btn btn-primary btn-sm" onClick={() => setSigning('taxpayer')}>Sign as taxpayer / authorised person</button>
        <button className="btn btn-outline btn-sm" onClick={() => setSigning('agent')}>Sign off as registered tax / BAS agent</button></div>}
      {approved && !can && <div className="text-xs text-muted">Only an Accountant or the Organisation Admin can sign off.</div>}
      {approved && s.declaration_ok && can && (
        <>
          <div className="text-sm" style={{ fontWeight: 600, margin: '8px 0 4px' }}>How will it be lodged?</div>
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit,minmax(240px,1fr))', gap: 10 }}>
            <Route title={prov.manual.label} text={prov.manual.description} note="Use Record lodgement above once you have the ATO receipt." />
            <Route title={prov.agent_pack.label} text={prov.agent_pack.description} action={<button className="btn btn-outline btn-sm" onClick={pack}>Prepare pack</button>} />
            <Route title={prov.sbr_gateway.label} text={prov.sbr_gateway.description} disabled={!prov.sbr_gateway.available} reason={prov.sbr_gateway.reason}
              action={<button className="btn btn-primary btn-sm" disabled={!prov.sbr_gateway.available} onClick={() => via('sbr_gateway')}>Lodge with the ATO</button>} />
            {prov.sandbox.available && <Route title={prov.sandbox.label} text={prov.sandbox.description} tone="warning" action={<button className="btn btn-outline btn-sm" onClick={() => via('sandbox')}>Run simulation</button>} />}
          </div></>)}
      {s.lodgements.length > 0 && <div style={{ marginTop: 12 }}><div className="text-sm" style={{ fontWeight: 600, marginBottom: 4 }}>Lodgement history</div>
        {s.lodgements.map(l => <div key={l.id} className="text-sm" style={{ padding: '2px 0' }}>{fmtDate(l.submitted_at)} · {label(l.provider)} · <StatusBadge status={l.simulated ? 'due_soon' : l.status === 'accepted' ? 'completed' : l.status === 'handed_off' ? 'in_progress' : 'overdue'} text={l.simulated ? 'SIMULATED — not lodged' : label(l.status)} />
          {l.receipt_reference && <span className="mono"> {l.receipt_reference}</span>} <span className="text-muted">{l.message}</span></div>)}</div>}
      {signing && <SignModal kind={signing} st={s} docType={docType} docId={docId} onClose={() => setSigning(false)} onDone={() => { setSigning(false); st.reload(); onChange && onChange() }} />}
    </Section>)
}

function Route({ title, text, action, note, disabled, reason, tone }) {
  return (
    <div className="card card-flat" style={{ padding: 10, opacity: disabled ? 0.8 : 1, borderColor: tone === 'warning' ? 'var(--warning)' : undefined }}>
      <div className="text-sm" style={{ fontWeight: 600 }}>{title}</div><div className="text-xs text-muted" style={{ margin: '4px 0 8px' }}>{text}</div>
      {disabled && <details className="text-xs" style={{ marginBottom: 6 }}><summary style={{ cursor: 'pointer' }}>Not available: why</summary><div className="text-muted" style={{ marginTop: 4 }}>{reason}</div></details>}
      {note && <div className="text-xs">{note}</div>}{action}
    </div>)
}

function SignModal({ kind, st, docType, docId, onClose, onDone }) {
  const [capacity, setCapacity] = useState(kind === 'agent' ? 'tax_agent' : 'taxpayer')
  const [name, setName] = useState('')
  const [num, setNum] = useState(kind === 'agent' ? (st.agent_number || '') : '')
  const [ok, setOk] = useState(false)
  const agent = capacity !== 'taxpayer'
  const numOk = !agent || /^\d{8}$/.test(num.replace(/\s/g, ''))
  const text = st.declarations[capacity].text
  const go = async () => { const r = await act(() => api.lodgement.sign({ doc_type: docType, doc_id: docId, capacity, typed_name: name, confirmed: ok, agent_number: agent ? num : '' }), 'Signed off'); if (r) onDone() }
  return (
    <Modal title={agent ? 'Agent sign-off' : 'Taxpayer declaration'} onClose={onClose} width={560}>
      {agent && <Select label="Capacity" value={capacity} onChange={e => setCapacity(e.target.value)} options={[{ value: 'tax_agent', label: 'Registered tax agent' }, { value: 'bas_agent', label: 'Registered BAS agent' }]} />}
      <div role="note" className="text-sm" style={{ background: 'var(--surface-2)', padding: 10, borderRadius: 8, margin: '6px 0 10px' }}>{text}<div className="text-xs text-muted" style={{ marginTop: 6 }}>Declaration version {st.declarations[capacity].version}. It is bound to the figures as they are now: if they change, you will need to sign again.</div></div>
      <Input label="Type your full name to sign" value={name} onChange={e => setName(e.target.value)} />
      {agent && <Input label="Agent registration number (8 digits)" value={num} onChange={e => setNum(e.target.value)} hint="Never enter a Tax File Number. AccFino records this as declared; verify it on the Tax Practitioners Board public register." />}
      <Check label="I confirm the declaration above" checked={ok} onChange={e => setOk(e.target.checked)} />
      <div className="flex gap-1" style={{ justifyContent: 'flex-end' }}><button className="btn btn-outline" onClick={onClose}>Cancel</button>
        <button className="btn btn-primary" disabled={!ok || name.trim().length < 3 || !numOk} onClick={go}>Sign</button></div>
    </Modal>)
}
