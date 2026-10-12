import React from 'react'
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, fireEvent, waitFor, within } from '@testing-library/react'

vi.mock('react-hot-toast', () => ({ default: Object.assign(vi.fn(), { success: vi.fn(), error: vi.fn() }) }))
vi.mock('../lib/adminApi.js', async () => {
  const actual = await vi.importActual('../lib/adminApi.js')
  return { ...actual, getSubscription: vi.fn(), requestSubscriptionChange: vi.fn(), adminSubOverview: vi.fn(), adminSavePlan: vi.fn(() => Promise.resolve({ data: {} })),
    adminGetForceDelete: vi.fn(() => Promise.resolve({ data: { enabled: false } })) }
})
vi.mock('../../modules/accounting/lib/booksApi.js', async () => {
  const actual = await vi.importActual('../../modules/accounting/lib/booksApi.js')
  return { ...actual, getSubscription: vi.fn(), requestSubscriptionChange: vi.fn(), adminSubOverview: vi.fn(), adminSavePlan: vi.fn(() => Promise.resolve({ data: {} })),
    adminGetForceDelete: vi.fn(() => Promise.resolve({ data: { enabled: false } })) }
})
vi.mock('../../modules/billing/lib/orgBillingApi.js', async () => {
  const actual = await vi.importActual('../../modules/billing/lib/orgBillingApi.js')
  return { ...actual, getSubscription: vi.fn(), requestSubscriptionChange: vi.fn(), adminSubOverview: vi.fn(), adminSavePlan: vi.fn(() => Promise.resolve({ data: {} })),
    adminGetForceDelete: vi.fn(() => Promise.resolve({ data: { enabled: false } })) }
})
vi.mock('../../modules/open_banking/lib/feedApi.js', async () => {
  const actual = await vi.importActual('../../modules/open_banking/lib/feedApi.js')
  return { ...actual, getSubscription: vi.fn(), requestSubscriptionChange: vi.fn(), adminSubOverview: vi.fn(), adminSavePlan: vi.fn(() => Promise.resolve({ data: {} })),
    adminGetForceDelete: vi.fn(() => Promise.resolve({ data: { enabled: false } })) }
})
import * as api from '../lib/adminApi.js'
import SubscriptionCard, { planSummary } from '../components/subscription/SubscriptionCard.jsx'
import SubscriptionAdminPanel from '../pages/admin/SubscriptionAdminPanel.jsx'

const DOMAINS = [
  { id: 'accounting', name: 'Books and Accounting', modules: ['sales', 'expenses'] },
  { id: 'payroll_workforce', name: 'Payroll & Workforce', modules: ['employees', 'pay-runs'] },
]
const CATALOGUE = [{ id: 'sales', name: 'Sales' }, { id: 'expenses', name: 'Expenses' }, { id: 'employees', name: 'Employees' }, { id: 'pay-runs', name: 'Pay Runs' }]
const ADDONS = [{ id: 'addon-payroll', name: 'Payroll & Workforce', price_monthly: '15.00', modules: ['domain:payroll_workforce'], extra_seats: 0 }]

beforeEach(() => vi.clearAllMocks())

describe('plans grouped by business domain', () => {
  it('planSummary names the domains a plan includes', () => {
    expect(planSummary({ modules: ['*'] }, DOMAINS)).toBe('all business domains')
    expect(planSummary({ modules: ['domain:accounting', 'employees'] }, DOMAINS)).toBe('Books and Accounting + 1 module')
    expect(planSummary({ modules: ['sales', 'expenses'] }, DOMAINS)).toBe('2 modules')
  })

  it('the organisation sees its modules grouped by domain and can request a whole-domain add-on in one click', async () => {
    api.getSubscription.mockResolvedValue({ data: { plan_id: 'essential', plan_name: 'Essential', status: 'active', read_only: false, seats: 3, seats_used: 1, addons: [], can_manage: true,
      catalogue: CATALOGUE, domains: DOMAINS, modules: ['sales'], locked: ['expenses', 'employees', 'pay-runs'], addon_catalogue: ADDONS, plans: [] } })
    render(<SubscriptionCard />)
    const head = await screen.findByTestId('sub-domain-payroll_workforce')
    expect(head).toHaveTextContent('Payroll & Workforce'); expect(head).toHaveTextContent('0 of 2 included')
    expect(screen.getByTestId('sub-domain-accounting')).toHaveTextContent('1 of 2 included')
    expect(within(head).getByRole('button', { name: /Request Payroll & Workforce/ })).toBeInTheDocument()
    expect(screen.getByTestId('sub-module-employees')).toHaveTextContent('Not in your plan')
  })

  it('the admin picks a whole domain with one tick (stored as domain:<id>) or single modules', async () => {
    api.adminSubOverview.mockResolvedValue({ data: { settings: { enforced: false, default_plan: 'essential' }, catalogue: CATALOGUE, domains: DOMAINS, addons: ADDONS, organisations: [],
      plans: [{ id: 'professional', name: 'Professional', description: '', price_monthly: '99.00', price_yearly: '990.00', seat_limit: 25, modules: ['domain:accounting'], is_active: true, sort_order: 3 }] } })
    render(<SubscriptionAdminPanel />)
    expect(await screen.findByText('All of Books and Accounting')).toBeInTheDocument()          // plan list shows the domain, not 40 module names
    fireEvent.click(screen.getAllByRole('button', { name: 'Edit' })[0])
    const pay = await screen.findByTestId('pick-domain-payroll_workforce')
    fireEvent.click(within(pay).getByLabelText('Whole domain Payroll & Workforce'))
    const payAfter = screen.getByTestId('pick-domain-payroll_workforce')                                   // the picker re-renders: look it up again
    expect(within(payAfter).getAllByRole('checkbox').slice(1).every(c => c.disabled && c.checked)).toBe(true)   // its modules show as included
    const acc = screen.getByTestId('pick-domain-accounting')
    expect(within(acc).getByLabelText('Whole domain Books and Accounting')).toBeChecked()
  })

  it('says plainly what the Enforce switch does: Off = every organisation sees everything, On = plans hide what they do not include', async () => {
    const overview = (enforced) => ({ data: { settings: { enforced, default_plan: 'essential' }, catalogue: CATALOGUE, domains: DOMAINS, addons: [], organisations: [], plans: [] } })
    api.adminSubOverview.mockResolvedValue(overview(false))
    const { unmount } = render(<SubscriptionAdminPanel />)
    expect(await screen.findByTestId('enforce-explainer')).toHaveTextContent('plans are not applied yet')
    expect(screen.getByTestId('enforce-explainer')).toHaveTextContent('every domain and module')
    unmount()
    api.adminSubOverview.mockResolvedValue(overview(true))
    render(<SubscriptionAdminPanel />)
    expect(await screen.findByTestId('enforce-explainer')).toHaveTextContent('in the menu, the tabs, the Home page and the dashboard')
  })
})

