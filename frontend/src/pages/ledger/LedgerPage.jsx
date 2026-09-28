import React, { useEffect, useMemo, useState } from 'react'
import toast from 'react-hot-toast'
import { BookOpen, Plus, RotateCcw, RefreshCw, Eye, Scale } from 'lucide-react'
import * as api from '../../lib/platformApi.js'

// ── helpers ────────────────────────────────────────────────────────────────
const aud = v => {
  const n = Number(v || 0)
  return n.toLocaleString('en-AU', { style: 'currency', currency: 'AUD' })
}
const iso = d => d.toISOString().slice(0, 10)
const today = () => iso(new Date())
const fyStart = () => {
  const d = new Date(); const y = d.getMonth() >= 6 ? d.getFullYear() : d.getFullYear() - 1
  return `${y}-07-01`
}
const TYPE_LABEL = {
  bank: 'Bank', current_asset: 'Current Asset', inventory: 'Inventory', fixed_asset: 'Fixed Asset',
  non_current_asset: 'Non-current Asset', credit_card: 'Credit Card', current_liability: 'Current Liability',
  non_current_liability: 'Non-current Liability', equity: 'Equity', revenue: 'Revenue', other_income: 'Other Income',
  direct_costs: 'Direct Costs', expense: 'Expense', other_expense: 'Other Expense',
}
const CLASSES = ['all', 'asset', 'liability', 'equity', 'revenue', 'expense']

function Modal({ title, onClose, children, width = 560 }) {
  return (
    <div className="modal-overlay" onClick={onClose}>
      <div className="modal" onClick={e => e.stopPropagation()} style={{ maxWidth: width, width: '95%', maxHeight: '90vh', overflow: 'auto' }}>
        <div className="modal-header"><h3 style={{ margin: 0 }}>{title}</h3>
          <button className="btn btn-ghost btn-xs" onClick={onClose}>✕</button></div>
        <div style={{ padding: 18 }}>{children}</div>
      </div>
    </div>
  )
}

