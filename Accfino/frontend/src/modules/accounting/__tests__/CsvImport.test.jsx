import React from 'react'
import { describe, it, expect, vi } from 'vitest'
import { render, screen, waitFor, fireEvent, within } from '@testing-library/react'

vi.mock('../../../core/lib/adminApi.js', async () => {
  const { booksApiMockFactory } = await import('../../../core/test/testUtils.js')
  const base = await booksApiMockFactory()
  return {
    ...base,
    bulkImportStatus: vi.fn(() => Promise.resolve({ data: { enabled: true } })),
    adminGetBulkImport: vi.fn(() => Promise.resolve({ data: { enabled: true } })),
    adminSetBulkImport: vi.fn(() => Promise.resolve({ data: { enabled: false } })),
    importCatalogue: vi.fn(() => Promise.resolve({ data: { items: [{ entity: 'invoices', title: 'Sales invoices', description: 'Tax invoices.', notes: ['One row per line.'],
      options: [{ name: 'mode', label: 'Import as', choices: [['post', 'Approved'], ['draft', 'Drafts']], default: 'post' }],
      columns: [{ name: 'number', required: false, help: 'Doc number', example: 'INV-0001' }] }] } })),
    importCsv: vi.fn((entity, file, o) => Promise.resolve({ data: o.dryRun
      ? { entity, dry_run: true, count: 2, valid: 2, invalid: 0, saved: 0, total: '220.00', error: null, warnings: [], items: [
          { row: 2, label: 'INV-1 · Acme', detail: 'posted', amount: '110.00', errors: [], warnings: [] }, { row: 3, label: 'INV-2 · Acme', detail: 'posted', amount: '110.00', errors: [], warnings: [] }] }
      : { entity, dry_run: false, count: 2, valid: 2, invalid: 0, saved: 2, total: '220.00', error: null, warnings: [], items: [] } })),
  }
})
vi.mock('../lib/booksApi.js', async () => {
  const { booksApiMockFactory } = await import('../../../core/test/testUtils.js')
  const base = await booksApiMockFactory()
  return {
    ...base,
    bulkImportStatus: vi.fn(() => Promise.resolve({ data: { enabled: true } })),
    adminGetBulkImport: vi.fn(() => Promise.resolve({ data: { enabled: true } })),
    adminSetBulkImport: vi.fn(() => Promise.resolve({ data: { enabled: false } })),
    importCatalogue: vi.fn(() => Promise.resolve({ data: { items: [{ entity: 'invoices', title: 'Sales invoices', description: 'Tax invoices.', notes: ['One row per line.'],
      options: [{ name: 'mode', label: 'Import as', choices: [['post', 'Approved'], ['draft', 'Drafts']], default: 'post' }],
      columns: [{ name: 'number', required: false, help: 'Doc number', example: 'INV-0001' }] }] } })),
    importCsv: vi.fn((entity, file, o) => Promise.resolve({ data: o.dryRun
      ? { entity, dry_run: true, count: 2, valid: 2, invalid: 0, saved: 0, total: '220.00', error: null, warnings: [], items: [
          { row: 2, label: 'INV-1 · Acme', detail: 'posted', amount: '110.00', errors: [], warnings: [] }, { row: 3, label: 'INV-2 · Acme', detail: 'posted', amount: '110.00', errors: [], warnings: [] }] }
      : { entity, dry_run: false, count: 2, valid: 2, invalid: 0, saved: 2, total: '220.00', error: null, warnings: [], items: [] } })),
  }
})
vi.mock('../../billing/lib/orgBillingApi.js', async () => {
  const { booksApiMockFactory } = await import('../../../core/test/testUtils.js')
  const base = await booksApiMockFactory()
  return {
    ...base,
    bulkImportStatus: vi.fn(() => Promise.resolve({ data: { enabled: true } })),
    adminGetBulkImport: vi.fn(() => Promise.resolve({ data: { enabled: true } })),
    adminSetBulkImport: vi.fn(() => Promise.resolve({ data: { enabled: false } })),
    importCatalogue: vi.fn(() => Promise.resolve({ data: { items: [{ entity: 'invoices', title: 'Sales invoices', description: 'Tax invoices.', notes: ['One row per line.'],
      options: [{ name: 'mode', label: 'Import as', choices: [['post', 'Approved'], ['draft', 'Drafts']], default: 'post' }],
      columns: [{ name: 'number', required: false, help: 'Doc number', example: 'INV-0001' }] }] } })),
    importCsv: vi.fn((entity, file, o) => Promise.resolve({ data: o.dryRun
      ? { entity, dry_run: true, count: 2, valid: 2, invalid: 0, saved: 0, total: '220.00', error: null, warnings: [], items: [
          { row: 2, label: 'INV-1 · Acme', detail: 'posted', amount: '110.00', errors: [], warnings: [] }, { row: 3, label: 'INV-2 · Acme', detail: 'posted', amount: '110.00', errors: [], warnings: [] }] }
      : { entity, dry_run: false, count: 2, valid: 2, invalid: 0, saved: 2, total: '220.00', error: null, warnings: [], items: [] } })),
  }
})
vi.mock('../../open_banking/lib/feedApi.js', async () => {
  const { booksApiMockFactory } = await import('../../../core/test/testUtils.js')
  const base = await booksApiMockFactory()
  return {
    ...base,
    bulkImportStatus: vi.fn(() => Promise.resolve({ data: { enabled: true } })),
    adminGetBulkImport: vi.fn(() => Promise.resolve({ data: { enabled: true } })),
    adminSetBulkImport: vi.fn(() => Promise.resolve({ data: { enabled: false } })),
    importCatalogue: vi.fn(() => Promise.resolve({ data: { items: [{ entity: 'invoices', title: 'Sales invoices', description: 'Tax invoices.', notes: ['One row per line.'],
      options: [{ name: 'mode', label: 'Import as', choices: [['post', 'Approved'], ['draft', 'Drafts']], default: 'post' }],
      columns: [{ name: 'number', required: false, help: 'Doc number', example: 'INV-0001' }] }] } })),
    importCsv: vi.fn((entity, file, o) => Promise.resolve({ data: o.dryRun
      ? { entity, dry_run: true, count: 2, valid: 2, invalid: 0, saved: 0, total: '220.00', error: null, warnings: [], items: [
          { row: 2, label: 'INV-1 · Acme', detail: 'posted', amount: '110.00', errors: [], warnings: [] }, { row: 3, label: 'INV-2 · Acme', detail: 'posted', amount: '110.00', errors: [], warnings: [] }] }
      : { entity, dry_run: false, count: 2, valid: 2, invalid: 0, saved: 2, total: '220.00', error: null, warnings: [], items: [] } })),
  }
})

