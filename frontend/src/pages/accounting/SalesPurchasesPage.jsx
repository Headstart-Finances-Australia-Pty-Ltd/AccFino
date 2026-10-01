import React, { useEffect, useMemo, useState } from 'react'
import toast from 'react-hot-toast'
import {
  Plus, RefreshCw, Trash2, Send, Check, X, ArrowRightLeft, Printer, DollarSign, Paperclip,
  Briefcase, ShoppingCart, Users,
} from 'lucide-react'
import * as api from '../../lib/booksApi.js'
import { Modal, Field, StatusBadge, EmptyState, fmtAUD, fmtDate, todayISO } from '../../components/books/Common.jsx'
import { CsvImportButton } from '../../components/books/CsvImportModal.jsx'

// which CSV importer belongs to which list
const IMPORT_ENTITY = {
  sales:     { contacts: 'customers', quote: 'quotes', main: 'invoices', credit: 'credit_notes', payments: 'receipts' },
  purchases: { contacts: 'suppliers', quote: 'purchase_orders', main: 'bills', credit: 'supplier_credits', payments: 'supplier_payments' },
}

const KIND_LABEL = {
  sales:     { quote: 'Quote',         main: 'Invoice',          credit: 'Credit Note',     contact: 'Customer' },
  purchases: { quote: 'Purchase Order', main: 'Bill',            credit: 'Supplier Credit', contact: 'Supplier' },
}
const KIND_ICON = { sales: Briefcase, purchases: ShoppingCart }

export default function SalesPurchasesPage({ side }) {
  const labels = KIND_LABEL[side]
  const Icon = KIND_ICON[side]
  const [tab, setTab] = useState('main')     // 'contacts' | 'quote' | 'main' | 'credit'
  const [accounts, setAccounts] = useState([])
  const [taxes, setTaxes] = useState([])
  const [banks, setBanks] = useState([])

  useEffect(() => {
    api.ledgerAccounts().then(r => setAccounts(r.data || [])).catch(() => {})
    api.taxCodes().then(r => setTaxes(r.data || [])).catch(() => {})
    api.bankAccounts().then(r => setBanks(r.data?.items || r.data || [])).catch(() => {})
  }, [side])

  return (
    <div className="fade-in">
      <div style={{ marginBottom: 18, display: 'flex', alignItems: 'flex-start', justifyContent: 'space-between', gap: 12, flexWrap: 'wrap' }}>
        <div>
          <div className="flex items-center gap-1"><Icon size={22} /><h2 style={{ margin: 0 }}>{side === 'sales' ? 'Sales' : 'Purchases'}</h2></div>
          <p className="text-sm text-muted" style={{ margin: '4px 0 0' }}>
            {labels.contact}s · {labels.quote}s · {labels.main}s · {labels.credit}s
          </p>
        </div>
      </div>

      <div className="tabs-bar" style={{ marginBottom: 0 }}>
        <button className={`tab-btn${tab === 'contacts' ? ' active' : ''}`} onClick={() => setTab('contacts')}>👥 {labels.contact}s</button>
        <button className={`tab-btn${tab === 'main' ? ' active' : ''}`} onClick={() => setTab('main')}>📄 {labels.main}s</button>
        <button className={`tab-btn${tab === 'quote' ? ' active' : ''}`} onClick={() => setTab('quote')}>📝 {labels.quote}s</button>
        <button className={`tab-btn${tab === 'credit' ? ' active' : ''}`} onClick={() => setTab('credit')}>↩️ {labels.credit}s</button>
        <button className={`tab-btn${tab === 'payments' ? ' active' : ''}`} onClick={() => setTab('payments')}>{side === 'sales' ? '💵 Receipts' : '💸 Payments'}</button>
      </div>

      <div style={{
        background: 'var(--surface)', border: '1px solid var(--border)', borderTop: 'none',
        borderRadius: '0 0 var(--r-lg) var(--r-lg)', minHeight: 320, boxShadow: 'var(--sh-sm)',
      }}>
        {tab === 'contacts' && <ContactsPanel side={side} accounts={accounts} taxes={taxes} />}
        {tab === 'payments' && <PaymentsPanel side={side} />}
        {tab !== 'contacts' && tab !== 'payments' && (
          <DocsPanel side={side} kind={tab} label={labels[tab]} accounts={accounts} taxes={taxes} banks={banks} />
        )}
      </div>
    </div>
  )
}

