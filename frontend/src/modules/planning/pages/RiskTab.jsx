import React, { useState } from 'react'
import * as api from '../lib/planningApi.js'
import { fmtAUD, fmtDate, label } from '../lib/format.js'
import { useLoad, Async, Stat, Section, Disclaimer, Basis, StatusBadge, Table, Select, Input, Grid, Modal, act, EmptyState } from '../components/kit.jsx'

function Review({ a, onClose, onDone }) {
  const [status, setStatus] = useState('acknowledged')
  const [note, setNote] = useState('')
  const needs = status === 'dismissed' || status === 'resolved'
  const save = async () => { if (await act(() => api.risk.review(a.id, status, note), 'Review recorded')) onDone() }
  return (
    <Modal title={`Review: ${a.title}`} onClose={onClose}>
      <div className="text-sm"><b>Why it was flagged:</b> {a.reason}</div>
      <div className="text-xs text-muted" style={{ margin: '4px 0 8px' }}>Rule {a.rule} ({a.rule_version}) · {a.event_date ? fmtDate(a.event_date) : 'no date'} · {a.amount != null ? fmtAUD(a.amount) : ''}</div>
      <details open><summary className="text-sm">Evidence and baseline</summary>
        <pre className="mono text-xs" style={{ whiteSpace: 'pre-wrap', overflowX: 'auto' }}>{JSON.stringify({ evidence: a.evidence, baseline: a.baseline }, null, 2)}</pre></details>
      <Select label="Outcome" value={status} onChange={e => setStatus(e.target.value)} options={[{ value: 'acknowledged', label: 'Acknowledged (looking into it)' }, { value: 'resolved', label: 'Resolved (checked, action taken)' }, { value: 'dismissed', label: 'Dismissed (expected / not an issue)' }, { value: 'new', label: 'Re-open' }]} />
      <Input label={needs ? 'Note (required)' : 'Note (optional)'} value={note} onChange={e => setNote(e.target.value)} />
      <div className="flex gap-1" style={{ justifyContent: 'flex-end', marginTop: 8 }}><button className="btn btn-outline" onClick={onClose}>Cancel</button><button className="btn btn-primary" disabled={needs && note.trim().length < 3} onClick={save}>Save review</button></div>
    </Modal>)
}

function Thresholds({ onClose, onSaved }) {
  const q = useLoad(() => api.risk.config(), [])
  const [t, setT] = useState(null)
  const cur = t || (q.data ? Object.fromEntries(Object.entries(q.data.thresholds).map(([k, v]) => [k, String(v)])) : {})
  const save = async () => { if (await act(() => api.risk.saveConfig(Object.fromEntries(Object.entries(cur).map(([k, v]) => [k, Number(v)]))), 'Thresholds saved')) onSaved() }
  return (
    <Modal title="Alert thresholds" onClose={onClose} width={760}>
      <Async q={q}>{() => (
        <>
          <Disclaimer>Lower thresholds raise more alerts. Changes apply to the next scan; existing alerts and their reviews are kept.</Disclaimer>
          <Grid cols={3}>{Object.keys(cur).map(k => <Input key={k} label={label(k)} type="number" step="any" value={cur[k]} onChange={e => setT({ ...cur, [k]: e.target.value })} />)}</Grid>
          <div className="flex gap-1" style={{ justifyContent: 'flex-end', marginTop: 8 }}><button className="btn btn-outline" onClick={onClose}>Cancel</button><button className="btn btn-primary" onClick={save}>Save</button></div>
        </>)}</Async>
    </Modal>)
}

