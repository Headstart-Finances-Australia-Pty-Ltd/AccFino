import React from 'react'
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, fireEvent, waitFor, within } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'

let lockedNow = new Set()
vi.mock('../hooks/useModuleVisibility.jsx', () => ({ useModuleVisibility: () => ({ isLocked: id => lockedNow.has(id), isModuleVisible: id => !lockedNow.has(id) && !(['basiq-open-banking', 'openfeed-open-banking'].includes(id) && lockedNow.has('open-banking')), subscription: { plan_name: 'Essential' } }) }))
vi.mock('react-hot-toast', () => ({ default: Object.assign(vi.fn(), { success: vi.fn(), error: vi.fn() }) }))
vi.mock('../lib/adminApi.js', async () => {
  const actual = await vi.importActual('../lib/adminApi.js')
  return { ...actual, obFeedStatus: vi.fn(), adminSubOverview: vi.fn(), adminSavePlan: vi.fn(() => Promise.resolve({ data: {} })), adminGetForceDelete: vi.fn(() => Promise.resolve({ data: { enabled: false } })) }
})
vi.mock('../../modules/accounting/lib/booksApi.js', async () => {
  const actual = await vi.importActual('../../modules/accounting/lib/booksApi.js')
  return { ...actual, obFeedStatus: vi.fn(), adminSubOverview: vi.fn(), adminSavePlan: vi.fn(() => Promise.resolve({ data: {} })), adminGetForceDelete: vi.fn(() => Promise.resolve({ data: { enabled: false } })) }
})
vi.mock('../../modules/billing/lib/orgBillingApi.js', async () => {
  const actual = await vi.importActual('../../modules/billing/lib/orgBillingApi.js')
  return { ...actual, obFeedStatus: vi.fn(), adminSubOverview: vi.fn(), adminSavePlan: vi.fn(() => Promise.resolve({ data: {} })), adminGetForceDelete: vi.fn(() => Promise.resolve({ data: { enabled: false } })) }
})
vi.mock('../../modules/open_banking/lib/feedApi.js', async () => {
  const actual = await vi.importActual('../../modules/open_banking/lib/feedApi.js')
  return { ...actual, obFeedStatus: vi.fn(), adminSubOverview: vi.fn(), adminSavePlan: vi.fn(() => Promise.resolve({ data: {} })), adminGetForceDelete: vi.fn(() => Promise.resolve({ data: { enabled: false } })) }
})
import * as api__0 from '../lib/adminApi.js'
import * as api__1 from '../../modules/open_banking/lib/feedApi.js'
import BankFeedCard from '../../modules/open_banking/components/BankFeedCard.jsx'
import SubscriptionAdminPanel from '../pages/admin/SubscriptionAdminPanel.jsx'

beforeEach(() => { vi.clearAllMocks(); lockedNow = new Set() })

describe('Open banking is a plan function', () => {
  it('the plan editor has a Functions checkbox for Open banking, separate from the business domains, and saving keeps it in the plan', async () => {
    api__0.adminSubOverview.mockResolvedValue({ data: { settings: { enforced: true, default_plan: 'essential' }, catalogue: [{ id: 'sales', name: 'Sales' }, { id: 'open-banking', name: 'Open banking - live bank feeds' }],
      domains: [{ id: 'accounting', name: 'Books and Accounting', modules: ['sales'] }], features: [{ id: 'open-banking', name: 'Open banking - live bank feeds', description: 'Connect bank accounts' }],
      addons: [], organisations: [], plans: [{ id: 'essential', name: 'Essential', description: '', price_monthly: '25.00', price_yearly: '275.00', seat_limit: 1, modules: ['domain:accounting', 'open-banking'], is_active: true, sort_order: 1 }] } })
    render(<SubscriptionAdminPanel />)
    fireEvent.click((await screen.findAllByRole('button', { name: 'Edit' }))[0])
    const box = await screen.findByTestId('plan-functions')
    const cb = within(box).getByLabelText('Open banking - live bank feeds')
    expect(cb).toBeChecked()                                                           // included in Essential
    fireEvent.click(cb)                                                                // switch it off for this plan
    expect(cb).not.toBeChecked()
    expect(screen.getByLabelText('Whole domain Books and Accounting')).toBeChecked()   // the business domain is untouched
  })

  it('the bank feed card says plainly when the plan leaves open banking out', async () => {
    api__1.obFeedStatus.mockResolvedValue({ data: { available: true, status: 'not_connected', can_manage: true, accounts: [], plan_allows: false, plan_name: 'Essential' } })
    render(<MemoryRouter><BankFeedCard /></MemoryRouter>)
    expect(await screen.findByTestId('feed-not-in-plan')).toHaveTextContent(/Essential plan doesn't include open banking/)
    expect(screen.queryByTestId('connect-bank-btn')).toBeNull()
  })
})
