import React, { useState, lazy, Suspense } from 'react'
import CryptoTrading from './trading/CryptoTrading.jsx'
import StockTrading  from './trading/StockTrading.jsx'
import PropertyCGT   from './trading/PropertyCGT.jsx'
import TaxReturnData from './trading/TaxReturnData.jsx'

const TABS = [
  { key:'crypto',   label:'₿ Crypto Trading'          },
  { key:'stocks',   label:'📊 Stock / Equity Trading'  },
  { key:'property', label:'🏠 Property CGT'            },
  { key:'taxreturn',label:'🗂 Tax Return Data'         },
]

export default function TradingPage() {
  const [tab, setTab] = useState('crypto')
  return (
    <div className="fade-in">
      <div style={{marginBottom:18}}>
        <h1>🧾 Taxation & Trading</h1>
        <p style={{color:'var(--text-3)',marginTop:4,fontSize:'.9rem'}}>
          ATO-compliant CGT · Crypto · Equity · Property · Full Australian Tax Return data
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
