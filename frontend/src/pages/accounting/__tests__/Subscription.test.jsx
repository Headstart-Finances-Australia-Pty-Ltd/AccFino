import React from 'react'
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, waitFor, fireEvent } from '@testing-library/react'

const CATALOGUE = [{ id: 'sales', name: 'Sales' }, { id: 'expenses', name: 'Expense claims' }, { id: 'inventory-trading', name: 'Inventory' }]
const subscription = (over = {}) => ({ enforced: true, grandfathered: false, plan_id: 'essential', plan_name: 'Essential', status: 'active', read_only: false, modules: ['sales'], locked: ['expenses', 'inventory-trading'],
  seats: 3, seats_used: 3, addons: [], period_end: null, trial_ends: null, catalogue: CATALOGUE, can_manage: true,
  plans: [{ id: 'essential', name: 'Essential', description: 'Core', price_monthly: '29.00', price_yearly: '290.00', seat_limit: 3, modules: ['sales'] }, { id: 'premium', name: 'Premium', description: 'All', price_monthly: '149.00', price_yearly: '1490.00', seat_limit: null, modules: ['*'] }],
  addon_catalogue: [{ id: 'addon-expenses', name: 'Expense claims', price_monthly: '10.00', modules: ['expenses'], extra_seats: 0 }], ...over })

vi.mock('../../../lib/api.js', async importOriginal => ({ ...(await importOriginal()), getModuleVisibility: vi.fn(() => Promise.resolve({ data: { domains: {}, modules: {} } })) }))
vi.mock('../../../lib/booksApi.js', async () => {
  const { booksApiMockFactory } = await import('./testUtils.js')
  const base = await booksApiMockFactory()
  return { ...base,
    getSubscription: vi.fn(), requestSubscription: vi.fn(() => Promise.resolve({ data: { ok: true, message: 'recorded' } })),
    adminSubOverview: vi.fn(), adminSubSettings: vi.fn(() => Promise.resolve({ data: {} })), adminSavePlan: vi.fn(() => Promise.resolve({ data: {} })),
    adminDeletePlan: vi.fn(), adminSaveAddon: vi.fn(), adminDeleteAddon: vi.fn(), adminAssignOrgPlan: vi.fn(() => Promise.resolve({ data: {} })) }
})

import * as api from '../../../lib/booksApi.js'
import { ModuleVisibilityProvider, useModuleVisibility } from '../../../hooks/useModuleVisibility.jsx'
import SubscriptionCard from '../../../components/subscription/SubscriptionCard.jsx'
import SubscriptionAdminPanel from '../../admin/SubscriptionAdminPanel.jsx'

beforeEach(() => { api.getSubscription.mockImplementation(() => Promise.resolve({ data: subscription() })) })

function Probe() {
  const { isModuleVisible } = useModuleVisibility()
  return <div><span data-testid="sales">{String(isModuleVisible('sales'))}</span><span data-testid="expenses">{String(isModuleVisible('expenses'))}</span></div>
}

describe('entitlements drive the menu', () => {
  it('locked modules are hidden, and an upgrade shows up without reloading', async () => {
    render(<ModuleVisibilityProvider><Probe /></ModuleVisibilityProvider>)
    await waitFor(() => expect(screen.getByTestId('expenses')).toHaveTextContent('false'))
    expect(screen.getByTestId('sales')).toHaveTextContent('true')
    api.getSubscription.mockImplementation(() => Promise.resolve({ data: subscription({ locked: [], modules: ['sales', 'expenses'] }) }))
    window.dispatchEvent(new Event('accfino:subscription-changed'))                           // what Admin dispatches after assigning a plan
    await waitFor(() => expect(screen.getByTestId('expenses')).toHaveTextContent('true'))
  })

  it('fails open when the subscription cannot be read', async () => {
    api.getSubscription.mockImplementation(() => Promise.reject(new Error('offline')))
    render(<ModuleVisibilityProvider><Probe /></ModuleVisibilityProvider>)
    await waitFor(() => expect(screen.getByTestId('sales')).toHaveTextContent('true'))
    expect(screen.getByTestId('expenses')).toHaveTextContent('true')
  })
})

