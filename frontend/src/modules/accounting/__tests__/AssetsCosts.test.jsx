import React from 'react'
import { describe, it, expect, vi } from 'vitest'
import { render, screen, within, fireEvent } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'

vi.mock('../../../core/hooks/useAuth.jsx', () => ({ useAuth: () => ({ user: { id: 1 } }) }))
let visible = () => true
vi.mock('../../../core/hooks/useModuleVisibility.jsx', () => ({ useModuleVisibility: () => ({ isModuleVisible: id => visible(id) }) }))
vi.mock('../pages/AccountingDashboard.jsx', () => ({ default: () => <div>stub</div> }))
vi.mock('../pages/SalesPage.jsx', () => ({ default: () => <div>stub</div> }))
vi.mock('../pages/PurchasesPage.jsx', () => ({ default: () => <div>stub</div> }))
vi.mock('../pages/SalesPurchasesPage.jsx', () => ({ default: () => <div>stub</div> }))
vi.mock('../pages/FinancialReports.jsx', () => ({ default: () => <div>stub</div> }))
vi.mock('../pages/ledger/LedgerPage.jsx', () => ({ default: () => <div>stub</div> }))
vi.mock('../pages/ExpensesPage.jsx', () => ({ default: () => <div>EXPENSES PAGE</div> }))
vi.mock('../pages/InventoryPage.jsx', () => ({ default: () => <div>INVENTORY PAGE</div> }))
vi.mock('../pages/FixedAssetsPage.jsx', () => ({ default: () => <div>FIXED PAGE</div> }))
vi.mock('../../reconciliation/public.js', () => ({ ReconciliationWrapper: () => <div>recon</div> }))

const mount = async (url = '/accounting') => { const { default: P } = await import('../pages/AccountingPage.jsx'); render(<MemoryRouter initialEntries={[url]}><P /></MemoryRouter>) }
const tops = () => screen.getAllByRole('button').map(b => b.textContent).filter(t => /Dashboard|Ledger|Reconciliation|Assets and Costs|Sales|Purchases|Reports|Expenses|Inventory|Fixed/.test(t))

describe('Accounting > Assets and Costs', () => {
  it('is a top-level tab right after Reconciliation; Expenses, Inventory, Fixed Assets are no longer top-level', async () => {
    visible = () => true; await mount()
    const bar = tops(); expect(bar.findIndex(t => /Assets and Costs/.test(t))).toBe(bar.findIndex(t => /Reconciliation/.test(t)) + 1)
    expect(bar.filter(t => /Expenses|Inventory|Fixed/.test(t))).toEqual([])
  })
  it('holds Expenses | Inventory | Fixed Assets as sub-tabs', async () => {
    visible = () => true; await mount('/accounting?tab=assets-costs')
    expect(within(screen.getByRole('tablist', { name: 'Assets and Costs pages' })).getAllByRole('tab').map(t => t.textContent)).toEqual(['🧾 Expenses', '📦 Inventory', '🏗 Fixed Assets'])
    expect(screen.getByText('EXPENSES PAGE')).toBeInTheDocument()
    fireEvent.click(screen.getByRole('tab', { name: /Fixed Assets/ })); expect(screen.getByText('FIXED PAGE')).toBeInTheDocument()
  })
  it('old links (?tab=inventory) open the Inventory sub-tab', async () => {
    visible = () => true; await mount('/accounting?tab=inventory')
    expect(screen.getByText('INVENTORY PAGE')).toBeInTheDocument(); expect(screen.getByRole('tab', { name: /Inventory/ })).toHaveAttribute('aria-selected', 'true')
  })
  it('hides a sub-tab whose module is off, and the whole tab when all three are off', async () => {
    visible = id => id !== 'inventory-trading'; await mount('/accounting?tab=assets-costs')
    expect(within(screen.getByRole('tablist', { name: 'Assets and Costs pages' })).getAllByRole('tab').map(t => t.textContent)).toEqual(['🧾 Expenses', '🏗 Fixed Assets'])
  })
})