// ── Chart of accounts ────────────────────────────────────────────────────────
function AccountsTab({ taxes }) {
  const [rows, setRows] = useState([])
  const [cls, setCls] = useState('all')
  const [q, setQ] = useState('')
  const [showInactive, setShowInactive] = useState(false)
  const [edit, setEdit] = useState(null)
  const [types, setTypes] = useState([])

  const load = () => api.accounts(showInactive).then(r => setRows(r.data)).catch(e => toast.error(api.errMsg(e)))
  useEffect(() => { load() }, [showInactive])
  useEffect(() => { api.accountTypes().then(r => setTypes(r.data)).catch(() => {}) }, [])

  const shown = rows.filter(a => (cls === 'all' || a.class === cls) &&
    (!q || `${a.code} ${a.name}`.toLowerCase().includes(q.toLowerCase())))

  const save = async () => {
    try {
      const body = { code: edit.code, name: edit.name, description: edit.description || null,
                     default_tax_code_id: edit.default_tax_code_id ? Number(edit.default_tax_code_id) : null }
      if (edit.id) await api.updateAccount(edit.id, body)
      else await api.createAccount({ ...body, type: edit.type })
      toast.success('Account saved'); setEdit(null); load()
    } catch (e) { toast.error(api.errMsg(e)) }
  }
  const toggleActive = async a => {
    try { await api.updateAccount(a.id, { is_active: !a.is_active }); toast.success(a.is_active ? 'Account archived' : 'Account restored'); load() }
    catch (e) { toast.error(api.errMsg(e)) }
  }

  return (
    <div>
      <div className="flex items-center gap-4" style={{ flexWrap: 'wrap', marginBottom: 12 }}>
        <div className="tabs-bar" style={{ margin: 0 }}>
          {CLASSES.map(c => <button key={c} className={`tab-btn${cls === c ? ' active' : ''}`} onClick={() => setCls(c)}>
            {c === 'all' ? 'All' : c[0].toUpperCase() + c.slice(1)}</button>)}
        </div>
        <input className="input input-sm" style={{ maxWidth: 220 }} placeholder="Search code or name" value={q} onChange={e => setQ(e.target.value)} />
        <label className="text-sm"><input type="checkbox" checked={showInactive} onChange={e => setShowInactive(e.target.checked)} /> Show archived</label>
        <div className="flex-1" />
        <button className="btn btn-primary btn-sm" onClick={() => setEdit({ code: '', name: '', type: 'expense', default_tax_code_id: '' })}>
          <Plus size={14} /> Add account</button>
      </div>
      <div className="data-table-wrap">
        <table className="data-table">
          <thead><tr><th>Code</th><th>Name</th><th>Type</th><th>Default tax</th><th className="text-right">Balance</th><th></th></tr></thead>
          <tbody>
            {shown.map(a => (
              <tr key={a.id} style={{ opacity: a.is_active ? 1 : .5 }}>
                <td className="mono">{a.code}</td>
                <td>{a.name} {a.is_system && <span className="badge badge-neutral" title="System account used by AccFino">system</span>}</td>
                <td>{TYPE_LABEL[a.type] || a.type}</td>
                <td className="text-sm">{a.default_tax_code || '—'}</td>
                <td className="text-right mono">{aud(a.balance)}</td>
                <td className="text-right" style={{ whiteSpace: 'nowrap' }}>
                  <button className="btn btn-ghost btn-xs" onClick={() => setEdit({ ...a, default_tax_code_id: a.default_tax_code_id || '' })}>Edit</button>
                  {!a.is_system && <button className="btn btn-ghost btn-xs" onClick={() => toggleActive(a)}>{a.is_active ? 'Archive' : 'Restore'}</button>}
                </td>
              </tr>))}
            {!shown.length && <tr><td colSpan={6} className="text-center text-muted">No accounts</td></tr>}
          </tbody>
        </table>
      </div>
      <p className="text-xs text-muted mt-1">{shown.length} account(s). Balances are natural-sign (assets and expenses positive when debit).</p>

      {edit && (
        <Modal title={edit.id ? `Edit ${edit.code}` : 'New account'} onClose={() => setEdit(null)}>
          <div className="grid-2" style={{ gap: 12 }}>
            <div><label className="text-sm fw-600">Code</label><input className="input" value={edit.code} onChange={e => setEdit({ ...edit, code: e.target.value })} data-testid="acc-code" /></div>
            <div><label className="text-sm fw-600">Type</label>
              <select className="input" disabled={!!edit.id} value={edit.type} onChange={e => setEdit({ ...edit, type: e.target.value })}>
                {types.map(t => <option key={t.type} value={t.type}>{TYPE_LABEL[t.type] || t.type}</option>)}
              </select></div>
          </div>
          <label className="text-sm fw-600 mt-4" style={{ display: 'block' }}>Name</label>
          <input className="input" value={edit.name} onChange={e => setEdit({ ...edit, name: e.target.value })} data-testid="acc-name" />
          <label className="text-sm fw-600 mt-4" style={{ display: 'block' }}>Default tax code</label>
          <select className="input" value={edit.default_tax_code_id} onChange={e => setEdit({ ...edit, default_tax_code_id: e.target.value })}>
            <option value="">— none —</option>
            {taxes.map(t => <option key={t.id} value={t.id}>{t.name}</option>)}
          </select>
          <label className="text-sm fw-600 mt-4" style={{ display: 'block' }}>Description</label>
          <input className="input" value={edit.description || ''} onChange={e => setEdit({ ...edit, description: e.target.value })} />
          <div className="flex gap-1 mt-4"><button className="btn btn-primary" onClick={save}>Save</button>
            <button className="btn btn-ghost" onClick={() => setEdit(null)}>Cancel</button></div>
        </Modal>)}
    </div>
  )
}

