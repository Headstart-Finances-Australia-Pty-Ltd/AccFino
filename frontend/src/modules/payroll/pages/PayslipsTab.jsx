import React, { useState } from 'react'
import * as api from '../lib/payrollApi.js'
import { Async, DataGrid, useLoad } from '../components/kit.jsx'
import PayslipView from '../components/PayslipView.jsx'
import { fmtDate } from '../lib/format.js'

export function PayslipList({ mine, runId }) {
  const [open, setOpen] = useState(null)
  const q = useLoad(() => api.payslips({ mine: mine || undefined, run_id: runId || undefined }), [mine, runId])
  return (
    <div>
      <Async q={q}>{rows => <DataGrid rows={rows} searchKeys={['employee', 'employee_number', 'payslip_no']} empty="No payslips yet" hint="Payslips are created when a pay run is finalised" onRowClick={r => setOpen(r.id)}
        columns={[{ key: 'payslip_no', label: 'Payslip' }, { key: 'employee', label: 'Employee' }, { key: 'pay_date', label: 'Pay date', date: true }, { key: 'period_start', label: 'Period', render: r => `${fmtDate(r.period_start)} – ${fmtDate(r.period_end)}` },
          { key: 'gross', label: 'Gross', money: true }, { key: 'payg', label: 'Tax', money: true }, { key: 'net', label: 'Net', money: true }, { key: 'super', label: 'Super', money: true }]} />}</Async>
      {open && <PayslipView id={open} onClose={() => setOpen(null)} />}
    </div>
  )
}
export default function PayslipsTab() {
  return <div><h3 style={{ marginTop: 0 }}>Payslips</h3><PayslipList /></div>
}