export default function RiskTab() {
  const [f, setF] = useState({ status: '', severity: '', rule: '' })
  const q = useLoad(() => api.risk.alerts(Object.fromEntries(Object.entries(f).filter(([, v]) => v))), [f.status, f.severity, f.rule])
  const me = useLoad(() => api.me(), [])
  const caps = me.data?.capabilities || []
  const [rev, setRev] = useState(null)
  const [cfg, setCfg] = useState(false)
  const [scanRes, setScanRes] = useState(null)
  const scan = async () => { const r = await act(() => api.risk.scan()); if (r) { setScanRes(r); q.reload() } }
  return (
    <div style={{ padding: 16 }}>
      <div role="note" className="alert alert-info" style={{ marginBottom: 12 }}><Basis basis="RULE" /> Alerts mean "unusual — please review". They are not findings of error or wrongdoing, and AccFino never changes your records because of them.</div>
      <Async q={q}>{d => (
        <>
          <Grid cols={3}>{['new', 'acknowledged', 'resolved', 'dismissed'].map(s => <Stat key={s} label={label(s)} basis="RULE" value={d.counts[s]} onClick={() => setF({ ...f, status: s })} />)}</Grid>
          <Section title="Alerts" actions={<>
            {caps.includes('edit') && <button className="btn btn-primary btn-sm" onClick={scan}>Run scan now</button>}
            {caps.includes('config') && <button className="btn btn-outline btn-sm" onClick={() => setCfg(true)}>Thresholds</button>}
          </>}>
            {scanRes && <div role="status" className="alert alert-success" style={{ marginBottom: 8 }}>Scan complete: {scanRes.created} new alert(s), {scanRes.suppressed_duplicates} already known (not duplicated), {scanRes.detected} detected by {scanRes.ruleset}.{scanRes.skipped?.length ? ` Skipped: ${scanRes.skipped.map(s => s.rule || s).join(', ')}.` : ''}</div>}
            <div className="flex items-center gap-1" style={{ flexWrap: 'wrap' }}>
              <Select label="Status" value={f.status} blank="All" onChange={e => setF({ ...f, status: e.target.value })} options={['new', 'acknowledged', 'dismissed', 'resolved']} />
              <Select label="Severity" value={f.severity} blank="All" onChange={e => setF({ ...f, severity: e.target.value })} options={['high', 'medium', 'low']} />
              <Select label="Rule" value={f.rule} blank="All" onChange={e => setF({ ...f, rule: e.target.value })} options={Object.entries(d.rules).map(([v, l]) => ({ value: v, label: l }))} />
            </div>
            <Table caption="Risk alerts" rows={d.alerts} empty="No alerts" hint="Nothing unusual has been recorded for this filter. Run a scan to check recent activity." columns={[
              { key: 'severity', label: 'Severity', render: a => <StatusBadge status={a.severity} /> }, { key: 'title', label: 'Alert' }, { key: 'reason', label: 'Why flagged' },
              { key: 'event_date', label: 'Date', date: true }, { key: 'amount', label: 'Amount', money: true }, { key: 'status', label: 'Status', render: a => <StatusBadge status={a.status} /> },
              { key: 'reviewer', label: 'Reviewed by', render: a => (a.reviewer ? `${a.reviewer}${a.review_note ? `: ${a.review_note}` : ''}` : '—') },
              { key: 'act', label: '', render: a => (caps.includes('review') ? <button className="btn btn-outline btn-sm" onClick={() => setRev(a)}>Review</button> : <button className="btn btn-ghost btn-sm" onClick={() => setRev({ ...a, readOnly: true })}>Details</button>) }]} />
            <Disclaimer>Rules: {Object.values(d.rules).join(' · ')}.</Disclaimer>
          </Section>
        </>)}</Async>
      {rev && !rev.readOnly && <Review a={rev} onClose={() => setRev(null)} onDone={() => { setRev(null); q.reload() }} />}
      {rev && rev.readOnly && <Modal title={rev.title} onClose={() => setRev(null)}><div className="text-sm">{rev.reason}</div><pre className="mono text-xs" style={{ whiteSpace: 'pre-wrap' }}>{JSON.stringify({ evidence: rev.evidence, baseline: rev.baseline }, null, 2)}</pre></Modal>}
      {cfg && <Thresholds onClose={() => setCfg(false)} onSaved={() => setCfg(false)} />}
    </div>)
}
