/**
 * JournalTools - the General Ledger screens beyond the editor:
 *   JournalsTab   search + filter (every source, status, account, amount) + paging + CSV; view a journal with its source, reversal, attachments and history; copy / reverse
 *   ReviewTab     the approval queue: AI/rule bank-coding suggestions (confidence, reason, adjust, approve, reject, bulk approve) + drafts awaiting approval + my drafts
 *   RepeatingTab  repeating journal templates and "run due now"
 *   ImportModal   CSV import - check first, all-or-nothing, as drafts or posted
 *   HealthStrip   what needs attention at a glance
 * Every rule is enforced by the server; the buttons shown here only reflect what the user's role can do.
 */
import React, { useEffect, useMemo, useRef, useState } from 'react'
import toast from 'react-hot-toast'
import { Plus, Eye, RotateCcw, Upload, Download, Copy, Paperclip, Play, Sparkles, Check, X, Coins } from 'lucide-react'
import * as api__0 from '../../lib/ledgerApi.js'
import * as api__1 from '../../../../core/lib/platformApi.js'
import * as books__0 from '../../lib/booksApi.js'
import * as books__1 from '../../../../core/lib/platformHttp.js'
import { useBulkImportEnabled } from '../../hooks/useBulkImport.jsx'
import { JournalEditor, RepeatingEditor, Modal, aud, money, today } from './JournalEditor.jsx'

const APPROVERS = ['owner', 'admin', 'accountant']
export const isApprover = role => APPROVERS.includes(role)
const fyStart = () => { const d = new Date(); const y = d.getMonth() >= 6 ? d.getFullYear() : d.getFullYear() - 1; return `${y}-07-01` }
const csvCell = v => `"${String(v ?? '').replace(/"/g, '""')}"`
const saveCsv = (rows, name) => { const a = document.createElement('a'); a.href = URL.createObjectURL(new Blob([rows.map(r => r.map(csvCell).join(',')).join('\n')], { type: 'text/csv' })); a.download = name; a.click() }
const useLookups = () => {
  const [accounts, setAccounts] = useState([]); const [taxes, setTaxes] = useState([]); const [categories, setCategories] = useState([])
  useEffect(() => {
    api__0.accounts().then(r => setAccounts(r.data || [])).catch(() => {})
    api__0.taxCodes().then(r => setTaxes(r.data || [])).catch(() => {})
    api__0.tracking().then(r => setCategories(r.data || [])).catch(() => {})
  }, [])
  return { accounts, taxes, categories }
}

export function statusBadge(j) {
  if (j.status === 'reversed') return <span className="badge badge-warning">reversed</span>
  if (j.reversal_of_id) return <span className="badge badge-info">{j.source_type === 'auto_reversal' ? 'auto-reversal' : 'reversal'}</span>
  if (j.reversed_by_id) return <span className="badge badge-info" title="A reversing journal is scheduled">auto-reverses</span>
  return <span className="badge badge-success">posted</span>
}

// ── Health strip ─────────────────────────────────────────────────────────────
export function HealthStrip({ health, onGo }) {
  if (!health) return null
  const chip = (label, n, tab, warn, extra) => (n > 0 || warn) && (
    <button key={label} className={`badge ${warn ? 'badge-warning' : 'badge-neutral'}`} style={{ cursor: 'pointer', border: 'none' }} onClick={() => onGo(tab, extra)}>{label}</button>)
  const susp = Number(health.suspense_balance) !== 0
  return (
    <div className="flex items-center gap-1" style={{ flexWrap: 'wrap', marginBottom: 12, fontSize: '.78rem' }} data-testid="health">
      {chip(`${health.ai_suggestions} AI suggestion${health.ai_suggestions === 1 ? '' : 's'} to review`, health.ai_suggestions, 'review', true)}
      {chip(`${health.awaiting_approval} awaiting approval`, health.awaiting_approval, 'review', true)}
      {chip(`${health.drafts} draft${health.drafts === 1 ? '' : 's'}`, health.drafts, 'review')}
      {chip(`${health.rejected} rejected`, health.rejected, 'review', true)}
      {chip(`${health.repeating_due} repeating due`, health.repeating_due, 'repeating', true)}
      {chip(`${health.future_dated} future-dated`, health.future_dated, 'journals', false, { to: '2099-12-31' })}
      {susp && <span className="badge badge-warning" title="Uncoded items are parked in Suspense">Suspense {aud(health.suspense_balance)}</span>}
      {!health.ai_suggestions && !health.awaiting_approval && !health.drafts && !health.rejected && !health.repeating_due && !susp && <span className="badge badge-success">Nothing needs attention</span>}
    </div>
  )
}

