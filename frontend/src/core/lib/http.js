import axios from 'axios'
import { handleIamBlock, persistTokenFields } from './authFetch.js'

export const http = axios.create({ baseURL: '/api' })

export const errMsg = (e, fallback = 'Something went wrong') => {
  const d = e?.response?.data?.detail
  if (Array.isArray(d)) return d.map(x => x.msg || JSON.stringify(x)).join('; ')
  return d || e?.message || fallback
}

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
    // A 401 on a sign-in call means wrong credentials - let the login form show the message.
    // Any other 401 means the session ended - clear it and go to the login page.
    const url = err.config?.url || ''
    handleIamBlock(err.response?.status, err.response?.data)
    if (err.response?.status === 401 && !url.includes('/auth/login') && !url.includes('/auth/mfa/')) {
      localStorage.removeItem('af_user')
      window.location.href = '/login'
    }
    return Promise.reject(err)
  }
)



export default http
