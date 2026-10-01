/**
 * reportKit - shared formatting helpers and UI atoms for every report screen (FinancialReports + ExtraReports).
 * Moved out of FinancialReports.jsx unchanged so the newer reports reuse exactly the same look and error handling.
 */
import React, { useEffect, useState, useCallback, useRef } from 'react'
import { ChevronDown, ChevronRight } from 'lucide-react'
import * as ledger from '../../lib/platformApi.js'

// ── formatting (all API amounts arrive as strings) ────────────────────────────
export const num = v => { const n = Number(v); return Number.isFinite(n) ? n : 0 }
export const fmtAUD = v => {
  if (v == null || v === '' || Number.isNaN(Number(v))) return '—'
  const n = Number(v)
  const s = new Intl.NumberFormat('en-AU', { style: 'currency', currency: 'AUD', minimumFractionDigits: 2 }).format(Math.abs(n))
  return n < 0 ? `(${s})` : s
}
export const fmtPct = n => (n == null || !Number.isFinite(n)) ? '—' : `${(n * 100).toFixed(1)}%`
export const fmtDate = d => d ? new Date(d + (String(d).length === 10 ? 'T00:00:00' : '')).toLocaleDateString('en-AU') : '—'
export const iso = d => d.toISOString().slice(0, 10)
export const todayISO = () => iso(new Date())
export const fyStart = () => { const d = new Date(); const y = d.getMonth() >= 6 ? d.getFullYear() : d.getFullYear() - 1; return `${y}-07-01` }
export const arr = v => Array.isArray(v) ? v : []
export const sum = rows => arr(rows).reduce((s, r) => s + num(r?.amount), 0)


// ── shared UI atoms ───────────────────────────────────────────────────────────
export function Sec({ label, total, accent = 'var(--brand)', children, open: init = true }) {
  const [open, setOpen] = useState(init)
  return (
    <div style={{ marginBottom: 3 }}>
      <button onClick={() => setOpen(o => !o)} style={{
        width: '100%', display: 'flex', alignItems: 'center', justifyContent: 'space-between',
        padding: '9px 14px', background: 'var(--surface-2)', border: 'none', cursor: 'pointer',
        fontFamily: 'inherit', borderRadius: 'var(--r-md)', borderLeft: `4px solid ${accent}`, marginBottom: open ? 3 : 0,
      }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 7 }}>
          {open ? <ChevronDown size={12} color="var(--text-3)" /> : <ChevronRight size={12} color="var(--text-3)" />}
          <span style={{ fontWeight: 700, fontSize: '.85rem' }}>{label}</span>
        </div>
        <span style={{ fontFamily: 'var(--font-mono)', fontWeight: 700, fontSize: '.85rem', color: total < 0 ? 'var(--danger)' : 'var(--text-1)' }}>{fmtAUD(total)}</span>
      </button>
      {open && <div style={{ paddingLeft: 3 }}>{children}</div>}
    </div>
  )
}
export const R = ({ account, amount }) => (
  <div style={{ display: 'flex', justifyContent: 'space-between', padding: '5px 14px', borderBottom: '1px solid var(--border)', fontSize: '.8rem' }}>
    <span style={{ color: 'var(--text-2)' }}>{account}</span>
    <span style={{ fontFamily: 'var(--font-mono)', color: num(amount) < 0 ? 'var(--danger)' : 'var(--text-1)', fontWeight: num(amount) < 0 ? 600 : 400 }}>{fmtAUD(amount)}</span>
  </div>
)
export const Rows = ({ rows }) => arr(rows).map((r, i) => <R key={r?.account_id ?? i} account={`${r?.code ?? ''} · ${r?.name ?? ''}`} amount={r?.amount} />)
export const Tot = ({ label, amount, strong = false, bg = false }) => (
  <div style={{
    display: 'flex', justifyContent: 'space-between', padding: strong ? '10px 14px' : '7px 14px',
    background: bg ? 'var(--surface-2)' : 'transparent', borderTop: strong ? '2px solid var(--border)' : '1px solid var(--border)',
    borderBottom: strong ? '2px solid var(--border)' : 'none', fontSize: strong ? '.9rem' : '.82rem' }}>
    <span style={{ fontWeight: strong ? 700 : 600 }}>{label}</span>
    <span style={{ fontFamily: 'var(--font-mono)', fontWeight: strong ? 700 : 600,
      color: num(amount) < 0 ? 'var(--danger)' : num(amount) > 0 ? 'var(--success)' : 'var(--text-1)' }}>{fmtAUD(amount)}</span>
  </div>
)
export const GH = ({ label }) => (
  <div style={{ padding: '8px 14px', fontWeight: 700, fontSize: '.72rem', color: 'var(--text-3)', textTransform: 'uppercase', letterSpacing: '.07em', marginTop: 6 }}>{label}</div>
)
export const EmptyState = ({ title, detail }) => (
  <div style={{ padding: '48px 24px', textAlign: 'center', color: 'var(--text-3)' }}>
    <div style={{ fontSize: '1.8rem', marginBottom: 10 }}>📭</div>
    <div style={{ fontWeight: 700, fontSize: '.9rem', color: 'var(--text-1)', marginBottom: 6 }}>{title}</div>
    <div style={{ maxWidth: 440, margin: '0 auto', fontSize: '.82rem', lineHeight: 1.6 }}>{detail}</div>
  </div>
)
export const ReportLoading = () => <div style={{ padding: 48, textAlign: 'center', color: 'var(--text-3)' }}><span className="spinner" /> Loading…</div>
export const Note = ({ children, warn }) => (
  <div style={{ marginTop: 14, padding: '8px 12px', background: warn ? '#fef3c7' : 'var(--surface-2)', borderRadius: 'var(--r-md)',
    fontSize: '.74rem', color: warn ? '#92400e' : 'var(--text-2)', border: `1px solid ${warn ? '#fde68a' : 'var(--border)'}` }}>{children}</div>
)
export const Badge = ({ ok, yes, no }) => (
  <span style={{ padding: '2px 8px', borderRadius: 100, fontSize: '.7rem', fontWeight: 700,
    color: ok ? '#166534' : '#92400e', background: ok ? '#dcfce7' : '#fef3c7' }}>{ok ? yes : no}</span>
)
export const Filters = ({ children, onRun, busy }) => (
  <div style={{ display: 'flex', alignItems: 'center', gap: 12, flexWrap: 'wrap', padding: '10px 14px', borderBottom: '1px solid var(--border)' }}>
    {children}
    <button className="btn btn-primary btn-sm" onClick={onRun} disabled={busy}>{busy ? 'Running…' : 'Run'}</button>
  </div>
)
export const DateField = ({ label, value, onChange }) => (
  <label className="text-sm">{label} <input type="date" className="input input-sm" value={value} onChange={e => onChange(e.target.value)} /></label>
)

