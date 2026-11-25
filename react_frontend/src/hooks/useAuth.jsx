import React, { createContext, useContext, useState } from 'react'
import { login as apiLogin, getMyPlan, licenceMyModules } from '../lib/api.js'

const Ctx = createContext(null)

export function AuthProvider({ children }) {
  const [user, setUser] = useState(() => {
    try { return JSON.parse(localStorage.getItem('af_user')) } catch { return null }
  })
  const [loading, setLoading] = useState(false)

  const login = async (email, password) => {
    setLoading(true)
    try {
      const { data } = await apiLogin(email.trim(), password.trim())
      const roles = (data.roles || []).map(r => String(r).trim().toLowerCase())
      const u = {
        ...data,
        roles:    roles,
        is_admin: roles.includes('admin'),
      }

      // Fetch current plan and modules on login so they're always fresh
      try {
        const [planRes, modsRes] = await Promise.all([
          getMyPlan(data.id),
          licenceMyModules(data.id),
        ])
        u.plan      = planRes.data        // { plan_id, licence_type, end_date, modules }
        u.modules   = modsRes.data?.modules || []
      } catch { /* non-fatal */ }

      setUser(u)
      localStorage.setItem('af_user', JSON.stringify(u))
      // Notify Layout to re-apply module permissions
      window.dispatchEvent(new Event('accfino:modules-changed'))
      return { ok: true, user: u }
    } catch (e) {
      return { ok: false, error: e.response?.data?.detail || 'Invalid credentials' }
    } finally {
      setLoading(false)
    }
  }

  const logout = () => {
    setUser(null)
    localStorage.removeItem('af_user')
  }

  return <Ctx.Provider value={{ user, login, logout, loading }}>{children}</Ctx.Provider>
}

export const useAuth = () => useContext(Ctx)
