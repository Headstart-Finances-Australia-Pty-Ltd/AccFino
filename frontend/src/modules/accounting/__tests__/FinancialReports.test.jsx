import React from 'react'
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, waitFor, fireEvent } from '@testing-library/react'

const { FX, ok, state, pick } = vi.hoisted(() => {
// Fixtures mirror the real backend response shapes (amounts are strings).
const row = (id, code, name, amount) => ({ account_id: id, code, name, type: 'x', amount })
const FX = {
  pl: { from: '2026-07-01', to: '2026-09-29', income: [row(1, '200', 'Sales', '1500.00')], total_income: '1500.00', cost_of_sales: [row(2, '310', 'COGS', '300.00')], total_cost_of_sales: '300.00',
    gross_profit: '1200.00', expenses: [row(3, '400', 'Rent', '200.00')], total_expenses: '200.00', operating_profit: '1000.00', other_income: [], total_other_income: '0.00',
    other_expenses: [], total_other_expenses: '0.00', net_profit: '1000.00' },
  bs: { as_at: '2026-09-29', financial_year_start: '2026-07-01', assets: { bank: [row(4, '090', 'Bank', '900.00')], current_asset: [], inventory: [], fixed_asset: [], non_current_asset: [] },
    total_assets: '900.00', liabilities: { credit_card: [], current_liability: [row(5, '820', 'GST', '100.00')], non_current_liability: [] }, total_liabilities: '100.00', net_assets: '800.00',
    equity: [], retained_earnings_prior_years: '0.00', current_year_earnings: '800.00', total_equity: '800.00', balanced: true },
  tb: { as_at: '2026-09-29', rows: [{ account_id: 4, code: '090', name: 'Bank', debit: '900.00', credit: '0.00' }, { account_id: 1, code: '200', name: 'Sales', debit: '0.00', credit: '900.00' }],
    total_debit: '900.00', total_credit: '900.00', balanced: true },
  gl: { account: { id: 4, code: '090', name: 'Bank' }, from: '2026-07-01', to: '2026-09-29', opening_balance: '0.00', closing_balance: '900.00',
    rows: [{ date: '2026-08-01', journal_id: 1, journal_no: 'J1', narration: 'Opening', description: null, debit: '900.00', credit: '0.00', balance: '900.00' }] },
  aged: { as_at: '2026-09-29', side: 'sales', buckets: { current: '10.00', '1-30': '0.00', '31-60': '0.00', '61-90': '0.00', '90+': '5.00' }, total: '15.00',
    contacts: [{ contact_id: 1, contact: 'Acme', docs: [], current: '10.00', '1-30': '0.00', '31-60': '0.00', '61-90': '0.00', '90+': '5.00', total: '15.00' }],
    control: { ledger_balance: '15.00', subledger_total: '15.00', difference: '0.00', reconciled: true } },
  gst: { basis: 'accrual', date_from: '2026-07-01', date_to: '2026-09-29', fields: { G1: '1100.00', G10: '0.00', G11: '220.00', '1A': '100.00', '1B': '20.00' },
    gst_on_sales_1A: '100.00', gst_on_purchases_1B: '20.00', net_gst_payable: '80.00', by_tax_code: {}, ledger_check: { gst_account_movement: '80.00', difference: '0.00', reconciled: true } },
  cash: { date_from: '2026-07-01', date_to: '2026-09-29', operating: { net_profit: '1000.00', adjustments: [{ label: 'Increase in GST', amount: '100.00' }], total: '1100.00' },
    investing: { items: [], total: '0.00' }, financing: { items: [], total: '0.00' }, net_change_in_cash: '1100.00', opening_cash: '0.00', closing_cash: '1100.00', reconciled: true, difference: '0.00' },
  ctrl: { as_at: '2026-09-29', receivables: { ledger_balance: '15.00', subledger_total: '15.00', difference: '0.00', reconciled: true }, payables: { ledger_balance: '0.00', subledger_total: '0.00', difference: '0.00', reconciled: true } },
  byc: { date_from: 'a', date_to: 'b', rows: [{ contact_id: 1, contact: 'Acme', net: '100.00', gst: '10.00', gross: '110.00', documents: 1 }], totals: { net: '100.00', gst: '10.00', gross: '110.00' } },
  inv: { total: 1, items: [{ id: 1, number: 'INV-1', contact: 'Acme', status: 'approved', issue_date: '2026-08-01', due_date: '2026-08-31', subtotal: '100.00', tax_total: '10.00', total: '110.00', amount_due: '110.00' }] },
}
const ok = data => () => Promise.resolve({ data })
const state = { mode: 'full' }                 // 'full' | 'empty' | 'fail'
const pick = data => () => state.mode === 'fail' ? Promise.reject(new Error('boom')) : Promise.resolve({ data: state.mode === 'empty' ? {} : data })

  return { FX, ok, state, pick }
})

