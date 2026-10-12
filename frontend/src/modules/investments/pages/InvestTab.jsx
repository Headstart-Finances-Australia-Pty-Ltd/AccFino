import React, { useState } from 'react'
import * as api from '../lib/invApi.js'
import { act, Async, Grid, Input, Modal, Select, useForm, useLoad } from '../components/kit.jsx'
import BulkDocs from '../components/BulkDocs.jsx'
import ImportPanel from '../components/ImportPanel.jsx'
import { GainsPanel, HoldingsPanel, IncomePanel, LedgerPanel, ReportsBar, SecuritiesPanel, SettingsButton, TransactionsPanel } from '../components/panels.jsx'
import { Disclaimer } from '../components/kit.jsx'
import { todayISO } from '../lib/format.js'

// One investments screen, configured by kind: holdings, transactions, income, realised gains (+ send to Tax), securities and prices, ledger, and optionally a statement analyser.
export default function InvestTab({ me, kinds, importKeys, secKeys, extraViews = [], swap = false, intro, defaultsFor }) {
  const [view, setView] = useState('holdings')
  const [bump, setBump] = useState(0)
  const [swapOpen, setSwapOpen] = useState(false)
  const again = () => setBump(n => n + 1)
  const kind = kinds.join(',')
  const VIEWS = [['holdings', 'Holdings'], ['transactions', 'Transactions'], ['income', 'Income'], ['gains', 'Realised gains (CGT)'], ['securities', 'Securities & prices'], ['ledger', 'Ledger & bank'], ...extraViews.map(v => [v.key, v.label])]
  const extra = extraViews.find(v => v.key === view)
  return (
    <div>
      <div className="tabs-bar" role="tablist" aria-label="Views" style={{ margin: '12px 16px 0', flexWrap: 'wrap' }}>
        {VIEWS.map(([k, l]) => <button key={k} role="tab" aria-selected={view === k} className={`tab-btn${view === k ? ' active' : ''}`} onClick={() => setView(k)}>{l}</button>)}
        <span style={{ marginLeft: 'auto', alignSelf: 'center', paddingRight: 8 }} className="flex gap-1" role="group" aria-label="Settings and bulk uploads"><BulkDocs caps={me.capabilities} onDone={again} /><ImportPanel datasets={[{ key: 'settings', label: 'Investment settings' }]} caps={me.capabilities} onDone={again} buttonLabel="Import settings (CSV)" /><SettingsButton me={me} onSaved={again} /></span>
      </div>
      <div style={{ padding: 16 }}>
        {intro && <div className="text-sm text-muted" style={{ marginBottom: 10 }}>{intro}</div>}
        {view === 'holdings' && <><HoldingsPanel kind={kind} caps={me.capabilities} bump={bump} /><div style={{ marginTop: 10 }}><ReportsBar kind={kind} /></div></>}
        {view === 'transactions' && <TransactionsPanel kinds={kinds} me={me} bump={bump} onChanged={again} importKeys={importKeys} defaultsFor={defaultsFor}
          extraActions={swap && me.capabilities.includes('edit') ? <button className="btn btn-outline btn-sm" onClick={() => setSwapOpen(true)}>+ Swap</button> : null} />}
        {view === 'income' && <IncomePanel kind={kind} bump={bump} />}
        {view === 'gains' && <GainsPanel kind={kind} me={me} bump={bump} onChanged={again} />}
        {view === 'securities' && <SecuritiesPanel kinds={kinds} me={me} onChanged={again} importKeys={secKeys} />}
        {view === 'ledger' && <LedgerPanel me={me} bump={bump} onChanged={again} />}
        {extra && extra.render({ me, bump, again })}
      </div>
      {swapOpen && <SwapForm onClose={() => setSwapOpen(false)} onSaved={() => { setSwapOpen(false); again() }} />}
    </div>)
}

function SwapForm({ onClose, onSaved }) {
  const q = useLoad(async () => ({ accounts: await api.accounts.list(true), securities: await api.securities.list({ kind: 'crypto', active_only: true }) }), [])
  return <Modal title="Crypto swap" onClose={onClose} width={620}><Async q={q}>{b => <SwapInner b={b} onClose={onClose} onSaved={onSaved} />}</Async></Modal>
}
function SwapInner({ b, onClose, onSaved }) {
  const [f, set] = useForm({ account_id: '', trade_date: todayISO(), sell_security_id: '', sell_qty: '', buy_security_id: '', buy_qty: '', value_aud: '', fees: '', reference: '' })
  const opts = b.securities.map(s => ({ value: s.id, label: `${s.code} · ${s.name}` }))
  const problems = [!f.account_id && 'Choose an account', !f.sell_security_id && 'Choose what you sent', !f.buy_security_id && 'Choose what you received', f.sell_security_id && f.sell_security_id === f.buy_security_id && 'A swap needs two different tokens',
    !(Number(f.sell_qty) > 0) && 'Quantity sent is required', !(Number(f.buy_qty) > 0) && 'Quantity received is required', !(Number(f.value_aud) > 0) && 'The AUD market value at the time is required'].filter(Boolean)
  return (
    <>
      <div className="text-sm text-muted" style={{ marginBottom: 8 }}>A swap is a CGT event: it disposes of what you sent AND acquires what you received, both at the AUD market value at that moment. AccFino records both legs together.</div>
      <Grid cols={2}><Select label="Account" value={f.account_id} blank="Choose…" onChange={set('account_id')} options={b.accounts.map(a => ({ value: a.id, label: a.name }))} /><Input label="Date" type="date" value={f.trade_date} onChange={set('trade_date')} />
        <Select label="Sent" value={f.sell_security_id} blank="Choose…" onChange={set('sell_security_id')} options={opts} /><Input label="Quantity sent" type="number" step="any" value={f.sell_qty} onChange={set('sell_qty')} />
        <Select label="Received" value={f.buy_security_id} blank="Choose…" onChange={set('buy_security_id')} options={opts} /><Input label="Quantity received" type="number" step="any" value={f.buy_qty} onChange={set('buy_qty')} />
        <Input label="AUD market value at the time" type="number" step="any" value={f.value_aud} onChange={set('value_aud')} /><Input label="Fee (AUD)" type="number" step="any" value={f.fees} onChange={set('fees')} /></Grid>
      <Input label="Reference / tx hash" value={f.reference} onChange={set('reference')} />
      {problems.length > 0 && <div className="text-xs" style={{ color: 'var(--danger)' }}>{problems.join(' · ')}</div>}
      <div className="flex gap-1" style={{ justifyContent: 'flex-end', marginTop: 8 }}><button className="btn btn-outline" onClick={onClose}>Cancel</button>
        <button className="btn btn-primary" disabled={problems.length > 0} onClick={async () => { const body = { ...f }; for (const k of Object.keys(body)) if (body[k] === '') body[k] = null; if (await act(() => api.txns.swap(body), 'Swap recorded')) onSaved() }}>Record swap</button></div>
    </>)
}
