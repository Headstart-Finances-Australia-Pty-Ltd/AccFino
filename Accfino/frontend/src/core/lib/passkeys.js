// Passkeys (WebAuthn): Face ID, Touch ID, Windows Hello (face / fingerprint / PIN), Android biometrics
// or a security key. The biometric check happens on the user's device; AccFino only receives a
// signed proof and never sees face or fingerprint data.
import { startAuthentication, startRegistration, browserSupportsWebAuthn } from '@simplewebauthn/browser'
import * as api from './platformApi.js'

export const passkeysSupported = () => { try { return browserSupportsWebAuthn() } catch { return false } }

export function passkeyError(e) {
  if (e?.name === 'NotAllowedError') return 'Passkey request was cancelled or timed out.'
  if (e?.name === 'InvalidStateError') return 'This device already has a passkey for your account.'
  return api.errMsg(e, 'Passkey failed')
}

export async function addPasskey(name) {
  const { data } = await api.passkeyRegOptions()
  const credential = await startRegistration({ optionsJSON: data.options })
  const r = await api.passkeyRegVerify({ challenge_id: data.challenge_id, credential, name })
  return r.data
}

// mfaToken given -> second step after password; omitted -> passwordless sign-in
export async function signInWithPasskey(mfaToken) {
  const { data } = await api.passkeyAuthOptions(mfaToken)
  const credential = await startAuthentication({ optionsJSON: data.options })
  const r = await api.passkeyAuthVerify({ challenge_id: data.challenge_id, credential, ...(mfaToken ? { mfa_token: mfaToken } : {}) })
  return r.data
}

export function suggestDeviceName() {
  const ua = navigator.userAgent
  if (/iPhone|iPad/.test(ua)) return 'iPhone / iPad (Face ID / Touch ID)'
  if (/Mac/.test(ua)) return 'Mac (Touch ID)'
  if (/Android/.test(ua)) return 'Android (face / fingerprint)'
  if (/Windows/.test(ua)) return 'Windows Hello'
  return 'Passkey'
}
