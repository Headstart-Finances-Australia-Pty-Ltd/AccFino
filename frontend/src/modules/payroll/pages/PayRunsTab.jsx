import React, { useState } from 'react'
import * as api from '../lib/payrollApi.js'
import { ImportButton } from '../components/CsvImport.jsx'
import { act, Async, DataGrid, Field, Grid, Input, Issues, Loading, Modal, Money, Section, Select, Stat, StatusBadge, useConfirm, useForm, useLoad } from '../components/kit.jsx'
import { fmtAUD, fmtDate, fmtHours, label, todayISO } from '../lib/format.js'

const STEPS = ['draft', 'review', 'approved', 'finalised', 'paid']
const NEXT_HELP = {
  draft: 'Add any bonuses, back pay or reimbursements, then Calculate.',
  review: 'Check each employee, fix errors (or exclude the employee), then Approve.',
  approved: 'Approved. Finalise to lock the run, create payslips and post the ledger journal.',
  finalised: 'Finalised and locked. Prepare the payment, or Reverse the run if it was wrong.',
  paid: 'Paid. The run is locked; a reversal is the only way to correct it.',
  voided: 'This pay run was cancelled.',
}

export default function PayRunsTab({ me, onNav }) {
  const [open, setOpen] = useState(null)
  const [creating, setCreating] = useState(false)
  const q = useLoad(() => api.runs(), [])
  const can = me.capabilities.includes('run_create')
  if (open) return <RunDetail id={open} me={me} onBack={() => { setOpen(null); q.reload() }} onNav={onNav} />
  return (
    <div>
      <div className="flex items-center justify-between" style={{ marginBottom: 12 }}>
        <h3 style={{ margin: 0 }}>Pay runs</h3>
        <div className="flex gap-1">
          {can && <ImportButton entities={['pay_runs', 'pay_run_inputs']} title="Import pay runs from CSV" onDone={() => q.reload()} />}
          {can && <button className="btn btn-primary" onClick={() => setCreating(true)}>+ New pay run</button>}
        </div>
      </div>
      <Async q={q}>{rows => <DataGrid rows={rows} searchKeys={['run_no', 'name', 'status']} empty="No pay runs yet" hint="Create a pay run for the current pay period" onRowClick={r => setOpen(r.id)}
        columns={[{ key: 'run_no', label: 'Run' }, { key: 'period_start', label: 'Period', render: r => `${fmtDate(r.period_start)} – ${fmtDate(r.period_end)}` }, { key: 'pay_date', label: 'Pay date', date: true },
          { key: 'run_type', label: 'Type', render: r => (r.run_type === 'regular' ? 'Regular' : <StatusBadge status={r.run_type} />) }, { key: 'employee_count', label: 'Employees', align: 'right' },
          { key: 'total_gross', label: 'Gross', money: true }, { key: 'total_payg', label: 'PAYG', money: true }, { key: 'total_net', label: 'Net', money: true }, { key: 'total_super', label: 'Super', money: true },
          { key: 'status', label: 'Status', render: r => <><StatusBadge status={r.status} />{r.reversed_by_run_id ? <> <StatusBadge status="reversed" /></> : null}{r.error_count ? <span className="badge badge-danger" style={{ marginLeft: 4 }}>{r.error_count} error{r.error_count > 1 ? 's' : ''}</span> : null}</> }]} />}</Async>
      {creating && <NewRun onClose={() => setCreating(false)} onCreated={id => { setCreating(false); setOpen(id) }} />}
    </div>
  )
}

