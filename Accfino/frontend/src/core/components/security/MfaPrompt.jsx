import React, { useState } from 'react'
import { ShieldCheck, ScanFace, KeyRound, Smartphone, Mail, LifeBuoy } from 'lucide-react'
import { errMsg, mfaLogin, mfaSendCode } from '../../lib/platformApi.js'
import { passkeyError, passkeysSupported, signInWithPasskey } from '../../lib/passkeys.js'

// Second sign-in step. Offers every verification method the account has set up.
const META = {
  passkey:  { icon: ScanFace,   label: 'Face or fingerprint', help: 'Use Face ID, Touch ID, Windows Hello or your phone.' },
  totp:     { icon: KeyRound,   label: 'Authenticator app',   help: 'Enter the 6-digit passcode from your authenticator app.' },
  sms:      { icon: Smartphone, label: 'Text message',        help: 'We will text a 6-digit code to your phone.' },
  email:    { icon: Mail,       label: 'Email code',          help: 'We will email a 6-digit code to you.' },
  recovery: { icon: LifeBuoy,   label: 'Recovery code',       help: 'Enter one of your saved recovery codes.' },
}

export default function MfaPrompt({ challenge, onDone, onCancel }) {
  const methods = (challenge.methods || ['totp']).filter(m => m !== 'passkey' || passkeysSupported())
  const [method, setMethod] = useState(methods[0] || 'totp')
  const [code, setCode] = useState('')
  const [sentTo, setSentTo] = useState('')
  const [err, setErr] = useState('')
  const [busy, setBusy] = useState(false)

  const pick = m => { setMethod(m); setCode(''); setErr(''); setSentTo('') }

  const sendCode = async () => {
    setBusy(true); setErr('')
    try { const { data } = await mfaSendCode(challenge.mfa_token, method); setSentTo(data.sent_to) }
    catch (e) { setErr(errMsg(e, 'Could not send the code')) } finally { setBusy(false) }
  }

  const usePasskey = async () => {
    setBusy(true); setErr('')
    try { onDone(await signInWithPasskey(challenge.mfa_token)) }
    catch (e) { setErr(passkeyError(e)) } finally { setBusy(false) }
  }

  const submit = async e => {
    e.preventDefault()
    setBusy(true); setErr('')
    try {
      const body = method === 'recovery'
        ? { mfa_token: challenge.mfa_token, recovery_code: code.trim() }
        : { mfa_token: challenge.mfa_token, code: code.trim(), method }
      const { data } = await mfaLogin(body)
      onDone(data)
    } catch (e2) { setErr(errMsg(e2, 'Invalid code')) } finally { setBusy(false) }
  }

  const M = META[method] || META.totp
  const needsSend = (method === 'sms' || method === 'email') && !sentTo
  return (
    <div className="modal-overlay" style={{ zIndex: 1000 }}>
      <div className="modal" style={{ maxWidth: 460, width: '94%', padding: 26 }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginBottom: 6 }}>
          <ShieldCheck size={22} color="var(--success)" /><h3 style={{ margin: 0 }}>Verify it's you</h3>
        </div>
        {methods.length > 1 && (
          <div className="tabs-bar" style={{ margin: '10px 0 14px', flexWrap: 'wrap' }}>
            {methods.map(m => { const I = META[m]?.icon || KeyRound
              return <button key={m} type="button" className={`tab-btn${method === m ? ' active' : ''}`} onClick={() => pick(m)} data-testid={`mfa-${m}`}>
                <I size={14} style={{ marginRight: 4, verticalAlign: '-2px' }} />{META[m]?.label || m}</button> })}
          </div>)}
        <p className="text-sm text-muted" style={{ marginBottom: 12 }}>
          {method === 'sms' && challenge.phone_hint ? `We will text a code to ${challenge.phone_hint}.`
            : method === 'email' && challenge.email_hint ? `We will email a code to ${challenge.email_hint}.` : M.help}
        </p>
        {method === 'passkey' ? (
          <button className="btn btn-primary w-full" disabled={busy} onClick={usePasskey} data-testid="mfa-passkey-go">
            <ScanFace size={16} /> {busy ? 'Waiting for your device…' : 'Use face or fingerprint'}</button>
        ) : needsSend ? (
          <button className="btn btn-primary w-full" disabled={busy} onClick={sendCode}>{busy ? 'Sending…' : 'Send code'}</button>
        ) : (
          <form onSubmit={submit}>
            {sentTo && <p className="text-xs text-muted">Code sent to {sentTo}. <button type="button" className="btn btn-ghost btn-xs" onClick={sendCode} disabled={busy}>Resend</button></p>}
            <input className="input" autoFocus value={code} onChange={e => setCode(e.target.value)}
                   inputMode={method === 'recovery' ? 'text' : 'numeric'} autoComplete="one-time-code"
                   placeholder={method === 'recovery' ? 'xxxxxx-xxxxxx' : '123456'} data-testid="mfa-code" />
            <button className="btn btn-primary w-full mt-4" disabled={busy || !code} type="submit">{busy ? 'Checking…' : 'Verify'}</button>
          </form>)}
        {err && <div className="alert alert-error" style={{ marginTop: 12 }}>{err}</div>}
        <button className="btn btn-ghost btn-sm mt-4" type="button" onClick={onCancel}>Cancel sign-in</button>
      </div>
    </div>
  )
}
