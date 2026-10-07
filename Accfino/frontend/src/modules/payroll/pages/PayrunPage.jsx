import React, { lazy, Suspense } from 'react'
import { useSearchParams } from 'react-router-dom'
import { useModuleVisibility } from '../../../core/hooks/useModuleVisibility.jsx'
import { Loading } from '../components/kit.jsx'
import { PAYRUN_TABS, visiblePayrunTabs } from '../lib/payrunTabs.js'

const PayRunsTab = lazy(() => import('./PayRunsTab.jsx'))
const PayslipsTab = lazy(() => import('./PayslipsTab.jsx'))
const PaymentsTab = lazy(() => import('./PaymentsTab.jsx'))
const SuperTab = lazy(() => import('./SuperTab.jsx'))
const PayItemsTab = lazy(() => import('./PayItemsTab.jsx'))
const PaygTab = lazy(() => import('./PaygTab.jsx'))
const AuditTab = lazy(() => import('./AuditTab.jsx'))

export default function PayrunPage({ me, onNav }) {
  const { isModuleVisible } = useModuleVisibility()
  const [params, setParams] = useSearchParams()
  const tabs = visiblePayrunTabs(me, isModuleVisible)
  const requested = params.get('sub')
  const sub = tabs.some(t => t.key === requested) ? requested : tabs[0]?.key
  const setSub = k => { const p = new URLSearchParams(params); p.set('tab', 'payrun'); p.set('sub', k); setParams(p, { replace: true }) }

  if (!tabs.length) return <div className="text-sm text-muted">You do not have access to any Payrun areas.</div>

  const body = k => {
    switch (k) {
      case 'pays': return <PayRunsTab me={me} onNav={onNav} />
      case 'payslips': return <PayslipsTab me={me} />
      case 'payments': return <PaymentsTab me={me} />
      case 'super': return <SuperTab me={me} />
      case 'payitems': return <PayItemsTab me={me} />
      case 'payg': return <PaygTab me={me} />
      case 'audit': return <AuditTab me={me} />
      default: return null
    }
  }
  return (
    <div>
      <div className="tabs-bar" style={{ marginBottom: 14, flexWrap: 'nowrap', overflowX: 'auto' }} role="tablist" aria-label="Payrun sections">
        {tabs.map(t => <button key={t.key} role="tab" aria-selected={sub === t.key} data-testid={`payrun-sub-${t.key}`} className={`tab-btn${sub === t.key ? ' active' : ''}`} onClick={() => setSub(t.key)}>{t.label}</button>)}
      </div>
      <Suspense fallback={<Loading />}>{body(sub)}</Suspense>
    </div>
  )
}
