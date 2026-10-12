// Accounting module API calls
// All calls go through the existing http axios instance already set up in api.js
// Import this alongside api.js in accounting pages

import axios from 'axios'

const http = axios.create({
  baseURL: '/api',
  withCredentials: true,
})

// Intercept to attach auth token
http.interceptors.request.use(cfg => {
  try {
    const u = JSON.parse(localStorage.getItem('af_user') || '{}')
    if (u.token) cfg.headers['Authorization'] = `Bearer ${u.token}`
  } catch {}
  return cfg
})

// ── Documents ─────────────────────────────────────────────────────────────────
export const listDocuments  = (userId, type, status) =>
  http.get('/accounting/documents', { params: { user_id: userId, document_type: type, status } })

export const getDocument    = (id, userId) =>
  http.get(`/accounting/documents/${id}`, { params: { user_id: userId } })

export const createDocument = (body)           => http.post('/accounting/documents', body)
export const patchDocument  = (id, userId, b)  => http.patch(`/accounting/documents/${id}`, b, { params: { user_id: userId } })
export const deleteDocument = (id, userId)     => http.delete(`/accounting/documents/${id}`, { params: { user_id: userId } })
export const convertToInvoice = (id, userId)   => http.post(`/accounting/documents/${id}/convert`, {}, { params: { user_id: userId } })

// ── Purchase extraction ───────────────────────────────────────────────────────
export const extractPurchase = (formData) =>
  http.post('/accounting/purchase/extract', formData, {
    headers: { 'Content-Type': 'multipart/form-data' },
    timeout: 120000,
  })

// ── Suppliers ─────────────────────────────────────────────────────────────────
export const listSuppliers   = (userId)        => http.get('/accounting/suppliers',    { params: { user_id: userId } })
export const createSupplier  = (body)          => http.post('/accounting/suppliers',    body)
export const patchSupplier   = (id, userId, b) => http.patch(`/accounting/suppliers/${id}`, b, { params: { user_id: userId } })
export const deleteSupplier  = (id, userId)    => http.delete(`/accounting/suppliers/${id}`, { params: { user_id: userId } })

// ── Customers ─────────────────────────────────────────────────────────────────
export const listCustomers   = (userId)        => http.get('/accounting/customers',    { params: { user_id: userId } })
export const createCustomer  = (body)          => http.post('/accounting/customers',    body)
export const patchCustomer   = (id, userId, b) => http.patch(`/accounting/customers/${id}`, b, { params: { user_id: userId } })
export const deleteCustomer  = (id, userId)    => http.delete(`/accounting/customers/${id}`, { params: { user_id: userId } })
export const importCustomersCSV = (fd)         => http.post('/accounting/customers/csv-import', fd, { headers: { 'Content-Type': 'multipart/form-data' } })
export const importSuppliersCSV = (fd)         => http.post('/accounting/suppliers/csv-import', fd, { headers: { 'Content-Type': 'multipart/form-data' } })

// ── Stats ─────────────────────────────────────────────────────────────────────
export const accountingStats = (userId) => http.get(`/accounting/stats/${userId}`)

// ── Next document number helper ───────────────────────────────────────────────
export const nextDocNumber = () => http.get('/invoice/next-number')
