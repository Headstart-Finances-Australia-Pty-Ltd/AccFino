import React from 'react'
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, waitFor, fireEvent, within } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'

vi.mock('react-hot-toast', () => ({ default: { success: vi.fn(), error: vi.fn() } }))
vi.mock('recharts', () => {
  const Box = ({ children }) => <div data-testid="chart">{children}</div>
  return { ResponsiveContainer: Box, PieChart: Box, Pie: Box, Cell: () => null, Tooltip: () => null, Legend: () => null, LineChart: Box, AreaChart: Box, BarChart: Box, Line: () => null, Area: () => null, Bar: () => null, CartesianGrid: () => null, XAxis: () => null, YAxis: () => null }
})
vi.mock('../lib/invApi.js', () => {
  const fn = vi.fn
  return {
    errMsg: e => e?.message || 'Error', me: fn(), reference: fn(), settings: { get: fn(), save: fn() }, accounts: { list: fn(), save: fn() },
    securities: { list: fn(), save: fn(), detail: fn(), setPrice: fn(), prices: fn(), removePrice: fn() }, txns: { list: fn(), save: fn(), void: fn(), swap: fn() },
    portfolio: { holdings: fn(), disposals: fn(), income: fn(), performance: fn(), allocation: fn(), history: fn() },
    property: { list: fn(), save: fn(), remove: fn(), detail: fn(), saveEntry: fn(), voidEntry: fn(), entries: fn(), sendSale: fn() }, valuations: { add: fn(), list: fn(), remove: fn() },
    otherAssets: { list: fn(), save: fn() }, liabilities: { list: fn(), save: fn() }, networth: { get: fn(), history: fn(), snapshots: fn(), snapshot: fn() },
    documents: { list: fn(), remove: fn(), download: fn(), upload: fn(), bulkTemplate: fn(), bulkPreview: fn(), bulkCommit: fn() }, cgt: { preview: fn(), send: fn() }, ledger: { bankAccounts: fn(), post: fn(), unlink: fn(), reconciliation: fn() },
    imports: { catalogue: fn(), template: fn(), preview: fn(), commit: fn() }, reports: { csv: fn(), pack: fn() }, audit: { list: fn(), verify: fn() },
  }
})
import * as api from '../lib/invApi.js'
import { fmtAUD, fmtPct, fmtQty } from '../lib/format.js'
import { HoldingsPanel, GainsPanel, LedgerPanel } from '../components/panels.jsx'
import { TxnForm, SecurityForm } from '../components/forms.jsx'
import PropertyTab from '../pages/PropertyTab.jsx'
import NetWorthTab from '../pages/NetWorthTab.jsx'
import PortfolioTab from '../pages/PortfolioTab.jsx'
import BulkDocs from '../components/BulkDocs.jsx'

const ALL = ['view', 'edit', 'import', 'post', 'config', 'audit_view', 'delete']
const ME = { capabilities: ALL }
const REF = { security_kinds: ['share', 'etf', 'crypto'], asset_classes: ['au_equity', 'crypto', 'fixed_interest'], account_kinds: ['broker'], txn_types: ['buy', 'sell', 'dividend'], states: ['NSW'], property_types: ['house'], property_uses: ['investment'], entry_kinds: ['rent_income', 'expense'], expense_categories: ['rates', 'agent_fees'], liability_kinds: ['mortgage'], other_asset_kinds: ['vehicle'] }
const W = ui => render(<MemoryRouter>{ui}</MemoryRouter>)
beforeEach(() => { vi.clearAllMocks(); api.imports.catalogue.mockResolvedValue([]); api.documents.list.mockResolvedValue([]); window.confirm = vi.fn(() => true) })

describe('formatting', () => {
  it('shows negative dollars in brackets, quantities without trailing noise and percentages', () => {
    expect(fmtAUD('-3959')).toBe('($3,959.00)'); expect(fmtAUD('1234.5')).toBe('$1,234.50'); expect(fmtAUD(null)).toBe('—')
    expect(fmtQty('0.15000000')).toBe('0.15'); expect(fmtQty('1234.5')).toBe('1,234.5'); expect(fmtPct(0.1234)).toBe('12.34%'); expect(fmtPct('x')).toBe('—')
  })
})

