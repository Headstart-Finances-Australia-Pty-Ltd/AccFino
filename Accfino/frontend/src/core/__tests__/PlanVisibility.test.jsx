import React from 'react'
import { describe, it, expect, vi } from 'vitest'
import { render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { domainGroups, homeGroups, visibleGroups, tabsForDomain, moduleAtLocation, MODULES, isAreaItem } from '../lib/modules.js'

// What the server says is LOCKED for an organisation on the Essential plan: everything outside Books & Accounting (which Essential includes IN FULL).
const STARTER = new Set(MODULES.filter(m => m.domain === 'accounting' && !isAreaItem(m)).map(m => m.id))
const sellable = MODULES.filter(m => !isAreaItem(m)).map(m => m.id)
const LOCKED = new Set(sellable.filter(id => !STARTER.has(id) && id !== 'bulk-import'))
const domainOn = () => true
const modOn = id => !LOCKED.has(id)

let lockedNow = new Set()
let isOrgAdminNow = true
vi.mock('../hooks/useModuleVisibility.jsx', () => ({ useModuleVisibility: () => ({ isLocked: id => lockedNow.has(id), subscription: { plan_name: 'Essential' } }) }))
vi.mock('../hooks/useOrgRole.jsx', () => ({ default: () => ({ isOrgAdmin: isOrgAdminNow }) }))
import PlanGate from '../components/subscription/PlanGate.jsx'

describe('modules a plan does not include disappear everywhere', () => {
  it('side panel: a Essential organisation sees Books and Accounting - ALL of it - and no other business domain', () => {
    const g = visibleGroups(domainGroups(), domainOn, modOn)
    expect(g.map(x => x.domain.id)).toEqual(['accounting'])
    const acc = g[0].items.flatMap(m => m.members || [m.id])       // a group (Assets and Costs) stands for its member modules
    expect(acc.sort()).toEqual([...STARTER].sort())
    for (const shown of ['dashboard-accounting', 'general-ledger', 'reconciliation', 'sales', 'purchases', 'expenses', 'inventory-trading', 'fixed-assets', 'financial-reports']) expect(acc).toContain(shown)
    expect(acc).not.toContain('cash-flow-forecasting')                  // Planning & Intelligence is Business and above
  })

  it('Home / dashboard tiles use the same rule', () => {
    const g = visibleGroups(homeGroups(), domainOn, modOn)
    expect(g.map(x => x.domain.id)).toEqual(['accounting'])
    expect(g.flatMap(x => x.items.flatMap(m => m.members || [m.id])).every(id => STARTER.has(id))).toBe(true)
  })

  it('the tab bar on a hub page (the main area) keeps every Books and Accounting tab for Essential', () => {
    const TABS = [{ key: 'dashboard' }, { key: 'ledger' }, { key: 'reconciliation' }, { key: 'sales' }, { key: 'purchases' }, { key: 'expenses' }, { key: 'inventory' }, { key: 'fixed-assets' }, { key: 'reports' }]
    expect(tabsForDomain('accounting', TABS, modOn).map(t => t.key)).toEqual(TABS.map(t => t.key))
    const TAX = MODULES.filter(m => m.domain === 'tax_compliance' && m.route).map(m => ({ key: m.tab || 'dashboard' }))      // the real tab keys of that hub
    expect(TAX.length).toBeGreaterThan(3)
    expect(tabsForDomain('tax_compliance', TAX, modOn)).toEqual([])      // every tab of another domain is gone
  })

  it('a plan with the whole of one domain keeps that domain complete', () => {
    const payroll = new Set(MODULES.filter(m => m.domain === 'payroll_workforce' && !isAreaItem(m)).map(m => m.id))
    const lockedWithoutPayroll = new Set([...LOCKED].filter(id => !payroll.has(id)))
    const g = visibleGroups(domainGroups(), domainOn, id => !lockedWithoutPayroll.has(id))
    expect(g.map(x => x.domain.id)).toContain('payroll_workforce')
    expect(g.find(x => x.domain.id === 'payroll_workforce').items.length).toBe(payroll.size)
  })
})

describe('moduleAtLocation: which module is this page?', () => {
  const at = (pathname, search = '') => moduleAtLocation({ pathname, search })
  it('finds the module by route and tab, including a hub page\'s default tab', () => {
    expect(at('/accounting')?.id).toBe('dashboard-accounting')
    expect(at('/accounting', '?tab=expenses')?.id).toBe('expenses')
    expect(at('/accounting', '?tab=reports')?.id).toBe('financial-reports')
    expect(at('/payroll', '?tab=payslips')?.id).toBe('payslips')
  })
  it('pages that are not business modules are never gated', () => {
    for (const p of ['/', '/settings/setup', '/admin/pricing', '/my-account', '/nowhere']) expect(at(p)).toBeNull()
  })
})

describe('PlanGate: a locked page opened from a typed address', () => {
  const show = (path) => render(<MemoryRouter initialEntries={[path]}><PlanGate><div data-testid="page">the page</div></PlanGate></MemoryRouter>)
  it('shows an explanation instead of the page, with the upgrade route for the Organisation Admin', () => {
    lockedNow = new Set(['payslips']); isOrgAdminNow = true
    show('/payroll?tab=payslips')
    expect(screen.queryByTestId('page')).toBeNull()
    expect(screen.getByTestId('not-in-plan')).toHaveTextContent(`${MODULES.find(m => m.id === 'payslips').name} is not part of your plan`); expect(screen.getByTestId('not-in-plan')).toHaveTextContent('Essential')
    expect(screen.getByTestId('plan-gate-upgrade')).toHaveAttribute('href', '/settings/setup')
  })
  it('a member who is not the Organisation Admin is told to ask them, with no upgrade button', () => {
    lockedNow = new Set(['payslips']); isOrgAdminNow = false
    show('/payroll?tab=payslips')
    expect(screen.getByTestId('not-in-plan')).toHaveTextContent('Ask your Organisation Admin'); expect(screen.queryByTestId('plan-gate-upgrade')).toBeNull()
  })
  it('included pages and non-module pages render normally', () => {
    lockedNow = new Set(['payslips'])
    show('/accounting?tab=sales'); expect(screen.getByTestId('page')).toBeInTheDocument()
    show('/settings/setup'); expect(screen.getAllByTestId('page').length).toBe(2)
  })
  it('nothing is blocked when nothing is locked (subscriptions not enforced, or no plan assigned)', () => {
    lockedNow = new Set(); isOrgAdminNow = true
    show('/payroll?tab=payslips'); expect(screen.getByTestId('page')).toBeInTheDocument(); expect(screen.queryByTestId('not-in-plan')).toBeNull()
  })
})
