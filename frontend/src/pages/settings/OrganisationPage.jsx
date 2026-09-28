import React, { useEffect, useState } from 'react'
import toast from 'react-hot-toast'
import { Building2, Lock, Users, Tag, Plus, ShieldAlert } from 'lucide-react'
import * as api from '../../lib/platformApi.js'
import { currentOrgId } from '../../lib/authFetch.js'

const ROLES = ['owner', 'admin', 'accountant', 'bookkeeper', 'payroll', 'readonly']
const ROLE_HELP = {
  owner: 'Full control including members', admin: 'Full control including members', accountant: 'Post, settings, lock date, audit',
  bookkeeper: 'Post journals, view reports', payroll: 'View only (payroll rights arrive in Phase 2)', readonly: 'View only',
}
const ENTITY = ['', 'company', 'trust', 'partnership', 'sole_trader', 'smsf', 'other']
const MONTHS = ['January', 'February', 'March', 'April', 'May', 'June', 'July', 'August', 'September', 'October', 'November', 'December']

const METHOD_LABEL = { passkey: 'Face / fingerprint (passkey)', totp: 'Authenticator app', sms: 'Text message (SMS)', email: 'Email code', recovery: 'Recovery code' }

function AccessPolicyCard({ canManage }) {
  const [p, setP] = useState(null)
  const [ips, setIps] = useState('')
  const [busy, setBusy] = useState(false)
  const load = () => api.accessPolicy().then(r => { setP(r.data); setIps((r.data.ip_allowlist || []).join('\n')) }).catch(() => setP(null))
  useEffect(() => { load() }, [])
  if (!p) return null
  const set = (k, v) => setP({ ...p, [k]: v })
  const toggleMethod = m => {
    const cur = p.allowed_mfa_methods || []
    set('allowed_mfa_methods', cur.includes(m) ? cur.filter(x => x !== m) : [...cur, m])
  }
  const save = async () => {
    setBusy(true)
    try {
      const body = { state: p.state, applies_to: p.applies_to, require_mfa: !!p.require_mfa,
        allowed_mfa_methods: p.allowed_mfa_methods && p.allowed_mfa_methods.length ? p.allowed_mfa_methods : null,
        ip_allowlist: ips.split(/[\s,]+/).filter(Boolean), max_session_hours: p.max_session_hours ? Number(p.max_session_hours) : null }
      await api.saveAccessPolicy(body); toast.success('Access policy saved'); load()
    } catch (e) { toast.error(api.errMsg(e)) } finally { setBusy(false) }
  }
  return (
    <div className="card">
      <h3 style={{ marginTop: 0 }}><ShieldAlert size={16} /> Access policy (Conditional Access)</h3>
      <p className="text-sm text-muted">Rules every member must meet to use this organisation. Start with <b>Report only</b> to see who would be
        affected (Security → audit log shows "ca.report_only"), then turn it <b>On</b>. You can't save an enforced policy that would lock yourself out.</p>
      <div className="grid-2" style={{ gap: 12 }}>
        <div><label className="text-sm fw-600">Policy state</label>
          <select className="input" disabled={!canManage} value={p.state} onChange={e => set('state', e.target.value)} data-testid="ca-state">
            <option value="off">Off</option><option value="report">Report only (log, don't block)</option><option value="on">On (enforce)</option></select></div>
        <div><label className="text-sm fw-600">Applies to</label>
          <select className="input" disabled={!canManage} value={p.applies_to} onChange={e => set('applies_to', e.target.value)}>
            <option value="all">All members</option><option value="admins">Owners and admins only</option></select></div>
      </div>
      <label className="text-sm mt-4" style={{ display: 'block' }}>
        <input type="checkbox" disabled={!canManage} checked={!!p.require_mfa} onChange={e => set('require_mfa', e.target.checked)} /> Require two-step verification
      </label>
      {p.require_mfa && (
        <div className="mt-1" style={{ paddingLeft: 20 }}>
          <span className="text-sm">Accepted methods (none ticked = any):</span>
          <div className="flex gap-4" style={{ flexWrap: 'wrap', marginTop: 4 }}>
            {Object.entries(METHOD_LABEL).map(([k, l]) => (
              <label key={k} className="text-sm"><input type="checkbox" disabled={!canManage} checked={(p.allowed_mfa_methods || []).includes(k)} onChange={() => toggleMethod(k)} /> {l}</label>))}
          </div>
        </div>)}
      <div className="grid-2 mt-4" style={{ gap: 12 }}>
        <div><label className="text-sm fw-600">Allowed networks (one IP or range per line, blank = anywhere)</label>
          <textarea className="input" rows={3} disabled={!canManage} value={ips} onChange={e => setIps(e.target.value)} placeholder={'203.0.113.10\n198.51.100.0/24'} />
          <span className="text-xs text-muted">Your current address: <span className="mono">{p.your_ip}</span></span></div>
        <div><label className="text-sm fw-600">Require signing in again after (hours, blank = session default)</label>
          <input className="input" type="number" min={1} max={720} disabled={!canManage} value={p.max_session_hours || ''} onChange={e => set('max_session_hours', e.target.value)} /></div>
      </div>
      {canManage && <button className="btn btn-primary btn-sm mt-4" disabled={busy} onClick={save}>Save access policy</button>}
      {p.updated_at && <span className="text-xs text-muted" style={{ marginLeft: 10 }}>Last changed {new Date(p.updated_at).toLocaleString('en-AU')}</span>}
    </div>)
}

export default function OrganisationPage() {
  const [org, setOrg] = useState(null)
  const [orgs, setOrgs] = useState([])
  const [form, setForm] = useState({})
  const [lock, setLock] = useState('')
  const [mem, setMem] = useState([])
  const [invite, setInvite] = useState({ email: '', role: 'bookkeeper' })
  const [cats, setCats] = useState([])
  const [newCat, setNewCat] = useState('')
  const [newOpt, setNewOpt] = useState({})
  const [newOrg, setNewOrg] = useState('')

  const load = () => {
    api.currentOrg().then(r => { setOrg(r.data); setForm(r.data); setLock(r.data.lock_date || '') }).catch(e => toast.error(api.errMsg(e)))
    api.myOrgs().then(r => setOrgs(r.data)).catch(() => {})
    api.members().then(r => setMem(r.data)).catch(() => {})
    api.tracking().then(r => setCats(r.data)).catch(() => {})
  }
  useEffect(load, [])
  const canManage = org && ['owner', 'admin'].includes(org.role)
  const canSettings = org && ['owner', 'admin', 'accountant'].includes(org.role)

  const saveDetails = async () => {
    try {
      const { name, legal_name, abn, entity_type, gst_registered, gst_basis, fy_end_month } = form
      await api.updateOrg({ name, legal_name: legal_name || null, abn: abn || null, entity_type: entity_type || null,
        gst_registered, gst_basis, fy_end_month: Number(fy_end_month) })
      toast.success('Organisation updated'); load()
    } catch (e) { toast.error(api.errMsg(e)) }
  }
  const saveLock = async clear => {
    try { await api.setLockDate(clear ? null : lock || null); toast.success(clear ? 'Lock date removed' : 'Lock date saved'); load() }
    catch (e) { toast.error(api.errMsg(e)) }
  }
  const addMember = async () => {
    try { await api.addMember(invite); toast.success('Member added'); setInvite({ email: '', role: 'bookkeeper' }); load() }
    catch (e) { toast.error(api.errMsg(e)) }
  }
  const setRole = async (uid, role) => { try { await api.changeRole(uid, role); toast.success('Role updated'); load() } catch (e) { toast.error(api.errMsg(e)); load() } }
  const remove = async m => {
    if (!window.confirm(`Remove ${m.email} from this organisation?`)) return
    try { await api.removeMember(m.user_id); toast.success('Member removed'); load() } catch (e) { toast.error(api.errMsg(e)) }
  }
  const switchTo = id => {
    if (String(id) === String(org?.id)) return
    localStorage.setItem('af_org', String(id))
    toast.success('Switched organisation'); setTimeout(() => window.location.reload(), 300)
  }
  const create = async () => {
    try { const { data } = await api.createOrg({ name: newOrg }); setNewOrg(''); toast.success('Organisation created'); switchTo(data.id) }
    catch (e) { toast.error(api.errMsg(e)) }
  }
  const addCat = async () => { try { await api.addTracking(newCat); setNewCat(''); load() } catch (e) { toast.error(api.errMsg(e)) } }
  const addOpt = async id => { try { await api.addTrackingOpt(id, newOpt[id] || ''); setNewOpt({ ...newOpt, [id]: '' }); load() } catch (e) { toast.error(api.errMsg(e)) } }

  if (!org) return <div><div className="spinner" /></div>
  return (
    <div style={{ display: 'grid', gap: 16 }}>
      <div className="flex items-center gap-1"><Building2 size={22} /><h2 style={{ margin: 0 }}>Organisation</h2>
        <span className="badge badge-brand" style={{ marginLeft: 8 }}>Your role: {org.role}</span></div>

      {orgs.length > 0 && (
        <div className="card card-sm">
          <div className="flex items-center gap-4" style={{ flexWrap: 'wrap' }}>
            <b>Working in:</b>
            <select className="input input-sm" style={{ maxWidth: 320 }} value={currentOrgId() || org.id} onChange={e => switchTo(e.target.value)}>
              {orgs.map(o => <option key={o.id} value={o.id}>{o.name} ({o.role})</option>)}
            </select>
            <div className="flex-1" />
            <input className="input input-sm" style={{ maxWidth: 240 }} placeholder="New organisation name" value={newOrg} onChange={e => setNewOrg(e.target.value)} />
            <button className="btn btn-outline btn-sm" disabled={!newOrg.trim()} onClick={create}><Plus size={13} /> Create</button>
          </div>
          <p className="text-xs text-muted mt-1">Your existing reconciliation, invoice and payroll data stays in your default organisation. Each organisation has its own ledger.</p>
        </div>)}

      <div className="card">
        <h3 style={{ marginTop: 0 }}>Details</h3>
        <div className="grid-2" style={{ gap: 12 }}>
          <div><label className="text-sm fw-600">Display name</label><input className="input" disabled={!canSettings} value={form.name || ''} onChange={e => setForm({ ...form, name: e.target.value })} /></div>
          <div><label className="text-sm fw-600">Legal name</label><input className="input" disabled={!canSettings} value={form.legal_name || ''} onChange={e => setForm({ ...form, legal_name: e.target.value })} /></div>
          <div><label className="text-sm fw-600">ABN</label><input className="input" disabled={!canSettings} value={form.abn || ''} placeholder="11 digits" onChange={e => setForm({ ...form, abn: e.target.value })} data-testid="org-abn" /></div>
          <div><label className="text-sm fw-600">Entity type</label>
            <select className="input" disabled={!canSettings} value={form.entity_type || ''} onChange={e => setForm({ ...form, entity_type: e.target.value })}>
              {ENTITY.map(x => <option key={x} value={x}>{x ? x.replace('_', ' ') : '— select —'}</option>)}</select></div>
          <div><label className="text-sm fw-600">GST registered</label>
            <select className="input" disabled={!canSettings} value={form.gst_registered ? 'yes' : 'no'} onChange={e => setForm({ ...form, gst_registered: e.target.value === 'yes' })}>
              <option value="yes">Yes</option><option value="no">No</option></select></div>
          <div><label className="text-sm fw-600">GST accounting basis</label>
            <select className="input" disabled={!canSettings} value={form.gst_basis || 'accrual'} onChange={e => setForm({ ...form, gst_basis: e.target.value })}>
              <option value="accrual">Accrual</option><option value="cash">Cash</option></select></div>
          <div><label className="text-sm fw-600">Financial year ends</label>
            <select className="input" disabled={!canSettings} value={form.fy_end_month || 6} onChange={e => setForm({ ...form, fy_end_month: e.target.value })}>
              {MONTHS.map((mn, i) => <option key={mn} value={i + 1}>{mn}</option>)}</select></div>
        </div>
        {canSettings && <button className="btn btn-primary btn-sm mt-4" onClick={saveDetails}>Save details</button>}
      </div>

      <div className="card">
        <h3 style={{ marginTop: 0 }}><Lock size={16} /> Lock date</h3>
        <p className="text-sm text-muted">No journal can be posted, reversed or re-synced on or before this date - use it once a period is reported (for example after a BAS is lodged).</p>
        <div className="flex items-center gap-1">
          <input type="date" className="input input-sm" style={{ maxWidth: 200 }} disabled={!canSettings} value={lock} onChange={e => setLock(e.target.value)} data-testid="lock-date" />
          {canSettings && <button className="btn btn-primary btn-sm" onClick={() => saveLock(false)}>Save lock date</button>}
          {canSettings && org.lock_date && <button className="btn btn-ghost btn-sm" onClick={() => saveLock(true)}>Remove lock</button>}
        </div>
      </div>

      <div className="card">
        <h3 style={{ marginTop: 0 }}><Users size={16} /> Members</h3>
        <div className="data-table-wrap"><table className="data-table">
          <thead><tr><th>User</th><th>Email</th><th>Role</th><th></th></tr></thead>
          <tbody>{mem.map(m => (
            <tr key={m.user_id}><td>{m.name || m.username}</td><td>{m.email}</td>
              <td>{canManage ? <select className="input input-sm" value={m.role} onChange={e => setRole(m.user_id, e.target.value)}>
                {ROLES.map(r => <option key={r} value={r}>{r}</option>)}</select> : <span className="badge badge-neutral">{m.role}</span>}</td>
              <td className="text-right">{canManage && <button className="btn btn-ghost btn-xs" onClick={() => remove(m)}>Remove</button>}</td></tr>))}
          </tbody></table></div>
        {canManage && (
          <div className="flex items-center gap-1 mt-4" style={{ flexWrap: 'wrap' }}>
            <input className="input input-sm" style={{ maxWidth: 260 }} placeholder="Email of an existing AccFino user" value={invite.email} onChange={e => setInvite({ ...invite, email: e.target.value })} />
            <select className="input input-sm" style={{ maxWidth: 160 }} value={invite.role} onChange={e => setInvite({ ...invite, role: e.target.value })}>
              {ROLES.map(r => <option key={r} value={r}>{r}</option>)}</select>
            <button className="btn btn-primary btn-sm" disabled={!invite.email} onClick={addMember}>Add member</button>
            <span className="text-xs text-muted">{ROLE_HELP[invite.role]}</span>
          </div>)}
      </div>

      {canSettings && <AccessPolicyCard canManage={canManage} />}

      <div className="card">
        <h3 style={{ marginTop: 0 }}><Tag size={16} /> Tracking categories</h3>
        <p className="text-sm text-muted">Tag journal lines by department, location or project (up to two active categories).</p>
        {cats.map(c => (
          <div key={c.id} style={{ marginBottom: 10 }}>
            <b>{c.name}</b>: {c.options.map(o => <span key={o.id} className="chip" style={{ marginRight: 4 }}>{o.name}</span>)}
            {canSettings && <span className="flex items-center gap-1" style={{ display: 'inline-flex', marginLeft: 8 }}>
              <input className="input input-sm" style={{ width: 160 }} placeholder="New option" value={newOpt[c.id] || ''} onChange={e => setNewOpt({ ...newOpt, [c.id]: e.target.value })} />
              <button className="btn btn-ghost btn-xs" disabled={!newOpt[c.id]} onClick={() => addOpt(c.id)}>Add</button></span>}
          </div>))}
        {canSettings && <div className="flex items-center gap-1"><input className="input input-sm" style={{ maxWidth: 220 }} placeholder="Category name, e.g. Department" value={newCat} onChange={e => setNewCat(e.target.value)} />
          <button className="btn btn-outline btn-sm" disabled={!newCat} onClick={addCat}>Add category</button></div>}
      </div>
    </div>
  )
}
