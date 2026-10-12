import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import toast from 'react-hot-toast'
import { Modal, EmptyState, Field } from '../../../core/components/ui/Common.jsx'
import { errMsg } from '../lib/planningApi.js'
import { fmtAUD, fmtDate, label, BASIS, basisKey, todayISO } from '../lib/format.js'

export { Modal, EmptyState, Field }

export function useLoad(fn, deps = []) {
  const [state, setState] = useState({ data: null, loading: true, error: null })
  const seq = useRef(0)
  const load = useCallback(async () => {
    const id = ++seq.current
    setState(s => ({ ...s, loading: true, error: null }))
    try { const data = await fn(); if (id === seq.current) setState({ data, loading: false, error: null }) }
    catch (e) { if (id === seq.current) setState({ data: null, loading: false, error: errMsg(e) }) }
  }, deps) // eslint-disable-line
  useEffect(() => { load() }, [load])
  return { ...state, reload: load }
}
export const Loading = ({ text = 'Loading…' }) => <div role="status" style={{ padding: 40, textAlign: 'center' }} className="text-muted"><span className="spinner spinner-lg" /><div style={{ marginTop: 8 }}>{text}</div></div>
export const ErrorBox = ({ error, onRetry }) => <div role="alert" className="alert alert-error" style={{ margin: 16 }}><div>{error}</div>{onRetry && <button className="btn btn-outline btn-sm" style={{ marginTop: 8 }} onClick={onRetry}>Try again</button>}</div>
export const Async = ({ q, children }) => (q.loading && !q.data ? <Loading /> : q.error ? <ErrorBox error={q.error} onRetry={q.reload} /> : children(q.data))

export async function act(fn, success) {
  try { const r = await fn(); if (success) toast.success(success); return r === undefined ? true : r }
  catch (e) { toast.error(errMsg(e)); return undefined }
}

// ---- labels: every number says what it is ---------------------------------------------------------------------------------------------------------------
export const Basis = ({ basis }) => { const b = BASIS[basisKey(basis)]; return <span className={`badge ${b.cls}`} title={b.hint} aria-label={`${b.text} figures: ${b.hint}`}>{b.text}</span> }
export const Provenance = ({ d }) => !d ? null : (
  <div className="text-xs text-muted" style={{ margin: '4px 0 10px' }} aria-label="Source and period">
    {d.organisation && <span>{d.organisation} · </span>}{d.currency && <span>{d.currency} · </span>}
    {d.period_from && <span>{fmtDate(d.period_from)} to {fmtDate(d.period_to)} · </span>}{d.as_at && !d.period_from && <span>as at {fmtDate(d.as_at)} · </span>}{d.source && <span>Source: {d.source}</span>}
  </div>)
export const Flags = ({ items }) => !items || !items.length ? null : (
  <div role="note" className="alert alert-warning" style={{ margin: '0 0 12px' }}>{items.map((f, i) => <div key={i}>⚠ {typeof f === 'string' ? f : f.text}</div>)}</div>)
export const Disclaimer = ({ children }) => <div className="text-xs text-muted" style={{ margin: '8px 0' }}>{children}</div>

export const Money = ({ v, strong }) => <span className="mono" style={{ fontWeight: strong ? 700 : 400, color: Number(v) < 0 ? 'var(--danger)' : undefined }}>{fmtAUD(v)}</span>
export const Stat = ({ label: l, value, sub, tone, basis, onClick }) => (
  <div className="stat-card" onClick={onClick} style={{ cursor: onClick ? 'pointer' : 'default' }} role={onClick ? 'button' : undefined} tabIndex={onClick ? 0 : undefined}
    onKeyDown={onClick ? e => { if (e.key === 'Enter' || e.key === ' ') onClick() } : undefined}>
    <div className="stat-label">{l} {basis && <Basis basis={basis} />}</div><div className="stat-value" style={tone ? { color: `var(--${tone})` } : undefined}>{value}</div>{sub && <div className="stat-sub">{sub}</div>}
  </div>)
export const Section = ({ title, actions, children, hint }) => (
  <div className="card card-flat" style={{ marginBottom: 14 }}>
    {(title || actions) && <div className="flex items-center justify-between" style={{ paddingBottom: 10, flexWrap: 'wrap', gap: 8 }}><div><h4 style={{ margin: 0 }}>{title}</h4>{hint && <div className="text-xs text-muted">{hint}</div>}</div><div className="flex gap-1" style={{ flexWrap: 'wrap' }}>{actions}</div></div>}
    {children}
  </div>)
