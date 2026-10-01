import React, { useEffect, useState } from 'react'
import toast from 'react-hot-toast'
import { Ban, CheckCircle2, LogOut, RotateCcw, KeyRound, Home, Info } from 'lucide-react'
import * as api from '../../lib/platformApi.js'

// Settings > Identity: organisation owners/admins manage the people in THEIR organisation.
const when = s => s ? new Date(s).toLocaleString('en-AU') : '—'
const METHOD = { passkey: 'Face/fingerprint', totp: 'Authenticator', sms: 'SMS', email: 'Email' }

function Detail({ id, onClose, onChanged }) {
  const [d, setD] = useState(null)
  const load = () => api.orgMember(id).then(r => setD(r.data)).catch(e => toast.error(api.errMsg(e)))
  useEffect(() => { load() }, [id])
  const act = async (action, body, confirmText, done) => {
    if (confirmText && !window.confirm(confirmText)) return
    try { await api.orgMemberAction(id, action, body); toast.success(done); load(); onChanged() } catch (e) { toast.error(api.errMsg(e)) }
  }
  const suspend = () => {
    const reason = window.prompt(`Suspend ${d.email}'s access to this organisation?\nThey keep their AccFino account and their other organisations.\n\nReason (recorded in the audit log):`, '')
    if (reason !== null) act('suspend', { reason }, null, 'Access suspended')
  }
  if (!d) return null
  return (
    <div className="modal-overlay" onClick={onClose}>
      <div className="modal" onClick={e => e.stopPropagation()} style={{ maxWidth: 820, width: '95%', maxHeight: '90vh', overflow: 'auto' }}>
        <div className="modal-header"><h3 style={{ margin: 0 }}>{d.name} <span className="text-sm text-muted">{d.email}</span></h3>
          <button className="btn btn-ghost btn-xs" onClick={onClose}>✕</button></div>
        <div style={{ padding: 18, display: 'grid', gap: 14 }}>
          <div className="text-sm">Role: <b>{d.role}</b> · {d.home_member ? <><Home size={12} /> Home organisation</> : 'Member from another organisation'} ·
            Two-step verification: {d.mfa_methods.length ? d.mfa_methods.map(m => METHOD[m] || m).join(', ') : <span className="badge badge-warning">Off</span>} ·
            Last sign-in: {when(d.last_login_at)}</div>
          {d.suspended_at && <div className="alert alert-error">Access suspended {when(d.suspended_at)}{d.suspended_reason ? ` - ${d.suspended_reason}` : ''}</div>}

          <div className="flex gap-1" style={{ flexWrap: 'wrap' }}>
            {d.suspended_at
              ? <button className="btn btn-primary btn-sm" onClick={() => act('restore', {}, null, 'Access restored')}><CheckCircle2 size={13} /> Restore access</button>
              : <button className="btn btn-danger btn-sm" onClick={suspend}><Ban size={13} /> Suspend access</button>}
            {d.home_member && <>
              <button className="btn btn-outline btn-sm" onClick={() => act('sign-out', {}, 'Sign this person out of every device?', 'Signed out everywhere')}><LogOut size={13} /> Sign out everywhere</button>
              <button className="btn btn-outline btn-sm" disabled={!d.mfa_methods.length} onClick={() => act('reset-mfa', {}, 'Remove all of this person\'s verification methods (e.g. lost phone)? They will set them up again after signing in.', 'Verification methods reset')}><RotateCcw size={13} /> Reset MFA</button>
              <button className="btn btn-outline btn-sm" onClick={() => act('require-password-change', { required: !d.must_change_password }, null, d.must_change_password ? 'Requirement removed' : 'Must change password at next sign-in')}>
                <KeyRound size={13} /> {d.must_change_password ? 'Cancel password change' : 'Require password change'}</button>
            </>}
          </div>
          {!d.home_member && <div className="alert alert-info text-sm"><Info size={13} /> This person's home organisation is a different one. You can suspend their access here or
            change/remove them under Organisation → Members. Account-wide actions (reset MFA, sign-out, password) belong to their own administrator.</div>}

          {d.sessions && <div><b>Devices</b>
            <div className="data-table-wrap"><table className="data-table">
              <thead><tr><th>Device</th><th>IP</th><th>Signed in</th><th>Last active</th><th>Status</th></tr></thead>
              <tbody>{d.sessions.map(s => <tr key={s.id}><td>{s.device}</td><td className="mono text-sm">{s.ip}</td>
                <td className="text-sm">{when(s.created_at)}</td><td className="text-sm">{when(s.last_seen_at)}</td>
                <td>{s.active ? <span className="badge badge-success">active</span> : <span className="badge badge-neutral">{s.revoked_reason || 'expired'}</span>}</td></tr>)}</tbody>
            </table></div></div>}
          {d.sign_ins && <div><b>Recent sign-in activity</b>
            <div className="data-table-wrap" style={{ maxHeight: 220, overflow: 'auto' }}><table className="data-table">
              <tbody>{d.sign_ins.map((a, i) => <tr key={i}><td className="text-sm">{when(a.at)}</td><td className="text-sm">{a.action.replace('auth.', '').replace(/_/g, ' ')}</td><td className="mono text-sm">{a.ip}</td></tr>)}</tbody>
            </table></div></div>}
        </div>
      </div>
    </div>)
}

