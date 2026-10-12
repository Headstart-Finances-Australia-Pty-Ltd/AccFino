import React from 'react'
import { Settings, ShieldCheck, SlidersHorizontal, Link2, Webhook, Landmark } from 'lucide-react'
import TabHub from './TabHub.jsx'

// Settings (every user): Business Setup (Organisation lives here as its first
// sub-tab, before Business Account — see SetupPage.jsx) · IAM Setup (Identity +
// Security, combined into one tab with its own sub-tabs — see IAMSetupPage.jsx) ·
// Open Banking · Integrations · Payment Setup (formerly "API & Webhooks" — bank
// account, Square and Stripe, i.e. how an org collects/pays money, not developer
// API keys) — account/platform-level items parked here rather than given their
// own business domain or duplicated under a workflow domain. Kept to a single
// row (see TabHub.jsx).
export default function SettingsHub() {
  return <TabHub title="Settings" icon={Settings} tabs={[
    { to: 'setup', label: 'Business Setup', icon: SlidersHorizontal },
    { to: 'iam', label: 'IAM Setup', icon: ShieldCheck },
    { to: 'open-banking', label: 'Open Banking', icon: Landmark },
    { to: 'integrations', label: 'Integrations', icon: Link2 },
    { to: 'api-webhooks', label: 'Payment Setup', icon: Webhook },
  ]} />
}
