import React, { useEffect, useState } from 'react'
import toast from 'react-hot-toast'
import * as api from '../lib/payrollApi.js'
import { act, Async, Check, DataGrid, Field, Grid, Input, Issues, Modal, Money, Select, StatusBadge, useConfirm, useForm, useLoad } from './kit.jsx'
import { digits, employeeProblems, validAccount, validBsb, validTfn } from '../lib/validators.js'
import { fmtDate, label, todayISO } from '../lib/format.js'

const SECTIONS = ['Profile', 'Employment & pay', 'Tax', 'Super', 'Bank', 'Recurring items', 'Leave']
const STATES = ['ACT', 'NSW', 'NT', 'QLD', 'SA', 'TAS', 'VIC', 'WA']

export default function EmployeeEditor({ id, me, refs, onClose, onSaved }) {
  const [empId, setEmpId] = useState(id)
  const [sec, setSec] = useState(0)
  const [dialog, confirm] = useConfirm()
  const q = useLoad(() => (empId ? api.employee(empId) : Promise.resolve(null)), [empId])
  const e = q.data
  const canEdit = me.capabilities.includes('employees_manage')
  const saved = emp => { setEmpId(emp.id); onSaved?.() }
  const unlocked = !!empId
  return (
    <Modal title={empId ? (e ? `${e.employee_number} · ${e.name}` : 'Employee') : 'New employee'} onClose={onClose} width={900}>
      {dialog}
      <div className="tabs-bar" style={{ marginBottom: 14, flexWrap: 'wrap' }}>
        {SECTIONS.map((s, i) => <button key={s} className={`tab-btn${sec === i ? ' active' : ''}`} disabled={(i > 1 && !unlocked) || (!!e && [2, 4].includes(i) && e.tax === undefined)} title={e && [2, 4].includes(i) && e.tax === undefined ? 'Not available for your role' : undefined} onClick={() => setSec(i)}>{s}</button>)}
      </div>
      {!unlocked && sec < 2 && <div className="alert alert-success" style={{ marginBottom: 10 }}>Enter the profile and pay details, then save. Tax, super and bank details unlock after the employee is created.</div>}
      {empId && q.loading && !e ? <div className="text-muted">Loading…</div> : q.error ? <div className="alert alert-error">{q.error}</div> : (
        <>
          {(sec === 0 || sec === 1) && <ProfileForm key={String(e?.id) + e?.status} e={e} refs={refs} canEdit={canEdit} part={sec === 0 ? 'profile' : 'pay'} onSaved={saved} reload={q.reload} confirm={confirm} />}
          {sec === 2 && e && <TaxSection e={e} me={me} canEdit={canEdit} reload={q.reload} />}
          {sec === 3 && e && <SuperSection e={e} refs={refs} canEdit={canEdit} reload={q.reload} />}
          {sec === 4 && e && <BankSection e={e} canEdit={canEdit} reload={q.reload} />}
          {sec === 5 && e && <ItemsSection e={e} refs={refs} canEdit={canEdit} reload={q.reload} confirm={confirm} />}
          {sec === 6 && e && <LeaveSection e={e} refs={refs} canEdit={canEdit && !me.self_service ? true : canEdit} />}
        </>)}
    </Modal>
  )
}

