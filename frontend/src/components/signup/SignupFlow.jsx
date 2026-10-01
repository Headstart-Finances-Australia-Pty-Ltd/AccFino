import React, { useEffect, useRef, useState } from 'react'
import toast from 'react-hot-toast'
import * as api from '../../lib/booksApi.js'
import { emailError, phoneError } from '../../lib/contact.js'
import ContactVerifier from './ContactVerifier.jsx'

const STATES = ['NSW', 'VIC', 'QLD', 'WA', 'SA', 'TAS', 'ACT', 'NT', 'Outside Australia']
const INDUSTRIES = ['Accounting & bookkeeping', 'Construction & trades', 'Retail & e-commerce', 'Hospitality', 'Health & wellbeing', 'Professional services', 'Technology', 'Manufacturing & wholesale',
  'Not-for-profit', 'Property & real estate', 'Transport & logistics', 'Education', 'Other']
const ENTITY_TYPES = [['company', 'Company'], ['trust', 'Trust'], ['partnership', 'Partnership'], ['sole_trader', 'Sole trader'], ['smsf', 'SMSF'], ['other', 'Other']]
const ROLE_LABEL = { owner: 'Organisation Admin', admin: 'Administrator', accountant: 'Accountant', bookkeeper: 'Bookkeeper', payroll: 'Payroll', readonly: 'Read-only' }
const BLANK_ORG = { name: '', abn: '', acn: '', other_id: '', entity_type: 'company', address: '', city: '', state: 'NSW', postcode: '', phone: '', contact_email: '', industry: '', slug: '' }
const BLANK_USER = { first_name: '', last_name: '', email: '', phone: '', password: '', confirm: '' }

/**
 * Sign up, organisation first.
 *   1. Create a new organisation   OR   join an existing one
 *   2a. new:  organisation details -> (web address shown) -> your account  -> you become the organisation's Organisation Admin (its one primary administrator)
 *   2b. join: find the organisation -> ACCESS CODE from its administrator -> your account
 * Selecting an organisation proves nothing: only a valid access code unlocks the account form (the server checks it again when the account is created).
 * Email address and phone number are mandatory for everyone. They are checked here for instant feedback and AGAIN by the server (which is what actually enforces it).
 */
// The two start-up choices: full width of the sign-up card, text wraps inside it (the shared .btn style is single-line / nowrap)
const CHOICE_BTN = { padding: 14, textAlign: 'left', display: 'flex', flexDirection: 'column', alignItems: 'flex-start', gap: 4, width: '100%', maxWidth: '100%', boxSizing: 'border-box', whiteSpace: 'normal', height: 'auto', lineHeight: 1.4 }