// ══════════════════════════════════════════════════════════════════════════ Contacts ═════════
function ContactsPanel({ side, accounts, taxes }) {
  const role = api.SIDE[side].role
  const label = KIND_LABEL[side].contact
  const [rows, setRows] = useState([])
  const [q, setQ] = useState('')
  const [showArchived, setShowArchived] = useState(false)
  const [loading, setLoading] = useState(false)
  const [edit, setEdit] = useState(null)

  const load = () => {
    setLoading(true)
    api.listContacts(side, { q, include_archived: showArchived }).then(r => setRows(r.data?.items || []))
      .catch(e => toast.error(api.errMsg(e))).finally(() => setLoading(false))
  }
  useEffect(() => { load() }, [side, showArchived])
  useEffect(() => { const t = setTimeout(load, 300); return () => clearTimeout(t) }, [q])

  const save = async () => {
    try {
      const body = { name: edit.name, email: edit.email || null, phone: edit.phone || null, abn: edit.abn || null,
        address: edit.address || null, terms_days: edit.terms_days ? Number(edit.terms_days) : null, is_active: edit.is_active !== false }
      if (edit.id) await api.patchContact(side, edit.id, body)
      else await api.createContact(side, body)
      toast.success(`${label} saved`); setEdit(null); load()
    } catch (e) { toast.error(api.errMsg(e)) }
  }
  const toggleArchive = async c => {
    try { await api.patchContact(side, c.id, { name: c.name, is_active: !c.is_active }); toast.success(c.is_active ? 'Archived' : 'Restored'); load() }
    catch (e) { toast.error(api.errMsg(e)) }
  }
  return (
    <div style={{ padding: 16 }}>
      <div className="flex items-center gap-4" style={{ flexWrap: 'wrap', marginBottom: 12 }}>
        <div className="search-wrap" style={{ maxWidth: 240 }}>
          <input className="input input-sm" placeholder={`Search ${label.toLowerCase()}s`} value={q} onChange={e => setQ(e.target.value)} />
        </div>
        <label className="text-sm"><input type="checkbox" checked={showArchived} onChange={e => setShowArchived(e.target.checked)} /> Show archived</label>
        <div className="flex-1" />
        <CsvImportButton entity={IMPORT_ENTITY[side].contacts} onDone={load} />
        <button className="btn btn-outline btn-sm" onClick={load} disabled={loading}><RefreshCw size={13} className={loading ? 'spin' : ''} /></button>
        <button className="btn btn-primary btn-sm" onClick={() => setEdit({ name: '', terms_days: role === 'customer' ? 14 : 30 })}>
          <Plus size={13} /> New {label}
        </button>
      </div>

      {rows.length === 0 ? <EmptyState icon="👥" title={`No ${label.toLowerCase()}s yet`} hint={`Create one, or import a CSV with name, email, phone, abn, terms_days columns.`} /> : (
        <table className="data-table">
          <thead><tr><th>Name</th><th>Email</th><th>ABN</th><th>Terms</th><th style={{ textAlign: 'right' }}>Owing</th><th style={{ width: 110 }}>Actions</th></tr></thead>
          <tbody>
            {rows.map(c => (
              <tr key={c.id} style={{ opacity: c.is_active ? 1 : .55 }}>
                <td>{c.name}</td>
                <td className="text-sm">{c.email || '—'}</td>
                <td className="mono text-sm">{c.abn || '—'}</td>
                <td className="text-sm">{c.terms_days ?? '—'}d</td>
                <td style={{ textAlign: 'right' }} className="mono">{fmtAUD(c.owing)}</td>
                <td>
                  <div className="flex items-center gap-1">
                    <button className="btn btn-outline btn-xs" onClick={() => setEdit(c)}>Edit</button>
                    <button className="btn btn-ghost btn-xs" onClick={() => toggleArchive(c)}>{c.is_active ? 'Archive' : 'Restore'}</button>
                  </div>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}

      {edit && (
        <Modal title={edit.id ? `Edit ${label}` : `New ${label}`} onClose={() => setEdit(null)} width={480}>
          <Field label="Name *"><input className="input" value={edit.name} onChange={e => setEdit({ ...edit, name: e.target.value })} /></Field>
          <Field label="Email"><input className="input" value={edit.email || ''} onChange={e => setEdit({ ...edit, email: e.target.value })} /></Field>
          <Field label="Phone"><input className="input" value={edit.phone || ''} onChange={e => setEdit({ ...edit, phone: e.target.value })} /></Field>
          <Field label="ABN" hint="11 digits, optional"><input className="input" value={edit.abn || ''} onChange={e => setEdit({ ...edit, abn: e.target.value })} /></Field>
          <Field label="Address"><textarea className="input" rows={2} value={edit.address || ''} onChange={e => setEdit({ ...edit, address: e.target.value })} /></Field>
          <Field label="Payment terms (days)"><input type="number" className="input" value={edit.terms_days ?? ''} onChange={e => setEdit({ ...edit, terms_days: e.target.value })} /></Field>
          <div className="flex justify-between" style={{ marginTop: 16 }}>
            <button className="btn btn-ghost btn-sm" onClick={() => setEdit(null)}>Cancel</button>
            <button className="btn btn-primary btn-sm" onClick={save} disabled={!edit.name?.trim()}>Save</button>
          </div>
        </Modal>
      )}
    </div>
  )
}

// ══════════════════════════════════════════════════════════════════════════ Docs ══════════════
function DocsPanel({ side, kind, label, accounts, taxes, banks }) {
  const [rows, setRows] = useState([])
  const [total, setTotal] = useState(0)
  const [status, setStatus] = useState('')
  const [loading, setLoading] = useState(false)
  const [creating, setCreating] = useState(false)
  const [openId, setOpenId] = useState(null)

  const load = () => {
    setLoading(true)
    api.listDocs(side, kind, { status: status || undefined, limit: 200 }).then(r => { setRows(r.data?.items || []); setTotal(r.data?.total || 0) })
      .catch(e => toast.error(api.errMsg(e))).finally(() => setLoading(false))
  }
  useEffect(() => { load() }, [side, kind, status])

  const statuses = kind === 'quote' ? ['draft', 'sent', 'accepted', 'declined', 'invoiced', 'billed']
    : kind === 'main' ? ['draft', 'approved', 'paid', 'voided'] : ['draft', 'approved', 'paid', 'voided']

  return (
    <div style={{ padding: 16 }}>
      <div className="flex items-center gap-4" style={{ flexWrap: 'wrap', marginBottom: 12 }}>
        <select className="select-compact" value={status} onChange={e => setStatus(e.target.value)} style={{ minWidth: 130 }}>
          <option value="">All statuses</option>
          {statuses.map(s => <option key={s} value={s}>{s}</option>)}
        </select>
        <span className="text-sm text-muted">{total} total</span>
        <div className="flex-1" />
        <CsvImportButton entity={IMPORT_ENTITY[side][kind]} onDone={load} />
        <button className="btn btn-outline btn-sm" onClick={load} disabled={loading}><RefreshCw size={13} className={loading ? 'spin' : ''} /></button>
        <button className="btn btn-primary btn-sm" onClick={() => setCreating(true)}><Plus size={13} /> New {label}</button>
      </div>

      {rows.length === 0 ? (
        <EmptyState icon="📄" title={`No ${label.toLowerCase()}s yet`} hint={`Click "New ${label}" to create one.`} />
      ) : (
        <table className="data-table">
          <thead>
            <tr><th>Number</th><th>{KIND_LABEL[side].contact}</th><th>Issued</th><th>Due</th>
              <th style={{ textAlign: 'right' }}>Total</th><th style={{ textAlign: 'right' }}>Due</th><th>Status</th></tr>
          </thead>
          <tbody>
            {rows.map(d => (
              <tr key={d.id} style={{ cursor: 'pointer' }} onClick={() => setOpenId(d.id)}>
                <td className="mono">{d.number}</td>
                <td>{d.contact}</td>
                <td className="text-sm">{fmtDate(d.issue_date)}</td>
                <td className="text-sm">{fmtDate(d.due_date)}</td>
                <td style={{ textAlign: 'right' }} className="mono">{fmtAUD(d.total)}</td>
                <td style={{ textAlign: 'right' }} className="mono">{fmtAUD(d.amount_due)}</td>
                <td><StatusBadge status={d.status} /></td>
              </tr>
            ))}
          </tbody>
        </table>
      )}

      {creating && (
        <DocFormModal side={side} kind={kind} label={label} accounts={accounts} taxes={taxes}
          onClose={() => setCreating(false)} onSaved={id => { setCreating(false); load(); setOpenId(id) }} />
      )}
      {openId && (
        <DocDetailModal side={side} kind={kind} label={label} id={openId} accounts={accounts} taxes={taxes} banks={banks}
          onClose={() => setOpenId(null)} onChanged={load} />
      )}
    </div>
  )
}

// ══════════════════════════════════════════════════════════════════════════ Receipts / Payments ═
function PaymentsPanel({ side }) {
  const [rows, setRows] = useState([])
  const [total, setTotal] = useState(0)
  const [loading, setLoading] = useState(false)
  const isSales = side === 'sales'
  const load = () => {
    setLoading(true)
    api.listPayments(side, { limit: 200 }).then(r => { setRows(r.data?.items || []); setTotal(r.data?.total || 0) })
      .catch(e => toast.error(api.errMsg(e))).finally(() => setLoading(false))
  }
  useEffect(() => { load() }, [side])
  return (
    <div style={{ padding: 16 }}>
      <div className="flex items-center gap-4" style={{ flexWrap: 'wrap', marginBottom: 12 }}>
        <span className="text-sm text-muted">{total} {isSales ? 'receipts (money received from customers)' : 'payments (money paid to suppliers)'}</span>
        <div className="flex-1" />
        <CsvImportButton entity={IMPORT_ENTITY[side].payments} onDone={load} />
        <button className="btn btn-outline btn-sm" onClick={load} disabled={loading}><RefreshCw size={13} className={loading ? 'spin' : ''} /></button>
      </div>
      {rows.length === 0 ? <EmptyState icon="💵" title={isSales ? 'No receipts yet' : 'No payments yet'} hint={`Record one from an ${isSales ? 'invoice' : 'bill'} ("${isSales ? 'Receive payment' : 'Pay'}"), or import a CSV.`} /> : (
        <table className="data-table">
          <thead><tr><th>Date</th><th>{isSales ? 'Customer' : 'Supplier'}</th><th>Reference</th><th style={{ textAlign: 'right' }}>Amount</th><th style={{ textAlign: 'right' }}>Unallocated</th><th>Bank</th><th>Status</th></tr></thead>
          <tbody>{rows.map(p => (
            <tr key={p.id} style={{ opacity: p.status === 'reversed' ? .55 : 1 }}>
              <td className="text-sm">{fmtDate(p.date)}</td><td>{p.contact}</td><td className="text-sm">{p.reference || '—'}</td>
              <td style={{ textAlign: 'right' }} className="mono">{fmtAUD(p.amount)}</td><td style={{ textAlign: 'right' }} className="mono">{Number(p.unallocated) ? fmtAUD(p.unallocated) : '—'}</td>
              <td className="text-sm">{p.reconciled ? 'reconciled' : 'not reconciled'}</td><td><StatusBadge status={p.status === 'posted' ? 'paid' : p.status} /></td>
            </tr>))}</tbody>
        </table>
      )}
    </div>
  )
}

// ── create form ──────────────────────────────────────────────────────────────────────────────
function emptyLine() { return { description: '', qty: 1, unit_price: '0.00', tax_code: '', account: '' } }

function DocFormModal({ side, kind, label, accounts, taxes, onClose, onSaved }) {
  const role = api.SIDE[side].role
  const [contact, setContact] = useState('')
  const [issued, setIssued] = useState(todayISO())
  const [due, setDue] = useState('')
  const [reference, setReference] = useState('')
  const [amountsAre, setAmountsAre] = useState('exclusive')
  const [lines, setLines] = useState([emptyLine()])
  const [saveAsDraft, setSaveAsDraft] = useState(false)
  const [saving, setSaving] = useState(false)

  const defaultTax = side === 'sales' ? (taxes.find(t => t.code === 'OUTPUT')?.code || '') : (taxes.find(t => t.code === 'INPUT')?.code || '')
  useEffect(() => { setLines([{ ...emptyLine(), tax_code: defaultTax }]) }, [defaultTax])

  const setLine = (i, patch) => setLines(ls => ls.map((l, ix) => ix === i ? { ...l, ...patch } : l))
  const addLine = () => setLines(ls => [...ls, { ...emptyLine(), tax_code: defaultTax }])
  const removeLine = i => setLines(ls => ls.length > 1 ? ls.filter((_, ix) => ix !== i) : ls)

  const totals = useMemo(() => {
    let net = 0, tax = 0
    for (const l of lines) {
      const gross = Number(l.qty || 0) * Number(l.unit_price || 0) * (1 - Number(l.discount_pct || 0) / 100)
      const tc = taxes.find(t => t.code === l.tax_code)
      const rate = tc ? Number(tc.rate) : 0
      if (amountsAre === 'inclusive') { const n = gross / (1 + rate); net += n; tax += gross - n }
      else if (amountsAre === 'no_tax') { net += gross }
      else { net += gross; tax += gross * rate }
    }
    return { net, tax, total: net + tax }
  }, [lines, amountsAre, taxes])

  const save = async () => {
    if (!contact.trim()) { toast.error(`Choose a ${role}`); return }
    if (!lines.some(l => l.description.trim() && Number(l.unit_price) !== 0)) { toast.error('Add at least one line with an amount'); return }
    setSaving(true)
    try {
      const body = {
        [role]: contact, issued, due: due || undefined, reference: reference || undefined, amounts_are: amountsAre,
        status: saveAsDraft ? 'draft' : 'approved',
        lines: lines.filter(l => l.description.trim()).map(l => ({
          description: l.description, qty: Number(l.qty || 1), unit_price: String(l.unit_price || 0),
          tax_code: l.tax_code || undefined, account: (kind !== 'quote' && side === 'purchases') ? (l.account || undefined) : undefined,
        })),
      }
      const r = await api.createDoc(side, kind, body)
      toast.success(`${label} ${saveAsDraft ? 'saved as draft' : 'created and posted'}`)
      onSaved(r.data.id)
    } catch (e) { toast.error(api.errMsg(e)) }
    finally { setSaving(false) }
  }

  return (
    <Modal title={`New ${label}`} onClose={onClose} width={780}>
      <div className="grid-2" style={{ gap: 12 }}>
        <Field label={`${KIND_LABEL[side].contact} *`}>
          <input className="input" list="contact-suggest" value={contact} onChange={e => setContact(e.target.value)} placeholder={`Type a name`} />
        </Field>
        <Field label="Reference"><input className="input" value={reference} onChange={e => setReference(e.target.value)} /></Field>
        <Field label="Issue date"><input type="date" className="input" value={issued} onChange={e => setIssued(e.target.value)} /></Field>
        <Field label="Due date" hint="Leave blank to use the contact's payment terms"><input type="date" className="input" value={due} onChange={e => setDue(e.target.value)} /></Field>
        <Field label="Amounts are">
          <select className="select-compact" value={amountsAre} onChange={e => setAmountsAre(e.target.value)}>
            <option value="exclusive">Tax exclusive</option><option value="inclusive">Tax inclusive</option><option value="no_tax">No GST</option>
          </select>
        </Field>
      </div>

      <div style={{ marginTop: 16, marginBottom: 6, fontWeight: 600, fontSize: '.85rem' }}>Line items</div>
      <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: '.8rem' }}>
        <thead><tr style={{ borderBottom: '1px solid var(--border)' }}>
          <th style={{ textAlign: 'left', padding: '4px 6px' }}>Description</th>
          <th style={{ width: 60, padding: '4px 6px' }}>Qty</th>
          <th style={{ width: 100, padding: '4px 6px' }}>Unit price</th>
          {side === 'purchases' && kind !== 'quote' && <th style={{ width: 110, padding: '4px 6px' }}>Account</th>}
          <th style={{ width: 110, padding: '4px 6px' }}>Tax</th>
          <th style={{ width: 30 }} />
        </tr></thead>
        <tbody>
          {lines.map((l, i) => (
            <tr key={i}>
              <td style={{ padding: '3px 6px' }}><input className="input input-sm" value={l.description} onChange={e => setLine(i, { description: e.target.value })} /></td>
              <td style={{ padding: '3px 6px' }}><input type="number" className="input input-sm" value={l.qty} onChange={e => setLine(i, { qty: e.target.value })} /></td>
              <td style={{ padding: '3px 6px' }}><input type="number" step="0.01" className="input input-sm" value={l.unit_price} onChange={e => setLine(i, { unit_price: e.target.value })} /></td>
              {side === 'purchases' && kind !== 'quote' && (
                <td style={{ padding: '3px 6px' }}>
                  <select className="select-compact" style={{ width: '100%' }} value={l.account} onChange={e => setLine(i, { account: e.target.value })}>
                    <option value="">—</option>
                    {accounts.filter(a => ['expense', 'direct_costs', 'other_expense', 'fixed_asset'].includes(a.type)).map(a => <option key={a.id} value={a.code}>{a.code} {a.name}</option>)}
                  </select>
                </td>
              )}
              <td style={{ padding: '3px 6px' }}>
                <select className="select-compact" style={{ width: '100%' }} value={l.tax_code} onChange={e => setLine(i, { tax_code: e.target.value })}>
                  <option value="">—</option>
                  {taxes.filter(t => t.applies_to === (side === 'sales' ? 'sales' : 'purchases') || t.applies_to === 'both').map(t => <option key={t.id} value={t.code}>{t.code}</option>)}
                </select>
              </td>
              <td><button className="btn btn-ghost btn-xs" onClick={() => removeLine(i)}><Trash2 size={12} /></button></td>
            </tr>
          ))}
        </tbody>
      </table>
      <button className="btn btn-outline btn-xs" style={{ marginTop: 6 }} onClick={addLine}><Plus size={11} /> Add line</button>

      <div className="flex justify-between items-center" style={{ marginTop: 16, borderTop: '1px solid var(--border)', paddingTop: 12 }}>
        <div className="text-sm">
          Subtotal <strong>{fmtAUD(totals.net)}</strong> &nbsp;+&nbsp; GST <strong>{fmtAUD(totals.tax)}</strong> &nbsp;=&nbsp;
          <span style={{ fontSize: '1rem' }}> Total <strong>{fmtAUD(totals.total)}</strong></span>
        </div>
        <label className="text-sm"><input type="checkbox" checked={saveAsDraft} onChange={e => setSaveAsDraft(e.target.checked)} /> Save as draft</label>
      </div>
      <div className="flex justify-between" style={{ marginTop: 16 }}>
        <button className="btn btn-ghost btn-sm" onClick={onClose}>Cancel</button>
        <button className="btn btn-primary btn-sm" onClick={save} disabled={saving}>{saving ? 'Saving…' : 'Save'}</button>
      </div>
    </Modal>
  )
}

// ── detail / actions ─────────────────────────────────────────────────────────────────────────
function DocDetailModal({ side, kind, label, id, accounts, taxes, banks, onClose, onChanged }) {
  const [doc, setDoc] = useState(null)
  const [busy, setBusy] = useState(false)
  const [showPay, setShowPay] = useState(false)
  const [showAllocate, setShowAllocate] = useState(false)
  const [attachments, setAttachments] = useState([])

  const load = () => api.getDoc(side, kind, id).then(r => setDoc(r.data)).catch(e => toast.error(api.errMsg(e)))
  useEffect(() => { load() }, [id])

  const act = async (fn, okMsg) => {
    setBusy(true)
    try { await fn(); toast.success(okMsg); load(); onChanged() } catch (e) { toast.error(api.errMsg(e)) } finally { setBusy(false) }
  }

  const doPrint = async () => {
    try { const r = await api.fetchPrintHtml(side, kind, id); if (!api.openPrintable(r.data)) toast.error('Pop-up blocked - allow pop-ups to print') }
    catch (e) { toast.error(api.errMsg(e)) }
  }

  const uploadFile = async e => {
    const file = e.target.files?.[0]; if (!file) return
    try { await api.uploadAttachment('doc', id, file); toast.success('Attached'); load() } catch (err) { toast.error(api.errMsg(err)) }
    finally { e.target.value = '' }
  }

  if (!doc) return <Modal title={label} onClose={onClose}><div className="spinner" /></Modal>

  const isQuote = kind === 'quote'
  const isCredit = kind === 'credit'
  const isMain = kind === 'main'

  return (
    <Modal title={`${label} ${doc.number}`} onClose={onClose} width={760}>
      <div className="flex items-center gap-4" style={{ marginBottom: 12, flexWrap: 'wrap' }}>
        <StatusBadge status={doc.status} />
        <span className="text-sm text-muted">{KIND_LABEL[side].contact}: <strong>{doc.contact}</strong></span>
        <span className="text-sm text-muted">Issued {fmtDate(doc.issue_date)}</span>
        {doc.due_date && <span className="text-sm text-muted">Due {fmtDate(doc.due_date)}</span>}
        <div className="flex-1" />
        <div className="flex items-center gap-1" style={{ flexWrap: 'wrap' }}>
          {doc.status === 'draft' && !isQuote && <button className="btn btn-primary btn-xs" disabled={busy} onClick={() => act(() => api.approveDoc(side, kind, id), 'Approved')}><Check size={12} /> Approve</button>}
          {doc.status === 'draft' && <button className="btn btn-danger btn-xs" disabled={busy} onClick={() => act(() => api.deleteDoc(side, kind, id), 'Deleted').then(onClose)}><Trash2 size={12} /> Delete</button>}
          {(doc.status === 'approved' || doc.status === 'sent') && <button className="btn btn-outline btn-xs" disabled={busy} onClick={() => act(() => api.sendDoc(side, kind, id), 'Marked as sent')}><Send size={12} /> Send</button>}
          {isQuote && doc.status === 'sent' && <button className="btn btn-outline btn-xs" disabled={busy} onClick={() => act(() => api.acceptQuote(side, id), 'Accepted')}><Check size={12} /> Accept</button>}
          {isQuote && ['draft', 'sent'].includes(doc.status) && <button className="btn btn-ghost btn-xs" disabled={busy} onClick={() => act(() => api.declineQuote(side, id), 'Declined')}><X size={12} /> Decline</button>}
          {isQuote && ['accepted', 'draft', 'sent'].includes(doc.status) && <button className="btn btn-primary btn-xs" disabled={busy} onClick={() => act(() => api.convertQuote(side, id), `Converted to ${KIND_LABEL[side].main.toLowerCase()}`)}><ArrowRightLeft size={12} /> Convert to {KIND_LABEL[side].main}</button>}
          {!isQuote && !['voided', 'draft'].includes(doc.status) && <button className="btn btn-outline btn-xs" onClick={doPrint}><Printer size={12} /> Print</button>}
          {isMain && doc.status === 'approved' && Number(doc.amount_due) > 0 && <button className="btn btn-primary btn-xs" onClick={() => setShowPay(true)}><DollarSign size={12} /> {side === 'sales' ? 'Receive payment' : 'Pay'}</button>}
          {isCredit && doc.status === 'approved' && Number(doc.amount_due) > 0 && <button className="btn btn-primary btn-xs" onClick={() => setShowAllocate(true)}><ArrowRightLeft size={12} /> Allocate</button>}
          {isCredit && doc.status === 'approved' && Number(doc.amount_due) > 0 && <button className="btn btn-outline btn-xs" onClick={() => setShowPay(true)}><DollarSign size={12} /> Refund</button>}
          {!['draft', 'voided'].includes(doc.status) && doc.status !== 'invoiced' && doc.status !== 'billed' && <button className="btn btn-ghost btn-xs" disabled={busy} onClick={() => act(() => api.voidDoc(side, kind, id), 'Voided')}><X size={12} /> Void</button>}
        </div>
      </div>

      <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: '.8rem', marginBottom: 12 }}>
        <thead><tr style={{ borderBottom: '1px solid var(--border)' }}>
          <th style={{ textAlign: 'left', padding: '4px 6px' }}>Description</th><th style={{ padding: '4px 6px' }}>Qty</th>
          <th style={{ padding: '4px 6px' }}>Unit price</th><th style={{ padding: '4px 6px' }}>Tax</th><th style={{ padding: '4px 6px' }}>Net</th>
        </tr></thead>
        <tbody>{(doc.lines || []).map(l => (
          <tr key={l.id}><td style={{ padding: '4px 6px' }}>{l.description}</td><td style={{ padding: '4px 6px', textAlign: 'right' }}>{l.qty}</td>
            <td style={{ padding: '4px 6px', textAlign: 'right' }} className="mono">{fmtAUD(l.unit_price)}</td>
            <td style={{ padding: '4px 6px', textAlign: 'center' }}>{l.tax_code || '—'}</td>
            <td style={{ padding: '4px 6px', textAlign: 'right' }} className="mono">{fmtAUD(l.net)}</td></tr>
        ))}</tbody>
      </table>
      <div className="flex justify-end gap-4 text-sm" style={{ marginBottom: 12 }}>
        <span>Subtotal <strong>{fmtAUD(doc.subtotal)}</strong></span>
        <span>GST <strong>{fmtAUD(doc.tax_total)}</strong></span>
        <span>Total <strong>{fmtAUD(doc.total)}</strong></span>
        {isMain && <span>Due <strong>{fmtAUD(doc.amount_due)}</strong></span>}
      </div>

      {doc.payments?.length > 0 && (
        <div style={{ marginBottom: 12 }}>
          <div className="text-sm" style={{ fontWeight: 600, marginBottom: 4 }}>Payments</div>
          {doc.payments.map((p, i) => <div key={i} className="text-sm text-muted">{fmtDate(p.date)} — {fmtAUD(p.amount)} {p.reference ? `(${p.reference})` : ''}</div>)}
        </div>
      )}

      <div>
        <div className="text-sm" style={{ fontWeight: 600, marginBottom: 4 }}>Attachments ({doc.attachments || 0})</div>
        <label className="btn btn-outline btn-xs" style={{ cursor: 'pointer' }}>
          <Paperclip size={11} /> Attach a file
          <input type="file" hidden onChange={uploadFile} />
        </label>
      </div>

      {showPay && (
        <PayModal side={side} kind={kind} id={id} isCredit={isCredit} doc={doc} banks={banks}
          onClose={() => setShowPay(false)} onDone={() => { setShowPay(false); load(); onChanged() }} />
      )}
      {showAllocate && (
        <AllocateModal side={side} id={id} doc={doc} onClose={() => setShowAllocate(false)} onDone={() => { setShowAllocate(false); load(); onChanged() }} />
      )}
    </Modal>
  )
}

