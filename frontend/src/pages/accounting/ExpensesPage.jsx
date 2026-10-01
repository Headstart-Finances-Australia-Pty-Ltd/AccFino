import React, { useEffect, useState } from 'react'
import toast from 'react-hot-toast'
import { Plus, RefreshCw, Trash2, Check, X, DollarSign, Paperclip, Receipt } from 'lucide-react'
import * as api from '../../lib/booksApi.js'
import { Modal, Field, StatusBadge, EmptyState, fmtAUD, fmtDate, todayISO } from '../../components/books/Common.jsx'
import { CsvImportButton } from '../../components/books/CsvImportModal.jsx'

const ATO_THRESHOLD = 82.50

export default function ExpensesPage() {
  const [rows, setRows] = useState([])
  const [status, setStatus] = useState('')
  const [mine, setMine] = useState(false)
  const [loading, setLoading] = useState(false)
  const [creating, setCreating] = useState(false)
  const [openId, setOpenId] = useState(null)
  const [accounts, setAccounts] = useState([])
  const [taxes, setTaxes] = useState([])
  const [banks, setBanks] = useState([])
  const [summary, setSummary] = useState(null)

  const load = () => {
    setLoading(true)
    api.listClaims({ status: status || undefined, mine: mine || undefined, limit: 200 })
      .then(r => setRows(r.data?.items || [])).catch(e => toast.error(api.errMsg(e))).finally(() => setLoading(false))
  }
  useEffect(() => { load() }, [status, mine])
  useEffect(() => {
    api.ledgerAccounts().then(r => setAccounts(r.data || [])).catch(() => {})
    api.taxCodes().then(r => setTaxes(r.data || [])).catch(() => {})
    api.bankAccounts().then(r => setBanks(r.data?.items || r.data || [])).catch(() => {})
    api.claimsSummary().then(r => setSummary(r.data?.by_status || {})).catch(() => {})
  }, [])

  return (
    <div className="fade-in">
      <div style={{ marginBottom: 18, display: 'flex', alignItems: 'flex-start', justifyContent: 'space-between', gap: 12, flexWrap: 'wrap' }}>
        <div>
          <div className="flex items-center gap-1"><Receipt size={22} /><h2 style={{ margin: 0 }}>Expenses</h2></div>
          <p className="text-sm text-muted" style={{ margin: '4px 0 0' }}>Receipts, mileage, and reimbursements — with sign-off before anything is paid.</p>
        </div>
        <div className="flex items-center gap-1">
          <CsvImportButton entity="expense_claims" onDone={() => { load(); api.claimsSummary().then(r => setSummary(r.data?.by_status || {})).catch(() => {}) }} />
          <button className="btn btn-primary btn-sm" onClick={() => setCreating(true)}><Plus size={13} /> New claim</button>
        </div>
      </div>

      {summary && (
        <div className="stats-grid" style={{ marginBottom: 16 }}>
          {['draft', 'submitted', 'approved', 'paid'].map(s => (
            <div key={s} className="stat-card">
              <div className="stat-label">{s[0].toUpperCase() + s.slice(1)}</div>
              <div className="stat-value">{fmtAUD(summary[s]?.total || 0)}</div>
              <div className="stat-sub">{summary[s]?.count || 0} claim{(summary[s]?.count || 0) === 1 ? '' : 's'}</div>
            </div>
          ))}
        </div>
      )}

      <div className="flex items-center gap-4" style={{ flexWrap: 'wrap', marginBottom: 12 }}>
        <select className="select-compact" value={status} onChange={e => setStatus(e.target.value)}>
          <option value="">All statuses</option>
          {['draft', 'submitted', 'approved', 'rejected', 'paid'].map(s => <option key={s} value={s}>{s}</option>)}
        </select>
        <label className="text-sm"><input type="checkbox" checked={mine} onChange={e => setMine(e.target.checked)} /> My claims only</label>
        <div className="flex-1" />
        <button className="btn btn-outline btn-sm" onClick={load} disabled={loading}><RefreshCw size={13} className={loading ? 'spin' : ''} /></button>
      </div>

      {rows.length === 0 ? <EmptyState icon="🧾" title="No claims yet" hint='Click "New claim" to submit a receipt or mileage.' /> : (
        <table className="data-table">
          <thead><tr><th>Number</th><th>Title</th><th>Claimant</th><th style={{ textAlign: 'right' }}>Total</th><th>Status</th></tr></thead>
          <tbody>
            {rows.map(c => (
              <tr key={c.id} style={{ cursor: 'pointer' }} onClick={() => setOpenId(c.id)}>
                <td className="mono">{c.number}</td><td>{c.title}</td><td className="text-sm">{c.claimant}</td>
                <td style={{ textAlign: 'right' }} className="mono">{fmtAUD(c.total)}</td><td><StatusBadge status={c.status} /></td>
              </tr>
            ))}
          </tbody>
        </table>
      )}

      {creating && <ClaimFormModal accounts={accounts} taxes={taxes} onClose={() => setCreating(false)} onSaved={id => { setCreating(false); load(); setOpenId(id) }} />}
      {openId && <ClaimDetailModal id={openId} banks={banks} onClose={() => setOpenId(null)} onChanged={load} />}
    </div>
  )
}