// ── Journals ─────────────────────────────────────────────────────────────────
function JournalForm({ accountsList, taxes, onPosted, onClose }) {
  const blank = () => ({ account_id: '', description: '', debit: '', credit: '', tax_code_id: '' })
  const [date, setDate] = useState(today())
  const [narration, setNarration] = useState('')
  const [lines, setLines] = useState([blank(), blank()])
  const [busy, setBusy] = useState(false)
  const set = (i, k, v) => setLines(ls => ls.map((l, j) => j === i ? { ...l, [k]: v, ...(k === 'debit' && v ? { credit: '' } : {}), ...(k === 'credit' && v ? { debit: '' } : {}) } : l))
  const cents = v => Math.round(Number(v || 0) * 100)
  const dr = lines.reduce((s, l) => s + cents(l.debit), 0)
  const cr = lines.reduce((s, l) => s + cents(l.credit), 0)
  const balanced = dr === cr && dr > 0

  const post = async () => {
    setBusy(true)
    try {
      const body = { date, narration, lines: lines.filter(l => l.account_id && (l.debit || l.credit)).map(l => ({
        account_id: Number(l.account_id), description: l.description || null,
        debit: l.debit || '0', credit: l.credit || '0', tax_code_id: l.tax_code_id ? Number(l.tax_code_id) : null })) }
      const { data } = await api.postJournal(body)
      toast.success(`Journal ${data.journal_no} posted`); onPosted()
    } catch (e) { toast.error(api.errMsg(e)) } finally { setBusy(false) }
  }

  return (
    <Modal title="New manual journal" onClose={onClose} width={900}>
      <div className="grid-2" style={{ gap: 12 }}>
        <div><label className="text-sm fw-600">Date</label><input type="date" className="input" value={date} onChange={e => setDate(e.target.value)} /></div>
        <div><label className="text-sm fw-600">Narration</label><input className="input" value={narration} onChange={e => setNarration(e.target.value)} placeholder="e.g. Opening balances" data-testid="jnl-narration" /></div>
      </div>
      <div className="data-table-wrap mt-4">
        <table className="data-table">
          <thead><tr><th style={{ width: '32%' }}>Account</th><th>Description</th><th>Tax code</th><th className="text-right">Debit</th><th className="text-right">Credit</th><th></th></tr></thead>
          <tbody>
            {lines.map((l, i) => (
              <tr key={i}>
                <td><select className="input input-sm" value={l.account_id} onChange={e => set(i, 'account_id', e.target.value)}>
                  <option value="">Select…</option>
                  {accountsList.map(a => <option key={a.id} value={a.id}>{a.code} · {a.name}</option>)}
                </select></td>
                <td><input className="input input-sm" value={l.description} onChange={e => set(i, 'description', e.target.value)} /></td>
                <td><select className="input input-sm" value={l.tax_code_id} onChange={e => set(i, 'tax_code_id', e.target.value)}>
                  <option value="">—</option>{taxes.map(t => <option key={t.id} value={t.id}>{t.name}</option>)}</select></td>
                <td><input className="input input-sm text-right" inputMode="decimal" value={l.debit} onChange={e => set(i, 'debit', e.target.value)} /></td>
                <td><input className="input input-sm text-right" inputMode="decimal" value={l.credit} onChange={e => set(i, 'credit', e.target.value)} /></td>
                <td>{lines.length > 2 && <button className="btn btn-ghost btn-xs" onClick={() => setLines(ls => ls.filter((_, j) => j !== i))}>✕</button>}</td>
              </tr>))}
            <tr><td colSpan={3}><button className="btn btn-ghost btn-xs" onClick={() => setLines(ls => [...ls, blank()])}><Plus size={12} /> Add line</button></td>
              <td className="text-right mono fw-700">{aud(dr / 100)}</td><td className="text-right mono fw-700">{aud(cr / 100)}</td><td /></tr>
          </tbody>
        </table>
      </div>
      <div className={`alert ${balanced ? 'alert-success' : 'alert-warning'} mt-4`}>
        {balanced ? 'Journal balances.' : `Out of balance by ${aud(Math.abs(dr - cr) / 100)}. Debits must equal credits.`}
      </div>
      <div className="flex gap-1 mt-4">
        <button className="btn btn-primary" disabled={!balanced || !narration || busy} onClick={post}>{busy ? 'Posting…' : 'Post journal'}</button>
        <button className="btn btn-ghost" onClick={onClose}>Cancel</button>
      </div>
      <p className="text-xs text-muted mt-1">Posted journals can't be edited or deleted. To correct one, reverse it and post a new journal.</p>
    </Modal>
  )
}

