/**
 * JournalEditor - create / edit a manual journal, a draft, or a repeating-journal template.
 *   - GST handling per journal (none / inclusive / exclusive) with a LIVE preview of exactly what will post (the GST line is added for you)
 *   - reference, narration, per-line description / contact / tax code / tracking (one select per tracking category), attachments
 *   - optional auto-reversing date (accruals)
 *   - three ways out: Post now (if allowed), Save draft, Submit for approval
 * The server is the source of truth for every rule; this screen only mirrors the balance check so the user sees problems as they type.
 */
import React, { useEffect, useMemo, useRef, useState } from 'react'
import toast from 'react-hot-toast'
import { Plus, Paperclip } from 'lucide-react'
import * as api from '../../lib/platformApi.js'
import * as books from '../../lib/booksApi.js'

export const aud = v => Number(v || 0).toLocaleString('en-AU', { style: 'currency', currency: 'AUD' })
export const money = (v, cur) => Number(v || 0).toLocaleString('en-AU', { style: 'currency', currency: cur || 'AUD' })
export const iso = d => d.toISOString().slice(0, 10)
export const today = () => iso(new Date())
const cents = v => Math.round(Number(v || 0) * 100)

export function Modal({ title, onClose, children, width = 560 }) {
  return (
    <div className="modal-overlay" onClick={onClose}>
      <div className="modal" onClick={e => e.stopPropagation()} style={{ maxWidth: width, width: '95%', maxHeight: '92vh', overflow: 'auto' }}>
        <div className="modal-header"><h3 style={{ margin: 0 }}>{title}</h3><button className="btn btn-ghost btn-xs" onClick={onClose} aria-label="Close">✕</button></div>
        <div style={{ padding: 18 }}>{children}</div>
      </div>
    </div>
  )
}

export const blankLine = () => ({ account_id: '', description: '', contact_name: '', debit: '', credit: '', tax_code_id: '', track: {}, split: null })

export function toPayloadLines(lines) {
  return lines.filter(l => l.account_id && (Number(l.debit) || Number(l.credit))).map(l => ({
    account_id: Number(l.account_id), description: l.description || null, contact_name: l.contact_name || null,
    debit: l.debit || '0', credit: l.credit || '0', tax_code_id: l.tax_code_id ? Number(l.tax_code_id) : null,
    tracking_option_ids: Object.values(l.track || {}).filter(Boolean).map(Number),
    // a part with a share but no job is a legitimate "unassigned" part: keep it, or the shares would no longer add up
    ...(l.split && l.split.rows.some(r => Number(r.value)) ? { allocations: l.split.rows.filter(r => r.option || Number(r.value)).map(r => ({ tracking_option_ids: r.option ? [Number(r.option)] : [], [l.split.mode]: r.value || '0' })) } : {}),
  }))
}
export function fromApiLines(lines, categories) {
  const out = (lines || []).map(l => {
    const track = {}
    for (const c of categories) { const hit = (c.options || []).find(o => (l.tracking_option_ids || []).includes(o.id)); if (hit) track[c.id] = String(hit.id) }
    return { account_id: l.account_id ? String(l.account_id) : '', description: l.description || '', contact_name: l.contact_name || '',
      debit: Number(l.debit) ? String(l.debit) : '', credit: Number(l.credit) ? String(l.credit) : '', tax_code_id: l.tax_code_id ? String(l.tax_code_id) : '', track,
      split: l.allocations?.length ? { mode: l.allocations[0].amount != null && l.allocations[0].percent == null ? 'amount' : 'percent',
        rows: l.allocations.map(a => ({ option: String((a.tracking_option_ids || [])[0] || ''), value: String(a.percent ?? a.amount ?? '') })) } : null }
  })
  while (out.length < 2) out.push(blankLine())
  return out
}

