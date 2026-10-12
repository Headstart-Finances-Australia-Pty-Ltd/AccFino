import React, { useState, useEffect } from 'react'
import { obReconcileAccounts, obPull } from '../../open_banking/public.js'
import { RefreshCw, Settings as SettingsIcon } from 'lucide-react'
import { Link, useLocation } from 'react-router-dom'
import { withReturn, withParam } from '../../../core/lib/returnTo.js'
import toast from 'react-hot-toast'
import useOrgRole from '../../../core/hooks/useOrgRole.jsx'

const iso = d => `${d.getFullYear()}-${String(d.getMonth()+1).padStart(2,'0')}-${String(d.getDate()).padStart(2,'0')}`
const daysAgo = n => { const d = new Date(); d.setDate(d.getDate()-n); return d }

// Australian financial year runs 1 Jul - 30 Jun
const PRESETS = {
  last30:  { label:'Last 30 days',  range:() => [daysAgo(30), new Date()] },
  last90:  { label:'Last 90 days',  range:() => [daysAgo(90), new Date()] },
  thisMon: { label:'This month',    range:() => { const n=new Date(); return [new Date(n.getFullYear(),n.getMonth(),1), n] } },
  lastMon: { label:'Last month',    range:() => { const n=new Date(); return [new Date(n.getFullYear(),n.getMonth()-1,1), new Date(n.getFullYear(),n.getMonth(),0)] } },
  fytd:    { label:'Financial year to date', range:() => { const n=new Date(); const y=n.getMonth()>=6?n.getFullYear():n.getFullYear()-1; return [new Date(y,6,1), n] } },
  custom:  { label:'Custom range' },
}

