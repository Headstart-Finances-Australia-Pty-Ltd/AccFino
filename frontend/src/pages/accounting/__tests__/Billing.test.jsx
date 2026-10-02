import React from 'react'
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, fireEvent, waitFor } from '@testing-library/react'

vi.mock('react-hot-toast', () => ({ default: Object.assign(vi.fn(), { success: vi.fn(), error: vi.fn() }) }))
vi.mock('../../../lib/booksApi.js', async () => {
  const actual = await vi.importActual('../../../lib/booksApi.js')
  return { ...actual, getBilling: vi.fn(), saveBillingCard: vi.fn(), deleteBillingCard: vi.fn(), billingSubscribe: vi.fn(), billingAutoRenew: vi.fn(),
    adminSquareStatus: vi.fn(), adminSaveSquare: vi.fn(), adminTestSquare: vi.fn(), adminBillingOverview: vi.fn(), adminRunBilling: vi.fn() }
})
import * as api from '../../../lib/booksApi.js'
import BillingCard from '../../../components/billing/BillingCard.jsx'
import SquarePlatformPanel from '../../../components/payments/SquarePlatformPanel.jsx'

const VIEW = (over = {}) => ({ data: { available: true, can_manage: true, has_plan: true, plan_name: 'Essentials', billing_period: 'monthly', status: 'active', prices: { monthly: 25, yearly: 250 }, amount_next: 25,
  square: { applicationId: 'sq0idp-X', locationId: 'L1', environment: 'sandbox' }, card: null, auto_renew: false, failure_count: 0, charges: [], ...over } })
let tokenize
beforeEach(() => {
  vi.clearAllMocks()
  tokenize = vi.fn(async () => ({ status: 'OK', token: 'cnon:abc' }))
  window.Square = { payments: () => ({ card: async () => ({ attach: vi.fn(), tokenize, destroy: vi.fn() }) }) }          // Square's secure form, replaced by a stand-in
  window.confirm = vi.fn(() => true)
})

describe('Organisation payment card', () => {
  it('with no card: shows the secure card form, saves only the one-time token, then offers to subscribe', async () => {
    api.getBilling.mockResolvedValueOnce(VIEW()).mockResolvedValue(VIEW({ card: { brand: 'Visa', last4: '1111', exp_month: 12, exp_year: 2030 } }))
    api.saveBillingCard.mockResolvedValue({ data: {} })
    render(<BillingCard />)
    expect(await screen.findByTestId('square-card-box')).toBeInTheDocument()
    expect(screen.getByText(/never sees or stores the card number/i)).toBeInTheDocument()
    await waitFor(() => expect(screen.getByTestId('billing-save-card')).toBeInTheDocument())
    fireEvent.click(screen.getByTestId('billing-save-card'))
    await waitFor(() => expect(api.saveBillingCard).toHaveBeenCalledWith('cnon:abc'))
    expect(await screen.findByTestId('billing-card-on-file')).toHaveTextContent('Visa ···· 1111')
    expect(screen.getByTestId('billing-subscribe')).toBeInTheDocument()
  })

  it('subscribe: chooses monthly or yearly, shows the real price, and charges through the server', async () => {
    api.getBilling.mockResolvedValue(VIEW({ card: { brand: 'Visa', last4: '1111', exp_month: 12, exp_year: 2030 } }))
    api.billingSubscribe.mockResolvedValue({ data: { charge: { status: 'paid', amount: 250 } } })
    render(<BillingCard />)
    const btn = await screen.findByTestId('billing-subscribe-btn')
    expect(btn).toHaveTextContent('$25.00')
    fireEvent.click(screen.getByLabelText(/Yearly/))
    expect(screen.getByTestId('billing-subscribe-btn')).toHaveTextContent('$250.00')
    fireEvent.click(screen.getByTestId('billing-subscribe-btn'))
    await waitFor(() => expect(api.billingSubscribe).toHaveBeenCalledWith('yearly'))
  })

  it('shows the next charge when automatic renewal is on, with a way to stop it and receipts for past payments', async () => {
    api.getBilling.mockResolvedValue(VIEW({ card: { brand: 'Visa', last4: '1111', exp_month: 12, exp_year: 2030 }, auto_renew: true, next_charge_on: '2026-11-02', billing_period: 'monthly',
      charges: [{ id: 1, date: '2026-10-02T00:00:00Z', amount: 25, status: 'paid', period_start: '2026-10-02', period_end: '2026-11-02', receipt_url: 'https://squareup.com/receipt/1' }] }))
    render(<BillingCard />)
    expect(await screen.findByTestId('billing-active')).toHaveTextContent(/Next charge/)
    expect(screen.getByTestId('billing-stop')).toBeInTheDocument()
    expect(screen.getByText('Receipt')).toHaveAttribute('href', 'https://squareup.com/receipt/1')
  })

  it('a failed payment is explained, and a non-admin member can see but not change anything', async () => {
    api.getBilling.mockResolvedValue(VIEW({ can_manage: false, card: { brand: 'Visa', last4: '1111', exp_month: 12, exp_year: 2030 }, auto_renew: true, failure_count: 2, last_error: 'The card was declined.' }))
    render(<BillingCard />)
    expect(await screen.findByTestId('billing-failed')).toHaveTextContent(/Ask your Organisation Admin/)
    expect(screen.queryByTestId('billing-save-card')).toBeNull(); expect(screen.queryByTestId('billing-stop')).toBeNull(); expect(screen.queryByText('Remove')).toBeNull()
  })

  it('when the platform has not set up Square, clients just see a contact-support note', async () => {
    api.getBilling.mockResolvedValue({ data: { available: false } })
    render(<BillingCard />)
    expect(await screen.findByTestId('billing-unavailable')).toHaveTextContent(/contact AccFino support/)
  })
})

