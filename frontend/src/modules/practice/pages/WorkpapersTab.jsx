import React, { useRef, useState } from 'react'
import { BulkLoadButton } from '../../../core/components/ui/BulkLoadButton.jsx'
import { Async, Section, Table, StatusBadge, useLoad, act, Input, Select, useForm, Modal } from '../components/kit.jsx'
import * as api from '../lib/practiceApi.js'
import { saveBlob } from '../lib/useMe.js'
import { fmtDate, label } from '../lib/format.js'

const CATS = ['general', 'tax_return', 'financial_statements', 'bank_statement', 'invoice_receipt', 'payroll', 'correspondence', 'engagement_letter', 'identification', 'workpaper_evidence', 'other']
const NEXT = { draft: ['start'], in_preparation: ['submit'], ready_for_review: ['start_review', 'withdraw'], review_in_progress: ['request_changes', 'finalise'], changes_required: [], finalised: ['reopen'] }
const ACTION_CAP = { start: 'wp_prepare', submit: 'wp_prepare', withdraw: 'wp_prepare', start_review: 'wp_review', request_changes: 'wp_review', finalise: 'wp_review', reopen: 'wp_reopen' }

function WorkpaperView({ id, can, onClose, onChanged }) {
  const q = useLoad(() => api.workpapers.get(id), [id])
  const [c, setC] = useForm({ body: '', mandatory: false })
  const [line, setLine] = useForm({ label: '', amount: '', kind: 'user_entered' })
  return (
    <Modal title="Workpaper" onClose={onClose} wide>
      <Async q={q}>{w => {
        const lines = w.content?.lines || []
        const editable = ['draft', 'in_preparation', 'changes_required'].includes(w.status)
        const save = async content => { if (await act(() => api.workpapers.save(id, { content, expected_version: w.version }), 'Saved')) { q.reload(); onChanged() } }
        const go = async (action) => {
          const reason = ['request_changes', 'reopen'].includes(action) ? window.prompt('Reason (required)', '') : ''
          if (reason === null) return
          if (await act(() => api.workpapers.transition(id, action, reason), label(action))) { q.reload(); onChanged() }
        }
        return (
          <>
            <h4 style={{ margin: 0 }}>{w.title} <StatusBadge status={w.status} /></h4>
            <div className="text-xs text-muted">Version {w.version} · {w.status === 'finalised' ? <>Hash {w.content_hash?.slice(0, 12)}… {w.integrity.intact ? '✓ intact' : '⚠ content changed since finalisation'}</> : 'not finalised'}</div>
            <Section title="Lines">
              <Table caption="Workpaper lines" rows={lines.map((l, i) => ({ ...l, id: i }))} empty="No lines" columns={[{ key: 'label', label: 'Item' }, { key: 'kind', label: 'Basis', render: r => label(r.kind) }, { key: 'amount', label: 'Amount', align: 'right' }, { key: 'note', label: 'Note' }]} />
              {editable && can('wp_prepare') && <div className="flex items-center gap-1" style={{ flexWrap: 'wrap' }}><Input label="Item" value={line.label} onChange={setLine('label')} /><Input label="Amount" value={line.amount} onChange={setLine('amount')} />
                <Select label="Basis" value={line.kind} onChange={setLine('kind')} options={['source', 'calculated', 'user_entered', 'assumption', 'estimate', 'review']} />
                <button className="btn btn-outline btn-sm" disabled={!line.label} onClick={() => save({ ...w.content, lines: [...lines, line] })}>Add line</button></div>}
            </Section>
            <Section title="Review points and queries">
              {w.comments.map(k => <div key={k.id} className="text-sm" style={{ marginBottom: 4 }}><StatusBadge status={k.status === 'open' ? 'new' : 'resolved'} text={k.status} /> {k.mandatory && <b>[mandatory] </b>}<span className="text-muted">{k.kind}</span> {k.body}
                {k.status === 'open' && w.status !== 'finalised' && can('wp_prepare') && <button className="btn btn-outline btn-sm" style={{ marginLeft: 8 }} onClick={async () => { if (await act(() => api.workpapers.resolve(id, k.id), 'Resolved')) q.reload() }}>Resolve</button>}</div>)}
              {w.status !== 'finalised' && can('wp_prepare') && <div className="flex gap-1"><input className="input" aria-label="Comment" placeholder="Comment or query" value={c.body} onChange={setC('body')} />
                {can('wp_review') && <label className="text-sm"><input type="checkbox" checked={c.mandatory} onChange={setC('mandatory')} /> Mandatory</label>}
                <button className="btn btn-outline btn-sm" disabled={!c.body} onClick={async () => { if (await act(() => api.workpapers.comment(id, { body: c.body, mandatory: c.mandatory }), 'Added')) { setC('body')(''); q.reload() } }}>Add</button></div>}
            </Section>
            <Section title="Evidence and references"><div className="text-sm">{w.documents.length} document(s) attached · {w.refs.length} reference(s) to ledger records</div>
              {w.refs.length > 0 && <button className="btn btn-outline btn-sm" onClick={async () => { const r = await act(() => api.workpapers.checkRefs(id)); if (r) window.alert(r.map(x => `${label(x.kind)}: ${x.changed ? 'CHANGED since seen' : 'unchanged'}`).join('\n')) }}>Check references for changes</button>}</Section>
            <div className="flex gap-1">{(NEXT[w.status] || []).filter(a => can(ACTION_CAP[a])).map(a => <button key={a} className="btn btn-primary btn-sm" onClick={() => go(a)}>{label(a)}</button>)}</div>
          </>)
      }}</Async>
    </Modal>)
}

