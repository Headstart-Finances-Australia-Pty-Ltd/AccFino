import React from 'react'
import { Landmark } from 'lucide-react'
import BasiqPlatformSetup from '../../components/openbanking/BasiqPlatformSetup.jsx'
import OpenFeedPlatformSetup from '../../components/openbanking/OpenFeedPlatformSetup.jsx'

/** Admin Console > Open Banking: platform set-up for both bank-feed providers. Clients only ever use Settings > Open Banking. */
export default function OpenBankingSetupPage() {
  return (
    <div data-testid="open-banking-setup">
      <div style={{ marginBottom: 16 }}>
        <div className="flex items-center gap-1"><Landmark size={22} /><h2 style={{ margin: 0 }}>Open Banking set-up</h2></div>
        <p className="text-sm text-muted" style={{ margin: '4px 0 0' }}>
          Set up each bank-feed provider once for the whole platform. Afterwards organisations connect their own accounts from Settings &gt; Open Banking,
          with no accounts or keys of their own to create.
        </p>
      </div>
      <BasiqPlatformSetup />
      <OpenFeedPlatformSetup />
    </div>
  )
}
