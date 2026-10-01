import React from 'react'
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, waitFor, fireEvent, within } from '@testing-library/react'
import { fmtAUD } from '../reportKit.jsx'
import FX from './fixtures/extraReports.json'   // real responses captured from the seeded demo organisation

const { state } = vi.hoisted(() => ({ state: { mode: 'full', cats: [{ id: 1, name: 'Department', options: [{ id: 2, name: 'Admin' }] }, { id: 7, name: 'Region', options: [] }] } }))          // 'full' | 'empty' | 'fail'
const BY = { 'gl-summary': 'gl', 'journal-report': 'journal', 'cash-summary': 'cashsum', 'account-summary': 'acctsum', 'cash-validation': 'validation', 'expense-claims': 'claims',
  'payg-summary': 'payg', 'profit-loss-by-tracking': 'plTracking', 'management-report': 'mgmt', 'inventory-items': 'invitems', 'budget-variance': 'budget' }

vi.mock('../../../lib/platformApi.js', () => ({ errMsg: e => e?.message || 'err', profitLoss: vi.fn(), balanceSheet: vi.fn(), trialBalance: vi.fn(), generalLedger: vi.fn(), accounts: () => Promise.resolve({ data: [{ id: 1, code: '090', name: 'Business Cheque Account' }] }), tracking: () => Promise.resolve({ data: state.cats }), journalSources: () => Promise.resolve({ data: { items: [{ source: 'manual', label: 'Manual journals', count: 3 }] } }) }))
vi.mock('../../../lib/api.js', () => ({ getMyPlan: () => Promise.resolve({ data: { plan_id: 'accounting_pro' } }) }))
vi.mock('../../../lib/booksApi.js', () => {
  const answer = data => state.mode === 'fail' ? Promise.reject(new Error('boom')) : Promise.resolve({ data: state.mode === 'empty' ? {} : data })
  return {
    errMsg: e => e?.message || 'err',
    salesReport: () => answer({}), purchasesReport: () => answer({}), listDocs: () => answer({}),
    ledgerReport: vi.fn(path => answer(FX[BY[path]])),
    ledgerReportMulti: vi.fn(() => answer(FX.glDetail)),
    bankAccounts: () => Promise.resolve({ data: FX.bankaccounts }),
    reconciliationReport: vi.fn(() => answer(FX.recon)),
    getBudget: () => Promise.resolve({ data: { scenarios: ['Budget', 'Forecast'] } }),
    generateBudget: vi.fn(() => Promise.resolve({ data: { lines: 12 } })),
  }
})
vi.mock('recharts', async () => {                       // jsdom has no layout, so charts render as inert placeholders
  const P = ({ children }) => <div data-chart>{children}</div>
  return { ResponsiveContainer: P, ComposedChart: P, Bar: () => null, Line: () => null, XAxis: () => null, YAxis: () => null, CartesianGrid: () => null, Tooltip: () => null, Legend: () => null }
})
import * as books from '../../../lib/booksApi.js'
import FinancialReports from '../FinancialReports.jsx'

const NEW = ['Budget Variance', 'Cash Summary', 'Management Report', 'Expense Claims', 'PAYG Summary', 'General Ledger Summary', 'Bank Reconciliation', 'Account Summary',
  'Cash Validation', 'Journal Report', 'Inventory Item Details']

async function open(label) {
  const btn = await screen.findByRole('button', { name: new RegExp(`^${label.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')}`) })
  await waitFor(() => expect(btn.style.cursor).toBe('pointer'))
  fireEvent.click(btn)
  await waitFor(() => expect(screen.getByRole('heading', { name: label })).toBeInTheDocument())
  await new Promise(r => setTimeout(r, 40))
}