function emptyItem() { return { date: todayISO(), merchant: '', description: '', account: '', amount: '', tax_code: '', kind: 'receipt', km: '', rate_per_km: '' } }

function ClaimFormModal({ accounts, taxes, onClose, onSaved }) {
  const [title, setTitle] = useState('')
  const [items, setItems] = useState([emptyItem()])
  const [saving, setSaving] = useState(false)

  const setItem = (i, patch) => setItems(xs => xs.map((x, ix) => ix === i ? { ...x, ...patch } : x))
  const addItem = () => setItems(xs => [...xs, emptyItem()])
  const removeItem = i => setItems(xs => xs.length > 1 ? xs.filter((_, ix) => ix !== i) : xs)

  const save = async () => {
    if (!items.some(i => i.description.trim())) { toast.error('Add at least one item'); return }
    setSaving(true)
    try {
      const body = {
        title: title || undefined,
        items: items.filter(i => i.description.trim()).map(i => i.kind === 'mileage'
          ? { date: i.date, description: i.description, account: i.account, kind: 'mileage', km: i.km, rate_per_km: i.rate_per_km || undefined }
          : { date: i.date, merchant: i.merchant || undefined, description: i.description, account: i.account, amount: i.amount, tax_code: i.tax_code || undefined }),
      }
      const r = await api.createClaim(body)
      toast.success('Claim created'); onSaved(r.data.id)
    } catch (e) { toast.error(api.errMsg(e)) } finally { setSaving(false) }
  }

  return (
    <Modal title="New expense claim" onClose={onClose} width={780}>
      <Field label="Title"><input className="input" placeholder="e.g. Client visit costs" value={title} onChange={e => setTitle(e.target.value)} /></Field>
      <div style={{ marginTop: 12, marginBottom: 6, fontWeight: 600, fontSize: '.85rem' }}>Items</div>
      {items.map((it, i) => (
        <div key={i} style={{ border: '1px solid var(--border)', borderRadius: 'var(--r-sm)', padding: 10, marginBottom: 8 }}>
          <div className="flex items-center gap-1" style={{ marginBottom: 6 }}>
            <select className="select-compact" value={it.kind} onChange={e => setItem(i, { kind: e.target.value })}>
              <option value="receipt">Receipt</option><option value="mileage">Mileage</option>
            </select>
            <input type="date" className="input input-sm" style={{ width: 140 }} value={it.date} onChange={e => setItem(i, { date: e.target.value })} />
            <input className="input input-sm" placeholder="Description" style={{ flex: 1 }} value={it.description} onChange={e => setItem(i, { description: e.target.value })} />
            <button className="btn btn-ghost btn-xs" onClick={() => removeItem(i)}><Trash2 size={12} /></button>
          </div>
          <div className="flex items-center gap-1" style={{ flexWrap: 'wrap' }}>
            {it.kind === 'receipt' && <input className="input input-sm" placeholder="Merchant" style={{ width: 140 }} value={it.merchant} onChange={e => setItem(i, { merchant: e.target.value })} />}
            <select className="select-compact" style={{ width: 160 }} value={it.account} onChange={e => setItem(i, { account: e.target.value })}>
              <option value="">Account…</option>
              {accounts.filter(a => ['expense', 'other_expense'].includes(a.type)).map(a => <option key={a.id} value={a.code}>{a.code} {a.name}</option>)}
            </select>
            {it.kind === 'receipt' ? (
              <>
                <input type="number" step="0.01" className="input input-sm" placeholder="Amount (incl. GST)" style={{ width: 150 }} value={it.amount} onChange={e => setItem(i, { amount: e.target.value })} />
                <select className="select-compact" style={{ width: 150 }} value={it.tax_code} onChange={e => setItem(i, { tax_code: e.target.value })}>
                  <option value="">No GST</option>
                  {taxes.filter(t => t.applies_to === 'purchases' || t.applies_to === 'both').map(t => <option key={t.id} value={t.code}>{t.code}</option>)}
                </select>
              </>
            ) : (
              <>
                <input type="number" className="input input-sm" placeholder="km" style={{ width: 90 }} value={it.km} onChange={e => setItem(i, { km: e.target.value })} />
                <input type="number" step="0.01" className="input input-sm" placeholder="$/km (optional)" style={{ width: 130 }} value={it.rate_per_km} onChange={e => setItem(i, { rate_per_km: e.target.value })} />
              </>
            )}
          </div>
        </div>
      ))}
      <button className="btn btn-outline btn-xs" onClick={addItem}><Plus size={11} /> Add item</button>
      <div className="alert alert-warning" style={{ marginTop: 12, fontSize: '.78rem' }}>
        The ATO requires a receipt attached to any item over ${ATO_THRESHOLD.toFixed(2)} that carries GST, before it can be submitted. You can attach receipts after saving.
      </div>
      <div className="flex justify-between" style={{ marginTop: 12 }}>
        <button className="btn btn-ghost btn-sm" onClick={onClose}>Cancel</button>
        <button className="btn btn-primary btn-sm" onClick={save} disabled={saving}>{saving ? 'Saving…' : 'Save'}</button>
      </div>
    </Modal>
  )
}

