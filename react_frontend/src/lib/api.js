import axios from 'axios'

const http = axios.create({ baseURL: '/api' })

// Attach JWT token to every request automatically
http.interceptors.request.use(cfg => {
  try {
    const u = JSON.parse(localStorage.getItem('af_user') || '{}')
    if (u?.token) cfg.headers['Authorization'] = `Bearer ${u.token}`
  } catch {}
  return cfg
})

// Redirect to login on 401
http.interceptors.response.use(
  res => res,
  err => {
    if (err.response?.status === 401) {
      localStorage.removeItem('af_user')
      window.location.href = '/login'
    }
    return Promise.reject(err)
  }
)

// ── Auth ──────────────────────────────────────────────────────────────────────
export const login          = (email, pw)    => http.post('/auth/login', { email, password: pw })
export const register       = (data)         => http.post('/auth/register', data)
export const changePassword = (data)         => http.post('/auth/change-password', data)
export const getAllUsers     = ()             => http.get('/auth/users')
export const deleteUser     = (id)           => http.delete(`/auth/users/${id}`)

// ── Sessions ──────────────────────────────────────────────────────────────────
export const getSessions   = (u)             => http.get('/sessions', { params: { username: u } })
export const getSession    = (u, sid)        => http.get(`/sessions/${u}/${sid}`)
export const deleteSession = (u, sid)        => http.delete(`/sessions/${u}/${sid}`)
export const saveSession   = (body)          => http.post('/sessions/save', body)

// ── Banks / GST ───────────────────────────────────────────────────────────────
export const getBanks        = ()            => http.get('/banks')
export const getGstCategories= ()            => http.get('/gst/categories')
export const calcGST         = (d,c,cat)     => http.get('/gst/calculate', { params:{debit:d,credit:c,category:cat} })

// ── Reconciliation ────────────────────────────────────────────────────────────
export const processFiles  = (fd)            => http.post('/reconcile/process', fd, { headers:{'Content-Type':'multipart/form-data'} })
export const classifyGL    = (sid, u)        => http.post('/reconcile/classify',   { session_id:sid, username:u })
export const reclassifyGL  = (sid, u)        => http.post('/reconcile/reclassify', { session_id:sid, username:u })
export const exportExcel   = (txns)          => http.post('/reconcile/export', { transactions:txns }, { responseType:'blob' })

// ── Transactions (DB) ─────────────────────────────────────────────────────────
export const saveToDB      = (uid, txns)     => http.post('/transactions/save', { user_id:uid, transactions:txns })
export const getUserTxns   = (uid)           => http.get(`/transactions/user/${uid}`)
export const getDbStats    = (uid)           => http.get(`/db/stats/${uid}`)
export const clearUserDb   = (uid)           => http.delete(`/db/transactions/${uid}`)
export const getAccountBalances  = (uid)     => http.get(`/account-balances/${uid}`)
export const upsertAccountBalance= (body)    => http.post('/account-balances', body)
export const bulkUpsertBalances  = (body)    => http.post('/account-balances/bulk', body)

// ── Trading ───────────────────────────────────────────────────────────────────
export const tradingAnalyze = (fd)           => http.post('/trading/analyze', fd, { headers:{'Content-Type':'multipart/form-data'} })
export const tradingExport  = (fd)           => http.post('/trading/export', fd, { headers:{'Content-Type':'multipart/form-data'}, responseType:'blob' })

// ── Cash Flow ─────────────────────────────────────────────────────────────────
export const cfDetect       = (fd)           => http.post('/cashflow/detect', fd, { headers:{'Content-Type':'multipart/form-data'} })
export const cfRun          = (rows, colMap) => http.post('/cashflow/run', { rows, col_map:colMap })
export const cfPredict      = (runId, model) => http.post(`/cashflow/predict/${runId}`, model, { headers:{'Content-Type':'application/json'} })

// ── ML Classifier ─────────────────────────────────────────────────────────────
export const mlStatus      = ()              => http.get('/ml/status')
export const mlSampleCsv   = ()              => http.get('/ml/sample-csv', { responseType:'blob' })
export const mlTrain       = (fd)            => http.post('/ml/train', fd, { headers:{'Content-Type':'multipart/form-data'} })

// ── RDR Rules ─────────────────────────────────────────────────────────────────
export const kbGet            = ()                    => http.get('/kb')
export const kbVendorUpsert   = (key, entry)           => http.put(`/kb/vendor/${encodeURIComponent(key)}`, entry)
export const kbVendorDelete   = (key)                  => http.delete(`/kb/vendor/${encodeURIComponent(key)}`)
export const kbKeywordUpsert  = (kw, entry)            => http.put(`/kb/keyword/${encodeURIComponent(kw)}`, entry)
export const kbKeywordDelete  = (kw)                   => http.delete(`/kb/keyword/${encodeURIComponent(kw)}`)
export const kbMetaUpdate     = (body)                 => http.put('/kb/meta', body)
export const coaAccounts  = ()              => http.get('/coa/accounts')
export const rdrList       = ()              => http.get('/rdr/rules')
export const rdrCreate     = (rule)          => http.post('/rdr/rules', rule)
export const rdrUpdate     = (id, rule)      => http.put(`/rdr/rules/${id}`, rule)
export const rdrDelete     = (id)            => http.delete(`/rdr/rules/${id}`)
export const rdrTest       = (body)          => http.post('/rdr/test', body)

