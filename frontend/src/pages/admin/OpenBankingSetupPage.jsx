import React from 'react'
import { Landmark } from 'lucide-react'
import BasiqPlatformSetup from '../../components/openbanking/BasiqPlatformSetup.jsx'
import OpenFeedPlatformSetup from '../../components/openbanking/OpenFeedPlatformSetup.jsx'
import { useModuleVisibility } from '../../hooks/useModuleVisibility.jsx'

/** Admin Console > API Keys > Open Banking: platform set-up for both bank-feed providers. Clients only ever use Settings > Open Banking. */
export default function OpenBankingSetupPage({ embedded = false }) {
  const { isModuleVisible } = useModuleVisibility()          // each provider can be switched on/off in Admin > Modules Management > Admin Console
  return (
    <div data-testid="open-banking-setup">
      <div style={{ marginBottom: 16 }}>
        {!embedded && <div className="flex items-center gap-1"><Landmark size={22} /><h2 style={{ margin: 0 }}>Open Banking set-up</h2></div>}
        <p className="text-sm text-muted" style={{ margin: '4px 0 0' }}>
          Set up each bank-feed provider once for the whole platform. Afterwards organisations connect their own accounts from Settings &gt; Open Banking,
          with no accounts or keys of their own to create.
        </p>
      </div>
      {isModuleVisible('basiq-admin-open-banking') && <BasiqPlatformSetup />}
      {isModuleVisible('openfeed-admin-open-banking') && <OpenFeedPlatformSetup />}
    </div>
  )
}
