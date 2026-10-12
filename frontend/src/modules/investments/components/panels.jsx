import React, { useState } from 'react'
import * as api from '../lib/invApi.js'
import { act, Async, Check, DataGrid, Disclaimer, Grid, Input, Modal, Money, Notice, Pct, Qty, Section, Select, Stat, StatusBadge, useForm, useLoad, usePrompt } from './kit.jsx'
import { AccountForm, PriceForm, SecurityForm, TxnForm, useBase } from './forms.jsx'
import DocsPanel from './DocsPanel.jsx'
import HistoryButton from './HistoryButton.jsx'
import ImportPanel from './ImportPanel.jsx'
import { fmtAUD, fmtDate, fmtPct, fyOptions, label, saveBlob } from '../lib/format.js'

const FY_ALL = ''

// ---- exports ------------------------------------------------------------------------------------------------------------------------------------
export function ReportsBar({ kind, fy }) {
  const dl = (name, file) => async () => { const b = await act(() => api.reports.csv(name, { kind, fy })); if (b && b !== true) saveBlob(file, b) }
  return (
    <div className="flex gap-1" style={{ flexWrap: 'wrap' }}>
      {[['holdings', 'Holdings'], ['transactions', 'Transactions'], ['realised', 'Realised gains'], ['income', 'Income'], ['parcels', 'Parcels and cost base']].map(([n, l]) => <button key={n} className="btn btn-outline btn-xs" onClick={dl(n, `${n}.csv`)}>{l} (CSV)</button>)}
      <button className="btn btn-outline btn-xs" onClick={async () => { const b = await act(() => api.reports.pack({ fy })); if (b && b !== true) saveBlob('investments_pack.xlsx', b) }}>Excel pack</button>
    </div>)
}

