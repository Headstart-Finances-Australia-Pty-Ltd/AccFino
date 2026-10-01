import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { ChevronDown, ChevronRight, Lock, RefreshCw, Search, Building2 } from 'lucide-react'
import toast from 'react-hot-toast'
import { adminOrgDirectory, adminBulkDeleteOrgs, adminBulkDeleteUsers, adminPruneEmptyOrgs, adminPruneOrphanUsers, errMsg } from '../../lib/booksApi.js'
import { useForceDeleteSwitch, useRowSelection, SelectAllCheckbox, RowCheckbox, ForceDeleteButton, reportBulkResult, announceDataChanged, DATA_CHANGED_EVENT } from '../../components/ui/ForceDelete.jsx'

const th = { padding: '9px 12px', textAlign: 'left', fontWeight: 600, color: 'var(--text-2)', whiteSpace: 'nowrap', fontSize: '.78rem' }
const td = { padding: '8px 12px', fontSize: '.82rem', verticalAlign: 'middle' }

const STATUS_STYLE = {
  active:    { bg: '#C6F6D5', color: '#276749' },
  trial:     { bg: '#FEFCBF', color: '#975A16' },
  past_due:  { bg: '#FEEBC8', color: '#9C4221' },
  cancelled: { bg: '#FED7D7', color: '#9B2C2C' },
  expired:   { bg: '#FED7D7', color: '#9B2C2C' },
}

function Pill({ children, style }) {
  return <span style={{ fontSize: '.7rem', fontWeight: 700, padding: '2px 8px', borderRadius: 100, background: 'var(--surface-3)', color: 'var(--text-2)', whiteSpace: 'nowrap', ...style }}>{children}</span>
}

function seatsText(l) {
  const used = l.active_users
  return l.seats == null ? `${used} / unlimited` : `${used} / ${l.seats}`
}