function NewRun({ onClose, onCreated }) {
  const cals = useLoad(() => api.calendars(), [])
  const [calId, setCal] = useState('')
  const [around, setAround] = useState(todayISO())          // periods are listed around this date: choose an earlier date for a back-dated run
  const periods = useLoad(() => (calId ? api.calendarPeriods(calId, { before: 4, after: 1, around }) : Promise.resolve([])), [calId, around])
  const [f, set, setF] = useForm({ idx: '', pay_date: '', name: '' })
  const [busy, setBusy] = useState(false)
  const p = periods.data?.[Number(f.idx)]
  const pick = e => { const i = Number(e.target.value); setF(s => ({ ...s, idx: e.target.value, pay_date: periods.data[i]?.pay_date || '' })) }
  const go = async () => {
    setBusy(true)
    const r = await act(() => api.createRun({ calendar_id: Number(calId), period_start: p.period_start, period_end: p.period_end, pay_date: f.pay_date, name: f.name || undefined }), 'Pay run created')
    setBusy(false)
    if (r) onCreated(r.id)
  }
  return (
    <Modal title="New pay run" onClose={onClose} width={560}>
      <Async q={cals}>{list => (
        <>
          <Select label="Pay calendar" value={calId} onChange={e => { setCal(e.target.value); setF({ idx: '', pay_date: '', name: '' }) }} blank="Choose a calendar…" options={list.filter(c => c.is_active).map(c => ({ value: c.id, label: `${c.name} (${c.frequency})` }))} />
          {list.length === 0 && <div className="alert alert-warning">No pay calendar yet. Create one in Settings first.</div>}
          {calId && <Input label="Show periods around" type="date" value={around} onChange={e => { setAround(e.target.value || todayISO()); setF(x => ({ ...x, idx: '', pay_date: '' })) }} hint="Change this to pick an earlier or later pay period" />}
          {calId && (periods.loading ? <Loading /> : <Select label="Pay period" value={f.idx} onChange={pick} blank="Choose a period…" options={(periods.data || []).map((x, i) => ({ value: i, label: `${fmtDate(x.period_start)} – ${fmtDate(x.period_end)} (pay ${fmtDate(x.pay_date)})` }))} />)}
          {p && <Input label="Pay date" type="date" value={f.pay_date} onChange={set('pay_date')} />}
          <Input label="Name (optional)" value={f.name} onChange={set('name')} />
          <p className="text-xs text-muted">Employees employed in the period, on this calendar's frequency, are included automatically. You can exclude individuals afterwards.</p>
          <div className="flex gap-1" style={{ justifyContent: 'flex-end' }}><button className="btn btn-outline" onClick={onClose}>Cancel</button>
            <button className="btn btn-primary" disabled={!p || !f.pay_date || busy} onClick={go}>{busy ? 'Creating…' : 'Create pay run'}</button></div>
        </>)}</Async>
    </Modal>
  )
}

function Stepper({ status, reversed }) {
  if (status === 'voided') return <StatusBadge status="voided" text="Cancelled" />
  const at = STEPS.indexOf(status)
  return (
    <div className="flex items-center gap-1" aria-label="Pay run progress" style={{ flexWrap: 'wrap' }}>
      {STEPS.map((s, i) => (
        <React.Fragment key={s}>
          <span className={`badge ${i < at ? 'badge-success' : i === at ? (reversed ? 'badge-danger' : 'badge-brand') : 'badge-neutral'}`} aria-current={i === at ? 'step' : undefined}>{i < at ? '✓ ' : ''}{label(s)}</span>
          {i < STEPS.length - 1 && <span className="text-muted">›</span>}
        </React.Fragment>))}
    </div>
  )
}