function ProfileForm({ e, refs, canEdit, part, onSaved, reload, confirm }) {
  const [f, set, setF] = useForm(() => ({
    first_name: '', middle_name: '', last_name: '', preferred_name: '', date_of_birth: '', email: '', phone: '', address_line1: '', address_line2: '', suburb: '', state: 'NSW', postcode: '',
    employee_number: '', start_date: todayISO(), end_date: '', status: 'active', employment_type: 'full_time', position: '', department_id: '', location_id: '', manager_id: '', calendar_id: refs.calendars.find(c => c.is_default)?.id || '',
    pay_frequency: 'fortnightly', pay_basis: 'salary', annual_salary: '', hourly_rate: '', hours_per_week: '38', login_user_id: '', pay_standard_hours: false, ...(e ? Object.fromEntries(Object.entries(e).map(([k, v]) => [k, v ?? ''])) : {}),
  }))
  const [busy, setBusy] = useState(false)
  const [touched, setTouched] = useState(false)
  const problems = touched ? employeeProblems(f) : []
  const users = useLoad(() => (canEdit ? api.loginUsers().catch(() => []) : Promise.resolve([])), [canEdit])
  const ro = !canEdit
  const body = () => {
    const b = { ...f }
    ;['department_id', 'location_id', 'manager_id', 'calendar_id', 'login_user_id'].forEach(k => { b[k] = b[k] === '' ? null : Number(b[k]) })
    ;['annual_salary', 'hourly_rate', 'end_date', 'date_of_birth'].forEach(k => { if (b[k] === '') b[k] = null })
    if (b.pay_basis === 'salary') b.hourly_rate = null; else b.annual_salary = null
    delete b.id; delete b.readiness; delete b.tax; delete b.super; delete b.bank; delete b.items; delete b.name; delete b.has_login; delete b.is_demo; delete b.user_id
    return b
  }
  const save = async () => {
    setTouched(true)
    if (employeeProblems(f).length) { toast.error('Please fix the highlighted problems first'); return }
    setBusy(true)
    const r = await act(() => api.saveEmployee(body(), e?.id), e ? 'Employee saved' : 'Employee created')
    setBusy(false)
    if (r) { onSaved(r); reload() }
  }
  const terminate = async () => {
    const c = await confirm({ title: 'Terminate employee', message: `Terminate ${e.name}? Final pay, unused leave and any termination payment are then added in a pay run.`, reasonLabel: 'Reason for leaving', confirmLabel: 'Terminate', danger: true })
    if (!c.ok) return
    const end = window.prompt('Last day of employment (YYYY-MM-DD)', todayISO())
    if (!end) return
    if (await act(() => api.terminateEmployee(e.id, { end_date: end, reason: c.reason }), 'Employee terminated')) { reload(); onSaved(e) }
  }
  const showSalary = f.annual_salary !== undefined && (e ? e.annual_salary !== undefined || e.hourly_rate !== undefined : true)
  return (
    <div>
      {part === 'profile' && (
        <>
          <Grid cols={3}>
            <Input label="First name" value={f.first_name} onChange={set('first_name')} disabled={ro} />
            <Input label="Middle name" value={f.middle_name} onChange={set('middle_name')} disabled={ro} />
            <Input label="Last name" value={f.last_name} onChange={set('last_name')} disabled={ro} />
            <Input label="Preferred name" value={f.preferred_name} onChange={set('preferred_name')} disabled={ro} />
            <Input label="Date of birth" type="date" value={f.date_of_birth} onChange={set('date_of_birth')} disabled={ro} />
            <Input label="Employee number" value={f.employee_number} onChange={set('employee_number')} disabled={ro || !!e} hint={e ? undefined : 'Leave blank to number automatically'} />
            <Input label="Email" type="email" value={f.email} onChange={set('email')} disabled={ro} />
            <Input label="Phone" value={f.phone} onChange={set('phone')} disabled={ro} />
            <Select label="Login (self-service)" value={f.login_user_id} onChange={set('login_user_id')} blank="— none —" disabled={ro}
              options={(users.data || []).map(u => ({ value: u.id, label: `${u.name} (${u.email})${u.linked_employee_id && u.linked_employee_id !== e?.id ? ' — linked' : ''}` }))} hint="Lets this person see their own payslips, leave and timesheets" />
          </Grid>
          <Grid cols={4}>
            <Input label="Address" value={f.address_line1} onChange={set('address_line1')} disabled={ro} />
            <Input label="Suburb" value={f.suburb} onChange={set('suburb')} disabled={ro} />
            <Select label="State" value={f.state} onChange={set('state')} options={STATES} disabled={ro} />
            <Input label="Postcode" value={f.postcode} onChange={set('postcode')} maxLength={4} disabled={ro} />
          </Grid>
        </>)}
      {part === 'pay' && (
        <>
          <Grid cols={3}>
            <Select label="Employment type" value={f.employment_type} onChange={set('employment_type')} options={['full_time', 'part_time', 'casual', 'contractor']} disabled={ro} />
            <Input label="Position" value={f.position} onChange={set('position')} disabled={ro} />
            <Select label="Status" value={f.status} onChange={set('status')} options={['active', 'inactive', 'terminated']} disabled={ro || !e} />
            <Input label="Start date" type="date" value={f.start_date} onChange={set('start_date')} disabled={ro} />
            <Input label="End date" type="date" value={f.end_date} onChange={set('end_date')} disabled={ro} />
            <Select label="Department" value={f.department_id} onChange={set('department_id')} blank="— none —" options={refs.departments.map(d => ({ value: d.id, label: d.name }))} disabled={ro} />
            <Select label="Location" value={f.location_id} onChange={set('location_id')} blank="— none —" options={refs.locations.map(d => ({ value: d.id, label: d.name }))} disabled={ro} />
            <Select label="Manager" value={f.manager_id} onChange={set('manager_id')} blank="— none —" options={refs.managers.filter(m => m.id !== e?.id).map(m => ({ value: m.id, label: `${m.employee_number} ${m.name}` }))} disabled={ro} />
            <Select label="Pay calendar" value={f.calendar_id} onChange={set('calendar_id')} blank="— none —" options={refs.calendars.map(c => ({ value: c.id, label: c.name }))} disabled={ro} />
            <Select label="Pay frequency" value={f.pay_frequency} onChange={set('pay_frequency')} options={['weekly', 'fortnightly', 'monthly']} disabled={ro} />
            <Select label="Pay basis" value={f.pay_basis} onChange={set('pay_basis')} options={['salary', 'hourly']} disabled={ro} />
            {showSalary ? (f.pay_basis === 'salary' ? <Input label="Annual salary" type="number" min="0" step="0.01" value={f.annual_salary} onChange={set('annual_salary')} disabled={ro} />
              : <Input label="Hourly rate" type="number" min="0" step="0.0001" value={f.hourly_rate} onChange={set('hourly_rate')} disabled={ro} />) : <Field label="Pay rate"><span className="text-muted">Hidden for your role</span></Field>}
            <Input label="Ordinary hours per week" type="number" min="0" step="0.1" value={f.hours_per_week} onChange={set('hours_per_week')} disabled={ro} />
            {f.pay_basis === 'hourly' && <Check label="Pay standard hours without a timesheet" checked={f.pay_standard_hours} onChange={set('pay_standard_hours')} />}
          </Grid>
          {e?.status === 'terminated' && <div className="text-sm">Terminated {fmtDate(e.end_date)} {e.termination_reason ? `· ${e.termination_reason}` : ''}</div>}
        </>)}
      {e?.readiness?.length > 0 && <div style={{ margin: '8px 0' }}><Issues errors={e.readiness.filter(r => r.severity === 'error')} warnings={e.readiness.filter(r => r.severity !== 'error')} /></div>}
      {problems.length > 0 && <div role="alert" className="alert alert-error" style={{ margin: '8px 0' }}>{problems.map(x => <div key={x}>{x}</div>)}</div>}
      {canEdit && (
        <div className="flex gap-1" style={{ marginTop: 12 }}>
          <button className="btn btn-primary" onClick={save} disabled={busy}>{busy ? 'Saving…' : e ? 'Save changes' : 'Create employee'}</button>
          {e && e.status !== 'terminated' && <button className="btn btn-danger btn-outline" onClick={terminate}>Terminate…</button>}
        </div>)}
    </div>
  )
}

