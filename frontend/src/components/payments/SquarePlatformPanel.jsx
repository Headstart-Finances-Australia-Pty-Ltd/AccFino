import React, { useCallback, useEffect, useState } from 'react'
import toast from 'react-hot-toast'
import { CreditCard } from 'lucide-react'
import * as api from '../../lib/booksApi.js'
import { fmtAUD, fmtDate } from '../books/Common.jsx'

// Admin Console > API Keys > Payment Card Setup > Square: the PLATFORM's Square account, used to charge organisations their subscription automatically.
// (Settings > Payment Setup is a different thing: an organisation's own account for taking payments from ITS customers.)
export default function SquarePlatformPanel() {
  const [st, setSt] = useState(null)
  const [form, setForm] = useState({ application_id: '', location_id: '', access_token: '', environment: 'sandbox' })
  const [busy, setBusy] = useState('')
  const [test, setTest] = useState(null)
  const [ov, setOv] = useState(null)

  const load = useCallback(async () => {
    try {
      const { data } = await api.adminSquareStatus(); setSt(data)
      setForm(f => ({ ...f, application_id: data.application_id || '', location_id: data.location_id || '', environment: data.environment || 'sandbox' }))
      if (data.configured) api.adminBillingOverview().then(r => setOv(r.data)).catch(() => {})
    } catch { setSt(null) }
  }, [])
  useEffect(() => { load() }, [load])
  if (!st) return null

  const act = async (name, fn) => { setBusy(name); try { await fn() } catch (e) { toast.error(api.errMsg(e)) } finally { setBusy(''); load() } }
  const save = () => act('save', async () => { await api.adminSaveSquare(form); setForm(f => ({ ...f, access_token: '' })); setTest(null); toast.success('Square settings saved') })
  const runTest = () => act('test', async () => { const { data } = await api.adminTestSquare(); setTest(data) })
  const runBilling = () => act('run', async () => { const { data } = await api.adminRunBilling(); toast.success(data.skipped ? `Not run: ${data.skipped}` : `Billing run: ${data.paid || 0} paid, ${data.failed || 0} failed`) })
  const set = k => e => setForm(f => ({ ...f, [k]: e.target.value }))

  return (
    <div data-testid="square-platform" style={{ maxWidth: 760 }}>
      <div className="card" style={{ marginBottom: 16 }}>
        <h3 style={{ marginBottom: 6 }}><CreditCard size={16} style={{ display: 'inline', marginRight: 6, verticalAlign: 'middle' }} />Square - subscription payments
          <span className={`badge ${st.configured ? 'badge-success' : 'badge-warning'}`} style={{ marginLeft: 8 }}>{st.configured ? `Ready (${st.environment})` : 'Not set up'}</span></h3>
        <p style={{ fontSize: '.8rem', color: 'var(--text-2)', marginBottom: 12 }}>
          AccFino's own Square account. Organisations add a card in Settings and are charged their plan automatically every month or year; the money goes to this account.
          Cards are entered into Square's secure form, so AccFino never sees card numbers.
        </p>
        <ol className="text-xs text-muted" style={{ margin: '0 0 12px', paddingLeft: 18, display: 'grid', gap: 3 }}>
          <li>In the Square Developer Dashboard create an application and copy its <b>Application ID</b> and an <b>Access token</b> (Sandbox first, then Production).</li>
          <li>Copy your <b>Location ID</b> (an Australian location - AccFino bills in AUD).</li>
          <li>Paste them below, <b>Save</b>, then <b>Test connection</b>.</li>
        </ol>
        <div style={{ display: 'grid', gap: 10 }}>
          <input className="input" placeholder="Application ID" value={form.application_id} onChange={set('application_id')} aria-label="Square application id" />
          <input className="input" placeholder="Location ID" value={form.location_id} onChange={set('location_id')} aria-label="Square location id" />
          {st.locked_by_environment
            ? <div className="alert alert-info text-sm" data-testid="square-env-locked">The access token is set by the server environment (<code>SQUARE_ACCESS_TOKEN</code>).</div>
            : <input className="input" type="password" autoComplete="off" data-testid="square-token-input" aria-label="Square access token" value={form.access_token} onChange={set('access_token')}
                     placeholder={st.has_token ? 'Access token saved - leave blank to keep it' : 'Access token'} />}
          <select className="input" value={form.environment} onChange={set('environment')} aria-label="Square environment">
            <option value="sandbox">Sandbox (testing - no real money)</option><option value="production">Production (real payments)</option>
          </select>
        </div>
        {form.environment === 'sandbox' && <div className="text-xs text-muted" style={{ marginTop: 8 }}>Sandbox test card (from Square's documentation): 4111 1111 1111 1111, any future expiry, CVV 111, postcode 94103. Use sandbox Application ID, token and Location ID together.</div>}
        <div style={{ display: 'flex', gap: 8, marginTop: 12 }}>
          <button className="btn btn-primary btn-sm" onClick={save} disabled={!!busy} data-testid="square-save">{busy === 'save' ? 'Saving…' : 'Save'}</button>
          <button className="btn btn-outline btn-sm" onClick={runTest} disabled={!!busy || !st.configured} data-testid="square-test">{busy === 'test' ? 'Testing…' : 'Test connection'}</button>
        </div>
        {test && <div className={`alert ${test.ok ? 'alert-success' : 'alert-error'} text-sm`} style={{ marginTop: 10 }} data-testid="square-test-result">{test.message}</div>}
      </div>

      {st.configured && (
        <div className="card" data-testid="billing-overview">
          <div style={{ display: 'flex', alignItems: 'center', marginBottom: 8 }}>
            <h3 style={{ margin: 0 }}>Automatic billing</h3>
            <button className="btn btn-outline btn-sm" style={{ marginLeft: 'auto' }} onClick={runBilling} disabled={!!busy} data-testid="square-run">Run billing now</button>
          </div>
          <p className="text-xs text-muted" style={{ marginBottom: 8 }}>Renewals run automatically (checked every 30 minutes). A declined card is retried after 3 and 6 days, and the organisation is emailed each time.</p>
          <table className="data-table" style={{ fontSize: '.8rem' }}>
            <thead><tr><th>Organisation</th><th>Plan</th><th>Card</th><th>Next charge</th><th>Status</th></tr></thead>
            <tbody>
              {(ov?.organisations || []).map(o => (
                <tr key={o.org_id}><td>{o.org_name}</td><td>{o.plan_id} · {o.billing_period}</td><td>{o.card || '—'}</td>
                  <td>{o.auto_renew ? fmtDate(o.next_charge_on) : 'Auto-renew off'}</td>
                  <td>{o.failure_count > 0 ? <span className="badge badge-danger" title={o.last_error || ''}>Failed ×{o.failure_count}</span> : <span className="badge badge-success">{o.status}</span>}</td></tr>))}
              {!(ov?.organisations || []).length && <tr><td colSpan={5} className="text-muted text-center">No organisation has added a card yet</td></tr>}
            </tbody>
          </table>
          {(ov?.recent || []).length > 0 && <div className="text-xs text-muted" style={{ marginTop: 10 }}>Recent: {(ov.recent).slice(0, 5).map(c => `${fmtAUD(c.amount)} ${c.status}`).join(' · ')}</div>}
        </div>
      )}
    </div>
  )
}
