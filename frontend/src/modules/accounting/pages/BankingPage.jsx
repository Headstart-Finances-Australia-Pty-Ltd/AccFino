import React, { useEffect, useState } from 'react'
import toast from 'react-hot-toast'
import {
  RefreshCw, Plus, Upload, Check, X, ArrowRightLeft, Wand2, Landmark, Settings2,
} from 'lucide-react'
import * as api__0 from '../lib/booksApi.js'
import * as api__1 from '../../../core/lib/platformHttp.js'
import { useBulkImportEnabled } from '../hooks/useBulkImport.jsx'
import { Modal, Field, StatusBadge, EmptyState, fmtAUD, fmtMoney, fmtDate, todayISO } from '../../../core/components/ui/Common.jsx'

export default function BankingPage() {
  const [accounts, setAccounts] = useState([])
  const [activeId, setActiveId] = useState(null)
  const [tab, setTab] = useState('lines')       // 'lines' | 'rules' | 'reconcile'
  const [loading, setLoading] = useState(false)
  const [creatingAccount, setCreatingAccount] = useState(false)

  const load = () => {
    setLoading(true)
    api__0.bankAccounts().then(r => {
      const items = r.data?.items || r.data || []
      setAccounts(items)
      if (!activeId && items.length) setActiveId(items[0].id)
    }).catch(e => toast.error(api__1.errMsg(e))).finally(() => setLoading(false))
  }
  useEffect(() => { load() }, [])

  const active = accounts.find(a => a.id === activeId)

  return (
    <div className="fade-in">
      <div style={{ marginBottom: 18, display: 'flex', alignItems: 'flex-start', justifyContent: 'space-between', gap: 12, flexWrap: 'wrap' }}>
        <div>
          <div className="flex items-center gap-1"><ArrowRightLeft size={22} /><h2 style={{ margin: 0 }}>Banking & Reconciliation</h2></div>
          <p className="text-sm text-muted" style={{ margin: '4px 0 0' }}>Import a statement, match it to your invoices and bills, code the rest.</p>
        </div>
        <div className="flex items-center gap-1">
          <button className="btn btn-outline btn-sm" onClick={load} disabled={loading}><RefreshCw size={13} className={loading ? 'spin' : ''} /></button>
          <button className="btn btn-primary btn-sm" onClick={() => setCreatingAccount(true)}><Plus size={13} /> New bank account</button>
        </div>
      </div>

      {accounts.length === 0 ? (
        <EmptyState icon="🏦" title="No bank accounts yet" hint="Create one to start importing a statement." />
      ) : (
        <>
          <div className="stats-grid" style={{ marginBottom: 16 }}>
            {accounts.map(a => (
              <div key={a.id} className={`stat-card${a.id === activeId ? ' card-accent-top' : ''}`}
                style={{ cursor: 'pointer', border: a.id === activeId ? '1px solid var(--brand)' : undefined }}
                onClick={() => setActiveId(a.id)}>
                <div className="stat-label">{a.code} {a.name}{a.foreign && <span className="badge badge-info" style={{ marginLeft: 6 }}>{a.currency}</span>}</div>
                <div className="stat-value">{fmtMoney(a.ledger_balance, a.currency)}</div>
                {a.foreign && <div className="stat-sub" data-testid="base-value">≈ {fmtAUD(a.base_value)} at cost</div>}
                <div className="stat-sub">{a.unreconciled} unreconciled{a.last_statement_date ? ` · last statement ${fmtDate(a.last_statement_date)}` : ''}</div>
              </div>
            ))}
          </div>

          {active && (
            <>
              <div className="tabs-bar" style={{ marginBottom: 0 }}>
                <button className={`tab-btn${tab === 'lines' ? ' active' : ''}`} onClick={() => setTab('lines')}>📥 Statement lines</button>
                <button className={`tab-btn${tab === 'reconcile' ? ' active' : ''}`} onClick={() => setTab('reconcile')}>✅ Reconciliation</button>
                <button className={`tab-btn${tab === 'rules' ? ' active' : ''}`} onClick={() => setTab('rules')}><Settings2 size={13} style={{ verticalAlign: -2 }} /> Coding rules</button>
              </div>
              <div style={{ background: 'var(--surface)', border: '1px solid var(--border)', borderTop: 'none', borderRadius: '0 0 var(--r-lg) var(--r-lg)', minHeight: 320, boxShadow: 'var(--sh-sm)' }}>
                {tab === 'lines' && <LinesTab account={active} />}
                {tab === 'reconcile' && <ReconcileTab account={active} />}
                {tab === 'rules' && <RulesTab />}
              </div>
            </>
          )}
        </>
      )}

      {creatingAccount && <NewAccountModal onClose={() => setCreatingAccount(false)} onSaved={() => { setCreatingAccount(false); load() }} />}
    </div>
  )
}

