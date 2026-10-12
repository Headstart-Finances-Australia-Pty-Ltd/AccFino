import React, { useRef } from 'react'
import * as api from '../lib/invApi.js'
import { act, Async, useLoad } from './kit.jsx'
import { fmtDate, saveBlob } from '../lib/format.js'

// Supporting records for one thing (contract notes, AMMA statements, contracts of sale, loan statements). Each file is stored with its SHA-256 and checked on every download.
export default function DocsPanel({ ownerType, ownerId, caps = [] }) {
  const q = useLoad(() => api.documents.list(ownerType, ownerId), [ownerType, ownerId])
  const input = useRef(null)
  const up = async e => {
    const f = e.target.files?.[0]
    if (!f) return
    if (await act(() => api.documents.upload(ownerType, ownerId, f.name, f), 'Uploaded')) q.reload()
    if (input.current) input.current.value = ''
  }
  return (
    <div>
      <div className="flex items-center justify-between" style={{ marginBottom: 6 }}><strong className="text-sm">Documents</strong>
        {caps.includes('edit') && <label className="btn btn-outline btn-sm" style={{ cursor: 'pointer', marginBottom: 0 }}>Attach file…<input ref={input} type="file" hidden aria-label="Attach document" onChange={up} /></label>}</div>
      <Async q={q}>{rows => rows.length === 0 ? <div className="text-xs text-muted">No documents attached. PDF, image, CSV or Excel up to 5 MB.</div> : rows.map(d => (
        <div key={d.id} className="flex items-center justify-between text-sm" style={{ padding: '3px 0', borderBottom: '1px solid var(--border)' }}>
          <span>{d.title} <span className="text-xs text-muted">· {Math.max(1, Math.round((d.size || 0) / 1024))} KB · {fmtDate(d.uploaded_at)} · sha256 {String(d.sha256).slice(0, 10)}…</span></span>
          <span className="flex gap-1"><button className="btn btn-ghost btn-xs" onClick={async () => { const b = await act(() => api.documents.download(d.id)); if (b && b !== true) saveBlob(d.file_name || d.title, b) }}>Download</button>
            {caps.includes('delete') && <button className="btn btn-ghost btn-xs" onClick={async () => { if (window.confirm(`Delete ${d.title}?`) && await act(() => api.documents.remove(d.id), 'Deleted')) q.reload() }}>Delete</button>}</span></div>))}</Async>
    </div>)
}
