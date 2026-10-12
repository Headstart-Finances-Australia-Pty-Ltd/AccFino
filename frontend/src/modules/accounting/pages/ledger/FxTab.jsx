import React, { useEffect, useState } from 'react'
import toast from 'react-hot-toast'
import { RefreshCw, Coins } from 'lucide-react'
import * as api__0 from '../../../../core/lib/platformApi.js'
import * as api__1 from '../../lib/ledgerApi.js'
import { FxRatesModal } from './JournalTools.jsx'
import { money, today } from './JournalEditor.jsx'

const iso = d => d.toISOString().slice(0, 10)
const monthEnd = () => { const d = new Date(); return iso(new Date(d.getFullYear(), d.getMonth() + 1, 0)) }
const yearStart = () => { const d = new Date(); return `${d.getMonth() >= 6 ? d.getFullYear() : d.getFullYear() - 1}-07-01` }
const gl = v => (Number(v) > 0 ? 'gain' : Number(v) < 0 ? 'loss' : 'nil')
const Sign = ({ v }) => <span className="mono" style={{ color: Number(v) < 0 ? 'var(--danger, #dc2626)' : Number(v) > 0 ? 'var(--success, #16a34a)' : undefined }}>{money(v)}</span>

// ── Rates and the automatic feed ─────────────────────────────────────────────────────────────────────────
function FeedPanel({ canApprove, settings, onSettings }) {
  const [st, setSt] = useState(null); const [busy, setBusy] = useState(false); const [extra, setExtra] = useState('')
  const [rates, setRates] = useState(false)
  const load = () => api__1.fxFeed().then(r => { setSt(r.data); setExtra((r.data.currencies || []).join(', ')) }).catch(() => {})
  useEffect(() => { load() }, [settings.fx_feed_enabled])
  const run = async backfill => {
    setBusy(true)
    try { const { data: r } = await api__1.fxFeedRun({ backfill }); toast.success(`${r.stored} rate(s) stored${r.updated ? `, ${r.updated} updated` : ''}${r.kept_manual ? `, ${r.kept_manual} of yours kept` : ''}`); if (r.unsupported?.length) toast.error(`Not published by the source: ${r.unsupported.join(', ')}`); load() }
    catch (e) { toast.error(api__0.errMsg(e)) } finally { setBusy(false) }
  }
  const saveCurrencies = async () => { try { await onSettings({ fx_feed_currencies: extra.split(/[ ,;]+/).filter(Boolean) }); toast.success('Currencies saved'); load() } catch (e) { toast.error(api__0.errMsg(e)) } }
  const lr = st?.last_run
  return (
    <div className="card" style={{ padding: 14, marginBottom: 14 }} data-testid="feed-panel">
      <div className="flex items-center justify-between" style={{ flexWrap: 'wrap', gap: 8 }}>
        <h4 style={{ margin: 0 }}>Exchange rates</h4>
        <button className="btn btn-outline btn-sm" onClick={() => setRates(true)}><Coins size={14} /> Enter or edit rates</button>
      </div>
      <p className="text-sm text-muted" style={{ margin: '6px 0' }}>Your own rates are always used first. The optional feed adds daily <b>ECB reference rates</b> (converted to {st?.base || 'your base currency'}) for the currencies below; a rate you typed for a day is never overwritten. These are reference rates, not what your bank charged.</p>
      {canApprove && <label className="text-sm"><input type="checkbox" checked={!!settings.fx_feed_enabled} onChange={e => onSettings({ fx_feed_enabled: e.target.checked })} /> Fetch rates automatically each business day</label>}
      {st && <div className="text-sm" style={{ marginTop: 6 }}>Currencies fetched: <b data-testid="feed-currencies">{st.effective_currencies.length ? st.effective_currencies.join(', ') : 'none yet'}</b> <span className="text-muted">(includes any used by foreign-currency accounts and templates)</span></div>}
      {canApprove && <div className="flex gap-1" style={{ marginTop: 6, flexWrap: 'wrap' }}>
        <input aria-label="Extra currencies" className="input input-sm" style={{ width: 220 }} placeholder="Extra currencies: USD, EUR, GBP" value={extra} onChange={e => setExtra(e.target.value.toUpperCase())} />
        <button className="btn btn-outline btn-sm" onClick={saveCurrencies}>Save currencies</button>
        <button className="btn btn-primary btn-sm" disabled={busy} onClick={() => run(false)}><RefreshCw size={13} /> Fetch now</button>
        <button className="btn btn-outline btn-sm" disabled={busy} onClick={() => run(true)}>Back-fill 90 days</button></div>}
      {lr && <div className="text-xs" style={{ marginTop: 6, color: lr.ok ? undefined : 'var(--danger, #dc2626)' }} data-testid="feed-last">{lr.ok ? `Last fetch ${new Date(lr.at).toLocaleString('en-AU')}: ${lr.stored ?? 0} stored, source ${lr.source}.` : `Last fetch failed: ${lr.error}`}</div>}
      {rates && <FxRatesModal onClose={() => { setRates(false); load() }} />}
    </div>)
}

