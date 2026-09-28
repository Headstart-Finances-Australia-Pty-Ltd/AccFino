import React, { useEffect, useState } from 'react'
import { bankAccountStatus, bankAccountSaveConfig } from '../../lib/api.js'
import { Landmark } from 'lucide-react'
import toast from 'react-hot-toast'

// The org's own bank account — where OUTGOING money is paid FROM: invoice
// payments the org makes to others, and refunds. Distinct from Settings >
// Open Banking (which reads transactions IN) and from Square/Stripe (which
// collect card payments IN). Same file-backed config convention as those.
export default function BankAccountPanel() {
  const [status, setStatus] = useState(null)
  const [form, setForm] = useState({ account_name:'', bank_name:'', bsb:'', account_number:'' })
  const [saving, setSaving] = useState(false)

  const load = () => bankAccountStatus().then(r => {
    setStatus(r.data)
    setForm(f => ({ ...f, account_name: r.data.account_name || '', bank_name: r.data.bank_name || '' }))
  }).catch(() => setStatus({ available:false, configured:false }))
  useEffect(() => { load() }, [])

  const save = async () => {
    setSaving(true)
    try { await bankAccountSaveConfig(form); toast.success('Bank account saved'); load() }
    catch (e) { toast.error(e.response?.data?.detail || 'Failed to save') }
    finally { setSaving(false) }
  }

  return (
    <div style={{maxWidth:560}}>
      <div className={`alert ${status?.configured?'alert-success':'alert-warning'}`} style={{marginBottom:20}}>
        {status?.configured
          ? `✅ Bank account on file (••••${status.account_number_last4}).`
          : '⚠️ No bank account set up yet.'}
      </div>
      <div className="card">
        <h3 style={{marginBottom:12}}>
          <Landmark size={16} style={{display:'inline',marginRight:6,verticalAlign:'middle'}}/>Bank account for outgoing payments
        </h3>
        <p style={{fontSize:'.8rem',color:'var(--text-2)',marginBottom:14}}>
          The account outgoing money is paid from — invoice payments you make and refunds you issue.
          This is separate from the accounts you connect under Open Banking to read transactions in.
        </p>
        <div className="input-group" style={{marginBottom:10}}>
          <label>Account Name</label>
          <input className="input" value={form.account_name} onChange={e=>setForm(f=>({...f,account_name:e.target.value}))} placeholder="e.g. AccFino Pty Ltd" />
        </div>
        <div className="input-group" style={{marginBottom:10}}>
          <label>Bank Name</label>
          <input className="input" value={form.bank_name} onChange={e=>setForm(f=>({...f,bank_name:e.target.value}))} placeholder="e.g. Commonwealth Bank" />
        </div>
        <div className="input-group" style={{marginBottom:10}}>
          <label>BSB</label>
          <input className="input" value={form.bsb} onChange={e=>setForm(f=>({...f,bsb:e.target.value}))} placeholder="xxx-xxx" />
        </div>
        <div className="input-group" style={{marginBottom:16}}>
          <label>Account Number</label>
          <input className="input" type="password" value={form.account_number} onChange={e=>setForm(f=>({...f,account_number:e.target.value}))} />
        </div>
        <button className="btn btn-primary btn-full" onClick={save} disabled={saving}>
          {saving ? <span className="spinner spinner-sm"/> : 'Save bank account'}
        </button>
      </div>
    </div>
  )
}
