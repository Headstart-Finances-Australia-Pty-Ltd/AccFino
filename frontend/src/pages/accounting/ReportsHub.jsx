import React, { useState } from 'react'
import { ReportsTab } from '../ledger/LedgerPage.jsx'
import BooksReportsPage from './BooksReportsPage.jsx'

// One Reports tab for the organisation, all computed from its posted ledger journals:
//   Financial statements  - Trial Balance, Profit & Loss, Balance Sheet, Account Transactions
//   Sales, purchases & tax - Aged Receivables/Payables, GST/BAS, Cash Flow, by customer/supplier, control check
const GROUPS = [
  ['statements', 'Financial Statements'],
  ['operational', 'Receivables, Payables, GST & Cash Flow'],
]

export default function ReportsHub() {
  const [group, setGroup] = useState('statements')
  return (
    <div className="fade-in" style={{ padding: 24 }}>
      <div className="tabs-bar" style={{ marginBottom: 16 }}>
        {GROUPS.map(([k, l]) => (
          <button key={k} className={`tab-btn${group === k ? ' active' : ''}`} onClick={() => setGroup(k)}>{l}</button>
        ))}
      </div>
      {group === 'statements' && <ReportsTab />}
      {group === 'operational' && <BooksReportsPage />}
    </div>
  )
}