// ---- security drill-down ---------------------------------------------------------------------------------------------------------------------------
export function SecurityDetail({ id, caps, onClose }) {
  const q = useLoad(() => api.securities.detail(id), [id])
  return (
    <Modal title="Investment detail" onClose={onClose} width={900}>
      <Async q={q}>{d => (
        <div>
          <h3 style={{ margin: '0 0 6px' }}>{d.security.code} · {d.security.name} <span className="badge badge-neutral">{label(d.security.kind)}</span></h3>
          <Notice items={d.warnings.map(w => w.message)} />
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit,minmax(150px,1fr))', gap: 10, marginBottom: 12 }}>
            <Stat label="Market value" value={<Money v={d.performance.market_value} />} /><Stat label="Total return" value={<Money v={d.performance.total_return} />} sub={<Pct v={d.performance.total_return_pct} />} tone={Number(d.performance.total_return) < 0 ? 'danger' : undefined} />
            <Stat label="Annual return (XIRR)" value={<Pct v={d.performance.xirr_since_inception} />} sub="money-weighted" /><Stat label="Invested" value={<Money v={d.performance.total_invested} />} /></div>
          {d.bond && <Section title="Bond maths" hint="Coupon and day-count conventions come from the security record: confirm them against the issue terms.">
            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit,minmax(150px,1fr))', gap: 10 }}>
              <Stat label="Next coupon" value={fmtDate(d.bond.next_coupon)} /><Stat label="Accrued interest / bond" value={<Money v={d.bond.accrued_interest_per_bond} />} /><Stat label="Annual coupon / bond" value={<Money v={d.bond.annual_coupon} />} />
              <Stat label="Days to maturity" value={d.bond.days_to_maturity} />{d.bond.ytm != null && <Stat label="Yield to maturity" value={<Pct v={d.bond.ytm} />} sub={`price ${d.bond.price_per_100} per 100`} />}{d.bond.current_yield != null && <Stat label="Current yield" value={<Pct v={d.bond.current_yield} />} />}
              {d.bond.duration && <Stat label="Duration (Macaulay / modified)" value={`${d.bond.duration[0].toFixed(2)} / ${d.bond.duration[1].toFixed(2)} yrs`} />}</div>
            <details style={{ marginTop: 8 }}><summary className="text-sm">Remaining cash flows per bond</summary><table className="data-table"><tbody>{d.bond.cashflows.map(c => <tr key={c.date}><td>{fmtDate(c.date)}</td><td className="text-right"><Money v={c.amount} /></td></tr>)}</tbody></table></details></Section>}
          <Section title="Parcels (cost base)" hint="Each parcel keeps its own acquisition date: the 12-month discount test is per parcel."><DataGrid rows={d.parcels} rowKey="lot_id" empty="Nothing held" columns={[{ key: 'acquired', label: 'Acquired', date: true }, { key: 'qty', label: 'Units', render: r => <Qty v={r.qty} />, align: 'right' }, { key: 'cost_base', label: 'Cost base', money: true },
            { key: 'unit_cost', label: 'Per unit', render: r => <Money v={r.unit_cost} />, align: 'right' }, { key: 'origin', label: 'Origin', render: r => label(r.origin) }, { key: 'discount_eligible', label: 'Over 12 months', render: r => (r.discount_eligible ? 'Yes' : 'No') }]} /></Section>
          <Section title="Disposals"><DataGrid rows={d.disposals} rowKey="txn_id" empty="No disposals" columns={[{ key: 'dispose_date', label: 'Sold', date: true }, { key: 'acquire_date', label: 'Acquired', date: true }, { key: 'qty', label: 'Units', render: r => <Qty v={r.qty} />, align: 'right' }, { key: 'proceeds_net', label: 'Net proceeds', money: true },
            { key: 'cost_base', label: 'Cost base', money: true }, { key: 'gain', label: 'Gain/(loss)', money: true }, { key: 'discount_eligible', label: 'Discount', render: r => (r.discount_eligible ? 'Eligible' : '—') }, { key: 'method', label: 'Method', render: r => label(r.method) }]} /></Section>
          <Section title="Income"><DataGrid rows={d.income} rowKey="txn_id" empty="No income recorded" columns={[{ key: 'date', label: 'Date', date: true }, { key: 'type', label: 'Type', render: r => label(r.type) }, { key: 'cash', label: 'Cash', money: true }, { key: 'franking_credits', label: 'Franking credits', money: true }, { key: 'tax_deferred', label: 'Tax deferred', money: true }]} /></Section>
          <DocsPanel ownerType="security" ownerId={id} caps={caps} />
          <div className="flex gap-1" style={{ justifyContent: 'flex-end', marginTop: 12 }}><button className="btn btn-outline" onClick={onClose}>Close</button></div>
        </div>)}</Async>
    </Modal>)
}

