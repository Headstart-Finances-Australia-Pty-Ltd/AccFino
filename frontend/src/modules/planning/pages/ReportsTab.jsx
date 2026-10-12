import React, { useState } from 'react'
import * as api from '../lib/planningApi.js'
import { fmtAUD, fmtDate, label, fyStartISO, todayISO, saveBlob } from '../lib/format.js'
import { useLoad, Async, Stat, Section, Provenance, Flags, Disclaimer, Money, StatusBadge, Table, Select, Input, Grid, act, Basis } from '../components/kit.jsx'

export const KINDS = [
  ['board_pack', 'Board pack'], ['kpis', 'KPIs'], ['profit_loss', 'Profit and loss'], ['balance_sheet', 'Balance sheet'], ['cash', 'Cash summary'], ['budget_vs_actual', 'Budget vs actual'],
  ['forecast_vs_actual', 'Forecast vs actual'], ['scenario_comparison', 'Scenario comparison'], ['working_capital', 'Working capital'], ['ageing', 'Receivables & payables ageing'],
]
const kpiVal = k => (k.unit === 'AUD' ? fmtAUD(k.value) : k.value == null ? 'n/a' : `${k.value}${k.unit === '%' ? '%' : k.unit === 'days' ? ' days' : k.unit === 'x' ? 'x' : ''}`)
const group = (title, rows) => (rows?.length ? [{ title, rows }] : [])

