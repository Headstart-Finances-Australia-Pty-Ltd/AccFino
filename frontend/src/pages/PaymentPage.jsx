import React, { useEffect, useState } from 'react'
import { useNavigate, useSearchParams } from 'react-router-dom'
import TopBar from '../components/ui/TopBar.jsx'
import { useAuth } from '../hooks/useAuth.jsx'
import { createCheckout, getMyPlan, getPricingPlans } from '../lib/api'
import { Check, Star, Zap } from 'lucide-react'
import toast from 'react-hot-toast'

const HIDDEN_KEYS = ['base', 'admin', 'file-manager', 'licence', 'dashboard', 'reconciliation', 'cashflow', 'invoice', 'full_bundle']

// Category groups for display
const CATEGORIES = [
  {
    key:   'accounting',
    emoji: '🏦',
    label: 'Accounting',
    color: '#2563eb',
    bg:    '#eff6ff',
    desc:  'Reconciliation · Sales · Purchases · Cash Flow · Financial Reports',
  },
  {
    key:   'trading',
    emoji: '🧾',
    label: 'Taxation & Trading',
    color: '#7c3aed',
    bg:    '#f5f3ff',
    desc:  'Crypto · Equity · Property CGT · Full Australian Tax Return',
  },
  {
    key:   'payroll',
    emoji: '👔',
    label: 'Payroll',
    color: '#0891b2',
    bg:    '#ecfeff',
    desc:  'PAYG · Superannuation · Payslips · STP Phase 2',
  },
  {
    key:   'lending',
    emoji: '🏦',
    label: 'Smart Lending',
    color: '#0891b2',
    bg:    '#ecfeff',
    desc:  'Bank statement analysis · AU responsible lending · ASIC RG 209 · APRA',
  },
  {
    key:   'bundle',
    emoji: '⭐',
    label: 'Bundles',
    color: '#d97706',
    bg:    '#fffbeb',
    desc:  'Combine modules and save — best value plans',
  },
]

const fmtPrice = (cents, period) => {
  if (!cents) return 'Free'
  const dollars = cents / 100
  return period === 'yearly'
    ? `$${dollars / 12 % 1 === 0 ? dollars/12 : (dollars/12).toFixed(0)}/mo`
    : `$${dollars}/mo`
}

const fmtYearly = (cents) => {
  if (!cents) return null
  return `$${cents / 100}/yr`
}

