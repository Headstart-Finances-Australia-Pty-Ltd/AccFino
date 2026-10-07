import React, { useState } from 'react'
import * as api from '../lib/taxApi.js'
import { act, Async, Check, DataGrid, Disclaimer, Findings, Input, Modal, Money, Section, Select, Stat, StatusBadge, useForm, useLoad, usePrompt, WorkflowBar } from '../components/kit.jsx'
import { fbtOf, fbtOptions, fmtDate, label, fyOf, fyOptions } from '../lib/format.js'
import LodgementPanel, { useLodgement } from '../components/LodgementPanel.jsx'
import ImportPanel from '../components/ImportPanel.jsx'
import HistoryButton from '../components/HistoryButton.jsx'

export default function FbtTab({ me }) {
  const [sub, setSub] = useState('fbt')
  return (
    <div style={{ padding: 16 }}>
      <div className="tabs-bar" style={{ marginBottom: 12 }}><button className={`tab-btn${sub === 'fbt' ? ' active' : ''}`} onClick={() => setSub('fbt')}>Fringe benefits tax</button><button className={`tab-btn${sub === 'div7a' ? ' active' : ''}`} onClick={() => setSub('div7a')}>Division 7A loans</button></div>
      {sub === 'fbt' ? <Fbt me={me} /> : <Div7a me={me} />}
    </div>)
}

const TYPE_FIELDS = {
  car: [['base_value', 'Car base value'], ['days_available', 'Days available (1–366)'], ['employee_contribution', 'Employee contributions']],
  loan: [['average_balance', 'Average loan balance'], ['interest_paid', 'Interest paid by employee'], ['days', 'Days outstanding']],
  expense_payment: [['actual_cost', 'Amount paid'], ['otherwise_deductible', 'Otherwise-deductible amount'], ['employee_contribution', 'Employee contributions']],
  property: [['actual_cost', 'Cost / market value'], ['employee_contribution', 'Employee contributions']], residual: [['actual_cost', 'Cost / market value'], ['employee_contribution', 'Employee contributions']],
  entertainment: [['actual_cost', 'Actual cost'], ['taxable_percent', 'Taxable % (default 100)'], ['employee_contribution', 'Employee contributions']], other: [['actual_cost', 'Cost / market value'], ['employee_contribution', 'Employee contributions']],
}