export default function OrgDirectoryPanel() {
  const [data, setData] = useState(null)
  const [loading, setLoading] = useState(true)
  const [open, setOpen] = useState(() => new Set())
  const [q, setQ] = useState('')
  const [busy, setBusy] = useState(false)
  const forceOn = useForceDeleteSwitch()
  const own = useRef(false)                 // true while this panel is the one announcing a change (it has already refreshed itself)

  // silent = keep the table on screen while refreshing (no spinner flash)
  const load = useCallback(async (silent = false) => {
    if (!silent) setLoading(true)
    try { const { data: d } = await adminOrgDirectory(); setData(d) }
    catch (e) { toast.error(errMsg(e, 'Could not load organisations')) }
    finally { setLoading(false) }
  }, [])
  useEffect(() => { load() }, [load])
  // another admin table deleted something, or this tab was brought back to the front: refresh at once
  useEffect(() => {
    const again = () => { if (own.current) { own.current = false; return } load(true) }
    window.addEventListener(DATA_CHANGED_EVENT, again)
    window.addEventListener('focus', again)
    return () => { window.removeEventListener(DATA_CHANGED_EVENT, again); window.removeEventListener('focus', again) }
  }, [load])

  const orgs = data?.organisations || []
  const unassigned = data?.unassigned_users || []
  const admins = data?.platform_admins || []

  // search across organisation name, admin contact and every user's name / email / phone
  const needle = q.trim().toLowerCase()
  const match = (...vals) => vals.some(v => (v || '').toString().toLowerCase().includes(needle))
  const shownOrgs = useMemo(() => !needle ? orgs : orgs.filter(o =>
    match(o.name, o.admin.email, o.admin.phone, o.admin.name, o.licence.plan_name) || o.users.some(u => match(u.username, u.full_name, u.email, u.phone))), [orgs, needle]) // eslint-disable-line
  const shownUnassigned = useMemo(() => !needle ? unassigned : unassigned.filter(u => match(u.username, u.full_name, u.email, u.phone)), [unassigned, needle]) // eslint-disable-line

  // two selections: whole organisations (and their users) and individual users. Protected accounts never get a checkbox.
  const orgSel = useRowSelection(shownOrgs.map(o => o.org_id))
  const userIds = useMemo(() => [...shownOrgs.flatMap(o => o.users), ...shownUnassigned].filter(u => !u.protected).map(u => u.user_id), [shownOrgs, shownUnassigned])
  const userSel = useRowSelection(userIds)
  const total = orgSel.count + userSel.count
  useEffect(() => { if (!forceOn) { orgSel.clear(); userSel.clear() } }, [forceOn]) // eslint-disable-line

  // organisations with no users left (leftovers of deleted logins)
  const emptyOrgs = useMemo(() => orgs.filter(o => o.user_count === 0), [orgs])
  const pruneEmpty = async () => {
    if (!emptyOrgs.length) return
    if (!confirm(`Remove ${emptyOrgs.length} organisation${emptyOrgs.length === 1 ? '' : 's'} that ${emptyOrgs.length === 1 ? 'has' : 'have'} no users left?\n\n${emptyOrgs.map(o => '• ' + o.name).join('\n')}\n\nThis cannot be undone.`)) return
    setBusy(true)
    try {
      const { data: r } = await adminPruneEmptyOrgs()
      const gone = new Set((r.removed || []).map(x => x.id))
      if (gone.size) toast.success(`Removed ${gone.size} empty organisation${gone.size === 1 ? '' : 's'}`)
      if ((r.skipped || []).length) toast.error(`${r.skipped.length} kept: ${r.skipped[0].reason}`, { duration: 9000 })
      setData(d => d && ({ ...d, organisations: d.organisations.filter(o => !gone.has(o.org_id)), totals: { ...d.totals, organisations: d.totals.organisations - gone.size } }))
      await load(true)
      own.current = true; announceDataChanged(); own.current = false
    } catch (e) { toast.error(errMsg(e, 'Could not remove empty organisations'), { duration: 8000 }); load(true) }
    finally { setBusy(false) }
  }

  // logins that belong to no organisation (leftovers of deleted organisations)
  const orphanUsers = useMemo(() => unassigned.filter(u => !u.protected), [unassigned])
  const pruneOrphans = async () => {
    if (!orphanUsers.length) return
    if (!confirm(`Delete ${orphanUsers.length} login${orphanUsers.length === 1 ? '' : 's'} that belong to no organisation?\n\n${orphanUsers.map(u => '• ' + (u.email || u.username)).join('\n')}\n\nThis cannot be undone.`)) return
    setBusy(true)
    try {
      const { data: r } = await adminPruneOrphanUsers()
      const gone = new Set((r.removed || []).map(x => x.id))
      if (gone.size) toast.success(`Deleted ${gone.size} login${gone.size === 1 ? '' : 's'}`)
      if ((r.skipped || []).length) toast.error(`${r.skipped.length} kept: ${r.skipped[0].reason}`, { duration: 9000 })
      setData(d => d && ({ ...d, unassigned_users: d.unassigned_users.filter(u => !gone.has(u.user_id)), totals: { ...d.totals, users: d.totals.users - gone.size } }))
      await load(true)
      own.current = true; announceDataChanged(); own.current = false
    } catch (e) { toast.error(errMsg(e, 'Could not delete the logins'), { duration: 8000 }); load(true) }
    finally { setBusy(false) }
  }

  const toggleOpen = id => setOpen(s => { const n = new Set(s); n.has(id) ? n.delete(id) : n.add(id); return n })
  const allOpen = shownOrgs.length > 0 && shownOrgs.every(o => open.has(o.org_id))
  const toggleAll = () => setOpen(allOpen ? new Set() : new Set(shownOrgs.map(o => o.org_id)))

  const forceDelete = async () => {
    const orgIds = orgSel.ids
    const doomedOrgs = orgs.filter(o => orgIds.includes(o.org_id))
    // users that go with a selected organisation are not sent twice
    const inDoomedOrg = new Set(doomedOrgs.flatMap(o => o.users.map(u => u.user_id)))
    const userIdsToSend = userSel.ids.filter(id => !inDoomedOrg.has(id))
    const allUsers = new Map([...orgs.flatMap(o => o.users), ...unassigned].map(u => [u.user_id, u]))
    const lines = [
      ...doomedOrgs.map(o => `• Organisation "${o.name}" and its ${o.user_count} user${o.user_count === 1 ? '' : 's'}`),
      ...userIdsToSend.map(id => `• User ${allUsers.get(id)?.email || '#' + id}`),
    ]
    if (!lines.length) return
    if (!confirm(`FORCE DELETE the following and ALL of their data?\n\n${lines.join('\n')}\n\nThis cannot be undone.`)) return
    setBusy(true)
    try {
      const goneOrgs = new Set(), goneUsers = new Set()
      if (orgIds.length) {
        const { data: r } = await adminBulkDeleteOrgs(orgIds, true)
        reportBulkResult(r, 'organisation')
        ;(r.results || []).filter(x => x.ok).forEach(x => { goneOrgs.add(x.id); (x.users_deleted || []).forEach(u => goneUsers.add(u.id)) })
      }
      if (userIdsToSend.length) {
        const { data: r } = await adminBulkDeleteUsers(userIdsToSend, true)
        reportBulkResult(r, 'user')
        ;(r.results || []).filter(x => x.ok).forEach(x => { goneUsers.add(x.id); (x.orgs_removed || []).forEach(o => goneOrgs.add(o.id)) })
      }
      orgSel.clear(); userSel.clear()
      // 1) the rows disappear immediately, from what is already on screen ...
      setData(d => d && ({
        ...d,
        organisations: d.organisations.filter(o => !goneOrgs.has(o.org_id)).map(o => {
          const users = o.users.filter(u => !goneUsers.has(u.user_id))
          return { ...o, users, user_count: users.length, licence: { ...o.licence, active_users: Math.max(0, o.licence.active_users - (o.users.length - users.length)) } }
        }),
        unassigned_users: d.unassigned_users.filter(u => !goneUsers.has(u.user_id)),
        totals: { organisations: d.totals.organisations - goneOrgs.size, users: d.totals.users - goneUsers.size },
      }))
      // 2) ... then the server's own numbers replace them, and every other open admin table refreshes too
      await load(true)
      own.current = true; announceDataChanged(); own.current = false
    } catch (e) { toast.error(errMsg(e, 'Force delete failed'), { duration: 8000 }); load(true) }
    finally { setBusy(false) }
  }

  const userRow = (u, withRole = true) => (
    <tr key={u.user_id} style={{ borderTop: '1px solid var(--border)' }}>
      {forceOn && <td style={{ ...td, width: 34 }}>
        {u.protected
          ? <Lock size={14} color="var(--text-3)" aria-label={`${u.username} is protected`} title="The AccFino administrator account is protected and can never be deleted" />
          : <RowCheckbox sel={userSel} id={u.user_id} label={`Select ${u.email}`} />}
      </td>}
      <td style={td}><strong>{u.full_name || u.username}</strong>{u.full_name ? <span style={{ color: 'var(--text-3)' }}> · {u.username}</span> : null}</td>
      {withRole && <td style={td}><Pill style={u.role === 'owner' ? { background: 'var(--brand-light)', color: 'var(--brand)' } : null}>{u.role_label || u.role}</Pill>{u.suspended ? <Pill style={{ background: '#FED7D7', color: '#9B2C2C', marginLeft: 6 }}>suspended</Pill> : null}</td>}
      <td style={{ ...td, color: 'var(--text-2)' }}>{u.email || '—'}</td>
      <td style={{ ...td, color: 'var(--text-2)' }}>{u.phone_display || u.phone || '—'}</td>
    </tr>
  )

  return (
    <div data-testid="org-directory">
      <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginBottom: 14, flexWrap: 'wrap' }}>
        <div>
          <h2 style={{ margin: 0 }}>Organisations &amp; Users</h2>
          <p style={{ color: 'var(--text-3)', fontSize: '.85rem', margin: '4px 0 0' }}>
            {data ? `${data.totals.organisations} organisation${data.totals.organisations === 1 ? '' : 's'} · ${data.totals.users} user${data.totals.users === 1 ? '' : 's'}` : 'Every organisation with its contact, licence and users'}
          </p>
        </div>
        <div style={{ flex: 1 }} />
        <div style={{ position: 'relative' }}>
          <Search size={13} style={{ position: 'absolute', left: 9, top: 9, color: 'var(--text-3)' }} />
          <input className="input input-sm" placeholder="Search organisation, name, email, phone…" value={q} onChange={e => setQ(e.target.value)} style={{ paddingLeft: 28, width: 280 }} aria-label="Search organisations and users" />
        </div>
        {emptyOrgs.length > 0 && <button className="btn btn-outline btn-sm" onClick={pruneEmpty} disabled={busy} data-testid="prune-empty-btn">Remove {emptyOrgs.length} empty organisation{emptyOrgs.length === 1 ? '' : 's'}</button>}
        <button className="btn btn-outline btn-sm" onClick={toggleAll}>{allOpen ? 'Collapse all' : 'Expand all'}</button>
        <ForceDeleteButton enabled={forceOn} count={total} busy={busy} onClick={forceDelete} noun="selected item" />
        <button className="btn btn-outline btn-sm" onClick={load}><RefreshCw size={13} /> Refresh</button>
      </div>

      {admins.length > 0 && (
        <div className="card card-flat" style={{ padding: '10px 14px', marginBottom: 14, display: 'flex', alignItems: 'center', gap: 12, flexWrap: 'wrap' }} data-testid="platform-admin-card">
          <Lock size={16} color="var(--brand)" />
          <strong>AccFino platform administrator</strong>
          {admins.map(a => <span key={a.user_id} style={{ color: 'var(--text-2)', fontSize: '.82rem' }}>{a.email}{a.phone_display ? ` · ${a.phone_display}` : ''}</span>)}
          <Pill style={{ marginLeft: 'auto' }}>Protected — can never be deleted</Pill>
        </div>
      )}

      {loading ? (
        <div style={{ padding: 40, textAlign: 'center', color: 'var(--text-3)' }}><span className="spinner" /> Loading…</div>
      ) : (
        <div style={{ overflowX: 'auto' }}>
          <table style={{ width: '100%', borderCollapse: 'collapse' }}>
            <thead>
              <tr style={{ background: 'var(--surface-2)', borderBottom: '2px solid var(--border)' }}>
                {forceOn && <th style={{ ...th, width: 34 }}><SelectAllCheckbox sel={orgSel} label="Select all organisations" /></th>}
                <th style={{ ...th, width: 28 }} />
                <th style={th}>Organisation</th><th style={th}>Admin email</th><th style={th}>Admin phone</th><th style={th}>Licence</th><th style={th}>Status</th><th style={th}>Users</th>
              </tr>
            </thead>
            <tbody>
              {shownOrgs.length === 0 && <tr><td colSpan={forceOn ? 8 : 7} style={{ ...td, textAlign: 'center', color: 'var(--text-3)', padding: 24 }}>{needle ? 'No organisation or user matches your search.' : 'No organisations yet.'}</td></tr>}
              {shownOrgs.map(o => {
                const isOpen = open.has(o.org_id) || (needle && o.users.some(u => match(u.username, u.full_name, u.email, u.phone)))
                const st = STATUS_STYLE[o.licence.status] || { bg: 'var(--surface-3)', color: 'var(--text-2)' }
                return (
                  <React.Fragment key={o.org_id}>
                    <tr style={{ borderBottom: '1px solid var(--border)', background: isOpen ? 'var(--surface-2)' : 'transparent', cursor: 'pointer' }} onClick={() => toggleOpen(o.org_id)} data-testid={`org-row-${o.org_id}`}>
                      {forceOn && <td style={td} onClick={e => e.stopPropagation()}><RowCheckbox sel={orgSel} id={o.org_id} label={`Select organisation ${o.name}`} /></td>}
                      <td style={td}>{isOpen ? <ChevronDown size={15} /> : <ChevronRight size={15} />}</td>
                      <td style={td}><Building2 size={13} style={{ marginRight: 6, verticalAlign: '-2px', color: 'var(--text-3)' }} /><strong>{o.name}</strong>{o.is_active ? null : <Pill style={{ marginLeft: 6 }}>inactive</Pill>}</td>
                      <td style={{ ...td, color: 'var(--text-2)' }}>{o.admin.email || '—'}</td>
                      <td style={{ ...td, color: 'var(--text-2)' }}>{o.admin.phone_display || o.admin.phone || '—'}</td>
                      <td style={td}>{o.licence.plan_name}</td>
                      <td style={td}><span style={{ background: st.bg, color: st.color, fontSize: '.7rem', fontWeight: 700, padding: '2px 8px', borderRadius: 100 }}>{o.licence.status}</span></td>
                      <td style={td} title={o.licence.pending_codes ? `${o.licence.pending_codes} seat(s) reserved by access codes` : undefined}>{seatsText(o.licence)}{o.licence.pending_codes ? <span style={{ color: 'var(--text-3)' }}> (+{o.licence.pending_codes} pending)</span> : null}</td>
                    </tr>
                    {isOpen && (
                      <tr key={`${o.org_id}-users`}>
                        {forceOn && <td />}
                        <td colSpan={7} style={{ padding: '0 0 10px 0', background: 'var(--surface-2)' }}>
                          <table style={{ width: '100%', borderCollapse: 'collapse' }}>
                            <thead><tr>{forceOn && <th style={{ ...th, width: 34 }} />}<th style={th}>User</th><th style={th}>Role</th><th style={th}>Email</th><th style={th}>Phone</th></tr></thead>
                            <tbody>{o.users.length ? o.users.map(u => userRow(u)) : <tr><td colSpan={forceOn ? 5 : 4} style={{ ...td, color: 'var(--text-3)' }}>No users.</td></tr>}</tbody>
                          </table>
                        </td>
                      </tr>
                    )}
                  </React.Fragment>
                )
              })}
            </tbody>
          </table>

          {shownUnassigned.length > 0 && (
            <div style={{ marginTop: 22 }} data-testid="unassigned-users">
              <div style={{ display: 'flex', alignItems: 'center', gap: 10, margin: '0 0 6px' }}>
                <h4 style={{ margin: 0 }}>Users not in any organisation <span style={{ color: 'var(--text-3)', fontWeight: 400 }}>({shownUnassigned.length})</span></h4>
                {orphanUsers.length > 0 && <button className="btn btn-outline btn-sm" onClick={pruneOrphans} disabled={busy} data-testid="prune-orphans-btn">Delete {orphanUsers.length} login{orphanUsers.length === 1 ? '' : 's'} without an organisation</button>}
              </div>
              <table style={{ width: '100%', borderCollapse: 'collapse' }}>
                <thead><tr style={{ background: 'var(--surface-2)' }}>{forceOn && <th style={{ ...th, width: 34 }} />}<th style={th}>User</th><th style={th}>Email</th><th style={th}>Phone</th></tr></thead>
                <tbody>{shownUnassigned.map(u => userRow(u, false))}</tbody>
              </table>
            </div>
          )}
        </div>
      )}
    </div>
  )
}
