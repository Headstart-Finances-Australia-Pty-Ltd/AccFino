import React, { useState } from 'react'
import * as api from '../lib/invApi.js'
import { act, Async, Check, DataGrid, Disclaimer, Grid, Input, Modal, Money, Notice, Pct, Section, Select, Stat, StatusBadge, useForm, useLoad, usePrompt } from '../components/kit.jsx'
import DocsPanel from '../components/DocsPanel.jsx'
import HistoryButton from '../components/HistoryButton.jsx'
import ImportPanel from '../components/ImportPanel.jsx'
import { fmtAUD, fmtDate, label, todayISO } from '../lib/format.js'

const IMPORTS = [{ key: 'properties', label: 'Properties' }, { key: 'property_entries', label: 'Rent, expenses and capital items' }, { key: 'valuations', label: 'Valuations and loan balances' }, { key: 'liabilities', label: 'Loans (liabilities)' }]
const blank = o => Object.fromEntries(Object.entries(o || {}).map(([k, v]) => [k, v ?? '']))

export default function PropertyTab({ me }) {
  const [bump, setBump] = useState(0)
  const [open, setOpen] = useState(null)
  const [edit, setEdit] = useState(null)
  const caps = me.capabilities
  const q = useLoad(() => api.property.list(), [bump])
  const again = () => setBump(n => n + 1)
  if (open) return <PropertyDetail id={open} me={me} onBack={() => { setOpen(null); again() }} />
  return (
    <div style={{ padding: 16 }}>
      <Disclaimer />
      <div className="text-sm text-muted" style={{ marginBottom: 10 }}>Your property register: purchase and cost base, rent and expenses, valuations and loans, yields and equity, and a capital gains estimate. Dates are contract dates, as for CGT.</div>
      <Async q={q}>{o => (
        <>
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit,minmax(180px,1fr))', gap: 12, marginBottom: 12 }}><Stat label="Property value (your share)" value={<Money v={o.total_value} strong />} /><Stat label="Loans" value={<Money v={o.total_loans} />} /><Stat label="Equity (your share)" value={<Money v={o.total_equity} strong />} /></div>
          <Section title="Properties" actions={<>{caps.includes('edit') && <button className="btn btn-primary btn-sm" onClick={() => setEdit({})}>+ Property</button>}<ImportPanel datasets={IMPORTS} caps={caps} onDone={again} /></>}>
            <DataGrid rows={o.rows} searchKeys={['name', 'address']} empty="No properties yet" hint="Add a property or import a file." onRowClick={r => setOpen(r.id)} columns={[
              { key: 'name', label: 'Property', render: r => <><strong>{r.name}</strong><div className="text-xs text-muted">{r.address}</div></> }, { key: 'use', label: 'Use', render: r => label(r.use) }, { key: 'status', label: 'Status', render: r => <StatusBadge status={r.status === 'sold' ? 'completed' : 'active'} text={label(r.status)} /> },
              { key: 'your_share_value', label: 'Value', money: true }, { key: 'loan', label: 'Loan', money: true }, { key: 'your_share_equity', label: 'Equity', money: true }, { key: 'gross_yield', label: 'Gross yield', render: r => <Pct v={r.gross_yield} />, align: 'right' },
              { key: 'net_yield', label: 'Net yield', render: r => <Pct v={r.net_yield} />, align: 'right' }, { key: 'cash_flow', label: 'Cash flow (12m)', money: true }, { key: 'warnings', label: '', render: r => (r.warnings ? <span className="badge badge-warning">{r.warnings} to check</span> : '') }]} />
          </Section>
        </>)}</Async>
      {edit && <PropertyForm item={edit.id ? edit : null} onClose={() => setEdit(null)} onSaved={() => { setEdit(null); again() }} />}
    </div>)
}

