import React, { useMemo } from 'react'
import * as api from '../lib/invApi.js'
import { act, Async, Check, Grid, Input, Modal, Select, useForm, useLoad } from './kit.jsx'
import { label, todayISO } from '../lib/format.js'

export const TYPES_FOR = {
  share: ['buy', 'sell', 'dividend', 'drp', 'split', 'bonus', 'return_of_capital', 'fee', 'transfer_out', 'transfer_in'],
  etf: ['buy', 'sell', 'distribution', 'dividend', 'drp', 'split', 'return_of_capital', 'cost_base_adjustment', 'fee', 'transfer_out', 'transfer_in'],
  crypto: ['buy', 'sell', 'income_in_kind', 'fee', 'transfer_out', 'transfer_in'],
  managed_fund: ['buy', 'sell', 'distribution', 'cost_base_adjustment', 'fee'],
  bond: ['buy', 'sell', 'interest', 'fee'],
  term_deposit: ['buy', 'sell', 'interest'],
}
const FIELDS = {
  buy: ['quantity', 'price', 'amount', 'fees', 'reference'], sell: ['quantity', 'price', 'amount', 'fees', 'reference', 'lot_ref'], dividend: ['amount', 'franked', 'unfranked', 'franking_credits', 'withholding_tax'],
  drp: ['quantity', 'price', 'amount', 'franked', 'unfranked', 'franking_credits'], distribution: ['amount', 'franked', 'unfranked', 'franking_credits', 'foreign_income', 'foreign_tax_paid', 'cg_discount_part', 'cg_other_part', 'tax_deferred', 'cost_base_adj', 'withholding_tax', 'reference'],
  interest: ['amount', 'withholding_tax'], fee: ['amount'], split: ['quantity', 'price'], bonus: ['quantity', 'amount'], return_of_capital: ['amount'], cost_base_adjustment: ['cost_base_adj'],
  income_in_kind: ['quantity', 'amount'], transfer_out: ['quantity', 'reference'], transfer_in: ['quantity', 'reference', 'amount'],
}
const LABEL = { quantity: 'Units / quantity', price: 'Price per unit', amount: 'Amount (AUD)', fees: 'Brokerage / fees', reference: 'Reference', franked: 'Franked amount', unfranked: 'Unfranked amount', franking_credits: 'Franking credits',
  withholding_tax: 'Tax withheld', foreign_income: 'Foreign income', foreign_tax_paid: 'Foreign tax paid', cg_discount_part: 'Capital gain (discountable)', cg_other_part: 'Capital gain (other)', tax_deferred: 'Tax-deferred amount',
  cost_base_adj: 'AMIT cost base net amount (+/−)', lot_ref: 'Specific parcel (optional)' }
const HINT = { split: 'Quantity is the new units, price is the old units: 2 for 1 is quantity 2, price 1', bonus: 'Leave the amount empty for a tax-free bonus issue (the cost base is spread across all units)', income_in_kind: 'Staking or airdrop: units received and their AUD value on receipt',
  transfer_out: 'Between your own accounts or wallets: the cost base and acquisition dates carry across. Use the same reference on both halves', transfer_in: 'Same reference as the transfer out. The amount is used only if no matching transfer out exists',
  tax_deferred: 'Reduces the cost base; not income', cost_base_adj: 'From the AMMA statement: positive increases, negative decreases the cost base' }

// Everything loaded once for the forms: accounts, securities (optionally limited to some kinds), reference lists.
export function useBase(kinds) {
  return useLoad(async () => {
    const [accounts, securities, reference, settings] = await Promise.all([api.accounts.list(true), api.securities.list({ kind: kinds ? kinds.join(',') : undefined, active_only: true }), api.reference(), api.settings.get()])
    return { accounts, securities, reference, settings }
  }, [(kinds || []).join(',')])
}

