import React from 'react'
import { describe, it, expect, vi } from 'vitest'
import { render, screen, waitFor, fireEvent } from '@testing-library/react'
vi.mock('../../../lib/booksApi.js', async () => {
  const { booksApiMockFactory } = await import('./testUtils.js')
  return booksApiMockFactory()
})

import BooksReportsPage from '../BooksReportsPage.jsx'
import * as api from '../../../lib/booksApi.js'

describe('BooksReportsPage', () => {
  it('renders every report tab and a zero-row Aged Receivables table by default', async () => {
    render(<BooksReportsPage />)
    expect(screen.getByRole('heading', { name: /Financial Reports/i })).toBeInTheDocument()
    for (const label of ['Aged Receivables', 'Aged Payables', 'GST / BAS Summary', 'Cash Flow', 'Sales by Customer', 'Purchases by Supplier', 'Sub-ledger Control Check']) {
      expect(screen.getByRole('button', { name: label })).toBeInTheDocument()
    }
    await waitFor(() => expect(api.salesReport).toHaveBeenCalledWith('aged-receivables', expect.objectContaining({ as_at: expect.any(String) })))
  })

  it('switches to the GST summary report and calls the ledger report endpoint', async () => {
    render(<BooksReportsPage />)
    fireEvent.click(screen.getByRole('button', { name: 'GST / BAS Summary' }))
    await waitFor(() => expect(api.ledgerReport).toHaveBeenCalledWith('gst-summary', expect.objectContaining({ basis: 'accrual' })))
  })
})