function PayModal({ side, kind, id, isCredit, doc, banks, onClose, onDone }) {
  const [amount, setAmount] = useState(doc.amount_due)
  const [date, setDate] = useState(todayISO())
  const [bank, setBank] = useState(banks[0]?.code || '')
  const [reference, setReference] = useState('')
  const [saving, setSaving] = useState(false)

  const save = async () => {
    setSaving(true)
    try {
      const body = { date, amount, bank_account: bank, reference: reference || undefined }
      if (isCredit) await api.refundCredit(side, id, body)
      else await api.payDoc(side, kind, id, body)
      toast.success(isCredit ? 'Refund recorded' : 'Payment recorded')
      onDone()
    } catch (e) { toast.error(api.errMsg(e)) } finally { setSaving(false) }
  }

  return (
    <Modal title={isCredit ? 'Refund' : (side === 'sales' ? 'Receive payment' : 'Pay bill')} onClose={onClose} width={420}>
      <Field label="Amount"><input type="number" step="0.01" className="input" value={amount} onChange={e => setAmount(e.target.value)} /></Field>
      <Field label="Date"><input type="date" className="input" value={date} onChange={e => setDate(e.target.value)} /></Field>
      <Field label="Bank account">
        <select className="select-compact" style={{ width: '100%' }} value={bank} onChange={e => setBank(e.target.value)}>
          {banks.map(b => <option key={b.id} value={b.code}>{b.code} {b.name}</option>)}
        </select>
      </Field>
      <Field label="Reference"><input className="input" value={reference} onChange={e => setReference(e.target.value)} /></Field>
      <div className="flex justify-between" style={{ marginTop: 12 }}>
        <button className="btn btn-ghost btn-sm" onClick={onClose}>Cancel</button>
        <button className="btn btn-primary btn-sm" onClick={save} disabled={saving || !bank}>{saving ? 'Saving…' : 'Save'}</button>
      </div>
    </Modal>
  )
}