export function TxnForm({ item, base, kinds, defaults, onClose, onSaved }) {
  const [f, set, setF] = useForm({ account_id: '', security_id: '', txn_type: 'buy', trade_date: todayISO(), quantity: '', price: '', amount: '', fees: '', reference: '', notes: '', lot_ref: '', franked: '', unfranked: '', franking_credits: '', foreign_income: '', foreign_tax_paid: '',
    cg_discount_part: '', cg_other_part: '', tax_deferred: '', cost_base_adj: '', withholding_tax: '', ...(defaults || {}), ...Object.fromEntries(Object.entries(item || {}).map(([k, v]) => [k, v ?? ''])) })
  const sec = base.securities.find(s => String(s.id) === String(f.security_id))
  const types = TYPES_FOR[sec?.kind] || [...new Set(kinds.flatMap(k => TYPES_FOR[k] || []))]
  const fields = FIELDS[f.txn_type] || []
  const parcels = useLoad(() => (f.txn_type === 'sell' && f.account_id && f.security_id ? api.txns.list({ account_id: f.account_id, security_id: f.security_id, txn_type: 'buy,drp,income_in_kind,bonus' }) : Promise.resolve([])), [f.txn_type, f.account_id, f.security_id])
  const q = Number(f.quantity), pr = Number(f.price)
  const auto = (f.txn_type === 'buy' || f.txn_type === 'sell') && q > 0 && pr > 0 && !f.amount ? (q * pr).toFixed(2) : null
  const problems = [!f.account_id && 'Choose an account', !f.security_id && 'Choose a security', !f.trade_date && 'Date is required', fields.includes('quantity') && !(q > 0) && 'Quantity must be greater than zero',
    ['buy', 'sell'].includes(f.txn_type) && !(Number(f.amount) > 0) && !(q > 0 && pr > 0) && 'Enter the amount (or a price and quantity)', ['dividend', 'drp', 'distribution', 'interest', 'fee', 'return_of_capital', 'income_in_kind'].includes(f.txn_type) && !(Number(f.amount) > 0) && 'Enter the amount',
    f.txn_type === 'split' && !(pr > 0) && 'A split needs both parts of the ratio', ['transfer_out', 'transfer_in'].includes(f.txn_type) && !String(f.reference).trim() && 'A transfer needs a reference shared by its two halves',
    f.txn_type === 'cost_base_adjustment' && !Number(f.cost_base_adj) && 'Enter the AMIT cost base net amount'].filter(Boolean)
  const franked = Number(f.franked), credits = Number(f.franking_credits)
  const warn = [credits > franked * 30 / 70 + 0.05 && 'Franking credits cannot be more than 30/70 of the franked amount', sec?.kind === 'crypto' && f.txn_type === 'sell' && 'Selling crypto is a CGT event; a swap is both a disposal and an acquisition: use "Swap"'].filter(Boolean)
  const go = async () => {
    const body = { ...f }; delete body.id
    for (const k of Object.keys(body)) if (body[k] === '') body[k] = null
    if (!fields.includes('lot_ref')) body.lot_ref = null
    if (await act(() => api.txns.save(body, item?.id), 'Saved')) onSaved()
  }
  return (
    <Modal title={item?.id ? 'Edit transaction' : 'New transaction'} onClose={onClose} width={680}>
      <Grid cols={2}><Select label="Account" value={f.account_id} blank="Choose…" onChange={set('account_id')} options={base.accounts.map(a => ({ value: a.id, label: a.name }))} />
        <Select label="Security" value={f.security_id} blank="Choose…" onChange={e => { set('security_id')(e); setF(s => ({ ...s, security_id: e.target.value, txn_type: (TYPES_FOR[base.securities.find(x => String(x.id) === e.target.value)?.kind] || [s.txn_type]).includes(s.txn_type) ? s.txn_type : 'buy' })) }} options={base.securities.map(s => ({ value: s.id, label: `${s.code} · ${s.name}` }))} />
        <Select label="Type" value={f.txn_type} onChange={set('txn_type')} options={types.map(t => ({ value: t, label: label(t) }))} /><Input label="Date" type="date" value={f.trade_date} onChange={set('trade_date')} /></Grid>
      <Grid cols={3}>{fields.filter(k => k !== 'lot_ref').map(k => <Input key={k} label={LABEL[k]} type={k === 'reference' ? 'text' : 'number'} step="any" value={f[k]} onChange={set(k)} hint={HINT[k]} />)}</Grid>
      {fields.includes('lot_ref') && <Select label={LABEL.lot_ref} value={f.lot_ref} blank="Use the account's method (FIFO unless changed)" onChange={set('lot_ref')} hint="Name the parcel sold: you must be able to support it with your records" options={(parcels.data || []).map(t => ({ value: t.id, label: `${t.trade_date} · ${t.quantity} units · ${t.amount}` }))} />}
      {HINT[f.txn_type] && !fields.some(k => HINT[k]) && <div className="text-xs text-muted">{HINT[f.txn_type]}</div>}
      {auto && <div className="text-xs text-muted">Amount will be {auto} (quantity × price).</div>}
      <Input label="Notes" value={f.notes} onChange={set('notes')} />
      {problems.length > 0 && <div className="text-xs" style={{ color: 'var(--danger)' }}>{problems.join(' · ')}</div>}
      {warn.length > 0 && <div className="text-xs" style={{ color: 'var(--warning)' }}>▲ {warn.join(' · ')}</div>}
      <div className="flex gap-1" style={{ justifyContent: 'flex-end', marginTop: 8 }}><button className="btn btn-outline" onClick={onClose}>Cancel</button><button className="btn btn-primary" disabled={problems.length > 0} onClick={go}>Save</button></div>
    </Modal>)
}