vi.mock('../../../core/lib/platformApi.js', () => ({
  errMsg: e => e?.message || 'err',
  profitLoss: (...a) => pick(FX.pl)(...a), balanceSheet: (...a) => pick(FX.bs)(...a), trialBalance: (...a) => pick(FX.tb)(...a),
  generalLedger: (...a) => pick(FX.gl)(...a), accounts: () => Promise.resolve({ data: [{ id: 4, code: '090', name: 'Bank' }] }),
}))
vi.mock('../lib/ledgerApi.js', () => ({
  errMsg: e => e?.message || 'err',
  profitLoss: (...a) => pick(FX.pl)(...a), balanceSheet: (...a) => pick(FX.bs)(...a), trialBalance: (...a) => pick(FX.tb)(...a),
  generalLedger: (...a) => pick(FX.gl)(...a), accounts: () => Promise.resolve({ data: [{ id: 4, code: '090', name: 'Bank' }] }),
}))
vi.mock('../../../core/lib/adminApi.js', () => ({
  errMsg: e => e?.message || 'err',
  salesReport: (...a) => pick(FX.aged)(...a), purchasesReport: (...a) => pick(FX.aged)(...a),
  ledgerReport: path => pick({ 'gst-summary': FX.gst, 'cash-flow': FX.cash, 'subledger-control': FX.ctrl }[path])(),
  listDocs: (...a) => pick(FX.inv)(...a),
}))
vi.mock('../lib/booksApi.js', () => ({
  errMsg: e => e?.message || 'err',
  salesReport: (...a) => pick(FX.aged)(...a), purchasesReport: (...a) => pick(FX.aged)(...a),
  ledgerReport: path => pick({ 'gst-summary': FX.gst, 'cash-flow': FX.cash, 'subledger-control': FX.ctrl }[path])(),
  listDocs: (...a) => pick(FX.inv)(...a),
}))
vi.mock('../../billing/lib/orgBillingApi.js', () => ({
  errMsg: e => e?.message || 'err',
  salesReport: (...a) => pick(FX.aged)(...a), purchasesReport: (...a) => pick(FX.aged)(...a),
  ledgerReport: path => pick({ 'gst-summary': FX.gst, 'cash-flow': FX.cash, 'subledger-control': FX.ctrl }[path])(),
  listDocs: (...a) => pick(FX.inv)(...a),
}))
vi.mock('../../open_banking/lib/feedApi.js', () => ({
  errMsg: e => e?.message || 'err',
  salesReport: (...a) => pick(FX.aged)(...a), purchasesReport: (...a) => pick(FX.aged)(...a),
  ledgerReport: path => pick({ 'gst-summary': FX.gst, 'cash-flow': FX.cash, 'subledger-control': FX.ctrl }[path])(),
  listDocs: (...a) => pick(FX.inv)(...a),
}))
vi.mock('../../../core/lib/api.js', () => ({ getMyPlan: ok({ plan_id: 'accounting_pro' }) }))
vi.mock('../lib/api.js', () => ({ getMyPlan: ok({ plan_id: 'accounting_pro' }) }))
vi.mock('../../billing/lib/api.js', () => ({ getMyPlan: ok({ plan_id: 'accounting_pro' }) }))
vi.mock('../../cashflow/lib/api.js', () => ({ getMyPlan: ok({ plan_id: 'accounting_pro' }) }))
vi.mock('../../open_banking/lib/api.js', () => ({ getMyPlan: ok({ plan_id: 'accounting_pro' }) }))
vi.mock('../../reconciliation/lib/api.js', () => ({ getMyPlan: ok({ plan_id: 'accounting_pro' }) }))
vi.mock('../../trading/lib/api.js', () => ({ getMyPlan: ok({ plan_id: 'accounting_pro' }) }))

import FinancialReports from '../pages/FinancialReports.jsx'

const LIVE = ['Executive Summary', 'Profit & Loss', 'Balance Sheet', 'Cash Flow Statement', 'Aged Receivables', 'Aged Payables', 'Invoice Summary',
  'Sales by Customer', 'Purchases by Supplier', 'GST / BAS Report', 'Trial Balance', 'Sub-ledger Control Check', 'Account Transactions']

async function openEach(label) {
  const btn = await screen.findByRole('button', { name: new RegExp(`^${label.replace(/[/&]/g, '.')}`) })
  await waitFor(() => expect(btn.style.cursor).toBe('pointer'))          // plan check has finished
  fireEvent.click(btn)
  await waitFor(() => expect(screen.getByRole('heading', { name: label })).toBeInTheDocument())
  if (label === 'Account Transactions') {
    fireEvent.change(await screen.findByRole('combobox'), { target: { value: '4' } })
    fireEvent.click(screen.getByRole('button', { name: 'Run' }))
  }
  await new Promise(r => setTimeout(r, 30))
  expect(screen.queryByText(/hit a display problem/i)).toBeNull()
}

describe('FinancialReports', () => {
  beforeEach(() => { state.mode = 'full' })

  it('shows the grouped menu and opens every live report without crashing (real-shaped data)', async () => {
    render(<FinancialReports userId={1} />)
    expect(screen.getByText('All Reports')).toBeInTheDocument()
    for (const l of LIVE) await openEach(l)
    expect(screen.queryByText(/could not be loaded/i)).toBeNull()
  })

  it('never crashes on empty or malformed responses', async () => {
    state.mode = 'empty'
    render(<FinancialReports userId={1} />)
    for (const l of LIVE) await openEach(l)
  })

  it('shows an inline error (not a crash) when the API fails', async () => {
    state.mode = 'fail'
    render(<FinancialReports userId={1} />)
    for (const l of LIVE.filter(x => x !== 'Account Transactions')) await openEach(l)
    expect(screen.queryByText(/hit a display problem/i)).toBeNull()
  })
})