// ── Which accounts are held in a foreign currency ────────────────────────────────────────────────────────
function AccountsPanel({ canApprove, onChanged }) {
  const [rows, setRows] = useState([]); const [base, setBase] = useState('AUD'); const [edit, setEdit] = useState({})
  const load = () => api__1.fxAccounts().then(r => { setRows(r.data.items || []); setBase(r.data.base || 'AUD') }).catch(e => toast.error(api__0.errMsg(e)))
  useEffect(() => { load() }, [])
  const save2 = async a => {
    const cur = (edit.cur || '').toUpperCase()
    if (!window.confirm(`Hold ${a.code} ${a.name} in ${cur}?\n\nFrom now on every posting to it must be in ${cur}, and it will be revalued at each period end. This can only be changed while the account has no postings.`)) return
    try { await api__1.setFxAccount(a.id, cur); toast.success(`${a.code} is now held in ${cur}`); setEdit({}); load(); onChanged?.() } catch (e) { toast.error(api__0.errMsg(e)) }
  }
  const foreign = rows.filter(r => r.currency); const candidates = rows.filter(r => !r.currency)
  return (
    <div className="card" style={{ padding: 14, marginBottom: 14 }} data-testid="accounts-panel">
      <h4 style={{ margin: '0 0 6px' }}>Foreign-currency accounts</h4>
      <p className="text-sm text-muted" style={{ margin: '0 0 8px' }}>A bank account, card or loan can be held in a foreign currency. Its balance is tracked in that currency, money going out leaves at average cost (so a realised gain or loss is recorded), and it is revalued at period end. Invoices and bills stay in {base}.</p>
      <div className="data-table-wrap"><table className="data-table"><thead><tr><th>Account</th><th>Currency</th><th className="text-right">Foreign balance</th><th className="text-right">Value in {base} (cost)</th><th /></tr></thead>
        <tbody>{foreign.map(a => <tr key={a.id}><td>{a.code} · {a.name}</td><td><b>{a.currency}</b></td><td className="text-right mono">{money(a.foreign_balance, a.currency)}</td><td className="text-right mono">{money(a.base_value)}</td>
          <td /></tr>)}
          {!foreign.length && <tr><td colSpan={5} className="text-center text-muted">No account is held in a foreign currency yet.</td></tr>}</tbody></table></div>
      {canApprove && <div className="flex gap-1" style={{ marginTop: 10, flexWrap: 'wrap', alignItems: 'center' }}>
        <select aria-label="Account to hold in a foreign currency" className="input input-sm" value={edit.pick || ''} onChange={e => setEdit(x => ({ ...x, pick: e.target.value }))}>
          <option value="">Choose an account…</option>{candidates.map(a => <option key={a.id} value={a.id} disabled={a.has_postings}>{a.code} {a.name}{a.has_postings ? ' (has postings)' : ''}</option>)}</select>
        <input aria-label="Currency code" className="input input-sm" style={{ width: 80 }} maxLength={3} placeholder="USD" value={edit.cur || ''} onChange={e => setEdit(x => ({ ...x, cur: e.target.value.toUpperCase() }))} />
        <button className="btn btn-primary btn-sm" disabled={!edit.pick || (edit.cur || '').length !== 3} onClick={() => { const a = rows.find(r => String(r.id) === String(edit.pick)); save2(a) }} data-testid="set-fx-account">Hold in this currency</button>
        <span className="text-xs text-muted">Create a new bank account under Chart of Accounts first — an account that already has postings can’t be switched.</span></div>}
    </div>)
}