export function SecurityForm({ item, kinds, reference, onClose, onSaved }) {
  const [f, set] = useForm({ kind: kinds[0], code: '', name: '', exchange: '', isin: '', asset_class: '', sector: '', country: '', mer_pct: '', amit: false, face_value: '', coupon_rate: '', coupon_freq: '2', issue_date: '', maturity_date: '', day_count: 'act/act', ...Object.fromEntries(Object.entries(item || {}).map(([k, v]) => [k, v ?? ''])) })
  const bond = f.kind === 'bond', td = f.kind === 'term_deposit', fund = f.kind === 'etf' || f.kind === 'managed_fund'
  const problems = [!f.code.trim() && 'Code is required', !f.name.trim() && 'Name is required', (bond || td) && !f.maturity_date && 'Maturity date is required', bond && !(Number(f.face_value) > 0) && 'Face value is required', bond && !(Number(f.coupon_rate) >= 0 && f.coupon_rate !== '') && 'Coupon rate is required (0.045 = 4.5%)'].filter(Boolean)
  const go = async () => { const b = { ...f }; delete b.id; for (const k of Object.keys(b)) if (b[k] === '') b[k] = null; if (await act(() => api.securities.save(b, item?.id), 'Saved')) onSaved() }
  return (
    <Modal title={item?.id ? 'Edit security' : 'New security'} onClose={onClose} width={640}>
      <Grid cols={2}><Select label="Kind" value={f.kind} onChange={set('kind')} options={kinds} disabled={!!item?.id} /><Input label="Code" value={f.code} onChange={set('code')} hint="ASX code, token symbol or your own code" /><Input label="Name" value={f.name} onChange={set('name')} />
        <Input label="Exchange" value={f.exchange} onChange={set('exchange')} /><Select label="Asset class" value={f.asset_class} blank="Default for the kind" onChange={set('asset_class')} options={reference.asset_classes} /><Input label="Sector" value={f.sector} onChange={set('sector')} />
        <Input label="Country" value={f.country} onChange={set('country')} /><Input label="ISIN" value={f.isin} onChange={set('isin')} />
        {fund && <Input label="MER % a year" type="number" step="any" value={f.mer_pct} onChange={set('mer_pct')} />}{fund && <Check label="Attribution managed investment trust (AMIT)" checked={f.amit} onChange={set('amit')} />}
        {(bond || td) && <Input label="Issue date" type="date" value={f.issue_date} onChange={set('issue_date')} />}{(bond || td) && <Input label="Maturity date" type="date" value={f.maturity_date} onChange={set('maturity_date')} />}
        {bond && <Input label="Face value per unit" type="number" value={f.face_value} onChange={set('face_value')} />}{(bond || td) && <Input label="Coupon / interest rate (fraction)" type="number" step="any" value={f.coupon_rate} onChange={set('coupon_rate')} hint="0.0425 means 4.25% a year" />}
        {bond && <Select label="Coupons a year" value={f.coupon_freq} onChange={set('coupon_freq')} options={['1', '2', '4', '12']} />}{bond && <Select label="Day count" value={f.day_count} onChange={set('day_count')} options={['act/act', 'act/365']} hint="Confirm against the issue terms" />}</Grid>
      {problems.length > 0 && <div className="text-xs" style={{ color: 'var(--danger)' }}>{problems.join(' · ')}</div>}
      <div className="flex gap-1" style={{ justifyContent: 'flex-end', marginTop: 8 }}><button className="btn btn-outline" onClick={onClose}>Cancel</button><button className="btn btn-primary" disabled={problems.length > 0} onClick={go}>Save</button></div>
    </Modal>)
}

