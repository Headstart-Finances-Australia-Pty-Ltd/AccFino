import React, { useEffect, useState, useRef, useContext } from 'react'
import { ReconciliationContext } from '../components/layout/Layout.jsx'
import toast from 'react-hot-toast'
import { useNavigate, useSearchParams } from 'react-router-dom'
import { useAuth } from '../hooks/useAuth.jsx'
import { getSessions, getDashboardStats, licenceMyModules, getMyPlan, activateAfterPayment } from '../lib/api.js'
import { ArrowLeftRight, TrendingUp, TrendingDown, RefreshCw, Activity,
         BarChart3, ArrowRight, Calendar, Folder, Trash2 } from 'lucide-react'
import { deleteSession as apiDeleteSession } from '../lib/api.js'

const fmtAUD  = n => new Intl.NumberFormat('en-AU',{style:'currency',currency:'AUD',maximumFractionDigits:0}).format(n||0)
const fmtFull = n => new Intl.NumberFormat('en-AU',{style:'currency',currency:'AUD',minimumFractionDigits:2}).format(n||0)

const QUICK = [
  {to:'/reconciliation', icon:'🏦', label:'Bank Reconciliation',  desc:'Upload statements or pull from Open Banking', key:'reconciliation'},
  {to:'/trading',        icon:'📈', label:'Trading Analysis',      desc:'Crypto & equity CGT tax reports',            key:'trading'},
  {to:'/cash-flow',      icon:'💰', label:'Cash Flow Forecast',    desc:'ML-powered next-month prediction',           key:'cash-flow'},
  {to:'/invoice',        icon:'📄', label:'Invoice Manager',       desc:'Create GST invoices & extract from PDFs',    key:'invoice'},
  {to:'/admin',          icon:'🧠', label:'Admin & ML Classifier', desc:'Train models, RDR rules, manage users',      key:'admin', adminOnly:true},
]

function StatCard({label,value,sub,colorVar,iconColor,icon:Icon}) {
  return (
    <div className="stat-card" style={{'--stat-accent':colorVar,'--stat-icon-bg':iconColor+'18'}}>
      <div className="stat-icon"><Icon size={18} color={iconColor}/></div>
      <div className="stat-label">{label}</div>
      <div className="stat-value">{value}</div>
      {sub && <div className="stat-sub">{sub}</div>}
    </div>
  )
}

