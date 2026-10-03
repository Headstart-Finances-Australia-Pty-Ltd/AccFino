import React from 'react'
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, fireEvent, waitFor } from '@testing-library/react'

vi.mock('react-hot-toast', () => ({ default: Object.assign(vi.fn(), { success: vi.fn(), error: vi.fn() }) }))
vi.mock('../../../lib/booksApi.js', async () => {
  const actual = await vi.importActual('../../../lib/booksApi.js')
  return { ...actual, getSubscription: vi.fn(), requestSubscription: vi.fn(), getBilling: vi.fn() }
})
import * as api from '../../../lib/booksApi.js'
import SubscriptionCard from '../../../components/subscription/SubscriptionCard.jsx'
import BillingCard from '../../../components/billing/BillingCard.jsx'

const SUB = (over = {}) => ({ data: { plan_id: 'essential', plan_name: 'Essential', status: 'active', read_only: false, seats: 1, seats_used: 1, addons: [], can_manage: true,
  catalogue: [{ id: 'sales', name: 'Sales' }], domains: [{ id: 'accounting', name: 'Books and Accounting', modules: ['sales'] }], modules: ['sales'], locked: [], addon_catalogue: [], plans: [], ...over } })
beforeEach(() => { vi.clearAllMocks(); api.getBilling.mockResolvedValue({ data: { available: false } }) })

describe('Every plan is 1 user: more users are a pack arranged with the AccFino team', () => {
  it('the organisation sees the rule and can ask for a pack (an Organisation Admin) - there is no self-serve seat button', async () => {
    api.getSubscription.mockResolvedValue(SUB()); api.requestSubscription.mockResolvedValue({ data: { message: 'recorded' } })
    render(<SubscriptionCard />)
    const note = await screen.findByTestId('user-pack-note')
    expect(note).toHaveTextContent('Every plan is for 1 user'); expect(note).toHaveTextContent('arranged with the AccFino team')
    expect(note.querySelector('a')).toHaveAttribute('href', expect.stringContaining('mailto:contact@accfino.com'))
    fireEvent.click(screen.getByTestId('ask-user-pack'))
    await waitFor(() => expect(api.requestSubscription).toHaveBeenCalledWith(expect.objectContaining({ message: expect.stringContaining('user pack') })))
    expect(screen.queryByText(/5 extra users|1 extra user/)).toBeNull()
  })

  it('a member who is not the Organisation Admin is told to ask their admin', async () => {
    api.getSubscription.mockResolvedValue(SUB({ can_manage: false }))
    render(<SubscriptionCard />)
    const note = await screen.findByTestId('user-pack-note')
    expect(note).toHaveTextContent('Ask your Organisation Admin'); expect(screen.queryByTestId('ask-user-pack')).toBeNull()
  })

  it('yearly says one month free', async () => {
    api.getBilling.mockResolvedValue({ data: { available: true, can_manage: true, has_plan: true, plan_name: 'Essential', billing_period: 'monthly', status: 'active', prices: { monthly: 25, yearly: 275 }, amount_next: 25,
      square: { applicationId: 'x', locationId: 'y', environment: 'sandbox' }, card: { brand: 'Visa', last4: '1111', exp_month: 12, exp_year: 2030 }, auto_renew: false, failure_count: 0, charges: [] } })
    render(<BillingCard />)
    expect(await screen.findByLabelText(/Yearly \(1 month free\)/)).toBeInTheDocument()
    expect(screen.getByTestId('billing-subscribe')).toHaveTextContent('$275.00')
    expect(screen.queryByText(/2 months free/)).toBeNull()
  })
})
