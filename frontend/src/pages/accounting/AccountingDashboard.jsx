/**
 * AccountingDashboard — KPI stats + session list with delete.
 * Uses the same API calls as DashboardPage:
 *   /dashboard/stats?username=  → income, expenses, GST totals from latest session
 *   /sessions?username=          → all session objects with display_name
 *   /db/stats/{user_id}          → DB row count, last saved, currencies
 *   /sessions/{username}/{sid}   → DELETE a session
 */
import React, { useState, useEffect, useRef } from 'react'
import { useAuth } from '../../hooks/useAuth.jsx'
import { TrendingUp, TrendingDown, DollarSign, BarChart2, RefreshCw } from 'lucide-react'
import { getSessions, getDashboardStats, deleteSession as apiDeleteSession } from '../../lib/api.js'
import axios from 'axios'
import toast from 'react-hot-toast'

const http = axios.create({ baseURL: '/api', withCredentials: true })
http.interceptors.request.use(cfg => {
  try { const u = JSON.parse(localStorage.getItem('af_user')||'{}'); if (u.token) cfg.headers['Authorization'] = `Bearer ${u.token}` } catch {}
  return cfg
})

const fmtAUD  = n => new Intl.NumberFormat('en-AU',{style:'currency',currency:'AUD',minimumFractionDigits:2}).format(n||0)
const fmtK    = n => {
  const a = Math.abs(n||0)
  if (a >= 1000000) return `${(n/1000000).toFixed(1)}M`
  if (a >= 1000)    return `${(n/1000).toFixed(1)}K`
  return fmtAUD(n)
}
const fmtDate = d => d ? new Date(d).toLocaleDateString('en-AU') : '—'