function SplitEditor({ line, onChange, options, amount }) {
  const sp = line.split
  const total = sp.rows.reduce((t, r) => t + Number(r.value || 0), 0)
  const target = sp.mode === 'percent' ? 100 : Number(amount || 0)
  const ok = Math.abs(total - target) < 0.005
  const setRow = (i, k, v) => onChange({ ...sp, rows: sp.rows.map((r, j) => (j === i ? { ...r, [k]: v } : r)) })
  return (
    <div data-testid="split" style={{ fontSize: '.75rem', marginTop: 4, padding: 6, border: '1px dashed var(--border)', borderRadius: 6 }}>
      <div className="flex items-center gap-1" style={{ marginBottom: 4 }}>
        <b>Split across</b>
        <select aria-label="Split by" className="input input-sm" value={sp.mode} onChange={e => onChange({ ...sp, mode: e.target.value, rows: sp.rows.map(r => ({ ...r, value: '' })) })}><option value="percent">percent</option><option value="amount">amount</option></select>
        <button className="btn btn-ghost btn-xs" onClick={() => onChange(null)}>Remove split</button>
      </div>
      {sp.rows.map((r, i) => (
        <div key={i} className="flex gap-1" style={{ marginBottom: 2 }}>
          <select aria-label={`Split job ${i + 1}`} className="input input-sm" value={r.option} onChange={e => setRow(i, 'option', e.target.value)}><option value="">Unassigned</option>{options.map(o => <option key={o.id} value={o.id}>{o.label}</option>)}</select>
          <input aria-label={`Split value ${i + 1}`} className="input input-sm text-right" style={{ width: 70 }} inputMode="decimal" value={r.value} onChange={e => setRow(i, 'value', e.target.value)} placeholder={sp.mode === 'percent' ? '%' : '$'} />
          {sp.rows.length > 2 && <button className="btn btn-ghost btn-xs" aria-label={`Remove part ${i + 1}`} onClick={() => onChange({ ...sp, rows: sp.rows.filter((_, j) => j !== i) })}>✕</button>}
        </div>))}
      <button className="btn btn-ghost btn-xs" onClick={() => onChange({ ...sp, rows: [...sp.rows, { option: '', value: '' }] })}>+ part</button>
      <span style={{ marginLeft: 8, color: ok ? 'var(--success, #16a34a)' : 'var(--danger, #dc2626)', fontWeight: 600 }}>{sp.mode === 'percent' ? `${total}% of 100%` : `${total} of ${target}`}{ok ? ' ✓' : ''}</span>
    </div>)
}

export function LinesEditor({ lines, setLines, accounts, taxes, categories }) {
  const allOptions = categories.flatMap(c => (c.options || []).filter(o => o.is_active !== false).map(o => ({ id: o.id, label: `${c.name}: ${o.name}` })))
  const setSplit = (i, sp) => setLines(ls => ls.map((l, j) => (j === i ? { ...l, split: sp } : l)))
  const set = (i, k, v) => setLines(ls => ls.map((l, j) => j === i ? { ...l, [k]: v, ...(k === 'debit' && v ? { credit: '' } : {}), ...(k === 'credit' && v ? { debit: '' } : {}) } : l))
  const setTrack = (i, cid, v) => setLines(ls => ls.map((l, j) => j === i ? { ...l, track: { ...l.track, [cid]: v } } : l))
  return (
    <div className="data-table-wrap mt-4">
      <table className="data-table">
        <thead><tr><th style={{ width: '24%' }}>Account</th><th>Description</th><th>Contact</th><th>Tax code</th>{categories.length > 0 && <th>Tracking</th>}<th className="text-right">Debit</th><th className="text-right">Credit</th><th /></tr></thead>
        <tbody>
          {lines.map((l, i) => (
            <tr key={i}>
              <td><select aria-label={`Account ${i + 1}`} className="input input-sm" value={l.account_id} onChange={e => set(i, 'account_id', e.target.value)}><option value="">Select…</option>
                {accounts.map(a => <option key={a.id} value={a.id}>{a.code} · {a.name}</option>)}</select></td>
              <td><input aria-label={`Description ${i + 1}`} className="input input-sm" value={l.description} onChange={e => set(i, 'description', e.target.value)} /></td>
              <td><input aria-label={`Contact ${i + 1}`} className="input input-sm" value={l.contact_name} onChange={e => set(i, 'contact_name', e.target.value)} style={{ minWidth: 90 }} /></td>
              <td><select aria-label={`Tax code ${i + 1}`} className="input input-sm" value={l.tax_code_id} onChange={e => set(i, 'tax_code_id', e.target.value)}><option value="">—</option>{taxes.map(t => <option key={t.id} value={t.id}>{t.name}</option>)}</select></td>
              {categories.length > 0 && <td>{categories.filter(c => c.is_active !== false).map(c => (
                <select key={c.id} aria-label={`${c.name} ${i + 1}`} className="input input-sm" style={{ marginBottom: 2 }} value={l.track?.[c.id] || ''} onChange={e => setTrack(i, c.id, e.target.value)}>
                  <option value="">{c.name}…</option>{(c.options || []).filter(o => o.is_active !== false).map(o => <option key={o.id} value={o.id}>{o.name}</option>)}</select>))}
                {allOptions.length > 1 && !l.split && <button className="btn btn-ghost btn-xs" onClick={() => setSplit(i, { mode: 'percent', rows: [{ option: '', value: '' }, { option: '', value: '' }] })}>Split across jobs</button>}
                {l.split && <SplitEditor line={l} onChange={sp => setSplit(i, sp)} options={allOptions} amount={l.debit || l.credit} />}</td>}
              <td><input aria-label={`Debit ${i + 1}`} className="input input-sm text-right" inputMode="decimal" value={l.debit} onChange={e => set(i, 'debit', e.target.value)} /></td>
              <td><input aria-label={`Credit ${i + 1}`} className="input input-sm text-right" inputMode="decimal" value={l.credit} onChange={e => set(i, 'credit', e.target.value)} /></td>
              <td>{lines.length > 2 && <button className="btn btn-ghost btn-xs" onClick={() => setLines(ls => ls.filter((_, j) => j !== i))} aria-label={`Remove line ${i + 1}`}>✕</button>}</td>
            </tr>))}
          <tr><td colSpan={categories.length > 0 ? 8 : 7}><button className="btn btn-ghost btn-xs" onClick={() => setLines(ls => [...ls, blankLine()])}><Plus size={12} /> Add line</button></td></tr>
        </tbody>
      </table>
    </div>
  )
}

