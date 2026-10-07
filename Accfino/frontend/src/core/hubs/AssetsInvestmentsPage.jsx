import React, { useState, useEffect } from 'react'
import { useSearchParams } from 'react-router-dom'
import { TrendingUp } from 'lucide-react'
import StockTrading  from '../../modules/trading/pages/StockTrading.jsx'
import CryptoTrading from '../../modules/trading/pages/CryptoTrading.jsx'
import ComingSoonTab from '../components/layout/ComingSoonTab.jsx'
import { useModuleVisibility } from '../hooks/useModuleVisibility.jsx'
import { tabsForDomain } from '../lib/modules.js'

// Live modules lead the tab bar so the page always lands on real content by default.
const ALL_TABS = [
  { key:'stocks',    label:'📊 Shares & ETFs' },
  { key:'crypto',    label:'₿ Crypto'         },
  { key:'property',  label:'🏠 Property'      },
  { key:'funds',     label:'🏦 Funds & Bonds' },
  { key:'portfolio', label:'📂 Portfolio'     },
  { key:'networth',  label:'💎 Net Worth'     },
]

export default function AssetsInvestmentsPage() {
  const { isModuleVisible } = useModuleVisibility()
  const TABS = tabsForDomain('assets_investments', ALL_TABS, isModuleVisible)
  const [params, setParams] = useSearchParams()
  const valid = TABS.map(t => t.key)
  const fromUrl = params.get('tab')
  const [tab, setTabState] = useState(valid.includes(fromUrl) ? fromUrl : 'stocks')
  useEffect(() => { if (valid.includes(fromUrl) && fromUrl !== tab) setTabState(fromUrl) }, [fromUrl])
  const setTab = k => { setTabState(k); setParams({ tab: k }, { replace: true }) }

  // If an admin hides the module currently open (Admin > Modules), fall back to the first visible tab
  useEffect(() => {
    if (TABS.length && !TABS.some(t => t.key === tab)) setTab(TABS[0].key)
  }, [TABS.map(t => t.key).join(',')])

  return (
    <div className="fade-in">
      <div style={{marginBottom:16}}>
        <div className="flex items-center gap-1">
          <TrendingUp size={22} />
          <h2 style={{margin:0}}>Assets, Investments & Wealth</h2>
        </div>
        <p className="text-sm text-muted" style={{margin:'4px 0 0'}}>
          Property, shares, funds, crypto, portfolio and net worth
        </p>
      </div>

      <div className="tabs-bar" style={{marginBottom:0, flexWrap:'nowrap', overflowX:'auto'}}>
        {TABS.map(t => (
          <button key={t.key} className={`tab-btn${tab===t.key?' active':''}`} onClick={() => setTab(t.key)}>
            {t.label}
          </button>
        ))}
      </div>

      <div style={{background:'var(--surface)',border:'1px solid var(--border)',
        borderTop:'none',borderRadius:'0 0 var(--r-lg) var(--r-lg)',
        minHeight:400,overflow:'hidden',boxShadow:'var(--sh-sm)'}}>
        {tab === 'stocks'    && <StockTrading/>}
        {tab === 'crypto'    && <CryptoTrading/>}
        {tab === 'property'  && <ComingSoonTab emoji="🏠" name="Property" phase="Phase 3" blurb="Property register, rental income and expenses, depreciation."/>}
        {tab === 'funds'     && <ComingSoonTab emoji="🏦" name="Funds & Bonds" phase="Phase 3" blurb="Managed funds, bonds and fixed-interest holdings."/>}
        {tab === 'portfolio' && <ComingSoonTab emoji="📂" name="Investment Portfolio" phase="Phase 3" blurb="Holdings, dividends and corporate actions."/>}
        {tab === 'networth'  && <ComingSoonTab emoji="💎" name="Wealth & Net Worth" phase="Later" blurb="Household net worth and wealth planning."/>}
      </div>
    </div>
  )
}