function Fbt({ me }) {
  const [year, setYear] = useState(fbtOf())
  const ben = useLoad(() => api.fbt.benefits(year), [year])
  const sum = useLoad(() => api.fbt.summary(year), [year])
  const rets = useLoad(() => api.fbt.returns(), [])
  const [edit, setEdit] = useState(null)
  const caps = me.capabilities
  const cur = (rets.data || []).find(r => r.fbt_year === year && r.status !== 'void')
  const detail = useLoad(() => (cur ? api.fbt.get(cur.id) : Promise.resolve(null)), [cur?.id, cur?.status])
  const lg = useLoad(() => (cur ? api.lodgement.state('fbt_return', cur.id) : Promise.resolve(null)), [cur?.id, cur?.status])
  const reload = () => { ben.reload(); sum.reload(); rets.reload(); detail.reload(); lg.reload() }
  const remove = async b => { if (await act(() => api.fbt.removeBenefit(year, b.id), 'Deleted')) reload() }
  const calc = async () => { if (await act(() => api.fbt.calculate(year), 'FBT return calculated')) reload() }
  return (
    <div>
      <Disclaimer />
      <div className="flex items-center gap-1" style={{ marginBottom: 10 }}><Select label="FBT year (1 April – 31 March)" value={year} onChange={e => setYear(e.target.value)} options={fbtOptions().map(v => ({ value: v, label: v.replace('FBT', 'Year ending 31 March ') }))} /></div>
      <Async q={sum}>{s => (
        <>
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit,minmax(170px,1fr))', gap: 12, marginBottom: 12 }}>
            <Stat label="Type 1 taxable value" value={<Money v={s.type1_taxable} />} /><Stat label="Type 2 taxable value" value={<Money v={s.type2_taxable} />} /><Stat label="Aggregate fringe benefits amount" value={<Money v={s.aggregate_fringe_benefits_amount} />} />
            <Stat label={`FBT payable at ${(Number(s.fbt_rate) * 100).toFixed(0)}%`} value={<Money v={s.fbt_payable} strong />} tone={Number(s.fbt_payable) > 0 ? 'danger' : undefined} /></div>
          <Findings items={s.findings} />
        </>)}</Async>
      <Section title="Benefits" actions={<><ImportPanel datasets={[{ key: 'fbt_benefits', label: 'FBT benefits' }]} caps={caps} onDone={reload} />{caps.includes('prepare') && <button className="btn btn-primary btn-sm" onClick={() => setEdit({})}>+ Benefit</button>}</>}>
        <Async q={ben}>{rows => <DataGrid rows={rows} empty="No benefits recorded for this FBT year" columns={[{ key: 'employee', label: 'Employee' }, { key: 'benefit_type', label: 'Type', render: b => label(b.benefit_type) + (b.method === 'exempt' ? ' (exempt)' : '') },
          { key: 'description', label: 'Description' }, { key: 'type1', label: 'Gross-up', render: b => (b.type1 ? 'Type 1' : 'Type 2') }, { key: 'taxable_value', label: 'Taxable value', money: true },
          { key: 'x', label: '', render: b => caps.includes('prepare') && <span className="flex gap-1"><button className="btn btn-ghost btn-xs" onClick={() => setEdit(b)}>Edit</button><button className="btn btn-ghost btn-xs" onClick={() => remove(b)}>Delete</button><HistoryButton type="tax_fbt_benefit" id={b.id} caps={caps} /></span> }]} />}</Async>
      </Section>
      <Async q={sum}>{s => s.employees.length > 0 && <Section title="Reportable fringe benefits (RFBA)" hint="Grossed up at the Type 2 rate. Reportable on the employee’s payment summary / STP when above the threshold."><DataGrid rows={s.employees} rowKey="employee" columns={[{ key: 'employee', label: 'Employee' }, { key: 'benefits', label: 'Benefits' },
        { key: 'reportable_grossed_up', label: 'Grossed-up (Type 2)', money: true }, { key: 'rfba_reportable', label: 'Reportable?', render: e => (e.rfba_reportable ? <StatusBadge status="due_soon" text="Reportable" /> : 'No') }]} /></Section>}</Async>
      <Section title="FBT return" actions={caps.includes('prepare') && (!cur || ['draft', 'prepared'].includes(cur.status)) && <button className="btn btn-outline btn-sm" onClick={calc}>{cur ? 'Recalculate' : 'Calculate return'}</button>}>
        {!cur ? <div className="text-sm text-muted">No return calculated for this FBT year yet.</div> : (
          <Async q={detail}>{r => r && <>
            <div className="text-sm">FBT payable <Money v={r.fbt_payable} strong /> · due {fmtDate(r.due_date)}{r.lodgement_reference && ` · lodged ${fmtDate(r.lodged_on)} ref ${r.lodgement_reference}`}</div>
            <WorkflowBar doc={{ ...r, calculated: true }} caps={caps} api={{ ...api.fbt, calculate: undefined, void: undefined }} noun="FBT return" onChange={reload} declarationOk={lg.data ? lg.data.declaration_ok : undefined} />
            {cur && <LodgementPanel st={lg} caps={caps} docType="fbt_return" docId={cur.id} onChange={reload} />}
            <div className="text-xs text-muted">Not assessed by AccFino: {(r.summary?.not_assessed || []).join('; ')}. Have a tax agent review before lodging.</div></>}</Async>)}
      </Section>
      {edit && <BenefitEditor year={year} item={edit} onClose={() => setEdit(null)} onSaved={() => { setEdit(null); reload() }} />}
    </div>)
}

