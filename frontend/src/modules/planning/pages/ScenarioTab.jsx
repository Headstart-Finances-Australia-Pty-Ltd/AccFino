import React, { useState } from 'react'
import * as api from '../lib/planningApi.js'
import { fmtAUD, fmtDate, label } from '../lib/format.js'
import { useLoad, Async, Stat, Section, Provenance, Disclaimer, Money, StatusBadge, Table, Select, Input, Grid, Modal, act, Basis, useForm, useConfirm } from '../components/kit.jsx'

const FIELDS = [
  ['revenue_change_pct', 'Revenue change (%)'], ['expense_change_pct', 'Expense change (%)'], ['inflation_pct', 'Inflation on costs (%)'], ['payroll_change_pct', 'Payroll change (%)'],
  ['payment_delay_days', 'Customer payment delay (days; negative = faster)'], ['debt_balance', 'Current debt balance ($)'], ['interest_rate_change_pp', 'Interest rate change (percentage points)'],
  ['new_loan_amount', 'New loan amount ($)'], ['new_loan_month', 'New loan in month #'], ['new_loan_monthly_repayment', 'New loan monthly repayment ($)'], ['loan_extra_monthly', 'Extra loan repayments per month ($)'],
]

function Editor({ initial, templates, budgets, onClose, onSaved }) {
  const editing = !!initial?.id
  const [f, set, setF] = useForm({ name: initial?.name || '', kind: initial?.kind || 'custom', base_source: initial?.base_source || 'run_rate', months: initial?.months || 12, notes: initial?.notes || '' })
  const [as, setAs] = useState(() => Object.fromEntries(Object.entries(initial?.assumptions || {}).filter(([k]) => k !== 'hires').map(([k, v]) => [k, String(v)])))
  const [hires, setHires] = useState(initial?.assumptions?.hires || [])
  const template = k => { setF(s => ({ ...s, kind: k })); if (templates[k]) setAs(Object.fromEntries(Object.entries(templates[k].assumptions).map(([a, v]) => [a, String(v)]))) }
  const save = async () => {
    const assumptions = Object.fromEntries(Object.entries(as).filter(([, v]) => v !== '' && v != null).map(([k, v]) => [k, Number(v)]))
    if (hires.length) assumptions.hires = hires.map(h => ({ count: Number(h.count), start_month: Number(h.start_month), monthly_cost: Number(h.monthly_cost), label: h.label }))
    const body = { name: f.name, kind: f.kind, base_source: f.base_source, months: Number(f.months), notes: f.notes, assumptions }
    const r = await act(() => (editing ? api.scenarios.update(initial.id, body) : api.scenarios.create(body)), editing ? 'Scenario saved (new version)' : 'Scenario created')
    if (r) onSaved(r)
  }
  return (
    <Modal title={editing ? `Edit ${initial.name}` : 'New scenario'} onClose={onClose} width={760}>
      <Grid>
        <Input label="Name" value={f.name} onChange={set('name')} maxLength={80} />
        <Select label="Start from template" value={f.kind} onChange={e => template(e.target.value)} options={['base', 'optimistic', 'downside', 'custom']} disabled={editing} />
        <Select label="Base plan" value={f.base_source} onChange={set('base_source')} hint="Run-rate = last 3 complete months of ledger actuals"
          options={[{ value: 'run_rate', label: 'Ledger run-rate (last 3 complete months)' }, ...budgets.map(b => ({ value: `budget:${b.name}`, label: `Budget: ${b.name}` }))]} />
        <Input label="Months to model" type="number" min="1" max="36" value={f.months} onChange={set('months')} />
      </Grid>
      {templates[f.kind] && <Disclaimer>{templates[f.kind].note}</Disclaimer>}
      <h5 style={{ margin: '10px 0 4px' }}>Assumptions</h5>
      <Grid cols={3}>{FIELDS.map(([k, l]) => <Input key={k} label={l} type="number" step="any" value={as[k] ?? ''} onChange={e => setAs(s => ({ ...s, [k]: e.target.value }))} />)}</Grid>
      <h5 style={{ margin: '10px 0 4px' }}>Hiring</h5>
      {hires.map((h, i) => (
        <div key={i} className="flex items-center gap-1" style={{ flexWrap: 'wrap' }}>
          <Input label="Role" value={h.label || ''} onChange={e => setHires(x => x.map((y, j) => (j === i ? { ...y, label: e.target.value } : y)))} />
          <Input label="People" type="number" min="1" value={h.count} onChange={e => setHires(x => x.map((y, j) => (j === i ? { ...y, count: e.target.value } : y)))} />
          <Input label="Start month #" type="number" min="1" value={h.start_month} onChange={e => setHires(x => x.map((y, j) => (j === i ? { ...y, start_month: e.target.value } : y)))} />
          <Input label="Monthly cost each incl. super ($)" type="number" min="0" value={h.monthly_cost} onChange={e => setHires(x => x.map((y, j) => (j === i ? { ...y, monthly_cost: e.target.value } : y)))} />
          <button className="btn btn-outline btn-sm" onClick={() => setHires(x => x.filter((_, j) => j !== i))}>Remove</button>
        </div>))}
      <button className="btn btn-outline btn-sm" onClick={() => setHires(x => [...x, { label: 'New hire', count: 1, start_month: 1, monthly_cost: 0 }])}>Add hire</button>
      <div className="flex gap-1" style={{ justifyContent: 'flex-end', marginTop: 14 }}><button className="btn btn-outline" onClick={onClose}>Cancel</button><button className="btn btn-primary" onClick={save} disabled={!f.name.trim()}>Save</button></div>
    </Modal>)
}

