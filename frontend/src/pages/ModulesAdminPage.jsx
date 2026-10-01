import React, { useState, useEffect } from 'react'
import toast from 'react-hot-toast'
import { Save, RefreshCw, CheckSquare, Square } from 'lucide-react'
import { getModuleVisibility, saveModuleVisibility } from '../lib/api.js'
import SubscriptionAdminPanel from './admin/SubscriptionAdminPanel.jsx'
import { adminGetBulkImport, adminSetBulkImport, adminGetForceDelete, adminSetForceDelete, errMsg } from '../lib/booksApi.js'
import { FORCE_DELETE_EVENT } from '../components/ui/ForceDelete.jsx'
import { DOMAINS, MODULES } from '../lib/modules.js'

// Settings & Admin Console items (bank feeds, payment gateways, platform
// settings) aren't business domains, so they don't live in DOMAINS/appear in
// the loop above — they're flagged with an `area` ("settings" | "admin") and
// a `group` (the page/section they live on) instead, and rendered as their
// own section below. Each has its own module id, so e.g. Stripe in Settings
// > Payment Setup and Stripe in Admin > Payment Card Setup toggle
// independently even though they're "the same" integration to a user.
const AREA_LABEL = { settings: { emoji: '⚙️', name: 'Settings' }, admin: { emoji: '🛡️', name: 'Admin Console' } }
const AREA_ORDER = ['settings', 'admin']
function settingsAdminGroups() {
  const items = MODULES.filter(m => m.area)
  return AREA_ORDER.map(area => {
    const areaItems = items.filter(m => m.area === area)
    const groupNames = [...new Set(areaItems.map(m => m.group || 'Other'))]
    return {
      area, ...AREA_LABEL[area],
      groups: groupNames.map(group => ({ group, items: areaItems.filter(m => (m.group || 'Other') === group) })),
    }
  }).filter(a => a.groups.length)
}

// Platform feature switch: Bulk data import (CSV upload of journals, contacts, invoices, bills, receipts, claims, stock, assets, bank statements).
// Saves immediately (its own endpoint), independent of the module checkboxes' Save button. When off, the server refuses every bulk CSV
// import and the Import buttons disappear for everyone.
function BulkImportSwitch() {
  const [on, setOn] = useState(null)
  const [busy, setBusy] = useState(false)
  useEffect(() => { adminGetBulkImport().then(r => setOn(r.data?.enabled !== false)).catch(() => setOn(true)) }, [])
  const toggle = async () => {
    const next = !on
    setBusy(true)
    try {
      await adminSetBulkImport(next)
      setOn(next)
      window.dispatchEvent(new Event('accfino:bulk-import-changed'))
      toast.success(next ? 'Bulk data import is now active' : 'Bulk data import is now inactive')
    } catch (e) { toast.error(errMsg(e)) } finally { setBusy(false) }
  }
  return (
    <div style={{ background: 'var(--surface)', border: '1px solid var(--border)', borderRadius: 'var(--r-lg)', overflow: 'hidden', marginBottom: 14 }}>
      <label style={{ display: 'flex', alignItems: 'center', gap: 10, padding: '12px 16px', cursor: busy ? 'wait' : 'pointer' }}>
        <input type="checkbox" aria-label="Bulk data import" checked={on !== false} disabled={on === null || busy} onChange={toggle} style={{ width: 16, height: 16 }} />
        <span style={{ fontSize: '1.1rem' }}>📥</span>
        <span style={{ fontWeight: 700, fontSize: '.9rem' }}>Bulk data import (CSV upload)</span>
        <span className={`badge ${on === false ? 'badge-neutral' : 'badge-success'}`} style={{ marginLeft: 'auto' }}>{on === null ? '…' : on ? 'Active' : 'Inactive'}</span>
      </label>
      <div style={{ padding: '0 16px 12px 42px', fontSize: '.78rem', color: 'var(--text-3)' }}>
        Lets users upload CSV files to load journals, customers, suppliers, quotes, invoices, credit notes, receipts, purchase orders, bills, supplier payments,
        expense claims, inventory, fixed assets, chart of accounts and bank statements. Untick to switch it off for everyone: the Import buttons are hidden and the server refuses uploads.
        Takes effect immediately; no Save needed.
      </div>
    </div>
  )
}

