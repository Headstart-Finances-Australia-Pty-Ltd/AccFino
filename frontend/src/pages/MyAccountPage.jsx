import React, { useEffect, useState } from 'react'
import { useSearchParams } from 'react-router-dom'
import toast from 'react-hot-toast'
import { UserRound, Lock } from 'lucide-react'
import { useAuth } from '../hooks/useAuth.jsx'
import useOrgRole from '../hooks/useOrgRole.jsx'
import * as api from '../lib/platformApi.js'
import { emailError, phoneError, normalisePhone } from '../lib/contact.js'
import ContactVerifier from '../components/signup/ContactVerifier.jsx'
import SecurityPage from './settings/SecurityPage.jsx'

const ROLE_NAME = { owner: 'Organisation Admin', admin: 'Administrator (legacy)', accountant: 'Accountant', bookkeeper: 'Bookkeeper', payroll: 'Payroll', readonly: 'Read-only' }

/** Stores the saved profile in the browser session so the rest of the app (name in the top bar, the "complete your profile" prompt) updates at once. */
export function rememberProfile(me) {
  try {
    const u = JSON.parse(localStorage.getItem('af_user') || '{}')
    localStorage.setItem('af_user', JSON.stringify({ ...u, name: me.name, email: me.email, phone: me.phone, profile_incomplete: !me.profile_complete, missing_contact: me.missing_contact || [] }))
    window.dispatchEvent(new Event('accfino:session-updated'))
  } catch { /* storage unavailable: the server is still the source of truth */ }
}

// NB: defined at module level on purpose. A component declared inside ProfileCard would be a NEW component type on every render, so React would rebuild the
// <input> after each keystroke and the field would lose focus (only the first character could be typed).
function Field({ k, label, type = 'text', f, errs, set, ...rest }) {
  return (
    <label className="text-sm" style={{ display: 'block' }}>{label}
      <input className="input" type={type} aria-label={label} aria-invalid={errs[k] ? 'true' : undefined} value={f[k]} onChange={set(k)} {...rest} />
      {errs[k] && <span role="alert" className="text-xs" style={{ color: 'var(--danger)', display: 'block' }} data-testid={`err-${k}`}>{errs[k]}</span>}
    </label>)
}

