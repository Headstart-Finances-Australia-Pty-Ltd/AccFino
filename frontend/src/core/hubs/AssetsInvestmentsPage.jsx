import React, { useState, useEffect } from 'react'
import { useSearchParams } from 'react-router-dom'
import { TrendingUp } from 'lucide-react'
import StockTrading from '../../modules/trading/pages/StockTrading.jsx'
import CryptoTrading from '../../modules/trading/pages/CryptoTrading.jsx'
import { CryptoTab, FundsBondsTab, NetWorthTab, PortfolioTab, PropertyTab, SharesTab, invMe } from '../../modules/investments/public.js'
import { useModuleVisibility } from '../hooks/useModuleVisibility.jsx'
import { tabsForDomain } from '../lib/modules.js'

// Shares & ETFs, Crypto, Property, Funds & Bonds, Portfolio and Net Worth. Each is its own plan-gated module (config/modules.json).
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
  const [me, setMe] = useState(null)
  const [meError, setMeError] = useState('')
  useEffect(() => { if (valid.includes(fromUrl) && fromUrl !== tab) setTabState(fromUrl) }, [fromUrl])
  const setTab = k => { setTabState(k); setParams({ tab: k }, { replace: true }) }
  useEffect(() => { invMe().then(setMe).catch(e => setMeError(e?.response?.data?.detail || 'Assets, Investments & Wealth is not available to your role in this organisation.')) }, [])

  // If an admin hides the module currently open (Admin > Modules), fall back to the first visible tab
  useEffect(() => {
    if (TABS.length && !TABS.some(t => t.key === tab)) setTab(TABS[0].key)
  }, [TABS.map(t => t.key).join(',')])

  const body = () => {
    if (meError) return <div role="alert" className="alert alert-error" style={{ margin: 16 }}>{meError}</div>
    if (!me) return <div role="status" style={{ padding: 40, textAlign: 'center' }} className="text-muted">Loading…</div>
    return (
      <>
        {tab === 'stocks'    && <SharesTab me={me} analyser={<StockTrading />} />}
        {tab === 'crypto'    && <CryptoTab me={me} analyser={<CryptoTrading />} />}
        {tab === 'property'  && <PropertyTab me={me} />}
        {tab === 'funds'     && <FundsBondsTab me={me} />}
        {tab === 'portfolio' && <PortfolioTab me={me} />}
        {tab === 'networth'  && <NetWorthTab me={me} />}
      </>)
  }

  return (
    <div className="fade-in">
      <div style={{marginBottom:16}}>
        <div className="flex items-center gap-1">
          <TrendingUp size={22} />
          <h2 style={{margin:0}}>Assets, Investments & Wealth</h2>
        </div>
        <p className="text-sm text-muted" style={{margin:'4px 0 0'}}>
          Shares, crypto, property, funds and bonds, with the portfolio and net worth calculated from your records and linked to the ledger and Taxation
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
        {body()}
      </div>
    </div>
  )
}
