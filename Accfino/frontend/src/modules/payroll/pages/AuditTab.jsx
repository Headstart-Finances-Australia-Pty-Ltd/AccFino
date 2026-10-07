import React, { useState } from 'react'
import * as api from '../lib/payrollApi.js'
import { Async, DataGrid, Grid, Input, Select, useLoad } from '../components/kit.jsx'

const ACTIONS = ['', 'employee.', 'payrun.', 'payment.', 'leave.', 'timesheet.', 'config.', 'payslip.', 'stp.', 'super.']
export default function AuditTab() {
  const [f, setF] = useState({ action: '', date_from: '', date_to: '' })
  const [open, setOpen] = useState(null)
  const q = useLoad(() => api.audit(Object.fromEntries(Object.entries(f).filter(([, v]) => v))), [f.action, f.date_from, f.date_to])
  return (
    <div>
      <h3 style={{ marginTop: 0 }}>Payroll audit trail</h3>
      <Grid cols={3}>
        <Select label="Area" value={f.action} onChange={e => setF({ ...f, action: e.target.value })} options={ACTIONS.map(a => ({ value: a, label: a ? a.replace('.', '') : 'All' }))} />
        <Input label="From" type="date" value={f.date_from} onChange={e => setF({ ...f, date_from: e.target.value })} /><Input label="To" type="date" value={f.date_to} onChange={e => setF({ ...f, date_to: e.target.value })} />
      </Grid>
      <Async q={q}>{rows => <DataGrid rows={rows} searchKeys={['user', 'action', 'entity_label', 'summary']} pageSize={30} empty="No audit events" onRowClick={r => setOpen(open === r.id ? null : r.id)}
        columns={[{ key: 'occurred_at', label: 'When (UTC)', render: r => r.occurred_at.replace('T', ' ').slice(0, 19) }, { key: 'user', label: 'User' }, { key: 'action', label: 'Action' }, { key: 'entity_label', label: 'Record', render: r => `${r.entity_type} ${r.entity_label || r.entity_id || ''}` },
          { key: 'summary', label: 'Summary', render: r => <div>{r.summary}{open === r.id && (r.before || r.after) && <div className="mono text-xs" style={{ marginTop: 6 }}>{r.before && <div>before: {JSON.stringify(r.before)}</div>}{r.after && <div>after: {JSON.stringify(r.after)}</div>}</div>}</div> }]} />}</Async>
    </div>
  )
}
