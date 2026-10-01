import React, { useState, useEffect } from 'react'
import { useSearchParams } from 'react-router-dom'
import TaxReturnData from './trading/TaxReturnData.jsx'
import PropertyCGT   from './trading/PropertyCGT.jsx'
import ComingSoonTab from '../components/layout/ComingSoonTab.jsx'
import { Receipt } from 'lucide-react'
import { useModuleVisibility } from '../hooks/useModuleVisibility.jsx'
import { tabsForDomain } from '../lib/modules.js'

// Live modules lead the tab bar so the page always lands on real content by default.
const ALL_TABS = [
  { key:'taxreturn', label:'🗂 Tax Returns' },
  { key:'property',  label:'🏠 CGT'         },
  { key:'gst',       label:'📤 GST/BAS/IAS' },
  { key:'income',    label:'💵 Income Tax'  },
  { key:'fbt',       label:'🚗 FBT'         },
  { key:'planning',  label:'🧮 Tax Planning'},
  { key:'lodgement', label:'🏢 ATO Lodgement'},
]

export default function TaxCompliancePage() {
  const { isModuleVisible } = useModuleVisibility()
  const TABS = tabsForDomain('tax_compliance', ALL_TABS, isModuleVisible)
  const [params, setParams] = useSearchParams()
  const valid = TABS.map(t => t.key)
  const fromUrl = params.get('tab')
  const [tab, setTabState] = useState(valid.includes(fromUrl) ? fromUrl : 'taxreturn')
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
          <Receipt size={22} />
          <h2 style={{margin:0}}>Taxation & Compliance</h2>
        </div>
        <p className="text-sm text-muted" style={{margin:'4px 0 0'}}>
          Tax returns, GST/BAS/IAS, income tax, CGT, FBT, tax planning and ATO lodgement
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
        {tab === 'taxreturn' && <TaxReturnData/>}
        {tab === 'property'  && <PropertyCGT/>}
        {tab === 'gst'       && <ComingSoonTab emoji="📤" name="GST / BAS / IAS" phase="Phase 2" blurb="BAS and IAS prepared from the ledger and ATO lodgement."/>}
        {tab === 'income'    && <ComingSoonTab emoji="💵" name="Income Tax" phase="Phase 2" blurb="Income tax calculations for individuals and entities."/>}
        {tab === 'fbt'       && <ComingSoonTab emoji="🚗" name="FBT & Other Taxes" phase="Phase 3" blurb="Fringe benefits tax and other business taxes."/>}
        {tab === 'planning'  && <ComingSoonTab emoji="🧮" name="Tax Planning" phase="Phase 3" blurb="Tax projections and planning strategies."/>}
        {tab === 'lodgement' && <ComingSoonTab emoji="🏢" name="Tax Lodgement & ATO" phase="Phase 2" blurb="Entity returns, workpapers and ATO lodgement."/>}
      </div>
    </div>
  )
}