// ---- holdings -------------------------------------------------------------------------------------------------------------------------------------
export function HoldingsPanel({ kind, caps, bump }) {
  const [merge, setMerge] = useState(false)
  const [open, setOpen] = useState(null)
  const q = useLoad(() => api.portfolio.holdings({ kind, merge }), [kind, merge, bump])
  return (
    <div>
      <Async q={q}>{h => {
        const unreal = h.rows.reduce((s, r) => s + Number(r.unrealised), 0), inc = h.rows.reduce((s, r) => s + Number(r.income_12m), 0)
        return (
          <>
            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit,minmax(170px,1fr))', gap: 12, margin: '0 0 12px' }}>
              <Stat label="Market value" value={<Money v={h.total_value} strong />} sub={`${h.rows.length} holding${h.rows.length === 1 ? '' : 's'}`} /><Stat label="Cost base" value={<Money v={h.total_cost} />} />
              <Stat label="Unrealised gain/(loss)" value={<Money v={unreal} strong />} sub={h.total_cost > 0 ? fmtPct(unreal / Number(h.total_cost)) : ''} tone={unreal < 0 ? 'danger' : undefined} /><Stat label="Income, last 12 months" value={<Money v={inc} />} /></div>
            <Notice items={h.warnings.map(w => w.message)} />
            <DataGrid rows={h.rows} rowKey={merge ? 'security_id' : undefined} searchKeys={['code', 'name', 'account']} empty="No holdings yet" hint="Add a transaction or import a broker or exchange file." onRowClick={r => setOpen(r.security_id)}
              toolbar={<Check label="Merge accounts" checked={merge} onChange={e => setMerge(e.target.checked)} />}
              columns={[{ key: 'code', label: 'Code', render: r => <strong>{r.code}</strong> }, { key: 'name', label: 'Name' }, { key: 'account', label: 'Account', render: r => (r.accounts ? r.accounts.join(', ') : r.account) }, { key: 'qty', label: 'Units', render: r => <Qty v={r.qty} />, align: 'right' },
                { key: 'cost_base', label: 'Cost base', money: true }, { key: 'price', label: 'Price', render: r => (r.price == null ? <span className="text-muted" title={r.price_note || ''}>no price</span> : <span className="mono" title={r.price_date ? `as at ${r.price_date}` : ''}>{fmtAUD(r.price)}{r.price_stale ? ' ▲' : ''}</span>), align: 'right' },
                { key: 'value', label: 'Value', money: true }, { key: 'unrealised', label: 'Gain/(loss)', money: true }, { key: 'unrealised_pct', label: '%', render: r => <Pct v={r.unrealised_pct} digits={1} />, align: 'right' }, { key: 'income_12m', label: 'Income 12m', money: true },
                { key: 'weight', label: 'Weight', render: r => <Pct v={r.weight} digits={1} />, align: 'right' }]} />
          </>)
      }}</Async>
      {open && <SecurityDetail id={open} caps={caps} onClose={() => setOpen(null)} />}
    </div>)
}

