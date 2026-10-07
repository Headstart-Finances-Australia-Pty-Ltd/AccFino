import React, { lazy, Suspense, useCallback, useEffect, useState } from 'react'
import { useLocation, useSearchParams } from 'react-router-dom'
import { Users } from 'lucide-react'
import { useModuleVisibility } from '../../../core/hooks/useModuleVisibility.jsx'
import { tabsForDomain } from '../../../core/lib/modules.js'
import * as api from '../lib/payrollApi.js'
import { Loading, ErrorBox, useLoad } from '../components/kit.jsx'
import DashboardTab from './DashboardTab.jsx'
import NotificationBell from '../components/NotificationBell.jsx'
import { PAYRUN_TABS, LEGACY_TAB_TO_SUB, visiblePayrunTabs } from '../lib/payrunTabs.js'
import { TIME_LEAVE_TABS, LEGACY_TIME_TO_SUB, visibleTimeLeaveTabs } from '../lib/timeLeaveTabs.js'

const EmployeesTab = lazy(() => import('./EmployeesTab.jsx'))
const TimeLeavePage = lazy(() => import('./TimeLeavePage.jsx'))
const PayrunPage = lazy(() => import('./PayrunPage.jsx'))
const StpTab = lazy(() => import('./StpTab.jsx'))
const ReportsTab = lazy(() => import('./ReportsTab.jsx'))
const SettingsTab = lazy(() => import('./SettingsTab.jsx'))
const MyPayTab = lazy(() => import('./MyPayTab.jsx'))

// need(me) decides who sees a tab. This only decides what is SHOWN: every API call is authorised again on the server.
const has = (me, ...caps) => caps.some(c => me.capabilities.includes(c))
export const ALL_TABS = [
  { key: 'dashboard', label: '📊 Dashboard', need: me => has(me, 'view') },
  { key: 'mypay', label: '🙋 My Pay', need: me => me.self_service },
  { key: 'employees', label: '👥 Employees', need: me => has(me, 'employees_view') || me.is_manager },
  { key: 'timeleave', label: '⏱ Time & Leave', need: me => TIME_LEAVE_TABS.some(t => t.need(me)) },
  { key: 'payrun', label: '💸 Payrun', need: me => PAYRUN_TABS.some(t => t.need(me)) },
  { key: 'compliance', label: '🏛 STP', need: me => has(me, 'stp_manage') },
  { key: 'reports', label: '📑 Reports', need: me => has(me, 'reports_view') },
  { key: 'settings', label: '⚙ Settings', need: me => has(me, 'config_manage') },
]