describe('the eleven newly built reports', () => {
  beforeEach(() => { state.mode = 'full'; vi.clearAllMocks() })

  it('none are marked "Soon" any more', async () => {
    render(<FinancialReports userId={1} />)
    await screen.findByText('All Reports')
    expect(screen.queryByText('Soon')).toBeNull()
    expect(screen.getByText(/26 live · 0 coming soon/)).toBeInTheDocument()
  })

  it('every one renders real-shaped data without a display problem or error', async () => {
    render(<FinancialReports userId={1} />)
    for (const l of NEW) {
      await open(l)
      expect(screen.queryByText(/hit a display problem/i), `${l} crashed`).toBeNull()
      expect(screen.queryByText(/could not be loaded/i), `${l} errored`).toBeNull()
    }
  })

  it('shows the figures from the ledger, not placeholders', async () => {
    render(<FinancialReports userId={1} />)
    await open('Cash Summary'); expect(await screen.findByText(/Reconciles to the movement in bank account balances/i)).toBeInTheDocument()
    await open('General Ledger Summary'); expect(await screen.findByText(/Period debits equal credits/i)).toBeInTheDocument()
    await open('Journal Report'); expect(await screen.findByText(/Every journal balances/i)).toBeInTheDocument()
    await open('Inventory Item Details'); expect(await screen.findByText(/Item values add up to the Inventory account/i)).toBeInTheDocument()
    await open('PAYG Summary'); expect(await screen.findByText(/PAYG withheld less remitted equals the movement/i)).toBeInTheDocument()
    await open('Management Report'); expect(await screen.findByText(/Key ratios/)).toBeInTheDocument()
    await open('Bank Reconciliation'); expect(await screen.findByText(/statement balance, adjusted for timing items, equals the ledger balance/i)).toBeInTheDocument()
  })

  it('Cash Validation lists every finding group with its severity', async () => {
    render(<FinancialReports userId={1} />)
    await open('Cash Validation')
    for (const c of FX.validation.checks) expect(await screen.findByText(new RegExp(c.title.slice(0, 20).replace(/[()]/g, '.')))).toBeInTheDocument()
  })

  it('Budget Variance offers to create a budget when none exists, and calls the API', async () => {
    const none = { ...FX.budget, has_budget: false }
    const original = books.ledgerReport.getMockImplementation()          // restored below so this override cannot leak into later tests
    books.ledgerReport.mockImplementation(p => Promise.resolve({ data: p === 'budget-variance' ? none : {} }))
    const spy = vi.spyOn(window, 'confirm').mockReturnValue(true)
    render(<FinancialReports userId={1} />)
    await open('Budget Variance')
    fireEvent.click(await screen.findByRole('button', { name: /Create budget from last year/ }))
    await waitFor(() => expect(books.generateBudget).toHaveBeenCalledWith(expect.objectContaining({ uplift_pct: 8, scenario: 'Budget' })))
    spy.mockRestore()
    books.ledgerReport.mockImplementation(original)
  })

  it('Bank Reconciliation asks the API for the chosen account and statement balance', async () => {
    render(<FinancialReports userId={1} />)
    await open('Bank Reconciliation')
    await waitFor(() => expect(books.reconciliationReport).toHaveBeenCalled())
    fireEvent.change(screen.getByPlaceholderText('from last line'), { target: { value: '1234.50' } })
    fireEvent.click(screen.getByRole('button', { name: 'Run' }))
    await waitFor(() => expect(books.reconciliationReport).toHaveBeenLastCalledWith(expect.any(String), expect.objectContaining({ statement_balance: '1234.50' })))
  })

  it('shows friendly empty states (never a crash) when there is no data', async () => {
    state.mode = 'empty'
    render(<FinancialReports userId={1} />)
    for (const l of NEW) { await open(l); expect(screen.queryByText(/hit a display problem/i), `${l} crashed on empty`).toBeNull() }
  })

  it('shows an inline error with retry when the API fails', async () => {
    state.mode = 'fail'
    render(<FinancialReports userId={1} />)
    await open('Journal Report')
    expect(await screen.findByText(/could not be loaded/i)).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Try again' })).toBeInTheDocument()
  })
})

describe('changing a filter and pressing Run really re-queries with the new values (all range reports)', () => {
  beforeEach(() => { state.mode = 'full'; vi.clearAllMocks() })
  for (const [label, path] of [['Journal Report', 'journal-report'], ['Cash Summary', 'cash-summary'], ['General Ledger Summary', 'gl-summary'], ['Account Summary', 'account-summary']]) {
    it(`${label}: new From date is sent to the API`, async () => {
      const { container } = render(<FinancialReports userId={1} />)
      await open(label)
      const from = container.querySelector('input[type=date]'); fireEvent.change(from, { target: { value: '2026-08-01' } })
      books.ledgerReport.mockClear()
      fireEvent.click(screen.getByRole('button', { name: /^(Run|Apply|Refresh|Go|Update)/ }))
      await waitFor(() => expect(books.ledgerReport).toHaveBeenCalledWith(path, expect.objectContaining({ from: '2026-08-01' })))
    })
  }
})

