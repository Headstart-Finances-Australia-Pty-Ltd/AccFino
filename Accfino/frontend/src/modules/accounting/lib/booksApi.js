// Accounting: sales, purchases, banking, expenses, contacts, attachments, assets, inventory and ledger-derived reports
import { http } from '../../../core/lib/platformHttp.js'

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

export const uploadAttachment = (ownerKind, ownerId, file) => {
  const fd = new FormData(); fd.append('file', file)
  return http.post('/attachments', fd, { params: { owner_kind: ownerKind, owner_id: ownerId }, headers: { 'Content-Type': 'multipart/form-data' } })
}

export const attachmentDownloadUrl = id => `/api/attachments/${id}/download`

export const deleteAttachment = id => http.delete(`/attachments/${id}`)

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

export const ledgerAccounts = (includeInactive=false) => http.get('/ledger/accounts', { params: { include_inactive: includeInactive } })

export const taxCodes       = () => http.get('/ledger/tax-codes')

export const listStockItems    = (params)          => http.get('/inventory/items', { params })

export const getStockItem      = (id)               => http.get(`/inventory/items/${id}`)

export const createStockItem   = (body)             => http.post('/inventory/items', body)

export const updateStockItem   = (id, body)         => http.put(`/inventory/items/${id}`, body)

export const deleteStockItem   = (id)               => http.delete(`/inventory/items/${id}`)

export const itemMovements     = (id)               => http.get(`/inventory/items/${id}/movements`)

export const recordMovement    = (id, body)         => http.post(`/inventory/items/${id}/movements`, body)

export const inventoryValuation = ()                => http.get('/inventory/valuation')

export const inventoryControl  = (asAt)             => http.get('/inventory/control', { params: { as_at: asAt } })

export const listAssets        = (params)           => http.get('/assets', { params })

export const getAsset          = (id)               => http.get(`/assets/${id}`)

export const createAsset       = (body)             => http.post('/assets', body)

export const updateAsset       = (id, body)         => http.put(`/assets/${id}`, body)

export const deleteAsset       = (id)               => http.delete(`/assets/${id}`)

export const runDepreciation   = (body)             => http.post('/assets/depreciation/run', body)

export const disposeAsset      = (id, body)         => http.post(`/assets/${id}/dispose`, body)

export const assetRegister     = ()                 => http.get('/assets/register')

export const assetControl      = (asAt)             => http.get('/assets/control', { params: { as_at: asAt } })

export const getBudget      = (params) => http.get('/ledger/reports/budget', { params })

export const saveBudget     = (body)   => http.put('/ledger/reports/budget', body)

export const generateBudget = (body)   => http.post('/ledger/reports/budget/generate', body)

export const ledgerReportMulti = (path, params) => http.get(`/ledger/reports/${path}`, { params, paramsSerializer: { indexes: null } })

export const downloadAttachment = async (id, filename) => {
  const r = await http.get(`/attachments/${id}/download`, { responseType: 'blob' })
  const a = document.createElement('a'); a.href = URL.createObjectURL(r.data); a.download = filename || 'attachment'; a.click()
}

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

export const bulkImportStatus = ()        => http.get('/imports/status')
