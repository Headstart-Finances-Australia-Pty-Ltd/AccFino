import React, { createContext, useContext, useState, useEffect } from 'react'
import { login as apiLogin, getMyPlan, licenceMyModules, verifySession } from '../lib/api.js'
import { logoutServer } from '../lib/platformApi.js'
import MfaPrompt from '../components/security/MfaPrompt.jsx'
import { passkeyError, signInWithPasskey } from '../lib/passkeys.js'

const Ctx = createContext(null)

// Always produce a readable message for a failed sign-in (never blank): the server's own text when it sent one,
// otherwise a message that matches what went wrong (no connection, server error, ...).
function loginErrorMessage(e) {
  const d = e?.response?.data?.detail
  if (typeof d === 'string' && d.trim()) return d
  if (Array.isArray(d) && d.length) return d.map(x => x?.msg || String(x)).join('; ')
  if (d && typeof d === 'object' && typeof d.message === 'string') return d.message
  const status = e?.response?.status
  if (!e?.response) return e?.isAxiosError ? 'Cannot reach the server. Check your internet connection and try again.' : 'Sign-in failed. Please try again.'
  if (status === 401 || status === 404) return 'The email / user id and password do not match, or the account does not exist.'
  if (status === 403) return 'You do not have access to sign in with this account.'
  if (status === 423) return 'This account is temporarily locked after repeated failed sign-ins. Try again later.'
  if (status === 429) return 'Too many sign-in attempts. Please wait a few minutes and try again.'
  if (status >= 500) return 'The server had a problem signing you in. Please try again in a moment.'
  return 'Sign-in failed. Please try again.'
}

export function AuthProvider({ children }) {
  const [user, setUser] = useState(() => {
    try {
      const u = JSON.parse(localStorage.getItem('af_user'))
      // Phase 0: sessions saved before server-side tokens existed can't call the
      // API any more - drop them so the user signs in once and gets a token.
      if (u && !u.token) { localStorage.removeItem('af_user'); return null }
      return u
    } catch { return null }
  })
  const [loading, setLoading] = useState(false)
  const [mfaChallenge, setMfaChallenge] = useState(null)

  // Keep React state in step when a fresh token is stored (password change, MFA enrolment)
  useEffect(() => {
    const sync = () => { try { setUser(JSON.parse(localStorage.getItem('af_user'))) } catch {} }
    window.addEventListener('accfino:session-updated', sync)
    return () => window.removeEventListener('accfino:session-updated', sync)
  }, [])

  // The user object above is restored straight from localStorage with no
  // server round-trip. If the database was ever reset/reseeded since this
  // browser last logged in, that cached user_id may no longer exist --
  // silently causing foreign-key errors deep in unrelated features (e.g.
  // creating an invoice) instead of a clear "please log in again". Check
  // once on mount and clear the stale session if the user is gone.
  useEffect(() => {
    if (!user?.id) return
    verifySession(user.id).catch(err => {
      if (err.response?.status === 404) {
        setUser(null)
        localStorage.removeItem('af_user')
      }
      // any other error (network blip, etc.) is not treated as invalid --
      // don't log someone out just because one check failed to reach the server
    })
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  // Shared by password, MFA and passkey sign-in. The token is stored BEFORE the follow-up
  // plan/module calls so they are authenticated (previously they returned 401 and reloaded the page).
  const completeLogin = async (data) => {
    const roles = (data.roles || []).map(r => String(r).trim().toLowerCase())
    const u = { ...data, roles, is_admin: roles.includes('admin') }
    localStorage.setItem('af_user', JSON.stringify(u))
    try {
      const [planRes, modsRes] = await Promise.all([getMyPlan(data.id), licenceMyModules(data.id)])
      u.plan    = planRes.data        // { plan_id, licence_type, end_date, modules }
      u.modules = modsRes.data?.modules || []
    } catch { /* non-fatal */ }
    setUser(u)
    localStorage.setItem('af_user', JSON.stringify(u))
    window.dispatchEvent(new Event('accfino:modules-changed'))   // Layout re-applies module permissions
    return { ok: true, user: u }
  }

  const login = async (email, password) => {
    setLoading(true)
    try {
      let { data } = await apiLogin(email.trim(), password.trim())
      if (data?.mfa_required) {
        // Second step: face/fingerprint, authenticator, SMS, email or recovery code in <MfaPrompt/>
        data = await new Promise((resolve, reject) => setMfaChallenge({ ...data, resolve, reject }))
        setMfaChallenge(null)
      }
      return await completeLogin(data)
    } catch (e) {
      setMfaChallenge(null)
      if (e?.message === 'mfa_cancelled') return { ok: false, error: 'Sign-in cancelled' }
      return { ok: false, error: loginErrorMessage(e) }
    } finally {
      setLoading(false)
    }
  }

  // Passwordless: sign in with a passkey (face / fingerprint / Windows Hello)
  const loginWithPasskey = async () => {
    setLoading(true)
    try { return await completeLogin(await signInWithPasskey()) }
    catch (e) { return { ok: false, error: passkeyError(e) } }
    finally { setLoading(false) }
  }


  const logout = () => {
    logoutServer(user?.token).catch(() => {})   // audit record; token is discarded client-side
    try { localStorage.removeItem('af_org') } catch {}
    setUser(null)
    localStorage.removeItem('af_user')
  }

  return (
    <Ctx.Provider value={{ user, login, loginWithPasskey, logout, loading }}>
      {children}
      {mfaChallenge && (
        <MfaPrompt challenge={mfaChallenge}
                   onDone={d => mfaChallenge.resolve(d)}
                   onCancel={() => mfaChallenge.reject(new Error('mfa_cancelled'))} />
      )}
    </Ctx.Provider>
  )
}

export const useAuth = () => useContext(Ctx)
