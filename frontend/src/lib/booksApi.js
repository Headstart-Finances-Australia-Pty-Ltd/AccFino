// Phase 1 "Books & Accounting" API client: sales, purchases, banking, expenses, contacts,
// attachments and the ledger-derived reports. Same conventions as platformApi.js (auth token +
// X-Org-Id attached automatically, 401 -> sign-out).
import axios from 'axios'
import { currentOrgId, expireSession, handleIamBlock } from './authFetch.js'

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

// ── Sales / Purchases (one shape, two base paths - mirrors the backend's own factory) ─────────
export const SIDE = {
  sales:     { base: '/sales',     quote: 'quotes',  main: 'invoices', credit: 'credit-notes', contacts: 'customers', role: 'customer' },
  purchases: { base: '/purchases', quote: 'orders',  main: 'bills',    credit: 'credits',      contacts: 'suppliers', role: 'supplier' },
}

export const listContacts   = (side, params)      => http.get(`${SIDE[side].base}/${SIDE[side].contacts}`, { params })
export const getContact     = (side, id)          => http.get(`${SIDE[side].base}/${SIDE[side].contacts}/${id}`)
export const createContact  = (side, body)        => http.post(`${SIDE[side].base}/${SIDE[side].contacts}`, body)
export const patchContact   = (side, id, body)    => http.patch(`${SIDE[side].base}/${SIDE[side].contacts}/${id}`, body)
export const importContactsCSV = (role, file) => {
  const fd = new FormData(); fd.append('file', file)
  return http.post('/contacts/import', fd, { params: { role }, headers: { 'Content-Type': 'multipart/form-data' } })
}

const segFor = (side, kind) => SIDE[side][kind]
export const listDocs   = (side, kind, params)   => http.get(`${SIDE[side].base}/${segFor(side, kind)}`, { params })
export const getDoc     = (side, kind, id)       => http.get(`${SIDE[side].base}/${segFor(side, kind)}/${id}`)
export const createDoc  = (side, kind, body)     => http.post(`${SIDE[side].base}/${segFor(side, kind)}`, body)
export const updateDoc  = (side, kind, id, body) => http.put(`${SIDE[side].base}/${segFor(side, kind)}/${id}`, body)
export const deleteDoc  = (side, kind, id)       => http.delete(`${SIDE[side].base}/${segFor(side, kind)}/${id}`)
export const approveDoc = (side, kind, id)       => http.post(`${SIDE[side].base}/${segFor(side, kind)}/${id}/approve`)
export const voidDoc    = (side, kind, id)       => http.post(`${SIDE[side].base}/${segFor(side, kind)}/${id}/void`)
export const sendDoc    = (side, kind, id)       => http.post(`${SIDE[side].base}/${segFor(side, kind)}/${id}/send`)
// The print endpoint returns a ready-to-print HTML page (not JSON) - fetched as text and opened in
// a new tab via a blob URL, since window.open(url) can't carry the Authorization header itself.
export const fetchPrintHtml = (side, kind, id) => http.get(`${SIDE[side].base}/${segFor(side, kind)}/${id}/print`, { responseType: 'text' })
export function openPrintable(html) {
  const blob = new Blob([html], { type: 'text/html' })
  const url = URL.createObjectURL(blob)
  const w = window.open(url, '_blank')
  if (!w) return false
  setTimeout(() => URL.revokeObjectURL(url), 30000)
  return true
}
export const acceptQuote  = (side, id)           => http.post(`${SIDE[side].base}/${SIDE[side].quote}/${id}/accept`)
export const declineQuote = (side, id)           => http.post(`${SIDE[side].base}/${SIDE[side].quote}/${id}/decline`)
export const convertQuote = (side, id)           => http.post(`${SIDE[side].base}/${SIDE[side].quote}/${id}/convert`)
export const payDoc     = (side, kind, id, body) => http.post(`${SIDE[side].base}/${segFor(side, kind)}/${id}/payments`, body)
export const allocateCredit = (side, id, body)   => http.post(`${SIDE[side].base}/${SIDE[side].credit}/${id}/allocate`, body)
export const refundCredit   = (side, id, body)   => http.post(`${SIDE[side].base}/${SIDE[side].credit}/${id}/refund`, body)