describe('General Ledger (detailed)', () => {
  beforeEach(() => { state.mode = 'full'; vi.clearAllMocks() })
  it('renders each account with opening balance, running balance and closing balance from the ledger', async () => {
    render(<FinancialReports userId={1} />)
    await open('General Ledger (detailed)')
    const cheque = FX.glDetail.groups.find(g => g.label.startsWith('090'))
    expect(await screen.findByText(new RegExp(`090 · Business Cheque Account \\(${cheque.count}\\)`))).toBeInTheDocument()
    expect(screen.getAllByText('Opening balance').length).toBe(2); expect(screen.getAllByText('Closing balance').length).toBe(2)
    expect(screen.getAllByText(/\$52,429\.42/).length).toBeGreaterThan(0)        // real opening balance of the cheque account
    expect(screen.getAllByText(/\$77,771\.04/).length).toBeGreaterThan(0)        // real closing balance
    expect(screen.getByText(new RegExp(`${FX.glDetail.line_count} lines`))).toBeInTheDocument()
  })
  it('sends every filter to the API (grouping, party, source, search, amounts, tracking, consolidation)', async () => {
    render(<FinancialReports userId={1} />)
    await open('General Ledger (detailed)')
    fireEvent.change(screen.getByLabelText('Group by'), { target: { value: 'party' } })
    fireEvent.change(screen.getByLabelText('Party'), { target: { value: 'AGL' } })
    fireEvent.change(screen.getByLabelText('Source'), { target: { value: 'manual' } })
    fireEvent.change(screen.getByLabelText('Search'), { target: { value: 'power' } })
    fireEvent.change(screen.getByLabelText('Min'), { target: { value: '100' } })
    fireEvent.change(screen.getByLabelText('Tracking option'), { target: { value: '2' } })
    fireEvent.click(screen.getByLabelText(/Consolidate/))
    fireEvent.click(screen.getByRole('button', { name: /^(Run|Apply|Refresh|Go)/ }))
    await waitFor(() => expect(books.ledgerReportMulti).toHaveBeenLastCalledWith('general-ledger-detail', expect.objectContaining({ group_by: 'party', contact: 'AGL', source_type: 'manual', q: 'power', min_amount: '100', tracking_option_ids: [2], consolidate: true })))
  })
  it('shows a friendly message when nothing matches, and an error with retry when the API fails', async () => {
    state.mode = 'empty'; const first = render(<FinancialReports userId={1} />); await open('General Ledger (detailed)')
    expect(await screen.findByText(/No ledger lines match/)).toBeInTheDocument(); first.unmount()
    state.mode = 'fail'; render(<FinancialReports userId={1} />); await open('General Ledger (detailed)')
    expect(await screen.findByText(/could not be loaded/i)).toBeInTheDocument()
  })
})

describe('Tracking Profit & Loss', () => {
  beforeEach(() => { state.mode = 'full'; state.cats = [{ id: 1, name: 'Department', options: [{ id: 2, name: 'Admin' }] }, { id: 7, name: 'Region', options: [] }]; vi.clearAllMocks() })
  it('shows a column per option plus Unassigned and Total, with real figures and the reconciliation note', async () => {
    render(<FinancialReports userId={1} />)
    await open('Tracking Profit & Loss')
    const table = await screen.findByTestId('pl-tracking')
    for (const c of FX.plTracking.columns) expect(within(table).getByRole('columnheader', { name: c.name })).toBeInTheDocument()
    expect(within(table).getByRole('columnheader', { name: 'Total' })).toBeInTheDocument()
    const net = FX.plTracking.net_profit
    const netRow = within(table).getByText('Net profit').closest('tr')
    expect(netRow.textContent).toContain(fmtAUD(net.total))
    for (const c of FX.plTracking.columns) expect(netRow.textContent).toContain(fmtAUD(net[c.key]))
    expect(screen.getByText(/columns add up to the ordinary Profit & Loss/)).toBeInTheDocument()
    expect(within(table).getAllByText(/^Total /).length).toBeGreaterThan(1)          // one total row per section
  })
  it('asks the API for the chosen category and dates', async () => {
    render(<FinancialReports userId={1} />)
    await open('Tracking Profit & Loss'); await screen.findByTestId('pl-tracking')
    fireEvent.change(screen.getByLabelText('Tracking category'), { target: { value: '7' } })
    await waitFor(() => expect(books.ledgerReport).toHaveBeenLastCalledWith('profit-loss-by-tracking', expect.objectContaining({ category_id: 7 })))
  })
  it('warns loudly if the columns ever fail to add up to the ordinary P&L', async () => {
    const bad = { ...FX.plTracking, matches_profit_loss: false, profit_loss_net: '1.00' }
    books.ledgerReport.mockImplementationOnce(() => Promise.resolve({ data: bad }))
    render(<FinancialReports userId={1} />)
    await open('Tracking Profit & Loss'); expect(await screen.findByText(/do not add up to the ordinary Profit & Loss/)).toBeInTheDocument()
  })
  it('explains what to do when there is no tracking category yet', async () => {
    state.cats = []; render(<FinancialReports userId={1} />)
    await open('Tracking Profit & Loss'); expect(await screen.findByText('No tracking categories yet')).toBeInTheDocument()
  })
  it('shows a friendly empty state and an error with retry', async () => {
    state.mode = 'empty'; const a = render(<FinancialReports userId={1} />); await open('Tracking Profit & Loss')
    expect(await screen.findByText(/No income or expenses in this period/)).toBeInTheDocument(); a.unmount()
    state.mode = 'fail'; render(<FinancialReports userId={1} />); await open('Tracking Profit & Loss'); expect(await screen.findByText(/could not be loaded/i)).toBeInTheDocument()
  })
})