function JournalsTab({ taxes }) {
  const [data, setData] = useState({ items: [], total: 0 })
  const [from, setFrom] = useState(fyStart())
  const [to, setTo] = useState(today())
  const [source, setSource] = useState('')
  const [view, setView] = useState(null)
  const [showNew, setShowNew] = useState(false)
  const [accs, setAccs] = useState([])

  const load = () => api.journals({ from, to, source_type: source || undefined, limit: 500 })
    .then(r => setData(r.data)).catch(e => toast.error(api.errMsg(e)))
  useEffect(() => { load() }, [from, to, source])
  useEffect(() => { api.accounts().then(r => setAccs(r.data)).catch(() => {}) }, [])

  const open = id => api.journal(id).then(r => setView(r.data)).catch(e => toast.error(api.errMsg(e)))
  const reverse = async j => {
    if (!window.confirm(`Reverse journal ${j.journal_no}? A reversing journal will be posted on the same date.`)) return
    try { const { data: r } = await api.reverseJournal(j.id); toast.success(`Reversal journal ${r.journal_no} posted`); setView(null); load() }
    catch (e) { toast.error(api.errMsg(e)) }
  }

  return (
    <div>
      <div className="flex items-center gap-4" style={{ flexWrap: 'wrap', marginBottom: 12 }}>
        <label className="text-sm">From <input type="date" className="input input-sm" value={from} onChange={e => setFrom(e.target.value)} /></label>
        <label className="text-sm">To <input type="date" className="input input-sm" value={to} onChange={e => setTo(e.target.value)} /></label>
        <select className="input input-sm" style={{ maxWidth: 180 }} value={source} onChange={e => setSource(e.target.value)}>
          <option value="">All sources</option><option value="manual">Manual</option><option value="bank_txn">Bank transactions</option><option value="reversal">Reversals</option>
        </select>
        <div className="flex-1" />
        <button className="btn btn-primary btn-sm" onClick={() => setShowNew(true)}><Plus size={14} /> New journal</button>
      </div>
      <div className="data-table-wrap">
        <table className="data-table">
          <thead><tr><th>No.</th><th>Date</th><th>Narration</th><th>Source</th><th>Status</th><th className="text-right">Total</th><th></th></tr></thead>
          <tbody>
            {data.items.map(j => (
              <tr key={j.id}>
                <td className="mono">{j.journal_no}</td><td>{j.date}</td><td className="truncate" style={{ maxWidth: 340 }}>{j.narration}</td>
                <td className="text-sm">{j.source_type}</td>
                <td>{j.status === 'reversed' ? <span className="badge badge-warning">reversed</span>
                  : j.reversal_of_id ? <span className="badge badge-info">reversal</span> : <span className="badge badge-success">posted</span>}</td>
                <td className="text-right mono">{aud(j.total)}</td>
                <td className="text-right"><button className="btn btn-ghost btn-xs" onClick={() => open(j.id)}><Eye size={12} /> View</button></td>
              </tr>))}
            {!data.items.length && <tr><td colSpan={7} className="text-center text-muted">No journals in this period</td></tr>}
          </tbody>
        </table>
      </div>
      <p className="text-xs text-muted mt-1">{data.total} journal(s)</p>

      {view && (
        <Modal title={`Journal ${view.journal_no} · ${view.date}`} onClose={() => setView(null)} width={820}>
          <p className="text-sm"><b>{view.narration}</b> <span className="text-muted">· source: {view.source_type}{view.source_ref ? ` (${view.source_ref})` : ''}</span></p>
          <div className="data-table-wrap"><table className="data-table">
            <thead><tr><th>Account</th><th>Description</th><th>Tax</th><th className="text-right">Debit</th><th className="text-right">Credit</th></tr></thead>
            <tbody>{view.lines.map(l => (
              <tr key={l.line_no}><td>{l.account_code} · {l.account_name}</td><td className="text-sm">{l.description}</td>
                <td className="text-sm">{l.tax_code || '—'}{Number(l.tax_amount) ? ` (${aud(l.tax_amount)})` : ''}</td>
                <td className="text-right mono">{Number(l.debit) ? aud(l.debit) : ''}</td><td className="text-right mono">{Number(l.credit) ? aud(l.credit) : ''}</td></tr>))}
            </tbody></table></div>
          {view.status === 'posted' && !view.reversal_of_id &&
            <button className="btn btn-outline btn-sm mt-4" onClick={() => reverse(view)}><RotateCcw size={13} /> Reverse journal</button>}
          {view.status === 'reversed' && <div className="alert alert-warning mt-4">This journal has been reversed.</div>}
        </Modal>)}
      {showNew && <JournalForm accountsList={accs} taxes={taxes} onClose={() => setShowNew(false)} onPosted={() => { setShowNew(false); load() }} />}
    </div>
  )
}

