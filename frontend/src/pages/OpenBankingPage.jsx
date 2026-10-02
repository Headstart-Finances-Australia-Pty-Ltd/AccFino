import React, { useState, useEffect } from 'react'
import { Link } from 'react-router-dom'
import { obStatus, obCreateUser, obAccounts, obTransactions, obSavedAccounts, obSaveAccounts, getBanks } from '../lib/api.js'
import BankFeedCard from '../components/openbanking/BankFeedCard.jsx'
import { useAuth } from '../hooks/useAuth.jsx'
import { Landmark, RefreshCw, Users, CreditCard, Link2 } from 'lucide-react'
import toast from 'react-hot-toast'
import { useModuleVisibility } from '../hooks/useModuleVisibility.jsx'

const fmtAUD = n => n==null?'—':new Intl.NumberFormat('en-AU',{style:'currency',currency:'AUD'}).format(n)

// Settings > Open Banking - two providers, each its own tab. Basiq is the
// original CDR integration; openfeed is an additional live bank-feed option.
// Square used to live here too, but it's a card-payment/API integration
// rather than a bank feed, so its setup moved to Settings > Payment Setup
// (see SquarePanel in components/payments/). Every provider can be switched
// off platform-wide from Admin > Modules Management (basiq-open-banking / openfeed-open-banking).
function OpenfeedPanel() {
  const { user } = useAuth()
  const isAdmin = !!(user?.is_admin || (user?.roles || []).includes('admin'))
  return <BankFeedCard isAdmin={isAdmin} />
}

