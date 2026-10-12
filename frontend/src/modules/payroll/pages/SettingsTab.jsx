import React, { useState } from 'react'
import * as api from '../lib/payrollApi.js'
import { act, Async, Check, DataGrid, Grid, Input, Modal, Section, Select, StatusBadge, useForm, useLoad } from '../components/kit.jsx'
import { RulesPanel } from './PaygTab.jsx'
import { label, todayISO } from '../lib/format.js'
import { ImportButton, ImportCentre } from '../components/CsvImport.jsx'

const SUB = [['org', 'Organisation & payslips'], ['payments', 'Payments'], ['accounting', 'Accounting'], ['calendars', 'Pay calendars'], ['leave', 'Leave policies'], ['funds', 'Super funds'], ['groups', 'Departments & locations'], ['rules', 'Statutory rules'], ['import', 'Bulk import']]

export default function SettingsTab({ me }) {
  const [sub, setSub] = useState('org')
  return (
    <div>
      <h3 style={{ marginTop: 0 }}>Payroll settings</h3>
      <div className="tabs-bar" style={{ marginBottom: 12, flexWrap: 'wrap' }}>{SUB.map(([k, t]) => <button key={k} className={`tab-btn${sub === k ? ' active' : ''}`} onClick={() => setSub(k)}>{t}</button>)}</div>
      {sub === 'org' && <OrgSettings />}{sub === 'payments' && <PaymentSettings />}{sub === 'accounting' && <AccountingSettings />}{sub === 'calendars' && <Calendars />}
      {sub === 'leave' && <LeaveTypes />}{sub === 'funds' && <Funds />}{sub === 'groups' && <Groups />}{sub === 'rules' && <RulesPanel />}{sub === 'import' && <ImportCentre />}
    </div>
  )
}

function useSettings() { return useLoad(() => api.settings(), []) }

function OrgSettings() {
  const q = useSettings()
  return <Async q={q}>{s => <OrgForm s={s} reload={q.reload} />}</Async>
}
function OrgForm({ s, reload }) {
  const [f, set] = useForm({ employer_name: s.employer_name || '', abn: s.abn || '', default_frequency: s.default_frequency, standard_hours_per_week: s.standard_hours_per_week, employee_prefix: s.employee_prefix, run_prefix: s.run_prefix,
    show_ytd: s.payslip_config.show_ytd !== false, show_leave: s.payslip_config.show_leave !== false, footer: s.payslip_config.footer || '', stp_bms: s.stp_config.bms_id || '', sep: !!s.controls.require_separate_approver })
  const go = async () => { if (await act(() => api.saveSettings({ employer_name: f.employer_name, abn: f.abn, default_frequency: f.default_frequency, standard_hours_per_week: f.standard_hours_per_week, employee_prefix: f.employee_prefix, run_prefix: f.run_prefix,
    payslip_config: { show_ytd: f.show_ytd, show_leave: f.show_leave, footer: f.footer }, stp_config: { bms_id: f.stp_bms }, controls: { require_separate_approver: f.sep } }), 'Settings saved')) reload() }
  return (
    <div>
      <Grid cols={3}>
        <Input label="Employer name (on payslips)" value={f.employer_name} onChange={set('employer_name')} /><Input label="ABN" value={f.abn} onChange={set('abn')} />
        <Select label="Default pay frequency" value={f.default_frequency} onChange={set('default_frequency')} options={['weekly', 'fortnightly', 'monthly']} />
        <Input label="Standard hours per week" type="number" value={f.standard_hours_per_week} onChange={set('standard_hours_per_week')} />
        <Input label="Employee number prefix" value={f.employee_prefix} onChange={set('employee_prefix')} maxLength={6} /><Input label="Pay run number prefix" value={f.run_prefix} onChange={set('run_prefix')} maxLength={6} />
        <Input label="STP BMS / software ID" value={f.stp_bms} onChange={set('stp_bms')} hint="Recorded in STP payloads only" />
      </Grid>
      <Check label="Show year-to-date on payslips" checked={f.show_ytd} onChange={set('show_ytd')} /><Check label="Show leave balances on payslips" checked={f.show_leave} onChange={set('show_leave')} />
      <Check label="Separation of duties: the person who created a pay run cannot approve it" checked={f.sep} onChange={set('sep')} />
      <Input label="Payslip footer" value={f.footer} onChange={set('footer')} />
      <button className="btn btn-primary" onClick={go}>Save settings</button>
    </div>
  )
}