export const listPayments   = (side, params)     => http.get(`${SIDE[side].base}/payments`, { params })
export const createPayment  = (side, body)       => http.post(`${SIDE[side].base}/payments`, body)
export const getPayment     = (side, id)         => http.get(`${SIDE[side].base}/payments/${id}`)
export const allocatePayment = (side, id, body)  => http.post(`${SIDE[side].base}/payments/${id}/allocate`, body)
export const reversePayment  = (side, id)        => http.delete(`${SIDE[side].base}/payments/${id}`)

export const salesReport     = (path, params) => http.get(`/sales/reports/${path}`, { params })
export const purchasesReport = (path, params) => http.get(`/purchases/reports/${path}`, { params })
export const ledgerReport    = (path, params) => http.get(`/ledger/reports/${path}`, { params })

export const booksSettings      = ()     => http.get('/org/current/books-settings')
export const saveBooksSettings  = (body) => http.put('/org/current/books-settings', body)

// ── Attachments ──────────────────────────────────────────────────────────────────────────────
export const uploadAttachment = (ownerKind, ownerId, file) => {
  const fd = new FormData(); fd.append('file', file)
  return http.post('/attachments', fd, { params: { owner_kind: ownerKind, owner_id: ownerId }, headers: { 'Content-Type': 'multipart/form-data' } })
}
export const attachmentDownloadUrl = id => `/api/attachments/${id}/download`
export const deleteAttachment = id => http.delete(`/attachments/${id}`)

// ── Banking ──────────────────────────────────────────────────────────────────────────────────
export const bankAccounts       = ()               => http.get('/banking/accounts')
export const createBankAccount  = (body)            => http.post('/banking/accounts', body)
export const importBankLines    = (body)            => http.post('/banking/lines/import', body)
export const importBankCSV      = (bankAccount, file) => {
  const fd = new FormData(); fd.append('file', file); fd.append('bank_account', bankAccount)
  return http.post('/banking/lines/import-csv', fd, { headers: { 'Content-Type': 'multipart/form-data' } })
}
export const listBankLines      = (params)          => http.get('/banking/lines', { params })
export const suggestMatches     = (body)            => http.post('/banking/reconcile/suggest', body)
export const matchLine          = (id, body)        => http.post(`/banking/lines/${id}/match`, body)
export const codeLine           = (id, body)        => http.post(`/banking/lines/${id}/create`, body)
export const transferLine       = (id, body)        => http.post(`/banking/lines/${id}/transfer`, body)
export const excludeLine        = (id)              => http.post(`/banking/lines/${id}/exclude`)
export const unreconcileLine    = (id, body={})     => http.post(`/banking/lines/${id}/unreconcile`, body)
export const autoReconcile      = (body={})         => http.post('/banking/reconcile/auto', body)
export const reconciliationReport = (accountId, params) => http.get(`/banking/reconciliation/${accountId}`, { params })
export const listRules          = ()                => http.get('/banking/rules')
export const createRule         = (body)            => http.post('/banking/rules', body)
export const updateRule         = (id, body)        => http.put(`/banking/rules/${id}`, body)
export const deleteRule         = (id)              => http.delete(`/banking/rules/${id}`)
export const classifierSuggest  = (body)            => http.post('/banking/classifier/suggest', body)
export const classifierFeedback = (body)            => http.post('/banking/classifier/feedback', body)

// ── Expenses ─────────────────────────────────────────────────────────────────────────────────
export const listClaims    = (params)      => http.get('/expenses/claims', { params })
export const getClaim      = (id)          => http.get(`/expenses/claims/${id}`)
export const createClaim   = (body)        => http.post('/expenses/claims', body)
export const updateClaim   = (id, body)    => http.put(`/expenses/claims/${id}`, body)
export const deleteClaim   = (id)          => http.delete(`/expenses/claims/${id}`)
export const submitClaim   = (id)          => http.post(`/expenses/claims/${id}/submit`)
export const approveClaim  = (id)          => http.post(`/expenses/claims/${id}/approve`)
export const rejectClaim   = (id, reason)  => http.post(`/expenses/claims/${id}/reject`, { reason })
export const unapproveClaim = (id)         => http.post(`/expenses/claims/${id}/unapprove`)
export const reimburseClaim = (id, body)   => http.post(`/expenses/claims/${id}/reimburse`, body)
export const claimsSummary  = ()           => http.get('/expenses/summary')

