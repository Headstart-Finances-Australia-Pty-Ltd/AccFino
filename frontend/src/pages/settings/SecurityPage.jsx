import React, { useEffect, useState } from 'react'
import toast from 'react-hot-toast'
import { ShieldCheck, KeyRound, LogOut, History, AlertTriangle, CheckCircle2, ScanFace, Smartphone, Mail, LifeBuoy, Trash2, Monitor, Lock } from 'lucide-react'
import { addPasskey, passkeyError, passkeysSupported, suggestDeviceName } from '../../lib/passkeys.js'
import * as api from '../../lib/platformApi.js'
import { useAuth } from '../../hooks/useAuth.jsx'

const when = s => s ? new Date(s).toLocaleString('en-AU') : ''

function MfaCard({ enabled, onChange }) {
  const [setup, setSetup] = useState(null)
  const [code, setCode] = useState('')
  const [codes, setCodes] = useState(null)
  const [dis, setDis] = useState({ password: '', code: '' })

  const start = async () => { try { const { data } = await api.mfaSetup(); setSetup(data) } catch (e) { toast.error(api.errMsg(e)) } }
  const enable = async () => {
    try { const { data } = await api.mfaEnable(code); setCodes(data.recovery_codes); setSetup(null); setCode(''); toast.success('Authenticator app added'); onChange() }
    catch (e) { toast.error(api.errMsg(e)) }
  }
  const disable = async () => {
    try { await api.mfaDisable(dis); setDis({ password: '', code: '' }); toast.success('Authenticator app removed'); onChange() }
    catch (e) { toast.error(api.errMsg(e)) }
  }
  return (
    <div className="card">
      <h3 style={{ marginTop: 0 }}><KeyRound size={16} /> Authenticator app passcode</h3>
      <p className="text-sm">Status: {enabled ? <span className="badge badge-success">On</span> : <span className="badge badge-warning">Off</span>}</p>
      {!enabled && !setup && <>
        <p className="text-sm text-muted">Protect your account with a 6-digit code from an authenticator app (Google Authenticator, Microsoft Authenticator, 1Password, Authy).
          The ATO requires this for software that lodges on your behalf.</p>
        <button className="btn btn-primary btn-sm" onClick={start}>Set up authenticator app</button></>}
      {setup && (
        <div className="flex gap-4" style={{ flexWrap: 'wrap', alignItems: 'flex-start' }}>
          {setup.qr_png && <img src={setup.qr_png} alt="Scan this QR code" style={{ width: 180, height: 180, border: '1px solid var(--border)', borderRadius: 8 }} />}
          <div style={{ maxWidth: 360 }}>
            <p className="text-sm">1. Scan the QR code with your authenticator app, or enter this key manually:</p>
            <p className="mono text-sm" style={{ wordBreak: 'break-all', background: 'var(--surface-2)', padding: 8, borderRadius: 6 }} data-testid="mfa-secret">{setup.secret}</p>
            <p className="text-sm">2. Enter the 6-digit code it shows:</p>
            <div className="flex gap-1"><input className="input input-sm" style={{ maxWidth: 140 }} inputMode="numeric" value={code} onChange={e => setCode(e.target.value)} data-testid="mfa-enable-code" />
              <button className="btn btn-primary btn-sm" disabled={code.length < 6} onClick={enable}>Turn on</button>
              <button className="btn btn-ghost btn-sm" onClick={() => setSetup(null)}>Cancel</button></div>
          </div>
        </div>)}
      {codes && codes.length > 0 && (
        <div className="alert alert-warning mt-4">
          <b>Save these recovery codes now.</b> Each works once if you lose your phone. They won't be shown again.
          <div className="mono" style={{ display: 'grid', gridTemplateColumns: 'repeat(2, max-content)', gap: '4px 24px', marginTop: 8 }} data-testid="recovery-codes">
            {codes.map(c => <span key={c}>{c}</span>)}</div>
          <button className="btn btn-outline btn-xs mt-1" onClick={() => { navigator.clipboard?.writeText(codes.join('\n')); toast.success('Copied') }}>Copy</button>
          <button className="btn btn-ghost btn-xs mt-1" onClick={() => setCodes(null)}>I've saved them</button>
        </div>)}
      {enabled && (
        <div className="mt-4">
          <p className="text-sm text-muted">To turn it off, confirm your password and a current code.</p>
          <div className="flex gap-1" style={{ flexWrap: 'wrap' }}>
            <input type="password" className="input input-sm" style={{ maxWidth: 200 }} placeholder="Password" value={dis.password} onChange={e => setDis({ ...dis, password: e.target.value })} />
            <input className="input input-sm" style={{ maxWidth: 140 }} placeholder="6-digit code" value={dis.code} onChange={e => setDis({ ...dis, code: e.target.value })} />
            <button className="btn btn-danger btn-sm" disabled={!dis.password || !dis.code} onClick={disable}>Turn off</button>
          </div>
        </div>)}
    </div>
  )
}


