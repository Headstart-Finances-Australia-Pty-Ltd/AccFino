// reconciliation module API client
import http from '../../../core/lib/http.js'

export const getSessions   = (u)             => http.get('/sessions', { params: { username: u } })

export const getSession    = (u, sid)        => http.get(`/sessions/${u}/${sid}`)

export const deleteSession = (u, sid)        => http.delete(`/sessions/${u}/${sid}`)

export const saveSession   = (body)          => http.post('/sessions/save', body)

export const getBanks        = ()            => http.get('/banks')

export const getGstCategories= ()            => http.get('/gst/categories')

export const calcGST         = (d,c,cat)     => http.get('/gst/calculate', { params:{debit:d,credit:c,category:cat} })

export const processFiles  = (fd)            => http.post('/reconcile/process', fd, { headers:{'Content-Type':'multipart/form-data'} })

export const classifyGL    = (sid, u)        => http.post('/reconcile/classify',   { session_id:sid, username:u })

export const reclassifyGL  = (sid, u)        => http.post('/reconcile/reclassify', { session_id:sid, username:u })

export const exportExcel   = (txns)          => http.post('/reconcile/export', { transactions:txns }, { responseType:'blob' })

export const saveToDB      = (uid, txns)     => http.post('/transactions/save', { user_id:uid, transactions:txns })

export const getUserTxns   = (uid)           => http.get(`/transactions/user/${uid}`)

export const getDbStats    = (uid)           => http.get(`/db/stats/${uid}`)

export const clearUserDb   = (uid)           => http.delete(`/db/transactions/${uid}`)

export const getAccountBalances  = (uid)     => http.get(`/account-balances/${uid}`)

export const upsertAccountBalance= (body)    => http.post('/account-balances', body)

export const bulkUpsertBalances  = (body)    => http.post('/account-balances/bulk', body)

export const mlStatus      = ()              => http.get('/ml/status')

export const mlSampleCsv   = ()              => http.get('/ml/sample-csv', { responseType:'blob' })

export const mlTrain       = (fd)            => http.post('/ml/train', fd, { headers:{'Content-Type':'multipart/form-data'} })

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

export const getDashboardStats = (username) => http.get('/dashboard/stats', { params: { username } })

export const getHomeCompany = (username)          => http.get('/profile/home-company', { params: { username } })

export const setHomeCompany = (username, company) => http.post('/profile/home-company', { username, home_company: company })

export const companySearch   = (q)           => http.get('/company/search', { params: { q } })

export const companyList     = (params)      => http.get('/company/list', { params })

export const companyCreate   = (data)        => http.post('/company', data)

export const companyUpdate   = (id, data)    => http.put(`/company/${id}`, data)

export const companyDelete   = (id)          => http.delete(`/company/${id}`)

export const companyAddAlias = (id, alias)   => http.post(`/company/${id}/alias`, alias)

export const companyDelAlias = (id, alias)   => http.delete(`/company/${id}/alias/${encodeURIComponent(alias)}`)

export const companyApprove  = (id)          => http.post(`/company/approve/${id}`)

export const companyCategories = ()          => http.get('/company/categories')

export const processFilesWithSession = (fd) =>
  http.post('/reconcile/process-with-session', fd, { headers: { 'Content-Type': 'multipart/form-data' } })

export const captureWho = (who, desc, username) =>
  http.post('/company/capture-who', { who, description: desc, username })
