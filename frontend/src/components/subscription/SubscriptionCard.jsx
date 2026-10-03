import React, { useEffect, useState } from 'react'
import toast from 'react-hot-toast'
import * as api from '../../lib/booksApi.js'
import { fmtAUD, fmtDate } from '../books/Common.jsx'
import BillingCard from '../billing/BillingCard.jsx'

const STATUS_LABEL = { trial: 'Trial', active: 'Active', past_due: 'Payment overdue', cancelled: 'Cancelled', expired: 'Expired (read-only)' }

/** Settings > Business Setup > Organisation > Subscription: this organisation's plan, seats, included / locked modules, and a way to ask for more. */
// "All business domains" / "Books and Accounting, Payroll & Workforce + 2 modules" / "6 modules"
export function planSummary(p, domains, features = []) {
  if (p.modules.includes('*')) return 'all business domains'
  const names = (domains || []).filter(d => p.modules.includes(`domain:${d.id}`)).map(d => d.name)
  const fnIds = new Set((features || []).map(f => f.id))
  const single = p.modules.filter(x => !x.startsWith('domain:') && !fnIds.has(x)).length
  if (!names.length) return `${single} modules`
  return `${names.join(', ')}${single ? ` + ${single} module${single === 1 ? '' : 's'}` : ''}`
}

