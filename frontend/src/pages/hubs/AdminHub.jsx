import React from 'react'
import { ShieldCheck, KeyRound, BadgeCheck, FolderOpen, DollarSign, LayoutGrid, CreditCard } from 'lucide-react'
import TabHub from './TabHub.jsx'

// Admin - AccFino super admin team only (route is guarded with <Guard adminOnly>)
// Note: Platform Users now lives inside the "Users & Licence" tab (see LicencePage.jsx),
// and Company DB was removed - it's covered by Data Manager and Settings > Setup > Knowledgebase.
export default function AdminHub() {
  return <TabHub title="Admin" icon={ShieldCheck} note="AccFino super admin team only" tabs={[
    { to: 'api-keys', label: 'API Keys', icon: KeyRound },
    { to: 'licence', label: 'Users & Licence', icon: BadgeCheck },
    { to: 'file-manager', label: 'Data Manager', icon: FolderOpen },
    { to: 'payments', label: 'Payment Card Setup', icon: CreditCard },
    { to: 'pricing', label: 'Pricing', icon: DollarSign },
    { to: 'modules', label: 'Modules Management', icon: LayoutGrid },
  ]} />
}
