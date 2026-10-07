import React, { useState, useEffect } from 'react'
import { useLocation, useSearchParams } from 'react-router-dom'
import { useAuth } from '../../../core/hooks/useAuth.jsx'
import { useModuleVisibility } from '../../../core/hooks/useModuleVisibility.jsx'
import { tabsForDomain } from '../../../core/lib/modules.js'
import { Landmark } from 'lucide-react'

// Sub-pages
import AccountingDashboard   from './AccountingDashboard.jsx'
import SalesPage             from './SalesPage.jsx'            // legacy (pre-ledger) records - still reachable, see LedgerOrLegacy below
import PurchasesPage         from './PurchasesPage.jsx'        // legacy (pre-ledger) records
import SalesPurchasesPage    from './SalesPurchasesPage.jsx'   // ledger-connected: every document posts to the general ledger and feeds the reports
import { ReconciliationWrapper } from '../../reconciliation/public.js'
import FinancialReports      from './FinancialReports.jsx'
import ExpensesPage          from './ExpensesPage.jsx'
import InventoryPage         from './InventoryPage.jsx'
import FixedAssetsPage       from './FixedAssetsPage.jsx'
import LedgerPage            from './ledger/LedgerPage.jsx'

// Note: Cash Flow Forecasting lives under Planning & Intelligence only (not duplicated here)
// so the same feature doesn't appear under two different business domains.

const ALL_TABS = [
  { key:'dashboard',      label:'📊 Dashboard'      },
  { key:'ledger',         label:'📒 Ledger'         },
  { key:'reconciliation', label:'🔀 Reconciliation' },
  { key:'assets-costs',   label:'🏗 Assets and Costs' },
  { key:'sales',          label:'💼 Sales'          },
  { key:'purchases',      label:'🧾 Purchases'      },
  { key:'reports',        label:'📋 Reports'        },
]

// Assets and Costs sits at the level of Reconciliation and holds Expenses, Inventory and Fixed Assets as sub-tabs.
// Each sub-tab keeps its own module switch (config/modules.json), so a plan or admin can still hide one of them.
const ASSET_SUBS = [
  { key:'expenses',     label:'🧾 Expenses',     module:'expenses' },
  { key:'inventory',    label:'📦 Inventory',    module:'inventory-trading' },
  { key:'fixed-assets', label:'🏗 Fixed Assets', module:'fixed-assets' },
]
// old links (?tab=expenses | inventory | fixed-assets) open the matching sub-tab of Assets and Costs
const ASSET_LEGACY = { expenses:'expenses', inventory:'inventory', 'fixed-assets':'fixed-assets' }

function AssetsCosts({ sub, onSub, isModuleVisible }) {
  const subs = ASSET_SUBS.filter(x => isModuleVisible(x.module))
  if (!subs.length) return <div style={{padding:16}} className="text-muted">None of the Assets and Costs modules are included in your plan.</div>
  const cur = subs.find(x => x.key === sub) || subs[0]
  return (
    <div>
      <div role="tablist" aria-label="Assets and Costs pages" className="tabs-bar" style={{margin:'12px 16px 0', fontSize:'.92em'}}>
        {subs.map(x => (
          <button key={x.key} role="tab" aria-selected={x.key===cur.key}
            className={`tab-btn${x.key===cur.key?' active':''}`} onClick={() => onSub(x.key)}>{x.label}</button>
        ))}
      </div>
      <div data-testid={`assets-${cur.key}`}>
        {cur.key === 'expenses'     && <ExpensesPage/>}
        {cur.key === 'inventory'    && <InventoryPage/>}
        {cur.key === 'fixed-assets' && <FixedAssetsPage/>}
      </div>
    </div>
  )
}

// Sales / Purchases: the ledger-connected screens (contacts, quotes/POs, invoices/bills, credits, receipts/payments, CSV import) are the default.
// The original screens wrote to the pre-ledger accounting_documents table, which no report reads, so they are kept behind this switch
// (legacy OCR upload & extract, old purchase-order list) rather than removed.
function LedgerOrLegacy({ side, userId, Legacy }) {
  const [legacy, setLegacy] = useState(false)
  return (
    <div>
      <div style={{ display: 'flex', justifyContent: 'flex-end', padding: '8px 16px 0' }}>
        <label className="text-xs text-muted" style={{ cursor: 'pointer' }}>
          <input type="checkbox" checked={legacy} onChange={e => setLegacy(e.target.checked)} /> Show legacy records (not connected to the ledger / reports)
        </label>
      </div>
      {legacy ? <Legacy userId={userId} /> : <SalesPurchasesPage side={side} />}
    </div>
  )
}

export default function AccountingPage() {
  const { user } = useAuth()
  const userId   = user?.id
  const location = useLocation()
  const { isModuleVisible } = useModuleVisibility()
  const TABS = tabsForDomain('accounting', ALL_TABS, isModuleVisible)
    .filter(t => t.key !== 'assets-costs' || ASSET_SUBS.some(x => isModuleVisible(x.module)))
  // The tab also lives in the address (?tab=) so side-panel links open it and highlight correctly
  const [params, setParams] = useSearchParams()
  const startRaw = params.get('tab') || location.state?.tab || 'dashboard'
  const [tab, setTabState] = useState(() => ASSET_LEGACY[startRaw] ? 'assets-costs' : startRaw)
  const [sub, setSub] = useState(() => ASSET_LEGACY[startRaw] || params.get('sub') || null)
  const write = (t, b) => setParams({ tab: t, ...(t === 'assets-costs' && b ? { sub: b } : {}) }, { replace: true })
  const setTab = k => {
    if (ASSET_LEGACY[k]) { setTabState('assets-costs'); setSub(ASSET_LEGACY[k]); write('assets-costs', ASSET_LEGACY[k]); return }
    setTabState(k); write(k, k === 'assets-costs' ? sub : null)
  }
  const onSub = b => { setSub(b); write('assets-costs', b) }
  useEffect(() => {                                   // follow the address bar (side-panel links, back/forward); old expense/inventory/asset links are rewritten
    const q = params.get('tab')
    if (q && ASSET_LEGACY[q]) { setTabState('assets-costs'); setSub(ASSET_LEGACY[q]); write('assets-costs', ASSET_LEGACY[q]) }
    else if (q && q !== tab) setTabState(q)
    if (q === 'assets-costs' && params.get('sub')) setSub(params.get('sub'))
  }, [params.get('tab'), params.get('sub')])

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
          Purchases & Payables · Assets & Costs (Expenses, Inventory, Fixed Assets) · Financial Reports
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
        {tab === 'sales'          && <LedgerOrLegacy side="sales" userId={userId} Legacy={SalesPage}/>}
        {tab === 'purchases'      && <LedgerOrLegacy side="purchases" userId={userId} Legacy={PurchasesPage}/>}
        {tab === 'assets-costs'   && <AssetsCosts sub={sub} onSub={onSub} isModuleVisible={isModuleVisible}/>}
        {tab === 'reports'        && <FinancialReports userId={userId}/>}
      </div>
    </div>
  )
}
