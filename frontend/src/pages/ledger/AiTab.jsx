import React, { useState } from 'react'
import toast from 'react-hot-toast'
import { Sparkles } from 'lucide-react'
import * as api from '../../lib/platformApi.js'
import { money, today } from './JournalEditor.jsx'

const iso = d => d.toISOString().slice(0, 10)
const shift = (d, m) => new Date(d.getFullYear(), d.getMonth() + m, 1)
const prevMonth = () => { const n = new Date(); const a = shift(n, -1), b = new Date(n.getFullYear(), n.getMonth(), 0), c = shift(n, -2), e = new Date(n.getFullYear(), n.getMonth() - 1, 0); return { date_from: iso(a), date_to: iso(b), compare_from: iso(c), compare_to: iso(e) } }

function DescribeJournal({ onOpen }) {
  const [text, setText] = useState(''); const [busy, setBusy] = useState(false); const [res, setRes] = useState(null)
  const go = async () => {
    setBusy(true); setRes(null)
    try { const { data } = await api.aiJournal({ text, date: today() }); setRes(data) } catch (e) { toast.error(api.errMsg(e)) } finally { setBusy(false) }
  }
  const open = () => {
    const p = res.proposal
    onOpen({ date: p.date, narration: p.narration, amounts_are: 'no_tax', lines: p.lines.map(l => ({ account_id: l.account_id, debit: l.debit || '0', credit: l.credit || '0', description: l.description })) })
  }
  return (
    <div className="card" style={{ padding: 14, marginBottom: 14 }} data-testid="describe">
      <h4 style={{ margin: '0 0 6px' }}>Describe a journal</h4>
      <p className="text-sm text-muted" style={{ margin: '0 0 8px' }}>Say what you want in a sentence. The assistant proposes the lines using only <b>your</b> accounts; nothing is saved until you open it in the editor, check it and post it yourself.</p>
      <textarea aria-label="Describe the journal" className="input" rows={2} style={{ width: '100%' }} value={text} maxLength={1000} onChange={e => setText(e.target.value)} placeholder="e.g. Accrue $4,500 audit fees for December and reverse it in January" />
      <button className="btn btn-primary btn-sm" style={{ marginTop: 6 }} disabled={busy || text.trim().length < 8} onClick={go}><Sparkles size={13} /> {busy ? 'Thinking…' : 'Draft it'}</button>
      {res && (
        <div style={{ marginTop: 10 }} data-testid="proposal">
          {res.dropped?.length > 0 && <div className="alert alert-warning">{res.dropped.join(' · ')}</div>}
          <div className="data-table-wrap"><table className="data-table"><thead><tr><th>Account</th><th>Description</th><th className="text-right">Debit</th><th className="text-right">Credit</th></tr></thead>
            <tbody>{(res.preview.lines || []).map((l, i) => <tr key={i}><td>{l.account_code} · {l.account_name}</td><td className="text-sm">{l.description}</td><td className="text-right mono">{Number(l.debit) ? money(l.debit) : ''}</td><td className="text-right mono">{Number(l.credit) ? money(l.credit) : ''}</td></tr>)}</tbody></table></div>
          {res.notes && <p className="text-sm">Assumption: {res.notes}</p>}
          {res.reverse_next_month && <p className="text-sm">You mentioned reversing it next month: tick “Reverse automatically” in the editor and choose the date.</p>}
          {res.errors?.length > 0 && <div className="alert alert-warning" data-testid="proposal-errors">{res.errors.join(' · ')} — you can still open it and fix the amounts.</div>}
          <button className="btn btn-outline btn-sm" onClick={open}>Open in the journal editor</button>
          <div className="text-xs text-muted" style={{ marginTop: 4 }}>{res.advisory}</div>
        </div>)}
    </div>)
}