function NewAccountModal({ onClose, onSaved }) {
  const [code, setCode] = useState(''); const [name, setName] = useState('')
  const [bankName, setBankName] = useState(''); const [ref, setRef] = useState(''); const [saving, setSaving] = useState(false)
  const save = async () => {
    if (!code.trim() || !name.trim()) { toast.error('Code and name are required'); return }
    setSaving(true)
    try { await api__0.createBankAccount({ code, name, bank_name: bankName || undefined, bank_account_ref: ref || undefined, type: 'bank' }); toast.success('Account created'); onSaved() }
    catch (e) { toast.error(api__1.errMsg(e)) } finally { setSaving(false) }
  }
  return (
    <Modal title="New bank account" onClose={onClose} width={420}>
      <Field label="Code *" hint="e.g. 090"><input className="input" value={code} onChange={e => setCode(e.target.value)} /></Field>
      <Field label="Name *" hint="e.g. Everyday Account"><input className="input" value={name} onChange={e => setName(e.target.value)} /></Field>
      <Field label="Bank name"><input className="input" value={bankName} onChange={e => setBankName(e.target.value)} /></Field>
      <Field label="Account number"><input className="input" value={ref} onChange={e => setRef(e.target.value)} /></Field>
      <div className="flex justify-between" style={{ marginTop: 12 }}>
        <button className="btn btn-ghost btn-sm" onClick={onClose}>Cancel</button>
        <button className="btn btn-primary btn-sm" onClick={save} disabled={saving}>{saving ? 'Saving…' : 'Create'}</button>
      </div>
    </Modal>
  )
}

