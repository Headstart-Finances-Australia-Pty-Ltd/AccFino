import React, { useRef, useState } from 'react'
import * as api from '../lib/planningApi.js'
import { errMsg } from '../lib/planningApi.js'
import { fmtDate } from '../lib/format.js'
import { useLoad, Async, Section, Disclaimer, Basis } from '../components/kit.jsx'

function Answer({ m, onPick }) {
  return (
    <div role="article" aria-label="Assistant answer" className="card card-flat" style={{ marginBottom: 10 }}>
      <div className="text-xs text-muted" style={{ marginBottom: 4 }}><Basis basis="AI" /> {m.label}</div>
      <div style={{ whiteSpace: 'pre-wrap' }}>{m.answer}</div>
      {m.status === 'clarify' && m.clarification?.options?.length > 0 && (
        <div className="flex gap-1" style={{ marginTop: 8, flexWrap: 'wrap' }}>{m.clarification.options.map(o => <button key={o} className="btn btn-outline btn-sm" onClick={() => onPick(o)}>{o}</button>)}</div>)}
      {m.status === 'refused' && <div className="text-xs" style={{ marginTop: 6, color: 'var(--danger)' }}>This request was declined. The assistant is read-only and cannot change records.</div>}
      {m.citations?.length > 0 && (
        <details style={{ marginTop: 8 }}><summary className="text-xs">Sources and calculations ({m.citations.length})</summary>
          <ul className="text-xs" style={{ margin: '4px 0 0', paddingLeft: 18 }}>{m.citations.map((c, i) => <li key={i}>{c.report}: {c.metric} — {c.period}; {c.calculation} (source: {c.source}; basis {c.basis})</li>)}</ul></details>)}
    </div>)
}

export default function AssistantTab() {
  const sugg = useLoad(() => api.assistant.suggestions(), [])
  const hist = useLoad(() => api.assistant.history(), [])
  const [q, setQ] = useState('')
  const [msgs, setMsgs] = useState([])
  const [busy, setBusy] = useState(false)
  const end = useRef()
  const ask = async text => {
    const question = (text ?? q).trim()
    if (!question || busy) return
    setBusy(true); setQ(''); setMsgs(m => [...m, { role: 'user', text: question }])
    try { const r = await api.assistant.ask(question); setMsgs(m => [...m, { role: 'ai', ...r }]); hist.reload() }
    catch (e) { setMsgs(m => [...m, { role: 'error', text: errMsg(e) }]) }
    finally { setBusy(false); setTimeout(() => end.current?.scrollIntoView?.({ block: 'nearest' }), 0) }
  }
  return (
    <div style={{ padding: 16 }}>
      <Async q={sugg}>{s => (
        <>
          <div role="note" className="alert alert-info" style={{ marginBottom: 12 }}><Basis basis="AI" /> {s.label} Limit: {s.limit_per_hour} questions per hour. Questions and answers are logged for audit.</div>
          <Section title="Ask about your finances" hint="Answers come from live reports and carry their source. If the assistant cannot answer from your data it says so.">
            <div aria-live="polite" style={{ minHeight: 120 }}>
              {msgs.length === 0 && <Disclaimer>Try one of the questions below.</Disclaimer>}
              {msgs.map((m, i) => m.role === 'user'
                ? <div key={i} style={{ textAlign: 'right', margin: '6px 0' }}><span className="badge badge-neutral" style={{ whiteSpace: 'normal', maxWidth: '85%' }}>{m.text}</span></div>
                : m.role === 'error' ? <div key={i} role="alert" className="alert alert-error">{m.text}</div> : <Answer key={i} m={m} onPick={ask} />)}
              {busy && <div role="status" className="text-muted">Looking at your reports…</div>}
              <div ref={end} />
            </div>
            <form onSubmit={e => { e.preventDefault(); ask() }} className="flex gap-1" style={{ marginTop: 8 }}>
              <input className="input" style={{ flex: 1 }} aria-label="Your question" maxLength={500} placeholder="e.g. What is our bank balance?" value={q} onChange={e => setQ(e.target.value)} />
              <button className="btn btn-primary" type="submit" disabled={busy || !q.trim()}>Ask</button>
            </form>
            <div className="flex gap-1" style={{ flexWrap: 'wrap', marginTop: 8 }}>{(s.suggestions || []).map(x => <button key={x} className="btn btn-outline btn-sm" onClick={() => ask(x)}>{x}</button>)}</div>
          </Section>
        </>)}</Async>
      <Section title="Recent questions" hint="Your organisation's audit trail of assistant use (sensitive details are masked)">
        <Async q={hist}>{rows => (rows.length === 0 ? <Disclaimer>No questions yet.</Disclaimer>
          : <ul style={{ margin: 0, paddingLeft: 18 }}>{rows.slice(0, 15).map(h => <li key={h.id} className="text-sm">{fmtDate(h.at)} — {h.question} <span className="text-muted">({h.status})</span></li>)}</ul>)}</Async>
      </Section>
    </div>)
}