// What will actually post (server-computed): includes the GST line for inclusive/exclusive journals
export function PreviewPanel({ pv, entered }) {
  const cur = pv?.fx?.currency
  if (!pv) return <div className="alert alert-info mt-4" style={{ fontSize: '.8rem' }}>{entered.dr === entered.cr && entered.dr > 0 ? 'Debits equal credits.' : `Debits ${aud(entered.dr / 100)} · credits ${aud(entered.cr / 100)}`}</div>
  const hasGst = pv.lines.some(l => l.is_gst)
  const showTable = hasGst || !!pv.fx || (entered.n != null && pv.lines.length > entered.n)
  return (
    <div className="mt-4" data-testid="preview">
      {pv.fx && <div className="alert alert-info" style={{ fontSize: '.8rem', marginBottom: 6 }} data-testid="fx-note">Entered in <b>{pv.fx.currency}</b> at 1 {pv.fx.currency} = {Number(pv.fx.rate)} {pv.fx.base} · {money(pv.fx.foreign_total, pv.fx.currency)} becomes {money(pv.total_debit)} in the ledger{Number(pv.fx.gst_base || 0) ? `, including ${money(pv.fx.gst_base)} GST` : ''}.</div>}
      {showTable && (
        <div className="data-table-wrap" style={{ marginBottom: 8 }}>
          <table className="data-table" style={{ fontSize: '.78rem' }}>
            <thead><tr><th>Will post</th><th>Description</th>{cur && <th className="text-right">{cur} entered</th>}<th className="text-right">Debit</th><th className="text-right">Credit</th></tr></thead>
            <tbody>{pv.lines.map((l, i) => (
              <tr key={i} style={l.is_gst ? { background: 'var(--surface-2)', fontWeight: 600 } : undefined}><td>{l.account_code} · {l.account_name}</td><td>{l.description}</td>
                {cur && <td className="text-right mono">{money(l.orig_debit ?? l.orig_credit, cur)}</td>}
                <td className="text-right mono">{Number(l.debit) ? aud(l.debit) : ''}</td><td className="text-right mono">{Number(l.credit) ? aud(l.credit) : ''}</td></tr>))}
              <tr className="fw-700"><td colSpan={cur ? 3 : 2}>Total{hasGst ? ` (GST ${aud(pv.gst_total)})` : ''}</td><td className="text-right mono">{aud(pv.total_debit)}</td><td className="text-right mono">{aud(pv.total_credit)}</td></tr></tbody>
          </table>
        </div>)}
      {pv.errors.map((e, i) => <div key={i} className="alert alert-error" style={{ fontSize: '.8rem', marginBottom: 4 }}>{e}</div>)}
      {pv.errors.length === 0 && pv.balanced && <div className="alert alert-success" style={{ fontSize: '.8rem', marginBottom: 4 }}>Journal balances{hasGst ? ` (includes ${aud(pv.gst_total)} GST)` : ''}.</div>}
      {pv.warnings.map((w, i) => <div key={i} className="alert alert-warning" style={{ fontSize: '.78rem', marginBottom: 4 }}>{w}</div>)}
    </div>
  )
}