// ══════════════════════════════════════════════════════════════════════ Statement lines ═══════
function LinesTab({ account }) {
  const [status, setStatus] = useState('unreconciled')
  const [rows, setRows] = useState([])
  const [loading, setLoading] = useState(false)
  const [importing, setImporting] = useState(false)
  const bulkImport = useBulkImportEnabled()
  const [autoBusy, setAutoBusy] = useState(false)
  const [actionLine, setActionLine] = useState(null)

  const load = () => {
    setLoading(true)
    api__0.listBankLines({ account_id: account.id, status: status || undefined, suggest: status === 'unreconciled', limit: 300 })
      .then(r => setRows(r.data?.items || [])).catch(e => toast.error(api__1.errMsg(e))).finally(() => setLoading(false))
  }
  useEffect(() => { load() }, [account.id, status])

  const onCSV = async e => {
    const file = e.target.files?.[0]; if (!file) return
    setImporting(true)
    try {
      const r = await api__0.importBankCSV(account.code, file)
      toast.success(`${r.data.created} imported, ${r.data.duplicates} already there${r.data.adopted_from_ledger ? `, ${r.data.adopted_from_ledger} matched to existing ledger entries` : ''}`)
      if (r.data.warnings?.length) console.warn('CSV warnings:', r.data.warnings)
      load()
    } catch (err) { toast.error(api__1.errMsg(err)) } finally { setImporting(false); e.target.value = '' }
  }

  const runAuto = async () => {
    setAutoBusy(true)
    try {
      const r = await api__0.autoReconcile({ bank_account: account.code })
      toast.success(`${r.data.matched.length} reconciled automatically, ${r.data.left_for_review} left for review`)
      load()
    } catch (e) { toast.error(api__1.errMsg(e)) } finally { setAutoBusy(false) }
  }

  return (
    <div style={{ padding: 16 }}>
      <div className="flex items-center gap-4" style={{ flexWrap: 'wrap', marginBottom: 12 }}>
        <select className="select-compact" value={status} onChange={e => setStatus(e.target.value)}>
          <option value="unreconciled">Unreconciled</option><option value="reconciled">Reconciled</option><option value="excluded">Excluded</option>
        </select>
        <div className="flex-1" />
        {bulkImport && <label className="btn btn-outline btn-sm" style={{ cursor: 'pointer' }}>
          <Upload size={13} /> {importing ? 'Importing…' : 'Import statement CSV'}
          <input type="file" accept=".csv" hidden onChange={onCSV} disabled={importing} />
        </label>}
        <button className="btn btn-outline btn-sm" onClick={load} disabled={loading}><RefreshCw size={13} className={loading ? 'spin' : ''} /></button>
        {status === 'unreconciled' && <button className="btn btn-primary btn-sm" onClick={runAuto} disabled={autoBusy}><Wand2 size={13} /> {autoBusy ? 'Working…' : 'Auto-reconcile certain matches'}</button>}
      </div>

      {rows.length === 0 ? <EmptyState icon="📭" title="Nothing here" hint="Import a CSV statement to get started." /> : (
        <table className="data-table">
          <thead><tr><th>Date</th><th>Description</th><th style={{ textAlign: 'right' }}>Amount</th><th>Suggestion</th>{status === 'unreconciled' && <th style={{ width: 190 }}>Action</th>}</tr></thead>
          <tbody>
            {rows.map(l => (
              <tr key={l.id}>
                <td className="text-sm">{fmtDate(l.date)}</td>
                <td className="text-sm">{l.description}</td>
                <td style={{ textAlign: 'right' }} className="mono">{fmtMoney(l.amount, account.currency)}</td>
                <td className="text-sm">
                  {l.suggestion ? <span className="badge badge-info">{l.suggestion.reference || l.suggestion.contact} · {(Number(l.suggestion.confidence) * 100).toFixed(0)}%</span>
                    : l.coding ? <span className="badge badge-neutral">{l.coding.account_code} ({l.coding.source})</span> : <span className="text-muted">—</span>}
                </td>
                {status === 'unreconciled' && (
                  <td>
                    <div className="flex items-center gap-1">
                      {l.suggestion && <button className="btn btn-primary btn-xs" onClick={() => actOn(l, 'accept')}>Accept</button>}
                      <button className="btn btn-outline btn-xs" onClick={() => setActionLine(l)}>Code…</button>
                      <button className="btn btn-ghost btn-xs" onClick={() => actOn(l, 'exclude')}>Exclude</button>
                    </div>
                  </td>
                )}
                {status !== 'unreconciled' && <td />}
              </tr>
            ))}
          </tbody>
        </table>
      )}

      {actionLine && <LineActionModal line={actionLine} account={account} onClose={() => setActionLine(null)} onDone={() => { setActionLine(null); load() }} />}
    </div>
  )

  async function actOn(line, kind) {
    try {
      if (kind === 'exclude') { await api__0.excludeLine(line.id); toast.success('Excluded') }
      else if (kind === 'accept') {
        const s = line.suggestion
        await api__0.matchLine(line.id, s.kind === 'payment' ? { kind: 'payment', payment_id: s.payment_id } : { kind: s.kind, doc_id: s.doc_id })
        toast.success('Matched')
      }
      load()
    } catch (e) { toast.error(api__1.errMsg(e)) }
  }
}