export default function WorkpapersTab({ can }) {
  const [view, setView] = useState('workpapers')
  const [status, setStatus] = useState('')
  const wps = useLoad(() => api.workpapers.list({ status: status || undefined, size: 50 }), [status])
  const docs = useLoad(() => api.documents.list({ size: 50 }), [])
  const [open, setOpen] = useState(null)
  const [nw, setNw] = useForm({ client_id: '', title: '' })
  const [nd, setNd] = useForm({ client_id: '', category: 'general', shared: false })
  const file = useRef(null)
  return (
    <div style={{ padding: 16 }}>
      <div style={{ display: 'flex', justifyContent: 'flex-end', marginBottom: 8 }}><BulkLoadButton base="/practice/bulk" areas={["Workpapers"]} onDone={() => window.location.reload()} /></div>
      <div className="tabs-bar" style={{ marginBottom: 12 }}>{['workpapers', 'documents'].map(v => <button key={v} className={`tab-btn${view === v ? ' active' : ''}`} onClick={() => setView(v)}>{label(v)}</button>)}</div>
      {view === 'workpapers' && <>
        <div className="flex items-center gap-1" style={{ flexWrap: 'wrap', marginBottom: 8 }}>
          <Select label="Status" value={status} onChange={e => setStatus(e.target.value)} options={['draft', 'in_preparation', 'ready_for_review', 'review_in_progress', 'changes_required', 'finalised']} blank="All" />
          {can('wp_prepare') && <><Input label="Client id" type="number" value={nw.client_id} onChange={setNw('client_id')} /><Input label="Title" value={nw.title} onChange={setNw('title')} />
            <button className="btn btn-primary btn-sm" disabled={!nw.client_id || !nw.title} onClick={async () => { if (await act(() => api.workpapers.create({ client_id: Number(nw.client_id), title: nw.title }), 'Workpaper created')) wps.reload() }}>New workpaper</button></>}
        </div>
        <Async q={wps}>{d => <Table caption="Workpapers" rows={d.items} empty="No workpapers" onRowClick={r => setOpen(r.id)} columns={[{ key: 'title', label: 'Title' }, { key: 'client_id', label: 'Client' }, { key: 'status', label: 'Status', render: r => <StatusBadge status={r.status} /> },
          { key: 'version', label: 'Ver.' }, { key: 'updated_at', label: 'Updated', date: true }]} />}</Async></>}
      {view === 'documents' && <>
        {can('docs') && <div className="flex items-center gap-1" style={{ flexWrap: 'wrap', marginBottom: 8 }}><Input label="Client id" type="number" value={nd.client_id} onChange={setNd('client_id')} /><Select label="Category" value={nd.category} onChange={setNd('category')} options={CATS} />
          <label className="text-sm"><input type="checkbox" checked={nd.shared} onChange={setNd('shared')} /> Share with client portal</label>
          <input ref={file} type="file" aria-label="Choose file" style={{ display: 'none' }} onChange={async e => { const f = e.target.files[0]; if (f && nd.client_id && await act(() => api.documents.upload(Number(nd.client_id), f, { category: nd.category, shared_with_portal: nd.shared }), 'Uploaded')) docs.reload(); e.target.value = '' }} />
          <button className="btn btn-primary btn-sm" disabled={!nd.client_id} onClick={() => file.current.click()}>Upload</button></div>}
        <Async q={docs}>{d => <Table caption="Documents" rows={d.items} empty="No documents" columns={[{ key: 'title', label: 'Title' }, { key: 'category', label: 'Category', render: r => label(r.category) }, { key: 'file_name', label: 'File' },
          { key: 'size', label: 'Size', render: r => `${Math.ceil((r.size || 0) / 1024)} KB` }, { key: 'sha256', label: 'SHA-256', render: r => <span className="mono">{r.sha256?.slice(0, 10)}…</span> }, { key: 'shared_with_portal', label: 'Portal', render: r => (r.shared_with_portal ? 'Shared' : 'Private') },
          { key: 'uploaded_at', label: 'Uploaded', date: true }, { key: 'x', label: '', render: r => (
            <span className="flex gap-1"><button className="btn btn-outline btn-sm" onClick={async () => { const f = await act(() => api.documents.download(r.id)); if (f) saveBlob(f.name, f.blob) }}>Download</button>
              {can('docs') && <button className="btn btn-outline btn-sm" onClick={async () => { if (await act(() => api.documents.archive(r.id), 'Archived')) docs.reload() }}>Archive</button>}
              {can('docs_delete') && <button className="btn btn-outline btn-sm" onClick={async () => { const why = window.prompt('Reason for deletion', ''); if (why && await act(() => api.documents.remove(r.id, why), 'Deleted')) docs.reload() }}>Delete</button>}</span>) }]} />}</Async></>}
      {open && <WorkpaperView id={open} can={can} onClose={() => setOpen(null)} onChanged={wps.reload} />}
    </div>)
}