function PropertyDetail({ id, me, onBack }) {
  const caps = me.capabilities
  const [sale, setSale] = useState({ price: '', date: '' })
  const [applied, setApplied] = useState({})
  const [bump, setBump] = useState(0)
  const [edit, setEdit] = useState(false)
  const [entry, setEntry] = useState(null)
  const [val, setVal] = useState(false)
  const [dialog, ask] = usePrompt()
  const q = useLoad(() => api.property.detail(id, applied), [id, JSON.stringify(applied), bump])
  const again = () => setBump(n => n + 1)
  const voidEntry = async e => { const r = await ask({ title: 'Void entry', message: `${label(e.kind)} ${fmtAUD(e.amount)} on ${fmtDate(e.entry_date)}`, confirmLabel: 'Void', fields: [{ key: 'reason', label: 'Reason (at least 5 characters)', value: '' }] }); if (r.ok && await act(() => api.property.voidEntry(id, e.id, r.values.reason), 'Voided')) again() }
  return (
    <div style={{ padding: 16 }}>
      {dialog}
      <button className="btn btn-outline btn-sm" onClick={onBack}>← All properties</button>
      <Async q={q}>{d => {
        const p = d.property, pf = d.performance, est = d.cgt_estimate
        return (
          <>
            <div className="flex items-center justify-between" style={{ margin: '10px 0', flexWrap: 'wrap', gap: 8 }}><h3 style={{ margin: 0 }}>{p.name} <span className="badge badge-neutral">{label(p.use)}</span>{Number(p.ownership_pct) < 100 && <span className="badge badge-info"> {p.ownership_pct}% share</span>}</h3>
              <span className="flex gap-1">{caps.includes('edit') && <button className="btn btn-outline btn-sm" onClick={() => setEdit(true)}>Edit property</button>}<HistoryButton type="inv_property" id={id} caps={caps} /></span></div>
            <Notice items={d.warnings} />
            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit,minmax(160px,1fr))', gap: 10, marginBottom: 12 }}>
              <Stat label="Value" value={<Money v={d.value} strong />} sub={d.value_basis} /><Stat label="Loan" value={<Money v={d.loan_balance} />} /><Stat label="Equity (your share)" value={<Money v={d.your_share_equity} strong />} /><Stat label="Gross yield" value={<Pct v={pf.gross_yield} />} />
              <Stat label="Net yield" value={<Pct v={pf.net_yield} />} sub="after running costs, before interest" /><Stat label="Cash flow after interest (12m)" value={<Money v={pf.cash_flow_after_interest} strong />} sub={pf.negatively_geared ? 'negatively geared' : 'positively geared'} tone={pf.negatively_geared ? 'danger' : undefined} />
              <Stat label="Loan to value" value={<Pct v={pf.lvr} digits={1} />} /><Stat label="Capital growth" value={<Money v={pf.capital_growth} />} sub={pf.cagr != null ? `${(pf.cagr * 100).toFixed(1)}% a year` : 'needs 6+ months held'} /></div>
            <Section title="Income and deductions by income year" hint="Capital works are estimated from the construction cost where you have not recorded the amount claimed.">
              <DataGrid rows={d.schedule.map(s => ({ ...s, id: s.fy }))} empty="No income or expense entries yet" columns={[{ key: 'fy', label: 'Year' }, { key: 'rent', label: 'Rent', money: true }, { key: 'expenses', label: 'Expenses', money: true }, { key: 'loan_interest', label: 'Loan interest', money: true },
                { key: 'capital_works', label: 'Capital works', render: s => <><Money v={s.capital_works} />{s.capital_works_estimated ? ' ~' : ''}</>, align: 'right' }, { key: 'depreciation', label: 'Depreciation', money: true }, { key: 'total_deductions', label: 'Deductions', money: true },
                { key: 'net_rental_result', label: 'Net result', money: true }, { key: 'your_share_net', label: 'Your share', money: true }]} /></Section>
            <Section title="Rent, expenses and capital items" actions={caps.includes('edit') && <button className="btn btn-primary btn-sm" onClick={() => setEntry({})}>+ Entry</button>}>
              <DataGrid rows={d.entries} searchKeys={['description', 'category', 'kind']} empty="Nothing recorded" columns={[{ key: 'entry_date', label: 'Date', date: true }, { key: 'kind', label: 'Kind', render: e => label(e.kind) }, { key: 'category', label: 'Category', render: e => (e.category ? label(e.category) : '—') }, { key: 'amount', label: 'Amount', money: true },
                { key: 'description', label: 'Description' }, { key: 'x', label: '', render: e => <span className="flex gap-1">{caps.includes('edit') && <button className="btn btn-ghost btn-xs" onClick={() => setEntry(e)}>Edit</button>}{caps.includes('edit') && <button className="btn btn-ghost btn-xs" onClick={() => voidEntry(e)}>Void</button>}</span> }]} /></Section>
            <Section title="Valuations" actions={caps.includes('edit') && <button className="btn btn-outline btn-sm" onClick={() => setVal(true)}>+ Valuation</button>}>
              <DataGrid rows={d.valuations} empty="No valuations: the purchase price is used" columns={[{ key: 'as_at', label: 'As at', date: true }, { key: 'value', label: 'Value', money: true }, { key: 'basis', label: 'Basis' }, { key: 'x', label: '', render: v => caps.includes('edit') && <button className="btn btn-ghost btn-xs" onClick={async () => { if (window.confirm('Delete this valuation?') && await act(() => api.valuations.remove(v.id), 'Deleted')) again() }}>Delete</button> }]} /></Section>
            <Section title="Cost base and capital gain" hint="Five cost base elements, less capital works already claimed. The CGT event is the contract date. An estimate: confirm with a tax agent.">
              <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit,minmax(170px,1fr))', gap: 10, marginBottom: 10 }}>
                <Stat label="1 Price paid (less plant)" value={<Money v={d.cost_base.element1_price} />} /><Stat label="2 Incidental costs" value={<Money v={d.cost_base.element2_incidental} />} sub="stamp duty, legal, selling" /><Stat label="3 Ownership costs" value={<Money v={d.cost_base.element3_ownership} />} />
                <Stat label="4 Capital improvements" value={<Money v={d.cost_base.element4_improvements} />} /><Stat label="Less capital works claimed" value={<Money v={d.cost_base.capital_works_claimed} />} /><Stat label="Cost base" value={<Money v={d.cost_base.cost_base} strong />} /></div>
              <Grid cols={3}><Input label="Planned sale price" type="number" value={sale.price} onChange={e => setSale(s => ({ ...s, price: e.target.value }))} /><Input label="Planned contract date" type="date" value={sale.date} onChange={e => setSale(s => ({ ...s, date: e.target.value }))} />
                <div style={{ marginBottom: 14, alignSelf: 'end' }}><button className="btn btn-outline btn-sm" disabled={!(Number(sale.price) > 0 && sale.date)} onClick={() => setApplied({ sale_price: sale.price, sale_date: sale.date })}>Estimate the gain</button></div></Grid>
              {est && (
                <div role="group" aria-label="Capital gain estimate">
                  <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit,minmax(170px,1fr))', gap: 10 }}>
                    <Stat label={est.planned ? 'Planned proceeds' : 'Capital proceeds'} value={<Money v={est.capital_proceeds} />} /><Stat label="Capital gain/(loss)" value={<Money v={est.capital_gain_or_loss} strong />} tone={Number(est.capital_gain_or_loss) < 0 ? 'danger' : undefined} />
                    <Stat label="Main residence exempt" value={<Money v={est.exempt_amount} />} sub={`${(Number(est.main_residence_fraction) * 100).toFixed(0)}% of ownership`} /><Stat label={`Discount (${label(est.holder)})`} value={<Money v={est.discount_applied} />} sub={est.held_over_12_months ? 'held over 12 months' : 'held under 12 months'} />
                    <Stat label="Net capital gain" value={<Money v={est.net_capital_gain} strong />} /></div>
                  {est.notes.map((n, i) => <div key={i} className="text-xs text-muted" style={{ marginTop: 4 }}>{n}</div>)}
                  {!est.planned && caps.includes('edit') && <div style={{ marginTop: 8 }}><button className="btn btn-primary btn-sm" onClick={async () => { const r = await act(() => api.property.sendSale(id, false)); if (r && r !== true) window.alert(`${r.added} added to Taxation > CGT, ${r.skipped_duplicates} already there, ${r.rejected} rejected.`) }}>Send the sale to Tax (CGT)</button></div>}
                </div>)}
            </Section>
            <Section title="Documents"><DocsPanel ownerType="property" ownerId={id} caps={caps} /></Section>
            {edit && <PropertyForm item={p} onClose={() => setEdit(false)} onSaved={() => { setEdit(false); again() }} />}
            {entry && <EntryForm pid={id} item={entry.id ? entry : null} onClose={() => setEntry(null)} onSaved={() => { setEntry(null); again() }} />}
            {val && <ValuationForm pid={id} loanId={p.loan_liability_id} onClose={() => setVal(false)} onSaved={() => { setVal(false); again() }} />}
          </>)
      }}</Async>
    </div>)
}

