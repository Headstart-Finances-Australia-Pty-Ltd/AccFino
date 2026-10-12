import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import toast from 'react-hot-toast'
import { Modal, EmptyState, Field, Pager } from '../../../core/components/ui/Common.jsx'
import { errMsg } from '../lib/taxApi.js'
import { fmtAUD, fmtDate, label } from '../lib/format.js'

export { Modal, EmptyState, Field, Pager }

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

const BADGE = { draft: 'badge-neutral', prepared: 'badge-warning', reviewed: 'badge-info', approved: 'badge-info', lodged: 'badge-success', paid: 'badge-success', void: 'badge-danger', upcoming: 'badge-neutral',
  in_progress: 'badge-info', completed: 'badge-success', not_required: 'badge-neutral', overdue: 'badge-danger', due_soon: 'badge-warning', ok: 'badge-success', difference: 'badge-danger', active: 'badge-success' }
export const StatusBadge = ({ status, text }) => <span className={`badge ${BADGE[status] || 'badge-neutral'}`}>{text || label(status)}</span>
export const Money = ({ v, strong }) => <span className="mono" style={{ fontWeight: strong ? 700 : 400, color: Number(v) < 0 ? 'var(--danger)' : undefined }}>{fmtAUD(v)}</span>
export const Stat = ({ label: l, value, sub, tone, onClick }) => <div className="stat-card" onClick={onClick} style={{ cursor: onClick ? 'pointer' : 'default' }}><div className="stat-label">{l}</div><div className="stat-value" style={tone ? { color: `var(--${tone})` } : undefined}>{value}</div>{sub && <div className="stat-sub">{sub}</div>}</div>
export const Section = ({ title, actions, children, hint }) => (
  <div className="card card-flat" style={{ marginBottom: 14 }}>
    {(title || actions) && <div className="flex items-center justify-between" style={{ paddingBottom: 10, flexWrap: 'wrap', gap: 8 }}><div><h4 style={{ margin: 0 }}>{title}</h4>{hint && <div className="text-xs text-muted">{hint}</div>}</div><div className="flex gap-1" style={{ flexWrap: 'wrap' }}>{actions}</div></div>}
    {children}
  </div>)

// ---- data grid ----------------------------------------------------------------------------------------------------------------------------------
export function DataGrid({ columns, rows, searchKeys = [], pageSize = 20, onRowClick, empty = 'Nothing to show', hint, toolbar, rowKey = 'id' }) {
  const [q, setQ] = useState('')
  const [page, setPage] = useState(1)
  const filtered = useMemo(() => { const t = q.trim().toLowerCase(); return t ? (rows || []).filter(x => searchKeys.some(k => String(x[k] ?? '').toLowerCase().includes(t))) : rows || [] }, [rows, q, searchKeys])
  useEffect(() => setPage(1), [q, rows])
  const pages = Math.max(1, Math.ceil(filtered.length / pageSize))
  const slice = filtered.slice((page - 1) * pageSize, page * pageSize)
  const cell = (c, r) => (c.render ? c.render(r) : c.money ? <Money v={r[c.key]} /> : c.date ? fmtDate(r[c.key]) : r[c.key] ?? '—')
  return (
    <div>
      {(searchKeys.length > 0 || toolbar) && <div className="flex items-center gap-1" style={{ paddingBottom: 10, flexWrap: 'wrap' }}>
        {searchKeys.length > 0 && <input className="input input-sm" placeholder="Search…" aria-label="Search" value={q} onChange={e => setQ(e.target.value)} style={{ maxWidth: 240 }} />}<div style={{ flex: 1 }} />{toolbar}</div>}
      {filtered.length === 0 ? <EmptyState icon="🗂" title={q ? 'No matches' : empty} hint={q ? 'Try a different search' : hint} /> : (
        <div className="data-table-wrap" style={{ overflowX: 'auto' }}><table className="data-table">
          <thead><tr>{columns.map(c => <th key={c.key} className={c.money || c.align === 'right' ? 'text-right' : ''} style={{ whiteSpace: 'nowrap' }}>{c.label}</th>)}</tr></thead>
          <tbody>{slice.map((r, i) => <tr key={r[rowKey] ?? i} onClick={onRowClick ? () => onRowClick(r) : undefined} style={{ cursor: onRowClick ? 'pointer' : 'default' }}>
            {columns.map(c => <td key={c.key} className={c.money || c.align === 'right' ? 'text-right' : ''}>{cell(c, r)}</td>)}</tr>)}</tbody></table></div>)}
      <div style={{ marginTop: 8 }} className="flex items-center justify-between"><span className="text-xs text-muted">{filtered.length} {filtered.length === 1 ? 'row' : 'rows'}</span><Pager page={page} pageCount={pages} onPage={setPage} /></div>
    </div>)
}

