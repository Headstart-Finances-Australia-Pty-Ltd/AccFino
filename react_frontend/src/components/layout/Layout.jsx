import TopBar from '../ui/TopBar.jsx'
import React, { useState, useEffect } from 'react'
import { Outlet, NavLink, useNavigate, useLocation } from 'react-router-dom'
import { useAuth } from '../../hooks/useAuth.jsx'
import UpgradeBanner from '../UpgradeBanner.jsx'
import { licenceMyModules, getMyPlan } from '../../lib/api.js'
import { Building2, LayoutDashboard, ArrowLeftRight, TrendingUp, BarChart2, FileText, ShieldCheck, ChevronLeft, ChevronRight, FolderOpen, BadgeCheck, Settings, Cpu, BookOpen, DollarSign, Users } from 'lucide-react'

// ── Reconciliation session context — persists across route navigation ─────────
export const ReconciliationContext = React.createContext(null)

const NAV = [
  { to:'/',               icon:LayoutDashboard, label:'Overview',         sub:'Modules & Plan',           key:'dashboard',      adminOnly:false, allPlans:true },
  { to:'/accounting',     icon:BookOpen,        label:'Accounting',       sub:'Dashboard · Recon · Sale', key:'accounting',     adminOnly:false },
  { to:'/trading',        icon:TrendingUp,      label:'Taxation & Trading',sub:'CGT · Tax Return',        key:'trading',        adminOnly:false },
  { to:'/payroll',        icon:Users,           label:'Payroll',          sub:'PAYG · Super · STP',       key:'payroll',        adminOnly:false },
  { to:'/lending',        icon:DollarSign,      label:'Smart Lending',    sub:'Statement analysis · HEM · UMI', key:'lending',     adminOnly:false },
]

// Setup is always visible; admin items below only for admins
const CONTROL_PANEL_SETUP = [
  { to:'/setup',          icon:Settings,        label:'Setup',           sub:'COA · Rules · Invoice',   key:'setup'          },
]
const CONTROL_PANEL = [
  { to:'/admin',          icon:ShieldCheck,     label:'ML Classifier',   sub:'Training & RDR rules',    key:'admin'          },
  { to:'/file-manager',   icon:FolderOpen,      label:'File Manager',    sub:'Files, tables, data',     key:'file-manager'   },
  { to:'/licence',        icon:BadgeCheck,      label:'Admin & Licence', sub:'Users, roles & licences', key:'licence'        },
  { to:'/pricing-admin',  icon:BadgeCheck,      label:'Plan Pricing',    sub:'Edit plan prices',        key:'pricing-admin'  },
  { to:'/company-db',     icon:Building2,       label:'Company DB',      sub:'AU & world organisations', key:'company-db'    },
]

