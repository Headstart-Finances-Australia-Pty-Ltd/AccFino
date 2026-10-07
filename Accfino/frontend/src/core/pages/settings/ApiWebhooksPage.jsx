import React, { useEffect, useState } from 'react'
import { Webhook, Landmark, CreditCard } from 'lucide-react'
import { BankAccountPanel } from '../../../modules/billing/public.js'
import { SquarePanel } from '../../../modules/billing/public.js'
import { StripePanel } from '../../../modules/billing/public.js'
import ComingSoonTab from '../../components/layout/ComingSoonTab.jsx'
import { useModuleVisibility } from '../../hooks/useModuleVisibility.jsx'

// Settings > Payment Setup (formerly "API & Webhooks"). Square's setup moved
// here from Settings > Open Banking, and Stripe is also configurable here,
// since both are card-payment gateways your org uses to collect money from
// its own customers (e.g. on invoices) rather than bank feeds. This is
// distinct from Admin > Payment Card Setup (Square/Stripe), which is
// AccFino's own gateway for charging your org its platform subscription fee
// — each has its own module id in Admin > Modules Management, so e.g. Stripe
// can be switched off there while staying available here. Bank Account is
// the org's own outgoing account — used for invoice payments the org makes
// and refunds — not a togglable gateway. General developer API keys +
// webhooks are still on the roadmap.
const ALL_TABS = [
  { key:'bank',   label:'Bank Account', icon:Landmark },
  { key:'square', label:'Square',       icon:CreditCard, moduleId:'square-open-banking' },
  { key:'stripe', label:'Stripe',       icon:CreditCard, moduleId:'stripe-payments' },
]

export default function ApiWebhooksPage() {
  const { isModuleVisible } = useModuleVisibility()
  const TABS = ALL_TABS.filter(t => !t.moduleId || isModuleVisible(t.moduleId))
  const [tab, setTabState] = useState('bank')
  const setTab = k => setTabState(k)
  useEffect(() => { if (!TABS.find(t => t.key === tab) && TABS[0]) setTab(TABS[0].key) }, [TABS.map(t => t.key).join(',')])

  return (
    <div className="fade-in">
      <div style={{marginBottom:16}}>
        <div className="flex items-center gap-1">
          <Webhook size={22} />
          <h2 style={{margin:0}}>Payment Setup</h2>
        </div>
        <p className="text-sm text-muted" style={{margin:'4px 0 0'}}>
          Set up your outgoing bank account and connect Square and Stripe to collect payments from your customers.
        </p>
      </div>

      <div className="tabs-bar" style={{marginBottom:20, flexWrap:'nowrap', overflowX:'auto'}}>
        {TABS.map(t => (
          <button key={t.key} className={`tab-btn${tab===t.key?' active':''}`} onClick={()=>setTab(t.key)}>
            <t.icon size={14} style={{marginRight:5,verticalAlign:'-2px'}}/>{t.label}
          </button>
        ))}
      </div>

      {tab === 'bank'   && <BankAccountPanel />}
      {tab === 'square' && <SquarePanel />}
      {tab === 'stripe' && <StripePanel />}

      <div style={{marginTop:24}}>
        <ComingSoonTab emoji="🔌" name="Developer API Keys & Webhooks" phase="Later" blurb="Personal API keys and webhooks for building on your own data." />
      </div>
    </div>
  )
}
