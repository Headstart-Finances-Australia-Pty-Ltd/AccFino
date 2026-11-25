import React, { useState, useEffect } from 'react'
import { obStatus, obCreateUser, obAccounts, obTransactions, obFetchNormalise } from '../../lib/api.js'
import { Landmark, RefreshCw } from 'lucide-react'
import toast from 'react-hot-toast'

export default function OpenBankingInput({ onTransactions }) {
  const [status,   setStatus]   = useState(null)
  const [userId,   setUserId]   = useState('')
  const [userForm, setUserForm] = useState({email:'',mobile:'',first_name:'',last_name:''})
  const [bankName, setBankName] = useState('OpenBanking')
  const [accounts, setAccounts] = useState(null)
  const [busy,     setBusy]     = useState(false)
  const [selAcc,   setSelAcc]   = useState('')

  useEffect(() => {
    obStatus().then(r=>setStatus(r.data)).catch(()=>setStatus({available:false,configured:false}))
  }, [])

  const createUser = async () => {
    setBusy(true)
    try {
      const { data } = await obCreateUser(userForm)
      const id = data?.id || data?.data?.id || ''
      if (id) { setUserId(id); toast.success(`Basiq user created: ${id}`) }
      else     { toast.error('User created but no ID returned') }
    } catch (e) { toast.error(e.response?.data?.detail||'Failed to create user') }
    finally { setBusy(false) }
  }

  const fetchAccounts = async () => {
    if (!userId) { toast.error('Enter a Basiq user ID'); return }
    setBusy(true)
    try {
      const { data } = await obAccounts(userId)
      const list = data?.data || data || []
      setAccounts(Array.isArray(list) ? list : [])
      toast.success(`${list.length} accounts loaded`)
    } catch (e) { toast.error(e.response?.data?.detail||'Failed to fetch accounts') }
    finally { setBusy(false) }
  }

  const pullAndNormalise = async () => {
    if (!userId) { toast.error('Enter a Basiq user ID'); return }
    setBusy(true)
    try {
      const { data } = await obFetchNormalise({
        user_id:    userId,
        account_id: selAcc,
        bank_name:  bankName,
      })
      toast.success(`${data.count} transactions fetched and normalised`)
      onTransactions(data.rows || [])
    } catch (e) { toast.error(e.response?.data?.detail||'Fetch failed') }
    finally { setBusy(false) }
  }

  return (
    <div>
      {/* Status */}
      {status && (
        <div className={`alert ${status.configured?'alert-success':status.available?'alert-warning':'alert-error'}`} style={{marginBottom:20}}>
          {status.configured
            ? '✅ Basiq Open Banking API configured and ready.'
            : status.available
              ? '⚠️ Basiq module loaded but BASIQ_API_KEY not set. Add it to HSLedger/main_app/.env'
              : '❌ Open Banking not available — check backend installation.'}
        </div>
      )}

      {!status?.configured && (
        <div className="card card-flat" style={{background:'var(--surface-2)',marginBottom:20}}>
          <h4 style={{marginBottom:10}}>Setup</h4>
          <div style={{fontSize:'.875rem',color:'var(--text-2)',lineHeight:1.8}}>
            <div>1. Register at <strong>basiq.io</strong> and get your API key</div>
            <div>2. Add to <code style={{background:'var(--surface)',padding:'1px 6px',borderRadius:4,fontFamily:'var(--font-mono)',fontSize:'.8rem'}}>main_app/.env</code>:</div>
            <div style={{background:'var(--surface)',border:'1px solid var(--border)',borderRadius:'var(--r-md)',padding:'10px 14px',marginTop:6,fontFamily:'var(--font-mono)',fontSize:'.8rem',lineHeight:1.9}}>
              BASIQ_BASE_URL=https://au-api.basiq.io<br/>
              BASIQ_API_KEY=your_key_here<br/>
              BASIQ_VERSION=3.0
            </div>
            <div style={{marginTop:6}}>3. Restart the Accfino API server</div>
          </div>
        </div>
      )}

      <div style={{display:'grid',gridTemplateColumns:'1fr 1fr',gap:20}}>
        {/* Create user */}
        <div className="card">
          <h3 style={{marginBottom:14,display:'flex',alignItems:'center',gap:8}}><Landmark size={17} color="var(--brand)"/>Create Basiq User</h3>
          <div style={{display:'flex',flexDirection:'column',gap:10}}>
            <div className="grid-2" style={{gap:10}}>
              <div className="input-group"><label>First Name</label><input className="input" value={userForm.first_name} onChange={e=>setUserForm(f=>({...f,first_name:e.target.value}))}/></div>
              <div className="input-group"><label>Last Name</label><input className="input" value={userForm.last_name} onChange={e=>setUserForm(f=>({...f,last_name:e.target.value}))}/></div>
            </div>
            <div className="input-group"><label>Email</label><input className="input" type="email" value={userForm.email} onChange={e=>setUserForm(f=>({...f,email:e.target.value}))}/></div>
            <div className="input-group"><label>Mobile</label><input className="input" type="tel" value={userForm.mobile} onChange={e=>setUserForm(f=>({...f,mobile:e.target.value}))} placeholder="+61 4xx xxx xxx"/></div>
            <button className="btn btn-outline btn-sm" onClick={createUser} disabled={busy||!status?.configured}>
              {busy?<span className="spinner spinner-sm"/>:'Create User'}
            </button>
          </div>
        </div>

        {/* Pull transactions */}
        <div className="card">
          <h3 style={{marginBottom:14,display:'flex',alignItems:'center',gap:8}}><RefreshCw size={17} color="var(--brand)"/>Pull Transactions</h3>
          <div style={{display:'flex',flexDirection:'column',gap:10}}>
            <div className="input-group">
              <label>Basiq User ID</label>
              <input className="input" value={userId} onChange={e=>setUserId(e.target.value)} placeholder="xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx"/>
            </div>
            <div className="input-group">
              <label>Bank Name (label)</label>
              <input className="input" value={bankName} onChange={e=>setBankName(e.target.value)} placeholder="e.g. ANZ, CBA…"/>
            </div>
            {accounts && accounts.length>0 && (
              <div className="input-group">
                <label>Filter by Account (optional)</label>
                <select className="input" value={selAcc} onChange={e=>setSelAcc(e.target.value)}>
                  <option value="">All accounts</option>
                  {accounts.map((a,i)=><option key={i} value={a.id||a.accountId}>{a.name||a.accountNo||a.id}</option>)}
                </select>
              </div>
            )}
            <div style={{display:'flex',gap:8}}>
              <button className="btn btn-outline btn-sm" onClick={fetchAccounts} disabled={busy||!userId||!status?.configured}>View Accounts</button>
              <button className="btn btn-primary btn-sm" onClick={pullAndNormalise} disabled={busy||!userId||!status?.configured}>
                {busy?<><span className="spinner spinner-sm"/>Fetching…</>:'⚡ Fetch & Add to Agent Run'}
              </button>
            </div>
            <p style={{fontSize:'.78rem',color:'var(--text-3)',lineHeight:1.5}}>
              Transactions are normalised to CSV format and added to the CSV input tab ready for Agent Run.
            </p>
          </div>
        </div>
      </div>
    </div>
  )
}
