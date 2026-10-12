import React from 'react'
import { describe, it, expect, vi } from 'vitest'
import { render, screen, waitFor, fireEvent } from '@testing-library/react'
vi.mock('../../../core/lib/adminApi.js', async () => {
  const { booksApiMockFactory } = await import('../../../core/test/testUtils.js')
  return booksApiMockFactory()
})
vi.mock('../lib/booksApi.js', async () => {
  const { booksApiMockFactory } = await import('../../../core/test/testUtils.js')
  return booksApiMockFactory()
})
vi.mock('../../billing/lib/orgBillingApi.js', async () => {
  const { booksApiMockFactory } = await import('../../../core/test/testUtils.js')
  return booksApiMockFactory()
})
vi.mock('../../open_banking/lib/feedApi.js', async () => {
  const { booksApiMockFactory } = await import('../../../core/test/testUtils.js')
  return booksApiMockFactory()
})

import BankingPage from '../pages/BankingPage.jsx'
import * as api from '../lib/booksApi.js'

describe('BankingPage', () => {
  it('renders the heading and an empty state when there are no bank accounts yet', async () => {
    render(<BankingPage />)
    expect(screen.getByRole('heading', { name: /Banking/i })).toBeInTheDocument()
    await waitFor(() => expect(screen.getByText(/No bank accounts yet/i)).toBeInTheDocument())
    expect(screen.getByRole('button', { name: /New bank account/i })).toBeInTheDocument()
  })

  it('shows the accounts list, and lets you switch to the coding-rules tab once an account exists', async () => {
    api.bankAccounts.mockResolvedValueOnce({ data: { items: [
      { id: 1, code: '090', name: 'Everyday Account', ledger_balance: '1000.00', unreconciled: 2, last_statement_date: null },
    ] } })
    render(<BankingPage />)
    await waitFor(() => expect(screen.getByText(/090 Everyday Account/)).toBeInTheDocument())
    fireEvent.click(screen.getByRole('button', { name: /Coding rules/i }))
    await waitFor(() => expect(api.listRules).toHaveBeenCalled())
  })

  it('creates a new bank account through the modal', async () => {
    render(<BankingPage />)
    await waitFor(() => screen.getByRole('button', { name: /New bank account/i }))
    fireEvent.click(screen.getByRole('button', { name: /New bank account/i }))
    const [codeInput, nameInput] = screen.getAllByRole('textbox')
    fireEvent.change(codeInput, { target: { value: '091' } })
    fireEvent.change(nameInput, { target: { value: 'Savings' } })
    fireEvent.click(screen.getByRole('button', { name: 'Create' }))
    await waitFor(() => expect(api.createBankAccount).toHaveBeenCalledWith(expect.objectContaining({ code: '091', name: 'Savings', type: 'bank' })))
  })
})
