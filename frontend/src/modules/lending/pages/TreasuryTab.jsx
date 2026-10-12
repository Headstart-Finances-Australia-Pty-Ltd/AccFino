import React, { useState } from 'react'
import { BulkLoadButton } from '../../../core/components/ui/BulkLoadButton.jsx'
import { CartesianGrid, Legend, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts'
import * as L from '../lib/lendApi.js'
import { act, Async, Check, DataGrid, Disclaimer, Grid, Input, Modal, Money, Section, Select, Stat, StatusBadge, useForm, useLoad } from '../components/kit.jsx'
import { fmtAUD, fmtDate, fmtPct, label, todayISO } from '../lib/format.js'

const SOURCE = { facility: 'Facility repayment', loan: 'Own loan', bill: 'Unpaid bill', invoice: 'Invoice due', forecast: 'Forecast' }
const WSTATUS = { healthy: 'Healthy', watch: 'Watch: short only if the forecast outflows happen', short: 'Short on committed flows alone' }

// Actual | Committed | Forecast: never blended. Actual is cash today; committed is contractual; forecast is an expectation somebody entered.
export default function TreasuryTab({ me }) {
  const caps = me.capabilities
  const [horizon, setHorizon] = useState('90')
  const [bump, setBump] = useState(0)
  const [fac, setFac] = useState(null)
  const [item, setItem] = useState(null)
  const pos = useLoad(() => L.treasury.position(Number(horizon)), [horizon, bump])
  const items = useLoad(() => L.treasury.items({ status: 'expected' }), [bump])
  const again = () => setBump(n => n + 1)
  return (
    <div style={{ padding: 16 }}>
      <div style={{ display: 'flex', justifyContent: 'flex-end', marginBottom: 8 }}><BulkLoadButton base="/lending/bulk" areas={["Treasury"]} onDone={() => window.location.reload()} /></div>
      <Disclaimer />
      <Async q={pos}>{p => (
        <>
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit,minmax(170px,1fr))', gap: 12, marginBottom: 12 }}>
            <Stat label="Cash today (actual)" value={<Money v={p.cash.total} strong />} sub={`${p.cash.accounts.length} bank account(s)`} /><Stat label="Funding limits" value={<Money v={p.facilities.limit} />} sub={`${fmtAUD(p.facilities.drawn)} drawn`} />
            <Stat label="Available to draw" value={<Money v={p.facilities.available} strong />} /><Stat label="Minimum cash buffer" value={<Money v={p.min_cash_buffer} />} sub="set under Credit > Policy settings" /></div>
          <div className="text-sm text-muted" style={{ marginBottom: 10 }}>{p.explain}</div>
          <Section title="Liquidity: 30, 60 and 90 days" actions={<div style={{ width: 160 }}><Select label="Look ahead" value={horizon} onChange={e => setHorizon(e.target.value)} options={[{ value: '30', label: '30 days' }, { value: '60', label: '60 days' }, { value: '90', label: '90 days' }, { value: '180', label: '180 days' }]} /></div>}>
            <table className="data-table" aria-label="Liquidity windows"><thead><tr><th>Next</th><th className="text-right">Cash today (actual)</th><th className="text-right">Committed in / out</th><th className="text-right">Forecast in / out</th><th className="text-right">Balance on committed alone</th><th className="text-right">Balance with forecast</th><th>Position</th></tr></thead>
              <tbody>{p.windows.map(w => (
                <tr key={w.days}><td><strong>{w.days} days</strong></td><td className="text-right"><Money v={w.actual.cash} /></td><td className="text-right text-sm">{fmtAUD(w.committed.inflow)} / {fmtAUD(w.committed.outflow)}</td><td className="text-right text-sm">{fmtAUD(w.forecast.inflow)} / {fmtAUD(w.forecast.outflow)}</td>
                  <td className="text-right"><Money v={w.closing_committed} strong /></td><td className="text-right"><Money v={w.closing_forecast} /></td>
                  <td><StatusBadge status={w.status} text={WSTATUS[w.status]} />{w.shortfall_committed.funding_required > 0 && <div className="text-xs">Funding needed {fmtAUD(w.shortfall_committed.funding_required)}: facilities cover {fmtAUD(w.shortfall_committed.covered_by_facilities)}{w.shortfall_committed.uncovered > 0 ? `, ${fmtAUD(w.shortfall_committed.uncovered)} uncovered` : ''}</div>}
                    {w.status === 'watch' && w.shortfall_forecast.funding_required > 0 && <div className="text-xs">If the forecast happens: lowest {fmtAUD(w.lowest_forecast.balance)} on {fmtDate(w.lowest_forecast.date)}; funding needed {fmtAUD(w.shortfall_forecast.funding_required)}</div>}</td></tr>))}</tbody></table>
          </Section>
          <Section title="Balance over time" hint="Committed alone (what is certain) against committed plus forecast.">
            <div role="img" aria-label="Projected balance: committed flows alone, and with the forecast"><ResponsiveContainer width="100%" height={240}><LineChart data={p.projection.days.map(d => ({ date: String(d.date).slice(5, 10), committed: Number(d.committed_balance), forecast: Number(d.forecast_balance) }))}>
              <CartesianGrid strokeDasharray="3 3" /><XAxis dataKey="date" fontSize={11} /><YAxis fontSize={11} /><Tooltip /><Legend /><Line type="stepAfter" dataKey="committed" name="Committed only" dot={false} stroke="var(--primary, #2563eb)" strokeWidth={2} /><Line type="stepAfter" dataKey="forecast" name="Committed + forecast" dot={false} stroke="var(--warning, #d97706)" strokeDasharray="5 3" /></LineChart></ResponsiveContainer></div>
            <details style={{ marginTop: 6 }}><summary className="text-xs text-muted" style={{ cursor: 'pointer' }}>Show the weekly figures</summary><table className="data-table" style={{ fontSize: 12 }} aria-label="Weekly flows"><thead><tr><th>Week from</th><th className="text-right">Committed net</th><th className="text-right">Forecast net</th></tr></thead>
              <tbody>{(p.projection.weekly || []).map(w => <tr key={w.week}><td>{fmtDate(w.from_date)}</td><td className="text-right mono">{fmtAUD(w.committed_net)}</td><td className="text-right mono">{fmtAUD(w.forecast_net)}</td></tr>)}{(p.projection.weekly || []).length === 0 && <tr><td colSpan={3} className="text-muted">No movements in this period.</td></tr>}</tbody></table></details>
          </Section>
          <Section title="Expected money in and out" hint="Committed flows come from the books and the loan register; forecast flows are the items you enter.">
            <DataGrid rows={p.flows.map((f, i) => ({ ...f, id: i }))} empty="Nothing expected in this period" pageSize={12} columns={[{ key: 'date', label: 'Date', date: true }, { key: 'label', label: 'What' }, { key: 'source', label: 'From', render: r => SOURCE[r.source] || label(r.source) }, { key: 'kind', label: 'Kind', render: r => <StatusBadge status={r.kind === 'committed' ? 'current' : 'expected'} text={label(r.kind)} /> }, { key: 'amount', label: 'Amount', money: true }]} />
            {p.overdue_receivables.length > 0 && <div style={{ marginTop: 8 }}><div className="text-sm" style={{ fontWeight: 600 }}>Overdue invoices (not counted: money owed to you that has not arrived is not something to plan on)</div>{p.overdue_receivables.map(o => <div key={o.number} className="text-sm">{o.number} · {o.contact}: {fmtAUD(o.amount)}, {o.days_overdue} days overdue</div>)}</div>}
          </Section>
        </>)}</Async>
      <Section title="Funding facilities" actions={caps.includes('configure') && <button className="btn btn-primary btn-sm" onClick={() => setFac({})}>+ Facility</button>} hint="Overdrafts, lines of credit, finance. Drawn is read from the ledger if you link the account.">
        <Async q={useLoad(() => L.treasury.facilities(), [bump])}>{f => <DataGrid rows={f.rows} empty="No facilities recorded" columns={[{ key: 'name', label: 'Facility' }, { key: 'lender', label: 'Lender' }, { key: 'limit', label: 'Limit', money: true }, { key: 'drawn', label: 'Drawn', money: true }, { key: 'available', label: 'Available', money: true },
          { key: 'utilisation_pct', label: 'Used', render: r => (r.over_limit ? <span className="badge badge-danger">over limit</span> : `${r.utilisation_pct}%`), align: 'right' }, { key: 'interest_rate', label: 'Rate', render: r => (r.interest_rate ? fmtPct(r.interest_rate) : '—'), align: 'right' },
          { key: 'expiry_date', label: 'Expires', render: r => (r.expiry_date ? <span>{fmtDate(r.expiry_date)}{r.expiry_warning && <span className="badge badge-warning" style={{ marginLeft: 4 }}>{r.days_to_expiry < 0 ? 'expired' : `${r.days_to_expiry} days`}</span>}</span> : '—') },
          { key: 'status', label: 'Status', render: r => <StatusBadge status={r.status === 'active' ? 'current' : 'closed'} text={label(r.status)} /> }, { key: 'x', label: '', render: r => caps.includes('configure') && <button className="btn btn-ghost btn-xs" onClick={() => setFac(r)}>Edit</button> }]} />}</Async>
      </Section>
      <Section title="Forecast items" actions={caps.includes('edit') && <button className="btn btn-primary btn-sm" onClick={() => setItem({})}>+ Expected money in or out</button>} hint="What you expect but nobody is bound to. These never count as committed.">
        <Async q={items}>{rows => <DataGrid rows={rows} empty="Nothing entered" columns={[{ key: 'item_date', label: 'Date', date: true }, { key: 'description', label: 'What' }, { key: 'category', label: 'Category' }, { key: 'amount', label: 'Amount', money: true }, { key: 'x', label: '', render: r => caps.includes('edit') && <span className="flex gap-1"><button className="btn btn-ghost btn-xs" onClick={() => setItem(r)}>Edit</button>
          <button className="btn btn-ghost btn-xs" onClick={async () => { if (await act(() => L.treasury.saveItem({ item_date: r.item_date, amount: r.amount, description: r.description, category: r.category, status: 'received' }, r.id), 'Marked received')) again() }}>Received</button></span> }]} />}</Async>
      </Section>
      {fac && <FacilityForm item={fac.id ? fac : null} onClose={() => setFac(null)} onSaved={() => { setFac(null); again() }} />}
      {item && <ItemForm item={item.id ? item : null} onClose={() => setItem(null)} onSaved={() => { setItem(null); again() }} />}
    </div>)
}

