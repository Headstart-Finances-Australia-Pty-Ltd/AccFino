import React from 'react'
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, fireEvent, waitFor, within } from '@testing-library/react'

vi.mock('react-hot-toast', () => ({ default: Object.assign(vi.fn(), { success: vi.fn(), error: vi.fn() }) }))
vi.mock('../lib/adminApi.js', async () => {
  const actual = await vi.importActual('../lib/adminApi.js')
  return { ...actual, adminUserPlans: vi.fn(), adminSetOrgPlan: vi.fn() }
})
vi.mock('../../modules/accounting/lib/booksApi.js', async () => {
  const actual = await vi.importActual('../../modules/accounting/lib/booksApi.js')
  return { ...actual, adminUserPlans: vi.fn(), adminSetOrgPlan: vi.fn() }
})
vi.mock('../../modules/billing/lib/orgBillingApi.js', async () => {
  const actual = await vi.importActual('../../modules/billing/lib/orgBillingApi.js')
  return { ...actual, adminUserPlans: vi.fn(), adminSetOrgPlan: vi.fn() }
})
vi.mock('../../modules/open_banking/lib/feedApi.js', async () => {
  const actual = await vi.importActual('../../modules/open_banking/lib/feedApi.js')
  return { ...actual, adminUserPlans: vi.fn(), adminSetOrgPlan: vi.fn() }
})
import toast from 'react-hot-toast'
import * as api from '../lib/adminApi.js'
import UserPlansPanel from '../pages/admin/UserPlansPanel.jsx'

const ORG = (o = {}) => ({ org_id: 5, org_name: 'Ann Pty Ltd', plan_id: 'business', plan_name: 'Business', grandfathered: false, status: 'active', billing_period: 'yearly', period_end: '2027-04-02', trial_ends: null,
  seats_used: 1, seats_pending: 0, seats_allowed: 1, addons: ['Payroll & Workforce'], domains: ['Books and Accounting', 'Payroll & Workforce', 'Planning & Intelligence'], card: 'Visa ···· 1111', auto_renew: true, ...o })
const DATA = { top_plan: 'Ultra', plans: [{ id: 'essential', name: 'Essential' }, { id: 'business', name: 'Business' }, { id: 'professional', name: 'Professional' }, { id: 'ultra', name: 'Ultra' }],
  rows: [
    { user_id: 1, username: 'admin', full_name: 'Administrator', email: 'admin@accfino.com', phone: '+61409809164', phone_display: '0409 809 164', platform_admin: true, role: 'owner', role_label: 'Organisation Admin', org: ORG({ org_id: 1, org_name: "Administrator's organisation", plan_id: 'ultra', plan_name: 'Ultra', billing_period: 'yearly', period_end: null, addons: [], domains: ['Books and Accounting', 'Payroll & Workforce'], card: null, auto_renew: false }) },
    { user_id: 2, username: 'ann', full_name: 'Ann', email: 'ann@x.com', phone: '+61411111111', phone_display: '0411 111 111', platform_admin: false, role: 'owner', role_label: 'Organisation Admin', org: ORG() },
    { user_id: 3, username: 'loose', full_name: 'Loose', email: 'l@x.com', phone: '', platform_admin: false, role: null, role_label: 'No organisation', org: null }] }
beforeEach(() => { vi.clearAllMocks(); window.confirm = vi.fn(() => true); api.adminUserPlans.mockResolvedValue({ data: DATA }) })

describe('Users & Licence > Plans by user', () => {
  it('shows the organisation plan of each person - never the old licence type, payment mode, start/end or module list', async () => {
    render(<UserPlansPanel />)
    expect(await screen.findByTestId('plan-name-1')).toHaveTextContent('Ultra')                       // the AccFino administrator: top plan, no dropdown
    const ann = screen.getByTestId('plan-row-2')
    expect(ann).toHaveTextContent('Ann Pty Ltd'); expect(ann).toHaveTextContent('yearly'); expect(ann).toHaveTextContent('paid to'); expect(ann).toHaveTextContent('Visa ···· 1111 · auto-renew')
    expect(ann).toHaveTextContent('1 / 1'); expect(ann).toHaveTextContent('Payroll & Workforce'); expect(ann).toHaveTextContent('Planning & Intelligence')
    expect(screen.getByTestId('plan-row-3')).toHaveTextContent('No organisation')
    const text = document.body.textContent
    for (const old of ['Vault', 'Ultra Plan', 'Auto-created', 'Admin & ML', 'Payment', 'Notes', 'Licence type']) expect(text).not.toContain(old)
    expect(screen.getByText('Plans by user')).toBeInTheDocument()
  })

  it('lists only the four plans in the plan dropdown and changes the organisation plan after a confirmation', async () => {
    api.adminSetOrgPlan.mockResolvedValue({ data: {} })
    render(<UserPlansPanel />)
    const sel = await screen.findByTestId('plan-select-2')
    expect([...sel.querySelectorAll('option')].map(o => o.textContent)).toEqual(['Essential', 'Business', 'Professional', 'Ultra'])
    expect(screen.queryByTestId('plan-select-1')).toBeNull()                                           // the administrator's plan is not editable
    fireEvent.change(sel, { target: { value: 'ultra' } })
    await waitFor(() => expect(api.adminSetOrgPlan).toHaveBeenCalledWith(5, 'ultra'))
    expect(window.confirm).toHaveBeenCalled(); await waitFor(() => expect(toast.success).toHaveBeenCalled())
  })

  it('does nothing when the confirmation is cancelled or the same plan is chosen', async () => {
    render(<UserPlansPanel />)
    const sel = await screen.findByTestId('plan-select-2')
    window.confirm = vi.fn(() => false); fireEvent.change(sel, { target: { value: 'professional' } })
    fireEvent.change(sel, { target: { value: 'business' } })
    expect(api.adminSetOrgPlan).not.toHaveBeenCalled()
  })

  it('searches across name, email, organisation and plan', async () => {
    render(<UserPlansPanel />)
    await screen.findByTestId('plan-row-2')
    fireEvent.change(screen.getByLabelText('Search users and plans'), { target: { value: 'ann pty' } })
    expect(screen.queryByTestId('plan-row-1')).toBeNull(); expect(screen.getByTestId('plan-row-2')).toBeInTheDocument()
  })
})