// ---- transactions -----------------------------------------------------------------------------------------------------------------------------------
export function TransactionsPanel({ kinds, me, bump, onChanged, importKeys, extraActions, defaultsFor }) {
  const caps = me.capabilities
  const base = useBase(kinds)
  const [f, set] = useForm({ account_id: '', security_id: '', txn_type: '', date_from: '', date_to: '', q: '', include_voided: false })
  const [applied, setApplied] = useState(f)
  const [edit, setEdit] = useState(null)
  const [dialog, ask] = usePrompt()
  const q = useLoad(() => api.txns.list({ ...applied, kind: kinds.join(',') }), [JSON.stringify(applied), kinds.join(','), bump])
  const reload = () => { q.reload(); onChanged && onChanged() }
  const bad = f.date_from && f.date_to && f.date_to < f.date_from
  const void_ = async t => { const r = await ask({ title: 'Void transaction', message: `${label(t.txn_type)} ${t.code} on ${fmtDate(t.trade_date)}. It stays in the history but no longer counts.`, confirmLabel: 'Void', fields: [{ key: 'reason', label: 'Reason (at least 5 characters)', value: '' }] }); if (r.ok && await act(() => api.txns.void(t.id, r.values.reason), 'Voided')) reload() }
  return (
    <div>
      {dialog}
      <Async q={base}>{b => (
        <>
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit,minmax(140px,1fr))', gap: 8, alignItems: 'end' }}>
            <Select label="Account" value={f.account_id} blank="All" onChange={set('account_id')} options={b.accounts.map(a => ({ value: a.id, label: a.name }))} /><Select label="Security" value={f.security_id} blank="All" onChange={set('security_id')} options={b.securities.map(s => ({ value: s.id, label: s.code }))} />
            <Select label="Type" value={f.txn_type} blank="All" onChange={set('txn_type')} options={b.reference.txn_types} /><Input label="From" type="date" value={f.date_from} onChange={set('date_from')} /><Input label="To" type="date" value={f.date_to} onChange={set('date_to')} />
            <Input label="Search" value={f.q} onChange={set('q')} /><Check label="Show voided" checked={f.include_voided} onChange={set('include_voided')} /><div style={{ marginBottom: 14 }}><button className="btn btn-primary btn-sm" disabled={bad} onClick={() => setApplied(f)}>Apply filters</button></div></div>
          {bad && <div className="text-xs" style={{ color: 'var(--danger)' }}>The end date is before the start date.</div>}
          <Section title="Transactions" actions={<>{caps.includes('edit') && <button className="btn btn-primary btn-sm" onClick={() => setEdit({})}>+ Transaction</button>}{extraActions}<ImportPanel datasets={importKeys} caps={caps} onDone={reload} /></>}>
            <Async q={q}>{rows => <DataGrid rows={rows} empty="No transactions match" hint="Add one, import a file, or widen the filters." columns={[
              { key: 'trade_date', label: 'Date', date: true }, { key: 'txn_type', label: 'Type', render: t => <span>{label(t.txn_type)}{t.voided && <> <StatusBadge status="void" text="Voided" /></>}{t.linked_journal_id && <> <span className="badge badge-info" title="Posted to the ledger">Ledger</span></>}</span> },
              { key: 'code', label: 'Security', render: t => <><strong>{t.code}</strong><div className="text-xs text-muted">{t.account}</div></> }, { key: 'quantity', label: 'Units', render: t => (Number(t.quantity) ? <Qty v={t.quantity} /> : '—'), align: 'right' },
              { key: 'price', label: 'Price', render: t => (t.price ? <Money v={t.price} /> : '—'), align: 'right' }, { key: 'amount', label: 'Amount', money: true }, { key: 'fees', label: 'Fees', money: true },
              { key: 'franking_credits', label: 'Franking', render: t => (Number(t.franking_credits) ? <Money v={t.franking_credits} /> : '—'), align: 'right' }, { key: 'reference', label: 'Reference' },
              { key: 'x', label: '', render: t => <span className="flex gap-1">{caps.includes('edit') && !t.voided && !t.linked_journal_id && <button className="btn btn-ghost btn-xs" onClick={() => setEdit(t)}>Edit</button>}
                {caps.includes('edit') && !t.voided && !t.linked_journal_id && <button className="btn btn-ghost btn-xs" onClick={() => void_(t)}>Void</button>}<HistoryButton type="inv_transaction" id={t.id} caps={caps} /></span> }]} searchKeys={['code', 'reference', 'txn_type']} />}</Async>
          </Section>
          {edit && <TxnForm item={edit.id ? edit : null} defaults={edit.id ? null : defaultsFor && defaultsFor()} base={b} kinds={kinds} onClose={() => setEdit(null)} onSaved={() => { setEdit(null); reload() }} />}
        </>)}</Async>
    </div>)
}