const AMOUNTS = [['no_tax', 'No GST calculation'], ['inclusive', 'Amounts include GST'], ['exclusive', 'Amounts exclude GST (add GST)']]

function usePreview(payload, enabled) {
  const [pv, setPv] = useState(null)
  const key = JSON.stringify(payload)
  useEffect(() => {
    if (!enabled || payload.lines.length < 2) { setPv(null); return }
    const t = setTimeout(() => { api.journalPreview(payload).then(r => setPv(r.data)).catch(() => setPv(null)) }, 350)
    return () => clearTimeout(t)
  }, [key, enabled]) // eslint-disable-line react-hooks/exhaustive-deps
  return pv
}

const COMMON = ['USD', 'EUR', 'GBP', 'NZD', 'SGD', 'JPY', 'CNY', 'CAD', 'CHF', 'HKD', 'INR']
// Currency + rate for one journal. The rate is ALWAYS visible and editable; it is prefilled only from the organisation's OWN stored rates - never guessed.
export function useCurrency(initialCur, initialRate, date) {
  const [currency, setCurrency] = useState(initialCur || '')
  const [rate, setRate] = useState(initialRate ? String(Number(initialRate)) : '')
  const touched = useRef(!!initialRate)          // a ref, not state: a lookup that returns AFTER the user typed must not overwrite what they typed
  const [base, setBase] = useState('AUD')
  const [known, setKnown] = useState([])
  const [note, setNote] = useState('')
  useEffect(() => { api.fxRates().then(r => { setBase(r.data.base || 'AUD'); setKnown([...new Set((r.data.items || []).map(x => x.currency))]) }).catch(() => {}) }, [])
  const cur = currency.trim().toUpperCase()
  const foreign = cur.length === 3 && cur !== base
  useEffect(() => {
    if (!foreign) { setNote(''); return }
    api.fxRate(cur, date).then(r => {
      if (r.data.rate) { setNote(`Your stored rate: 1 ${cur} = ${Number(r.data.rate)} ${base} (${r.data.rate_date}${r.data.source ? `, ${r.data.source}` : ''})`); if (!touched.current) setRate(String(Number(r.data.rate))) }
      else { setNote(`You have no stored ${cur} rate on or before this date - enter the rate you are using.`); if (!touched.current) setRate('') }
    }).catch(() => {})
  }, [cur, date, foreign]) // eslint-disable-line react-hooks/exhaustive-deps
  return { currency, setCurrency, rate, setRate: v => { touched.current = true; setRate(v) }, foreign, cur, base, known, note }
}

export function CurrencyFields({ fx }) {
  const list = [...new Set([...COMMON, ...fx.known])]
  return (
    <>
      <div><label className="text-sm fw-600" htmlFor="jc">Currency</label>
        <input id="jc" className="input" list="jc-list" value={fx.currency} onChange={e => fx.setCurrency(e.target.value.toUpperCase())} placeholder={`${fx.base} (base)`} maxLength={3} />
        <datalist id="jc-list">{list.filter(c => c !== fx.base).map(c => <option key={c} value={c} />)}</datalist></div>
      {fx.foreign
        ? <div><label className="text-sm fw-600" htmlFor="jx">Rate (1 {fx.cur} = ? {fx.base})</label><input id="jx" className="input" inputMode="decimal" value={fx.rate} onChange={e => fx.setRate(e.target.value)} />
          <div className="text-xs text-muted" data-testid="fx-rate-note">{fx.note}</div></div>
        : <div className="text-xs text-muted" style={{ alignSelf: 'end' }}>Leave blank for {fx.base}. For a foreign currency you enter the amounts in that currency; the ledger stores {fx.base} and keeps the original amounts.</div>}
    </>)
}