function TaxSection({ e, me, canEdit, reload }) {
  const t = e.tax || {}
  const [f, set] = useForm({ tfn: '', tfn_status: t.tfn_status || 'not_provided', residency: t.residency || 'resident', claims_tft: t.claims_tft ?? true, has_study_loan: !!t.has_study_loan,
    study_loan_type: t.study_loan_type || 'HELP', medicare_variation: t.medicare_variation || 'none', tax_offset_annual: t.tax_offset_annual || '0', variation_pct: t.variation_pct || '', extra_withholding: t.extra_withholding || '0',
    declaration_date: t.declaration_date || '' })
  const [revealed, setRevealed] = useState(null)
  const bad = f.tfn && !validTfn(f.tfn)
  const save = async () => {
    const b = { ...f, variation_pct: f.variation_pct === '' ? null : f.variation_pct, declaration_date: f.declaration_date || null }
    if (!b.tfn) delete b.tfn
    if (await act(() => api.saveTax(e.id, b), 'Tax details saved')) { set('tfn')(''); reload() }
  }
  return (
    <div>
      <div className="alert alert-warning" style={{ marginBottom: 10 }}>TFNs are stored encrypted and shown masked. {me.capabilities.includes('tfn_reveal') ? 'You can reveal one (this is recorded in the audit trail).' : 'Only a Payroll Administrator can reveal a full TFN.'}</div>
      <Grid cols={3}>
        <Field label="TFN" hint={t.tfn_masked ? `On file: ${t.tfn_masked}` : 'Not on file'}>
          <input className="input" aria-label="TFN" inputMode="numeric" autoComplete="off" placeholder={t.tfn_masked ? 'Enter a new TFN to replace' : '9 digits'} value={f.tfn} onChange={set('tfn')} disabled={!canEdit} />
          {bad && <div className="text-xs" style={{ color: 'var(--danger)' }}>That is not a valid TFN (check digit fails)</div>}
        </Field>
        <Select label="TFN status" value={f.tfn_status} onChange={set('tfn_status')} options={['provided', 'pending', 'exempt', 'not_provided']} disabled={!canEdit} />
        <Select label="Residency for tax" value={f.residency} onChange={set('residency')} options={['resident', 'foreign_resident']} disabled={!canEdit} />
        <Check label="Claims the tax-free threshold" checked={f.claims_tft} onChange={set('claims_tft')} />
        <Check label="Has a study or training loan (HELP/VSL/SSL/TSL)" checked={f.has_study_loan} onChange={set('has_study_loan')} />
        {f.has_study_loan && <Select label="Loan type" value={f.study_loan_type} onChange={set('study_loan_type')} options={['HELP', 'VSL', 'SSL', 'TSL', 'SFSS']} disabled={!canEdit} />}
        <Select label="Medicare levy variation" value={f.medicare_variation} onChange={set('medicare_variation')} options={['none', 'half', 'full']} disabled={!canEdit} />
        <Input label="Tax offsets claimed (annual $)" type="number" min="0" value={f.tax_offset_annual} onChange={set('tax_offset_annual')} disabled={!canEdit} />
        <Input label="Approved withholding variation %" type="number" min="0" max="100" value={f.variation_pct} onChange={set('variation_pct')} disabled={!canEdit} hint="Only with an ATO variation notice" />
        <Input label="Extra withholding per pay ($)" type="number" min="0" value={f.extra_withholding} onChange={set('extra_withholding')} disabled={!canEdit} />
        <Input label="Declaration date" type="date" value={f.declaration_date} onChange={set('declaration_date')} disabled={!canEdit} />
      </Grid>
      <div className="flex gap-1" style={{ marginTop: 10 }}>
        {canEdit && <button className="btn btn-primary" disabled={!!bad} onClick={save}>Save tax details</button>}
        {me.capabilities.includes('tfn_reveal') && t.tfn_masked && <button className="btn btn-outline" onClick={async () => { const r = await act(() => api.revealTfn(e.id)); if (r) setRevealed(r.tfn) }}>Reveal TFN</button>}
        {revealed && <span className="mono" style={{ alignSelf: 'center' }}>{revealed} <button className="btn btn-ghost btn-xs" onClick={() => setRevealed(null)}>hide</button></span>}
      </div>
    </div>
  )
}