// ── Reports ──────────────────────────────────────────────────────────────────
function Section({ title, rows, total }) {
  if (!rows || !rows.length) return null
  return (<>
    <tr><td colSpan={2} className="fw-700" style={{ paddingTop: 14 }}>{title}</td></tr>
    {rows.map(r => <tr key={r.account_id}><td style={{ paddingLeft: 20 }}>{r.code} · {r.name}</td><td className="text-right mono">{aud(r.amount)}</td></tr>)}
    {total !== undefined && <tr><td className="fw-600" style={{ paddingLeft: 20 }}>Total {title}</td><td className="text-right mono fw-600">{aud(total)}</td></tr>}
  </>)
}

function ReportsTab() {
  const [kind, setKind] = useState('tb')
  const [from, setFrom] = useState(fyStart())
  const [to, setTo] = useState(today())
  const [acct, setAcct] = useState('')
  const [accs, setAccs] = useState([])
  const [data, setData] = useState(null)
  const [busy, setBusy] = useState(false)
  useEffect(() => { api.accounts(true).then(r => setAccs(r.data)).catch(() => {}) }, [])

  const run = async () => {
    setBusy(true); setData(null)
    try {
      const r = kind === 'tb' ? await api.trialBalance(to)
        : kind === 'pl' ? await api.profitLoss(from, to)
        : kind === 'bs' ? await api.balanceSheet(to)
        : await api.generalLedger(acct, from, to)
      setData(r.data)
    } catch (e) { toast.error(api.errMsg(e)) } finally { setBusy(false) }
  }
  useEffect(() => { if (kind !== 'gl') run() }, [kind])

  const flat = obj => Object.values(obj || {}).flat()
  return (
    <div>
      <div className="flex items-center gap-4" style={{ flexWrap: 'wrap', marginBottom: 12 }}>
        <div className="tabs-bar" style={{ margin: 0 }}>
          {[['tb', 'Trial Balance'], ['pl', 'Profit & Loss'], ['bs', 'Balance Sheet'], ['gl', 'Account Transactions']].map(([k, l]) =>
            <button key={k} className={`tab-btn${kind === k ? ' active' : ''}`} onClick={() => setKind(k)}>{l}</button>)}
        </div>
        {(kind === 'pl' || kind === 'gl') && <label className="text-sm">From <input type="date" className="input input-sm" value={from} onChange={e => setFrom(e.target.value)} /></label>}
        <label className="text-sm">{kind === 'pl' || kind === 'gl' ? 'To' : 'As at'} <input type="date" className="input input-sm" value={to} onChange={e => setTo(e.target.value)} /></label>
        {kind === 'gl' && <select className="input input-sm" style={{ maxWidth: 260 }} value={acct} onChange={e => setAcct(e.target.value)}>
          <option value="">Choose account…</option>{accs.map(a => <option key={a.id} value={a.id}>{a.code} · {a.name}</option>)}</select>}
        <button className="btn btn-primary btn-sm" disabled={busy || (kind === 'gl' && !acct)} onClick={run}>{busy ? 'Running…' : 'Run report'}</button>
      </div>

      {data && kind === 'tb' && (
        <div className="card">
          <h3 style={{ marginTop: 0 }}>Trial Balance as at {data.as_at}</h3>
          <div className="data-table-wrap"><table className="data-table">
            <thead><tr><th>Code</th><th>Account</th><th className="text-right">Debit</th><th className="text-right">Credit</th></tr></thead>
            <tbody>{data.rows.map(r => <tr key={r.account_id}><td className="mono">{r.code}</td><td>{r.name}</td>
              <td className="text-right mono">{Number(r.debit) ? aud(r.debit) : ''}</td><td className="text-right mono">{Number(r.credit) ? aud(r.credit) : ''}</td></tr>)}
              <tr className="fw-700"><td colSpan={2}>Total</td><td className="text-right mono">{aud(data.total_debit)}</td><td className="text-right mono">{aud(data.total_credit)}</td></tr>
            </tbody></table></div>
          <div className={`alert ${data.balanced ? 'alert-success' : 'alert-error'} mt-4`}>
            <Scale size={14} /> {data.balanced ? 'Debits equal credits.' : 'Trial balance does not balance - contact support.'}</div>
        </div>)}

      {data && kind === 'pl' && (
        <div className="card"><h3 style={{ marginTop: 0 }}>Profit &amp; Loss · {data.from} to {data.to}</h3>
          <table className="summary-table" style={{ width: '100%' }}><tbody>
            <Section title="Income" rows={data.income} total={data.total_income} />
            <Section title="Cost of Sales" rows={data.cost_of_sales} total={data.total_cost_of_sales} />
            <tr className="fw-700"><td style={{ paddingTop: 10 }}>Gross Profit</td><td className="text-right mono">{aud(data.gross_profit)}</td></tr>
            <Section title="Operating Expenses" rows={data.expenses} total={data.total_expenses} />
            <Section title="Other Income" rows={data.other_income} total={data.total_other_income} />
            <Section title="Other Expenses" rows={data.other_expenses} total={data.total_other_expenses} />
            <tr className="fw-700" style={{ borderTop: '2px solid var(--border-dark)' }}><td style={{ paddingTop: 10 }}>Net Profit</td><td className="text-right mono">{aud(data.net_profit)}</td></tr>
          </tbody></table></div>)}

      {data && kind === 'bs' && (
        <div className="card"><h3 style={{ marginTop: 0 }}>Balance Sheet as at {data.as_at}</h3>
          <table className="summary-table" style={{ width: '100%' }}><tbody>
            <Section title="Assets" rows={flat(data.assets)} total={data.total_assets} />
            <Section title="Liabilities" rows={flat(data.liabilities)} total={data.total_liabilities} />
            <tr className="fw-700"><td style={{ paddingTop: 10 }}>Net Assets</td><td className="text-right mono">{aud(data.net_assets)}</td></tr>
            <Section title="Equity" rows={data.equity} />
            <tr><td style={{ paddingLeft: 20 }}>Retained earnings (prior years)</td><td className="text-right mono">{aud(data.retained_earnings_prior_years)}</td></tr>
            <tr><td style={{ paddingLeft: 20 }}>Current year earnings (from {data.financial_year_start})</td><td className="text-right mono">{aud(data.current_year_earnings)}</td></tr>
            <tr className="fw-700"><td>Total Equity</td><td className="text-right mono">{aud(data.total_equity)}</td></tr>
          </tbody></table>
          <div className={`alert ${data.balanced ? 'alert-success' : 'alert-error'} mt-4`}>{data.balanced ? 'Net assets equal total equity.' : 'Balance sheet does not balance.'}</div>
        </div>)}

      {data && kind === 'gl' && (
        <div className="card"><h3 style={{ marginTop: 0 }}>{data.account.code} · {data.account.name} · {data.from} to {data.to}</h3>
          <div className="data-table-wrap"><table className="data-table">
            <thead><tr><th>Date</th><th>Journal</th><th>Description</th><th className="text-right">Debit</th><th className="text-right">Credit</th><th className="text-right">Balance</th></tr></thead>
            <tbody>
              <tr className="fw-600"><td colSpan={5}>Opening balance</td><td className="text-right mono">{aud(data.opening_balance)}</td></tr>
              {data.rows.map((r, i) => <tr key={i}><td>{r.date}</td><td className="mono">{r.journal_no}</td><td className="text-sm">{r.description || r.narration}</td>
                <td className="text-right mono">{Number(r.debit) ? aud(r.debit) : ''}</td><td className="text-right mono">{Number(r.credit) ? aud(r.credit) : ''}</td>
                <td className="text-right mono">{aud(r.balance)}</td></tr>)}
              <tr className="fw-700"><td colSpan={5}>Closing balance</td><td className="text-right mono">{aud(data.closing_balance)}</td></tr>
            </tbody></table></div></div>)}
    </div>
  )
}

