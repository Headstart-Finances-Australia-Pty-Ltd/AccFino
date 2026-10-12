import React from 'react'
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, fireEvent, waitFor } from '@testing-library/react'

vi.mock('react-hot-toast', () => ({ default: Object.assign(vi.fn(), { success: vi.fn(), error: vi.fn() }) }))
vi.mock('../../../core/lib/adminApi.js', async () => {
  const actual = await vi.importActual('../../../core/lib/adminApi.js')
  return { ...actual, obFeedStatus: vi.fn(), obFeedConnect: vi.fn(), obFeedSync: vi.fn(), obFeedDisconnect: vi.fn(), obFeedSetAccount: vi.fn() }
})
vi.mock('../../accounting/lib/booksApi.js', async () => {
  const actual = await vi.importActual('../../accounting/lib/booksApi.js')
  return { ...actual, obFeedStatus: vi.fn(), obFeedConnect: vi.fn(), obFeedSync: vi.fn(), obFeedDisconnect: vi.fn(), obFeedSetAccount: vi.fn() }
})
vi.mock('../../billing/lib/orgBillingApi.js', async () => {
  const actual = await vi.importActual('../../billing/lib/orgBillingApi.js')
  return { ...actual, obFeedStatus: vi.fn(), obFeedConnect: vi.fn(), obFeedSync: vi.fn(), obFeedDisconnect: vi.fn(), obFeedSetAccount: vi.fn() }
})
vi.mock('../lib/feedApi.js', async () => {
  const actual = await vi.importActual('../lib/feedApi.js')
  return { ...actual, obFeedStatus: vi.fn(), obFeedConnect: vi.fn(), obFeedSync: vi.fn(), obFeedDisconnect: vi.fn(), obFeedSetAccount: vi.fn() }
})
import toast from 'react-hot-toast'
import * as api from '../lib/feedApi.js'
import BankFeedCard from '../components/BankFeedCard.jsx'

const ACTIVE = { available: true, status: 'active', can_manage: true, last_sync: '2026-10-01T01:00:00Z', accounts: [{ id: 'a1', name: 'Business Cheque', masked: 'xxxx1234', provider: 'Commonwealth Bank' }] }
let assign
beforeEach(() => {
  vi.clearAllMocks()
  assign = vi.fn()
  window.open = vi.fn(() => null)                                  // pop-ups blocked unless a test says otherwise
  window.confirm = vi.fn(() => true)                               // confirmations accepted unless a test says otherwise
  Object.defineProperty(window, 'location', { value: { pathname: '/settings/open-banking', search: '', assign }, writable: true })
  window.history.replaceState = vi.fn()
})

describe('Connect my bank (organisation view)', () => {
  it('one button sends the Organisation Admin to OpenFeed and nothing about creating an OpenFeed account is asked of them', async () => {
    api.obFeedStatus.mockResolvedValue({ data: { available: true, status: 'not_connected', can_manage: true, accounts: [] } })
    api.obFeedConnect.mockResolvedValue({ data: { url: 'https://auth.openfeed.au/auth?client_id=app-1&request_uri=urn:x' } })
    render(<BankFeedCard />)
    fireEvent.click(await screen.findByTestId('connect-bank-btn'))
    await waitFor(() => expect(assign).toHaveBeenCalledWith('https://auth.openfeed.au/auth?client_id=app-1&request_uri=urn:x'))
    expect(api.obFeedConnect).toHaveBeenCalledWith('/settings/open-banking', undefined)          // no pop-up (blocked) -> ordinary full-page flow
    expect(screen.queryByText(/client id|api key|register the app/i)).toBeNull()                      // platform setup is never shown to an organisation
    expect(screen.getByText(/no separate account to set up/i)).toBeInTheDocument()
  })

  it('a member who is not the Organisation Admin sees the status but no connect button', async () => {
    api.obFeedStatus.mockResolvedValue({ data: { available: true, status: 'not_connected', can_manage: false, accounts: [] } })
    render(<BankFeedCard />)
    expect(await screen.findByText(/Your Organisation Admin can connect/)).toBeInTheDocument()
    expect(screen.queryByTestId('connect-bank-btn')).toBeNull()
  })

  it('shows the shared accounts and last update once connected, with refresh / change / disconnect for the admin', async () => {
    api.obFeedStatus.mockResolvedValue({ data: ACTIVE })
    render(<BankFeedCard />)
    expect(await screen.findByText('Business Cheque')).toBeInTheDocument()
    expect(screen.getByText('Commonwealth Bank')).toBeInTheDocument(); expect(screen.getByText('xxxx1234')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /Refresh now/ })).toBeInTheDocument(); expect(screen.getByRole('button', { name: 'Disconnect all' })).toBeInTheDocument()
  })

  it('asks to reconnect when the access was withdrawn at OpenFeed', async () => {
    api.obFeedStatus.mockResolvedValue({ data: { available: true, status: 'revoked', can_manage: true, accounts: [] } })
    render(<BankFeedCard />)
    expect(await screen.findByTestId('feed-reconnect')).toHaveTextContent(/withdrawn/)
    expect(screen.getByRole('button', { name: 'Reconnect' })).toBeInTheDocument()
  })

  it('says plainly when the platform has not been set up yet', async () => {
    api.obFeedStatus.mockResolvedValue({ data: { available: false, status: 'not_connected', can_manage: true, accounts: [] } })
    render(<BankFeedCard />)
    expect(await screen.findByTestId('feed-unavailable')).toHaveTextContent(/contact AccFino support/)
    expect(screen.queryByTestId('connect-bank-btn')).toBeNull()
  })

  it('tells the person what happened when OpenFeed sends them back', async () => {
    window.location.search = '?openfeed=connected'
    api.obFeedStatus.mockResolvedValue({ data: ACTIVE })
    render(<BankFeedCard />)
    await waitFor(() => expect(toast.success).toHaveBeenCalledWith('Your bank is connected'))
    window.location.search = '?openfeed=error&reason=flow_expired'
    render(<BankFeedCard />)
    await waitFor(() => expect(toast.error).toHaveBeenCalledWith(expect.stringMatching(/expired/), expect.anything()))
  })
})