function SuperSection({ e, refs, canEdit, reload }) {
  const [rows, setRows] = useState((e.super || []).map(s => ({ fund_id: s.fund_id, member_number: s.member_number || '', allocation_pct: s.allocation_pct, is_default_fund: s.is_default_fund, choice_form_date: s.choice_form_date || '' })))
  const total = rows.reduce((s, r) => s + Number(r.allocation_pct || 0), 0)
  const upd = (i, k, v) => setRows(rs => rs.map((r, j) => (j === i ? { ...r, [k]: v } : r)))
  const save = async () => { if (await act(() => api.saveSuper(e.id, rows.map(r => ({ ...r, choice_form_date: r.choice_form_date || null }))), 'Super details saved')) reload() }
  const dflt = refs.funds.find(f => f.is_default)
  return (
    <div>
      <p className="text-sm text-muted">Employer contributions are paid at the super guarantee rate. {dflt ? `Default fund: ${dflt.name}.` : 'No default fund set yet.'} Salary sacrifice and extra contributions are set under Recurring items.</p>
      {rows.map((r, i) => (
        <Grid key={i} cols={5}>
          <Select label="Fund" value={r.fund_id} onChange={ev => upd(i, 'fund_id', Number(ev.target.value))} options={refs.funds.map(f => ({ value: f.id, label: f.name }))} blank="Choose…" disabled={!canEdit} />
          <Input label="Member number" value={r.member_number} onChange={ev => upd(i, 'member_number', ev.target.value)} disabled={!canEdit} />
          <Input label="Allocation %" type="number" value={r.allocation_pct} onChange={ev => upd(i, 'allocation_pct', ev.target.value)} disabled={!canEdit} />
          <Input label="Choice form received" type="date" value={r.choice_form_date} onChange={ev => upd(i, 'choice_form_date', ev.target.value)} disabled={!canEdit} />
          <Field label=""><label className="flex items-center gap-1"><input type="checkbox" checked={r.is_default_fund} onChange={ev => upd(i, 'is_default_fund', ev.target.checked)} /> Employer default</label>
            {canEdit && <button className="btn btn-ghost btn-xs" onClick={() => setRows(rs => rs.filter((_, j) => j !== i))}>Remove</button>}</Field>
        </Grid>))}
      {rows.length === 0 && <div className="alert alert-error">No super fund: superannuation cannot be paid until one is added.</div>}
      {rows.length > 0 && total !== 100 && <div className="text-xs" style={{ color: 'var(--danger)' }}>Allocations add up to {total}% (must be 100%)</div>}
      {canEdit && <div className="flex gap-1" style={{ marginTop: 10 }}>
        <button className="btn btn-outline" onClick={() => setRows(rs => [...rs, { fund_id: dflt?.id || '', member_number: '', allocation_pct: rs.length ? 0 : 100, is_default_fund: false, choice_form_date: '' }])}>Add fund</button>
        <button className="btn btn-primary" disabled={rows.length > 0 && total !== 100} onClick={save}>Save super details</button></div>}
    </div>
  )
}

