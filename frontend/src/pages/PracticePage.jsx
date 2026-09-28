import React, { useState, useEffect } from 'react'
import { useSearchParams } from 'react-router-dom'
import { FolderKanban } from 'lucide-react'
import ComingSoonTab from '../components/layout/ComingSoonTab.jsx'
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
          Tools for accountants and tax agents managing clients — all on the roadmap
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
        {tab === 'management'  && <ComingSoonTab emoji="🗂" name="Practice Management" phase="Phase 4" blurb="Multi-client dashboard for accountants and tax agents."/>}
        {tab === 'clients'     && <ComingSoonTab emoji="🏢" name="Clients & Entities" phase="Phase 4" blurb="Client and entity register with structures and contacts."/>}
        {tab === 'workpapers'  && <ComingSoonTab emoji="📄" name="Workpapers & Documents" phase="Phase 4" blurb="Workpapers, evidence and document storage per client."/>}
        {tab === 'portal'      && <ComingSoonTab emoji="🌐" name="Client Portal" phase="Later" blurb="Self-service portal for clients to upload documents and view status."/>}
        {tab === 'engagements' && <ComingSoonTab emoji="📋" name="Engagements & Workflows" phase="Later" blurb="Engagement tracking, jobs and lodgement deadlines."/>}
        {tab === 'billing'     && <ComingSoonTab emoji="💵" name="Billing" phase="Later" blurb="Time recording and client invoicing for the practice."/>}
      </div>
    </div>
  )
}