function PaymentSettings() {
  const q = useSettings()
  return <Async q={q}>{s => <PayForm s={s} reload={q.reload} />}</Async>
}
function PayForm({ s, reload }) {
  const p = s.payment_config || {}
  const [f, set] = useForm({ bsb: p.bsb || '', account: '', account_name: p.account_name || '', apca_user_id: p.apca_user_id || '', bank_abbrev: p.bank_abbrev || '', description: p.description || 'PAYROLL' })
  const go = async () => { const b = { ...f }; if (!b.account) delete b.account; if (await act(() => api.saveSettings({ payment_config: b }), 'Payment settings saved')) { set('account')(''); reload() } }
  return (
    <div>
      <div className="alert alert-warning">Used only to build the bank file (ABA). The account number is stored encrypted. Check the file layout with your bank before using it.</div>
      <Grid cols={3}>
        <Input label="Company BSB" value={f.bsb} onChange={set('bsb')} placeholder="062-000" /><Input label="Company account number" value={f.account} onChange={set('account')} placeholder={p.account_masked || ''} autoComplete="off" inputMode="numeric" />
        <Input label="Account name" value={f.account_name} onChange={set('account_name')} /><Input label="APCA user ID (6 digits)" value={f.apca_user_id} onChange={set('apca_user_id')} maxLength={6} />
        <Input label="Bank abbreviation (3 letters)" value={f.bank_abbrev} onChange={set('bank_abbrev')} maxLength={3} /><Input label="File description" value={f.description} onChange={set('description')} maxLength={12} />
      </Grid>
      <button className="btn btn-primary" onClick={go}>Save payment settings</button>
    </div>
  )
}

const MAP = [['wages_expense', 'Wages and salaries (expense)'], ['super_expense', 'Superannuation (expense)'], ['reimbursement_expense', 'Employee reimbursements (expense)'], ['wages_payable', 'Wages payable / payroll clearing'],
  ['payg_payable', 'PAYG withholding payable'], ['super_payable', 'Superannuation payable'], ['deductions_payable', 'Payroll deductions payable'], ['payment_bank', 'Bank account for net pay (optional)']]
function AccountingSettings() {
  const q = useSettings(); const acc = useLoad(() => api.ledgerAccounts(), [])
  return <Async q={q}>{s => <Async q={acc}>{accts => <MapForm s={s} accts={accts} reload={q.reload} />}</Async>}</Async>
}
function MapForm({ s, accts, reload }) {
  const [f, , setF] = useForm(Object.fromEntries(MAP.map(([k]) => [k, s.accounting_map[k] || ''])))
  const go = async () => { const m = Object.fromEntries(Object.entries(f).filter(([, v]) => v !== '').map(([k, v]) => [k, Number(v)])); if (await act(() => api.saveSettings({ accounting_map: m }), 'Accounting settings saved')) reload() }
  return (
    <div>
      <p className="text-sm text-muted">A finalised pay run posts one balanced journal using these ledger accounts (the Chart of Accounts is in Books & Accounting).</p>
      <Grid cols={2}>{MAP.map(([k, t]) => <Select key={k} label={t} value={f[k]} onChange={e => setF(x => ({ ...x, [k]: e.target.value }))} blank="— not set —" options={accts.map(a => ({ value: a.id, label: `${a.code} ${a.name}` }))} />)}</Grid>
      <button className="btn btn-primary" onClick={go}>Save accounting settings</button>
    </div>
  )
}

