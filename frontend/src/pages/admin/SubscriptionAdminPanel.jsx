import React, { useEffect, useState } from 'react'
import toast from 'react-hot-toast'
import * as api from '../../lib/booksApi.js'
import { useForceDeleteSwitch, useRowSelection, SelectAllCheckbox, RowCheckbox, ForceDeleteButton, reportBulkResult, announceDataChanged, DATA_CHANGED_EVENT } from '../../components/ui/ForceDelete.jsx'

const STATUSES = ['trial', 'active', 'past_due', 'cancelled', 'expired']
const box = { background: 'var(--surface)', border: '1px solid var(--border)', borderRadius: 'var(--r-lg)', padding: 16, marginBottom: 14 }
const changed = () => window.dispatchEvent(new Event('accfino:subscription-changed'))

/** Admin > Modules Management > Subscriptions: enforcement switch, plan + add-on catalogue, and each organisation's plan. */
export default function SubscriptionAdminPanel() {
  const [d, setD] = useState(null)
  const [plan, setPlan] = useState(null)       // plan being edited: {id, isNew, ...}
  const [addon, setAddon] = useState(null)
  const load = () => api.adminSubOverview().then(r => setD(r.data)).catch(e => toast.error(api.errMsg(e)))
  useEffect(() => { load() }, [])
  useEffect(() => { window.addEventListener(DATA_CHANGED_EVENT, load); return () => window.removeEventListener(DATA_CHANGED_EVENT, load) }, []) // eslint-disable-line
  // Organisation rows: select (header checkbox = all), Delete, and Force delete selected (needs the Force delete switch on)
  const forceOn = useForceDeleteSwitch()
  const [bulkBusy, setBulkBusy] = useState(false)
  const sel = useRowSelection((d?.organisations || []).map(o => o.org_id))
  if (!d) return <div style={box}>Loading subscriptions…</div>

  const act = async (fn, ok) => { try { await fn(); if (ok) toast.success(ok); await load(); changed() } catch (e) { toast.error(api.errMsg(e)) } }
  const deleteOrgs = async (orgs, force) => {
    const names = orgs.map(o => o.name).join(', ')
    const users = orgs.reduce((n, o) => n + (o.members || 0), 0)
    const msg = force
      ? `FORCE DELETE ${orgs.length} organisation${orgs.length === 1 ? '' : 's'}?\n\n${names}\n\nThis permanently deletes the organisation(s), ALL their accounting data (including posted journals) and every user who belongs only to them (${users} member${users === 1 ? '' : 's'}). It cannot be undone.`
      : `Delete organisation "${names}"?\n\nIts ${users} user${users === 1 ? '' : 's'} will be deleted too. This cannot be undone.`
    if (!window.confirm(msg)) return
    setBulkBusy(true)
    try {
      const { data } = await api.adminBulkDeleteOrgs(orgs.map(o => o.org_id), force)
      reportBulkResult(data, 'organisation')
      sel.clear()
      await load(); changed(); announceDataChanged()
    } catch (e) { toast.error(api.errMsg(e)) } finally { setBulkBusy(false) }
  }
  const selectedOrgs = d.organisations.filter(o => sel.selected.has(o.org_id))

  const domName = id => (d.domains || []).find(x => x.id === id)?.name || id
  const modLabel = id => (id === '*' ? 'Everything' : id.startsWith('domain:') ? `All of ${domName(id.slice(7))}` : d.catalogue.find(c => c.id === id)?.name || id)
  const toggle = (obj, setObj, id) => setObj({ ...obj, modules: obj.modules.includes(id) ? obj.modules.filter(x => x !== id) : [...obj.modules, id] })

  // Pick whole business domains ("domain:<id>") or single modules inside a domain. Ticking a whole domain replaces its single-module ticks.
  const toggleDomain = (obj, setObj, dom) => {
    const tok = `domain:${dom.id}`
    setObj({ ...obj, modules: obj.modules.includes(tok) ? obj.modules.filter(x => x !== tok) : [...obj.modules.filter(x => !dom.modules.includes(x)), tok] })
  }
  const ModulePicker = ({ obj, setObj, allowAll }) => (
    <div style={{ margin: '8px 0', display: 'grid', gap: 8 }}>
      {allowAll && <label className="text-sm"><input type="checkbox" checked={obj.modules.includes('*')} onChange={() => setObj({ ...obj, modules: obj.modules.includes('*') ? [] : ['*'] })} /> <b>Everything (all business domains, also future ones)</b></label>}
      {!obj.modules.includes('*') && (d.domains || []).map(dom => {
        const whole = obj.modules.includes(`domain:${dom.id}`)
        return (
          <div key={dom.id} style={{ border: '1px solid var(--border)', borderRadius: 6, padding: '6px 10px' }} data-testid={`pick-domain-${dom.id}`}>
            <label className="text-sm"><input type="checkbox" aria-label={`Whole domain ${dom.name}`} checked={whole} onChange={() => toggleDomain(obj, setObj, dom)} /> <b>{dom.name}</b> <span className="text-muted">(whole domain)</span></label>
            <div style={{ display: 'flex', flexWrap: 'wrap', gap: '4px 12px', marginTop: 4, paddingLeft: 22 }}>
              {dom.modules.map(id => <label key={id} className="text-xs"><input type="checkbox" checked={whole || obj.modules.includes(id)} disabled={whole} onChange={() => toggle(obj, setObj, id)} /> {d.catalogue.find(c => c.id === id)?.name || id}</label>)}
            </div>
          </div>)
      })}
      {!obj.modules.includes('*') && !(d.domains || []).length && <div style={{ display: 'flex', flexWrap: 'wrap', gap: 10 }}>{d.catalogue.map(c => <label key={c.id} className="text-sm"><input type="checkbox" checked={obj.modules.includes(c.id)} onChange={() => toggle(obj, setObj, c.id)} /> {c.name}</label>)}</div>}
    </div>
  )

  return (
    <div data-testid="subscription-admin">
      <div style={box}>
        <label style={{ display: 'flex', alignItems: 'center', gap: 10, cursor: 'pointer' }}>
          <input type="checkbox" aria-label="Enforce subscriptions" checked={d.settings.enforced} onChange={e => act(() => api.adminSubSettings({ enforced: e.target.checked }), e.target.checked ? 'Subscriptions are now enforced' : 'Subscriptions are no longer enforced')} />
          <b>Enforce subscriptions</b>
          <span className={`badge ${d.settings.enforced ? 'badge-success' : 'badge-neutral'}`}>{d.settings.enforced ? 'On' : 'Off'}</span>
        </label>
        <div className={`text-xs ${d.settings.enforced ? 'text-muted' : ''}`} style={{ marginTop: 6 }} data-testid="enforce-explainer">
          {d.settings.enforced
            ? 'On: each organisation sees only the business domains and modules its plan (and add-ons) include - in the menu, the tabs, the Home page and the dashboard. The server refuses the rest.'
            : <><b>Off: plans are not applied yet.</b> Every organisation sees every domain and module, whatever its plan. Tick the box above to hide what a plan does not include.</>}
        </div>
        <div className="text-xs text-muted" style={{ margin: '6px 0 10px 26px' }}>
          Off (default): every organisation can use every module, whatever plan it is on. On: each organisation sees and can use only what its plan and add-ons include; organisations with no plan assigned keep everything. Takes effect immediately.
        </div>
        <label className="text-sm" style={{ marginLeft: 26 }}>Default plan for new organisations{' '}
          <select className="input input-sm" aria-label="Default plan" value={d.settings.default_plan} onChange={e => act(() => api.adminSubSettings({ default_plan: e.target.value }), 'Default plan saved')}>
            {d.plans.filter(p => p.is_active).map(p => <option key={p.id} value={p.id}>{p.name}</option>)}
          </select>
        </label>
      </div>

      <div style={box}>
        <div className="flex items-center" style={{ marginBottom: 8 }}><b>Plans</b><div className="flex-1" />
          <button className="btn btn-outline btn-sm" onClick={() => setPlan({ isNew: true, id: '', name: '', description: '', price_monthly: '0', price_yearly: '0', seat_limit: '', modules: [], is_active: true, sort_order: d.plans.length + 1 })}>+ New plan</button></div>
        <table className="data-table" style={{ fontSize: '.82rem' }}>
          <thead><tr><th>Plan</th><th>Monthly</th><th>Yearly</th><th>Users</th><th>Modules</th><th>Orgs</th><th /></tr></thead>
          <tbody>{d.plans.map(p => (
            <tr key={p.id} style={{ opacity: p.is_active ? 1 : .55 }}>
              <td><b>{p.name}</b> <span className="text-muted">({p.id})</span></td><td>${p.price_monthly}</td><td>${p.price_yearly}</td><td>{p.seat_limit ?? 'Unlimited'}</td>
              <td className="text-xs">{p.modules.map(modLabel).join(', ')}</td><td>{d.organisations.filter(o => o.plan_id === p.id).length}</td>
              <td style={{ textAlign: 'right', whiteSpace: 'nowrap' }}><button className="btn btn-ghost btn-xs" onClick={() => setPlan({ ...p, seat_limit: p.seat_limit ?? '' })}>Edit</button>
                <button className="btn btn-ghost btn-xs" onClick={() => window.confirm(`Delete plan ${p.name}?`) && act(() => api.adminDeletePlan(p.id), 'Plan deleted')}>Delete</button></td>
            </tr>))}</tbody>
        </table>
        {plan && (
          <div style={{ border: '1px solid var(--border)', borderRadius: 8, padding: 12, marginTop: 10 }}>
            <div className="flex gap-4" style={{ flexWrap: 'wrap' }}>
              {plan.isNew && <label className="text-sm">Id<br /><input className="input input-sm" aria-label="Plan id" placeholder="e.g. gold" value={plan.id} onChange={e => setPlan({ ...plan, id: e.target.value.toLowerCase() })} /></label>}
              <label className="text-sm">Name<br /><input className="input input-sm" aria-label="Plan name" value={plan.name} onChange={e => setPlan({ ...plan, name: e.target.value })} /></label>
              <label className="text-sm">Monthly $<br /><input className="input input-sm" style={{ width: 90 }} value={plan.price_monthly} onChange={e => setPlan({ ...plan, price_monthly: e.target.value })} /></label>
              <label className="text-sm">Yearly $<br /><input className="input input-sm" style={{ width: 90 }} value={plan.price_yearly} onChange={e => setPlan({ ...plan, price_yearly: e.target.value })} /></label>
              <label className="text-sm">Users (blank = unlimited)<br /><input className="input input-sm" style={{ width: 90 }} value={plan.seat_limit} onChange={e => setPlan({ ...plan, seat_limit: e.target.value })} /></label>
              <label className="text-sm"><input type="checkbox" checked={plan.is_active} onChange={e => setPlan({ ...plan, is_active: e.target.checked })} /> Active</label>
            </div>
            <label className="text-sm">Description<br /><input className="input input-sm" style={{ width: '100%' }} value={plan.description || ''} onChange={e => setPlan({ ...plan, description: e.target.value })} /></label>
            <ModulePicker obj={plan} setObj={setPlan} allowAll />
            <button className="btn btn-primary btn-sm" onClick={() => act(async () => {
              await api.adminSavePlan(plan.id, { name: plan.name, description: plan.description, price_monthly: String(plan.price_monthly), price_yearly: String(plan.price_yearly),
                seat_limit: plan.seat_limit === '' ? null : Number(plan.seat_limit), modules: plan.modules, is_active: plan.is_active, sort_order: plan.sort_order }); setPlan(null)
            }, 'Plan saved')}>Save plan</button>{' '}
            <button className="btn btn-ghost btn-sm" onClick={() => setPlan(null)}>Cancel</button>
          </div>)}
      </div>

      <div style={box}>
        <div className="flex items-center" style={{ marginBottom: 8 }}><b>Add-ons</b><div className="flex-1" />
          <button className="btn btn-outline btn-sm" onClick={() => setAddon({ isNew: true, id: '', name: '', description: '', price_monthly: '0', modules: [], extra_seats: 0, is_active: true, sort_order: d.addons.length + 1 })}>+ New add-on</button></div>
        <table className="data-table" style={{ fontSize: '.82rem' }}>
          <thead><tr><th>Add-on</th><th>Monthly</th><th>Adds</th><th /></tr></thead>
          <tbody>{d.addons.map(a => (
            <tr key={a.id} style={{ opacity: a.is_active ? 1 : .55 }}>
              <td><b>{a.name}</b> <span className="text-muted">({a.id})</span></td><td>${a.price_monthly}</td>
              <td className="text-xs">{[...a.modules.map(modLabel), a.extra_seats ? `${a.extra_seats} users` : null].filter(Boolean).join(', ')}</td>
              <td style={{ textAlign: 'right', whiteSpace: 'nowrap' }}><button className="btn btn-ghost btn-xs" onClick={() => setAddon({ ...a })}>Edit</button>
                <button className="btn btn-ghost btn-xs" onClick={() => window.confirm(`Delete add-on ${a.name}?`) && act(() => api.adminDeleteAddon(a.id), 'Add-on deleted')}>Delete</button></td>
            </tr>))}</tbody>
        </table>
        {addon && (
          <div style={{ border: '1px solid var(--border)', borderRadius: 8, padding: 12, marginTop: 10 }}>
            <div className="flex gap-4" style={{ flexWrap: 'wrap' }}>
              {addon.isNew && <label className="text-sm">Id<br /><input className="input input-sm" aria-label="Add-on id" placeholder="e.g. addon-payroll" value={addon.id} onChange={e => setAddon({ ...addon, id: e.target.value.toLowerCase() })} /></label>}
              <label className="text-sm">Name<br /><input className="input input-sm" aria-label="Add-on name" value={addon.name} onChange={e => setAddon({ ...addon, name: e.target.value })} /></label>
              <label className="text-sm">Monthly $<br /><input className="input input-sm" style={{ width: 90 }} value={addon.price_monthly} onChange={e => setAddon({ ...addon, price_monthly: e.target.value })} /></label>
              <label className="text-sm">Extra users<br /><input className="input input-sm" style={{ width: 80 }} value={addon.extra_seats} onChange={e => setAddon({ ...addon, extra_seats: Number(e.target.value) || 0 })} /></label>
              <label className="text-sm"><input type="checkbox" checked={addon.is_active} onChange={e => setAddon({ ...addon, is_active: e.target.checked })} /> Active</label>
            </div>
            <ModulePicker obj={addon} setObj={setAddon} />
            <button className="btn btn-primary btn-sm" onClick={() => act(async () => {
              await api.adminSaveAddon(addon.id, { name: addon.name, description: addon.description, price_monthly: String(addon.price_monthly), modules: addon.modules, extra_seats: addon.extra_seats, is_active: addon.is_active, sort_order: addon.sort_order }); setAddon(null)
            }, 'Add-on saved')}>Save add-on</button>{' '}
            <button className="btn btn-ghost btn-sm" onClick={() => setAddon(null)}>Cancel</button>
          </div>)}
      </div>

      <div style={box}>
        <div className="flex items-center" style={{ gap: 8 }}><b>Organisations</b><div className="flex-1" />
          <ForceDeleteButton enabled={forceOn} count={sel.count} busy={bulkBusy} noun="organisation" onClick={() => deleteOrgs(selectedOrgs, true)} /></div>
        <table className="data-table" style={{ fontSize: '.82rem', marginTop: 8 }}>
          <thead><tr>{forceOn && <th style={{ width: 30 }}><SelectAllCheckbox sel={sel} label="Select all organisations" /></th>}<th>Organisation</th><th>Users</th><th>Plan</th><th>Add-ons</th><th>Status</th><th>Paid until</th><th /></tr></thead>
          <tbody>{d.organisations.map(o => <OrgRow key={o.org_id} o={o} d={d} sel={sel} forceOn={forceOn} busy={bulkBusy} onDelete={() => deleteOrgs([o], false)} onSave={(body) => act(() => api.adminAssignOrgPlan(o.org_id, body), `Saved ${o.name}`)} />)}</tbody>
        </table>
        <div className="text-xs text-muted" style={{ marginTop: 6 }}>An organisation showing "—" has no plan assigned and keeps every module. A change here applies to all of its users immediately. Deleting an organisation also deletes all of its users; an organisation that already has posted journals can only be removed with <b>Force delete</b> (switch it on under Platform features).</div>
      </div>
    </div>
  )
}

