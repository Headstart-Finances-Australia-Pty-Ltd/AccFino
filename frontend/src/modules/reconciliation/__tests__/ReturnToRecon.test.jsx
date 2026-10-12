import React from 'react'
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, fireEvent, waitFor, act } from '@testing-library/react'
import { MemoryRouter, Routes, Route, useLocation } from 'react-router-dom'
import { safeReturn, withReturn, withParam, returnLabel, inputModeFromSearch } from '../../../core/lib/returnTo.js'

vi.mock('react-hot-toast', () => ({ default: Object.assign(vi.fn(), { success: vi.fn(), error: vi.fn() }) }))
vi.mock('../../../core/hooks/useOrgRole.jsx', () => ({ default: () => ({ isOrgAdmin: true }) }))
vi.mock('../../../core/hooks/useAuth.jsx', () => ({ useAuth: () => ({ user: { id: 1, username: 'ann', is_admin: false, roles: ['user'] } }) }))
vi.mock('../../../core/hooks/useModuleVisibility.jsx', () => ({ useModuleVisibility: () => ({ isModuleVisible: () => true, isLocked: () => false, subscription: null }) }))
vi.mock('../../../core/lib/adminApi.js', async () => ({ ...(await vi.importActual('../../../core/lib/adminApi.js')), obFeedStatus: vi.fn(), obFeedConnect: vi.fn() }))
vi.mock('../../accounting/lib/booksApi.js', async () => ({ ...(await vi.importActual('../../accounting/lib/booksApi.js')), obFeedStatus: vi.fn(), obFeedConnect: vi.fn() }))
vi.mock('../../billing/lib/orgBillingApi.js', async () => ({ ...(await vi.importActual('../../billing/lib/orgBillingApi.js')), obFeedStatus: vi.fn(), obFeedConnect: vi.fn() }))
vi.mock('../../open_banking/lib/feedApi.js', async () => ({ ...(await vi.importActual('../../open_banking/lib/feedApi.js')), obFeedStatus: vi.fn(), obFeedConnect: vi.fn() }))
vi.mock('../../../core/lib/api.js', async () => ({ ...(await vi.importActual('../../../core/lib/api.js')), obReconcileAccounts: vi.fn(), obPull: vi.fn(), obStatus: vi.fn(), obSavedAccounts: vi.fn(), obSaveAccounts: vi.fn(),
  obCreateUser: vi.fn(), obAccounts: vi.fn(), obTransactions: vi.fn(), getBanks: vi.fn(), openfeedStatus: vi.fn(), openfeedSaveConfig: vi.fn(), openfeedGenerateKeys: vi.fn() }))
vi.mock('../../accounting/lib/api.js', async () => ({ ...(await vi.importActual('../../accounting/lib/api.js')), obReconcileAccounts: vi.fn(), obPull: vi.fn(), obStatus: vi.fn(), obSavedAccounts: vi.fn(), obSaveAccounts: vi.fn(),
  obCreateUser: vi.fn(), obAccounts: vi.fn(), obTransactions: vi.fn(), getBanks: vi.fn(), openfeedStatus: vi.fn(), openfeedSaveConfig: vi.fn(), openfeedGenerateKeys: vi.fn() }))
vi.mock('../../billing/lib/api.js', async () => ({ ...(await vi.importActual('../../billing/lib/api.js')), obReconcileAccounts: vi.fn(), obPull: vi.fn(), obStatus: vi.fn(), obSavedAccounts: vi.fn(), obSaveAccounts: vi.fn(),
  obCreateUser: vi.fn(), obAccounts: vi.fn(), obTransactions: vi.fn(), getBanks: vi.fn(), openfeedStatus: vi.fn(), openfeedSaveConfig: vi.fn(), openfeedGenerateKeys: vi.fn() }))
vi.mock('../../cashflow/lib/api.js', async () => ({ ...(await vi.importActual('../../cashflow/lib/api.js')), obReconcileAccounts: vi.fn(), obPull: vi.fn(), obStatus: vi.fn(), obSavedAccounts: vi.fn(), obSaveAccounts: vi.fn(),
  obCreateUser: vi.fn(), obAccounts: vi.fn(), obTransactions: vi.fn(), getBanks: vi.fn(), openfeedStatus: vi.fn(), openfeedSaveConfig: vi.fn(), openfeedGenerateKeys: vi.fn() }))
vi.mock('../../open_banking/lib/api.js', async () => ({ ...(await vi.importActual('../../open_banking/lib/api.js')), obReconcileAccounts: vi.fn(), obPull: vi.fn(), obStatus: vi.fn(), obSavedAccounts: vi.fn(), obSaveAccounts: vi.fn(),
  obCreateUser: vi.fn(), obAccounts: vi.fn(), obTransactions: vi.fn(), getBanks: vi.fn(), openfeedStatus: vi.fn(), openfeedSaveConfig: vi.fn(), openfeedGenerateKeys: vi.fn() }))