// ── Exchange rates (the organisation's OWN rates; AccFino never invents one) ─────────────────────────────
export function FxRatesModal({ onClose }) {
  const [items, setItems] = useState([]); const [base, setBase] = useState('AUD')
  const [f, setF] = useState({ currency: '', date: today(), rate: '', source: '' })
  const load = () => api__0.fxRates().then(r => { setItems(r.data.items || []); setBase(r.data.base || 'AUD') }).catch(e => toast.error(api__1.errMsg(e)))
  useEffect(() => { load() }, [])
  const save = async () => { try { await api__0.putFxRate({ ...f, currency: f.currency.toUpperCase(), source: f.source || null }); toast.success('Rate saved'); setF(x => ({ ...x, rate: '' })); load() } catch (e) { toast.error(api__1.errMsg(e)) } }
  const del = async id => { if (window.confirm('Delete this rate? Journals already posted at it keep it.')) { try { await api__0.deleteFxRate(id); load() } catch (e) { toast.error(api__1.errMsg(e)) } } }
  return (
    <Modal title="Exchange rates" onClose={onClose} width={700}>
      <p className="text-sm" style={{ marginTop: 0 }}>Rates are 1 unit of the foreign currency in <b>{base}</b>. A foreign-currency journal uses the latest rate on or before its date, or the rate you type on the journal. Nothing is ever fetched or guessed.</p>
      <div className="flex gap-1" style={{ flexWrap: 'wrap', marginBottom: 12 }}>
        <input aria-label="Rate currency" className="input input-sm" style={{ width: 80 }} maxLength={3} placeholder="USD" value={f.currency} onChange={e => setF(x => ({ ...x, currency: e.target.value.toUpperCase() }))} />
        <input aria-label="Rate date" type="date" className="input input-sm" value={f.date} onChange={e => setF(x => ({ ...x, date: e.target.value }))} />
        <input aria-label="Rate value" className="input input-sm" style={{ width: 110 }} inputMode="decimal" placeholder={`${base} per 1`} value={f.rate} onChange={e => setF(x => ({ ...x, rate: e.target.value }))} />
        <input aria-label="Rate source" className="input input-sm" style={{ width: 120 }} placeholder="Source (RBA…)" value={f.source} onChange={e => setF(x => ({ ...x, source: e.target.value }))} />
        <button className="btn btn-primary btn-sm" disabled={!f.currency || !f.rate} onClick={save}>Save rate</button>
      </div>
      <div className="data-table-wrap"><table className="data-table"><thead><tr><th>Currency</th><th>Date</th><th className="text-right">Rate</th><th>Source</th><th /></tr></thead>
        <tbody>{items.map(r => <tr key={r.id}><td><b>{r.currency}</b></td><td>{r.date}</td><td className="text-right mono">{Number(r.rate)}</td><td className="text-sm">{r.source}</td><td className="text-right"><button className="btn btn-ghost btn-xs" onClick={() => del(r.id)}>Delete</button></td></tr>)}
          {!items.length && <tr><td colSpan={5} className="text-center text-muted">No rates yet.</td></tr>}</tbody></table></div>
    </Modal>)
}