// ── Ledger accounts / tax codes (Phase 0, reused here for pickers) ────────────────────────────
export const ledgerAccounts = (includeInactive=false) => http.get('/ledger/accounts', { params: { include_inactive: includeInactive } })
export const taxCodes       = () => http.get('/ledger/tax-codes')

// ── Inventory ────────────────────────────────────────────────────────────────────────────────
export const listStockItems    = (params)          => http.get('/inventory/items', { params })
export const getStockItem      = (id)               => http.get(`/inventory/items/${id}`)
export const createStockItem   = (body)             => http.post('/inventory/items', body)
export const updateStockItem   = (id, body)         => http.put(`/inventory/items/${id}`, body)
export const deleteStockItem   = (id)               => http.delete(`/inventory/items/${id}`)
export const itemMovements     = (id)               => http.get(`/inventory/items/${id}/movements`)
export const recordMovement    = (id, body)         => http.post(`/inventory/items/${id}/movements`, body)
export const inventoryValuation = ()                => http.get('/inventory/valuation')
export const inventoryControl  = (asAt)             => http.get('/inventory/control', { params: { as_at: asAt } })

// ── Fixed Assets ─────────────────────────────────────────────────────────────────────────────
export const listAssets        = (params)           => http.get('/assets', { params })
export const getAsset          = (id)               => http.get(`/assets/${id}`)
export const createAsset       = (body)             => http.post('/assets', body)
export const updateAsset       = (id, body)         => http.put(`/assets/${id}`, body)
export const deleteAsset       = (id)               => http.delete(`/assets/${id}`)
export const runDepreciation   = (body)             => http.post('/assets/depreciation/run', body)
export const disposeAsset      = (id, body)         => http.post(`/assets/${id}/dispose`, body)
export const assetRegister     = ()                 => http.get('/assets/register')
export const assetControl      = (asAt)             => http.get('/assets/control', { params: { as_at: asAt } })

// ── Budgets (Budget Variance report) ─────────────────────────────────────────────────────────
export const getBudget      = (params) => http.get('/ledger/reports/budget', { params })
export const saveBudget     = (body)   => http.put('/ledger/reports/budget', body)
export const generateBudget = (body)   => http.post('/ledger/reports/budget/generate', body)

// Reports that take repeated query keys (?account_ids=1&account_ids=2) - axios would otherwise send account_ids[]=1
export const ledgerReportMulti = (path, params) => http.get(`/ledger/reports/${path}`, { params, paramsSerializer: { indexes: null } })
export const downloadAttachment = async (id, filename) => {
  const r = await http.get(`/attachments/${id}/download`, { responseType: 'blob' })
  const a = document.createElement('a'); a.href = URL.createObjectURL(r.data); a.download = filename || 'attachment'; a.click()
}

// ── CSV bulk import (/imports): check first (dry run), then import - all-or-nothing ────────────
export const importCatalogue = () => http.get('/imports')
export const importCsv = (entity, file, { dryRun = true, mode, amountsAre } = {}) => {
  const fd = new FormData()
  fd.append('file', file)
  fd.append('dry_run', dryRun ? 'true' : 'false')
  if (mode) fd.append('mode', mode)
  if (amountsAre) fd.append('amounts_are', amountsAre)
  return http.post(`/imports/${entity}`, fd, { headers: { 'Content-Type': 'multipart/form-data' } })
}
export const downloadImportTemplateFor = async entity => {
  const r = await http.get(`/imports/${entity}/template`, { responseType: 'blob' })
  const a = document.createElement('a'); a.href = URL.createObjectURL(r.data); a.download = `${entity}-template.csv`; a.click()
}

// ── Platform switch: bulk data import on/off (Admin > Modules Management) ──────────────────────
export const bulkImportStatus = ()        => http.get('/imports/status')
export const adminGetBulkImport = ()      => http.get('/admin/bulk-import')
export const adminSetBulkImport = enabled => http.put('/admin/bulk-import', { enabled })
// Force delete (Admin > Modules Management): the on/off switch, and bulk delete of users / organisations (an organisation takes its users with it)
export const adminGetForceDelete   = ()              => http.get('/admin/force-delete/settings')
export const adminSetForceDelete   = enabled         => http.put('/admin/force-delete/settings', { enabled })
export const adminOrgDirectory     = ()              => http.get('/admin/org-directory', { params: { _t: Date.now() }, headers: { 'Cache-Control': 'no-cache' } })
export const adminPruneEmptyOrgs   = ()              => http.post('/admin/org-directory/prune-empty')
export const adminPruneOrphanUsers = ()              => http.post('/admin/org-directory/prune-orphan-users')
export const adminBulkDeleteUsers  = (ids, force)    => http.post('/admin/force-delete/users', { ids, force: !!force })
export const adminBulkDeleteOrgs   = (ids, force)    => http.post('/admin/force-delete/organisations', { ids, force: !!force })