export default function Layout() {
  const { user, logout } = useAuth()
  const nav = useNavigate()
  const loc = useLocation()
  const [col,            setCol]           = useState(false)
  const [allowedModules, setAllowedModules] = useState(null)
  const [myPlan,         setMyPlan]        = useState(null)

  const fetchModules = () => {
    if (!user) return
    const isAdmin = Array.isArray(user.roles) && user.roles.includes('admin')
    if (isAdmin || !user.id) { setAllowedModules('all'); return }
    // Always fetch fresh from API — never use cached value
    licenceMyModules(user.id)
      .then(r => setAllowedModules(r.data.modules || ['dashboard','reconciliation']))
      .catch(() => setAllowedModules(['dashboard','reconciliation']))
  }

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

  const showUpgradeBtn = myPlan && !(myPlan.plan_id === 'premium' && myPlan.billing_period === 'yearly')

  const isAdmin = (Array.isArray(user?.roles) && user.roles.includes('admin')) || user?.is_admin === true

  const canAccess = (moduleKey) => {
    if (moduleKey === 'setup') return true        // Control Panel always accessible
    if (moduleKey === 'accounting') return true   // Accounting always accessible — Reconciliation is free for all
    if (moduleKey === 'lending')     return true   // Smart Lending always accessible
    if (moduleKey === 'dashboard') return true    // Overview always accessible
    if (isAdmin) return true
    if (allowedModules === null) return false     // still loading
    if (allowedModules === 'all') return true
    return allowedModules.includes(moduleKey)
  }

  const initials = (user?.name || user?.email || 'U').split(' ').map(w => w[0]).join('').slice(0,2).toUpperCase()
  const userName = user?.name || user?.email || ''
  const pageName = loc.pathname === '/' ? 'Overview' : loc.pathname.slice(1).replace(/-/g,' ').replace(/\b\w/g, c => c.toUpperCase())

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
        width:col ? 'var(--sidebar-w-sm)' : 'var(--sidebar-w)', minHeight:'100vh', flexShrink:0,
        position:'relative', display:'flex', flexDirection:'column',
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
        <nav style={{flex:1, padding:col ? '12px 6px' : '12px 10px', display:'flex', flexDirection:'column',
          gap:2, overflowY:'auto', overflowX:'hidden', position:'relative', zIndex:1}}>
          {!col && <div style={{fontSize:'.9rem', fontWeight:700, color:'rgba(255,255,255,.35)',
            letterSpacing:'.1em', textTransform:'uppercase', padding:'4px 12px 8px', marginTop:4}}>Modules</div>}
          {NAV.map(({to, icon:Icon, label, sub, key}) => {
            const allowed = canAccess(key)
            return allowed ? (
              <NavLink key={to} to={to} end={to==='/'} title={col ? label : undefined}
                className={({isActive}) => `nav-item${isActive ? ' active' : ''}`}>
                <Icon size={23} strokeWidth={1.8} style={{flexShrink:0}}/>
                {!col && <div style={{minWidth:0}}>
                  <div style={{fontSize:'.8rem', fontWeight:600, lineHeight:1.2}}>{label}</div>
                  <div style={{fontSize:'.6rem', opacity:.55, lineHeight:1.3, marginTop:1}}>{sub}</div>
                </div>}
              </NavLink>
            ) : (
              <div key={to} title={col ? label : undefined}
                className="nav-item"
                style={{opacity:.35, cursor:'not-allowed', pointerEvents:'none', userSelect:'none'}}>
                <Icon size={23} strokeWidth={1.8} style={{flexShrink:0}}/>
                {!col && <div style={{minWidth:0}}>
                  <div style={{fontSize:'.8rem', fontWeight:600, lineHeight:1.2}}>{label}</div>
                  <div style={{fontSize:'.6rem', opacity:.55, lineHeight:1.3, marginTop:1}}>🔒 No access</div>
                </div>}
              </div>
            )
          })}

          {/* Control Panel section — Setup visible to all; admin items for admin only */}
          <div style={{
            fontSize:'.9rem', fontWeight:700, color:'rgba(255,255,255,.35)',
            letterSpacing:'.1em', textTransform:'uppercase',
            padding: col ? '12px 0 6px' : '12px 12px 6px',
            marginTop:8, borderTop:'1px solid rgba(255,255,255,.08)',
            display:'flex', alignItems:'center', gap:6,
          }}>
            <Cpu size={13} style={{opacity:.6}}/>
            {!col && 'Control Panel'}
          </div>

          {/* Setup — always visible to all users */}
          {CONTROL_PANEL_SETUP.map(({to, icon:Icon, label, sub}) => (
            <NavLink key={to} to={to} title={col ? label : undefined}
              className={({isActive}) => `nav-item${isActive ? ' active' : ''}`}>
              <Icon size={23} strokeWidth={1.8} style={{flexShrink:0}}/>
              {!col && <div style={{minWidth:0}}>
                <div style={{fontSize:'.8rem', fontWeight:600, lineHeight:1.2}}>{label}</div>
                <div style={{fontSize:'.6rem', opacity:.55, lineHeight:1.3, marginTop:1}}>{sub}</div>
              </div>}
            </NavLink>
          ))}

          {/* Admin tools — admin only */}
          {isAdmin && (
            <>
              {CONTROL_PANEL.map(({to, icon:Icon, label, sub}) => (
                <NavLink key={to} to={to} title={col ? label : undefined}
                  className={({isActive}) => `nav-item${isActive ? ' active' : ''}`}>
                  <Icon size={23} strokeWidth={1.8} style={{flexShrink:0}}/>
                  {!col && <div style={{minWidth:0}}>
                    <div style={{fontSize:'.8rem', fontWeight:600, lineHeight:1.2}}>{label}</div>
                    <div style={{fontSize:'.6rem', opacity:.55, lineHeight:1.3, marginTop:1}}>{sub}</div>
                  </div>}
                </NavLink>
              ))}
            </>
          )}
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
        <main style={{flex:1, padding:'24px 28px', overflowY:'auto'}}><ReconciliationContext.Provider value={reconCtx}><Outlet/></ReconciliationContext.Provider></main>
      </div>
    </div>
    </>
  )
}