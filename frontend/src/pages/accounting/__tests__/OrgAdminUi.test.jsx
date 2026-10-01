import React from 'react'
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, waitFor, fireEvent } from '@testing-library/react'
import { MemoryRouter, Routes, Route } from 'react-router-dom'

vi.mock('../../../lib/platformApi.js', async () => {
  const actual = await vi.importActual('../../../lib/platformApi.js')
  return { ...actual,
    me: vi.fn(), updateMyProfile: vi.fn(), myContactSend: vi.fn(() => Promise.resolve({ data: { ok: true, required: true, sent_to: 'ne•••@alpha.example' } })), myContactVerify: vi.fn((ch, d, code) => code === '123456' ? Promise.resolve({ data: { token: 'proof-new' } }) : Promise.reject({ response: { data: { detail: 'That code is not correct.' } } })), currentOrg: vi.fn(), myOrgs: vi.fn(() => Promise.resolve({ data: [] })), members: vi.fn(), tracking: vi.fn(() => Promise.resolve({ data: [] })),
    accessPolicy: vi.fn(() => Promise.resolve({ data: { state: 'off', applies_to: 'all' } })), transferAdmin: vi.fn(() => Promise.resolve({ data: { ok: true } })),
    addMember: vi.fn(), changeRole: vi.fn(), removeMember: vi.fn(), updateOrg: vi.fn(), setLockDate: vi.fn(), createOrg: vi.fn(),
    errMsg: e => e?.response?.data?.detail || e?.message || 'error' }
})
vi.mock('../../../components/subscription/SubscriptionCard.jsx', () => ({ default: () => null }))
vi.mock('../../../components/signup/InviteManager.jsx', () => ({ default: () => <div data-testid="invite-manager" /> }))
vi.mock('../../settings/SecurityPage.jsx', () => ({ default: () => <div data-testid="security-page" /> }))
vi.mock('../../../hooks/useAuth.jsx', () => ({ useAuth: () => ({ user: authUser }) }))

import * as api from '../../../lib/platformApi.js'
import { ProfileCard } from '../../MyAccountPage.jsx'
import OrganisationPage from '../../settings/OrganisationPage.jsx'
import useOrgRole from '../../../hooks/useOrgRole.jsx'

let authUser
const type = (label, value) => fireEvent.change(screen.getByLabelText(label), { target: { value } })
const meOk = (over = {}) => ({ data: { name: 'Bob Book', email: 'bob@alpha.example', phone: '+61498765432', phone_display: '0498 765 432', profile_complete: true, missing_contact: [], is_org_admin: false, ...over } })
beforeEach(() => { vi.clearAllMocks(); localStorage.clear(); authUser = { id: 1, organisations: [{ id: 5, role: 'bookkeeper' }], org_id: 5, roles: ['user'] } })

describe('My Account profile', () => {
  it('lets a user change their name without touching contact details or needing a password', async () => {
    api.me.mockResolvedValue(meOk()); api.updateMyProfile.mockResolvedValue(meOk({ name: 'Bobby Book' }))
    render(<ProfileCard />)
    await screen.findByTestId('profile-card')
    type('Full name *', 'Bobby Book')
    fireEvent.click(screen.getByRole('button', { name: 'Save details' }))
    await waitFor(() => expect(api.updateMyProfile).toHaveBeenCalledWith({ full_name: 'Bobby Book', email: 'bob@alpha.example', phone: '0498 765 432' }))
  })

  it('refuses to blank or break email and phone, with the specified messages, before calling the server', async () => {
    api.me.mockResolvedValue(meOk())
    render(<ProfileCard />)
    await screen.findByTestId('profile-card')
    type('Email address *', ''); type('Phone number *', '')
    fireEvent.click(screen.getByRole('button', { name: 'Save details' }))
    expect(await screen.findByTestId('err-email')).toHaveTextContent('Email address is required.')
    expect(screen.getByTestId('err-phone')).toHaveTextContent('Phone number is required.')
    type('Email address *', 'nope'); type('Phone number *', '12')
    fireEvent.click(screen.getByRole('button', { name: 'Save details' }))
    expect(await screen.findByTestId('err-email')).toHaveTextContent('Please enter a valid email address.')
    expect(screen.getByTestId('err-phone')).toHaveTextContent('Please enter a valid phone number.')
    expect(api.updateMyProfile).not.toHaveBeenCalled()
  })

  it('needs the current password to replace an email address that is already set', async () => {
    api.me.mockResolvedValue(meOk()); api.updateMyProfile.mockResolvedValue(meOk({ email: 'new@alpha.example' }))
    render(<ProfileCard />)
    await screen.findByTestId('profile-card')
    type('Email address *', 'new@alpha.example')
    fireEvent.click(screen.getByRole('button', { name: 'Save details' }))
    expect(await screen.findByTestId('err-current_password')).toBeInTheDocument()
    expect(api.updateMyProfile).not.toHaveBeenCalled()
    type('Current password *', 'Str0ng!Passw0rd#2026')
    fireEvent.click(screen.getByRole('button', { name: 'Save details' }))
    await waitFor(() => expect(api.updateMyProfile).toHaveBeenCalledWith(expect.objectContaining({ email: 'new@alpha.example', current_password: 'Str0ng!Passw0rd#2026' })))
  })

  it('an old account missing its phone is told to add it, and filling it in needs no password', async () => {
    api.me.mockResolvedValue(meOk({ phone: null, phone_display: '', profile_complete: false, missing_contact: ['phone'] }))
    api.updateMyProfile.mockResolvedValue(meOk())
    render(<ProfileCard required />)
    expect(await screen.findByTestId('profile-incomplete')).toHaveTextContent('phone number')
    type('Phone number *', '0498 765 432')
    expect(screen.queryByLabelText('Current password *')).not.toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: 'Save details' }))
    await waitFor(() => expect(api.updateMyProfile).toHaveBeenCalled())
    await waitFor(() => expect(JSON.parse(localStorage.getItem('af_user'))).toMatchObject({ phone: '+61498765432', profile_incomplete: false, missing_contact: [] }))   // the app stops asking
  })

  it('tells the Organisation Admin their details are the organisation contact details', async () => {
    api.me.mockResolvedValue(meOk({ is_org_admin: true }))
    render(<ProfileCard />)
    expect(await screen.findByText(/primary contact details/)).toBeInTheDocument()
  })
})