export default function PaymentPage() {
  const { user }       = useAuth()
  const navigate       = useNavigate()
  const [searchParams] = useSearchParams()

  const [plans,    setPlans]    = useState({})
  const [myPlan,   setMyPlan]   = useState(null)
  const [billing,  setBilling]  = useState('monthly')
  const [selKey,   setSelKey]   = useState(null)
  const [paying,   setPaying]   = useState(false)
  const [loading,  setLoading]  = useState(true)

  useEffect(() => {
    if (searchParams.get('success')) {
      toast.success('🎉 Payment successful! Your plan has been upgraded.')
      window.dispatchEvent(new Event('accfino:modules-changed'))
      setTimeout(() => navigate(user ? '/' : '/login', { replace: true }), 1500)
    }
    if (searchParams.get('cancelled')) toast('Payment cancelled.', { icon: 'ℹ️' })
  }, [])

  useEffect(() => {
    Promise.all([
      getPricingPlans(),
      user?.id ? getMyPlan(user.id) : Promise.resolve({ data: null }),
    ]).then(([pr, mr]) => {
      setPlans(pr.data || {})
      setMyPlan(mr.data)
    }).catch(() => toast.error('Could not load pricing'))
      .finally(() => setLoading(false))
  }, [user?.id])

  // Group plans by category
  const grouped = React.useMemo(() => {
    const result = {}
    Object.entries(plans).forEach(([key, plan]) => {
      if (HIDDEN_KEYS.includes(key)) return
      const cat = plan.category || (key === 'premium' ? 'bundle' : 'other')
      if (!result[cat]) result[cat] = []
      result[cat].push({ key, plan })
    })
    return result
  }, [plans])

  const selected = selKey ? plans[selKey] : null
  const price    = selected
    ? (billing === 'yearly' ? selected.price_yearly : selected.price_monthly)
    : 0

  const handleCheckout = async () => {
    if (!user) { navigate('/login'); return }
    if (!selKey) return
    setPaying(true)
    try {
      const mods   = selected?.modules || ['dashboard']
      const { data } = await createCheckout({
        plan_id:        selKey,
        billing_period: billing,
        user_id:        user.id,
        user_email:     user.email,
        modules:        mods,
        amount:         price,
        plan_name:      selected?.name || selKey,
      })
      if (data.checkout_url) window.location.href = data.checkout_url
    } catch (e) {
      toast.error(e.response?.data?.detail || 'Checkout failed')
    } finally { setPaying(false) }
  }

  return (
    <>
    <TopBar
      variant="marketing"
      onSignIn={() => navigate('/login')}
      onStartFree={() => navigate('/login?tab=register')}
    />

    <div style={{ paddingTop:56, minHeight:'100vh', background:'var(--bg,#f8fafc)' }}>
      <div style={{ maxWidth:1100, margin:'0 auto', padding:'40px 24px' }}>

        {/* Header */}
        <div style={{ textAlign:'center', marginBottom:40 }}>
          <h1 style={{ fontSize:'2rem', fontWeight:800, marginBottom:10 }}>
            AccFino Pricing
          </h1>
          <p style={{ color:'var(--text-3)', fontSize:'1rem', marginBottom:20 }}>
            Pick the modules your business needs. Start free, upgrade anytime.
          </p>

          {/* Billing toggle */}
          <div style={{ display:'inline-flex', borderRadius:100, overflow:'hidden',
            border:'1px solid var(--border)', background:'var(--surface)' }}>
            {['monthly','yearly'].map(p => (
              <button key={p} onClick={() => setBilling(p)} style={{
                padding:'8px 24px', border:'none', cursor:'pointer', fontFamily:'inherit',
                fontSize:'.85rem', fontWeight:600,
                background: billing===p ? 'var(--brand)' : 'transparent',
                color:      billing===p ? '#fff'         : 'var(--text-2)',
                transition: 'background .15s',
              }}>
                {p === 'monthly' ? 'Monthly' : 'Yearly'}{p === 'yearly' ? ' (save ~17%)' : ''}
              </button>
            ))}
          </div>

          {/* Current plan */}
          {myPlan && (
            <div style={{ marginTop:12, fontSize:'.82rem', color:'var(--text-3)' }}>
              Current plan: <strong>{plans[myPlan.plan_id]?.name || myPlan.plan_id}</strong>
            </div>
          )}
        </div>

        {/* Free plan banner */}
        <div style={{
          display:'flex', alignItems:'center', justifyContent:'space-between',
          padding:'14px 20px', marginBottom:32,
          background:'#f0fdf4', border:'1px solid #bbf7d0', borderRadius:'var(--r-lg)',
        }}>
          <div>
            <span style={{ fontWeight:700, marginRight:10 }}>🆓 Vault Plan — Free forever</span>
            <span style={{ fontSize:'.82rem', color:'#166534' }}>
              CSV Reconciliation (up to 1,000 txns/mo) · Accounting Dashboard · Basic Sales & Purchases
            </span>
          </div>
          <button className="btn btn-outline btn-sm" onClick={() => navigate(user ? '/' : '/login')}
            style={{ borderColor:'#16a34a', color:'#16a34a', whiteSpace:'nowrap' }}>
            {user ? 'You have this' : 'Get started free'}
          </button>
        </div>

        {/* Category sections */}
        {loading ? (
          <div style={{ textAlign:'center', padding:60, color:'var(--text-3)' }}>Loading plans…</div>
        ) : (
          CATEGORIES.map(cat => {
            const catPlans = grouped[cat.key] || []
            if (!catPlans.length) return null
            return (
              <div key={cat.key} style={{ marginBottom:40 }}>
                {/* Category header */}
                <div style={{ display:'flex', alignItems:'center', gap:10, marginBottom:16 }}>
                  <div style={{
                    width:38, height:38, borderRadius:'var(--r-md)',
                    background:cat.bg, display:'flex', alignItems:'center',
                    justifyContent:'center', fontSize:'1.2rem', flexShrink:0,
                    border:`1px solid ${cat.color}22`,
                  }}>{cat.emoji}</div>
                  <div>
                    <h2 style={{ margin:0, fontSize:'1.1rem', fontWeight:700, color:'var(--text-1)' }}>
                      {cat.label}
                    </h2>
                    <div style={{ fontSize:'.78rem', color:'var(--text-3)', marginTop:2 }}>{cat.desc}</div>
                  </div>
                </div>

                {/* Plan cards */}
                <div style={{
                  display:'grid',
                  gridTemplateColumns:`repeat(${Math.min(catPlans.length, 3)}, 1fr)`,
                  gap:16,
                }}>
                  {catPlans.map(({ key, plan }) => {
                    const isSelected = selKey === key
                    const isCurrent  = myPlan?.plan_id === key
                    const mo = billing === 'yearly'
                      ? Math.round(plan.price_yearly / 12 / 100)
                      : plan.price_monthly / 100
                    const yr = plan.price_yearly ? `$${plan.price_yearly / 100}/yr` : null

                    return (
                      <div key={key}
                        onClick={() => setSelKey(isSelected ? null : key)}
                        style={{
                          border: `2px solid ${isSelected ? cat.color : isCurrent ? '#16a34a' : 'var(--border)'}`,
                          borderRadius:'var(--r-xl,16px)', padding:'20px',
                          background: isSelected ? cat.bg : 'var(--surface)',
                          cursor:'pointer', position:'relative',
                          transition:'border-color .15s, box-shadow .15s',
                          boxShadow: isSelected ? `0 0 0 3px ${cat.color}22` : 'var(--sh-sm)',
                        }}>

                        {/* Badges */}
                        <div style={{ display:'flex', justifyContent:'space-between', marginBottom:8 }}>
                          <span style={{ fontWeight:800, fontSize:'.9rem', color:'var(--text-1)' }}>
                            {plan.name}
                          </span>
                          <div style={{ display:'flex', gap:6 }}>
                            {plan.highlight && (
                              <span style={{ padding:'2px 8px', borderRadius:100, fontSize:'.65rem',
                                fontWeight:700, background:cat.color, color:'#fff', whiteSpace:'nowrap' }}>
                                <Star size={9}/> {plan.badge || 'Popular'}
                              </span>
                            )}
                            {plan.badge && !plan.highlight && (
                              <span style={{ padding:'2px 8px', borderRadius:100, fontSize:'.65rem',
                                fontWeight:700, background:'#fef3c7', color:'#92400e', whiteSpace:'nowrap' }}>
                                {plan.badge}
                              </span>
                            )}
                            {isCurrent && (
                              <span style={{ padding:'2px 8px', borderRadius:100, fontSize:'.65rem',
                                fontWeight:700, background:'#dcfce7', color:'#166534' }}>
                                ✓ Current
                              </span>
                            )}
                          </div>
                        </div>

                        {/* Price */}
                        <div style={{ marginBottom:12 }}>
                          <span style={{
                            fontFamily:'var(--font-mono)', fontWeight:800,
                            fontSize:'1.6rem', color: cat.color,
                          }}>
                            {mo === 0 ? 'Free' : `$${mo}`}
                          </span>
                          {mo > 0 && <span style={{ fontSize:'.8rem', color:'var(--text-3)', marginLeft:4 }}>/mo</span>}
                          {yr && billing === 'yearly' && (
                            <div style={{ fontSize:'.72rem', color:'var(--text-3)', marginTop:2 }}>
                              Billed {yr}
                            </div>
                          )}
                        </div>

                        {/* Description */}
                        <div style={{ fontSize:'.78rem', color:'var(--text-3)', marginBottom:14, lineHeight:1.5 }}>
                          {plan.description}
                        </div>

                        {/* Features */}
                        <div style={{ display:'flex', flexDirection:'column', gap:6 }}>
                          {(plan.features || []).map(f => (
                            <div key={f} style={{ display:'flex', alignItems:'flex-start', gap:7, fontSize:'.78rem' }}>
                              <Check size={12} color={cat.color} style={{ flexShrink:0, marginTop:2 }}/>
                              <span style={{ color:'var(--text-2)' }}>{f}</span>
                            </div>
                          ))}
                        </div>

                        {/* Selected tick */}
                        {isSelected && (
                          <div style={{
                            position:'absolute', top:12, right:12,
                            width:22, height:22, borderRadius:'50%',
                            background:cat.color, display:'flex',
                            alignItems:'center', justifyContent:'center',
                          }}>
                            <Check size={13} color="#fff"/>
                          </div>
                        )}
                      </div>
                    )
                  })}
                </div>
              </div>
            )
          })
        )}

        {/* Sticky checkout bar */}
        {selKey && selected && (
          <div style={{
            position:'sticky', bottom:20, zIndex:50,
            background:'var(--surface)', border:'2px solid var(--brand)',
            borderRadius:'var(--r-xl)', padding:'16px 24px',
            display:'flex', alignItems:'center', justifyContent:'space-between',
            boxShadow:'0 8px 32px rgba(0,0,0,.15)', gap:16, flexWrap:'wrap',
          }}>
            <div>
              <div style={{ fontWeight:700, fontSize:'.95rem' }}>
                {selected.name}
                {billing === 'yearly' && selected.price_yearly
                  ? ` — $${selected.price_yearly/100}/yr`
                  : selected.price_monthly
                    ? ` — $${selected.price_monthly/100}/mo`
                    : ''}
              </div>
              <div style={{ fontSize:'.75rem', color:'var(--text-3)', marginTop:2 }}>
                {(selected.modules || []).join(' · ')}
              </div>
            </div>
            <div style={{ display:'flex', gap:10, alignItems:'center' }}>
              <button className="btn btn-ghost btn-sm" onClick={() => setSelKey(null)}>
                Clear
              </button>
              <button className="btn btn-primary" onClick={handleCheckout} disabled={paying}
                style={{ minWidth:160 }}>
                {paying
                  ? <><span className="spinner spinner-sm"/> Processing…</>
                  : user ? <><Zap size={14}/> Subscribe Now</> : 'Sign in to subscribe'
                }
              </button>
            </div>
          </div>
        )}

        {/* Footer note */}
        <div style={{
          textAlign:'center', marginTop:40, fontSize:'.75rem',
          color:'var(--text-3)', lineHeight:1.7,
        }}>
          🔒 Secured by Stripe · Cancel anytime · All prices in AUD including GST<br/>
          Need a custom plan? <a href="mailto:support@accfino.com" style={{ color:'var(--brand)' }}>Contact us</a>
        </div>
      </div>
    </div>
    </>
  )
}