const blank = o => Object.fromEntries(Object.entries(o || {}).map(([k, v]) => [k, v ?? '']))

function FacilityForm({ item, onClose, onSaved }) {
  const ref = useLoad(() => L.reference(), [])
  const accts = useLoad(() => L.ledgerAccounts(), [])
  const [f, set] = useForm({ name: '', lender: '', facility_type: 'line_of_credit', rate_pct: item?.interest_rate ? (Number(item.interest_rate) * 100).toFixed(2) : '', expiry_date: '', ledger_account_id: '', repayment_amount: '', repayment_frequency: '', next_repayment_date: '', status: 'active', ...blank(item), limit_amount: item?.limit ?? '', drawn_amount: item?.drawn_from_ledger ? '' : (item?.drawn ?? '0') })
  const bad = [!f.name.trim() && 'Give the facility a name', !(Number(f.limit_amount) > 0) && 'Enter the limit', f.repayment_amount && (!f.repayment_frequency || !f.next_repayment_date) && 'A repayment needs its frequency and next date'].filter(Boolean)
  return (
    <Modal title={item ? 'Edit facility' : 'New facility'} onClose={onClose} width={720}><Async q={ref}>{r => (
      <><Grid cols={3}><Input label="Name" value={f.name} onChange={set('name')} /><Input label="Lender" value={f.lender} onChange={set('lender')} /><Select label="Type" value={f.facility_type} onChange={set('facility_type')} options={r.facility_types} />
        <Input label="Limit (AUD)" type="number" value={f.limit_amount} onChange={set('limit_amount')} /><Input label="Drawn (AUD)" type="number" value={f.drawn_amount} onChange={set('drawn_amount')} hint="Ignored if linked to a ledger account" /><Input label="Rate (% a year)" type="number" step="any" value={f.rate_pct} onChange={set('rate_pct')} />
        <Input label="Expires" type="date" value={f.expiry_date} onChange={set('expiry_date')} /><Async q={accts}>{as => <Select label="Read drawn from ledger account" value={f.ledger_account_id} blank="Not linked" onChange={set('ledger_account_id')} options={as.filter(a => /liab/i.test(a.type)).map(a => ({ value: a.id, label: `${a.code} ${a.name}` }))} />}</Async><Select label="Status" value={f.status} onChange={set('status')} options={['active', 'closed']} /></Grid>
        <details><summary className="text-sm" style={{ cursor: 'pointer', marginBottom: 8 }}>More options: scheduled repayments</summary><Grid cols={3}><Input label="Repayment (AUD)" type="number" value={f.repayment_amount} onChange={set('repayment_amount')} /><Select label="How often" value={f.repayment_frequency} blank="—" onChange={set('repayment_frequency')} options={r.frequencies} /><Input label="Next repayment" type="date" value={f.next_repayment_date} onChange={set('next_repayment_date')} /></Grid></details>
        {bad.length > 0 && <div className="text-xs" style={{ color: 'var(--danger)' }}>{bad.join(' · ')}</div>}
        <div className="flex gap-1" style={{ justifyContent: 'flex-end' }}><button className="btn btn-outline" onClick={onClose}>Cancel</button><button className="btn btn-primary" disabled={bad.length > 0} onClick={async () => {
          const b = { ...f, interest_rate: f.rate_pct === '' ? null : Number(f.rate_pct) / 100 }; for (const k of ['rate_pct', 'id', 'limit', 'drawn', 'available', 'over_limit', 'utilisation_pct', 'drawn_from_ledger', 'days_to_expiry', 'expiry_warning']) delete b[k]; for (const k of Object.keys(b)) if (b[k] === '') b[k] = null
          if (await act(() => L.treasury.saveFacility(b, item?.id), 'Saved')) onSaved() }}>Save</button></div></>)}</Async></Modal>)
}

