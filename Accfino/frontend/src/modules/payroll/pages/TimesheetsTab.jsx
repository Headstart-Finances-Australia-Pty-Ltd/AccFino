import React, { useMemo, useState } from 'react'
import * as api from '../lib/payrollApi.js'
import { ImportButton } from '../components/CsvImport.jsx'
import { act, Async, DataGrid, Field, Grid, Input, Modal, Select, StatusBadge, useConfirm, useLoad } from '../components/kit.jsx'
import { fmtDate, fmtHours, todayISO } from '../lib/format.js'

const mondayOf = iso => { const d = new Date(iso + 'T00:00:00'); d.setDate(d.getDate() - ((d.getDay() + 6) % 7)); return d.toISOString().slice(0, 10) }
const addDays = (iso, n) => { const d = new Date(iso + 'T00:00:00'); d.setDate(d.getDate() + n); return d.toISOString().slice(0, 10) }
export const timesheetProblems = (lines, week) => {
  const p = []
  const perDay = {}
  lines.forEach((l, i) => {
    const h = Number(l.hours)
    if (!l.pay_item_id) p.push(`Line ${i + 1}: choose a pay category`)
    if (!(h > 0)) p.push(`Line ${i + 1}: hours must be greater than zero`)
    if (h > 24) p.push(`Line ${i + 1}: more than 24 hours`)
    if (l.work_date < week || l.work_date > addDays(week, 6)) p.push(`Line ${i + 1}: date is outside the week`)
    perDay[l.work_date] = (perDay[l.work_date] || 0) + h
  })
  Object.entries(perDay).forEach(([d, h]) => { if (h > 24) p.push(`${d}: more than 24 hours across lines`) })
  if (lines.length === 0) p.push('Add at least one line')
  return p
}

