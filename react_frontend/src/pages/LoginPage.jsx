import React, { useState, useEffect } from 'react'
import { useNavigate, useSearchParams } from 'react-router-dom'
import { useAuth } from '../hooks/useAuth.jsx'
import { register, forgotPassword, getPricingPlans, createCheckout } from '../lib/api.js'
import { Eye, EyeOff, ArrowRight } from 'lucide-react'
import toast from 'react-hot-toast'
import TopBar from '../components/ui/TopBar.jsx'

export default function LoginPage() {
  const { login, loading } = useAuth()
  const navigate = useNavigate()
  const [searchParams] = useSearchParams()

  const [tab, setTab] = useState('login')
  const [showPw, setShowPw] = useState(false)
  const [err, setErr] = useState('')
  const [submitting, setSubmitting] = useState(false)
  const [plans, setPlans] = useState({})
  const [selPlan, setSelPlan] = useState('base')

  const [showPayModal, setShowPayModal] = useState(false)
  const [payLoading, setPayLoading] = useState(false)
  const [pendingUser, setPendingUser] = useState(null)

  // forgot password
  const [showForgot, setShowForgot] = useState(false)
  const [forgotEmail, setForgotEmail] = useState('')
  const [forgotStatus, setForgotStatus] = useState('idle')
  const [forgotErr, setForgotErr] = useState('')

  const [form, setForm] = useState({
    email: '',
    password: '',
    name: '',
    username: '',
    phone: '',
    address: '',
  })

  const set = k => e => {
    setForm(f => ({ ...f, [k]: e.target.value }))
    setErr('')
  }

  useEffect(() => {
    getPricingPlans().then(r => setPlans(r.data || {})).catch(() => {})

    // Auto-switch to register tab if ?tab=register in URL
    const tabParam = searchParams.get('tab')
    const planParam = searchParams.get('plan')

    if (tabParam === 'register') setTab('register')
    if (planParam) setSelPlan(planParam)
  }, []) // eslint-disable-line

  // ── Login ──────────────────────────────────────────────────────────────────
  const handleLogin = async e => {
    e.preventDefault()
    setErr('')

    const res = await login(form.email, form.password)

    if (res.ok) navigate('/', { replace: true })
    else setErr(res.error)
  }

  // ── Register ───────────────────────────────────────────────────────────────
  const handleRegister = async e => {
    e.preventDefault()
    setErr('')
    setSubmitting(true)

    try {
      const userData = await register({
        username: form.username.trim(),
        full_name: form.name.trim(),
        email: form.email.trim(),
        password: form.password.trim(),
        role: 'user',
        phone: form.phone.trim(),
        address: '',
        home_company: (form.home_company || '').trim(),
      })

      if (selPlan === 'base') {
        // Free plan — just log in
        toast.success('Account created — signing you in…')

        const res = await login(
          form.email.trim(),
          form.password.trim()
        )

        if (res.ok) {
          navigate('/', { replace: true })
        } else {
          setTab('login')
          toast.success('Account created — please sign in')
        }
      } else {
        // Paid plan — show payment modal
        setPendingUser({
          email: form.email.trim(),
          password: form.password.trim(),
        })

        setShowPayModal(true)
      }
    } catch (ex) {
      setErr(
        ex.response?.data?.detail ||
          'Registration failed. Email or username may already exist.'
      )
    } finally {
      setSubmitting(false)
    }
  }

  // ── Payment modal checkout ─────────────────────────────────────────────────
  const handlePayNow = async () => {
    setPayLoading(true)

    try {
      const { data } = await createCheckout({
        plan_id: selPlan,
        billing_period: 'monthly',
        user_id: pendingUser?.id || 0,
        user_email: pendingUser?.email || form.email,
      })

      if (data.checkout_url) {
        window.location.href = data.checkout_url
      }
    } catch (e) {
      toast.error(
        e.response?.data?.detail ||
          'Payment failed — try again'
      )
    } finally {
      setPayLoading(false)
    }
  }

  const handlePayLater = async () => {
    // Skip payment — log in on free/demo
    setShowPayModal(false)

    if (pendingUser) {
      const res = await login(
        pendingUser.email,
        pendingUser.password
      )

      if (res.ok) navigate('/', { replace: true })
      else {
        setTab('login')
        toast.success('Account created — please sign in')
      }
    }
  }

  // ── Forgot password ────────────────────────────────────────────────────────
  const handleForgot = async e => {
    e.preventDefault()

    setForgotErr('')
    setForgotStatus('loading')

    try {
      await forgotPassword(forgotEmail.trim())

      setForgotStatus('sent')

      setTimeout(() => {
        setShowForgot(false)
        setForgotStatus('idle')
        setForgotEmail('')
      }, 30000)
    } catch {
      setForgotStatus('error')
      setForgotErr('Something went wrong. Please try again.')
    }
  }

  const closeForgot = () => {
    setShowForgot(false)
    setForgotStatus('idle')
    setForgotEmail('')
    setForgotErr('')
  }

  // ── Plan helpers ───────────────────────────────────────────────────────────
  const planList = Object.entries(plans)
  const selPlanData = plans[selPlan]
  const planPrice = selPlanData?.price_monthly || 0

  return (
    <>
      <TopBar
        variant="marketing"
        onSignIn={() => { setTab('login'); setErr('') }}
        onStartFree={() => { setTab('register'); setErr('') }}
      />

      <div className="login-page">
        {/* ── Centred form panel ── */}
        <div className="login-right">
          <div className="login-form-wrap">
            {/* Heading */}
            <div style={{ marginBottom: 16 }}>
              <h1 style={{ fontSize: '1.5rem', marginBottom: 6 }}>
                {tab === 'login'
                  ? 'Welcome to Accfino'
                  : 'Create your account'}
              </h1>

              <p
                style={{
                  color: 'var(--text-3)',
                  fontSize: '1rem',
                }}
              >
                {tab === 'login'
                  ? 'Sign in to your Accfino account'
                  : 'Start your Accfino journey today'}
              </p>
            </div>

            {/* ── Subscription plans (register only) ── */}
            {tab === 'register' && planList.length > 0 && (
              <div
                style={{
                  background: 'var(--surface-2)',
                  borderRadius: 'var(--r-md)',
                  padding: '10px 14px',
                  marginBottom: 18,
                  border: '.78px solid var(--border)',
                }}
              >
                <div
                  style={{
                    fontSize: '.72rem',
                    fontWeight: 700,
                    color: 'var(--text-3)',
                    textTransform: 'uppercase',
                    letterSpacing: '.06em',
                    marginBottom: 8,
                  }}
                >
                  Subscription Plans
                </div>

                <div
                  style={{
                    display: 'flex',
                    flexWrap: 'wrap',
                    gap: 6,
                    alignItems: 'center',
                  }}
                >
                  {Object.keys(plans).map(id => {
                    const plan = plans[id]
                    if (!plan) return null

                    const price = plan.price_monthly
                    const active = selPlan === id

                    return (
                      <button
                        key={id}
                        type="button"
                        onClick={() => setSelPlan(id)}
                        style={{
                          padding: '5px 12px',
                          borderRadius: 100,
                          border: 'none',
                          cursor: 'pointer',
                          background: active
                            ? '#1a73e8'
                            : id === 'premium'
                              ? '#EAF1FB'
                              : 'var(--surface)',
                          color: active
                            ? '#fff'
                            : id === 'premium'
                              ? '#1a73e8'
                              : 'var(--text-1)',
                          fontSize: '.72rem',
                          fontWeight: active ? 700 : 600,
                          boxShadow: active
                            ? 'var(--sh-sm)'
                            : 'none',
                          transition: 'all .15s',
                          outline: active
                            ? 'none'
                            : '1px solid var(--border)',
                        }}
                      >
                        {plan.name}

                        <span
                          style={{
                            marginLeft: 5,
                            opacity: 0.75,
                            fontSize: '.8rem',
                            fontWeight: 400,
                          }}
                        >
                          {price === 0
                            ? <span style={{color: active ? '#fff' : '#1a73e8'}}>— Free</span>
                            : `— $${price / 100}/mo`}
                        </span>
                      </button>
                    )
                  })}

                  <a href="/index-marketing.html#pricing"
                    style={{ color: '#1a73e8', textDecoration: 'underline', fontWeight: 600, fontSize: '.9rem' }}
                  >Full pricing details →</a>
                </div>

                {selPlanData && (
                  <div
                    style={{
                      marginTop: 8,
                      fontSize: '1rem',
                      color: 'var(--text-3)',
                    }}
                  >
                    {planPrice === 0
                      ? '✓ Free for 6 months — no payment required'
                      : `✓ ${selPlanData.name} — $${planPrice/100}/mo · secure payment via Stripe after registration`}
                  </div>
                )}
              </div>
            )}

            {/* ── Login form ── */}
            {tab === 'login' ? (
              <form
                onSubmit={handleLogin}
                style={{
                  display: 'flex',
                  flexDirection: 'column',
                  gap: 16,
                }}
              >
                <div className="input-group">
                  <label>Email or Username</label>

                  <input
                    className="input"
                    type="text"
                    value={form.email}
                    onChange={set('email')}
                    required
                    placeholder="you@company.com.au"
                    autoFocus
                    autoComplete="username"
                  />
                </div>

                <div className="input-group">
                  <label>Password</label>

                  <div style={{ position: 'relative' }}>
                    <input
                      className="input"
                      type={showPw ? 'text' : 'password'}
                      value={form.password}
                      onChange={set('password')}
                      required
                      placeholder="••••••••"
                      style={{ paddingRight: 42 }}
                      autoComplete="current-password"
                    />

                    <button
                      type="button"
                      onClick={() => setShowPw(s => !s)}
                      style={{
                        position: 'absolute',
                        right: 12,
                        top: '50%',
                        transform: 'translateY(-50%)',
                        background: 'none',
                        border: 'none',
                        cursor: 'pointer',
                        color: 'var(--text-3)',
                        display: 'flex',
                        padding: 0,
                      }}
                    >
                      {showPw ? (
                        <EyeOff size={16} />
                      ) : (
                        <Eye size={16} />
                      )}
                    </button>
                  </div>
                </div>

                {err && (
                  <div className="alert alert-error">
                    {err}
                  </div>
                )}

                <button
                  className="btn btn-primary btn-xl btn-full"
                  type="submit"
                  disabled={loading}
                  style={{ marginTop: 4 }}
                >
                  {loading ? (
                    <>
                      <span className="spinner spinner-sm" />{' '}
                      Signing in…
                    </>
                  ) : (
                    <>
                      Sign In <ArrowRight size={16} />
                    </>
                  )}
                </button>

                <div
                  style={{
                    textAlign: 'center',
                    marginTop: 4,
                  }}
                >
                  <button
                    type="button"
                    onClick={() => setShowForgot(true)}
                    style={{
                      background: 'none',
                      border: 'none',
                      cursor: 'pointer',
                      fontSize: '.82rem',
                      color: 'var(--text-3)',
                      textDecoration: 'underline',
                      fontFamily: 'inherit',
                      padding: 0,
                    }}
                  >
                    Forgot your password?
                  </button>
                </div>
              </form>
            ) : (
              /* ── Register form ── */
              <form
                onSubmit={handleRegister}
                style={{
                  display: 'flex',
                  flexDirection: 'column',
                  gap: 13,
                }}
              >
                <div className="grid-2">
                  <div className="input-group">
                    <label>Full Name</label>

                    <input
                      className="input"
                      type="text"
                      value={form.name}
                      onChange={set('name')}
                      required
                      placeholder="Jane Smith"
                    />
                  </div>

                  <div className="input-group">
                    <label>Username</label>

                    <input
                      className="input"
                      type="text"
                      value={form.username}
                      onChange={set('username')}
                      required
                      placeholder="jsmith"
                    />
                  </div>
                </div>

                <div className="input-group">
                  <label>Email</label>

                  <input
                    className="input"
                    type="email"
                    value={form.email}
                    onChange={set('email')}
                    required
                    placeholder="jane@company.com.au"
                  />
                </div>

                <div className="input-group">
                  <label>Password</label>

                  <div style={{ position: 'relative' }}>
                    <input
                      className="input"
                      type={showPw ? 'text' : 'password'}
                      value={form.password}
                      onChange={set('password')}
                      required
                      placeholder="Min. 8 characters"
                      style={{ paddingRight: 42 }}
                    />

                    <button
                      type="button"
                      onClick={() => setShowPw(s => !s)}
                      style={{
                        position: 'absolute',
                        right: 12,
                        top: '50%',
                        transform: 'translateY(-50%)',
                        background: 'none',
                        border: 'none',
                        cursor: 'pointer',
                        color: 'var(--text-3)',
                        display: 'flex',
                        padding: 0,
                      }}
                    >
                      {showPw ? (
                        <EyeOff size={16} />
                      ) : (
                        <Eye size={16} />
                      )}
                    </button>
                  </div>
                </div>

                <div className="input-group">
                  <label>Phone</label>

                  <input
                    className="input"
                    type="tel"
                    value={form.phone}
                    onChange={set('phone')}
                    placeholder="+61 4xx xxx xxx"
                  />
                </div>
                <div className="input-group">
                  <label>Company Name</label>
                  <input
                    className="input"
                    type="text"
                    value={form.home_company||''}
                    onChange={e=>setForm(f=>({...f,home_company:e.target.value}))}
                    placeholder="e.g. Headstart Finances Australia Pty Ltd"
                  />
                </div>

                {/* Plan selector dropdown */}
                <div className="input-group">
                  <label>Subscription Plan</label>

                  <select
                    className="input"
                    value={selPlan}
                    onChange={e => setSelPlan(e.target.value)}
                  >
                    {planList.map(([id, plan]) => (
                      <option key={id} value={id}>
                        {plan.name} —{' '}
                        {plan.price_monthly === 0
                          ? 'Free · 6 months'
                          : `$${plan.price_monthly/100}/mo`}
                        {plan.badge
                          ? ` (${plan.badge})`
                          : ''}
                      </option>
                    ))}
                  </select>

                  {selPlanData && (
                    <div
                      style={{
                        fontSize: '.75rem',
                        color: 'var(--text-3)',
                        marginTop: 4,
                      }}
                    >
                      {selPlanData.features?.[0]}
                      {planPrice > 0 &&
                        ' · Payment via Stripe after account creation'}
                    </div>
                  )}
                </div>

                {err && (
                  <div className="alert alert-error">
                    {err}
                  </div>
                )}

                <button
                  className="btn btn-primary btn-xl btn-full"
                  type="submit"
                  disabled={submitting}
                  style={{ marginTop: 4 }}
                >
                  {submitting ? (
                    <>
                      <span className="spinner spinner-sm" />{' '}
                      Creating account…
                    </>
                  ) : planPrice > 0 ? (
                    <>
                      Register & Pay{' '}
                      <ArrowRight size={16} />
                    </>
                  ) : (
                    <>
                      Create Free Account{' '}
                      <ArrowRight size={16} />
                    </>
                  )}
                </button>
              </form>
            )}

            <p
              style={{
                textAlign: 'center',
                color: 'var(--text-3)',
                fontSize: '1rem',
                marginTop: 28,
              }}
            >
              © {new Date().getFullYear()} Accfino ·
              Accounting & Finance Operations Platform
              <br />
              <span style={{ opacity: 0.6 }}>
                Powered by Prama AI engine
              </span>
            </p>
          </div>
        </div>
      </div>

      {/* ── Forgot Password Modal ── */}
      {showForgot && (
        <div
          style={{
            position: 'fixed',
            inset: 0,
            zIndex: 1000,
            background: 'rgba(0,0,0,.55)',
            backdropFilter: 'blur(4px)',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            padding: 16,
          }}
          onClick={closeForgot}
        >
          <div
            style={{
              background: 'var(--surface)',
              borderRadius: 'var(--r-lg)',
              padding: '32px 28px',
              width: '100%',
              maxWidth: 400,
              boxShadow:
                '0 24px 64px rgba(0,0,0,.25)',
              position: 'relative',
            }}
            onClick={e => e.stopPropagation()}
          >
            <button
              onClick={closeForgot}
              style={{
                position: 'absolute',
                top: 14,
                right: 14,
                background: 'none',
                border: 'none',
                cursor: 'pointer',
                color: 'var(--text-3)',
                fontSize: '1.2rem',
                lineHeight: 1,
                padding: 4,
              }}
            >
              ✕
            </button>

            {forgotStatus === 'sent' ? (
              <div
                style={{
                  textAlign: 'center',
                  padding: '8px 0',
                }}
              >
                <div
                  style={{
                    fontSize: '2.5rem',
                    marginBottom: 12,
                  }}
                >
                  📧
                </div>

                <h3 style={{ marginBottom: 8 }}>
                  Check your email
                </h3>

                <p
                  style={{
                    color: 'var(--text-3)',
                    fontSize: '1rem',
                    lineHeight: 1.7,
                  }}
                >
                  A password reset link has been sent
                  to <strong>{forgotEmail}</strong>.
                </p>

                <button
                  className="btn btn-primary btn-full"
                  onClick={closeForgot}
                  style={{ marginTop: 20 }}
                >
                  Close
                </button>
              </div>
            ) : (
              <>
                <h3 style={{ marginBottom: 6 }}>
                  Reset your password
                </h3>

                <p
                  style={{
                    color: 'var(--text-3)',
                    fontSize: '1rem',
                    marginBottom: 20,
                  }}
                >
                  Enter your email and we'll send
                  you a reset link.
                </p>

                <form
                  onSubmit={handleForgot}
                  style={{
                    display: 'flex',
                    flexDirection: 'column',
                    gap: 14,
                  }}
                >
                  <div className="input-group">
                    <label>Email address</label>

                    <input
                      className="input"
                      type="email"
                      value={forgotEmail}
                      onChange={e => {
                        setForgotEmail(
                          e.target.value
                        )
                        setForgotErr('')
                      }}
                      required
                      placeholder="you@company.com.au"
                      autoFocus
                    />
                  </div>

                  {forgotErr && (
                    <div className="alert alert-error">
                      {forgotErr}
                    </div>
                  )}

                  <button
                    className="btn btn-primary btn-full"
                    type="submit"
                    disabled={
                      forgotStatus === 'loading'
                    }
                  >
                    {forgotStatus === 'loading' ? (
                      <>
                        <span className="spinner spinner-sm" />{' '}
                        Sending…
                      </>
                    ) : (
                      'Send Reset Link'
                    )}
                  </button>
                </form>
              </>
            )}
          </div>
        </div>
      )}

      {/* ── Payment Modal ── */}
      {showPayModal && selPlanData && (
        <div
          style={{
            position: 'fixed',
            inset: 0,
            zIndex: 1000,
            background: 'rgba(0,0,0,.6)',
            backdropFilter: 'blur(4px)',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            padding: 16,
          }}
        >
          <div
            style={{
              background: 'var(--surface)',
              borderRadius: 'var(--r-lg)',
              padding: '32px 28px',
              width: '100%',
              maxWidth: 440,
              boxShadow:
                '0 24px 64px rgba(0,0,0,.3)',
            }}
          >
            <div
              style={{
                textAlign: 'center',
                marginBottom: 20,
              }}
            >
              <div
                style={{
                  fontSize: '2rem',
                  marginBottom: 8,
                }}
              >
                🎉
              </div>

              <h3 style={{ marginBottom: 4 }}>
                Account created!
              </h3>

              <p
                style={{
                  color: 'var(--text-3)',
                  fontSize: '.875rem',
                }}
              >
                Complete your{' '}
                <strong>{selPlanData.name}</strong>{' '}
                subscription to activate all
                features.
              </p>
            </div>

            <div
              style={{
                background: 'var(--surface-2)',
                borderRadius: 'var(--r-md)',
                padding: '14px 16px',
                marginBottom: 20,
              }}
            >
              <div
                style={{
                  display: 'flex',
                  justifyContent:
                    'space-between',
                  alignItems: 'center',
                }}
              >
                <span style={{ fontWeight: 600 }}>
                  {selPlanData.name}
                </span>

                <span
                  style={{
                    fontWeight: 700,
                    color: 'var(--brand)',
                    fontSize: '1.1rem',
                  }}
                >
                  ${planPrice/100}/mo
                </span>
              </div>

              <div
                style={{
                  marginTop: 8,
                  display: 'flex',
                  flexWrap: 'wrap',
                  gap: 4,
                }}
              >
                {(selPlanData.features || [])
                  .slice(0, 3)
                  .map((f, i) => (
                    <span
                      key={i}
                      style={{
                        fontSize: '.72rem',
                        color: 'var(--text-3)',
                      }}
                    >
                      ✓ {f}
                    </span>
                  ))}
              </div>
            </div>

            <div
              style={{
                display: 'flex',
                flexDirection: 'column',
                gap: 10,
              }}
            >
              <button
                className="btn btn-primary btn-xl btn-full"
                onClick={handlePayNow}
                disabled={payLoading}
              >
                {payLoading ? (
                  <>
                    <span className="spinner spinner-sm" />{' '}
                    Redirecting to Stripe…
                  </>
                ) : (
                  <>
                    Pay $
                    {planPrice/100}/mo with Stripe{' '}
                    <ArrowRight size={16} />
                  </>
                )}
              </button>

              <button
                className="btn btn-ghost btn-full"
                onClick={handlePayLater}
              >
                Skip for now — continue with Free
                plan
              </button>
            </div>

            <p
              style={{
                textAlign: 'center',
                fontSize: '.72rem',
                color: 'var(--text-3)',
                marginTop: 12,
              }}
            >
              🔒 Secured by Stripe · Cancel anytime
            </p>
          </div>
        </div>
      )}
    </>
  )
}
