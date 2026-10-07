import React, { useState } from 'react'
import * as api from '../lib/taxApi.js'
import { act, Async, DataGrid, Disclaimer, Findings, Input, Modal, Money, Section, Select, Stat, Steps, useLoad } from '../components/kit.jsx'
import { label } from '../lib/format.js'
import ImportPanel from '../components/ImportPanel.jsx'
import HistoryButton from '../components/HistoryButton.jsx'

export default function PlanningTab({ me, fy }) {
  const [projected, setProjected] = useState('')
  const [levers, setLevers] = useState([])
  const [res, setRes] = useState(null)
  const [busy, setBusy] = useState(false)
  const [name, setName] = useState('')
  const [openSc, setOpenSc] = useState(null)
  const sc = useLoad(() => api.planning.scenarios(fy), [fy])
  const body = () => ({ fy, projected_profit: projected === '' ? undefined : projected, levers: levers.filter(l => l.amount !== '').map(l => ({ label: l.label || 'Lever', amount: l.amount, direction: l.direction })) })
  const run = async () => { setBusy(true); const r = await act(() => api.planning.estimate(body())); setBusy(false); if (r) setRes(r) }
  const save = async () => { if (await act(() => api.planning.saveScenario({ ...body(), name }), 'Scenario saved')) { setName(''); sc.reload() } }
  const set = (i, k) => e => setLevers(ls => ls.map((l, j) => (j === i ? { ...l, [k]: e.target.value } : l)))
  return (
    <div style={{ padding: 16 }}>
      <Disclaimer />
      <Section title={`Tax estimate ${fy}`} hint="Projects the year from the ledger year-to-date (a labelled assumption) unless you enter your own full-year profit. Levers are planning what-ifs that are not in the ledger.">
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit,minmax(220px,1fr))', gap: 10 }}>
          <Input label="Projected full-year profit (optional)" type="number" value={projected} onChange={e => setProjected(e.target.value)} hint="Leave blank to project from the ledger" />
        </div>
        {levers.map((l, i) => <div key={i} style={{ display: 'grid', gridTemplateColumns: '2fr 1fr 1fr auto', gap: 8, alignItems: 'end' }}>
          <Input label="Lever" value={l.label} onChange={set(i, 'label')} /><Input label="Amount" type="number" value={l.amount} onChange={set(i, 'amount')} />
          <Select label="Effect" value={l.direction} onChange={set(i, 'direction')} options={[{ value: 'deduct', label: 'Extra deduction' }, { value: 'add', label: 'Extra income' }]} /><button className="btn btn-ghost btn-sm" onClick={() => setLevers(ls => ls.filter((_, j) => j !== i))}>Remove</button></div>)}
        <div className="flex gap-1" style={{ marginTop: 8 }}><button className="btn btn-outline btn-sm" onClick={() => setLevers(ls => [...ls, { label: '', amount: '', direction: 'deduct' }])}>+ Lever</button><button className="btn btn-primary btn-sm" onClick={run} disabled={busy}>{busy ? 'Estimating…' : 'Estimate'}</button></div>
      </Section>
      {res && (
        <>
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit,minmax(170px,1fr))', gap: 12, marginBottom: 12 }}>
            <Stat label="Projected profit" value={<Money v={res.projected_profit} />} sub={res.projection_basis === 'assumption' ? `${res.months_elapsed} month(s) projected to 12 — assumption` : label(res.projection_basis)} />
            <Stat label="Taxable income" value={<Money v={res.result.taxable_income} />} /><Stat label="Tax assessed" value={<Money v={res.result.tax_assessed} strong />} /><Stat label="Instalments paid" value={<Money v={res.instalments_paid} />} />
            <Stat label="Expected balance" value={<Money v={res.expected_balance} strong />} tone={Number(res.expected_balance) > 0 ? 'danger' : 'success'} /></div>
          <div className="flex gap-1" style={{ marginBottom: 12 }}><input className="input input-sm" aria-label="Scenario name" placeholder="Name this scenario" value={name} onChange={e => setName(e.target.value)} style={{ maxWidth: 260 }} />
            {me.capabilities.includes('prepare') && <button className="btn btn-outline btn-sm" disabled={!name.trim()} onClick={save}>Save scenario</button>}</div>
          <Section title="Working"><Steps steps={res.result.steps} /></Section>
          <Section title="Warnings"><Findings items={res.result.warnings.map((w, i) => ({ key: 'w' + i, severity: w.kind === 'review' ? 'review' : 'warn', message: w.note || w.label }))} /></Section>
          <Section title="Year-end considerations (to discuss with a tax agent — not recommendations)">{res.year_end_considerations.map(c => <div key={c.key} className="text-sm" style={{ padding: '2px 0' }}>• {c.message}</div>)}</Section>
        </>)}
      <Section title="Saved scenarios" actions={<ImportPanel datasets={[{ key: 'planning_scenarios', label: 'Tax planning scenarios' }]} caps={me.capabilities} onDone={sc.reload} />}><Async q={sc}>{rows => <DataGrid rows={rows} empty="No scenarios saved" columns={[{ key: 'name', label: 'Scenario' }, { key: 'pp', label: 'Projected profit', render: r => <Money v={r.result.projected_profit} /> }, { key: 'ti', label: 'Taxable income', render: r => <Money v={r.result.taxable_income} /> },
        { key: 'ta', label: 'Tax assessed', render: r => <Money v={r.result.tax_assessed} /> }, { key: 'b', label: 'Balance', render: r => <Money v={r.result.balance} /> },
        { key: 'x', label: '', render: r => <span className="flex gap-1"><button className="btn btn-outline btn-xs" onClick={() => setOpenSc(r.id)}>Open</button><button className="btn btn-ghost btn-xs" onClick={async () => { if (await act(() => api.planning.removeScenario(r.id), 'Deleted')) sc.reload() }}>Delete</button><HistoryButton type="tax_scenario" id={r.id} caps={me.capabilities} /></span> }]} />}</Async></Section>
      {openSc && <ScenarioModal id={openSc} me={me} onClose={() => setOpenSc(null)} onSaved={() => { setOpenSc(null); sc.reload() }} />}
    </div>)
}