// ── Journals list ────────────────────────────────────────────────────────────
const PAGE = 50
export function JournalsTab({ canApprove, requireApproval, onChanged, preset }) {
  const lk = useLookups()
  const [f, setF] = useState({ from: fyStart(), to: today(), source: '', status: '', account: '', q: '', min: '', max: '' })
  const [data, setData] = useState({ items: [], total: 0, sum_total: '0' })
  const [sources, setSources] = useState([])
  const [page, setPage] = useState(0)
  const [view, setView] = useState(null)
  const [editor, setEditor] = useState(null)
  const [importing, setImporting] = useState(false)
  const bulkImport = useBulkImportEnabled()
  const [rates, setRates] = useState(false)
  useEffect(() => { if (preset) { const { open, _k, ...filters } = preset; if (Object.keys(filters).length) setF(x => ({ ...x, ...filters })); if (open) setEditor({ initial: open }) } }, [preset])
  useEffect(() => { api__0.journalSources().then(r => setSources(r.data.items || [])).catch(() => {}) }, [data.total])
  const srcLabel = useMemo(() => Object.fromEntries(sources.map(s => [s.source, s.label])), [sources])
  const params = (offset, limit) => ({ from: f.from, to: f.to, source_type: f.source || undefined, status: f.status || undefined, account_id: f.account || undefined, q: f.q || undefined,
    min_amount: f.min || undefined, max_amount: f.max || undefined, limit, offset })
  const load = () => api__0.journals(params(page * PAGE, PAGE)).then(r => setData(r.data)).catch(e => toast.error(api__1.errMsg(e)))
  useEffect(() => { const t = setTimeout(load, f.q ? 300 : 0); return () => clearTimeout(t) }, [f, page]) // eslint-disable-line react-hooks/exhaustive-deps
  const set = (k, v) => { setPage(0); setF(x => ({ ...x, [k]: v })) }
  const refresh = () => { load(); onChanged?.() }
  const exportAll = async () => {
    try {
      const rows = []; for (let off = 0; off < Math.min(data.total, 5000); off += 500) rows.push(...(await api__0.journals(params(off, 500))).data.items)
      saveCsv([['No.', 'Date', 'Reference', 'Narration', 'Source', 'Status', 'Total'], ...rows.map(j => [j.journal_no, j.date, j.reference, j.narration, srcLabel[j.source_type] || j.source_type, j.status, j.total])], `journals-${f.from}-${f.to}.csv`)
    } catch (e) { toast.error(api__1.errMsg(e)) }
  }
  const open = id => api__0.journal(id).then(r => setView(r.data)).catch(e => toast.error(api__1.errMsg(e)))
  const pages = Math.max(1, Math.ceil(data.total / PAGE))
  return (
    <div>
      <div className="flex items-center gap-4" style={{ flexWrap: 'wrap', marginBottom: 8 }}>
        <input aria-label="Search journals" className="input input-sm" style={{ maxWidth: 220 }} placeholder="Search narration, reference, no., contact…" value={f.q} onChange={e => set('q', e.target.value)} />
        <label className="text-sm">From <input type="date" aria-label="From" className="input input-sm" value={f.from} onChange={e => set('from', e.target.value)} /></label>
        <label className="text-sm">To <input type="date" aria-label="To" className="input input-sm" value={f.to} onChange={e => set('to', e.target.value)} /></label>
        <div className="flex-1" />
        <button className="btn btn-outline btn-sm" onClick={() => setRates(true)}><Coins size={14} /> Exchange rates</button>
        {bulkImport && <button className="btn btn-outline btn-sm" onClick={() => setImporting(true)}><Upload size={14} /> Import</button>}
        <button className="btn btn-outline btn-sm" onClick={exportAll} disabled={!data.total}><Download size={14} /> CSV</button>
        <button className="btn btn-primary btn-sm" onClick={() => setEditor({})}><Plus size={14} /> New journal</button>
      </div>
      <div className="flex items-center gap-4" style={{ flexWrap: 'wrap', marginBottom: 12 }}>
        <select aria-label="Source" className="input input-sm" style={{ maxWidth: 200 }} value={f.source} onChange={e => set('source', e.target.value)}>
          <option value="">All sources</option>{sources.map(s => <option key={s.source} value={s.source}>{s.label} ({s.count})</option>)}</select>
        <select aria-label="Status" className="input input-sm" style={{ maxWidth: 150 }} value={f.status} onChange={e => set('status', e.target.value)}>
          <option value="">Any status</option><option value="posted">Posted</option><option value="reversed">Reversed</option><option value="reversal">Reversals</option></select>
        <select aria-label="Account" className="input input-sm" style={{ maxWidth: 220 }} value={f.account} onChange={e => set('account', e.target.value)}>
          <option value="">Any account</option>{lk.accounts.map(a => <option key={a.id} value={a.id}>{a.code} · {a.name}</option>)}</select>
        <input aria-label="Minimum amount" className="input input-sm" style={{ width: 100 }} inputMode="decimal" placeholder="Min $" value={f.min} onChange={e => set('min', e.target.value)} />
        <input aria-label="Maximum amount" className="input input-sm" style={{ width: 100 }} inputMode="decimal" placeholder="Max $" value={f.max} onChange={e => set('max', e.target.value)} />
        {(f.q || f.source || f.status || f.account || f.min || f.max) && <button className="btn btn-ghost btn-xs" onClick={() => { setPage(0); setF(x => ({ ...x, q: '', source: '', status: '', account: '', min: '', max: '' })) }}>Clear filters</button>}
      </div>
      <div className="data-table-wrap">
        <table className="data-table">
          <thead><tr><th>No.</th><th>Date</th><th>Reference</th><th>Narration</th><th>Source</th><th>Status</th><th className="text-right">Total</th><th /></tr></thead>
          <tbody>
            {data.items.map(j => (
              <tr key={j.id}>
                <td className="mono">{j.journal_no}</td><td>{j.date}</td><td className="text-sm mono">{j.reference || ''}{j.currency && <span className="badge badge-info" style={{ marginLeft: 4 }}>{j.currency}</span>}</td><td className="truncate" style={{ maxWidth: 320 }} title={j.narration}>{j.narration}</td>
                <td className="text-sm">{srcLabel[j.source_type] || j.source_type}</td><td>{statusBadge(j)}</td><td className="text-right mono">{aud(j.total)}</td>
                <td className="text-right"><button className="btn btn-ghost btn-xs" onClick={() => open(j.id)}><Eye size={12} /> View</button></td>
              </tr>))}
            {!data.items.length && <tr><td colSpan={8} className="text-center text-muted">No journals match{f.q || f.source || f.status || f.account || f.min || f.max ? ' these filters' : ' in this period'}</td></tr>}
          </tbody>
        </table>
      </div>
      <div className="flex items-center gap-4 mt-1" style={{ fontSize: '.78rem' }}>
        <span className="text-muted">{data.total} journal(s) · combined value {aud(data.sum_total)}</span><div className="flex-1" />
        <button className="btn btn-ghost btn-xs" disabled={page === 0} onClick={() => setPage(p => p - 1)}>← Previous</button><span>Page {page + 1} of {pages}</span>
        <button className="btn btn-ghost btn-xs" disabled={page + 1 >= pages} onClick={() => setPage(p => p + 1)}>Next →</button>
      </div>
      {view && <JournalView j={view} onClose={() => setView(null)} onChanged={() => { open(view.id); refresh() }} onReversed={() => { setView(null); refresh() }}
        onCopy={() => { setEditor({ initial: { narration: `${view.narration} (copy)`, reference: view.reference, currency: view.currency, lines: view.lines.map(l => { const x = view.currency ? { ...l, debit: l.orig_debit ?? l.debit, credit: l.orig_credit ?? l.credit } : l; return (Number(l.tax_amount) > 0 || l.account_code === '820') ? { ...x, tax_code_id: null } : x }) } }); setView(null) }} />}
      {editor && <JournalEditor {...lk} initial={editor.initial} canApprove={canApprove} requireApproval={requireApproval} onClose={() => setEditor(null)} onDone={() => { setEditor(null); refresh() }} />}
      {rates && <FxRatesModal onClose={() => setRates(false)} />}
      {importing && <ImportModal canApprove={canApprove} onClose={() => setImporting(false)} onDone={() => { setImporting(false); refresh() }} />}
    </div>
  )
}