// ---- income ---------------------------------------------------------------------------------------------------------------------------------------
export function IncomePanel({ kind, bump }) {
  const [fy, setFy] = useState(FY_ALL)
  const q = useLoad(() => api.portfolio.income({ fy }), [fy, bump])
  const kinds = kind ? kind.split(',') : null
  return (
    <div>
      <div style={{ maxWidth: 220 }}><Select label="Income year" value={fy} blank="All years" onChange={e => setFy(e.target.value)} options={fyOptions(6)} /></div>
      <Async q={q}>{inc => {
        const rows = kinds ? inc.rows.filter(r => kinds.includes(r.kind)) : inc.rows
        const tot = k => rows.reduce((s, r) => s + Number(r[k] || 0), 0)
        return (
          <>
            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit,minmax(160px,1fr))', gap: 12, margin: '8px 0 12px' }}>
              <Stat label="Cash income" value={<Money v={tot('cash')} strong />} /><Stat label="Franking credits" value={<Money v={tot('franking_credits')} />} sub="a tax offset, grossed up in your return" /><Stat label="Capital gain components" value={<Money v={tot('cg_discount_part') + tot('cg_other_part')} />} />
              <Stat label="Tax-deferred (cost base)" value={<Money v={tot('tax_deferred')} />} />{tot('value_in_kind') > 0 && <Stat label="Staking / airdrops" value={<Money v={tot('value_in_kind')} />} sub="income at AUD value on receipt" />}</div>
            <Notice items={inc.flags.map(f => f.message)} />
            <Section title="By income year"><DataGrid rows={inc.by_fy.map(r => ({ ...r, id: r.key }))} empty="No income yet" columns={[{ key: 'key', label: 'Income year' }, { key: 'cash', label: 'Cash', money: true }, { key: 'franked', label: 'Franked', money: true }, { key: 'unfranked', label: 'Unfranked', money: true }, { key: 'franking_credits', label: 'Franking credits', money: true },
              { key: 'foreign_income', label: 'Foreign', money: true }, { key: 'capital_gain_components', label: 'Capital gain parts', money: true }, { key: 'tax_deferred', label: 'Tax deferred', money: true }, { key: 'interest', label: 'Interest', money: true }, { key: 'staking_airdrop', label: 'Staking/airdrop', money: true }]} /></Section>
            <Section title="Entries"><DataGrid rows={rows} rowKey="txn_id" searchKeys={['code', 'name', 'type']} empty="No income recorded" columns={[{ key: 'date', label: 'Date', date: true }, { key: 'code', label: 'Security', render: r => <strong>{r.code}</strong> }, { key: 'type', label: 'Type', render: r => label(r.type) }, { key: 'cash', label: 'Cash', money: true },
              { key: 'franked', label: 'Franked', money: true }, { key: 'franking_credits', label: 'Franking', money: true }, { key: 'tax_deferred', label: 'Tax deferred', money: true }, { key: 'fy', label: 'Year' }]} /></Section>
          </>)
      }}</Async>
    </div>)
}

