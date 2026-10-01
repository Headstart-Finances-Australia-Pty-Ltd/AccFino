// Phase 0 platform API client: organisations, ledger, security, audit.
import axios from 'axios'
import { currentOrgId, expireSession, handleIamBlock, persistTokenFields } from './authFetch.js'

const http = axios.create({ baseURL: '/api' })
http.interceptors.request.use(cfg => {
  try {
    const u = JSON.parse(localStorage.getItem('af_user') || '{}')
    if (u?.token) cfg.headers['Authorization'] = `Bearer ${u.token}`
  } catch {}
  const org = currentOrgId()
  if (org) cfg.headers['X-Org-Id'] = org
  return cfg
})
http.interceptors.response.use(r => r, err => {
  handleIamBlock(err.response?.status, err.response?.data)
  if (err.response?.status === 401) expireSession()
  return Promise.reject(err)
})

export const errMsg = (e, fallback = 'Something went wrong') => {
  const d = e?.response?.data?.detail
  if (Array.isArray(d)) return d.map(x => x.msg || JSON.stringify(x)).join('; ')
  return d || e?.message || fallback
}

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
const pub = axios.create({ baseURL: '/api' })   // sign-in steps: no session yet
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

// ledger
export const accounts      = (include_inactive = false) => http.get('/ledger/accounts', { params: { include_inactive } })
export const createAccount = (b) => http.post('/ledger/accounts', b)
export const updateAccount = (id, b) => http.patch(`/ledger/accounts/${id}`, b)
export const accountTypes  = () => http.get('/ledger/account-types')
export const taxCodes      = () => http.get('/ledger/tax-codes')
export const tracking      = () => http.get('/ledger/tracking-categories')
export const addTracking   = (name) => http.post('/ledger/tracking-categories', { name })
export const addTrackingOpt= (id, name) => http.post(`/ledger/tracking-categories/${id}/options`, { name })
export const journals      = (params) => http.get('/ledger/journals', { params })
export const journal       = (id) => http.get(`/ledger/journals/${id}`)
export const postJournal   = (b) => http.post('/ledger/journals', b)
export const reverseJournal= (id, b = {}) => http.post(`/ledger/journals/${id}/reverse`, b)
export const syncBank      = (dry_run) => http.post('/ledger/sync/bank-transactions', null, { params: { dry_run } })
export const trialBalance  = (as_at) => http.get('/ledger/reports/trial-balance', { params: { as_at } })
export const profitLoss    = (from, to) => http.get('/ledger/reports/profit-loss', { params: { from, to } })
export const balanceSheet  = (as_at) => http.get('/ledger/reports/balance-sheet', { params: { as_at } })
export const generalLedger = (account_id, from, to) => http.get('/ledger/reports/general-ledger', { params: { account_id, from, to } })

// ── Journal workflow: preview, drafts + approval, AI suggestions, repeating, import, health ──
export const journalPreview   = (b) => http.post('/ledger/journal-preview', b)
export const journalSources   = () => http.get('/ledger/journal-sources')
export const journalHistory   = (id) => http.get(`/ledger/journals/${id}/history`)
export const journalSettings  = () => http.get('/ledger/journal-settings')
export const saveJournalSettings = (b) => http.put('/ledger/journal-settings', b)
export const ledgerHealth     = () => http.get('/ledger/ledger-health')
export const journalDrafts    = (params) => http.get('/ledger/journal-drafts', { params })
export const journalDraft     = (id) => http.get(`/ledger/journal-drafts/${id}`)
export const createDraft      = (b, submit = false) => http.post('/ledger/journal-drafts', b, { params: { submit } })
export const updateDraft      = (id, b) => http.put(`/ledger/journal-drafts/${id}`, b)
export const deleteDraft      = (id) => http.delete(`/ledger/journal-drafts/${id}`)
export const submitDraft      = (id) => http.post(`/ledger/journal-drafts/${id}/submit`)
export const approveDraft     = (id, b = {}) => http.post(`/ledger/journal-drafts/${id}/approve`, b)
export const rejectDraft      = (id, reason) => http.post(`/ledger/journal-drafts/${id}/reject`, { reason })
export const bulkApprove      = (min_confidence, ids) => http.post('/ledger/journal-drafts/bulk-approve', { min_confidence, ids })
export const generateSuggestions = () => http.post('/ledger/journal-suggestions/generate')
export const repeatingJournals = () => http.get('/ledger/repeating-journals')
export const createRepeating  = (b) => http.post('/ledger/repeating-journals', b)
export const updateRepeating  = (id, b) => http.put(`/ledger/repeating-journals/${id}`, b)
export const deleteRepeating  = (id) => http.delete(`/ledger/repeating-journals/${id}`)
export const runRepeating     = (as_at) => http.post('/ledger/repeating-journals/run', { as_at })
export const importJournals   = (b) => http.post('/ledger/journal-import', b)
export const importTemplateUrl = '/api/ledger/journal-import/template'
export const downloadImportTemplate = async () => {
  const r = await http.get('/ledger/journal-import/template', { responseType: 'blob' })
  const a = document.createElement('a'); a.href = URL.createObjectURL(r.data); a.download = 'journal-import-template.csv'; a.click()
}
export const fxRates          = (currency) => http.get('/ledger/fx-rates', { params: { currency } })
export const putFxRate        = (b) => http.put('/ledger/fx-rates', b)
export const deleteFxRate     = (id) => http.delete(`/ledger/fx-rates/${id}`)
export const fxRate           = (currency, date) => http.get('/ledger/fx-rate', { params: { currency, date } })
export const schedulerStatus  = () => http.get('/ledger/scheduler-status')
export const fxAccounts       = () => http.get('/ledger/fx/accounts')
export const setFxAccount     = (id, currency) => http.put(`/ledger/fx/accounts/${id}`, { currency: currency || null })
export const fxRevaluation    = (as_at) => http.get('/ledger/fx/revaluation', { params: { as_at } })
export const fxRevalue        = (b) => http.post('/ledger/fx/revalue', b)
export const fxGainsLosses    = (from, to) => http.get('/ledger/reports/fx-gains-losses', { params: { from, to } })
export const fxFeed           = () => http.get('/ledger/fx-feed')
export const fxFeedRun        = (b) => http.post('/ledger/fx-feed/run', b || {})
export const aiJournal        = (b) => http.post('/ledger/ai/journal-from-text', b)
export const aiReviewDraft    = (id) => http.post(`/ledger/ai/review-draft/${id}`)
export const aiExplainPL      = (b) => http.post('/ledger/ai/explain-profit-loss', b)
