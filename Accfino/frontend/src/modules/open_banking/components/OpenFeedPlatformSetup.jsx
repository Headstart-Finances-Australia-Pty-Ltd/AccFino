import React, { useState, useEffect } from 'react'
import toast from 'react-hot-toast'
import { openfeedStatus, openfeedSaveConfig, openfeedGenerateKeys, openfeedTest, openfeedPublicKey } from '../lib/api.js'

// OpenFeed PLATFORM setup - shown only in Admin Console > Open Banking. Organisations never see this: they just press "Connect my bank" (BankFeedCard).
export default function OpenFeedPlatformSetup() {
  const [st, setSt] = useState(null)
  const [busy, setBusy] = useState('')
  const [jwks, setJwks] = useState(null)
  const [form, setForm] = useState({ client_id:'', app_id:'' })
  const [result, setResult] = useState(null)
  const [fp, setFp] = useState(null)

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
  const showKey = () => act('show', async () => { const { data } = await openfeedPublicKey(); setJwks(JSON.stringify(data.jwks, null, 2)); setFp({ kid: data.kid, fingerprint: data.fingerprint }) })
  const runTest = () => act('test', async () => { const { data } = await openfeedTest(); setResult(data) })
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
          {st.needsRegenerate && <div className="alert alert-warning text-xs" data-testid="openfeed-regenerate" style={{marginBottom:8}}>These keys were made by an older version and have no key id, so OpenFeed cannot match them. Generate new keys, then paste the new public key set into the OpenFeed dashboard.</div>}
          <div style={{display:'flex',gap:8,flexWrap:'wrap'}}>
            <button className="btn btn-outline btn-sm" onClick={genKeys} disabled={!!busy}>{st.hasKeys?'Replace keys':'Generate keys'}</button>
            {st.hasKeys && !st.needsRegenerate && <button className="btn btn-outline btn-sm" onClick={showKey} disabled={!!busy} data-testid="openfeed-show-key">Show public key set</button>}
          </div>
          {st.kid && <div className="text-xs text-muted" style={{marginTop:6}} data-testid="openfeed-kid">Key id AccFino signs with: <code>{st.kid}</code>{fp?.fingerprint && <> · fingerprint <code>{fp.fingerprint}</code></>}. The key set registered at OpenFeed must have this same key id.</div>}
          {jwks && <div style={{marginTop:8}}>
            <div className="text-xs text-muted">Paste this <b>public</b> key set into the openfeed dashboard (the private keys never leave the server):</div>
            <textarea className="input" readOnly rows={8} value={jwks} style={{width:'100%',fontFamily:'monospace',fontSize:'.7rem'}} onFocus={e=>e.target.select()} data-testid="jwks-box"/>
          </div>}
        </>
      ))}
      {step(2, st.hasIds, 'Register the app at app.openfeed.au/registered-apps/new, then paste the two IDs it shows', (
        <div style={{display:'flex',flexDirection:'column',gap:8}}>
          <div className="text-xs text-muted" style={{display:'grid',gap:3}} data-testid="openfeed-register-values">
            <div>Auth method: <code>private_key_jwt</code> · public key source: <b>Paste JWKS JSON</b> - paste the key set from step 1, then Save changes</div>
            <div>Requested scopes - tick only <b>Banking accounts and transactions</b> (<code>{(st.dashboardScopes||['openfeed-au:data:banking:read'])[0]}</code>). Leave Energy unticked. <code>openid</code> and <code>offline_access</code> are not boxes: AccFino asks for them automatically.</div>
            <div>Redirect URI: nothing to register - AccFino sends <code style={{userSelect:'all'}}>{st.redirectUri}</code> with each sign-in{(st.redirectUri||'').startsWith('http://') && !(st.redirectUri||'').includes('localhost') ? ' (plain http: fine for testing, use https on your live site - set APP_URL)' : ''}.</div>
          </div>
          <input className="input input-sm" placeholder="OAuth2 Client ID (starts with app-)" value={form.client_id} onChange={e=>setForm(f=>({...f,client_id:e.target.value}))}/>
          <input className="input input-sm" placeholder="App ID (plain UUID)" value={form.app_id} onChange={e=>setForm(f=>({...f,app_id:e.target.value}))}/>
          <button className="btn btn-outline btn-sm" onClick={saveIds} disabled={!!busy} style={{alignSelf:'flex-start'}}>Save app details</button>
        </div>
      ))}
      {step(3, !!result?.ok, 'Test the set-up', (
        <>
          <button className="btn btn-outline btn-sm" onClick={runTest} disabled={!!busy || !st.ready} data-testid="openfeed-test-btn">{busy==='test'?'Testing…':'Test OpenFeed set-up'}</button>
          {result && <div className={`alert ${result.ok?'alert-success':'alert-error'} text-xs`} style={{marginTop:8}} data-testid="openfeed-test-result">
            {result.message}
            {result.client_id && <div className="text-xs" style={{marginTop:4,opacity:.85}} data-testid="openfeed-tested-as">Tested as Client ID <code>{result.client_id}</code>{result.kid ? <> · key id <code>{result.kid}</code></> : null} - compare it with the Client ID shown for your app in the OpenFeed dashboard.</div>}
            {(result.variant_check||[]).length > 0 && <div style={{marginTop:6}} data-testid="openfeed-variant-check">{result.variant_check.map(x => <div key={x.key}>{x.ok === true ? '✓' : x.ok === false ? '✗' : '?'} {x.label}</div>)}</div>}
            {(result.redirect_check||[]).length > 1 && <div style={{marginTop:6}} data-testid="openfeed-redirect-check">{result.redirect_check.map(x => <div key={x.redirect_uri}>{x.ok === true ? '✓' : x.ok === false ? '✗' : '?'} banking scope with redirect <code>{x.redirect_uri}</code></div>)}</div>}
            {(result.scope_check||[]).length > 0 && <ul style={{margin:'6px 0 0',paddingLeft:0,listStyle:'none',display:'grid',gap:2}} data-testid="openfeed-scope-check">{result.scope_check.map(x => (
              <li key={x.scope}>{x.ok === true ? '✓' : x.ok === false ? '✗' : '?'} <code>{x.scope}</code> {x.ok === false ? '- not enabled for this app at OpenFeed: tick it' : x.ok === null ? '- could not be checked yet' : '- enabled'}</li>))}</ul>}
            {(result.hints||[]).length > 0 && <ul style={{margin:'6px 0 0',paddingLeft:18,display:'grid',gap:3}} data-testid="openfeed-test-hints">{result.hints.map((h,i)=><li key={i}>{h}</li>)}</ul>}
          </div>}
        </>
      ))}
      <div className="text-xs text-muted">Cost: openfeed charges AccFino about 10 cents per connected organisation per month (introductory rate) - not the organisation.</div>
    </div>
  )
}
