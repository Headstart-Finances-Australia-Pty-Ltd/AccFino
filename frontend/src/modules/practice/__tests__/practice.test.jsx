import React from 'react'
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, fireEvent, waitFor } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'

vi.mock('react-hot-toast', () => ({ default: { success: vi.fn(), error: vi.fn() }, Toaster: () => null }))
let signedIn = true
vi.mock('../../../core/hooks/useAuth.jsx', () => ({ useAuth: () => ({ user: signedIn ? { id: 7, token: 't' } : null }) }))

const A = vi.hoisted(() => ({
  me: vi.fn(), workspace: { create: vi.fn() },
  billing: {
    dashboard: vi.fn(), time: vi.fn(), invoices: vi.fn(), rates: vi.fn(), approveTime: vi.fn(), submitTime: vi.fn(), rejectTime: vi.fn(), writeOff: vi.fn(), logTime: vi.fn(), generate: vi.fn(), invoice: vi.fn(),
  },
  clientPortal: {
    lookup: vi.fn(), accept: vi.fn(), claim: vi.fn(), clients: vi.fn(), dashboard: vi.fn(), requests: vi.fn(), respondText: vi.fn(), documents: vi.fn(), download: vi.fn(),
    messages: vi.fn(), invoices: vi.fn(), consents: vi.fn(), notifications: vi.fn(), postMessage: vi.fn(), uploadFile: vi.fn(), recordConsent: vi.fn(), markRead: vi.fn(),
  },
}))
vi.mock('../lib/practiceApi.js', () => ({ ...A, errMsg: e => e?.message || 'error' }))
import toast from 'react-hot-toast'

beforeEach(() => { vi.clearAllMocks(); signedIn = true })

describe('Practice gate', () => {
  it('offers workspace creation only to the organisation admin and posts the name', async () => {
    A.me.mockResolvedValue({ has_practice: false, can_create: true }); A.workspace.create.mockResolvedValue({ id: 1 })
    const { Gate } = await import('../public.js')
    render(<Gate>{() => <div>TABS</div>}</Gate>)
    fireEvent.change(await screen.findByLabelText('Practice name'), { target: { value: 'Smith & Co' } })
    fireEvent.click(screen.getByRole('button', { name: 'Create practice' }))
    await waitFor(() => expect(A.workspace.create).toHaveBeenCalledWith({ name: 'Smith & Co' }))
    expect(screen.queryByText('TABS')).toBeNull()
  })
  it('tells a non-member why, and shows no tabs', async () => {
    A.me.mockResolvedValue({ has_practice: true, is_member: false })
    const { Gate } = await import('../public.js')
    render(<Gate>{() => <div>TABS</div>}</Gate>)
    expect(await screen.findByText(/not a member of this practice/i)).toBeInTheDocument()
    expect(screen.queryByText('TABS')).toBeNull()
  })
  it('passes the server-decided capabilities to members', async () => {
    A.me.mockResolvedValue({ has_practice: true, is_member: true, capabilities: ['view'] })
    const { Gate } = await import('../public.js')
    render(<Gate>{can => <div>{can('view') ? 'CAN VIEW' : 'NO'} {can('billing_admin') ? 'ADMIN' : 'NOADMIN'}</div>}</Gate>)
    expect(await screen.findByText('CAN VIEW NOADMIN')).toBeInTheDocument()
  })
})

describe('Portal invitation page', () => {
  const mount = async () => { const { PortalAccept } = await import('../public.js'); render(<MemoryRouter><PortalAccept /></MemoryRouter>) }
  it('reads the token from the URL fragment, removes it from the address bar and creates the account for the invited email only', async () => {
    window.history.replaceState(null, '', '/portal/accept#token=abc123')
    A.clientPortal.lookup.mockResolvedValue({ practice: 'Smith & Co', client: 'Acme Pty Ltd', email: 'j***@x.com', account_exists: false, expires_at: '2026-11-01T00:00:00' })
    A.clientPortal.accept.mockResolvedValue({ accepted: true })
    await mount()
    await screen.findByText(/Acme Pty Ltd/)
    expect(window.location.hash).toBe('')                                  // token no longer visible/shareable
    expect(A.clientPortal.lookup).toHaveBeenCalledWith('abc123')
    fireEvent.change(screen.getByLabelText('Full name'), { target: { value: 'Jo Client' } })
    fireEvent.change(screen.getByLabelText('Mobile phone'), { target: { value: '+61412345678' } })
    fireEvent.change(screen.getByLabelText('Choose a password'), { target: { value: 'Str0ng!Passw0rd#2026' } })
    fireEvent.click(screen.getByRole('button', { name: 'Create account' }))
    await waitFor(() => expect(A.clientPortal.accept).toHaveBeenCalled())
    const body = A.clientPortal.accept.mock.calls[0][0]
    expect(body.token).toBe('abc123'); expect(body).not.toHaveProperty('email')
  })
  it('shows one generic message for any invalid, expired or used invitation', async () => {
    window.history.replaceState(null, '', '/portal/accept#token=bad')
    A.clientPortal.lookup.mockRejectedValue(new Error('404'))
    await mount()
    expect(await screen.findByRole('alert')).toHaveTextContent(/invalid, expired or already used/)
  })
  it('an existing account must sign in before accepting', async () => {
    signedIn = false; window.history.replaceState(null, '', '/portal/accept#token=t2')
    A.clientPortal.lookup.mockResolvedValue({ practice: 'P', client: 'C', email: 'a***@x.com', account_exists: true, expires_at: '2026-11-01' })
    await mount()
    expect(await screen.findByRole('link', { name: 'sign in' })).toHaveAttribute('href', '/login')
    expect(screen.queryByRole('button', { name: 'Accept invitation' })).toBeNull()
  })
})

