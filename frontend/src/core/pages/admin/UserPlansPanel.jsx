import React, { useCallback, useEffect, useMemo, useState } from 'react'
import { RefreshCw, Search, Lock } from 'lucide-react'
import toast from 'react-hot-toast'
import { adminUserPlans, adminSetOrgPlan } from '../../lib/adminApi.js'
import { errMsg } from '../../lib/platformHttp.js'
import { announceDataChanged, DATA_CHANGED_EVENT } from '../../components/ui/ForceDelete.jsx'
import { fmtDate } from '../../components/ui/Common.jsx'

const th = { padding: '9px 12px', textAlign: 'left', fontWeight: 600, color: 'var(--text-2)', whiteSpace: 'nowrap', fontSize: '.78rem' }
const td = { padding: '8px 12px', fontSize: '.82rem', verticalAlign: 'top' }
const STATUS = { active: ['#C6F6D5', '#276749'], trial: ['#FEFCBF', '#975A16'], past_due: ['#FEEBC8', '#9C4221'], cancelled: ['#FED7D7', '#9B2C2C'], expired: ['#FED7D7', '#9B2C2C'] }

// Admin > Users & Licence > Plans by user. The licence of a person IS their organisation's plan: this table shows it, and the plan can be changed here.
// (The old per-user licence record - licence type, payment mode, start/end, notes, module list - no longer decides anything.)
export default function UserPlansPanel() {
  const [data, setData] = useState(null)
  const [loading, setLoading] = useState(true)
  const [q, setQ] = useState('')
  const [busy, setBusy] = useState(null)

  const load = useCallback(async (silent = false) => {
    if (!silent) setLoading(true)
    try { const { data: d } = await adminUserPlans(); setData(d) } catch (e) { toast.error(errMsg(e, 'Could not load the plans')) } finally { setLoading(false) }
  }, [])
  useEffect(() => { load() }, [load])
  useEffect(() => {
    const again = () => load(true)
    window.addEventListener(DATA_CHANGED_EVENT, again); window.addEventListener('focus', again)
    return () => { window.removeEventListener(DATA_CHANGED_EVENT, again); window.removeEventListener('focus', again) }
  }, [load])

  const rows = data?.rows || []
  const needle = q.trim().toLowerCase()
  const shown = useMemo(() => !needle ? rows : rows.filter(r => [r.username, r.full_name, r.email, r.phone, r.org?.org_name, r.org?.plan_name, r.role_label].some(v => (v || '').toLowerCase().includes(needle))), [rows, needle])

  const changePlan = async (row, planId) => {
    const plan = data.plans.find(p => p.id === planId)
    if (!plan || planId === row.org.plan_id) return
    if (!window.confirm(`Move "${row.org.org_name}" to the ${plan.name} plan?\n\nEveryone in this organisation gets what ${plan.name} includes straight away.`)) return
    setBusy(row.org.org_id)
    try { await adminSetOrgPlan(row.org.org_id, planId); toast.success(`${row.org.org_name} is now on ${plan.name}`); await load(true); announceDataChanged() }
    catch (e) { toast.error(errMsg(e, 'Could not change the plan')) } finally { setBusy(null) }
  }

  return (
    <div data-testid="user-plans">
      <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginBottom: 14, flexWrap: 'wrap' }}>
        <div>
          <h2 style={{ margin: 0 }}>Plans by user</h2>
          <p style={{ color: 'var(--text-3)', fontSize: '.85rem', margin: '4px 0 0' }}>
            A person's licence is the plan of their organisation: it decides which business domains and modules they see. The AccFino administrator is always on {data?.top_plan || 'the top plan'}.
          </p>
        </div>
        <div style={{ flex: 1 }} />
        <div style={{ position: 'relative' }}>
          <Search size={13} style={{ position: 'absolute', left: 9, top: 9, color: 'var(--text-3)' }} />
          <input className="input input-sm" placeholder="Search name, email, organisation, plan…" value={q} onChange={e => setQ(e.target.value)} style={{ paddingLeft: 28, width: 280 }} aria-label="Search users and plans" />
        </div>
        <button className="btn btn-outline btn-sm" onClick={() => load()}><RefreshCw size={13} /> Refresh</button>
      </div>

      {loading ? <div style={{ padding: 40, textAlign: 'center', color: 'var(--text-3)' }}><span className="spinner" /> Loading…</div> : (
        <div style={{ overflowX: 'auto' }}>
          <table style={{ width: '100%', borderCollapse: 'collapse' }}>
            <thead><tr style={{ background: 'var(--surface-2)', borderBottom: '2px solid var(--border)' }}>
              {['User', 'Email', 'Phone', 'Organisation', 'Role', 'Plan', 'Billing', 'Status', 'Users', 'Add-ons', 'Business domains'].map(h => <th key={h} style={th}>{h}</th>)}
            </tr></thead>
            <tbody>
              {shown.length === 0 && <tr><td colSpan={11} style={{ ...td, textAlign: 'center', color: 'var(--text-3)', padding: 24 }}>{needle ? 'Nothing matches your search.' : 'No users yet.'}</td></tr>}
              {shown.map(r => {
                const o = r.org
                const st = o ? (STATUS[o.status] || ['var(--surface-3)', 'var(--text-2)']) : null
                return (
                  <tr key={`${r.user_id}-${o?.org_id ?? 'none'}`} style={{ borderBottom: '1px solid var(--border)' }} data-testid={`plan-row-${r.user_id}`}>
                    <td style={td}><strong>{r.full_name || r.username}</strong>{r.full_name ? <span style={{ color: 'var(--text-3)' }}> · {r.username}</span> : null}{r.platform_admin && <Lock size={12} style={{ marginLeft: 6, verticalAlign: '-1px' }} aria-label="AccFino administrator" />}</td>
                    <td style={{ ...td, color: 'var(--text-2)' }}>{r.email || '—'}</td>
                    <td style={{ ...td, color: 'var(--text-2)' }}>{r.phone_display || r.phone || '—'}</td>
                    <td style={td}>{o ? o.org_name : <span style={{ color: 'var(--text-3)' }}>No organisation</span>}</td>
                    <td style={td}>{r.role_label}{r.suspended ? ' (suspended)' : ''}</td>
                    <td style={td}>
                      {!o ? '—' : r.platform_admin
                        ? <b data-testid={`plan-name-${r.user_id}`}>{o.plan_name}</b>
                        : <select className="input input-sm" value={o.plan_id || ''} disabled={busy === o.org_id} onChange={e => changePlan(r, e.target.value)} aria-label={`Plan of ${o.org_name}`} data-testid={`plan-select-${r.user_id}`}>
                            {!o.plan_id && <option value="">No plan (all modules)</option>}
                            {data.plans.map(p => <option key={p.id} value={p.id}>{p.name}</option>)}
                          </select>}
                    </td>
                    <td style={td}>{o && o.plan_id ? <>{o.billing_period || '—'}{o.period_end ? <div style={{ color: 'var(--text-3)', fontSize: '.74rem' }}>paid to {fmtDate(o.period_end)}</div> : null}<div style={{ color: 'var(--text-3)', fontSize: '.74rem' }}>{o.card ? `${o.card}${o.auto_renew ? ' · auto-renew' : ''}` : 'no card'}</div></> : '—'}</td>
                    <td style={td}>{o ? <span style={{ background: st[0], color: st[1], fontSize: '.7rem', fontWeight: 700, padding: '2px 8px', borderRadius: 100 }}>{o.status}</span> : '—'}</td>
                    <td style={td}>{o ? `${o.seats_used} / ${o.seats_allowed ?? '∞'}${o.seats_pending ? ` (+${o.seats_pending} pending)` : ''}` : '—'}</td>
                    <td style={td}>{o && o.addons.length ? o.addons.join(', ') : '—'}</td>
                    <td style={td}>{o ? <div style={{ display: 'flex', gap: 4, flexWrap: 'wrap' }}>{o.domains.map(d => <span key={d} className="badge badge-neutral" style={{ fontSize: '.68rem' }}>{d}</span>)}</div> : '—'}</td>
                  </tr>)
              })}
            </tbody>
          </table>
        </div>
      )}
    </div>
  )
}
