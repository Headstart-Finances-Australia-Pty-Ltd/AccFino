import React, { useEffect, useState } from 'react'
import { stripeStatus, stripeSaveConfig } from '../../lib/api.js'
import { CreditCard } from 'lucide-react'
import toast from 'react-hot-toast'

// Stripe credentials panel. Settings > Payment Setup — sits alongside
// Square as the two card-payment gateway options an org can use to collect
// card payments from its own customers (e.g. on invoices). Also reused on
// Admin > Payment Card Setup, which is AccFino's own gateway for charging
// orgs their platform subscription fee — each surface has its own module id
// (stripe-payments for Settings, stripe-admin-payments for Admin). Same
// file-backed config convention as Square (see /stripe/status +
// /stripe/config).
export default function StripePanel() {
  const [status, setStatus] = useState(null)
  const [form, setForm] = useState({ publishable_key:'', secret_key:'', webhook_secret:'', environment:'sandbox' })
  const [saving, setSaving] = useState(false)

  const load = () => stripeStatus().then(r => {
    setStatus(r.data)
    setForm(f => ({ ...f, environment: r.data.environment || 'sandbox', publishable_key: r.data.publishable_key || '' }))
  }).catch(() => setStatus({ available:false, configured:false }))
  useEffect(() => { load() }, [])

  const save = async () => {
    setSaving(true)
    try { await stripeSaveConfig(form); toast.success('Stripe configuration saved'); load() }
    catch (e) { toast.error(e.response?.data?.detail || 'Failed to save') }
    finally { setSaving(false) }
  }

  return (
    <div style={{maxWidth:560}}>
      <div className={`alert ${status?.configured?'alert-success':'alert-warning'}`} style={{marginBottom:20}}>
        {status?.configured ? `✅ Stripe configured (${status.environment}).` : '⚠️ Stripe not configured yet.'}
      </div>
      <div className="card">
        <h3 style={{marginBottom:12}}>
          <CreditCard size={16} style={{display:'inline',marginRight:6,verticalAlign:'middle'}}/>Stripe credentials
        </h3>
        <p style={{fontSize:'.8rem',color:'var(--text-2)',marginBottom:14}}>
          Used to collect card payments from your own customers (e.g. on invoices), alongside Square.
        </p>
        <div className="input-group" style={{marginBottom:10}}>
          <label>Publishable Key</label>
          <input className="input" value={form.publishable_key} onChange={e=>setForm(f=>({...f,publishable_key:e.target.value}))} placeholder="pk_live_..." />
        </div>
        <div className="input-group" style={{marginBottom:10}}>
          <label>Secret Key</label>
          <input className="input" type="password" value={form.secret_key} onChange={e=>setForm(f=>({...f,secret_key:e.target.value}))} placeholder="sk_live_..." />
        </div>
        <div className="input-group" style={{marginBottom:10}}>
          <label>Webhook Signing Secret</label>
          <input className="input" type="password" value={form.webhook_secret} onChange={e=>setForm(f=>({...f,webhook_secret:e.target.value}))} placeholder="whsec_..." />
        </div>
        <div className="input-group" style={{marginBottom:16}}>
          <label>Environment</label>
          <select className="input" value={form.environment} onChange={e=>setForm(f=>({...f,environment:e.target.value}))}>
            <option value="sandbox">Sandbox (Test mode)</option>
            <option value="production">Production (Live mode)</option>
          </select>
        </div>
        <button className="btn btn-primary btn-full" onClick={save} disabled={saving}>
          {saving ? <span className="spinner spinner-sm"/> : 'Save Stripe configuration'}
        </button>
      </div>
    </div>
  )
}