function BankSection({ e, canEdit, reload }) {
  const [rows, setRows] = useState((e.bank || []).map(b => ({ id: b.id, account_name: b.account_name, bsb: b.bsb, account_number: '', masked: b.account_masked, allocation_type: b.allocation_type, allocation_value: b.allocation_value, reference: b.reference || '' })))
  const upd = (i, k, v) => setRows(rs => rs.map((r, j) => (j === i ? { ...r, [k]: v } : r)))
  const problems = rows.flatMap((r, i) => [!r.account_name.trim() && `Account ${i + 1}: name is required`, !validBsb(r.bsb) && `Account ${i + 1}: BSB must be 6 digits`,
    (r.account_number ? !validAccount(r.account_number) : !r.id) && `Account ${i + 1}: account number must be 5-9 digits`].filter(Boolean))
  if (rows.length && rows.filter(r => r.allocation_type === 'remainder').length !== 1) problems.push('Exactly one account must receive the remainder')
  const save = async () => { if (await act(() => api.saveBank(e.id, rows.map(({ masked, ...r }) => r)), 'Bank details saved')) reload() }
  return (
    <div>
      <div className="alert alert-warning" style={{ marginBottom: 10 }}>Account numbers are stored encrypted and never shown in full. Leave the account number blank to keep the existing one.</div>
      {rows.map((r, i) => (
        <Grid key={i} cols={6}>
          <Input label="Account name" value={r.account_name} onChange={ev => upd(i, 'account_name', ev.target.value)} disabled={!canEdit} />
          <Input label="BSB" value={r.bsb} onChange={ev => upd(i, 'bsb', ev.target.value)} placeholder="062-000" disabled={!canEdit} />
          <Input label="Account number" value={r.account_number} onChange={ev => upd(i, 'account_number', ev.target.value)} placeholder={r.masked || ''} inputMode="numeric" autoComplete="off" disabled={!canEdit} />
          <Select label="Allocation" value={r.allocation_type} onChange={ev => upd(i, 'allocation_type', ev.target.value)} options={['fixed', 'percent', 'remainder']} disabled={!canEdit} />
          <Input label={r.allocation_type === 'percent' ? 'Percent' : 'Amount'} type="number" value={r.allocation_type === 'remainder' ? '' : r.allocation_value} onChange={ev => upd(i, 'allocation_value', ev.target.value)} disabled={!canEdit || r.allocation_type === 'remainder'} />
          <Field label="">{canEdit && <button className="btn btn-ghost btn-xs" onClick={() => setRows(rs => rs.filter((_, j) => j !== i))}>Remove</button>}</Field>
        </Grid>))}
      {rows.length === 0 && <div className="alert alert-error">No bank account: net pay cannot be paid.</div>}
      {problems.length > 0 && <div className="text-xs" style={{ color: 'var(--danger)' }}>{problems.map(p => <div key={p}>{p}</div>)}</div>}
      {canEdit && <div className="flex gap-1" style={{ marginTop: 10 }}>
        <button className="btn btn-outline" disabled={rows.length >= 5} onClick={() => setRows(rs => [...rs, { account_name: e.name, bsb: '', account_number: '', allocation_type: rs.length ? 'fixed' : 'remainder', allocation_value: '', reference: '' }])}>Add account</button>
        <button className="btn btn-primary" disabled={problems.length > 0} onClick={save}>Save bank details</button></div>}
    </div>
  )
}

