import React from 'react'
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, fireEvent, waitFor, within } from '@testing-library/react'

vi.mock('react-hot-toast', () => ({ default: Object.assign(vi.fn(), { success: vi.fn(), error: vi.fn() }) }))
vi.mock('../lib/api.js', () => ({ getModuleVisibility: vi.fn(), saveModuleVisibility: vi.fn(() => Promise.resolve({ data: {} })) }))
vi.mock('../../modules/accounting/lib/api.js', () => ({ getModuleVisibility: vi.fn(), saveModuleVisibility: vi.fn(() => Promise.resolve({ data: {} })) }))
vi.mock('../../modules/billing/lib/api.js', () => ({ getModuleVisibility: vi.fn(), saveModuleVisibility: vi.fn(() => Promise.resolve({ data: {} })) }))
vi.mock('../../modules/cashflow/lib/api.js', () => ({ getModuleVisibility: vi.fn(), saveModuleVisibility: vi.fn(() => Promise.resolve({ data: {} })) }))
vi.mock('../../modules/open_banking/lib/api.js', () => ({ getModuleVisibility: vi.fn(), saveModuleVisibility: vi.fn(() => Promise.resolve({ data: {} })) }))
vi.mock('../../modules/reconciliation/lib/api.js', () => ({ getModuleVisibility: vi.fn(), saveModuleVisibility: vi.fn(() => Promise.resolve({ data: {} })) }))
vi.mock('../../modules/trading/lib/api.js', () => ({ getModuleVisibility: vi.fn(), saveModuleVisibility: vi.fn(() => Promise.resolve({ data: {} })) }))
vi.mock('../lib/adminApi.js', async () => {
  const actual = await vi.importActual('../lib/adminApi.js')
  return { ...actual, adminGetBulkImport: vi.fn(() => Promise.resolve({ data: { enabled: true } })), adminSetBulkImport: vi.fn(), adminGetForceDelete: vi.fn(() => Promise.resolve({ data: { enabled: false } })),
    adminSetForceDelete: vi.fn(), adminSubOverview: vi.fn(() => Promise.resolve({ data: { settings: { enforced: false, default_plan: 'essential' }, plans: [], addons: [], catalogue: [], domains: [], organisations: [] } })) }
})
vi.mock('../../modules/accounting/lib/booksApi.js', async () => {
  const actual = await vi.importActual('../../modules/accounting/lib/booksApi.js')
  return { ...actual, adminGetBulkImport: vi.fn(() => Promise.resolve({ data: { enabled: true } })), adminSetBulkImport: vi.fn(), adminGetForceDelete: vi.fn(() => Promise.resolve({ data: { enabled: false } })),
    adminSetForceDelete: vi.fn(), adminSubOverview: vi.fn(() => Promise.resolve({ data: { settings: { enforced: false, default_plan: 'essential' }, plans: [], addons: [], catalogue: [], domains: [], organisations: [] } })) }
})
vi.mock('../../modules/billing/lib/orgBillingApi.js', async () => {
  const actual = await vi.importActual('../../modules/billing/lib/orgBillingApi.js')
  return { ...actual, adminGetBulkImport: vi.fn(() => Promise.resolve({ data: { enabled: true } })), adminSetBulkImport: vi.fn(), adminGetForceDelete: vi.fn(() => Promise.resolve({ data: { enabled: false } })),
    adminSetForceDelete: vi.fn(), adminSubOverview: vi.fn(() => Promise.resolve({ data: { settings: { enforced: false, default_plan: 'essential' }, plans: [], addons: [], catalogue: [], domains: [], organisations: [] } })) }
})
vi.mock('../../modules/open_banking/lib/feedApi.js', async () => {
  const actual = await vi.importActual('../../modules/open_banking/lib/feedApi.js')
  return { ...actual, adminGetBulkImport: vi.fn(() => Promise.resolve({ data: { enabled: true } })), adminSetBulkImport: vi.fn(), adminGetForceDelete: vi.fn(() => Promise.resolve({ data: { enabled: false } })),
    adminSetForceDelete: vi.fn(), adminSubOverview: vi.fn(() => Promise.resolve({ data: { settings: { enforced: false, default_plan: 'essential' }, plans: [], addons: [], catalogue: [], domains: [], organisations: [] } })) }
})
import * as api from '../lib/api.js'
import ModulesAdminPage from '../pages/ModulesAdminPage.jsx'

beforeEach(() => { vi.clearAllMocks(); api.getModuleVisibility.mockResolvedValue({ data: { domains: {}, modules: {} } }) })

const adminSection = async () => (await screen.findByText('Admin Console')).closest('div[style]').parentElement

describe('Modules Management > Settings & Admin Console', () => {
  it('lists Open Banking (Basiq, OpenFeed) and Payment Card Setup (Square, Stripe) under the Admin Console, alongside the Settings ones', async () => {
    render(<ModulesAdminPage />)
    await screen.findByText('Settings & Admin Console')
    const admin = await adminSection()
    const text = admin.textContent
    for (const t of ['Payment Card Setup', 'Square', 'Stripe', 'Open Banking', 'Basiq', 'OpenFeed', 'ML Training']) expect(text, t).toContain(t)
    expect(within(admin).getAllByRole('checkbox').length).toBeGreaterThanOrEqual(10)         // 4 for these two groups + the other Admin Console items
    expect((await screen.findAllByText('OpenFeed')).length).toBeGreaterThanOrEqual(2)       // once under Admin Console, once under Settings
  })

  it('switching the Admin Console OpenFeed item off is saved under its own id, separate from the Settings one', async () => {
    render(<ModulesAdminPage />)
    await screen.findByText('Settings & Admin Console')
    const admin = await adminSection()
    const box = within(admin).getByText('OpenFeed').closest('label, div').querySelector('input[type=checkbox]')
    fireEvent.click(box)
    fireEvent.click(screen.getAllByRole('button', { name: /Save changes/ })[0])
    await waitFor(() => expect(api.saveModuleVisibility).toHaveBeenCalled())
    const saved = api.saveModuleVisibility.mock.calls[0][0]
    expect(saved.modules['openfeed-admin-open-banking']).toBe(false)
    expect(saved.modules['openfeed-open-banking']).not.toBe(false)
  })
})
