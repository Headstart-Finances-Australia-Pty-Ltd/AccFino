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

import ExpensesPage from '../pages/ExpensesPage.jsx'

describe('ExpensesPage', () => {
  it('renders the heading, status filters and an empty state', async () => {
    render(<ExpensesPage />)
    expect(screen.getByRole('heading', { name: /Expenses/i })).toBeInTheDocument()
    expect(screen.getByText(/My claims only/i)).toBeInTheDocument()
    await waitFor(() => expect(screen.getByText(/No claims yet/i)).toBeInTheDocument())
    expect(screen.getByRole('button', { name: /New claim/i })).toBeInTheDocument()
  })

  it('opens the new-claim form with a receipt item by default', async () => {
    render(<ExpensesPage />)
    await waitFor(() => screen.getByRole('button', { name: /New claim/i }))
    fireEvent.click(screen.getByRole('button', { name: /New claim/i }))
    expect(screen.getByText(/New expense claim/i)).toBeInTheDocument()
    expect(screen.getByText(/ATO requires a receipt/i)).toBeInTheDocument()
  })
})