// ---------------------------------------------------------------------------------------------------------- the pop-up window
describe('Connect my bank in a pop-up window', () => {
  const fakePopup = () => ({ closed: false, document: { write: vi.fn() }, location: { href: '' }, close: vi.fn(function () { this.closed = true }), focus: vi.fn() })
  const status = { available: true, status: 'not_connected', can_manage: true, accounts: [] }
  const press = async () => { render(<BankFeedCard />); fireEvent.click(await screen.findByTestId('connect-bank-btn')) }

  it('opens OpenFeed in a pop-up window, leaves the page where it is, and tells the server which origin to report back to', async () => {
    const popup = fakePopup(); window.open = vi.fn(() => popup)
    api.obFeedStatus.mockResolvedValue({ data: status })
    api.obFeedConnect.mockResolvedValue({ data: { url: 'https://auth.openfeed.au/auth?client_id=app-1&request_uri=urn:x' } })
    await press()
    await waitFor(() => expect(popup.location.href).toBe('https://auth.openfeed.au/auth?client_id=app-1&request_uri=urn:x'))
    expect(window.open).toHaveBeenCalledWith('about:blank', 'accfino-openfeed', expect.stringContaining('width=520'))     // opened straight from the click
    expect(api.obFeedConnect).toHaveBeenCalledWith('/settings/open-banking', window.location.origin)
    expect(assign).not.toHaveBeenCalled()                                                                              // the main window never navigates away
    expect(screen.getByTestId('connect-bank-btn')).toHaveTextContent('Waiting for OpenFeed')
    expect(screen.getByTestId('connect-bank-btn')).toBeDisabled()
    fireEvent.click(screen.getByTestId('focus-popup')); expect(popup.focus).toHaveBeenCalled()
  })

  it('when the pop-up reports success the card refreshes, says so, and the window is closed', async () => {
    const popup = fakePopup(); window.open = vi.fn(() => popup)
    api.obFeedStatus.mockResolvedValueOnce({ data: status }).mockResolvedValue({ data: ACTIVE })
    api.obFeedConnect.mockResolvedValue({ data: { url: 'https://auth.openfeed.au/auth?x' } })
    await press(); await waitFor(() => expect(popup.location.href).toContain('auth.openfeed.au'))
    window.dispatchEvent(new MessageEvent('message', { data: { type: 'accfino-openfeed', result: 'connected', reason: '' } }))
    await waitFor(() => expect(toast.success).toHaveBeenCalledWith('Your bank is connected'))
    expect(popup.close).toHaveBeenCalled()
    expect(await screen.findByText('Business Cheque')).toBeInTheDocument()                                              // the accounts are shown without a page reload
    expect(screen.queryByText(/Waiting for OpenFeed/)).toBeNull()
  })

  it('declined and error results are explained in plain words', async () => {
    const popup = fakePopup(); window.open = vi.fn(() => popup)
    api.obFeedStatus.mockResolvedValue({ data: status })
    api.obFeedConnect.mockResolvedValue({ data: { url: 'https://auth.openfeed.au/auth?x' } })
    await press(); await waitFor(() => expect(popup.location.href).toContain('auth.openfeed.au'))
    window.dispatchEvent(new MessageEvent('message', { data: { type: 'accfino-openfeed', result: 'declined' } }))
    await waitFor(() => expect(toast).toHaveBeenCalledWith(expect.stringMatching(/Nothing was shared/)))
    fireEvent.click(await screen.findByTestId('connect-bank-btn'))
    await waitFor(() => expect(popup.location.href).toContain('auth.openfeed.au'))
    window.dispatchEvent(new MessageEvent('message', { data: { type: 'accfino-openfeed', result: 'error', reason: 'flow_expired' } }))
    await waitFor(() => expect(toast.error).toHaveBeenCalledWith(expect.stringMatching(/expired/), expect.anything()))
  })

  it('ignores messages that are not from the connect pop-up', async () => {
    const popup = fakePopup(); window.open = vi.fn(() => popup)
    api.obFeedStatus.mockResolvedValue({ data: status })
    api.obFeedConnect.mockResolvedValue({ data: { url: 'https://auth.openfeed.au/auth?x' } })
    await press(); await waitFor(() => expect(popup.location.href).toContain('auth.openfeed.au'))
    window.dispatchEvent(new MessageEvent('message', { data: { type: 'something-else', result: 'connected' } }))
    window.dispatchEvent(new MessageEvent('message', { data: 'just a string' }))
    expect(toast.success).not.toHaveBeenCalled(); expect(popup.close).not.toHaveBeenCalled()
  })

  it('if the person closes the window themselves the button comes back and the status is refreshed', async () => {
    const popup = fakePopup(); window.open = vi.fn(() => popup)
    api.obFeedStatus.mockResolvedValue({ data: status })
    api.obFeedConnect.mockResolvedValue({ data: { url: 'https://auth.openfeed.au/auth?x' } })
    await press(); await waitFor(() => expect(popup.location.href).toContain('auth.openfeed.au'))
    const calls = api.obFeedStatus.mock.calls.length
    popup.closed = true
    await waitFor(() => expect(screen.getByTestId('connect-bank-btn')).toHaveTextContent('Connect my bank'), { timeout: 3000 })
    expect(api.obFeedStatus.mock.calls.length).toBeGreaterThan(calls)
  })

  it('a server error closes the pop-up and shows the message instead of leaving a blank window', async () => {
    const popup = fakePopup(); window.open = vi.fn(() => popup)
    api.obFeedStatus.mockResolvedValue({ data: status })
    api.obFeedConnect.mockRejectedValue({ response: { data: { detail: 'Live bank feeds are not switched on' } } })
    await press()
    await waitFor(() => expect(popup.close).toHaveBeenCalled())
    expect(toast.error).toHaveBeenCalled(); expect(assign).not.toHaveBeenCalled()
    expect(screen.getByTestId('connect-bank-btn')).toHaveTextContent('Connect my bank')
  })

  it('when the browser blocks the pop-up it falls back to the full-page flow instead of doing nothing', async () => {
    window.open = vi.fn(() => null)
    api.obFeedStatus.mockResolvedValue({ data: status })
    api.obFeedConnect.mockResolvedValue({ data: { url: 'https://auth.openfeed.au/auth?x' } })
    await press()
    await waitFor(() => expect(assign).toHaveBeenCalledWith('https://auth.openfeed.au/auth?x'))
    expect(api.obFeedConnect).toHaveBeenCalledWith('/settings/open-banking', undefined)                                 // no pop-up origin: the server returns to the page itself
  })
})