// Platform feature switch: Force delete. Off by default. While it is ticked, the "Force delete selected" buttons on Users & Licence and on the
// Organisations table below are active; unticked, they are greyed out and the server refuses force deletes. Saves immediately.
function ForceDeleteSwitch() {
  const [on, setOn] = useState(null)
  const [busy, setBusy] = useState(false)
  useEffect(() => { adminGetForceDelete().then(r => setOn(!!r.data?.enabled)).catch(() => setOn(false)) }, [])
  const toggle = async () => {
    const next = !on
    setBusy(true)
    try {
      await adminSetForceDelete(next)
      setOn(next)
      window.dispatchEvent(new Event(FORCE_DELETE_EVENT))
      toast.success(next ? 'Force delete is now active' : 'Force delete is now inactive')
    } catch (e) { toast.error(errMsg(e)) } finally { setBusy(false) }
  }
  return (
    <div style={{ background: 'var(--surface)', border: '1px solid var(--border)', borderRadius: 'var(--r-lg)', overflow: 'hidden', marginBottom: 14 }}>
      <label style={{ display: 'flex', alignItems: 'center', gap: 10, padding: '12px 16px', cursor: busy ? 'wait' : 'pointer' }}>
        <input type="checkbox" aria-label="Force delete" checked={on === true} disabled={on === null || busy} onChange={toggle} style={{ width: 16, height: 16 }} />
        <span style={{ fontSize: '1.1rem' }}>🗑️</span>
        <span style={{ fontWeight: 700, fontSize: '.9rem' }}>Force delete</span>
        <span className={`badge ${on ? 'badge-danger' : 'badge-neutral'}`} style={{ marginLeft: 'auto' }}>{on === null ? '…' : on ? 'Active' : 'Inactive'}</span>
      </label>
      <div style={{ padding: '0 16px 12px 42px', fontSize: '.78rem', color: 'var(--text-3)' }}>
        Tick to activate the <b>Force delete selected</b> buttons (Users &amp; Licence, and Organisations below); untick to deactivate them. A force delete permanently removes the
        selected rows with everything linked to them, including posted accounting records; deleting an organisation always deletes its users too. The platform administrator
        and the account you are signed in with can never be deleted. Takes effect immediately; no Save needed.
      </div>
    </div>
  )
}

