import React from 'react'
import { ReconciliationProvider } from '../modules/reconciliation/ReconciliationContext.jsx'

// Composition point: React providers that modules need above the router outlet. Core's Layout stays free of module state.
export default function ModuleProviders({ children }) {
  return <ReconciliationProvider>{children}</ReconciliationProvider>
}