describe('Holdings', () => {
  const H = { as_at: '2026-10-05', total_value: '20235.00', total_cost: '18964.45', warnings: [{ message: 'BTC: no price on or before 2026-10-05: valued at cost' }], rows: [
    { account_id: 1, account: 'CommSec', security_id: 1, code: 'BHP', name: 'BHP Group', kind: 'share', qty: '100', cost_base: '4019.95', price: '50.5', price_date: '2026-09-30', price_stale: false, value: '5050.00', unrealised: '1030.05', unrealised_pct: 0.256, income_12m: '90.00', weight: 0.25 },
    { account_id: 2, account: 'Swyftx', security_id: 3, code: 'BTC', name: 'Bitcoin', kind: 'crypto', qty: '0.15', cost_base: '9935.00', price: null, price_note: 'no price: valued at cost', price_stale: false, value: '9935.00', unrealised: '0.00', unrealised_pct: 0, income_12m: '0.00', weight: 0.49 }] }
  it('shows value, cost, unrealised gain, flags a missing price and surfaces the warning', async () => {
    api.portfolio.holdings.mockResolvedValue(H)
    W(<HoldingsPanel kind="" caps={ALL} />)
    expect(await screen.findByText('BHP')).toBeInTheDocument(); expect(screen.getByText('$20,235.00')).toBeInTheDocument(); expect(screen.getByText('$18,964.45')).toBeInTheDocument(); expect(screen.getAllByText('$1,030.05').length).toBe(2)                                      // the summary card and the BHP row
    expect(screen.getByText('no price')).toBeInTheDocument(); expect(screen.getByText(/BTC: no price on or before/)).toBeInTheDocument()
    expect(api.portfolio.holdings).toHaveBeenCalledWith(expect.objectContaining({ merge: false }))
  })
  it('merges accounts when asked and opens the drill-down for a holding', async () => {
    api.portfolio.holdings.mockResolvedValue(H)
    api.securities.detail.mockResolvedValue({ security: { code: 'BHP', name: 'BHP Group', kind: 'share' }, warnings: [], performance: { market_value: '5050', total_return: '1030.05', total_return_pct: 0.256, xirr_since_inception: 0.2, total_invested: '4019.95' }, parcels: [{ lot_id: 1, acquired: '2024-01-10', qty: '100', cost_base: '4019.95', unit_cost: '40.1995', origin: 'buy', discount_eligible: true }], disposals: [], income: [] })
    W(<HoldingsPanel kind="" caps={ALL} />)
    fireEvent.click(await screen.findByLabelText('Merge accounts')); await waitFor(() => expect(api.portfolio.holdings).toHaveBeenLastCalledWith(expect.objectContaining({ merge: true })))
    fireEvent.click(await screen.findByText('BHP'))
    expect(await screen.findByText(/Investment detail/)).toBeInTheDocument(); expect(await screen.findByText('Parcels (cost base)')).toBeInTheDocument(); expect(screen.getByText('Yes')).toBeInTheDocument()
  })
})

