import React, { useState, useEffect } from 'react'
import { useSearchParams } from 'react-router-dom'
import { FolderKanban } from 'lucide-react'
import { ManagementTab, ClientsTab, WorkpapersTab, PortalTab, EngagementsTab, BillingTab, Gate } from '../../modules/practice/public.js'
import { useModuleVisibility } from '../hooks/useModuleVisibility.jsx'
import { tabsForDomain } from '../lib/modules.js'

const ALL_TABS = [
  { key:'management',  label:'🗂 Practice'     },
  { key:'clients',     label:'🏢 Clients'      },
  { key:'workpapers',  label:'📄 Workpapers'   },
  { key:'portal',      label:'🌐 Client Portal'},
  { key:'engagements', label:'📋 Engagements'  },
  { key:'billing',     label:'💵 Billing'      },
]

export default function PracticePage() {
  const { isModuleVisible } = useModuleVisibility()
  const TABS = tabsForDomain('practice', ALL_TABS, isModuleVisible)
  const [params, setParams] = useSearchParams()
  const valid = TABS.map(t => t.key)
  const fromUrl = params.get('tab')
  const [tab, setTabState] = useState(valid.includes(fromUrl) ? fromUrl : 'management')
  useEffect(() => { if (valid.includes(fromUrl) && fromUrl !== tab) setTabState(fromUrl) }, [fromUrl])
  const setTab = k => { setTabState(k); setParams({ tab: k }, { replace: true }) }

  // If an admin hides the module currently open (Admin > Modules), fall back to the first visible tab
  useEffect(() => {
    if (TABS.length && !TABS.some(t => t.key === tab)) setTab(TABS[0].key)
  }, [TABS.map(t => t.key).join(',')])

  return (
    <div className="fade-in">
      <div style={{marginBottom:16}}>
        <div className="flex items-center gap-1">
          <FolderKanban size={22} />
          <h2 style={{margin:0}}>Practice & Client Services</h2>
        </div>
        <p className="text-sm text-muted" style={{margin:'4px 0 0'}}>
          Clients, workpapers, engagements, the client portal and billing for your practice
        </p>
      </div>

      <div className="tabs-bar" style={{marginBottom:0, flexWrap:'nowrap', overflowX:'auto'}}>
        {TABS.map(t => (
          <button key={t.key} className={`tab-btn${tab===t.key?' active':''}`} onClick={() => setTab(t.key)}>
            {t.label}
          </button>
        ))}
      </div>

      <div style={{background:'var(--surface)',border:'1px solid var(--border)',
        borderTop:'none',borderRadius:'0 0 var(--r-lg) var(--r-lg)',
        minHeight:400,overflow:'hidden',boxShadow:'var(--sh-sm)'}}>
        <Gate>{can => <>
          {tab === 'management'  && <ManagementTab can={can} />}
          {tab === 'clients'     && <ClientsTab can={can} />}
          {tab === 'workpapers'  && <WorkpapersTab can={can} />}
          {tab === 'portal'      && <PortalTab can={can} />}
          {tab === 'engagements' && <EngagementsTab can={can} />}
          {tab === 'billing'     && <BillingTab can={can} />}
        </>}</Gate>
      </div>
    </div>
  )
}
