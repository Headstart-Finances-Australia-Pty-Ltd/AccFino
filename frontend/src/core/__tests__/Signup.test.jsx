import React from 'react'
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, waitFor, fireEvent, within } from '@testing-library/react'

vi.mock('../lib/adminApi.js', async () => {
  const { booksApiMockFactory } = await import('../test/testUtils.js')
  const base = await booksApiMockFactory()
  return { ...base,
    tenantCurrent: vi.fn(() => Promise.resolve({ data: { tenant: null } })),
    contactConfig: vi.fn(() => Promise.resolve({ data: { mode: 'off', email_required: false, phone_required: false } })),
    contactSend: vi.fn((ch, dest) => Promise.resolve({ data: { ok: true, required: true, sent_to: ch === 'email' ? 'ne•••@alpha.example' : '•••• 678' } })),
    contactVerify: vi.fn((ch, dest, code) => code === '123456' ? Promise.resolve({ data: { ok: true, token: `proof-${ch}` } }) : Promise.reject({ response: { data: { detail: 'That code is not correct.' } } })),
    signupValidateOrg: vi.fn(() => Promise.resolve({ data: { ok: true, slug: 'alpha', tenant_url: 'https://alpha.acc.test' } })),
    signupCreateOrg: vi.fn(() => Promise.resolve({ data: { ok: true, tenant_url: 'https://alpha.acc.test', login_url: 'https://alpha.acc.test/login', organisation: { name: 'Alpha Pty Ltd' } } })),
    signupSearchOrgs: vi.fn(() => Promise.resolve({ data: { items: [{ slug: 'alpha', name: 'Alpha Pty Ltd', location: 'Sydney, NSW' }] } })),
    signupLookupOrg: vi.fn(() => Promise.resolve({ data: { slug: 'alpha', name: 'Alpha Pty Ltd', location: 'Sydney, NSW' } })),
    signupVerifyCode: vi.fn(() => Promise.resolve({ data: { ok: true, signup_token: 'tok123', role: 'bookkeeper', organisation: { name: 'Alpha Pty Ltd', slug: 'alpha' } } })),
    signupJoin: vi.fn(() => Promise.resolve({ data: { ok: true, tenant_url: 'https://alpha.acc.test', login_url: 'https://alpha.acc.test/login', organisation: { name: 'Alpha Pty Ltd' } } })),
    listInvites: vi.fn(), createInvites: vi.fn(), revokeInvite: vi.fn(() => Promise.resolve({ data: { ok: true } })), getTenantProfile: vi.fn(), patchTenantProfile: vi.fn(),
    errMsg: e => e?.response?.data?.detail || e?.message || 'error',
  }
})
vi.mock('../../modules/accounting/lib/booksApi.js', async () => {
  const { booksApiMockFactory } = await import('../test/testUtils.js')
  const base = await booksApiMockFactory()
  return { ...base,
    tenantCurrent: vi.fn(() => Promise.resolve({ data: { tenant: null } })),
    contactConfig: vi.fn(() => Promise.resolve({ data: { mode: 'off', email_required: false, phone_required: false } })),
    contactSend: vi.fn((ch, dest) => Promise.resolve({ data: { ok: true, required: true, sent_to: ch === 'email' ? 'ne•••@alpha.example' : '•••• 678' } })),
    contactVerify: vi.fn((ch, dest, code) => code === '123456' ? Promise.resolve({ data: { ok: true, token: `proof-${ch}` } }) : Promise.reject({ response: { data: { detail: 'That code is not correct.' } } })),
    signupValidateOrg: vi.fn(() => Promise.resolve({ data: { ok: true, slug: 'alpha', tenant_url: 'https://alpha.acc.test' } })),
    signupCreateOrg: vi.fn(() => Promise.resolve({ data: { ok: true, tenant_url: 'https://alpha.acc.test', login_url: 'https://alpha.acc.test/login', organisation: { name: 'Alpha Pty Ltd' } } })),
    signupSearchOrgs: vi.fn(() => Promise.resolve({ data: { items: [{ slug: 'alpha', name: 'Alpha Pty Ltd', location: 'Sydney, NSW' }] } })),
    signupLookupOrg: vi.fn(() => Promise.resolve({ data: { slug: 'alpha', name: 'Alpha Pty Ltd', location: 'Sydney, NSW' } })),
    signupVerifyCode: vi.fn(() => Promise.resolve({ data: { ok: true, signup_token: 'tok123', role: 'bookkeeper', organisation: { name: 'Alpha Pty Ltd', slug: 'alpha' } } })),
    signupJoin: vi.fn(() => Promise.resolve({ data: { ok: true, tenant_url: 'https://alpha.acc.test', login_url: 'https://alpha.acc.test/login', organisation: { name: 'Alpha Pty Ltd' } } })),
    listInvites: vi.fn(), createInvites: vi.fn(), revokeInvite: vi.fn(() => Promise.resolve({ data: { ok: true } })), getTenantProfile: vi.fn(), patchTenantProfile: vi.fn(),
    errMsg: e => e?.response?.data?.detail || e?.message || 'error',
  }
})
vi.mock('../../modules/billing/lib/orgBillingApi.js', async () => {
  const { booksApiMockFactory } = await import('../test/testUtils.js')
  const base = await booksApiMockFactory()
  return { ...base,
    tenantCurrent: vi.fn(() => Promise.resolve({ data: { tenant: null } })),
    contactConfig: vi.fn(() => Promise.resolve({ data: { mode: 'off', email_required: false, phone_required: false } })),
    contactSend: vi.fn((ch, dest) => Promise.resolve({ data: { ok: true, required: true, sent_to: ch === 'email' ? 'ne•••@alpha.example' : '•••• 678' } })),
    contactVerify: vi.fn((ch, dest, code) => code === '123456' ? Promise.resolve({ data: { ok: true, token: `proof-${ch}` } }) : Promise.reject({ response: { data: { detail: 'That code is not correct.' } } })),
    signupValidateOrg: vi.fn(() => Promise.resolve({ data: { ok: true, slug: 'alpha', tenant_url: 'https://alpha.acc.test' } })),
    signupCreateOrg: vi.fn(() => Promise.resolve({ data: { ok: true, tenant_url: 'https://alpha.acc.test', login_url: 'https://alpha.acc.test/login', organisation: { name: 'Alpha Pty Ltd' } } })),
    signupSearchOrgs: vi.fn(() => Promise.resolve({ data: { items: [{ slug: 'alpha', name: 'Alpha Pty Ltd', location: 'Sydney, NSW' }] } })),
    signupLookupOrg: vi.fn(() => Promise.resolve({ data: { slug: 'alpha', name: 'Alpha Pty Ltd', location: 'Sydney, NSW' } })),
    signupVerifyCode: vi.fn(() => Promise.resolve({ data: { ok: true, signup_token: 'tok123', role: 'bookkeeper', organisation: { name: 'Alpha Pty Ltd', slug: 'alpha' } } })),
    signupJoin: vi.fn(() => Promise.resolve({ data: { ok: true, tenant_url: 'https://alpha.acc.test', login_url: 'https://alpha.acc.test/login', organisation: { name: 'Alpha Pty Ltd' } } })),
    listInvites: vi.fn(), createInvites: vi.fn(), revokeInvite: vi.fn(() => Promise.resolve({ data: { ok: true } })), getTenantProfile: vi.fn(), patchTenantProfile: vi.fn(),
    errMsg: e => e?.response?.data?.detail || e?.message || 'error',
  }
})
vi.mock('../../modules/open_banking/lib/feedApi.js', async () => {
  const { booksApiMockFactory } = await import('../test/testUtils.js')
  const base = await booksApiMockFactory()
  return { ...base,
    tenantCurrent: vi.fn(() => Promise.resolve({ data: { tenant: null } })),
    contactConfig: vi.fn(() => Promise.resolve({ data: { mode: 'off', email_required: false, phone_required: false } })),
    contactSend: vi.fn((ch, dest) => Promise.resolve({ data: { ok: true, required: true, sent_to: ch === 'email' ? 'ne•••@alpha.example' : '•••• 678' } })),
    contactVerify: vi.fn((ch, dest, code) => code === '123456' ? Promise.resolve({ data: { ok: true, token: `proof-${ch}` } }) : Promise.reject({ response: { data: { detail: 'That code is not correct.' } } })),
    signupValidateOrg: vi.fn(() => Promise.resolve({ data: { ok: true, slug: 'alpha', tenant_url: 'https://alpha.acc.test' } })),
    signupCreateOrg: vi.fn(() => Promise.resolve({ data: { ok: true, tenant_url: 'https://alpha.acc.test', login_url: 'https://alpha.acc.test/login', organisation: { name: 'Alpha Pty Ltd' } } })),
    signupSearchOrgs: vi.fn(() => Promise.resolve({ data: { items: [{ slug: 'alpha', name: 'Alpha Pty Ltd', location: 'Sydney, NSW' }] } })),
    signupLookupOrg: vi.fn(() => Promise.resolve({ data: { slug: 'alpha', name: 'Alpha Pty Ltd', location: 'Sydney, NSW' } })),
    signupVerifyCode: vi.fn(() => Promise.resolve({ data: { ok: true, signup_token: 'tok123', role: 'bookkeeper', organisation: { name: 'Alpha Pty Ltd', slug: 'alpha' } } })),
    signupJoin: vi.fn(() => Promise.resolve({ data: { ok: true, tenant_url: 'https://alpha.acc.test', login_url: 'https://alpha.acc.test/login', organisation: { name: 'Alpha Pty Ltd' } } })),
    listInvites: vi.fn(), createInvites: vi.fn(), revokeInvite: vi.fn(() => Promise.resolve({ data: { ok: true } })), getTenantProfile: vi.fn(), patchTenantProfile: vi.fn(),
    errMsg: e => e?.response?.data?.detail || e?.message || 'error',
  }
})

