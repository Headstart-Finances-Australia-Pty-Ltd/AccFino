import React from 'react'
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, fireEvent, waitFor } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'

let authUser = {}
vi.mock('../../../core/hooks/useAuth.jsx', () => ({ useAuth: () => ({ user: authUser }) }))
let hidden = new Set()
vi.mock('../../../core/hooks/useModuleVisibility.jsx', () => ({ useModuleVisibility: () => ({ isModuleVisible: id => !hidden.has(id), isLocked: () => false, subscription: null }) }))
vi.mock('react-hot-toast', () => ({ default: Object.assign(vi.fn(), { success: vi.fn(), error: vi.fn() }) }))
vi.mock('../../../core/lib/adminApi.js', async () => {
  const actual = await vi.importActual('../../../core/lib/adminApi.js')
  return { ...actual, adminOpenBanking: vi.fn(), adminSaveBasiq: vi.fn(), adminTestBasiq: vi.fn(), obFeedStatus: vi.fn() }
})
vi.mock('../../accounting/lib/booksApi.js', async () => {
  const actual = await vi.importActual('../../accounting/lib/booksApi.js')
  return { ...actual, adminOpenBanking: vi.fn(), adminSaveBasiq: vi.fn(), adminTestBasiq: vi.fn(), obFeedStatus: vi.fn() }
})
vi.mock('../../billing/lib/orgBillingApi.js', async () => {
  const actual = await vi.importActual('../../billing/lib/orgBillingApi.js')
  return { ...actual, adminOpenBanking: vi.fn(), adminSaveBasiq: vi.fn(), adminTestBasiq: vi.fn(), obFeedStatus: vi.fn() }
})
vi.mock('../lib/feedApi.js', async () => {
  const actual = await vi.importActual('../lib/feedApi.js')
  return { ...actual, adminOpenBanking: vi.fn(), adminSaveBasiq: vi.fn(), adminTestBasiq: vi.fn(), obFeedStatus: vi.fn() }
})
vi.mock('../../../core/lib/api.js', () => ({
  openfeedStatus: vi.fn(() => Promise.resolve({ data: { ready: true, hasKeys: true, hasIds: true, missing: [], clientId: 'app-1', appId: 'u', needsRegenerate: false,
    kid: 'accfino-ab12cd34', dashboardScopes: ['openfeed-au:data:banking:read'], redirectUri: 'https://www.accfino.com/open-banking/openfeed/callback', scopes: ['openid', 'offline_access', 'openfeed-au:data:banking:read'] } })),
  openfeedSaveConfig: vi.fn(), openfeedGenerateKeys: vi.fn(), openfeedTest: vi.fn(), openfeedPublicKey: vi.fn(),
  obStatus: vi.fn(), obCreateUser: vi.fn(), obAccounts: vi.fn(), obTransactions: vi.fn(), obSavedAccounts: vi.fn(() => Promise.resolve({ data: { accounts: [] } })), obSaveAccounts: vi.fn(),
  getBanks: vi.fn(() => Promise.resolve({ data: [] })),
}))
vi.mock('../../accounting/lib/api.js', () => ({
  openfeedStatus: vi.fn(() => Promise.resolve({ data: { ready: true, hasKeys: true, hasIds: true, missing: [], clientId: 'app-1', appId: 'u', needsRegenerate: false,
    kid: 'accfino-ab12cd34', dashboardScopes: ['openfeed-au:data:banking:read'], redirectUri: 'https://www.accfino.com/open-banking/openfeed/callback', scopes: ['openid', 'offline_access', 'openfeed-au:data:banking:read'] } })),
  openfeedSaveConfig: vi.fn(), openfeedGenerateKeys: vi.fn(), openfeedTest: vi.fn(), openfeedPublicKey: vi.fn(),
  obStatus: vi.fn(), obCreateUser: vi.fn(), obAccounts: vi.fn(), obTransactions: vi.fn(), obSavedAccounts: vi.fn(() => Promise.resolve({ data: { accounts: [] } })), obSaveAccounts: vi.fn(),
  getBanks: vi.fn(() => Promise.resolve({ data: [] })),
}))
vi.mock('../../billing/lib/api.js', () => ({
  openfeedStatus: vi.fn(() => Promise.resolve({ data: { ready: true, hasKeys: true, hasIds: true, missing: [], clientId: 'app-1', appId: 'u', needsRegenerate: false,
    kid: 'accfino-ab12cd34', dashboardScopes: ['openfeed-au:data:banking:read'], redirectUri: 'https://www.accfino.com/open-banking/openfeed/callback', scopes: ['openid', 'offline_access', 'openfeed-au:data:banking:read'] } })),
  openfeedSaveConfig: vi.fn(), openfeedGenerateKeys: vi.fn(), openfeedTest: vi.fn(), openfeedPublicKey: vi.fn(),
  obStatus: vi.fn(), obCreateUser: vi.fn(), obAccounts: vi.fn(), obTransactions: vi.fn(), obSavedAccounts: vi.fn(() => Promise.resolve({ data: { accounts: [] } })), obSaveAccounts: vi.fn(),
  getBanks: vi.fn(() => Promise.resolve({ data: [] })),
}))
vi.mock('../../cashflow/lib/api.js', () => ({
  openfeedStatus: vi.fn(() => Promise.resolve({ data: { ready: true, hasKeys: true, hasIds: true, missing: [], clientId: 'app-1', appId: 'u', needsRegenerate: false,
    kid: 'accfino-ab12cd34', dashboardScopes: ['openfeed-au:data:banking:read'], redirectUri: 'https://www.accfino.com/open-banking/openfeed/callback', scopes: ['openid', 'offline_access', 'openfeed-au:data:banking:read'] } })),
  openfeedSaveConfig: vi.fn(), openfeedGenerateKeys: vi.fn(), openfeedTest: vi.fn(), openfeedPublicKey: vi.fn(),
  obStatus: vi.fn(), obCreateUser: vi.fn(), obAccounts: vi.fn(), obTransactions: vi.fn(), obSavedAccounts: vi.fn(() => Promise.resolve({ data: { accounts: [] } })), obSaveAccounts: vi.fn(),
  getBanks: vi.fn(() => Promise.resolve({ data: [] })),
}))
vi.mock('../lib/api.js', () => ({
  openfeedStatus: vi.fn(() => Promise.resolve({ data: { ready: true, hasKeys: true, hasIds: true, missing: [], clientId: 'app-1', appId: 'u', needsRegenerate: false,
    kid: 'accfino-ab12cd34', dashboardScopes: ['openfeed-au:data:banking:read'], redirectUri: 'https://www.accfino.com/open-banking/openfeed/callback', scopes: ['openid', 'offline_access', 'openfeed-au:data:banking:read'] } })),
  openfeedSaveConfig: vi.fn(), openfeedGenerateKeys: vi.fn(), openfeedTest: vi.fn(), openfeedPublicKey: vi.fn(),
  obStatus: vi.fn(), obCreateUser: vi.fn(), obAccounts: vi.fn(), obTransactions: vi.fn(), obSavedAccounts: vi.fn(() => Promise.resolve({ data: { accounts: [] } })), obSaveAccounts: vi.fn(),
  getBanks: vi.fn(() => Promise.resolve({ data: [] })),
}))
vi.mock('../../reconciliation/lib/api.js', () => ({
  openfeedStatus: vi.fn(() => Promise.resolve({ data: { ready: true, hasKeys: true, hasIds: true, missing: [], clientId: 'app-1', appId: 'u', needsRegenerate: false,
    kid: 'accfino-ab12cd34', dashboardScopes: ['openfeed-au:data:banking:read'], redirectUri: 'https://www.accfino.com/open-banking/openfeed/callback', scopes: ['openid', 'offline_access', 'openfeed-au:data:banking:read'] } })),
  openfeedSaveConfig: vi.fn(), openfeedGenerateKeys: vi.fn(), openfeedTest: vi.fn(), openfeedPublicKey: vi.fn(),
  obStatus: vi.fn(), obCreateUser: vi.fn(), obAccounts: vi.fn(), obTransactions: vi.fn(), obSavedAccounts: vi.fn(() => Promise.resolve({ data: { accounts: [] } })), obSaveAccounts: vi.fn(),
  getBanks: vi.fn(() => Promise.resolve({ data: [] })),
}))
vi.mock('../../trading/lib/api.js', () => ({
  openfeedStatus: vi.fn(() => Promise.resolve({ data: { ready: true, hasKeys: true, hasIds: true, missing: [], clientId: 'app-1', appId: 'u', needsRegenerate: false,
    kid: 'accfino-ab12cd34', dashboardScopes: ['openfeed-au:data:banking:read'], redirectUri: 'https://www.accfino.com/open-banking/openfeed/callback', scopes: ['openid', 'offline_access', 'openfeed-au:data:banking:read'] } })),
  openfeedSaveConfig: vi.fn(), openfeedGenerateKeys: vi.fn(), openfeedTest: vi.fn(), openfeedPublicKey: vi.fn(),
  obStatus: vi.fn(), obCreateUser: vi.fn(), obAccounts: vi.fn(), obTransactions: vi.fn(), obSavedAccounts: vi.fn(() => Promise.resolve({ data: { accounts: [] } })), obSaveAccounts: vi.fn(),
  getBanks: vi.fn(() => Promise.resolve({ data: [] })),
}))
import * as api from '../lib/feedApi.js'
import * as plain from '../lib/api.js'
import OpenBankingSetupPage from '../pages/OpenBankingSetupPage.jsx'
import OpenBankingPage from '../pages/OpenBankingPage.jsx'