export default function SignupFlow({ tenant, onDone }) {
  const locked = tenant?.found ? tenant : null                  // we are on an organisation's own address: you can only join THAT organisation
  const [step, setStep] = useState(locked ? 'find' : 'choose')
  const [mode, setMode] = useState(locked ? 'join' : null)
  const [org, setOrg] = useState(BLANK_ORG)
  const [user, setUser] = useState(BLANK_USER)
  const [err, setErr] = useState('')
  const [vcfg, setVcfg] = useState({ email_required: true, phone_required: true })      // server policy; assume 'verify both' until it answers (the server enforces regardless)
  const [proof, setProof] = useState({ email: { done: false, token: null }, phone: { done: false, token: null } })
  const [fieldErr, setFieldErr] = useState({})                // per-field messages on the account form
  const [busy, setBusy] = useState(false)
  const [proposed, setProposed] = useState(null)               // {slug, tenant_url}
  const [q, setQ] = useState('')
  const [results, setResults] = useState([])
  const [picked, setPicked] = useState(null)                   // {slug, name, location}
  const [code, setCode] = useState('')
  const [verified, setVerified] = useState(null)               // {signup_token, role, organisation}
  const [done, setDone] = useState(null)
  const timer = useRef(null)

  const fail = e => setErr(api.errMsg(e))
  const run = async fn => { setBusy(true); setErr(''); try { await fn() } catch (e) { fail(e) } finally { setBusy(false) } }
  const setO = k => e => setOrg(o => ({ ...o, [k]: e.target.value }))
  const setU = k => e => { setUser(u => ({ ...u, [k]: e.target.value })); setFieldErr(f => (f[k] ? { ...f, [k]: undefined } : f)) }

  useEffect(() => {                                            // on an organisation's address, pre-select that organisation (no searching needed)
    if (locked) api.signupLookupOrg(locked.tenant).then(r => setPicked(r.data)).catch(() => {})
  }, [locked?.tenant]) // eslint-disable-line

  useEffect(() => {                                            // search as the person types (3+ letters)
    clearTimeout(timer.current)
    if (locked || step !== 'find' || picked || q.trim().length < 3) { if (q.trim().length < 3) setResults([]); return }
    timer.current = setTimeout(() => api.signupSearchOrgs(q.trim()).then(r => setResults(r.data?.items || [])).catch(e => { setResults([]); fail(e) }), 350)
    return () => clearTimeout(timer.current)
  }, [q, step, picked]) // eslint-disable-line

  const choose = m => { setMode(m); setErr(''); setStep(m === 'new' ? 'org' : 'find') }

  const checkOrg = () => run(async () => {
    const { data } = await api.signupValidateOrg(org)
    setProposed(data); setStep('user')
  })
  const verify = () => run(async () => {
    const { data } = await api.signupVerifyCode(picked.slug, code)
    setVerified(data); setStep('user')
  })
  useEffect(() => { api.contactConfig?.().then(r => setVcfg(r.data)).catch(() => {}) }, []) // eslint-disable-line
  const onProof = ch => p => {
    setProof(x => (x[ch].done === p.done && x[ch].token === p.token ? x : { ...x, [ch]: p }))
    if (p.done) setFieldErr(f => (f[ch] ? { ...f, [ch]: undefined } : f))                 // verified: the 'please verify' message no longer applies
  }
  useEffect(() => { if (err === 'Please correct the highlighted fields.' && !Object.values(fieldErr).some(Boolean)) setErr('') }, [fieldErr]) // eslint-disable-line

  const validateUser = u => {
    const e = {}
    if (!u.first_name.trim()) e.first_name = 'First name is required.'
    if (!u.last_name.trim()) e.last_name = 'Last name is required.'
    const ee = emailError(u.email); if (ee) e.email = ee
    const pe = phoneError(u.phone); if (pe) e.phone = pe
    if (!ee && vcfg.email_required && !proof.email.done) e.email = 'Please verify your email address.'
    if (!pe && vcfg.phone_required && !proof.phone.done) e.phone = 'Please verify your phone number.'
    if (!u.password) e.password = 'Password is required.'
    if (!u.confirm) e.confirm = 'Please confirm your password.'
    else if (u.password !== u.confirm) e.confirm = 'The two passwords do not match.'
    return e
  }
  const create = () => run(async () => {
    const e = validateUser(user)
    setFieldErr(e)
    if (Object.keys(e).length) { setErr('Please correct the highlighted fields.'); return }      // nothing is sent until the form is complete (the server checks again regardless)
    const u = { first_name: user.first_name.trim(), last_name: user.last_name.trim(), email: user.email.trim(), phone: user.phone.trim(), password: user.password, email_token: proof.email.token, phone_token: proof.phone.token }
    const { data } = mode === 'new' ? await api.signupCreateOrg({ org: { ...org, slug: org.slug || proposed?.slug || '' }, user: u })
      : await api.signupJoin({ signup_token: verified.signup_token, user: u })
    setDone(data); toast.success('Account created')
  })
  const back = () => { setErr(''); setStep(mode === 'new' ? (step === 'user' ? 'org' : 'choose') : (step === 'user' ? 'find' : 'choose')) }

  const Err = () => err ? <div className="alert alert-error text-sm" role="alert" style={{ marginBottom: 10 }}>{err}</div> : null
  const field = (label, k, props = {}) => {
    const { error, ...rest } = props
    return (
      <label className="text-sm" style={{ display: 'block' }}>{label}{props.required ? ' *' : ''}
        <input className="input" aria-label={label} aria-invalid={error ? 'true' : undefined} style={error ? { borderColor: 'var(--danger)' } : undefined}
               value={props.state ? props.state[k] : org[k]} onChange={props.set || setO(k)} {...rest} />
        {error && <span role="alert" className="text-xs" style={{ color: 'var(--danger)', display: 'block', marginTop: 2 }} data-testid={`err-${k}`}>{error}</span>}
      </label>)
  }

  // ── done ────────────────────────────────────────────────────────────────────────────────────────────────────────
  if (done) {
    const o = done.organisation || {}
    return (
      <div data-testid="signup-done" style={{ textAlign: 'center' }}>
        <div style={{ fontSize: '2rem' }}>✅</div>
        <h3 style={{ margin: '8px 0' }}>{mode === 'new' ? `${o.name} is ready` : `Welcome to ${o.name}`}</h3>
        {done.tenant_url
          ? <><p className="text-sm">Your organisation's address is<br /><b>{done.tenant_url}</b></p>
            <button className="btn btn-primary" onClick={() => window.location.assign(done.login_url)}>Go to {o.name} and sign in</button></>
          : <><p className="text-sm">Your account is ready. Sign in with the email and password you just chose.{o.slug || done.slug ? <><br />Your organisation's web name is <b>{o.slug || done.slug}</b>. A full web address appears here once the platform owner switches on organisation addresses (TENANT_BASE_DOMAIN).</> : null}</p>
            <button className="btn btn-primary" onClick={() => onDone?.()}>Go to sign in</button></>}
      </div>)
  }

  // ── 1. organisation ─────────────────────────────────────────────────────────────────────────────────────────────
  if (step === 'choose') return (
    <div data-testid="signup-choose">
      <h3 style={{ marginTop: 0 }}>What would you like to do?</h3>
      <div style={{ display: 'grid', gap: 10, gridTemplateColumns: 'minmax(0, 1fr)' }}>
        <button className="btn btn-primary" style={CHOICE_BTN} onClick={() => choose('new')}><b>Create a New Organisation</b><span className="text-xs" style={{ display: 'block', whiteSpace: 'normal', fontWeight: 400 }}>Set up your business. You become its Organisation Admin: the main contact and the only person who manages its settings, users and access codes.</span></button>
        <button className="btn btn-outline" style={CHOICE_BTN} onClick={() => choose('join')}><b>Join an Existing Organisation</b><span className="text-xs" style={{ display: 'block', whiteSpace: 'normal', fontWeight: 400 }}>You need the organisation's name and an access code from its Organisation Admin.</span></button>
      </div>
    </div>)

  if (step === 'org') return (
    <form onSubmit={e => { e.preventDefault(); checkOrg() }} style={{ display: 'grid', gap: 10 }} data-testid="signup-org">
      <h3 style={{ margin: 0 }}>Organisation details</h3>
      <Err />
      {field('Organisation name', 'name', { required: true })}
      <div className="grid-2" style={{ gap: 10 }}>{field('ABN', 'abn', { placeholder: '11 digits' })}{field('ACN', 'acn', { placeholder: '9 digits' })}</div>
      {field('Other registration number (if not ABN/ACN)', 'other_id')}
      <div className="grid-2" style={{ gap: 10 }}>
        <label className="text-sm">Organisation type<select className="input" aria-label="Organisation type" value={org.entity_type} onChange={setO('entity_type')}>{ENTITY_TYPES.map(([v, l]) => <option key={v} value={v}>{l}</option>)}</select></label>
        <label className="text-sm">Industry<select className="input" aria-label="Industry" value={org.industry} onChange={setO('industry')}><option value="">Select…</option>{INDUSTRIES.map(i => <option key={i}>{i}</option>)}</select></label>
      </div>
      {field('Address', 'address', { required: true })}
      <div className="grid-2" style={{ gap: 10 }}>{field('City or suburb', 'city', { required: true })}
        <label className="text-sm">State *<select className="input" aria-label="State" value={org.state} onChange={setO('state')}>{STATES.map(s => <option key={s}>{s}</option>)}</select></label></div>
      <div className="grid-2" style={{ gap: 10 }}>{field('Postcode', 'postcode')}{field('Phone', 'phone', { placeholder: 'Optional - defaults to the Organisation Admin\'s phone' })}</div>
      {field('Contact email', 'contact_email', { type: 'email', placeholder: 'Optional - defaults to the Organisation Admin\'s email' })}
      {field('Web address (optional)', 'slug', { placeholder: 'e.g. abc-accounting' })}
      <div className="flex gap-1"><button type="button" className="btn btn-ghost" onClick={back}>Back</button><button className="btn btn-primary" disabled={busy}>{busy ? 'Checking…' : 'Continue'}</button></div>
    </form>)

  // ── 2b. find + verify ───────────────────────────────────────────────────────────────────────────────────────────
  if (step === 'find') return (
    <form onSubmit={e => { e.preventDefault(); verify() }} style={{ display: 'grid', gap: 10 }} data-testid="signup-find">
      <h3 style={{ margin: 0 }}>{locked ? `Join ${locked.name}` : 'Join an existing organisation'}</h3>
      <Err />
      {!locked && !picked && (<>
        <label className="text-sm">Organisation name<input className="input" aria-label="Organisation name" value={q} onChange={e => setQ(e.target.value)} placeholder="Start typing at least 3 letters" autoComplete="off" /></label>
        {results.map(r => (
          <button type="button" key={r.slug} className="btn btn-outline" style={{ textAlign: 'left' }} onClick={() => { setPicked(r); setResults([]); setErr('') }} data-testid={`org-result-${r.slug}`}>
            <b>{r.name}</b>{r.location ? <span className="text-muted"> · {r.location}</span> : null}</button>))}
        {q.trim().length >= 3 && results.length === 0 && <div className="text-xs text-muted">No organisation found. Check the spelling, or ask your administrator for the organisation's web address.</div>}
      </>)}
      {picked && (<>
        <div style={{ padding: 10, border: '1px solid var(--border)', borderRadius: 8 }}><div className="text-xs text-muted">Organisation</div><b>{picked.name}</b>{picked.location ? <span className="text-muted"> · {picked.location}</span> : null}
          {!locked && <button type="button" className="btn btn-ghost btn-xs" style={{ float: 'right' }} onClick={() => { setPicked(null); setCode('') }}>Change</button>}</div>
        <label className="text-sm">Organisation access code *<input className="input mono" aria-label="Organisation access code" value={code} onChange={e => setCode(e.target.value)} placeholder="ABC-7F4K-92LM" autoComplete="off" /></label>
        <div className="text-xs text-muted">Ask your Organisation Admin for a code. Choosing an organisation is not enough to create an account.</div>
      </>)}
      <div className="flex gap-1"><button type="button" className="btn btn-ghost" onClick={back}>Back</button>
        <button className="btn btn-primary" disabled={busy || !picked || code.trim().length < 6}>{busy ? 'Verifying…' : 'Verify & Continue'}</button></div>
    </form>)

  // ── 3. your account ─────────────────────────────────────────────────────────────────────────────────────────────
  return (
    <form noValidate onSubmit={e => { e.preventDefault(); create() }} style={{ display: 'grid', gap: 10 }} data-testid="signup-user">
      <h3 style={{ margin: 0 }}>Your account</h3>
      {mode === 'new'
        ? <div className="text-sm">You will be the <b>Organisation Admin</b> of <b>{org.name}</b>: its primary contact, and the only person who manages its settings, users and access codes. Its address will be <b>{proposed?.tenant_url || proposed?.slug}</b>.</div>
        : <div className="text-sm">Joining <b>{verified?.organisation?.name}</b> as <b>{ROLE_LABEL[verified?.role] || verified?.role}</b>.</div>}
      <Err />
      <div className="grid-2" style={{ gap: 10 }}>
        {field('First Name', 'first_name', { state: user, set: setU('first_name'), required: true, error: fieldErr.first_name, autoComplete: 'given-name' })}
        {field('Last Name', 'last_name', { state: user, set: setU('last_name'), required: true, error: fieldErr.last_name, autoComplete: 'family-name' })}
      </div>
      {field('Email Address', 'email', { state: user, set: setU('email'), required: true, type: 'email', error: fieldErr.email, autoComplete: 'email' })}
      <ContactVerifier channel="email" label="Email" value={user.email.trim().toLowerCase()} valid={!emailError(user.email)} required={vcfg.email_required} send={api.contactSend} verify={api.contactVerify} onChange={onProof('email')} />
      {field('Phone Number', 'phone', { state: user, set: setU('phone'), required: true, type: 'tel', error: fieldErr.phone, autoComplete: 'tel', placeholder: '0412 345 678 or +61 412 345 678' })}
      <ContactVerifier channel="phone" label="Phone" value={user.phone.trim()} valid={!phoneError(user.phone)} required={vcfg.phone_required} send={api.contactSend} verify={api.contactVerify} onChange={onProof('phone')} />
      {mode === 'new' && <div className="text-xs text-muted">As Organisation Admin, your email and phone number become the organisation's primary contact details: account, licence, billing and security notices are sent to you.</div>}
      {field('Password', 'password', { state: user, set: setU('password'), required: true, type: 'password', error: fieldErr.password, autoComplete: 'new-password' })}
      {field('Confirm Password', 'confirm', { state: user, set: setU('confirm'), required: true, type: 'password', error: fieldErr.confirm, autoComplete: 'new-password' })}
      <div className="flex gap-1"><button type="button" className="btn btn-ghost" onClick={back}>Back</button><button className="btn btn-primary" disabled={busy}>{busy ? 'Creating…' : 'Create Account'}</button></div>
    </form>)
}
