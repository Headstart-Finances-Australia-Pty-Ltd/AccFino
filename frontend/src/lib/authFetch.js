// Phase 0: attach the session token to every same-origin /api request made with
// window.fetch (several screens call fetch directly instead of the axios client),
// and send the user back to login when the session is no longer valid.
const readUser = () => { try { return JSON.parse(localStorage.getItem('af_user') || '{}') } catch { return {} } }

export function currentOrgId() {
  try { return localStorage.getItem('af_org') || '' } catch { return '' }
}

export function persistTokenFields(data) {
  // Merge a fresh token (e.g. after password change or MFA enrolment) into the stored session
  if (!data || !data.token) return
  const u = readUser()
  if (!u || !u.id) return
  const next = { ...u, token: data.token, token_expires_at: data.token_expires_at,
                 mfa_enabled: data.mfa_enabled ?? u.mfa_enabled, organisations: data.organisations ?? u.organisations,
                 mfa_required_to_enrol: data.mfa_required_to_enrol ?? u.mfa_required_to_enrol,
                 password_change_required: data.password_change_required ?? u.password_change_required }
  localStorage.setItem('af_user', JSON.stringify(next))
  window.dispatchEvent(new Event('accfino:session-updated'))
}

// IAM: send users somewhere they can fix a block (enrol MFA, change password), with the reason shown there.
const GUIDED = { password_change_required: 1, ca_mfa_required: 1, ca_method_not_allowed: 1, mfa_enrolment_required: 1 }
export function handleIamBlock(status, data) {
  const code = data?.code
  if (status === 403 && code && (GUIDED[code] || code === 'ca_ip_blocked')) {
    try { sessionStorage.setItem('af_notice', JSON.stringify({ code, message: data.detail })) } catch {}
    if (GUIDED[code] && !window.location.pathname.startsWith('/settings/iam')) window.location.href = '/settings/iam?tab=security'
    return true
  }
  if (status === 401 && ['ca_reauth_required', 'session_ended', 'account_disabled'].includes(code)) {
    try { sessionStorage.setItem('af_notice', JSON.stringify({ code, message: data.detail })) } catch {}
  }
  return false
}

export function expireSession() {
  localStorage.removeItem('af_user')
  if (!window.location.pathname.startsWith('/login')) window.location.href = '/login'
}

export function installAuthFetch() {
  if (window.__accfinoFetchInstalled) return
  window.__accfinoFetchInstalled = true
  const orig = window.fetch.bind(window)
  window.fetch = async (input, init = {}) => {
    const url = typeof input === 'string' ? input : (input && input.url) || ''
    const isApi = url.startsWith('/api/') || url.startsWith(window.location.origin + '/api/')
    if (!isApi) return orig(input, init)
    const u = readUser()
    const headers = new Headers(init.headers || (typeof input !== 'string' && input.headers) || {})
    if (u.token && !headers.has('Authorization')) headers.set('Authorization', `Bearer ${u.token}`)
    const org = currentOrgId()
    if (org && !headers.has('X-Org-Id')) headers.set('X-Org-Id', org)
    const res = await orig(input, { ...init, headers })
    if ((res.status === 401 || res.status === 403) && !url.includes('/auth/login') && !url.includes('/auth/mfa/')) {
      const data = await res.clone().json().catch(() => ({}))
      handleIamBlock(res.status, data)
      if (res.status === 401) expireSession()
    }
    return res
  }
}
