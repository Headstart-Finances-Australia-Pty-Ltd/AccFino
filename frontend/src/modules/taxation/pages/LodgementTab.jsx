import React, { useState } from 'react'
import * as api from '../lib/taxApi.js'
import { Async, DataGrid, Disclaimer, LODGE_NOTE, Section, Select, StatusBadge, useLoad } from '../components/kit.jsx'
import { fmtDate, label } from '../lib/format.js'

export default function LodgementTab({ fy, go }) {
  const bas = useLoad(() => api.bas.list({ fy }), [fy])
  const rets = useLoad(() => api.returns.list({ fy }), [fy])
  const fbts = useLoad(() => api.fbt.returns(), [])
  const [sel, setSel] = useState(null)
  const docs = [...(bas.data || []).filter(s => s.status !== 'void').map(s => ({ key: `bas_statement:${s.id}`, kind: 'bas_statement', id: s.id, title: `${s.kind.toUpperCase()} ${fmtDate(s.period_start)} – ${fmtDate(s.period_end)}`, status: s.status, ref: s.lodgement_reference, tab: 'gst' })),
    ...(rets.data || []).filter(s => s.status !== 'void').map(r => ({ key: `tax_return:${r.id}`, kind: 'tax_return', id: r.id, title: `Income tax return ${r.fy} v${r.version}`, status: r.status, ref: r.lodgement_reference, tab: 'taxreturn' })),
    ...(fbts.data || []).filter(s => s.status !== 'void').map(r => ({ key: `fbt_return:${r.id}`, kind: 'fbt_return', id: r.id, title: `FBT return ${r.fbt_year}`, status: r.status, ref: r.lodgement_reference, tab: 'fbt' }))]
  return (
    <div style={{ padding: 16 }}>
      <Disclaimer />
      <div className="alert alert-info" style={{ marginBottom: 12 }}><strong>How lodgement works in AccFino.</strong> {LODGE_NOTE} Submitting directly from AccFino would need ATO Digital Service Provider onboarding, which is not in place, so this screen is a checklist and a record — not a submission.</div>
      <Section title="Documents">
        <DataGrid rows={docs} rowKey="key" empty="No documents yet for this year" hint="Prepare an activity statement or return first." onRowClick={d => setSel(d)} columns={[{ key: 'title', label: 'Document' }, { key: 'status', label: 'Status', render: d => <StatusBadge status={d.status} /> }, { key: 'ref', label: 'ATO reference' }]} />
      </Section>
      {sel && <Readiness doc={sel} go={go} />}
    </div>)
}

function Readiness({ doc, go }) {
  const q = useLoad(() => api.readiness(doc.kind, doc.id), [doc.key, doc.status])
  return (
    <Section title={`Readiness: ${doc.title}`} actions={<button className="btn btn-outline btn-sm" onClick={() => go(doc.tab)}>Open document</button>}>
      <Async q={q}>{r => <>
        {r.checks.map(c => <div key={c.key} className="text-sm" style={{ padding: '2px 0', color: c.ok ? 'var(--success)' : 'var(--warning)' }}>{c.ok ? '✔' : '○'} {c.label}{!c.ok && c.detail ? <span className="text-xs text-muted"> — {c.detail}</span> : null}</div>)}
        <div className="text-sm" style={{ marginTop: 8 }}>{r.already_lodged ? 'Already recorded as lodged.' : r.ready ? 'Ready: lodge outside AccFino, then record the receipt reference on the document.' : 'Not ready: complete the unticked items.'}</div></>}</Async>
    </Section>)
}
