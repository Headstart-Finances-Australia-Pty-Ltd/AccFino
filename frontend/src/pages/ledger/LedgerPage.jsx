import React, { useEffect, useMemo, useRef, useState } from 'react'
import { useBulkImportEnabled } from '../../hooks/useBulkImport.jsx'
import toast from 'react-hot-toast'
import { BookOpen, Plus, RotateCcw, RefreshCw, Eye, Scale, Download, Upload } from 'lucide-react'
import * as api from '../../lib/platformApi.js'
import { HealthStrip, JournalsTab, RepeatingTab, ReviewTab, isApprover } from './JournalTools.jsx'
import FxTab from './FxTab.jsx'
import AiTab from './AiTab.jsx'

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

// ── Chart of accounts (organisation ledger; also shown in Settings → Chart of Accounts) ──
export function AccountsTab({ taxes }) {
  const [rows, setRows] = useState([])
  const [cls, setCls] = useState('all')
  const [q, setQ] = useState('')
  const [showInactive, setShowInactive] = useState(false)
  const [edit, setEdit] = useState(null)
  const [types, setTypes] = useState([])

  const load = () => api.accounts(showInactive).then(r => setRows(r.data)).catch(e => toast.error(api.errMsg(e)))
  useEffect(() => { load() }, [showInactive])
  useEffect(() => { api.accountTypes().then(r => setTypes(r.data)).catch(() => {}) }, [])


  const fileRef = useRef()
  const bulkImport = useBulkImportEnabled()
  const csvCell = v => `"${String(v ?? '').replace(/"/g, '""')}"`
  const exportCSV = () => {
    const lines = ['Code,Name,Type,Tax Code,Description,Active',
      ...rows.map(a => [a.code, a.name, TYPE_LABEL[a.type] || a.type, a.default_tax_code || '', a.description || '', a.is_active ? 'yes' : 'no'].map(csvCell).join(','))]
    const a = document.createElement('a')
    a.href = URL.createObjectURL(new Blob([lines.join('\n')], { type: 'text/csv' }))
    a.download = 'ChartOfAccounts.csv'; a.click()
  }
  const parseCSV = text => text.replace(/\r/g, '').split('\n').filter(l => l.trim()).map(line => {
    const out = []; let cur = '', q = false
    for (let i = 0; i < line.length; i++) {
      const ch = line[i]
      if (ch === '"') { if (q && line[i + 1] === '"') { cur += '"'; i++ } else q = !q }
      else if (ch === ',' && !q) { out.push(cur); cur = '' } else cur += ch
    }
    out.push(cur); return out.map(v => v.trim())
  })
  // Import adds accounts that don't exist yet (matched on code or name). Existing accounts are never overwritten,
  // because they may already carry posted journals.
  const importCSV = async e => {
    const file = e.target.files[0]; e.target.value = ''
    if (!file) return
    const grid = parseCSV(await file.text())
    if (grid.length < 2) { toast.error('CSV appears empty'); return }
    const head = grid[0].map(h => h.replace(/^\*/, '').toLowerCase())
    const col = n => head.indexOf(n)
    const typeByLabel = Object.fromEntries(Object.entries(TYPE_LABEL).map(([k, v]) => [v.toLowerCase(), k]))
    Object.assign(typeByLabel, { revenue: 'revenue', 'direct costs': 'direct_costs', gst: 'current_liability', 'fixed asset': 'fixed_asset' })
    const have = new Set(rows.flatMap(a => [`c:${a.code.toLowerCase()}`, `n:${a.name.toLowerCase()}`]))
    let added = 0, skipped = 0, failed = []
    for (const r of grid.slice(1)) {
      const code = r[col('code')] || '', name = r[col('name')] || '', typeLabel = (r[col('type')] || '').toLowerCase()
      if (!name) continue
      const type = typeByLabel[typeLabel] || (types.some(t => t.type === typeLabel) ? typeLabel : null)
      if (!code || !type) { failed.push(name); continue }
      if (have.has(`c:${code.toLowerCase()}`) || have.has(`n:${name.toLowerCase()}`)) { skipped++; continue }
      try { await api.createAccount({ code, name, type, description: r[col('description')] || null }); added++ }
      catch (err) { failed.push(`${name} (${api.errMsg(err)})`) }
    }
    toast[failed.length ? 'error' : 'success'](`${added} added, ${skipped} already existed${failed.length ? `, ${failed.length} failed: ${failed.slice(0, 3).join('; ')}` : ''}`)
    load()
  }

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
        {bulkImport && <input ref={fileRef} type="file" accept=".csv" style={{ display: 'none' }} onChange={importCSV} />}
        {bulkImport && <button className="btn btn-outline btn-sm" onClick={() => fileRef.current?.click()}><Upload size={13} /> Import CSV</button>}
        <button className="btn btn-outline btn-sm" onClick={exportCSV}><Download size={13} /> Export CSV</button>
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
// ── Reports ──────────────────────────────────────────────────────────────────
function Section({ title, rows, total }) {
  if (!rows || !rows.length) return null
  return (<>
    <tr><td colSpan={2} className="fw-700" style={{ paddingTop: 14 }}>{title}</td></tr>
    {rows.map(r => <tr key={r.account_id}><td style={{ paddingLeft: 20 }}>{r.code} · {r.name}</td><td className="text-right mono">{aud(r.amount)}</td></tr>)}
    {total !== undefined && <tr><td className="fw-600" style={{ paddingLeft: 20 }}>Total {title}</td><td className="text-right mono fw-600">{aud(total)}</td></tr>}
  </>)
}

export function ReportsTab() {
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
  const [tab, setTab] = useState('journals')
  const [org, setOrg] = useState(null)
  const [health, setHealth] = useState(null)
  const [settings, setSettings] = useState({ require_journal_approval: false })
  const [preset, setPreset] = useState(null)
  const loadHealth = () => { api.ledgerHealth().then(r => setHealth(r.data)).catch(() => {}); api.journalSettings().then(r => setSettings(r.data)).catch(() => {}) }
  useEffect(() => { api.currentOrg().then(r => setOrg(r.data)).catch(() => {}); loadHealth() }, [])
  const canApprove = isApprover(org?.role)
  const toggleApproval = async v => { try { const { data } = await api.saveJournalSettings({ require_journal_approval: v }); setSettings(data); toast.success(v ? 'Manual journals now need approval' : 'Approval no longer required') } catch (e) { toast.error(api.errMsg(e)) } }
  const saveSettings = async patch => { const { data } = await api.saveJournalSettings(patch); setSettings(data); return data }
  const toggleLlm = async v => { try { const { data } = await api.saveJournalSettings({ llm_suggestions: v }); setSettings(data); toast.success(v ? 'AI suggestions turned on' : 'AI suggestions turned off') } catch (e) { toast.error(api.errMsg(e)) } }
  // Chart of Accounts lives in Settings; Trial Balance / P&L / Balance Sheet live in Reports. Journals and their workflow stay here.
  const pending = health ? health.ai_suggestions + health.awaiting_approval : 0
  const TABS = [['journals', 'Journals'], ['review', pending ? `Review (${pending})` : 'Review'], ['repeating', 'Repeating'], ['fx', 'Foreign currency'], ['ai', 'AI assistant'], ['sync', 'Bank Sync']]
  const go = (t, extra) => { setTab(t); if (extra) setPreset({ ...extra, _k: Math.random() }) }
  return (
    <div className="fade-in" style={{ padding: 24 }}>
      <div className="section-header" style={{ marginBottom: 16 }}>
        <div className="flex items-center gap-1"><BookOpen size={22} />
          <h2 style={{ margin: 0 }}>General Ledger</h2>
          {org && <span className="badge badge-neutral" style={{ marginLeft: 8 }}>{org.name}</span>}
          {org?.lock_date && <span className="badge badge-warning" title="No postings on or before this date">Locked to {org.lock_date}</span>}
        </div>
      </div>
      <HealthStrip health={health} onGo={go} />
      <div className="tabs-bar">{TABS.map(([k, l]) => <button key={k} className={`tab-btn${tab === k ? ' active' : ''}`} onClick={() => setTab(k)}>{l}</button>)}</div>
      <div style={{ marginTop: 16 }}>
        {tab === 'journals' && <JournalsTab canApprove={canApprove} requireApproval={settings.require_journal_approval} onChanged={loadHealth} preset={preset} />}
        {tab === 'review' && <ReviewTab canApprove={canApprove} requireApproval={settings.require_journal_approval} onChanged={loadHealth} onSettings={toggleApproval} llmEnabled={settings.llm_suggestions} onLlm={toggleLlm} assistEnabled={settings.llm_assist} />}
        {tab === 'fx' && <FxTab canApprove={canApprove} settings={settings} onSettings={saveSettings} onChanged={loadHealth} />}
        {tab === 'ai' && <AiTab canApprove={canApprove} settings={settings} onSettings={saveSettings} onOpenEditor={open => go('journals', { open })} />}
        {tab === 'repeating' && <RepeatingTab canApprove={canApprove} onChanged={loadHealth} />}
        {tab === 'sync' && <SyncTab />}
      </div>
    </div>
  )
}
