import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import toast from 'react-hot-toast'
import { Modal, EmptyState, Field, Pager } from '../../../core/components/ui/Common.jsx'
import { errMsg } from '../lib/payrollApi.js'
import { fmtAUD, fmtHours, fmtDate, label } from '../lib/format.js'

export { Modal, EmptyState, Field, Pager }

// ── data loading ──────────────────────────────────────────────────────────────────────────────────────────────────────────────────
export function useLoad(fn, deps = []) {
  const [state, setState] = useState({ data: null, loading: true, error: null })
  const seq = useRef(0)
  const load = useCallback(async () => {
    const id = ++seq.current
    setState(s => ({ ...s, loading: true, error: null }))
    try {
      const data = await fn()
      if (id === seq.current) setState({ data, loading: false, error: null })
    } catch (e) {
      if (id === seq.current) setState({ data: null, loading: false, error: errMsg(e) })
    }
  }, deps) // eslint-disable-line
  useEffect(() => { load() }, [load])
  return { ...state, reload: load, setData: data => setState(s => ({ ...s, data })) }
}

export const Loading = ({ text = 'Loading…' }) => (
  <div role="status" style={{ padding: 40, textAlign: 'center' }} className="text-muted"><span className="spinner spinner-lg" /><div style={{ marginTop: 8 }}>{text}</div></div>
)
export const ErrorBox = ({ error, onRetry }) => (
  <div role="alert" className="alert alert-error" style={{ margin: 16 }}>
    <div>{error}</div>{onRetry && <button className="btn btn-outline btn-sm" style={{ marginTop: 8 }} onClick={onRetry}>Try again</button>}
  </div>
)
export const Async = ({ q, children, empty }) => (q.loading && !q.data ? <Loading /> : q.error ? <ErrorBox error={q.error} onRetry={q.reload} /> : children(q.data))

// Run an API action with consistent success / error toasts. Resolves to the result, or undefined if it failed.
export async function act(fn, success) {
  try {
    const r = await fn()
    if (success) toast.success(success)
    return r === undefined ? true : r
  } catch (e) {
    toast.error(errMsg(e))
    return undefined
  }
}

// ── presentation ──────────────────────────────────────────────────────────────────────────────────────────────────────────────────
const BADGE = {
  draft: 'badge-neutral', review: 'badge-warning', processing: 'badge-info', approved: 'badge-info', finalised: 'badge-success', paid: 'badge-success', voided: 'badge-danger',
  submitted: 'badge-info', rejected: 'badge-danger', processed: 'badge-success', pending: 'badge-warning', cancelled: 'badge-neutral', active: 'badge-success', terminated: 'badge-danger',
  inactive: 'badge-neutral', prepared: 'badge-warning', completed: 'badge-success', failed: 'badge-danger', returned: 'badge-danger', reconciled: 'badge-success', unreconciled: 'badge-warning',
  mock_submitted: 'badge-info', reversed: 'badge-danger', reversal: 'badge-danger', overdue: 'badge-danger', error: 'badge-danger', warning: 'badge-warning', not_started: 'badge-neutral',
}
export const StatusBadge = ({ status, text }) => <span className={`badge ${BADGE[status] || 'badge-neutral'}`}>{text || label(status)}</span>
export const Money = ({ v, strong }) => <span className="mono" style={{ fontWeight: strong ? 700 : 400, color: Number(v) < 0 ? 'var(--danger)' : undefined }}>{fmtAUD(v)}</span>

export const Stat = ({ label: l, value, sub, tone, onClick }) => (
  <div className="stat-card" onClick={onClick} style={{ cursor: onClick ? 'pointer' : 'default' }}>
    <div className="stat-label">{l}</div>
    <div className="stat-value" style={tone ? { color: `var(--${tone})` } : undefined}>{value}</div>
    {sub && <div className="stat-sub">{sub}</div>}
  </div>
)

export const Section = ({ title, actions, children, pad = true }) => (
  <div className="card card-flat" style={{ marginBottom: 14, padding: pad ? undefined : 0 }}>
    {(title || actions) && <div className="flex items-center justify-between" style={{ padding: pad ? '0 0 10px' : '12px 16px' }}>
      <h4 style={{ margin: 0 }}>{title}</h4><div className="flex gap-1">{actions}</div></div>}
    {children}
  </div>
)

