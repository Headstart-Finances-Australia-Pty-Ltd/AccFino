import React, { useState, useEffect } from 'react'
import { useSearchParams } from 'react-router-dom'
import { Compass } from 'lucide-react'
import CashFlowPage  from './CashFlowPage.jsx'
import ComingSoonTab from '../components/layout/ComingSoonTab.jsx'
import { useModuleVisibility } from '../hooks/useModuleVisibility.jsx'
import { tabsForDomain } from '../lib/modules.js'

const ALL_TABS = [
  { key:'cashflow',  label:'📈 Cash Flow'    },
  { key:'budgeting', label:'🎯 Budgeting'    },
  { key:'scenario',  label:'🔀 Scenarios'    },
  { key:'reporting', label:'📋 Reporting'    },
  { key:'cfo',       label:'🧠 CFO Insights' },
  { key:'ai',        label:'🤖 AI Assistant' },
  { key:'risk',      label:'🚨 Risk & Anomaly' },
]

export default function PlanningPage() {
  const { isModuleVisible } = useModuleVisibility()
  const TABS = tabsForDomain('planning_insights', ALL_TABS, isModuleVisible)
  const [params, setParams] = useSearchParams()
  const valid = TABS.map(t => t.key)
  const fromUrl = params.get('tab')
  const [tab, setTabState] = useState(valid.includes(fromUrl) ? fromUrl : 'cashflow')
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
          <Compass size={22} />
          <h2 style={{margin:0}}>Planning & Intelligence</h2>
        </div>
        <p className="text-sm text-muted" style={{margin:'4px 0 0'}}>
          Cash flow, budgets, scenarios, management reporting and the AI assistant
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
        {tab === 'cashflow'  && <CashFlowPage/>}
        {tab === 'budgeting' && <ComingSoonTab emoji="🎯" name="Budgeting & Forecasting" phase="Phase 4" blurb="Budgets, budget vs actual, scenarios and KPIs."/>}
        {tab === 'scenario'  && <ComingSoonTab emoji="🔀" name="Scenario Planning" phase="Phase 4" blurb="What-if scenarios across cash flow and budgets."/>}
        {tab === 'reporting' && <ComingSoonTab emoji="📋" name="Management Reporting" phase="Phase 4" blurb="Management reports and board packs."/>}
        {tab === 'cfo'       && <ComingSoonTab emoji="🧠" name="CFO Insights" phase="Later" blurb="Trend analysis and benchmarking for finance leaders."/>}
        {tab === 'ai'        && <ComingSoonTab emoji="🤖" name="AI Financial Assistant" phase="Phase 4" blurb="Ask questions of your ledger in plain English."/>}
        {tab === 'risk'      && <ComingSoonTab emoji="🚨" name="Risk & Anomaly Detection" phase="Later" blurb="Automated detection of anomalies and risk flags."/>}
      </div>
    </div>
  )
}