function CrudList({ q, columns, onEdit, onNew, newLabel, empty, importEntity }) {
  return <div><div className="flex gap-1" style={{ marginBottom: 10 }}><button className="btn btn-primary" onClick={onNew}>{newLabel}</button>{importEntity && <ImportButton entities={[importEntity]} onDone={() => q.reload()} />}</div><Async q={q}>{rows => <DataGrid rows={rows} columns={columns} onRowClick={onEdit} empty={empty} />}</Async></div>
}

function Calendars() {
  const q = useLoad(() => api.calendars(), [])
  const [edit, setEdit] = useState(null)
  return (
    <>
      <CrudList q={q} importEntity="calendars" newLabel="+ New pay calendar" empty="No pay calendars yet" onNew={() => setEdit({})} onEdit={setEdit}
        columns={[{ key: 'name', label: 'Name' }, { key: 'frequency', label: 'Frequency', render: c => label(c.frequency) }, { key: 'anchor_start', label: 'A period starts', date: true }, { key: 'pay_offset_days', label: 'Pay date', render: c => `${c.pay_offset_days} days after period end` },
          { key: 'is_default', label: '', render: c => c.is_default && <StatusBadge status="active" text="Default" /> }]} />
      {edit && <CalForm c={edit} onClose={() => setEdit(null)} onSaved={() => { setEdit(null); q.reload() }} />}
    </>)
}
function CalForm({ c, onClose, onSaved }) {
  const [f, set] = useForm({ name: '', frequency: 'fortnightly', anchor_start: '', pay_offset_days: 5, is_default: false, is_active: true, ...c })
  const periods = useLoad(() => (c.id ? api.calendarPeriods(c.id, { before: 1, after: 3 }) : Promise.resolve([])), [c.id])
  return (
    <Modal title={c.id ? 'Pay calendar' : 'New pay calendar'} onClose={onClose} width={560}>
      <Grid cols={2}><Input label="Name" value={f.name} onChange={set('name')} /><Select label="Frequency" value={f.frequency} onChange={set('frequency')} options={['weekly', 'fortnightly', 'monthly']} />
        <Input label="First day of any one pay period" type="date" value={f.anchor_start} onChange={set('anchor_start')} hint="Weekly periods run 7 days, fortnightly 14, monthly = calendar months" /><Input label="Days from period end to pay date" type="number" min="0" max="31" value={f.pay_offset_days} onChange={set('pay_offset_days')} /></Grid>
      <Check label="Default calendar" checked={f.is_default} onChange={set('is_default')} /><Check label="Active" checked={f.is_active} onChange={set('is_active')} />
      {c.id && periods.data?.length > 0 && <div className="text-xs text-muted">Periods: {periods.data.map(p => `${p.period_start}→${p.period_end} (pay ${p.pay_date})`).join(' · ')}</div>}
      <div className="flex gap-1" style={{ justifyContent: 'flex-end', marginTop: 10 }}><button className="btn btn-outline" onClick={onClose}>Cancel</button>
        <button className="btn btn-primary" disabled={!f.name.trim() || !f.anchor_start} onClick={async () => { if (await act(() => api.saveCalendar({ name: f.name, frequency: f.frequency, anchor_start: f.anchor_start, pay_offset_days: Number(f.pay_offset_days), is_default: f.is_default, is_active: f.is_active }, c.id), 'Calendar saved')) onSaved() }}>Save</button></div>
    </Modal>
  )
}