vi.mock('../lib/api.js', async () => ({ ...(await vi.importActual('../lib/api.js')), obReconcileAccounts: vi.fn(), obPull: vi.fn(), obStatus: vi.fn(), obSavedAccounts: vi.fn(), obSaveAccounts: vi.fn(),
  obCreateUser: vi.fn(), obAccounts: vi.fn(), obTransactions: vi.fn(), getBanks: vi.fn(), openfeedStatus: vi.fn(), openfeedSaveConfig: vi.fn(), openfeedGenerateKeys: vi.fn() }))
vi.mock('../../trading/lib/api.js', async () => ({ ...(await vi.importActual('../../trading/lib/api.js')), obReconcileAccounts: vi.fn(), obPull: vi.fn(), obStatus: vi.fn(), obSavedAccounts: vi.fn(), obSaveAccounts: vi.fn(),
  obCreateUser: vi.fn(), obAccounts: vi.fn(), obTransactions: vi.fn(), getBanks: vi.fn(), openfeedStatus: vi.fn(), openfeedSaveConfig: vi.fn(), openfeedGenerateKeys: vi.fn() }))
import * as books from '../../open_banking/lib/feedApi.js'
import * as api__0 from '../lib/api.js'
import * as api__1 from '../../open_banking/lib/api.js'
import OpenBankingInput from '../components/OpenBankingInput.jsx'
import OpenBankingPage from '../../open_banking/pages/OpenBankingPage.jsx'

describe('return-address helpers', () => {
  it('accept only addresses inside AccFino', () => {
    expect(safeReturn('/reconciliation?input=openbanking')).toBe('/reconciliation?input=openbanking')
    for (const bad of ['//evil.example', 'https://evil.example/x', '/\\evil', 'javascript:alert(1)', '', null, undefined, '/' + 'a'.repeat(300)]) expect(safeReturn(bad), String(bad)).toBeNull()
  })
  it('build the link, add a parameter and name the place', () => {
    expect(withReturn('/settings/open-banking', '/reconciliation?input=openbanking')).toBe('/settings/open-banking?returnTo=%2Freconciliation%3Finput%3Dopenbanking')
    expect(withReturn('/settings/open-banking', 'https://evil.example')).toBe('/settings/open-banking')            // an unsafe address is simply dropped
    expect(withParam('/reconciliation', 'input', 'openbanking')).toBe('/reconciliation?input=openbanking')
    expect(withParam('/reconciliation?x=1&input=csv', 'input', 'openbanking')).toBe('/reconciliation?x=1&input=openbanking')
    expect(returnLabel('/reconciliation?input=openbanking')).toBe('Reconciliation'); expect(returnLabel('/somewhere')).toBe('where you were')
  })
  it('Reconciliation opens on the Open Banking input when the address asks for it', () => {
    expect(inputModeFromSearch('?input=openbanking')).toBe('openbanking'); expect(inputModeFromSearch('')).toBe('csv'); expect(inputModeFromSearch('?input=other')).toBe('csv')
  })
})

const Where = () => { const l = useLocation(); return <div data-testid="where">{l.pathname + l.search}</div> }