export function JournalEditor({ accounts, taxes, categories = [], initial, draftId, canApprove, requireApproval, onDone, onClose }) {
  const [date, setDate] = useState(initial?.date || today())
  const [narration, setNarration] = useState(initial?.narration || '')
  const [reference, setReference] = useState(initial?.reference || '')
  const [amountsAre, setAmountsAre] = useState(initial?.amounts_are || 'no_tax')
  const [reverse, setReverse] = useState(!!initial?.auto_reverse_date)
  const [reverseDate, setReverseDate] = useState(initial?.auto_reverse_date || '')
  const [lines, setLines] = useState(() => fromApiLines(initial?.lines, categories))
  const fx = useCurrency(initial?.currency, initial?.exchange_rate, date)
  const [files, setFiles] = useState([])
  const [busy, setBusy] = useState(false)
  const fileRef = useRef()
  const payload = useMemo(() => ({ date, narration, reference: reference || null, amounts_are: amountsAre, auto_reverse_date: reverse && reverseDate ? reverseDate : null, lines: toPayloadLines(lines),
    currency: fx.foreign ? fx.cur : null, exchange_rate: fx.foreign && fx.rate ? fx.rate : null }),
    [date, narration, reference, amountsAre, reverse, reverseDate, lines, fx.foreign, fx.cur, fx.rate])
  const pv = usePreview(payload, true)
  const entered = { dr: lines.reduce((s, l) => s + cents(l.debit), 0), cr: lines.reduce((s, l) => s + cents(l.credit), 0) }
  const canPostNow = canApprove || !requireApproval
  const blocked = busy || !narration.trim() || (pv ? pv.errors.length > 0 : !(entered.dr === entered.cr && entered.dr > 0)) || (fx.foreign && !fx.rate)

  const upload = async (kind, id) => {
    for (const f of files) { try { await books.uploadAttachment(kind, id, f) } catch (e) { toast.error(`${f.name}: ${books.errMsg(e)}`) } }
  }
  const run = async fn => { setBusy(true); try { await fn() } catch (e) { toast.error(api.errMsg(e)) } finally { setBusy(false) } }
  const draftBody = () => ({ ...payload })

  const post = () => run(async () => {
    if (draftId) {                                     // approver posting a saved draft
      await api.updateDraft(draftId, draftBody()); await upload('journal_draft', draftId)
      const { data } = await api.approveDraft(draftId); toast.success(`Journal ${data.posted_journal_id} posted`); onDone('posted'); return
    }
    const { data } = await api.postJournal(payload); await upload('journal', data.id)
    toast.success(`Journal ${data.journal_no} posted${data.auto_reversal ? ` · auto-reverses ${data.auto_reversal.date}` : ''}`); onDone('posted')
  })
  const save = submit => run(async () => {
    let id = draftId
    if (id) await api.updateDraft(id, draftBody()); else id = (await api.createDraft(draftBody())).data.id
    await upload('journal_draft', id)
    if (submit) await api.submitDraft(id)
    toast.success(submit ? 'Submitted for approval' : 'Draft saved'); onDone(submit ? 'submitted' : 'draft')
  })

  return (
    <Modal title={draftId ? `Edit draft #${draftId}` : 'New manual journal'} onClose={onClose} width={1000}>
      <div className="grid-2" style={{ gap: 12 }}>
        <div><label className="text-sm fw-600" htmlFor="jd">Date</label><input id="jd" type="date" className="input" value={date} onChange={e => setDate(e.target.value)} /></div>
        <div><label className="text-sm fw-600" htmlFor="jr">Reference</label><input id="jr" className="input" value={reference} onChange={e => setReference(e.target.value)} placeholder="e.g. workpaper / cheque no." maxLength={100} /></div>
        <div><label className="text-sm fw-600" htmlFor="jn">Narration</label><input id="jn" className="input" data-testid="jnl-narration" value={narration} onChange={e => setNarration(e.target.value)} placeholder="e.g. Accrue September audit fee" /></div>
        <div><label className="text-sm fw-600" htmlFor="ja">GST</label><select id="ja" className="input" value={amountsAre} onChange={e => setAmountsAre(e.target.value)}>{AMOUNTS.map(([k, l]) => <option key={k} value={k}>{l}</option>)}</select>
          {fx.foreign && amountsAre !== 'no_tax' && <div className="text-xs text-muted" data-testid="fx-gst-note">GST is worked out in {fx.base} on the converted amount, as your BAS needs.</div>}</div>
        <CurrencyFields fx={fx} />
      </div>
      <LinesEditor lines={lines} setLines={setLines} accounts={accounts} taxes={taxes} categories={categories} />
      <div className="flex items-center gap-4 mt-4" style={{ flexWrap: 'wrap' }}>
        <label className="text-sm"><input type="checkbox" checked={reverse} onChange={e => setReverse(e.target.checked)} /> Auto-reverse (accrual)</label>
        {reverse && <label className="text-sm">on <input aria-label="Auto-reverse date" type="date" className="input input-sm" value={reverseDate} onChange={e => setReverseDate(e.target.value)} /></label>}
        <button className="btn btn-ghost btn-xs" onClick={() => fileRef.current?.click()}><Paperclip size={12} /> Attach files{files.length ? ` (${files.length})` : ''}</button>
        <input ref={fileRef} type="file" multiple hidden onChange={e => setFiles(Array.from(e.target.files || []))} />
        {files.length > 0 && <span className="text-xs text-muted">{files.map(f => f.name).join(', ')}</span>}
      </div>
      <PreviewPanel pv={pv} entered={{ ...entered, n: payload.lines.length }} />
      <div className="flex gap-1 mt-4" style={{ flexWrap: 'wrap' }}>
        {canPostNow && <button className="btn btn-primary" disabled={blocked} onClick={post}>{busy ? 'Working…' : draftId ? 'Post now' : 'Post journal'}</button>}
        <button className={`btn ${canPostNow ? 'btn-outline' : 'btn-primary'}`} disabled={busy || !narration.trim()} onClick={() => save(false)}>Save draft</button>
        <button className="btn btn-outline" disabled={blocked} onClick={() => save(true)}>Submit for approval</button>
        <button className="btn btn-ghost" onClick={onClose}>Cancel</button>
      </div>
      {!canPostNow && <p className="text-xs text-muted mt-1">This organisation requires journals to be approved before they post. Save a draft or submit it for approval.</p>}
      <p className="text-xs text-muted mt-1">Posted journals can't be edited or deleted. To correct one, reverse it and post a new journal. Drafts have no effect on your reports until they are posted.</p>
    </Modal>
  )
}

