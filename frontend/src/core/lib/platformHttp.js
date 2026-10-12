// Org-aware HTTP client (adds X-Org-Id) shared by the platform API and the ledger API.
import axios from 'axios'
import { currentOrgId, expireSession, handleIamBlock, persistTokenFields } from './authFetch.js'

// A request that gets no answer for 60 s ends with a readable error and a Retry button instead of an endless spinner.
export const REQUEST_TIMEOUT_MS = 60000
export const http = axios.create({ baseURL: '/api', timeout: REQUEST_TIMEOUT_MS })
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
  if (e?.code === 'ECONNABORTED') return 'The server took too long to answer (over 60 seconds). Try again; if it keeps happening the database connection is probably slow.'
  return d || e?.message || fallback
}

export const pub = axios.create({ baseURL: '/api' })   // sign-in steps: no session yet