describe('Client portal', () => {
  const mount = async () => { const m = await import('../public.js'); render(<MemoryRouter><m.PortalApp /></MemoryRouter>) }
  it('asks an anonymous visitor to sign in and calls no API', async () => {
    signedIn = false; await mount()
    expect(screen.getByRole('link', { name: 'sign in' })).toBeInTheDocument(); expect(A.clientPortal.clients).not.toHaveBeenCalled()
  })
  it('shows an explicit empty state when the login has no client access', async () => {
    A.clientPortal.clients.mockResolvedValue([]); await mount()
    expect(await screen.findByText('No portal access')).toBeInTheDocument()
  })
  it('shows the server counts, answers a text request item and downloads through a ticket', async () => {
    A.clientPortal.clients.mockResolvedValue([{ client_id: 5, name: 'Acme', practice: 'Smith' }])
    A.clientPortal.dashboard.mockResolvedValue({ client: { id: 5, name: 'Acme' }, practice: 'Smith', open_requests: 2, shared_documents: 1, staff_messages: 0, invoices: 0, unread_notifications: 3 })
    A.clientPortal.requests.mockResolvedValue([{ id: 1, title: 'FY26 records', due_date: null, status: 'requested', items: [{ id: 11, description: 'Bank statements note', response_types: ['text'], status: 'requested' }] }])
    A.clientPortal.respondText.mockResolvedValue({}); A.clientPortal.documents.mockResolvedValue({ items: [{ id: 9, title: 'Engagement letter', category: 'letter', file_name: 'l.pdf', uploaded_at: '2026-10-01' }] })
    await mount()
    expect(await screen.findByText('Open requests')).toBeInTheDocument(); expect(screen.getByText('2')).toBeInTheDocument(); expect(screen.getByText('3')).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: 'Requests' }))
    fireEvent.change(await screen.findByLabelText('Answer for Bank statements note'), { target: { value: 'attached by post' } })
    fireEvent.click(screen.getByRole('button', { name: 'Send answer' }))
    await waitFor(() => expect(A.clientPortal.respondText).toHaveBeenCalledWith(5, 11, 'attached by post'))
    fireEvent.click(screen.getByRole('button', { name: 'Documents' }))
    A.clientPortal.download.mockRejectedValue(new Error('gone'))
    fireEvent.click(await screen.findByRole('button', { name: 'Download' }))
    await waitFor(() => expect(A.clientPortal.download).toHaveBeenCalledWith(5, 9))
    await waitFor(() => expect(toast.error).toHaveBeenCalledWith('gone'))   // a refused download is shown, never silently ignored
  })
})

describe('Billing tab', () => {
  const setup = async (caps, entries) => {
    A.billing.dashboard.mockResolvedValue({ wip: '1070.00', drafted_unissued: '0', submitted_awaiting_approval: { count: 1, minutes: 90 }, invoiced_net: '0', written_off: '100.00', realisation_pct: 85.6, receivables: '0', receivables_overdue: '0' })
    A.billing.time.mockResolvedValue({ items: entries }); A.billing.invoices.mockResolvedValue({ items: [] }); A.billing.rates.mockResolvedValue([])
    const { BillingTab } = await import('../public.js')
    render(<BillingTab can={c => caps.includes(c)} />)
    await screen.findByText('Realisation')
  }
  const entry = { id: 3, work_date: '2026-10-01', client_id: 5, description: 'BAS prep', hours: '1.50', status: 'submitted', billable: true, rate_applied: '180', amount: '270' }
  it('shows server figures (realisation is the server value, not recomputed)', async () => {
    await setup(['billing', 'time'], [entry]); expect(screen.getByText('85.6%')).toBeInTheDocument()
  })
  it('only offers approve to roles with the capability; the approver action sends the selected ids', async () => {
    await setup(['billing', 'time'], [entry]); expect(screen.queryByRole('button', { name: /Approve/ })).toBeNull()
  })
  it('approves the selected entries', async () => {
    A.billing.approveTime.mockResolvedValue({ skipped: [] })
    await setup(['billing', 'time', 'time_approve'], [entry])
    fireEvent.click(screen.getByLabelText('Select entry 3')); fireEvent.click(screen.getByRole('button', { name: /^Approve/ }))
    await waitFor(() => expect(A.billing.approveTime).toHaveBeenCalledWith([3]))
  })
})
