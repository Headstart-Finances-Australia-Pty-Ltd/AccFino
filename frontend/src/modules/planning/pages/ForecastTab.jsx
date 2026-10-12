import React, { useState } from 'react'
import * as api from '../lib/planningApi.js'
import { fmtAUD, fmtDate, label } from '../lib/format.js'
import { useLoad, Async, Stat, Section, Provenance, Flags, Disclaimer, Money, StatusBadge, Table, Select, Input, Grid, act, Basis } from '../components/kit.jsx'

const SOURCE = { expected_sales: 'Expected customer receipts', expected_bills: 'Bills to pay', recurring: 'Recurring payments', recurring_invoices: 'Recurring invoices', lending: 'Loans and facilities', tax: 'Tax obligations', other: 'Other' }

export default function ForecastTab({ Legacy }) {
  const [view, setView] = useState('forecast')
  const [granularity, setGranularity] = useState('week')
  const [periods, setPeriods] = useState('')
  const q = useLoad(() => api.forecast.get({ granularity, periods: periods || undefined }), [granularity, periods])
  const snaps = useLoad(() => api.forecast.snapshots(), [])
  const [open, setOpen] = useState(null)
  const [label_, setLabel] = useState('')

  const save = async () => { if (await act(() => api.forecast.save({ granularity, periods: periods ? Number(periods) : undefined, label: label_ }), 'Forecast snapshot saved')) { setLabel(''); snaps.reload() } }
  const showVs = async id => { const r = await act(() => api.forecast.vsActual(id)); if (r) setOpen(r) }

  return (
    <div style={{ padding: 16 }}>
      <div className="tabs-bar" style={{ marginBottom: 12 }} role="tablist">
        <button role="tab" aria-selected={view === 'forecast'} className={`tab-btn${view === 'forecast' ? ' active' : ''}`} onClick={() => setView('forecast')}>Driver-based forecast</button>
        <button role="tab" aria-selected={view === 'snapshots'} className={`tab-btn${view === 'snapshots' ? ' active' : ''}`} onClick={() => setView('snapshots')}>Snapshots &amp; accuracy</button>
        {Legacy && <button role="tab" aria-selected={view === 'model'} className={`tab-btn${view === 'model' ? ' active' : ''}`} onClick={() => setView('model')}>Statistical model lab</button>}
      </div>
      {view === 'model' && Legacy && <Legacy />}
      {view === 'forecast' && (
        <>
          <div className="flex items-center gap-1" style={{ flexWrap: 'wrap', marginBottom: 8 }}>
            <Select label="View" value={granularity} onChange={e => setGranularity(e.target.value)} options={[{ value: 'week', label: '13-week (weekly)' }, { value: 'month', label: 'Monthly' }]} />
            <Input label="Periods" type="number" min="1" max="26" value={periods} onChange={e => setPeriods(e.target.value)} placeholder="default" />
            <button className="btn btn-outline btn-sm" onClick={q.reload}>Refresh</button>
          </div>
          <Async q={q}>{f => (
            <>
              <Provenance d={f} />
              <div role="note" className="alert alert-info" style={{ marginBottom: 10 }}><Basis basis="FORECAST" /> {f.label_note}. Confidence: <StatusBadge status={f.confidence.level === 'indicative' ? 'indicative' : f.confidence.level} text={f.confidence.level} /> — {f.confidence.reasons.join('; ')}.</div>
              <Flags items={[...(f.warnings || []), ...(f.stale ? ['Bank data is stale; the opening balance may be out of date.'] : []), ...(!f.opening.reconciled ? ['The opening balance is not reconciled to the bank feed.'] : [])]} />
              <Grid cols={3}>
                <Stat label="Opening cash" basis="ACTUAL" value={fmtAUD(f.opening.balance)} sub={`as at ${fmtDate(f.as_at)}`} />
                <Stat label="Total receipts" basis="FORECAST" value={fmtAUD(f.total_receipts)} />
                <Stat label="Total payments" basis="FORECAST" value={fmtAUD(f.total_payments)} />
                <Stat label="Closing cash" basis="FORECAST" value={fmtAUD(f.closing)} />
                <Stat label="Lowest balance" basis="FORECAST" tone={f.shortfall.goes_negative ? 'danger' : undefined} value={fmtAUD(f.minimum.balance)} sub={`${f.minimum.label} (to ${fmtDate(f.minimum.date_to)})`} />
                <Stat label={`Shortfall vs ${fmtAUD(f.threshold)} threshold`} basis="FORECAST" tone={Number(f.shortfall.max_shortfall) > 0 ? 'danger' : 'success'} value={fmtAUD(f.shortfall.max_shortfall)} sub={f.shortfall.first_breach ? `First breach: ${f.shortfall.first_breach.label || f.shortfall.first_breach}` : 'No breach in the horizon'} />
              </Grid>
              <Section title={granularity === 'week' ? '13-week cash forecast' : 'Monthly cash forecast'}>
                <Table caption="Cash forecast" columns={[
                  { key: 'label', label: 'Period' }, { key: 'date_from', label: 'From', date: true }, { key: 'date_to', label: 'To', date: true },
                  { key: 'opening', label: 'Opening', money: true }, { key: 'receipts', label: 'Receipts', money: true }, { key: 'payments', label: 'Payments', money: true },
                  { key: 'net', label: 'Net', money: true }, { key: 'closing', label: 'Closing', money: true },
                  { key: 'below_minimum', label: 'Below threshold', render: r => (r.below_minimum ? <StatusBadge status="high" text="Below" /> : '—') },
                ]} rows={f.rows} rowKey="index" />
              </Section>
              <Section title="Drivers" hint="What the forecast is made of">
                <Table caption="Forecast drivers" columns={[{ key: 'source', label: 'Driver', render: r => SOURCE[r.source] || label(r.source) }, { key: 'count', label: 'Items', align: 'right' },
                  { key: 'inflow', label: 'Inflow', money: true }, { key: 'outflow', label: 'Outflow', money: true }, { key: 'net', label: 'Net', money: true }]} rows={f.drivers} rowKey="source" empty="No drivers" />
                <Disclaimer>Committed share of forecast value (open invoices, bills, loans, tax): {Math.round(Number(f.committed_share) * 100)}%. The rest is expected from recurring patterns.</Disclaimer>
              </Section>
              <Section title="Assumptions"><ul style={{ margin: 0, paddingLeft: 18 }}>{f.assumptions.map((a, i) => <li key={i} className="text-sm">{a}</li>)}</ul></Section>
              <Section title="Statistical baseline &amp; backtest" hint={f.baseline.note}>
                <div className="text-sm" style={{ marginBottom: 8 }}>Selected model: <b>{f.baseline.label}</b>. {f.backtest.method} ({f.backtest.origins} origins over {f.backtest.weeks_of_series} weeks).</div>
                <Table caption="Backtest" columns={[{ key: 'label', label: 'Model' }, { key: 'mae', label: 'Mean abs. error', money: true }, { key: 'n', label: 'Weeks scored', align: 'right' }, { key: 'best', label: '', render: r => (r.model === f.backtest.best ? <StatusBadge status="active" text="Selected" /> : '') }]} rows={f.backtest.models} rowKey="model" empty="Not enough history to backtest" hint="At least 8 weeks of history is needed." />
              </Section>
              <Section title="Sources"><ul style={{ margin: 0, paddingLeft: 18 }}>{f.sources.map((s, i) => <li key={i} className="text-sm">{s.name} — {s.detail}</li>)}</ul>
                <Disclaimer>Input fingerprint {String(f.input_hash).slice(0, 12)} — identical inputs always give an identical forecast. {f.duplicates_ignored ? `${f.duplicates_ignored} duplicate item(s) ignored. ` : ''}{f.outside_horizon ? `${f.outside_horizon} item(s) fall beyond the horizon.` : ''}</Disclaimer></Section>
              <Section title="Save a snapshot" hint="Stores this forecast so its accuracy can be measured against what actually happens">
                <div className="flex items-center gap-1" style={{ flexWrap: 'wrap' }}><Input label="Label" value={label_} onChange={e => setLabel(e.target.value)} placeholder="e.g. Board forecast" /><button className="btn btn-primary btn-sm" onClick={save}>Save snapshot</button></div>
              </Section>
            </>)}</Async>
        </>)}
      {view === 'snapshots' && (
        <Async q={snaps}>{rows => (
          <>
            <Section title="Saved forecast snapshots" hint="Compare a past forecast with the bank movements that actually followed">
              <Table caption="Snapshots" rows={rows} empty="No snapshots yet" hint="Save one from the forecast view." columns={[
                { key: 'created_at', label: 'Saved', date: true }, { key: 'label', label: 'Label' }, { key: 'as_at', label: 'As at', date: true }, { key: 'granularity', label: 'View', render: r => label(r.granularity) },
                { key: 'closing', label: 'Forecast closing', money: true, render: r => <Money v={r.summary?.closing} /> }, { key: 'confidence', label: 'Confidence', render: r => r.summary?.confidence },
                { key: 'act', label: '', render: r => <button className="btn btn-outline btn-sm" onClick={() => showVs(r.id)}>Forecast vs actual</button> }]} />
            </Section>
            {open && (
              <Section title="Forecast vs actual" hint={open.note}>
                <Disclaimer>Periods compared: {open.compared}. Mean absolute error (net): {fmtAUD(open.mae_net)} · bias: {fmtAUD(open.bias_net)} · closing error: {fmtAUD(open.mae_closing)}</Disclaimer>
                <Table caption="Forecast vs actual" rows={open.rows} empty="No period has elapsed yet" hint="Accuracy can only be measured for periods that have finished." columns={[
                  { key: 'label', label: 'Period' }, { key: 'forecast_net', label: 'Forecast net', money: true }, { key: 'actual_net', label: 'Actual net', money: true }, { key: 'error_net', label: 'Error (actual − forecast)', money: true }, { key: 'forecast_closing', label: 'Forecast closing', money: true }, { key: 'actual_closing', label: 'Actual closing', money: true }]} rowKey="index" />
              </Section>)}
          </>)}</Async>)}
    </div>)
}