function ExplainPL() {
  const [p, setP] = useState(prevMonth()); const [busy, setBusy] = useState(false); const [res, setRes] = useState(null)
  const go = async () => { setBusy(true); setRes(null); try { const { data } = await api.aiExplainPL(p); setRes(data) } catch (e) { toast.error(api.errMsg(e)) } finally { setBusy(false) } }
  const set = k => e => setP({ ...p, [k]: e.target.value })
  return (
    <div className="card" style={{ padding: 14 }} data-testid="explain">
      <h4 style={{ margin: '0 0 6px' }}>Explain the change in profit</h4>
      <p className="text-sm text-muted" style={{ margin: '0 0 8px' }}>AccFino works out what moved. The assistant only writes the plain-English summary, and it is withheld if it quotes a figure that isn’t in your data. It sees account names and totals only — no contacts or narrations.</p>
      <div className="flex gap-1" style={{ flexWrap: 'wrap', alignItems: 'center' }}>
        <input aria-label="Period from" type="date" className="input input-sm" value={p.date_from} onChange={set('date_from')} /> to <input aria-label="Period to" type="date" className="input input-sm" value={p.date_to} onChange={set('date_to')} />
        <span className="text-muted">compared with</span>
        <input aria-label="Compare from" type="date" className="input input-sm" value={p.compare_from} onChange={set('compare_from')} /> to <input aria-label="Compare to" type="date" className="input input-sm" value={p.compare_to} onChange={set('compare_to')} />
        <button className="btn btn-primary btn-sm" disabled={busy} onClick={go}><Sparkles size={13} /> {busy ? 'Working…' : 'Explain'}</button></div>
      {res && (
        <div style={{ marginTop: 10 }}>
          {res.commentary && <div className="alert alert-info" data-testid="commentary">{res.commentary}</div>}
          {res.note && <div className="alert alert-warning" data-testid="explain-note">{res.note}</div>}
          {res.headline && <div className="stats-grid">{Object.entries(res.headline).map(([k, v]) => <div key={k} className="stat-card"><div className="stat-label">{k.replace(/_/g, ' ')}</div><div className="stat-value">{money(v.current)}</div><div className="stat-sub">was {money(v.previous)} · change {money(v.change)}</div></div>)}</div>}
          {res.movements?.length > 0 && <div className="data-table-wrap" style={{ marginTop: 8 }}><table className="data-table" data-testid="movements"><thead><tr><th>Account</th><th className="text-right">This period</th><th className="text-right">Before</th><th className="text-right">Change</th></tr></thead>
            <tbody>{res.movements.map(m => <tr key={m.code}><td>{m.code} · {m.name}</td><td className="text-right mono">{money(m.current)}</td><td className="text-right mono">{money(m.previous)}</td><td className="text-right mono">{money(m.change)}</td></tr>)}</tbody></table></div>}
          {res.advisory && <div className="text-xs text-muted" style={{ marginTop: 4 }}>{res.advisory}</div>}
        </div>)}
    </div>)
}

export default function AiTab({ canApprove, settings, onSettings, onOpenEditor }) {
  const on = !!settings.llm_assist
  const toggle = e => {
    if (e.target.checked && !window.confirm('Turn on AI assistance?\n\nWhen you use these features, account names, amounts and the sentence you type (long numbers and emails masked) are sent to Groq. Contact names are never sent. Everything the assistant produces is advisory: it cannot post, approve or change anything, and its output is checked against your own accounts.')) return
    onSettings({ llm_assist: e.target.checked })
  }
  return (
    <div>
      <div className="card" style={{ padding: 14, marginBottom: 14 }}>
        <h4 style={{ margin: '0 0 6px' }}>AI assistant <span className={`badge ${on ? 'badge-success' : 'badge-neutral'}`}>{on ? 'on' : 'off'}</span></h4>
        <p className="text-sm text-muted" style={{ margin: 0 }}>Draft a journal from a sentence, get a second opinion on a submitted draft (in the Review tab), and have a change in profit explained. Off by default; limited to 20 requests an hour.</p>
        {canApprove ? <label className="text-sm" style={{ display: 'block', marginTop: 8 }}><input type="checkbox" checked={on} onChange={toggle} /> Use AI assistance for this organisation</label>
          : <div className="text-xs text-muted" style={{ marginTop: 6 }}>Only an approver can turn this on.</div>}
      </div>
      {on && <><DescribeJournal onOpen={onOpenEditor} /><ExplainPL /></>}
    </div>)
}