export default function SubscriptionCard() {
  const [sub, setSub] = useState(null)
  const [busy, setBusy] = useState(false)
  const load = () => api.getSubscription().then(r => setSub(r.data)).catch(e => toast.error(api.errMsg(e)))
  useEffect(() => { load() }, [])
  if (!sub) return null

  const request = async (body, what) => {
    setBusy(true)
    try { const { data } = await api.requestSubscription({ ...body, message: `Request: ${what}` }); toast.success(data.message) }
    catch (e) { toast.error(api.errMsg(e)) } finally { setBusy(false) }
  }
  const name = id => sub.catalogue.find(c => c.id === id)?.name || id
  const seats = sub.seats == null ? 'unlimited' : sub.seats
  const full = sub.seats != null && sub.seats_used >= sub.seats
  const ownedAddons = new Set(sub.addons.map(a => a.id))
  // modules grouped by business domain (an older server without domains shows one flat list)
  const groups = [...(sub.domains?.length ? sub.domains : [{ id: null, name: '', modules: sub.catalogue.filter(c => !(sub.features || []).some(f => f.id === c.id)).map(c => c.id) }]),
    ...((sub.features || []).length ? [{ id: 'functions', name: 'Functions', modules: sub.features.map(f => f.id) }] : [])]

  return (
    <div className="card" style={{ padding: 16, marginBottom: 16 }} data-testid="subscription-card">
      <h3 style={{ marginTop: 0 }}>Subscription</h3>
      {!sub.enforced && <div className="alert alert-info text-sm" style={{ marginBottom: 10 }}>Plan limits are not being enforced yet, so every module is available. The plan below shows what will apply once enforcement is switched on.</div>}
      {sub.read_only && <div className="alert alert-error text-sm" style={{ marginBottom: 10 }}>This subscription has expired, so the organisation is read-only: you can view and export everything, but not post or edit. Ask your platform administrator to renew it.</div>}
      <div className="flex items-center gap-4" style={{ flexWrap: 'wrap', marginBottom: 12 }}>
        <div><div className="text-xs text-muted">Plan</div><b style={{ fontSize: '1.05rem' }}>{sub.plan_name}</b></div>
        <div><div className="text-xs text-muted">Status</div><span className={`badge ${sub.read_only ? 'badge-danger' : 'badge-success'}`}>{STATUS_LABEL[sub.status] || sub.status}</span></div>
        <div><div className="text-xs text-muted">Users</div><b style={{ color: full ? 'var(--danger)' : undefined }}>{sub.seats_used} of {seats}</b></div>
        {sub.period_end && <div><div className="text-xs text-muted">Paid until</div>{fmtDate(sub.period_end)}</div>}
        {sub.trial_ends && sub.status === 'trial' && <div><div className="text-xs text-muted">Trial ends</div>{fmtDate(sub.trial_ends)}</div>}
        {sub.addons.length > 0 && <div><div className="text-xs text-muted">Add-ons</div>{sub.addons.map(a => a.name).join(', ')}</div>}
      </div>

      <table className="data-table" style={{ fontSize: '.82rem', marginBottom: 12 }}>
        <thead><tr><th>Module</th><th>Included</th>{sub.can_manage && <th />}</tr></thead>
        <tbody>{groups.map(g => {
          const rows = g.modules.map(id => sub.catalogue.find(c => c.id === id)).filter(Boolean)
          const incCount = rows.filter(c => sub.modules.includes(c.id) && !sub.locked.includes(c.id)).length
          const domAddon = g.id ? (sub.addon_catalogue || []).find(a => a.modules.includes(`domain:${g.id}`) && !ownedAddons.has(a.id)) : null
          return (
            <React.Fragment key={g.id || 'all'}>
              {g.id && <tr data-testid={`sub-domain-${g.id}`} style={{ background: 'var(--surface-2, #f3f6fa)' }}>
                <td><b>{g.name}</b></td>
                <td className="text-xs text-muted">{incCount} of {rows.length} included</td>
                {sub.can_manage && <td style={{ textAlign: 'right' }}>{incCount < rows.length && domAddon && <button className="btn btn-outline btn-xs" disabled={busy} onClick={() => request({ addon_ids: [domAddon.id] }, `add ${domAddon.name}`)}>Request {domAddon.name} ({fmtAUD(domAddon.price_monthly)}/mo)</button>}</td>}
              </tr>}
              {rows.map(c => {
                const inc = sub.modules.includes(c.id) && !sub.locked.includes(c.id)
                const addon = (sub.addon_catalogue || []).find(a => a.modules.includes(c.id) && !ownedAddons.has(a.id))
                return (
                  <tr key={c.id} data-testid={`sub-module-${c.id}`}>
                    <td style={g.id ? { paddingLeft: 22 } : undefined}>{c.name}</td>
                    <td>{inc ? <span className="badge badge-success">Included</span> : <span className="badge badge-neutral">🔒 Not in your plan</span>}</td>
                    {sub.can_manage && <td style={{ textAlign: 'right' }}>{!inc && addon && <button className="btn btn-outline btn-xs" disabled={busy} onClick={() => request({ addon_ids: [addon.id] }, `add ${addon.name}`)}>Request {addon.name} ({fmtAUD(addon.price_monthly)}/mo)</button>}</td>}
                  </tr>)
              })}
            </React.Fragment>)
        })}</tbody>
      </table>

      <div className="text-sm fw-600" style={{ marginBottom: 6 }}>Plans</div>
      <div className="flex gap-4" style={{ flexWrap: 'wrap' }}>
        {sub.plans.map(p => (
          <div key={p.id} style={{ border: '1px solid var(--border)', borderRadius: 8, padding: 12, minWidth: 190, flex: '1 1 190px', background: p.id === sub.plan_id ? 'var(--surface-2, #f3f6fa)' : undefined }}>
            <b>{p.name}</b> {p.id === sub.plan_id && <span className="badge badge-success">Current</span>}
            <div className="text-sm">{fmtAUD(p.price_monthly)}/month · {fmtAUD(p.price_yearly)}/year</div>
            <div className="text-xs text-muted" style={{ margin: '4px 0' }}>{p.seat_limit == null ? 'Unlimited users' : `${p.seat_limit} ${p.seat_limit === 1 ? 'user' : 'users'}`} · {planSummary(p, sub.domains, sub.features)}</div>
            <div className="text-xs text-muted">{p.description}</div>
            {sub.can_manage && p.id !== sub.plan_id && <button className="btn btn-outline btn-xs mt-4" disabled={busy} onClick={() => request({ plan_id: p.id }, `change to ${p.name}`)}>Request {p.name}</button>}
          </div>))}
      </div>
      {!sub.can_manage && <div className="text-xs text-muted mt-4">Only an owner can request plan changes.</div>}
      <div data-testid="user-pack-note" style={{ marginTop: 14, padding: '10px 12px', border: '1px solid var(--border)', borderRadius: 8, background: 'var(--surface-2)' }}>
        <div className="text-sm fw-600">Need more users?</div>
        <div className="text-xs text-muted" style={{ margin: '2px 0 8px' }}>Every plan is for 1 user. More users come in a user pack arranged with the AccFino team to suit your organisation.</div>
        {sub.can_manage
          ? <div style={{ display: 'flex', gap: 8, alignItems: 'center', flexWrap: 'wrap' }}>
              <button className="btn btn-outline btn-xs" disabled={busy} onClick={() => request({}, 'a user pack for more users')} data-testid="ask-user-pack">Ask about a user pack</button>
              <a className="text-xs" href="mailto:contact@accfino.com?subject=User pack enquiry">or email contact@accfino.com</a>
            </div>
          : <div className="text-xs text-muted">Ask your Organisation Admin to arrange it with AccFino.</div>}
      </div>
      <BillingCard />
    </div>
  )
}
