import React, { useCallback, useEffect, useState } from 'react'
import toast from 'react-hot-toast'
import * as api__0 from '../lib/feedApi.js'
import * as api__1 from '../../../core/lib/platformHttp.js'

// Basiq PLATFORM setup - shown only in Admin Console > Open Banking. The API key is write-only: it is saved encrypted and never shown again.
export default function BasiqPlatformSetup() {
  const [st, setSt] = useState(null)
  const [key, setKey] = useState('')
  const [adv, setAdv] = useState({ base_url: '', version: '' })
  const [busy, setBusy] = useState('')
  const [result, setResult] = useState(null)

  const load = useCallback(() => api__0.adminOpenBanking().then(r => { setSt(r.data.basiq); setAdv({ base_url: r.data.basiq.base_url || '', version: r.data.basiq.version || '' }) }).catch(() => setSt(null)), [])
  useEffect(() => { load() }, [load])
  if (!st) return null

  const act = async (name, fn) => { setBusy(name); try { await fn() } catch (e) { toast.error(api__1.errMsg(e)) } finally { setBusy(''); load() } }
  const save = () => act('save', async () => {
    await api__0.adminSaveBasiq({ api_key: key, base_url: adv.base_url, version: adv.version }); setKey(''); setResult(null); toast.success('Basiq settings saved')
  })
  const test = () => act('test', async () => { const { data } = await api__0.adminTestBasiq(); setResult(data) })
  const clear = () => act('clear', async () => {
    if (!window.confirm('Remove the saved Basiq API key? Basiq bank feeds stop working for every organisation until a new key is saved.')) return
    await api__0.adminSaveBasiq({ clear: true }); setResult(null); toast.success('Basiq key removed')
  })

  return (
    <div className="card" data-testid="basiq-platform-setup" style={{ maxWidth: 640, marginBottom: 16 }}>
      <h3 style={{ marginBottom: 6 }}>Basiq <span className="badge badge-neutral" style={{ marginLeft: 6 }}>AccFino admin · once</span>
        <span className={`badge ${st.configured ? 'badge-success' : 'badge-warning'}`} style={{ marginLeft: 6 }}>{st.configured ? 'Ready' : 'Not set up'}</span></h3>
      <p style={{ fontSize: '.8rem', color: 'var(--text-2)', marginBottom: 14 }}>
        One Basiq account for the whole platform. After you save the key, every organisation connects its own bank accounts from Settings &gt; Open Banking -
        they never need a Basiq account or any of the details below.
      </p>

      {st.locked_by_environment
        ? <div className="alert alert-info text-sm" data-testid="basiq-env-locked">The Basiq key is set by the server environment (<code>BASIQ_API_KEY</code>), so it is managed there, not here.</div>
        : <>
            <ol className="text-xs text-muted" style={{ margin: '0 0 12px', paddingLeft: 18, display: 'grid', gap: 3 }}>
              <li>Create an account at <b>basiq.io</b> and an application of type <b>server</b>.</li>
              <li>Copy its API key and paste it below.</li>
              <li>Press <b>Save</b>, then <b>Test connection</b>.</li>
            </ol>
            <div className="input-group" style={{ marginBottom: 10 }}>
              <label>Basiq API key {st.configured && <span className="text-xs text-muted">(saved - leave blank to keep it)</span>}</label>
              <input className="input" type="password" autoComplete="off" value={key} onChange={e => setKey(e.target.value)} placeholder={st.configured ? '••••••••••••••••' : 'Paste the API key'} data-testid="basiq-key-input" />
            </div>
            <details style={{ marginBottom: 12 }}>
              <summary className="text-xs text-muted" style={{ cursor: 'pointer' }}>Advanced (normally leave as is)</summary>
              <div style={{ display: 'grid', gap: 8, marginTop: 8 }}>
                <input className="input input-sm" value={adv.base_url} onChange={e => setAdv(a => ({ ...a, base_url: e.target.value }))} placeholder="https://au-api.basiq.io" aria-label="Basiq address" />
                <input className="input input-sm" value={adv.version} onChange={e => setAdv(a => ({ ...a, version: e.target.value }))} placeholder="3.0" aria-label="Basiq API version" />
              </div>
            </details>
            <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
              <button className="btn btn-primary btn-sm" onClick={save} disabled={!!busy} data-testid="basiq-save">{busy === 'save' ? 'Saving…' : 'Save'}</button>
              <button className="btn btn-outline btn-sm" onClick={test} disabled={!!busy || !st.configured} data-testid="basiq-test">{busy === 'test' ? 'Testing…' : 'Test connection'}</button>
              {st.configured && <button className="btn btn-ghost btn-sm" onClick={clear} disabled={!!busy}>Remove key</button>}
            </div>
          </>}
      {result && <div className={`alert ${result.ok ? 'alert-success' : 'alert-error'} text-sm`} style={{ marginTop: 10 }} data-testid="basiq-test-result">{result.message}</div>}
    </div>
  )
}
