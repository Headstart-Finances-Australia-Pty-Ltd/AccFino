import React, { useState, useEffect } from 'react'
import { useLocation, useSearchParams } from 'react-router-dom'
import { useAuth } from '../../hooks/useAuth.jsx'
import { useModuleVisibility } from '../../hooks/useModuleVisibility.jsx'
import { tabsForDomain } from '../../lib/modules.js'
import { Landmark } from 'lucide-react'

// Sub-pages
import AccountingDashboard   from './AccountingDashboard.jsx'
import SalesPage             from './SalesPage.jsx'
import PurchasesPage         from './PurchasesPage.jsx'
import ReconciliationWrapper from './ReconciliationWrapper.jsx'
import FinancialReports      from './FinancialReports.jsx'
import LedgerPage            from '../ledger/LedgerPage.jsx'
import ComingSoonTab         from '../../components/layout/ComingSoonTab.jsx'

// Note: Cash Flow Forecasting lives under Planning & Intelligence only (not duplicated here)
// so the same feature doesn't appear under two different business domains.

const ALL_TABS = [
  { key:'dashboard',      label:'📊 Dashboard'      },
  { key:'ledger',         label:'📒 Ledger'         },
  { key:'reconciliation', label:'🔀 Reconciliation' },
  { key:'sales',          label:'💼 Sales'          },
  { key:'purchases',      label:'🧾 Purchases'      },
  { key:'expenses',       label:'🧾 Expenses'       },
  { key:'inventory',      label:'📦 Inventory'      },
  { key:'fixed-assets',   label:'🏗 Fixed Assets'   },
  { key:'reports',        label:'📋 Reports'        },
]

export default function AccountingPage() {
  const { user } = useAuth()
  const userId   = user?.id
  const location = useLocation()
  const { isModuleVisible } = useModuleVisibility()
  const TABS = tabsForDomain('accounting', ALL_TABS, isModuleVisible)
  // The tab also lives in the address (?tab=) so side-panel links open it and highlight correctly
  const [params, setParams] = useSearchParams()
  const [tab, setTabState] = useState(() => params.get('tab') || location.state?.tab || 'dashboard')
  const setTab = k => { setTabState(k); setParams({ tab: k }, { replace: true }) }
  useEffect(() => { const q = params.get('tab'); if (q && q !== tab) setTabState(q) }, [params.get('tab')])

  // Navigate to a specific tab when arriving from Overview page
  useEffect(() => {
    if (location.state?.tab) setTab(location.state.tab)
  }, [location.state?.tab])

  // If an admin hides the module currently open (Admin > Modules), fall back to the first visible tab
  useEffect(() => {
    if (TABS.length && !TABS.some(t => t.key === tab)) setTab(TABS[0].key)
  }, [TABS.map(t => t.key).join(',')])

  return (
    <div className="fade-in">
      <div style={{marginBottom:16}}>
        <div className="flex items-center gap-1">
          <Landmark size={22} />
          <h2 style={{margin:0}}>Books and Accounting</h2>
        </div>
        <p className="text-sm text-muted" style={{margin:'4px 0 0'}}>
          Dashboard · General Ledger · Banking & Reconciliation · Sales & Receivables ·
          Purchases & Payables · Expenses · Inventory & Trading · Fixed Assets · Financial Reports
        </p>
      </div>

      <div className="tabs-bar" style={{marginBottom:0, flexWrap:'nowrap', overflowX:'auto'}}>
        {TABS.map(t => (
          <button key={t.key}
            className={`tab-btn${tab===t.key?' active':''}`}
            onClick={() => setTab(t.key)}>
            {t.label}
          </button>
        ))}
      </div>

      <div style={{
        background:'var(--surface)', border:'1px solid var(--border)',
        borderTop:'none', borderRadius:'0 0 var(--r-lg) var(--r-lg)',
        minHeight:400, overflow:'hidden', boxShadow:'var(--sh-sm)',
      }}>
        {tab === 'dashboard'      && <AccountingDashboard userId={userId}/>}
        {tab === 'ledger'         && <LedgerPage/>}
        {tab === 'reconciliation' && <ReconciliationWrapper userId={userId}/>}
        {tab === 'sales'          && <SalesPage userId={userId}/>}
        {tab === 'purchases'      && <PurchasesPage userId={userId}/>}
        {tab === 'expenses'       && <ComingSoonTab emoji="🧾" name="Expenses" phase="Phase 1" blurb="Expense claims, receipt capture and reimbursements."/>}
        {tab === 'inventory'      && <ComingSoonTab emoji="📦" name="Inventory & Trading" phase="Phase 3" blurb="Stock, cost of goods sold and stocktakes."/>}
        {tab === 'fixed-assets'   && <ComingSoonTab emoji="🏗" name="Fixed Assets" phase="Phase 3" blurb="Asset register, book and tax depreciation."/>}
        {tab === 'reports'        && <FinancialReports userId={userId}/>}
      </div>
    </div>
  )
}
