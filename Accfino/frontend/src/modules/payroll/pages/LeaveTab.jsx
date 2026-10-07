import React, { useState } from 'react'
import * as api from '../lib/payrollApi.js'
import { ImportButton } from '../components/CsvImport.jsx'
import { act, Async, DataGrid, Grid, Input, Modal, Select, Section, StatusBadge, useConfirm, useForm, useLoad } from '../components/kit.jsx'
import { fmtDate, fmtHours } from '../lib/format.js'

export default function LeaveTab({ me, mine = false, onChanged }) {
  const [status, setStatus] = useState('')
  const [asking, setAsking] = useState(false)
  const [dialog, confirm] = useConfirm()
  const q = useLoad(() => api.leaveRequests({ status: status || undefined, mine: mine || undefined }), [status, mine])
  const bal = useLoad(() => (me.self_service ? api.myLeaveBalances().catch(() => []) : Promise.resolve([])), [me.self_service])
    const doit = async (fn, ok) => { if (await act(fn, ok)) { q.reload(); bal.reload(); onChanged?.() } }
  const reject = async r => { const c = await confirm({ title: 'Reject leave', confirmLabel: 'Reject', reasonLabel: 'Reason for rejecting', message: `Reject ${r.employee}'s ${r.leave_type} request?` }); if (c.ok) doit(() => api.decideLeave(r.id, false, c.reason), 'Rejected') }
  const cancel = async r => { const c = await confirm({ title: 'Cancel leave request', danger: true, confirmLabel: 'Cancel request', message: `Cancel this ${r.leave_type} request (${fmtDate(r.start_date)} – ${fmtDate(r.end_date)})?` }); if (c.ok) doit(() => api.cancelLeave(r.id), 'Cancelled') }
  return (
    <div>
      {dialog}
      <div className="flex items-center justify-between" style={{ marginBottom: 12 }}><h3 style={{ margin: 0 }}>Leave</h3>
        <div className="flex gap-1">{!mine && me.capabilities.includes('leave_manage') && <ImportButton entities={['leave_requests']} onDone={() => { q.reload(); bal.reload(); onChanged?.() }} />}
          <button className="btn btn-primary" onClick={() => setAsking(true)}>+ Request leave</button></div></div>
      {mine && me.approver && <p className="text-sm text-muted" style={{ margin: '0 0 8px' }}>Your leave requests are approved by <b>{me.approver}</b>. You'll get a notification when they are decided.</p>}
      {me.self_service && <Section title="My leave balances"><Async q={bal}>{rows => <DataGrid rows={rows} rowKey="leave_type_id" empty="No leave balances yet" columns={[{ key: 'name', label: 'Leave type' }, { key: 'balance', label: 'Balance (h)', hours: true }, { key: 'committed', label: 'Requested (h)', hours: true }, { key: 'available', label: 'Available (h)', hours: true }]} />}</Async></Section>}
      <Async q={q}>{rows => <DataGrid rows={rows} searchKeys={['employee', 'leave_type', 'status']} empty="No leave requests"
        toolbar={<select className="input input-sm" aria-label="Status filter" value={status} onChange={e => setStatus(e.target.value)} style={{ maxWidth: 160 }}><option value="">All statuses</option>{['pending', 'approved', 'rejected', 'cancelled'].map(s => <option key={s} value={s}>{s}</option>)}</select>}
        columns={[{ key: 'employee', label: 'Employee' }, { key: 'leave_type', label: 'Leave' }, { key: 'start_date', label: 'From', date: true }, { key: 'end_date', label: 'To', date: true }, { key: 'hours', label: 'Hours', hours: true },
          { key: 'reason', label: 'Reason' }, { key: 'status', label: 'Status', render: r => <><StatusBadge status={r.status} />{r.paid && <span className="badge badge-success" style={{ marginLeft: 4 }}>paid</span>}{r.decision_note && <div className="text-xs text-muted">{r.decision_note}</div>}</> },
          { key: 'x', label: '', render: r => <span className="flex gap-1">
            {r.status === 'pending' && r.can_decide && !mine && <><button className="btn btn-success btn-xs" onClick={() => doit(() => api.decideLeave(r.id, true), 'Approved')}>Approve</button><button className="btn btn-outline btn-xs" onClick={() => reject(r)}>Reject</button></>}
            {['pending', 'approved'].includes(r.status) && !r.paid && <button className="btn btn-ghost btn-xs" onClick={() => cancel(r)}>Cancel</button>}</span> }]} />}</Async>
      {asking && <Request me={me} onClose={() => setAsking(false)} onSaved={() => { setAsking(false); q.reload(); bal.reload(); onChanged?.() }} />}
    </div>
  )
}

function Request({ me, onClose, onSaved }) {
  const d = useLoad(async () => { const [types, emps] = await Promise.all([api.leaveTypes.list(), me.is_payroll_staff ? api.employees({ status: 'active', limit: 200 }) : Promise.resolve({ items: [] })]); return { types: types.filter(t => t.is_active), emps: emps.items } }, [])
  const [f, set] = useForm({ employee_id: '', leave_type_id: '', start_date: '', end_date: '', hours: '', reason: '' })
  const go = async () => {
    const b = { leave_type_id: Number(f.leave_type_id), start_date: f.start_date, end_date: f.end_date || f.start_date, hours: f.hours || null, reason: f.reason }
    if (f.employee_id) b.employee_id = Number(f.employee_id)
    if (await act(() => api.requestLeave(b), 'Leave requested')) onSaved()
  }
  return (
    <Modal title="Request leave" onClose={onClose} width={520}>
      <Async q={d}>{x => (
        <>
          {me.is_payroll_staff && <Select label="Employee" value={f.employee_id} onChange={set('employee_id')} blank={me.self_service ? 'Myself' : 'Choose…'} options={x.emps.map(e => ({ value: e.id, label: `${e.employee_number} ${e.name}` }))} />}
          <Select label="Leave type" value={f.leave_type_id} onChange={set('leave_type_id')} blank="Choose…" options={x.types.map(t => ({ value: t.id, label: t.name }))} />
          <Grid cols={2}><Input label="From" type="date" value={f.start_date} onChange={set('start_date')} /><Input label="To" type="date" value={f.end_date} min={f.start_date} onChange={set('end_date')} /></Grid>
          <Input label="Hours (optional)" type="number" step="0.25" value={f.hours} onChange={set('hours')} hint="Blank = scheduled working hours in the range" />
          <Input label="Reason" value={f.reason} onChange={set('reason')} />
          {f.start_date && f.end_date && f.end_date < f.start_date && <div className="text-xs" style={{ color: 'var(--danger)' }}>The end date is before the start date</div>}
          <div className="flex gap-1" style={{ justifyContent: 'flex-end' }}><button className="btn btn-outline" onClick={onClose}>Cancel</button>
            <button className="btn btn-primary" disabled={!f.leave_type_id || !f.start_date || (f.end_date && f.end_date < f.start_date) || (me.is_payroll_staff && !me.self_service && !f.employee_id)} onClick={go}>Submit request</button></div>
        </>)}</Async>
    </Modal>
  )
}