// Admin > Modules: one checkbox per business domain, one per module underneath it.
// Unchecking a domain hides it (and everything in it) everywhere - the side panel,
// every hub page's tab bar, the Home page and the public marketing page. Unchecking
// a single module hides just that module, leaving the rest of its domain untouched.
export default function ModulesAdminPage() {
  const [domainVis, setDomainVis] = useState({})   // { [domainId]: bool }
  const [moduleVis, setModuleVis] = useState({})   // { [moduleId]: bool }
  const [loading,   setLoading]   = useState(true)
  const [saving,    setSaving]    = useState(false)
  const [dirty,     setDirty]     = useState(false)

  const load = () => {
    setLoading(true)
    getModuleVisibility()
      .then(r => {
        const data = r.data || {}
        setDomainVis({ ...data.domains })
        setModuleVis({ ...data.modules })
        setDirty(false)
      })
      .catch(() => toast.error('Failed to load module visibility'))
      .finally(() => setLoading(false))
  }
  useEffect(() => { load() }, [])

  // Missing entries default to visible (matches the backend/front-end default).
  const isDomainOn = id => domainVis[id] !== false
  const isModuleOn = id => moduleVis[id] !== false

  const toggleDomain = id => { setDomainVis(v => ({ ...v, [id]: !isDomainOn(id) })); setDirty(true) }
  const toggleModule = id => { setModuleVis(v => ({ ...v, [id]: !isModuleOn(id) })); setDirty(true) }

  const setAll = (on) => {
    const d = {}, m = {}
    DOMAINS.forEach(x => { d[x.id] = on })
    MODULES.forEach(x => { m[x.id] = on })
    setDomainVis(d); setModuleVis(m); setDirty(true)
  }

  const save = async () => {
    setSaving(true)
    try {
      await saveModuleVisibility({ domains: domainVis, modules: moduleVis })
      window.dispatchEvent(new Event('accfino:module-visibility-changed'))
      toast.success('Module visibility saved')
      setDirty(false)
    } catch (e) {
      toast.error(e.response?.data?.detail || 'Failed to save')
    } finally {
      setSaving(false)
    }
  }

  if (loading) return <div style={{ padding: 40, textAlign: 'center', color: 'var(--text-3)' }}>Loading…</div>

  return (
    <div className="fade-in" style={{ padding: 24 }}>
      <div style={{ display: 'flex', alignItems: 'flex-start', justifyContent: 'space-between', marginBottom: 20, gap: 12, flexWrap: 'wrap' }}>
        <div>
          <h2 style={{ margin: 0 }}>🧩 Modules Management</h2>
          <p style={{ color: 'var(--text-3)', marginTop: 4, fontSize: '.85rem' }}>
            Untick a domain or module to hide it from the side panel, its hub page, Home and the public landing page.
          </p>
        </div>
        <div style={{ display: 'flex', gap: 8 }}>
          <button className="btn btn-outline btn-sm" onClick={() => setAll(true)}><CheckSquare size={13}/> Show all</button>
          <button className="btn btn-outline btn-sm" onClick={load}><RefreshCw size={13}/> Reload</button>
          <button className="btn btn-primary btn-sm" onClick={save} disabled={saving || !dirty}>
            <Save size={13}/> {saving ? 'Saving…' : 'Save changes'}
          </button>
        </div>
      </div>

      <div style={{ display: 'flex', flexDirection: 'column', gap: 14 }}>
        {DOMAINS.map(domain => {
          const items = MODULES.filter(m => m.domain === domain.id && !m.area)
          const domainOn = isDomainOn(domain.id)
          return (
            <div key={domain.id} style={{
              background: 'var(--surface)', border: '1px solid var(--border)', borderRadius: 'var(--r-lg)',
              overflow: 'hidden', opacity: domainOn ? 1 : 0.6,
            }}>
              <label style={{
                display: 'flex', alignItems: 'center', gap: 10, padding: '12px 16px',
                background: 'var(--surface-2)', borderBottom: '1px solid var(--border)', cursor: 'pointer',
              }}>
                <input type="checkbox" checked={domainOn} onChange={() => toggleDomain(domain.id)} style={{ width: 16, height: 16 }} />
                <span style={{ fontSize: '1.1rem' }}>{domain.emoji}</span>
                <span style={{ fontWeight: 700, fontSize: '.9rem', flex: 1 }}>{domain.name}</span>
                <span style={{ fontSize: '.7rem', color: 'var(--text-3)' }}>{items.length} module{items.length !== 1 ? 's' : ''}</span>
              </label>

              <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill,minmax(230px,1fr))', gap: 2, padding: 8 }}>
                {items.map(m => {
                  const moduleOn = isModuleOn(m.id)
                  return (
                    <label key={m.id} title={m.blurb} style={{
                      display: 'flex', alignItems: 'center', gap: 8, padding: '7px 10px',
                      borderRadius: 'var(--r-md)', cursor: 'pointer', fontSize: '.8rem',
                      opacity: moduleOn ? 1 : 0.5,
                    }}
                      onMouseEnter={e => e.currentTarget.style.background = 'var(--surface-2)'}
                      onMouseLeave={e => e.currentTarget.style.background = 'transparent'}>
                      <input type="checkbox" checked={moduleOn} onChange={() => toggleModule(m.id)} style={{ width: 14, height: 14, flexShrink: 0 }} />
                      <span style={{ flexShrink: 0 }}>{m.emoji}</span>
                      <span style={{ overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{m.name}</span>
                      {m.status === 'planned' && <span className="badge badge-neutral" style={{ marginLeft: 'auto', flexShrink: 0 }}>Soon</span>}
                    </label>
                  )
                })}
              </div>
            </div>
          )
        })}
      </div>

      <div style={{ marginTop: 28, marginBottom: 10 }}>
        <h3 style={{ margin: 0, fontSize: '.95rem' }}>Platform features</h3>
      </div>
      <BulkImportSwitch />
      <ForceDeleteSwitch />

      <div style={{ marginTop: 22, marginBottom: 10 }}>
        <h3 style={{ margin: 0, fontSize: '.95rem' }}>Subscriptions (plans, add-ons and organisations)</h3>
      </div>
      <SubscriptionAdminPanel />

      <div style={{ marginTop: 28, marginBottom: 10 }}>
        <h3 style={{ margin: 0, fontSize: '.95rem' }}>Settings & Admin Console</h3>
        <p style={{ color: 'var(--text-3)', marginTop: 4, fontSize: '.8rem' }}>
          The same integration can appear in more than one place (e.g. Stripe in both Settings and Admin) —
          each one below is its own independent switch.
        </p>
      </div>

      <div style={{ display: 'flex', flexDirection: 'column', gap: 14 }}>
        {settingsAdminGroups().map(area => (
          <div key={area.area} style={{
            background: 'var(--surface)', border: '1px solid var(--border)', borderRadius: 'var(--r-lg)', overflow: 'hidden',
          }}>
            <div style={{
              display: 'flex', alignItems: 'center', gap: 10, padding: '12px 16px',
              background: 'var(--surface-2)', borderBottom: '1px solid var(--border)',
            }}>
              <span style={{ fontSize: '1.1rem' }}>{area.emoji}</span>
              <span style={{ fontWeight: 700, fontSize: '.9rem' }}>{area.name}</span>
            </div>
            <div style={{ padding: 8 }}>
              {area.groups.map(g => (
                <div key={g.group} style={{ marginBottom: 8 }}>
                  <div style={{ fontSize: '.7rem', fontWeight: 700, color: 'var(--text-3)', textTransform: 'uppercase', letterSpacing: '.04em', padding: '6px 10px' }}>
                    {g.group}
                  </div>
                  <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill,minmax(230px,1fr))', gap: 2 }}>
                    {g.items.map(m => {
                      const moduleOn = isModuleOn(m.id)
                      return (
                        <label key={m.id} title={m.blurb} style={{
                          display: 'flex', alignItems: 'center', gap: 8, padding: '7px 10px',
                          borderRadius: 'var(--r-md)', cursor: 'pointer', fontSize: '.8rem',
                          opacity: moduleOn ? 1 : 0.5,
                        }}
                          onMouseEnter={e => e.currentTarget.style.background = 'var(--surface-2)'}
                          onMouseLeave={e => e.currentTarget.style.background = 'transparent'}>
                          <input type="checkbox" checked={moduleOn} onChange={() => toggleModule(m.id)} style={{ width: 14, height: 14, flexShrink: 0 }} />
                          <span style={{ flexShrink: 0 }}>{m.emoji}</span>
                          <span style={{ overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{m.name}</span>
                        </label>
                      )
                    })}
                  </div>
                </div>
              ))}
            </div>
          </div>
        ))}
      </div>

      {dirty && (
        <div style={{
          position: 'sticky', bottom: 16, marginTop: 16, display: 'flex', justifyContent: 'flex-end',
        }}>
          <button className="btn btn-primary" onClick={save} disabled={saving} style={{ boxShadow: 'var(--sh-md)' }}>
            <Save size={14}/> {saving ? 'Saving…' : 'Save changes'}
          </button>
        </div>
      )}
    </div>
  )
}
