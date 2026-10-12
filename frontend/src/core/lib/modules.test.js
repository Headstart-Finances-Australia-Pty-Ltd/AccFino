import { describe, it, expect } from 'vitest'
import { DOMAINS, MODULES, domainGroups, homeGroups, visibleGroups, tabsForDomain, activeLeafId, isAreaItem } from './modules.js'

const all = () => true

describe('visibleGroups (side panel / Overview filtering)', () => {
  it('keeps every domain when nothing is hidden', () => {
    expect(visibleGroups(domainGroups(), all, all)).toHaveLength(DOMAINS.length)
  })
  it('drops a hidden domain entirely', () => {
    const g = visibleGroups(domainGroups(), id => id !== 'practice', all)
    expect(g.map(x => x.domain.id)).not.toContain('practice')
    expect(g).toHaveLength(DOMAINS.length - 1)
  })
  it('drops a hidden module but keeps its domain', () => {
    const g = visibleGroups(domainGroups(), all, id => id !== 'expenses')
    const acc = g.find(x => x.domain.id === 'accounting')
    expect(acc).toBeTruthy()
    expect(acc.items.map(m => m.id)).not.toContain('expenses')
    expect(acc.items.map(m => m.id)).toContain('general-ledger')
  })
  it('drops a domain left with no visible modules (no empty pages linked)', () => {
    const ids = new Set(MODULES.filter(m => m.domain === 'practice').map(m => m.id))
    const g = visibleGroups(domainGroups(), all, id => !ids.has(id))
    expect(g.map(x => x.domain.id)).not.toContain('practice')
  })
})

describe('tabsForDomain (hub page tab bars)', () => {
  const TABS = [{ key: 'dashboard' }, { key: 'ledger' }, { key: 'expenses' }, { key: 'not-in-registry' }]
  it('removes tabs whose module is hidden', () => {
    const keys = tabsForDomain('accounting', TABS, id => id !== 'expenses').map(t => t.key)
    expect(keys).toEqual(['dashboard', 'ledger', 'not-in-registry'])
  })
  it('treats the module without a tab field as the default "dashboard" tab', () => {
    const keys = tabsForDomain('accounting', TABS, id => id !== 'dashboard-accounting').map(t => t.key)
    expect(keys).not.toContain('dashboard')
  })
  it('keeps tabs that are unknown to the registry rather than hiding them by accident', () => {
    expect(tabsForDomain('accounting', TABS, () => false).map(t => t.key)).toEqual(['not-in-registry'])
  })
})

describe('activeLeafId', () => {
  const items = MODULES.filter(m => m.domain === 'accounting')
  it('finds the module for a tab', () => {
    expect(activeLeafId(items, { pathname: '/accounting', search: '?tab=ledger' })).toBe('general-ledger')
  })
  it('falls back to the default module when there is no tab', () => {
    expect(activeLeafId(items, { pathname: '/accounting', search: '' })).toBe('dashboard-accounting')
  })
  it('returns null for a page outside the domain', () => {
    expect(activeLeafId(items, { pathname: '/payroll', search: '' })).toBeNull()
  })
})

describe('registry integrity', () => {
  it('has unique module ids', () => {
    const ids = MODULES.map(m => m.id)
    expect(new Set(ids).size).toBe(ids.length)
  })
  it('never lists the same (route, tab) twice within a domain', () => {
    const seen = new Set()
    for (const m of MODULES.filter(x => x.route)) {
      const k = `${m.domain}|${m.route}|${m.tab || ''}`
      expect(seen.has(k), k).toBe(false)
      seen.add(k)
    }
  })
  it('gives every domain a routable landing module', () => {
    for (const g of domainGroups()) expect(g.items.find(m => m.route), g.domain.id).toBeTruthy()
  })
  it('never maps a route-less capability entry onto a hub tab', () => {
    const keys = tabsForDomain('accounting', [{ key: 'dashboard' }], id => id !== 'openfeed-open-banking')
    expect(keys.map(t => t.key)).toEqual(['dashboard'])           // hiding a capability flag must not hide the Dashboard tab
  })
  it('does not link a domain whose only visible modules have no route', () => {
    const routable = new Set(MODULES.filter(m => m.domain === 'accounting' && m.route).map(m => m.id))
    const g = visibleGroups(domainGroups(), all, id => !routable.has(id))
    expect(g.map(x => x.domain.id)).not.toContain('accounting')
  })
})