// ---------------------------------------------------------------------------------------- several accounts from several banks
describe('Several accounts from several banks', () => {
  const MULTI = { available: true, status: 'active', can_manage: true, last_sync: '2026-10-02T06:00:00Z', bank_count: 2, accounts: [
    { id: 'a1', name: 'ANZ One Offset', masked: 'xxxx1912', provider: 'ANZ', enabled: true },
    { id: 'a2', name: 'ANZ Business Saver', masked: 'xxxx7788', provider: 'ANZ', enabled: true },
    { id: 'a3', name: 'Everyday Account', masked: 'xxxx4455', provider: 'Commonwealth Bank', enabled: false }] }

  it('lists every shared account with a count of accounts and banks, and marks the ones switched off', async () => {
    api.obFeedStatus.mockResolvedValue({ data: MULTI })
    render(<BankFeedCard />)
    expect(await screen.findByTestId('feed-count')).toHaveTextContent('3 accounts from 2 banks shared with AccFino')
    expect(screen.getByTestId('feed-count')).toHaveTextContent('1 switched off')
    for (const n of ['ANZ One Offset', 'ANZ Business Saver', 'Everyday Account']) expect(screen.getByText(n)).toBeInTheDocument()
    expect(screen.getByLabelText('Use ANZ One Offset in AccFino')).toBeChecked(); expect(screen.getByLabelText('Use Everyday Account in AccFino')).not.toBeChecked()
    expect(screen.getByTestId('feed-help')).toHaveTextContent(/another bank/)
  })

  it('switches ONE account off or on without touching the others', async () => {
    api.obFeedStatus.mockResolvedValue({ data: MULTI }); api.obFeedSetAccount.mockResolvedValue({ data: {} })
    render(<BankFeedCard />)
    fireEvent.click(await screen.findByLabelText('Use ANZ Business Saver in AccFino'))
    await waitFor(() => expect(api.obFeedSetAccount).toHaveBeenCalledWith('a2', false))
    fireEvent.click(screen.getByLabelText('Use Everyday Account in AccFino'))
    await waitFor(() => expect(api.obFeedSetAccount).toHaveBeenCalledWith('a3', true))
    expect(api.obFeedSetAccount).toHaveBeenCalledTimes(2); expect(api.obFeedDisconnect).not.toHaveBeenCalled()
  })

  it('Stop sharing on one account switches just that one off, then opens OpenFeed so permission can be withdrawn there', async () => {
    const popup = { closed: false, document: { write: vi.fn() }, location: { href: '' }, close: vi.fn(), focus: vi.fn() }; window.open = vi.fn(() => popup)
    api.obFeedStatus.mockResolvedValue({ data: MULTI }); api.obFeedSetAccount.mockResolvedValue({ data: {} })
    api.obFeedConnect.mockResolvedValue({ data: { url: 'https://auth.openfeed.au/auth?replace' } })
    render(<BankFeedCard />)
    fireEvent.click(await screen.findByTestId('stop-a1'))
    await waitFor(() => expect(api.obFeedSetAccount).toHaveBeenCalledWith('a1', false))
    await waitFor(() => expect(popup.location.href).toBe('https://auth.openfeed.au/auth?replace'))
    expect(api.obFeedDisconnect).not.toHaveBeenCalled(); expect(api.obFeedSetAccount).toHaveBeenCalledTimes(1)
  })

  it('Stop sharing does nothing if the person cancels the confirmation', async () => {
    window.confirm = vi.fn(() => false)
    api.obFeedStatus.mockResolvedValue({ data: MULTI })
    render(<BankFeedCard />)
    fireEvent.click(await screen.findByTestId('stop-a1'))
    expect(api.obFeedSetAccount).not.toHaveBeenCalled(); expect(api.obFeedConnect).not.toHaveBeenCalled()
  })

  it('"Add or remove accounts" opens OpenFeed to change what is shared, and "Disconnect all" is the only way to drop everything', async () => {
    const popup = { closed: false, document: { write: vi.fn() }, location: { href: '' }, close: vi.fn(), focus: vi.fn() }; window.open = vi.fn(() => popup)
    api.obFeedStatus.mockResolvedValue({ data: MULTI }); api.obFeedConnect.mockResolvedValue({ data: { url: 'https://auth.openfeed.au/auth?replace' } }); api.obFeedDisconnect.mockResolvedValue({ data: {} })
    render(<BankFeedCard />)
    fireEvent.click(await screen.findByTestId('add-remove-accounts'))
    await waitFor(() => expect(api.obFeedConnect).toHaveBeenCalled())
    expect(api.obFeedDisconnect).not.toHaveBeenCalled()
  })

  it('a member who is not the Organisation Admin sees the accounts but no switches or buttons', async () => {
    api.obFeedStatus.mockResolvedValue({ data: { ...MULTI, can_manage: false } })
    render(<BankFeedCard />)
    expect(await screen.findByText('ANZ One Offset')).toBeInTheDocument()
    expect(screen.queryByLabelText('Use ANZ One Offset in AccFino')).toBeNull(); expect(screen.queryByTestId('add-remove-accounts')).toBeNull(); expect(screen.queryByTestId('stop-a1')).toBeNull()
  })
})