function LeaveTypes() {
  const q = useLoad(() => api.leaveTypes.list(), [])
  const [edit, setEdit] = useState(null)
  return (
    <>
      <CrudList q={q} importEntity="leave_types" newLabel="+ New leave type" empty="No leave types" onNew={() => setEdit({})} onEdit={setEdit}
        columns={[{ key: 'code', label: 'Code' }, { key: 'name', label: 'Name' }, { key: 'category', label: 'Category', render: l => label(l.category) }, { key: 'is_paid', label: 'Paid', render: l => (l.is_paid ? 'Yes' : 'No') },
          { key: 'accrual_method', label: 'Accrual', render: l => (l.accrual_method === 'none' ? 'None' : `${Number(l.accrual_annual_hours)} h/yr (38h week), ${label(l.accrual_method).toLowerCase()}`) }, { key: 'loading_pct', label: 'Loading', render: l => (Number(l.loading_pct) ? `${Number(l.loading_pct)}%` : '—') },
          { key: 'is_active', label: 'Status', render: l => <StatusBadge status={l.is_active ? 'active' : 'inactive'} /> }]} />
      {edit && <LeaveForm l={edit} onClose={() => setEdit(null)} onSaved={() => { setEdit(null); q.reload() }} />}
    </>)
}
function LeaveForm({ l, onClose, onSaved }) {
  const [f, set] = useForm({ code: '', name: '', category: 'other', is_paid: true, accrual_method: 'none', accrual_annual_hours: '0', loading_pct: '0', min_service_years: '0', max_balance: '', allow_negative: false, is_active: true, ...Object.fromEntries(Object.entries(l).map(([k, v]) => [k, v ?? ''])) })
  const go = async () => { const b = { ...f, max_balance: f.max_balance === '' ? null : f.max_balance, applies_to: l.applies_to || null }; delete b.id; if (await act(() => api.leaveTypes.save(b, l.id), 'Leave type saved')) onSaved() }
  return (
    <Modal title={l.id ? `Leave type ${l.code}` : 'New leave type'} onClose={onClose} width={660}>
      <Grid cols={3}><Input label="Code" value={f.code} onChange={set('code')} /><Input label="Name" value={f.name} onChange={set('name')} />
        <Select label="Category" value={f.category} onChange={set('category')} options={['annual', 'personal', 'compassionate', 'long_service', 'parental', 'unpaid', 'other']} />
        <Select label="Accrual method" value={f.accrual_method} onChange={set('accrual_method')} options={[{ value: 'none', label: 'None' }, { value: 'per_ordinary_hour', label: 'Per ordinary hour worked' }, { value: 'fixed_per_year', label: 'Fixed per year' }]} />
        <Input label="Hours per year (38-hour week)" type="number" value={f.accrual_annual_hours} onChange={set('accrual_annual_hours')} /><Input label="Leave loading %" type="number" value={f.loading_pct} onChange={set('loading_pct')} />
        <Input label="Minimum service (years)" type="number" value={f.min_service_years} onChange={set('min_service_years')} /><Input label="Maximum balance (h)" type="number" value={f.max_balance} onChange={set('max_balance')} /></Grid>
      <Check label="Paid leave" checked={f.is_paid} onChange={set('is_paid')} /><Check label="Can be taken without a balance" checked={f.allow_negative} onChange={set('allow_negative')} /><Check label="Active" checked={f.is_active} onChange={set('is_active')} />
      <div className="flex gap-1" style={{ justifyContent: 'flex-end' }}><button className="btn btn-outline" onClick={onClose}>Cancel</button><button className="btn btn-primary" disabled={!f.code.trim() || !f.name.trim()} onClick={go}>Save</button></div>
    </Modal>
  )
}

