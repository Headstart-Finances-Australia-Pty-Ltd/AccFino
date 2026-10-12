/**
 * Smart Lending API helpers
 */
import axios from 'axios'

const http = axios.create({ baseURL: '/api', withCredentials: true })
http.interceptors.request.use(cfg => {
  try { const u = JSON.parse(localStorage.getItem('af_user')||'{}'); if (u.token) cfg.headers['Authorization'] = `Bearer ${u.token}` } catch {}
  return cfg
})

/** Upload multiple files (PDF + CSV + image) in one shot */
export const uploadMultipleStatements = (formData, onProgress) =>
  http.post('/lending/upload-multi', formData, {
    headers: { 'Content-Type': 'multipart/form-data' },
    onUploadProgress: onProgress,
  })

/** Single file upload (backward compat) */
export const uploadStatement = (formData) =>
  http.post('/lending/upload', formData, { headers: { 'Content-Type': 'multipart/form-data' } })

export const analyseTransactions   = (body) => http.post('/lending/analyse', body)
export const classifyTransactions  = (txns) => http.post('/lending/classify', txns)
export const getLendingCategories  = ()     => http.get('/lending/categories')
export const getRegulatoryInfo     = ()     => http.get('/lending/regulatory')