function BenefitEditor({ year, item, onClose, onSaved }) {
  const emps = useLoad(() => api.fbt.employees().catch(() => []), [])
  const [f, set] = useForm({ benefit_type: item.benefit_type || 'car', employee: item.employee || '', employee_id: item.employee_id || '', description: item.description || '', type1: item.type1 ?? true, ...(item.inputs || {}) })
  const fields = TYPE_FIELDS[f.benefit_type] || []
  const go = async () => {
    const inputs = {}; fields.forEach(([k]) => { if (f[k] !== undefined && f[k] !== '') inputs[k] = f[k] }); if (f.exempt_reason) inputs.exempt_reason = f.exempt_reason; if (f.minor_benefit) inputs.minor_benefit = true
    if (await act(() => api.fbt.saveBenefit(year, { benefit_type: f.benefit_type, employee: f.employee, employee_id: f.employee_id ? Number(f.employee_id) : undefined, description: f.description, type1: f.type1, inputs }, item.id), 'Saved')) onSaved() }
  return (
    <Modal title={item.id ? 'Edit benefit' : 'New benefit'} onClose={onClose} width={560}>
      <Select label="Benefit type" value={f.benefit_type} onChange={set('benefit_type')} options={['car', 'loan', 'expense_payment', 'property', 'residual', 'entertainment', 'other']} />
      <Select label="Employee (from Payroll)" value={f.employee_id} blank="Not an employee / enter a name" onChange={e => set('employee_id')(e.target.value)} options={(emps.data || []).map(x => ({ value: x.id, label: x.name }))} />
      {!f.employee_id && <Input label="Employee or associate name" value={f.employee} onChange={set('employee')} />}
      <Input label="Description" value={f.description} onChange={set('description')} />
      {fields.map(([k, l]) => <Input key={k} label={l} type="number" value={f[k] ?? ''} onChange={set(k)} />)}
      <Check label="Type 1: the business can claim a GST credit for this benefit (higher gross-up rate)" checked={f.type1} onChange={set('type1')} />
      <Check label="Minor benefit (under the minor-benefit threshold, infrequent and irregular)" checked={f.minor_benefit} onChange={set('minor_benefit')} />
      <Input label="Exemption reason (leave blank unless an exemption applies; evidence required)" value={f.exempt_reason ?? ''} onChange={set('exempt_reason')} />
      <div className="flex gap-1" style={{ justifyContent: 'flex-end' }}><button className="btn btn-outline" onClick={onClose}>Cancel</button><button className="btn btn-primary" disabled={!f.employee && !f.employee_id} onClick={go}>Save</button></div>
    </Modal>)
}

function Div7a({ me }) {
  const loans = useLoad(() => api.div7a.loans(), [])
  const [sel, setSel] = useState(null)
  const [edit, setEdit] = useState(null)
  const can = me.capabilities.includes('prepare')
  return (
    <div>
      <Disclaimer />
      <Section title="Division 7A loans" hint="Loans from a private company to a shareholder or associate. Minimum yearly repayments use the ATO benchmark rate for each year." actions={<><ImportPanel datasets={[{ key: 'div7a_loans', label: 'Division 7A loans' }, { key: 'div7a_payments', label: 'Division 7A repayments and interest' }]} caps={me.capabilities} onDone={() => loans.reload()} />{can && <button className="btn btn-primary btn-sm" onClick={() => setEdit({})}>+ Loan</button>}</>}>
        <Async q={loans}>{rows => <DataGrid rows={rows} empty="No Division 7A loans recorded" onRowClick={l => setSel(l.id)} columns={[{ key: 'borrower', label: 'Borrower' }, { key: 'advance_date', label: 'Advanced', date: true }, { key: 'principal', label: 'Principal', money: true },
          { key: 'term_years', label: 'Term', render: l => `${l.term_years} yrs${l.secured ? ' secured' : ''}` }, { key: 'agreement_date', label: 'Written agreement', render: l => (l.agreement_date ? fmtDate(l.agreement_date) : <StatusBadge status="overdue" text="Missing" />) }, { key: 'status', label: 'Status', render: l => <StatusBadge status={l.status} /> }]} />}</Async>
      </Section>
      {sel && <Schedule id={sel} can={can} key={sel} onEdit={l => setEdit(l)} onGone={() => { setSel(null); loans.reload() }} />}
      {edit && <LoanEditor item={edit} onClose={() => setEdit(null)} onSaved={() => { setEdit(null); loans.reload() }} />}
    </div>)
}

