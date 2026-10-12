// Phase 0 platform API client: organisations, security, audit, identity.
import axios from 'axios'
import { persistTokenFields } from './authFetch.js'
import { http, pub, errMsg } from './platformHttp.js'
export { errMsg }

// auth / security
export const me            = () => http.get('/auth/me')
export const mfaLogin      = (body) => http.post('/auth/mfa/login', body)
export const mfaSetup      = () => http.post('/auth/mfa/setup')
export const mfaEnable     = (code) => http.post('/auth/mfa/enable', { code }).then(r => { persistTokenFields(r.data); return r })
export const mfaDisable    = (body) => http.post('/auth/mfa/disable', body).then(r => { persistTokenFields(r.data); return r })
export const logoutServer  = (token) => axios.post('/api/auth/logout', null, { headers: token ? { Authorization: `Bearer ${token}` } : {} })
export const logoutAll     = () => http.post('/auth/logout-all')
export const myAudit       = () => http.get('/audit/mine')
export const orgAudit      = (params) => http.get('/audit', { params })
export const allAudit      = (params) => http.get('/audit/all', { params })     // AccFino administrator only
export const securityStatus= () => http.get('/admin/security-status')

// MFA methods (passkeys = face / fingerprint / Windows Hello, SMS, email, authenticator app)
export const mfaMethods        = () => http.get('/auth/mfa/methods')
export const smsEnrol          = (phone) => http.post('/auth/mfa/sms/enrol', { phone })
export const smsConfirm        = (code) => http.post('/auth/mfa/sms/confirm', { code }).then(r => { persistTokenFields(r.data); return r })
export const smsDisable        = (password) => http.post('/auth/mfa/sms/disable', { password }).then(r => { persistTokenFields(r.data); return r })
export const emailEnrol        = () => http.post('/auth/mfa/email/enrol')
export const emailConfirm      = (code) => http.post('/auth/mfa/email/confirm', { code }).then(r => { persistTokenFields(r.data); return r })
export const emailDisable      = (password) => http.post('/auth/mfa/email/disable', { password }).then(r => { persistTokenFields(r.data); return r })
export const passkeyRegOptions = () => http.post('/auth/mfa/passkeys/register/options')
export const passkeyRegVerify  = (b) => http.post('/auth/mfa/passkeys/register/verify', b).then(r => { persistTokenFields(r.data); return r })
export const passkeyRemove     = (id, password) => http.post(`/auth/mfa/passkeys/${id}/remove`, { password }).then(r => { persistTokenFields(r.data); return r })
export const regenerateCodes   = (password) => http.post('/auth/mfa/recovery-codes/regenerate', { password })
export const mfaSendCode       = (mfa_token, channel) => pub.post('/auth/mfa/challenge/send', { mfa_token, channel })
export const passkeyAuthOptions= (mfa_token) => pub.post('/auth/mfa/passkeys/auth/options', mfa_token ? { mfa_token } : {})
export const passkeyAuthVerify = (b) => pub.post('/auth/mfa/passkeys/auth/verify', b)

// IAM: devices, password, organisation access policy, admin identity management
export const mySessions        = () => http.get('/auth/sessions')
export const revokeSession     = (id) => http.post(`/auth/sessions/${id}/revoke`)
export const revokeOthers      = () => http.post('/auth/sessions/revoke-others')
export const changeMyPassword  = (b) => http.post('/auth/change-password', b).then(r => { persistTokenFields(r.data); return r })
export const accessPolicy      = () => http.get('/org/current/access-policy')
export const saveAccessPolicy  = (b) => http.put('/org/current/access-policy', b)
export const adminUsers        = (params) => http.get('/admin/users', { params })
export const adminUser         = (id) => http.get(`/admin/users/${id}`)
export const adminAction       = (id, action, body = {}) => http.post(`/admin/users/${id}/${action}`, body)
export const adminRevokeSession= (id, sid) => http.post(`/admin/users/${id}/sessions/${sid}/revoke`)
// Organisation identity (Settings > Identity, organisation owners/admins)
export const orgMembers        = () => http.get('/org/current/identity/members')
export const orgMember         = (id) => http.get(`/org/current/identity/members/${id}`)
export const orgMemberAction   = (id, action, body = {}) => http.post(`/org/current/identity/members/${id}/${action}`, body)

// organisations
export const myOrgs        = () => http.get('/org/mine')
export const createOrg     = (b) => http.post('/org', b)
export const currentOrg    = () => http.get('/org/current')
export const updateOrg     = (b) => http.patch('/org/current', b)
export const setLockDate   = (lock_date) => http.post('/org/current/lock-date', { lock_date })
export const members       = () => http.get('/org/current/members')
export const addMember     = (b) => http.post('/org/current/members', b)
export const changeRole    = (uid, role) => http.patch(`/org/current/members/${uid}`, { role })
export const removeMember  = (uid) => http.delete(`/org/current/members/${uid}`)
export const orgDirectory  = () => http.get('/org/current/directory')                 // names + roles only: any member
export const adminOverview = () => http.get('/org/current/admin/overview')             // Organisation Admin dashboard
export const transferAdmin = (new_admin_user_id, password) => http.post('/org/current/transfer-admin', { new_admin_user_id, password })

// my account (personal profile: any signed-in user)
export const updateMyProfile = (b) => http.patch('/auth/me/profile', b)
export const myContactSend   = (channel, destination)       => http.post('/auth/me/contact/send', { channel, destination })
export const myContactVerify = (channel, destination, code) => http.post('/auth/me/contact/verify', { channel, destination, code })