export function RunDetail({ id, me, onBack, onNav }) {
  const q = useLoad(() => api.run(id), [id])
  const [dialog, confirm] = useConfirm()
  const [expanded, setExpanded] = useState(null)
  const [adding, setAdding] = useState(null)
  const [tab, setTab] = useState('employees')
  const [busy, setBusy] = useState('')
  const cap = c => me.capabilities.includes(c)
  const r = q.data
  const doit = async (key, fn, ok) => { setBusy(key); const x = await act(fn, ok); setBusy(''); if (x) q.reload(); return x }
  if (q.loading && !r) return <Loading />
  if (q.error) return <div className="alert alert-error">{q.error}</div>
  const editable = ['draft', 'review'].includes(r.status)
  const locked = r.locked
  const finalise = async () => {
    const c = await confirm({ title: 'Finalise pay run', confirmLabel: 'Finalise and lock', message: `Finalise ${r.run_no}? Gross ${fmtAUD(r.total_gross)}, PAYG ${fmtAUD(r.total_payg)}, net ${fmtAUD(r.total_net)}. This creates payslips, updates leave and super, and posts the ledger journal. The run can no longer be edited (only reversed).` })
    if (c.ok) doit('finalise', () => api.runAction(r.id, 'finalise'), 'Pay run finalised')
  }
  const reverse = async () => {
    const c = await confirm({ title: 'Reverse pay run', danger: true, confirmLabel: 'Reverse', message: `Reverse ${r.run_no}? A reversal run cancels every amount, the ledger journal is reversed, and leave and timesheets are released. The original stays on record.`, reasonLabel: 'Reason for reversal' })
    if (c.ok) doit('reverse', () => api.runAction(r.id, 'reverse', { reason: c.reason }), 'Pay run reversed')
  }
  const voidRun = async () => {
    const c = await confirm({ title: 'Cancel pay run', danger: true, confirmLabel: 'Cancel pay run', message: `Cancel ${r.run_no}? Nothing has been paid or posted.`, reasonLabel: 'Reason' })
    if (c.ok) doit('void', () => api.runAction(r.id, 'void', { reason: c.reason }), 'Pay run cancelled')
  }
  const exclude = async e => {
    const c = await confirm({ title: 'Exclude employee', confirmLabel: 'Exclude', message: `Exclude ${e.employee_name} from this pay run?`, reasonLabel: 'Reason' })
    if (c.ok) doit('x' + e.employee_id, () => api.excludeEmployee(r.id, e.employee_id, c.reason), 'Employee excluded')
  }
  const included = r.employees.filter(e => e.status === 'included')
  const nErr = included.filter(e => e.errors.length).length
  return (
    <div>
      {dialog}
      <button className="btn btn-ghost btn-sm" onClick={onBack}>← All pay runs</button>
      <div className="flex items-center justify-between" style={{ margin: '8px 0', flexWrap: 'wrap', gap: 8 }}>
        <div><h3 style={{ margin: 0 }}>{r.run_no} {r.run_type === 'reversal' && <StatusBadge status="reversal" />} {r.reversed_by_run_id && <StatusBadge status="reversed" />}</h3>
          <div className="text-sm text-muted">{r.name} · period {fmtDate(r.period_start)} – {fmtDate(r.period_end)} · pay date {fmtDate(r.pay_date)} · rules {r.rule_set}</div></div>
        <Stepper status={r.status} reversed={!!r.reversed_by_run_id} />
      </div>
      <div className={`alert ${locked ? 'alert-success' : 'alert-warning'}`} role="status">
        {locked ? '🔒 ' : ''}{r.run_type === 'reversal' ? `This is the reversal of another pay run. It cannot be changed.` : NEXT_HELP[r.status]}</div>

      <div className="flex gap-1" style={{ margin: '10px 0', flexWrap: 'wrap' }}>
        {cap('run_create') && editable && <button className="btn btn-primary" disabled={!!busy} onClick={() => doit('calc', () => api.runAction(r.id, 'calculate'), 'Calculated')}>{busy === 'calc' ? 'Calculating…' : r.status === 'draft' ? 'Calculate' : 'Recalculate'}</button>}
        {cap('run_approve') && r.status === 'review' && <button className="btn btn-success" disabled={!!busy || nErr > 0} title={nErr ? 'Resolve errors first' : ''} onClick={() => doit('approve', () => api.runAction(r.id, 'approve'), 'Approved')}>Approve</button>}
        {cap('run_approve') && r.status === 'approved' && <button className="btn btn-outline" disabled={!!busy} onClick={() => doit('unapprove', () => api.runAction(r.id, 'unapprove'), 'Returned to review')}>Return to review</button>}
        {cap('run_finalise') && r.status === 'approved' && <button className="btn btn-success" disabled={!!busy} onClick={finalise}>Finalise…</button>}
        {cap('payments_manage') && r.status === 'finalised' && !r.reversed_by_run_id && <button className="btn btn-primary" onClick={() => onNav?.('payments')}>Go to payments</button>}
        {cap('stp_manage') && locked && r.run_type !== 'reversal' && <button className="btn btn-outline" disabled={!!busy} onClick={() => doit('stp', () => api.stpPrepare(r.id), 'STP pay event prepared (not lodged)')}>Prepare STP event</button>}
        {cap('run_create') && !locked && r.status !== 'voided' && <button className="btn btn-outline" onClick={voidRun}>Cancel run…</button>}
        {cap('run_reverse') && ['finalised', 'paid'].includes(r.status) && r.run_type !== 'reversal' && !r.reversed_by_run_id && <button className="btn btn-danger btn-outline" onClick={reverse}>Reverse…</button>}
      </div>

      <div className="stats-grid" style={{ marginBottom: 12 }}>
        <Stat label="Employees" value={r.employee_count} sub={nErr ? `${nErr} with errors` : r.status === 'draft' ? 'not calculated' : 'no errors'} tone={nErr ? 'danger' : undefined} />
        <Stat label="Gross" value={fmtAUD(r.total_gross)} sub={`Taxable ${fmtAUD(r.total_taxable)}`} />
        <Stat label="PAYG + study loan" value={fmtAUD(Number(r.total_payg) + Number(r.total_study_loan))} sub={`Deductions ${fmtAUD(r.total_deductions)}`} />
        <Stat label="Net pay" value={fmtAUD(r.total_net)} sub={`Super ${fmtAUD(r.total_super)} · cost ${fmtAUD(r.total_employer_cost)}`} />
      </div>

      <div className="tabs-bar" style={{ marginBottom: 10 }}>
        {[['employees', 'Employees'], ['inputs', 'Bonuses & adjustments'], ['journal', 'Ledger journal'], ['integrity', 'Integrity']].map(([k, t]) => <button key={k} className={`tab-btn${tab === k ? ' active' : ''}`} onClick={() => setTab(k)}>{t}</button>)}
      </div>

      {tab === 'employees' && (
        <div className="data-table-wrap" style={{ overflowX: 'auto' }}>
          <table className="data-table">
            <thead><tr><th>Employee</th><th className="text-right">Hours</th><th className="text-right">Gross</th><th className="text-right">PAYG</th><th className="text-right">Other ded.</th><th className="text-right">Net</th><th className="text-right">Super</th><th>Checks</th><th /></tr></thead>
            <tbody>{r.employees.map(e => (
              <React.Fragment key={e.id}>
                <tr style={{ opacity: e.status === 'excluded' ? 0.5 : 1, cursor: 'pointer' }} onClick={() => setExpanded(expanded === e.id ? null : e.id)}>
                  <td><b>{e.employee_number}</b> {e.employee_name} {e.status === 'excluded' && <StatusBadge status="cancelled" text="Excluded" />}</td>
                  <td className="text-right">{fmtHours(Number(e.ordinary_hours) + Number(e.overtime_hours) + Number(e.leave_hours))}</td>
                  <td className="text-right"><Money v={e.gross} /></td><td className="text-right"><Money v={Number(e.payg) + Number(e.study_loan)} /></td>
                  <td className="text-right"><Money v={Number(e.pretax_deductions) + Number(e.posttax_deductions) + Number(e.sacrifice_super)} /></td><td className="text-right"><Money v={e.net} strong /></td><td className="text-right"><Money v={e.super_total} /></td>
                  <td>{e.status === 'excluded' ? <span className="text-xs text-muted">{e.exclusion_reason}</span> : r.status === 'draft' ? <span className="text-xs text-muted">—</span> : e.errors.length ? <StatusBadge status="error" text={`${e.errors.length} error${e.errors.length > 1 ? 's' : ''}`} /> : e.warnings.length ? <StatusBadge status="warning" text={`${e.warnings.length} warning${e.warnings.length > 1 ? 's' : ''}`} /> : <StatusBadge status="finalised" text="OK" />}</td>
                  <td onClick={ev => ev.stopPropagation()}>{editable && cap('run_create') && (e.status === 'included' ? <button className="btn btn-ghost btn-xs" onClick={() => exclude(e)}>Exclude</button> : <button className="btn btn-ghost btn-xs" onClick={() => doit('i' + e.employee_id, () => api.includeEmployee(r.id, e.employee_id), 'Included')}>Include</button>)}</td>
                </tr>
                {expanded === e.id && (
                  <tr><td colSpan={9} style={{ background: 'var(--surface-2)' }}>
                    <Issues errors={e.errors} warnings={e.warnings} />
                    {e.lines ? (
                      <table className="summary-table" style={{ marginTop: 6 }}><thead><tr><th>Ref</th><th>Item</th><th>Type</th><th className="text-right">Hours</th><th className="text-right">Rate</th><th className="text-right">Amount</th><th>Note</th></tr></thead>
                        <tbody>{e.lines.map(l => <tr key={l.id}><td className="mono text-xs">{l.txn_ref}</td><td>{l.name}</td><td>{label(l.kind)}</td><td className="text-right">{l.hours != null ? fmtHours(l.hours) : ''}</td><td className="text-right">{l.rate != null ? fmtAUD(l.rate) : ''}</td><td className="text-right"><Money v={l.amount} /></td><td className="text-xs text-muted">{l.note || l.source}</td></tr>)}</tbody></table>) : null}
                    <div className="text-xs text-muted" style={{ marginTop: 6 }}>Tax scale {e.tax_scale || '—'} · taxable <Money v={e.taxable} />{e.ytd && <> · YTD gross {fmtAUD(e.ytd.gross)}, tax {fmtAUD(e.ytd.tax)}, super {fmtAUD(e.ytd.super_total)}</>}</div>
                    {editable && cap('run_create') && e.status === 'included' && <button className="btn btn-outline btn-sm" style={{ marginTop: 6 }} onClick={() => setAdding(e)}>+ Add bonus / adjustment…</button>}
                  </td></tr>)}
              </React.Fragment>))}</tbody>
          </table>
        </div>)}

      {tab === 'inputs' && <Inputs r={r} editable={editable && cap('run_create')} onAdd={() => setAdding(included[0] || null)} onRemove={async i => { if (await act(() => api.removeRunInput(r.id, i.id), 'Removed')) q.reload() }} />}
      {tab === 'journal' && <Journal id={r.id} status={r.status} can={cap('journal_view')} />}
      {tab === 'integrity' && <Integrity id={r.id} />}
      {adding && <AddInput run={r} employee={adding} onClose={() => setAdding(null)} onAdded={() => { setAdding(null); q.reload() }} />}
    </div>
  )
}

