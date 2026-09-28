import React, { createContext, useContext, useEffect, useState, useCallback } from 'react'
import { getModuleVisibility } from '../lib/api.js'

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
})

export function ModuleVisibilityProvider({ children }) {
  const [raw, setRaw] = useState({ domains: {}, modules: {} })
  const [loaded, setLoaded] = useState(false)

  const load = useCallback(() => {
    getModuleVisibility()
      .then(r => { setRaw(r.data || { domains: {}, modules: {} }); setLoaded(true) })
      .catch(() => setLoaded(true)) // fail open - treat everything as visible rather than blank the app
  }, [])

  useEffect(() => {
    load()
    window.addEventListener('accfino:module-visibility-changed', load)
    return () => window.removeEventListener('accfino:module-visibility-changed', load)
  }, [load])

  // Missing entries default to visible, so a brand-new domain/module shows up
  // until an admin explicitly hides it, and nothing flashes hidden before load.
  const isDomainVisible = id => raw.domains?.[id] !== false
  const isModuleVisible = id => raw.modules?.[id] !== false

  return (
    <ModuleVisibilityContext.Provider value={{ loaded, isDomainVisible, isModuleVisible, raw }}>
      {children}
    </ModuleVisibilityContext.Provider>
  )
}

export function useModuleVisibility() {
  return useContext(ModuleVisibilityContext)
}