export function AccountForm({ item, reference, onClose, onSaved }) {
  const [f, set] = useForm({ name: '', kind: 'broker', institution: '', identifier: '', holder_note: '', ...Object.fromEntries(Object.entries(item || {}).map(([k, v]) => [k, v ?? ''])) })
  const go = async () => { const b = { ...f }; delete b.id; if (await act(() => api.accounts.save(b, item?.id), 'Saved')) onSaved() }
  return (
    <Modal title={item?.id ? 'Edit account' : 'New account'} onClose={onClose} width={520}>
      <Input label="Name" value={f.name} onChange={set('name')} /><Select label="Kind" value={f.kind} onChange={set('kind')} options={reference.account_kinds} /><Input label="Institution" value={f.institution} onChange={set('institution')} />
      <Input label="Identifier" value={f.identifier} onChange={set('identifier')} hint="The last digits of a HIN or a wallet label. Never a Tax File Number" /><Input label="Held in the name of" value={f.holder_note} onChange={set('holder_note')} />
      <div className="flex gap-1" style={{ justifyContent: 'flex-end' }}><button className="btn btn-outline" onClick={onClose}>Cancel</button><button className="btn btn-primary" disabled={!f.name.trim()} onClick={go}>Save</button></div>
    </Modal>)
}

export function PriceForm({ security, onClose, onSaved }) {
  const [f, set] = useForm({ price_date: todayISO(), price: '' })
  const hist = useLoad(() => api.securities.prices(security.id), [security.id])
  return (
    <Modal title={`Prices: ${security.code}`} onClose={onClose} width={520}>
      <Grid cols={2}><Input label="Price date" type="date" value={f.price_date} onChange={set('price_date')} /><Input label="Price per unit (AUD)" type="number" step="any" value={f.price} onChange={set('price')} /></Grid>
      <div className="flex gap-1" style={{ justifyContent: 'flex-end' }}><button className="btn btn-primary btn-sm" disabled={!(Number(f.price) >= 0 && f.price !== '') || !f.price_date} onClick={async () => { if (await act(() => api.securities.setPrice(security.id, f), 'Price saved')) { hist.reload(); onSaved() } }}>Save price</button></div>
      <Async q={hist}>{rows => rows.length === 0 ? <div className="text-xs text-muted">No prices recorded.</div> : <table className="data-table" style={{ marginTop: 8 }}><thead><tr><th>Date</th><th className="text-right">Price</th><th /></tr></thead><tbody>{rows.slice(0, 12).map(r => <tr key={r.id}><td>{r.date}</td><td className="text-right mono">{r.price}</td>
        <td><button className="btn btn-ghost btn-xs" onClick={async () => { if (await act(() => api.securities.removePrice(r.id), 'Removed')) { hist.reload(); onSaved() } }}>Remove</button></td></tr>)}</tbody></table>}</Async>
      <div className="flex gap-1" style={{ justifyContent: 'flex-end', marginTop: 10 }}><button className="btn btn-outline" onClick={onClose}>Close</button></div>
    </Modal>)
}