// ---- forms ----------------------------------------------------------------------------------------------------------------------------------------
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
export const Check = ({ label: l, checked, onChange, hint }) => <Field label="" hint={hint}><label className="flex items-center gap-1"><input type="checkbox" checked={!!checked} onChange={onChange} /> {l}</label></Field>
export const Grid = ({ cols = 2, children }) => <div style={{ display: 'grid', gridTemplateColumns: `repeat(${cols}, minmax(0,1fr))`, gap: '0 14px' }}>{children}</div>

// ---- prompt (inputs + reason) and confirm ---------------------------------------------------------------------------------------------------------------
export function usePrompt() {
  const [req, setReq] = useState(null)
  const [vals, setVals] = useState({})
  const ask = useCallback(opts => new Promise(resolve => { setVals(Object.fromEntries((opts.fields || []).map(f => [f.key, f.value ?? '']))); setReq({ ...opts, resolve }) }), [])
  const close = ok => { req.resolve(ok ? { ok: true, values: vals } : { ok: false }); setReq(null) }
  const missing = req && (req.fields || []).some(f => f.required !== false && !String(vals[f.key] ?? '').trim())
  const dialog = req && (
    <Modal title={req.title} onClose={() => close(false)} width={480}>
      {req.message && <p style={{ marginTop: 0 }}>{req.message}</p>}
      {(req.fields || []).map(f => <Input key={f.key} label={f.label} type={f.type || 'text'} value={vals[f.key]} hint={f.hint} onChange={e => setVals(s => ({ ...s, [f.key]: e.target.value }))} />)}
      <div className="flex gap-1" style={{ justifyContent: 'flex-end' }}><button className="btn btn-outline" onClick={() => close(false)}>Cancel</button>
        <button className={`btn ${req.danger ? 'btn-danger' : 'btn-primary'}`} disabled={!!missing} onClick={() => close(true)}>{req.confirmLabel || 'Confirm'}</button></div>
    </Modal>)
  return [dialog, ask]
}

// ---- tagged working: the five provenance kinds + review -------------------------------------------------------------------------------------------------------
const KIND = { source: ['Source data', 'badge-info'], calculated: ['Calculated', 'badge-neutral'], user_entered: ['Entered', 'badge-warning'], input: ['Entered', 'badge-warning'],
  assumption: ['Assumption', 'badge-warning'], estimate: ['Estimate', 'badge-warning'], review: ['Needs review', 'badge-danger'], warning: ['Warning', 'badge-warning'] }
export const KindTag = ({ kind }) => { const [t, c] = KIND[kind] || [label(kind), 'badge-neutral']; return <span className={`badge ${c}`} title={`How this figure was produced: ${t}`}>{t}</span> }
const SEV = { error: ['✖', 'var(--danger)'], warn: ['▲', 'var(--warning)'], review: ['◆', 'var(--danger)'], info: ['ℹ', 'var(--text-muted)'] }
export const Findings = ({ items = [] }) => items.length === 0 ? <div className="text-sm text-muted">No findings.</div> : (
  <div role="list" aria-label="Findings">{items.map((f, i) => { const [ic, col] = SEV[f.severity] || SEV.info
    return <div role="listitem" key={f.key + i} className="text-sm" style={{ color: col, padding: '3px 0' }}><strong>{ic} {label(f.severity)}</strong> <span style={{ color: 'var(--text)' }}>{f.message}</span></div> })}</div>)
export const Steps = ({ steps = [] }) => (
  <table className="data-table"><thead><tr><th>Working</th><th>Basis</th><th className="text-right">Amount</th></tr></thead>
    <tbody>{steps.map((s, i) => <tr key={s.key + i}><td>{s.label}{s.note && <div className="text-xs text-muted">{s.note}</div>}</td><td><KindTag kind={s.kind} /></td><td className="text-right">{s.amount == null ? '—' : <Money v={s.amount} />}</td></tr>)}</tbody></table>)