// ── Bank sync ────────────────────────────────────────────────────────────────
function SyncTab() {
  const [res, setRes] = useState(null)
  const [busy, setBusy] = useState(false)
  const run = async dry => {
    setBusy(true)
    try { const { data } = await api.syncBank(dry); setRes(data); if (!dry) toast.success('Bank transactions posted to the ledger') }
    catch (e) { toast.error(api.errMsg(e)) } finally { setBusy(false) }
  }
  const labels = { transactions: 'Transactions checked', posted: 'Newly posted', updated: 'Changed & re-posted', unchanged: 'Already posted (no change)',
    to_suspense: 'Posted to Suspense (uncoded)', locked: 'Skipped - locked period', would_post: 'Would post', would_update: 'Would re-post',
    reversed_deleted: 'Reversed (deleted in reconciliation)', would_reverse_deleted: 'Would reverse (deleted)', skipped_zero: 'Skipped - zero amount',
    skipped_loan_split_exceeds_payment: 'Skipped - loan split larger than payment' }
  return (
    <div>
      <div className="card card-sm" style={{ marginBottom: 12 }}>
        <p style={{ marginTop: 0 }}>Post your saved, reconciled bank transactions into the general ledger. Each transaction becomes a balanced journal
          (bank ↔ GL account, with GST split to the GST account). Running it again only posts new or changed transactions; a transaction you change
          or delete in Reconciliation is reversed and re-posted automatically. Uncoded transactions go to the Suspense account so nothing is lost.</p>
        <div className="flex gap-1">
          <button className="btn btn-outline btn-sm" disabled={busy} onClick={() => run(true)}>Preview (no changes)</button>
          <button className="btn btn-primary btn-sm" disabled={busy} onClick={() => run(false)}><RefreshCw size={13} /> Post to ledger</button>
        </div>
      </div>
      {res && (
        <div className="card">
          <h3 style={{ marginTop: 0 }}>{res.dry_run ? 'Preview' : 'Result'}</h3>
          {res.ok === false ? <div className="alert alert-warning">{res.detail}</div> : (
            <table className="summary-table"><tbody>
              {Object.entries(res).filter(([k, v]) => typeof v === 'number').map(([k, v]) =>
                <tr key={k}><td>{labels[k] || k}</td><td className="text-right mono fw-600" style={{ paddingLeft: 24 }}>{v}</td></tr>)}
            </tbody></table>)}
          {res.suspense_items?.length > 0 && (<>
            <h4>Transactions in Suspense (code them in Reconciliation, then sync again)</h4>
            <div className="data-table-wrap"><table className="data-table"><thead><tr><th>Date</th><th>Description</th><th>GL account on file</th></tr></thead>
              <tbody>{res.suspense_items.map(s => <tr key={s.transaction_id}><td>{s.date}</td><td>{s.description}</td><td>{s.gl_account || '(uncoded)'}</td></tr>)}</tbody></table></div>
          </>)}
        </div>)}
    </div>
  )
}