export default function TimesheetsTab({ me, mine = false, onChanged }) {
  const [status, setStatus] = useState('')
  const [edit, setEdit] = useState(null)
  const [dialog, confirm] = useConfirm()
  const q = useLoad(() => api.timesheets({ status: status || undefined, mine: mine || undefined }), [status, mine])
  const can = c => me.capabilities.includes(c)
  const doit = async (fn, ok) => { if (await act(fn, ok)) { q.reload(); onChanged?.() } }
  const reject = async t => { const c = await confirm({ title: 'Reject timesheet', confirmLabel: 'Reject', reasonLabel: 'Reason', message: `Reject ${t.employee}'s timesheet for the week of ${fmtDate(t.week_start)}?` }); if (c.ok) doit(() => api.timesheetAction(t.id, 'reject', { reason: c.reason }), 'Rejected') }
  const del = async t => { const c = await confirm({ title: 'Delete timesheet', danger: true, confirmLabel: 'Delete', message: 'Delete this timesheet? This cannot be undone.' }); if (c.ok) doit(() => api.deleteTimesheet(t.id), 'Deleted') }
  return (
    <div>
      {dialog}
      <div className="flex items-center justify-between" style={{ marginBottom: 12 }}><h3 style={{ margin: 0 }}>Timesheets</h3>
        <div className="flex gap-1">{!mine && can('timesheets_manage') && <ImportButton entities={['timesheets']} onDone={() => { q.reload(); onChanged?.() }} />}
          <button className="btn btn-primary" onClick={() => setEdit({})}>+ New timesheet</button></div></div>
      {mine && me.approver && <p className="text-sm text-muted" style={{ margin: '0 0 8px' }}>Your timesheets are approved by <b>{me.approver}</b>. You'll get a notification when they are decided.</p>}
      <Async q={q}>{rows => <DataGrid rows={rows} searchKeys={['employee', 'employee_number', 'status']} empty="No timesheets" hint="Hourly employees record their hours here; approved hours flow into the pay run"
        toolbar={<select className="input input-sm" aria-label="Status filter" value={status} onChange={e => setStatus(e.target.value)} style={{ maxWidth: 160 }}><option value="">All statuses</option>{['draft', 'submitted', 'approved', 'rejected', 'processed'].map(s => <option key={s} value={s}>{s}</option>)}</select>}
        columns={[{ key: 'employee_number', label: 'No.' }, { key: 'employee', label: 'Employee' }, { key: 'week_start', label: 'Week of', date: true }, { key: 'o', label: 'Ordinary', hours: true, render: t => fmtHours(t.totals.ordinary) }, { key: 'ot', label: 'Overtime', hours: true, render: t => fmtHours(t.totals.overtime) },
          { key: 'l', label: 'Leave', hours: true, render: t => fmtHours(t.totals.leave) }, { key: 'status', label: 'Status', render: t => <><StatusBadge status={t.status} />{t.reject_reason && <div className="text-xs" style={{ color: 'var(--danger)' }}>{t.reject_reason}</div>}</> },
          { key: 'x', label: '', render: t => (
            <span className="flex gap-1" onClick={e => e.stopPropagation()}>
              {['draft', 'rejected'].includes(t.status) && t.can_edit !== false && <><button className="btn btn-outline btn-xs" onClick={() => setEdit(t)}>Edit</button><button className="btn btn-primary btn-xs" onClick={() => doit(() => api.timesheetAction(t.id, 'submit'), 'Submitted')}>Submit</button><button className="btn btn-ghost btn-xs" onClick={() => del(t)}>Delete</button></>}
              {t.status === 'submitted' && t.can_decide && !mine && <><button className="btn btn-success btn-xs" onClick={() => doit(() => api.timesheetAction(t.id, 'approve'), 'Approved')}>Approve</button><button className="btn btn-outline btn-xs" onClick={() => reject(t)}>Reject</button></>}
              {['approved', 'submitted'].includes(t.status) && can('timesheets_approve') && !mine && <button className="btn btn-ghost btn-xs" onClick={() => doit(() => api.timesheetAction(t.id, 'reopen'), 'Returned to draft')}>Reopen</button>}
              {(t.status === 'approved' || t.status === 'processed') && <button className="btn btn-ghost btn-xs" onClick={() => setEdit({ ...t, view: true })}>View</button>}
            </span>) }]} />}</Async>
      {edit && <Editor me={me} base={edit} onClose={() => setEdit(null)} onSaved={() => { setEdit(null); q.reload(); onChanged?.() }} />}
    </div>
  )
}

function Editor({ me, base, onClose, onSaved }) {
  const data = useLoad(async () => {
    const [emps, items, ts] = await Promise.all([api.employees({ limit: 200 }), api.payItems.list().catch(() => []), base.id ? api.timesheet(base.id) : Promise.resolve(null)])
    return { emps: emps.items.filter(e => e.pay_basis === 'hourly' && e.status === 'active'), items: items.filter(i => i.calc_method === 'hours_x_rate' && ['earnings', 'overtime', 'penalty', 'leave'].includes(i.kind) && i.is_active), ts }
  }, [base.id])
  const [emp, setEmp] = useState(base.employee_id || '')
  const [week, setWeek] = useState(base.week_start || mondayOf(todayISO()))
  const [lines, setLines] = useState(null)
  const L = lines ?? (data.data?.ts?.lines || []).map(l => ({ work_date: l.work_date, pay_item_id: l.pay_item_id, leave_type_id: l.leave_type_id, hours: l.hours, break_minutes: l.break_minutes, start_time: l.start_time || '', end_time: l.end_time || '', notes: l.notes || '' }))
  const ro = !!base.view
  const upd = (i, k, v) => setLines(L.map((l, j) => (j === i ? { ...l, [k]: v } : l)))
  const problems = useMemo(() => timesheetProblems(L, week), [L, week])
  const total = L.reduce((s, l) => s + Number(l.hours || 0), 0)
  const save = async submit => {
    const body = { employee_id: emp ? Number(emp) : undefined, week_start: week, lines: L.map(l => ({ ...l, hours: l.hours, break_minutes: Number(l.break_minutes || 0), start_time: l.start_time || null, end_time: l.end_time || null })) }
    const ts = await act(() => api.saveTimesheet(body, base.id), 'Timesheet saved')
    if (ts && submit) await act(() => api.timesheetAction(ts.id, 'submit'), 'Submitted for approval')
    if (ts) onSaved()
  }
  return (
    <Modal title={base.id ? `Timesheet · ${base.employee} · week of ${fmtDate(base.week_start)}` : 'New timesheet'} onClose={onClose} width={860}>
      <Async q={data}>{d => (
        <>
          {!base.id && <Grid cols={2}>
            {(me.capabilities.includes('timesheets_approve') || me.capabilities.includes('timesheets_manage')) && !me.self_service || d.emps.length > 1 ? <Select label="Employee" value={emp} onChange={e => setEmp(e.target.value)} blank="Choose…" options={d.emps.map(e => ({ value: e.id, label: `${e.employee_number} ${e.name}` }))} /> : null}
            <Input label="Week (any day in the week)" type="date" value={week} onChange={e => setWeek(mondayOf(e.target.value))} hint={`Week runs ${fmtDate(week)} – ${fmtDate(addDays(week, 6))}`} /></Grid>}
          <table className="summary-table"><thead><tr><th>Date</th><th>Pay category</th><th>Hours</th><th>Break (min)</th><th>Notes</th><th /></tr></thead>
            <tbody>{L.map((l, i) => (
              <tr key={i}>
                <td><input className="input input-sm" type="date" aria-label={`Line ${i + 1} date`} value={l.work_date} min={week} max={addDays(week, 6)} disabled={ro} onChange={e => upd(i, 'work_date', e.target.value)} /></td>
                <td><select className="input input-sm" aria-label={`Line ${i + 1} pay category`} value={l.pay_item_id} disabled={ro} onChange={e => upd(i, 'pay_item_id', Number(e.target.value))}><option value="">Choose…</option>{d.items.map(it => <option key={it.id} value={it.id}>{it.name}</option>)}</select></td>
                <td><input className="input input-sm" style={{ width: 80 }} type="number" step="0.25" min="0" max="24" aria-label={`Line ${i + 1} hours`} value={l.hours} disabled={ro} onChange={e => upd(i, 'hours', e.target.value)} /></td>
                <td><input className="input input-sm" style={{ width: 80 }} type="number" min="0" aria-label={`Line ${i + 1} break`} value={l.break_minutes} disabled={ro} onChange={e => upd(i, 'break_minutes', e.target.value)} /></td>
                <td><input className="input input-sm" aria-label={`Line ${i + 1} notes`} value={l.notes} disabled={ro} onChange={e => upd(i, 'notes', e.target.value)} /></td>
                <td>{!ro && <button className="btn btn-ghost btn-xs" onClick={() => setLines(L.filter((_, j) => j !== i))}>✕</button>}</td></tr>))}</tbody></table>
          <div className="flex items-center justify-between" style={{ marginTop: 8 }}>
            {!ro && <button className="btn btn-outline btn-sm" onClick={() => setLines([...L, { work_date: week, pay_item_id: d.items.find(i => i.code === 'ORD')?.id || '', hours: '', break_minutes: 0, start_time: '', end_time: '', notes: '' }])}>+ Add line</button>}
            <b>Total {fmtHours(total)} h</b></div>
          {problems.length > 0 && !ro && L.length > 0 && <div role="alert" className="alert alert-error" style={{ marginTop: 8 }}>{problems.map(p => <div key={p}>{p}</div>)}</div>}
          {!ro && <div className="flex gap-1" style={{ marginTop: 12, justifyContent: 'flex-end' }}>
            <button className="btn btn-outline" onClick={onClose}>Cancel</button>
            <button className="btn btn-outline" disabled={problems.length > 0 || (!base.id && !emp && d.emps.length > 1)} onClick={() => save(false)}>Save draft</button>
            <button className="btn btn-primary" disabled={problems.length > 0 || (!base.id && !emp && d.emps.length > 1)} onClick={() => save(true)}>Save & submit</button></div>}
        </>)}</Async>
    </Modal>
  )
}