function Body({ r }) {
  const k = r.kind
  if (k === 'kpis') return (
    <Grid cols={3}>{r.kpis.map(x => <Stat key={x.label} label={x.label} basis="ACTUAL" value={kpiVal(x)} sub={`${x.previous != null ? `Prior: ${x.unit === 'AUD' ? fmtAUD(x.previous) : x.previous} · ` : ''}${x.calculation}`} />)}</Grid>)
  if (k === 'profit_loss') return (
    <>
      <Table caption="Profit and loss" rows={r.rows} rowKey="code" columns={[{ key: 'section', label: 'Section', render: x => label(x.section) }, { key: 'code', label: 'Account', render: x => `${x.code} ${x.name}` },
        { key: 'current', label: 'This period', money: true }, { key: 'previous', label: 'Comparison', money: true }, { key: 'change', label: 'Change', money: true }, { key: 'change_pct', label: '%', align: 'right', render: x => (x.change_pct == null ? 'n/a' : `${x.change_pct}%`) }]} />
      <Table caption="Totals" rows={Object.entries(r.totals).map(([n, v]) => ({ n: label(n), ...v }))} rowKey="n" columns={[{ key: 'n', label: 'Total' }, { key: 'current', label: 'This period', money: true }, { key: 'previous', label: 'Comparison', money: true }]} />
    </>)
  if (k === 'balance_sheet') {
    const c = r.current
    const sec = (t, obj) => Object.entries(obj).flatMap(([cls, rows]) => rows.map(x => ({ ...x, cls })))
    return (
      <>
        <Table caption="Assets" rows={sec('a', c.assets)} rowKey="account_id" columns={[{ key: 'code', label: 'Assets', render: x => `${x.code} ${x.name}` }, { key: 'cls', label: 'Class', render: x => label(x.cls) }, { key: 'amount', label: 'Amount', money: true }]} empty="No assets" />
        <Table caption="Liabilities" rows={sec('l', c.liabilities)} rowKey="account_id" columns={[{ key: 'code', label: 'Liabilities', render: x => `${x.code} ${x.name}` }, { key: 'cls', label: 'Class', render: x => label(x.cls) }, { key: 'amount', label: 'Amount', money: true }]} empty="No liabilities" />
        <Table caption="Equity" rows={c.equity} rowKey="account_id" columns={[{ key: 'code', label: 'Equity', render: x => `${x.code} ${x.name}` }, { key: 'amount', label: 'Amount', money: true }]} empty="No equity accounts" />
        <Grid cols={3}><Stat label="Total assets" basis="ACTUAL" value={fmtAUD(r.totals.assets)} /><Stat label="Total liabilities" basis="ACTUAL" value={fmtAUD(r.totals.liabilities)} /><Stat label="Net assets" basis="ACTUAL" value={fmtAUD(r.totals.net_assets)} sub={r.totals.balanced ? 'Balanced' : 'NOT balanced: review'} tone={r.totals.balanced ? undefined : 'danger'} /></Grid>
      </>)
  }
  if (k === 'cash') return (
    <>
      <Grid cols={3}><Stat label="Opening cash" basis="ACTUAL" value={fmtAUD(r.summary.opening_cash)} /><Stat label="Receipts" basis="ACTUAL" value={fmtAUD(r.summary.total_receipts)} /><Stat label="Payments" basis="ACTUAL" value={fmtAUD(r.summary.total_payments)} />
        <Stat label="Closing cash" basis="ACTUAL" value={fmtAUD(r.summary.closing_cash)} sub={r.summary.reconciled ? 'Agrees to the ledger' : `Difference ${fmtAUD(r.summary.difference)}`} tone={r.summary.reconciled ? undefined : 'danger'} /></Grid>
      <Table caption="Cash by month" rows={r.months} rowKey="month" empty="No bank movements in this period" columns={[{ key: 'month', label: 'Month' }, { key: 'receipts', label: 'Receipts', money: true }, { key: 'payments', label: 'Payments', money: true }, { key: 'net', label: 'Net', money: true }, { key: 'closing', label: 'Closing', money: true }]} />
      <Table caption="Cash by section" rows={r.sections} rowKey="section" columns={[{ key: 'section', label: 'Section' }, { key: 'receipts', label: 'Receipts', money: true }, { key: 'payments', label: 'Payments', money: true }, { key: 'net', label: 'Net', money: true }]} />
    </>)
  if (k === 'budget_vs_actual') return !r.totals ? null : (
    <>
      <Grid cols={3}>{['revenue', 'expenses', 'profit'].map(x => <Stat key={x} label={label(x)} basis="BUDGET" value={fmtAUD(r.totals[x].actual)} sub={`Budget ${fmtAUD(r.totals[x].budget)} · variance ${fmtAUD(r.totals[x].variance)}`} />)}</Grid>
      <Table caption="Budget vs actual" rows={r.rows} rowKey="account_id" columns={[{ key: 'code', label: 'Account', render: x => `${x.code} ${x.name}` }, { key: 'budget', label: 'Budget', money: true }, { key: 'actual', label: 'Actual', money: true }, { key: 'variance', label: 'Variance', money: true }, { key: 'variance_pct', label: '%', align: 'right', render: x => (x.variance_pct == null ? 'n/a' : `${x.variance_pct}%`) }]} />
      <Disclaimer>{r.convention}</Disclaimer>
    </>)
  if (k === 'forecast_vs_actual') return (
    <>
      {r.compared > 0 && <Disclaimer>Periods compared {r.compared} · MAE (net) {fmtAUD(r.mae_net)} · bias {fmtAUD(r.bias_net)}. {r.note}</Disclaimer>}
      <Table caption="Forecast vs actual" rows={r.rows} rowKey="index" empty="Nothing to compare yet" columns={[{ key: 'label', label: 'Period' }, { key: 'forecast_net', label: 'Forecast net', money: true }, { key: 'actual_net', label: 'Actual net', money: true }, { key: 'error_net', label: 'Error', money: true }]} />
    </>)
  if (k === 'scenario_comparison') return (
    <>
      <Table caption="Scenario comparison" rows={r.rows} rowKey="name" empty="Create at least two scenarios" columns={[{ key: 'name', label: 'Scenario' }, { key: 'revenue', label: 'Revenue', money: true }, { key: 'profit', label: 'Profit', money: true }, { key: 'closing_cash', label: 'Closing cash', money: true }, { key: 'd_profit', label: 'Δ profit', money: true }]} />
      {r.limitations && <Disclaimer>{r.limitations.join(' ')}</Disclaimer>}
    </>)
  if (k === 'working_capital') return (
    <>
      <Grid cols={3}>{[['net_working_capital', 'Net working capital', 'AUD'], ['current_ratio', 'Current ratio', 'x'], ['quick_ratio', 'Quick ratio', 'x'], ['cash', 'Cash', 'AUD'], ['receivables', 'Receivables', 'AUD'], ['payables', 'Payables', 'AUD'], ['dso_days', 'DSO', 'days'], ['dpo_days', 'DPO', 'days']]
        .map(([m, l, u]) => <Stat key={m} label={l} basis="ACTUAL" value={r.metrics[m] == null ? 'n/a' : u === 'AUD' ? fmtAUD(r.metrics[m]) : `${r.metrics[m]} ${u}`} />)}</Grid>
      <Disclaimer>{Object.entries(r.definitions).map(([n, d]) => `${label(n)}: ${d}.`).join(' ')}</Disclaimer>
    </>)
  if (k === 'ageing') return ['receivables', 'payables'].map(side => {
    const s = r[side]
    const cols = Object.keys(s.buckets || {})
    return (
      <Section key={side} title={side === 'receivables' ? 'Receivables (customers owe you)' : 'Payables (you owe suppliers)'} hint={s.control ? `${s.control.reconciled ? 'Agrees to the ledger control account' : `DOES NOT agree to the ledger: difference ${fmtAUD(s.control.difference)}`}` : undefined}>
        <Table caption={side} rows={s.contacts} rowKey="contact" empty="Nothing outstanding" columns={[{ key: 'contact', label: 'Contact' }, ...cols.map(c => ({ key: c, label: label(c), money: true, render: x => <Money v={x.buckets?.[c]} /> })), { key: 'total', label: 'Total', money: true }]} />
        <Disclaimer>Total {fmtAUD(s.total)}</Disclaimer>
      </Section>)
  })
  return null
}

