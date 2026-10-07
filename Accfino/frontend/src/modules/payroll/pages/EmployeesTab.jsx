import React, { useState } from 'react'
import * as api from '../lib/payrollApi.js'
import { DataGrid, Money, StatusBadge, useLoad, Async, Select } from '../components/kit.jsx'
import EmployeeEditor from '../components/EmployeeEditor.jsx'
import { label } from '../lib/format.js'
import { ImportButton } from '../components/CsvImport.jsx'

export function useRefs() {
  return useLoad(async () => {
    const [departments, locations, calendars, funds, items, leaveTypes, emps] = await Promise.all([
      api.departments.list().catch(() => []), api.locations.list().catch(() => []), api.calendars().catch(() => []), api.funds.list().catch(() => []),
      api.payItems.list().catch(() => []), api.leaveTypes.list().catch(() => []), api.employees({ limit: 200 }).catch(() => ({ items: [] }))])
    return { departments, locations, calendars, funds, items, leaveTypes, managers: emps.items }
  }, [])
}

export default function EmployeesTab({ me }) {
  const [status, setStatus] = useState('')
  const [editing, setEditing] = useState(null)       // null | 'new' | id
  const q = useLoad(() => api.employees({ status: status || undefined, limit: 200 }), [status])
  const refsQ = useRefs()
  const canManage = me.capabilities.includes('employees_manage')
  const canSeePay = q.data?.items?.some(e => e.annual_salary !== undefined || e.hourly_rate !== undefined)
  const dept = id => refsQ.data?.departments.find(d => d.id === id)?.name || '—'
  const cols = [
    { key: 'employee_number', label: 'No.' }, { key: 'name', label: 'Name' }, { key: 'position', label: 'Position' },
    { key: 'department_id', label: 'Department', render: r => dept(r.department_id), sortValue: r => dept(r.department_id) },
    { key: 'employment_type', label: 'Type', render: r => label(r.employment_type) }, { key: 'pay_frequency', label: 'Paid', render: r => label(r.pay_frequency) },
    ...(canSeePay ? [{ key: 'pay', label: 'Rate', align: 'right', sortValue: r => Number(r.annual_salary || r.hourly_rate || 0), render: r => (r.pay_basis === 'salary' ? <><Money v={r.annual_salary} /> <span className="text-xs text-muted">pa</span></> : <><Money v={r.hourly_rate} /> <span className="text-xs text-muted">/h</span></>) }] : []),
    { key: 'status', label: 'Status', render: r => <StatusBadge status={r.status} /> },
  ]
  return (
    <div>
      <div className="flex items-center justify-between" style={{ marginBottom: 12 }}>
        <h3 style={{ margin: 0 }}>Employees</h3>
        <div className="flex gap-1">
          {canManage && <ImportButton entities={['employees', 'employee_tax', 'employee_super', 'employee_bank', 'employee_items', 'leave_balances']} title="Import employees from CSV" onDone={() => { q.reload(); refsQ.reload() }} />}
          {canManage && <button className="btn btn-primary" onClick={() => setEditing('new')} disabled={!refsQ.data}>+ New employee</button>}
        </div>
      </div>
      <Async q={q}>{d => (
        <DataGrid rows={d.items} searchKeys={['name', 'employee_number', 'position']} empty="No employees yet" hint={canManage ? 'Add your first employee to get started' : undefined}
          onRowClick={r => setEditing(r.id)} columns={cols}
          toolbar={<select className="input input-sm" aria-label="Status filter" value={status} onChange={e => setStatus(e.target.value)} style={{ maxWidth: 160 }}><option value="">All statuses</option><option value="active">Active</option><option value="terminated">Terminated</option><option value="inactive">Inactive</option></select>} />)}</Async>
      {editing && refsQ.data && <EmployeeEditor id={editing === 'new' ? null : editing} me={me} refs={refsQ.data} onClose={() => { setEditing(null); q.reload() }} onSaved={() => q.reload()} />}
    </div>
  )
}
