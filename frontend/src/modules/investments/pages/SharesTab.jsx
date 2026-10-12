import React from 'react'
import InvestTab from './InvestTab.jsx'

// `analyser` is the broker statement analyser, handed in by the hub (another module's screen: this module never imports it).
export default function SharesTab({ me, analyser }) {
  return (
    <InvestTab me={me} kinds={['share', 'etf']}
      intro="Listed shares and ETFs: every purchase, sale, dividend, reinvestment, split and bonus issue. Brokerage is part of the cost base; each parcel keeps its own date for the 12-month discount; franking credits are tracked."
      importKeys={[{ key: 'broker_trades', label: 'Broker trades (contract notes)' }, { key: 'transactions', label: 'Transactions (AccFino standard layout)' }, { key: 'fund_distributions', label: 'ETF distributions (from AMMA / distribution statements)' }]}
      secKeys={[{ key: 'securities', label: 'Securities' }, { key: 'accounts', label: 'Accounts' }, { key: 'prices', label: 'Prices' }]}
      extraViews={analyser ? [{ key: 'analyse', label: 'Analyse a broker statement', render: () => <div style={{ margin: '-16px' }}>{analyser}</div> }] : []} />)
}
