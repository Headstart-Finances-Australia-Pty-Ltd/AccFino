import TopBar from '../ui/TopBar.jsx'
import React, { useState, useEffect, Suspense } from 'react'
import { Outlet, NavLink, useNavigate, useLocation } from 'react-router-dom'
import { useAuth } from '../../hooks/useAuth.jsx'
import UpgradeBanner from '../UpgradeBanner.jsx'
import { licenceMyModules, getMyPlan } from '../../lib/api.js'
import { useModuleVisibility } from '../../hooks/useModuleVisibility.jsx'
import useOrgRole from '../../hooks/useOrgRole.jsx'
import { ProfileCard } from '../../pages/MyAccountPage.jsx'
import PlanGate from '../subscription/PlanGate.jsx'
import { me as fetchMe } from '../../lib/platformApi.js'
import { domainGroups, hrefOf, activeLeafId, domainForLocation, visibleGroups } from '../../lib/modules.js'
import { Building2, LayoutDashboard, ArrowLeftRight, TrendingUp, BarChart2, FileText, ShieldCheck, ChevronLeft, ChevronRight, FolderOpen, BadgeCheck, Settings, Cpu, BookOpen, DollarSign, Users, Landmark, Building, Lock, UserCog, LineChart,
  Receipt, ShoppingCart, FileBarChart, CheckCircle2, Send, Upload, Home, Wallet, Target } from 'lucide-react'

// ── Reconciliation session context — persists across route navigation ─────────
export const ReconciliationContext = React.createContext(null)

// Side panel entries come from the module registry (src/config/modules.json), grouped by domain.
const ICONS = { BookOpen, Landmark, TrendingUp, Users, FileText, LineChart, DollarSign, ArrowLeftRight, Receipt,
  ShoppingCart, FileBarChart, CheckCircle2, Send, Upload, Home, Wallet, Target, ShieldCheck, FolderOpen, Lock }
const HOME = { to:'/', icon:LayoutDashboard, label:'Overview', sub:'Modules & Plan', key:'dashboard' }

// Settings holds ORGANISATION-level administration (organisation details, users, access codes, licence, security policy...), so it is shown ONLY to the
// Organisation Admin - the server refuses everyone else on every one of those endpoints regardless of what is shown here. Every user gets My Account
// (their own name, email, phone, password and sign-in security). Admin is its own section, visible to the AccFino super admin team only.
const SETTINGS_ITEM = { to:'/settings', icon:Settings,    label:'Settings',       sub:'Organisation · Users · Access codes · Licence · IAM · Integrations', key:'settings' }
const MY_ACCOUNT_ITEM = { to:'/my-account', icon:UserCog,  label:'My Account',     sub:'My details · Password · Sign-in security', key:'my-account' }
const ADMIN_ITEM    = { to:'/admin',    icon:ShieldCheck, label:'Admin Console',  sub:'ML · Licences · Files · Pricing · Users',        key:'admin'    }

