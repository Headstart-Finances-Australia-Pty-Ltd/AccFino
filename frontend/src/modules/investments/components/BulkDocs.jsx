import React, { useRef, useState } from 'react'
import * as api from '../lib/invApi.js'
import { act, Modal, StatusBadge } from './kit.jsx'
import { saveBlob } from '../lib/format.js'

const BADGE = { ok: ['completed', 'Valid'], duplicate: ['in_progress', 'Duplicate: skipped'], error: ['overdue', 'Rejected'] }

// Bulk upload of supporting documents: the FILES plus one MANIFEST CSV (file_name, owner_type, owner, title) saying what each belongs to. A CSV cannot carry files, so the manifest is how many files are attached in one go.
export default function BulkDocs({ caps = [], onDone }) {
  const [open, setOpen] = useState(false)
  const [manifest, setManifest] = useState(null)
  const [files, setFiles] = useState([])
  const [pv, setPv] = useState(null)
  const [mode, setMode] = useState('valid_only')
  const [result, setResult] = useState(null)
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState('')
  const m = useRef(null), f = useRef(null)
  const reset = () => { setManifest(null); setFiles([]); setPv(null); setResult(null); setErr(''); setMode('valid_only') }
  const close = () => { setOpen(false); reset() }
  const check = async () => { setBusy(true); setErr(''); setPv(null); try { setPv(await api.documents.bulkPreview(manifest, files)) } catch (e) { setErr(api.errMsg(e)) } finally { setBusy(false) } }
  const run = async () => { setBusy(true); const r = await act(() => api.documents.bulkCommit(manifest, files, mode)); setBusy(false); if (r && r !== true) setResult(r) }
  if (!caps.includes('edit')) return null
  return (
    <>
      <button className="btn btn-outline btn-sm" onClick={() => setOpen(true)} aria-haspopup="dialog">⬆ Bulk upload documents</button>
      {open && (
        <Modal title="Bulk upload documents" onClose={close} width={900}>
          <div className="text-sm text-muted" style={{ marginBottom: 8 }}>Choose the manifest CSV and the files it lists. Each manifest row names a file and what it belongs to: a security (its CODE), an account, property, liability or other asset (its NAME) or a transaction (its REFERENCE). PDF, PNG, JPEG, CSV, TXT or XLSX, up to 5 MB each, 50 files at a time.</div>
          <div className="flex gap-1 items-center" style={{ flexWrap: 'wrap', marginBottom: 10 }}>
            <button className="btn btn-outline btn-sm" onClick={async () => { const b = await act(() => api.documents.bulkTemplate()); if (b && b !== true) saveBlob('template_documents_manifest.csv', b) }}>Download manifest template</button>
            <label className="btn btn-outline btn-sm" style={{ cursor: 'pointer', marginBottom: 0 }}>Choose manifest CSV…<input ref={m} type="file" accept=".csv,text/csv" hidden aria-label="Manifest CSV" onChange={e => { setManifest(e.target.files?.[0] || null); setPv(null); setResult(null) }} /></label>
            <label className="btn btn-outline btn-sm" style={{ cursor: 'pointer', marginBottom: 0 }}>Choose files…<input ref={f} type="file" multiple hidden aria-label="Document files" onChange={e => { setFiles(Array.from(e.target.files || [])); setPv(null); setResult(null) }} /></label>
            <button className="btn btn-primary btn-sm" disabled={!manifest || files.length === 0 || busy} onClick={check}>Check files</button>
            {busy && <span role="status" className="text-sm text-muted">Working…</span>}
          </div>
          <div className="text-xs text-muted">{manifest ? `Manifest: ${manifest.name}` : 'No manifest chosen'} · {files.length} file{files.length === 1 ? '' : 's'} chosen</div>
          {err && <div role="alert" className="alert alert-error">{err}</div>}
          {pv?.file_error && <div role="alert" className="alert alert-error">{pv.file_error}</div>}
          {pv && !pv.file_error && !result && (
            <>
              <div className="flex gap-1" style={{ flexWrap: 'wrap', margin: '8px 0' }} aria-label="Preview summary"><span className="badge badge-neutral">{pv.total} row(s) read</span><span className="badge badge-success">{pv.ok} valid</span><span className="badge badge-info">{pv.duplicates} duplicate(s)</span><span className={`badge ${pv.errors ? 'badge-danger' : 'badge-neutral'}`}>{pv.errors} with errors</span></div>
              {pv.unused_files?.length > 0 && <div className="text-sm" style={{ color: 'var(--warning)' }}>▲ Not in the manifest, so not uploaded: {pv.unused_files.join(', ')}</div>}
              <div style={{ maxHeight: 280, overflow: 'auto', marginTop: 6 }}><table className="data-table"><thead><tr><th>Line</th><th>Result</th><th>File</th><th>Belongs to</th><th>Details</th></tr></thead>
                <tbody>{pv.rows.map(r => <tr key={r.line}><td>{r.line}</td><td><StatusBadge status={BADGE[r.status][0]} text={BADGE[r.status][1]} /></td><td className="text-xs">{r.data.file_name}</td><td className="text-xs">{r.data.owner_type} · {r.data.owner}</td>
                  <td>{r.messages.map((x, i) => <div key={i} className="text-xs" style={{ color: x.level === 'error' ? 'var(--danger)' : 'var(--text-muted)' }}>{x.text}</div>)}</td></tr>)}</tbody></table></div>
              <fieldset style={{ border: 0, padding: 0, margin: '10px 0' }}><legend className="text-sm" style={{ fontWeight: 600 }}>If some rows are rejected</legend>
                <label className="text-sm" style={{ display: 'block' }}><input type="radio" name="bdmode" checked={mode === 'valid_only'} onChange={() => setMode('valid_only')} /> Upload the valid files only and report the rest</label>
                <label className="text-sm" style={{ display: 'block' }}><input type="radio" name="bdmode" checked={mode === 'all_or_nothing'} onChange={() => setMode('all_or_nothing')} /> All or nothing: upload nothing unless every row is valid</label></fieldset>
              {mode === 'all_or_nothing' && pv.errors > 0 && <div className="text-sm" style={{ color: 'var(--danger)' }}>Nothing will be uploaded while {pv.errors} row(s) have errors.</div>}
              <div className="flex gap-1" style={{ justifyContent: 'flex-end' }}><button className="btn btn-outline" onClick={close}>Cancel</button><button className="btn btn-primary" disabled={busy || !pv.can_commit || (mode === 'all_or_nothing' && pv.errors > 0)} onClick={run}>Upload {pv.ok} valid file{pv.ok === 1 ? '' : 's'}</button></div>
            </>)}
          {result && (
            <div role="status" aria-label="Upload result">
              <div className="alert alert-info"><strong>Upload complete.</strong> {result.uploaded} uploaded · {result.skipped_duplicates} duplicate(s) skipped · {result.rejected} rejected · {result.failed.length} failed.<div className="text-xs">Recorded in the audit trail with the manifest's SHA-256 ({result.file_sha256.slice(0, 12)}…).</div></div>
              {result.rows.filter(r => r.status === 'error').slice(0, 20).map(r => <div key={r.line} className="text-xs" style={{ color: 'var(--danger)' }}>Line {r.line} rejected: {r.messages[0]?.text}</div>)}
              <div className="flex gap-1" style={{ justifyContent: 'flex-end', marginTop: 10 }}><button className="btn btn-primary" onClick={() => { close(); onDone && onDone(result) }}>Done</button></div>
            </div>)}
          {!result && (!pv || pv.file_error) && <div className="flex gap-1" style={{ justifyContent: 'flex-end', marginTop: 10 }}><button className="btn btn-outline" onClick={close}>Close</button></div>}
        </Modal>)}
    </>)
}