export default function AccountingDashboard({ userId }) {
  const { user }  = useAuth()
  const username  = user?.username || user?.email || ''

  const [stats,           setStats]           = useState(null)
  const [dbStats,         setDbStats]         = useState(null)
  const [sessions,        setSessions]        = useState([])
  const [loading,         setLoading]         = useState(false)
  const [deletingSession, setDeletingSession] = useState(null)

  const usernameRef = useRef(username)
  useEffect(() => { usernameRef.current = username }, [username])

  const load = async () => {
    const uname = usernameRef.current
    if (!uname) return
    setLoading(true)
    try {
      const [statsRes, sessRes] = await Promise.all([
        getDashboardStats(uname),
        getSessions(uname),
      ])
      setStats(statsRes.data)
      setSessions(Array.isArray(sessRes.data) ? sessRes.data : [])

      // Also load DB stats if userId available
      if (userId) {
        http.get(`/db/stats/${userId}`)
          .then(r => setDbStats(r.data))
          .catch(() => {})
      }
    } catch {}
    finally { setLoading(false) }
  }

  useEffect(() => { load() }, [username, userId])

  const handleDeleteSession = async (sid) => {
    if (!confirm('Delete this session? This cannot be undone.')) return
    const uname = usernameRef.current
    setDeletingSession(sid)
    try {
      await apiDeleteSession(uname, sid)
      setSessions(p => p.filter(s => s.session_id !== sid))
      // Reload stats since latest session may have changed
      getDashboardStats(uname).then(r => setStats(r.data)).catch(() => {})
      toast.success('Session deleted')
    } catch { toast.error('Delete failed') }
    finally { setDeletingSession(null) }
  }

  const income  = stats?.total_in    || 0
  const expense = stats?.total_out   || 0
  const net     = stats?.net         || 0
  const gst     = stats?.total_gst   || 0
  const txns    = stats?.txn_count   || 0
  const sessCnt = stats?.session_count ?? sessions.length

  const KPI = ({ label, value, color, sub, icon: Icon }) => (
    <div style={{
      background:'var(--surface)', border:'1px solid var(--border)',
      borderRadius:'var(--r-lg)', padding:'16px 18px',
      boxShadow:'var(--sh-xs)', display:'flex', alignItems:'center', gap:14,
    }}>
      <div style={{
        width:40, height:40, borderRadius:'var(--r-md)', flexShrink:0,
        background: color + '22',
        display:'flex', alignItems:'center', justifyContent:'center',
      }}>
        <Icon size={18} color={color}/>
      </div>
      <div>
        <div style={{fontSize:'.7rem',fontWeight:700,color:'var(--text-3)',
          textTransform:'uppercase',letterSpacing:'.05em',marginBottom:4}}>{label}</div>
        <div style={{fontFamily:'var(--font-mono)',fontWeight:700,fontSize:'1rem',
          color: loading ? 'var(--text-3)' : color}}>
          {loading ? '…' : fmtK(value)}
        </div>
        {sub && <div style={{fontSize:'.7rem',color:'var(--text-3)',marginTop:2}}>{sub}</div>}
      </div>
    </div>
  )

  return (
    <div style={{padding:24}}>

      {/* ── Header ───────────────────────────────────────────────────────── */}
      <div style={{display:'flex',justifyContent:'space-between',alignItems:'center',marginBottom:16}}>
        <h3 style={{margin:0}}>Financial Overview</h3>
        <button className="btn btn-outline btn-sm" onClick={load} disabled={loading}>
          <RefreshCw size={13} className={loading?'spin':''}/> Refresh
        </button>
      </div>

      {/* ── KPI strip ─────────────────────────────────────────────────────── */}
      <div style={{display:'grid',gridTemplateColumns:'repeat(4,1fr)',gap:12,marginBottom:20}}>
        <KPI label="Total Income"    value={income}  color="#16a34a" sub={`${txns} transactions`}          icon={TrendingUp}/>
        <KPI label="Total Expenses"  value={expense} color="#dc2626" sub="From latest session"              icon={TrendingDown}/>
        <KPI label="Net Position"    value={net}     color={net>=0?"#16a34a":"#dc2626"} sub="Income − Expenses" icon={DollarSign}/>
        <KPI label="GST (total)"     value={gst}     color="#7c3aed" sub="From classified transactions"    icon={BarChart2}/>
      </div>

      {/* ── DB stats strip ────────────────────────────────────────────────── */}
      <div style={{display:'grid',gridTemplateColumns:'repeat(4,1fr)',gap:10,marginBottom:24}}>
        {[
          { l:'Sessions',          v: sessCnt },
          { l:'Transactions in DB',v: dbStats?.total?.toLocaleString() ?? '—' },
          { l:'Last Saved',        v: fmtDate(dbStats?.last_saved) },
          { l:'Currencies',        v: (dbStats?.currencies||[]).join(', ') || 'AUD' },
        ].map(({l,v}) => (
          <div key={l} style={{background:'var(--surface-2)',border:'1px solid var(--border)',
            borderRadius:'var(--r-md)',padding:'10px 14px'}}>
            <div style={{fontSize:'.7rem',fontWeight:700,color:'var(--text-3)',
              textTransform:'uppercase',letterSpacing:'.04em',marginBottom:4}}>{l}</div>
            <div style={{fontWeight:600,fontSize:'.875rem',fontFamily:'var(--font-mono)'}}>{v}</div>
          </div>
        ))}
      </div>

      {/* ── Sessions list ─────────────────────────────────────────────────── */}
      <div style={{border:'1px solid var(--border)',borderRadius:'var(--r-lg)',
        overflow:'hidden',boxShadow:'var(--sh-xs)'}}>
        <div style={{padding:'10px 16px',background:'var(--surface-2)',
          display:'flex',alignItems:'center',justifyContent:'space-between',
          borderBottom:'1px solid var(--border)'}}>
          <h3 style={{margin:0,fontSize:'.9rem'}}>
            📂 Reconciliation Sessions ({sessions.length})
          </h3>
        </div>

        {loading && sessions.length === 0 ? (
          <div style={{padding:32,textAlign:'center',color:'var(--text-3)'}}>Loading…</div>
        ) : sessions.length === 0 ? (
          <div style={{padding:40,textAlign:'center',color:'var(--text-3)'}}>
            <div style={{fontSize:'2rem',marginBottom:8}}>📂</div>
            <p>No sessions yet. Upload a bank CSV in the Reconciliation tab to get started.</p>
          </div>
        ) : (
          <>
            <table className="data-table" style={{fontSize:'.78rem'}}>
              <thead>
                <tr>
                  <th>Session</th>
                  <th>Date / Time</th>
                  <th>Has Results</th>
                  <th style={{width:80}}>Actions</th>
                </tr>
              </thead>
              <tbody>
                {sessions.map(s => (
                  <tr key={s.session_id}
                    style={{cursor:'pointer'}}
                    onClick={() => window.location.href = '/accounting'}>
                    <td style={{fontFamily:'var(--font-mono)',fontWeight:600,color:'var(--brand)'}}>
                      {s.session_id}
                    </td>
                    <td>{s.display_name || '—'}</td>
                    <td>
                      <span style={{
                        padding:'2px 8px',borderRadius:100,fontSize:'.72rem',fontWeight:700,
                        background: s.has_results ? '#dcfce7' : 'var(--surface-2)',
                        color:      s.has_results ? '#16a34a' : 'var(--text-3)',
                      }}>
                        {s.has_results ? '✓ Results saved' : 'No results'}
                      </span>
                    </td>
                    <td>
                      <button
                        className="btn btn-danger btn-xs"
                        disabled={deletingSession === s.session_id}
                        onClick={e => { e.stopPropagation(); handleDeleteSession(s.session_id) }}
                        style={{padding:'2px 8px'}}>
                        {deletingSession === s.session_id ? '…' : '🗑 Delete'}
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
            <div style={{padding:'8px 14px',fontSize:'.73rem',color:'var(--text-3)',
              borderTop:'1px solid var(--border)'}}>
              Click any session to open it in Reconciliation · KPI totals are from the latest session with results
            </div>
          </>
        )}
      </div>

      <div style={{marginTop:14,padding:'10px 14px',background:'var(--surface-2)',
        borderRadius:'var(--r-md)',border:'1px solid var(--border)',
        fontSize:'.75rem',color:'var(--text-3)'}}>
        💡 P&amp;L, Balance Sheet, GST/BAS and all financial reports are in the <strong>Financial Reports</strong> tab.
      </div>
    </div>
  )
}