export default function OrgIdentityPage() {
  const [rows, setRows] = useState(null)
  const [open, setOpen] = useState(null)
  const [err, setErr] = useState('')
  const load = () => api.orgMembers().then(r => setRows(r.data)).catch(e => setErr(api.errMsg(e)))
  useEffect(() => { load() }, [])
  if (err) return <div style={{ padding: 24 }}><div className="alert alert-warning">{err}</div></div>
  if (!rows) return <div style={{ padding: 24 }}><div className="spinner" /></div>
  const noMfa = rows.filter(r => !r.mfa_methods.length).length
  return (
    <div style={{ padding: 24, display: 'grid', gap: 14 }}>
      <p className="text-sm text-muted" style={{ margin: 0 }}>People in this organisation, their sign-in security and access.
        {noMfa > 0 && <> <b>{noMfa}</b> without two-step verification - you can require it under Organisation → Access policy.</>}</p>
      <div className="data-table-wrap"><table className="data-table">
        <thead><tr><th>Person</th><th>Email</th><th>Role</th><th>Status</th><th>Two-step verification</th><th>Last sign-in</th><th></th></tr></thead>
        <tbody>{rows.map(r => (
          <tr key={r.user_id}>
            <td>{r.name} {r.is_you && <span className="badge badge-brand">you</span>} {r.home_member && !r.is_you && <span className="badge badge-neutral" title="Home organisation"><Home size={10} /></span>}</td>
            <td className="text-sm">{r.email}</td><td>{r.role}</td>
            <td>{r.suspended ? <span className="badge badge-danger">Suspended</span> : <span className="badge badge-success">Active</span>}
              {r.must_change_password && <span className="badge badge-info" style={{ marginLeft: 4 }}>Must change password</span>}</td>
            <td className="text-sm">{r.mfa_methods.length ? r.mfa_methods.map(m => METHOD[m] || m).join(', ') : <span className="badge badge-warning">Off</span>}</td>
            <td className="text-sm">{when(r.last_login_at)}</td>
            <td className="text-right">{!r.is_you && !r.platform_admin && <button className="btn btn-ghost btn-xs" onClick={() => setOpen(r.user_id)}>Manage</button>}
              {r.is_you && <a className="btn btn-ghost btn-xs" href="/my-account?tab=security">My security</a>}</td>
          </tr>))}</tbody></table></div>
      {open && <Detail id={open} onClose={() => setOpen(null)} onChanged={load} />}
    </div>)
}