describe('Transaction form', () => {
  const base = { accounts: [{ id: 1, name: 'CommSec' }], securities: [{ id: 1, code: 'BHP', name: 'BHP', kind: 'share' }, { id: 2, code: 'BTC', name: 'Bitcoin', kind: 'crypto' }], reference: REF, settings: {} }
  const open = (props = {}) => { api.txns.list.mockResolvedValue([]); return W(<TxnForm base={base} kinds={['share', 'etf', 'crypto']} onClose={() => {}} onSaved={() => {}} {...props} />) }
  it('is disabled until the essentials are given and says what is missing', () => {
    open(); expect(screen.getByRole('button', { name: 'Save' })).toBeDisabled(); expect(screen.getByText(/Choose an account/)).toBeInTheDocument(); expect(screen.getByText(/Choose a security/)).toBeInTheDocument()
  })
  it('shows the fields that belong to the type: franking for a dividend, a ratio for a split, a reference for a transfer', () => {
    open({ item: { account_id: 1, security_id: 1, txn_type: 'dividend', trade_date: '2026-01-01' } })
    expect(screen.getByLabelText('Franked amount')).toBeInTheDocument(); expect(screen.getByLabelText('Franking credits')).toBeInTheDocument(); expect(screen.queryByLabelText('Brokerage / fees')).not.toBeInTheDocument()
    fireEvent.change(screen.getByLabelText('Type'), { target: { value: 'buy' } }); expect(screen.getByLabelText('Brokerage / fees')).toBeInTheDocument(); expect(screen.queryByLabelText('Franked amount')).not.toBeInTheDocument()
  })
  it('works out the amount from quantity x price, and warns when franking credits exceed 30/70 of the franked amount', () => {
    open({ item: { account_id: 1, security_id: 1, txn_type: 'buy', trade_date: '2026-01-01' } })
    fireEvent.change(screen.getByLabelText('Units / quantity'), { target: { value: '100' } }); fireEvent.change(screen.getByLabelText('Price per unit'), { target: { value: '45.5' } })
    expect(screen.getByText(/Amount will be 4550.00/)).toBeInTheDocument(); expect(screen.getByRole('button', { name: 'Save' })).not.toBeDisabled()
    fireEvent.change(screen.getByLabelText('Type'), { target: { value: 'dividend' } }); fireEvent.change(screen.getByLabelText('Amount (AUD)'), { target: { value: '100' } }); fireEvent.change(screen.getByLabelText('Franked amount'), { target: { value: '100' } }); fireEvent.change(screen.getByLabelText('Franking credits'), { target: { value: '50' } })
    expect(screen.getByText(/cannot be more than 30\/70/)).toBeInTheDocument()
  })
  it('a transfer needs its reference and a sale offers the parcels to name', async () => {
    open({ item: { account_id: 1, security_id: 1, txn_type: 'transfer_out', trade_date: '2026-01-01', quantity: '5' } })
    api.txns.list.mockResolvedValue([{ id: 7, trade_date: '2024-01-10', quantity: '100', amount: '4000' }])
    expect(screen.getByText(/A transfer needs a reference/)).toBeInTheDocument()
    fireEvent.change(screen.getByLabelText('Type'), { target: { value: 'sell' } })
    expect(await screen.findByLabelText('Specific parcel (optional)')).toBeInTheDocument(); expect(await screen.findByText(/2024-01-10 · 100 units/)).toBeInTheDocument()
  })
  it('sends blanks as null and reports success', async () => {
    api.txns.save.mockResolvedValue({}); const saved = vi.fn()
    open({ item: { account_id: 1, security_id: 1, txn_type: 'buy', trade_date: '2026-01-01', quantity: '10', amount: '100' }, onSaved: saved })
    fireEvent.click(screen.getByRole('button', { name: 'Save' })); await waitFor(() => expect(saved).toHaveBeenCalled())
    expect(api.txns.save.mock.calls[0][0]).toMatchObject({ txn_type: 'buy', quantity: '10', amount: '100', reference: null, lot_ref: null })
  })
  it('a bond needs its face value, coupon and maturity before it can be saved', () => {
    W(<SecurityForm kinds={['bond']} reference={REF} onClose={() => {}} onSaved={() => {}} />)
    expect(screen.getByText(/Maturity date is required/)).toBeInTheDocument(); expect(screen.getByText(/Face value is required/)).toBeInTheDocument(); expect(screen.getByRole('button', { name: 'Save' })).toBeDisabled()
    fireEvent.change(screen.getByLabelText('Code'), { target: { value: 'GS32' } }); fireEvent.change(screen.getByLabelText('Name'), { target: { value: 'Treasury 2032' } }); fireEvent.change(screen.getByLabelText('Maturity date'), { target: { value: '2032-06-21' } })
    fireEvent.change(screen.getByLabelText('Face value per unit'), { target: { value: '1000' } }); fireEvent.change(screen.getByLabelText('Coupon / interest rate (fraction)'), { target: { value: '0.0425' } })
    expect(screen.getByRole('button', { name: 'Save' })).not.toBeDisabled()
  })
})

describe('Realised gains and Tax', () => {
  const D = { holder: 'individual', method: 'fifo', excess_gains: [], summary: { discount_rate: 0.5, note: 'Estimate from this register only.', by_fy: [{ fy: '2025-26', gains_discountable: '2000.00', gains_other: '600.00', losses: '800.00', discount: '900.00', net_capital_gain: '900.00', losses_carried_forward: '0.00' }] },
    rows: [{ txn_id: 1, dispose_date: '2025-11-03', code: 'BHP', acquire_date: '2023-01-10', qty: '100', proceeds: '3000', selling_costs: '0', cost_base: '1000', gain: '2000', discount_eligible: true, method: 'fifo', fy: '2025-26' }] }
  it('summarises the year with the discount and a clear estimate note, and sends to Tax with a dry-run first', async () => {
    api.portfolio.disposals.mockResolvedValue(D); api.cgt.send.mockResolvedValue({ added: 1, skipped_duplicates: 2, rejected: 0, errors: [] })
    W(<GainsPanel kind="" me={ME} />)
    expect(await screen.findByText('Estimated net capital gain')).toBeInTheDocument(); expect(screen.getAllByText('$900.00').length).toBeGreaterThan(0); expect(screen.getAllByText(/Estimate from this register only|authoritative CGT calculation/).length).toBeGreaterThan(0)
    fireEvent.click(screen.getByRole('button', { name: 'Check what would go to Tax' })); expect(await screen.findByText(/Check only, nothing was saved/)).toBeInTheDocument(); expect(api.cgt.send).toHaveBeenLastCalledWith({ fy: '', kind: '', dry_run: true })
    fireEvent.click(screen.getByRole('button', { name: 'Send disposals to Tax (CGT)' })); await waitFor(() => expect(api.cgt.send).toHaveBeenLastCalledWith({ fy: '', kind: '', dry_run: false })); expect(await screen.findByText(/2 already in Taxation/)).toBeInTheDocument()
  })
  it('hides the send buttons from roles that cannot edit', async () => {
    api.portfolio.disposals.mockResolvedValue(D)
    W(<GainsPanel kind="" me={{ capabilities: ['view'] }} />); await screen.findByText('BHP'); expect(screen.queryByRole('button', { name: 'Send disposals to Tax (CGT)' })).not.toBeInTheDocument()
  })
})

