import React from 'react'
import * as api from '../lib/payrollApi.js'
import { Async, Section, useLoad } from '../components/kit.jsx'
import ReportTable from '../components/ReportTable.jsx'
import { fyLabel } from '../lib/format.js'

export function RulesPanel() {
  const q = useLoad(() => api.rules(), [])
  return <Async q={q}>{d => d.rule_sets.map(r => (
    <div key={r.id} className="card card-flat" style={{ marginBottom: 10 }}>
      <b>{r.label}</b><div className="text-sm text-muted">Effective {r.effective_from}{r.effective_to ? ` to ${r.effective_to}` : ''} · super guarantee {Number(r.sg_rate) * 100}% · max contribution base ${Number(r.max_contribution_base_annual).toLocaleString()} · super due {r.super_due_business_days} business days after payday · ETP cap ${Number(r.etp_cap).toLocaleString()}</div>
      <div className="text-sm">PAYG scales loaded: {r.scales.join(', ')}</div>
      {Object.entries(r.sources).map(([k, s]) => <div key={k} className="text-xs"><span className={`badge ${s.verified === 'primary' ? 'badge-success' : s.verified === 'unverified' ? 'badge-danger' : 'badge-warning'}`}>{s.verified}</span> {k}: {s.title}</div>)}
      <p className="text-xs text-muted" style={{ marginBottom: 0 }}>These rates are data in the statutory rules file, not code. Anything marked secondary or unverified should be checked against the ATO before relying on it.</p>
    </div>))}</Async>
}

export default function PaygTab() {
  const from = `${fyLabel().slice(0, 4)}-07-01`
  const q = useLoad(() => api.report('payg_withholding', { date_from: from }), [])
  return (
    <div>
      <h3 style={{ marginTop: 0 }}>PAYG withholding</h3>
      <Section title="Statutory rules in force"><RulesPanel /></Section>
      <Section title="Withholding this financial year"><Async q={q}>{rep => <ReportTable rep={rep} />}</Async></Section>
    </div>
  )
}