function LineActionModal({ line, account, onClose, onDone }) {
  const [mode, setMode] = useState('code')   // 'code' | 'transfer'
  const [accounts, setAccounts] = useState([])
  const [taxes, setTaxes] = useState([])
  const [banks, setBanks] = useState([])
  const [accCode, setAccCode] = useState('')
  const [taxCode, setTaxCode] = useState('')
  const [contact, setContact] = useState('')
  const [toAccount, setToAccount] = useState('')
  const [rate, setRate] = useState('')
  const [otherAmount, setOtherAmount] = useState('')
  const [saving, setSaving] = useState(false)
  const moneyIn = Number(line.amount) > 0
  const target = banks.find(b => b.code === toAccount)
  const needsOther = mode === 'transfer' && target && (target.currency || 'AUD') !== (account.currency || 'AUD')

  useEffect(() => {
    api__0.ledgerAccounts().then(r => setAccounts(r.data || [])).catch(() => {})
    api__0.taxCodes().then(r => setTaxes(r.data || [])).catch(() => {})
    api__0.bankAccounts().then(r => setBanks((r.data?.items || r.data || []).filter(b => b.id !== account.id))).catch(() => {})
    if (line.coding) { setAccCode(line.coding.account_code || ''); setTaxCode(line.coding.tax_code || ''); setContact(line.coding.contact_name || '') }
  }, [])

  const save = async () => {
    setSaving(true)
    try {
      let res
      if (mode === 'transfer') { ({ data: res } = await api__0.transferLine(line.id, { to_account: toAccount, ...(needsOther && otherAmount ? { other_amount: otherAmount } : {}), ...(rate ? { rate } : {}) })); toast.success('Transferred') }
      else { ({ data: res } = await api__0.codeLine(line.id, { account: accCode || undefined, tax_code: taxCode || undefined, contact: contact || undefined, ...(rate ? { rate } : {}) })); toast.success('Coded') }
      if (res?.realised_fx && Number(res.realised_fx) !== 0) toast(`Realised foreign exchange ${Number(res.realised_fx) > 0 ? 'gain' : 'loss'}: ${fmtAUD(Math.abs(Number(res.realised_fx)))}`)
      onDone()
    } catch (e) { toast.error(api__1.errMsg(e)) } finally { setSaving(false) }
  }

  return (
    <Modal title={`Code: ${line.description}`} onClose={onClose} width={460}>
      <p className="text-sm text-muted" style={{ marginTop: 0 }}>{fmtDate(line.date)} · <span className="mono">{fmtMoney(line.amount, account.currency)}</span></p>
      {account.foreign && <div className="alert alert-info" style={{ fontSize: '.8rem' }} data-testid="fx-line-note">This account is held in {account.currency}. The line is booked at your stored {account.currency} rate for its date (or the rate you enter); money going out leaves at the account’s average cost and any difference is a realised gain or loss.</div>}
      <div className="flex gap-1" style={{ marginBottom: 12 }}>
        <button className={`btn btn-sm ${mode === 'code' ? 'btn-primary' : 'btn-outline'}`} onClick={() => setMode('code')}>Code to an account</button>
        <button className={`btn btn-sm ${mode === 'transfer' ? 'btn-primary' : 'btn-outline'}`} onClick={() => setMode('transfer')}>Transfer between accounts</button>
      </div>
      {mode === 'code' ? (
        <>
          <Field label="Account">
            <select className="select-compact" style={{ width: '100%' }} value={accCode} onChange={e => setAccCode(e.target.value)}>
              <option value="">Choose…</option>
              {accounts.filter(a => !['bank', 'credit_card'].includes(a.type)).map(a => <option key={a.id} value={a.code}>{a.code} {a.name}</option>)}
            </select>
          </Field>
          <Field label="Tax code">
            <select className="select-compact" style={{ width: '100%' }} value={taxCode} onChange={e => setTaxCode(e.target.value)}>
              <option value="">None</option>
              {taxes.filter(t => t.applies_to === (moneyIn ? 'sales' : 'purchases') || t.applies_to === 'both').map(t => <option key={t.id} value={t.code}>{t.code}</option>)}
            </select>
          </Field>
          <Field label="Contact (optional)"><input className="input" value={contact} onChange={e => setContact(e.target.value)} /></Field>
          {account.foreign && <Field label={`Exchange rate (AUD per 1 ${account.currency}) — optional`}><input aria-label="Exchange rate" className="input" inputMode="decimal" value={rate} onChange={e => setRate(e.target.value)} placeholder="blank = your stored rate" /></Field>}
        </>
      ) : (
        <Field label="Transfer to">
          <select className="select-compact" style={{ width: '100%' }} value={toAccount} onChange={e => setToAccount(e.target.value)}>
            <option value="">Choose…</option>
            {banks.map(b => <option key={b.id} value={b.code}>{b.code} {b.name}{b.foreign ? ` (${b.currency})` : ''}</option>)}
          </select>
          {needsOther && <div style={{ marginTop: 8 }}><label className="text-sm fw-600" htmlFor="oa">Amount {moneyIn ? 'sent from' : 'received in'} {target.code} ({target.currency})</label>
            <input id="oa" className="input" inputMode="decimal" value={otherAmount} onChange={e => setOtherAmount(e.target.value)} placeholder="the real amount, so the exchange rate is exact" />
            <div className="text-xs text-muted">Or code the other side’s statement line first, then transfer with its pair.</div></div>}
        </Field>
      )}
      <div className="flex justify-between" style={{ marginTop: 12 }}>
        <button className="btn btn-ghost btn-sm" onClick={onClose}>Cancel</button>
        <button className="btn btn-primary btn-sm" onClick={save} disabled={saving || (mode === 'transfer' && (!toAccount || (needsOther && !otherAmount)))}>{saving ? 'Saving…' : 'Save'}</button>
      </div>
    </Modal>
  )
}

