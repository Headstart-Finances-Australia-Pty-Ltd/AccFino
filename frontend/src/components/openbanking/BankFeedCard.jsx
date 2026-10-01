import React, { useCallback, useEffect, useState } from 'react'
import toast from 'react-hot-toast'
import { Link2, RefreshCw, ShieldCheck } from 'lucide-react'
import * as api from '../../lib/booksApi.js'

const REASONS = {
  flow_expired: 'That connection attempt expired. Please press Connect again.',
  token_failed: 'OpenFeed sign-in could not be completed. Please try again.',
  grant_not_bound: 'OpenFeed did not confirm the share. Please try again.',
  grant_mismatch: 'OpenFeed returned an unexpected result. Please try again.',
}
const when = s => (s ? new Date(s).toLocaleString('en-AU') : '—')

// "Connect my bank": the Organisation Admin never visits OpenFeed on their own - AccFino sends them there and brings them back.
export default function BankFeedCard({ isAdmin = false }) {
  const [st, setSt] = useState(null)
  const [busy, setBusy] = useState('')

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

  const run = async (name, fn) => { setBusy(name); try { await fn() } catch (e) { toast.error(api.errMsg(e)) } finally { setBusy(''); load() } }
  const connect = () => run('connect', async () => {
    const { data } = await api.obFeedConnect(window.location.pathname)
    window.location.assign(data.url)
  })
  const sync = () => run('sync', async () => { await api.obFeedSync(); toast.success('Accounts refreshed') })
  const disconnect = () => run('disconnect', async () => {
    if (!window.confirm('Stop the live bank feed for this organisation?\n\nAccFino will forget the connection. You can also withdraw access any time from your OpenFeed dashboard.')) return
    await api.obFeedDisconnect(); toast.success('Bank feed disconnected')
  })

  if (!st) return <div className="empty-state" style={{ padding: 40 }}><p>Loading…</p></div>
  const manage = st.can_manage
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
          Live bank feeds are not switched on for this platform yet. {isAdmin ? <>Set them up in <a href="/admin/open-banking">Admin Console &gt; Open Banking</a>.</> : 'Please contact AccFino support.'}
        </div>
      )}

      {st.available && st.status === 'not_connected' && (
        manage
          ? <>
              <button className="btn btn-primary" onClick={connect} disabled={!!busy} data-testid="connect-bank-btn">{busy === 'connect' ? 'Opening…' : 'Connect my bank'}</button>
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
          <div className="text-xs text-muted" style={{ marginBottom: 8 }}>Connected · last updated {when(st.last_sync)} · banks refresh about every 4 hours</div>
          <table className="data-table" style={{ fontSize: '.82rem', marginBottom: 12 }}>
            <thead><tr><th>Account</th><th>Bank</th><th>Number</th></tr></thead>
            <tbody>{st.accounts.map(a => <tr key={a.id}><td>{a.name}</td><td>{a.provider || '—'}</td><td className="mono">{a.masked || '—'}</td></tr>)}
              {!st.accounts.length && <tr><td colSpan={3} className="text-muted text-center">No accounts shared yet</td></tr>}</tbody>
          </table>
          {manage && <div style={{ display: 'flex', gap: 8 }}>
            <button className="btn btn-outline btn-sm" onClick={sync} disabled={!!busy}><RefreshCw size={13} /> Refresh now</button>
            <button className="btn btn-ghost btn-sm" onClick={connect} disabled={!!busy}>Change shared accounts</button>
            <button className="btn btn-ghost btn-sm" onClick={disconnect} disabled={!!busy}>Disconnect</button>
          </div>}
        </>
      )}
      {st.error && st.status !== 'active' && <div className="text-xs text-muted" style={{ marginTop: 8 }}>{st.error}</div>}
    </div>
  )
}
