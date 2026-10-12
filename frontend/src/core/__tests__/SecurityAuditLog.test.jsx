import React from 'react'
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'

let authUser = {}
vi.mock('../hooks/useAuth.jsx', () => ({ useAuth: () => ({ user: authUser, logout: vi.fn() }) }))
vi.mock('react-hot-toast', () => ({ default: Object.assign(vi.fn(), { success: vi.fn(), error: vi.fn() }) }))
vi.mock('../lib/platformApi.js', async () => {
  const actual = await vi.importActual('../lib/platformApi.js')
  const ok = (data) => vi.fn(() => Promise.resolve({ data }))
  return { ...actual, me: ok({}), myAudit: ok([]), orgAudit: ok({ total: 0, items: [] }),
    allAudit: ok({ total: 1, items: [{ id: 1, at: '2026-10-01T00:00:00Z', org_id: 7, username: 'ann', action: 'invoice.create', detail: {} }] }),
    securityStatus: ok({ mfa_enabled_users: 0, users: 1, checks: [] }), mfaStatus: ok({}), signInMethods: ok({}), listPasskeys: ok([]), listDevices: ok([]) }
})
vi.mock('../../modules/accounting/lib/ledgerApi.js', async () => {
  const actual = await vi.importActual('../../modules/accounting/lib/ledgerApi.js')
  const ok = (data) => vi.fn(() => Promise.resolve({ data }))
  return { ...actual, me: ok({}), myAudit: ok([]), orgAudit: ok({ total: 0, items: [] }),
    allAudit: ok({ total: 1, items: [{ id: 1, at: '2026-10-01T00:00:00Z', org_id: 7, username: 'ann', action: 'invoice.create', detail: {} }] }),
    securityStatus: ok({ mfa_enabled_users: 0, users: 1, checks: [] }), mfaStatus: ok({}), signInMethods: ok({}), listPasskeys: ok([]), listDevices: ok([]) }
})
import * as api from '../lib/platformApi.js'
import SecurityPage from '../pages/settings/SecurityPage.jsx'

beforeEach(() => vi.clearAllMocks())

describe('Security page: organisation audit log', () => {
  it('is shown to the AccFino administrator', async () => {
    authUser = { username: 'admin', is_admin: true, roles: ['admin'] }
    render(<SecurityPage />)
    expect(await screen.findByTestId('audit-log')).toHaveTextContent('invoice.create')
    expect(api.allAudit).toHaveBeenCalled()
  })
  it('is not displayed - and not even requested - for an organisation admin or any other user', async () => {
    authUser = { username: 'ann', is_admin: false, roles: ['user'], org_role: 'owner' }
    render(<SecurityPage />)
    await screen.findByText('Security')
    await waitFor(() => expect(api.myAudit).toHaveBeenCalled())
    expect(screen.queryByTestId('audit-log')).toBeNull()
    expect(screen.queryByText('Organisation audit log')).toBeNull()
    expect(api.allAudit).not.toHaveBeenCalled(); expect(api.orgAudit).not.toHaveBeenCalled()
  })
})
