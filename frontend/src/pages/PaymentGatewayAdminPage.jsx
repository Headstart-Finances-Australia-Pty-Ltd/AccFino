import React, { useEffect, useState } from 'react'
import { CreditCard } from 'lucide-react'
import { useModuleVisibility } from '../hooks/useModuleVisibility.jsx'
import SquarePanel from '../components/payments/SquarePanel.jsx'
import StripePanel from '../components/payments/StripePanel.jsx'

// Admin > Payment Card Setup (formerly "Subscription Billing") - the card
// payment gateways AccFino uses to charge orgs their platform subscription/
// licence fee: Square and Stripe. (Stride has been removed.) Not to be
// confused with Settings > Payment Setup (formerly "API & Webhooks"), which
// is where an org connects its OWN Stripe/Square account to collect card
// payments from its own customers — each gateway here has its own module id
// (see Admin > Modules Management) so it can be switched on/off
// independently of its Settings counterpart, e.g. Stripe can stay available
// in Settings for orgs to use while switched off here.
const GATEWAY_TABS = [
  { key:'square', label:'Square', moduleId:'square-admin-payments' },
  { key:'stripe', label:'Stripe', moduleId:'stripe-admin-payments' },
]

export default function PaymentGatewayAdminPage({ embedded = false }) {
  const { isModuleVisible } = useModuleVisibility()
  const TABS = GATEWAY_TABS.filter(t => isModuleVisible(t.moduleId))
  const [tab, setTabState] = useState('square')
  const setTab = k => setTabState(k)
  useEffect(() => { if (!TABS.find(t => t.key === tab) && TABS[0]) setTab(TABS[0].key) }, [TABS.map(t => t.key).join(',')])

  return (
    <div className="fade-in">
      <div style={{marginBottom:16}}>
        {!embedded && <div className="flex items-center gap-1">
          <CreditCard size={22} />
          <h2 style={{margin:0}}>Payment Card Setup</h2>
        </div>}
        <p className="text-sm text-muted" style={{margin:'4px 0 0'}}>
          Configure the card payment gateway(s) AccFino uses to charge orgs their platform subscription/licence
          fee — Square and/or Stripe. This is separate from Settings &gt; Payment Setup, where an org connects
          its own Stripe/Square account to collect payments from its own customers.
        </p>
      </div>

      {TABS.length === 0 && (
        <div className="alert alert-warning">
          ⚠️ Every payment gateway here is currently switched off in Admin &gt; Modules Management. Turn at
          least one back on there to configure it.
        </div>
      )}

      {TABS.length > 0 && (
        <div className="tabs-bar" style={{marginBottom:20, flexWrap:'nowrap', overflowX:'auto'}}>
          {TABS.map(t => (
            <button key={t.key} className={`tab-btn${tab===t.key?' active':''}`} onClick={()=>setTab(t.key)}>{t.label}</button>
          ))}
        </div>
      )}

      {tab==='square' && <SquarePanel/>}
      {tab==='stripe' && <StripePanel/>}
    </div>
  )
}