describe('typing keeps focus', () => {
  // A real browser drops focus (so only the first character can be typed) when an <input> is rebuilt on every keystroke. jsdom's fireEvent doesn't notice that by itself,
  // so check that the very same DOM node survives each change.
  it('My Account: the input element is not rebuilt while the person types', async () => {
    api.me.mockResolvedValue(meOk())
    render(<ProfileCard />)
    await screen.findByTestId('profile-card')
    for (const label of ['Full name *', 'Email address *', 'Phone number *']) {
      const before = screen.getByLabelText(label)
      before.focus()
      fireEvent.change(before, { target: { value: 'x' } }); fireEvent.change(screen.getByLabelText(label), { target: { value: 'xy' } })
      expect(screen.getByLabelText(label)).toBe(before)
      expect(document.activeElement).toBe(before)
    }
  })
})

describe('My Account verification', () => {
  const verif = { email_required: true, phone_required: true, email_needed: false, phone_needed: false }
  it('a changed email must be verified before it can be saved, and the proof is sent', async () => {
    api.me.mockResolvedValue(meOk({ verification: verif, email_verified: true, phone_verified: true })); api.updateMyProfile.mockResolvedValue(meOk({ email: 'new@alpha.example' }))
    render(<ProfileCard />)
    await screen.findByTestId('profile-card')
    expect(screen.queryByTestId('verify-email')).not.toBeInTheDocument()                          // unchanged and already verified: nothing to do
    type('Email address *', 'new@alpha.example'); type('Current password *', 'pw')
    fireEvent.click(screen.getByRole('button', { name: 'Save details' }))
    expect(await screen.findByTestId('err-email')).toHaveTextContent('Please verify your email address.')
    expect(api.updateMyProfile).not.toHaveBeenCalled()
    fireEvent.click(screen.getByRole('button', { name: /Send code to verify email address/ }))
    fireEvent.change(await screen.findByLabelText('Email verification code'), { target: { value: '123456' } })
    fireEvent.click(screen.getByRole('button', { name: 'Verify' }))
    await screen.findByText(/Email verified/)
    fireEvent.click(screen.getByRole('button', { name: 'Save details' }))
    await waitFor(() => expect(api.updateMyProfile).toHaveBeenCalledWith(expect.objectContaining({ email: 'new@alpha.example', email_token: 'proof-new', current_password: 'pw' })))
  })

  it('an existing unverified account is offered verification of what it already has', async () => {
    api.me.mockResolvedValue(meOk({ verification: { ...verif, email_needed: true }, email_verified: false, phone_verified: true }))
    render(<ProfileCard />)
    await screen.findByTestId('profile-card')
    expect(screen.getByTestId('verify-email')).toBeInTheDocument()
    expect(screen.getByText(/Phone verified/)).toBeInTheDocument()
  })
})

