import React, { useState } from 'react'
import * as api from '../lib/planningApi.js'
import { label, fyStartISO, todayISO } from '../lib/format.js'
import { useLoad, Async, Section, Provenance, Disclaimer, StatusBadge, Table, Input, Select, Grid, Modal, act, Basis, EmptyState } from '../components/kit.jsx'

const src = s => (typeof s === 'string' ? s : s?.name || s?.reference || JSON.stringify(s))

function InsightCard({ i }) {
  const [open, setOpen] = useState(false)
  return (
    <div className="card card-flat" style={{ marginBottom: 10, borderLeft: `4px solid var(--${i.severity === 'high' ? 'danger' : i.severity === 'medium' ? 'warning' : 'border'})` }}>
      <div className="flex items-center justify-between" style={{ gap: 8, flexWrap: 'wrap' }}>
        <div><StatusBadge status={i.severity} /> <b>{i.title}</b></div>
        <div className="text-xs text-muted">{i.rule} · {i.rule_version}</div>
      </div>
      <div className="text-sm" style={{ margin: '6px 0' }}><b>{i.metric}</b> ({i.period}): actual <b>{i.actual}</b> vs {i.comparison}</div>
      <div className="text-sm"><b>Why it matters:</b> {i.why_it_matters}</div>
      <div className="text-sm" style={{ marginTop: 4 }}><b>{i.recommendation.label} (suggestion, not advice):</b> {i.recommendation.text}</div>
      <div className="text-xs text-muted" style={{ marginTop: 4 }}>Confidence: {i.confidence}{i.limitations?.length ? ` · Limitations: ${i.limitations.join('; ')}` : ''}</div>
      <button className="btn btn-ghost btn-xs" aria-expanded={open} onClick={() => setOpen(o => !o)}>{open ? 'Hide' : 'Show'} calculation &amp; sources</button>
      {open && <div className="text-xs" style={{ marginTop: 4 }}><div><b>Calculation:</b> {i.calculation}</div><div><b>Sources:</b> {(i.sources || []).map(src).join('; ') || 'ledger'}</div></div>}
    </div>)
}

function Config({ d, onClose, onSaved }) {
  const [t, setT] = useState(Object.fromEntries(Object.entries(d.thresholds).map(([k, v]) => [k, String(v)])))
  const [bm, setBm] = useState(d.benchmarks || [])
  const save = async () => {
    const thresholds = Object.fromEntries(Object.entries(t).map(([k, v]) => [k, Number(v)]))
    if (await act(() => api.insights.saveConfig({ thresholds, benchmarks: bm }), 'Insight settings saved')) onSaved()
  }
  return (
    <Modal title="Insight thresholds &amp; benchmarks" onClose={onClose} width={800}>
      <Disclaimer>Thresholds decide when a rule fires. Benchmarks are shown only when you supply a figure with its source and link — AccFino does not ship any. Only the margins AccFino calculates can be compared.</Disclaimer>
      <Grid cols={3}>{Object.keys(t).map(k => <Input key={k} label={label(k)} type="number" step="any" value={t[k]} onChange={e => setT(s => ({ ...s, [k]: e.target.value }))} />)}</Grid>
      <h5>Benchmarks (optional)</h5>
      {bm.map((b, i) => (
        <div key={i} className="flex items-center gap-1" style={{ flexWrap: 'wrap' }}>
          <Select label="Metric" value={b.metric} blank="Choose…" onChange={e => setBm(x => x.map((y, j) => (j === i ? { ...y, metric: e.target.value } : y)))} options={[{ value: 'gross_margin_pct', label: 'Gross margin %' }, { value: 'net_margin_pct', label: 'Net margin %' }]} />
          {['value', 'as_of', 'source', 'source_url'].map(k => <Input key={k} label={label(k)} value={b[k] ?? ''} onChange={e => setBm(x => x.map((y, j) => (j === i ? { ...y, [k]: e.target.value } : y)))} />)}
          <button className="btn btn-outline btn-sm" onClick={() => setBm(x => x.filter((_, j) => j !== i))}>Remove</button>
        </div>))}
      <button className="btn btn-outline btn-sm" onClick={() => setBm(x => [...x, { metric: '', value: '', as_of: '', source: '', source_url: '' }])}>Add benchmark</button>
      <div className="flex gap-1" style={{ justifyContent: 'flex-end', marginTop: 12 }}><button className="btn btn-outline" onClick={onClose}>Cancel</button><button className="btn btn-primary" onClick={save}>Save</button></div>
    </Modal>)
}

export default function InsightsTab() {
  const [p, setP] = useState({ from: fyStartISO(), to: todayISO() })
  const q = useLoad(() => api.insights.get({ from: p.from, to: p.to }), [p.from, p.to])
  const me = useLoad(() => api.me(), [])
  const [cfg, setCfg] = useState(false)
  const canConfig = (me.data?.capabilities || []).includes('config')
  return (
    <div style={{ padding: 16 }}>
      <Section title="CFO insights" hint="Each insight is the result of a named rule over your ledger. Insights highlight; they do not decide." actions={canConfig && <button className="btn btn-outline btn-sm" onClick={() => setCfg(true)}>Thresholds</button>}>
        <div className="flex items-center gap-1" style={{ flexWrap: 'wrap' }}>
          <Input label="From" type="date" value={p.from} onChange={e => setP({ ...p, from: e.target.value })} /><Input label="To" type="date" value={p.to} max={todayISO()} onChange={e => setP({ ...p, to: e.target.value })} />
        </div>
      </Section>
      <Async q={q}>{d => (
        <>
          <Provenance d={d} />
          <div className="text-sm" style={{ marginBottom: 8 }}><Basis basis="RULE" /> Rule set {d.ruleset}: {d.counts.high} high · {d.counts.medium} medium · {d.counts.low} low · {d.counts.info} info</div>
          {d.insights.length === 0
            ? <EmptyState icon="✅" title="No insights triggered" hint="Nothing in this period crossed a rule threshold. Rules that need more history stay silent rather than guess." />
            : d.insights.map((i, n) => <InsightCard key={`${i.rule}-${n}`} i={i} />)}
          <Section title="Benchmarks"><Disclaimer>{d.benchmark_note}</Disclaimer>
            <Table caption="Benchmarks" rows={d.benchmarks} rowKey="metric" empty="No verified benchmarks configured" columns={[{ key: 'metric', label: 'Metric' }, { key: 'value', label: 'Value' }, { key: 'as_of', label: 'As of' },
              { key: 'source', label: 'Source', render: b => <a href={b.source_url} target="_blank" rel="noopener noreferrer">{b.source}</a> }]} /></Section>
          <Section title="Facts used" hint="Every rule reads only these figures"><div className="mono text-xs" style={{ overflowX: 'auto' }}>{Object.entries(d.facts_used).filter(([, v]) => typeof v !== 'object' || v === null).map(([k, v]) => <div key={k}>{label(k)}: {String(v)}</div>)}</div></Section>
        </>)}</Async>
      {cfg && q.data && <Config d={q.data} onClose={() => setCfg(false)} onSaved={() => { setCfg(false); q.reload() }} />}
    </div>)
}