function Funds() {
  const q = useLoad(() => api.funds.list(), [])
  const [edit, setEdit] = useState(null)
  return (
    <>
      <CrudList q={q} importEntity="super_funds" newLabel="+ New super fund" empty="No super funds" onNew={() => setEdit({})} onEdit={setEdit}
        columns={[{ key: 'name', label: 'Fund' }, { key: 'fund_type', label: 'Type', render: f => (f.fund_type === 'smsf' ? 'Self-managed' : 'APRA regulated') }, { key: 'usi', label: 'USI' }, { key: 'abn', label: 'ABN' }, { key: 'is_default', label: '', render: f => f.is_default && <StatusBadge status="active" text="Employer default" /> }]} />
      {edit && <FundForm f0={edit} onClose={() => setEdit(null)} onSaved={() => { setEdit(null); q.reload() }} />}
    </>)
}
function FundForm({ f0, onClose, onSaved }) {
  const [f, set] = useForm({ name: '', fund_type: 'apra', usi: '', abn: '', esa: '', smsf_bsb: '', smsf_account: '', smsf_account_name: '', is_default: false, is_active: true, ...Object.fromEntries(Object.entries(f0).map(([k, v]) => [k, v ?? ''])) })
  const go = async () => { const b = { ...f }; delete b.id; if (!b.smsf_account) delete b.smsf_account; if (await act(() => api.funds.save(b, f0.id), 'Fund saved')) onSaved() }
  return (
    <Modal title={f0.id ? 'Super fund' : 'New super fund'} onClose={onClose} width={620}>
      <Grid cols={2}><Input label="Fund name" value={f.name} onChange={set('name')} /><Select label="Type" value={f.fund_type} onChange={set('fund_type')} options={[{ value: 'apra', label: 'APRA regulated' }, { value: 'smsf', label: 'Self-managed (SMSF)' }]} />
        <Input label="USI" value={f.usi} onChange={set('usi')} /><Input label="Fund ABN" value={f.abn} onChange={set('abn')} />
        {f.fund_type === 'smsf' && <><Input label="SMSF BSB" value={f.smsf_bsb} onChange={set('smsf_bsb')} /><Input label="SMSF account" value={f.smsf_account} onChange={set('smsf_account')} autoComplete="off" /><Input label="SMSF account name" value={f.smsf_account_name} onChange={set('smsf_account_name')} /><Input label="ESA" value={f.esa} onChange={set('esa')} /></>}</Grid>
      <Check label="Employer default fund (used when an employee makes no choice)" checked={f.is_default} onChange={set('is_default')} /><Check label="Active" checked={f.is_active} onChange={set('is_active')} />
      <div className="flex gap-1" style={{ justifyContent: 'flex-end' }}><button className="btn btn-outline" onClick={onClose}>Cancel</button><button className="btn btn-primary" disabled={!f.name.trim()} onClick={go}>Save</button></div>
    </Modal>
  )
}

function Groups() {
  return <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit,minmax(320px,1fr))', gap: 14 }}><Simple title="Departments" api={api.departments} entity="departments" /><Simple title="Locations" api={api.locations} entity="locations" /></div>
}
function Simple({ title, api: A, entity }) {
  const q = useLoad(() => A.list(), [])
  const [f, set, setF] = useForm({ code: '', name: '' })
  const add = async () => { if (await act(() => A.save({ code: f.code.toUpperCase(), name: f.name }), 'Saved')) { setF({ code: '', name: '' }); q.reload() } }
  return (
    <Section title={title} actions={<ImportButton entities={[entity]} className="btn btn-outline btn-xs" onDone={() => q.reload()} />}>
      <Async q={q}>{rows => <DataGrid rows={rows} empty={`No ${title.toLowerCase()} yet`} columns={[{ key: 'code', label: 'Code' }, { key: 'name', label: 'Name' }, { key: 'is_active', label: '', render: r => !r.is_active && <StatusBadge status="inactive" /> }]} />}</Async>
      <div className="flex gap-1" style={{ marginTop: 8 }}><input className="input input-sm" aria-label={`${title} code`} placeholder="Code" value={f.code} onChange={set('code')} style={{ width: 90 }} /><input className="input input-sm" aria-label={`${title} name`} placeholder="Name" value={f.name} onChange={set('name')} />
        <button className="btn btn-primary btn-sm" disabled={!f.code.trim() || !f.name.trim()} onClick={add}>Add</button></div>
    </Section>
  )
}