function ItemsSection({ e, refs, canEdit, reload, confirm }) {
  const assignable = refs.items.filter(i => !i.is_system && i.is_active && !['leave', 'leave_loading', 'unpaid_leave', 'salary_adjustment', 'termination_leave', 'etp', 'overtime', 'penalty'].includes(i.kind))
  const [f, set, setF] = useForm({ pay_item_id: '', amount: '', rate: '', hours: '', effective_from: '', effective_to: '' })
  const item = assignable.find(i => String(i.id) === String(f.pay_item_id))
  const add = async () => {
    const b = { pay_item_id: Number(f.pay_item_id), amount: f.amount || null, rate: f.rate || null, hours: f.hours || null, effective_from: f.effective_from || null, effective_to: f.effective_to || null }
    if (await act(() => api.assignItem(e.id, b), 'Pay item added')) { setF({ pay_item_id: '', amount: '', rate: '', hours: '', effective_from: '', effective_to: '' }); reload() }
  }
  const remove = async r => { const c = await confirm({ message: `Remove ${r.name} from ${e.name}?`, confirmLabel: 'Remove', danger: true }); if (c.ok && await act(() => api.removeItem(e.id, r.id), 'Removed')) reload() }
  return (
    <div>
      <p className="text-sm text-muted">Recurring allowances, salary sacrifice, deductions and extra super applied to every pay in the effective period.</p>
      <DataGrid rows={e.items || []} empty="No recurring items" columns={[{ key: 'code', label: 'Code' }, { key: 'name', label: 'Item' }, { key: 'kind', label: 'Type', render: r => label(r.kind) },
        { key: 'amount', label: 'Amount / %', render: r => r.amount ?? r.rate ?? 'default' }, { key: 'effective_from', label: 'From', date: true }, { key: 'effective_to', label: 'To', date: true },
        { key: 'x', label: '', render: r => canEdit && <button className="btn btn-ghost btn-xs" onClick={() => remove(r)}>Remove</button> }]} />
      {canEdit && (
        <div style={{ marginTop: 12 }}>
          <Grid cols={5}>
            <Select label="Pay item" value={f.pay_item_id} onChange={set('pay_item_id')} blank="Choose…" options={assignable.map(i => ({ value: i.id, label: `${i.code} · ${i.name}` }))} />
            {item?.calc_method === 'hours_x_rate' ? <><Input label="Hours per pay" type="number" value={f.hours} onChange={set('hours')} /><Input label="Rate $/h" type="number" value={f.rate} onChange={set('rate')} /></>
              : item?.calc_method?.startsWith('percent') ? <Input label="Percent" type="number" value={f.rate} onChange={set('rate')} />
              : <Input label="Amount per pay" type="number" value={f.amount} onChange={set('amount')} hint={item?.default_amount ? `Default ${item.default_amount}` : undefined} />}
            <Input label="From" type="date" value={f.effective_from} onChange={set('effective_from')} />
            <Input label="To" type="date" value={f.effective_to} onChange={set('effective_to')} />
            <Field label=""><button className="btn btn-primary" disabled={!f.pay_item_id} onClick={add}>Add</button></Field>
          </Grid>
        </div>)}
    </div>
  )
}