function ClaimDetailModal({ id, banks, onClose, onChanged }) {
  const [claim, setClaim] = useState(null)
  const [busy, setBusy] = useState(false)
  const [rejecting, setRejecting] = useState(false)
  const [reimbursing, setReimbursing] = useState(false)

  const load = () => api.getClaim(id).then(r => setClaim(r.data)).catch(e => toast.error(api.errMsg(e)))
  useEffect(() => { load() }, [id])

  const act = async (fn, msg) => { setBusy(true); try { await fn(); toast.success(msg); load(); onChanged() } catch (e) { toast.error(api.errMsg(e)) } finally { setBusy(false) } }
  const uploadReceipt = async (itemId, e) => {
    const file = e.target.files?.[0]; if (!file) return
    try { await api.uploadAttachment('expense_item', itemId, file); toast.success('Receipt attached'); load() } catch (err) { toast.error(api.errMsg(err)) } finally { e.target.value = '' }
  }

  if (!claim) return <Modal title="Expense claim" onClose={onClose}><div className="spinner" /></Modal>

  return (
    <Modal title={`${claim.number} — ${claim.title}`} onClose={onClose} width={680}>
      <div className="flex items-center gap-4" style={{ marginBottom: 12, flexWrap: 'wrap' }}>
        <StatusBadge status={claim.status} />
        <span className="text-sm text-muted">Claimant: <strong>{claim.claimant}</strong></span>
        <div className="flex-1" />
        <div className="flex items-center gap-1" style={{ flexWrap: 'wrap' }}>
          {claim.status === 'draft' && <button className="btn btn-primary btn-xs" disabled={busy} onClick={() => act(() => api.submitClaim(id), 'Submitted')}><Check size={12} /> Submit</button>}
          {claim.status === 'draft' && <button className="btn btn-danger btn-xs" disabled={busy} onClick={() => act(() => api.deleteClaim(id), 'Deleted').then(onClose)}><Trash2 size={12} /> Delete</button>}
          {claim.status === 'submitted' && <button className="btn btn-primary btn-xs" disabled={busy} onClick={() => act(() => api.approveClaim(id), 'Approved')}><Check size={12} /> Approve</button>}
          {claim.status === 'submitted' && <button className="btn btn-ghost btn-xs" disabled={busy} onClick={() => setRejecting(true)}><X size={12} /> Reject</button>}
          {claim.status === 'approved' && <button className="btn btn-outline btn-xs" disabled={busy} onClick={() => act(() => api.unapproveClaim(id), 'Un-approved')}>Un-approve</button>}
          {claim.status === 'approved' && <button className="btn btn-primary btn-xs" onClick={() => setReimbursing(true)}><DollarSign size={12} /> Reimburse</button>}
        </div>
      </div>
      {claim.rejected_reason && <div className="alert alert-error" style={{ marginBottom: 12 }}>Rejected: {claim.rejected_reason}</div>}

      <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: '.8rem' }}>
        <thead><tr style={{ borderBottom: '1px solid var(--border)' }}>
          <th style={{ textAlign: 'left', padding: '4px 6px' }}>Date</th><th style={{ textAlign: 'left', padding: '4px 6px' }}>Description</th>
          <th style={{ padding: '4px 6px' }}>Gross</th><th style={{ padding: '4px 6px' }}>GST</th><th style={{ padding: '4px 6px' }}>Receipt</th>
        </tr></thead>
        <tbody>
          {claim.items.map(it => (
            <tr key={it.id}>
              <td style={{ padding: '4px 6px' }}>{fmtDate(it.date)}</td>
              <td style={{ padding: '4px 6px' }}>{it.merchant ? `${it.merchant} — ` : ''}{it.description}{it.km ? ` (${it.km} km)` : ''}</td>
              <td style={{ padding: '4px 6px', textAlign: 'right' }} className="mono">{fmtAUD(it.gross)}</td>
              <td style={{ padding: '4px 6px', textAlign: 'right' }} className="mono">{fmtAUD(it.tax)}</td>
              <td style={{ padding: '4px 6px' }}>
                {it.receipts > 0 ? <span className="badge badge-success">Attached</span> : (
                  <label className="btn btn-outline btn-xs" style={{ cursor: 'pointer' }}><Paperclip size={11} /><input type="file" hidden onChange={e => uploadReceipt(it.id, e)} /></label>
                )}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      <div className="flex justify-end gap-4 text-sm" style={{ marginTop: 8 }}>
        <span>Total <strong>{fmtAUD(claim.total)}</strong></span><span>GST <strong>{fmtAUD(claim.tax_total)}</strong></span>
      </div>

      {rejecting && <RejectModal onClose={() => setRejecting(false)} onDone={reason => act(() => api.rejectClaim(id, reason), 'Rejected').then(() => setRejecting(false))} />}
      {reimbursing && <ReimburseModal banks={banks} onClose={() => setReimbursing(false)} onDone={body => act(() => api.reimburseClaim(id, body), 'Reimbursed').then(() => setReimbursing(false))} />}
    </Modal>
  )
}

function RejectModal({ onClose, onDone }) {
  const [reason, setReason] = useState('')
  return (
    <Modal title="Reject claim" onClose={onClose} width={400}>
      <Field label="Reason"><textarea className="input" rows={3} value={reason} onChange={e => setReason(e.target.value)} /></Field>
      <div className="flex justify-between"><button className="btn btn-ghost btn-sm" onClick={onClose}>Cancel</button>
        <button className="btn btn-danger btn-sm" onClick={() => onDone(reason)} disabled={!reason.trim()}>Reject</button></div>
    </Modal>
  )
}

function ReimburseModal({ banks, onClose, onDone }) {
  const [date, setDate] = useState(todayISO())
  const [bank, setBank] = useState(banks[0]?.code || '')
  return (
    <Modal title="Reimburse" onClose={onClose} width={400}>
      <Field label="Date"><input type="date" className="input" value={date} onChange={e => setDate(e.target.value)} /></Field>
      <Field label="Bank account">
        <select className="select-compact" style={{ width: '100%' }} value={bank} onChange={e => setBank(e.target.value)}>
          {banks.map(b => <option key={b.id} value={b.code}>{b.code} {b.name}</option>)}
        </select>
      </Field>
      <div className="flex justify-between"><button className="btn btn-ghost btn-sm" onClick={onClose}>Cancel</button>
        <button className="btn btn-primary btn-sm" onClick={() => onDone({ date, bank_account: bank })} disabled={!bank}>Reimburse</button></div>
    </Modal>
  )
}
