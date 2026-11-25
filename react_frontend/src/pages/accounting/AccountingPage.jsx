import React, { useState, useEffect } from 'react'
import { useLocation } from 'react-router-dom'
import { getMyPlan } from '../../lib/api.js'
import { useAuth } from '../../hooks/useAuth.jsx'

// Sub-pages
import AccountingDashboard   from './AccountingDashboard.jsx'
import SalesPage             from './SalesPage.jsx'
import PurchasesPage         from './PurchasesPage.jsx'
import ReconciliationWrapper from './ReconciliationWrapper.jsx'
import CashFlowPage          from './CashFlowPage.jsx'
import FinancialReports      from './FinancialReports.jsx'

// TABS defined inside component so hasCashFlow is in scope

export default function AccountingPage() {
  const { user } = useAuth()
  const userId   = user?.id
  const location = useLocation()
  const [hasCashFlow, setHasCashFlow] = useState(false)
  const [tab, setTab] = useState(() => location.state?.tab || 'dashboard')

  useEffect(() => {
    if (!userId) return
    const isAdmin = user?.is_admin || (Array.isArray(user?.roles) && user.roles.includes('admin'))
    if (isAdmin) { setHasCashFlow(true); return }
    getMyPlan(userId).then(r => {
      const planId = r.data?.plan_id || 'base'
      const VAULT_PLANS = new Set(['base','accounting_starter',''])
      setHasCashFlow(!VAULT_PLANS.has(planId))
    }).catch(() => {})
  }, [userId])

  // Navigate to a specific tab when arriving from Overview page
  useEffect(() => {
    if (location.state?.tab) setTab(location.state.tab)
  }, [location.state?.tab])

  return (
    <div className="fade-in">
      <div style={{marginBottom:20}}>
        <h1>🏦 Accounting</h1>
        <p style={{color:'var(--text-3)',marginTop:4,fontSize:'.9rem'}}>
          Dashboard · Reconciliation · Sales · Purchases · Cash Flow · Financial Reports
        </p>
      </div>

      <div className="tabs-bar" style={{marginBottom:0}}>
        {[
          { key:'dashboard',      label:'📊 Dashboard'        },
          { key:'reconciliation', label:'🔀 Reconciliation'    },
          { key:'sales',          label:'💼 Sales'            },
          { key:'purchases',      label:'🧾 Purchases'        },
          { key:'cashflow',       label:'📈 Cash Flow',  locked:!hasCashFlow },
          { key:'reports',        label:'📋 Financial Reports' },
        ].map(t => (
          <button key={t.key}
            className={`tab-btn${tab===t.key?' active':''}`}
            onClick={() => t.locked ? null : setTab(t.key)}
            disabled={t.locked}
            title={t.locked ? 'Upgrade to Accounting Pro to access Cash Flow forecasting' : undefined}
            style={t.locked ? {opacity:.45,cursor:'not-allowed'} : undefined}>
            {t.label}{t.locked ? ' 🔒' : ''}
          </button>
        ))}
      </div>

      <div style={{
        background:'var(--surface)', border:'1px solid var(--border)',
        borderTop:'none', borderRadius:'0 0 var(--r-lg) var(--r-lg)',
        minHeight:400, overflow:'hidden', boxShadow:'var(--sh-sm)',
      }}>
        {tab === 'dashboard'      && <AccountingDashboard userId={userId}/>}
        {tab === 'reconciliation' && <ReconciliationWrapper userId={userId}/>}
        {tab === 'sales'          && <SalesPage userId={userId}/>}
        {tab === 'purchases'      && <PurchasesPage userId={userId}/>}
        {tab === 'cashflow'       && <CashFlowPage userId={userId}/>}
        {tab === 'reports'        && <FinancialReports userId={userId}/>}
      </div>
    </div>
  )
}
