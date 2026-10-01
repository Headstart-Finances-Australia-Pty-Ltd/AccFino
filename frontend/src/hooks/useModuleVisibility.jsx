import React, { createContext, useContext, useEffect, useState, useCallback } from 'react'
import { getModuleVisibility } from '../lib/api.js'
import * as books from '../lib/booksApi.js'

// Which business domains and modules an admin has switched on/off platform-wide
// (side panel, hub page tabs, Home page and the public landing page). Fetched
// once here and shared via context; the Admin > Modules page dispatches
// 'accfino:module-visibility-changed' after saving so every open tab picks up
// the change immediately, the same pattern UpgradeBanner uses for plan changes.
const ModuleVisibilityContext = createContext({
  loaded: false,
  isDomainVisible: () => true,
  isModuleVisible: () => true,
  raw: { domains: {}, modules: {} },
  subscription: null,
  isLocked: () => false,
})

export function ModuleVisibilityProvider({ children }) {
  const [raw, setRaw] = useState({ domains: {}, modules: {} })
  const [loaded, setLoaded] = useState(false)
  const [locked, setLocked] = useState([])          // modules this organisation's subscription does not include
  const [subscription, setSubscription] = useState(null)

  const load = useCallback(() => {
    getModuleVisibility()
      .then(r => { setRaw(r.data || { domains: {}, modules: {} }); setLoaded(true) })
      .catch(() => setLoaded(true)) // fail open - treat everything as visible rather than blank the app
  }, [])

  // The organisation's plan + add-ons (fails open: if it cannot be read nothing is hidden - the server still refuses what is not included).
  // Re-read after an admin changes a plan ('accfino:subscription-changed'), so an upgrade shows up without signing out.
  const loadSub = useCallback(() => {
    let p
    try { p = Promise.resolve(books.getSubscription()) } catch (e) { p = Promise.reject(e) }
    p.then(r => { setSubscription(r.data || null); setLocked(r.data?.locked || []) }).catch(() => {})
  }, [])

  useEffect(() => {
    load(); loadSub()
    window.addEventListener('accfino:module-visibility-changed', load)
    window.addEventListener('accfino:subscription-changed', loadSub)
    return () => { window.removeEventListener('accfino:module-visibility-changed', load); window.removeEventListener('accfino:subscription-changed', loadSub) }
  }, [load, loadSub])

  // Missing entries default to visible, so a brand-new domain/module shows up
  // until an admin explicitly hides it, and nothing flashes hidden before load.
  const isDomainVisible = id => raw.domains?.[id] !== false
  // A module shows when the platform allows it AND the organisation's subscription includes it
  const isLocked = id => locked.includes(id)
  const isModuleVisible = id => raw.modules?.[id] !== false && !isLocked(id)

  return (
    <ModuleVisibilityContext.Provider value={{ loaded, isDomainVisible, isModuleVisible, raw, subscription, isLocked }}>
      {children}
    </ModuleVisibilityContext.Provider>
  )
}

export function useModuleVisibility() {
  return useContext(ModuleVisibilityContext)
}