// ---- realised gains and Tax ---------------------------------------------------------------------------------------------------------------------
export function GainsPanel({ kind, me, bump, onChanged }) {
  const [fy, setFy] = useState(FY_ALL)
  const caps = me.capabilities
  const q = useLoad(() => api.portfolio.disposals({ fy, kind }), [fy, kind, bump])
  const [sent, setSent] = useState(null)
  const send = async dry => { const r = await act(() => api.cgt.send({ fy, kind, dry_run: dry })); if (r && r !== true) { setSent({ ...r, dry }); if (!dry) onChanged && onChanged() } }
  return (
    <div>
      <Disclaimer />
      <div className="flex items-end gap-1" style={{ flexWrap: 'wrap' }}><div style={{ minWidth: 200 }}><Select label="Income year" value={fy} blank="All years" onChange={e => { setFy(e.target.value); setSent(null) }} options={fyOptions(6)} /></div>
        {caps.includes('edit') && <div style={{ marginBottom: 14 }} className="flex gap-1"><button className="btn btn-outline btn-sm" onClick={() => send(true)}>Check what would go to Tax</button><button className="btn btn-primary btn-sm" onClick={() => send(false)}>Send disposals to Tax (CGT)</button></div>}</div>
      {sent && <div role="status" className="alert alert-info" style={{ marginBottom: 10 }}>{sent.dry ? 'Check only, nothing was saved: ' : 'Sent: '}{sent.added} would be added{sent.dry ? '' : ' (added)'}, {sent.skipped_duplicates} already in Taxation, {sent.rejected} rejected.{sent.errors?.slice(0, 3).map((e, i) => <div key={i} className="text-xs">Row {e.row}: {e.error}</div>)}</div>}
      <Async q={q}>{d => (
        <>
          {d.summary.by_fy.map(s => (
            <div key={s.fy} style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit,minmax(150px,1fr))', gap: 10, marginBottom: 10 }}>
              <Stat label={`${s.fy} gains (discountable)`} value={<Money v={s.gains_discountable} />} sub="held over 12 months" /><Stat label="Gains (other)" value={<Money v={s.gains_other} />} /><Stat label="Losses" value={<Money v={s.losses} />} tone={Number(s.losses) > 0 ? 'danger' : undefined} />
              <Stat label={`Discount (${fmtPct(d.summary.discount_rate, 1)})`} value={<Money v={s.discount} />} sub={`holder: ${label(d.holder)}`} /><Stat label="Estimated net capital gain" value={<Money v={s.net_capital_gain} strong />} sub={Number(s.losses_carried_forward) > 0 ? `${fmtAUD(s.losses_carried_forward)} loss carried forward` : undefined} /></div>))}
          {d.excess_gains.length > 0 && <Notice items={d.excess_gains.map(e => `${e.code}: ${e.reason} on ${fmtDate(e.date)}: ${fmtAUD(e.amount)} is a capital gain`)} />}
          <div className="text-xs text-muted" style={{ marginBottom: 6 }}>{d.summary.note} Parcel method: {d.method.toUpperCase()}.</div>
          <DataGrid rows={d.rows} rowKey="txn_id" searchKeys={['code', 'name']} empty="No disposals" hint="Sales appear here with the parcels they were matched to." columns={[{ key: 'dispose_date', label: 'Sold', date: true }, { key: 'code', label: 'Security', render: r => <strong>{r.code}</strong> }, { key: 'acquire_date', label: 'Acquired', date: true }, { key: 'qty', label: 'Units', render: r => <Qty v={r.qty} />, align: 'right' },
            { key: 'proceeds', label: 'Proceeds', money: true }, { key: 'selling_costs', label: 'Selling costs', money: true }, { key: 'cost_base', label: 'Cost base', money: true }, { key: 'gain', label: 'Gain/(loss)', money: true }, { key: 'discount_eligible', label: 'Over 12 months', render: r => (r.gain > 0 ? (r.discount_eligible ? 'Yes' : 'No') : '—') },
            { key: 'method', label: 'Method', render: r => label(r.method) }, { key: 'fy', label: 'Year' }]} />
        </>)}</Async>
    </div>)
}

// ---- securities and prices --------------------------------------------------------------------------------------------------------------------------
export function SecuritiesPanel({ kinds, me, onChanged, importKeys }) {
  const caps = me.capabilities
  const base = useBase(kinds)
  const q = useLoad(() => api.securities.list({ kind: kinds.join(',') }), [kinds.join(',')])
  const [edit, setEdit] = useState(null)
  const [price, setPrice] = useState(null)
  const [acct, setAcct] = useState(null)
  const reload = () => { q.reload(); base.reload(); onChanged && onChanged() }
  return (
    <div>
      <Async q={base}>{b => (
        <>
          <Section title="Accounts" hint="Brokers, exchanges and platforms. Parcels are tracked per account." actions={caps.includes('edit') && <button className="btn btn-outline btn-sm" onClick={() => setAcct({})}>+ Account</button>}>
            <DataGrid rows={b.accounts} empty="No accounts yet" hint="Add the broker or exchange you buy through." columns={[{ key: 'name', label: 'Name' }, { key: 'kind', label: 'Kind', render: r => label(r.kind) }, { key: 'institution', label: 'Institution' }, { key: 'identifier', label: 'Identifier' },
              { key: 'x', label: '', render: r => caps.includes('edit') && <button className="btn btn-ghost btn-xs" onClick={() => setAcct(r)}>Edit</button> }]} /></Section>
          <Section title="Securities and prices" actions={<>{caps.includes('edit') && <button className="btn btn-primary btn-sm" onClick={() => setEdit({})}>+ Security</button>}<ImportPanel datasets={importKeys} caps={caps} onDone={reload} /></>}>
            <Async q={q}>{rows => <DataGrid rows={rows} searchKeys={['code', 'name', 'sector']} empty="No securities yet" columns={[{ key: 'code', label: 'Code', render: r => <strong>{r.code}</strong> }, { key: 'name', label: 'Name' }, { key: 'kind', label: 'Kind', render: r => label(r.kind) }, { key: 'asset_class', label: 'Asset class', render: r => label(r.asset_class) },
              { key: 'sector', label: 'Sector' }, { key: 'x', label: '', render: r => <span className="flex gap-1">{caps.includes('edit') && <button className="btn btn-outline btn-xs" onClick={() => setPrice(r)}>Prices</button>}{caps.includes('edit') && <button className="btn btn-ghost btn-xs" onClick={() => setEdit(r)}>Edit</button>}<HistoryButton type="inv_security" id={r.id} caps={caps} /></span> }]} />}</Async>
          </Section>
          {edit && <SecurityForm item={edit.id ? edit : null} kinds={kinds} reference={b.reference} onClose={() => setEdit(null)} onSaved={() => { setEdit(null); reload() }} />}
          {acct && <AccountForm item={acct.id ? acct : null} reference={b.reference} onClose={() => setAcct(null)} onSaved={() => { setAcct(null); reload() }} />}
          {price && <PriceForm security={price} onClose={() => setPrice(null)} onSaved={onChanged} />}
        </>)}</Async>
    </div>)
}

