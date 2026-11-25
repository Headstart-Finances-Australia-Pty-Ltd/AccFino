import React, { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { useAuth } from '../hooks/useAuth.jsx'
import { getMyPlan } from '../lib/api'
import { X, ArrowRight, AlertTriangle, Clock } from 'lucide-react'

export default function UpgradeBanner() {
  const { user }              = useAuth()
  const navigate              = useNavigate()
  const [myPlan, setMyPlan]   = useState(null)
  const [dismissed, setDism]  = useState(false)

  useEffect(() => {
    if (!user?.id) return
    getMyPlan(user.id).then(r => setMyPlan(r.data)).catch(() => {})
    const refresh = () => getMyPlan(user.id).then(r => setMyPlan(r.data)).catch(() => {})
    window.addEventListener('accfino:modules-changed', refresh)
    return () => window.removeEventListener('accfino:modules-changed', refresh)
  }, [user?.id])

  if (!myPlan || dismissed) return null

  // Never show upgrade banner to admins or users on premium/bundle plans
  const isAdmin = Array.isArray(user?.roles) && user.roles.includes('admin')
  if (isAdmin) return null
  if (['premium', 'basic'].includes(myPlan.plan_id)) return null

  const endDate  = myPlan.end_date
  if (!endDate || endDate === '9999-12-31') return null

  const daysLeft = Math.ceil((new Date(endDate) - new Date()) / 86400000)
  if (daysLeft > 2) return null   // only show 2 days before expiry

  const expired  = daysLeft < 1
  const urgent   = daysLeft <= 1

  return (
    <div style={{
      position:       'fixed',
      top:            16,
      right:          16,
      zIndex:         9999,
      width:          340,
      borderRadius:   'var(--r-lg)',
      boxShadow:      '0 8px 32px rgba(0,0,0,.18)',
      background:     urgent ? '#FFF5F5' : '#FFFBEB',
      border:         `1px solid ${urgent ? '#FC8181' : '#F6E05E'}`,
      padding:        '14px 16px',
      display:        'flex',
      flexDirection:  'column',
      gap:            8,
      animation:      'slideIn .3s ease',
    }}>
      <style>{`
        @keyframes slideIn {
          from { transform: translateX(120%); opacity: 0; }
          to   { transform: translateX(0);   opacity: 1; }
        }
      `}</style>

      {/* Header row */}
      <div style={{ display:'flex', alignItems:'center', gap:8 }}>
        {urgent
          ? <AlertTriangle size={18} color="#E53E3E" style={{flexShrink:0}}/>
          : <Clock size={18} color="#D69E2E" style={{flexShrink:0}}/>}
        <strong style={{ fontSize:'.88rem', color: urgent ? '#C53030' : '#92400E', flex:1 }}>
          {expired
            ? 'Your plan has expired'
            : `Plan expires in ${daysLeft} day${daysLeft !== 1 ? 's' : ''}`}
        </strong>
        <button onClick={() => setDism(true)} style={{
          background:'none', border:'none', cursor:'pointer',
          color:'var(--text-3)', padding:2, display:'flex',
        }}>
          <X size={14}/>
        </button>
      </div>

      {/* Details */}
      <div style={{ fontSize:'.78rem', color:'var(--text-3)', lineHeight:1.5 }}>
        {expired
          ? 'Renew your plan to restore full access to your modules.'
          : `Your ${myPlan.plan_id} plan expires on ${endDate}. Renew now to avoid interruption.`}
      </div>

      {/* Action buttons */}
      <div style={{ display:'flex', gap:8, marginTop:4 }}>
        <button className="btn btn-primary btn-sm" onClick={() => navigate('/upgrade')}
          style={{ flex:1 }}>
          Renew Plan <ArrowRight size={13}/>
        </button>
        <button className="btn btn-ghost btn-sm" onClick={() => setDism(true)}>
          Later
        </button>
      </div>
    </div>
  )
}