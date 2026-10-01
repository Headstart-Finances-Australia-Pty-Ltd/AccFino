import React from 'react'
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, fireEvent, waitFor } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'

let authUser = {}
vi.mock('../../../hooks/useAuth.jsx', () => ({ useAuth: () => ({ user: authUser }) }))
vi.mock('../../../hooks/useModuleVisibility.jsx', () => ({ useModuleVisibility: () => ({ isModuleVisible: () => true }) }))
vi.mock('react-hot-toast', () => ({ default: Object.assign(vi.fn(), { success: vi.fn(), error: vi.fn() }) }))
vi.mock('../../../lib/booksApi.js', async () => {
  const actual = await vi.importActual('../../../lib/booksApi.js')
  return { ...actual, adminOpenBanking: vi.fn(), adminSaveBasiq: vi.fn(), adminTestBasiq: vi.fn(), obFeedStatus: vi.fn() }
})
vi.mock('../../../lib/api.js', () => ({
  openfeedStatus: vi.fn(() => Promise.resolve({ data: { ready: false, hasKeys: false, hasIds: false, missing: ['OpenFeed app (client id)'], clientId: '', appId: '' } })),
  openfeedSaveConfig: vi.fn(), openfeedGenerateKeys: vi.fn(),
  obStatus: vi.fn(), obCreateUser: vi.fn(), obAccounts: vi.fn(), obTransactions: vi.fn(), obSavedAccounts: vi.fn(() => Promise.resolve({ data: { accounts: [] } })), obSaveAccounts: vi.fn(),
  getBanks: vi.fn(() => Promise.resolve({ data: [] })),
}))
import * as api from '../../../lib/booksApi.js'
import * as plain from '../../../lib/api.js'
import OpenBankingSetupPage from '../../admin/OpenBankingSetupPage.jsx'
import OpenBankingPage from '../../OpenBankingPage.jsx'

const BASIQ = (over = {}) => ({ data: { basiq: { configured: false, source: null, base_url: 'https://au-api.basiq.io', version: '3.0', locked_by_environment: false, ...over }, openfeed: { ready: false } } })
beforeEach(() => { vi.clearAllMocks(); api.adminOpenBanking.mockResolvedValue(BASIQ()) })

describe('Admin Console > Open Banking (platform set-up)', () => {
  it('holds BOTH providers\' platform set-up in one place', async () => {
    render(<MemoryRouter><OpenBankingSetupPage /></MemoryRouter>)
    expect(await screen.findByTestId('basiq-platform-setup')).toBeInTheDocument()
    expect(await screen.findByTestId('openfeed-platform-setup')).toBeInTheDocument()
  })

  it('saves the Basiq key (write-only), clears the field, and tests the connection', async () => {
    api.adminSaveBasiq.mockResolvedValue({ data: {} }); api.adminTestBasiq.mockResolvedValue({ data: { ok: true, message: 'Connected to Basiq.' } })
    render(<MemoryRouter><OpenBankingSetupPage /></MemoryRouter>)
    const input = await screen.findByTestId('basiq-key-input')
    expect(input).toHaveAttribute('type', 'password')                                        // never shown in clear
    fireEvent.change(input, { target: { value: 'MY-KEY' } })
    api.adminOpenBanking.mockResolvedValue(BASIQ({ configured: true, source: 'admin' }))
    fireEvent.click(screen.getByTestId('basiq-save'))
    await waitFor(() => expect(api.adminSaveBasiq).toHaveBeenCalledWith({ api_key: 'MY-KEY', base_url: 'https://au-api.basiq.io', version: '3.0' }))
    await waitFor(() => expect(screen.getByTestId('basiq-key-input')).toHaveValue(''))
    expect(await screen.findByText('Ready')).toBeInTheDocument()
    fireEvent.click(screen.getByTestId('basiq-test'))
    expect(await screen.findByTestId('basiq-test-result')).toHaveTextContent('Connected to Basiq.')
  })

  it('when the server environment owns the key there is nothing to type, only an explanation', async () => {
    api.adminOpenBanking.mockResolvedValue(BASIQ({ configured: true, source: 'environment', locked_by_environment: true }))
    render(<MemoryRouter><OpenBankingSetupPage /></MemoryRouter>)
    expect(await screen.findByTestId('basiq-env-locked')).toBeInTheDocument()
    expect(screen.queryByTestId('basiq-key-input')).toBeNull()
  })
})

describe('Settings > Open Banking (what clients see)', () => {
  it('a client sees no key, no .env instructions and no platform set-up - only a contact-support note when Basiq is not switched on', async () => {
    authUser = { username: 'ann', is_admin: false, roles: ['user'] }
    plain.obStatus.mockResolvedValue({ data: { available: true, configured: false } })
    render(<MemoryRouter><OpenBankingPage /></MemoryRouter>)
    const note = await screen.findByTestId('basiq-unavailable')
    expect(note).toHaveTextContent(/contact AccFino support/)
    expect(screen.queryByText(/BASIQ_API_KEY|\.env|Setup Instructions/)).toBeNull()
    expect(screen.queryByTestId('basiq-platform-setup')).toBeNull(); expect(screen.queryByTestId('openfeed-platform-setup')).toBeNull()
  })

  it('the AccFino administrator is pointed to Admin Console > Open Banking instead', async () => {
    authUser = { username: 'admin', is_admin: true, roles: ['admin'] }
    plain.obStatus.mockResolvedValue({ data: { available: true, configured: false } })
    render(<MemoryRouter><OpenBankingPage /></MemoryRouter>)
    const note = await screen.findByTestId('basiq-unavailable')
    expect(note.querySelector('a')).toHaveAttribute('href', '/admin/open-banking')
  })

  it('the OpenFeed tab shows only the Connect my bank card - never the platform set-up, even for the administrator', async () => {
    authUser = { username: 'admin', is_admin: true, roles: ['admin'] }
    plain.obStatus.mockResolvedValue({ data: { available: true, configured: true } })
    api.obFeedStatus.mockResolvedValue({ data: { available: true, status: 'not_connected', can_manage: true, accounts: [] } })
    render(<MemoryRouter><OpenBankingPage /></MemoryRouter>)
    fireEvent.click(await screen.findByRole('button', { name: 'OpenFeed' }))
    expect(await screen.findByTestId('bank-feed-card')).toBeInTheDocument()
    expect(screen.queryByTestId('openfeed-platform-setup')).toBeNull()
  })
})
