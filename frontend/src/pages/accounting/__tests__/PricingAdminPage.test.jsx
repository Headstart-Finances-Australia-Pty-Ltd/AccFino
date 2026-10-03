import React from 'react'
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, fireEvent, waitFor } from '@testing-library/react'

vi.mock('react-hot-toast', () => ({ default: Object.assign(vi.fn(), { success: vi.fn(), error: vi.fn() }) }))
vi.mock('../../../lib/api', () => ({ getPricingPlans: vi.fn(() => Promise.resolve({ data: { base: { name: 'Vault', price_monthly: 0, price_yearly: 0, modules: [], features: [] } } })), updatePricingPlan: vi.fn() }))
vi.mock('../../../lib/booksApi.js', async () => {
  const actual = await vi.importActual('../../../lib/booksApi.js')
  return { ...actual, adminSubOverview: vi.fn(), adminGetForceDelete: vi.fn(() => Promise.resolve({ data: { enabled: false } })) }
})
import * as booksApi from '../../../lib/booksApi.js'
import PricingAdminPage from '../../PricingAdminPage.jsx'

const PLANS = [['essential', 'Essential', '25.00', 1], ['business', 'Business', '59.00', 3], ['professional', 'Professional', '99.00', 6], ['ultra', 'Ultra', '179.00', 15]]
beforeEach(() => {
  vi.clearAllMocks()
  booksApi.adminSubOverview.mockResolvedValue({ data: { settings: { enforced: false, default_plan: 'essential' }, catalogue: [], domains: [], addons: [], organisations: [],
    plans: PLANS.map(([id, name, m, seats], i) => ({ id, name, description: '', price_monthly: m, price_yearly: String(Number(m) * 10), seat_limit: seats, modules: ['*'], is_active: true, sort_order: i + 1 })) } })
})

describe('Admin Console > Pricing', () => {
  it('shows the current plans with their users, not the old Vault / Opus price list', async () => {
    render(<PricingAdminPage />)
    expect(await screen.findByText('Plans & Pricing')).toBeInTheDocument()
    await waitFor(() => expect(screen.getAllByText('Ultra').length).toBeGreaterThan(0))
    for (const [, name, m] of PLANS) { expect(screen.getAllByText(name).length).toBeGreaterThan(0); expect(screen.getAllByText(`$${m}`).length).toBeGreaterThan(0) }
    expect(screen.queryByText('Vault')).toBeNull()                                               // the legacy editor is hidden until asked for
  })

  it('keeps the legacy per-user plans one click away, clearly labelled', async () => {
    render(<PricingAdminPage />)
    await screen.findByText('Plans & Pricing')
    fireEvent.click(screen.getByTestId('legacy-toggle'))
    expect(await screen.findByText('Legacy per-user plans')).toBeInTheDocument()
    expect(await screen.findByText('Vault')).toBeInTheDocument()
  })
})
