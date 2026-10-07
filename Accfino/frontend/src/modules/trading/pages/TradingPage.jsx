import React, { useState, useEffect, lazy, Suspense } from 'react'
import { useSearchParams } from 'react-router-dom'
import CryptoTrading from './CryptoTrading.jsx'
import StockTrading  from './StockTrading.jsx'
import PropertyCGT   from './PropertyCGT.jsx'
import TaxReturnData from './TaxReturnData.jsx'
import { FolderArchive, TrendingUp } from 'lucide-react'

const TABS = [
  { key:'crypto',   label:'₿ Crypto Trading'          },
  { key:'stocks',   label:'📊 Stock / Equity Trading'  },
  { key:'property', label:'🏠 Property CGT'            },
  { key:'taxreturn',label:'🗂 Tax Return Data'         },
]

export default function TradingPage() {
  // The tab lives in the address (?tab=) so the side panel can open Tax return data or Investments directly
  const [params, setParams] = useSearchParams()
  const valid = TABS.map(t => t.key)
  const fromUrl = params.get('tab')
  const [tab, setTabState] = useState(valid.includes(fromUrl) ? fromUrl : 'crypto')
  useEffect(() => { if (valid.includes(fromUrl) && fromUrl !== tab) setTabState(fromUrl) }, [fromUrl])
  const setTab = k => { setTabState(k); setParams({ tab: k }, { replace: true }) }
  return (
    <div className="fade-in">
      <div style={{marginBottom:16}}>
        <div className="flex items-center gap-1">
          {tab === 'taxreturn' || tab === 'property' ? <FolderArchive size={22} /> : <TrendingUp size={22} />}
          <h2 style={{margin:0}}>{tab === 'taxreturn' || tab === 'property' ? 'Tax Returns' : 'Shares & Crypto'}</h2>
        </div>
        <p className="text-sm text-muted" style={{margin:'4px 0 0'}}>
          Capital gains using Australian CGT rules · Crypto · Shares · Property · Individual tax return data
        </p>
      </div>
      <div className="tabs-bar" style={{marginBottom:0}}>
        {TABS.map(t => (
          <button key={t.key}
            className={`tab-btn${tab===t.key?' active':''}`}
            onClick={() => setTab(t.key)}>
            {t.label}
          </button>
        ))}
      </div>
      <div style={{background:'var(--surface)',border:'1px solid var(--border)',
        borderTop:'none',borderRadius:'0 0 var(--r-lg) var(--r-lg)',
        boxShadow:'var(--sh-sm)',overflow:'hidden'}}>
        {tab === 'crypto'    && <CryptoTrading/>}
        {tab === 'stocks'    && <StockTrading/>}
        {tab === 'property'  && <PropertyCGT/>}
        {tab === 'taxreturn' && <TaxReturnData/>}
      </div>
    </div>
  )
}
