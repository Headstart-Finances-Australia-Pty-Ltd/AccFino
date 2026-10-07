import React, { useState } from 'react'
import * as api from '../lib/taxApi.js'
import { act, Async, DataGrid, Disclaimer, Input, Section, StatusBadge, useLoad } from '../components/kit.jsx'
import { saveBlob } from '../lib/format.js'

const range = fy => [`${fy.slice(0, 4)}-07-01`, `${Number(fy.slice(0, 4)) + 1}-06-30`]

export default function ReportsTab({ fy }) {
  const [from, setFrom] = useState(range(fy)[0])
  const [to, setTo] = useState(range(fy)[1])
  const [applied, setApplied] = useState([range(fy)[0], range(fy)[1]])
  const q = useLoad(() => api.reconcile(applied[0], applied[1]), [applied.join()])
  const exp = async what => { const r = await act(() => api.exportCsv({ what, fy })); if (r) saveBlob(`${what}_${fy}.csv`, r) }
  const xlsx = async () => { const r = await act(() => api.exportXlsx(fy)); if (r) saveBlob(`tax_summary_${fy}.xlsx`, r) }
  return (
    <div style={{ padding: 16 }}>
      <Disclaimer />
      <Section title="Tax reconciliation" hint="Cross-checks AccFino’s own sources (ledger, payroll, activity statements). Agreement does not prove the figures are right for tax; a difference needs an explanation in a workpaper.">
        <div className="flex gap-1 items-center" style={{ flexWrap: 'wrap', marginBottom: 8 }}><Input label="From" type="date" value={from} onChange={e => setFrom(e.target.value)} /><Input label="To" type="date" value={to} onChange={e => setTo(e.target.value)} />
          <button className="btn btn-outline btn-sm" onClick={() => setApplied([from, to])} disabled={!from || !to || to < from}>Run</button></div>
        <Async q={q}>{r => <>
          <div className="text-sm" style={{ marginBottom: 6 }}>{r.rows.length === 0 ? 'Nothing to reconcile in this period.' : r.all_ok ? '✔ All checks agree.' : '▲ Some checks differ.'}</div>
          <DataGrid rows={r.rows} rowKey="key" empty="No checks apply" columns={[{ key: 'label', label: 'Check', render: x => <>{x.label}<div className="text-xs text-muted">{x.explanation}</div></> }, { key: 'a', label: 'Figure A', money: true }, { key: 'b', label: 'Figure B', money: true },
            { key: 'difference', label: 'Difference', money: true }, { key: 'status', label: 'Result', render: x => <StatusBadge status={x.status} text={x.status === 'ok' ? 'Agrees' : 'Differs'} /> }]} /></>}</Async>
      </Section>
      <Section title={`Exports ${fy}`} hint="CSV cells that start with = + - @ are neutralised so spreadsheets cannot run them.">
        <div className="flex gap-1" style={{ flexWrap: 'wrap' }}><button className="btn btn-outline btn-sm" onClick={xlsx}>Summary pack (Excel)</button><button className="btn btn-outline btn-sm" onClick={() => exp('adjustments')}>Adjustments (CSV)</button>
          <button className="btn btn-outline btn-sm" onClick={() => exp('cgt')}>CGT events (CSV)</button><button className="btn btn-outline btn-sm" onClick={() => exp('obligations')}>Obligations (CSV)</button><button className="btn btn-outline btn-sm" onClick={() => exp('audit')}>Audit trail (CSV)</button></div>
        <p className="text-xs text-muted">Activity statement figures export from the statement itself (BAS tab).</p>
      </Section>
    </div>)
}
