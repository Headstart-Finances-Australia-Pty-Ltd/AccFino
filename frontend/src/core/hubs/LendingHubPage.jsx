import React, { useState, useEffect } from 'react'
import { useSearchParams } from 'react-router-dom'
import { CreditCard } from 'lucide-react'
import { CollectionsTab, CreditTab, LendingOverview, LoansTab, OriginationTab, SmartLendingPage, StatementTab, TreasuryTab, lendingMe } from '../../modules/lending/public.js'
import { useModuleVisibility } from '../hooks/useModuleVisibility.jsx'
import { tabsForDomain } from '../lib/modules.js'

// Statement analysis, credit assessment, origination, loans, collections and treasury. Each is its own plan-gated module (config/modules.json).
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
  const [me, setMe] = useState(null)
  const [meError, setMeError] = useState('')
  const [tick, setTick] = useState(0)
  useEffect(() => { if (valid.includes(fromUrl) && fromUrl !== tab) setTabState(fromUrl) }, [fromUrl])
  const setTab = k => { setTabState(k); setParams({ tab: k }, { replace: true }); setTick(n => n + 1) }
  useEffect(() => { lendingMe().then(setMe).catch(e => setMeError(e?.response?.data?.detail || 'Smart Lending is not available to your role in this organisation.')) }, [])

  // If an admin hides the module currently open (Admin > Modules), fall back to the first visible tab
  useEffect(() => {
    if (TABS.length && !TABS.some(t => t.key === tab)) setTab(TABS[0].key)
  }, [TABS.map(t => t.key).join(',')])

  const body = () => {
    if (meError) return <div role="alert" className="alert alert-error" style={{ margin: 16 }}>{meError}</div>
    if (!me) return <div role="status" style={{ padding: 40, textAlign: 'center' }} className="text-muted">Loading…</div>
    return (
      <>
        <LendingOverview onGo={k => valid.includes(k) && setTab(k)} refreshKey={tick} />
        {tab === 'statement'   && <StatementTab me={me} quickCheck={<SmartLendingPage />} />}
        {tab === 'credit'      && <CreditTab me={me} />}
        {tab === 'origination' && <OriginationTab me={me} />}
        {tab === 'management'  && <LoansTab me={me} />}
        {tab === 'collections' && <CollectionsTab me={me} />}
        {tab === 'treasury'    && <TreasuryTab me={me} />}
      </>)
  }

  return (
    <div className="fade-in">
      <div style={{marginBottom:16}}>
        <div className="flex items-center gap-1">
          <CreditCard size={22} />
          <h2 style={{margin:0}}>Smart Lending, Credit & Treasury</h2>
        </div>
        <p className="text-sm text-muted" style={{margin:'4px 0 0'}}>
          Can this applicant afford the loan? What are the risks, and what is missing? Then manage the loan, the arrears and the cash behind it
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