describe('Reconciliation > Settings > back again', () => {
  beforeEach(() => { vi.clearAllMocks(); window.confirm = vi.fn(() => true); window.open = vi.fn(() => null) })

  it('the links to Settings from the Reconciliation input carry the way back (empty state and the account list)', async () => {
    api__1.obReconcileAccounts.mockResolvedValueOnce({ data: { accounts: [] } })
    const { unmount } = render(<MemoryRouter initialEntries={['/reconciliation']}><OpenBankingInput onPulled={vi.fn()} /></MemoryRouter>)
    expect((await screen.findByTestId('open-bank-settings')).getAttribute('href')).toBe('/settings/open-banking?returnTo=%2Freconciliation%3Finput%3Dopenbanking')
    unmount()
    api__1.obReconcileAccounts.mockResolvedValueOnce({ data: { accounts: [{ key: 'openfeed:a', provider: 'openfeed', bank: 'ANZ', name: 'One', number: 'xxxx1912' }] } })
    render(<MemoryRouter initialEntries={['/reconciliation']}><OpenBankingInput onPulled={vi.fn()} /></MemoryRouter>)
    expect((await screen.findByTestId('change-bank-accounts')).getAttribute('href')).toContain('returnTo=%2Freconciliation%3Finput%3Dopenbanking')
  })

  const settingsAt = (search) => (
    <MemoryRouter initialEntries={[`/settings/open-banking${search}`]}>
      <Routes><Route path="/settings/open-banking" element={<><OpenBankingPage /><Where /></>} /><Route path="/reconciliation" element={<Where />} /></Routes>
    </MemoryRouter>)
  const RETURN = '?returnTo=%2Freconciliation%3Finput%3Dopenbanking'

  it('shows where it will return to and a way back', async () => {
    api__1.obStatus.mockResolvedValue({ data: { available: true, configured: true } }); api__1.obSavedAccounts.mockResolvedValue({ data: { accounts: [] } }); api__0.getBanks.mockResolvedValue({ data: [] })
    render(settingsAt(RETURN))
    expect(await screen.findByTestId('return-banner')).toHaveTextContent('taken back to Reconciliation')
    fireEvent.click(screen.getByTestId('return-link'))
    await waitFor(() => expect(screen.getByTestId('where')).toHaveTextContent('/reconciliation?input=openbanking'))
  })

  it('no banner and no automatic return when Settings was opened on its own, or with an unsafe address', async () => {
    api__1.obStatus.mockResolvedValue({ data: { available: true, configured: true } }); api__1.obSavedAccounts.mockResolvedValue({ data: { accounts: [] } }); api__0.getBanks.mockResolvedValue({ data: [] })
    const { unmount } = render(settingsAt(''))
    await screen.findByRole('button', { name: 'OpenFeed' }); expect(screen.queryByTestId('return-banner')).toBeNull()
    unmount()
    render(settingsAt('?returnTo=https%3A%2F%2Fevil.example'))
    await screen.findByRole('button', { name: 'OpenFeed' }); expect(screen.queryByTestId('return-banner')).toBeNull()
  })

  it('goes back to Reconciliation by itself once an OpenFeed bank is connected', async () => {
    api__1.obStatus.mockResolvedValue({ data: { available: true, configured: true } }); api__1.obSavedAccounts.mockResolvedValue({ data: { accounts: [] } }); api__0.getBanks.mockResolvedValue({ data: [] })
    books.obFeedStatus.mockResolvedValue({ data: { available: true, status: 'not_connected', can_manage: true, accounts: [], plan_allows: true } })
    render(settingsAt(RETURN))
    fireEvent.click(await screen.findByRole('button', { name: 'OpenFeed' }))
    await screen.findByTestId('connect-bank-btn')
    expect(screen.getByTestId('where')).toHaveTextContent('/settings/open-banking')
    act(() => { window.dispatchEvent(new MessageEvent('message', { data: { type: 'accfino-openfeed', result: 'connected' } })) })      // the pop-up reports success
    await waitFor(() => expect(screen.getByTestId('where')).toHaveTextContent('/reconciliation?input=openbanking'), { timeout: 3000 })
  })

  it('a declined or failed connection stays on Settings', async () => {
    api__1.obStatus.mockResolvedValue({ data: { available: true, configured: true } }); api__1.obSavedAccounts.mockResolvedValue({ data: { accounts: [] } }); api__0.getBanks.mockResolvedValue({ data: [] })
    books.obFeedStatus.mockResolvedValue({ data: { available: true, status: 'not_connected', can_manage: true, accounts: [], plan_allows: true } })
    render(settingsAt(RETURN))
    fireEvent.click(await screen.findByRole('button', { name: 'OpenFeed' })); await screen.findByTestId('connect-bank-btn')
    act(() => { window.dispatchEvent(new MessageEvent('message', { data: { type: 'accfino-openfeed', result: 'declined' } })) })
    await new Promise(r => setTimeout(r, 1300))
    expect(screen.getByTestId('where')).toHaveTextContent('/settings/open-banking')
  })

  it('the full-page fallback keeps the return address while it goes to OpenFeed and back', async () => {
    api__1.obStatus.mockResolvedValue({ data: { available: true, configured: true } }); api__1.obSavedAccounts.mockResolvedValue({ data: { accounts: [] } }); api__0.getBanks.mockResolvedValue({ data: [] })
    books.obFeedStatus.mockResolvedValue({ data: { available: true, status: 'not_connected', can_manage: true, accounts: [], plan_allows: true } })
    books.obFeedConnect.mockResolvedValue({ data: { url: 'https://auth.openfeed.au/auth?x' } })
    Object.defineProperty(window, 'location', { value: { pathname: '/settings/open-banking', search: RETURN, origin: 'http://localhost', assign: vi.fn() }, writable: true })
    window.history.replaceState = vi.fn()
    render(settingsAt(RETURN))
    fireEvent.click(await screen.findByRole('button', { name: 'OpenFeed' }))
    fireEvent.click(await screen.findByTestId('connect-bank-btn'))
    await waitFor(() => expect(books.obFeedConnect).toHaveBeenCalledWith('/settings/open-banking' + RETURN, undefined))                 // path AND query: the way back is not lost
  })
})
