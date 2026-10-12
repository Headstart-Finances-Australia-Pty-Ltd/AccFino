// Public surface of the accounting module: the ONLY file other modules (and Core's settings/admin composition pages) may import from it.
// Generated from the real cross-module usages; add an export here deliberately when another module genuinely needs something.
export { AccountsTab } from './pages/ledger/LedgerPage.jsx'
export * as ns_ledgerApi from './lib/ledgerApi.js'
