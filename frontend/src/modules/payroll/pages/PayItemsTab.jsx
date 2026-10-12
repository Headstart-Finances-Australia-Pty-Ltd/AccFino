import React, { useState } from 'react'
import * as api from '../lib/payrollApi.js'
import { act, Async, Check, DataGrid, Grid, Input, Modal, Select, StatusBadge, useConfirm, useForm, useLoad } from '../components/kit.jsx'
import { label } from '../lib/format.js'
import { ImportButton } from '../components/CsvImport.jsx'

const KINDS = ['earnings', 'overtime', 'penalty', 'allowance', 'bonus', 'commission', 'back_pay', 'leave', 'leave_loading', 'termination_leave', 'etp', 'salary_adjustment', 'unpaid_leave',
  'deduction_pretax', 'salary_sacrifice_super', 'deduction_posttax', 'employee_super_after_tax', 'employer_super_additional', 'reimbursement']
const GROUPS = { Earnings: ['earnings', 'overtime', 'penalty', 'allowance', 'bonus', 'commission', 'back_pay', 'leave', 'leave_loading', 'termination_leave', 'etp', 'salary_adjustment', 'unpaid_leave'],
  Deductions: ['deduction_pretax', 'salary_sacrifice_super', 'deduction_posttax'], Reimbursements: ['reimbursement'], Superannuation: ['employee_super_after_tax', 'employer_super_additional'] }
const EARN = GROUPS.Earnings

export default function PayItemsTab({ me }) {
  const [group, setGroup] = useState('Earnings')
  const [edit, setEdit] = useState(null)
  const [dialog, confirm] = useConfirm()
  const q = useLoad(() => api.payItems.list(), [])
  const can = me.capabilities.includes('items_manage')
  const rows = (q.data || []).filter(i => GROUPS[group].includes(i.kind))
  const remove = async i => {
    const c = await confirm({ title: 'Remove pay item', danger: true, confirmLabel: 'Remove', message: `Remove ${i.name}? If it has been used it is deactivated instead, so history is kept.` })
    if (c.ok) { const r = await act(() => api.payItems.remove(i.id), 'Done'); if (r) q.reload() }
  }
  return (
    <div>
      {dialog}
      <div className="flex items-center justify-between" style={{ marginBottom: 12 }}><h3 style={{ margin: 0 }}>Pay items</h3><div className="flex gap-1">{can && <ImportButton entities={['pay_items']} onDone={() => q.reload()} />}{can && <button className="btn btn-primary" onClick={() => setEdit({})}>+ New pay item</button>}</div></div>
      <div className="tabs-bar" style={{ marginBottom: 10 }}>{Object.keys(GROUPS).map(g => <button key={g} className={`tab-btn${group === g ? ' active' : ''}`} onClick={() => setGroup(g)}>{g}</button>)}</div>
      <Async q={q}>{() => <DataGrid rows={rows} searchKeys={['code', 'name']} empty="No pay items in this group" onRowClick={can ? setEdit : undefined}
        columns={[{ key: 'code', label: 'Code' }, { key: 'name', label: 'Name' }, { key: 'kind', label: 'Type', render: i => label(i.kind) }, { key: 'calc_method', label: 'Calculation', render: i => label(i.calc_method) + (i.calc_method === 'hours_x_rate' && Number(i.multiplier) !== 1 ? ` ×${Number(i.multiplier)}` : '') },
          { key: 'payg_treatment', label: 'Tax', render: i => (i.taxable ? label(i.payg_treatment) : 'Not taxable') }, { key: 'super_treatment', label: 'Super', render: i => (i.super_treatment === 'ote' ? 'OTE' : '—') },
          { key: 'is_active', label: 'Status', render: i => <><StatusBadge status={i.is_active ? 'active' : 'inactive'} />{i.is_system && <span className="badge badge-neutral" style={{ marginLeft: 4 }}>system</span>}</> },
          { key: 'x', label: '', render: i => can && !i.is_system && <button className="btn btn-ghost btn-xs" onClick={e => { e.stopPropagation(); remove(i) }}>Remove</button> }]} />}</Async>
      {edit && <Editor item={edit} onClose={() => setEdit(null)} onSaved={() => { setEdit(null); q.reload() }} />}
    </div>
  )
}

