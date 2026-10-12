import React, { useState } from 'react'
import * as L from '../lib/lendApi.js'
import { ApplicationDetail } from './OriginationTab.jsx'
import { act, Async, DataGrid, Disclaimer, Grade, Grid, Input, Modal, Outcome, Section, StatusBadge, useForm, useLoad } from '../components/kit.jsx'
import { fmtDate, label } from '../lib/format.js'

const POLICY_LABELS = { dti_limit: 'Debt repayments as a share of income: guide limit (0.43 is 43%)', serviceability_buffer: 'Buffer added to the loan rate for the affordability test (0.03 is 3%)', min_umi: 'Minimum surplus a month after the loan ($)',
  max_lti: 'Maximum loan as a multiple of annual income', lvr_cap: 'Maximum loan to value (0.80 is 80%)', min_months: 'Months of statements required', min_classification: 'Share of transactions that must be categorised (0.85 is 85%)', gambling_threshold: 'Gambling as a share of income that raises a flag (0.05 is 5%)', min_recurring_share: 'Share of income that must recur before a grade better than C is possible (0.5 is 50%)' }

export default function CreditTab({ me }) {
  const caps = me.capabilities
  const [bump, setBump] = useState(0)
  const [open, setOpen] = useState(null)
  const [policy, setPolicy] = useState(false)
  const list = useLoad(() => L.applications.list({}), [bump])
  const ref = useLoad(() => L.reference(), [])
  const again = () => setBump(n => n + 1)
  return (
    <div style={{ padding: 16 }}>
      <Disclaimer />
      <Section title="Assessments" hint="Score, then risk grade, then the factors behind it, then the recommendation. The system recommends; a person decides. Open one to see every factor, or to approve, decline or override with a recorded reason."
        actions={<button className="btn btn-outline btn-sm" onClick={() => setPolicy(true)}>Policy settings</button>}>
        <Async q={list}>{d => <DataGrid rows={d.rows.filter(r => r.grade || ['draft', 'submitted', 'assessing', 'more_information'].includes(r.status))} empty="Nothing to assess yet" hint="Start an application under Origination." onRowClick={r => setOpen(r.id)} searchKeys={['number', 'applicant']} columns={[
          { key: 'number', label: 'No.' }, { key: 'applicant', label: 'Applicant' }, { key: 'amount', label: 'Amount', money: true }, { key: 'status', label: 'Status', render: r => <StatusBadge status={r.status} /> },
          { key: 'grade', label: 'Risk grade', render: r => <Grade g={r.grade} score={r.score} /> }, { key: 'outcome', label: 'Recommendation / decision', render: r => <Outcome o={r.outcome} /> }, { key: 'created_at', label: 'Started', date: true }]} />}</Async>
      </Section>
      <Async q={ref}>{r => (
        <Section title="How the score works" hint="Nine factors, fixed maximum points, adding to 100. Higher is lower risk. A limit shown in the assessment is the guide in force for this organisation.">
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit,minmax(340px,1fr))', gap: 16 }}>
            <table className="data-table" aria-label="Scoring factors"><thead><tr><th>Factor</th><th className="text-right">Max points</th></tr></thead><tbody>{r.factors.map(f => <tr key={f.key}><td>{f.label}</td><td className="text-right mono">{f.max}</td></tr>)}<tr><td><strong>Total</strong></td><td className="text-right mono"><strong>{r.factors.reduce((s, f) => s + f.max, 0)}</strong></td></tr></tbody></table>
            <table className="data-table" aria-label="Risk grades"><thead><tr><th>Grade</th><th>Score</th><th>Meaning</th></tr></thead><tbody>{r.grades.map((g, i) => <tr key={g.grade}><td><Grade g={g.grade} /></td><td className="mono">{i === 0 ? `${g.min}+` : `${g.min} to ${r.grades[i - 1].min - 1}`}</td><td>{g.band}</td></tr>)}</tbody></table>
          </div>
        </Section>)}</Async>
      {open && <Modal title="Credit assessment and decision" onClose={() => { setOpen(null); again() }} width={1100}><ApplicationDetail id={open} caps={caps} onChanged={again} onClose={() => { setOpen(null); again() }} /></Modal>}
      {policy && <PolicyForm caps={caps} onClose={() => setPolicy(false)} />}
    </div>)
}

function PolicyForm({ caps, onClose }) {
  const q = useLoad(() => L.settings.get(), [])
  return <Modal title="Assessment policy" onClose={onClose} width={720}><Async q={q}>{s => <PolicyInner s={s} can={caps.includes('configure')} onClose={onClose} />}</Async></Modal>
}

function PolicyInner({ s, can, onClose }) {
  const [f, set] = useForm({ ...Object.fromEntries(Object.keys(s.ranges).map(k => [k, s.policy[k]])), min_cash_buffer: s.min_cash_buffer })
  const out = Object.entries(s.ranges).filter(([k, [lo, hi]]) => !(Number(f[k]) >= lo && Number(f[k]) <= hi)).map(([k, [lo, hi]]) => `${k.replace(/_/g, ' ')} must be between ${lo} and ${hi}`)
  return (
    <>
      <div className="text-xs text-muted" style={{ marginBottom: 8 }}>{s.note} {!can && 'Your role can view these but not change them.'}</div>
      <Grid cols={2}>{Object.keys(s.ranges).map(k => <Input key={k} label={POLICY_LABELS[k] || label(k)} type="number" step="any" value={f[k]} onChange={set(k)} disabled={!can} hint={`Default ${s.defaults[k]}`} />)}
        <Input label="Minimum cash buffer treasury plans against ($)" type="number" value={f.min_cash_buffer} onChange={set('min_cash_buffer')} disabled={!can} /></Grid>
      {out.length > 0 && <div className="text-xs" style={{ color: 'var(--danger)' }}>{out.join(' · ')}</div>}
      <div className="flex gap-1" style={{ justifyContent: 'flex-end' }}><button className="btn btn-outline" onClick={onClose}>Close</button>
        {can && <button className="btn btn-primary" disabled={out.length > 0} onClick={async () => { const policy = {}; for (const k of Object.keys(s.ranges)) policy[k] = f[k]; if (await act(() => L.settings.save({ policy, min_cash_buffer: f.min_cash_buffer }), 'Policy saved')) onClose() }}>Save policy</button>}</div>
    </>)
}