describe('SubscriptionCard (owner view)', () => {
  it('shows plan, seats, locked modules, and lets an owner request an add-on', async () => {
    render(<SubscriptionCard />)
    await waitFor(() => expect(screen.getByTestId('subscription-card')).toBeInTheDocument())
    expect(screen.getByTestId('subscription-card').querySelector('b').textContent).toBe('Essential')
    expect(screen.getByText('3 of 3')).toBeInTheDocument()
    expect(screen.getByTestId('sub-module-expenses')).toHaveTextContent('Not in your plan')
    fireEvent.click(screen.getByRole('button', { name: /Request Expense claims/ }))
    await waitFor(() => expect(api.requestSubscription).toHaveBeenCalledWith({ addon_ids: ['addon-expenses'], message: 'Request: add Expense claims' }))
    fireEvent.click(screen.getByRole('button', { name: 'Request Premium' }))
    await waitFor(() => expect(api.requestSubscription).toHaveBeenCalledWith({ plan_id: 'premium', message: 'Request: change to Premium' }))
  })

  it('members who are not owners cannot request changes; read-only is explained', async () => {
    api.getSubscription.mockImplementation(() => Promise.resolve({ data: subscription({ can_manage: false, read_only: true, status: 'expired' }) }))
    render(<SubscriptionCard />)
    await waitFor(() => expect(screen.getByTestId('subscription-card')).toBeInTheDocument())
    expect(screen.queryByRole('button', { name: /Request/ })).not.toBeInTheDocument()
    expect(screen.getByText(/so the organisation is read-only/)).toBeInTheDocument()
  })

  it('says limits are not enforced yet when enforcement is off', async () => {
    api.getSubscription.mockImplementation(() => Promise.resolve({ data: subscription({ enforced: false, locked: [] }) }))
    render(<SubscriptionCard />)
    await waitFor(() => expect(screen.getByText(/not being enforced yet/)).toBeInTheDocument())
  })
})

describe('SubscriptionAdminPanel', () => {
  const overview = () => ({ settings: { enforced: false, default_plan: 'essential' }, catalogue: CATALOGUE,
    plans: [{ id: 'essential', name: 'Essential', description: '', price_monthly: '29.00', price_yearly: '290.00', seat_limit: 3, modules: ['sales'], is_active: true, sort_order: 1 }],
    addons: [{ id: 'addon-expenses', name: 'Expense claims', description: '', price_monthly: '10.00', modules: ['expenses'], extra_seats: 0, is_active: true, sort_order: 1 }],
    organisations: [{ org_id: 7, name: 'Acme Org', members: 2, plan_id: 'essential', addons: [], status: 'active', effective_status: 'active', billing_period: 'monthly', period_end: null, trial_ends: null, notes: null }] })
  beforeEach(() => { api.adminSubOverview.mockImplementation(() => Promise.resolve({ data: overview() })) })

  it('the enforcement checkbox saves immediately', async () => {
    render(<SubscriptionAdminPanel />)
    const box = await screen.findByLabelText('Enforce subscriptions')
    expect(box).not.toBeChecked()
    fireEvent.click(box)
    await waitFor(() => expect(api.adminSubSettings).toHaveBeenCalledWith({ enforced: true }))
  })

  it('assigns an add-on to an organisation (applies at once)', async () => {
    render(<SubscriptionAdminPanel />)
    const row = await screen.findByTestId('org-sub-7')
    const save = row.querySelector('button.btn-primary')
    expect(save).toBeDisabled()                                                                 // nothing changed yet
    fireEvent.click(row.querySelectorAll('input[type=checkbox]')[0])                            // tick "Expense claims"
    expect(save).not.toBeDisabled()
    fireEvent.click(save)
    await waitFor(() => expect(api.adminAssignOrgPlan).toHaveBeenCalledWith(7, expect.objectContaining({ plan_id: 'essential', addons: ['addon-expenses'], status: 'active' })))
  })

  it('creates a new plan with chosen modules', async () => {
    render(<SubscriptionAdminPanel />)
    fireEvent.click(await screen.findByRole('button', { name: '+ New plan' }))
    fireEvent.change(screen.getByLabelText('Plan id'), { target: { value: 'gold' } })
    fireEvent.change(screen.getByLabelText('Plan name'), { target: { value: 'Gold' } })
    fireEvent.click(screen.getByLabelText(/Inventory/))
    fireEvent.click(screen.getByRole('button', { name: 'Save plan' }))
    await waitFor(() => expect(api.adminSavePlan).toHaveBeenCalledWith('gold', expect.objectContaining({ name: 'Gold', modules: ['inventory-trading'], seat_limit: null })))
  })
})