// ══════════════════════════════════════════════════════════════════════ Reconciliation report ═
function ReconcileTab({ account }) {
  const [asAt, setAsAt] = useState(todayISO())
  const [statementBalance, setStatementBalance] = useState('')
  const [report, setReport] = useState(null)
  const [loading, setLoading] = useState(false)

  const run = () => {
    setLoading(true)
    api__0.reconciliationReport(account.id, { as_at: asAt, statement_balance: statementBalance || undefined })
      .then(r => setReport(r.data)).catch(e => toast.error(api__1.errMsg(e))).finally(() => setLoading(false))
  }
  useEffect(() => { run() }, [account.id])

  return (
    <div style={{ padding: 16 }}>
      <div className="flex items-center gap-4" style={{ flexWrap: 'wrap', marginBottom: 12 }}>
        <Field label="As at"><input type="date" className="input input-sm" value={asAt} onChange={e => setAsAt(e.target.value)} /></Field>
        <Field label="Statement balance (optional)"><input type="number" step="0.01" className="input input-sm" value={statementBalance} onChange={e => setStatementBalance(e.target.value)} /></Field>
        <button className="btn btn-primary btn-sm" style={{ alignSelf: 'flex-end' }} onClick={run} disabled={loading}>Run</button>
      </div>

      {report && (
        <>
          <div className="stats-grid" style={{ marginBottom: 16 }}>
            <div className="stat-card"><div className="stat-label">Ledger balance</div><div className="stat-value">{fmtMoney(report.ledger_balance, report.account?.currency)}</div></div>
            <div className="stat-card"><div className="stat-label">Statement balance</div><div className="stat-value">{report.statement_balance ? fmtMoney(report.statement_balance, report.account?.currency) : '—'}</div></div>
            <div className="stat-card"><div className="stat-label">Status</div>
              <div className="stat-value">{report.reconciled === true ? <span className="badge badge-success">Reconciled</span> : report.reconciled === false ? <span className="badge badge-warning">Not yet</span> : '—'}</div>
              {report.difference && <div className="stat-sub">Difference {fmtMoney(report.difference, report.account?.currency)}</div>}
            </div>
          </div>

          <div className="grid-2" style={{ gap: 16 }}>
            <div>
              <div className="section-header">Unreconciled statement lines ({report.unreconciled_statement_lines.count})</div>
              {report.unreconciled_statement_lines.lines.map(l => (
                <div key={l.id} className="text-sm" style={{ padding: '4px 0', borderBottom: '1px solid var(--border)' }}>
                  {fmtDate(l.date)} — {l.description} — <span className="mono">{fmtMoney(l.amount, report.account?.currency)}</span>
                </div>
              ))}
            </div>
            <div>
              <div className="section-header">Unmatched ledger items ({report.unmatched_ledger_items.count})</div>
              {report.unmatched_ledger_items.items.map(it => (
                <div key={it.journal_id} className="text-sm" style={{ padding: '4px 0', borderBottom: '1px solid var(--border)' }}>
                  {fmtDate(it.date)} — {it.description} — <span className="mono">{fmtMoney(it.amount, report.account?.currency)}</span>
                </div>
              ))}
            </div>
          </div>
        </>
      )}
    </div>
  )
}