export default function OpenBankingPage() {
  const { isModuleVisible } = useModuleVisibility()
  const { user } = useAuth()
  const isAdmin = !!(user?.is_admin || (user?.roles || []).includes('admin'))
  const PROVIDERS = [
    { key:'basiq',    label:'Basiq',    moduleId:'basiq-open-banking' },
    { key:'openfeed', label:'OpenFeed', moduleId:'openfeed-open-banking' },
  ].filter(p => isModuleVisible(p.moduleId))
  const [provider, setProvider] = useState('basiq')
  useEffect(() => { if (!PROVIDERS.find(p=>p.key===provider) && PROVIDERS[0]) setProvider(PROVIDERS[0].key) }, [PROVIDERS.map(p=>p.key).join(',')])

  const [status,   setStatus]   = useState(null)
  const [userId,   setUserId]   = useState('')
  const [userForm, setUserForm] = useState({email:'',mobile:'',first_name:'',last_name:''})
  const [accounts, setAccounts] = useState(null)
  const [txns,     setTxns]     = useState(null)
  const [busy,     setBusy]     = useState(false)
  const [tab,      setTab]      = useState('accounts')
  // Accounts ticked here are the only Basiq accounts Reconciliation can pull from.
  const [banks,    setBanks]    = useState([])
  const [saved,    setSaved]    = useState({})   // account_id -> {user_id, account_id, bank, name, number}
  useEffect(() => {
    getBanks().then(r => setBanks(Array.isArray(r.data) ? r.data : [])).catch(() => {})
    obSavedAccounts().then(r => setSaved(Object.fromEntries((r.data?.accounts||[]).map(a => [a.account_id, a])))).catch(() => {})
  }, [])
  const accId = a => a.id || a.accountId
  const toggleSaved = acc => setSaved(m => {
    const id = accId(acc), n = { ...m }
    if (n[id]) delete n[id]
    else n[id] = { user_id:userId, account_id:id, bank:'', name:acc.name||'', number:String(acc.accountNo||'') }
    return n
  })
  const setSavedBank = (id, bank) => setSaved(m => ({ ...m, [id]: { ...m[id], bank } }))
  const saveForRecon = async () => {
    const list = Object.values(saved)
    if (list.some(a => !a.bank)) { toast.error('Choose a bank for each account you tick'); return }
    try { await obSaveAccounts(list); toast.success(`${list.length} account${list.length!==1?'s':''} available in Reconciliation`) }
    catch (e) { toast.error(e.response?.data?.detail || 'Could not save') }
  }

  useEffect(() => {
    obStatus().then(r=>setStatus(r.data)).catch(()=>setStatus({available:false,configured:false}))
  }, [])

  const createUser = async () => {
    setBusy(true)
    try {
      const { data } = await obCreateUser(userForm)
      const id = data?.id || data?.data?.id
      if (id) { setUserId(id); toast.success(`User created: ${id}`) }
    } catch (e) { toast.error(e.response?.data?.detail||'Failed to create user') }
    finally { setBusy(false) }
  }

  const fetchAccounts = async () => {
    if (!userId) { toast.error('Enter a Basiq User ID'); return }
    setBusy(true)
    try {
      const { data } = await obAccounts(userId)
      setAccounts(data?.data || data || [])
      toast.success('Accounts loaded')
    } catch (e) { toast.error(e.response?.data?.detail||'Failed to fetch accounts') }
    finally { setBusy(false) }
  }

  const fetchTxns = async () => {
    if (!userId) { toast.error('Enter a Basiq User ID'); return }
    setBusy(true)
    try {
      const { data } = await obTransactions(userId)
      setTxns(data?.data || data || [])
      toast.success('Transactions loaded')
    } catch (e) { toast.error(e.response?.data?.detail||'Failed to fetch transactions') }
    finally { setBusy(false) }
  }

  return (
    <div className="fade-in">
      <div style={{marginBottom:16}}>
        <div className="flex items-center gap-1">
          <Landmark size={22} />
          <h2 style={{margin:0}}>Open Banking</h2>
        </div>
        <p className="text-sm text-muted" style={{margin:'4px 0 0'}}>Connect bank accounts via Basiq or openfeed for real-time transaction data</p>
      </div>

      {PROVIDERS.length > 1 && (
        <div className="tabs-bar" style={{marginBottom:20}}>
          {PROVIDERS.map(p => (
            <button key={p.key} className={`tab-btn${provider===p.key?' active':''}`} onClick={()=>setProvider(p.key)}>{p.label}</button>
          ))}
        </div>
      )}

      {provider === 'openfeed' && <OpenfeedPanel />}

      {provider === 'basiq' && <>
      {/* Platform not set up yet: clients get a plain message; only the AccFino administrator is pointed to the set-up screen */}
      {status && !status.configured && (
        <div className="alert alert-warning" style={{marginBottom:20}} data-testid="basiq-unavailable">
          Basiq bank feeds are not switched on for this platform yet. {isAdmin
            ? <>Set them up in <Link to="/admin/api-keys?tab=open-banking">Admin Console &gt; API Keys &gt; Open Banking</Link>.</>
            : 'Please contact AccFino support.'}
        </div>
      )}

      {Object.keys(saved).length > 0 && (
        <div className="card card-sm" style={{marginBottom:16}}>
          <div style={{fontSize:'.8rem',fontWeight:700,marginBottom:8}}>Available in Reconciliation ({Object.keys(saved).length})</div>
          <div style={{display:'flex',flexDirection:'column',gap:6}}>
            {Object.values(saved).map(a => (
              <div key={a.account_id} style={{display:'flex',alignItems:'center',gap:8,fontSize:'.82rem'}}>
                <span style={{flex:1}}>{[a.bank, a.name, a.number && `···${String(a.number).slice(-4)}`].filter(Boolean).join(' · ') || a.account_id}</span>
                <button className="btn btn-ghost btn-xs" onClick={async()=>{
                  const next = Object.values(saved).filter(x => x.account_id !== a.account_id)
                  try { await obSaveAccounts(next); setSaved(Object.fromEntries(next.map(x=>[x.account_id,x]))); toast.success('Removed') }
                  catch (e) { toast.error(e.response?.data?.detail || 'Could not remove') }
                }}>Remove</button>
              </div>
            ))}
          </div>
        </div>
      )}

      <div style={{display:'grid',gridTemplateColumns:'320px 1fr',gap:20,alignItems:'start'}}>
        {/* Left: controls */}
        <div style={{display:'flex',flexDirection:'column',gap:14}}>
          {/* Create user */}
          <div className="card">
            <div style={{display:'flex',alignItems:'center',gap:8,marginBottom:14}}>
              <Users size={17} color="var(--brand)"/><h3>Create Basiq User</h3>
            </div>
            {['first_name','last_name','email','mobile'].map(k=>(
              <div key={k} className="input-group" style={{marginBottom:10}}>
                <label>{k.replace('_',' ').replace(/\b\w/g,c=>c.toUpperCase())}</label>
                <input className="input" value={userForm[k]} onChange={e=>setUserForm(f=>({...f,[k]:e.target.value}))} placeholder={k==='mobile'?'+61 4xx xxx xxx':k==='email'?'user@example.com':''}/>
              </div>
            ))}
            <button className="btn btn-primary btn-full" onClick={createUser} disabled={busy||!status?.configured}>
              {busy?<span className="spinner spinner-sm"/>:'Create User'}
            </button>
          </div>

          {/* Load existing */}
          <div className="card">
            <div style={{display:'flex',alignItems:'center',gap:8,marginBottom:14}}>
              <CreditCard size={17} color="var(--brand)"/><h3>Load User Data</h3>
            </div>
            <div className="input-group" style={{marginBottom:10}}>
              <label>Basiq User ID</label>
              <input className="input" value={userId} onChange={e=>setUserId(e.target.value)} placeholder="xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx"/>
            </div>
            <div style={{display:'flex',gap:8}}>
              <button className="btn btn-outline btn-sm" onClick={fetchAccounts} disabled={busy||!userId||!status?.configured}>Accounts</button>
              <button className="btn btn-outline btn-sm" onClick={fetchTxns}     disabled={busy||!userId||!status?.configured}>Transactions</button>
            </div>
          </div>
        </div>

        {/* Right: results */}
        <div>
          {(accounts||txns) && (
            <>
              <div className="tabs-bar" style={{marginBottom:0}}>
                {[['accounts',`Accounts (${Array.isArray(accounts)?accounts.length:0})`],['txns',`Transactions (${Array.isArray(txns)?txns.length:0})`]].map(([k,label])=>(
                  <button key={k} className={`tab-btn${tab===k?' active':''}`} onClick={()=>setTab(k)}>{label}</button>
                ))}
              </div>
              <div style={{background:'var(--surface)',border:'1px solid var(--border)',borderTop:'none',borderRadius:'0 0 var(--r-lg) var(--r-lg)',overflow:'hidden'}}>
                {tab==='accounts' && (
                  Array.isArray(accounts)&&accounts.length>0
                    ? <div style={{padding:16,display:'flex',flexDirection:'column',gap:12}}>
                        {accounts.map((acc,i)=>(
                          <div key={i} className="card card-sm card-flat">
                            <div style={{display:'flex',alignItems:'center',gap:10,flexWrap:'wrap',marginBottom:10,paddingBottom:10,borderBottom:'1px solid var(--border)'}}>
                              <label style={{display:'flex',alignItems:'center',gap:6,fontSize:'.8rem',fontWeight:600,cursor:'pointer'}}>
                                <input type="checkbox" checked={!!saved[accId(acc)]} onChange={()=>toggleSaved(acc)}/> Use in Reconciliation
                              </label>
                              {saved[accId(acc)] && (
                                <select className="input input-sm" style={{maxWidth:200}} value={saved[accId(acc)].bank} onChange={e=>setSavedBank(accId(acc), e.target.value)}>
                                  <option value="">Select bank…</option>
                                  {banks.map(b=><option key={b} value={b}>{b}</option>)}
                                </select>
                              )}
                            </div>
                            <div style={{display:'flex',gap:20,flexWrap:'wrap'}}>
                              <div><div style={{fontSize:'.7rem',fontWeight:700,color:'var(--text-3)',textTransform:'uppercase',letterSpacing:'.05em'}}>Account</div><div style={{fontWeight:600}}>{acc.name||acc.accountNo||'—'}</div></div>
                              <div><div style={{fontSize:'.7rem',fontWeight:700,color:'var(--text-3)',textTransform:'uppercase',letterSpacing:'.05em'}}>Balance</div><div style={{fontWeight:700,fontFamily:'var(--font-mono)',color:'var(--brand)'}}>{fmtAUD(acc.balance)}</div></div>
                              <div><div style={{fontSize:'.7rem',fontWeight:700,color:'var(--text-3)',textTransform:'uppercase',letterSpacing:'.05em'}}>Type</div><div style={{fontSize:'.8rem'}}>{acc.accountType||acc.type||'—'}</div></div>
                              <div><div style={{fontSize:'.7rem',fontWeight:700,color:'var(--text-3)',textTransform:'uppercase',letterSpacing:'.05em'}}>Institution</div><div style={{fontSize:'.8rem'}}>{acc.institution||acc.bank||'—'}</div></div>
                            </div>
                          </div>
                        ))}
                        <button className="btn btn-primary btn-sm" style={{alignSelf:'flex-start'}} onClick={saveForRecon}>Save accounts for Reconciliation</button>
                      </div>
                    : <div className="empty-state" style={{padding:40}}><p>No account data</p></div>
                )}
                {tab==='txns' && (
                  Array.isArray(txns)&&txns.length>0
                    ? <div style={{overflowX:'auto'}}>
                        <table className="data-table">
                          <thead><tr><th>Date</th><th>Description</th><th style={{textAlign:'right'}}>Amount</th><th>Direction</th><th>Status</th></tr></thead>
                          <tbody>
                            {txns.slice(0,200).map((t,i)=>(
                              <tr key={i}>
                                <td className="mono" style={{fontSize:'.78rem'}}>{t.postDate||t.date||''}</td>
                                <td style={{fontSize:'.8rem',maxWidth:280,overflow:'hidden',textOverflow:'ellipsis',whiteSpace:'nowrap'}}>{t.description||t.narration||''}</td>
                                <td className="mono" style={{textAlign:'right',fontSize:'.78rem',fontWeight:600,color:t.direction==='credit'||parseFloat(t.amount||0)>0?'var(--info)':'var(--warning)'}}>
                                  {fmtAUD(Math.abs(parseFloat(t.amount||0)))}
                                </td>
                                <td><span className={`badge ${t.direction==='credit'?'badge-info':'badge-warning'}`}>{t.direction||'—'}</span></td>
                                <td style={{fontSize:'.75rem',color:'var(--text-3)'}}>{t.status||''}</td>
                              </tr>
                            ))}
                          </tbody>
                        </table>
                        {txns.length>200&&<div style={{padding:'10px 16px',fontSize:'.78rem',color:'var(--text-3)'}}>Showing 200 of {txns.length} transactions</div>}
                      </div>
                    : <div className="empty-state" style={{padding:40}}><p>No transaction data</p></div>
                )}
              </div>
            </>
          )}

          {!accounts && !txns && (
            <div className="card">
              <div className="empty-state">
                <div className="empty-icon">🏛️</div>
                <h3>Open Banking via Basiq CDR API</h3>
                <p>Create a Basiq user and connect their bank accounts to fetch real-time transactions without manual CSV uploads.</p>
                <div style={{marginTop:16,display:'flex',gap:8,flexWrap:'wrap',justifyContent:'center'}}>
                  {['ANZ','NAB','CBA','Westpac','Macquarie','ING','Bendigo','BOQ'].map(b=>
                    <span key={b} className="badge badge-neutral">{b}</span>
                  )}
                </div>
              </div>
            </div>
          )}
        </div>
      </div>
      </>}
    </div>
  )
}