export function JournalView({ j, onClose, onChanged, onReversed, onCopy }) {
  const [hist, setHist] = useState(null)
  const [revDate, setRevDate] = useState(j.date)
  const fileRef = useRef()
  const src = j.source || {}
  const reverse = async () => {
    if (!window.confirm(`Reverse journal ${j.journal_no}? A reversing journal will be posted on ${revDate}.`)) return
    try { const { data: r } = await api__0.reverseJournal(j.id, { date: revDate }); toast.success(`Reversal journal ${r.journal_no} posted`); onReversed() } catch (e) { toast.error(api__1.errMsg(e)) }
  }
  const attach = async e => {
    for (const f of Array.from(e.target.files || [])) { try { await books__0.uploadAttachment('journal', j.id, f); toast.success(`${f.name} attached`) } catch (er) { toast.error(books__1.errMsg(er)) } }
    onChanged()
  }
  return (
    <Modal title={`Journal ${j.journal_no} · ${j.date}`} onClose={onClose} width={900}>
      <p className="text-sm"><b>{j.narration}</b>{j.reference && <span className="badge badge-neutral" style={{ marginLeft: 8 }}>Ref {j.reference}</span>}</p>
      {j.currency && <div className="alert alert-info" data-testid="fx-view">Entered in <b>{j.currency}</b> at 1 {j.currency} = {Number(j.exchange_rate)}. The ledger holds the base-currency amounts; the original amounts are shown under each figure.</div>}
      <p className="text-xs text-muted" style={{ marginTop: 0 }}>Source: <span data-testid="source-label">{src.label || j.source_type}</span>{src.status ? ` · ${src.status}` : ''}{src.total ? ` · ${aud(src.total)}` : ''}</p>
      {j.reversal && <div className={`alert ${j.reversal.pending ? 'alert-info' : 'alert-warning'}`}>{j.reversal.pending ? `Auto-reverses on ${j.reversal.date} (journal ${j.reversal.journal_no}).` : `Reversed by journal ${j.reversal.journal_no} on ${j.reversal.date}.`}</div>}
      {j.reverses && <div className="alert alert-info">This journal reverses journal {j.reverses.journal_no}.</div>}
      <div className="data-table-wrap"><table className="data-table">
        <thead><tr><th>Account</th><th>Description</th><th>Contact</th><th>Tax</th><th>Tracking</th><th className="text-right">Debit</th><th className="text-right">Credit</th></tr></thead>
        <tbody>{j.lines.map(l => (
          <tr key={l.line_no}><td>{l.account_code} · {l.account_name}</td><td className="text-sm">{l.description}</td><td className="text-sm">{l.contact_name}</td>
            <td className="text-sm">{l.tax_code || '—'}{Number(l.tax_amount) ? ` (${aud(l.tax_amount)})` : ''}</td><td className="text-sm">{(l.tracking || []).join(', ')}</td>
            <td className="text-right mono">{Number(l.debit) ? aud(l.debit) : ''}{j.currency && l.orig_debit != null && Number(l.orig_debit) ? <div className="text-xs text-muted">{money(l.orig_debit, j.currency)}</div> : null}</td>
            <td className="text-right mono">{Number(l.credit) ? aud(l.credit) : ''}{j.currency && l.orig_credit != null && Number(l.orig_credit) ? <div className="text-xs text-muted">{money(l.orig_credit, j.currency)}</div> : null}</td></tr>))}</tbody>
      </table></div>
      <div className="mt-4" style={{ fontSize: '.82rem' }}>
        <b>Attachments</b>{' '}
        {(j.attachments || []).length ? j.attachments.map(a => <button key={a.id} className="btn btn-ghost btn-xs" onClick={() => books__0.downloadAttachment(a.id, a.filename)}><Paperclip size={11} /> {a.filename}</button>) : <span className="text-muted">none</span>}
        <button className="btn btn-ghost btn-xs" onClick={() => fileRef.current?.click()}><Plus size={11} /> Add</button><input ref={fileRef} type="file" multiple hidden onChange={attach} />
      </div>
      <div className="flex items-center gap-1 mt-4" style={{ flexWrap: 'wrap' }}>
        <button className="btn btn-outline btn-sm" onClick={onCopy}><Copy size={13} /> Copy to new journal</button>
        {j.status === 'posted' && !j.reversal_of_id && !j.reversed_by_id && !j.reversal && <>
          <label className="text-sm" style={{ marginLeft: 8 }}>Reverse on <input type="date" aria-label="Reversal date" className="input input-sm" value={revDate} onChange={e => setRevDate(e.target.value)} /></label>
          <button className="btn btn-outline btn-sm" onClick={reverse}><RotateCcw size={13} /> Reverse journal</button></>}
        <button className="btn btn-ghost btn-sm" onClick={() => (hist ? setHist(null) : api__0.journalHistory(j.id).then(r => setHist(r.data.events)).catch(e => toast.error(api__1.errMsg(e))))}>{hist ? 'Hide history' : 'History & notes'}</button>
      </div>
      {j.status === 'reversed' && <div className="alert alert-warning mt-4">This journal has been reversed.</div>}
      {hist && <ul className="mt-4" style={{ fontSize: '.8rem', paddingLeft: 18 }} data-testid="history">{hist.map((e, i) => <li key={i}><b>{e.action}</b>{e.who ? ` — ${e.who}` : ''}{e.at ? <span className="text-muted"> · {new Date(e.at).toLocaleString('en-AU')}</span> : null}{e.detail ? <span className="text-muted"> · {e.detail}</span> : null}</li>)}</ul>}
    </Modal>
  )
}

// ── Review queue ─────────────────────────────────────────────────────────────
const confColor = c => (c >= 0.95 ? '#16a34a' : c >= 0.85 ? '#d97706' : '#dc2626')
export function ConfidenceBar({ value }) {
  const c = Number(value || 0)
  return (
    <div title={`${(c * 100).toFixed(0)}% confidence`} style={{ minWidth: 92 }}>
      <div style={{ height: 6, background: 'var(--surface-2)', borderRadius: 3, overflow: 'hidden' }}><div style={{ width: `${c * 100}%`, height: '100%', background: confColor(c) }} /></div>
      <div style={{ fontSize: '.7rem', fontWeight: 700, color: confColor(c) }}>{(c * 100).toFixed(0)}%</div>
    </div>)
}
export const sourceBadge = d => {
  const t = d.suggestion?.type; const src = String(d.suggestion?.source || '')
  const [label, cls, tip] = t === 'match' ? ['Match', 'badge-success', 'Matches an open invoice or bill']
    : src === 'llm' ? ['AI', 'badge-warning', 'Suggested by the AI model - needs your judgement (max 80%)']
    : src === 'rdr' ? ['Platform rule', 'badge-info', 'From AccFino\'s shared rule set (85%)']
    : src === 'learned' ? ['Learned', 'badge-neutral', 'From your own earlier codings']
    : ['Your rule', 'badge-neutral', 'From one of your bank rules']
  return <span className={`badge ${cls}`} title={tip} style={{ marginBottom: 2 }}>{label}</span>
}
const shorthand = lines => lines.map(l => `${Number(l.debit) ? 'Dr' : 'Cr'} ${l.account_code} ${aud(Number(l.debit) || Number(l.credit))}`).join(' · ')

