import React, { useEffect, useState } from 'react'
import { squareStatus, squareSaveConfig } from '../lib/api.js'
import { CreditCard } from 'lucide-react'
import toast from 'react-hot-toast'

// Square credentials panel. Lives in Settings > Payment Setup (moved here
// from Settings > Open Banking — Square is a card-payment/API integration,
// not a bank feed), and is also reused on Admin > Payment Card Setup so
// AccFino can accept Square for orgs' platform subscription/licence fee.
// Each surface has its own module id in Admin > Modules Management
// (square-open-banking for Settings, square-admin-payments for Admin), and
// both use the same /square/status + /square/config endpoints, so nothing
// on the backend needed to change.
export default function SquarePanel() {
  const [status, setStatus] = useState(null)
  const [form, setForm] = useState({ application_id:'', access_token:'', location_id:'', environment:'sandbox' })
  const [saving, setSaving] = useState(false)

  const load = () => squareStatus().then(r=>setStatus(r.data)).catch(()=>setStatus({available:false,configured:false}))
  useEffect(() => { load() }, [])

  const save = async () => {
    setSaving(true)
    try { await squareSaveConfig(form); toast.success('Square configuration saved'); load() }
    catch (e) { toast.error(e.response?.data?.detail || 'Failed to save') }
    finally { setSaving(false) }
  }

  return (
    <div style={{maxWidth:560}}>
      <div className={`alert ${status?.configured?'alert-success':'alert-warning'}`} style={{marginBottom:20}}>
        {status?.configured ? `✅ Square connected (${status.environment}).` : '⚠️ Square not configured yet.'}
      </div>
      <div className="card">
        <h3 style={{marginBottom:12}}><CreditCard size={16} style={{display:'inline',marginRight:6,verticalAlign:'middle'}}/>Square credentials</h3>
        <p style={{fontSize:'.8rem',color:'var(--text-2)',marginBottom:14}}>Connect a Square account to pull transactions and accept payments alongside your bank feeds.</p>
        {[['application_id','Application ID'],['access_token','Access Token'],['location_id','Location ID']].map(([k,label])=>(
          <div key={k} className="input-group" style={{marginBottom:10}}>
            <label>{label}</label>
            <input className="input" value={form[k]} onChange={e=>setForm(f=>({...f,[k]:e.target.value}))} type={k==='access_token'?'password':'text'} />
          </div>
        ))}
        <div className="input-group" style={{marginBottom:14}}>
          <label>Environment</label>
          <select className="input" value={form.environment} onChange={e=>setForm(f=>({...f,environment:e.target.value}))}>
            <option value="sandbox">Sandbox</option>
            <option value="production">Production</option>
          </select>
        </div>
        <button className="btn btn-primary btn-full" onClick={save} disabled={saving}>{saving?<span className="spinner spinner-sm"/>:'Save Square configuration'}</button>
      </div>
    </div>
  )
}
