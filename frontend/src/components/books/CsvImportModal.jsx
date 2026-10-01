import React, { useEffect, useState } from 'react'
import toast from 'react-hot-toast'
import { Upload } from 'lucide-react'
import * as api from '../../lib/booksApi.js'
import { Modal, fmtAUD } from './Common.jsx'
import { useBulkImportEnabled } from '../../hooks/useBulkImport.jsx'

/**
 * CsvImportModal - one import window for every Books & Accounting list (customers, invoices, bills, receipts, claims, stock, assets ...).
 * The columns, notes and options come from the server (GET /imports) so they can never drift from what the importer accepts.
 * Flow: choose a file -> "Check file" (a full dry run: nothing is saved) -> "Import" (all-or-nothing).
 */
export function CsvImportModal({ entity, title, onClose, onDone }) {
  const [info, setInfo] = useState(null)
  const [file, setFile] = useState(null)
  const [opts, setOpts] = useState({})
  const [res, setRes] = useState(null)
  const [busy, setBusy] = useState(false)
  const [showCols, setShowCols] = useState(false)

  useEffect(() => {
    api.importCatalogue().then(r => {
      const i = (r.data?.items || []).find(x => x.entity === entity)
      setInfo(i || null)
      const d = {}; (i?.options || []).forEach(o => { d[o.name] = o.default }); setOpts(d)
    }).catch(e => toast.error(api.errMsg(e)))
  }, [entity])

  const run = async dry => {
    if (!file) return
    setBusy(true)
    try {
      const { data } = await api.importCsv(entity, file, { dryRun: dry, mode: opts.mode, amountsAre: opts.amounts_are })
      setRes(data)
      if (!dry) {
        if (data.error) toast.error(data.error)
        else { toast.success(`${data.saved} record(s) imported`); onDone?.(data) }
      }
    } catch (e) { toast.error(api.errMsg(e)); setRes(null) } finally { setBusy(false) }
  }

  const heading = title || info?.title || 'Import'
  const canImport = res && !res.error && res.dry_run && res.valid > 0 && !busy

  return (
    <Modal title={`Import ${heading} from CSV`} onClose={onClose} width={920}>
      {info && <p className="text-sm" style={{ marginTop: 0 }}>{info.description}</p>}
      {info?.notes?.length > 0 && <ul className="text-sm text-muted" style={{ margin: '0 0 10px 18px', padding: 0 }}>{info.notes.map((n, i) => <li key={i}>{n}</li>)}</ul>}
      <div className="flex items-center gap-4" style={{ flexWrap: 'wrap', marginBottom: 8 }}>
        <button className="btn btn-ghost btn-xs" onClick={() => api.downloadImportTemplateFor(entity).catch(e => toast.error(api.errMsg(e)))}>Download template</button>
        <button className="btn btn-ghost btn-xs" onClick={() => setShowCols(s => !s)}>{showCols ? 'Hide columns' : 'Show columns'}</button>
      </div>
      {showCols && info && (
        <div className="data-table-wrap" style={{ maxHeight: 220, overflow: 'auto', marginBottom: 10 }}>
          <table className="data-table" style={{ fontSize: '.76rem' }}>
            <thead><tr><th>Column</th><th>Required</th><th>What goes in it</th></tr></thead>
            <tbody>{info.columns.map(c => <tr key={c.name}><td className="mono">{c.name}</td><td>{c.required ? 'yes' : ''}</td><td>{c.help}{c.example ? <span className="text-muted"> e.g. {c.example}</span> : null}</td></tr>)}</tbody>
          </table>
        </div>
      )}
      <div className="flex items-center gap-4" style={{ flexWrap: 'wrap' }}>
        <input aria-label="CSV file" type="file" accept=".csv,text/csv" onChange={e => { setFile(e.target.files?.[0] || null); setRes(null) }} />
        {(info?.options || []).map(o => (
          <label key={o.name} className="text-sm" title={o.help}>{o.label}{' '}
            <select aria-label={o.label} className="input input-sm" value={opts[o.name] ?? o.default} onChange={e => { setOpts({ ...opts, [o.name]: e.target.value }); setRes(null) }}>
              {o.choices.map(([v, l]) => <option key={v} value={v}>{l}</option>)}
            </select>
          </label>
        ))}
      </div>
      <div className="flex gap-1 mt-4">
        <button className="btn btn-outline" disabled={!file || busy} onClick={() => run(true)}>{busy && !res ? 'Checking…' : 'Check file'}</button>
        <button className="btn btn-primary" disabled={!canImport} onClick={() => run(false)}><Upload size={13} /> {res && !res.error ? `Import ${res.valid} record(s)` : 'Import'}</button>
      </div>
      {res && (
        <div className="mt-4" data-testid="csv-import-result">
          <div className={`alert ${res.error ? 'alert-error' : 'alert-success'}`}>
            {res.error || (res.dry_run ? `Checked: all ${res.count} record(s) are valid${Number(res.total) ? ` (total ${fmtAUD(res.total)})` : ''}. Nothing has been saved yet - press Import.` : `${res.saved} record(s) imported.`)}
          </div>
          {res.warnings?.map((w, i) => <div key={i} className="text-sm text-muted" style={{ marginBottom: 4 }}>⚠ {w}</div>)}
          <div className="data-table-wrap" style={{ maxHeight: 320, overflow: 'auto' }}>
            <table className="data-table" style={{ fontSize: '.78rem' }}>
              <thead><tr><th>Row</th><th>Record</th><th>Detail</th><th className="text-right">Amount</th><th>Result</th></tr></thead>
              <tbody>{res.items.map((it, n) => (
                <tr key={n}><td>{it.row}</td><td>{it.label}</td><td className="text-muted">{it.detail}</td><td className="text-right mono">{it.amount != null ? fmtAUD(it.amount) : ''}</td>
                  <td>{it.errors.length ? it.errors.map((e, i) => <div key={i} style={{ color: 'var(--danger)' }}>{e}</div>) : <span className="badge badge-success">ok</span>}
                    {it.warnings.map((w, i) => <div key={i} className="text-muted">{w}</div>)}</td></tr>))}</tbody>
            </table>
          </div>
          {res.items_truncated > 0 && <div className="text-xs text-muted">{res.items_truncated} more valid record(s) not shown.</div>}
        </div>
      )}
    </Modal>
  )
}

/** A button that opens the import window. */
export function CsvImportButton({ entity, label = 'Import CSV', title, onDone, className = 'btn btn-outline btn-sm' }) {
  const [open, setOpen] = useState(false)
  const enabled = useBulkImportEnabled()
  if (!enabled) return null                 // switched off by an administrator
  return (
    <>
      <button className={className} onClick={() => setOpen(true)} data-testid={`import-${entity}`}><Upload size={13} /> {label}</button>
      {open && <CsvImportModal entity={entity} title={title} onClose={() => setOpen(false)} onDone={d => { setOpen(false); onDone?.(d) }} />}
    </>
  )
}