export default function PayrollPage() {
  const location = useLocation()
  const { isModuleVisible } = useModuleVisibility()
  const meQ = useLoad(() => api.me(), [])
  const [params, setParams] = useSearchParams()
  // Old top-level keys now live inside Payrun (runs, payslips, payments, super, payg, audit, payitems) or Time & Leave (timesheets, leave): translate them so old links and dashboard shortcuts still land on the right screen.
  const resolve = k => (LEGACY_TAB_TO_SUB[k] ? { tab: 'payrun', sub: LEGACY_TAB_TO_SUB[k] } : LEGACY_TIME_TO_SUB[k] ? { tab: 'timeleave', sub: LEGACY_TIME_TO_SUB[k] } : { tab: k })
  const initial = resolve(params.get('tab') || location.state?.tab || '')
  const [tab, setTabState] = useState(initial.tab)
  const go = k => {
    const r = resolve(k)
    setTabState(r.tab)
    setParams(r.sub ? { tab: r.tab, sub: r.sub } : { tab: r.tab }, { replace: true })
  }
  const setTab = go
  useEffect(() => {
    const q = params.get('tab'); if (!q) return
    if (LEGACY_TAB_TO_SUB[q] || LEGACY_TIME_TO_SUB[q]) { go(q); return }        // rewrite a legacy address to ?tab=payrun&sub=...
    if (q !== tab) setTabState(q)
  }, [params.get('tab')]) // eslint-disable-line

  const me = meQ.data
  // Approvals: how many items wait for me (badge on Time & Leave) and my notifications (the bell). Refreshed every minute and after any action here.
  const [pending, setPending] = useState({ total: 0 })
  const [bell, setBell] = useState({ unread: 0, items: [] })
  const refresh = useCallback(async () => {
    if (!me) return
    const [pa, nt] = await Promise.all([api.pendingApprovals?.().catch(() => null), api.notifications?.().catch(() => null)])
    if (pa) setPending(pa)
    if (nt) setBell(nt)
  }, [me])
  useEffect(() => {
    refresh()
    const t = setInterval(refresh, 60000)
    return () => clearInterval(t)
  }, [refresh])
  const readAll = async () => { await api.markAllNotificationsRead?.().catch(() => null); refresh() }
  const openNotification = async n => {
    if (!n.is_read) await api.markNotificationRead?.(n.id).catch(() => null)
    const target = TABS.some(t => t.key === n.tab) ? n.tab : TABS[0]?.key
    if (target) { setTabState(target); setParams(n.sub && target === n.tab ? { tab: target, sub: n.sub } : { tab: target }, { replace: true }) }
    refresh()
  }
  const TABS = me ? tabsForDomain('payroll_workforce', ALL_TABS.filter(t => t.need(me)), isModuleVisible)
    .filter(t => t.key !== 'payrun' || visiblePayrunTabs(me, isModuleVisible).length > 0)
    .filter(t => t.key !== 'timeleave' || visibleTimeLeaveTabs(me, isModuleVisible).length > 0) : []
  const [wantedMyPay, setWantedMyPay] = useState(initial.tab === 'mypay')
  const noEmployeeLink = wantedMyPay && !!me && !me.self_service      // opened from the Home tile by someone whose login is not linked to an employee record
  useEffect(() => {
    if (me && TABS.length && !TABS.some(t => t.key === tab)) setTab(me.capabilities.includes('view') ? 'dashboard' : TABS[0].key)
  }, [me, TABS.map(t => t.key).join(',')]) // eslint-disable-line

  const body = k => {
    switch (k) {
      case 'dashboard': return <DashboardTab me={me} onNav={setTab} />
      case 'mypay': return <MyPayTab me={me} onChanged={refresh} />
      case 'employees': return <EmployeesTab me={me} />
      case 'timeleave': return <TimeLeavePage me={me} onChanged={refresh} />
      case 'payrun': return <PayrunPage me={me} onNav={setTab} />
      case 'compliance': return <StpTab me={me} />
      case 'reports': return <ReportsTab me={me} />
      case 'settings': return <SettingsTab me={me} />
      default: return null
    }
  }
  return (
    <div className="fade-in">
      <div className="flex items-center justify-between" style={{ marginBottom: 16, gap: 12 }}>
        <div>
          <div className="flex items-center gap-1"><Users size={22} /><h2 style={{ margin: 0 }}>Payroll & Workforce</h2></div>
          <p className="text-sm text-muted" style={{ margin: '4px 0 0' }}>Employees · Time & Leave · Payrun · STP · Reports</p>
        </div>
        {me && <NotificationBell data={bell} onOpen={openNotification} onReadAll={readAll} />}
      </div>
      {meQ.loading && !me ? <Loading /> : meQ.error ? <ErrorBox error={meQ.error} onRetry={meQ.reload} /> : (
        <>
          {noEmployeeLink && <div role="status" className="alert alert-warning" style={{ marginBottom: 10 }}>My Pay shows your own payslips, leave and timesheets, but your login is not linked to an employee record yet. Ask your payroll administrator to link it (Employees → open your record → Login user).</div>}
          <div className="tabs-bar" style={{ marginBottom: 0, flexWrap: 'nowrap', overflowX: 'auto' }} role="tablist">
            {TABS.map(t => <button key={t.key} role="tab" aria-selected={tab === t.key} className={`tab-btn${tab === t.key ? ' active' : ''}`} onClick={() => { setWantedMyPay(false); setTab(t.key) }}>{t.label}{t.key === 'timeleave' && pending.total > 0 && <span className="badge badge-danger" data-testid="pending-approvals-badge" title={`${pending.total} waiting for your approval`} style={{ marginLeft: 6 }}>{pending.total}</span>}</button>)}
          </div>
          <div style={{ background: 'var(--surface)', border: '1px solid var(--border)', borderTop: 'none', borderRadius: '0 0 var(--r-lg) var(--r-lg)', minHeight: 400, padding: 18, boxShadow: 'var(--sh-sm)' }}>
            <Suspense fallback={<Loading />}>{tab && TABS.some(t => t.key === tab) ? body(tab) : null}</Suspense>
          </div>
        </>)}
    </div>
  )
}