// Loads a report; never throws into React. `deps` change -> reload.
export function useReport(fetcher, deps) {
  const [state, setState] = useState({ data: null, loading: true, error: '' })
  // `run` is memoised on `deps` (so deps changing reloads the report), but it must ALWAYS call the LATEST fetcher: otherwise a report
  // with deps [] keeps querying with the filter values from its first render, and "Run" silently ignores what the user just changed.
  const latest = useRef(fetcher)
  latest.current = fetcher
  const run = useCallback(() => {
    setState(s => ({ ...s, loading: true, error: '' }))
    Promise.resolve().then(() => latest.current())
      .then(r => setState({ data: r?.data ?? null, loading: false, error: '' }))
      .catch(e => setState({ data: null, loading: false, error: ledger.errMsg(e, 'Could not load this report') }))
  }, deps) // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => { run() }, [run])
  return { ...state, run }
}
export const ErrorState = ({ error, run }) => (
  <EmptyState title="This report could not be loaded" detail={<>{error}<br /><button className="btn btn-outline btn-sm" style={{ marginTop: 10 }} onClick={run}>Try again</button></>} />
)

export class ReportBoundary extends React.Component {
  state = { err: null }
  static getDerivedStateFromError(err) { return { err } }
  componentDidCatch(err) { console.error('[Reports] render failed:', err) }
  componentDidUpdate(prev) { if (prev.resetKey !== this.props.resetKey && this.state.err) this.setState({ err: null }) }
  render() {
    if (this.state.err) return <EmptyState title="This report hit a display problem" detail={`${this.state.err?.message || 'Unexpected data'}. Try another report or run it again.`} />
    return this.props.children
  }
}

