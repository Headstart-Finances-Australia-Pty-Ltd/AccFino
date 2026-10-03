import React, { useCallback, useEffect, useRef, useState } from 'react'
import toast from 'react-hot-toast'
import { Link2, RefreshCw, ShieldCheck } from 'lucide-react'
import * as api from '../../lib/booksApi.js'

const REASONS = {
  flow_expired: 'That connection attempt expired. Please press Connect again.',
  token_failed: 'OpenFeed sign-in could not be completed. Please try again.',
  grant_not_bound: 'OpenFeed did not confirm the share. Please try again.',
  grant_mismatch: 'OpenFeed returned an unexpected result. Please try again.',
}
const POPUP_FEATURES = () => {                                       // a centred window of a sensible size for sign-in and the bank screens
  const w = 520, h = 780
  const left = Math.max(0, Math.round((window.screenX || 0) + ((window.outerWidth || 1024) - w) / 2))
  const top = Math.max(0, Math.round((window.screenY || 0) + ((window.outerHeight || 800) - h) / 2))
  return `popup=yes,width=${w},height=${h},left=${left},top=${top},resizable=yes,scrollbars=yes`
}
const when = s => (s ? new Date(s).toLocaleString('en-AU') : '—')

// "Connect my bank": the Organisation Admin never visits OpenFeed on their own - AccFino sends them there and brings them back.
export default function BankFeedCard({ isAdmin = false }) {
  const [st, setSt] = useState(null)
  const [busy, setBusy] = useState('')
  const [popupOpen, setPopupOpen] = useState(false)                  // a ref alone would not re-render the card
  const popupRef = useRef(null)
  const timerRef = useRef(null)

  const load = useCallback(() => api.obFeedStatus().then(r => setSt(r.data)).catch(() => setSt({ available: false, status: 'not_connected', accounts: [] })), [])
  useEffect(() => {
    load()
    const q = new URLSearchParams(window.location.search)           // back from OpenFeed: say what happened, then tidy the address
    const res = q.get('openfeed')
    if (res) {
      if (res === 'connected') toast.success('Your bank is connected')
      else if (res === 'declined') toast('Nothing was shared, so no bank was connected.')
      else toast.error(REASONS[q.get('reason')] || 'The bank connection could not be completed. Please try again.', { duration: 8000 })
      window.history.replaceState({}, '', window.location.pathname)
    }
  }, [load])

  // what happened in the pop-up (it reports through postMessage, or BroadcastChannel if the browser cut the opener link)
  const finish = useCallback((result, reason) => {
    clearInterval(timerRef.current); timerRef.current = null
    try { if (popupRef.current && !popupRef.current.closed) popupRef.current.close() } catch {}
    popupRef.current = null; setPopupOpen(false); setBusy('')
    if (result === 'connected') toast.success('Your bank is connected')
    else if (result === 'declined') toast('Nothing was shared, so no bank was connected.')
    else toast.error(REASONS[reason] || 'The bank connection could not be completed. Please try again.', { duration: 8000 })
    load()
  }, [load])
  useEffect(() => {
    const onMessage = ev => { if (ev?.data?.type === 'accfino-openfeed') finish(ev.data.result, ev.data.reason) }
    window.addEventListener('message', onMessage)
    let bc = null
    try { bc = new BroadcastChannel('accfino-openfeed'); bc.onmessage = onMessage } catch {}
    return () => { window.removeEventListener('message', onMessage); try { bc?.close() } catch {}; clearInterval(timerRef.current) }
  }, [finish])

  const run = async (name, fn) => { setBusy(name); try { await fn() } catch (e) { toast.error(api.errMsg(e)) } finally { setBusy(''); load() } }
  // Opens OpenFeed's sign-in and bank screens in a pop-up window; the page behind stays where it is. If the browser blocks pop-ups it falls back to the full-page flow.
  const connect = async () => {
    const popup = window.open('about:blank', 'accfino-openfeed', POPUP_FEATURES())          // opened straight from the click, or browsers block it
    try { if (popup) popup.document.write('<p style="font-family:system-ui,sans-serif;padding:32px;text-align:center">Opening OpenFeed…</p>') } catch {}
    setBusy('connect')
    try {
      const { data } = await api.obFeedConnect(window.location.pathname, popup ? window.location.origin : undefined)
      if (!popup) { window.location.assign(data.url); return }                               // blocked: ordinary redirect, comes back to this page
      popupRef.current = popup; setPopupOpen(true)
      popup.location.href = data.url
      clearInterval(timerRef.current)
      timerRef.current = setInterval(() => {                                                 // the person closed the window themselves, or it finished without a message
        if (popupRef.current && popupRef.current.closed) { clearInterval(timerRef.current); timerRef.current = null; popupRef.current = null; setPopupOpen(false); setBusy(''); load() }
      }, 700)
    } catch (e) {
      try { popup?.close() } catch {}
      setPopupOpen(false); setBusy(''); toast.error(api.errMsg(e))
    }
  }
  const focusPopup = () => { try { popupRef.current?.focus() } catch {} }
  const setAccount = (a, on) => run('acct', async () => { await api.obFeedSetAccount(a.id, on); toast.success(on ? `${a.name} is on` : `${a.name} is off in AccFino`) })
  // ONE account: switch it off in AccFino now, then open OpenFeed's screen so its permission can be withdrawn there too (only the account holder can do that part)
  const stopSharing = async a => {
    if (!window.confirm(`Stop using "${a.name}" (${a.masked || a.provider}) in AccFino?\n\nIt is switched off in AccFino immediately. OpenFeed's screen then opens so you can also untick it there and withdraw permission. Your other accounts are not affected.`)) return
    setBusy('acct')
    try { await api.obFeedSetAccount(a.id, false); await load() } catch (e) { toast.error(api.errMsg(e)); setBusy(''); return }
    setBusy(''); connect()
  }
  const sync = () => run('sync', async () => { await api.obFeedSync(); toast.success('Accounts refreshed') })
  const disconnect = () => run('disconnect', async () => {
    if (!window.confirm('Stop the live bank feed for this organisation?\n\nAccFino will forget the connection. You can also withdraw access any time from your OpenFeed dashboard.')) return
    await api.obFeedDisconnect(); toast.success('Bank feed disconnected')
  })

  if (!st) return <div className="empty-state" style={{ padding: 40 }}><p>Loading…</p></div>
  if (st.plan_allows === false) return (
    <div className="card" data-testid="feed-not-in-plan" style={{ maxWidth: 640 }}>
      <h3 style={{ marginBottom: 6 }}>Live bank feeds are not part of your plan</h3>
      <p className="text-sm text-muted" style={{ marginBottom: 0 }}>{st.plan_name ? <>The <b>{st.plan_name}</b> plan doesn't include open banking. </> : null}Statement upload still works for reconciliation. To add live bank feeds, upgrade the plan under Settings &gt; Subscription.</p>
    </div>)
  const manage = st.can_manage
  const sortedAccounts = [...st.accounts].sort((x, y) => (x.provider || '').localeCompare(y.provider || '') || (x.name || '').localeCompare(y.name || ''))
  const offCount = st.accounts.filter(a => !a.enabled).length
  const needs = st.status === 'reconnect_required' || st.status === 'revoked'

  return (
    <div className="card" data-testid="bank-feed-card" style={{ maxWidth: 640 }}>
      <h3 style={{ marginBottom: 6 }}><Link2 size={16} style={{ display: 'inline', marginRight: 6, verticalAlign: 'middle' }} />Live bank feed (Consumer Data Right)</h3>
      <p style={{ fontSize: '.82rem', color: 'var(--text-2)', marginBottom: 14 }}>
        Bring your business bank transactions straight into AccFino - no statement files. You approve the connection once, at your own bank;
        AccFino then keeps it up to date. Read-only: nothing can be paid out of your accounts.
      </p>

      {!st.available && (
        <div className="alert alert-warning text-sm" data-testid="feed-unavailable">
          Live bank feeds are not switched on for this platform yet. {isAdmin ? <>Set them up in <a href="/admin/api-keys?tab=open-banking">Admin Console &gt; API Keys &gt; Open Banking</a>.</> : 'Please contact AccFino support.'}
        </div>
      )}

      {st.available && st.status === 'not_connected' && (
        manage
          ? <>
              <button className="btn btn-primary" onClick={connect} disabled={!!busy} data-testid="connect-bank-btn">{busy === 'connect' ? 'Waiting for OpenFeed…' : 'Connect my bank'}</button>
              {busy === 'connect' && popupOpen && <button className="btn btn-ghost btn-sm" style={{ marginLeft: 8 }} onClick={focusPopup} data-testid="focus-popup">Show the window</button>}
              <ol className="text-xs text-muted" style={{ margin: '12px 0 0', paddingLeft: 18, display: 'grid', gap: 3 }}>
                <li>You are taken to our CDR partner, <b>openfeed</b>, to confirm your email (a one-time code - there is no separate account to set up or password to remember).</li>
                <li>Choose your bank and approve sharing at the bank itself - AccFino never sees your bank login.</li>
                <li>Tick the accounts to share with AccFino and you are brought straight back here.</li>
              </ol>
              <div className="text-xs text-muted" style={{ marginTop: 8 }}><ShieldCheck size={12} style={{ verticalAlign: '-2px' }} /> If the account belongs to a company or trust, your bank may ask that you are its nominated representative for data sharing.</div>
            </>
          : <div className="text-sm text-muted">Your Organisation Admin can connect the organisation's bank accounts here.</div>
      )}

      {st.status === 'pending' && <div className="alert alert-info text-sm">A connection was started but not finished. {manage && <button className="btn btn-outline btn-xs" style={{ marginLeft: 8 }} onClick={connect} disabled={!!busy}>Continue</button>}</div>}

      {needs && (
        <div className="alert alert-warning text-sm" data-testid="feed-reconnect">
          {st.status === 'revoked' ? 'Access to your bank data was withdrawn.' : 'The bank connection has expired.'} {manage ? 'Reconnect to keep your transactions flowing.' : 'Ask your Organisation Admin to reconnect.'}
          {manage && <button className="btn btn-primary btn-xs" style={{ marginLeft: 8 }} onClick={connect} disabled={!!busy}>Reconnect</button>}
        </div>
      )}
      {st.status === 'paused' && <div className="alert alert-warning text-sm">Bank data access is paused. Please contact AccFino support.</div>}

      {(st.status === 'active' || st.status === 'paused') && (
        <>
          <div className="text-xs text-muted" style={{ marginBottom: 4 }}>Connected · last updated {when(st.last_sync)} · banks refresh about every 4 hours</div>
          <div className="text-sm fw-600" style={{ marginBottom: 8 }} data-testid="feed-count">
            {st.accounts.length} account{st.accounts.length === 1 ? '' : 's'} from {st.bank_count || 0} bank{(st.bank_count || 0) === 1 ? '' : 's'} shared with AccFino
            {offCount > 0 && <span className="text-muted fw-400"> · {offCount} switched off</span>}
          </div>
          <table className="data-table" style={{ fontSize: '.82rem', marginBottom: 10 }} data-testid="feed-accounts">
            <thead><tr>{manage && <th title="Use this account in AccFino (reconciliation and refreshes)">Use</th>}<th>Account</th><th>Bank</th><th>Number</th>{manage && <th />}</tr></thead>
            <tbody>{sortedAccounts.map(a => (
              <tr key={a.id} style={a.enabled ? undefined : { opacity: .55 }} data-testid={`feed-row-${a.id}`}>
                {manage && <td><input type="checkbox" checked={a.enabled} disabled={!!busy} onChange={e => setAccount(a, e.target.checked)} aria-label={`Use ${a.name} in AccFino`} /></td>}
                <td>{a.name}{!a.enabled && <span className="badge badge-neutral" style={{ marginLeft: 6 }}>off</span>}</td><td>{a.provider || '—'}</td><td className="mono">{a.masked || '—'}</td>
                {manage && <td style={{ textAlign: 'right' }}><button className="btn btn-ghost btn-xs" disabled={!!busy} onClick={() => stopSharing(a)} data-testid={`stop-${a.id}`}>Stop sharing…</button></td>}
              </tr>))}
              {!st.accounts.length && <tr><td colSpan={manage ? 5 : 3} className="text-muted text-center">No accounts shared yet</td></tr>}</tbody>
          </table>
          <div className="text-xs text-muted" style={{ marginBottom: 10 }} data-testid="feed-help">
            Tick or untick <b>Use</b> to include an account in AccFino or not - it takes effect straight away and the other accounts are not affected.
            To share accounts from <b>another bank</b>, connect that bank at OpenFeed first (app.openfeed.au), then press <b>Add or remove accounts</b> and tick them. To withdraw OpenFeed's permission for one account, untick it on that screen.
          </div>
          {manage && <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
            <button className="btn btn-primary btn-sm" onClick={connect} disabled={!!busy} data-testid="add-remove-accounts">Add or remove accounts</button>
            <button className="btn btn-outline btn-sm" onClick={sync} disabled={!!busy}><RefreshCw size={13} /> Refresh now</button>
            <button className="btn btn-ghost btn-sm" onClick={disconnect} disabled={!!busy} data-testid="disconnect-all">Disconnect all</button>
          </div>}
        </>
      )}
      {st.error && st.status !== 'active' && <div className="text-xs text-muted" style={{ marginTop: 8 }}>{st.error}</div>}
    </div>
  )
}
