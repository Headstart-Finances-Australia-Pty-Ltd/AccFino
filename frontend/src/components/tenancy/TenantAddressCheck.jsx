import React, { useState } from 'react'
import { Globe, CheckCircle2, XCircle } from 'lucide-react'
import * as api from '../../lib/booksApi.js'

const LABEL = { setting: '1. Setting', dns: '2. Wildcard DNS', https: '3. Wildcard certificate (HTTPS)', routing: '4. Routing to AccFino' }

// Admin Console > API Keys > Web Addresses: tells the platform owner which step of "https://<organisation>.<your domain>" is still missing.
export default function TenantAddressCheck() {
  const [res, setRes] = useState(null)
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState('')
  const run = async () => {
    setBusy(true); setErr('')
    try { const { data } = await api.adminAddressCheck(); setRes(data) }
    catch (e) { setErr(api.errMsg(e, 'The check could not run')) }
    finally { setBusy(false) }
  }
  return (
    <div data-testid="tenant-address-check" style={{ maxWidth: 760 }}>
      <div className="card" style={{ marginBottom: 16 }}>
        <h3 style={{ marginBottom: 6 }}><Globe size={16} style={{ display: 'inline', marginRight: 6, verticalAlign: 'middle' }} />Organisation web addresses</h3>
        <p style={{ fontSize: '.82rem', color: 'var(--text-2)', marginBottom: 12 }}>
          Give every organisation its own address, like <code>kutumb-accounting.yourdomain.com</code>. Four things make that work, all on the platform side. Press the button and AccFino
          checks each one with a made-up name, so it shows exactly which is still missing. Nothing is changed.
        </p>
        <ol className="text-xs text-muted" style={{ margin: '0 0 12px', paddingLeft: 18, display: 'grid', gap: 3 }}>
          <li>Set <code>TENANT_BASE_DOMAIN</code> on the server (for example <code>accfino.com</code>) and restart.</li>
          <li>Add a wildcard DNS record <code>*.accfino.com</code> pointing at your host.</li>
          <li>Add a wildcard certificate for <code>*.accfino.com</code> (on Northflank: certificate generation "Wildcard via DCV").</li>
          <li>Route the wildcard to the AccFino service and pass the Host header unchanged.</li>
        </ol>
        <button className="btn btn-primary btn-sm" onClick={run} disabled={busy} data-testid="address-check-run">{busy ? 'Checking…' : 'Check my set-up'}</button>
        {err && <div className="alert alert-error text-sm" style={{ marginTop: 10 }}>{err}</div>}
      </div>

      {res && (
        <div className="card" data-testid="address-check-result">
          {res.ok
            ? <div className="alert alert-success text-sm" style={{ marginBottom: 12 }} data-testid="address-check-ok">Everything is in place. Organisation addresses look like <b>{res.example}</b>.</div>
            : <div className="alert alert-warning text-sm" style={{ marginBottom: 12 }}>Not working yet - fix the first step below that has a cross, then check again.</div>}
          <div style={{ display: 'grid', gap: 10 }}>
            {res.steps.map(s => (
              <div key={s.key} style={{ display: 'flex', gap: 10 }} data-testid={`step-${s.key}`}>
                {s.ok ? <CheckCircle2 size={18} color="var(--success)" /> : <XCircle size={18} color="var(--danger)" />}
                <div>
                  <div style={{ fontWeight: 600 }}>{LABEL[s.key] || s.key}</div>
                  <div className="text-xs text-muted">{s.detail}</div>
                  {!s.ok && s.fix && <div className="text-xs" style={{ marginTop: 4 }} data-testid={`fix-${s.key}`}><b>What to do:</b> {s.fix}</div>}
                </div>
              </div>))}
          </div>
        </div>
      )}
    </div>
  )
}
