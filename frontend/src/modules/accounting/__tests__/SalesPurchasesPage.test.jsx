import React from 'react'
import { describe, it, expect, vi } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
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

import SalesPurchasesPage from '../pages/SalesPurchasesPage.jsx'

describe('SalesPurchasesPage - sales side', () => {
  it('renders the Sales heading and every expected tab', async () => {
    render(<SalesPurchasesPage side="sales" />)
    expect(screen.getByRole('heading', { name: 'Sales' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /Customers/ })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /Invoices/ })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /Quotes/ })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /Credit Notes/ })).toBeInTheDocument()
    // The default tab (Invoices) starts empty until the mocked API resolves
    await waitFor(() => expect(screen.getByText(/No invoices yet/i)).toBeInTheDocument())
  })

  it('offers a "New Invoice" action', async () => {
    render(<SalesPurchasesPage side="sales" />)
    await waitFor(() => expect(screen.getByRole('button', { name: /New Invoice/i })).toBeInTheDocument())
  })
})

describe('SalesPurchasesPage - purchases side', () => {
  it('renders the Purchases heading with supplier-flavoured labels', async () => {
    render(<SalesPurchasesPage side="purchases" />)
    expect(screen.getByRole('heading', { name: 'Purchases' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /Suppliers/ })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /Bills/ })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /Purchase Order/ })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /Supplier Credit/ })).toBeInTheDocument()
    await waitFor(() => expect(screen.getByText(/No bills yet/i)).toBeInTheDocument())
  })
})
