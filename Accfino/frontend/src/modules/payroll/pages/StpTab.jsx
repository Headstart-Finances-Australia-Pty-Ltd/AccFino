import React, { useState } from 'react'
import * as api from '../lib/payrollApi.js'
import { act, Async, DataGrid, Modal, Money, Section, Select, StatusBadge, useConfirm, useLoad } from '../components/kit.jsx'
import { fmtDate, fyLabel, label } from '../lib/format.js'

export default function StpTab({ me }) {
  const [view, setView] = useState(null)
  const [fy, setFy] = useState(fyLabel())
  const [dialog, confirm] = useConfirm()
  const ev = useLoad(() => api.stpList(), [])
  const fin = useLoad(() => api.stpFinalisation(fy), [fy])
  const [summary, setSummary] = useState(null)
  const FYS = [0, 1, 2].map(i => { const y = Number(fyLabel().slice(0, 4)) - i; return `${y}-${String(y + 1).slice(2)}` })
  const submit = async e => { const c = await confirm({ title: 'Mock submission', confirmLabel: 'Record mock submission', message: 'This only records a reference inside AccFino so you can test the workflow. It is NOT sent to the ATO.' }); if (c.ok && await act(() => api.stpMockSubmit(e.id), 'Mock submission recorded')) ev.reload() }
  return (
    <div>
      {dialog}
      <h3 style={{ marginTop: 0 }}>Single Touch Payroll</h3>
      <div className="alert alert-error"><b>AccFino does not lodge with the ATO.</b> These are STP-style pay events and finalisation data prepared for your review, with a mock submission that only records a reference. Lodge through ATO-certified software.</div>
      <Section title="Pay events"><Async q={ev}>{rows => <DataGrid rows={rows} empty="No STP events yet" hint="Prepare one from a finalised pay run" columns={[{ key: 'id', label: '#' }, { key: 'event_type', label: 'Type', render: r => label(r.event_type) }, { key: 'fy', label: 'FY' }, { key: 'employees', label: 'Employees', align: 'right' }, { key: 'gross', label: 'Gross', money: true },
        { key: 'status', label: 'Status', render: r => <><StatusBadge status={r.status} text={r.status === 'mock_submitted' ? 'Mock submitted' : 'Draft'} />{r.mock_reference && <div className="mono text-xs">{r.mock_reference}</div>}</> },
        { key: 'x', label: '', render: r => <span className="flex gap-1"><button className="btn btn-ghost btn-xs" onClick={() => setView(r.id)}>View payload</button>{r.status === 'draft' && me.capabilities.includes('stp_manage') && r.event_type !== 'finalisation' && <button className="btn btn-outline btn-xs" onClick={() => submit(r)}>Mock submit…</button>}</span> }]} />}</Async></Section>
      <Section title="Year-end finalisation" actions={<select className="input input-sm" aria-label="Financial year" value={fy} onChange={e => setFy(e.target.value)}>{FYS.map(f => <option key={f}>{f}</option>)}</select>}>
        <Async q={fin}>{d => (
          <>
            <div className="text-sm" style={{ marginBottom: 8 }}>{d.fy_ended ? 'Financial year has ended.' : 'This financial year has not ended: employees can be finalised after 30 June.'} {d.due_date && <>Finalisation due {fmtDate(d.due_date)}.</>} {d.open_runs > 0 && <b style={{ color: 'var(--danger)' }}>{d.open_runs} pay run(s) not yet finalised.</b>}</div>
            <DataGrid rows={d.employees} rowKey="employee_id" empty="No pays in this year" columns={[{ key: 'employee_number', label: 'No.' }, { key: 'name', label: 'Employee' }, { key: 'gross', label: 'Gross', money: true }, { key: 'tax', label: 'Tax', money: true }, { key: 'super', label: 'Super', money: true },
              { key: 'finalised', label: 'Finalised', render: r => <StatusBadge status={r.finalised ? 'finalised' : 'pending'} text={r.finalised ? 'Finalised' : 'Open'} /> },
              { key: 'x', label: '', render: r => <span className="flex gap-1"><button className="btn btn-ghost btn-xs" onClick={async () => { const s = await act(() => api.stpPaymentSummary(r.employee_id, d.fy)); if (s) setSummary(s) }}>Payment summary</button>
                {!r.finalised && d.fy_ended && d.open_runs === 0 && <button className="btn btn-outline btn-xs" onClick={async () => { if (await act(() => api.stpFinalise(d.fy, [r.employee_id]), 'Employee finalised')) fin.reload() }}>Finalise</button>}</span> }]} />
          </>)}</Async></Section>
      {view && <Payload id={view} onClose={() => setView(null)} />}
      {summary && <Modal title={`Payment summary ${summary.fy}`} onClose={() => setSummary(null)} width={520}>
        <p><b>{summary.employee}</b> ({summary.employee_number})<br />{summary.employer.name} · ABN {summary.employer.abn}</p>
        <table className="summary-table"><tbody><tr><td>Gross payments</td><td className="text-right"><Money v={summary.gross_payments} /></td></tr><tr><td>Tax withheld</td><td className="text-right"><Money v={summary.tax_withheld} /></td></tr><tr><td>Reportable employer super</td><td className="text-right"><Money v={summary.reportable_employer_super} /></td></tr></tbody></table>
        <p className="text-xs text-muted">{summary.note}</p></Modal>}
    </div>
  )
}
function Payload({ id, onClose }) {
  const q = useLoad(() => api.stpEvent(id), [id])
  return <Modal title={`STP event #${id}`} onClose={onClose} width={820}><Async q={q}>{e => <pre className="mono text-xs" style={{ maxHeight: 460, overflow: 'auto', background: 'var(--surface-2)', padding: 10 }}>{JSON.stringify(e.payload, null, 2)}</pre>}</Async></Modal>
}