function PropertyForm({ item, onClose, onSaved }) {
  const refs = useLoad(async () => ({ reference: await api.reference(), loans: await api.liabilities.list() }), [])
  return <Modal title={item ? 'Edit property' : 'New property'} onClose={onClose} width={760}><Async q={refs}>{r => <PropertyInner item={item} r={r} onClose={onClose} onSaved={onSaved} />}</Async></Modal>
}
function PropertyInner({ item, r, onClose, onSaved }) {
  const [f, set] = useForm({ name: '', address: '', suburb: '', state: '', postcode: '', property_type: 'house', use: 'investment', ownership_pct: '100', contract_date: '', settlement_date: '', purchase_price: '', stamp_duty: '', legal_costs: '', other_acq_costs: '', depreciating_assets_value: '',
    construction_cost: '', construction_date: '', capital_works_rate: '0.025', main_residence_from: '', main_residence_until: '', first_income_date: '', value_when_first_income: '', sale_contract_date: '', sale_price: '', selling_costs: '', loan_liability_id: '', notes: '', ...blank(item) })
  const problems = [!f.name.trim() && 'Name is required', !f.contract_date && 'Contract date is required (the CGT date)', !(Number(f.purchase_price) > 0) && 'Purchase price is required', !(Number(f.ownership_pct) > 0 && Number(f.ownership_pct) <= 100) && 'Ownership must be more than 0 and at most 100',
    f.settlement_date && f.contract_date && f.settlement_date < f.contract_date && 'Settlement cannot be before the contract date', f.sale_contract_date && !(Number(f.sale_price) > 0) && 'A sale needs a price'].filter(Boolean)
  const go = async () => { const b = { ...f }; delete b.id; for (const k of Object.keys(b)) if (b[k] === '') b[k] = null; if (await act(() => api.property.save(b, item?.id), 'Saved')) onSaved() }
  return (
    <>
      <Grid cols={3}><Input label="Name" value={f.name} onChange={set('name')} /><Input label="Address" value={f.address} onChange={set('address')} /><Input label="Suburb" value={f.suburb} onChange={set('suburb')} />
        <Select label="State" value={f.state} blank="—" onChange={set('state')} options={r.reference.states} /><Input label="Postcode" value={f.postcode} onChange={set('postcode')} /><Select label="Type" value={f.property_type} onChange={set('property_type')} options={r.reference.property_types} />
        <Select label="Use" value={f.use} onChange={set('use')} options={r.reference.property_uses} /><Input label="Your ownership %" type="number" value={f.ownership_pct} onChange={set('ownership_pct')} /><Select label="Loan" value={f.loan_liability_id} blank="None" onChange={set('loan_liability_id')} options={r.loans.map(l => ({ value: l.id, label: l.name }))} />
        <Input label="Contract date" type="date" value={f.contract_date} onChange={set('contract_date')} /><Input label="Settlement date" type="date" value={f.settlement_date} onChange={set('settlement_date')} /><Input label="Purchase price" type="number" value={f.purchase_price} onChange={set('purchase_price')} />
        <Input label="Stamp duty" type="number" value={f.stamp_duty} onChange={set('stamp_duty')} /><Input label="Legal and conveyancing" type="number" value={f.legal_costs} onChange={set('legal_costs')} /><Input label="Other acquisition costs" type="number" value={f.other_acq_costs} onChange={set('other_acq_costs')} hint="Inspections, valuation, borrowing costs" />
        <Input label="Plant and equipment in the price" type="number" value={f.depreciating_assets_value} onChange={set('depreciating_assets_value')} hint="Not part of the CGT cost base" /><Input label="Construction cost (capital works)" type="number" value={f.construction_cost} onChange={set('construction_cost')} /><Input label="Construction date" type="date" value={f.construction_date} onChange={set('construction_date')} />
        <Select label="Capital works rate" value={f.capital_works_rate} onChange={set('capital_works_rate')} options={[{ value: '0.025', label: '2.5% (40 years)' }, { value: '0.04', label: '4% (25 years)' }]} /><Input label="First rented" type="date" value={f.first_income_date} onChange={set('first_income_date')} hint="Starts the 6-year absence rule" />
        <Input label="Lived in from" type="date" value={f.main_residence_from} onChange={set('main_residence_from')} /><Input label="Lived in until" type="date" value={f.main_residence_until} onChange={set('main_residence_until')} /><Input label="Value when first rented" type="number" value={f.value_when_first_income} onChange={set('value_when_first_income')} />
        <Input label="Sale contract date" type="date" value={f.sale_contract_date} onChange={set('sale_contract_date')} /><Input label="Sale price" type="number" value={f.sale_price} onChange={set('sale_price')} /><Input label="Selling costs" type="number" value={f.selling_costs} onChange={set('selling_costs')} /></Grid>
      <Input label="Notes" value={f.notes} onChange={set('notes')} />
      {problems.length > 0 && <div className="text-xs" style={{ color: 'var(--danger)' }}>{problems.join(' · ')}</div>}
      <div className="flex gap-1" style={{ justifyContent: 'flex-end', marginTop: 8 }}><button className="btn btn-outline" onClick={onClose}>Cancel</button><button className="btn btn-primary" disabled={problems.length > 0} onClick={go}>Save</button></div>
    </>)
}