function Rendered({ r }) {
  return (
    <div id="plan-report">
      <h3 style={{ margin: '0 0 4px' }}>{r.title}</h3>
      <Provenance d={r} />
      <Disclaimer>{r.disclaimer}</Disclaimer>
      <Flags items={r.flags} />
      {r.kind === 'board_pack'
        ? (
          <>
            {r.sections.map(sx => <Section key={sx.kind} title={sx.title}><Body r={sx} />{sx.commentary?.length > 0 && <ul style={{ margin: '8px 0 0', paddingLeft: 18 }}>{sx.commentary.map((c, i) => <li key={i} className="text-sm">{c}</li>)}</ul>}</Section>)}
            {r.forecast && <Section title="Cash outlook" hint="FORECAST: a projection, not a record"><div className="text-sm">Lowest forecast balance {fmtAUD(r.forecast.minimum.balance)} ({r.forecast.minimum.label}); closing {fmtAUD(r.forecast.closing)}; confidence {r.forecast.confidence.level}. {r.forecast.shortfall.goes_negative ? 'Cash is forecast to go negative.' : 'No shortfall forecast.'}</div></Section>}
          </>)
        : <><Body r={r} />{r.commentary?.length > 0 && <Section title="Commentary" hint="Generated from the figures above; contains no inference"><ul style={{ margin: 0, paddingLeft: 18 }}>{r.commentary.map((c, i) => <li key={i} className="text-sm">{c}</li>)}</ul></Section>}</>}
      <Disclaimer>Report fingerprint {String(r.input_hash).slice(0, 12)} — the same data and settings always give the same report.</Disclaimer>
    </div>)
}

