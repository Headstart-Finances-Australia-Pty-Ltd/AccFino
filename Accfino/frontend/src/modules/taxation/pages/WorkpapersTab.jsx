import React, { useState } from 'react'
import * as api from '../lib/taxApi.js'
import { act, Async, DataGrid, Disclaimer, Input, KindTag, Modal, Money, Section, Select, StatusBadge, useForm, useLoad, usePrompt } from '../components/kit.jsx'
import { fmtDate, label, saveBlob } from '../lib/format.js'
import ImportPanel from '../components/ImportPanel.jsx'
import HistoryButton from '../components/HistoryButton.jsx'

export default function WorkpapersTab({ me, fy }) {
  const [open, setOpen] = useState(null)
  const [creating, setCreating] = useState(false)
  const q = useLoad(() => api.workpapers.list({ fy }), [fy])
  const ref = useLoad(() => api.reference(fy), [fy])
  const can = me.capabilities.includes('prepare')
  if (open) return <Editor id={open} me={me} onBack={() => { setOpen(null); q.reload() }} />
  return (
    <div style={{ padding: 16 }}>
      <Disclaimer />
      <div className="flex items-center justify-between" style={{ marginBottom: 12, flexWrap: 'wrap', gap: 8 }}><h3 style={{ margin: 0 }}>Workpapers {fy}</h3><div className="flex gap-1"><ImportPanel datasets={[{ key: 'workpapers', label: 'Workpapers (headers)' }, { key: 'workpaper_lines', label: 'Workpaper lines' }, { key: 'workpaper_evidence', label: 'Workpaper evidence register' }]} caps={me.capabilities} onDone={q.reload} />{can && <button className="btn btn-primary" onClick={() => setCreating(true)}>+ New workpaper</button>}</div></div>
      <p className="text-xs text-muted">Generate a workpaper from a BAS, return or FBT return to capture the working behind every figure. Create workpapers from the document screens, or add a free-form one here.</p>
      <Async q={q}>{rows => <DataGrid rows={rows} searchKeys={['title', 'reference']} empty="No workpapers for this year" onRowClick={w => setOpen(w.id)} columns={[{ key: 'reference', label: 'Ref' }, { key: 'title', label: 'Title' }, { key: 'area', label: 'Area', render: w => label(w.area) },
        { key: 'status', label: 'Status', render: w => <StatusBadge status={w.status} /> }, { key: 'evidence_count', label: 'Evidence' }, { key: 'updated_at', label: 'Updated', date: true }]} />}</Async>
      {creating && <Create fy={fy} areas={ref.data?.workpaper_areas || ['general']} onClose={() => setCreating(false)} onDone={id => { setCreating(false); q.reload(); setOpen(id) }} />}
    </div>)
}

function Create({ fy, areas, onClose, onDone }) {
  const [f, set] = useForm({ title: '', area: 'general', reference: '' })
  return (
    <Modal title="New workpaper" onClose={onClose} width={440}>
      <Input label="Title" value={f.title} onChange={set('title')} /><Select label="Area" value={f.area} onChange={set('area')} options={areas} /><Input label="Reference" value={f.reference} onChange={set('reference')} />
      <div className="flex gap-1" style={{ justifyContent: 'flex-end' }}><button className="btn btn-outline" onClick={onClose}>Cancel</button><button className="btn btn-primary" disabled={!f.title.trim()} onClick={async () => { const r = await act(() => api.workpapers.save({ ...f, fy }), 'Created'); if (r) onDone(r.id) }}>Create</button></div>
    </Modal>)
}