const BADGE = { new: 'badge-warning', acknowledged: 'badge-info', dismissed: 'badge-neutral', resolved: 'badge-success', high: 'badge-danger', medium: 'badge-warning', low: 'badge-neutral', info: 'badge-info',
  draft: 'badge-neutral', submitted: 'badge-info', approved: 'badge-success', archived: 'badge-neutral', active: 'badge-success', indicative: 'badge-warning', medium_c: 'badge-info', high_c: 'badge-success' }
export const StatusBadge = ({ status, text }) => <span className={`badge ${BADGE[status] || 'badge-neutral'}`}>{text || label(status)}</span>

// ---- simple table (responsive scroll, accessible) -------------------------------------------------------------------------------------------------------
export function Table({ columns, rows, empty = 'Nothing to show', hint, caption, onRowClick, rowKey = 'id' }) {
  if (!rows || rows.length === 0) return <EmptyState icon="🗂" title={empty} hint={hint} />
  const cell = (c, r) => (c.render ? c.render(r) : c.money ? <Money v={r[c.key]} /> : c.date ? fmtDate(r[c.key]) : r[c.key] ?? '—')
  return (
    <div className="data-table-wrap" style={{ overflowX: 'auto' }}>
      <table className="data-table">
        {caption && <caption className="sr-only">{caption}</caption>}
        <thead><tr>{columns.map(c => <th scope="col" key={c.key} className={c.money || c.align === 'right' ? 'text-right' : ''} style={{ whiteSpace: 'nowrap' }}>{c.label}</th>)}</tr></thead>
        <tbody>{rows.map((r, i) => (
          <tr key={r[rowKey] ?? i} onClick={onRowClick ? () => onRowClick(r) : undefined} style={{ cursor: onRowClick ? 'pointer' : 'default' }}>
            {columns.map(c => <td key={c.key} className={c.money || c.align === 'right' ? 'text-right' : ''}>{cell(c, r)}</td>)}
          </tr>))}</tbody>
      </table>
    </div>)
}

// ---- forms ----------------------------------------------------------------------------------------------------------------------------------------------
export function useForm(initial) {
  const [v, setV] = useState(initial)
  const set = k => e => setV(s => ({ ...s, [k]: e && e.target ? (e.target.type === 'checkbox' ? e.target.checked : e.target.value) : e }))
  return [v, set, setV]
}
export const Input = ({ label: l, value, onChange, type = 'text', hint, ...rest }) => <Field label={l} hint={hint}><input className="input" aria-label={l} type={type} value={value ?? ''} onChange={onChange} {...rest} /></Field>
export const Select = ({ label: l, value, onChange, options, hint, blank, ...rest }) => (
  <Field label={l} hint={hint}><select className="input" aria-label={l} value={value ?? ''} onChange={onChange} {...rest}>
    {blank !== undefined && <option value="">{blank}</option>}
    {options.map(o => (typeof o === 'object' ? <option key={o.value} value={o.value}>{o.label}</option> : <option key={o} value={o}>{label(o)}</option>))}</select></Field>)
export const Grid = ({ cols = 2, children }) => <div style={{ display: 'grid', gridTemplateColumns: `repeat(auto-fit, minmax(${cols > 2 ? 150 : 220}px, 1fr))`, gap: '0 14px' }}>{children}</div>

// ---- period filter shared by every tab: consistent labels, one place -------------------------------------------------------------------------------------
export function PeriodBar({ from, to, onChange, extra }) {
  return (
    <div className="flex items-center gap-1" style={{ flexWrap: 'wrap', marginBottom: 12 }} role="group" aria-label="Period">
      <label className="text-sm">From <input className="input input-sm" type="date" aria-label="From date" value={from} onChange={e => onChange({ from: e.target.value, to })} /></label>
      <label className="text-sm">To <input className="input input-sm" type="date" aria-label="To date" value={to} max={todayISO()} onChange={e => onChange({ from, to: e.target.value })} /></label>
      {extra}
    </div>)
}
export function useConfirm() {
  return useCallback(msg => window.confirm(msg), [])
}
