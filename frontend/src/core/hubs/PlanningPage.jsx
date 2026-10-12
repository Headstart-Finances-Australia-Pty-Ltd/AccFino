import React, { useState, useEffect } from 'react'
import { useSearchParams } from 'react-router-dom'
import { Compass } from 'lucide-react'
import CashFlowPage from '../../modules/cashflow/pages/CashFlowPage.jsx'
import { PlanningHome, ForecastTab, BudgetTab, ScenarioTab, ReportsTab, InsightsTab, AssistantTab, RiskTab } from '../../modules/planning/public.js'
import { useModuleVisibility } from '../hooks/useModuleVisibility.jsx'
import { tabsForDomain } from '../lib/modules.js'

const ALL_TABS = [
  { key:'overview',  label:'🏠 Overview'     },
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
  const [tab, setTabState] = useState(valid.includes(fromUrl) ? fromUrl : (valid[0] || 'overview'))
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
          Cash flow, budgets, scenarios, management reporting, insights, the AI assistant and risk alerts. Actuals, budgets, forecasts and scenarios are always labelled separately.
        </p>
      </div>

      <div className="tabs-bar" role="tablist" style={{marginBottom:0, flexWrap:'nowrap', overflowX:'auto'}}>
        {TABS.map(t => (
          <button key={t.key} role="tab" aria-selected={tab===t.key} className={`tab-btn${tab===t.key?' active':''}`} onClick={() => setTab(t.key)}>
            {t.label}
          </button>
        ))}
      </div>

      <div style={{background:'var(--surface)',border:'1px solid var(--border)',
        borderTop:'none',borderRadius:'0 0 var(--r-lg) var(--r-lg)',
        minHeight:400,overflow:'hidden',boxShadow:'var(--sh-sm)'}}>
        {tab === 'overview'  && <PlanningHome go={setTab}/>}
        {tab === 'cashflow'  && <ForecastTab Legacy={CashFlowPage}/>}
        {tab === 'budgeting' && <BudgetTab/>}
        {tab === 'scenario'  && <ScenarioTab/>}
        {tab === 'reporting' && <ReportsTab/>}
        {tab === 'cfo'       && <InsightsTab/>}
        {tab === 'ai'        && <AssistantTab/>}
        {tab === 'risk'      && <RiskTab/>}
      </div>
    </div>
  )
}