// ── data grid: search, sort, pagination, empty state ───────────────────────────────────────────────────────────────────────────────
// columns: [{key, label, render?(row), align?: 'right', sortValue?(row), money?: true, hours?: true, date?: true}]
export function DataGrid({ columns, rows, searchKeys = [], pageSize = 25, onRowClick, empty = 'Nothing to show', hint, toolbar, footer, rowKey = 'id' }) {
  const [q, setQ] = useState('')
  const [sort, setSort] = useState(null)
  const [page, setPage] = useState(1)
  const filtered = useMemo(() => {
    const t = q.trim().toLowerCase()
    let r = rows || []
    if (t) r = r.filter(x => searchKeys.some(k => String(x[k] ?? '').toLowerCase().includes(t)))
    if (sort) {
      const c = columns.find(c => c.key === sort.key)
      const val = x => (c?.sortValue ? c.sortValue(x) : x[sort.key])
      r = [...r].sort((a, b) => {
        const va = val(a), vb = val(b)
        const na = Number(va), nb = Number(vb)
        const cmp = Number.isFinite(na) && Number.isFinite(nb) && va !== '' && vb !== '' ? na - nb : String(va ?? '').localeCompare(String(vb ?? ''))
        return sort.dir === 'asc' ? cmp : -cmp
      })
    }
    return r
  }, [rows, q, sort, columns, searchKeys])
  useEffect(() => setPage(1), [q, rows])
  const pages = Math.max(1, Math.ceil(filtered.length / pageSize))
  const slice = filtered.slice((page - 1) * pageSize, page * pageSize)
  const cell = (c, r) => (c.render ? c.render(r) : c.money ? <Money v={r[c.key]} /> : c.hours ? fmtHours(r[c.key]) : c.date ? fmtDate(r[c.key]) : r[c.key] ?? '—')
  return (
    <div>
      {(searchKeys.length > 0 || toolbar) && (
        <div className="flex items-center gap-1" style={{ padding: '0 0 10px', flexWrap: 'wrap' }}>
          {searchKeys.length > 0 && <input className="input input-sm" placeholder="Search…" aria-label="Search" value={q} onChange={e => setQ(e.target.value)} style={{ maxWidth: 240 }} />}
          <div style={{ flex: 1 }} />{toolbar}
        </div>)}
      {filtered.length === 0 ? <EmptyState icon="🗂" title={q ? 'No matches' : empty} hint={q ? 'Try a different search' : hint} /> : (
        <div className="data-table-wrap" style={{ overflowX: 'auto' }}>
          <table className="data-table">
            <thead><tr>{columns.map(c => (
              <th key={c.key} className={c.align === 'right' || c.money || c.hours ? 'text-right' : ''} onClick={() => setSort(s => ({ key: c.key, dir: s?.key === c.key && s.dir === 'asc' ? 'desc' : 'asc' }))}
                style={{ cursor: 'pointer', whiteSpace: 'nowrap' }} aria-sort={sort?.key === c.key ? (sort.dir === 'asc' ? 'ascending' : 'descending') : 'none'}>
                {c.label}{sort?.key === c.key ? (sort.dir === 'asc' ? ' ▲' : ' ▼') : ''}</th>))}</tr></thead>
            <tbody>{slice.map((r, i) => (
              <tr key={r[rowKey] ?? i} onClick={onRowClick ? () => onRowClick(r) : undefined} style={{ cursor: onRowClick ? 'pointer' : 'default' }}>
                {columns.map(c => <td key={c.key} className={c.align === 'right' || c.money || c.hours ? 'text-right' : ''}>{cell(c, r)}</td>)}</tr>))}</tbody>
            {footer && <tfoot>{footer}</tfoot>}
          </table>
        </div>)}
      <div style={{ marginTop: 8 }} className="flex items-center justify-between">
        <span className="text-xs text-muted">{filtered.length} {filtered.length === 1 ? 'row' : 'rows'}</span>
        <Pager page={page} pageCount={pages} onPage={setPage} />
      </div>
    </div>
  )
}

// ── confirmation dialog (destructive actions) ──────────────────────────────────────────────────────────────────────────────────────
export function useConfirm() {
  const [req, setReq] = useState(null)
  const [reason, setReason] = useState('')
  const confirm = useCallback(opts => new Promise(resolve => { setReason(''); setReq({ ...opts, resolve }) }), [])
  const close = ok => { req.resolve(ok ? { ok: true, reason } : { ok: false }); setReq(null) }
  const dialog = req && (
    <Modal title={req.title || 'Please confirm'} onClose={() => close(false)} width={460}>
      <p style={{ marginTop: 0 }}>{req.message}</p>
      {req.reasonLabel && <Field label={req.reasonLabel}><input className="input" autoFocus aria-label={req.reasonLabel} value={reason} onChange={e => setReason(e.target.value)} /></Field>}
      <div className="flex gap-1" style={{ justifyContent: 'flex-end' }}>
        <button className="btn btn-outline" onClick={() => close(false)}>Cancel</button>
        <button className={`btn ${req.danger ? 'btn-danger' : 'btn-primary'}`} disabled={!!req.reasonLabel && !reason.trim()} onClick={() => close(true)}>{req.confirmLabel || 'Confirm'}</button>
      </div>
    </Modal>)
  return [dialog, confirm]
}

// ── tiny form helpers ───────────────────────────────────────────────────────────────────────────────────────────────────────────────
export function useForm(initial) {
  const [v, setV] = useState(initial)
  const set = k => e => setV(s => ({ ...s, [k]: e && e.target ? (e.target.type === 'checkbox' ? e.target.checked : e.target.value) : e }))
  return [v, set, setV]
}
export const Input = ({ label: l, value, onChange, type = 'text', hint, ...rest }) => (
  <Field label={l} hint={hint}><input className="input" aria-label={l} type={type} value={value ?? ''} onChange={onChange} {...rest} /></Field>)
export const Select = ({ label: l, value, onChange, options, hint, blank, ...rest }) => (
  <Field label={l} hint={hint}><select className="input" aria-label={l} value={value ?? ''} onChange={onChange} {...rest}>
    {blank !== undefined && <option value="">{blank}</option>}
    {options.map(o => (typeof o === 'object' ? <option key={o.value} value={o.value}>{o.label}</option> : <option key={o} value={o}>{label(o)}</option>))}</select></Field>)
export const Check = ({ label: l, checked, onChange, hint }) => (
  <Field label="" hint={hint}><label className="flex items-center gap-1"><input type="checkbox" checked={!!checked} onChange={onChange} /> {l}</label></Field>)
export const Grid = ({ cols = 2, children }) => <div style={{ display: 'grid', gridTemplateColumns: `repeat(${cols}, minmax(0,1fr))`, gap: '0 14px' }}>{children}</div>

export const Issues = ({ errors = [], warnings = [] }) => (
  <div>
    {errors.map((e, i) => <div key={'e' + i} className="text-xs" style={{ color: 'var(--danger)' }}>✖ {e.message}</div>)}
    {warnings.map((e, i) => <div key={'w' + i} className="text-xs" style={{ color: 'var(--warning)' }}>▲ {e.message}</div>)}
  </div>
)
