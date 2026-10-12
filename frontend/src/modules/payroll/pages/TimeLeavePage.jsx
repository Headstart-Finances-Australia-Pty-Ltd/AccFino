import React, { lazy, Suspense } from 'react'
import { useSearchParams } from 'react-router-dom'
import { useModuleVisibility } from '../../../core/hooks/useModuleVisibility.jsx'
import { Loading } from '../components/kit.jsx'
import { visibleTimeLeaveTabs } from '../lib/timeLeaveTabs.js'

const TimesheetsTab = lazy(() => import('./TimesheetsTab.jsx'))
const LeaveTab = lazy(() => import('./LeaveTab.jsx'))

export default function TimeLeavePage({ me, onChanged }) {
  const { isModuleVisible } = useModuleVisibility()
  const [params, setParams] = useSearchParams()
  const tabs = visibleTimeLeaveTabs(me, isModuleVisible)
  const requested = params.get('sub')
  const sub = tabs.some(t => t.key === requested) ? requested : tabs[0]?.key
  const setSub = k => { const p = new URLSearchParams(params); p.set('tab', 'timeleave'); p.set('sub', k); setParams(p, { replace: true }) }

  if (!tabs.length) return <div className="text-sm text-muted">You do not have access to any Time & Leave areas.</div>

  const body = k => {
    switch (k) {
      case 'timesheets': return <TimesheetsTab me={me} onChanged={onChanged} />
      case 'leave': return <LeaveTab me={me} onChanged={onChanged} />
      default: return null
    }
  }
  return (
    <div>
      <div className="tabs-bar" style={{ marginBottom: 14, flexWrap: 'nowrap', overflowX: 'auto' }} role="tablist" aria-label="Time and leave sections">
        {tabs.map(t => <button key={t.key} role="tab" aria-selected={sub === t.key} data-testid={`timeleave-sub-${t.key}`} className={`tab-btn${sub === t.key ? ' active' : ''}`} onClick={() => setSub(t.key)}>{t.label}</button>)}
      </div>
      <Suspense fallback={<Loading />}>{body(sub)}</Suspense>
    </div>
  )
}
