import React from 'react'
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, fireEvent, waitFor } from '@testing-library/react'

vi.mock('react-hot-toast', () => ({ default: Object.assign(vi.fn(), { success: vi.fn(), error: vi.fn() }) }))
vi.mock('../../../lib/booksApi.js', async () => {
  const actual = await vi.importActual('../../../lib/booksApi.js')
  return { ...actual, obFeedStatus: vi.fn(), obFeedConnect: vi.fn(), obFeedSync: vi.fn(), obFeedDisconnect: vi.fn() }
})
import toast from 'react-hot-toast'
import * as api from '../../../lib/booksApi.js'
import BankFeedCard from '../../../components/openbanking/BankFeedCard.jsx'

const ACTIVE = { available: true, status: 'active', can_manage: true, last_sync: '2026-10-01T01:00:00Z', accounts: [{ id: 'a1', name: 'Business Cheque', masked: 'xxxx1234', provider: 'Commonwealth Bank' }] }
let assign
beforeEach(() => {
  vi.clearAllMocks()
  assign = vi.fn()
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
    expect(api.obFeedConnect).toHaveBeenCalledWith('/settings/open-banking')
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
    expect(screen.getByRole('button', { name: /Refresh now/ })).toBeInTheDocument(); expect(screen.getByRole('button', { name: 'Disconnect' })).toBeInTheDocument()
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
