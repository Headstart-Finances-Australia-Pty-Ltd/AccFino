import React, { useEffect, useState } from 'react'
import toast from 'react-hot-toast'
import { UserCog, Search, Ban, CheckCircle2, LogOut, KeyRound, Unlock, RotateCcw } from 'lucide-react'
import * as api from '../../lib/platformApi.js'

// Platform administrators: user accounts, status, MFA, devices and sign-in history (Entra "Users" blade).
const when = s => s ? new Date(s).toLocaleString('en-AU') : '—'
const METHOD = { passkey: 'Face/fingerprint', totp: 'Authenticator', sms: 'SMS', email: 'Email' }

function StatusBadges({ u }) {
  return (<>
    {u.disabled || u.disabled_at ? <span className="badge badge-danger">Disabled</span> : <span className="badge badge-success">Active</span>}
    {(u.locked || u.locked_until) && <span className="badge badge-warning" style={{ marginLeft: 4 }}>Locked</span>}
    {u.must_change_password && <span className="badge badge-info" style={{ marginLeft: 4 }}>Must change password</span>}
  </>)
}

function UserDetail({ id, onClose, onChanged }) {
  const [d, setD] = useState(null)
  const load = () => api.adminUser(id).then(r => setD(r.data)).catch(e => toast.error(api.errMsg(e)))
  useEffect(() => { load() }, [id])
  const act = async (action, body, confirmText, done) => {
    if (confirmText && !window.confirm(confirmText)) return
    try { await api.adminAction(id, action, body); toast.success(done); load(); onChanged() } catch (e) { toast.error(api.errMsg(e)) }
  }
  const disable = () => {
    const reason = window.prompt(`Disable ${d.email}? They will be signed out everywhere and can't sign in.\n\nReason (recorded in the audit log):`, '')
    if (reason === null) return
    act('disable', { reason }, null, 'Account disabled')
  }
  const endSession = async s => { try { await api.adminRevokeSession(id, s.id); toast.success('Session ended'); load() } catch (e) { toast.error(api.errMsg(e)) } }
  if (!d) return null
  return (
    <div className="modal-overlay" onClick={onClose}>
      <div className="modal" onClick={e => e.stopPropagation()} style={{ maxWidth: 900, width: '95%', maxHeight: '90vh', overflow: 'auto' }}>
        <div className="modal-header"><h3 style={{ margin: 0 }}>{d.name || d.username} <span className="text-sm text-muted">{d.email}</span></h3>
          <button className="btn btn-ghost btn-xs" onClick={onClose}>✕</button></div>
        <div style={{ padding: 18, display: 'grid', gap: 14 }}>
          <div className="flex items-center gap-1" style={{ flexWrap: 'wrap' }}>
            <StatusBadges u={d} />
            <span className="text-sm text-muted" style={{ marginLeft: 8 }}>Roles: {d.roles.join(', ') || 'user'} · Last sign-in: {when(d.last_login_at)}</span>
          </div>
          {d.disabled_at && <div className="alert alert-error">Disabled {when(d.disabled_at)}{d.disabled_reason ? ` - ${d.disabled_reason}` : ''}</div>}
          <div className="flex gap-1" style={{ flexWrap: 'wrap' }}>
            {d.disabled_at
              ? <button className="btn btn-primary btn-sm" onClick={() => act('enable', {}, null, 'Account enabled')}><CheckCircle2 size={13} /> Enable account</button>
              : <button className="btn btn-danger btn-sm" onClick={disable}><Ban size={13} /> Disable account</button>}
            <button className="btn btn-outline btn-sm" onClick={() => act('sign-out', {}, 'Sign this user out of every device?', 'Signed out everywhere')}><LogOut size={13} /> Sign out everywhere</button>
            <button className="btn btn-outline btn-sm" disabled={!d.mfa_methods.length} onClick={() => act('reset-mfa', {}, 'Remove ALL of this user\'s verification methods and recovery codes (e.g. lost phone)? They will need to set them up again.', 'Verification methods reset')}><RotateCcw size={13} /> Reset MFA</button>
            {d.locked_until && <button className="btn btn-outline btn-sm" onClick={() => act('unlock', {}, null, 'Account unlocked')}><Unlock size={13} /> Unlock</button>}
            <button className="btn btn-outline btn-sm" onClick={() => act('require-password-change', { required: !d.must_change_password }, null, d.must_change_password ? 'Requirement removed' : 'User must change password at next sign-in')}>
              <KeyRound size={13} /> {d.must_change_password ? 'Cancel password change' : 'Require password change'}</button>
          </div>

          <div className="grid-2" style={{ gap: 14 }}>
            <div className="card card-sm"><b>Verification methods</b>
              <p className="text-sm" style={{ marginBottom: 0 }}>{d.mfa_methods.length ? d.mfa_methods.map(m => METHOD[m] || m).join(', ') : <span className="text-muted">None - two-step verification is off</span>}
                <br /><span className="text-xs text-muted">{d.recovery_codes_remaining} recovery code(s) left</span></p></div>
            <div className="card card-sm"><b>Organisations</b>
              <p className="text-sm" style={{ marginBottom: 0 }}>{d.organisations.map(o => `${o.name} (${o.role})`).join(', ') || '—'}</p></div>
          </div>

          <div><b>Devices</b>
            <div className="data-table-wrap"><table className="data-table">
              <thead><tr><th>Device</th><th>IP</th><th>Methods</th><th>Signed in</th><th>Last active</th><th>Status</th><th></th></tr></thead>
              <tbody>{d.sessions.map(s => (
                <tr key={s.id}><td>{s.device}</td><td className="mono text-sm">{s.ip}</td><td className="text-sm">{(s.methods || []).join(' + ')}</td>
                  <td className="text-sm">{when(s.created_at)}</td><td className="text-sm">{when(s.last_seen_at)}</td>
                  <td>{s.active ? <span className="badge badge-success">active</span> : <span className="badge badge-neutral">{s.revoked_reason || 'expired'}</span>}</td>
                  <td>{s.active && <button className="btn btn-ghost btn-xs" onClick={() => endSession(s)}>End</button>}</td></tr>))}
                {!d.sessions.length && <tr><td colSpan={7} className="text-muted text-center">No sessions</td></tr>}</tbody></table></div></div>

          <div><b>Recent sign-in activity</b>
            <div className="data-table-wrap" style={{ maxHeight: 260, overflow: 'auto' }}><table className="data-table">
              <thead><tr><th>When</th><th>Event</th><th>IP</th></tr></thead>
              <tbody>{d.sign_ins.map((a, i) => <tr key={i}><td className="text-sm">{when(a.at)}</td>
                <td className="text-sm">{a.action.replace('auth.', '').replace(/_/g, ' ')}</td><td className="mono text-sm">{a.ip}</td></tr>)}</tbody></table></div></div>
        </div>
      </div>
    </div>)
}

