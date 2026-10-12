import React, { useEffect, useState } from 'react'
import toast from 'react-hot-toast'
import { Upload } from 'lucide-react'
import * as api from '../lib/payrollApi.js'
import { Modal, Loading, ErrorBox, Money } from './kit.jsx'

/**
 * Bulk CSV import for Payroll. The columns, notes and load order come from the server (GET /payroll/imports) so this window can never drift from what
 * the importer accepts. Flow: choose a file -> "Check file" (a full dry run: nothing is saved) -> "Import" (all-or-nothing).
 * Everything goes through the same services as typing it in, so it is permission-checked, audited and (TFN / bank numbers) never echoed back.
 */

// Is bulk import switched on (Admin > Modules Management) and included in the plan? Fetched once and shared. Fails OPEN: the server refuses the upload anyway.
let cached = null
const listeners = new Set()
function refresh() {
  return Promise.resolve().then(() => api.importStatus()).then(r => { cached = r?.enabled !== false }).catch(() => {}).finally(() => listeners.forEach(f => f(cached !== false)))
}
export const resetImportStatus = () => { cached = null }
export function useImportEnabled() {
  const [on, setOn] = useState(cached !== false)
  useEffect(() => {
    listeners.add(setOn)
    if (cached === null) refresh()
    return () => { listeners.delete(setOn) }
  }, [])
  return on
}

function useCatalogue() {
  const [state, setState] = useState({ items: null, error: null })
  useEffect(() => {
    let live = true
    Promise.resolve().then(() => api.importCatalogue()).then(r => live && setState({ items: r.items || [], error: null })).catch(e => live && setState({ items: null, error: api.errMsg(e) }))
    return () => { live = false }
  }, [])
  return state
}

export function ImportModal({ entities, title, onClose, onDone }) {
  const cat = useCatalogue()
  const [entity, setEntity] = useState(entities[0])
  const [file, setFile] = useState(null)
  const [res, setRes] = useState(null)
  const [busy, setBusy] = useState(false)
  const [showCols, setShowCols] = useState(false)

  const offered = (cat.items || []).filter(i => entities.includes(i.entity)).sort((a, b) => entities.indexOf(a.entity) - entities.indexOf(b.entity))
  const info = offered.find(i => i.entity === entity)
  const choose = e => { setEntity(e); setFile(null); setRes(null); setShowCols(false) }

  const run = async dry => {
    if (!file || !info) return
    setBusy(true)
    try {
      const data = await api.importCsv(entity, file, dry)
      setRes(data)
      if (!dry) {
        if (data.error) toast.error(data.error)
        else { toast.success(`${data.saved} record(s) imported`); onDone?.(data) }
      }
    } catch (e) { toast.error(api.errMsg(e)); setRes(null) } finally { setBusy(false) }
  }
  const canImport = res && !res.error && res.dry_run && res.valid > 0 && !busy

  return (
    <Modal title={title || `Import ${info?.title || ''} from CSV`} onClose={onClose} width={940}>
      {cat.error ? <ErrorBox error={cat.error} /> : !cat.items ? <Loading /> : !offered.length ? <div className="text-sm text-muted">This import is not available for your role.</div> : (
        <>
          {offered.length > 1 && (
            <label className="text-sm" style={{ display: 'block', marginBottom: 8 }}>What are you importing?{' '}
              <select aria-label="What are you importing" className="input input-sm" value={entity} onChange={e => choose(e.target.value)}>
                {offered.map(i => <option key={i.entity} value={i.entity} disabled={!i.allowed}>{i.title}{i.allowed ? '' : ' (not permitted for your role)'}</option>)}
              </select></label>)}
          {info && (
            <>
              <p className="text-sm" style={{ marginTop: 0 }}>{info.description}</p>
              <p className="text-xs text-muted" style={{ margin: '0 0 6px' }}>{info.mode === 'upsert' ? 'Existing records are updated; new ones are created. Blank cells keep the current value.' : 'Creates new records only: loading the same rows twice is refused, never duplicated.'}</p>
              {info.notes?.length > 0 && <ul className="text-sm text-muted" style={{ margin: '0 0 10px 18px', padding: 0 }}>{info.notes.map((n, i) => <li key={i}>{n}</li>)}</ul>}
              {!info.allowed && <div className="alert alert-warning" role="alert">Your role cannot import this. Ask a payroll administrator.</div>}
              <div className="flex items-center gap-4" style={{ flexWrap: 'wrap', marginBottom: 8 }}>
                <button className="btn btn-ghost btn-xs" onClick={() => api.downloadImportTemplate(entity).catch(e => toast.error(api.errMsg(e)))}>Download template</button>
                <button className="btn btn-ghost btn-xs" onClick={() => setShowCols(s => !s)}>{showCols ? 'Hide columns' : 'Show columns'}</button>
              </div>
              {showCols && (
                <div className="data-table-wrap" style={{ maxHeight: 220, overflow: 'auto', marginBottom: 10 }}>
                  <table className="data-table" style={{ fontSize: '.76rem' }}>
                    <thead><tr><th>Column</th><th>Required</th><th>What goes in it</th></tr></thead>
                    <tbody>{info.columns.map(c => <tr key={c.name}><td className="mono">{c.name}</td><td>{c.required ? 'yes' : ''}</td><td>{c.help}{c.example ? <span className="text-muted"> e.g. {c.example}</span> : null}</td></tr>)}</tbody>
                  </table>
                </div>)}
              <div className="flex items-center gap-4" style={{ flexWrap: 'wrap' }}>
                <input aria-label="CSV file" type="file" accept=".csv,text/csv" disabled={!info.allowed} onChange={e => { setFile(e.target.files?.[0] || null); setRes(null) }} />
              </div>
              <div className="flex gap-1 mt-4">
                <button className="btn btn-outline" disabled={!file || busy || !info.allowed} onClick={() => run(true)}>{busy && !res ? 'Checking…' : 'Check file'}</button>
                <button className="btn btn-primary" disabled={!canImport} onClick={() => run(false)}><Upload size={13} /> {res && !res.error ? `Import ${res.valid} record(s)` : 'Import'}</button>
              </div>
            </>)}
          {res && (
            <div className="mt-4" data-testid="csv-import-result">
              <div className={`alert ${res.error ? 'alert-error' : 'alert-success'}`} role="status">
                {res.error || (res.dry_run ? `Checked: all ${res.count} record(s) are valid${Number(res.total) ? ` (total ${Number(res.total).toLocaleString('en-AU', { style: 'currency', currency: 'AUD' })})` : ''}. Nothing has been saved yet - press Import.` : `${res.saved} record(s) imported.`)}
              </div>
              {res.warnings?.map((w, i) => <div key={i} className="text-sm text-muted" style={{ marginBottom: 4 }}>⚠ {w}</div>)}
              <div className="data-table-wrap" style={{ maxHeight: 320, overflow: 'auto' }}>
                <table className="data-table" style={{ fontSize: '.78rem' }}>
                  <thead><tr><th>Row</th><th>Record</th><th>Detail</th><th className="text-right">Amount</th><th>Result</th></tr></thead>
                  <tbody>{res.items.map((it, n) => (
                    <tr key={n}><td>{it.row}</td><td>{it.label}</td><td className="text-muted">{it.detail}</td><td className="text-right">{it.amount != null ? <Money v={it.amount} /> : ''}</td>
                      <td>{it.errors.length ? it.errors.map((e, i) => <div key={i} style={{ color: 'var(--danger)' }}>{e}</div>) : <span className="badge badge-success">{it.action === 'update' ? 'update' : 'ok'}</span>}
                        {it.warnings.map((w, i) => <div key={i} className="text-muted">⚠ {w}</div>)}</td></tr>))}</tbody>
                </table>
              </div>
              {res.items_truncated > 0 && <div className="text-xs text-muted">{res.items_truncated} more valid record(s) not shown.</div>}
            </div>)}
        </>)}
    </Modal>
  )
}