function RecoveryCodes({ codes, onClose }) {
  if (!codes || !codes.length) return null
  return (
    <div className="alert alert-warning mt-4">
      <b>Save these recovery codes now.</b> Each works once if you lose access to your other methods. They won't be shown again.
      <div className="mono" style={{ display: 'grid', gridTemplateColumns: 'repeat(2, max-content)', gap: '4px 24px', marginTop: 8 }} data-testid="recovery-codes">
        {codes.map(c => <span key={c}>{c}</span>)}</div>
      <button className="btn btn-outline btn-xs mt-1" onClick={() => { navigator.clipboard?.writeText(codes.join('\n')); toast.success('Copied') }}>Copy</button>
      <button className="btn btn-ghost btn-xs mt-1" onClick={onClose}>I've saved them</button>
    </div>)
}

const askPassword = (what) => window.prompt(`Enter your password to ${what}`) || ''

function PasskeysCard({ m, onChange, setCodes }) {
  const [busy, setBusy] = useState(false)
  const supported = passkeysSupported()
  const add = async () => {
    const name = window.prompt('Name this device', suggestDeviceName())
    if (name === null) return
    setBusy(true)
    try { const d = await addPasskey(name); setCodes(d.recovery_codes); toast.success('Face / fingerprint sign-in added'); onChange() }
    catch (e) { toast.error(passkeyError(e)) } finally { setBusy(false) }
  }
  const remove = async p => {
    const pw = askPassword(`remove "${p.name}"`); if (!pw) return
    try { await api.passkeyRemove(p.id, pw); toast.success('Passkey removed'); onChange() } catch (e) { toast.error(api.errMsg(e)) }
  }
  return (
    <div className="card">
      <h3 style={{ marginTop: 0 }}><ScanFace size={16} /> Face or fingerprint (passkeys) <span className="badge badge-success" style={{ marginLeft: 6 }}>Recommended</span></h3>
      <p className="text-sm text-muted">Sign in with Face ID, Touch ID, Windows Hello or your Android phone's face or fingerprint unlock - no code to type, and it can't be phished.
        Your face and fingerprint never leave your device; AccFino only stores a public key.</p>
      {m.passkeys.length > 0 && (
        <div className="data-table-wrap"><table className="data-table">
          <thead><tr><th>Device</th><th>Added</th><th>Last used</th><th></th></tr></thead>
          <tbody>{m.passkeys.map(p => (
            <tr key={p.id}><td>{p.name} {p.synced && <span className="badge badge-info" title="Synced via iCloud Keychain / Google Password Manager">synced</span>}</td>
              <td className="text-sm">{when(p.created_at)}</td><td className="text-sm">{when(p.last_used_at) || '—'}</td>
              <td className="text-right"><button className="btn btn-ghost btn-xs" onClick={() => remove(p)}><Trash2 size={12} /> Remove</button></td></tr>))}
          </tbody></table></div>)}
      {supported ? <button className="btn btn-primary btn-sm mt-4" disabled={busy} onClick={add} data-testid="add-passkey">
        <ScanFace size={14} /> {busy ? 'Follow the prompt on your device…' : 'Add face / fingerprint on this device'}</button>
        : <div className="alert alert-warning mt-4">This browser doesn't support passkeys. Try the latest Chrome, Edge, Safari or Firefox.</div>}
    </div>)
}

function CodeMethodCard({ kind, m, onChange, setCodes }) {
  const isSms = kind === 'sms'
  const st = isSms ? m.sms : m.email
  const [phone, setPhone] = useState('')
  const [sent, setSent] = useState('')
  const [code, setCode] = useState('')
  const [busy, setBusy] = useState(false)
  const send = async () => {
    setBusy(true)
    try { const { data } = isSms ? await api.smsEnrol(phone) : await api.emailEnrol(); setSent(data.sent_to); toast.success(`Code sent to ${data.sent_to}`) }
    catch (e) { toast.error(api.errMsg(e)) } finally { setBusy(false) }
  }
  const confirm = async () => {
    setBusy(true)
    try { const { data } = isSms ? await api.smsConfirm(code) : await api.emailConfirm(code)
      setCodes(data.recovery_codes); setSent(''); setCode(''); setPhone(''); toast.success(isSms ? 'Text message codes turned on' : 'Email codes turned on'); onChange() }
    catch (e) { toast.error(api.errMsg(e)) } finally { setBusy(false) }
  }
  const disable = async () => {
    const pw = askPassword(`turn off ${isSms ? 'text message' : 'email'} codes`); if (!pw) return
    try { isSms ? await api.smsDisable(pw) : await api.emailDisable(pw); toast.success('Turned off'); onChange() } catch (e) { toast.error(api.errMsg(e)) }
  }
  const Icon = isSms ? Smartphone : Mail
  return (
    <div className="card">
      <h3 style={{ marginTop: 0 }}><Icon size={16} /> {isSms ? 'Code sent to your phone (SMS)' : 'Code sent by email'}</h3>
      {st.enabled ? (<>
        <p className="text-sm"><span className="badge badge-success">On</span> {isSms ? st.phone : st.address}</p>
        <button className="btn btn-outline btn-sm" onClick={disable}>Turn off</button></>) : (<>
        <p className="text-sm text-muted">{isSms ? 'Get a 6-digit code by text message when you sign in. Convenient, but less secure than face/fingerprint or an authenticator app because phone numbers can be hijacked (SIM swap).'
          : `Get a 6-digit code at ${st.address} when you sign in. Useful as a backup method.`}</p>
        {!sent ? (
          <div className="flex gap-1" style={{ flexWrap: 'wrap' }}>
            {isSms && <input className="input input-sm" style={{ maxWidth: 200 }} placeholder="0412 345 678" value={phone} onChange={e => setPhone(e.target.value)} data-testid="sms-phone" />}
            <button className="btn btn-primary btn-sm" disabled={busy || (isSms && !phone)} onClick={send}>Send verification code</button>
          </div>) : (
          <div className="flex gap-1" style={{ flexWrap: 'wrap', alignItems: 'center' }}>
            <span className="text-sm">Code sent to {sent}:</span>
            <input className="input input-sm" style={{ maxWidth: 130 }} inputMode="numeric" autoComplete="one-time-code" value={code} onChange={e => setCode(e.target.value)} />
            <button className="btn btn-primary btn-sm" disabled={busy || code.length < 6} onClick={confirm}>Confirm</button>
            <button className="btn btn-ghost btn-sm" onClick={() => setSent('')}>Back</button>
          </div>)}
      </>)}
    </div>)
}

function RecoveryCard({ m, setCodes }) {
  const regen = async () => {
    const pw = askPassword('create new recovery codes (old codes will stop working)'); if (!pw) return
    try { const { data } = await api.regenerateCodes(pw); setCodes(data.recovery_codes) } catch (e) { toast.error(api.errMsg(e)) }
  }
  if (!m.enabled_methods.length) return null
  return (
    <div className="card">
      <h3 style={{ marginTop: 0 }}><LifeBuoy size={16} /> Recovery codes</h3>
      <p className="text-sm">{m.recovery_codes_remaining} unused code(s) left. {m.recovery_codes_remaining < 3 && <b>Create new ones soon.</b>}</p>
      <button className="btn btn-outline btn-sm" onClick={regen}>Create new recovery codes</button>
    </div>)
}

function SignInMethods({ onChange }) {
  const [m, setM] = useState(null)
  const [codes, setCodes] = useState(null)
  const load = () => api.mfaMethods().then(r => setM(r.data)).catch(e => toast.error(api.errMsg(e)))
  useEffect(() => { load() }, [])
  const changed = () => { load(); onChange() }
  if (!m) return null
  return (<>
    <div className="card card-sm">
      <h3 style={{ margin: 0 }}>Sign-in methods</h3>
      <p className="text-sm text-muted" style={{ marginBottom: 0 }}>
        {m.enabled_methods.length ? `Two-step verification is ON (${m.enabled_methods.length} method${m.enabled_methods.length > 1 ? 's' : ''}). Add a second method as a backup.`
          : 'Two-step verification is OFF. Add at least one method below - the ATO requires it for software that lodges on your behalf.'}</p>
      <RecoveryCodes codes={codes} onClose={() => setCodes(null)} />
    </div>
    <PasskeysCard m={m} onChange={changed} setCodes={setCodes} />
    <MfaCard enabled={m.totp} onChange={changed} />
    <CodeMethodCard kind="sms" m={m} onChange={changed} setCodes={setCodes} />
    <CodeMethodCard kind="email" m={m} onChange={changed} setCodes={setCodes} />
    <RecoveryCard m={m} setCodes={setCodes} />
  </>)
}

const NOTICE_TEXT = {
  password_change_required: 'Your administrator requires you to choose a new password before continuing.',
  ca_mfa_required: 'Your organisation requires two-step verification. Add a method below, then sign out and sign in again.',
  ca_method_not_allowed: 'Your organisation only accepts certain verification methods. Add an allowed method below, then sign in again.',
  mfa_enrolment_required: 'Two-step verification is required. Add a method below.',
  ca_ip_blocked: 'Your organisation only allows access from approved networks.',
}

function Notice() {
  const [n] = useState(() => { try { return JSON.parse(sessionStorage.getItem('af_notice') || 'null') } catch { return null } })
  useEffect(() => { try { sessionStorage.removeItem('af_notice') } catch {} }, [])
  if (!n) return null
  return <div className="alert alert-warning" data-testid="iam-notice"><b>Action needed.</b> {n.message || NOTICE_TEXT[n.code]}</div>
}

function ChangePasswordCard({ required }) {
  const { user } = useAuth()
  const [f, setF] = useState({ old: '', next: '', again: '' })
  const [busy, setBusy] = useState(false)
  const save = async () => {
    if (f.next !== f.again) { toast.error('The new passwords do not match'); return }
    setBusy(true)
    try {
      await api.changeMyPassword({ email: user.email, old_password: f.old, new_password: f.next })
      toast.success('Password changed. Your other devices have been signed out.')
      setF({ old: '', next: '', again: '' })
      if (required) setTimeout(() => window.location.reload(), 600)
    } catch (e) { toast.error(api.errMsg(e)) } finally { setBusy(false) }
  }
  return (
    <div className="card" style={required ? { borderColor: 'var(--warning)' } : undefined}>
      <h3 style={{ marginTop: 0 }}><Lock size={16} /> Change password {required && <span className="badge badge-warning">Required</span>}</h3>
      <div className="flex gap-1" style={{ flexWrap: 'wrap' }}>
        <input type="password" className="input input-sm" style={{ maxWidth: 190 }} placeholder="Current password" value={f.old} onChange={e => setF({ ...f, old: e.target.value })} autoComplete="current-password" />
        <input type="password" className="input input-sm" style={{ maxWidth: 190 }} placeholder="New password" value={f.next} onChange={e => setF({ ...f, next: e.target.value })} autoComplete="new-password" />
        <input type="password" className="input input-sm" style={{ maxWidth: 190 }} placeholder="Repeat new password" value={f.again} onChange={e => setF({ ...f, again: e.target.value })} autoComplete="new-password" />
        <button className="btn btn-primary btn-sm" disabled={busy || !f.old || !f.next} onClick={save}>Change password</button>
      </div>
      <p className="text-xs text-muted mt-1">At least 8 characters with a letter and a number.</p>
    </div>)
}

function DevicesCard() {
  const [rows, setRows] = useState([])
  const load = () => api.mySessions().then(r => setRows(r.data)).catch(() => {})
  useEffect(() => { load() }, [])
  const end = async s => { try { await api.revokeSession(s.id); toast.success('Signed out that device'); load() } catch (e) { toast.error(api.errMsg(e)) } }
  const others = async () => { try { const { data } = await api.revokeOthers(); toast.success(`Signed out ${data.ended} other device(s)`); load() } catch (e) { toast.error(api.errMsg(e)) } }
  const M = { pwd: 'password', passkey: 'face/fingerprint', totp: 'authenticator', sms: 'SMS', email: 'email code', recovery: 'recovery code' }
  return (
    <div className="card">
      <h3 style={{ marginTop: 0 }}><Monitor size={16} /> Your devices</h3>
      <p className="text-sm text-muted">Everywhere you're signed in. If you don't recognise a device, sign it out and change your password.</p>
      <div className="data-table-wrap"><table className="data-table">
        <thead><tr><th>Device</th><th>IP address</th><th>Signed in with</th><th>Signed in</th><th>Last active</th><th></th></tr></thead>
        <tbody>{rows.map(s => (
          <tr key={s.id}><td>{s.device} {s.current && <span className="badge badge-success">This device</span>}</td>
            <td className="mono text-sm">{s.ip}</td><td className="text-sm">{(s.methods || []).map(x => M[x] || x).join(' + ')}</td>
            <td className="text-sm">{when(s.created_at)}</td><td className="text-sm">{when(s.last_seen_at)}</td>
            <td className="text-right">{!s.current && <button className="btn btn-ghost btn-xs" onClick={() => end(s)}>Sign out</button>}</td></tr>))}
        </tbody></table></div>
      {rows.length > 1 && <button className="btn btn-outline btn-sm mt-4" onClick={others}>Sign out all other devices</button>}
    </div>)
}

export default function SecurityPage() {
  const { user, logout } = useAuth()
  const [info, setInfo] = useState(null)
  const [history, setHistory] = useState([])
  const [audit, setAudit] = useState(null)
  const [status, setStatus] = useState(null)
  const isAdmin = user?.is_admin || (user?.roles || []).includes('admin')

  const load = () => {
    api.me().then(r => setInfo(r.data)).catch(e => toast.error(api.errMsg(e)))
    api.myAudit().then(r => setHistory(r.data)).catch(() => {})
    api.orgAudit({ limit: 200 }).then(r => setAudit(r.data)).catch(() => setAudit(null))
    if (isAdmin) api.securityStatus().then(r => setStatus(r.data)).catch(() => {})
  }
  useEffect(load, [])

  const everywhere = async () => {
    if (!window.confirm('Sign out of AccFino on every device, including this one?')) return
    try { await api.logoutAll(); toast.success('Signed out everywhere'); logout() } catch (e) { toast.error(api.errMsg(e)) }
  }

  return (
    <div className="fade-in" style={{ padding: 24, display: 'grid', gap: 16 }}>
      <div className="flex items-center gap-1"><ShieldCheck size={22} /><h2 style={{ margin: 0 }}>Security</h2></div>
      <Notice />
      {(user?.password_change_required || info?.password_change_required) && <ChangePasswordCard required />}
      {user?.mfa_required_to_enrol && <div className="alert alert-warning">Your organisation requires two-step verification. Set it up below to continue using AccFino.</div>}

      {status && (
        <div className="card">
          <h3 style={{ marginTop: 0 }}>Platform security checklist (admin)</h3>
          <p className="text-sm text-muted">{status.mfa_enabled_users} of {status.users} users have two-step verification.</p>
          {[['now', 'Fix now (applies on every computer, including development)'], ['go-live', 'Before go-live (production settings in Northflank - expected to show as not done on a laptop)']].map(([when, title]) => (
          <div key={when} style={{ marginTop: 10 }}>
          <div className="text-sm fw-700" style={{ marginBottom: 4 }}>{title}</div>
          {status.checks.filter(c => (c.when || 'now') === when).map(c => (
            <div key={c.check} className="flex items-center gap-1" style={{ padding: '4px 0' }}>
              {c.ok ? <CheckCircle2 size={16} color="var(--success)" /> : <AlertTriangle size={16} color="var(--warning)" />}
              <span className="text-sm"><b>{c.check}</b>{!c.ok && <span className="text-muted"> - {c.fix}</span>}</span>
            </div>))}
          </div>))}
        </div>)}

      <SignInMethods onChange={load} />

      <DevicesCard />
      {!(user?.password_change_required) && <ChangePasswordCard />}
      <div className="card">
        <h3 style={{ marginTop: 0 }}><LogOut size={16} /> Sessions</h3>
        <p className="text-sm text-muted">Sessions expire automatically after 8 hours. Changing your password signs out all other devices.</p>
        <button className="btn btn-outline btn-sm" onClick={everywhere}>Sign out of all devices</button>
      </div>

      <div className="card">
        <h3 style={{ marginTop: 0 }}><History size={16} /> Your sign-in history</h3>
        <div className="data-table-wrap"><table className="data-table">
          <thead><tr><th>When</th><th>Event</th><th>IP address</th></tr></thead>
          <tbody>{history.map(h => <tr key={h.id}><td>{when(h.at)}</td><td>{h.action.replace('auth.', '').replace(/_/g, ' ')}</td><td className="mono text-sm">{h.ip}</td></tr>)}
            {!history.length && <tr><td colSpan={3} className="text-muted text-center">No events yet</td></tr>}</tbody></table></div>
      </div>

      {audit && (
        <div className="card">
          <h3 style={{ marginTop: 0 }}>Organisation audit log</h3>
          <p className="text-sm text-muted">Every change made in this organisation. Entries can't be edited or deleted.</p>
          <div className="data-table-wrap" style={{ maxHeight: 420, overflow: 'auto' }}><table className="data-table">
            <thead><tr><th>When</th><th>User</th><th>Action</th><th>Detail</th></tr></thead>
            <tbody>{audit.items.map(a => (
              <tr key={a.id}><td className="text-sm">{when(a.at)}</td><td className="text-sm">{a.username}</td>
                <td className="text-sm">{a.action}</td>
                <td className="text-xs mono truncate" style={{ maxWidth: 380 }} title={JSON.stringify(a.detail || {})}>
                  {a.method ? `${a.method} ${a.path} → ${a.status}` : JSON.stringify(a.detail || {})}</td></tr>))}
              {!audit.items.length && <tr><td colSpan={4} className="text-muted text-center">No entries</td></tr>}</tbody></table></div>
        </div>)}
    </div>
  )
}