describe('Admin Console: Square platform set-up', () => {
  const ST = (o = {}) => ({ data: { configured: false, environment: 'sandbox', application_id: '', location_id: '', has_token: false, locked_by_environment: false, missing: ['Access token'], ...o } })
  it('saves the credentials write-only, tests them in plain words and shows the billing overview', async () => {
    api.adminSquareStatus.mockResolvedValueOnce(ST()).mockResolvedValue(ST({ configured: true, application_id: 'A', location_id: 'L', has_token: true }))
    api.adminSaveSquare.mockResolvedValue({ data: {} }); api.adminTestSquare.mockResolvedValue({ data: { ok: true, message: 'Connected to Square location "AccFino HQ" (AU, AUD, sandbox).' } })
    api.adminBillingOverview.mockResolvedValue({ data: { organisations: [{ org_id: 1, org_name: 'Alpha', plan_id: 'essentials', billing_period: 'monthly', card: 'Visa ···· 1111', auto_renew: true, next_charge_on: '2026-11-02', failure_count: 0, status: 'active' }], recent: [] } })
    render(<SquarePlatformPanel />)
    const token = await screen.findByTestId('square-token-input'); expect(token).toHaveAttribute('type', 'password')
    fireEvent.change(screen.getByLabelText('Square application id'), { target: { value: 'A' } }); fireEvent.change(screen.getByLabelText('Square location id'), { target: { value: 'L' } })
    fireEvent.change(token, { target: { value: 'SECRET' } }); fireEvent.click(screen.getByTestId('square-save'))
    await waitFor(() => expect(api.adminSaveSquare).toHaveBeenCalledWith({ application_id: 'A', location_id: 'L', access_token: 'SECRET', environment: 'sandbox' }))
    await waitFor(() => expect(screen.getByTestId('square-token-input')).toHaveValue(''))
    fireEvent.click(await screen.findByTestId('square-test'))
    expect(await screen.findByTestId('square-test-result')).toHaveTextContent('AccFino HQ')
    expect(await screen.findByText('Alpha')).toBeInTheDocument()
    fireEvent.click(screen.getByTestId('square-run')); api.adminRunBilling.mockResolvedValue({ data: { paid: 1, failed: 0 } })
  })
})