describe('Ledger', () => {
  it('shows the register against the ledger and posts the selected transactions to the chosen bank account', async () => {
    api.ledger.reconciliation.mockResolvedValue({ register_cost_base: '2411.97', ledger_account: { code: '1640', name: 'Investments at cost', balance: '2411.97' }, difference: '0.00', status: 'agrees', posted_transactions: 3, unposted_postable: 1, explanation: 'The register cost base equals the ledger.' })
    api.ledger.bankAccounts.mockResolvedValue([{ id: 9, code: '090', name: 'Business Cheque' }]); api.txns.list.mockResolvedValue([{ id: 5, trade_date: '2026-03-02', txn_type: 'buy', code: 'BHP', amount: '4000', fees: '20', voided: false, linked_journal_id: null }])
    api.ledger.post.mockResolvedValue({ posted: [{ id: 5, journal_id: 77 }], skipped: [], failed: [] })
    W(<LedgerPanel me={ME} />)
    expect(await screen.findByText('agrees')).toBeInTheDocument(); expect(screen.getByText('3 / 1')).toBeInTheDocument()
    const post = await screen.findByRole('button', { name: /Post/ }); expect(post).toBeDisabled()
    fireEvent.click(await screen.findByLabelText('Select BHP 2026-03-02')); fireEvent.change(await screen.findByLabelText('Bank account'), { target: { value: '9' } }); expect(screen.getByRole('button', { name: /Post 1 selected/ })).not.toBeDisabled()
    fireEvent.click(screen.getByRole('button', { name: /Post 1 selected/ })); await waitFor(() => expect(api.ledger.post).toHaveBeenCalledWith({ txn_ids: [5], bank_account_id: 9 })); expect(await screen.findByText(/1 posted · 0 skipped · 0 failed/)).toBeInTheDocument()
  })
  it('Select all ticks every postable transaction and Clear removes the ticks', async () => {
    api.ledger.reconciliation.mockResolvedValue({ register_cost_base: '0', ledger_account: { code: '1640', name: 'Investments at cost', balance: null }, difference: null, status: 'no_ledger_account', posted_transactions: 0, unposted_postable: 3, explanation: 'Nothing posted' })
    api.ledger.bankAccounts.mockResolvedValue([{ id: 9, code: '090', name: 'Business Cheque' }])
    api.txns.list.mockResolvedValue([1, 2, 3].map(i => ({ id: i, trade_date: `2026-03-0${i}`, txn_type: 'buy', code: 'BHP', amount: '100', fees: '0', voided: false, linked_journal_id: null })).concat([{ id: 9, trade_date: '2026-03-09', txn_type: 'split', code: 'BHP', amount: '0', fees: '0', voided: false, linked_journal_id: null }]))
    W(<LedgerPanel me={ME} />)
    fireEvent.change(await screen.findByLabelText('Bank account'), { target: { value: '9' } })
    fireEvent.click(await screen.findByRole('button', { name: 'Select all' })); expect(await screen.findByRole('button', { name: 'Post 3 selected' })).not.toBeDisabled()          // the split is not offered: it has no ledger effect
    fireEvent.click(screen.getByRole('button', { name: 'Clear' })); expect(screen.getByRole('button', { name: /^Post\s*selected$/ })).toBeDisabled()
  })
  it('says plainly when the only difference is tax-only cost base adjustments', async () => {
    api.ledger.reconciliation.mockResolvedValue({ register_cost_base: '96739.89', ledger_account: { code: '1640', name: 'Investments at cost', balance: '96884.89' }, difference: '-145.00', tax_only_adjustments: '-145.00', unexplained_difference: '0.00', status: 'agrees_after_tax_adjustments',
      posted_transactions: 31, unposted_postable: 0, explanation: 'The only difference is tax-only cost base changes (the tax-deferred part of distributions and AMIT adjustments).' })
    api.ledger.bankAccounts.mockResolvedValue([]); api.txns.list.mockResolvedValue([])
    W(<LedgerPanel me={ME} />)
    expect(await screen.findByText('agrees after tax-only adjustments')).toBeInTheDocument(); expect(screen.getByText(/The only difference is tax-only cost base changes/)).toBeInTheDocument()
  })
  it('does not offer posting to roles that cannot post', async () => {
    api.ledger.reconciliation.mockResolvedValue({ register_cost_base: '0', ledger_account: { code: '1640', name: 'x', balance: null }, difference: null, status: 'no_ledger_account', posted_transactions: 0, unposted_postable: 0, explanation: 'Nothing posted' })
    api.ledger.bankAccounts.mockResolvedValue([]); api.txns.list.mockResolvedValue([])
    W(<LedgerPanel me={{ capabilities: ['view', 'edit'] }} />); await screen.findByText('nothing posted yet'); expect(screen.queryByText('Post transactions to the ledger')).not.toBeInTheDocument()
  })
})

