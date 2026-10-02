import React from 'react'
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, fireEvent } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'

let hidden = new Set()
vi.mock('../../../hooks/useModuleVisibility.jsx', () => ({ useModuleVisibility: () => ({ isModuleVisible: id => !hidden.has(id) }) }))
vi.mock('../../../lib/api.js', () => ({ mlStatus: vi.fn(() => Promise.resolve({ data: {} })), mlTrain: vi.fn(), mlSampleCsv: vi.fn() }))
vi.mock('react-hot-toast', () => ({ default: Object.assign(vi.fn(), { success: vi.fn(), error: vi.fn() }) }))
vi.mock('../../admin/PlatformSettingsPanels.jsx', () => ({ default: () => <div data-testid="platform-panels" /> }))
vi.mock('../../admin/OpenBankingSetupPage.jsx', () => ({ default: ({ embedded }) => <div data-testid="open-banking-setup" data-embedded={String(!!embedded)} /> }))
vi.mock('../../PaymentGatewayAdminPage.jsx', () => ({ default: ({ embedded }) => <div data-testid="payment-card-setup" data-embedded={String(!!embedded)} /> }))
import AdminPage from '../../AdminPage.jsx'
import AdminHub from '../../hubs/AdminHub.jsx'

const setUrl = (search) => window.history.replaceState({}, '', '/admin/api-keys' + search)
beforeEach(() => { hidden = new Set(); setUrl('') })

describe('Admin Console > API Keys holds all platform set-up', () => {
  it('has Open Banking and Payment Card Setup as tabs next to Platform Settings', () => {
    render(<AdminPage />)
    expect(screen.getByRole('button', { name: /Platform Settings/ })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /Open Banking/ })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /Payment Card Setup/ })).toBeInTheDocument()
    expect(screen.getByTestId('platform-panels')).toBeInTheDocument()                          // opens on Platform Settings
  })

  it('shows each set-up inside the API Keys page (no second heading) when its tab is chosen', () => {
    render(<AdminPage />)
    fireEvent.click(screen.getByRole('button', { name: /Open Banking/ }))
    expect(screen.getByTestId('open-banking-setup')).toHaveAttribute('data-embedded', 'true')
    expect(screen.queryByTestId('platform-panels')).toBeNull()
    fireEvent.click(screen.getByRole('button', { name: /Payment Card Setup/ }))
    expect(screen.getByTestId('payment-card-setup')).toHaveAttribute('data-embedded', 'true')
  })

  it('a deep link opens the right tab straight away (used by "set it up in Admin Console" links)', () => {
    setUrl('?tab=open-banking')
    render(<AdminPage />)
    expect(screen.getByTestId('open-banking-setup')).toBeInTheDocument()
    expect(screen.queryByTestId('platform-panels')).toBeNull()
  })

  it('an unknown tab in the link falls back to Platform Settings', () => {
    setUrl('?tab=nonsense')
    render(<AdminPage />)
    expect(screen.getByTestId('platform-panels')).toBeInTheDocument()
  })

  it('the Admin Console menu no longer lists Open Banking or Payment Card Setup as separate tabs', () => {
    render(<MemoryRouter initialEntries={['/admin/api-keys']}><AdminHub /></MemoryRouter>)
    expect(screen.getByText('API Keys')).toBeInTheDocument()
    expect(screen.getByText('Pricing')).toBeInTheDocument()
    expect(screen.queryByText('Payment Card Setup')).toBeNull()
    expect(screen.queryByText('Open Banking')).toBeNull()
  })

  it('the Open Banking tab is hidden only when BOTH its providers are switched off in Modules Management (Admin Console)', () => {
    hidden = new Set(['basiq-admin-open-banking'])
    const { unmount } = render(<AdminPage />)
    expect(screen.getByRole('button', { name: /Open Banking/ })).toBeInTheDocument()            // OpenFeed is still on
    unmount()
    hidden = new Set(['basiq-admin-open-banking', 'openfeed-admin-open-banking'])
    render(<AdminPage />)
    expect(screen.queryByRole('button', { name: /Open Banking/ })).toBeNull()
  })

  it('the Payment Card Setup tab follows the Square / Stripe Admin Console switches the same way', () => {
    hidden = new Set(['square-admin-payments'])
    const { unmount } = render(<AdminPage />)
    expect(screen.getByRole('button', { name: /Payment Card Setup/ })).toBeInTheDocument()
    unmount()
    hidden = new Set(['square-admin-payments', 'stripe-admin-payments'])
    render(<AdminPage />)
    expect(screen.queryByRole('button', { name: /Payment Card Setup/ })).toBeNull()
  })

  it('a deep link to a tab that is switched off falls back to Platform Settings', () => {
    hidden = new Set(['basiq-admin-open-banking', 'openfeed-admin-open-banking']); setUrl('?tab=open-banking')
    render(<AdminPage />)
    expect(screen.getByTestId('platform-panels')).toBeInTheDocument()
  })
})