function Editor({ item, onClose, onSaved }) {
  const accts = useLoad(() => api.ledgerAccounts().catch(() => []), [])
  const lts = useLoad(() => api.leaveTypes.list().catch(() => []), [])
  const [f, set] = useForm({ code: '', name: '', kind: 'allowance', description: '', calc_method: 'fixed', multiplier: '1', rate: '', default_amount: '', percent: '', taxable: true, payg_treatment: 'regular', super_treatment: 'none',
    reportable_fringe: false, expense_account_id: '', leave_type_id: '', is_active: true, ...Object.fromEntries(Object.entries(item).map(([k, v]) => [k, v ?? ''])) })
  const earn = EARN.includes(f.kind)
  const sys = !!item.is_system
  const problems = [!f.code.trim() && 'Code is required', !/^[A-Za-z0-9_]*$/.test(f.code) && 'Code may only use letters, digits and underscores', !f.name.trim() && 'Name is required'].filter(Boolean)
  const go = async () => {
    const b = { ...f, code: f.code.toUpperCase(), expense_account_id: f.expense_account_id === '' ? null : Number(f.expense_account_id), leave_type_id: f.leave_type_id === '' ? null : Number(f.leave_type_id),
      rate: f.rate === '' ? null : f.rate, default_amount: f.default_amount === '' ? null : f.default_amount, percent: f.percent === '' ? null : f.percent }
    delete b.id; delete b.is_system; delete b.is_default; delete b.sort
    if (await act(() => api.payItems.save(b, item.id), 'Pay item saved')) onSaved()
  }
  return (
    <Modal title={item.id ? `Pay item ${item.code}` : 'New pay item'} onClose={onClose} width={760}>
      {sys && <div className="alert alert-warning">System pay item: required by the payroll engine. Its code and type are fixed.</div>}
      <Grid cols={3}>
        <Input label="Code" value={f.code} onChange={set('code')} disabled={sys} maxLength={20} /><Input label="Name" value={f.name} onChange={set('name')} />
        <Select label="Type" value={f.kind} onChange={set('kind')} options={KINDS} disabled={sys} />
        <Select label="Calculation" value={f.calc_method} onChange={set('calc_method')} options={['fixed', 'hours_x_rate', 'percent_of_base', 'percent_of_gross']} />
        {f.calc_method === 'hours_x_rate' && <><Input label="Multiplier (× base rate)" type="number" step="0.01" value={f.multiplier} onChange={set('multiplier')} /><Input label="Fixed $/hour (optional)" type="number" value={f.rate} onChange={set('rate')} /></>}
        {f.calc_method === 'fixed' && <Input label="Default amount per pay" type="number" value={f.default_amount} onChange={set('default_amount')} />}
        {f.calc_method.startsWith('percent') && <Input label="Default percent" type="number" value={f.percent} onChange={set('percent')} />}
        {earn && <Check label="Taxable (subject to PAYG)" checked={f.taxable} onChange={set('taxable')} />}
        {earn && <Select label="PAYG method" value={f.payg_treatment} onChange={set('payg_treatment')} options={['regular', 'additional', 'none', 'termination_leave', 'etp']} hint="'additional' = bonus method (ATO Schedule 5, Method A)" />}
        {earn && <Select label="Super treatment" value={f.super_treatment} onChange={set('super_treatment')} options={[{ value: 'ote', label: 'Ordinary time earnings (super payable)' }, { value: 'none', label: 'Not OTE' }]} />}
        <Select label={earn ? 'Expense account' : 'Ledger account'} value={f.expense_account_id} onChange={set('expense_account_id')} blank="Default" options={(accts.data || []).map(a => ({ value: a.id, label: `${a.code} ${a.name}` }))} />
        {(f.kind === 'leave' || f.kind === 'unpaid_leave') && <Select label="Leave type" value={f.leave_type_id} onChange={set('leave_type_id')} blank="— none —" options={(lts.data || []).map(l => ({ value: l.id, label: l.name }))} />}
        <Check label="Active" checked={f.is_active} onChange={set('is_active')} />
      </Grid>
      <Input label="Description" value={f.description} onChange={set('description')} />
      {problems.length > 0 && <div className="text-xs" style={{ color: 'var(--danger)' }}>{problems.map(p => <div key={p}>{p}</div>)}</div>}
      <div className="flex gap-1" style={{ justifyContent: 'flex-end', marginTop: 10 }}><button className="btn btn-outline" onClick={onClose}>Cancel</button><button className="btn btn-primary" disabled={problems.length > 0} onClick={go}>Save</button></div>
    </Modal>
  )
}