const BASIQ = (over = {}) => ({ data: { basiq: { configured: false, source: null, base_url: 'https://au-api.basiq.io', version: '3.0', locked_by_environment: false, ...over }, openfeed: { ready: false } } })
beforeEach(() => { hidden = new Set(); vi.clearAllMocks(); api.adminOpenBanking.mockResolvedValue(BASIQ()) })

describe('Admin Console > Open Banking (platform set-up)', () => {
  it('holds BOTH providers\' platform set-up in one place', async () => {
    render(<MemoryRouter><OpenBankingSetupPage /></MemoryRouter>)
    expect(await screen.findByTestId('basiq-platform-setup')).toBeInTheDocument()
    expect(await screen.findByTestId('openfeed-platform-setup')).toBeInTheDocument()
  })

  it('each provider card follows its own Admin Console switch (separate from the Settings switches clients see)', async () => {
    hidden = new Set(['openfeed-admin-open-banking'])
    const { unmount } = render(<MemoryRouter><OpenBankingSetupPage /></MemoryRouter>)
    expect(await screen.findByTestId('basiq-platform-setup')).toBeInTheDocument(); expect(screen.queryByTestId('openfeed-platform-setup')).toBeNull()
    unmount()
    hidden = new Set(['basiq-admin-open-banking']); render(<MemoryRouter><OpenBankingSetupPage /></MemoryRouter>)
    expect(await screen.findByTestId('openfeed-platform-setup')).toBeInTheDocument(); expect(screen.queryByTestId('basiq-platform-setup')).toBeNull()
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

describe('OpenFeed set-up tells the administrator exactly what to register', () => {
  it('says to tick only the banking scope, that openid/offline_access are automatic, and that no redirect URI needs registering', async () => {
    plain.openfeedTest.mockResolvedValue({ data: { ok: false, message: 'HTTP 400: invalid_scope - requested scope is not allowed',
      scope_check: [{ scope: 'openid', ok: true }, { scope: 'offline_access', ok: true }, { scope: 'openfeed-au:data:banking:read', ok: false }],
      hints: ["In the OpenFeed dashboard, under 'Requested scopes', tick 'Banking accounts and transactions' (openfeed-au:data:banking:read) and press 'Save changes'."] } })
    render(<MemoryRouter><OpenBankingSetupPage /></MemoryRouter>)
    const box = await screen.findByTestId('openfeed-register-values')
    expect(box).toHaveTextContent('Banking accounts and transactions'); expect(box).toHaveTextContent('openfeed-au:data:banking:read')
    expect(box).toHaveTextContent(/not boxes/); expect(box).toHaveTextContent(/nothing to register/i)
    expect(box).toHaveTextContent('https://www.accfino.com/open-banking/openfeed/callback')
    fireEvent.click(await screen.findByTestId('openfeed-test-btn'))
    const check = await screen.findByTestId('openfeed-scope-check')
    expect(check).toHaveTextContent('✓ openid'); expect(check).toHaveTextContent('✗ openfeed-au:data:banking:read')
    expect(await screen.findByTestId('openfeed-test-hints')).toHaveTextContent('Banking accounts and transactions')
  })
})

describe('OpenFeed: banking scope refused although ticked', () => {
  it('shows which Client ID was tested and whether the redirect address is the cause', async () => {
    plain.openfeedTest.mockResolvedValue({ data: { ok: false, message: 'HTTP 400: invalid_scope - requested scope is not allowed', client_id: 'app-d0bfec19', kid: 'accfino-741ade35',
      scope_check: [{ scope: 'openid', ok: true }, { scope: 'offline_access', ok: true }, { scope: 'openfeed-au:data:banking:read', ok: false }],
      variant_check: [{ key: 'resource', label: 'banking scope + resource https://api.openfeed.au', ok: false }, { key: 'no_openid', label: 'banking scope alone (without openid)', ok: false }],
      redirect_check: [{ redirect_uri: 'http://127.0.0.1:8001/open-banking/openfeed/callback', ok: false }, { redirect_uri: 'http://localhost:8001/open-banking/openfeed/callback', ok: true }],
      hints: ['OpenFeed accepts the banking scope with the redirect address http://localhost:8001/open-banking/openfeed/callback but not with http://127.0.0.1:8001/open-banking/openfeed/callback.'] } })
    render(<MemoryRouter><OpenBankingSetupPage /></MemoryRouter>)
    fireEvent.click(await screen.findByTestId('openfeed-test-btn'))
    expect(await screen.findByTestId('openfeed-tested-as')).toHaveTextContent('app-d0bfec19')
    expect(await screen.findByTestId('openfeed-variant-check')).toHaveTextContent('✗ banking scope alone (without openid)')
    const rc = await screen.findByTestId('openfeed-redirect-check')
    expect(rc).toHaveTextContent('✗ banking scope with redirect http://127.0.0.1:8001'); expect(rc).toHaveTextContent('✓ banking scope with redirect http://localhost:8001')
  })
})

describe('OpenFeed: invalid_client help', () => {
  it('shows the key id AccFino signs with, can show the public key set again, and lists what to check when OpenFeed says invalid_client', async () => {
    plain.openfeedPublicKey.mockResolvedValue({ data: { jwks: { keys: [{ kty: 'RSA', kid: 'accfino-ab12cd34', n: 'x', e: 'AQAB' }] }, kid: 'accfino-ab12cd34', fingerprint: 'FPRINT123' } })
    plain.openfeedTest.mockResolvedValue({ data: { ok: false, message: 'HTTP 401: invalid_client - client authentication failed', hints: ['The key AccFino signs with has key id accfino-ab12cd34 and fingerprint FPRINT123.', "must be exactly the one shown by 'Show public key set'"] } })
    render(<MemoryRouter><OpenBankingSetupPage /></MemoryRouter>)
    expect(await screen.findByTestId('openfeed-kid')).toHaveTextContent('accfino-ab12cd34')
    fireEvent.click(await screen.findByTestId('openfeed-show-key'))
    expect((await screen.findByTestId('jwks-box')).value).toContain('accfino-ab12cd34')
    expect(await screen.findByTestId('openfeed-kid')).toHaveTextContent('FPRINT123')
    fireEvent.click(await screen.findByTestId('openfeed-test-btn'))
    const hints = await screen.findByTestId('openfeed-test-hints')
    expect(hints).toHaveTextContent('accfino-ab12cd34'); expect(hints).toHaveTextContent('Show public key set')
  })
})

describe('OpenFeed: invalid_scope help', () => {
  it('ticks and crosses each scope so the administrator knows exactly which box to tick at OpenFeed', async () => {
    plain.openfeedTest.mockResolvedValue({ data: { ok: false, message: 'HTTP 400: invalid_scope - requested scope is not allowed',
      scope_check: [{ scope: 'openid', ok: true }, { scope: 'offline_access', ok: false }, { scope: 'openfeed-au:data:banking:read', ok: true }], hints: ['At OpenFeed, edit the app and tick: offline_access.'] } })
    render(<MemoryRouter><OpenBankingSetupPage /></MemoryRouter>)
    fireEvent.click(await screen.findByTestId('openfeed-test-btn'))
    const list = await screen.findByTestId('openfeed-scope-check')
    expect(list.querySelectorAll('li')).toHaveLength(3)
    expect(list.querySelectorAll('li')[1]).toHaveTextContent('✗'); expect(list.querySelectorAll('li')[1]).toHaveTextContent('offline_access'); expect(list.querySelectorAll('li')[1]).toHaveTextContent(/tick it/)
    expect(list.querySelectorAll('li')[0]).toHaveTextContent('✓')
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
    expect(note.querySelector('a')).toHaveAttribute('href', '/admin/api-keys?tab=open-banking')
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