export default function ReportsTab() {
  const [kind, setKind] = useState('board_pack')
  const [p, setP] = useState({ from: fyStartISO(), to: todayISO(), cfrom: '', cto: '' })
  const [run, setRun] = useState(0)
  const [note, setNote] = useState('')
  const [snapView, setSnapView] = useState(null)
  const params = { from: p.from, to: p.to, ...(p.cfrom && p.cto ? { compare_from: p.cfrom, compare_to: p.cto } : {}) }
  const q = useLoad(() => api.reports.get(kind, params), [kind, p.from, p.to, p.cfrom, p.cto, run])
  const snaps = useLoad(() => api.reports.snapshots(''), [])
  const me = useLoad(() => api.me(), [])
  const canEdit = (me.data?.capabilities || []).includes('edit')
  const exp = async fmt => { const d = await act(() => api.reports.exportFile(kind, { ...params, format: fmt })); if (d) saveBlob(`${kind}_${p.from}_${p.to}.${fmt}`, d) }
  const snap = async () => { const r = await act(() => api.reports.snapshot(kind, { from: p.from, to: p.to, compare_from: p.cfrom || undefined, compare_to: p.cto || undefined, note }), 'Snapshot saved'); if (r) { setNote(''); snaps.reload() } }
  const view = async id => { const r = await act(() => api.reports.snapshotGet(id)); if (r) setSnapView(r) }
  return (
    <div style={{ padding: 16 }}>
      <Section title="Management reports" hint="Management information prepared from the ledger. Not statutory or audited financial statements.">
        <div className="flex items-center gap-1" style={{ flexWrap: 'wrap' }}>
          <Select label="Report" value={kind} onChange={e => setKind(e.target.value)} options={KINDS.map(([v, l]) => ({ value: v, label: l }))} />
          <Input label="From" type="date" value={p.from} onChange={e => setP({ ...p, from: e.target.value })} />
          <Input label="To" type="date" value={p.to} max={todayISO()} onChange={e => setP({ ...p, to: e.target.value })} />
          <Input label="Compare from" type="date" value={p.cfrom} onChange={e => setP({ ...p, cfrom: e.target.value })} hint="Optional" />
          <Input label="Compare to" type="date" value={p.cto} onChange={e => setP({ ...p, cto: e.target.value })} />
        </div>
        <div className="flex gap-1" style={{ flexWrap: 'wrap', marginTop: 8 }}>
          <button className="btn btn-outline btn-sm" onClick={() => setRun(x => x + 1)}>Refresh</button>
          <button className="btn btn-outline btn-sm" onClick={() => exp('csv')}>Export CSV</button><button className="btn btn-outline btn-sm" onClick={() => exp('xlsx')}>Export Excel</button>
          <button className="btn btn-outline btn-sm" onClick={() => window.print()}>Print / Save as PDF</button>
          {canEdit && <><Input label="Snapshot note" value={note} onChange={e => setNote(e.target.value)} placeholder="e.g. Board pack, September" /><button className="btn btn-primary btn-sm" onClick={snap}>Save snapshot</button></>}
        </div>
      </Section>
      <Async q={q}>{r => <Rendered r={r} />}</Async>
      <Section title="Saved snapshots" hint="Frozen copies for board packs; they never change when the ledger does">
        <Async q={snaps}>{rows => <Table caption="Report snapshots" rows={rows} empty="No snapshots saved" columns={[{ key: 'created_at', label: 'Saved', date: true }, { key: 'title', label: 'Report' }, { key: 'period_from', label: 'From', date: true }, { key: 'period_to', label: 'To', date: true },
          { key: 'note', label: 'Note' }, { key: 'v', label: '', render: x => <button className="btn btn-outline btn-sm" onClick={() => view(x.id)}>View</button> }]} />}</Async>
        {snapView && <div style={{ marginTop: 12 }}><div className="flex justify-between items-center"><b>Snapshot #{snapView.id}</b><button className="btn btn-outline btn-sm" onClick={() => setSnapView(null)}>Close</button></div><Rendered r={snapView.payload || snapView} /></div>}
      </Section>
    </div>)
}
