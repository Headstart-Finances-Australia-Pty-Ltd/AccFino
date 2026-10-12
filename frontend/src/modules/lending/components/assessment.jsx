import React from 'react'
import { Grade, Money, Notice, Outcome, Pct, Section, Stat } from './kit.jsx'
import { fmtAUD, fmtDate, fmtPct, label } from '../lib/format.js'

const SEV = { high: 'var(--danger)', warning: 'var(--warning)', info: 'var(--text-muted)' }

// Score -> Risk grade -> Key factors -> Recommendation. Every point is traceable to a named factor and a sentence: there is no hidden model.
export default function AssessmentPanel({ a, request }) {
  if (!a) return <div className="text-sm text-muted" style={{ padding: 12 }}>Not assessed yet. Analyse the applicant's statements, then run the credit assessment.</div>
  const r = a.result || {}, rec = r.recommendation || {}, cf = r.cash_flow || {}
  return (
    <div aria-label="Credit assessment">
      {a.stale && <div role="alert" className="alert alert-warning" style={{ marginBottom: 10 }}>The loan terms changed after this assessment: run it again before deciding.</div>}
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit,minmax(170px,1fr))', gap: 10, marginBottom: 10 }}>
        <Stat label="Score" value={<span><span style={{ fontWeight: 700 }}>{Number(a.score).toFixed(0)}</span> <span className="text-sm text-muted">of 100</span></span>} sub={`Version ${a.version}`} />
        <Stat label="Risk grade" value={<Grade g={a.grade} />} sub={r.band} />
        <Stat label="Recommendation" value={<Outcome o={a.outcome} />} sub={a.override ? `Overridden: ${label(a.override.outcome)}` : 'A person decides'} />
        <Stat label="Supportable loan" value={<Money v={rec.supportable_rounded} strong />} sub={rec.limited_by ? `limited by ${rec.limited_by}` : ''} tone={Number(rec.requested) > Number(rec.supportable_amount) ? 'danger' : undefined} />
      </div>
      {(rec.reasons || []).map((t, i) => <div key={i} className="text-sm" style={{ marginBottom: 4 }}>• {t}</div>)}
      {a.override && (
        <div className="alert alert-info" style={{ margin: '10px 0' }} aria-label="Override">
          <strong>Overridden by {a.override.by}</strong> on {fmtDate(a.override.at)}: decided <strong>{label(a.override.outcome).toLowerCase()}</strong> against the recommendation to <strong>{(rec.outcome ? label(rec.outcome) : label(a.outcome)).toLowerCase()}</strong>.
          <div className="text-sm">Reason recorded: {a.override.reason}</div>
        </div>)}
      {(rec.conditions || []).length > 0 && <Section title="Conditions and what is missing"><ul style={{ margin: 0, paddingLeft: 18 }}>{rec.conditions.map((c, i) => <li key={i} className="text-sm">{c}</li>)}</ul></Section>}
      <Section title="What happens to the applicant's cash flow if this loan is added" hint="Income, then expenses, then existing commitments, then what is left. The assessment rate is the loan rate plus the buffer.">
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit,minmax(160px,1fr))', gap: 10 }} aria-label="Cash flow with the loan">
          <Stat label="Income a month" value={<Money v={cf.income_monthly} />} /><Stat label="Expenses a month" value={<Money v={cf.expenses_monthly} />} sub={`of which existing debts ${fmtAUD(cf.existing_commitments_monthly)}`} />
          <Stat label="Surplus today" value={<Money v={cf.surplus_before} strong />} />
          <Stat label="New repayment" value={<Money v={cf.new_repayment_actual} />} sub={`at the loan rate; ${fmtAUD(cf.new_repayment_assessed)} at ${fmtPct(cf.assessment_rate)}`} />
          <Stat label="Surplus after (loan rate)" value={<Money v={cf.surplus_after_actual} strong />} />
          <Stat label="Surplus after (assessment rate)" value={<Money v={cf.surplus_after_assessed} strong />} sub={cf.surplus_after_assessed_pct_of_income != null ? `${cf.surplus_after_assessed_pct_of_income}% of income` : ''} tone={Number(cf.surplus_after_assessed) < 0 ? 'danger' : undefined} />
        </div>
      </Section>
      <Section title="Why this score" hint="Nine factors with fixed maximum points that add up to 100. Nothing is hidden.">
        <table className="data-table" aria-label="Score factors"><thead><tr><th>Factor</th><th style={{ width: 200 }}>Points</th><th>Why</th></tr></thead>
          <tbody>{(r.factors || []).map(f => (
            <tr key={f.key}><td>{f.label}</td>
              <td><div className="flex items-center gap-1"><div role="img" aria-label={`${f.points} of ${f.max} points`} style={{ flex: 1, height: 8, background: 'var(--border)', borderRadius: 4 }}><div style={{ width: `${(f.points / f.max) * 100}%`, height: 8, borderRadius: 4, background: f.points / f.max >= 0.6 ? 'var(--success)' : f.points / f.max >= 0.3 ? 'var(--warning)' : 'var(--danger)' }} /></div><span className="mono text-sm" style={{ minWidth: 56, textAlign: 'right' }}>{f.points} / {f.max}</span></div></td>
              <td className="text-sm">{f.detail}</td></tr>))}
            {(r.adjustments || []).map((x, i) => <tr key={`a${i}`}><td>{x.label}</td><td className="mono">{x.points ? x.points : 'cap'}</td><td className="text-sm">{x.detail}</td></tr>)}
            <tr><td><strong>Total</strong></td><td className="mono"><strong>{a.score} / 100</strong></td><td className="text-sm">Grade {a.grade}: {r.band}. A 80+, B 65+, C 50+, D 35+, E below.</td></tr></tbody></table>
      </Section>
      {(r.flags || []).length > 0 && <Section title="Risk flags">{r.flags.map((f, i) => <div key={i} className="text-sm" style={{ color: SEV[f.severity] }}>{f.severity === 'high' ? '▲▲ ' : '▲ '}{f.text}</div>)}</Section>}
      {(r.missing_info || []).length > 0 && <Notice items={r.missing_info.map(m => `Missing: ${m}`)} />}
      {Number(r.declared_commitments_added) > 0 && <div className="text-sm text-muted">Declared debts of {fmtAUD(r.declared_commitments_added)} a month that the statements do not show were added (never counted twice).</div>}
      {r.key_factors && (r.key_factors.strengths?.length > 0 || r.key_factors.concerns?.length > 0) && (
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit,minmax(280px,1fr))', gap: 12, marginTop: 8 }}>
          <div><div className="text-sm" style={{ fontWeight: 600 }}>Strengths</div>{(r.key_factors.strengths || []).map((s, i) => <div key={i} className="text-xs">✓ {s.label}</div>)}</div>
          <div><div className="text-sm" style={{ fontWeight: 600 }}>Concerns</div>{(r.key_factors.concerns || []).map((s, i) => <div key={i} className="text-xs">• {s.label}</div>)}</div></div>)}
    </div>)
}