import * as api from '../lib/adminApi.js'
import SignupFlow from '../components/signup/SignupFlow.jsx'
import InviteManager from '../components/signup/InviteManager.jsx'

const type = (label, value) => fireEvent.change(screen.getByLabelText(label), { target: { value } })
const fillUser = (email = 'new@alpha.example', pw = 'Str0ng!Passw0rd#2026', confirm = pw, phone = '0412 345 678') => {
  type('First Name', 'Nina'); type('Last Name', 'New'); type('Email Address', email); type('Phone Number', phone); type('Password', pw); type('Confirm Password', confirm)
}
beforeEach(() => { vi.clearAllMocks() })

describe('SignupFlow - organisation first', () => {
  it('starts with the organisation choice, never with the account form', () => {
    render(<SignupFlow />)
    expect(screen.getByText('What would you like to do?')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /Create a New Organisation/ })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /Join an Existing Organisation/ })).toBeInTheDocument()
    expect(screen.queryByLabelText('Password')).not.toBeInTheDocument()
  })

  it('new organisation: details -> account -> created, then the tenant address', async () => {
    render(<SignupFlow />)
    fireEvent.click(screen.getByRole('button', { name: /Create a New Organisation/ }))
    type('Organisation name', 'Alpha Pty Ltd'); type('ABN', '51 824 753 556'); type('Address', '1 George St'); type('City or suburb', 'Sydney'); type('Contact email', 'office@alpha.example')
    fireEvent.click(screen.getByRole('button', { name: 'Continue' }))
    await waitFor(() => expect(api.signupValidateOrg).toHaveBeenCalled())
    expect(await screen.findByText(/Its address will be/)).toBeInTheDocument()
    expect(screen.getByText('https://alpha.acc.test')).toBeInTheDocument()
    fillUser()
    fireEvent.click(screen.getByRole('button', { name: 'Create Account' }))
    await waitFor(() => expect(api.signupCreateOrg).toHaveBeenCalledWith(expect.objectContaining({
      org: expect.objectContaining({ name: 'Alpha Pty Ltd', abn: '51 824 753 556', slug: 'alpha' }), user: expect.objectContaining({ email: 'new@alpha.example', phone: '0412 345 678' }) })))
    expect(await screen.findByTestId('signup-done')).toHaveTextContent('https://alpha.acc.test')
    expect(screen.getByRole('button', { name: /Go to Alpha Pty Ltd and sign in/ })).toBeInTheDocument()
  })

  it('shows the server problem and stays on the organisation form when details are rejected', async () => {
    api.signupValidateOrg.mockImplementationOnce(() => Promise.reject({ response: { data: { detail: 'That ABN is not valid (11 digits, ATO checksum)' } } }))
    render(<SignupFlow />)
    fireEvent.click(screen.getByRole('button', { name: /Create a New Organisation/ }))
    type('Organisation name', 'Alpha Pty Ltd'); type('ABN', '11 111 111 111'); type('Address', '1 George St'); type('City or suburb', 'Sydney'); type('Contact email', 'office@alpha.example')
    fireEvent.click(screen.getByRole('button', { name: 'Continue' }))
    expect(await screen.findByRole('alert')).toHaveTextContent('ABN is not valid')
    expect(screen.queryByLabelText('Password')).not.toBeInTheDocument()
  })

  it('join: choosing an organisation is NOT enough - the account form only appears after a valid code', async () => {
    render(<SignupFlow />)
    fireEvent.click(screen.getByRole('button', { name: /Join an Existing Organisation/ }))
    type('Organisation name', 'alp')
    fireEvent.click(await screen.findByTestId('org-result-alpha', {}, { timeout: 2000 }))
    expect(screen.queryByLabelText('Password')).not.toBeInTheDocument()                    // organisation chosen, still no account form
    expect(screen.getByRole('button', { name: 'Verify & Continue' })).toBeDisabled()        // and no code yet
    type('Organisation access code', 'ALP-7F4K-92LM')
    fireEvent.click(screen.getByRole('button', { name: 'Verify & Continue' }))
    await waitFor(() => expect(api.signupVerifyCode).toHaveBeenCalledWith('alpha', 'ALP-7F4K-92LM'))
    expect(await screen.findByText(/Joining/)).toHaveTextContent('Bookkeeper')
    fillUser()
    fireEvent.click(screen.getByRole('button', { name: 'Create Account' }))
    await waitFor(() => expect(api.signupJoin).toHaveBeenCalledWith({ signup_token: 'tok123', user: expect.objectContaining({ email: 'new@alpha.example', phone: '0412 345 678' }) }))
    expect(await screen.findByTestId('signup-done')).toHaveTextContent('Welcome to Alpha Pty Ltd')
  })

  it('a bad code is refused and the person stays on the verification step', async () => {
    api.signupVerifyCode.mockImplementationOnce(() => Promise.reject({ response: { data: { detail: 'That access code is not valid, or has expired. Check it with your organisation administrator.' } } }))
    render(<SignupFlow />)
    fireEvent.click(screen.getByRole('button', { name: /Join an Existing Organisation/ }))
    type('Organisation name', 'alp')
    fireEvent.click(await screen.findByTestId('org-result-alpha', {}, { timeout: 2000 }))
    type('Organisation access code', 'WRONG-CODE-1')
    fireEvent.click(screen.getByRole('button', { name: 'Verify & Continue' }))
    expect(await screen.findByRole('alert')).toHaveTextContent('not valid')
    expect(screen.queryByLabelText('Password')).not.toBeInTheDocument()
    expect(api.signupJoin).not.toHaveBeenCalled()
  })

  it('a licence-limit refusal is shown as is', async () => {
    api.signupVerifyCode.mockImplementationOnce(() => Promise.reject({ response: { data: { detail: 'This organisation has reached its licensed user limit. Please contact your organisation administrator.' } } }))
    render(<SignupFlow />)
    fireEvent.click(screen.getByRole('button', { name: /Join an Existing Organisation/ }))
    type('Organisation name', 'alp')
    fireEvent.click(await screen.findByTestId('org-result-alpha', {}, { timeout: 2000 }))
    type('Organisation access code', 'ALP-7F4K-92LM')
    fireEvent.click(screen.getByRole('button', { name: 'Verify & Continue' }))
    expect(await screen.findByRole('alert')).toHaveTextContent('licensed user limit')
  })

  it('mismatched passwords never reach the server', async () => {
    render(<SignupFlow />)
    fireEvent.click(screen.getByRole('button', { name: /Join an Existing Organisation/ }))
    type('Organisation name', 'alp')
    fireEvent.click(await screen.findByTestId('org-result-alpha', {}, { timeout: 2000 }))
    type('Organisation access code', 'ALP-7F4K-92LM')
    fireEvent.click(screen.getByRole('button', { name: 'Verify & Continue' }))
    await screen.findByText(/Joining/)
    fillUser('x@y.example', 'Str0ng!Passw0rd#2026', 'different')
    fireEvent.click(screen.getByRole('button', { name: 'Create Account' }))
    expect(await screen.findByTestId('err-confirm')).toHaveTextContent('do not match')
    expect(api.signupJoin).not.toHaveBeenCalled()
  })

  const reachAccountForm = async () => {
    render(<SignupFlow />)
    fireEvent.click(screen.getByRole('button', { name: /Join an Existing Organisation/ }))
    type('Organisation name', 'alp')
    fireEvent.click(await screen.findByTestId('org-result-alpha', {}, { timeout: 2000 }))
    type('Organisation access code', 'ALP-7F4K-92LM')
    fireEvent.click(screen.getByRole('button', { name: 'Verify & Continue' }))
    await screen.findByText(/Joining/)
  }

  it('typing in the account form does not rebuild the inputs (a real browser would drop focus)', async () => {
    await reachAccountForm()
    for (const label of ['First Name', 'Email Address', 'Phone Number', 'Password']) {
      const before = screen.getByLabelText(label); before.focus()
      fireEvent.change(before, { target: { value: 'a' } }); fireEvent.change(screen.getByLabelText(label), { target: { value: 'ab' } })
      expect(screen.getByLabelText(label)).toBe(before); expect(document.activeElement).toBe(before)
    }
  })

  it('shows every mandatory field with an asterisk, exactly as specified', async () => {
    await reachAccountForm()
    const form = screen.getByTestId('signup-user')
    for (const l of ['First Name *', 'Last Name *', 'Email Address *', 'Phone Number *', 'Password *', 'Confirm Password *']) expect(form).toHaveTextContent(l)
  })

  it('email and phone cannot be left out: clear messages, and nothing is sent to the server', async () => {
    await reachAccountForm()
    fillUser('', 'Str0ng!Passw0rd#2026', undefined, '')
    fireEvent.click(screen.getByRole('button', { name: 'Create Account' }))
    expect(await screen.findByTestId('err-email')).toHaveTextContent('Email address is required.')
    expect(screen.getByTestId('err-phone')).toHaveTextContent('Phone number is required.')
    expect(api.signupJoin).not.toHaveBeenCalled()
  })

  it('invalid email and phone are explained and never sent', async () => {
    await reachAccountForm()
    fillUser('not-an-email', 'Str0ng!Passw0rd#2026', undefined, '12345')
    fireEvent.click(screen.getByRole('button', { name: 'Create Account' }))
    expect(await screen.findByTestId('err-email')).toHaveTextContent('Please enter a valid email address.')
    expect(screen.getByTestId('err-phone')).toHaveTextContent('Please enter a valid phone number.')
    expect(api.signupJoin).not.toHaveBeenCalled()
  })

  it('a server-side rejection of email/phone is shown (the frontend is not the only check)', async () => {
    api.signupJoin.mockImplementationOnce(() => Promise.reject({ response: { data: { detail: 'Phone number is required.' } } }))
    await reachAccountForm()
    fillUser()
    fireEvent.click(screen.getByRole('button', { name: 'Create Account' }))
    expect(await screen.findByRole('alert')).toHaveTextContent('Phone number is required.')
  })

  it('a new organisation makes the person its Organisation Admin and asks for the same mandatory fields', async () => {
    render(<SignupFlow />)
    expect(screen.getByRole('button', { name: /Create a New Organisation/ })).toHaveTextContent('Organisation Admin')
    fireEvent.click(screen.getByRole('button', { name: /Create a New Organisation/ }))
    type('Organisation name', 'Alpha Pty Ltd'); type('ABN', '51 824 753 556'); type('Address', '1 George St'); type('City or suburb', 'Sydney')
    fireEvent.click(screen.getByRole('button', { name: 'Continue' }))
    await screen.findByText(/Its address will be/)
    expect(screen.getByTestId('signup-user')).toHaveTextContent('Organisation Admin')
    fillUser('', undefined, undefined, '')
    fireEvent.click(screen.getByRole('button', { name: 'Create Account' }))
    expect(await screen.findByTestId('err-email')).toBeInTheDocument()
    expect(api.signupCreateOrg).not.toHaveBeenCalled()
  })

  it("on an organisation's own address the organisation is fixed and no search is offered", async () => {
    render(<SignupFlow tenant={{ tenant: 'alpha', found: true, name: 'Alpha Pty Ltd' }} />)
    expect(await screen.findByText('Join Alpha Pty Ltd')).toBeInTheDocument()
    expect(screen.queryByLabelText('Organisation name')).not.toBeInTheDocument()
    expect(api.signupLookupOrg).toHaveBeenCalledWith('alpha')
    expect(await screen.findByLabelText('Organisation access code')).toBeInTheDocument()
  })
})

