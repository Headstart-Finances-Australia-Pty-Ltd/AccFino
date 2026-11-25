import React, { useState, useEffect } from 'react'
import { obStatus, obCreateUser, obAccounts, obTransactions } from '../lib/api.js'
import { Landmark, RefreshCw, Users, CreditCard } from 'lucide-react'
import toast from 'react-hot-toast'

const fmtAUD = n => n==null?'—':new Intl.NumberFormat('en-AU',{style:'currency',currency:'AUD'}).format(n)

export default function OpenBankingPage() {
  const [status,   setStatus]   = useState(null)
  const [userId,   setUserId]   = useState('')
  const [userForm, setUserForm] = useState({email:'',mobile:'',first_name:'',last_name:''})
  const [accounts, setAccounts] = useState(null)
  const [txns,     setTxns]     = useState(null)
  const [busy,     setBusy]     = useState(false)
  const [tab,      setTab]      = useState('accounts')

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
      <div style={{marginBottom:22}}>
        <h1>🏛️ Open Banking</h1>
        <p style={{color:'var(--text-3)',marginTop:4,fontSize:'.9rem'}}>Connect to your bank accounts via the Basiq CDR API for real-time transaction data</p>
      </div>

      {/* Status banner */}
      {status && (
        <div className={`alert ${status.configured?'alert-success':status.available?'alert-warning':'alert-error'}`} style={{marginBottom:20}}>
          {status.configured
            ? '✅ Basiq API configured and ready.'
            : status.available
              ? '⚠️ Module available but BASIQ_API_KEY not configured. Set it in your .env file.'
              : '❌ Open Banking module not available. Check your installation.'}
        </div>
      )}

      {!status?.configured && (
        <div className="card" style={{marginBottom:20}}>
          <h3 style={{marginBottom:12}}>Setup Instructions</h3>
          <div style={{fontSize:'.875rem',color:'var(--text-2)',lineHeight:1.8}}>
            <div>1. Register at <strong>basiq.io</strong> and get your API key</div>
            <div>2. Add to your <code style={{background:'var(--surface-2)',padding:'1px 6px',borderRadius:4,fontFamily:'var(--font-mono)',fontSize:'.8rem'}}>HSLedger/main_app/.env</code> file:</div>
            <div style={{background:'var(--surface-2)',border:'1px solid var(--border)',borderRadius:'var(--r-md)',padding:'12px 16px',marginTop:8,fontFamily:'var(--font-mono)',fontSize:'.8rem',lineHeight:1.9}}>
              BASIQ_BASE_URL=https://au-api.basiq.io<br/>
              BASIQ_API_KEY=your_api_key_here<br/>
              BASIQ_VERSION=3.0
            </div>
            <div style={{marginTop:8}}>3. Restart the Accfino API server</div>
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
                            <div style={{display:'flex',gap:20,flexWrap:'wrap'}}>
                              <div><div style={{fontSize:'.7rem',fontWeight:700,color:'var(--text-3)',textTransform:'uppercase',letterSpacing:'.05em'}}>Account</div><div style={{fontWeight:600}}>{acc.name||acc.accountNo||'—'}</div></div>
                              <div><div style={{fontSize:'.7rem',fontWeight:700,color:'var(--text-3)',textTransform:'uppercase',letterSpacing:'.05em'}}>Balance</div><div style={{fontWeight:700,fontFamily:'var(--font-mono)',color:'var(--brand)'}}>{fmtAUD(acc.balance)}</div></div>
                              <div><div style={{fontSize:'.7rem',fontWeight:700,color:'var(--text-3)',textTransform:'uppercase',letterSpacing:'.05em'}}>Type</div><div style={{fontSize:'.8rem'}}>{acc.accountType||acc.type||'—'}</div></div>
                              <div><div style={{fontSize:'.7rem',fontWeight:700,color:'var(--text-3)',textTransform:'uppercase',letterSpacing:'.05em'}}>Institution</div><div style={{fontSize:'.8rem'}}>{acc.institution||acc.bank||'—'}</div></div>
                            </div>
                          </div>
                        ))}
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
    </div>
  )
}