/** My Account: PERSONAL details and sign-in security only. Everything about the organisation (details, users, access codes, licence) lives under Settings and is for the Organisation Admin. */
export function ProfileCard({ required }) {
  const [me, setMe] = useState(null)
  const [f, setF] = useState({ full_name: '', email: '', phone: '', current_password: '' })
  const [errs, setErrs] = useState({})
  const [busy, setBusy] = useState(false)
  const [proof, setProof] = useState({ email: { done: false, token: null }, phone: { done: false, token: null } })
  const onProof = ch => p => {
    setProof(x => (x[ch].done === p.done && x[ch].token === p.token ? x : { ...x, [ch]: p }))
    if (p.done) setErrs(e => (e[ch === 'email' ? 'email' : 'phone'] ? { ...e, [ch === 'email' ? 'email' : 'phone']: undefined } : e))
  }
  const load = () => api.me().then(r => { setMe(r.data); setF({ full_name: r.data.name || '', email: r.data.email || '', phone: r.data.phone_display || r.data.phone || '', current_password: '' }) }).catch(e => toast.error(api.errMsg(e)))
  useEffect(() => { load() }, [])
  if (!me) return <div className="spinner" />

  const emailSet = !emailError(me.email), phoneSet = !phoneError(me.phone)
  const emailChanged = f.email.trim().toLowerCase() !== (me.email || '').toLowerCase()
  const phoneChanged = !!normalisePhone(f.phone) && normalisePhone(f.phone) !== (me.phone || '')
  const changing = (f.email.trim().toLowerCase() !== (me.email || '').toLowerCase() && emailSet) || (f.phone.trim() !== (me.phone_display || me.phone || '') && phoneSet)
  const set = k => e => { setF({ ...f, [k]: e.target.value }); setErrs({ ...errs, [k]: undefined }) }
  const save = async () => {
    const e = {}
    if (!f.full_name.trim()) e.full_name = 'Name is required.'
    const ee = emailError(f.email); if (ee) e.email = ee
    const pe = phoneError(f.phone); if (pe) e.phone = pe
    const v = me.verification || {}
    if (!ee && emailChanged && v.email_required && !proof.email.done) e.email = 'Please verify your email address.'
    if (!pe && phoneChanged && v.phone_required && !proof.phone.done) e.phone = 'Please verify your phone number.'
    if (changing && !f.current_password) e.current_password = 'Enter your current password to change your email address or phone number.'
    setErrs(e)
    if (Object.keys(e).length) return
    setBusy(true)
    try {
      const { data } = await api.updateMyProfile({ full_name: f.full_name.trim(), email: f.email.trim(), phone: f.phone.trim(), ...(f.current_password ? { current_password: f.current_password } : {}),
        ...(proof.email.token ? { email_token: proof.email.token } : {}), ...(proof.phone.token ? { phone_token: proof.phone.token } : {}) })
      rememberProfile(data); setMe(data); setF({ full_name: data.name, email: data.email, phone: data.phone_display || data.phone, current_password: '' })
      toast.success('Profile saved')
    } catch (err) { toast.error(api.errMsg(err)) } finally { setBusy(false) }
  }
  return (
    <div className="card" data-testid="profile-card">
      <h3 style={{ marginTop: 0 }}><UserRound size={16} /> My details {required && <span className="badge badge-warning">Required</span>}</h3>
      {(me.missing_contact || []).length > 0 && (
        <div className="alert alert-warning" role="status" data-testid="profile-incomplete">
          Every account needs a valid email address and phone number. Please add your {me.missing_contact.map(k => k === 'email' ? 'email address' : 'phone number').join(' and ')} to continue.
        </div>)}
      <div style={{ display: 'grid', gap: 10, maxWidth: 440 }}>
        <Field f={f} errs={errs} set={set} k="full_name" label="Full name *" />
        <Field f={f} errs={errs} set={set} k="email" label="Email address *" type="email" autoComplete="email" />
        {(emailChanged || (me.verification || {}).email_needed) && <ContactVerifier channel="email" label="Email" value={f.email.trim().toLowerCase()} valid={!emailError(f.email)} required={(me.verification || {}).email_required}
          send={api.myContactSend} verify={api.myContactVerify} onChange={onProof('email')} />}
        {!emailChanged && me.email_verified && <div className="text-xs" style={{ color: 'var(--success, #1a7f37)' }}>✓ Email verified</div>}
        <Field f={f} errs={errs} set={set} k="phone" label="Phone number *" type="tel" autoComplete="tel" placeholder="0412 345 678 or +61 412 345 678" />
        {(phoneChanged || (me.verification || {}).phone_needed) && <ContactVerifier channel="phone" label="Phone" value={normalisePhone(f.phone) || f.phone.trim()} valid={!phoneError(f.phone)} required={(me.verification || {}).phone_required}
          send={api.myContactSend} verify={api.myContactVerify} onChange={onProof('phone')} />}
        {!phoneChanged && me.phone_verified && <div className="text-xs" style={{ color: 'var(--success, #1a7f37)' }}>✓ Phone verified</div>}
        {changing && <Field f={f} errs={errs} set={set} k="current_password" label="Current password *" type="password" autoComplete="current-password" />}
        {me.is_org_admin && <div className="text-xs text-muted">You are the Organisation Admin: your email and phone number are your organisation's primary contact details, and organisation-level notices (account, licence, billing, security) are sent to you.</div>}
        <div><button className="btn btn-primary btn-sm" disabled={busy} onClick={save}>{busy ? 'Saving…' : 'Save details'}</button></div>
      </div>
    </div>)
}

export function OrganisationAddressCard() {
  const { org } = useOrgRole()
  if (!org) return null
  return (
    <div className="card card-sm" style={{ marginBottom: 12 }} data-testid="my-org">
      <div className="text-xs text-muted">Your organisation</div>
      <b>{org.name}</b> <span className="text-xs text-muted">· your role: {ROLE_NAME[org.role] || org.role}</span>
      <div className="text-sm" style={{ marginTop: 4 }}>Sign-in address: {org.tenant_url ? <a href={org.tenant_url}><b>{org.tenant_url}</b></a> : <span className="text-muted">{org.tenant_urls_enabled ? 'not available' : 'not switched on for this installation - ask your Organisation Admin'}</span>}</div>
    </div>)
}

export default function MyAccountPage() {
  const { user } = useAuth()
  const [params] = useSearchParams()
  const [tab, setTab] = useState(params.get('tab') === 'security' ? 'security' : 'profile')
  const TABS = [{ key: 'profile', label: 'My details', icon: UserRound }, { key: 'security', label: 'Security', icon: Lock }]
  return (
    <div className="fade-in" style={{ padding: '4px 24px' }}>
      <div className="flex items-center gap-1" style={{ marginBottom: 6 }}><UserRound size={22} /><h2 style={{ margin: 0 }}>My Account</h2></div>
      <p className="text-sm text-muted" style={{ margin: '0 0 12px' }}>Your own name, email, phone number, password and sign-in security. {user?.email ? <>Signed in as <b>{user.email}</b>.</> : null}</p>
      <div className="tabs-bar" style={{ marginBottom: 16 }}>
        {TABS.map(t => <button key={t.key} className={`tab-btn${tab === t.key ? ' active' : ''}`} onClick={() => setTab(t.key)}><t.icon size={14} style={{ marginRight: 5, verticalAlign: '-2px' }} />{t.label}</button>)}
      </div>
      {tab === 'profile' && <><OrganisationAddressCard /><ProfileCard /></>}
      {tab === 'security' && <SecurityPage />}
    </div>)
}
