import React, { useState } from 'react'
import * as api from '../lib/payrollApi.js'
import { act, Async, DataGrid, Modal, Money, Stat, StatusBadge, useLoad, Input } from '../components/kit.jsx'
import { fmtAUD, label } from '../lib/format.js'

export default function SuperTab({ me }) {
  const [status, setStatus] = useState('pending')
  const [sel, setSel] = useState([])
  const [ref, setRef] = useState(null)
  const q = useLoad(() => api.superList({ status: status || undefined }), [status])
  const can = me.capabilities.includes('payments_manage')
  const toggle = id => setSel(s => (s.includes(id) ? s.filter(x => x !== id) : [...s, id]))
  return (
    <div>
      <h3 style={{ marginTop: 0 }}>Superannuation</h3>
      <div className="alert alert-warning">Under Payday Super each contribution must reach the fund within 7 business days of payday. Due dates here do not allow for public holidays, so they can fall a day early. Record payment once your clearing house confirms it.</div>
      <Async q={q}>{d => (
        <>
          <div className="stats-grid" style={{ marginBottom: 12 }}>
            <Stat label="All contributions" value={fmtAUD(d.totals.all)} /><Stat label="Unpaid" value={fmtAUD(d.totals.pending)} /><Stat label="Overdue" value={fmtAUD(d.totals.overdue)} tone={Number(d.totals.overdue) > 0 ? 'danger' : undefined} /><Stat label="Paid" value={fmtAUD(d.totals.paid)} />
          </div>
          <DataGrid rows={d.items} searchKeys={['employee', 'fund', 'employee_number']} empty="No super contributions" hint="They are created when a pay run is finalised"
            toolbar={<><select className="input input-sm" aria-label="Status filter" value={status} onChange={e => { setStatus(e.target.value); setSel([]) }} style={{ maxWidth: 160 }}><option value="">All</option><option value="pending">Unpaid</option><option value="overdue">Overdue</option><option value="paid">Paid</option></select>
              {can && <button className="btn btn-primary btn-sm" disabled={!sel.length} onClick={() => setRef('')}>Mark {sel.length || ''} as paid…</button>}</>}
            columns={[...(can ? [{ key: 'sel', label: '', render: r => r.status === 'pending' && <input type="checkbox" aria-label={`Select ${r.employee}`} checked={sel.includes(r.id)} onChange={() => toggle(r.id)} /> }] : []),
              { key: 'employee', label: 'Employee' }, { key: 'fund', label: 'Fund' }, { key: 'component', label: 'Component', render: r => label(r.component) }, { key: 'amount', label: 'Amount', money: true },
              { key: 'due_date', label: 'Due', date: true }, { key: 'status', label: 'Status', render: r => <StatusBadge status={r.overdue ? 'overdue' : r.status} /> }, { key: 'payment_ref', label: 'Reference' }]} />
        </>)}</Async>
      {ref !== null && <Modal title="Record super payment" onClose={() => setRef(null)} width={460}>
        <p>{sel.length} contribution(s) will be marked as paid.</p><Input label="Payment reference" value={ref} onChange={e => setRef(e.target.value)} hint="From your clearing house or bank" />
        <div className="flex gap-1" style={{ justifyContent: 'flex-end' }}><button className="btn btn-outline" onClick={() => setRef(null)}>Cancel</button>
          <button className="btn btn-primary" disabled={!ref.trim()} onClick={async () => { if (await act(() => api.superMarkPaid(sel, ref), 'Marked as paid')) { setRef(null); setSel([]); q.reload() } }}>Mark as paid</button></div></Modal>}
    </div>
  )
}
