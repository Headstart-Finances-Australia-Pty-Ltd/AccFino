import React, { useState, useEffect } from 'react'
import { useSearchParams } from 'react-router-dom'
import { CreditCard } from 'lucide-react'
import SmartLendingPage from '../../modules/lending/pages/SmartLendingPage.jsx'
import ComingSoonTab    from '../components/layout/ComingSoonTab.jsx'
import { useModuleVisibility } from '../hooks/useModuleVisibility.jsx'
import { tabsForDomain } from '../lib/modules.js'

const ALL_TABS = [
  { key:'statement',  label:'💳 Statement Analysis' },
  { key:'credit',     label:'📝 Credit'             },
  { key:'origination',label:'📥 Origination'        },
  { key:'management', label:'📑 Loans'              },
  { key:'collections',label:'📞 Collections'        },
  { key:'treasury',   label:'🏛 Treasury'           },
]

export default function LendingHubPage() {
  const { isModuleVisible } = useModuleVisibility()
  const TABS = tabsForDomain('lending_treasury', ALL_TABS, isModuleVisible)
  const [params, setParams] = useSearchParams()
  const valid = TABS.map(t => t.key)
  const fromUrl = params.get('tab')
  const [tab, setTabState] = useState(valid.includes(fromUrl) ? fromUrl : 'statement')
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
          <CreditCard size={22} />
          <h2 style={{margin:0}}>Smart Lending, Credit & Treasury</h2>
        </div>
        <p className="text-sm text-muted" style={{margin:'4px 0 0'}}>
          Statement analysis, credit assessment, loans, collections and treasury
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
        {tab === 'statement'   && <SmartLendingPage/>}
        {tab === 'credit'      && <ComingSoonTab emoji="📝" name="Credit Assessment" phase="Phase 3" blurb="Credit scoring and risk grading for applicants."/>}
        {tab === 'origination' && <ComingSoonTab emoji="📥" name="Loan Origination" phase="Phase 3" blurb="Loan application intake and approval workflow."/>}
        {tab === 'management'  && <ComingSoonTab emoji="📑" name="Loan Management" phase="Phase 3" blurb="Loan register, amortisation, leases and hire purchase."/>}
        {tab === 'collections' && <ComingSoonTab emoji="📞" name="Collections" phase="Phase 3" blurb="Arrears management and hardship workflows."/>}
        {tab === 'treasury'    && <ComingSoonTab emoji="🏛" name="Treasury & Liquidity" phase="Later" blurb="Cash position, funding facilities and liquidity management."/>}
      </div>
    </div>
  )
}
