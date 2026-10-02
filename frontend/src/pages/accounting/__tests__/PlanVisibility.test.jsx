import React from 'react'
import { describe, it, expect, vi } from 'vitest'
import { render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { domainGroups, homeGroups, visibleGroups, tabsForDomain, moduleAtLocation, MODULES, isAreaItem } from '../../../lib/modules.js'

// What the server says is LOCKED for an organisation on the Essentials plan (subscriptions enforced): everything except the core books + cash-flow forecasting.
const ESSENTIALS = new Set(['dashboard-accounting', 'general-ledger', 'reconciliation', 'sales', 'purchases', 'financial-reports', 'cash-flow-forecasting'])
const sellable = MODULES.filter(m => !isAreaItem(m)).map(m => m.id)
const LOCKED = new Set(sellable.filter(id => !ESSENTIALS.has(id) && id !== 'bulk-import'))
const domainOn = () => true
const modOn = id => !LOCKED.has(id)

let lockedNow = new Set()
let isOrgAdminNow = true
vi.mock('../../../hooks/useModuleVisibility.jsx', () => ({ useModuleVisibility: () => ({ isLocked: id => lockedNow.has(id), subscription: { plan_name: 'Essentials' } }) }))
vi.mock('../../../hooks/useOrgRole.jsx', () => ({ default: () => ({ isOrgAdmin: isOrgAdminNow }) }))
import PlanGate from '../../../components/subscription/PlanGate.jsx'

describe('modules a plan does not include disappear everywhere', () => {
  it('side panel: whole business domains with nothing in the plan are gone, and the remaining ones list only what is included', () => {
    const g = visibleGroups(domainGroups(), domainOn, modOn)
    expect(g.map(x => x.domain.id).sort()).toEqual(['accounting', 'planning_insights'])
    const acc = g.find(x => x.domain.id === 'accounting').items.map(m => m.id)
    expect(acc.sort()).toEqual(['dashboard-accounting', 'financial-reports', 'general-ledger', 'purchases', 'reconciliation', 'sales'])
    for (const hidden of ['expenses', 'inventory-trading', 'fixed-assets']) expect(acc).not.toContain(hidden)
    expect(g.find(x => x.domain.id === 'planning_insights').items.map(m => m.id)).toEqual(['cash-flow-forecasting'])
  })

  it('Home / dashboard tiles use the same rule', () => {
    const g = visibleGroups(homeGroups(), domainOn, modOn)
    expect(g.map(x => x.domain.id).sort()).toEqual(['accounting', 'planning_insights'])
    expect(g.flatMap(x => x.items.map(m => m.id)).every(id => ESSENTIALS.has(id))).toBe(true)
  })

  it('the tab bar on a hub page (the main area) drops locked tabs', () => {
    const TABS = [{ key: 'dashboard' }, { key: 'ledger' }, { key: 'reconciliation' }, { key: 'sales' }, { key: 'purchases' }, { key: 'expenses' }, { key: 'inventory' }, { key: 'fixed-assets' }, { key: 'reports' }]
    expect(tabsForDomain('accounting', TABS, modOn).map(t => t.key)).toEqual(['dashboard', 'ledger', 'reconciliation', 'sales', 'purchases', 'reports'])
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
    lockedNow = new Set(['expenses']); isOrgAdminNow = true
    show('/accounting?tab=expenses')
    expect(screen.queryByTestId('page')).toBeNull()
    expect(screen.getByTestId('not-in-plan')).toHaveTextContent('Expenses is not part of your plan'); expect(screen.getByTestId('not-in-plan')).toHaveTextContent('Essentials')
    expect(screen.getByTestId('plan-gate-upgrade')).toHaveAttribute('href', '/settings/setup')
  })
  it('a member who is not the Organisation Admin is told to ask them, with no upgrade button', () => {
    lockedNow = new Set(['expenses']); isOrgAdminNow = false
    show('/accounting?tab=expenses')
    expect(screen.getByTestId('not-in-plan')).toHaveTextContent('Ask your Organisation Admin'); expect(screen.queryByTestId('plan-gate-upgrade')).toBeNull()
  })
  it('included pages and non-module pages render normally', () => {
    lockedNow = new Set(['expenses'])
    show('/accounting?tab=sales'); expect(screen.getByTestId('page')).toBeInTheDocument()
    show('/settings/setup'); expect(screen.getAllByTestId('page').length).toBe(2)
  })
  it('nothing is blocked when nothing is locked (subscriptions not enforced, or no plan assigned)', () => {
    lockedNow = new Set(); isOrgAdminNow = true
    show('/accounting?tab=expenses'); expect(screen.getByTestId('page')).toBeInTheDocument(); expect(screen.queryByTestId('not-in-plan')).toBeNull()
  })
})