// ── Subscriptions (per organisation) ───────────────────────────────────────────────────────────
export const adminOpenBanking    = ()              => http.get('/admin/open-banking', { params: { _t: Date.now() } })
export const adminSaveBasiq      = (body)          => http.put('/admin/open-banking/basiq', body)
export const adminTestBasiq      = ()              => http.post('/admin/open-banking/basiq/test')
export const getBilling          = ()              => http.get('/org/current/billing', { params: { _t: Date.now() } })
export const saveBillingCard     = (source_id)     => http.post('/org/current/billing/card', { source_id })
export const deleteBillingCard   = ()              => http.delete('/org/current/billing/card')
export const billingSubscribe    = (billing_period) => http.post('/org/current/billing/subscribe', { billing_period })
export const billingAutoRenew    = (enabled)       => http.post('/org/current/billing/auto-renew', { enabled })
export const adminSquareStatus   = ()              => http.get('/admin/billing/square')
export const adminSaveSquare     = (body)          => http.put('/admin/billing/square', body)
export const adminTestSquare     = ()              => http.post('/admin/billing/square/test')
export const adminBillingOverview = ()             => http.get('/admin/billing/overview', { params: { _t: Date.now() } })
export const adminRunBilling     = ()              => http.post('/admin/billing/run')
export const obFeedStatus       = ()              => http.get('/org/current/open-banking')
export const obFeedConnect      = (return_to, popup_origin) => http.post('/org/current/open-banking/connect', { return_to, popup_origin })
export const obFeedSetAccount   = (account_id, enabled) => http.post('/org/current/open-banking/account', { account_id, enabled })
export const obFeedSync         = ()              => http.post('/org/current/open-banking/sync')
export const obFeedDisconnect   = ()              => http.post('/org/current/open-banking/disconnect')
export const getSubscription      = ()              => http.get('/org/current/subscription')
export const requestSubscription  = body            => http.post('/org/current/subscription/request', body)
export const adminSubOverview     = ()              => http.get('/admin/subscriptions')
export const adminSubSettings     = body            => http.put('/admin/subscriptions/settings', body)
export const adminSavePlan        = (id, body)      => http.put(`/admin/subscriptions/plans/${id}`, body)
export const adminDeletePlan      = id              => http.delete(`/admin/subscriptions/plans/${id}`)
export const adminSaveAddon       = (id, body)      => http.put(`/admin/subscriptions/addons/${id}`, body)
export const adminDeleteAddon     = id              => http.delete(`/admin/subscriptions/addons/${id}`)
export const adminAssignOrgPlan   = (orgId, body)   => http.put(`/admin/subscriptions/orgs/${orgId}`, body)

// ── Organisation-first signup (public) and invitation management (owner/admin) ─────────────────
export const tenantCurrent       = ()            => http.get('/tenant/current')
export const signupValidateOrg   = org           => http.post('/signup/organisation/validate', org)
export const signupCreateOrg     = body          => http.post('/signup/organisation', body)
export const signupSearchOrgs    = q             => http.get('/signup/organisations/search', { params: { q } })
export const signupLookupOrg     = slug          => http.get('/signup/organisations/lookup', { params: { slug } })
export const signupVerifyCode    = (slug, code)  => http.post('/signup/verify-code', { slug, code })
export const signupJoin          = body          => http.post('/signup/join', body)
export const contactConfig       = ()            => http.get('/signup/contact/config')
export const contactSend         = (channel, destination)       => http.post('/signup/contact/send', { channel, destination })
export const contactVerify       = (channel, destination, code) => http.post('/signup/contact/verify', { channel, destination, code })
export const listInvites         = ()            => http.get('/org/current/invites')
export const createInvites       = body          => http.post('/org/current/invites', body)
export const revokeInvite        = id            => http.delete(`/org/current/invites/${id}`)
export const getTenantProfile    = ()            => http.get('/org/current/tenant')
export const patchTenantProfile  = body          => http.patch('/org/current/tenant', body)