describe('Property', () => {
  const OV = { total_value: '1000000.00', total_loans: '480000.00', total_equity: '520000.00', rows: [{ id: 1, name: '14 Wattle Rd', address: '14 Wattle Rd, Manly', use: 'investment', status: 'active', your_share_value: '1000000.00', loan: '480000.00', your_share_equity: '520000.00', gross_yield: 0.036, net_yield: 0.0274, cash_flow: '-580.00', warnings: 1 }] }
  const DET = (est = null) => ({ property: { id: 1, name: '14 Wattle Rd', use: 'investment', ownership_pct: '100', loan_liability_id: 4 }, value: '1000000.00', value_basis: 'valuation 2026-06-30', loan_balance: '480000.00', your_share_equity: '520000.00', warnings: ['Valued at the purchase price: add a current valuation'],
    performance: { gross_yield: 0.036, net_yield: 0.0274, cash_flow_after_interest: '-580.00', negatively_geared: true, lvr: 0.48, capital_growth: '168000.00', cagr: 0.034 }, cost_base: { element1_price: '800000.00', element2_incidental: '32000.00', element3_ownership: '0.00', element4_improvements: '40000.00', capital_works_claimed: '5000.00', cost_base: '867000.00' },
    cgt_estimate: est, schedule: [{ fy: '2025-26', rent: '27000.00', expenses: '8580.00', loan_interest: '28000.00', capital_works: '6250.00', capital_works_estimated: true, depreciation: '0.00', total_deductions: '42830.00', net_rental_result: '-15830.00', your_share_net: '-15830.00' }], valuations: [], entries: [], documents: 0 })
  it('lists properties with value, loan, equity, yields and cash flow, and opens one', async () => {
    api.property.list.mockResolvedValue(OV); api.property.detail.mockResolvedValue(DET())
    W(<PropertyTab me={ME} />)
    expect(await screen.findByText('14 Wattle Rd')).toBeInTheDocument(); expect(screen.getAllByText('$1,000,000.00').length).toBeGreaterThan(0); expect(screen.getByText('3.60%')).toBeInTheDocument(); expect(screen.getByText('1 to check')).toBeInTheDocument()
    fireEvent.click(screen.getByText('14 Wattle Rd'))
    expect(await screen.findByText('Cost base and capital gain')).toBeInTheDocument(); expect(screen.getByText('$867,000.00')).toBeInTheDocument(); expect(screen.getByText('negatively geared')).toBeInTheDocument(); expect(screen.getByText(/Valued at the purchase price/)).toBeInTheDocument()
    expect(screen.getByText(/\$6,250.00/)).toBeInTheDocument()
  })
  it('estimates a planned sale only once the price and date are given, and shows the exemption notes', async () => {
    api.property.list.mockResolvedValue(OV)
    api.property.detail.mockImplementation((id, p) => Promise.resolve(DET(p && p.sale_price ? { capital_proceeds: '1200000.00', capital_gain_or_loss: '333000.00', main_residence_fraction: '0.0000', exempt_amount: '0.00', discount_applied: '166500.00', net_capital_gain: '166500.00', held_over_12_months: true, holder: 'individual', planned: true, notes: ['Estimate by days of ownership.'] } : null)))
    W(<PropertyTab me={ME} />); fireEvent.click(await screen.findByText('14 Wattle Rd')); const btn = await screen.findByRole('button', { name: 'Estimate the gain' }); expect(btn).toBeDisabled()
    fireEvent.change(screen.getByLabelText('Planned sale price'), { target: { value: '1200000' } }); fireEvent.change(screen.getByLabelText('Planned contract date'), { target: { value: '2026-10-01' } }); fireEvent.click(btn)
    expect((await screen.findAllByText('$166,500.00')).length).toBe(2); expect(screen.getByText('Estimate by days of ownership.')).toBeInTheDocument()                       // the discount and the net gain
    expect(screen.queryByRole('button', { name: /Send the sale to Tax/ })).not.toBeInTheDocument()                           // a planned sale is not sent to Tax
  })
})

