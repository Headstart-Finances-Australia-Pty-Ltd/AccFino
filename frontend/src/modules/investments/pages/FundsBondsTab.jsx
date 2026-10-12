import React from 'react'
import InvestTab from './InvestTab.jsx'

export default function FundsBondsTab({ me }) {
  return (
    <InvestTab me={me} kinds={['managed_fund', 'bond', 'term_deposit']}
      intro="Managed funds, bonds and term deposits. Record distributions with the components from the distribution or AMMA statement: tax-deferred amounts and the AMIT cost base net amount adjust the cost base. Open a bond to see accrued interest, yield to maturity, duration and the remaining cash flows."
      importKeys={[{ key: 'fund_distributions', label: 'Fund distributions (from AMMA / distribution statements)' }, { key: 'transactions', label: 'Transactions (AccFino standard layout)' }]}
      secKeys={[{ key: 'securities', label: 'Funds, bonds and term deposits' }, { key: 'accounts', label: 'Accounts and platforms' }, { key: 'prices', label: 'Prices' }]} />)
}
