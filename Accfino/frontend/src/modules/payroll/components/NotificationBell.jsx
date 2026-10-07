import React, { useEffect, useRef, useState } from 'react'
import { Bell } from 'lucide-react'
import { fmtDate } from '../lib/format.js'

// The approvals bell: timesheets / leave waiting for an approver, and decisions for the employee. Clicking an item marks it read and opens the screen it is about.
export default function NotificationBell({ data, onOpen, onReadAll }) {
  const [open, setOpen] = useState(false)
  const box = useRef(null)
  useEffect(() => {
    if (!open) return undefined
    const away = e => { if (box.current && !box.current.contains(e.target)) setOpen(false) }
    document.addEventListener('mousedown', away)
    return () => document.removeEventListener('mousedown', away)
  }, [open])
  const unread = data?.unread || 0
  const items = data?.items || []
  return (
    <div ref={box} style={{ position: 'relative' }}>
      <button className="btn btn-outline btn-sm" aria-label={unread ? `Notifications, ${unread} unread` : 'Notifications'} aria-expanded={open} onClick={() => setOpen(o => !o)} style={{ position: 'relative' }}>
        <Bell size={16} />
        {unread > 0 && <span className="badge badge-danger" data-testid="bell-unread" style={{ position: 'absolute', top: -7, right: -7, minWidth: 18, padding: '0 5px', fontSize: '.68rem' }}>{unread > 99 ? '99+' : unread}</span>}
      </button>
      {open && (
        <div role="dialog" aria-label="Notifications" style={{ position: 'absolute', right: 0, top: 'calc(100% + 6px)', width: 340, maxWidth: '86vw', maxHeight: 420, overflowY: 'auto', zIndex: 50, background: 'var(--surface)', border: '1px solid var(--border)', borderRadius: 'var(--r-lg)', boxShadow: 'var(--sh-md)' }}>
          <div className="flex items-center justify-between" style={{ padding: '10px 12px', borderBottom: '1px solid var(--border)' }}>
            <b className="text-sm">Notifications</b>
            {unread > 0 && <button className="btn btn-ghost btn-xs" onClick={onReadAll}>Mark all read</button>}
          </div>
          {items.length === 0 ? <div className="text-sm text-muted" style={{ padding: 16 }}>Nothing yet. You'll be told here when a timesheet or leave request needs your approval, or has been decided.</div> : items.map(n => (
            <button key={n.id} onClick={() => { setOpen(false); onOpen(n) }} className="text-left" style={{ display: 'block', width: '100%', padding: '10px 12px', border: 0, borderBottom: '1px solid var(--border)', background: n.is_read ? 'transparent' : 'var(--info-bg)', cursor: 'pointer', fontFamily: 'inherit' }}>
              <div className="text-sm" style={{ fontWeight: n.is_read ? 500 : 700 }}>{n.title}</div>
              {n.body && <div className="text-xs text-muted">{n.body}</div>}
              <div className="text-xs text-muted">{n.created_at ? fmtDate(n.created_at.slice(0, 10)) : ''}</div>
            </button>))}
        </div>)}
    </div>
  )
}