// Only bank accounts that were set up in Settings > Open Banking (Basiq / OpenFeed) are offered here.
export default function OpenBankingInput({ onPulled }) {
  const { isOrgAdmin } = useOrgRole()
  const here = useLocation()
  // Settings > Open Banking sends the person back here (on this same input) as soon as an account is connected
  const settingsTo = withReturn('/settings/open-banking', withParam(here.pathname + here.search, 'input', 'openbanking'))
  const [accounts, setAccounts] = useState(null)   // null = loading
  const [picked,   setPicked]   = useState([])
  const [preset,   setPreset]   = useState('last30')
  const [from,     setFrom]     = useState(iso(daysAgo(30)))
  const [to,       setTo]       = useState(iso(new Date()))
  const [busy,     setBusy]     = useState(false)

  useEffect(() => {
    obReconcileAccounts()
      .then(r => { setAccounts(r.data?.accounts || []) })
      .catch(() => setAccounts([]))
  }, [])

  const choosePreset = k => {
    setPreset(k)
    if (PRESETS[k].range) { const [f,t] = PRESETS[k].range(); setFrom(iso(f)); setTo(iso(t)) }
  }
  // Basiq and OpenFeed accounts can both be pulled (the server reads each from its own provider)
  const PROVIDER_LABEL = { basiq: 'Basiq', openfeed: 'OpenFeed' }
  const pullable = accounts || []
  const allPicked = pullable.length > 0 && pullable.every(a => picked.includes(a.key))
  const toggleAll = () => setPicked(allPicked ? [] : pullable.map(a => a.key))
  const toggle = key => setPicked(p => p.includes(key) ? p.filter(k => k!==key) : [...p, key])
  const badPeriod = !from || !to || from > to
  const label = a => [a.bank, a.name, a.number && `···${String(a.number).slice(-4)}`].filter(Boolean).join(' · ') || a.key

  const pull = async () => {
    if (!picked.length) { toast.error('Select at least one account'); return }
    if (badPeriod)      { toast.error('Check the period — From must be on or before To'); return }
    setBusy(true)
    let total = 0
    for (const a of accounts.filter(x => picked.includes(x.key))) {
      try {
        const { data } = await obPull({ account_key: a.key, from_date: from, to_date: to })
        onPulled(data.rows || [], { bank: data.bank, number: data.account, name: data.account_name, from, to })
        total += data.count || 0
      } catch (e) { toast.error(`${label(a)}: ${e.response?.data?.detail || 'Pull failed'}`) }
    }
    setBusy(false)
    if (total) toast.success(`${total} transactions pulled for ${from} → ${to} and merged into the account CSV data`)
  }

  if (accounts === null) return <div style={{padding:24,textAlign:'center'}}><span className="spinner spinner-sm"/></div>

  if (!accounts.length) return (
    <div className="card card-flat" style={{background:'var(--surface-2)'}}>
      <h4 style={{marginBottom:8}}>No Open Banking accounts set up</h4>
      <p style={{fontSize:'.85rem',color:'var(--text-2)',lineHeight:1.6,margin:'0 0 12px'}}>
        Only bank accounts saved in <strong>Settings → Open Banking</strong> (Basiq or OpenFeed) can be pulled here.{!isOrgAdmin && ' Ask your Organisation Admin to set this up.'}
      </p>
      {isOrgAdmin && <Link className="btn btn-outline btn-sm" to={settingsTo} data-testid="open-bank-settings"><SettingsIcon size={14}/> Open settings</Link>}
    </div>
  )

  return (
    <div style={{display:'flex',flexDirection:'column',gap:14}}>
      <div className="input-group" style={{margin:0}}>
        <label style={{display:'flex',alignItems:'center',justifyContent:'space-between'}}>
          <span>1. Select bank accounts <span style={{fontWeight:400,color:'var(--text-3)'}}>({picked.length} of {pullable.length} selected)</span></span>
          {pullable.length > 1 && (
            <button type="button" className="btn btn-ghost btn-xs" onClick={toggleAll}>{allPicked ? 'Clear' : 'Select all'}</button>
          )}
        </label>
        <div style={{display:'flex',flexDirection:'column',gap:6}}>
          {accounts.map(a => {
            const off = false
            const on  = picked.includes(a.key)
            return (
              <label key={a.key} title={undefined}
                style={{display:'flex',alignItems:'center',gap:8,padding:'8px 10px',fontSize:'.83rem',
                  border:`1.5px solid ${on ? 'var(--brand)' : 'var(--border)'}`,
                  background: on ? 'var(--brand-xlight)' : 'transparent',
                  borderRadius:'var(--r-md)', cursor: off ? 'not-allowed' : 'pointer', opacity: off ? .5 : 1}}>
                <input type="checkbox" checked={on} disabled={off} onChange={() => toggle(a.key)}/>
                <span style={{flex:1,minWidth:0}}>{label(a)}</span>
                <span className="badge badge-neutral">{PROVIDER_LABEL[a.provider] || a.provider}</span>
              </label>
            )
          })}
        </div>
      </div>

      <div className="input-group" style={{margin:0}}>
        <label>2. Choose the period</label>
        <select value={preset} onChange={e => choosePreset(e.target.value)}>
          {Object.entries(PRESETS).map(([k,v]) => <option key={k} value={k}>{v.label}</option>)}
        </select>
      </div>
      <div style={{display:'grid',gridTemplateColumns:'1fr 1fr',gap:10}}>
        <div className="input-group" style={{margin:0}}><label>From</label>
          <input className="input" type="date" value={from} max={to || undefined} onChange={e => { setFrom(e.target.value); setPreset('custom') }}/></div>
        <div className="input-group" style={{margin:0}}><label>To</label>
          <input className="input" type="date" value={to} min={from || undefined} max={iso(new Date())} onChange={e => { setTo(e.target.value); setPreset('custom') }}/></div>
      </div>

      <button className="btn btn-primary btn-sm" onClick={pull} disabled={busy || !picked.length || badPeriod}>
        {busy ? <><span className="spinner spinner-sm"/> Pulling…</> : <><RefreshCw size={14}/> Pull {picked.length > 1 ? `${picked.length} accounts` : 'account'} &amp; merge into CSV data</>}
      </button>
      {isOrgAdmin && <Link className="text-xs" to={settingsTo} data-testid="change-bank-accounts" style={{alignSelf:'flex-start'}}>Add or change bank accounts</Link>}
      <p style={{fontSize:'.78rem',color:'var(--text-3)',lineHeight:1.5,margin:0}}>
        Pulled transactions are merged into the uploaded CSV data of the same account (matched by account number).
        Rows that already exist in the CSV are not counted twice.
      </p>
    </div>
  )
}