const FREQS = [['weekly', 'Weekly'], ['fortnightly', 'Fortnightly'], ['monthly', 'Monthly'], ['quarterly', 'Quarterly'], ['yearly', 'Yearly']]
export function RepeatingEditor({ accounts, taxes, categories = [], initial, canApprove, onDone, onClose }) {
  const [f, setF] = useState({ name: initial?.name || '', frequency: initial?.frequency || 'monthly', next_date: initial?.next_date || today(), end_date: initial?.end_date || '', mode: initial?.mode || 'draft',
    narration: initial?.narration || '', reference: initial?.reference || '', amounts_are: initial?.amounts_are || 'no_tax', reverse_after_days: initial?.reverse_after_days || '', auto_run: !!initial?.auto_run })
  const [cur, setCur] = useState(initial?.currency || '')
  const [lines, setLines] = useState(() => fromApiLines(initial?.lines, categories))
  const [busy, setBusy] = useState(false)
  const set = (k, v) => setF(x => ({ ...x, [k]: v }))
  const foreign = cur.trim().length === 3
  const body = { ...f, amounts_are: f.amounts_are, currency: foreign ? cur.trim().toUpperCase() : null, end_date: f.end_date || null, reverse_after_days: f.reverse_after_days ? Number(f.reverse_after_days) : null, reference: f.reference || null, lines: toPayloadLines(lines) }
  const pv = usePreview({ date: f.next_date, amounts_are: body.amounts_are, lines: body.lines, currency: body.currency, exchange_rate: foreign ? '1' : null }, true)
  const save = async () => {
    setBusy(true)
    try { if (initial?.id) await api.updateRepeating(initial.id, body); else await api.createRepeating(body); toast.success('Repeating journal saved'); onDone() }
    catch (e) { toast.error(api.errMsg(e)) } finally { setBusy(false) }
  }
  return (
    <Modal title={initial?.id ? 'Edit repeating journal' : 'New repeating journal'} onClose={onClose} width={1000}>
      <div className="grid-2" style={{ gap: 12 }}>
        <div><label className="text-sm fw-600" htmlFor="rn">Name</label><input id="rn" className="input" value={f.name} onChange={e => set('name', e.target.value)} placeholder="e.g. Monthly insurance release" /></div>
        <div><label className="text-sm fw-600" htmlFor="rf">Repeats</label><select id="rf" className="input" value={f.frequency} onChange={e => set('frequency', e.target.value)}>{FREQS.map(([k, l]) => <option key={k} value={k}>{l}</option>)}</select></div>
        <div><label className="text-sm fw-600" htmlFor="rd">Next date</label><input id="rd" type="date" className="input" value={f.next_date} onChange={e => set('next_date', e.target.value)} /></div>
        <div><label className="text-sm fw-600" htmlFor="re">Ends (optional)</label><input id="re" type="date" className="input" value={f.end_date} onChange={e => set('end_date', e.target.value)} /></div>
        <div><label className="text-sm fw-600" htmlFor="rm">Each time</label><select id="rm" className="input" value={f.mode} onChange={e => set('mode', e.target.value)}>
          <option value="draft">Create a draft for review</option>{canApprove && <option value="post">Post straight to the ledger</option>}</select></div>
        <div><label className="text-sm fw-600" htmlFor="rv">Auto-reverse after (days, optional)</label><input id="rv" className="input" inputMode="numeric" value={f.reverse_after_days} onChange={e => set('reverse_after_days', e.target.value)} placeholder="e.g. 31 for accruals" /></div>
        <div><label className="text-sm fw-600" htmlFor="rnar">Narration</label><input id="rnar" className="input" value={f.narration} onChange={e => set('narration', e.target.value)} placeholder="Insurance release - {month} {year}" /></div>
        <div><label className="text-sm fw-600" htmlFor="rref">Reference</label><input id="rref" className="input" value={f.reference} onChange={e => set('reference', e.target.value)} placeholder="PREPAY-{mon}{year}" /></div>
        <div><label className="text-sm fw-600" htmlFor="rcur">Currency (optional)</label><input id="rcur" className="input" value={cur} maxLength={3} onChange={e => setCur(e.target.value.toUpperCase())} placeholder="base currency" />
          {foreign && <div className="text-xs text-muted">Each run uses YOUR stored {cur.toUpperCase()} rate for that occurrence's date; without one it stops with an error rather than guess.</div>}</div>
        <div><label className="text-sm fw-600" htmlFor="ram">GST</label><select id="ram" className="input" value={f.amounts_are} onChange={e => set('amounts_are', e.target.value)}>{AMOUNTS.map(([k, l]) => <option key={k} value={k}>{l}</option>)}</select></div>
      </div>
      <label className="text-sm" style={{ display: 'block', marginTop: 8 }}><input type="checkbox" checked={f.auto_run} onChange={e => set('auto_run', e.target.checked)} /> Run automatically when due (no need to press “Run due now”)</label>
      <p className="text-xs text-muted mt-1">Labels you can use in the narration, reference and line descriptions: {'{month} {mon} {year} {prev_month} {prev_year} {fy} {quarter} {date}'}</p>
      <LinesEditor lines={lines} setLines={setLines} accounts={accounts} taxes={taxes} categories={categories} />
      <PreviewPanel pv={pv} entered={{ dr: 0, cr: 0 }} />
      <div className="flex gap-1 mt-4"><button className="btn btn-primary" disabled={busy || !f.name.trim() || (pv && pv.errors.some(e => !/lock date/i.test(e)))} onClick={save}>{busy ? 'Saving…' : 'Save'}</button><button className="btn btn-ghost" onClick={onClose}>Cancel</button></div>
    </Modal>
  )
}
