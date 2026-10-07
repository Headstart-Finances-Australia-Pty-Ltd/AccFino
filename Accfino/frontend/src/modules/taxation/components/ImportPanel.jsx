import React, { useEffect, useMemo, useRef, useState } from 'react'
import * as api from '../lib/taxApi.js'
import { act, Modal, Select, StatusBadge } from './kit.jsx'
import { label, saveBlob } from '../lib/format.js'

let CATALOGUE = null                      // fetched once per page load: the importers' own column definitions drive the on-screen guidance
const loadCatalogue = () => (CATALOGUE ? Promise.resolve(CATALOGUE) : api.imports.catalogue().then(c => (CATALOGUE = Object.fromEntries(c.map(x => [x.key, x]))))).catch(() => ({}))
export const resetImportCatalogue = () => { CATALOGUE = null }

const LEVEL = { error: 'var(--danger)', warning: 'var(--warning)', info: 'var(--text-muted)' }
const rowBadge = { ok: ['completed', 'Valid'], duplicate: ['in_progress', 'Duplicate: skipped'], error: ['overdue', 'Rejected'] }

// Bulk upload / import CSV for one or more datasets of a module. PREVIEW first (nothing is written), then import. Valid rows only, or all-or-nothing.
export default function ImportPanel({ datasets, caps = [], onDone, buttonLabel = 'Bulk upload / Import CSV', small = false }) {
  const [open, setOpen] = useState(false)
  const [key, setKey] = useState(datasets[0]?.key)
  const [cat, setCat] = useState({})
  const [file, setFile] = useState(null)
  const [pv, setPv] = useState(null)
  const [busy, setBusy] = useState(false)
  const [mode, setMode] = useState('valid_only')
  const [result, setResult] = useState(null)
  const [filter, setFilter] = useState('all')
  const [err, setErr] = useState('')
  const input = useRef(null)
  useEffect(() => { if (open) loadCatalogue().then(setCat) }, [open])
  const ds = datasets.find(d => d.key === key) || datasets[0]
  const meta = cat[key]
  const needs = meta?.capability || 'prepare'
  const allowed = caps.includes(needs)
  const reset = () => { setFile(null); setPv(null); setResult(null); setErr(''); setFilter('all'); if (input.current) input.current.value = '' }
  const close = () => { setOpen(false); reset() }
  const pick = async f => {
    setFile(f); setPv(null); setResult(null); setErr('')
    if (!f) return
    setBusy(true)
    try { setPv(await api.imports.preview(key, f)) } catch (e) { setErr(api.errMsg(e)) } finally { setBusy(false) }
  }
  const template = async () => saveBlob(`template_${key}.csv`, await api.imports.template(key))
  const run = async () => {
    setBusy(true)
    const r = await act(() => api.imports.commit(key, file, mode))
    setBusy(false)
    if (r) setResult(r)
  }
  const report = () => {
    const rows = (result || pv)?.rows || []
    const esc = v => `"${String(v ?? '').replace(/"/g, '""')}"`
    saveBlob(`import_report_${key}.csv`, ['line,status,messages'].concat(rows.map(r => [r.line, r.status, r.messages.map(m => m.text).join(' | ')].map(esc).join(','))).join('\n'))
  }
  const shown = useMemo(() => (pv?.rows || []).filter(r => filter === 'all' || r.status === filter || (filter === 'warning' && r.messages.some(m => m.level === 'warning'))).slice(0, 300), [pv, filter])
  const cols = (meta?.columns || [])
  return (
    <>
      <button className={`btn btn-outline ${small ? 'btn-sm' : 'btn-sm'}`} onClick={() => setOpen(true)} aria-haspopup="dialog">⬆ {buttonLabel}</button>
      {open && (
        <Modal title="Bulk upload / Import CSV" onClose={close} width={920}>
          {datasets.length > 1 && <Select label="What are you importing?" value={key} onChange={e => { setKey(e.target.value); reset() }} options={datasets.map(d => ({ value: d.key, label: d.label }))} />}
          <div className="text-sm" style={{ marginBottom: 8 }}><strong>{meta?.title || ds.label}</strong>{meta && <span className="text-muted"> — {meta.description}</span>}</div>
          {!allowed && <div role="alert" className="alert alert-error">Your role cannot import this dataset ({needs} permission needed).</div>}
          <details style={{ marginBottom: 8 }}><summary className="text-sm" style={{ cursor: 'pointer' }}>Columns ({cols.length}; * required)</summary>
            <div className="text-xs" style={{ marginTop: 6, display: 'grid', gridTemplateColumns: 'repeat(auto-fit,minmax(260px,1fr))', gap: '2px 14px' }}>
              {cols.map(c => <div key={c.name}><span className="mono">{c.name}{c.required ? '*' : ''}</span> <span className="text-muted">({c.kind}{c.enum?.length ? `: ${c.enum.join('/')}` : ''}){c.help ? ` ${c.help}` : ''}</span></div>)}</div></details>
          <div className="flex gap-1 items-center" style={{ flexWrap: 'wrap', marginBottom: 10 }}>
            <button className="btn btn-outline btn-sm" onClick={template}>Download CSV template</button>
            <label className="btn btn-outline btn-sm" style={{ cursor: 'pointer', marginBottom: 0 }}>Choose CSV file…<input ref={input} type="file" accept=".csv,.txt,text/csv" hidden aria-label="CSV file" disabled={!allowed} onChange={e => pick(e.target.files?.[0])} /></label>
            {file && <span className="text-sm">{file.name} <span className="text-muted">({Math.max(1, Math.round(file.size / 1024))} KB)</span></span>}
            {busy && <span role="status" className="text-sm text-muted">Working…</span>}
          </div>
          {err && <div role="alert" className="alert alert-error">{err}</div>}
          {pv?.file_error && <div role="alert" className="alert alert-error">{pv.file_error}</div>}
          {!result && (!pv || pv.file_error || err) && <div className="flex gap-1" style={{ justifyContent: 'flex-end', marginTop: 8 }}><button className="btn btn-outline" onClick={close}>Close</button></div>}
          {pv && !pv.file_error && !result && (
            <>
              <div className="flex gap-1" style={{ flexWrap: 'wrap', margin: '6px 0' }} aria-label="Preview summary">
                <span className="badge badge-neutral">{pv.total} row(s) read</span><span className="badge badge-success">{pv.ok} valid</span>
                <span className="badge badge-info">{pv.duplicates} duplicate(s)</span><span className={`badge ${pv.errors ? 'badge-danger' : 'badge-neutral'}`}>{pv.errors} with errors</span>
                {pv.warnings > 0 && <span className="badge badge-warning">{pv.warnings} warning(s)</span>}</div>
              {pv.unknown_columns?.length > 0 && <div className="text-xs text-muted">Ignored columns: {pv.unknown_columns.join(', ')}</div>}
              <div className="flex gap-1 items-center" style={{ margin: '6px 0' }}>
                <select className="input input-sm" aria-label="Show rows" value={filter} onChange={e => setFilter(e.target.value)} style={{ maxWidth: 220 }}>
                  <option value="all">Show all rows</option><option value="error">Only rejected</option><option value="ok">Only valid</option><option value="duplicate">Only duplicates</option><option value="warning">Only with warnings</option></select>
                <button className="btn btn-ghost btn-xs" onClick={report}>Download row report (CSV)</button></div>
              <div style={{ maxHeight: 300, overflow: 'auto' }}>
                <table className="data-table"><thead><tr><th>Line</th><th>Result</th><th>Details</th><th>Data</th></tr></thead>
                  <tbody>{shown.map(r => <tr key={r.line}><td>{r.line}</td><td><StatusBadge status={rowBadge[r.status][0]} text={rowBadge[r.status][1]} /></td>
                    <td>{r.messages.map((m, i) => <div key={i} className="text-xs" style={{ color: LEVEL[m.level] }}>{m.level === 'warning' ? '▲ ' : ''}{m.text}</div>)}</td>
                    <td className="text-xs text-muted">{Object.entries(r.data || {}).slice(0, 4).map(([k, v]) => `${k}: ${v}`).join(' · ')}</td></tr>)}</tbody></table></div>
              <fieldset style={{ border: 0, padding: 0, margin: '10px 0' }}><legend className="text-sm" style={{ fontWeight: 600 }}>If some rows are rejected</legend>
                <label className="text-sm" style={{ display: 'block' }}><input type="radio" name="mode" checked={mode === 'valid_only'} onChange={() => setMode('valid_only')} /> Import the valid rows only and report the rest</label>
                <label className="text-sm" style={{ display: 'block' }}><input type="radio" name="mode" checked={mode === 'all_or_nothing'} onChange={() => setMode('all_or_nothing')} /> All or nothing: import nothing unless every row is valid</label></fieldset>
              {mode === 'all_or_nothing' && pv.errors > 0 && <div className="text-sm" style={{ color: 'var(--danger)' }}>Nothing will be imported while {pv.errors} row(s) have errors.</div>}
              <div className="flex gap-1" style={{ justifyContent: 'flex-end' }}>
                <button className="btn btn-outline" onClick={close}>Cancel</button>
                <button className="btn btn-primary" disabled={busy || !pv.can_commit || (mode === 'all_or_nothing' && pv.errors > 0)} onClick={run}>Import {pv.ok} valid row{pv.ok === 1 ? '' : 's'}</button></div>
            </>)}
          {result && (
            <div role="status" aria-label="Import result">
              <div className="alert alert-info" style={{ marginBottom: 8 }}><strong>Import complete.</strong> {result.imported} imported · {result.skipped_duplicates} duplicate(s) skipped · {result.rejected} rejected · {result.failed.length} failed.
                <div className="text-xs">Recorded in the audit trail with the file’s SHA-256 ({result.file_sha256.slice(0, 12)}…).</div></div>
              {result.failed.map(f => <div key={f.line} className="text-sm" style={{ color: 'var(--danger)' }}>Line {f.line} failed: {f.error}</div>)}
              {result.rows.filter(r => r.status === 'error').slice(0, 20).map(r => <div key={r.line} className="text-xs" style={{ color: 'var(--danger)' }}>Line {r.line} rejected: {r.messages[0]?.text}</div>)}
              <div className="flex gap-1" style={{ justifyContent: 'flex-end', marginTop: 10 }}><button className="btn btn-outline btn-sm" onClick={report}>Download row report (CSV)</button><button className="btn btn-primary" onClick={() => { close(); onDone && onDone(result) }}>Done</button></div>
            </div>)}
        </Modal>)}
    </>)
}