// View / edit one saved scenario: shows the saved result next to a fresh estimate, and lets you change the name and levers (the estimate is recalculated on save).
function ScenarioModal({ id, me, onClose, onSaved }) {
  const q = useLoad(() => api.planning.get(id), [id])
  const [name, setName] = useState(null)
  const [levers, setLevers] = useState(null)
  const d = q.data
  if (d && name === null) { setName(d.name); setLevers((d.levers || []).map(l => ({ ...l }))) }
  const set = (i, k) => e => setLevers(ls => ls.map((l, j) => (j === i ? { ...l, [k]: e.target.value } : l)))
  const bad = !name?.trim() || (levers || []).some(l => l.amount === '' || !(Number(l.amount) >= 0))
  const save = async () => { if (await act(() => api.planning.update(id, { name, levers: levers.map(l => ({ label: l.label || 'Lever', amount: l.amount, direction: l.direction })) }), 'Scenario updated')) onSaved() }
  return (
    <Modal title="Scenario" onClose={onClose} width={680}>
      <Async q={q}>{s => (
        <>
          <div className="text-sm text-muted">Saved result: tax assessed <Money v={s.saved.tax_assessed} /> · taxable income <Money v={s.saved.taxable_income} /> · balance <Money v={s.saved.balance} /> ({label(s.saved.basis)}). Current estimate with today's data: <Money v={s.current.result.tax_assessed} />.</div>
          <Input label="Scenario name" value={name || ''} onChange={e => setName(e.target.value)} />
          {(levers || []).map((l, i) => <div key={i} style={{ display: 'grid', gridTemplateColumns: '2fr 1fr 1fr auto', gap: 8, alignItems: 'end' }}>
            <Input label="Lever" value={l.label} onChange={set(i, 'label')} /><Input label="Amount" type="number" value={l.amount} onChange={set(i, 'amount')} />
            <Select label="Effect" value={l.direction} onChange={set(i, 'direction')} options={[{ value: 'deduct', label: 'Extra deduction' }, { value: 'add', label: 'Extra income' }]} />
            <button className="btn btn-ghost btn-sm" onClick={() => setLevers(ls => ls.filter((_, j) => j !== i))}>Remove</button></div>)}
          <button className="btn btn-outline btn-sm" onClick={() => setLevers(ls => [...ls, { label: '', amount: '', direction: 'deduct' }])}>+ Lever</button>
          <div className="flex gap-1" style={{ justifyContent: 'flex-end', marginTop: 12 }}><button className="btn btn-outline" onClick={onClose}>Close</button>
            {me.capabilities.includes('prepare') && <button className="btn btn-primary" disabled={bad} onClick={save}>Save and recalculate</button>}</div>
        </>)}</Async>
    </Modal>)
}
