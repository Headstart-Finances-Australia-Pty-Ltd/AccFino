import React, { useState, useEffect } from 'react'
import toast from 'react-hot-toast'
import { openfeedStatus, openfeedSaveConfig, openfeedGenerateKeys } from '../../lib/api.js'

// OpenFeed PLATFORM setup - shown only in Admin Console > Open Banking. Organisations never see this: they just press "Connect my bank" (BankFeedCard).
export default function OpenFeedPlatformSetup() {
  const [st, setSt] = useState(null)
  const [busy, setBusy] = useState('')
  const [jwks, setJwks] = useState(null)
  const [form, setForm] = useState({ client_id:'', app_id:'' })

  const load = () => openfeedStatus().then(r=>{ setSt(r.data); setForm({ client_id:r.data.clientId||'', app_id:r.data.appId||'' }) }).catch(()=>setSt(null))
  useEffect(() => { load() }, [])
  const act = async (name, fn) => {
    setBusy(name)
    try { await fn() } catch (e) { toast.error(e.response?.data?.detail || 'Failed') }
    finally { setBusy(''); load() }
  }
  const genKeys = () => act('keys', async () => {
    if (st?.hasKeys && !confirm('Replace the platform keys? Connected organisations keep working only after you paste the NEW public key into the OpenFeed dashboard.')) return
    const { data } = await openfeedGenerateKeys(); setJwks(JSON.stringify(data.jwks, null, 2)); toast.success('Keys generated')
  })
  const saveIds = () => act('ids', async () => { await openfeedSaveConfig(form); toast.success('App details saved') })
  if (!st) return null

  const step = (n, done, title, body) => (
    <div style={{display:'flex',gap:12,marginBottom:14}}>
      <span style={{flexShrink:0,width:22,height:22,borderRadius:'50%',display:'flex',alignItems:'center',justifyContent:'center',fontSize:'.72rem',fontWeight:700,background:done?'var(--success)':'var(--surface-3)',color:done?'#fff':'var(--text-3)'}}>{done?'✓':n}</span>
      <div style={{flex:1}}><div style={{fontWeight:600,marginBottom:4}}>{title}</div><div style={{fontSize:'.82rem',color:'var(--text-2)'}}>{body}</div></div>
    </div>
  )
  return (
    <div className="card" data-testid="openfeed-platform-setup" style={{maxWidth:640,marginBottom:16}}>
      <h3 style={{marginBottom:6}}>OpenFeed platform setup <span className="badge badge-neutral" style={{marginLeft:6}}>AccFino admin · once</span></h3>
      <p style={{fontSize:'.8rem',color:'var(--text-2)',marginBottom:14}}>
        Register AccFino as ONE app with openfeed. After this, every organisation connects its own bank with a single button - no organisation ever needs to
        create an OpenFeed account or visit its dashboard. {st.ready ? <b style={{color:'var(--success)'}}>Ready.</b> : <>Still needed: {st.missing.join(', ')}.</>}
      </p>
      {step(1, st.hasKeys, 'Create the platform keys', (
        <>
          <button className="btn btn-outline btn-sm" onClick={genKeys} disabled={!!busy}>{st.hasKeys?'Replace keys':'Generate keys'}</button>
          {jwks && <div style={{marginTop:8}}>
            <div className="text-xs text-muted">Paste this <b>public</b> key set into the openfeed dashboard (the private keys never leave the server):</div>
            <textarea className="input" readOnly rows={8} value={jwks} style={{width:'100%',fontFamily:'monospace',fontSize:'.7rem'}} onFocus={e=>e.target.select()} data-testid="jwks-box"/>
          </div>}
        </>
      ))}
      {step(2, st.hasIds, 'Register the app at app.openfeed.au/registered-apps/new, then paste the two IDs it shows', (
        <div style={{display:'flex',flexDirection:'column',gap:8}}>
          <div className="text-xs text-muted">Auth method <code>private_key_jwt</code> · scope <code>openfeed-au:data:banking:read</code> (add <code>openfeed-au:grant:self:revoke</code> so AccFino can withdraw a grant when an organisation disconnects).</div>
          <input className="input input-sm" placeholder="OAuth2 Client ID (starts with app-)" value={form.client_id} onChange={e=>setForm(f=>({...f,client_id:e.target.value}))}/>
          <input className="input input-sm" placeholder="App ID (plain UUID)" value={form.app_id} onChange={e=>setForm(f=>({...f,app_id:e.target.value}))}/>
          <button className="btn btn-outline btn-sm" onClick={saveIds} disabled={!!busy} style={{alignSelf:'flex-start'}}>Save app details</button>
        </div>
      ))}
      <div className="text-xs text-muted">Cost: openfeed charges AccFino about 10 cents per connected organisation per month (introductory rate) - not the organisation.</div>
    </div>
  )
}