describe('useOrgRole: only the Organisation Admin is an admin', () => {
  const Probe = () => { const r = useOrgRole(); return <div data-testid="probe">{String(r.isOrgAdmin)}|{r.role}|{String(r.loading)}</div> }
  it.each([['owner', 'true'], ['accountant', 'false'], ['bookkeeper', 'false'], ['admin', 'false'], ['readonly', 'false']])('%s -> isOrgAdmin %s', async (role, expected) => {
    authUser = { id: 1, organisations: [{ id: 5, role }], org_id: 5, roles: ['user'] }
    api.currentOrg.mockResolvedValue({ data: { role, is_org_admin: role === 'owner' } })
    render(<Probe />)
    await waitFor(() => expect(screen.getByTestId('probe')).toHaveTextContent(`${expected}|${role}|false`))
  })
  it('trusts the server answer over the cached session', async () => {
    authUser = { id: 1, organisations: [{ id: 5, role: 'owner' }], org_id: 5, roles: ['user'] }                       // stale browser data says owner...
    api.currentOrg.mockResolvedValue({ data: { role: 'readonly', is_org_admin: false } })                              // ...the server says otherwise
    render(<Probe />)
    await waitFor(() => expect(screen.getByTestId('probe')).toHaveTextContent('false|readonly|false'))
  })
  it('an error is treated as not-admin', async () => {
    authUser = { id: 1, organisations: [], org_id: 5, roles: ['user'] }
    api.currentOrg.mockRejectedValue({ response: { status: 403 } })
    render(<Probe />)
    await waitFor(() => expect(screen.getByTestId('probe')).toHaveTextContent('false|'))
  })
})

describe('OrganisationPage', () => {
  const org = (over = {}) => ({ data: { id: 5, name: 'Alpha Pty Ltd', role: 'owner', is_org_admin: true, admin_name: 'Olive Owner', admin_email: 'olive@alpha.example', admin_phone: '+61412345678', gst_registered: true, gst_basis: 'accrual', fy_end_month: 6, lock_date: null, ...over } })
  const mem = [{ user_id: 1, name: 'Olive Owner', email: 'olive@alpha.example', phone: '+61412345678', role: 'owner', is_org_admin: true },
               { user_id: 2, name: 'Bob Book', email: 'bob@alpha.example', phone: '+61498765432', role: 'bookkeeper', is_org_admin: false }]
  const renderPage = () => render(<MemoryRouter><OrganisationPage /></MemoryRouter>)

  it('shows the single Organisation Admin as the primary contact, with no role picker or Remove for them', async () => {
    api.currentOrg.mockResolvedValue(org()); api.members.mockResolvedValue({ data: mem })
    renderPage()
    const card = await screen.findByTestId('primary-contact')
    expect(card).toHaveTextContent('Olive Owner'); expect(card).toHaveTextContent('olive@alpha.example'); expect(card).toHaveTextContent('0412 345 678')
    const adminRow = await screen.findByTestId('member-1')
    expect(adminRow).toHaveTextContent('Organisation Admin'); expect(adminRow.querySelector('select')).toBeNull(); expect(adminRow).not.toHaveTextContent('Remove')
    const row = screen.getByTestId('member-2')
    expect(row.querySelector('select')).not.toBeNull(); expect(row).toHaveTextContent('Remove')
    expect(Array.from(row.querySelectorAll('option')).map(o => o.value)).toEqual(['accountant', 'bookkeeper', 'payroll', 'readonly'])     // never owner/admin
  })

  it('transfers the organisation only after confirmation and with a password', async () => {
    api.currentOrg.mockResolvedValue(org()); api.members.mockResolvedValue({ data: mem }); window.confirm = vi.fn(() => true)
    delete window.location; window.location = { reload: vi.fn() }
    renderPage()
    await screen.findByTestId('transfer-admin')
    const btn = screen.getByRole('button', { name: 'Make Organisation Admin' })
    expect(btn).toBeDisabled()
    fireEvent.change(screen.getByLabelText('New Organisation Admin'), { target: { value: '2' } })
    fireEvent.change(screen.getByLabelText('Your password'), { target: { value: 'pw' } })
    fireEvent.click(btn)
    await waitFor(() => expect(api.transferAdmin).toHaveBeenCalledWith(2, 'pw'))
  })

  it('a non-admin sees no editing controls, no member list and no access policy (and the server would refuse them anyway)', async () => {
    api.currentOrg.mockResolvedValue(org({ role: 'bookkeeper', is_org_admin: false, admin_email: undefined, admin_phone: undefined }))
    renderPage()
    await screen.findByText('Organisation')
    expect(api.members).not.toHaveBeenCalled()
    expect(screen.queryByRole('button', { name: 'Save details' })).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Save lock date' })).not.toBeInTheDocument()
    expect(screen.queryByTestId('transfer-admin')).not.toBeInTheDocument()
    expect(screen.queryByText(/Access policy/)).not.toBeInTheDocument()
    expect(api.accessPolicy).not.toHaveBeenCalled()
  })
})
