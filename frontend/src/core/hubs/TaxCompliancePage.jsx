import React, { useState, useEffect } from 'react'
import { useSearchParams } from 'react-router-dom'
import TaxReturnData from '../../modules/trading/pages/TaxReturnData.jsx'
import PropertyCGT from '../../modules/trading/pages/PropertyCGT.jsx'
import { AuditTab, CalendarTab, OverviewTab, ReportsTab, ReturnsTab, SettingsTab, TaxesTab, TAXES_LEGACY, taxesVisibleSections, taxMe } from '../../modules/taxation/public.js'
import { Receipt } from 'lucide-react'
import { useModuleVisibility } from '../hooks/useModuleVisibility.jsx'
import { tabsForDomain } from '../lib/modules.js'

// Top level, beside Tax Returns:  Taxes (GST | CGT | FBT)  and  Tax Workings (Income Tax Workings | Lodgment Readiness | Tax Planning | Workpapers).
// Top-level tabs follow config/modules.json for plan locks and visibility; the seven modules inside them are gated one by one (taxesVisibleSections).
const ALL_TABS = [
  { key: 'overview',  label: '📊 Dashboard' },
  { key: 'taxreturn', label: '🗂 Tax Returns' },
  { key: 'taxes',     label: '📚 Taxes' },
  { key: 'workings',  label: '🧮 Tax Workings' },
  { key: 'calendar',  label: '📅 Calendar' },
  { key: 'reports',   label: '📑 Reports' },
  { key: 'settings',  label: '⚙️ Rates & Settings' },
  { key: 'audit',     label: '🧾 Audit Trail' },
]

const GROUPS = ['taxes', 'workings']
const fyNow = () => { const d = new Date(), y = d.getMonth() >= 6 ? d.getFullYear() : d.getFullYear() - 1; return `${y}-${String(y + 1).slice(2)}` }
const fyList = () => { const y = Number(fyNow().slice(0, 4)); return [y + 1, y, y - 1, y - 2, y - 3].map(s => `${s}-${String(s + 1).slice(2)}`) }

export default function TaxCompliancePage() {
  const { isModuleVisible } = useModuleVisibility()
  const sections = taxesVisibleSections(isModuleVisible)
  const TABS = tabsForDomain('tax_compliance', ALL_TABS, isModuleVisible).filter(t => !GROUPS.includes(t.key) || sections.some(x => x.key === t.key))
  const [params, setParams] = useSearchParams()
  const valid = TABS.map(t => t.key)
  const urlTab = params.get('tab')
  const legacy = TAXES_LEGACY[urlTab]                                   // an old bookmark such as ?tab=gst opens Taxes > GST; ?tab=income opens Tax Workings > Income Tax Workings
  const startTab = legacy ? legacy[0] : (valid.includes(urlTab) ? urlTab : 'overview')
  const [tab, setTabState] = useState(valid.includes(startTab) ? startTab : (valid.includes('overview') ? 'overview' : valid[0]))
  const [nav, setNav] = useState({ sub: legacy ? legacy[1] : params.get('sub') })
  const [fy, setFy] = useState(params.get('fy') || fyNow())
  const [me, setMe] = useState(null)
  const [meError, setMeError] = useState('')
  const write = (t, n, y) => setParams({ tab: t, ...(GROUPS.includes(t) && n.sub ? { sub: n.sub } : {}), fy: y }, { replace: true })
  useEffect(() => {                                                      // follow the address bar when it changes from outside (a link, back/forward)
    const l = TAXES_LEGACY[urlTab]
    if (l) { setTabState(l[0]); setNav({ sub: l[1] }); write(l[0], { sub: l[1] }, fy) }      // an old bookmark is rewritten to its new address
    else if (valid.includes(urlTab) && urlTab !== tab) setTabState(urlTab)
    if (GROUPS.includes(urlTab)) setNav({ sub: params.get('sub') })
  }, [urlTab, params.get('section'), params.get('sub')])               // eslint-disable-line
  const setTab = k => {
    if (TAXES_LEGACY[k]) { const [s, b] = TAXES_LEGACY[k]; setTabState(s); setNav({ sub: b }); write(s, { sub: b }, fy); return }
    setNav({ sub: null }); setTabState(k); write(k, { sub: null }, fy)
  }
  const onNav = (section, sub) => { setNav({ sub }); write(section, { sub }, fy) }
  useEffect(() => { if (TABS.length && !TABS.some(t => t.key === tab)) setTab(TABS[0].key) }, [TABS.map(t => t.key).join(',')])    // eslint-disable-line
  useEffect(() => { taxMe().then(setMe).catch(e => setMeError(e?.response?.data?.detail || 'Taxation & Compliance is not available to your role in this organisation.')) }, [])

  const body = () => {
    if (meError) return <div role="alert" className="alert alert-error" style={{ margin: 16 }}>{meError}</div>
    if (!me) return <div role="status" style={{ padding: 40, textAlign: 'center' }} className="text-muted">Loading…</div>
    const p = { me, fy, go: setTab }
    return (
      <>
        {tab === 'overview'  && <OverviewTab {...p} />}
        {tab === 'taxreturn' && <ReturnsTab {...p} legacy={<TaxReturnData />} />}
        {GROUPS.includes(tab) && <TaxesTab key={tab} {...p} group={tab} sub={nav.sub} onNav={onNav} isVisible={isModuleVisible} legacyCgt={<PropertyCGT />} />}
        {tab === 'calendar'  && <CalendarTab {...p} />}
        {tab === 'reports'   && <ReportsTab {...p} />}
        {tab === 'settings'  && <SettingsTab {...p} />}
        {tab === 'audit'     && <AuditTab {...p} />}
      </>)
  }

  return (
    <div className="fade-in">
      <div style={{ marginBottom: 16, flexWrap: 'wrap', gap: 12 }} className="flex items-center justify-between">
        <div>
          <div className="flex items-center gap-1"><Receipt size={22} /><h2 style={{ margin: 0 }}>Taxation & Compliance</h2></div>
          <p className="text-sm text-muted" style={{ margin: '4px 0 0' }}>Tax Returns · Taxes (GST, CGT, FBT) · Tax Workings (income tax workings, lodgment readiness, tax planning, workpapers), prepared from your ledger and payroll</p>
        </div>
        <label className="text-sm flex items-center gap-1">Income year
          <select className="input input-sm" style={{ minWidth: 110 }} aria-label="Income year" value={fy} onChange={e => { setFy(e.target.value); write(tab, nav, e.target.value) }}>{fyList().map(y => <option key={y} value={y}>{y}</option>)}</select></label>
      </div>

      <div className="tabs-bar" style={{ marginBottom: 0, flexWrap: 'nowrap', overflowX: 'auto' }}>
        {TABS.map(t => <button key={t.key} className={`tab-btn${tab === t.key ? ' active' : ''}`} onClick={() => setTab(t.key)}>{t.label}</button>)}
      </div>

      <div style={{ background: 'var(--surface)', border: '1px solid var(--border)', borderTop: 'none', borderRadius: '0 0 var(--r-lg) var(--r-lg)', minHeight: 400, overflow: 'hidden', boxShadow: 'var(--sh-sm)' }}>
        {body()}
      </div>
    </div>
  )
}
