// Public surface of the Investments frontend module: the ONLY import path other parts of the app may use.
export { default as SharesTab } from './pages/SharesTab.jsx'
export { default as CryptoTab } from './pages/CryptoTab.jsx'
export { default as FundsBondsTab } from './pages/FundsBondsTab.jsx'
export { default as PropertyTab } from './pages/PropertyTab.jsx'
export { default as PortfolioTab } from './pages/PortfolioTab.jsx'
export { default as NetWorthTab } from './pages/NetWorthTab.jsx'
export { me as invMe } from './lib/invApi.js'
