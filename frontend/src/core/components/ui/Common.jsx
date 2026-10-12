import React from 'react'

export const fmtAUD = v => {
  const n = Number(v ?? 0)
  return n.toLocaleString('en-AU', { style: 'currency', currency: 'AUD' })
}
export const fmtMoney = (v, cur) => Number(v ?? 0).toLocaleString('en-AU', { style: 'currency', currency: cur || 'AUD' })
export const fmtDate = d => d ? new Date(d + (String(d).length === 10 ? 'T00:00:00' : '')).toLocaleDateString('en-AU') : '—'
export const todayISO = () => new Date().toISOString().slice(0, 10)

// Status -> badge class. Kept small and shared so every module's pills look identical.
const STATUS_BADGE = {
  draft: 'badge-neutral', sent: 'badge-info', accepted: 'badge-success', declined: 'badge-danger',
  approved: 'badge-info', paid: 'badge-success', voided: 'badge-danger', cancelled: 'badge-neutral',
  invoiced: 'badge-neutral', billed: 'badge-neutral', archived: 'badge-neutral',
  submitted: 'badge-info', rejected: 'badge-danger',
  unreconciled: 'badge-warning', reconciled: 'badge-success', excluded: 'badge-neutral',
}
export function StatusBadge({ status }) {
  return <span className={`badge ${STATUS_BADGE[status] || 'badge-neutral'}`}>{status}</span>
}

export function Modal({ title, onClose, children, width = 640 }) {
  return (
    <div className="modal-overlay" onClick={onClose}>
      <div className="modal" onClick={e => e.stopPropagation()} style={{ maxWidth: width, width: '95%', maxHeight: '90vh', overflow: 'auto' }}>
        <div className="modal-header">
          <h3 style={{ margin: 0 }}>{title}</h3>
          <button className="btn btn-ghost btn-xs" onClick={onClose}>✕</button>
        </div>
        <div style={{ padding: 18 }}>{children}</div>
      </div>
    </div>
  )
}

export function EmptyState({ icon = '📄', title, hint }) {
  return (
    <div className="empty-state" style={{ padding: 40 }}>
      <div className="empty-icon">{icon}</div>
      <p style={{ fontWeight: 600, margin: '8px 0 4px' }}>{title}</p>
      {hint && <p className="text-sm text-muted" style={{ margin: 0 }}>{hint}</p>}
    </div>
  )
}

export function Field({ label, children, hint }) {
  return (
    <div className="input-group" style={{ marginBottom: 12 }}>
      <label>{label}</label>
      {children}
      {hint && <div className="text-xs text-muted" style={{ marginTop: 2 }}>{hint}</div>}
    </div>
  )
}

// Simple client-side pager for lists the API already returns in full (most Phase 1 list endpoints
// cap at 100-500 rows and paginate server-side via limit/offset; this is for the common case where
// a screen wants to page through an already-fetched array without another round trip).
export function Pager({ page, pageCount, onPage }) {
  if (pageCount <= 1) return null
  return (
    <div className="pagination">
      <button className="page-btn" disabled={page <= 1} onClick={() => onPage(page - 1)}>‹</button>
      <span className="text-sm text-muted">Page {page} of {pageCount}</span>
      <button className="page-btn" disabled={page >= pageCount} onClick={() => onPage(page + 1)}>›</button>
    </div>
  )
}

export function ConfirmDelete({ what = 'this item' }) {
  return `Delete ${what}? This cannot be undone.`
}
