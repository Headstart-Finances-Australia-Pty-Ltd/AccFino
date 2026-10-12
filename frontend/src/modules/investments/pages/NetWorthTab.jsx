import React, { useState } from 'react'
import * as api from '../lib/invApi.js'
import { act, Async, DataGrid, Disclaimer, Grid, Input, Modal, Money, Notice, Pct, Section, Select, Stat, useForm, useLoad } from '../components/kit.jsx'
import { Donut, HistoryChart } from '../components/charts.jsx'
import ImportPanel from '../components/ImportPanel.jsx'
import { ValuationForm } from './PropertyTab.jsx'
import { fmtAUD, fmtDate, fmtPct, label, todayISO } from '../lib/format.js'

const IMPORTS = [{ key: 'other_assets', label: 'Other assets' }, { key: 'liabilities', label: 'Liabilities (loans, cards)' }, { key: 'valuations', label: 'Valuations and balances' }, { key: 'networth_snapshots', label: 'Net worth history (snapshots)' }]

// Net worth from the register (market value), property, the LEDGER (cash, other assets, loans) and what you record by hand, with no double counting.
export default function NetWorthTab({ me }) {
  const caps = me.capabilities
  const [bump, setBump] = useState(0)
  const [months, setMonths] = useState('24')
  const [asset, setAsset] = useState(null)
  const [liab, setLiab] = useState(null)
  const [value, setValue] = useState(null)
  const nw = useLoad(() => api.networth.get(), [bump])
  const hist = useLoad(() => api.networth.history(Number(months)), [months, bump])
  const oa = useLoad(() => api.otherAssets.list(), [bump])
  const li = useLoad(() => api.liabilities.list(), [bump])
  const snaps = useLoad(() => api.networth.snapshots(), [bump])
  const rec = useLoad(() => api.ledger.reconciliation(), [bump])
  const again = () => setBump(n => n + 1)
  return (
    <div style={{ padding: 16 }}>
      <Disclaimer />
      <Async q={nw}>{n => (
        <>
          <Notice items={n.warnings} />
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit,minmax(170px,1fr))', gap: 12, marginBottom: 12 }}>
            <Stat label="Net worth" value={<Money v={n.net_worth} strong />} tone={Number(n.net_worth) < 0 ? 'danger' : undefined} /><Stat label="Total assets" value={<Money v={n.total_assets} />} /><Stat label="Total liabilities" value={<Money v={n.total_liabilities} />} />
            <Stat label="Debt to assets" value={<Pct v={n.ratios.debt_to_assets} digits={1} />} /><Stat label="Liquid assets" value={<Money v={n.ratios.liquid_assets} />} sub={n.ratios.liquid_share != null ? `${fmtPct(n.ratios.liquid_share, 0)} of assets: cash, shares, funds, crypto` : ''} /></div>
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit,minmax(300px,1fr))', gap: 12 }}>
            <Section title="Assets by group"><Donut data={n.assets_by_group} title="Assets by group" /></Section><Section title="Liabilities by group"><Donut data={n.liabilities_by_group.map(x => ({ ...x, weight: Number(n.total_liabilities) ? Number(x.value) / Number(n.total_liabilities) : 0 }))} title="Liabilities by group" /></Section></div>
          <Section title="Net worth over time" actions={<div style={{ width: 150 }}><Select label="Period" value={months} onChange={e => setMonths(e.target.value)} options={[{ value: '12', label: '12 months' }, { value: '24', label: '24 months' }, { value: '60', label: '5 years' }, { value: '120', label: '10 years' }]} /></div>}
            hint="Month-end figures recomputed from your register, valuations and the ledger as at each date.">
            <Async q={hist}>{h => (
              <>
                {h.change && <div className="text-sm" style={{ marginBottom: 6 }}>Change since {fmtDate(h.change.from_date)}: <Money v={h.change.amount} strong /> {h.change.pct != null && <span className="text-muted">({fmtPct(h.change.pct, 1)})</span>}</div>}
                <HistoryChart points={h.points} series={[{ key: 'assets', name: 'Assets' }, { key: 'liabilities', name: 'Liabilities' }, { key: 'net_worth', name: 'Net worth' }]} /></>)}</Async></Section>
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit,minmax(360px,1fr))', gap: 12 }}>
            <Section title="What is counted: assets"><DataGrid rows={n.assets.map((a, i) => ({ ...a, id: i }))} pageSize={50} empty="No assets" columns={[{ key: 'group', label: 'Group' }, { key: 'name', label: 'Item' }, { key: 'value', label: 'Value', money: true }, { key: 'source', label: 'Source', render: a => <span className="text-xs text-muted">{a.source}</span> }]} /></Section>
            <Section title="What is counted: liabilities"><DataGrid rows={n.liabilities.map((a, i) => ({ ...a, id: i }))} pageSize={50} empty="No liabilities" columns={[{ key: 'group', label: 'Group' }, { key: 'name', label: 'Item' }, { key: 'value', label: 'Balance', money: true }, { key: 'source', label: 'Source', render: a => <span className="text-xs text-muted">{a.source}</span> }]} /></Section></div>
        </>)}</Async>
      <Section title="Other assets" hint="Vehicles, collectables, super, business interests: anything that is not an investment, property or in the ledger." actions={<>{caps.includes('edit') && <button className="btn btn-primary btn-sm" onClick={() => setAsset({})}>+ Asset</button>}<ImportPanel datasets={IMPORTS} caps={caps} onDone={again} /></>}>
        <Async q={oa}>{rows => <DataGrid rows={rows} empty="No other assets" columns={[{ key: 'name', label: 'Asset' }, { key: 'kind', label: 'Kind', render: r => label(r.kind) }, { key: 'value', label: 'Latest value', render: r => (r.value == null ? <span className="text-muted">none recorded</span> : <Money v={r.value} />), align: 'right' }, { key: 'value_as_at', label: 'As at', date: true },
          { key: 'x', label: '', render: r => caps.includes('edit') && <span className="flex gap-1"><button className="btn btn-outline btn-xs" onClick={() => setValue({ type: 'other_asset', id: r.id, name: r.name })}>+ Value</button><button className="btn btn-ghost btn-xs" onClick={() => setAsset(r)}>Edit</button></span> }]} />}</Async></Section>
      <Section title="Liabilities" hint="Loans that are not already in the ledger. A liability linked to a ledger account is read from the ledger only, so nothing is counted twice." actions={caps.includes('edit') && <button className="btn btn-primary btn-sm" onClick={() => setLiab({})}>+ Liability</button>}>
        <Async q={li}>{rows => <DataGrid rows={rows} empty="No liabilities recorded" columns={[{ key: 'name', label: 'Liability' }, { key: 'kind', label: 'Kind', render: r => label(r.kind) }, { key: 'lender', label: 'Lender' }, { key: 'interest_rate', label: 'Rate', render: r => (r.interest_rate ? `${r.interest_rate}%` : '—'), align: 'right' },
          { key: 'balance', label: 'Latest balance', render: r => (r.ledger_account_id ? <span className="text-muted">from the ledger</span> : r.balance == null ? <span className="text-muted">none recorded</span> : <Money v={r.balance} />), align: 'right' }, { key: 'balance_as_at', label: 'As at', date: true },
          { key: 'x', label: '', render: r => caps.includes('edit') && <span className="flex gap-1">{!r.ledger_account_id && <button className="btn btn-outline btn-xs" onClick={() => setValue({ type: 'liability', id: r.id, name: r.name })}>+ Balance</button>}<button className="btn btn-ghost btn-xs" onClick={() => setLiab(r)}>Edit</button></span> }]} />}</Async></Section>
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit,minmax(340px,1fr))', gap: 12 }}>
        <Section title="Saved snapshots" hint="A fixed record of net worth on a date (for example each 30 June). Saving twice on a date replaces it." actions={caps.includes('edit') && <button className="btn btn-outline btn-sm" onClick={async () => { if (await act(() => api.networth.snapshot(), 'Snapshot saved')) again() }}>Save today's snapshot</button>}>
          <Async q={snaps}>{rows => <DataGrid rows={rows} empty="No snapshots yet" columns={[{ key: 'as_at', label: 'As at', date: true }, { key: 'total_assets', label: 'Assets', money: true }, { key: 'total_liabilities', label: 'Liabilities', money: true }, { key: 'net_worth', label: 'Net worth', money: true }]} />}</Async></Section>
        <Section title="Investments against the ledger"><Async q={rec}>{r => (
          <div className="text-sm"><div>Register cost base <Money v={r.register_cost_base} /></div><div>Ledger {r.ledger_account.code} {r.ledger_account.name}: {r.ledger_account.balance == null ? 'nothing posted' : <Money v={r.ledger_account.balance} />}</div>
            <div className="text-xs text-muted" style={{ marginTop: 4 }}>{r.explanation} Net worth uses the register's market value and leaves this ledger account out.</div></div>)}</Async></Section></div>
      {asset && <AssetForm item={asset.id ? asset : null} onClose={() => setAsset(null)} onSaved={() => { setAsset(null); again() }} />}
      {liab && <LiabilityForm item={liab.id ? liab : null} onClose={() => setLiab(null)} onSaved={() => { setLiab(null); again() }} />}
      {value && <ValuationForm pid={value.id} ownerType={value.type} onClose={() => setValue(null)} onSaved={() => { setValue(null); again() }} />}
    </div>)
}

function AssetForm({ item, onClose, onSaved }) {
  const refs = useLoad(() => api.reference(), [])
  const [f, set] = useForm({ name: item?.name || '', kind: item?.kind || 'other', notes: item?.notes || '' })
  return (
    <Modal title={item ? 'Edit asset' : 'New asset'} onClose={onClose} width={480}>
      <Async q={refs}>{r => (<><Input label="Name" value={f.name} onChange={set('name')} /><Select label="Kind" value={f.kind} onChange={set('kind')} options={r.other_asset_kinds} /><Input label="Notes" value={f.notes} onChange={set('notes')} />
        <div className="flex gap-1" style={{ justifyContent: 'flex-end' }}><button className="btn btn-outline" onClick={onClose}>Cancel</button><button className="btn btn-primary" disabled={!f.name.trim()} onClick={async () => { if (await act(() => api.otherAssets.save(f, item?.id), 'Saved')) onSaved() }}>Save</button></div></>)}</Async>
    </Modal>)
}

function LiabilityForm({ item, onClose, onSaved }) {
  const refs = useLoad(() => api.reference(), [])
  const [f, set] = useForm({ name: item?.name || '', kind: item?.kind || 'mortgage', lender: item?.lender || '', limit_amount: item?.limit_amount || '', interest_rate: item?.interest_rate || '' })
  return (
    <Modal title={item ? 'Edit liability' : 'New liability'} onClose={onClose} width={520}>
      <Async q={refs}>{r => (<><Grid cols={2}><Input label="Name" value={f.name} onChange={set('name')} /><Select label="Kind" value={f.kind} onChange={set('kind')} options={r.liability_kinds} /><Input label="Lender" value={f.lender} onChange={set('lender')} /><Input label="Limit (AUD)" type="number" value={f.limit_amount} onChange={set('limit_amount')} />
        <Input label="Interest rate % a year" type="number" step="any" value={f.interest_rate} onChange={set('interest_rate')} /></Grid>
        <div className="flex gap-1" style={{ justifyContent: 'flex-end' }}><button className="btn btn-outline" onClick={onClose}>Cancel</button><button className="btn btn-primary" disabled={!f.name.trim()} onClick={async () => { const b = { ...f }; for (const k of Object.keys(b)) if (b[k] === '') b[k] = null; if (await act(() => api.liabilities.save(b, item?.id), 'Saved')) onSaved() }}>Save</button></div></>)}</Async>
    </Modal>)
}