describe('SignupFlow - email and phone verification', () => {
  const reach = async () => {
    api.contactConfig.mockImplementation(() => Promise.resolve({ data: { mode: 'both', email_required: true, phone_required: true } }))
    render(<SignupFlow />)
    fireEvent.click(screen.getByRole('button', { name: /Join an Existing Organisation/ }))
    type('Organisation name', 'alp')
    fireEvent.click(await screen.findByTestId('org-result-alpha', {}, { timeout: 2000 }))
    type('Organisation access code', 'ALP-7F4K-92LM')
    fireEvent.click(screen.getByRole('button', { name: 'Verify & Continue' }))
    await screen.findByText(/Joining/)
  }
  const verifyChannel = async (channel, word, label) => {
    fireEvent.click(within(screen.getByTestId(`verify-${channel}`)).getByRole('button', { name: new RegExp(`Send code to verify ${word}`) }))
    fireEvent.change(await screen.findByLabelText(`${label} verification code`), { target: { value: '123456' } })
    fireEvent.click(within(screen.getByTestId(`verify-${channel}`)).getByRole('button', { name: 'Verify' }))
    await within(screen.getByTestId(`verify-${channel}`)).findByText(/verified/)
  }

  it('cannot create the account until the email and the phone are verified, and says so', async () => {
    await reach()
    fillUser()
    fireEvent.click(screen.getByRole('button', { name: 'Create Account' }))
    expect(await screen.findByTestId('err-email')).toHaveTextContent('Please verify your email address.')
    expect(screen.getByTestId('err-phone')).toHaveTextContent('Please verify your phone number.')
    expect(api.signupJoin).not.toHaveBeenCalled()
  })

  it('verify both, then the proofs travel with the sign-up request', async () => {
    await reach()
    fillUser()
    fireEvent.click(screen.getByRole('button', { name: 'Create Account' }))                     // first try without proof: both problems are shown...
    expect(await screen.findByTestId('err-email')).toBeInTheDocument()
    await verifyChannel('email', 'email address', 'Email')
    await verifyChannel('phone', 'phone number', 'Phone')
    expect(screen.queryByTestId('err-email')).not.toBeInTheDocument()                           // ...and they disappear as soon as each one is verified
    expect(screen.queryByTestId('err-phone')).not.toBeInTheDocument()
    expect(screen.queryByText('Please correct the highlighted fields.')).not.toBeInTheDocument()
    expect(api.contactSend).toHaveBeenCalledWith('email', 'new@alpha.example')
    expect(api.contactSend).toHaveBeenCalledWith('phone', '0412 345 678')
    fireEvent.click(screen.getByRole('button', { name: 'Create Account' }))
    await waitFor(() => expect(api.signupJoin).toHaveBeenCalledWith({ signup_token: 'tok123', user: expect.objectContaining({ email: 'new@alpha.example', phone: '0412 345 678', email_token: 'proof-email', phone_token: 'proof-phone' }) }))
  })

  it('a wrong code is explained and does not verify', async () => {
    await reach()
    fillUser()
    fireEvent.click(within(screen.getByTestId('verify-email')).getByRole('button', { name: /Send code/ }))
    fireEvent.change(await screen.findByLabelText('Email verification code'), { target: { value: '999999' } })
    fireEvent.click(within(screen.getByTestId('verify-email')).getByRole('button', { name: 'Verify' }))
    expect(await screen.findByTestId('verify-err-email')).toHaveTextContent('That code is not correct.')
    expect(within(screen.getByTestId('verify-email')).queryByText(/✓/)).not.toBeInTheDocument()
  })

  it('changing the address after verifying it starts verification again', async () => {
    await reach()
    fillUser()
    await verifyChannel('email', 'email address', 'Email')
    type('Email Address', 'different@alpha.example')
    expect(await within(screen.getByTestId('verify-email')).findByRole('button', { name: /Send code/ })).toBeInTheDocument()
    expect(within(screen.getByTestId('verify-email')).queryByText(/✓/)).not.toBeInTheDocument()
  })

  it('Send code stays disabled until the address is valid', async () => {
    await reach()
    type('First Name', 'N'); type('Email Address', 'bad')
    expect(within(screen.getByTestId('verify-email')).getByRole('button', { name: /Send code/ })).toBeDisabled()
    type('Email Address', 'good@alpha.example')
    expect(within(screen.getByTestId('verify-email')).getByRole('button', { name: /Send code/ })).toBeEnabled()
  })

  it('a number we cannot text is not blocked: it is saved as unverified', async () => {
    api.contactSend.mockImplementation((ch) => ch === 'phone' ? Promise.resolve({ data: { ok: true, required: false, reason: 'sms_unavailable' } }) : Promise.resolve({ data: { ok: true, required: true, sent_to: 'x' } }))
    await reach()
    fillUser('new@alpha.example', 'Str0ng!Passw0rd#2026', undefined, '+44 7911 123456')
    await verifyChannel('email', 'email address', 'Email')
    fireEvent.click(within(screen.getByTestId('verify-phone')).getByRole('button', { name: /Send code/ }))
    expect(await within(screen.getByTestId('verify-phone')).findByText(/can't be verified/)).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: 'Create Account' }))
    await waitFor(() => expect(api.signupJoin).toHaveBeenCalled())
  })

  it('when verification is switched off nothing extra is shown', async () => {
    api.contactConfig.mockImplementation(() => Promise.resolve({ data: { mode: 'off', email_required: false, phone_required: false } }))
    render(<SignupFlow tenant={{ tenant: 'alpha', found: true, name: 'Alpha Pty Ltd' }} />)
    fireEvent.change(await screen.findByLabelText('Organisation access code'), { target: { value: 'ALP-7F4K-92LM' } })
    fireEvent.click(screen.getByRole('button', { name: 'Verify & Continue' }))
    await screen.findByText(/Joining/)
    await waitFor(() => expect(screen.queryByTestId('verify-email')).not.toBeInTheDocument())
  })
})

describe('InviteManager', () => {
  const list = (over = {}) => ({ summary: { licensed_users: 3, active_users: 1, pending_invitations: 0, available_slots: 2, codes: { unused: 0, partly_used: 0, used: 0, expired: 0, revoked: 0 } }, items: [], ...over })
  beforeEach(() => {
    api.listInvites.mockImplementation(() => Promise.resolve({ data: list() }))
    api.getTenantProfile.mockImplementation(() => Promise.resolve({ data: { slug: 'alpha', tenant_url: 'https://alpha.acc.test', discoverable: true } }))
  })

  it('shows licence usage and the organisation address', async () => {
    render(<InviteManager />)
    expect(await screen.findByTestId('invite-manager')).toBeInTheDocument()
    expect(screen.getByText('Licensed users')).toBeInTheDocument()
    expect(screen.getByText('https://alpha.acc.test')).toBeInTheDocument()
  })

  it('shows newly generated codes once, with the not-shown-again warning', async () => {
    api.createInvites.mockImplementation(() => Promise.resolve({ data: { note: 'Copy these now. For security the full codes are not stored and cannot be shown again.', tenant_url: 'https://alpha.acc.test',
      codes: [{ id: 1, code: 'ALP-7F4K-92LM', role: 'bookkeeper', expires_at: '2026-10-08T00:00:00' }], summary: list().summary } }))
    render(<InviteManager />)
    await screen.findByTestId('invite-manager')
    fireEvent.click(screen.getByRole('button', { name: 'Generate' }))
    const box = await screen.findByTestId('fresh-codes')
    expect(box).toHaveTextContent('ALP-7F4K-92LM')
    expect(box).toHaveTextContent('cannot be shown again')
    fireEvent.click(screen.getByRole('button', { name: 'I have copied them' }))
    expect(screen.queryByTestId('fresh-codes')).not.toBeInTheDocument()
    expect(api.createInvites).toHaveBeenCalledWith({ role: 'bookkeeper', count: 1, expires_in_days: 7, max_uses: 1, label: null })
  })

  it('lists codes by hint only and revokes an unused one', async () => {
    api.listInvites.mockImplementation(() => Promise.resolve({ data: list({ items: [{ id: 5, code_hint: 'ALP-V7DS-....', role: 'bookkeeper', label: 'Sam', status: 'unused', uses: 0, max_uses: 1, expires_at: '2026-10-08T00:00:00' },
      { id: 6, code_hint: 'ALP-K2MN-....', role: 'readonly', label: '', status: 'used', uses: 1, max_uses: 1, expires_at: '2026-10-08T00:00:00' }] }) }))
    window.confirm = vi.fn(() => true)
    render(<InviteManager />)
    expect(await screen.findByText('ALP-V7DS-....')).toBeInTheDocument()
    expect(screen.getAllByRole('button', { name: 'Revoke' })).toHaveLength(1)               // a used code cannot be revoked
    fireEvent.click(screen.getByRole('button', { name: 'Revoke' }))
    await waitFor(() => expect(api.revokeInvite).toHaveBeenCalledWith(5))
  })

  it('disables Generate and explains when no licensed slots are left', async () => {
    api.listInvites.mockImplementation(() => Promise.resolve({ data: list({ summary: { ...list().summary, pending_invitations: 2, available_slots: 0 } }) }))
    render(<InviteManager />)
    await screen.findByTestId('invite-manager')
    expect(screen.getByRole('button', { name: 'Generate' })).toBeDisabled()
    expect(screen.getByText(/No licensed slots left/)).toBeInTheDocument()
  })

  it('shows the Organisation Admin dashboard: organisation, primary contact, users and code counts', async () => {
    api.listInvites.mockImplementation(() => Promise.resolve({ data: list({ summary: { ...list().summary, codes: { unused: 1, partly_used: 1, used: 3, expired: 2, revoked: 4 } },
      overview: { organisation: { id: 7, name: 'Alpha Pty Ltd', admin_name: 'Olive Owner', admin_email: 'olive@alpha.example', admin_phone: '+61412345678', admin_phone_display: '0412 345 678' } } }) }))
    render(<InviteManager />)
    const ov = await screen.findByTestId('admin-overview')
    for (const t of ['Alpha Pty Ltd', '7', 'Olive Owner', 'olive@alpha.example', '0412 345 678']) expect(ov).toHaveTextContent(t)
    expect(screen.getByTestId('code-counts')).toHaveTextContent('2 active · 3 used · 2 expired · 4 revoked')
  })

  it('can only issue Organisation User roles - never an Organisation Admin', async () => {
    render(<InviteManager />)
    await screen.findByTestId('invite-manager')
    const options = Array.from(screen.getByLabelText('Role').querySelectorAll('option')).map(o => o.value)
    expect(options).toEqual(['bookkeeper', 'accountant', 'payroll', 'payroll_admin', 'employee', 'readonly'])      // Payroll Manager / Administrator / Employee added in Phase 2
  })

  it('renders nothing for people who are not the Organisation Admin', async () => {
    api.listInvites.mockImplementation(() => Promise.reject({ response: { status: 403 } }))
    const { container } = render(<InviteManager />)
    await waitFor(() => expect(api.listInvites).toHaveBeenCalled())
    expect(container).toBeEmptyDOMElement()
  })
})
