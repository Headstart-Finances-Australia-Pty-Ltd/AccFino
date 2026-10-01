// Shared factory for mocking lib/booksApi.js across the Phase 1 page render tests, so every
// network call resolves to an empty-but-valid response without a running backend.
//
// IMPORTANT: vi.mock(path, factory) must be called directly, at the top level, in each *.test.jsx
// file for Vitest to hoist it above that file's own imports - wrapping the call itself inside a
// helper function (and invoking the helper from the test file) defeats the hoisting and silently
// leaves the real module in place. Only the FACTORY is shared here; each test file still writes
// `vi.mock('../../lib/booksApi.js', booksApiMockFactory)` itself.
import { vi } from 'vitest'

export async function booksApiMockFactory() {
  const actual = await vi.importActual('../../../lib/booksApi.js')
  const emptyList = () => Promise.resolve({ data: { items: [], total: 0 } })
  const emptyArray = () => Promise.resolve({ data: [] })
  return {
    ...actual,
    ledgerAccounts: vi.fn(emptyArray),
    taxCodes: vi.fn(emptyArray),
    bankAccounts: vi.fn(emptyList),
    listContacts: vi.fn(emptyList),
    listDocs: vi.fn(emptyList),
    listPayments: vi.fn(emptyList),
    listBankLines: vi.fn(emptyList),
    listRules: vi.fn(emptyList),
    createBankAccount: vi.fn(() => Promise.resolve({ data: { id: 99 } })),
    createRule: vi.fn(() => Promise.resolve({ data: { id: 1 } })),
    createContact: vi.fn(() => Promise.resolve({ data: { id: 1 } })),
    createDoc: vi.fn(() => Promise.resolve({ data: { id: 1 } })),
    createClaim: vi.fn(() => Promise.resolve({ data: { id: 1 } })),
    listClaims: vi.fn(emptyList),
    claimsSummary: vi.fn(() => Promise.resolve({ data: { by_status: {} } })),
    salesReport: vi.fn(() => Promise.resolve({ data: { contacts: [], buckets: {}, total: '0.00', control: { reconciled: true, difference: '0.00' } } })),
    purchasesReport: vi.fn(() => Promise.resolve({ data: { contacts: [], buckets: {}, total: '0.00', control: { reconciled: true, difference: '0.00' } } })),
    ledgerReport: vi.fn((path) => Promise.resolve({ data: path === 'gst-summary'
      ? { basis: 'accrual', fields: {}, gst_on_sales_1A: '0.00', gst_on_purchases_1B: '0.00', net_gst_payable: '0.00', ledger_check: { reconciled: true, difference: '0.00' } }
      : path === 'cash-flow'
      ? { operating: { net_profit: '0.00', adjustments: [], total: '0.00' }, investing: { items: [], total: '0.00' }, financing: { items: [], total: '0.00' },
          net_change_in_cash: '0.00', opening_cash: '0.00', closing_cash: '0.00', reconciled: true, difference: '0.00' }
      : path === 'subledger-control'
      ? { receivables: { ledger_balance: '0.00', subledger_total: '0.00', difference: '0.00', reconciled: true }, payables: { ledger_balance: '0.00', subledger_total: '0.00', difference: '0.00', reconciled: true } }
      : {} })),
  }
}