function LeaveSection({ e, refs, canEdit }) {
  const bal = useLoad(() => api.employeeLeave(e.id), [e.id])
  const hist = useLoad(() => api.employeeLeaveHistory(e.id), [e.id])
  const [adj, set, setAdj] = useForm({ leave_type_id: '', hours: '', note: '' })
  const go = async () => { if (await act(() => api.adjustLeave(e.id, { ...adj, leave_type_id: Number(adj.leave_type_id) }), 'Balance adjusted')) { setAdj({ leave_type_id: '', hours: '', note: '' }); bal.reload(); hist.reload() } }
  return (
    <div>
      <Async q={bal}>{rows => <DataGrid rows={rows} rowKey="leave_type_id" empty="No leave balances yet" columns={[{ key: 'name', label: 'Leave type' }, { key: 'balance', label: 'Balance (h)', hours: true }, { key: 'committed', label: 'Requested (h)', hours: true },
        { key: 'available', label: 'Available (h)', hours: true }, { key: 'accrued', label: 'Accrued (h)', hours: true }, { key: 'taken', label: 'Taken (h)', hours: true }]} />}</Async>
      <h5 style={{ margin: '14px 0 6px' }}>History</h5>
      <Async q={hist}>{rows => <DataGrid rows={rows} pageSize={8} empty="No leave movements" columns={[{ key: 'date', label: 'Date', date: true }, { key: 'leave_type', label: 'Leave' }, { key: 'type', label: 'Type', render: r => label(r.type) }, { key: 'hours', label: 'Hours', hours: true }, { key: 'note', label: 'Note' }]} />}</Async>
      {canEdit && <div style={{ marginTop: 10 }}><Grid cols={4}>
        <Select label="Adjust leave type" value={adj.leave_type_id} onChange={set('leave_type_id')} blank="Choose…" options={refs.leaveTypes.map(l => ({ value: l.id, label: l.name }))} />
        <Input label="Hours (+/−)" type="number" value={adj.hours} onChange={set('hours')} /><Input label="Reason" value={adj.note} onChange={set('note')} />
        <Field label=""><button className="btn btn-outline" disabled={!adj.leave_type_id || !adj.hours || !adj.note} onClick={go}>Apply adjustment</button></Field></Grid></div>}
    </div>
  )
}
