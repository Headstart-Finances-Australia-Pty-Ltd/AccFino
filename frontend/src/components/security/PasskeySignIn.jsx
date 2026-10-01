import React, { useState } from 'react'
import { ScanFace } from 'lucide-react'
import { useAuth } from '../../hooks/useAuth.jsx'
import { passkeysSupported } from '../../lib/passkeys.js'

// "Sign in with face or fingerprint" - passwordless sign-in with a passkey.
export default function PasskeySignIn() {
  const { loginWithPasskey } = useAuth()
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState('')
  if (!passkeysSupported()) return null
  const go = async () => {
    setBusy(true); setErr('')
    const r = await loginWithPasskey()
    if (!r.ok) setErr(r.error)
    setBusy(false)
  }
  return (
    <div style={{ marginTop: 4 }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 8, margin: '6px 0 10px', color: 'var(--text-3)', fontSize: '.75rem' }}>
        <div style={{ flex: 1, height: 1, background: 'var(--border)' }} />or<div style={{ flex: 1, height: 1, background: 'var(--border)' }} />
      </div>
      <button type="button" className="btn btn-outline w-full" onClick={go} disabled={busy} data-testid="passkey-signin">
        <ScanFace size={16} /> {busy ? 'Waiting for your device…' : 'Sign in with face or fingerprint'}
      </button>
      {err && <div className="alert alert-error" style={{ marginTop: 8 }}>{err}</div>}
    </div>
  )
}
