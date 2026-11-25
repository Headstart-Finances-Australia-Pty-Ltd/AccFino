/**
 * AccFino Overview — the new landing page (replaces DashboardPage at "/")
 * Shows modules grouped by category, plan info, and user details.
 * No financial stats here — those live inside Accounting > Dashboard.
 */
import React, { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { useAuth } from '../hooks/useAuth.jsx'
import { licenceMyModules, getMyPlan } from '../lib/api.js'
import {
  BookOpen, TrendingUp, Users, Settings, Lock,
  ChevronRight, Star, Shield, ArrowUpRight,
} from 'lucide-react'

/* ── Module catalogue grouped by category ──────────────────────────────────── */
const CATEGORIES = [
  {
    key:   'accounting',
    icon:  '🏦',
    label: 'Accounting',
    color: 'var(--brand)',
    bg:    'var(--brand-xlight,#eff6ff)',
    border:'#bfdbfe',
    modules: [
      { key:'accounting', icon:'📊', label:'Dashboard',          desc:'KPI overview · sessions · income & expense totals',    to:'/accounting', tab:'dashboard'      },
      { key:'accounting', icon:'🔀', label:'Reconciliation',     desc:'Bank CSV · Open Banking · GL & GST auto-classification', to:'/accounting', tab:'reconciliation' },
      { key:'accounting', icon:'💼', label:'Sales',              desc:'Customers · Quotes · Tax Invoices · save to DB',        to:'/accounting', tab:'sales'          },
      { key:'accounting', icon:'🧾', label:'Purchases',          desc:'Suppliers · Purchase Orders · Bills · Receipts · OCR',  to:'/accounting', tab:'purchases'      },
      { key:'cash-flow',  icon:'📈', label:'Cash Flow',          desc:'ML forecast · 17 models · DB data source',              to:'/accounting', tab:'cashflow'       },
      { key:'accounting', icon:'📋', label:'Financial Reports',  desc:'P&L · Balance Sheet · Aged Receivables · GST/BAS · 20+ reports', to:'/accounting', tab:'reports' },
    ],
  },
  {
    key:   'trading',
    icon:  '🧾',
    label: 'Taxation & Trading',
    color: '#7c3aed',
    bg:    '#f5f3ff',
    border:'#ddd6fe',
    modules: [
      { key:'trading', icon:'₿',  label:'Crypto CGT',      desc:'Capital gains tax for crypto assets',         to:'/trading' },
      { key:'trading', icon:'📊', label:'Stock / Equity CGT', desc:'Capital gains for shares & ETFs — ATO compliant', to:'/trading' },
      { key:'trading', icon:'🏠', label:'Property CGT',    desc:'Property capital gains · main residence exemption', to:'/trading' },
      { key:'trading', icon:'🗂', label:'Tax Return Data', desc:'Full Australian ITR · all income, deductions, offsets', to:'/trading' },
    ],
  },
  {
    key:   'payroll',
    icon:  '👔',
    label: 'Payroll',
    color: '#0891b2',
    bg:    '#ecfeff',
    border:'#a5f3fc',
    modules: [
      { key:'payroll', icon:'👥', label:'Employees',    desc:'Employee master · super · banking',      to:'/payroll' },
      { key:'payroll', icon:'⏱', label:'Timesheets',   desc:'Hours · leave · overtime tracking',      to:'/payroll' },
      { key:'payroll', icon:'💸', label:'Payroll Runs', desc:'PAYG · super · payslip generation',      to:'/payroll' },
      { key:'payroll', icon:'🏛', label:'STP / ATO',   desc:'STP Phase 2 · ATO compliance reporting',  to:'/payroll' },
    ],
  },
  {
    key:   'lending',
    icon:  '🏦',
    label: 'Smart Lending',
    color: '#0891b2',
    bg:    '#ecfeff',
    border:'#a5f3fc',
    modules: [
      { key:'lending', icon:'📤', label:'Upload Statement',      desc:'PDF · image · CSV bank statement extraction',         to:'/lending' },
      { key:'lending', icon:'🗂', label:'Transaction Analysis',  desc:'AI classification into 40+ expense categories',       to:'/lending' },
      { key:'lending', icon:'📊', label:'Lending Metrics',       desc:'NDI · UMI · DSR · HEM · LTI · risk score',           to:'/lending' },
      { key:'lending', icon:'🏛', label:'Serviceability Check',  desc:'ASIC RG 209 · APRA buffer · max borrowing capacity',  to:'/lending' },
    ],
  },
  {
    key:   'setup',
    icon:  '⚙️',
    label: 'Control Panel · Setup',
    color: '#6b7280',
    bg:    '#f9fafb',
    border:'#e5e7eb',
    modules: [
      { key:'setup', icon:'🏢', label:'Business Account', desc:'Business name · ABN · GST · banking details', to:'/setup' },
      { key:'setup', icon:'📋', label:'Chart of Accounts', desc:'GL accounts · tax codes · COA management',   to:'/setup' },
      { key:'setup', icon:'⚙️', label:'Business Rules',   desc:'RDR classification rules engine',            to:'/setup' },
      { key:'setup', icon:'📚', label:'Knowledge Base',   desc:'Vendor map · keyword classification map',     to:'/setup' },
    ],
  },
]

const PLAN_LABELS = {
  base:    { label:'Vault Plan',    color:'#6b7280', emoji:'🔒' },
  premium: { label:'Ultra Plan',    color:'#7c3aed', emoji:'⚡' },
  custom:  { label:'Custom Plan',   color:'var(--brand)', emoji:'✨' },
}

export default function OverviewPage() {
  const { user }    = useAuth()
  const nav         = useNavigate()
  const [myPlan,    setMyPlan]    = useState(null)
  const [modules,   setModules]   = useState(null)
  const isAdmin = (Array.isArray(user?.roles) && user.roles.includes('admin')) || user?.is_admin === true

  useEffect(() => {
    if (!user?.id) return
    getMyPlan(user.id).then(r => setMyPlan(r.data)).catch(() => {})
    if (isAdmin) { setModules('all'); return }
    licenceMyModules(user.id).then(r => setModules(r.data.modules || [])).catch(() => setModules([]))
  }, [user?.id])

  // Vault plan IDs that do NOT include cash-flow
  const VAULT_PLANS = new Set(['base', 'accounting_starter', ''])

  const canAccess = (key) => {
    if (isAdmin || modules === 'all') return true
    if (!modules) return false
    // Always accessible to all users
    if (key === 'setup' || key === 'dashboard' || key === 'accounting') return true
    // Vault/Base plan: reconciliation always accessible
    if (key === 'reconciliation') return true
    // Smart Lending always accessible
    if (key === 'lending') return true
    // Cash Flow requires Accounting Pro or above — check plan_id, not just modules
    // (modules may contain stale cash-flow from previous plan merges)
    if (key === 'cash-flow') {
      const planId = myPlan?.plan_id || 'base'
      return !VAULT_PLANS.has(planId)
    }
    return modules.includes(key)
  }

  const planInfo = myPlan
    ? (PLAN_LABELS[myPlan.plan_id] || { label:(myPlan.plan_name||'Plan')+' Plan', color:'var(--brand)', emoji:'✨' })
    : null

  const firstName = (user?.name || '').split(' ')[0] || 'there'
  const initials  = (user?.name || user?.email || 'U').split(' ').map(w=>w[0]).join('').slice(0,2).toUpperCase()

  return (
    <div className="fade-in" style={{maxWidth:1100,margin:'0 auto'}}>

      {/* ── Welcome banner ─────────────────────────────────────────────────── */}
      <div style={{
        background:'linear-gradient(135deg,#0D1117 0%,#1a2332 100%)',
        borderRadius:'var(--r-xl,20px)', padding:'28px 32px',
        marginBottom:28, position:'relative', overflow:'hidden',
        border:'1px solid rgba(255,255,255,.08)',
        boxShadow:'0 8px 32px rgba(0,0,0,.18)',
      }}>
        <div style={{position:'absolute',top:0,right:0,bottom:0,left:0,pointerEvents:'none',
          backgroundImage:'radial-gradient(circle at 85% 30%,rgba(200,150,62,.12) 0%,transparent 55%)'}}/>
        <div style={{display:'flex',alignItems:'center',justifyContent:'space-between',gap:16,flexWrap:'wrap'}}>
          <div>
            <div style={{fontSize:'.8rem',color:'rgba(255,255,255,.45)',fontWeight:500,marginBottom:6}}>
              {new Date().toLocaleDateString('en-AU',{weekday:'long',day:'numeric',month:'long',year:'numeric'})}
            </div>
            <h1 style={{color:'#fff',marginBottom:6,fontSize:'1.6rem'}}>
              Welcome back, {firstName} 👋
            </h1>
            <p style={{color:'rgba(255,255,255,.55)',fontSize:'.875rem',margin:0}}>
              AccFino financial platform · Your modules are ready
            </p>
          </div>

          {/* User + plan card */}
          <div style={{
            background:'rgba(255,255,255,.06)', borderRadius:'var(--r-lg)',
            border:'1px solid rgba(255,255,255,.1)', padding:'16px 20px',
            display:'flex',alignItems:'center',gap:14,minWidth:240,
          }}>
            <div style={{
              width:44,height:44,borderRadius:'50%',flexShrink:0,
              background:'linear-gradient(135deg,#C8963E,#E8B86D)',
              display:'flex',alignItems:'center',justifyContent:'center',
              fontWeight:700,fontSize:'1rem',color:'#fff',
            }}>{initials}</div>
            <div style={{flex:1,minWidth:0}}>
              <div style={{color:'#fff',fontWeight:700,fontSize:'.9rem',
                overflow:'hidden',textOverflow:'ellipsis',whiteSpace:'nowrap'}}>
                {user?.name || user?.email}
              </div>
              <div style={{color:'rgba(255,255,255,.5)',fontSize:'.75rem',marginTop:2}}>
                {user?.email}
              </div>
              {planInfo && (
                <div style={{display:'flex',alignItems:'center',gap:6,marginTop:6}}>
                  <span style={{
                    padding:'2px 8px',borderRadius:100,fontSize:'.7rem',fontWeight:700,
                    background: planInfo.color, color:'#fff',
                  }}>
                    {planInfo.emoji} {planInfo.label}
                  </span>
                  {!isAdmin && myPlan?.plan_id !== 'premium' && (
                    <button className="btn btn-xs"
                      onClick={()=>nav('/upgrade')}
                      style={{background:'#FF6B35',color:'#fff',border:'none',fontSize:'.68rem',padding:'2px 8px',borderRadius:100}}>
                      ⚡ Upgrade
                    </button>
                  )}
                </div>
              )}
            </div>
          </div>
        </div>
      </div>

      {/* ── Module categories ───────────────────────────────────────────────── */}
      {CATEGORIES.map(cat => {
        const access = canAccess(cat.key)
        return (
          <div key={cat.key} style={{marginBottom:28}}>
            {/* Category header */}
            <div style={{display:'flex',alignItems:'center',gap:10,marginBottom:14}}>
              <div style={{
                width:34,height:34,borderRadius:'var(--r-md)',
                background:cat.bg,border:`1px solid ${cat.border}`,
                display:'flex',alignItems:'center',justifyContent:'center',fontSize:'1.1rem',
              }}>{cat.icon}</div>
              <h2 style={{margin:0,fontSize:'1.05rem',fontWeight:700,color:'var(--text-1)'}}>{cat.label}</h2>
              {!access && (
                <span style={{
                  display:'flex',alignItems:'center',gap:4,fontSize:'.7rem',fontWeight:700,
                  color:'#9ca3af',padding:'2px 8px',borderRadius:100,
                  background:'var(--surface-2)',border:'1px solid var(--border)',
                }}>
                  <Lock size={10}/> Locked
                </span>
              )}
            </div>

            {/* Module cards */}
            <div style={{display:'grid',gridTemplateColumns:'repeat(auto-fill,minmax(210px,1fr))',gap:10}}>
              {cat.modules.map((mod, i) => {
                const modAccess = canAccess(mod.key)
                return (
                <button key={i}
                  onClick={() => modAccess && nav(mod.to, mod.tab ? { state: { tab: mod.tab } } : undefined)}
                  disabled={!modAccess}
                  style={{
                    display:'flex',alignItems:'flex-start',gap:12,
                    padding:'14px 16px',borderRadius:'var(--r-lg)',
                    background: modAccess ? 'var(--surface)' : 'var(--surface-2)',
                    border:`1.5px solid ${modAccess ? 'var(--border)' : 'var(--border)'}`,
                    cursor: modAccess ? 'pointer' : 'not-allowed',
                    textAlign:'left',fontFamily:'inherit',
                    transition:'border-color .15s, box-shadow .15s, transform .15s',
                    boxShadow:'var(--sh-xs)',
                    opacity: modAccess ? 1 : 0.45,
                  }}
                  onMouseEnter={e=>{ if(modAccess){
                    e.currentTarget.style.borderColor=cat.color
                    e.currentTarget.style.boxShadow='var(--sh-md)'
                    e.currentTarget.style.transform='translateY(-2px)'
                  }}}
                  onMouseLeave={e=>{ if(modAccess){
                    e.currentTarget.style.borderColor='var(--border)'
                    e.currentTarget.style.boxShadow='var(--sh-xs)'
                    e.currentTarget.style.transform='none'
                  }}}
                >
                  <span style={{fontSize:'1.3rem',lineHeight:1,flexShrink:0,marginTop:2,
                    filter:modAccess?'none':'grayscale(1)'}}>{mod.icon}</span>
                  <div style={{flex:1,minWidth:0}}>
                    <div style={{fontWeight:700,fontSize:'.82rem',color:modAccess?'var(--text-1)':'var(--text-3)',marginBottom:3}}>
                      {mod.label}
                    </div>
                    <div style={{fontSize:'.72rem',color:'var(--text-3)',lineHeight:1.4}}>
                      {mod.desc}
                    </div>
                  </div>
                  {modAccess
                    ? <ChevronRight size={14} color="var(--text-3)" style={{flexShrink:0,marginTop:2}}/>
                    : <Lock size={12} color="#9ca3af" style={{flexShrink:0,marginTop:2}}/>
                  }
                </button>
                )
              })}
            </div>
          </div>
        )
      })}

      {/* ── Footer info ─────────────────────────────────────────────────────── */}
      <div style={{
        display:'flex',gap:12,padding:'16px 20px',
        background:'var(--surface-2)',borderRadius:'var(--r-lg)',
        border:'1px solid var(--border)',fontSize:'.78rem',
        color:'var(--text-3)',alignItems:'center',flexWrap:'wrap',
      }}>
        <Shield size={14} color="var(--brand)"/>
        <span>All data is encrypted and stored securely on your PostgreSQL database.</span>
        <span style={{marginLeft:'auto',color:'var(--text-3)'}}>
          AccFino v1.2.0 · <a href="/setup" style={{color:'var(--brand)',textDecoration:'none'}}>Settings</a>
        </span>
      </div>
    </div>
  )
}