import * as api__0 from '../../../core/lib/adminApi.js'
import * as api__1 from '../lib/booksApi.js'
import { CsvImportModal, CsvImportButton } from '../components/CsvImportModal.jsx'
import SalesPurchasesPage from '../pages/SalesPurchasesPage.jsx'
import InventoryPage from '../pages/InventoryPage.jsx'
import FixedAssetsPage from '../pages/FixedAssetsPage.jsx'
import ExpensesPage from '../pages/ExpensesPage.jsx'

describe('CsvImportModal', () => {
  it('checks first, then imports only after a clean check', async () => {
    const onDone = vi.fn()
    render(<CsvImportModal entity="invoices" onClose={() => {}} onDone={onDone} />)
    await waitFor(() => expect(screen.getByText('Tax invoices.')).toBeInTheDocument())
    const importBtn = screen.getByRole('button', { name: /^Import$/ })
    expect(importBtn).toBeDisabled()                                           // nothing to import before a file is checked
    const file = new File(['number,contact\nINV-1,Acme'], 'inv.csv', { type: 'text/csv' })
    fireEvent.change(screen.getByLabelText('CSV file'), { target: { files: [file] } })
    fireEvent.click(screen.getByRole('button', { name: 'Check file' }))
    await waitFor(() => expect(screen.getByTestId('csv-import-result')).toBeInTheDocument())
    expect(api__1.importCsv).toHaveBeenLastCalledWith('invoices', file, { dryRun: true, mode: 'post', amountsAre: undefined })
    expect(screen.getByText(/all 2 record\(s\) are valid/)).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: /Import 2 record/ }))
    await waitFor(() => expect(onDone).toHaveBeenCalled())
    expect(api__1.importCsv).toHaveBeenLastCalledWith('invoices', file, { dryRun: false, mode: 'post', amountsAre: undefined })
  })

  it('shows a problem report and keeps Import disabled when the check fails', async () => {
    api__1.importCsv.mockImplementationOnce(() => Promise.resolve({ data: { entity: 'invoices', dry_run: true, count: 1, valid: 0, invalid: 1, saved: 0, total: '0.00',
      error: '1 of 1 record(s) have problems; nothing was imported. Fix the file and try again.', warnings: [], items: [{ row: 2, label: 'INV-1', detail: '', amount: null, errors: ['Customer is required'], warnings: [] }] } }))
    render(<CsvImportModal entity="invoices" onClose={() => {}} />)
    await waitFor(() => expect(screen.getByText('Tax invoices.')).toBeInTheDocument())
    fireEvent.change(screen.getByLabelText('CSV file'), { target: { files: [new File(['x'], 'bad.csv')] } })
    fireEvent.click(screen.getByRole('button', { name: 'Check file' }))
    await waitFor(() => expect(screen.getByText('Customer is required')).toBeInTheDocument())
    expect(screen.getByRole('button', { name: /^Import$/ })).toBeDisabled()
  })

  it('CsvImportButton opens the window', async () => {
    render(<CsvImportButton entity="invoices" />)
    fireEvent.click(screen.getByTestId('import-invoices'))
    await waitFor(() => expect(screen.getByText(/Import Sales invoices from CSV/)).toBeInTheDocument())
  })
})