export const LODGE_NOTE = 'AccFino prepares, checks and records. It does not submit anything to the ATO: lodge through ATO Online services, myTax or your registered tax agent, then record the receipt reference here.'
export const Disclaimer = () => <div className="text-xs text-muted" style={{ margin: '4px 0 12px' }}>{LODGE_NOTE} Prepared figures are for review and are not tax advice; items marked “Needs review” require a registered tax agent.</div>

// ---- document workflow bar (BAS, income tax return, FBT return) ---------------------------------------------------------------------------------------------------
export function WorkflowBar({ doc, caps, api, onChange, extra, noun = 'document', declarationOk }) {
  const [dialog, ask] = usePrompt()
  const can = c => caps.includes(c)
  const run = async (fn, ok) => { const r = await act(fn, ok); if (r) onChange(r === true ? undefined : r) }
  const s = doc.status
  const lodge = async () => { const r = await ask({ title: `Record that this ${noun} was lodged`, message: LODGE_NOTE, confirmLabel: 'Record lodgement',
    fields: [{ key: 'reference', label: 'ATO receipt / reference number' }, { key: 'lodged_on', label: 'Lodged on', type: 'date', required: false }] })
    if (r.ok) run(() => api.lodged(doc.id, { ...r.values, lodged_on: r.values.lodged_on || undefined }), 'Lodgement recorded') }
  const paid = async () => { const r = await ask({ title: 'Record payment', confirmLabel: 'Record', fields: [{ key: 'paid_on', label: 'Paid on', type: 'date', required: false }] }); if (r.ok) run(() => api.paid(doc.id, { paid_on: r.values.paid_on || undefined }), 'Payment recorded') }
  const approve = async () => { const r = await ask({ title: `Approve this ${noun}`, message: 'Approval confirms the figures were reviewed against their sources.', confirmLabel: 'Approve', fields: [{ key: 'note', label: 'Approval note', required: false }] }); if (r.ok) run(() => api.approve(doc.id, r.values), 'Approved') }
  const back = async () => { const r = await ask({ title: 'Return to draft', fields: [{ key: 'note', label: 'Reason', required: false }], confirmLabel: 'Return to draft' }); if (r.ok) run(() => api.back(doc.id, r.values), 'Returned to draft') }
  const voidIt = async () => { const r = await ask({ title: `Void this ${noun}`, danger: true, confirmLabel: 'Void', fields: [{ key: 'reason', label: 'Reason (at least 5 characters)' }] }); if (r.ok) run(() => api.void(doc.id, r.values), 'Voided') }
  return (
    <div className="flex items-center gap-1" style={{ flexWrap: 'wrap', padding: '8px 0' }}>
      {dialog}
      <StatusBadge status={s} />
      {['draft', 'prepared'].includes(s) && can('prepare') && api.calculate && <button className="btn btn-outline btn-sm" onClick={() => run(() => api.calculate(doc.id), 'Recalculated')}>{doc.calculated ? 'Recalculate' : 'Calculate'}</button>}
      {s === 'draft' && can('prepare') && doc.calculated && <button className="btn btn-primary btn-sm" onClick={() => run(() => api.prepare(doc.id), 'Marked prepared')}>Mark prepared</button>}
      {s === 'prepared' && can('approve') && <button className="btn btn-primary btn-sm" onClick={approve}>Approve</button>}
      {['prepared', 'approved'].includes(s) && can('prepare') && <button className="btn btn-outline btn-sm" onClick={back}>Return to draft</button>}
      {s === 'approved' && can('lodge') && declarationOk !== false && <button className="btn btn-primary btn-sm" onClick={lodge}>Record lodgement</button>}
      {s === 'approved' && can('lodge') && declarationOk === false && <span className="text-xs text-muted">Sign-off needed below before lodgement can be recorded.</span>}
      {s === 'lodged' && can('lodge') && <button className="btn btn-primary btn-sm" onClick={paid}>Record payment</button>}
      {['draft', 'prepared', 'approved'].includes(s) && can('prepare') && api.void && <button className="btn btn-ghost btn-sm" onClick={voidIt}>Void</button>}
      {extra}
      {s === 'prepared' && !can('approve') && <span className="text-xs text-muted">Waiting for an approver (Accountant or Organisation Admin).</span>}
    </div>)
}
