import React from 'react'
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, fireEvent, waitFor } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'

let loginResult = { ok: false, error: '' }
vi.mock('../../../hooks/useAuth.jsx', () => ({ useAuth: () => ({ login: vi.fn(() => Promise.resolve(loginResult)), loading: false }) }))
vi.mock('react-hot-toast', () => ({ default: Object.assign(vi.fn(), { success: vi.fn(), error: vi.fn() }) }))
vi.mock('../../../components/security/PasskeySignIn.jsx', () => ({ default: () => null }))
vi.mock('../../../components/signup/SignupFlow.jsx', () => ({ default: () => <div data-testid="signup-flow" /> }))
vi.mock('../../../components/ui/TopBar.jsx', () => ({ default: () => null }))
vi.mock('../../../lib/api.js', () => ({ register: vi.fn(), forgotPassword: vi.fn(), getPricingPlans: vi.fn(() => Promise.resolve({ data: {} })), createCheckout: vi.fn() }))
vi.mock('../../../lib/booksApi.js', () => ({ tenantCurrent: vi.fn(() => Promise.resolve({ data: {} })) }))
import LoginPage from '../../LoginPage.jsx'

const submit = async (email = 'nobody@example.com') => {
  render(<MemoryRouter><LoginPage /></MemoryRouter>)
  const inputs = document.querySelectorAll('input')
  fireEvent.change(inputs[0], { target: { value: email } })
  fireEvent.change(inputs[1], { target: { value: 'whatever1' } })
  fireEvent.submit(document.querySelector('form'))
}

beforeEach(() => vi.clearAllMocks())

describe('login: no account exists', () => {
  it('shows a Sign up button just below the message, and it opens sign-up', async () => {
    loginResult = { ok: false, error: 'No account exists for this email / user id. Check it, or create an account.' }
    await submit()
    const alert = await screen.findByRole('alert')
    const prompt = await screen.findByTestId('login-signup-suggestion')
    expect(alert.compareDocumentPosition(prompt) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy()      // directly after the error
    fireEvent.click(screen.getByTestId('login-signup-btn'))
    expect(await screen.findByTestId('signup-flow')).toBeInTheDocument()
    expect(screen.queryByTestId('login-signup-suggestion')).toBeNull()
  })

  it('a wrong password is only an error - no sign-up button', async () => {
    loginResult = { ok: false, error: 'The email / user id and password do not match. Check your password and try again.' }
    await submit('known@example.com')
    await screen.findByRole('alert')
    expect(screen.queryByTestId('login-signup-btn')).toBeNull()
  })
})
