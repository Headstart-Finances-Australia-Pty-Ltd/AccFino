import React from 'react'
import GstTab from './GstTab.jsx'
import CgtTab from './CgtTab.jsx'
import FbtTab from './FbtTab.jsx'
import IncomeTab from './IncomeTab.jsx'
import LodgmentReadinessTab from './LodgmentReadinessTab.jsx'
import PlanningTab from './PlanningTab.jsx'
import WorkpapersTab from './WorkpapersTab.jsx'

// Tax Returns | Taxes | Tax Workings (top-level tabs).  Taxes: GST | CGT | FBT   and   Tax Workings: Income Tax Workings | Lodgment Readiness | Tax Planning | Workpapers
export const SECTIONS = [
  { key: 'taxes', label: 'Taxes', subs: [{ key: 'gst', label: 'GST', module: 'gst-bas-ias' }, { key: 'cgt', label: 'CGT', module: 'cgt' }, { key: 'fbt', label: 'FBT', module: 'fbt-other-taxes' }] },
  { key: 'workings', label: 'Tax Workings', subs: [{ key: 'income', label: 'Income Tax Workings', module: 'income-tax' }, { key: 'lodgment', label: 'Lodgment Readiness', module: 'tax-lodgement-ato' },
                                                    { key: 'planning', label: 'Tax Planning', module: 'tax-planning' }, { key: 'workpapers', label: 'Workpapers', module: 'tax-workpapers' }] },
]
// the old top-level tab keys still work as links (bookmarks, dashboard tiles, the lodgement screen): they land on the matching sub-tab of Taxes
export const LEGACY = { gst: ['taxes', 'gst'], property: ['taxes', 'cgt'], fbt: ['taxes', 'fbt'], income: ['workings', 'income'], lodgement: ['workings', 'lodgment'], planning: ['workings', 'planning'], workpapers: ['workings', 'workpapers'] }

export const visibleSections = isVisible => SECTIONS.map(s => ({ ...s, subs: s.subs.filter(x => isVisible(x.module)) })).filter(s => s.subs.length)

// `group` ('taxes' | 'workings') renders just that section as a top-level tab of Tax Returns (no section switcher); without it both sections show, as before.
export default function TaxesTab({ me, fy, go, section, sub, group, onNav, isVisible = () => true, legacyCgt, props }) {
  const secs = visibleSections(isVisible).filter(s => !group || s.key === group)
  if (!secs.length) return <div style={{ padding: 16 }} className="text-muted">None of the Taxes modules are included in your plan.</div>
  const sec = secs.find(s => s.key === (group || section)) || secs[0]
  const cur = sec.subs.find(s => s.key === sub) || sec.subs[0]
  const p = { me, fy, go, ...(props || {}) }
  return (
    <div>
      {!group && <div role="tablist" aria-label="Taxes sections" className="tabs-bar" style={{ margin: '12px 16px 0' }}>
        {secs.map(s => <button key={s.key} role="tab" aria-selected={s.key === sec.key} className={`tab-btn${s.key === sec.key ? ' active' : ''}`} onClick={() => onNav(s.key, s.subs[0].key)} style={{ fontWeight: 700 }}>{s.label}</button>)}
      </div>}
      <div role="tablist" aria-label={`${sec.label} pages`} className="tabs-bar" style={{ margin: '4px 16px 0', fontSize: '.92em' }}>
        {sec.subs.map(s => <button key={s.key} role="tab" aria-selected={s.key === cur.key} className={`tab-btn${s.key === cur.key ? ' active' : ''}`} onClick={() => onNav(sec.key, s.key)}>{s.label}</button>)}
      </div>
      <div data-testid={`taxes-${cur.key}`}>
        {cur.key === 'gst' && <GstTab {...p} />}
        {cur.key === 'cgt' && <CgtTab {...p} legacy={legacyCgt} />}
        {cur.key === 'fbt' && <FbtTab {...p} />}
        {cur.key === 'income' && <IncomeTab {...p} />}
        {cur.key === 'lodgment' && <LodgmentReadinessTab {...p} />}
        {cur.key === 'planning' && <PlanningTab {...p} />}
        {cur.key === 'workpapers' && <WorkpapersTab {...p} />}
      </div>
    </div>)
}