export function ReviewTab({ canApprove, requireApproval, onChanged, onSettings, llmEnabled, onLlm, assistEnabled }) {
  const [aiRev, setAiRev] = useState(null)
  const lk = useLookups()
  const [data, setData] = useState({ items: [], counts: {} })
  const [busy, setBusy] = useState(false)
  const [thr, setThr] = useState('0.95')
  const [adjust, setAdjust] = useState(null)
  const [detail, setDetail] = useState(null)
  const [editor, setEditor] = useState(null)
  const load = () => api__0.journalDrafts().then(r => setData(r.data)).catch(e => toast.error(api__1.errMsg(e)))
  useEffect(() => { load() }, [])
  const done = () => { load(); onChanged?.() }
  const guard = async fn => { setBusy(true); try { await fn() } catch (e) { toast.error(api__1.errMsg(e)) } finally { setBusy(false) } }
  const ai = data.items.filter(d => d.kind === 'ai_bank' && d.status === 'submitted')
  const awaiting = data.items.filter(d => d.kind !== 'ai_bank' && d.status === 'submitted')
  const mine = data.items.filter(d => d.kind !== 'ai_bank' && (d.status === 'draft' || d.status === 'rejected'))
  const eligible = ai.filter(d => Number(d.confidence) >= Number(thr))
  const find = () => guard(async () => { const { data: r } = await api__0.generateSuggestions(); toast.success(r.created ? `${r.created} new suggestion(s) — ${r.matches} matches, ${r.coded} coded${r.rdr ? ` (${r.rdr} from platform rules` : ''}${r.llm ? `${r.rdr ? ', ' : ' ('}${r.llm} by AI` : ''}${(r.rdr || r.llm) ? ')' : ''}` : 'No new suggestions (nothing else has enough evidence)')
    if (r.llm_unavailable) toast.error(`AI unavailable: ${r.llm_unavailable}`)
    done() })
  const askReview = d => guard(async () => { setAiRev({ id: d.id, loading: true }); try { const { data: r } = await api__0.aiReviewDraft(d.id); setAiRev({ id: d.id, ...r }) } catch (e) { setAiRev(null); throw e } })
  const approve = d => guard(async () => { await api__0.approveDraft(d.id); toast.success(d.kind === 'ai_bank' ? 'Approved and reconciled' : 'Journal posted'); setDetail(null); done() })
  const reject = d => { const reason = window.prompt('Reason for rejecting (the preparer will see this):'); if (reason) guard(async () => { await api__0.rejectDraft(d.id, reason); setDetail(null); done() }) }
  const submit = d => guard(async () => { await api__0.submitDraft(d.id); toast.success('Submitted for approval'); done() })
  const remove = d => { if (window.confirm('Delete this draft?')) guard(async () => { await api__0.deleteDraft(d.id); setDetail(null); done() }) }
  const bulk = () => guard(async () => {
    if (!window.confirm(`Approve ${eligible.length} suggestion(s) at ${(Number(thr) * 100).toFixed(0)}% confidence or higher? Each will post a journal and reconcile its bank line.`)) return
    const { data: r } = await api__0.bulkApprove(thr); toast.success(`${r.approved} approved${r.failed.length ? `, ${r.failed.length} failed` : ''}`); if (r.failed.length) toast.error(r.failed[0].error); done()
  })
  const saveAdjust = () => guard(async () => { await api__0.updateDraft(adjust.id, { account_id: Number(adjust.account_id), tax_code_id: adjust.tax_code_id ? Number(adjust.tax_code_id) : null }); setAdjust(null); done() })
  const edit = async d => { const { data: full } = await api__0.journalDraft(d.id); setEditor({ draftId: d.id, initial: full }) }
  return (
    <div>
      <div className="flex items-center gap-4" style={{ flexWrap: 'wrap', marginBottom: 12 }}>
        <button className="btn btn-primary btn-sm" onClick={find} disabled={busy}><Sparkles size={14} /> Find suggestions from bank lines</button>
        {canApprove && <label className="text-sm"><input type="checkbox" checked={!!requireApproval} onChange={e => onSettings?.(e.target.checked)} /> Require approval for manual journals</label>}
        {canApprove && <label className="text-sm" title="Sends bank descriptions (long numbers and emails masked) to Groq"><input type="checkbox" checked={!!llmEnabled} onChange={e => {
          if (e.target.checked && !window.confirm('Turn on AI suggestions?\n\nFor bank lines with no rule, the description (long numbers and email addresses masked) and your list of accounts are sent to Groq to suggest an account. Suggestions are never posted without your approval and never bulk-approved.')) return
          onLlm?.(e.target.checked) }} /> Use AI for lines with no rule</label>}
        <div className="flex-1" /><button className="btn btn-outline btn-sm" onClick={() => setEditor({})}><Plus size={14} /> New draft</button>
      </div>

      <h4 style={{ margin: '4px 0 6px' }}>AI &amp; rule suggestions <span className="text-muted" style={{ fontWeight: 400 }}>({ai.length})</span></h4>
      <p className="text-xs text-muted" style={{ marginTop: 0 }}>Suggested from unreconciled bank lines using open invoices/bills, your bank rules and what you have taught AccFino. Nothing posts until you approve — and approving teaches AccFino for next time.</p>
      {canApprove && ai.length > 0 && (
        <div className="flex items-center gap-4" style={{ marginBottom: 8 }}>
          <label className="text-sm">Approve everything at or above <select aria-label="Confidence threshold" className="input input-sm" value={thr} onChange={e => setThr(e.target.value)}>{['0.90', '0.95', '0.99'].map(v => <option key={v} value={v}>{(Number(v) * 100).toFixed(0)}%</option>)}</select></label>
          <button className="btn btn-outline btn-sm" disabled={!eligible.length || busy} onClick={bulk}><Check size={13} /> Approve {eligible.length}</button>
        </div>)}
      <div className="data-table-wrap"><table className="data-table">
        <thead><tr><th>Bank line</th><th>Suggested</th><th>Why</th><th>Confidence</th><th /></tr></thead>
        <tbody>
          {ai.map(d => (
            <tr key={d.id}>
              <td className="text-sm"><div className="mono">{d.suggestion?.bank_line?.date}</div><div className="truncate" style={{ maxWidth: 240 }} title={d.suggestion?.bank_line?.description}>{d.suggestion?.bank_line?.description}</div><b className="mono">{aud(d.suggestion?.bank_line?.amount)}</b></td>
              <td className="text-sm">{d.suggestion?.type === 'match' ? <><b>Match to {d.suggestion.match || 'a document'}</b><div className="text-muted">{shorthand(d.lines)}</div></> : <>
                {adjust?.id === d.id ? (
                  <div className="flex gap-1" style={{ flexWrap: 'wrap' }}>
                    <select aria-label="Account" className="input input-sm" value={adjust.account_id} onChange={e => setAdjust(a => ({ ...a, account_id: e.target.value }))}>{lk.accounts.map(a => <option key={a.id} value={a.id}>{a.code} · {a.name}</option>)}</select>
                    <select aria-label="Tax code" className="input input-sm" value={adjust.tax_code_id} onChange={e => setAdjust(a => ({ ...a, tax_code_id: e.target.value }))}><option value="">—</option>{lk.taxes.map(t => <option key={t.id} value={t.id}>{t.name}</option>)}</select>
                    <button className="btn btn-primary btn-xs" onClick={saveAdjust}>Save</button><button className="btn btn-ghost btn-xs" onClick={() => setAdjust(null)}>Cancel</button>
                  </div>) : <div>{shorthand(d.lines)}</div>}</>}</td>
              <td className="text-xs text-muted" style={{ maxWidth: 260 }}>{sourceBadge(d)}<div>{d.reason}</div></td>
              <td><ConfidenceBar value={d.confidence} /></td>
              <td className="text-right" style={{ whiteSpace: 'nowrap' }}>
                {canApprove && <button className="btn btn-primary btn-xs" disabled={busy} onClick={() => approve(d)}><Check size={12} /> Approve</button>}{' '}
                {canApprove && d.suggestion?.type === 'coding' && <button className="btn btn-ghost btn-xs" onClick={() => setAdjust({ id: d.id, account_id: String(d.suggestion.account_id || ''), tax_code_id: d.suggestion.tax_code_id ? String(d.suggestion.tax_code_id) : '' })}>Adjust</button>}{' '}
                {canApprove && <button className="btn btn-ghost btn-xs" disabled={busy} onClick={() => reject(d)}><X size={12} /> Reject</button>}
              </td>
            </tr>))}
          {!ai.length && <tr><td colSpan={5} className="text-center text-muted">No suggestions waiting. Press “Find suggestions” after importing bank lines.</td></tr>}
        </tbody>
      </table></div>

      <h4 style={{ margin: '20px 0 6px' }}>Awaiting approval <span className="text-muted" style={{ fontWeight: 400 }}>({awaiting.length})</span></h4>
      <DraftTable rows={awaiting} onOpen={setDetail} empty="Nothing is waiting for approval." showBy />
      <h4 style={{ margin: '20px 0 6px' }}>Drafts &amp; rejected <span className="text-muted" style={{ fontWeight: 400 }}>({mine.length})</span></h4>
      <DraftTable rows={mine} onOpen={setDetail} empty="No drafts. Use “New draft”, import a file, or run your repeating journals." showBy />

      {detail && (
        <Modal title={`${detail.kind === 'repeating' ? 'Repeating' : detail.kind === 'import' ? 'Imported' : 'Manual'} journal draft #${detail.id}`} onClose={() => setDetail(null)} width={860}>
          <p className="text-sm"><b>{detail.narration}</b> · {detail.date}{detail.reference ? ` · Ref ${detail.reference}` : ''}<span className={`badge ${detail.status === 'rejected' ? 'badge-warning' : 'badge-neutral'}`} style={{ marginLeft: 8 }}>{detail.status}</span></p>
          <p className="text-xs text-muted" style={{ marginTop: 0 }}>Prepared by {detail.created_by}{detail.auto_reverse_date ? ` · auto-reverses ${detail.auto_reverse_date}` : ''}{detail.amounts_are !== 'no_tax' ? ` · amounts ${detail.amounts_are === 'inclusive' ? 'include' : 'exclude'} GST` : ''}</p>
          {detail.rejected_reason && <div className="alert alert-warning">Rejected: {detail.rejected_reason}</div>}
          <div className="data-table-wrap"><table className="data-table"><thead><tr><th>Account</th><th>Description</th><th className="text-right">Debit</th><th className="text-right">Credit</th></tr></thead>
            <tbody>{detail.lines.map((l, i) => <tr key={i}><td>{l.account_code} · {l.account_name}</td><td className="text-sm">{l.description}</td><td className="text-right mono">{Number(l.debit) ? aud(l.debit) : ''}</td><td className="text-right mono">{Number(l.credit) ? aud(l.credit) : ''}</td></tr>)}</tbody></table></div>
          {aiRev && aiRev.id === detail.id && !aiRev.loading && (
            <div className={`alert ${aiRev.verdict === 'ok' ? 'alert-success' : 'alert-warning'}`} data-testid="ai-review" style={{ marginTop: 10 }}>
              <b>AI review: {aiRev.verdict === 'ok' ? 'nothing stands out' : aiRev.verdict === 'concern' ? 'worth a closer look' : 'check these points'}</b>{aiRev.summary ? ` — ${aiRev.summary}` : ''}
              {aiRev.points?.length > 0 && <ul style={{ margin: '6px 0 0 18px' }}>{aiRev.points.map((p, i) => <li key={i}>{p}</li>)}</ul>}
              {aiRev.checks?.length > 0 && <div className="text-xs" style={{ marginTop: 6 }}><b>Automatic checks:</b> {aiRev.checks.join(' · ')}</div>}
              <div className="text-xs text-muted" style={{ marginTop: 4 }}>{aiRev.advisory}</div>
            </div>)}
          <div className="flex gap-1 mt-4" style={{ flexWrap: 'wrap' }}>
            {canApprove && assistEnabled && detail.status === 'submitted' && <button className="btn btn-outline btn-sm" disabled={busy} onClick={() => askReview(detail)}><Sparkles size={12} /> AI review</button>}
            {canApprove && <button className="btn btn-primary btn-sm" disabled={busy} onClick={() => approve(detail)}>Approve &amp; post</button>}
            {canApprove && <button className="btn btn-outline btn-sm" disabled={busy} onClick={() => reject(detail)}>Reject</button>}
            {(detail.status === 'draft' || detail.status === 'rejected') && <><button className="btn btn-outline btn-sm" onClick={() => { edit(detail); setDetail(null) }}>Edit</button>
              <button className="btn btn-outline btn-sm" disabled={busy} onClick={() => submit(detail)}>Submit for approval</button></>}
            <button className="btn btn-ghost btn-sm" disabled={busy} onClick={() => remove(detail)}>Delete</button>
          </div>
        </Modal>)}
      {editor && <JournalEditor {...lk} initial={editor.initial} draftId={editor.draftId} canApprove={canApprove} requireApproval={requireApproval} onClose={() => setEditor(null)} onDone={() => { setEditor(null); done() }} />}
    </div>
  )
}

function DraftTable({ rows, onOpen, empty, showBy }) {
  return (
    <div className="data-table-wrap"><table className="data-table">
      <thead><tr><th>Date</th><th>Narration</th><th>Reference</th><th>Kind</th>{showBy && <th>Prepared by</th>}<th>Status</th><th className="text-right">Total</th><th /></tr></thead>
      <tbody>
        {rows.map(d => (
          <tr key={d.id}><td>{d.date}</td><td className="truncate" style={{ maxWidth: 300 }}>{d.narration}</td><td className="mono text-sm">{d.reference || ''}</td><td className="text-sm">{d.kind}</td>{showBy && <td className="text-sm">{d.created_by}</td>}
            <td><span className={`badge ${d.status === 'rejected' ? 'badge-warning' : d.status === 'submitted' ? 'badge-info' : 'badge-neutral'}`}>{d.status}</span></td><td className="text-right mono">{aud(d.total)}</td>
            <td className="text-right"><button className="btn btn-ghost btn-xs" onClick={() => onOpen(d)}><Eye size={12} /> Open</button></td></tr>))}
        {!rows.length && <tr><td colSpan={showBy ? 8 : 7} className="text-center text-muted">{empty}</td></tr>}
      </tbody>
    </table></div>)
}

// ── Repeating journals ───────────────────────────────────────────────────────
export function RepeatingTab({ canApprove, onChanged }) {
  const lk = useLookups()
  const [items, setItems] = useState([])
  const [editor, setEditor] = useState(null)
  const [sched, setSched] = useState(null)
  const load = () => { api__0.repeatingJournals().then(r => setItems(r.data.items || [])).catch(e => toast.error(api__1.errMsg(e))); api__0.schedulerStatus().then(r => setSched(r.data)).catch(() => {}) }
  useEffect(() => { load() }, [])
  const run = async () => {
    try {
      const { data: r } = await api__0.runRepeating(today())
      toast.success(r.templates ? `${r.drafts} draft(s) created, ${r.posted} posted` : 'Nothing is due yet'); if (r.errors.length) toast.error(`${r.errors[0].name}: ${r.errors[0].error}`)
      load(); onChanged?.()
    } catch (e) { toast.error(api__1.errMsg(e)) }
  }
  const del = async r => { if (window.confirm(`Delete “${r.name}”? Journals already created from it are not affected.`)) { try { await api__0.deleteRepeating(r.id); load(); onChanged?.() } catch (e) { toast.error(api__1.errMsg(e)) } } }
  const due = items.filter(r => r.is_active && r.next_date <= today()).length
  return (
    <div>
      <div className="flex items-center gap-4" style={{ marginBottom: 12 }}>
        <button className="btn btn-primary btn-sm" onClick={run}><Play size={14} /> Run due now{due ? ` (${due})` : ''}</button>
        <span className="text-xs text-muted">Templates not marked “auto” do nothing until they are run. Each occurrence becomes a draft for review, or posts automatically if you chose that (approvers only).</span>
        <div className="flex-1" /><button className="btn btn-outline btn-sm" onClick={() => setEditor({})}><Plus size={14} /> New repeating journal</button>
      </div>
      {sched && <div className="text-xs text-muted" style={{ marginBottom: 8 }} data-testid="scheduler-status">
        {sched.enabled ? <>Automatic runs are <b>on</b> — checked every {Math.round(sched.interval_seconds / 60)} min ({sched.timezone}); {sched.auto_templates} template(s) opted in.{' '}
          {sched.last_sweep ? `Last check ${new Date(sched.last_sweep.at).toLocaleString('en-AU')}: ${sched.last_sweep.drafts} draft(s), ${sched.last_sweep.posted} posted${sched.last_sweep.errors?.length ? `, ${sched.last_sweep.errors.length} error(s)` : ''}.` : 'No check has run yet.'}</>
          : <>Automatic runs are <b>off</b> on this server (ACCFINO_SCHEDULER=0). Use “Run due now”.</>}</div>}
      <div className="data-table-wrap"><table className="data-table">
        <thead><tr><th>Name</th><th>Repeats</th><th>Next</th><th>Next narration</th><th>Each time</th><th>Last run</th><th /></tr></thead>
        <tbody>
          {items.map(r => (
            <tr key={r.id}><td><b>{r.name}</b>{r.auto_run && <span className="badge badge-info" style={{ marginLeft: 6 }} title="Runs by itself when due">auto</span>}{r.currency && <span className="badge badge-neutral" style={{ marginLeft: 6 }}>{r.currency}</span>}{!r.is_active && <span className="badge badge-neutral" style={{ marginLeft: 6 }}>paused</span>}{r.last_error && <div className="text-xs" style={{ color: 'var(--danger)' }}>{r.last_error}</div>}</td>
              <td className="text-sm">{r.frequency}{r.reverse_after_days ? ` · reverses after ${r.reverse_after_days}d` : ''}</td>
              <td className="text-sm">{r.next_date}{r.is_active && r.next_date <= today() && <span className="badge badge-warning" style={{ marginLeft: 6 }}>due</span>}</td>
              <td className="text-sm truncate" style={{ maxWidth: 260 }}>{r.next_narration}</td><td className="text-sm">{r.mode === 'post' ? 'posts automatically' : 'creates a draft'}</td>
              <td className="text-sm">{r.last_run_date ? `${r.last_run_date} (${r.runs}×)` : 'never'}</td>
              <td className="text-right" style={{ whiteSpace: 'nowrap' }}><button className="btn btn-ghost btn-xs" onClick={() => setEditor({ initial: r })}>Edit</button><button className="btn btn-ghost btn-xs" onClick={() => del(r)}>Delete</button></td></tr>))}
          {!items.length && <tr><td colSpan={7} className="text-center text-muted">No repeating journals yet — e.g. monthly prepayment releases, accrual and reversal, depreciation adjustments.</td></tr>}
        </tbody>
      </table></div>
      {editor && <RepeatingEditor {...lk} initial={editor.initial} canApprove={canApprove} onClose={() => setEditor(null)} onDone={() => { setEditor(null); load(); onChanged?.() }} />}
    </div>
  )
}

// ── CSV import ───────────────────────────────────────────────────────────────
export function ImportModal({ canApprove, onClose, onDone }) {
  const [text, setText] = useState('')
  const [name, setName] = useState('')
  const [mode, setMode] = useState('draft')
  const [amountsAre, setAmountsAre] = useState('no_tax')
  const [res, setRes] = useState(null)
  const [busy, setBusy] = useState(false)
  const read = f => { if (!f) return; setName(f.name); setRes(null); const r = new FileReader(); r.onload = () => setText(String(r.result || '')); r.readAsText(f) }
  const call = async dry => {
    setBusy(true)
    try { const { data } = await api__0.importJournals({ csv: text, mode, amounts_are: amountsAre, dry_run: dry }); setRes(data)
      if (!dry) { if (data.error) toast.error(data.error); else { toast.success(mode === 'post' ? `${data.posted} journal(s) posted` : `${data.saved} draft(s) saved for review`); onDone() } }
    } catch (e) { toast.error(api__1.errMsg(e)); setRes(null) } finally { setBusy(false) }
  }
  return (
    <Modal title="Import journals from CSV" onClose={onClose} width={900}>
      <p className="text-sm" style={{ marginTop: 0 }}>Columns: <b>Date, Narration, Reference, Account</b> (code or name)<b>, Description, Debit, Credit</b> (or a signed Amount)<b>, Tax Code, Contact, Tracking</b>. Rows with a blank date and narration continue the previous journal. Up to 2,000 lines.
        {' '}<button className="btn btn-ghost btn-xs" onClick={() => api__0.downloadImportTemplate().catch(e => toast.error(api__1.errMsg(e)))}>Download template</button></p>
      <div className="flex items-center gap-4" style={{ flexWrap: 'wrap' }}>
        <input aria-label="CSV file" type="file" accept=".csv,text/csv" onChange={e => read(e.target.files?.[0])} />{name && <span className="text-xs text-muted">{name}</span>}
        <label className="text-sm">Import as <select aria-label="Import as" className="input input-sm" value={mode} onChange={e => { setMode(e.target.value); setRes(null) }}><option value="draft">Drafts for review</option>{canApprove && <option value="post">Posted journals</option>}</select></label>
        <label className="text-sm">GST <select aria-label="GST" className="input input-sm" value={amountsAre} onChange={e => { setAmountsAre(e.target.value); setRes(null) }}><option value="no_tax">No GST calculation</option><option value="inclusive">Amounts include GST</option><option value="exclusive">Amounts exclude GST</option></select></label>
      </div>
      <textarea aria-label="CSV text" className="input mt-4" rows={4} style={{ width: '100%', fontFamily: 'var(--font-mono)', fontSize: '.75rem' }} placeholder="…or paste CSV here" value={text} onChange={e => { setText(e.target.value); setRes(null) }} />
      <div className="flex gap-1 mt-4"><button className="btn btn-outline" disabled={!text.trim() || busy} onClick={() => call(true)}>{busy ? 'Checking…' : 'Check file'}</button>
        <button className="btn btn-primary" disabled={!res || res.invalid > 0 || busy} onClick={() => call(false)}>{res ? `Import ${res.valid} journal(s)` : 'Import'}</button></div>
      {res && (
        <div className="mt-4" data-testid="import-result">
          <div className={`alert ${res.invalid ? 'alert-error' : 'alert-success'}`}>{res.invalid ? `${res.invalid} of ${res.count} journal(s) have problems — nothing will be imported until they are fixed.` : `All ${res.count} journal(s) are valid.`}</div>
          <div className="data-table-wrap"><table className="data-table" style={{ fontSize: '.78rem' }}>
            <thead><tr><th>Row</th><th>Date</th><th>Narration</th><th>Ref</th><th className="text-right">Lines</th><th className="text-right">Total</th><th>Result</th></tr></thead>
            <tbody>{res.journals.map(j => (
              <tr key={j.row}><td>{j.row}</td><td>{j.date}</td><td>{j.narration}</td><td>{j.reference}</td><td className="text-right">{j.lines}</td><td className="text-right mono">{aud(j.total)}</td>
                <td>{j.errors.length ? j.errors.map((e, i) => <div key={i} style={{ color: 'var(--danger)' }}>{e}</div>) : <span className="badge badge-success">ok</span>}{j.warnings.map((w, i) => <div key={i} className="text-muted">{w}</div>)}</td></tr>))}</tbody>
          </table></div>
        </div>)}
    </Modal>
  )
}
