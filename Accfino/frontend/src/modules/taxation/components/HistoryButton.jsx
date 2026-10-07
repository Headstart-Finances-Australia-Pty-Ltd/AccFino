import React, { useState } from 'react'
import * as api from '../lib/taxApi.js'
import { Async, Modal, useLoad } from './kit.jsx'
import { fmtDate } from '../lib/format.js'

function History({ type, id, onClose }) {
  const q = useLoad(() => api.auditFor(type, id), [type, id])
  return (
    <Modal title="History" onClose={onClose} width={640}>
      <Async q={q}>{rows => rows.length === 0 ? <div className="text-sm text-muted">No recorded history for this record.</div> : (
        <div role="list" aria-label="Record history">{rows.map(r => <div role="listitem" key={r.seq} className="text-sm" style={{ padding: '4px 0', borderBottom: '1px solid var(--border)' }}>
          <strong>{fmtDate(r.at)}</strong> · {r.user || 'system'} · <span className="mono text-xs">{r.action}</span><div className="text-muted">{r.summary}</div></div>)}</div>)}</Async>
    </Modal>)
}

// Per-record audit history (who changed what, when). Only for roles that may view the audit trail.
export default function HistoryButton({ type, id, caps = [] }) {
  const [open, setOpen] = useState(false)
  if (!caps.includes('audit_view')) return null
  return <><button className="btn btn-ghost btn-xs" onClick={() => setOpen(true)} aria-label={`History of ${type} ${id}`}>History</button>{open && <History type={type} id={id} onClose={() => setOpen(false)} />}</>
}