describe('Settings/Admin switches never appear as business tiles', () => {
  const areaIds = MODULES.filter(isAreaItem).map(m => m.id)
  it('exist (13 today) and each names its area and group', () => {
    expect(areaIds.length).toBeGreaterThan(0)
    for (const m of MODULES.filter(isAreaItem)) { expect(['settings', 'admin']).toContain(m.area); expect(m.group, m.id).toBeTruthy() }
  })
  it('are excluded from the Overview and side-panel groups', () => {
    for (const g of [...homeGroups(), ...domainGroups()]) for (const m of g.items) expect(areaIds, m.id).not.toContain(m.id)
  })
  it('leave Smart Lending with lending modules only', () => {
    const ids = homeGroups().find(g => g.domain.id === 'lending_treasury').items.map(m => m.id)
    expect(ids).toEqual(['financial-statement-analysis', 'credit-assessment', 'loan-origination', 'loan-management', 'collections', 'treasury-liquidity'])
  })
  it('leave Books and Accounting with accounting modules only', () => {
    const ids = homeGroups().find(g => g.domain.id === 'accounting').items.map(m => m.id)
    // Expenses, Inventory and Fixed Assets are one tile, Assets and Costs, listed right after Reconciliation
    expect(ids).toEqual(['dashboard-accounting', 'general-ledger', 'reconciliation', 'assets-costs', 'sales', 'purchases', 'financial-reports'])
  })
  it('Taxation shows Taxes and Tax Workings as their own tiles beside Tax Returns, not the seven modules inside them', () => {
    const ids = homeGroups().find(g => g.domain.id === 'tax_compliance').items.map(m => m.id)
    expect(ids.slice(0, 4)).toEqual(['overview-tax', 'tax-returns', 'taxes', 'tax-workings'])
    for (const hidden of ['gst-bas-ias', 'cgt', 'fbt-other-taxes', 'income-tax', 'tax-lodgement-ato', 'tax-planning', 'tax-workpapers']) expect(ids).not.toContain(hidden)
  })
  it('a group shows while any member is on, and goes when all are off', () => {
    const all = () => true
    const accIds = isOn => visibleGroups(domainGroups(), all, isOn).find(g => g.domain.id === 'accounting').items.map(m => m.id)
    expect(accIds(id => id !== 'expenses' && id !== 'inventory-trading')).toContain('assets-costs')
    expect(accIds(id => !['expenses', 'inventory-trading', 'fixed-assets'].includes(id))).not.toContain('assets-costs')
  })
})

describe('Admin Console switches for Open Banking and Payment Card Setup', () => {
  const adminItems = MODULES.filter(m => m.area === 'admin')
  const inGroup = g => adminItems.filter(m => m.group === g).map(m => m.id).sort()
  it('Open Banking has its own Basiq and OpenFeed switches under Admin Console (not only under Settings)', () => {
    expect(inGroup('Open Banking')).toEqual(['basiq-admin-open-banking', 'openfeed-admin-open-banking'])
    expect(MODULES.filter(m => m.area === 'settings' && m.group === 'Open Banking').map(m => m.id).sort()).toEqual(['basiq-open-banking', 'openfeed-open-banking'])
  })
  it('Payment Card Setup has Square and Stripe switches under Admin Console', () => {
    expect(inGroup('Payment Card Setup')).toEqual(['square-admin-payments', 'stripe-admin-payments'])
  })
  it('every Admin Console switch names where it lives', () => {
    for (const m of adminItems) { expect(m.sub, m.id).toMatch(/^Admin > /); expect(m.blurb, m.id).toBeTruthy() }
  })
})

describe('Payroll & Workforce on Home (sub-tab modules are grouped under their parent)', () => {
  it('lists only the top-level payroll modules, not the sub-tabs inside Payrun or Time & Leave', () => {
    const ids = homeGroups().find(g => g.domain.id === 'payroll_workforce').items.map(m => m.id)
    expect(ids).toEqual(['overview-payroll', 'employees', 'time-leave', 'payrun', 'stp-lodgement', 'payroll-reports', 'payroll-settings', 'my-pay'])        // My Pay has its own Home tile
  })
  it('no payroll module is flagged Preview: they are all Live (so no "Preview" badge on the Home tiles)', () => {
    for (const m of MODULES.filter(x => x.domain === 'payroll_workforce')) expect(m.status, m.id).toBe('live')
    expect(MODULES.find(x => x.id === 'my-pay').home).not.toBe(false)
  })
  it('every parent exists in the same domain, and sub-tab modules stay in the plan/visibility list', () => {
    for (const m of MODULES.filter(x => x.parent)) {
      const p = MODULES.find(x => x.id === m.parent)
      expect(p, m.id).toBeTruthy(); expect(p.domain).toBe(m.domain); expect(p.parent).toBeUndefined()
    }
    const ids = domainGroups().find(g => g.domain.id === 'payroll_workforce').items.map(m => m.id)
    expect(ids).toContain('my-pay')       // still in the plan / visibility list and the Payroll page
    for (const id of ['pay-runs', 'payslips', 'payroll-payments', 'superannuation', 'payg-withholding', 'payroll-audit', 'pay-items', 'timesheets', 'leave-entitlements']) expect(ids).toContain(id)
  })
})