// ── Invoice Extractor ─────────────────────────────────────────────────────────
export const ieStatus      = ()              => http.get('/invoice-extractor/status')
export const ieProcess     = (fd)            => http.post('/invoice-extractor/process', fd, { headers:{'Content-Type':'multipart/form-data'} })

// ── Invoice (DB) ──────────────────────────────────────────────────────────────
export const invoiceGetBusinesses  = ()      => http.get('/invoice/businesses')
export const invoiceCreateBusiness = (data)  => http.post('/invoice/businesses', data)
export const invoiceGetAll   = (bid)         => http.get(`/invoice/businesses/${bid}/invoices`)
export const invoiceCreate   = (data)        => http.post('/invoice/invoices', data)
export const invoiceGetOne   = (id)          => http.get(`/invoice/invoices/${id}`)
export const invoiceNextNum  = ()            => http.get('/invoice/next-number')
export const invoiceUpdateStatus = (id,stat) => http.patch(`/invoice/invoices/${id}/status`, { status:stat })

// ── Open Banking ─────────────────────────────────────────────────────────────
export const obStatus      = ()              => http.get('/openbanking/status')
export const obCreateUser  = (data)          => http.post('/openbanking/create-user', data)
export const obAccounts    = (uid)           => http.get(`/openbanking/accounts/${uid}`)
export const obTransactions= (uid)           => http.get(`/openbanking/transactions/${uid}`)

export default http

// ── Stock / Equity Trading ────────────────────────────────────────────────────
export const stocksStatus  = ()            => http.get('/stocks/status')
export const stocksAnalyze = (fd)          => http.post('/stocks/analyze', fd, { headers:{'Content-Type':'multipart/form-data'} })
export const stocksExport  = (fd)          => http.post('/stocks/export',  fd, { headers:{'Content-Type':'multipart/form-data'}, responseType:'blob' })

// ── Open Banking → normalised CSV ────────────────────────────────────────────
export const obFetchNormalise = (body)     => http.post('/openbanking/fetch-and-normalise', body)

export const getDashboardStats = (username) => http.get('/dashboard/stats', { params: { username } })

// ── File Manager ──────────────────────────────────────────────────────────────
export const fmTree      = ()           => http.get('/filemanager/tree')
export const fmRead      = (path, tbl)  => http.get(`/filemanager/read/${encodeURIComponent(path)}`, { params: { table: tbl||'' } })
export const fmSave      = (body)       => http.post('/filemanager/save', body)
export const fmDeleteRow = (body)       => http.delete('/filemanager/delete-row', { data: body })

// ── Licence Management ────────────────────────────────────────────────────────
export const licenceList       = ()          => http.get('/licence/list')
export const licenceSave       = (body)      => http.post('/licence/save', body)
export const licenceDeleteUser = (uid)       => http.delete(`/licence/user/${uid}`)
export const licenceMyModules  = (uid)       => http.get('/licence/my-modules', { params: { user_id: uid } })
export const licenceUpdateUser = (uid, body) => http.patch(`/licence/user/${uid}`, body)

// ── Password Reset ────────────────────────────────────────────────────────────
export const forgotPassword   = (email)     => http.post('/auth/forgot-password', { email })
export const resetPassword    = (token, pw) => http.post('/auth/reset-password', { token, new_password: pw })
export const verifyResetToken = (token)     => http.get('/auth/verify-reset-token', { params: { token } })

// ── Payments ──────────────────────────────────────────────────────────────────
export const getPlans       = ()     => http.get('/payments/plans')
export const createCheckout = (body) => http.post('/payments/create-checkout', body)
export const getMyPlan      = (uid)  => http.get(`/payments/my-plan/${uid}`)
export const adminActivate  = (body) => http.post('/payments/admin/activate', body)
export const activateAfterPayment = (body) => http.post('/payments/activate-after-payment', body)

// ── Pricing Management (admin) ────────────────────────────────────────────────
export const getPricingPlans    = ()              => http.get('/pricing/plans')

// Home company — used for internal transfer auto-detection
export const getHomeCompany = (username)          => http.get('/profile/home-company', { params: { username } })
export const setHomeCompany = (username, company) => http.post('/profile/home-company', { username, home_company: company })

// Company database — search, list, manage
export const companySearch   = (q)           => http.get('/company/search', { params: { q } })
export const companyList     = (params)      => http.get('/company/list', { params })
export const companyCreate   = (data)        => http.post('/company', data)
export const companyUpdate   = (id, data)    => http.put(`/company/${id}`, data)
export const companyDelete   = (id)          => http.delete(`/company/${id}`)
export const companyAddAlias = (id, alias)   => http.post(`/company/${id}/alias`, alias)
export const companyDelAlias = (id, alias)   => http.delete(`/company/${id}/alias/${encodeURIComponent(alias)}`)
export const companyApprove  = (id)          => http.post(`/company/approve/${id}`)
export const companyCategories = ()          => http.get('/company/categories')
export const savePricingPlans   = (data)          => http.post('/pricing/plans', data)
export const updatePricingPlan  = (planId, data)  => http.patch(`/pricing/plans/${planId}`, data)
export const processFilesWithSession = (fd) =>
  http.post('/reconcile/process-with-session', fd, { headers: { 'Content-Type': 'multipart/form-data' } })
export const captureWho = (who, desc, username) =>
  http.post('/company/capture-who', { who, description: desc, username })