// ── Revaluation ──────────────────────────────────────────────────────────────────────────────────────────
function RevaluationPanel({ canApprove, onChanged }) {
  const [asAt, setAsAt] = useState(monthEnd()); const [pv, setPv] = useState(null); const [reverse, setReverse] = useState(true); const [busy, setBusy] = useState(false)
  const load = () => api__1.fxRevaluation(asAt).then(r => setPv(r.data)).catch(e => { setPv(null); toast.error(api__0.errMsg(e)) })
  useEffect(() => { load() }, [asAt])
  const post = async () => {
    if (!window.confirm(`Post the revaluation at ${asAt}?\\n\\nThis books an UNREALISED gain or loss to the ledger${reverse ? ' and reverses it automatically the next day' : ' (it will NOT reverse itself)'}.`)) return
    setBusy(true)
    try { const { data: r } = await api__1.fxRevalue({ as_at: asAt, reverse }); toast.success(r.nothing_to_do ? 'Nothing to post — already up to date' : `Posted ${r.posted.length} revaluation journal(s)`); load(); onChanged?.() }
    catch (e) { toast.error(api__0.errMsg(e)) } finally { setBusy(false) }
  }
  return (
    <div className="card" style={{ padding: 14, marginBottom: 14 }} data-testid="reval-panel">
      <div className="flex items-center gap-2" style={{ flexWrap: 'wrap' }}><h4 style={{ margin: 0 }}>Period-end revaluation</h4>
        <label className="text-sm">as at <input aria-label="Revalue as at" type="date" className="input input-sm" value={asAt} onChange={e => setAsAt(e.target.value)} /></label></div>
      <p className="text-sm text-muted" style={{ margin: '6px 0' }}>Restates each foreign-currency account to the closing rate. The difference is an <b>unrealised</b> gain or loss; it reverses the next day so it is never counted twice when the money is actually spent or converted.</p>
      {pv && pv.missing_rates.length > 0 && <div className="alert alert-warning" data-testid="missing-rates">No rate on or before {asAt} for <b>{pv.missing_rates.join(', ')}</b>. Add the closing rate under Exchange rates (or fetch it) — AccFino will not guess one.</div>}
      {pv && pv.rows.length === 0 && <div className="text-sm text-muted">No foreign-currency account has a balance at this date.</div>}
      {pv && pv.rows.length > 0 && <div className="data-table-wrap"><table className="data-table" data-testid="reval-table"><thead><tr><th>Account</th><th className="text-right">Balance</th><th className="text-right">Cost ({pv.base})</th><th className="text-right">Rate</th><th className="text-right">Revalued</th><th className="text-right">Unrealised</th><th className="text-right">To post</th></tr></thead>
        <tbody>{pv.rows.map(r => <tr key={r.account_id}><td>{r.code} · {r.name}</td><td className="text-right mono">{money(r.foreign_balance, r.currency)}</td><td className="text-right mono">{money(r.historical_base)}</td>
          <td className="text-right mono">{r.rate ? Number(r.rate) : '—'}</td><td className="text-right mono">{r.revalued_base != null ? money(r.revalued_base) : '—'}</td>
          <td className="text-right">{r.adjustment != null ? <Sign v={r.adjustment} /> : '—'}</td><td className="text-right">{r.to_post != null ? <Sign v={r.to_post} /> : '—'}</td></tr>)}</tbody></table></div>}
      {canApprove && <div className="flex items-center gap-2" style={{ marginTop: 10, flexWrap: 'wrap' }}>
        <label className="text-sm"><input type="checkbox" checked={reverse} onChange={e => setReverse(e.target.checked)} /> Reverse automatically the next day (recommended)</label>
        <button className="btn btn-primary btn-sm" disabled={busy || !pv?.can_post} onClick={post}>Post revaluation</button>
        {pv && pv.rows.length > 0 && !pv.missing_rates.length && !pv.can_post && <span className="text-xs text-muted">Already up to date at this date.</span>}</div>}
      {!canApprove && <div className="text-xs text-muted" style={{ marginTop: 6 }}>Only an approver can post a revaluation.</div>}
    </div>)
}