export default function DashboardPage() {
  const { user }  = useAuth()
  const nav            = useNavigate()
  const recon          = useContext(ReconciliationContext)
  const [searchParams, setSearchParams] = useSearchParams()
  const [myPlan, setMyPlan] = useState(null)
  const [allowedModules, setAllowedModules] = useState(null)

  useEffect(() => {
    if (!user?.id) return
    // Use cached plan from login if available, then refresh in background
    if (user.plan) setMyPlan(user.plan)
    getMyPlan(user.id).then(r => setMyPlan(r.data)).catch(() => {})
  }, [user?.id])

  // Handle return from Stripe payment — activate plan immediately
  useEffect(() => {
    if (searchParams.get('payment') === 'success' && user?.id) {
      const planFromUrl   = searchParams.get('plan') || 'basic'
      const periodFromUrl = searchParams.get('period') || 'monthly'
      // mods is pipe-separated e.g. "reconciliation|invoice"
      const modsStr   = searchParams.get('mods') || ''
      const modsFromUrl = modsStr ? modsStr.split('|').filter(Boolean) : []

      setSearchParams({})

      // Use exact modules from URL — don't default to bundle
      const planId  = planFromUrl === 'custom' ? 'custom' : planFromUrl
      const modules = modsFromUrl.length > 0 ? modsFromUrl : null

      activateAfterPayment({
        user_id:        user.id,
        plan_id:        planId,
        billing_period: periodFromUrl,
        modules:        modules || [],
      })
        .then(res => {
          // Use returned data directly for instant update
          const updated = res.data
          if (updated?.ok) {
            setMyPlan({
              plan_id:  updated.plan_id,
              modules:  updated.modules,
              end_date: updated.end_date,
            })
          }
          window.dispatchEvent(new Event('accfino:modules-changed'))
          toast.success('🎉 Payment successful! Your plan has been upgraded.')
          // Also refresh from server after 2s for webhook data
          setTimeout(() => getMyPlan(user.id).then(r => setMyPlan(r.data)).catch(()=>{}), 2000)
        })
        .catch(() => {
          toast.success('🎉 Payment received! Refreshing your plan...')
          setTimeout(() => {
            getMyPlan(user.id).then(r => {
              setMyPlan(r.data)
              window.dispatchEvent(new Event('accfino:modules-changed'))
            }).catch(() => {})
          }, 3000)
        })
    }
  }, [user?.id])

  useEffect(() => {
    if (!user) return
    const _isAdmin = Array.isArray(user.roles) && user.roles.includes('admin')
    if (_isAdmin || !user.id) { setAllowedModules('all'); return }
    const fetch = () => licenceMyModules(user.id)
      .then(r => setAllowedModules(r.data.modules || 'all'))
      .catch(() => setAllowedModules('all'))
    fetch()
    window.addEventListener('accfino:modules-changed', fetch)
    return () => window.removeEventListener('accfino:modules-changed', fetch)
  }, [user?.id])

  const isAdmin   = Array.isArray(user?.roles) && user.roles.includes('admin')
  const canAccess = key => {
    if (isAdmin) return true
    if (!allowedModules || allowedModules === 'all') return true
    return allowedModules.includes(key)
  }

  const [stats,    setStats]    = useState(null)
  const [sessions, setSessions] = useState([])
  const [loading,  setLoading]  = useState(true)
  const [lastRefresh, setLastRefresh] = useState(Date.now())

  const usernameRef = useRef(user?.username || user?.email || '')

  useEffect(() => {
    usernameRef.current = user?.username || user?.email || ''
  }, [user])

  const doLoad = (uname) => {
    if (!uname) { setLoading(false); return }
    Promise.all([
      getDashboardStats(uname).then(r => setStats(r.data)).catch(() => setStats(null)),
      getSessions(uname).then(r => setSessions(Array.isArray(r.data) ? r.data : [])).catch(() => setSessions([])),
    ]).finally(() => { setLastRefresh(Date.now()); setLoading(false) })
  }

  useEffect(() => {
    const uname = user?.username || user?.email || ''
    usernameRef.current = uname
    setLoading(true)
    doLoad(uname)
  }, [user?.username, user?.email]) // eslint-disable-line

  useEffect(() => {
    const t = setInterval(() => doLoad(usernameRef.current), 30000)
    return () => clearInterval(t)
  }, []) // eslint-disable-line

  const firstName   = (user?.name || '').split(' ')[0] || 'there'
  const hour        = new Date().getHours()
  const greeting    = hour < 12 ? 'Good morning' : hour < 17 ? 'Good afternoon' : 'Good evening'
  const refreshTime = new Date(lastRefresh).toLocaleTimeString('en-AU', {hour:'2-digit',minute:'2-digit'})

  const totalIn  = stats?.total_in  || 0
  const totalOut = stats?.total_out || 0
  const totalGST = stats?.total_gst || 0
  const internal = stats?.internal  || 0
  const incoming = stats?.incoming  || 0
  const outgoing = stats?.outgoing  || 0
  const net      = totalIn - totalOut

  const ZERO_STATS = {total_in:0,total_out:0,total_gst:0,internal:0,incoming:0,outgoing:0,net:0,session_count:0}

  const delSession = async (sid) => {
    const uname = usernameRef.current
    await apiDeleteSession(uname, sid).catch(() => {})
    // If the deleted session is currently loaded in the Reconciliation page,
    // reset that page so it doesn't keep showing stale data.
    if (recon?.resetRecon) recon.resetRecon(sid)
    setSessions(prev => {
      const next = prev.filter(x => x.session_id !== sid)
      // Reset stats immediately if no sessions remain
      if (next.length === 0) setStats(ZERO_STATS)
      // Otherwise refresh stats from server to reflect the new latest session
      else getDashboardStats(uname).then(r => setStats(r.data)).catch(() => {})
      return next
    })
  }

  return (
    <div className="fade-in">
      {/* Header */}
      <div style={{marginBottom:24,display:'flex',alignItems:'center',justifyContent:'space-between',flexWrap:'wrap',gap:12}}>
        <div>
          <div style={{fontSize:'.8rem',color:'var(--text-3)',fontWeight:500,marginBottom:4}}>
            {new Date().toLocaleDateString('en-AU',{weekday:'long',day:'numeric',month:'long',year:'numeric'})}
          </div>
          <h1>{greeting}, {firstName} 👋</h1>
          <p style={{color:'var(--text-3)',marginTop:4,fontSize:'.9rem'}}>
            Financial overview across all reconciliation sessions.
            <span style={{marginLeft:8,fontSize:'.75rem',opacity:.7}}>Updated {refreshTime}</span>
          </p>
        </div>
        <div style={{display:'flex',flexDirection:'column',alignItems:'center',gap:5}}>
          {/* Current plan + upgrade — above New Reconciliation */}
          {myPlan && (
            <div style={{display:'flex',alignItems:'center',justifyContent:'center',gap:8}}>
              <span style={{
                fontSize:'.75rem', fontWeight:700, padding:'4px 10px',
                borderRadius:100, background:'var(--surface-2)',
                border:'1px solid var(--border)', color:'var(--text-2)',
              }}>
                {(() => {
                  const pid = myPlan.plan_id || 'base'
                  // Show human-readable plan name
                  // Only known bundle plans get simple names
                  // Individual module purchases always show "Base + X Plan"
                  // Use plan name directly from pricing.json via myPlan
                  if (myPlan.plan_name) return myPlan.plan_name + ' Plan'
                  const BUNDLE_NAMES = { base:'Vault', premium:'Ultra' }
                  if (BUNDLE_NAMES[pid]) return BUNDLE_NAMES[pid] + ' Plan'
                  // Custom multi-module — show "Base + Trading Plan"
                  const SHORT = {
                    dashboard:'Base', reconciliation:'Reconciliation',
                    trading:'Trading', 'cash-flow':'Cash Flow', invoice:'Invoice',
                  }
                  const activeMods = (myPlan.modules || [])
                    .map(m => SHORT[m]).filter(Boolean)
                  // Always starts with Base, then add paid modules
                  const baseLabel = ['Base']
                  const paidMods  = activeMods.filter(m => m !== 'Base' && m !== 'Reconciliation')
                  return [...baseLabel, ...paidMods].join(' + ') + ' Plan'
                })()}
              </span>
              {!isAdmin && myPlan.plan_id !== 'premium' && (
                <button className="btn btn-primary btn-sm" onClick={() => nav('/upgrade')}>
                  ⚡ Upgrade Plan
                </button>
              )}
            </div>
          )}
          <div style={{display:'flex',gap:8,marginTop:5,justifyContent:'center'}}>
            <button className="btn btn-ghost btn-sm" onClick={() => { setLoading(true); doLoad(usernameRef.current) }}>
              <RefreshCw size={14}/> Refresh
            </button>
            <button className="btn btn-primary" onClick={() => nav('/reconciliation')}>
              <ArrowLeftRight size={15}/> New Reconciliation
            </button>
          </div>
        </div>
      </div>

      {/* Stat cards */}
      {loading ? (
        <div className="stats-grid" style={{marginBottom:24}}>
          {[...Array(4)].map((_,i) => <div key={i} className="skeleton" style={{height:112,borderRadius:'var(--r-lg)'}}/>)}
        </div>
      ) : (
        <div className="stats-grid" style={{marginBottom:24}}>
          <StatCard label="Total Incoming"     value={fmtAUD(totalIn)}
            sub={`${incoming} transactions`}   colorVar="var(--info)"    iconColor="#2563EB" icon={TrendingUp}/>
          <StatCard label="Total Outgoing"     value={fmtAUD(totalOut)}
            sub={`${outgoing} transactions`}   colorVar="var(--warning)" iconColor="#D97706" icon={TrendingDown}/>
          <StatCard label="Internal Transfers" value={internal}
            sub="matched pairs"                colorVar="var(--success)" iconColor="#059669" icon={RefreshCw}/>
          <StatCard label="Net Position"       value={fmtAUD(Math.abs(net))}
            sub={net >= 0 ? '↑ Surplus' : '↓ Deficit'}
            colorVar={net >= 0 ? 'var(--success)' : 'var(--danger)'}
            iconColor={net >= 0 ? '#059669' : '#DC2626'} icon={Activity}/>
        </div>
      )}

      {/* GST strip */}
      {!loading && totalGST > 0 && (
        <div style={{background:'linear-gradient(135deg,var(--brand-light),#fff)',border:'1px solid #A7F3D0',borderRadius:'var(--r-lg)',padding:'14px 20px',marginBottom:24,display:'flex',alignItems:'center',gap:16,flexWrap:'wrap'}}>
          <div style={{width:36,height:36,borderRadius:'var(--r-md)',background:'var(--brand)',display:'flex',alignItems:'center',justifyContent:'center'}}>
            <BarChart3 size={18} color="#fff"/>
          </div>
          <div>
            <div style={{fontSize:'.78rem',fontWeight:700,color:'var(--brand)',textTransform:'uppercase',letterSpacing:'.05em'}}>Total GST Collected / Paid</div>
            <div style={{fontFamily:'var(--font-mono)',fontWeight:700,fontSize:'1.1rem',color:'var(--text-1)'}}>{fmtFull(totalGST)}</div>
          </div>
          <div style={{marginLeft:'auto'}}><span className="badge badge-brand">BAS Ready</span></div>
        </div>
      )}

      {/* Modules */}
      <h2 style={{marginBottom:14}}>Modules</h2>
      <div style={{display:'grid',gridTemplateColumns:'repeat(3,1fr)',gap:14,marginBottom:28}}>
        {QUICK.map(({to,icon,label,desc,key,adminOnly}) => {
          if (adminOnly && !isAdmin) return null
          const ok = canAccess(key)
          return (
            <button key={to} onClick={() => ok && nav(to)}
              style={{
                display:'flex',alignItems:'center',gap:14,padding:'16px 18px',
                borderRadius:'var(--r-lg)',
                background: ok ? 'var(--surface)' : 'var(--surface-2)',
                border:'1.5px solid var(--border)',
                cursor: ok ? 'pointer' : 'not-allowed',
                textAlign:'left',transition:'all .18s',
                boxShadow:'var(--sh-sm)',fontFamily:'inherit',
                opacity: ok ? 1 : 0.45,
              }}
              onMouseEnter={e=>{ if(ok){e.currentTarget.style.borderColor='var(--brand)';e.currentTarget.style.boxShadow='var(--sh-md)';e.currentTarget.style.transform='translateY(-2px)'}}}
              onMouseLeave={e=>{ if(ok){e.currentTarget.style.borderColor='var(--border)';e.currentTarget.style.boxShadow='var(--sh-sm)';e.currentTarget.style.transform='none'}}}
            >
              <div style={{fontSize:'1.75rem',lineHeight:1,flexShrink:0,filter:ok?'none':'grayscale(1)'}}>{icon}</div>
              <div style={{flex:1,minWidth:0}}>
                <div style={{fontWeight:700,fontSize:'.9rem',color:ok?'var(--text-1)':'var(--text-3)',marginBottom:2}}>{label}</div>
                <div style={{fontSize:'.78rem',color:'var(--text-3)',lineHeight:1.4}}>{desc}</div>
              </div>
              <ArrowRight size={16} color="var(--text-3)" style={{flexShrink:0,opacity:ok?1:0.3}}/>
            </button>
          )
        })}
      </div>

      {/* Reconciliation Sessions */}
      {sessions.length > 0 && (
        <div style={{marginBottom:24}}>
          <div style={{display:'flex',alignItems:'center',gap:10,marginBottom:14}}>
            <h2 style={{display:'flex',alignItems:'center',gap:8}}>
              <Folder size={20} color="var(--brand)"/> Reconciliation Sessions
            </h2>
            <span style={{fontSize:'.78rem',color:'var(--text-3)',marginLeft:'auto'}}>
              {sessions.length} session{sessions.length !== 1 ? 's' : ''}
            </span>
          </div>
          <div className="data-table-wrap">
            <table className="data-table">
              <thead>
                <tr>
                  <th>Date &amp; Time</th>
                  <th>Bank Accounts</th>
                  <th>Input Files</th>
                  <th>Status</th>
                  <th></th>
                </tr>
              </thead>
              <tbody>
                {sessions.map(s => (
                  <tr key={s.session_id} style={{cursor:'pointer'}}
                    onClick={() => nav('/reconciliation', {state:{openSession:s.session_id}})}
                    onMouseEnter={e => Array.from(e.currentTarget.cells).forEach(c => c.style.background='var(--brand-xlight)')}
                    onMouseLeave={e => Array.from(e.currentTarget.cells).forEach(c => c.style.background='')}>
                    <td>
                      <div style={{fontWeight:600,fontSize:'.8rem',color:'var(--text-1)'}}>
                        {s.display_name || s.session_id}
                      </div>
                      {s.datetime && (
                        <div style={{fontSize:'.72rem',color:'var(--text-3)'}}>
                          {new Date(s.datetime).toLocaleTimeString('en-AU',{hour:'2-digit',minute:'2-digit',second:'2-digit'})}
                        </div>
                      )}
                    </td>
                    <td>
                      {(s.account_count > 0) ? (
                        <div style={{display:'flex',alignItems:'center',gap:4,flexWrap:'wrap'}}>
                          <span style={{fontWeight:700,color:'var(--brand)',fontSize:'.8rem'}}>{s.account_count}</span>
                          {(s.accounts_meta || []).slice(0,3).map((a,i) => (
                            <span key={i} className="badge badge-neutral" style={{fontSize:'.65rem'}}>
                              {a.bank_name || a.bankName || '—'}
                            </span>
                          ))}
                        </div>
                      ) : <span style={{color:'var(--text-3)',fontSize:'.8rem'}}>—</span>}
                    </td>
                    <td>
                      {(s.file_count > 0)
                        ? <span style={{fontWeight:700,fontSize:'.8rem',color:'var(--text-2)'}}>{s.file_count}</span>
                        : <span style={{color:'var(--text-3)',fontSize:'.8rem'}}>—</span>}
                    </td>
                    <td>
                      {s.has_results
                        ? <span className="badge badge-success">✓ Results</span>
                        : <span className="badge badge-neutral">Pending</span>}
                    </td>
                    <td onClick={e => e.stopPropagation()}>
                      <button className="btn btn-ghost btn-icon btn-sm"
                        style={{color:'var(--text-3)'}}
                        onMouseEnter={e => e.currentTarget.style.color='var(--danger)'}
                        onMouseLeave={e => e.currentTarget.style.color='var(--text-3)'}
                        onClick={() => delSession(s.session_id)}>
                        <Trash2 size={13}/>
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <p style={{fontSize:'.75rem',color:'var(--text-3)',marginTop:8}}>
            Click any session to open it in Reconciliation with full input and output restored.
          </p>
        </div>
      )}

      {!loading && sessions.length === 0 && (
        <div className="card" style={{maxWidth:480}}>
          <div className="empty-state">
            <div className="empty-icon">📂</div>
            <h3>No sessions yet</h3>
            <p>Run your first bank reconciliation to see financial stats here. Data auto-refreshes every 30 seconds.</p>
            <button className="btn btn-primary" onClick={() => nav('/reconciliation')} style={{marginTop:12}}>
              Go to Reconciliation
            </button>
          </div>
        </div>
      )}
    </div>
  )
}