function Inputs({ r, editable, onAdd, onRemove }) {
  const name = id => r.employees.find(e => e.employee_id === id)?.employee_name
  return (
    <div>
      {editable && <button className="btn btn-outline" onClick={onAdd} disabled={!r.employees.some(e => e.status === 'included')}>+ Add bonus, back pay, reimbursement or termination payment</button>}
      <DataGrid rows={r.inputs} empty="No manual inputs" hint="Recurring allowances and deductions are set on each employee" columns={[{ key: 'employee_id', label: 'Employee', render: i => name(i.employee_id) }, { key: 'pay_item_id', label: 'Pay item ID' },
        { key: 'amount', label: 'Amount', money: true }, { key: 'hours', label: 'Hours', hours: true }, { key: 'note', label: 'Note' }, { key: 'x', label: '', render: i => editable && <button className="btn btn-ghost btn-xs" onClick={() => onRemove(i)}>Remove</button> }]} />
    </div>
  )
}

function AddInput({ run, employee, onClose, onAdded }) {
  const items = useLoad(() => api.payItems.list(), [])
  const [f, set] = useForm({ employee_id: employee.employee_id, pay_item_id: '', amount: '', hours: '', note: '', periods: '', leave_pre1993: false, genuine_redundancy: false })
  const sugg = useLoad(() => api.terminationSuggestion(employee.employee_id).catch(() => []), [employee.employee_id])
  const usable = (items.data || []).filter(i => i.is_active && !['salary_adjustment', 'leave_loading'].includes(i.kind) && !i.is_system && !['overtime', 'penalty', 'leave', 'unpaid_leave'].includes(i.kind) && !['deduction_posttax', 'deduction_pretax'].includes(i.kind) || ['TLEAVE', 'ETP'].includes(i.code))
  const item = usable.find(i => String(i.id) === String(f.pay_item_id))
  const go = async () => {
    const b = { employee_id: Number(f.employee_id), pay_item_id: Number(f.pay_item_id), amount: f.amount || null, hours: f.hours || null, note: f.note, periods: f.periods || null, leave_pre1993: f.leave_pre1993, genuine_redundancy: f.genuine_redundancy }
    if (await act(() => api.addRunInput(run.id, b), 'Added')) onAdded()
  }
  const emps = run.employees.filter(e => e.status === 'included')
  return (
    <Modal title="Add to pay run" onClose={onClose} width={560}>
      <Select label="Employee" value={f.employee_id} onChange={set('employee_id')} options={emps.map(e => ({ value: e.employee_id, label: `${e.employee_number} ${e.employee_name}` }))} />
      <Select label="Pay item" value={f.pay_item_id} onChange={set('pay_item_id')} blank="Choose…" options={usable.map(i => ({ value: i.id, label: `${i.code} · ${i.name}` }))} />
      {item?.calc_method === 'hours_x_rate' && <Input label="Hours" type="number" value={f.hours} onChange={set('hours')} />}
      {item?.calc_method !== 'hours_x_rate' && <Input label="Amount" type="number" min="0" step="0.01" value={f.amount} onChange={set('amount')} />}
      {item?.code === 'TLEAVE' && sugg.data?.length > 0 && <div className="alert alert-success text-sm">Unused leave suggestion: {sugg.data.map(s => `${s.leave_type} ${s.hours}h = ${fmtAUD(s.amount)}`).join('; ')} <button className="btn btn-ghost btn-xs" onClick={() => set('amount')(sugg.data.reduce((s, x) => s + Number(x.amount), 0).toFixed(2))}>Use</button></div>}
      {item?.payg_treatment === 'additional' && <Input label="Pay periods this payment relates to (optional)" type="number" min="1" max="52" value={f.periods} onChange={set('periods')} hint="Blank = the whole year (ATO Method A)" />}
      {item?.code === 'TLEAVE' && <label className="flex items-center gap-1"><input type="checkbox" checked={f.leave_pre1993} onChange={set('leave_pre1993')} /> Balance accrued before 18 August 1993</label>}
      {item?.code === 'ETP' && <label className="flex items-center gap-1"><input type="checkbox" checked={f.genuine_redundancy} onChange={set('genuine_redundancy')} /> Genuine redundancy (tax-free limit applies)</label>}
      <Input label="Note" value={f.note} onChange={set('note')} />
      <div className="flex gap-1" style={{ justifyContent: 'flex-end' }}><button className="btn btn-outline" onClick={onClose}>Cancel</button><button className="btn btn-primary" disabled={!f.pay_item_id} onClick={go}>Add</button></div>
    </Modal>
  )
}