function RunView({ r }) {
  return (
    <>
      <div role="note" className="alert alert-warning" style={{ marginBottom: 10 }}><Basis basis="SCENARIO" /> Hypothetical results. Nothing here is posted to your books and it is not a forecast.</div>
      <Provenance d={{ ...r, period_from: undefined }} />
      <div className="text-xs text-muted">Months {r.period_from} to {r.period_to} · opening cash {fmtAUD(r.base.opening_cash)} · base: {r.base.provenance.detail}</div>
      <Grid cols={3}>
        <Stat label="Revenue" basis="SCENARIO" value={fmtAUD(r.summary.revenue)} /><Stat label="Expenses" basis="SCENARIO" value={fmtAUD(r.summary.expenses)} />
        <Stat label="Profit" basis="SCENARIO" tone={Number(r.summary.profit) < 0 ? 'danger' : undefined} value={fmtAUD(r.summary.profit)} sub={r.summary.profit_margin_pct != null ? `${r.summary.profit_margin_pct}% margin` : undefined} />
        <Stat label="Closing cash" basis="SCENARIO" value={fmtAUD(r.summary.closing_cash)} /><Stat label="Lowest cash" basis="SCENARIO" tone={Number(r.summary.lowest_cash.balance) < 0 ? 'danger' : undefined} value={fmtAUD(r.summary.lowest_cash.balance)} sub={r.summary.lowest_cash.month} />
      </Grid>
      <Table caption="Scenario by month" rows={r.months} rowKey="month" columns={[{ key: 'month', label: 'Month' }, { key: 'revenue', label: 'Revenue', money: true }, { key: 'expenses', label: 'Expenses', money: true },
        { key: 'profit', label: 'Profit', money: true }, { key: 'debt_service', label: 'Debt service', money: true }, { key: 'net_cash', label: 'Net cash', money: true }, { key: 'closing_cash', label: 'Closing cash', money: true }]} />
      <Section title="Limitations"><ul style={{ margin: 0, paddingLeft: 18 }}>{r.limitations.map((l, i) => <li key={i} className="text-sm">{l}</li>)}</ul>
        <Disclaimer>Input fingerprint {String(r.input_hash).slice(0, 12)} — re-running with the same assumptions and data gives the same result.</Disclaimer></Section>
    </>)
}