function Schedule({ id, can, onEdit, onGone }) {
  const [through, setThrough] = useState(fyOf())
  const q = useLoad(() => api.div7a.schedule(id, through), [id, through])
  const pays = useLoad(() => api.div7a.payments(id), [id])
  const [dialog, ask] = usePrompt()
  const pay = async () => { const r = await ask({ title: 'Record a payment', confirmLabel: 'Record', fields: [{ key: 'paid_on', label: 'Date', type: 'date' }, { key: 'amount', label: 'Amount', type: 'number' }, { key: 'kind', label: 'Kind: repayment or interest', value: 'repayment' }] }); if (r.ok && await act(() => api.div7a.addPayment(id, r.values), 'Recorded')) { q.reload(); pays.reload() } }
  return (
    <Section title="Schedule" actions={<><Select label="" value={through} onChange={e => setThrough(e.target.value)} options={fyOptions().map(v => ({ value: v, label: `to ${v}` }))} />{can && <button className="btn btn-outline btn-sm" onClick={pay}>+ Payment</button>}</>}>
      {dialog}
      <Async q={q}>{s => (
        <>
          <Findings items={s.flags.map((f, i) => ({ key: 'f' + i, severity: f.severity, message: f.message }))} />
          <DataGrid rows={s.rows} rowKey="fy" columns={[{ key: 'fy', label: 'Year' }, { key: 'opening', label: 'Opening', money: true }, { key: 'benchmark_rate', label: 'Benchmark', render: r => `${(Number(r.benchmark_rate) * 100).toFixed(2)}%` }, { key: 'minimum_repayment', label: 'Minimum repayment', money: true },
            { key: 'repaid', label: 'Repaid', money: true }, { key: 'shortfall', label: 'Shortfall', money: true }, { key: 'closing', label: 'Closing', money: true }, { key: 'note', label: '', render: r => <span className="text-xs text-muted">{r.note}</span> }]} />
          <div className="text-xs text-muted">Not assessed: {s.not_assessed.join('; ')}.</div>
          <div className="text-sm" style={{ marginTop: 8 }}>Payments: {(pays.data || []).map(p => `${fmtDate(p.paid_on)} ${p.kind} ${p.amount}`).join(' · ') || 'none'}</div>
          {can && <div className="flex gap-1" style={{ marginTop: 8 }}><button className="btn btn-ghost btn-sm" onClick={() => onEdit(s.loan)}>Edit loan</button><button className="btn btn-ghost btn-sm" onClick={async () => { if (await act(() => api.div7a.remove(id), 'Deleted')) onGone() }}>Delete loan</button></div>}
        </>)}</Async>
    </Section>)
}

function LoanEditor({ item, onClose, onSaved }) {
  const [f, set] = useForm({ borrower: '', advance_date: '', principal: '', term_years: 7, secured: false, agreement_date: '', notes: '', ...Object.fromEntries(Object.entries(item).map(([k, v]) => [k, v ?? ''])) })
  const problems = [!f.borrower.trim() && 'Borrower is required', !f.advance_date && 'Advance date is required', !(Number(f.principal) > 0) && 'Principal must be greater than zero', Number(f.term_years) > 7 && !f.secured && 'Terms over 7 years must be secured by a registered mortgage'].filter(Boolean)
  const go = async () => { const b = { ...f, term_years: Number(f.term_years), agreement_date: f.agreement_date || null }; delete b.id; delete b.status; if (await act(() => api.div7a.save(b, item.id), 'Saved')) onSaved() }
  return (
    <Modal title={item.id ? 'Edit loan' : 'New Division 7A loan'} onClose={onClose} width={500}>
      <Input label="Borrower (shareholder or associate)" value={f.borrower} onChange={set('borrower')} />
      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 10 }}><Input label="Advance date" type="date" value={f.advance_date} onChange={set('advance_date')} /><Input label="Principal" type="number" value={f.principal} onChange={set('principal')} /></div>
      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 10 }}><Input label="Term (years)" type="number" value={f.term_years} onChange={set('term_years')} /><Input label="Written agreement date" type="date" value={f.agreement_date} onChange={set('agreement_date')} /></div>
      <Check label="Secured by registered mortgage over real property (allows up to 25 years)" checked={f.secured} onChange={set('secured')} />
      {problems.length > 0 && <div className="text-xs" style={{ color: 'var(--danger)' }}>{problems.join(' · ')}</div>}
      <div className="flex gap-1" style={{ justifyContent: 'flex-end' }}><button className="btn btn-outline" onClick={onClose}>Cancel</button><button className="btn btn-primary" disabled={problems.length > 0} onClick={go}>Save</button></div>
    </Modal>)
}