function Journal({ id, status, can }) {
  const q = useLoad(() => (can ? api.runJournal(id) : Promise.resolve(null)), [id, status])
  if (!can) return <div className="text-muted">You do not have access to ledger journals.</div>
  return <Async q={q}>{j => !j ? null : !j.posted ? <div className="alert alert-warning">{j.message}</div> : (
    <div>
      <div className="text-sm" style={{ marginBottom: 8 }}>Ledger journal #{j.ledger_journal?.journal_no} dated {fmtDate(j.ledger_journal?.date)} · <StatusBadge status={j.status === 'reversed' ? 'reversed' : 'finalised'} text={j.status === 'reversed' ? 'Reversed' : 'Posted'} /> · {j.balanced ? '✓ debits equal credits' : '✖ OUT OF BALANCE'}</div>
      <DataGrid rows={j.by_account} rowKey="account_id" columns={[{ key: 'code', label: 'Account', render: a => `${a.code} ${a.name}` }, { key: 'debit', label: 'Debit', money: true }, { key: 'credit', label: 'Credit', money: true }]}
        footer={<tr><td><b>Total</b></td><td className="text-right"><Money v={j.total_debit} strong /></td><td className="text-right"><Money v={j.total_credit} strong /></td></tr>} />
      <details style={{ marginTop: 10 }}><summary className="text-sm">Employee-level lines ({j.lines.length}): traceable to payroll transactions</summary>
        <DataGrid rows={j.lines.map((l, i) => ({ ...l, id: i }))} pageSize={15} searchKeys={['description', 'txn_ref', 'account_name']} columns={[{ key: 'txn_ref', label: 'Transaction' }, { key: 'account_code', label: 'Account', render: l => `${l.account_code} ${l.account_name}` }, { key: 'description', label: 'Description' }, { key: 'debit', label: 'Dr', money: true }, { key: 'credit', label: 'Cr', money: true }]} /></details>
    </div>)}</Async>
}

function Integrity({ id }) {
  const q = useLoad(() => api.runIntegrity(id), [id])
  return <Async q={q}>{r => !r.checked ? <div className="alert alert-warning">{r.reason}</div> : <div className={`alert ${r.intact ? 'alert-success' : 'alert-error'}`}>{r.intact ? '✓ ' : '✖ '}{r.message}</div>}</Async>
}
