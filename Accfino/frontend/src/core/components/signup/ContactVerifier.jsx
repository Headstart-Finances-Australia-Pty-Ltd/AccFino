import React, { useEffect, useRef, useState } from 'react'

/**
 * "Send code -> enter the 6-digit code -> verified" for ONE email address or phone number.
 *
 *   channel   'email' | 'phone'
 *   value     what the person typed (the proof is bound to exactly this value: editing it starts again)
 *   valid     the value passes the format check (Send code stays disabled until it does)
 *   required  does verification apply to this channel at all (server policy)? When not, nothing is rendered and onChange({ done: true }) is reported
 *   send / verify   (channel, destination[, code]) => Promise<{ data }>   (public at sign-up, authenticated on My Account)
 *   onChange  ({ done, token })  done = verified, or verification isn't available for this number; token = the proof to send with the request
 *
 * This is only the user interface. The server requires and re-checks the proof on every request that creates or changes an account.
 */
export default function ContactVerifier({ channel, value, valid, required, send, verify, onChange, label }) {
  const [phase, setPhase] = useState('idle')     // idle | sent | verified | skipped
  const [sentTo, setSentTo] = useState('')
  const [code, setCode] = useState('')
  const [err, setErr] = useState('')
  const [busy, setBusy] = useState(false)
  const first = useRef(true)
  const word = channel === 'email' ? 'email address' : 'phone number'

  useEffect(() => {                                            // a different address / number = a fresh start
    if (first.current) { first.current = false } else { setPhase('idle'); setCode(''); setErr('') }
    onChange?.({ done: required === false, token: null })
  }, [value, required]) // eslint-disable-line

  if (required === false) return null
  const msg = e => e?.response?.data?.detail || e?.message || 'Something went wrong'
  const doSend = async () => {
    setBusy(true); setErr('')
    try {
      const { data } = await send(channel, value)
      if (data.required === false) { setPhase('skipped'); onChange?.({ done: true, token: null }) }
      else { setSentTo(data.sent_to || ''); setPhase('sent') }
    } catch (e) { setErr(msg(e)) } finally { setBusy(false) }
  }
  const doVerify = async () => {
    setBusy(true); setErr('')
    try {
      const { data } = await verify(channel, value, code.trim())
      setPhase('verified'); onChange?.({ done: true, token: data.token })
    } catch (e) { setErr(msg(e)) } finally { setBusy(false) }
  }
  const box = { marginTop: 4, display: 'flex', gap: 6, alignItems: 'center', flexWrap: 'wrap' }
  return (
    <div data-testid={`verify-${channel}`} style={{ marginTop: -4 }}>
      {phase === 'verified' && <div className="text-xs" style={{ color: 'var(--success, #1a7f37)' }} role="status">✓ {label || word} verified</div>}
      {phase === 'skipped' && <div className="text-xs text-muted" role="status">We can't text numbers in this country, so this number can't be verified. It will be saved as unverified.</div>}
      {phase === 'idle' && (
        <div style={box}><button type="button" className="btn btn-outline btn-xs" disabled={!valid || busy} onClick={doSend}>{busy ? 'Sending…' : `Send code to verify ${word}`}</button>
          <span className="text-xs text-muted">Required</span></div>)}
      {phase === 'sent' && (
        <div style={box}>
          <span className="text-xs">Enter the 6-digit code sent to {sentTo}</span>
          <input className="input input-sm mono" style={{ width: 110 }} inputMode="numeric" maxLength={8} aria-label={`${label || word} verification code`} value={code} onChange={e => setCode(e.target.value)} autoComplete="one-time-code" />
          <button type="button" className="btn btn-primary btn-xs" disabled={busy || code.trim().length < 6} onClick={doVerify}>{busy ? 'Checking…' : 'Verify'}</button>
          <button type="button" className="btn btn-ghost btn-xs" disabled={busy} onClick={doSend}>Resend</button>
        </div>)}
      {err && <div role="alert" className="text-xs" style={{ color: 'var(--danger)' }} data-testid={`verify-err-${channel}`}>{err}</div>}
    </div>)
}
