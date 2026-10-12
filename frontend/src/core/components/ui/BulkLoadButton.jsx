import React, { useEffect, useState } from 'react'
import toast from 'react-hot-toast'
import { Upload } from 'lucide-react'
import { http, errMsg } from '../../lib/platformHttp.js'
import { Modal } from './Common.jsx'

/**
 * BulkLoadButton - one CSV bulk-load window for any module that mounts the shared bulk router (accfino/shared/bulkload.py).
 * `base` is the router prefix, e.g. "/practice/bulk". The table list, columns, examples and permissions all come from the server,
 * so this screen can never drift from what the loader accepts. Flow: pick table -> download template -> choose file ->
 * "Check file" (full dry run, nothing saved) -> "Load" (all-or-nothing unless the box is unticked).
 * `areas` optionally limits the tables offered (so each tab shows only its own tables). Hidden when the feature is switched off.
 */
export function BulkLoadButton({ base, areas, label = 'Bulk load (CSV)', onDone }) {
  const [on, setOn] = useState(false)
  const [open, setOpen] = useState(false)
  useEffect(() => {
    let live = true
    http.get(`${base}/status`).then(r => { if (live) setOn(!!r.data?.enabled) }).catch(() => { if (live) setOn(false) })
    return () => { live = false }
  }, [base])
  if (!on) return null
  return (
    <>
      <button type="button" className="btn btn-outline btn-sm" onClick={() => setOpen(true)} title="Load many rows from a CSV file"><Upload size={14} /> {label}</button>
      {open && <BulkLoadModal base={base} areas={areas} onClose={loaded => { setOpen(false); if (loaded) onDone?.() }} />}
    </>
  )
}

export function BulkLoadModal({ base, areas, onClose }) {
  const [loaded, setLoaded] = useState(false)
  const [items, setItems] = useState(null)
  const [key, setKey] = useState('')
  const [file, setFile] = useState(null)
  const [strict, setStrict] = useState(true)
  const [res, setRes] = useState(null)
  const [busy, setBusy] = useState(false)

  useEffect(() => {
    http.get(base).then(r => {
      const all = (r.data?.items || []).filter(i => !areas || areas.includes(i.area))
      setItems(all)
      const first = all.find(i => i.allowed) || all[0]
      if (first) setKey(first.key)
    }).catch(e => { toast.error(errMsg(e)); setItems([]) })
  }, [base]) // eslint-disable-line

  const cur = (items || []).find(i => i.key === key)
  const pick = k => { setKey(k); setRes(null); setFile(null) }

  const template = async () => {
    try {
      const r = await http.get(`${base}/${key}/template`, { responseType: 'blob' })
      const url = URL.createObjectURL(r.data)
      const a = document.createElement('a'); a.href = url; a.download = `${key}-template.csv`; a.click(); URL.revokeObjectURL(url)
    } catch (e) { toast.error(errMsg(e)) }
  }
  const run = async apply => {
    if (!file || !cur) return
    setBusy(true)
    try {
      const fd = new FormData(); fd.append('file', file); fd.append('apply', apply ? 'true' : 'false'); fd.append('strict', strict ? 'true' : 'false')
      const r = await http.post(`${base}/${key}`, fd)
      setRes(r.data)
      if (apply) {
        if (r.data.file_error) toast.error(r.data.file_error)
        else if (r.data.applied > 0) { toast.success(`${r.data.applied} row(s) loaded`); setLoaded(true) }
        else toast.error('Nothing was loaded - see the row messages')
      }
    } catch (e) { toast.error(errMsg(e)); setRes(null) } finally { setBusy(false) }
  }

  const checked = res && res.dry_run
  const canLoad = checked && !res.file_error && res.valid_rows > 0 && (!strict || res.rejected.length === 0)
  return (
    <Modal title="Bulk load from CSV" onClose={() => onClose(loaded)} width={760}>
      {items === null ? <div role="status">Loading…</div> : items.length === 0 ? <div className="text-muted">No tables are available for bulk loading here.</div> : (
        <div style={{ display: 'grid', gap: 12 }}>
          <label className="text-sm">Table
            <select className="input" aria-label="Table to load" value={key} onChange={e => pick(e.target.value)} style={{ display: 'block', width: '100%' }}>
              {items.map(i => <option key={i.key} value={i.key} disabled={!i.allowed}>{i.label}{i.allowed ? '' : ' (no permission)'}</option>)}
            </select>
          </label>
          {cur && (
            <>
              {cur.notes && <div className="text-sm text-muted">{cur.notes}</div>}
              <details>
                <summary className="text-sm">Columns ({cur.columns.length})</summary>
                <table className="table text-xs" style={{ marginTop: 6 }}>
                  <thead><tr><th>Column</th><th>Required</th><th>Allowed / notes</th><th>Example</th></tr></thead>
                  <tbody>{cur.columns.map(c => <tr key={c.name}><td><code>{c.name}</code></td><td>{c.required ? 'Yes' : 'No'}</td><td>{c.help}</td><td>{c.example}</td></tr>)}</tbody>
                </table>
              </details>
              <div className="flex items-center gap-1" style={{ flexWrap: 'wrap' }}>
                <button type="button" className="btn btn-outline btn-sm" onClick={template}>Download template</button>
                <input type="file" accept=".csv,text/csv" aria-label="CSV file" onChange={e => { setFile(e.target.files?.[0] || null); setRes(null) }} />
              </div>
              <label className="text-sm"><input type="checkbox" checked={strict} onChange={e => { setStrict(e.target.checked); setRes(null) }} /> All or nothing (load nothing if any row has a problem)</label>
              <div className="flex gap-1">
                <button type="button" className="btn btn-outline" disabled={!file || busy || !cur.allowed} onClick={() => run(false)}>{busy && !checked ? 'Checking…' : 'Check file'}</button>
                <button type="button" className="btn btn-primary" disabled={!canLoad || busy} onClick={() => run(true)}>Load</button>
              </div>
            </>
          )}
          {res && <BulkResult res={res} />}
        </div>
      )}
    </Modal>
  )
}

function BulkResult({ res }) {
  if (res.file_error) return <div role="alert" className="alert alert-error">{res.file_error}</div>
  return (
    <div role="status" aria-live="polite">
      <div className={`alert ${res.rejected.length ? 'alert-warning' : 'alert-success'}`}>
        {res.dry_run
          ? `Check only - nothing saved. ${res.valid_rows} row(s) can be loaded, ${res.rejected.length} row(s) have a problem.`
          : `${res.applied} row(s) loaded, ${res.rejected.length} row(s) not loaded.`}
        {res.note ? ` ${res.note}` : ''}
      </div>
      {res.ignored_columns?.length > 0 && <div className="text-xs text-muted">Ignored columns: {res.ignored_columns.join(', ')}</div>}
      {res.rejected.length > 0 && (
        <table className="table text-xs" style={{ marginTop: 6 }}>
          <thead><tr><th>Row</th><th>Problem</th></tr></thead>
          <tbody>{res.rejected.slice(0, 200).map(x => <tr key={x.row}><td>{x.row}</td><td>{x.error}</td></tr>)}</tbody>
        </table>
      )}
    </div>
  )
}
