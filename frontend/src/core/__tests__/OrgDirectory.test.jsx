import React from 'react'
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, waitFor, fireEvent, within } from '@testing-library/react'

vi.mock('../lib/adminApi.js', async () => {
  const actual = await vi.importActual('../lib/adminApi.js')
  return { ...actual, adminOrgDirectory: vi.fn(), adminGetForceDelete: vi.fn(), adminSetForceDelete: vi.fn(() => Promise.resolve({ data: { enabled: true } })),
    adminBulkDeleteUsers: vi.fn(), adminBulkDeleteOrgs: vi.fn(), adminPruneEmptyOrgs: vi.fn(), adminPruneOrphanUsers: vi.fn() }
})
vi.mock('../../modules/accounting/lib/booksApi.js', async () => {
  const actual = await vi.importActual('../../modules/accounting/lib/booksApi.js')
  return { ...actual, adminOrgDirectory: vi.fn(), adminGetForceDelete: vi.fn(), adminSetForceDelete: vi.fn(() => Promise.resolve({ data: { enabled: true } })),
    adminBulkDeleteUsers: vi.fn(), adminBulkDeleteOrgs: vi.fn(), adminPruneEmptyOrgs: vi.fn(), adminPruneOrphanUsers: vi.fn() }
})
vi.mock('../../modules/billing/lib/orgBillingApi.js', async () => {
  const actual = await vi.importActual('../../modules/billing/lib/orgBillingApi.js')
  return { ...actual, adminOrgDirectory: vi.fn(), adminGetForceDelete: vi.fn(), adminSetForceDelete: vi.fn(() => Promise.resolve({ data: { enabled: true } })),
    adminBulkDeleteUsers: vi.fn(), adminBulkDeleteOrgs: vi.fn(), adminPruneEmptyOrgs: vi.fn(), adminPruneOrphanUsers: vi.fn() }
})
vi.mock('../../modules/open_banking/lib/feedApi.js', async () => {
  const actual = await vi.importActual('../../modules/open_banking/lib/feedApi.js')
  return { ...actual, adminOrgDirectory: vi.fn(), adminGetForceDelete: vi.fn(), adminSetForceDelete: vi.fn(() => Promise.resolve({ data: { enabled: true } })),
    adminBulkDeleteUsers: vi.fn(), adminBulkDeleteOrgs: vi.fn(), adminPruneEmptyOrgs: vi.fn(), adminPruneOrphanUsers: vi.fn() }
})
vi.mock('react-hot-toast', () => ({ default: Object.assign(vi.fn(), { success: vi.fn(), error: vi.fn() }) }))

import * as api from '../lib/adminApi.js'
import OrgDirectoryPanel from '../pages/admin/OrgDirectoryPanel.jsx'

const U = (id, name, email, role, over = {}) => ({ user_id: id, username: name.toLowerCase(), full_name: name, email, phone: '+61412345678', phone_display: '0412 345 678', role, role_label: role === 'owner' ? 'Organisation Admin' : 'Accountant', suspended: false, protected: false, ...over })
const DIR = {
  totals: { organisations: 2, users: 6 },
  platform_admins: [U(1, 'AccFino Admin', 'admin@accfino.com', null, { protected: true, role_label: '' })],
  unassigned_users: [U(9, 'Loose Lou', 'lou@example.com', null, { role_label: '' })],
  organisations: [
    { org_id: 10, name: 'Alpha Pty Ltd', is_active: true, admin: { user_id: 2, name: 'Ann', email: 'ann@alpha.example', phone: '+61412345678', phone_display: '0412 345 678' },
      licence: { plan_id: 'essential', plan_name: 'Essential', status: 'active', seats: 3, active_users: 2, pending_codes: 0 }, user_count: 2,
      users: [U(2, 'Ann', 'ann@alpha.example', 'owner'), U(3, 'Bob', 'bob@alpha.example', 'accountant')] },
    { org_id: 11, name: 'Beta Pty Ltd', is_active: true, admin: { user_id: 4, name: 'Cy', email: 'cy@beta.example', phone: '', phone_display: '' },
      licence: { plan_id: null, plan_name: 'All modules (no plan assigned)', status: 'trial', seats: null, active_users: 1, pending_codes: 0 }, user_count: 1, users: [U(4, 'Cy', 'cy@beta.example', 'owner')] },
  ],
}
beforeEach(() => { vi.clearAllMocks(); vi.spyOn(window, 'confirm').mockReturnValue(true)
  api.adminOrgDirectory.mockResolvedValue({ data: DIR }); api.adminGetForceDelete.mockResolvedValue({ data: { enabled: true } }) })