// ── Page ─────────────────────────────────────────────────────────────────────
export default function LedgerPage() {
  const [tab, setTab] = useState('coa')
  const [taxes, setTaxes] = useState([])
  const [org, setOrg] = useState(null)
  useEffect(() => {
    api.taxCodes().then(r => setTaxes(r.data)).catch(() => {})
    api.currentOrg().then(r => setOrg(r.data)).catch(() => {})
  }, [])
  const TABS = [['coa', 'Chart of Accounts'], ['journals', 'Journals'], ['reports', 'Reports'], ['sync', 'Bank Sync']]
  return (
    <div className="fade-in" style={{ padding: 24 }}>
      <div className="section-header" style={{ marginBottom: 16 }}>
        <div className="flex items-center gap-1"><BookOpen size={22} />
          <h2 style={{ margin: 0 }}>General Ledger</h2>
          {org && <span className="badge badge-neutral" style={{ marginLeft: 8 }}>{org.name}</span>}
          {org?.lock_date && <span className="badge badge-warning" title="No postings on or before this date">Locked to {org.lock_date}</span>}
        </div>
      </div>
      <div className="tabs-bar">{TABS.map(([k, l]) => <button key={k} className={`tab-btn${tab === k ? ' active' : ''}`} onClick={() => setTab(k)}>{l}</button>)}</div>
      <div style={{ marginTop: 16 }}>
        {tab === 'coa' && <AccountsTab taxes={taxes} />}
        {tab === 'journals' && <JournalsTab taxes={taxes} />}
        {tab === 'reports' && <ReportsTab />}
        {tab === 'sync' && <SyncTab />}
      </div>
    </div>
  )
}