function ItemForm({ item, onClose, onSaved }) {
  const [f, set] = useForm({ item_date: todayISO(), direction: 'in', amount: '', description: '', category: '', ...(item ? { item_date: item.item_date, direction: Number(item.amount) < 0 ? 'out' : 'in', amount: Math.abs(Number(item.amount)), description: item.description, category: item.category || '' } : {}) })
  return (
    <Modal title={item ? 'Edit expected money' : 'Expected money in or out'} onClose={onClose} width={500}>
      <Grid cols={2}><Input label="Expected date" type="date" value={f.item_date} onChange={set('item_date')} /><Select label="Direction" value={f.direction} onChange={set('direction')} options={[{ value: 'in', label: 'Money in' }, { value: 'out', label: 'Money out' }]} /><Input label="Amount (AUD)" type="number" step="any" value={f.amount} onChange={set('amount')} /><Input label="Category" value={f.category} onChange={set('category')} /></Grid>
      <Input label="What is it" value={f.description} onChange={set('description')} />
      <div className="flex gap-1" style={{ justifyContent: 'flex-end' }}><button className="btn btn-outline" onClick={onClose}>Cancel</button><button className="btn btn-primary" disabled={!f.description.trim() || !(Number(f.amount) > 0) || !f.item_date} onClick={async () => { const b = { item_date: f.item_date, description: f.description, category: f.category || null, amount: f.direction === 'out' ? -Math.abs(Number(f.amount)) : Math.abs(Number(f.amount)) }; if (await act(() => L.treasury.saveItem(b, item?.id), 'Saved')) onSaved() }}>Save</button></div>
    </Modal>)
}