/** A button that opens the import window for one or several related imports. Hidden when bulk import is switched off. */
export function ImportButton({ entities, label = 'Import CSV', title, onDone, className = 'btn btn-outline' }) {
  const [open, setOpen] = useState(false)
  const enabled = useImportEnabled()
  if (!enabled) return null
  return (
    <>
      <button className={className} onClick={() => setOpen(true)} data-testid={`import-${entities[0]}`}><Upload size={13} /> {label}</button>
      {open && <ImportModal entities={entities} title={title} onClose={() => setOpen(false)} onDone={d => { setOpen(false); onDone?.(d) }} />}
    </>
  )
}

/** Settings > Bulk import: every import in load order, with its button and template. */
export function ImportCentre({ onDone }) {
  const enabled = useImportEnabled()
  const cat = useCatalogue()
  const [open, setOpen] = useState(null)
  if (!enabled) return <div className="alert alert-warning" role="status">Bulk data import has been switched off by your platform administrator (Admin &gt; Modules Management).</div>
  if (cat.error) return <ErrorBox error={cat.error} />
  if (!cat.items) return <Loading />
  return (
    <div>
      <div className="alert alert-warning">
        <b>Load in the numbered order.</b> Later files refer to earlier ones (employees need calendars and departments; pay runs need employees). For a trial, use a <b>new, empty organisation</b>.
        Every import has <b>Check file</b> first, which runs the whole import for real and rolls it back, so what it reports is exactly what the real import will do. If any record has a problem, nothing is saved.
      </div>
      <div className="data-table-wrap">
        <table className="data-table" data-testid="import-centre">
          <thead><tr><th>#</th><th>Import</th><th>Group</th><th>What it loads</th><th>When re-loaded</th><th /></tr></thead>
          <tbody>{[...cat.items].sort((x, y) => x.order - y.order).map(i => (
            <tr key={i.entity}>
              <td>{String(i.order).padStart(2, '0')}</td><td><b>{i.title}</b><div className="text-xs text-muted mono">{i.entity}</div></td><td>{i.group}</td>
              <td className="text-sm" style={{ maxWidth: 420 }}>{i.description}</td>
              <td className="text-sm">{i.mode === 'upsert' ? 'Updates' : 'New only'}</td>
              <td style={{ whiteSpace: 'nowrap' }}>
                <button className="btn btn-outline btn-xs" disabled={!i.allowed} data-testid={`centre-import-${i.entity}`} onClick={() => setOpen(i.entity)}><Upload size={12} /> Import</button>{' '}
                <button className="btn btn-ghost btn-xs" onClick={() => api.downloadImportTemplate(i.entity).catch(e => toast.error(api.errMsg(e)))}>Template</button>
              </td>
            </tr>))}</tbody>
        </table>
      </div>
      {open && <ImportModal entities={[open]} onClose={() => setOpen(null)} onDone={d => { setOpen(null); onDone?.(d) }} />}
    </div>
  )
}