// ── Gains and losses ─────────────────────────────────────────────────────────────────────────────────────
function GainsLosses() {
  const [f, setF] = useState({ from: yearStart(), to: today() }); const [r, setR] = useState(null)
  const load = () => api__1.fxGainsLosses(f.from, f.to).then(x => setR(x.data)).catch(e => toast.error(api__0.errMsg(e)))
  useEffect(() => { load() }, []) // eslint-disable-line react-hooks/exhaustive-deps
  return (
    <div className="card" style={{ padding: 14 }} data-testid="gl-panel">
      <div className="flex items-center gap-2" style={{ flexWrap: 'wrap' }}><h4 style={{ margin: 0 }}>Foreign exchange gains &amp; losses</h4>
        <input aria-label="Gains from" type="date" className="input input-sm" value={f.from} onChange={e => setF({ ...f, from: e.target.value })} />
        <input aria-label="Gains to" type="date" className="input input-sm" value={f.to} onChange={e => setF({ ...f, to: e.target.value })} />
        <button className="btn btn-outline btn-sm" onClick={load}>Run</button></div>
      {r && <>
        <div className="stats-grid" style={{ margin: '10px 0' }}>
          {[['Realised', r.realised.total], ['Unrealised', r.unrealised.total], ['Net', r.net]].map(([l, v]) => <div key={l} className="stat-card"><div className="stat-label">{l} ({gl(v)})</div><div className="stat-value"><Sign v={v} /></div></div>)}</div>
        {[['Realised', r.realised], ['Unrealised', r.unrealised]].map(([l, x]) => x.by_currency.length > 0 && <div key={l} className="text-sm" style={{ marginBottom: 4 }}><b>{l} by currency:</b> {x.by_currency.map(c => <span key={c.currency} style={{ marginRight: 12 }}>{c.currency} <Sign v={c.amount} /></span>)}</div>)}
        {r.positions.length > 0 && <div className="data-table-wrap" style={{ marginTop: 8 }}><table className="data-table"><thead><tr><th>Position at {r.to}</th><th className="text-right">Foreign balance</th><th className="text-right">Cost ({r.base})</th><th className="text-right">At closing rate</th></tr></thead>
          <tbody>{r.positions.map(p => <tr key={p.code}><td>{p.code} · {p.name}</td><td className="text-right mono">{money(p.foreign_balance, p.currency)}</td><td className="text-right mono">{money(p.historical_base)}</td><td className="text-right mono">{p.revalued_base != null ? money(p.revalued_base) : '—'}</td></tr>)}</tbody></table></div>}
        <p className="text-xs text-muted">Gains are positive, losses negative. Realised = recorded when money is spent or converted; unrealised = the period-end revaluation (which reverses the next day, so a later period shows the reversal).</p></>}
    </div>)
}

export default function FxTab({ canApprove, settings, onSettings, onChanged }) {
  return (
    <div>
      <FeedPanel canApprove={canApprove} settings={settings} onSettings={onSettings} />
      <AccountsPanel canApprove={canApprove} onChanged={onChanged} />
      <RevaluationPanel canApprove={canApprove} onChanged={onChanged} />
      <GainsLosses />
    </div>)
}
