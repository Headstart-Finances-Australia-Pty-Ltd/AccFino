import React, { useEffect, useState } from 'react'
import toast from 'react-hot-toast'
import * as api from '../../lib/booksApi.js'
import { fmtDate } from '../books/Common.jsx'

// Organisation User roles only: an access code can never create an Organisation Admin (each organisation has exactly one).
const ROLES = [['bookkeeper', 'Bookkeeper'], ['accountant', 'Accountant'], ['payroll', 'Payroll'], ['readonly', 'Read-only']]
const STATUS = { unused: ['Unused', 'badge-success'], partly_used: ['Partly used', 'badge-success'], used: ['Used', 'badge-neutral'], expired: ['Expired', 'badge-neutral'], revoked: ['Revoked', 'badge-danger'] }

/** Settings > Organisation > Users and access codes: the Organisation Admin dashboard (organisation, primary contact, licence usage, code counts), generate / revoke access codes,
 *  and the organisation's web address. Organisation Admin only (the server refuses everyone else; this renders nothing for them). */
export default function InviteManager() {
  const [data, setData] = useState(null)
  const [tenant, setTenant] = useState(null)
  const [denied, setDenied] = useState(false)
  const [form, setForm] = useState({ role: 'bookkeeper', count: 1, expires_in_days: 7, max_uses: 1, label: '' })
  const [fresh, setFresh] = useState(null)           // the newly generated codes - the ONLY time the full code can be seen
  const [busy, setBusy] = useState(false)

  const load = () => Promise.all([api.listInvites(), api.getTenantProfile()])
    .then(([i, t]) => { setData(i.data); setTenant(t.data) })
    .catch(e => { if (e?.response?.status === 403) setDenied(true); else toast.error(api.errMsg(e)) })
  useEffect(() => { load() }, [])
  if (denied || !data) return null

  const s = data.summary
  const ov = data.overview
  const generate = async () => {
    setBusy(true)
    try {
      const { data: r } = await api.createInvites({ ...form, count: Number(form.count), expires_in_days: Number(form.expires_in_days), max_uses: Number(form.max_uses), label: form.label || null })
      setFresh(r); load()
    } catch (e) { toast.error(api.errMsg(e)) } finally { setBusy(false) }
  }
  const revoke = async i => {
    if (!window.confirm(`Revoke access code ${i.code_hint}? It will stop working immediately.`)) return
    try { await api.revokeInvite(i.id); toast.success('Access code revoked'); load() } catch (e) { toast.error(api.errMsg(e)) }
  }
  const copyAll = () => { navigator.clipboard?.writeText(fresh.codes.map(c => c.code).join('\n')); toast.success('Codes copied') }
  const Tile = ({ label, value, warn }) => <div style={{ border: '1px solid var(--border)', borderRadius: 8, padding: '8px 14px', minWidth: 120 }}><div className="text-xs text-muted">{label}</div><b style={{ fontSize: '1.2rem', color: warn ? 'var(--danger)' : undefined }}>{value ?? '∞'}</b></div>
  const toggleDiscover = async () => { try { const { data: t } = await api.patchTenantProfile({ discoverable: !tenant.discoverable }); setTenant(t) } catch (e) { toast.error(api.errMsg(e)) } }

  return (
    <div className="card" style={{ padding: 16, marginBottom: 16 }} data-testid="invite-manager">
      <h3 style={{ marginTop: 0 }}>Users and access codes</h3>
      {ov && (
        <div data-testid="admin-overview" style={{ border: '1px solid var(--border)', borderRadius: 8, padding: 12, marginBottom: 12 }}>
          <div className="text-xs text-muted" style={{ marginBottom: 4 }}>ORGANISATION</div>
          <div className="grid-2" style={{ gap: 6 }}>
            <div className="text-sm">Organisation name: <b>{ov.organisation.name}</b></div>
            <div className="text-sm">Organisation ID: <b>{ov.organisation.id}</b></div>
            <div className="text-sm">Admin name: <b>{ov.organisation.admin_name}</b></div>
            <div className="text-sm">Admin email: <b>{ov.organisation.admin_email}</b></div>
            <div className="text-sm">Admin phone: <b>{ov.organisation.admin_phone_display || ov.organisation.admin_phone}</b></div>
          </div>
          <div className="text-xs text-muted" style={{ marginTop: 4 }}>The Organisation Admin's email and phone are this organisation's primary contact details. Change them under My Account.</div>
        </div>)}
      <div className="flex gap-4" style={{ flexWrap: 'wrap', marginBottom: 12 }}>
        <Tile label="Licensed users" value={s.licensed_users} /><Tile label="Active users" value={s.active_users} /><Tile label="Pending invitations" value={s.pending_invitations} />
        <Tile label="Available slots" value={s.available_slots} warn={s.available_slots === 0} />
      </div>
      <div className="text-sm" style={{ marginBottom: 6 }}>Organisation address: <b>{tenant?.tenant_url || `(web address ${tenant?.slug}; organisation addresses are not switched on for this installation)`}</b></div>
      <label className="text-xs text-muted" style={{ cursor: 'pointer', display: 'block', marginBottom: 12 }}>
        <input type="checkbox" checked={!!tenant?.discoverable} onChange={toggleDiscover} /> Show this organisation when people search to join (turn off to make it findable only by its exact web address)
      </label>

      <div style={{ border: '1px solid var(--border)', borderRadius: 8, padding: 12, marginBottom: 12 }}>
        <b className="text-sm">Generate access codes</b>
        <div className="flex gap-4 mt-1" style={{ flexWrap: 'wrap', alignItems: 'flex-end' }}>
          <label className="text-xs">Role<br /><select className="input input-sm" aria-label="Role" value={form.role} onChange={e => setForm({ ...form, role: e.target.value })}>{ROLES.map(([v, l]) => <option key={v} value={v}>{l}</option>)}</select></label>
          <label className="text-xs">How many<br /><input className="input input-sm" style={{ width: 70 }} type="number" min="1" max="50" aria-label="How many" value={form.count} onChange={e => setForm({ ...form, count: e.target.value })} /></label>
          <label className="text-xs">Valid for (days)<br /><input className="input input-sm" style={{ width: 80 }} type="number" min="1" max="90" aria-label="Valid for days" value={form.expires_in_days} onChange={e => setForm({ ...form, expires_in_days: e.target.value })} /></label>
          <label className="text-xs">Uses per code<br /><input className="input input-sm" style={{ width: 70 }} type="number" min="1" max="50" aria-label="Uses per code" value={form.max_uses} onChange={e => setForm({ ...form, max_uses: e.target.value })} /></label>
          <label className="text-xs">Note (e.g. who it is for)<br /><input className="input input-sm" aria-label="Note" value={form.label} onChange={e => setForm({ ...form, label: e.target.value })} /></label>
          <button className="btn btn-primary btn-sm" disabled={busy || s.available_slots === 0} onClick={generate}>{busy ? 'Generating…' : 'Generate'}</button>
        </div>
        {s.available_slots === 0 && <div className="text-xs" style={{ color: 'var(--danger)', marginTop: 6 }}>No licensed slots left. Revoke unused codes or upgrade the plan to invite more people.</div>}
      </div>

      {fresh && (
        <div className="alert alert-success" data-testid="fresh-codes" style={{ marginBottom: 12 }}>
          <b>Copy these now.</b> {fresh.note}
          <div className="mono" style={{ margin: '8px 0', fontSize: '1rem' }}>{fresh.codes.map(c => <div key={c.id}>{c.code} <span className="text-xs text-muted">· {c.role} · expires {fmtDate(c.expires_at)}</span></div>)}</div>
          {fresh.tenant_url && <div className="text-xs">Give people this address too: {fresh.tenant_url}</div>}
          <button className="btn btn-outline btn-xs" onClick={copyAll}>Copy all</button> <button className="btn btn-ghost btn-xs" onClick={() => setFresh(null)}>I have copied them</button>
        </div>)}

      <div className="text-xs text-muted" style={{ marginBottom: 6 }} data-testid="code-counts">Access codes: {s.codes.unused + s.codes.partly_used} active · {s.codes.used} used · {s.codes.expired} expired · {s.codes.revoked} revoked</div>
      {data.items.length === 0 ? <div className="text-sm text-muted">No access codes yet.</div> : (
        <table className="data-table" style={{ fontSize: '.8rem' }}>
          <thead><tr><th>Code</th><th>Role</th><th>Note</th><th>Status</th><th>Uses</th><th>Expires</th><th /></tr></thead>
          <tbody>{data.items.map(i => (
            <tr key={i.id}><td className="mono">{i.code_hint}</td><td>{i.role}</td><td>{i.label || ''}</td>
              <td><span className={`badge ${STATUS[i.status][1]}`}>{STATUS[i.status][0]}</span></td><td>{i.uses}/{i.max_uses}</td><td>{fmtDate(i.expires_at)}</td>
              <td>{(i.status === 'unused' || i.status === 'partly_used') && <button className="btn btn-ghost btn-xs" onClick={() => revoke(i)}>Revoke</button>}</td></tr>))}</tbody>
        </table>)}
    </div>
  )
}