function Editor({ id, me, onBack }) {
  const q = useLoad(() => api.workpapers.get(id), [id])
  const [dialog, ask] = usePrompt()
  const [lines, setLines] = useState(null)
  const [concl, setConcl] = useState('')
  const caps = me.capabilities
  const [loaded, setLoaded] = useState(null)
  const advance = async to => { let note = ''; if (to === 'reviewed') { const r = await ask({ title: 'Review workpaper', confirmLabel: 'Mark reviewed', fields: [{ key: 'note', label: 'Review note', required: false }] }); if (!r.ok) return; note = r.values.note }
    if (await act(() => api.workpapers.advance(id, { to, note }), `Workpaper ${to}`)) { setLoaded(null); q.reload() } }
  const upload = async (w, e) => { const file = e.target.files?.[0]; if (!file) return; if (await act(() => api.evidence.add({ workpaper_id: w.id, title: file.name, file }), 'Evidence added')) q.reload(); e.target.value = '' }
  const addNote = async w => { const r = await ask({ title: 'Add evidence', confirmLabel: 'Add', fields: [{ key: 'title', label: 'Title' }, { key: 'kind', label: 'Kind: note, url or ledger_ref', value: 'note' }, { key: 'note', label: 'Note', required: false }, { key: 'url', label: 'URL (https://…)', required: false }, { key: 'ledger_ref', label: 'Ledger reference (e.g. journal:42)', required: false }] }); if (r.ok && await act(() => api.evidence.add({ workpaper_id: w.id, ...r.values }), 'Evidence added')) q.reload() }
  const dl = async e => saveBlob(e.file_name || 'evidence', await api.evidence.download(e.id))
  return (
    <div style={{ padding: 16 }}>
      {dialog}
      <button className="btn btn-ghost btn-sm" onClick={onBack}>← All workpapers</button>
      <Async q={q}>{w => {
        const key = w.id + ':' + w.updated_at
        if (loaded !== key) { setLoaded(key); setLines(w.content?.lines || []); setConcl(w.content?.conclusion || '') }
        const editable = w.status === 'draft' && caps.includes('prepare')
        const save = async () => { if (await act(() => api.workpapers.save({ area: w.area, fy: w.fy, title: w.title, reference: w.reference, linked_type: w.linked_type, linked_id: w.linked_id, content: { lines, conclusion: concl } }, w.id), 'Saved')) { setLoaded(null); q.reload() } }
        const setLine = (i, k) => e => setLines(ls => ls.map((l, j) => (j === i ? { ...l, [k]: e.target.value } : l)))
        return (
          <>
            <h3 style={{ margin: '6px 0' }}>{w.reference} {w.title} <StatusBadge status={w.status} /> <HistoryButton type="tax_workpaper" id={w.id} caps={caps} /></h3>
            <div className="flex gap-1" style={{ marginBottom: 8, flexWrap: 'wrap' }}>
              {w.status === 'draft' && caps.includes('prepare') && <button className="btn btn-primary btn-sm" onClick={() => advance('prepared')}>Mark prepared</button>}
              {w.status === 'prepared' && caps.includes('approve') && <button className="btn btn-primary btn-sm" onClick={() => advance('reviewed')}>Review</button>}
              {w.status === 'reviewed' && caps.includes('approve') && <button className="btn btn-primary btn-sm" onClick={() => advance('approved')}>Approve</button>}
              {['prepared', 'reviewed', 'approved'].includes(w.status) && caps.includes('prepare') && <button className="btn btn-outline btn-sm" onClick={() => advance('draft')}>Reopen</button>}
              {editable && <button className="btn btn-outline btn-sm" onClick={save}>Save changes</button>}
            </div>
            {w.review_note && <div className="text-sm">Review note: {w.review_note}</div>}
            <Section title="Working" actions={editable && <button className="btn btn-outline btn-sm" onClick={() => setLines(ls => [...ls, { label: '', amount: '', kind: 'user_entered', source: '', note: '' }])}>+ Line</button>}>
              <table className="data-table"><thead><tr><th>Item</th><th>Basis</th><th className="text-right">Amount</th><th>Source / note</th></tr></thead>
                <tbody>{(lines || []).map((l, i) => <tr key={i}><td>{editable ? <input className="input input-sm" aria-label={`Item ${i + 1}`} value={l.label} onChange={setLine(i, 'label')} /> : l.label}</td>
                  <td>{editable ? <select className="input input-sm" aria-label={`Basis ${i + 1}`} value={l.kind} onChange={setLine(i, 'kind')}>{['source', 'calculated', 'user_entered', 'assumption', 'estimate', 'review'].map(k => <option key={k} value={k}>{label(k)}</option>)}</select> : <KindTag kind={l.kind} />}</td>
                  <td className="text-right">{editable ? <input className="input input-sm" type="number" aria-label={`Amount ${i + 1}`} value={l.amount ?? ''} onChange={setLine(i, 'amount')} /> : l.amount == null || l.amount === '' ? '—' : <Money v={l.amount} />}</td>
                  <td>{editable ? <input className="input input-sm" aria-label={`Note ${i + 1}`} value={l.note || l.source || ''} onChange={setLine(i, 'note')} /> : <span className="text-xs">{l.source}{l.note ? ` — ${l.note}` : ''}</span>}</td></tr>)}</tbody></table>
              <div style={{ marginTop: 10 }}><label className="text-sm" htmlFor="concl">Conclusion</label><textarea id="concl" className="input" rows={3} style={{ width: '100%' }} disabled={!editable} value={concl} onChange={e => setConcl(e.target.value)} /></div>
            </Section>
            <Section title="Supporting evidence" actions={w.status !== 'approved' && caps.includes('evidence') && <><button className="btn btn-outline btn-sm" onClick={() => addNote(w)}>+ Note / link</button><label className="btn btn-outline btn-sm" style={{ cursor: 'pointer' }}>Upload file<input type="file" hidden onChange={e => upload(w, e)} accept=".pdf,.png,.jpg,.jpeg,.csv,.txt,.xlsx,.docx" /></label></>}
              hint="PDF, image, CSV, text, Excel or Word up to 5 MB. Files are stored with a SHA-256 fingerprint.">
              <DataGrid rows={w.evidence} empty="No evidence attached" columns={[{ key: 'title', label: 'Title' }, { key: 'kind', label: 'Kind', render: e => label(e.kind) }, { key: 'detail', label: 'Detail', render: e => e.url || e.ledger_ref || e.note || (e.size ? `${Math.round(e.size / 1024)} KB` : '') },
                { key: 'created_at', label: 'Added', date: true }, { key: 'x', label: '', render: e => <span className="flex gap-1">{e.kind === 'file' && <button className="btn btn-ghost btn-xs" onClick={() => dl(e)}>Download</button>}
                  {w.status !== 'approved' && caps.includes('evidence') && <button className="btn btn-ghost btn-xs" onClick={async () => { if (await act(() => api.evidence.remove(e.id), 'Removed')) q.reload() }}>Remove</button>}</span> }]} />
            </Section>
          </>)
      }}</Async>
    </div>)
}
