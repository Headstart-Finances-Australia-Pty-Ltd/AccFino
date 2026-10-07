import React, { useState } from 'react'

// Reconciliation state is kept ABOVE the routes (mounted by core/moduleProviders.jsx) so it survives navigation between pages.
export const ReconciliationContext = React.createContext(null)

export function ReconciliationProvider({ children }) {
  // ── Reconciliation state — kept in Layout so it survives navigation ──────
  const [reconTransactions,   setReconTransactions]   = useState(null)
  const [reconSummary,        setReconSummary]        = useState([])
  const [reconSessionId,      setReconSessionId]      = useState(null)
  const [reconAccounts,       setReconAccounts]       = useState([])
  const [reconMainTab,        setReconMainTab]        = useState('input')

  // Resets all reconciliation state — called by DashboardPage when a session
  // is deleted so the Reconciliation page does not show stale data.
  const resetRecon = React.useCallback((sessionIdToReset) => {
    setReconSessionId(prev => {
      // Only reset if the deleted session matches what's currently loaded,
      // or if no specific session was provided (reset unconditionally).
      if (sessionIdToReset && prev !== sessionIdToReset) return prev
      setReconTransactions(null)
      setReconSummary([])
      setReconAccounts([])
      setReconMainTab('input')
      return null
    })
  }, [])

  const reconCtx = {
    transactions:    reconTransactions,  setTransactions:   setReconTransactions,
    monthlySummary:  reconSummary,       setMonthlySummary: setReconSummary,
    sessionId:       reconSessionId,     setSessionId:      setReconSessionId,
    accounts:        reconAccounts,      setAccounts:       setReconAccounts,
    mainTab:         reconMainTab,       setMainTab:        setReconMainTab,
    resetRecon,
  }


  return <ReconciliationContext.Provider value={reconCtx}>{children}</ReconciliationContext.Provider>
}