function EntryForm({ pid, item, onClose, onSaved }) {
  const refs = useLoad(() => api.reference(), [])
  return <Modal title={item ? 'Edit entry' : 'New entry'} onClose={onClose} width={560}><Async q={refs}>{r => <EntryInner pid={pid} item={item} r={r} onClose={onClose} onSaved={onSaved} />}</Async></Modal>
}
function EntryInner({ pid, item, r, onClose, onSaved }) {
  const [f, set] = useForm({ kind: 'rent_income', entry_date: todayISO(), category: '', amount: '', description: '', reference: '', ...blank(item) })
  const problems = [!f.entry_date && 'Date is required', !(Number(f.amount) > 0) && 'Amount must be greater than zero', f.kind === 'expense' && !f.category && 'Choose a category for an expense'].filter(Boolean)
  return (
    <>
      <Grid cols={2}><Select label="Kind" value={f.kind} onChange={set('kind')} options={r.entry_kinds} /><Input label="Date" type="date" value={f.entry_date} onChange={set('entry_date')} />{f.kind === 'expense' && <Select label="Category" value={f.category} blank="Choose…" onChange={set('category')} options={r.expense_categories} />}
        <Input label="Amount (AUD)" type="number" step="any" value={f.amount} onChange={set('amount')} hint="Positive: the kind says which way it goes" /><Input label="Description" value={f.description} onChange={set('description')} /><Input label="Reference" value={f.reference} onChange={set('reference')} /></Grid>
      {problems.length > 0 && <div className="text-xs" style={{ color: 'var(--danger)' }}>{problems.join(' · ')}</div>}
      <div className="flex gap-1" style={{ justifyContent: 'flex-end', marginTop: 8 }}><button className="btn btn-outline" onClick={onClose}>Cancel</button>
        <button className="btn btn-primary" disabled={problems.length > 0} onClick={async () => { const b = { ...f }; delete b.id; if (await act(() => api.property.saveEntry(pid, b, item?.id), 'Saved')) onSaved() }}>Save</button></div>
    </>)
}