export default function Layout() {
  const { user, logout } = useAuth()
  const nav = useNavigate()
  const loc = useLocation()
  const [col,            setCol]           = useState(false)
  const [allowedModules, setAllowedModules] = useState(null)
  const [myPlan,         setMyPlan]        = useState(null)
  const [openDomainId,   setOpenDomainId]  = useState(null)
  const { isDomainVisible, isModuleVisible } = useModuleVisibility()
  const { isOrgAdmin, org: myOrg } = useOrgRole()
  const [needsProfile, setNeedsProfile] = useState(!!user?.profile_incomplete)

  const fetchModules = () => {
    if (!user) return
    const isAdmin = Array.isArray(user.roles) && user.roles.includes('admin')
    if (isAdmin || !user.id) { setAllowedModules('all'); return }
    // Always fetch fresh from API — never use cached value
    licenceMyModules(user.id)
      .then(r => setAllowedModules(r.data.modules || ['dashboard','reconciliation']))
      .catch(() => setAllowedModules(['dashboard','reconciliation']))
  }

  // The visibility provider mounts before sign-in; ask it to read this organisation's subscription now that we are signed in
  useEffect(() => { window.dispatchEvent(new Event('accfino:subscription-changed')) }, [])
  useEffect(() => {
    fetchModules()
    // Re-fetch when admin saves licence changes
    window.addEventListener('accfino:modules-changed', fetchModules)
    return () => window.removeEventListener('accfino:modules-changed', fetchModules)
  }, [user?.id])

  useEffect(() => {
    if (!user?.id) return
    getMyPlan(user.id).then(r => setMyPlan(r.data)).catch(() => {})
    window.addEventListener('accfino:modules-changed', () =>
      getMyPlan(user.id).then(r => setMyPlan(r.data)).catch(() => {})
    )
  }, [user?.id])

  // Phase 0: when MFA is enforced platform-wide, users must enrol before anything else
  useEffect(() => {
    if ((user?.mfa_required_to_enrol || user?.password_change_required) && loc.pathname !== '/my-account') nav('/my-account?tab=security', { replace: true })
  }, [user?.mfa_required_to_enrol, user?.password_change_required, loc.pathname])

  // Every account needs a valid email AND phone number. Accounts that pre-date the rule are asked to add what is missing before using the app
  // (the server enforces the same thing: until the profile is complete it only allows the profile, security and sign-out endpoints).
  useEffect(() => {
    if (!user?.id) return
    fetchMe().then(r => setNeedsProfile(r.data.profile_complete === false)).catch(() => {})
    const sync = () => { try { setNeedsProfile(!!JSON.parse(localStorage.getItem('af_user'))?.profile_incomplete) } catch {} }
    window.addEventListener('accfino:session-updated', sync)
    return () => window.removeEventListener('accfino:session-updated', sync)
  }, [user?.id])

  // Which domain owns the currently active route — keeps that domain's dropdown open as you navigate.
  const currentDomainId = domainForLocation(loc)
  useEffect(() => { setOpenDomainId(currentDomainId) }, [currentDomainId])

  const isAdmin = (Array.isArray(user?.roles) && user.roles.includes('admin')) || user?.is_admin === true

  const canAccess = (moduleKey) => {
    if (moduleKey === 'setup') return true        // Control Panel always accessible
    if (moduleKey === 'accounting') return true   // Accounting always accessible — Reconciliation is free for all
    if (moduleKey === 'lending')     return true   // Smart Lending always accessible
    if (moduleKey === 'ledger')      return true   // Phase 0: General Ledger available to every organisation
    if (moduleKey === 'dashboard') return true    // Overview always accessible
    if (isAdmin) return true
    if (allowedModules === null) return false     // still loading
    if (allowedModules === 'all') return true
    return allowedModules.includes(moduleKey)
  }

  const initials = (user?.name || user?.email || 'U').split(' ').map(w => w[0]).join('').slice(0,2).toUpperCase()
  const userName = user?.name || user?.email || ''
  const pageName = loc.pathname === '/' ? 'Overview' : loc.pathname.slice(1).split('/').filter(Boolean)
    .map(p => p.replace(/-/g,' ').replace(/\b\w/g, c => c.toUpperCase()).replace(/^Ml /, 'ML ')).join(' · ')

  // ── Reconciliation state — kept in Layout so it survives navigation ──────
  const [reconTransactions,   setReconTransactions]   = useState(null)
  const [reconSummary,        setReconSummary]        = useState([])
  const [reconSessionId,      setReconSessionId]      = useState(null)
  const [reconAccounts,       setReconAccounts]       = useState([])
  const [reconMainTab,        setReconMainTab]        = useState('input')

  // Resets all reconciliation state — called by DashboardPage when a session
  // is deleted so the Reconciliation page does not show stale data.
  const resetRecon = React.useCallback((sessionIdToReset) => {
    setReconSessionId(prev => {
      // Only reset if the deleted session matches what's currently loaded,
      // or if no specific session was provided (reset unconditionally).
      if (sessionIdToReset && prev !== sessionIdToReset) return prev
      setReconTransactions(null)
      setReconSummary([])
      setReconAccounts([])
      setReconMainTab('input')
      return null
    })
  }, [])

  const reconCtx = {
    transactions:    reconTransactions,  setTransactions:   setReconTransactions,
    monthlySummary:  reconSummary,       setMonthlySummary: setReconSummary,
    sessionId:       reconSessionId,     setSessionId:      setReconSessionId,
    accounts:        reconAccounts,      setAccounts:       setReconAccounts,
    mainTab:         reconMainTab,       setMainTab:        setReconMainTab,
    resetRecon,
  }

  const handleLogout = () => {
    try { logout(); nav('/login') }
    catch { localStorage.removeItem('af_user'); window.location.href = '/login' }
  }

  return (
    <>
    <UpgradeBanner />
    <div style={{display:'flex', minHeight:'100vh', background:'var(--bg)'}}>
      <aside style={{
        width:col ? 'var(--sidebar-w-sm)' : 'var(--sidebar-w)', height:'100vh', flexShrink:0,
        position:'sticky', top:0, display:'flex', flexDirection:'column',
        background:'#0D1117',
        transition:'width .22s cubic-bezier(.4,0,.2,1)', overflow:'hidden',
      }}>
        <div style={{position:'absolute', inset:0, pointerEvents:'none',
          backgroundImage:'radial-gradient(circle at 80% 20%,rgba(200,150,62,.08) 0%,transparent 60%)'}}/>

        {/* Logo */}
        <div style={{padding:col ? '18px 12px' : '18px 16px', borderBottom:'3px solid rgba(255,255,255,0.12)',
          display:'flex', alignItems:'center', minHeight:'var(--header-h)', position:'relative', zIndex:1}}>
          <div style={{display:'flex', alignItems:'center', gap:9, textDecoration:'none'}}>
            <div style={{
              width:35, height:35, borderRadius:12, flexShrink:0,
              background:'linear-gradient(135deg,#C8963E 0%,#E8B86D 100%)',
              display:'flex', alignItems:'center', justifyContent:'center',
              boxShadow:'0 2px 10px rgba(200,150,62,.4)',
            }}>
              <svg width="20" height="20" viewBox="0 0 40 40" fill="none">
                <rect x="8"  y="28" width="5" height="16" rx="2" transform="rotate(-30 8 28)" fill="white" opacity="0.9"/>
                <rect x="27" y="9"  width="5" height="16" rx="2" transform="rotate(30 27 9)"  fill="white" opacity="0.9"/>
                <rect x="12" y="23" width="16" height="4" rx="2" fill="#FF6B35"/>
                <path d="M20 7 L24 13 H22 V18 H18 V13 H16 Z" fill="#FF6B35"/>
              </svg>
            </div>
            {!col && <span style={{
              fontFamily:"'Instrument Serif', serif",
              fontSize:'1.35rem', color:'#fff', letterSpacing:'-.01em',
            }}>Acc<span style={{color:'#FF6B35'}}>Fino</span></span>}
          </div>
        </div>

        {/* Nav */}
        {/* minHeight:0 lets this flex child shrink so the menu scrolls inside the fixed-height panel */}
        {/* Which organisation am I in, and where do people sign in? Shown to every member, at the TOP of the menu so it is always visible. */}
        {!col && myOrg?.name && (
          <div data-testid="org-address" style={{padding:'8px 14px', borderBottom:'1px solid rgba(255,255,255,.08)', fontSize:'.68rem', lineHeight:1.4, color:'rgba(255,255,255,.7)', wordBreak:'break-all'}}>
            <div style={{fontWeight:600, color:'#fff', fontSize:'.78rem'}}>{myOrg.name}</div>
            {myOrg.tenant_url ? <a href={myOrg.tenant_url} style={{color:'#E8B86D', textDecoration:'underline'}}>{myOrg.tenant_url.replace(/^https?:\/\//, '')}</a> : null}
          </div>)}

        <nav className="sidebar-scroll" style={{flex:1, minHeight:0, padding:col ? '12px 6px' : '12px 10px', display:'flex', flexDirection:'column',
          gap:2, overflowY:'auto', overflowX:'hidden', position:'relative', zIndex:1}}>
          {(() => {
            const SectionLabel = ({ text, first }) => (
              <div style={{
                fontSize:'.68rem', fontWeight:700, color:'rgba(255,255,255,.4)',
                letterSpacing:'.08em', textTransform:'uppercase',
                padding: col ? '10px 0 4px' : '10px 12px 4px',
                marginTop: first ? 0 : 6, borderTop: first ? 'none' : '1px solid rgba(255,255,255,.08)',
              }}>
                {!col && text}
              </div>
            )

            const overviewBody = <>
              <LayoutDashboard size={23} strokeWidth={1.8} style={{flexShrink:0}}/>
              {!col && <div style={{minWidth:0}}>
                <div style={{fontSize:'.8rem', fontWeight:600, lineHeight:1.2}}>{HOME.label}</div>
                <div style={{fontSize:'.6rem', opacity:.55, lineHeight:1.3, marginTop:1}}>{HOME.sub}</div>
              </div>}
            </>

            const simpleLink = ({ to, icon:Icon, label, sub }) => (
              <NavLink key={to} to={to} title={col ? label : undefined}
                className={({isActive}) => `nav-item${isActive ? ' active' : ''}`}>
                <Icon size={23} strokeWidth={1.8} style={{flexShrink:0}}/>
                {!col && <div style={{minWidth:0}}>
                  <div style={{fontSize:'.8rem', fontWeight:600, lineHeight:1.2}}>{label}</div>
                  <div style={{fontSize:'.6rem', opacity:.55, lineHeight:1.3, marginTop:1}}>{sub}</div>
                </div>}
              </NavLink>
            )

            // A single business/supporting domain row — click to expand/collapse its list of
            // modules. A domain marked expandable:false is a single link straight to its own
            // page, which shows all of that domain's modules as tabs (e.g. Accounting).
            const renderDomain = ({ domain, items }) => {
              const DomainIcon = ICONS[domain.icon] || BookOpen
              const isCurrentDomain = domain.id === currentDomainId
              const isOpen = openDomainId === domain.id
              const activeId = activeLeafId(items, loc)

              if (domain.expandable === false) {
                const landing = items.find(i => i.route) || items[0]
                return (
                  <NavLink key={domain.id} to={landing.route} title={col ? domain.name : undefined}
                    data-testid={`domain-${domain.id}`}
                    className={({isActive}) => `nav-item domain-row${isActive ? ' active' : ''}`}>
                    <DomainIcon size={20} strokeWidth={1.8} style={{flexShrink:0}}/>
                    {!col && <div style={{minWidth:0}}>
                      <div className="domain-row-label">{domain.name}</div>
                      {domain.tagline && <div className="domain-row-tagline">{domain.tagline}</div>}
                    </div>}
                  </NavLink>
                )
              }

              const handleDomainClick = () => {
                if (col) {
                  // Collapsed rail: no room to expand — jump straight to the domain's first available module
                  const target = items.find(m => m.status !== 'planned' && canAccess(m.licence)) || items.find(m => m.status !== 'planned')
                  if (target) nav(hrefOf(target))
                  return
                }
                setOpenDomainId(prev => prev === domain.id ? null : domain.id)
              }

              return (
                <div key={domain.id} className="domain-group">
                  <button type="button" title={col ? domain.name : undefined} data-testid={`domain-${domain.id}`}
                    onClick={handleDomainClick} className={`nav-item domain-row${isCurrentDomain ? ' active' : ''}${isOpen ? ' open' : ''}`}>
                    <DomainIcon size={20} strokeWidth={1.8} style={{flexShrink:0}}/>
                    {!col && <span className="domain-row-label">{domain.name}</span>}
                    {!col && <ChevronRight size={14} strokeWidth={2} className="domain-chevron"
                      style={{transform: isOpen ? 'rotate(90deg)' : 'none'}}/>}
                  </button>

                  {!col && isOpen && (
                    <div className="domain-submenu" data-testid={`domain-submenu-${domain.id}`}>
                      {items.map(leaf => {
                        const planned = leaf.status === 'planned'
                        const allowed = !planned && canAccess(leaf.licence)
                        const isLeafActive = activeId === leaf.id

                        if (planned || !allowed) return (
                          <div key={leaf.id} className="nav-subitem disabled"
                            title={planned ? `Coming ${leaf.phase ? 'in ' + leaf.phase : 'soon'}` : '🔒 Not in your plan'}>
                            <span className="nav-subitem-dot"/>
                            <span className="nav-subitem-label">{leaf.name}</span>
                            {planned && <span className="soon-tag">Soon</span>}
                            {!planned && !allowed && <Lock size={10} style={{flexShrink:0, opacity:.6}}/>}
                          </div>
                        )

                        return (
                          <NavLink key={leaf.id} to={hrefOf(leaf)}
                            className={() => `nav-subitem${isLeafActive ? ' active' : ''}`}>
                            <span className="nav-subitem-dot"/>
                            <span className="nav-subitem-label">{leaf.name}</span>
                          </NavLink>
                        )
                      })}
                    </div>
                  )}
                </div>
              )
            }

            const visibleDomains = visibleGroups(domainGroups(), isDomainVisible, isModuleVisible)
            const businessDomains   = visibleDomains.filter(g => g.domain.section !== 'supporting')
            const supportingDomains = visibleDomains.filter(g => g.domain.section === 'supporting')

            return <>
              <SectionLabel text="Platform" first/>
              <NavLink to={HOME.to} end title={col ? HOME.label : undefined} data-testid="nav-overview"
                className={({isActive}) => `nav-item${isActive ? ' active' : ''}`}>{overviewBody}</NavLink>

              {businessDomains.length > 0 && <SectionLabel text="Business Modules"/>}
              {businessDomains.map(renderDomain)}

              {/* Settings lives here too, so this section always shows even if Practice is hidden */}
              <SectionLabel text="Supporting Modules"/>
              {supportingDomains.map(renderDomain)}
              {simpleLink(MY_ACCOUNT_ITEM)}
              {isOrgAdmin && simpleLink(SETTINGS_ITEM)}

              {isAdmin && <>
                <SectionLabel text="Admin"/>
                {simpleLink(ADMIN_ITEM)}
              </>}
            </>
          })()}
        </nav>

        {/* Collapse toggle */}
        <button onClick={() => setCol(c => !c)} style={{
          position:'absolute', top:68, right:-11, width:22, height:22, borderRadius:'50%',
          background:'var(--surface)', border:'1.5px solid var(--border)', cursor:'pointer',
          display:'flex', alignItems:'center', justifyContent:'center', boxShadow:'var(--sh-md)', zIndex:30}}>
          {col ? <ChevronRight size={11} color="var(--text-2)"/> : <ChevronLeft size={11} color="var(--text-2)"/>}
        </button>
      </aside>

      {/* Right pane */}
      <div style={{flex:1, display:'flex', flexDirection:'column', overflow:'hidden', minWidth:0, height:'100vh'}}>
        <TopBar
          variant="app"
          pageName={pageName}
          initials={initials}
          userName={userName}
          onLogout={handleLogout}
        />
        <main style={{flex:1, padding:'24px 28px', overflowY:'auto'}}><ReconciliationContext.Provider value={reconCtx}><Suspense fallback={<div style={{padding:40,textAlign:'center',color:'var(--text-3)'}}>Loading…</div>}>{needsProfile ? <div style={{maxWidth:560, margin:'24px auto'}} data-testid="complete-profile"><ProfileCard required /></div> : <PlanGate><Outlet/></PlanGate>}</Suspense></ReconciliationContext.Provider></main>
      </div>
    </div>
    </>
  )
}