// ══════════════════════════════════════════════════════════════════════ Coding rules ══════════
function RulesTab() {
  const [rows, setRows] = useState([])
  const [edit, setEdit] = useState(null)
  const [accounts, setAccounts] = useState([])
  const [taxes, setTaxes] = useState([])

  const load = () => api__0.listRules().then(r => setRows(r.data?.items || [])).catch(e => toast.error(api__1.errMsg(e)))
  useEffect(() => {
    load()
    api__0.ledgerAccounts().then(r => setAccounts(r.data || [])).catch(() => {})
    api__0.taxCodes().then(r => setTaxes(r.data || [])).catch(() => {})
  }, [])

  const save = async () => {
    try {
      const body = { name: edit.name, pattern: edit.pattern, account: edit.account, priority: Number(edit.priority || 100),
        direction: edit.direction || 'any', match_type: edit.match_type || 'contains', tax_code: edit.tax_code || undefined }
      if (edit.id) await api__0.updateRule(edit.id, body); else await api__0.createRule(body)
      toast.success('Rule saved'); setEdit(null); load()
    } catch (e) { toast.error(api__1.errMsg(e)) }
  }
  const del = async id => { if (!confirm('Delete this rule?')) return; try { await api__0.deleteRule(id); load() } catch (e) { toast.error(api__1.errMsg(e)) } }

  return (
    <div style={{ padding: 16 }}>
      <div className="flex justify-between" style={{ marginBottom: 12 }}>
        <p className="text-sm text-muted" style={{ margin: 0 }}>Coding rules belong to this organisation only — nothing here is ever shared with another organisation.</p>
        <button className="btn btn-primary btn-sm" onClick={() => setEdit({ name: '', pattern: '', account: '', priority: 100, direction: 'any', match_type: 'contains' })}><Plus size={13} /> New rule</button>
      </div>
      {rows.length === 0 ? <EmptyState icon="⚙️" title="No coding rules yet" /> : (
        <table className="data-table">
          <thead><tr><th>Name</th><th>Pattern</th><th>Direction</th><th>Account</th><th>Priority</th><th style={{ width: 90 }} /></tr></thead>
          <tbody>{rows.map(r => (
            <tr key={r.id}><td>{r.name}</td><td className="mono text-sm">{r.pattern}</td><td className="text-sm">{r.direction}</td><td className="text-sm">{r.account}</td><td>{r.priority}</td>
              <td><div className="flex gap-1"><button className="btn btn-outline btn-xs" onClick={() => setEdit(r)}>Edit</button><button className="btn btn-danger btn-xs" onClick={() => del(r.id)}>Delete</button></div></td></tr>
          ))}</tbody>
        </table>
      )}
      {edit && (
        <Modal title={edit.id ? 'Edit rule' : 'New rule'} onClose={() => setEdit(null)} width={440}>
          <Field label="Name"><input className="input" value={edit.name} onChange={e => setEdit({ ...edit, name: e.target.value })} /></Field>
          <Field label="Pattern (text to match in the description)"><input className="input" value={edit.pattern} onChange={e => setEdit({ ...edit, pattern: e.target.value })} /></Field>
          <Field label="Direction">
            <select className="select-compact" style={{ width: '100%' }} value={edit.direction} onChange={e => setEdit({ ...edit, direction: e.target.value })}>
              <option value="any">Either</option><option value="in">Money in</option><option value="out">Money out</option>
            </select>
          </Field>
          <Field label="Account">
            <select className="select-compact" style={{ width: '100%' }} value={edit.account} onChange={e => setEdit({ ...edit, account: e.target.value })}>
              <option value="">Choose…</option>
              {accounts.map(a => <option key={a.id} value={a.code}>{a.code} {a.name}</option>)}
            </select>
          </Field>
          <Field label="Tax code (optional)">
            <select className="select-compact" style={{ width: '100%' }} value={edit.tax_code || ''} onChange={e => setEdit({ ...edit, tax_code: e.target.value })}>
              <option value="">None</option>
              {taxes.map(t => <option key={t.id} value={t.code}>{t.code}</option>)}
            </select>
          </Field>
          <Field label="Priority" hint="Lower runs first"><input type="number" className="input" value={edit.priority} onChange={e => setEdit({ ...edit, priority: e.target.value })} /></Field>
          <div className="flex justify-between" style={{ marginTop: 12 }}>
            <button className="btn btn-ghost btn-sm" onClick={() => setEdit(null)}>Cancel</button>
            <button className="btn btn-primary btn-sm" onClick={save} disabled={!edit.name || !edit.pattern || !edit.account}>Save</button>
          </div>
        </Modal>
      )}
    </div>
  )
}