export default function ScenarioTab() {
  const list = useLoad(() => api.scenarios.list(true), [])
  const tpl = useLoad(() => api.scenarios.templates(), [])
  const bud = useLoad(() => api.budgets.list(false), [])
  const me = useLoad(() => api.me(), [])
  const [edit, setEdit] = useState(null)
  const [sel, setSel] = useState(null)
  const [run, setRun] = useState(null)
  const [sens, setSens] = useState(null)
  const [cmp, setCmp] = useState([])
  const [cmpRes, setCmpRes] = useState(null)
  const [hist, setHist] = useState(null)
  const confirm = useConfirm()
  const canEdit = (me.data?.capabilities || []).includes('edit')
  const pick = id => setCmp(c => (c.includes(id) ? c.filter(x => x !== id) : [...c, id]))
  const doRun = async (id, save) => { const r = await act(() => api.scenarios.run(id, { save }), save ? 'Run saved' : undefined); if (r) { setRun(r); setSel(id); setSens(null); if (save) loadHist(id) } }
  const loadHist = async id => { const h = await act(() => api.scenarios.runs(id)); if (h) setHist(h) }
  const doSens = async id => { const r = await act(() => api.scenarios.sensitivity(id)); if (r) { setSens(r); setSel(id) } }
  const doCmp = async () => { const r = await act(() => api.scenarios.compare({ ids: cmp })); if (r) setCmpRes(r) }
  const openRun = async (id, rid) => { const r = await act(() => api.scenarios.runGet(id, rid)); if (r) setRun(r) }

  return (
    <div style={{ padding: 16 }}>
      <Async q={list}>{rows => (
        <>
          <Section title="Scenarios" hint="What-if models on top of your ledger run-rate or an approved budget. They never change your books."
            actions={canEdit && <button className="btn btn-primary btn-sm" onClick={() => setEdit({})}>New scenario</button>}>
            <Table caption="Scenarios" rows={rows} empty="No scenarios yet" hint="Create a base, optimistic or downside scenario to get started." columns={[
              { key: 'cmp', label: 'Compare', render: r => <input type="checkbox" aria-label={`Compare ${r.name}`} checked={cmp.includes(r.id)} disabled={r.status === 'archived'} onChange={() => pick(r.id)} /> },
              { key: 'name', label: 'Name' }, { key: 'kind', label: 'Type', render: r => label(r.kind) }, { key: 'status', label: 'Status', render: r => <StatusBadge status={r.status} /> },
              { key: 'version', label: 'Version', align: 'right' }, { key: 'base_source', label: 'Base', render: r => (r.base_source === 'run_rate' ? 'Run-rate' : r.base_source.replace('budget:', 'Budget: ')) },
              { key: 'a', label: 'Actions', render: r => (
                <span className="flex gap-1" style={{ flexWrap: 'wrap' }}>
                  <button className="btn btn-outline btn-sm" disabled={r.status === 'archived'} onClick={() => doRun(r.id, false)}>Preview</button>
                  {canEdit && <button className="btn btn-outline btn-sm" disabled={r.status === 'archived'} onClick={() => doRun(r.id, true)}>Run &amp; save</button>}
                  <button className="btn btn-outline btn-sm" onClick={() => doSens(r.id)}>Sensitivity</button>
                  <button className="btn btn-outline btn-sm" onClick={() => { setSel(r.id); loadHist(r.id) }}>History</button>
                  {canEdit && r.status !== 'archived' && <button className="btn btn-outline btn-sm" onClick={() => setEdit(r)}>Edit</button>}
                  {canEdit && <button className="btn btn-outline btn-sm" onClick={async () => { const n = window.prompt('Name for the copy', `${r.name} (copy)`); if (n && await act(() => api.scenarios.duplicate(r.id, n), 'Duplicated')) list.reload() }}>Duplicate</button>}
                  {canEdit && r.status !== 'archived' && <button className="btn btn-outline btn-sm" onClick={async () => { if (confirm(`Archive ${r.name}?`) && await act(() => api.scenarios.archive(r.id), 'Archived')) list.reload() }}>Archive</button>}
                </span>) }]} />
            <div className="flex items-center gap-1" style={{ marginTop: 8 }}><button className="btn btn-primary btn-sm" disabled={cmp.length < 2 || cmp.length > 6} onClick={doCmp}>Compare selected ({cmp.length})</button><span className="text-xs text-muted">Choose 2 to 6 scenarios</span></div>
          </Section>
          {cmpRes && (
            <Section title="Scenario comparison" hint={`Reference: ${cmpRes.reference}`}>
              <Table caption="Scenario comparison" rows={cmpRes.rows} rowKey="name" columns={[{ key: 'name', label: 'Scenario' }, { key: 'revenue', label: 'Revenue', money: true }, { key: 'expenses', label: 'Expenses', money: true }, { key: 'profit', label: 'Profit', money: true },
                { key: 'closing_cash', label: 'Closing cash', money: true }, { key: 'd_profit', label: 'Δ profit vs reference', money: true }, { key: 'd_closing_cash', label: 'Δ cash vs reference', money: true }]} />
              <Disclaimer>{cmpRes.basis}. {cmpRes.limitations.join(' ')}</Disclaimer>
            </Section>)}
          {run && <Section title={`Result: ${run.scenario.name} (v${run.scenario.version})`} actions={<button className="btn btn-outline btn-sm" onClick={() => setRun(null)}>Close</button>}><RunView r={run} /></Section>}
          {sens && (
            <Section title={`Sensitivity: ${sens.scenario.name}`} hint={sens.note}>
              <Table caption="Sensitivity" rows={sens.rows} columns={[{ key: 'driver', label: 'Driver', render: r => label(r.driver) }, { key: 'step', label: 'Step', align: 'right' },
                { key: 'profit_delta', label: 'Δ profit', money: true }, { key: 'closing_cash_delta', label: 'Δ closing cash', money: true }]} />
            </Section>)}
          {hist && sel && (
            <Section title="Saved runs" hint="Past results are preserved exactly as they were run">
              <Table caption="Saved runs" rows={hist} empty="No saved runs" columns={[{ key: 'created_at', label: 'Run', date: true }, { key: 'scenario_version', label: 'Version', align: 'right' }, { key: 'as_at', label: 'As at', date: true },
                { key: 'p', label: 'Profit', money: true, render: r => <Money v={r.summary?.profit} /> }, { key: 'o', label: 'Open', render: r => <button className="btn btn-outline btn-sm" onClick={() => openRun(sel, r.id)}>View</button> }]} />
            </Section>)}
          {edit && <Editor initial={edit} templates={tpl.data || {}} budgets={bud.data || []} onClose={() => setEdit(null)} onSaved={() => { setEdit(null); list.reload() }} />}
        </>)}</Async>
    </div>)
}