// ---- ledger -----------------------------------------------------------------------------------------------------------------------------------------
export function LedgerPanel({ me, bump, onChanged }) {
  const caps = me.capabilities
  const rec = useLoad(() => api.ledger.reconciliation(), [bump])
  const banks = useLoad(() => api.ledger.bankAccounts(), [])
  const tx = useLoad(() => api.txns.list({}), [bump])
  const [bank, setBank] = useState('')
  const [sel, setSel] = useState({})
  const [res, setRes] = useState(null)
  const postable = t => !t.voided && !t.linked_journal_id && !['split', 'bonus', 'cost_base_adjustment', 'transfer_out', 'transfer_in'].includes(t.txn_type)
  const chosen = Object.keys(sel).filter(k => sel[k])
  const post = async () => { const r = await act(() => api.ledger.post({ txn_ids: chosen.map(Number), bank_account_id: Number(bank) })); if (r && r !== true) { setRes(r); setSel({}); tx.reload(); rec.reload(); onChanged && onChanged() } }
  return (
    <div>
      <Section title="Register against the ledger" hint="Posting records each transaction as a journal at cost, with the realised gain or loss on a sale. The cash side goes to the bank account you choose, so your bank reconciliation matches it against the statement.">
        <Async q={rec}>{r => (
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit,minmax(170px,1fr))', gap: 12 }}>
            <Stat label="Register cost base" value={<Money v={r.register_cost_base} />} /><Stat label={`Ledger ${r.ledger_account.code} ${r.ledger_account.name}`} value={r.ledger_account.balance == null ? '—' : <Money v={r.ledger_account.balance} />} />
            <Stat label="Difference" value={r.difference == null ? '—' : <Money v={r.difference} />} tone={r.status === 'differs' ? 'danger' : undefined} sub={{ agrees: 'agrees', agrees_after_tax_adjustments: 'agrees after tax-only adjustments', differs: 'differs', no_ledger_account: 'nothing posted yet' }[r.status]} /><Stat label="Posted / still to post" value={`${r.posted_transactions} / ${r.unposted_postable}`} />
            <div style={{ gridColumn: '1 / -1' }} className="text-xs text-muted">{r.explanation}</div></div>)}</Async>
      </Section>
      {caps.includes('post') && (
        <Section title="Post transactions to the ledger" actions={<button className="btn btn-primary btn-sm" disabled={!bank || chosen.length === 0} onClick={post}>Post {chosen.length || ''} selected</button>}>
          <div style={{ maxWidth: 360 }}><Async q={banks}>{b => <Select label="Bank account" value={bank} blank="Choose the bank account…" onChange={e => setBank(e.target.value)} options={b.map(x => ({ value: x.id, label: `${x.code} ${x.name}` }))} />}</Async></div>
          {res && <div role="status" className="alert alert-info" style={{ marginBottom: 8 }}>{res.posted.length} posted · {res.skipped.length} skipped · {res.failed.length} failed.{res.failed.slice(0, 5).map(f => <div key={f.id} className="text-xs">#{f.id}: {f.error}</div>)}</div>}
          <div className="flex gap-1" style={{ margin: '6px 0' }}><button className="btn btn-outline btn-xs" onClick={() => setSel(Object.fromEntries((tx.data || []).filter(postable).map(t => [t.id, true])))}>Select all</button><button className="btn btn-outline btn-xs" onClick={() => setSel({})}>Clear</button></div>
          <Async q={tx}>{rows => <DataGrid rows={rows.filter(postable)} empty="Everything postable has been posted" columns={[{ key: 's', label: '', render: t => <input type="checkbox" aria-label={`Select ${t.code} ${t.trade_date}`} checked={!!sel[t.id]} onChange={e => setSel(s => ({ ...s, [t.id]: e.target.checked }))} /> }, { key: 'trade_date', label: 'Date', date: true },
            { key: 'txn_type', label: 'Type', render: t => label(t.txn_type) }, { key: 'code', label: 'Security' }, { key: 'amount', label: 'Amount', money: true }, { key: 'fees', label: 'Fees', money: true }]} />}</Async>
        </Section>)}
    </div>)
}

// ---- settings --------------------------------------------------------------------------------------------------------------------------------------
export function SettingsButton({ me, onSaved }) {
  const [open, setOpen] = useState(false)
  return <>{<button className="btn btn-outline btn-sm" onClick={() => setOpen(true)}>Settings</button>}{open && <SettingsModal can={me.capabilities.includes('config')} onClose={() => setOpen(false)} onSaved={() => { setOpen(false); onSaved && onSaved() }} />}</>
}
function SettingsModal({ can, onClose, onSaved }) {
  const q = useLoad(() => api.settings.get(), [])
  return (
    <Modal title="Investment settings" onClose={onClose} width={520}>
      <Async q={q}>{s => <SettingsForm s={s} can={can} onClose={onClose} onSaved={onSaved} />}</Async>
    </Modal>)
}
function SettingsForm({ s, can, onClose, onSaved }) {
  const [f, set] = useForm({ cgt_method: s.cgt_method, holder: s.holder })
  return (
    <>
      <Select label="Parcel (CGT) method" value={f.cgt_method} onChange={set('cgt_method')} disabled={!can} options={[{ value: 'fifo', label: 'First in, first out (default)' }, { value: 'lifo', label: 'Last in, first out' }, { value: 'hifo', label: 'Highest cost first' }]}
        hint="FIFO is the default where parcels cannot be identified. LIFO and HIFO, or naming the parcel on a sale, need records that support them. Average cost is not an accepted method." />
      <Select label="Who holds these investments (CGT discount)" value={f.holder} onChange={set('holder')} disabled={!can} options={[{ value: 'individual', label: 'Individual (50% discount over 12 months)' }, { value: 'trust', label: 'Trust (50%)' }, { value: 'super', label: 'Super fund (one third)' }, { value: 'company', label: 'Company (no discount)' }]} />
      <div className="text-xs text-muted">Ledger accounts used when posting: {Object.values(s.ledger_map).map(a => `${a.code} ${a.name}`).join(' · ')}</div>
      <div className="flex gap-1" style={{ justifyContent: 'flex-end', marginTop: 10 }}><button className="btn btn-outline" onClick={onClose}>Close</button>{can && <button className="btn btn-primary" onClick={async () => { if (await act(() => api.settings.save(f), 'Saved')) onSaved() }}>Save</button>}</div>
    </>)
}
