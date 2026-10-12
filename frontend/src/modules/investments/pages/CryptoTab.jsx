import React from 'react'
import InvestTab from './InvestTab.jsx'

export default function CryptoTab({ me, analyser }) {
  return (
    <InvestTab me={me} kinds={['crypto']} swap
      intro="Each token is its own CGT asset. Sells, swaps (including stablecoins) and spending are CGT events; staking and airdrops are income at the AUD value on receipt and set the cost base; moving tokens between your own wallets is not a disposal. FIFO is the default parcel method."
      importKeys={[{ key: 'crypto_exchange', label: 'Crypto exchange export' }, { key: 'transactions', label: 'Transactions (AccFino standard layout)' }]}
      secKeys={[{ key: 'securities', label: 'Tokens' }, { key: 'accounts', label: 'Accounts and wallets' }, { key: 'prices', label: 'Prices' }]}
      extraViews={analyser ? [{ key: 'analyse', label: 'Analyse an exchange file', render: () => <div style={{ margin: '-16px' }}>{analyser}</div> }] : []} />)
}