function OrgRow({ o, d, onSave, sel, onDelete, busy, forceOn }) {
  const [f, setF] = useState({ plan_id: o.plan_id || d.settings.default_plan, addons: o.addons, status: o.status || 'active', period_end: o.period_end || '', trial_ends: o.trial_ends || '' })
  const dirty = !o.plan_id || f.plan_id !== o.plan_id || f.status !== o.status || f.period_end !== (o.period_end || '') || f.addons.join() !== o.addons.join()
  return (
    <tr data-testid={`org-sub-${o.org_id}`}>
      {forceOn && <td><RowCheckbox sel={sel} id={o.org_id} label={`Select ${o.name}`} /></td>}
      <td><b>{o.name}</b> <span className="text-muted">#{o.org_id}</span></td><td>{o.members}</td>
      <td><select className="input input-sm" aria-label={`Plan for ${o.name}`} value={f.plan_id} onChange={e => setF({ ...f, plan_id: e.target.value })}>
        {!o.plan_id && <option value="">—</option>}{d.plans.map(p => <option key={p.id} value={p.id}>{p.name}</option>)}</select></td>
      <td>{d.addons.map(a => <label key={a.id} className="text-xs" style={{ marginRight: 8, whiteSpace: 'nowrap' }}><input type="checkbox" checked={f.addons.includes(a.id)} onChange={() => setF({ ...f, addons: f.addons.includes(a.id) ? f.addons.filter(x => x !== a.id) : [...f.addons, a.id] })} /> {a.name}</label>)}</td>
      <td><select className="input input-sm" value={f.status} onChange={e => setF({ ...f, status: e.target.value })}>{STATUSES.map(s => <option key={s} value={s}>{s}</option>)}</select>
        {o.effective_status !== o.status && o.status && <div className="text-xs" style={{ color: 'var(--danger)' }}>now {o.effective_status}</div>}</td>
      <td><input className="input input-sm" type="date" value={f.period_end} onChange={e => setF({ ...f, period_end: e.target.value })} /></td>
      <td><button className="btn btn-primary btn-xs" disabled={!dirty} onClick={() => onSave({ plan_id: f.plan_id, addons: f.addons, status: f.status, billing_period: o.billing_period || 'monthly', period_end: f.period_end || null, trial_ends: f.trial_ends || null, notes: o.notes })}>Save</button>{' '}
        <button className="btn btn-ghost btn-xs" disabled={busy} title="Delete this organisation and all of its users" onClick={onDelete}>Delete</button></td>
    </tr>
  )
}