export default function IdentityPage() {
  const [q, setQ] = useState('')
  const [status, setStatus] = useState('')
  const [data, setData] = useState({ total: 0, items: [] })
  const [open, setOpen] = useState(null)
  const load = () => api.adminUsers({ q: q || undefined, status: status || undefined, limit: 100 })
    .then(r => setData(r.data)).catch(e => toast.error(api.errMsg(e)))
  useEffect(() => { const t = setTimeout(load, 250); return () => clearTimeout(t) }, [q, status])

  return (
    <div className="fade-in">
      <div className="flex items-center gap-1" style={{ marginBottom: 14 }}><UserCog size={22} /><h2 style={{ margin: 0 }}>Platform Users</h2></div>
      <div className="flex items-center gap-4" style={{ flexWrap: 'wrap', marginBottom: 12 }}>
        <div className="flex items-center gap-1"><Search size={14} />
          <input className="input input-sm" style={{ width: 260 }} placeholder="Search name, username or email" value={q} onChange={e => setQ(e.target.value)} data-testid="identity-search" /></div>
        <select className="input input-sm" style={{ width: 160 }} value={status} onChange={e => setStatus(e.target.value)} data-testid="identity-status-filter">
          {[['', 'All'], ['active', 'Active'], ['disabled', 'Disabled'], ['locked', 'Locked'], ['no_mfa', 'No MFA']].map(([k, l]) =>
            <option key={k} value={k}>{l}</option>)}
        </select>
        <span className="text-sm text-muted">{data.total} user(s)</span>
      </div>
      <div className="data-table-wrap"><table className="data-table">
        <thead><tr><th>User</th><th>Email</th><th>Status</th><th>Verification</th><th>Last sign-in</th><th></th></tr></thead>
        <tbody>{data.items.map(u => (
          <tr key={u.id}><td>{u.name || u.username} {u.is_admin && <span className="badge badge-brand">admin</span>}</td>
            <td className="text-sm">{u.email}</td><td><StatusBadges u={u} /></td>
            <td className="text-sm">{u.mfa_methods.length ? u.mfa_methods.map(m => METHOD[m] || m).join(', ') : <span className="badge badge-warning">Off</span>}</td>
            <td className="text-sm">{when(u.last_login_at)}</td>
            <td className="text-right"><button className="btn btn-ghost btn-xs" onClick={() => setOpen(u.id)}>Manage</button></td></tr>))}
          {!data.items.length && <tr><td colSpan={6} className="text-muted text-center">No users</td></tr>}</tbody></table></div>
      {open && <UserDetail id={open} onClose={() => setOpen(null)} onChanged={load} />}
    </div>)
}