function AllocateModal({ side, id, doc, onClose, onDone }) {
  const [targetDoc, setTargetDoc] = useState('')
  const [amount, setAmount] = useState(doc.amount_due)
  const [options, setOptions] = useState([])
  const [saving, setSaving] = useState(false)

  useEffect(() => {
    api.listDocs(side, 'main', { contact_id: doc.contact_id, status: 'approved', limit: 100 })
      .then(r => setOptions((r.data?.items || []).filter(d => Number(d.amount_due) > 0))).catch(() => {})
  }, [])

  const save = async () => {
    if (!targetDoc) { toast.error('Choose a document to apply the credit to'); return }
    setSaving(true)
    try {
      await api.allocateCredit(side, id, { allocations: [{ doc_id: Number(targetDoc), amount }] })
      toast.success('Applied'); onDone()
    } catch (e) { toast.error(api.errMsg(e)) } finally { setSaving(false) }
  }

  return (
    <Modal title="Apply credit" onClose={onClose} width={440}>
      <Field label={`Apply to ${side === 'sales' ? 'invoice' : 'bill'}`}>
        <select className="select-compact" style={{ width: '100%' }} value={targetDoc} onChange={e => setTargetDoc(e.target.value)}>
          <option value="">Choose…</option>
          {options.map(d => <option key={d.id} value={d.id}>{d.number} — due {fmtAUD(d.amount_due)}</option>)}
        </select>
      </Field>
      <Field label="Amount"><input type="number" step="0.01" className="input" value={amount} onChange={e => setAmount(e.target.value)} /></Field>
      <div className="flex justify-between" style={{ marginTop: 12 }}>
        <button className="btn btn-ghost btn-sm" onClick={onClose}>Cancel</button>
        <button className="btn btn-primary btn-sm" onClick={save} disabled={saving}>{saving ? 'Saving…' : 'Apply'}</button>
      </div>
    </Modal>
  )
}