describe('Organisations & Users directory', () => {
  it('lists each organisation with admin email, phone, licence and user count', async () => {
    render(<OrgDirectoryPanel />)
    const row = await screen.findByTestId('org-row-10')
    expect(row).toHaveTextContent('Alpha Pty Ltd'); expect(row).toHaveTextContent('ann@alpha.example'); expect(row).toHaveTextContent('0412 345 678')
    expect(row).toHaveTextContent('Essential'); expect(row).toHaveTextContent('active'); expect(row).toHaveTextContent('2 / 3')
    expect(screen.getByTestId('org-row-11')).toHaveTextContent('1 / unlimited')
  })

  it('shows each organisation\'s users with role, email and phone when expanded', async () => {
    render(<OrgDirectoryPanel />)
    fireEvent.click(await screen.findByTestId('org-row-10'))
    expect(await screen.findByText('bob@alpha.example')).toBeInTheDocument()
    expect(screen.getByText('Accountant')).toBeInTheDocument(); expect(screen.getAllByText('Organisation Admin').length).toBeGreaterThan(0)
  })

  it('the AccFino administrator is locked: shown as protected and has no checkbox anywhere', async () => {
    render(<OrgDirectoryPanel />)
    const card = await screen.findByTestId('platform-admin-card')
    expect(card).toHaveTextContent('admin@accfino.com'); expect(card).toHaveTextContent(/can never be deleted/i)
    expect(screen.queryByLabelText('Select admin@accfino.com')).toBeNull()
  })

  it('while Force delete is switched off the button and every selection checkbox are not on the page at all', async () => {
    api.adminGetForceDelete.mockResolvedValue({ data: { enabled: false } })
    render(<OrgDirectoryPanel />)
    await screen.findByTestId('org-row-10')
    fireEvent.click(screen.getByTestId('org-row-10'))
    await screen.findByText('bob@alpha.example')
    expect(screen.queryByTestId('force-delete-btn')).toBeNull()
    expect(screen.queryAllByRole('checkbox')).toHaveLength(0)
    expect(screen.queryByText(/switched/i)).toBeNull()
  })

  it('deleted rows vanish at once - without waiting for the reload and without a page refresh', async () => {
    api.adminBulkDeleteUsers.mockResolvedValue({ data: { results: [{ id: 3, ok: true }] } })
    let release; api.adminOrgDirectory.mockResolvedValueOnce({ data: DIR }).mockImplementationOnce(() => new Promise(r => { release = r }))   // the reload is slow
    render(<OrgDirectoryPanel />)
    fireEvent.click(await screen.findByTestId('org-row-10'))
    fireEvent.click(await screen.findByLabelText('Select bob@alpha.example'))
    fireEvent.click(screen.getByTestId('force-delete-btn'))
    await waitFor(() => expect(screen.queryByText('bob@alpha.example')).toBeNull())
    expect(screen.getByTestId('org-row-10')).toHaveTextContent('1 / 3')
    release({ data: { ...DIR, organisations: [{ ...DIR.organisations[0], users: [DIR.organisations[0].users[0]], user_count: 1 }, DIR.organisations[1]] } })
  })

  it('a deleted organisation disappears immediately together with its users', async () => {
    api.adminBulkDeleteOrgs.mockResolvedValue({ data: { results: [{ id: 10, ok: true, users_deleted: [{ id: 3 }] }] } })
    api.adminOrgDirectory.mockResolvedValueOnce({ data: DIR }).mockImplementationOnce(() => new Promise(() => {}))
    render(<OrgDirectoryPanel />)
    fireEvent.click(await screen.findByLabelText('Select organisation Alpha Pty Ltd'))
    fireEvent.click(screen.getByTestId('force-delete-btn'))
    await waitFor(() => expect(screen.queryByTestId('org-row-10')).toBeNull())
    expect(screen.getByTestId('org-row-11')).toBeInTheDocument()
  })

  it('force deletes the selected users and reloads', async () => {
    api.adminBulkDeleteUsers.mockResolvedValue({ data: { results: [{ id: 3, ok: true }] } })
    render(<OrgDirectoryPanel />)
    fireEvent.click(await screen.findByTestId('org-row-10'))
    fireEvent.click(await screen.findByLabelText('Select bob@alpha.example'))
    await waitFor(() => expect(screen.getByTestId('force-delete-btn')).not.toBeDisabled())
    fireEvent.click(screen.getByTestId('force-delete-btn'))
    await waitFor(() => expect(api.adminBulkDeleteUsers).toHaveBeenCalledWith([3], true))
    expect(api.adminBulkDeleteOrgs).not.toHaveBeenCalled()
    await waitFor(() => expect(api.adminOrgDirectory).toHaveBeenCalledTimes(2))
  })

  it('a selected organisation is deleted as an organisation (its users are not sent twice)', async () => {
    api.adminBulkDeleteOrgs.mockResolvedValue({ data: { results: [{ id: 10, ok: true, users_deleted: [{}, {}] }] } })
    render(<OrgDirectoryPanel />)
    fireEvent.click(await screen.findByLabelText('Select organisation Alpha Pty Ltd'))
    fireEvent.click(await screen.findByTestId('org-row-10'))
    fireEvent.click(await screen.findByLabelText('Select bob@alpha.example'))
    fireEvent.click(screen.getByTestId('force-delete-btn'))
    await waitFor(() => expect(api.adminBulkDeleteOrgs).toHaveBeenCalledWith([10], true))
    expect(api.adminBulkDeleteUsers).not.toHaveBeenCalled()
  })

  it('searches across organisation and user details', async () => {
    render(<OrgDirectoryPanel />)
    await screen.findByTestId('org-row-10')
    fireEvent.change(screen.getByLabelText('Search organisations and users'), { target: { value: 'cy@beta' } })
    await waitFor(() => expect(screen.queryByTestId('org-row-10')).toBeNull())
    expect(screen.getByTestId('org-row-11')).toBeInTheDocument()
  })

  it('organisations with no users left can be removed in one click, and vanish at once', async () => {
    const empty = { org_id: 12, name: 'UserATest', is_active: true, admin: { user_id: null, name: '', email: '', phone: '', phone_display: '' },
      licence: { plan_id: null, plan_name: 'All modules (no plan assigned)', status: 'active', seats: null, active_users: 0, pending_codes: 0 }, user_count: 0, users: [] }
    api.adminOrgDirectory.mockResolvedValueOnce({ data: { ...DIR, organisations: [...DIR.organisations, empty] } }).mockImplementationOnce(() => new Promise(() => {}))
    api.adminPruneEmptyOrgs.mockResolvedValue({ data: { removed: [{ id: 12, name: 'UserATest' }], skipped: [] } })
    render(<OrgDirectoryPanel />)
    const btn = await screen.findByTestId('prune-empty-btn')
    expect(btn).toHaveTextContent('Remove 1 empty organisation')
    fireEvent.click(btn)
    await waitFor(() => expect(api.adminPruneEmptyOrgs).toHaveBeenCalled())
    await waitFor(() => expect(screen.queryByTestId('org-row-12')).toBeNull())
    expect(screen.getByTestId('org-row-10')).toBeInTheDocument()
  })

  it('shows no empty-organisation button when every organisation has users', async () => {
    render(<OrgDirectoryPanel />)
    await screen.findByTestId('org-row-10')
    expect(screen.queryByTestId('prune-empty-btn')).toBeNull()
  })

  it('logins left without an organisation can be deleted in one click and vanish at once', async () => {
    api.adminPruneOrphanUsers.mockResolvedValue({ data: { removed: [{ id: 9 }], skipped: [] } })
    api.adminOrgDirectory.mockResolvedValueOnce({ data: DIR }).mockImplementationOnce(() => new Promise(() => {}))
    render(<OrgDirectoryPanel />)
    const btn = await screen.findByTestId('prune-orphans-btn')
    expect(btn).toHaveTextContent('Delete 1 login without an organisation')
    fireEvent.click(btn)
    await waitFor(() => expect(api.adminPruneOrphanUsers).toHaveBeenCalled())
    await waitFor(() => expect(screen.queryByText('lou@example.com')).toBeNull())
  })
})