describe('import buttons are on every list page', () => {
  it('Sales: customers, invoices, quotes, credit notes and receipts', async () => {
    render(<SalesPurchasesPage side="sales" />)
    await waitFor(() => expect(screen.getByTestId('import-invoices')).toBeInTheDocument())
    fireEvent.click(screen.getByRole('button', { name: /Quotes/ }));        await waitFor(() => expect(screen.getByTestId('import-quotes')).toBeInTheDocument())
    fireEvent.click(screen.getByRole('button', { name: /Credit Notes/ }));  await waitFor(() => expect(screen.getByTestId('import-credit_notes')).toBeInTheDocument())
    fireEvent.click(screen.getByRole('button', { name: /Receipts/ }));      await waitFor(() => expect(screen.getByTestId('import-receipts')).toBeInTheDocument())
    fireEvent.click(screen.getByRole('button', { name: /Customers/ }));     await waitFor(() => expect(screen.getByTestId('import-customers')).toBeInTheDocument())
  })
  it('Purchases: suppliers, bills, purchase orders, supplier credits and payments', async () => {
    render(<SalesPurchasesPage side="purchases" />)
    await waitFor(() => expect(screen.getByTestId('import-bills')).toBeInTheDocument())
    fireEvent.click(screen.getByRole('button', { name: /Purchase Order/ })); await waitFor(() => expect(screen.getByTestId('import-purchase_orders')).toBeInTheDocument())
    fireEvent.click(screen.getByRole('button', { name: /Supplier Credit/ })); await waitFor(() => expect(screen.getByTestId('import-supplier_credits')).toBeInTheDocument())
    fireEvent.click(screen.getByRole('button', { name: /Payments/ }));        await waitFor(() => expect(screen.getByTestId('import-supplier_payments')).toBeInTheDocument())
    fireEvent.click(screen.getByRole('button', { name: /Suppliers/ }));       await waitFor(() => expect(screen.getByTestId('import-suppliers')).toBeInTheDocument())
  })
  it('Expenses, Inventory and Fixed Assets', async () => {
    const { unmount } = render(<ExpensesPage />); await waitFor(() => expect(screen.getByTestId('import-expense_claims')).toBeInTheDocument()); unmount()
    const r2 = render(<InventoryPage />); await waitFor(() => { expect(screen.getByTestId('import-inventory_items')).toBeInTheDocument(); expect(screen.getByTestId('import-stock_movements')).toBeInTheDocument() }); r2.unmount()
    render(<FixedAssetsPage />); await waitFor(() => expect(screen.getByTestId('import-fixed_assets')).toBeInTheDocument())
  })
})

describe('bulk import platform switch', () => {
  it('Import buttons disappear when an administrator switches bulk import off', async () => {
    api__1.bulkImportStatus.mockImplementation(() => Promise.resolve({ data: { enabled: false } }))
    render(<CsvImportButton entity="invoices" />)
    window.dispatchEvent(new Event('accfino:bulk-import-changed'))
    await waitFor(() => expect(screen.queryByTestId('import-invoices')).not.toBeInTheDocument())
    api__1.bulkImportStatus.mockImplementation(() => Promise.resolve({ data: { enabled: true } }))
    window.dispatchEvent(new Event('accfino:bulk-import-changed'))
    await waitFor(() => expect(screen.getByTestId('import-invoices')).toBeInTheDocument())
  })

  it('Admin > Modules Management has a Bulk data import checkbox that saves straight away', async () => {
    api__0.adminGetBulkImport.mockImplementation(() => Promise.resolve({ data: { enabled: true } }))
    const { default: ModulesAdminPage } = await import('../../../core/pages/ModulesAdminPage.jsx')
    render(<ModulesAdminPage />)
    const box = await screen.findByLabelText('Bulk data import')
    await waitFor(() => expect(box).toBeChecked())
    fireEvent.click(box)
    await waitFor(() => expect(api__0.adminSetBulkImport).toHaveBeenCalledWith(false))
    await waitFor(() => expect(screen.getByLabelText('Bulk data import')).not.toBeChecked())
    expect(within(screen.getByLabelText('Bulk data import').closest('label')).getByText('Inactive')).toBeInTheDocument()      // scoped: other platform switches also show an Inactive badge
  })
})
