import React, { useEffect, useState } from 'react'
import { useSearchParams } from 'react-router-dom'
import { ShieldCheck, UserCog, Lock } from 'lucide-react'
import { useAuth } from '../../hooks/useAuth.jsx'
import { currentOrg } from '../../lib/platformApi.js'
import OrgIdentityPage from './OrgIdentityPage.jsx'
import SecurityPage from './SecurityPage.jsx'

// Settings > IAM Setup — combines the old separate Identity (organisation
// owners/admins manage the people in their org) and Security (personal
// sign-in security) tabs into one place, each as its own sub-tab. Identity
// is only shown to organisation owners/admins (API enforces it too).
// A ?tab=security (or ?tab=identity) query param can force which sub-tab
// opens — used e.g. when a forced MFA/password-change redirect needs to
// land squarely on Security even for an org admin.
export default function IAMSetupPage() {
  const { user } = useAuth()
  const [role, setRole] = useState(null)
  const [searchParams] = useSearchParams()
  useEffect(() => { currentOrg().then(r => setRole(r.data.role)).catch(() => setRole(null)) }, [])
  const orgAdmin = ['owner', 'admin'].includes(role) || user?.is_admin

  const TABS = [
    { key: 'identity', label: 'Identity', icon: UserCog, visible: !!orgAdmin },
    { key: 'security', label: 'Security', icon: Lock, visible: true },
  ].filter(t => t.visible)

  const requested = searchParams.get('tab')
  const [tab, setTab] = useState((requested && TABS.find(t => t.key === requested)) ? requested : (orgAdmin ? 'identity' : 'security'))
  useEffect(() => { if (!TABS.find(t => t.key === tab) && TABS[0]) setTab(TABS[0].key) }, [TABS.map(t => t.key).join(',')])

  return (
    <div className="fade-in">
      <div style={{marginBottom:16}}>
        <div className="flex items-center gap-1">
          <ShieldCheck size={22} />
          <h2 style={{margin:0}}>IAM Setup</h2>
        </div>
        <p className="text-sm text-muted" style={{margin:'4px 0 0'}}>
          Manage who has access to this organisation and your own sign-in security.
        </p>
      </div>

      {TABS.length > 1 && (
        <div className="tabs-bar" style={{marginBottom:20}}>
          {TABS.map(t => (
            <button key={t.key} className={`tab-btn${tab===t.key?' active':''}`} onClick={()=>setTab(t.key)}>
              <t.icon size={14} style={{marginRight:5,verticalAlign:'-2px'}}/>{t.label}
            </button>
          ))}
        </div>
      )}

      {tab === 'identity' && orgAdmin && <OrgIdentityPage />}
      {tab === 'security' && <SecurityPage />}
    </div>
  )
}