export function ValuationForm({ pid, ownerType = 'property', loanId, onClose, onSaved }) {
  const [f, set] = useForm({ as_at: todayISO(), value: '', basis: '', target: ownerType })
  const isLoan = f.target === 'liability'
  return (
    <Modal title={isLoan ? 'Loan balance' : 'Valuation'} onClose={onClose} width={480}>
      {ownerType === 'property' && loanId && <Select label="Record a" value={f.target} onChange={set('target')} options={[{ value: 'property', label: 'Property valuation' }, { value: 'liability', label: 'Balance of the linked loan' }]} />}
      <Grid cols={2}><Input label="As at" type="date" value={f.as_at} onChange={set('as_at')} /><Input label={isLoan ? 'Balance (AUD)' : 'Value (AUD)'} type="number" step="any" value={f.value} onChange={set('value')} /></Grid>
      <Input label="Basis" value={f.basis} onChange={set('basis')} hint="Agent appraisal, bank valuation, statement balance, own estimate" />
      <div className="flex gap-1" style={{ justifyContent: 'flex-end' }}><button className="btn btn-outline" onClick={onClose}>Cancel</button>
        <button className="btn btn-primary" disabled={!f.as_at || !(Number(f.value) >= 0 && f.value !== '')} onClick={async () => { if (await act(() => api.valuations.add({ owner_type: f.target, owner_id: isLoan ? loanId : pid, as_at: f.as_at, value: f.value, basis: f.basis }), 'Saved')) onSaved() }}>Save</button></div>
    </Modal>)
}