describe('Portfolio and Net worth', () => {
  it('Portfolio shows return, allocation tables and an advisory concentration message', async () => {
    api.portfolio.performance.mockResolvedValue({ market_value: '10000.00', total_return: '1500.00', total_return_pct: 0.15, xirr_since_inception: 0.12, xirr_last_12_months: 0.1, total_invested: '8500.00', total_returned: '0.00' })
    api.portfolio.allocation.mockResolvedValue({ warnings: [], by_class: [{ name: 'au_equity', value: '8000.00', weight: 0.8 }, { name: 'crypto', value: '2000.00', weight: 0.2 }], by_kind: [], by_country: [], by_sector: [], by_account: [],
      diversification: { holdings: 3, hhi: 0.38, effective_holdings: 2.6, top1: 0.5, top5: 1, limit: 0.2, over_limit: [{ name: 'BHP', weight: 0.5 }] } })
    api.portfolio.history.mockResolvedValue({ points: [{ date: '2026-08-31', value: '9000', cost: '8500', invested_to_date: '8500' }, { date: '2026-09-30', value: '10000', cost: '8500', invested_to_date: '8500' }] })
    api.portfolio.income.mockResolvedValue({ by_fy: [], rows: [], flags: [] }); api.portfolio.disposals.mockResolvedValue({ summary: { by_fy: [] }, rows: [], excess_gains: [] }); api.portfolio.holdings.mockResolvedValue({ rows: [], total_value: '0', total_cost: '0', warnings: [] })
    W(<PortfolioTab me={ME} />)
    expect(await screen.findByText('Annual return since start (XIRR)')).toBeInTheDocument(); expect(screen.getByText('12.00%')).toBeInTheDocument(); expect(screen.getAllByText('80.0%').length).toBeGreaterThan(0)
    expect(await screen.findByText(/Above 20% of the portfolio: BHP 50.0%/)).toBeInTheDocument(); expect(screen.getByText('2.6')).toBeInTheDocument(); expect(screen.getAllByTestId('chart').length).toBeGreaterThan(0)
  })
  it('Net worth shows totals, what is counted and its source, warnings, and saves a snapshot', async () => {
    api.networth.get.mockResolvedValue({ net_worth: '720000.00', total_assets: '1300000.00', total_liabilities: '580000.00', warnings: ['Hilux: no value recorded'], ratios: { debt_to_assets: 0.446, liquid_assets: '255000.00', liquid_share: 0.196 },
      assets_by_group: [{ name: 'Property', value: '1000000.00', weight: 0.77 }, { name: 'Cash', value: '150000.00', weight: 0.115 }], liabilities_by_group: [{ name: 'Loans & borrowings', value: '580000.00' }],
      assets: [{ group: 'Property', name: '14 Wattle Rd', value: '1000000.00', source: 'property register, valuation 2026-06-30' }], liabilities: [{ group: 'Loans & borrowings', name: 'Manly loan', value: '480000.00', source: 'balance 2026-09-30' }] })
    api.networth.history.mockResolvedValue({ points: [], change: { from_date: '2025-10-31', amount: '120000.00', pct: 0.2 } }); api.otherAssets.list.mockResolvedValue([]); api.liabilities.list.mockResolvedValue([]); api.networth.snapshots.mockResolvedValue([])
    api.ledger.reconciliation.mockResolvedValue({ register_cost_base: '0', ledger_account: { code: '1640', name: 'Investments at cost', balance: null }, explanation: 'Nothing has been posted to the ledger yet.' }); api.networth.snapshot.mockResolvedValue({})
    W(<NetWorthTab me={ME} />)
    expect(await screen.findByText('Net worth')).toBeInTheDocument(); expect(screen.getAllByText('$720,000.00').length).toBeGreaterThan(0); expect(screen.getByText(/Hilux: no value recorded/)).toBeInTheDocument()
    expect(screen.getByText('property register, valuation 2026-06-30')).toBeInTheDocument(); expect(screen.getByText(/Change since/)).toBeInTheDocument(); expect(screen.getByText(/Net worth uses the register's market value/)).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: "Save today's snapshot" })); await waitFor(() => expect(api.networth.snapshot).toHaveBeenCalled())
  })
  it('Net worth history offers up to 10 years and lists its figures in a table', async () => {
    api.networth.get.mockResolvedValue({ net_worth: '0', total_assets: '0', total_liabilities: '0', warnings: [], ratios: { debt_to_assets: null, liquid_assets: '0', liquid_share: null }, assets_by_group: [], liabilities_by_group: [], assets: [], liabilities: [] })
    api.networth.history.mockResolvedValue({ points: [{ date: '2017-06-30', assets: '410000.00', liabilities: '120000.00', net_worth: '290000.00', from_snapshot: true }, { date: '2018-06-30', assets: '455000.00', liabilities: '110000.00', net_worth: '345000.00', from_snapshot: true }], change: null })
    api.otherAssets.list.mockResolvedValue([]); api.liabilities.list.mockResolvedValue([]); api.networth.snapshots.mockResolvedValue([]); api.ledger.reconciliation.mockResolvedValue({ register_cost_base: '0', ledger_account: { code: '1640', name: 'x', balance: null }, explanation: '' })
    W(<NetWorthTab me={ME} />)
    const sel = await screen.findByLabelText('Period'); expect(within(sel).getByText('10 years')).toBeInTheDocument(); fireEvent.change(sel, { target: { value: '120' } }); await waitFor(() => expect(api.networth.history).toHaveBeenLastCalledWith(120))
    expect(await screen.findByText('Show the figures')).toBeInTheDocument(); expect(screen.getByText('2017-06-30')).toBeInTheDocument(); expect(screen.getAllByText('$345,000.00').length).toBeGreaterThan(0)
  })
})


describe('Bulk uploads for the remaining tables', () => {
  const PREVIEW = { total: 4, ok: 2, duplicates: 1, errors: 1, unused_files: ['spare.pdf'], can_commit: true, file_sha256: 'c'.repeat(64),
    rows: [{ line: 2, status: 'ok', messages: [], data: { file_name: 'cn.pdf', owner_type: 'security', owner: 'BHP' } }, { line: 3, status: 'ok', messages: [], data: { file_name: 'sale.pdf', owner_type: 'property', owner: 'Manly' } },
           { line: 4, status: 'duplicate', messages: [{ level: 'info', text: 'This exact file is already attached to that record: skipped' }], data: { file_name: 'cn.pdf', owner_type: 'security', owner: 'BHP' } },
           { line: 5, status: 'error', messages: [{ level: 'error', text: "The file 'missing.pdf' was not uploaded with the manifest" }], data: { file_name: 'missing.pdf', owner_type: 'security', owner: 'BHP' } }] }
  const choose = () => {
    fireEvent.change(screen.getByLabelText('Manifest CSV'), { target: { files: [new File(['file_name,owner_type,owner'], 'manifest.csv', { type: 'text/csv' })] } })
    fireEvent.change(screen.getByLabelText('Document files'), { target: { files: [new File(['%PDF'], 'cn.pdf', { type: 'application/pdf' }), new File(['%PDF'], 'sale.pdf', { type: 'application/pdf' })] } })
  }
  it('is offered only to roles that can edit', () => {
    const { container } = W(<BulkDocs caps={['view']} />); expect(container).toBeEmptyDOMElement()
  })
  it('previews the manifest against the chosen files, flags files the manifest never mentions, and uploads the valid ones', async () => {
    api.documents.bulkPreview.mockResolvedValue(PREVIEW); api.documents.bulkCommit.mockResolvedValue({ uploaded: 2, skipped_duplicates: 1, rejected: 1, failed: [], file_sha256: 'c'.repeat(64), unused_files: ['spare.pdf'], rows: PREVIEW.rows })
    const done = vi.fn(); W(<BulkDocs caps={ALL} onDone={done} />)
    fireEvent.click(screen.getByRole('button', { name: /Bulk upload documents/ })); const check = screen.getByRole('button', { name: 'Check files' }); expect(check).toBeDisabled()
    choose(); expect(screen.getByText(/Manifest: manifest.csv · 2 files chosen/)).toBeInTheDocument(); expect(check).not.toBeDisabled(); fireEvent.click(check)
    expect(await screen.findByText('2 valid')).toBeInTheDocument(); expect(screen.getByText('1 duplicate(s)')).toBeInTheDocument(); expect(screen.getByText('1 with errors')).toBeInTheDocument()
    expect(screen.getByText(/Not in the manifest, so not uploaded: spare.pdf/)).toBeInTheDocument(); expect(screen.getByText(/was not uploaded with the manifest/)).toBeInTheDocument()
    expect(api.documents.bulkPreview).toHaveBeenCalledWith(expect.any(File), [expect.any(File), expect.any(File)]); expect(api.documents.bulkCommit).not.toHaveBeenCalled()
    fireEvent.click(screen.getByRole('button', { name: 'Upload 2 valid files' })); await waitFor(() => expect(api.documents.bulkCommit).toHaveBeenCalledWith(expect.any(File), expect.any(Array), 'valid_only'))
    expect(await screen.findByText(/2 uploaded · 1 duplicate\(s\) skipped · 1 rejected · 0 failed/)).toBeInTheDocument(); fireEvent.click(screen.getByRole('button', { name: 'Done' })); expect(done).toHaveBeenCalled()
  })
  it('all-or-nothing blocks the upload while any row is rejected, and a manifest problem is shown plainly with a way out', async () => {
    api.documents.bulkPreview.mockResolvedValueOnce(PREVIEW); W(<BulkDocs caps={ALL} />)
    fireEvent.click(screen.getByRole('button', { name: /Bulk upload documents/ })); choose(); fireEvent.click(screen.getByRole('button', { name: 'Check files' })); await screen.findByText('2 valid')
    fireEvent.click(screen.getByLabelText(/All or nothing/)); expect(screen.getByText(/Nothing will be uploaded while 1 row/)).toBeInTheDocument(); expect(screen.getByRole('button', { name: 'Upload 2 valid files' })).toBeDisabled()
    fireEvent.click(screen.getByRole('button', { name: 'Cancel' })); fireEvent.click(screen.getByRole('button', { name: /Bulk upload documents/ })); choose()
    api.documents.bulkPreview.mockResolvedValueOnce({ total: 1, ok: 0, duplicates: 0, errors: 0, rows: [], unused_files: [], can_commit: false, file_error: 'Required manifest column(s) missing: owner_type. Download the manifest template for the exact layout.' })
    fireEvent.click(screen.getByRole('button', { name: 'Check files' })); expect(await screen.findByRole('alert')).toHaveTextContent(/Required manifest column\(s\) missing: owner_type/); expect(screen.queryByRole('button', { name: /^Upload \d/ })).not.toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Close' })).toBeInTheDocument()
  })
  it('the Portfolio header offers the settings import and the bulk document upload; Net Worth offers the snapshot dataset', async () => {
    api.portfolio.performance.mockResolvedValue({ market_value: '0', total_return: '0', total_return_pct: null, xirr_since_inception: null, xirr_last_12_months: null, total_invested: '0', total_returned: '0' })
    api.portfolio.allocation.mockResolvedValue({ warnings: [], by_class: [], by_kind: [], by_country: [], by_sector: [], by_account: [], diversification: { holdings: 0, hhi: null, over_limit: [], limit: 0.2 } }); api.portfolio.history.mockResolvedValue({ points: [] })
    api.portfolio.income.mockResolvedValue({ by_fy: [], rows: [], flags: [] }); api.portfolio.disposals.mockResolvedValue({ summary: { by_fy: [] }, rows: [], excess_gains: [] }); api.portfolio.holdings.mockResolvedValue({ rows: [], total_value: '0', total_cost: '0', warnings: [] })
    W(<PortfolioTab me={ME} />)
    expect(await screen.findByRole('button', { name: /Import settings \(CSV\)/ })).toBeInTheDocument(); expect(screen.getByRole('button', { name: /Bulk upload documents/ })).toBeInTheDocument()
  })
  it('the Net Worth import dialog lists the net worth history dataset', async () => {
    api.networth.get.mockResolvedValue({ net_worth: '0', total_assets: '0', total_liabilities: '0', warnings: [], ratios: { debt_to_assets: null, liquid_assets: '0', liquid_share: null }, assets_by_group: [], liabilities_by_group: [], assets: [], liabilities: [] })
    api.networth.history.mockResolvedValue({ points: [], change: null }); api.otherAssets.list.mockResolvedValue([]); api.liabilities.list.mockResolvedValue([]); api.networth.snapshots.mockResolvedValue([])
    api.ledger.reconciliation.mockResolvedValue({ register_cost_base: '0', ledger_account: { code: '1640', name: 'x', balance: null }, explanation: '' })
    api.imports.catalogue.mockResolvedValue([{ key: 'networth_snapshots', title: 'Net worth history (snapshots)', description: 'Past net worth figures.', capability: 'edit', columns: [{ name: 'as_at', kind: 'date', required: true, enum: [], help: '' }] }])
    W(<NetWorthTab me={ME} />); fireEvent.click(await screen.findByRole('button', { name: /Bulk upload \/ Import CSV/ }))
    const sel = await screen.findByLabelText('What are you importing?'); expect(within(sel).getByText('Net worth history (snapshots)')).toBeInTheDocument()
  })
})
